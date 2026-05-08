#!/usr/bin/env python3
"""Run the full offline chess retraining pipeline."""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.games.chess_arena import default_chess_reports_dir  # noqa: E402
from services.games.chess_pipeline import (  # noqa: E402
    build_pipeline_run_id,
    candidate_paths_for_run,
    dataset_paths_for_run,
    pipeline_recommendation,
)
from services.games.chess_promotion import stage_candidate_model, promote_candidate_model  # noqa: E402
from services.games.chess_replay_buffer import replay_buffer_summary  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Full offline chess replay -> prepare -> train -> benchmark -> promote pipeline.")
    parser.add_argument("--run-id", default="")
    parser.add_argument("--preset", choices=["micro", "quick", "standard", "strong"], default="standard")
    parser.add_argument("--include-quarantine", action="store_true")
    parser.add_argument("--include-exp2", action="store_true")
    parser.add_argument("--skip-exp3", action="store_true")
    parser.add_argument("--skip-exp4", action="store_true")
    parser.add_argument("--skip-exp3-refine", action="store_true")
    parser.add_argument("--skip-promote", action="store_true")
    parser.add_argument("--stage-only", action="store_true")
    parser.add_argument("--min-usable-replays", type=int, default=-1)
    parser.add_argument("--seed", type=int, default=20260508)
    parser.add_argument("--teacher-depth", type=int, default=-1)
    parser.add_argument("--max-plies", type=int, default=-1)
    parser.add_argument("--student-exploration-rate", type=float, default=-1.0)
    parser.add_argument("--dl-search-depth", type=int, default=1)
    parser.add_argument("--dl-quiescence-depth", type=int, default=1)
    parser.add_argument("--pv-search-depth", type=int, default=1)
    parser.add_argument("--pv-quiescence-depth", type=int, default=1)
    parser.add_argument("--smoke-games-per-pair", type=int, default=1)
    parser.add_argument("--benchmark-rounds", type=int, default=1)
    parser.add_argument(
        "--promote-engines",
        default="experiment 3:dl,experiment 4:pv",
        help="Comma-separated engines to auto stage/promote if their gate passes.",
    )
    return parser.parse_args()


def _run_json(cmd: list[str]) -> dict:
    proc = subprocess.run(cmd, cwd=str(ROOT), text=True, capture_output=True, check=True)
    try:
        return json.loads(proc.stdout)
    except Exception as exc:
        raise RuntimeError(f"command did not emit JSON: {' '.join(cmd)}\nstdout={proc.stdout}\nstderr={proc.stderr}") from exc


def _report_paths(summary: dict) -> tuple[str, str]:
    reports = summary.get("reports") or {}
    return str(reports.get("json_report") or ""), str(reports.get("md_report") or "")


def _write_report(summary: dict) -> dict:
    report_dir = default_chess_reports_dir()
    report_dir.mkdir(parents=True, exist_ok=True)
    stamp = summary["finished_at"].replace(":", "").replace("-", "").replace("T", "_").replace("Z", "")
    json_path = report_dir / f"chess_train_pipeline_{stamp}.json"
    md_path = report_dir / f"chess_train_pipeline_{stamp}.md"
    json_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    lines = [
        "# chess_train_pipeline",
        "",
        f"- run_id: `{summary['run_id']}`",
        f"- finished_at: `{summary['finished_at']}`",
        f"- usable_replays_before: `{summary['replay_before'].get('usable_replays', 0)}`",
        f"- prepare_train_samples: `{summary['prepare'].get('accepted_train_samples', 0)}`",
        f"- prepare_eval_samples: `{summary['prepare'].get('accepted_eval_samples', 0)}`",
        f"- seed_games_played: `{summary['seed_train'].get('games_played', 0)}`",
        f"- benchmark_report: `{summary['benchmark'].get('reports', {}).get('json_report', '')}`",
        "",
        "## Stage / Promote",
        "",
    ]
    for row in summary.get("promotion_results") or []:
        lines.append(
            f"- {row.get('engine')}: stage=`{row.get('staged')}` promote=`{row.get('promoted')}` gate=`{row.get('gate_pass')}`"
        )
    md_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return {"json_report": str(json_path), "md_report": str(md_path)}


