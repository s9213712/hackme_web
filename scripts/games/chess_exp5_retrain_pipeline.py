#!/usr/bin/env python3
"""Minimal exp5-only replay retrain pipeline.

This pipeline intentionally stays separate from exp3/exp4 live-learning gates.
It prepares an exp5 candidate model and report, but does not claim strength
improvement or promotion readiness.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime
from pathlib import Path
import shutil
import subprocess
import sys
import time


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.games.chess_arena import default_chess_reports_dir  # noqa: E402
from services.games.chess_pipeline import candidate_paths_for_run  # noqa: E402
from services.games.chess_nnue import EXP5_STATIC_BASE_MODEL_SHA256, default_chess_nnue_model_path  # noqa: E402


def _progress(message: str) -> None:
    print(f"[chess-exp5-pipeline] {message}", file=sys.stderr, flush=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Exp5-only minimal replay retrain pipeline.")
    parser.add_argument("--input-jsonl", action="append", default=[], help="Exp5-compatible FEN/move JSONL files.")
    parser.add_argument("--run-id", default="")
    parser.add_argument("--candidate-model-path", default="")
    parser.add_argument("--candidate-replay-path", default="")
    parser.add_argument("--baseline-model-path", default="")
    parser.add_argument("--max-samples", type=int, default=0)
    parser.add_argument("--replace-replay", action="store_true")
    return parser.parse_args()


def _run_json(cmd: list[str]) -> dict:
    _progress("phase trainer started: " + " ".join(cmd))
    proc = subprocess.run(cmd, cwd=str(ROOT), text=True, capture_output=True)
    if proc.stderr:
        sys.stderr.write(proc.stderr)
        sys.stderr.flush()
    if proc.returncode != 0:
        raise RuntimeError(f"trainer failed: {' '.join(cmd)}\nstdout={proc.stdout}\nstderr={proc.stderr}")
    try:
        return json.loads(proc.stdout)
    except Exception as exc:
        raise RuntimeError(f"trainer did not emit JSON\nstdout={proc.stdout}\nstderr={proc.stderr}") from exc


def _sha256_file(path: Path) -> str:
    path = Path(path)
    if not path.exists():
        return ""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sha256_inputs(paths: list[Path]) -> str:
    digest = hashlib.sha256()
    for path in sorted(paths, key=lambda item: str(item)):
        digest.update(str(path).encode("utf-8"))
        digest.update(b"\0")
        digest.update(_sha256_file(path).encode("ascii"))
        digest.update(b"\0")
    return digest.hexdigest()


def _write_report(summary: dict) -> dict:
    reports_dir = default_chess_reports_dir()
    reports_dir.mkdir(parents=True, exist_ok=True)
    stamp = summary["finished_at"].replace(":", "").replace("-", "").replace("T", "_").replace("Z", "")
    json_path = reports_dir / f"chess_exp5_retrain_pipeline_{stamp}.json"
    md_path = reports_dir / f"chess_exp5_retrain_pipeline_{stamp}.md"
    json_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    lines = [
        "# chess_exp5_retrain_pipeline",
        "",
        f"- run_id: `{summary['run_id']}`",
        f"- baseline_model_path: `{summary['baseline_model_path']}`",
        f"- candidate_model_path: `{summary['candidate_model_path']}`",
        f"- baseline_hash: `{summary['baseline_hash']}`",
        f"- candidate_hash: `{summary['candidate_hash']}`",
        f"- dataset_hash: `{summary['dataset_hash']}`",
        f"- accepted_samples: `{summary['trainer_result'].get('accepted_samples', 0)}`",
        f"- rejected_samples: `{summary['trainer_result'].get('rejected_samples', 0)}`",
        f"- strength_validation_supported: `{summary['strength_validation_supported']}`",
        f"- promotion_gate_supported: `{summary['promotion_gate_supported']}`",
        "",
        "## Boundary",
        "",
        "- This is exp5-only scaffolding.",
        "- It does not reuse exp3/exp4 semantic replay gates.",
        "- Strength validation and promotion gate design are pending.",
    ]
    md_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return {"json_report": str(json_path), "md_report": str(md_path)}


def main() -> int:
    args = parse_args()
    run_id = str(args.run_id or f"exp5_{datetime.utcnow().strftime('%Y%m%dT%H%M%SZ')}")
    default_candidates = candidate_paths_for_run(run_id)
    candidate_model_path = (
        Path(args.candidate_model_path).expanduser().resolve()
        if args.candidate_model_path
        else default_candidates["experiment 5:nnue"]
    )
    candidate_replay_path = (
        Path(args.candidate_replay_path).expanduser().resolve()
        if args.candidate_replay_path
        else default_candidates["experiment 5:nnue replay"]
    )
    baseline_model_path = Path(args.baseline_model_path).expanduser().resolve() if args.baseline_model_path else default_chess_nnue_model_path()
    input_paths = [Path(item).expanduser().resolve() for item in args.input_jsonl]
    if baseline_model_path.exists() and not candidate_model_path.exists():
        candidate_model_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(baseline_model_path, candidate_model_path)
    baseline_hash = _sha256_file(baseline_model_path) or EXP5_STATIC_BASE_MODEL_SHA256
    dataset_hash = _sha256_inputs(input_paths)
    distill_config_hash = hashlib.sha256(
        json.dumps(
            {
                "input_jsonl": [str(path) for path in input_paths],
                "max_samples": int(args.max_samples or 0),
                "replace_replay": bool(args.replace_replay),
                "baseline_model_hash": baseline_hash,
            },
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()
    trainer_cmd = [
        sys.executable,
        str(ROOT / "scripts" / "games" / "chess_exp5_dataset_train.py"),
        "--model-path",
        str(candidate_model_path),
        "--replay-path",
        str(candidate_replay_path),
    ]
    for input_path in input_paths:
        trainer_cmd.extend(["--input-jsonl", str(input_path)])
    if args.replace_replay:
        trainer_cmd.append("--replace-replay")
    if int(args.max_samples) > 0:
        trainer_cmd.extend(["--max-samples", str(int(args.max_samples))])
    started = time.perf_counter()
    trainer_result = _run_json(trainer_cmd)
    retrain_seconds = round(time.perf_counter() - started, 6)
    candidate_hash = _sha256_file(candidate_model_path)
    finished_at = datetime.utcnow().isoformat() + "Z"
    summary = {
        "ok": bool(trainer_result.get("ok")),
        "run_id": run_id,
        "finished_at": finished_at,
        "engine": "experiment 5:nnue",
        "baseline_model_path": str(baseline_model_path),
        "baseline_source": "file" if baseline_model_path.exists() else "source_embedded_static_base",
        "candidate_model_path": str(candidate_model_path),
        "candidate_replay_path": str(candidate_replay_path),
        "baseline_hash": baseline_hash,
        "candidate_hash": candidate_hash,
        "hash_changed": bool(baseline_hash and candidate_hash and baseline_hash != candidate_hash),
        "dataset_hash": dataset_hash,
        "distill_config_hash": distill_config_hash,
        "retrain_seconds": retrain_seconds,
        "input_jsonl": [str(path) for path in input_paths],
        "trainer_result": trainer_result,
        "strength_validation_supported": False,
        "promotion_gate_supported": False,
        "boundary": "exp5-only minimal retrain pipeline; no exp3/exp4 semantic gate reuse",
    }
    summary["reports"] = _write_report(summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    _progress(f"phase result report: {summary['reports']['json_report']}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        _progress(f"FAIL: {exc}")
        _progress("failure hint: verify exp5 JSONL schema and candidate path permissions")
        raise
