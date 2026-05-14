#!/usr/bin/env python3
"""Evaluate exp5 main-model + experience-adapter mode.

This wrapper keeps the main model as the production decision source and exposes
an opt-in adapter through environment variables. It runs the same exp5 score
probe, tactical suite, complete-game gauntlet, and advanced score used for
direct-retrain candidates, then counts adapter adoption events in the emitted
artifacts.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _iso_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _progress(message: str) -> None:
    print(f"[chess-exp5-adapter-eval] {message}", file=sys.stderr, flush=True)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _run(cmd: list[str], *, env: dict[str, str], output_dir: Path, name: str) -> None:
    _progress(f"run {name}: {' '.join(cmd)}")
    started = time.perf_counter()
    proc = subprocess.run(cmd, cwd=str(ROOT), env=env, text=True, capture_output=True, check=False)
    elapsed = round(time.perf_counter() - started, 3)
    logs = output_dir / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    stdout_path = logs / f"{name}.stdout"
    stderr_path = logs / f"{name}.stderr"
    stdout_path.write_text(proc.stdout, encoding="utf-8")
    stderr_path.write_text(proc.stderr, encoding="utf-8")
    with (output_dir / "commands.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(
            json.dumps(
                {
                    "name": name,
                    "cmd": cmd,
                    "returncode": int(proc.returncode),
                    "elapsed_seconds": elapsed,
                    "stdout_path": str(stdout_path),
                    "stderr_path": str(stderr_path),
                },
                ensure_ascii=False,
                sort_keys=True,
            )
            + "\n"
        )
    if proc.returncode != 0:
        raise RuntimeError(f"{name} failed with exit {proc.returncode}; stderr={proc.stderr[-2000:]}")


def _adapter_counts(payload: Any) -> dict[str, Any]:
    total = 0
    adopted = 0
    source_counts: dict[str, int] = {}
    reason_counts: dict[str, int] = {}

    def walk(obj: Any) -> None:
        nonlocal total, adopted
        if isinstance(obj, dict):
            decision = obj.get("adapter_decision")
            if isinstance(decision, dict):
                total += 1
                if bool(decision.get("adopted")):
                    adopted += 1
                source = str(decision.get("source") or "")
                if source:
                    source_counts[source] = source_counts.get(source, 0) + 1
                for reason in decision.get("reasons") or []:
                    reason_text = str(reason or "")
                    if reason_text:
                        reason_counts[reason_text] = reason_counts.get(reason_text, 0) + 1
            for value in obj.values():
                walk(value)
        elif isinstance(obj, list):
            for item in obj:
                walk(item)

    walk(payload)
    return {
        "adapter_decisions": total,
        "adapter_adoptions": adopted,
        "adapter_adoption_rate": round(adopted / max(1, total), 6),
        "source_counts": source_counts,
        "reason_counts": reason_counts,
    }


def _write_markdown(output_dir: Path, summary: dict[str, Any]) -> Path:
    path = output_dir / "SUMMARY.md"
    advanced = summary.get("advanced_score") or {}
    gauntlet = summary.get("gauntlet_summary") or {}
    tactical = summary.get("tactical_summary") or {}
    adapter = summary.get("adapter_counts") or {}
    lines = [
        "# Exp5 Adapter Mode Evaluation",
        "",
        f"- generated_at: `{summary.get('generated_at')}`",
        f"- main_model_path: `{summary.get('main_model_path')}`",
        f"- adapter_model_path: `{summary.get('adapter_model_path')}`",
        f"- adapter_rows_path: `{summary.get('adapter_rows_path')}`",
        f"- adapter_mode: `{summary.get('adapter_mode')}`",
        f"- adapter_allow_exact_adoption: `{summary.get('adapter_allow_exact_adoption')}`",
        f"- adapter_allow_general_adapter: `{summary.get('adapter_allow_general_adapter')}`",
        "",
        "## Result",
        f"- advanced score: `{advanced.get('normalized_100')}`",
        f"- grade: `{advanced.get('grade')}`",
        f"- gauntlet: `{gauntlet.get('ai_wins')}`W/`{gauntlet.get('draws')}`D/`{gauntlet.get('codex_wins')}`L",
        f"- gauntlet score rate: `{gauntlet.get('ai_score_rate')}`",
        f"- threefold rate: `{gauntlet.get('threefold_rate')}`",
        f"- tactical suite: `{tactical.get('passed')}`/`{tactical.get('cases')}`",
        f"- adapter decisions: `{adapter.get('adapter_decisions')}`, adoptions `{adapter.get('adapter_adoptions')}`",
        f"- adoption source counts: `{adapter.get('source_counts')}`",
        f"- rejection reason counts: `{adapter.get('reason_counts')}`",
        "",
        "## Artifacts",
        f"- score_probe: `{summary.get('artifacts', {}).get('score_probe')}`",
        f"- tactical_suite: `{summary.get('artifacts', {}).get('tactical_suite')}`",
        f"- gauntlet: `{summary.get('artifacts', {}).get('gauntlet')}`",
        f"- gauntlet_jsonl: `{summary.get('artifacts', {}).get('gauntlet_jsonl')}`",
        f"- advanced_score: `{summary.get('artifacts', {}).get('advanced_score')}`",
        f"- summary_json: `{summary.get('artifacts', {}).get('summary_json')}`",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate exp5 adapter mode.")
    parser.add_argument("--main-model-path", required=True)
    parser.add_argument("--adapter-model-path", required=True)
    parser.add_argument("--adapter-rows-path", required=True)
    parser.add_argument("--adapter-mode", default="guarded", choices=["guarded", "exact", "shadow"])
    parser.add_argument("--allow-exact-adoption", action="store_true")
    parser.add_argument("--allow-general-adapter", action="store_true")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--tactical-cases", type=int, default=300)
    parser.add_argument("--pgn-case-count", type=int, default=240)
    parser.add_argument("--gauntlet-max-plies", type=int, default=220)
    parser.add_argument(
        "--gauntlet-openings",
        default="start,open_game,sicilian,french,caro_kann,scandinavian,queen_pawn,queens_gambit,kings_indian,english,reti,fianchetto,kings_gambit,flank_probe,early_queen_probe",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    main_model = Path(args.main_model_path).expanduser().resolve()
    adapter_model = Path(args.adapter_model_path).expanduser().resolve()
    adapter_rows = Path(args.adapter_rows_path).expanduser().resolve()
    for path in (main_model, adapter_model, adapter_rows):
        if not path.exists():
            raise FileNotFoundError(path)
    output_dir = Path(args.output_dir).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=False)
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT)
    env["HTML_LEARNING_CHESS_ENGINE_NNUE_MODEL_PATH"] = str(main_model)
    env["HTML_LEARNING_CHESS_ENGINE_NNUE_ADAPTER_MODEL_PATH"] = str(adapter_model)
    env["HTML_LEARNING_CHESS_ENGINE_NNUE_ADAPTER_ROWS_PATH"] = str(adapter_rows)
    env["HTML_LEARNING_CHESS_ENGINE_NNUE_ADAPTER_MODE"] = str(args.adapter_mode)
    if args.allow_exact_adoption:
        env["HTML_LEARNING_CHESS_ENGINE_NNUE_ADAPTER_ALLOW_EXACT"] = "1"
    else:
        env.pop("HTML_LEARNING_CHESS_ENGINE_NNUE_ADAPTER_ALLOW_EXACT", None)
    if args.allow_general_adapter:
        env["HTML_LEARNING_CHESS_ENGINE_NNUE_ADAPTER_ALLOW_GENERAL"] = "1"
    else:
        env.pop("HTML_LEARNING_CHESS_ENGINE_NNUE_ADAPTER_ALLOW_GENERAL", None)

    score_probe = output_dir / "adapter_score_probe.json"
    tactical = output_dir / "adapter_tactical_suite_300.json"
    gauntlet = output_dir / "adapter_gauntlet_30.json"
    gauntlet_jsonl = output_dir / "adapter_gauntlet_30.jsonl"
    advanced = output_dir / "adapter_advanced_score.json"

    _run(
        [
            sys.executable,
            str(ROOT / "scripts" / "games" / "chess_exp5_score_probe.py"),
            "--output",
            str(score_probe),
            "--games-per-side",
            "3",
            "--chess-max-plies",
            "120",
            "--external-case-limit",
            "24",
        ],
        env=env,
        output_dir=output_dir,
        name="adapter_score_probe",
    )
    _run(
        [
            sys.executable,
            str(ROOT / "scripts" / "games" / "chess_exp5_tactical_suite.py"),
            "--target-cases",
            str(int(args.tactical_cases)),
            "--pgn-case-count",
            str(int(args.pgn_case_count)),
            "--output",
            str(tactical),
        ],
        env=env,
        output_dir=output_dir,
        name="adapter_tactical_suite",
    )
    _run(
        [
            sys.executable,
            str(ROOT / "scripts" / "games" / "chess_exp5_gauntlet.py"),
            "--games-per-opening",
            "2",
            "--max-plies",
            str(int(args.gauntlet_max_plies)),
            "--openings",
            str(args.gauntlet_openings),
            "--output",
            str(gauntlet),
            "--jsonl-output",
            str(gauntlet_jsonl),
        ],
        env=env,
        output_dir=output_dir,
        name="adapter_gauntlet",
    )
    _run(
        [
            sys.executable,
            str(ROOT / "scripts" / "games" / "chess_exp5_advanced_score.py"),
            "--score-probe",
            str(score_probe),
            "--tactical-suite",
            str(tactical),
            "--gauntlet",
            str(gauntlet),
            "--output",
            str(advanced),
        ],
        env=env,
        output_dir=output_dir,
        name="adapter_advanced_score",
    )

    artifacts_payload = {
        "score_probe": _load_json(score_probe),
        "tactical": _load_json(tactical),
        "gauntlet": _load_json(gauntlet),
    }
    summary = {
        "ok": True,
        "generated_at": _iso_now(),
        "main_model_path": str(main_model),
        "main_model_sha256": _sha256_file(main_model),
        "adapter_model_path": str(adapter_model),
        "adapter_model_sha256": _sha256_file(adapter_model),
        "adapter_rows_path": str(adapter_rows),
        "adapter_rows_sha256": _sha256_file(adapter_rows),
        "adapter_mode": str(args.adapter_mode),
        "adapter_allow_exact_adoption": bool(args.allow_exact_adoption),
        "adapter_allow_general_adapter": bool(args.allow_general_adapter),
        "advanced_score": _load_json(advanced),
        "score_probe_summary": artifacts_payload["score_probe"].get("summary") or {},
        "tactical_summary": artifacts_payload["tactical"].get("summary") or {},
        "gauntlet_summary": artifacts_payload["gauntlet"].get("summary") or {},
        "adapter_counts": _adapter_counts(artifacts_payload),
        "artifacts": {
            "score_probe": str(score_probe),
            "tactical_suite": str(tactical),
            "gauntlet": str(gauntlet),
            "gauntlet_jsonl": str(gauntlet_jsonl),
            "advanced_score": str(advanced),
            "summary_json": str(output_dir / "summary.json"),
            "summary_md": str(output_dir / "SUMMARY.md"),
            "commands_jsonl": str(output_dir / "commands.jsonl"),
        },
    }
    _write_json(output_dir / "summary.json", summary)
    md_path = _write_markdown(output_dir, summary)
    summary["artifacts"]["summary_md"] = str(md_path)
    _write_json(output_dir / "summary.json", summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