def main() -> int:
    args = parse_args()
    run_id = str(args.run_id or build_pipeline_run_id("pipeline"))
    replay_before = replay_buffer_summary()
    recommendation = pipeline_recommendation(replay=replay_before)
    min_usable = int(args.min_usable_replays if args.min_usable_replays >= 0 else recommendation["thresholds"]["min_usable_replays"])
    if int(replay_before.get("usable_replays") or 0) < max(1, min_usable):
        raise SystemExit(
            f"usable_replays {int(replay_before.get('usable_replays') or 0)} below required threshold {max(1, min_usable)}"
        )

    dataset_paths = dataset_paths_for_run(run_id)
    candidate_paths = candidate_paths_for_run(run_id, include_exp2=bool(args.include_exp2))

    prepare_cmd = [
        sys.executable,
        str(ROOT / "scripts" / "games" / "chess_replay_prepare.py"),
        "--replace-output",
        "--output-dir",
        str(dataset_paths["root"]),
    ]
    if args.include_quarantine:
        prepare_cmd.append("--include-quarantine")
    prepare = _run_json(prepare_cmd)

    seed_cmd = [
        sys.executable,
        str(ROOT / "scripts" / "games" / "chess_seed_train.py"),
        "--preset",
        args.preset,
        "--seed",
        str(int(args.seed)),
        "--dl-search-depth",
        str(int(args.dl_search_depth)),
        "--dl-quiescence-depth",
        str(int(args.dl_quiescence_depth)),
        "--pv-search-depth",
        str(int(args.pv_search_depth)),
        "--pv-quiescence-depth",
        str(int(args.pv_quiescence_depth)),
        "--experiment-3-model-path",
        str(candidate_paths["experiment 3:dl"]),
        "--experiment-4-model-path",
        str(candidate_paths["experiment 4:pv"]),
    ]
    if args.include_exp2:
        seed_cmd.extend(["--include-exp2", "--experiment-2-model-path", str(candidate_paths["experiment 2:nn"])])
    if args.skip_exp3:
        seed_cmd.append("--skip-exp3")
    if args.skip_exp4:
        seed_cmd.append("--skip-exp4")
    if int(args.teacher_depth) > 0:
        seed_cmd.extend(["--teacher-depth", str(int(args.teacher_depth))])
    if int(args.max_plies) > 0:
        seed_cmd.extend(["--max-plies", str(int(args.max_plies))])
    if float(args.student_exploration_rate) >= 0:
        seed_cmd.extend(["--student-exploration-rate", str(float(args.student_exploration_rate))])
    seed_train = _run_json(seed_cmd)

    exp3_refine = {"ok": False, "skipped": True, "reason": "exp3 refine not requested"}
    if not args.skip_exp3 and not args.skip_exp3_refine and int(prepare.get("accepted_train_samples") or 0) > 0:
        exp3_cmd = [
            sys.executable,
            str(ROOT / "scripts" / "games" / "chess_exp3_dataset_train.py"),
            "--input-jsonl",
            str(dataset_paths["train"]),
            "--model-path",
            str(candidate_paths["experiment 3:dl"]),
            "--replay-path",
            str(candidate_paths["experiment 3:dl replay"]),
        ]
        exp3_refine = _run_json(exp3_cmd)
        exp3_refine["ok"] = True

    benchmark_cmd = [
        sys.executable,
        str(ROOT / "scripts" / "games" / "chess_self_play_train.py"),
        "--exp1-games", "0",
        "--exp2-games", "0",
        "--exp3-games", "0",
        "--exp4-games", "0",
        "--hard-exp1-games", "0",
        "--hard-exp2-games", "0",
        "--hard-exp3-games", "0",
        "--hard-exp4-games", "0",
        "--cross-games", "0",
        "--cross-exp1-exp3-games", "0",
        "--cross-exp2-exp3-games", "0",
        "--cross-exp1-exp4-games", "0",
        "--cross-exp2-exp4-games", "0",
        "--cross-exp3-exp4-games", "0",
        "--smoke-games-per-pair",
        str(max(1, int(args.smoke_games_per_pair))),
        "--benchmark-rounds",
        str(max(1, int(args.benchmark_rounds))),
        "--seed",
        str(int(args.seed) + 1000),
        "--experiment-3-model-path",
        str(candidate_paths["experiment 3:dl"]),
        "--experiment-4-model-path",
        str(candidate_paths["experiment 4:pv"]),
    ]
    if args.include_exp2:
        benchmark_cmd.extend(["--experiment-2-model-path", str(candidate_paths["experiment 2:nn"])])
    if int(args.teacher_depth) > 0:
        benchmark_cmd.extend(["--teacher-depth", str(int(args.teacher_depth))])
    if int(args.max_plies) > 0:
        benchmark_cmd.extend(["--max-plies", str(int(args.max_plies))])
    benchmark = _run_json(benchmark_cmd)
    benchmark_report_path = str((benchmark.get("reports") or {}).get("json_report") or "")

    promotion_results = []
    requested_engines = [item.strip() for item in str(args.promote_engines or "").split(",") if item.strip()]
    for engine in requested_engines:
        source_path = candidate_paths.get(engine)
        if source_path is None or not Path(source_path).exists():
            promotion_results.append({
                "engine": engine,
                "staged": False,
                "promoted": False,
                "gate_pass": False,
                "reason": "candidate model missing",
            })
            continue
        stage_result = stage_candidate_model(
            engine=engine,
            source_path=Path(source_path),
            benchmark_report_path=Path(benchmark_report_path) if benchmark_report_path else None,
        )
        row = {
            "engine": engine,
            "staged": bool(stage_result.get("ok")),
            "promoted": False,
            "gate_pass": bool(((stage_result.get("promotion_gate") or {}) if isinstance(stage_result, dict) else {}) or False),
            "candidate_path": str(source_path),
        }
        if not args.skip_promote and not args.stage_only:
            try:
                promote_result = promote_candidate_model(
                    engine=engine,
                    benchmark_report_path=Path(benchmark_report_path),
                )
                row["promoted"] = bool(promote_result.get("ok"))
                row["production_path"] = str(promote_result.get("production_path") or "")
                row["gate_pass"] = True
            except Exception as exc:
                row["reason"] = str(exc)
        promotion_results.append(row)

    finished_at = datetime.utcnow().isoformat() + "Z"
    summary = {
        "ok": True,
        "run_id": run_id,
        "finished_at": finished_at,
        "replay_before": replay_before,
        "recommendation": recommendation,
        "prepare": prepare,
        "seed_train": seed_train,
        "exp3_refine": exp3_refine,
        "benchmark": benchmark,
        "benchmark_report_path": benchmark_report_path,
        "candidate_paths": {key: str(value) for key, value in candidate_paths.items()},
        "dataset_paths": {key: str(value) for key, value in dataset_paths.items()},
        "promotion_results": promotion_results,
    }
    summary["reports"] = _write_report(summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
