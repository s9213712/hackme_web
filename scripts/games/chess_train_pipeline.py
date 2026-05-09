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


def _progress(message: str) -> None:
    print(f"[chess-train-pipeline] {message}", file=sys.stderr, flush=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Full offline chess replay -> prepare -> train -> benchmark -> promote pipeline.")
    parser.add_argument("--run-id", default="")
    parser.add_argument("--preset", choices=["micro", "quick", "standard", "strong"], default="standard")
    parser.add_argument("--include-quarantine", action="store_true")
    parser.add_argument("--include-exp2", action="store_true")
    parser.add_argument("--skip-exp3", action="store_true")
    parser.add_argument("--skip-exp4", action="store_true")
    parser.add_argument("--skip-exp1-refine", action="store_true")
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
    parser.add_argument("--skip-benchmark", action="store_true")
    parser.add_argument(
        "--promote-engines",
        default="experiment 3:dl,experiment 4:pv",
        help="Comma-separated engines to auto stage/promote if their gate passes.",
    )
    return parser.parse_args()


def _run_json(cmd: list[str], *, label: str) -> dict:
    _progress(f"phase {label} started: {' '.join(cmd)}")
    proc = subprocess.run(cmd, cwd=str(ROOT), text=True, capture_output=True)
    if proc.stderr:
        sys.stderr.write(proc.stderr)
        sys.stderr.flush()
    if proc.returncode != 0:
        raise RuntimeError(f"command failed for {label}: {' '.join(cmd)}\nstdout={proc.stdout}\nstderr={proc.stderr}")
    try:
        payload = json.loads(proc.stdout)
    except Exception as exc:
        raise RuntimeError(f"command did not emit JSON: {' '.join(cmd)}\nstdout={proc.stdout}\nstderr={proc.stderr}") from exc
    _progress(f"phase result {label}: ok")
    return payload


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
        f"- exp1_refine_samples: `{summary.get('exp1_refine', {}).get('accepted_samples', 0)}`",
        f"- exp2_refine_samples: `{summary.get('exp2_refine', {}).get('accepted_samples', 0)}`",
        f"- exp3_refine_samples: `{summary.get('exp3_refine', {}).get('accepted_samples', 0)}`",
        f"- exp4_refine_samples: `{summary.get('exp4_refine', {}).get('accepted_samples', 0)}`",
        f"- benchmark_skipped: `{summary['benchmark'].get('skipped', False)}`",
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
    _progress(f"run_id: {run_id}")
    _progress(f"preset: {args.preset} seed={int(args.seed)}")
    _progress(f"repo root: {ROOT}")
    replay_before = replay_buffer_summary()
    recommendation = pipeline_recommendation(replay=replay_before)
    min_usable = int(args.min_usable_replays if args.min_usable_replays >= 0 else recommendation["thresholds"]["min_usable_replays"])
    _progress(f"phase replay scan: usable={int(replay_before.get('usable_replays') or 0)} required={max(1, min_usable)}")
    if int(replay_before.get("usable_replays") or 0) < max(1, min_usable):
        raise SystemExit(
            f"usable_replays {int(replay_before.get('usable_replays') or 0)} below required threshold {max(1, min_usable)}"
        )

    dataset_paths = dataset_paths_for_run(run_id)
    candidate_paths = candidate_paths_for_run(run_id, include_exp2=bool(args.include_exp2))
    _progress(f"dataset root: {dataset_paths['root']}")
    _progress(f"candidate root: {candidate_paths.get('root', '<derived paths>')}")

    prepare_cmd = [
        sys.executable,
        str(ROOT / "scripts" / "games" / "chess_replay_prepare.py"),
        "--replace-output",
        "--output-dir",
        str(dataset_paths["root"]),
    ]
    if args.include_quarantine:
        prepare_cmd.append("--include-quarantine")
    prepare = _run_json(prepare_cmd, label="prepare dataset")

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
        "--experiment-db-path",
        str(candidate_paths["experiment"]),
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
    seed_train = _run_json(seed_cmd, label="seed train")

    exp1_refine = {"ok": False, "skipped": True, "reason": "exp1 refine not requested"}
    if not args.skip_exp1_refine and int(prepare.get("accepted_train_samples") or 0) > 0:
        exp1_cmd = [
            sys.executable,
            str(ROOT / "scripts" / "games" / "chess_exp1_dataset_train.py"),
            "--input-jsonl",
            str(dataset_paths["train"]),
            "--db-path",
            str(candidate_paths["experiment"]),
        ]
        exp1_refine = _run_json(exp1_cmd, label="exp1 refine")
    else:
        _progress(f"phase exp1 refine skipped: {exp1_refine['reason']}")

    exp2_refine = {"ok": False, "skipped": True, "reason": "exp2 refine not requested"}
    if args.include_exp2 and int(prepare.get("accepted_train_samples") or 0) > 0:
        exp2_cmd = [
            sys.executable,
            str(ROOT / "scripts" / "games" / "chess_exp2_dataset_train.py"),
            "--input-jsonl",
            str(dataset_paths["train"]),
            "--model-path",
            str(candidate_paths["experiment 2:nn"]),
        ]
        exp2_refine = _run_json(exp2_cmd, label="exp2 refine")
    else:
        _progress(f"phase exp2 refine skipped: {exp2_refine['reason']}")

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
        exp3_refine = _run_json(exp3_cmd, label="exp3 refine")
    else:
        _progress(f"phase exp3 refine skipped: {exp3_refine['reason']}")

    exp4_refine = {"ok": False, "skipped": True, "reason": "exp4 refine not requested"}
    if not args.skip_exp4 and int(prepare.get("accepted_train_samples") or 0) > 0:
        exp4_cmd = [
            sys.executable,
            str(ROOT / "scripts" / "games" / "chess_exp4_dataset_train.py"),
            "--input-jsonl",
            str(dataset_paths["train"]),
            "--model-path",
            str(candidate_paths["experiment 4:pv"]),
        ]
        exp4_refine = _run_json(exp4_cmd, label="exp4 refine")
    else:
        _progress(f"phase exp4 refine skipped: {exp4_refine['reason']}")

    benchmark_report_path = ""
    if args.skip_benchmark:
        benchmark = {
            "ok": True,
            "skipped": True,
            "reason": "disabled_by_flag",
            "reports": {},
        }
        _progress("phase benchmark skipped: disabled_by_flag")
    else:
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
            "--experiment-db-path",
            str(candidate_paths["experiment"]),
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
        benchmark = _run_json(benchmark_cmd, label="benchmark")
        benchmark_report_path = str((benchmark.get("reports") or {}).get("json_report") or "")
        _progress(f"benchmark artifact: {benchmark_report_path or '<none>'}")

    promotion_results = []
    skip_promote_effective = bool(args.skip_promote or args.skip_benchmark)
    requested_engines = [item.strip() for item in str(args.promote_engines or "").split(",") if item.strip()]
    for engine in requested_engines:
        _progress(f"phase stage/promote started: {engine}")
        source_path = candidate_paths.get(engine)
        if source_path is None or not Path(source_path).exists():
            promotion_results.append({
                "engine": engine,
                "staged": False,
                "promoted": False,
                "gate_pass": False,
                "reason": "candidate model missing",
            })
            _progress(f"phase result stage/promote {engine}: skipped candidate model missing")
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
        if not skip_promote_effective and not args.stage_only:
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
        elif args.skip_benchmark:
            row["reason"] = "promotion skipped because benchmark was disabled"
        promotion_results.append(row)
        _progress(f"phase result stage/promote {engine}: staged={row.get('staged')} promoted={row.get('promoted')} gate={row.get('gate_pass')}")

    finished_at = datetime.utcnow().isoformat() + "Z"
    summary = {
        "ok": True,
        "run_id": run_id,
        "finished_at": finished_at,
        "replay_before": replay_before,
        "recommendation": recommendation,
        "prepare": prepare,
        "seed_train": seed_train,
        "exp1_refine": exp1_refine,
        "exp2_refine": exp2_refine,
        "exp3_refine": exp3_refine,
        "exp4_refine": exp4_refine,
        "benchmark": benchmark,
        "benchmark_report_path": benchmark_report_path,
        "candidate_paths": {key: str(value) for key, value in candidate_paths.items()},
        "dataset_paths": {key: str(value) for key, value in dataset_paths.items()},
        "promotion_results": promotion_results,
    }
    summary["reports"] = _write_report(summary)
    _progress(f"phase result report: json={summary['reports']['json_report']} md={summary['reports']['md_report']}")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    _progress("phase result pipeline: PASS")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        _progress(f"FAIL: {exc}")
        _progress("failure hint: inspect the last phase above, child stderr, and runtime/reports/games pipeline report paths")
        raise
