#!/usr/bin/env python3
"""End-to-end dry-run orchestrator for the chess replay/training pipeline.

W6 commit 3. Runs every stage with safe defaults:

  1. PvP / human-vs-engine export
     ↳ scripts/games/chess_pvp_history_to_replay.py
  2. exp4 vs exp5 sparring (smoke mode by default)
     ↳ scripts/games/chess_exp4_vs_exp5_sparring.py
  3. Sparring artefacts → replay JSONL harvester
     ↳ scripts/games/chess_sparring_to_replay.py
  4. seed_train external-replay dry-run validation
     ↳ scripts/games/chess_seed_train.py --dry-run
  5. Aggregate per-stage summaries into one report
     ↳ scripts/games/chess_pipeline_report.py

Safety contract (intentionally narrow):

  * Every stage runs in its own subprocess. The orchestrator only reads
    summary files; it never writes models, never writes the main DB, and
    never opens a non-dry-run training.
  * Stage 4 ALWAYS uses --dry-run; the orchestrator does not expose a
    flag to disable that.
  * A "suggested staging warm-up command" is *printed* at the end (and
    embedded in the aggregate report). The operator has to manually
    copy/paste it into a new shell after reviewing the dry-run artifact
    and providing an explicit staging candidate path — the orchestrator
    never executes it.

Each stage is optional. A missing prerequisite (no runtime DB given, no
sparring model paths given, etc.) makes that stage skip and the rest of
the pipeline continues.
"""
from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

PVP_CONVERTER = REPO_ROOT / "scripts" / "games" / "chess_pvp_history_to_replay.py"
SPARRING_RUNNER = REPO_ROOT / "scripts" / "games" / "chess_exp4_vs_exp5_sparring.py"
SPARRING_HARVESTER = REPO_ROOT / "scripts" / "games" / "chess_sparring_to_replay.py"
SEED_TRAIN = REPO_ROOT / "scripts" / "games" / "chess_seed_train.py"
AGGREGATOR = REPO_ROOT / "scripts" / "games" / "chess_pipeline_report.py"


def _now_dirname() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S_%fZ")


def _latest_subdir(root: Path, prefix: str) -> Path | None:
    candidates = sorted(
        (p for p in root.glob(f"{prefix}*") if p.is_dir()),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    return candidates[0] if candidates else None


def _run_subprocess(cmd: list[str], *, label: str, log_file: Path) -> int:
    """Run a stage subprocess, tee its output to log_file, return exit code."""
    log_file.parent.mkdir(parents=True, exist_ok=True)
    with log_file.open("w", encoding="utf-8") as fh:
        fh.write(f"# {label}\n")
        fh.write("# cmd: " + " ".join(shlex.quote(c) for c in cmd) + "\n\n")
        fh.flush()
        proc = subprocess.run(
            cmd,
            env=os.environ.copy(),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        fh.write(proc.stdout or "")
    return proc.returncode


# ---- stage runners (each returns dict with status + artefacts) --------


def run_pvp_export_stage(
    *,
    runtime_dir: str,
    since: str,
    output_root: Path,
    log_dir: Path,
) -> dict:
    """Stage 1: export PvP / human-vs-engine replay JSONL."""
    if not runtime_dir:
        return {"stage": "pvp_export", "status": "skipped", "reason": "no --runtime-dir"}
    output_root.mkdir(parents=True, exist_ok=True)
    cmd = [
        sys.executable,
        str(PVP_CONVERTER),
        "--output-root",
        str(output_root),
    ]
    if since:
        cmd.extend(["--since", since])
    env = os.environ.copy()
    env["HACKME_RUNTIME_DIR"] = runtime_dir
    log = log_dir / "01_pvp_export.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("w", encoding="utf-8") as fh:
        fh.write(
            "# pvp_export\n# cmd: "
            + " ".join(shlex.quote(c) for c in cmd)
            + f"\n# HACKME_RUNTIME_DIR={runtime_dir}\n\n"
        )
        fh.flush()
        proc = subprocess.run(
            cmd, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
        )
        fh.write(proc.stdout or "")
    if proc.returncode != 0:
        return {"stage": "pvp_export", "status": "failed", "exit_code": proc.returncode, "log": str(log)}
    run_dir = _latest_subdir(output_root, "pvp_replay_")
    if not run_dir:
        return {"stage": "pvp_export", "status": "failed", "reason": "no pvp_replay_* dir found", "log": str(log)}
    return {
        "stage": "pvp_export",
        "status": "ok",
        "run_dir": str(run_dir),
        "summary_path": str(run_dir / "summary.json"),
        "training_eligible_jsonl": str(run_dir / "pvp_replay_training_eligible.jsonl"),
        "log": str(log),
    }


def run_sparring_stage(
    *,
    exp4_model_path: str,
    exp5_model_path: str,
    mode: str,
    output_root: Path,
    log_dir: Path,
    max_plies: int,
) -> dict:
    """Stage 2: exp4 vs exp5 sparring."""
    if not exp4_model_path or not exp5_model_path:
        return {
            "stage": "sparring",
            "status": "skipped",
            "reason": "missing --exp4-model-path or --exp5-model-path",
        }
    output_root.mkdir(parents=True, exist_ok=True)
    cmd = [
        sys.executable,
        str(SPARRING_RUNNER),
        "--non-interactive",
        "--exp4-model-path",
        exp4_model_path,
        "--exp5-model-path",
        exp5_model_path,
        "--mode",
        mode,
        "--max-plies",
        str(max_plies),
        "--output-root",
        str(output_root),
    ]
    log = log_dir / "02_sparring.log"
    rc = _run_subprocess(cmd, label="sparring", log_file=log)
    if rc != 0:
        return {"stage": "sparring", "status": "failed", "exit_code": rc, "log": str(log)}
    run_dir = _latest_subdir(output_root, "exp4_vs_exp5_smoke_")
    if not run_dir:
        return {"stage": "sparring", "status": "failed", "reason": "no exp4_vs_exp5_smoke_* dir found", "log": str(log)}
    return {
        "stage": "sparring",
        "status": "ok",
        "run_dir": str(run_dir),
        "summary_path": str(run_dir / "summary.json"),
        "log": str(log),
    }


def run_sparring_to_replay_stage(
    *,
    sparring_run_dir: str,
    output_root: Path,
    log_dir: Path,
) -> dict:
    """Stage 3: sparring artefacts → replay JSONL."""
    if not sparring_run_dir:
        return {"stage": "sparring_to_replay", "status": "skipped", "reason": "no sparring run dir"}
    cmd = [
        sys.executable,
        str(SPARRING_HARVESTER),
        "--run-dir",
        sparring_run_dir,
        "--output-root",
        str(output_root),
    ]
    log = log_dir / "03_sparring_to_replay.log"
    rc = _run_subprocess(cmd, label="sparring_to_replay", log_file=log)
    if rc != 0:
        return {"stage": "sparring_to_replay", "status": "failed", "exit_code": rc, "log": str(log)}
    run_dir = _latest_subdir(output_root, "sparring_replay_")
    if not run_dir:
        return {"stage": "sparring_to_replay", "status": "failed", "reason": "no sparring_replay_* dir found", "log": str(log)}
    return {
        "stage": "sparring_to_replay",
        "status": "ok",
        "run_dir": str(run_dir),
        "summary_path": str(run_dir / "summary.json"),
        "training_eligible_jsonl": str(run_dir / "sparring_objective_replay.jsonl"),
        "log": str(log),
    }


def run_seed_train_dryrun_stage(
    *,
    include_jsonls: list[str],
    report_dir: Path,
    log_dir: Path,
) -> dict:
    """Stage 4: seed_train --dry-run (combines all available replay JSONLs)."""
    real_jsonls = [p for p in include_jsonls if p and Path(p).exists()]
    if not real_jsonls:
        return {
            "stage": "seed_train_dry_run",
            "status": "skipped",
            "reason": "no --include-replay-jsonl candidate present",
        }
    report_dir.mkdir(parents=True, exist_ok=True)
    cmd = [
        sys.executable,
        str(SEED_TRAIN),
        "--preset",
        "warmup10",
        "--dry-run",
        "--report-dir",
        str(report_dir),
    ]
    for jsonl in real_jsonls:
        cmd.extend(["--include-replay-jsonl", jsonl])
    log = log_dir / "04_seed_train_dryrun.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("w", encoding="utf-8") as fh:
        fh.write("# seed_train_dryrun\n# cmd: " + " ".join(shlex.quote(c) for c in cmd) + "\n\n")
        fh.flush()
        proc = subprocess.run(
            cmd, env=os.environ.copy(), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
        )
        fh.write(proc.stdout or "")
    if proc.returncode != 0:
        return {
            "stage": "seed_train_dry_run",
            "status": "failed",
            "exit_code": proc.returncode,
            "log": str(log),
        }
    # Parse the payload printed to stdout for the artifact path.
    try:
        payload = json.loads(proc.stdout or "{}")
    except Exception:
        payload = {}
    artifact = str(payload.get("dry_run_artifact") or "")
    return {
        "stage": "seed_train_dry_run",
        "status": "ok",
        "summary_path": artifact,  # artifact is the same shape as a stage summary
        "dry_run_artifact": artifact,
        "log": str(log),
    }


def run_aggregate_stage(
    *,
    summary_paths: list[str],
    output_dir: Path,
    next_step_command: str,
) -> dict:
    """Stage 5: aggregate all stage summaries into one final report."""
    if not summary_paths:
        return {"stage": "aggregate", "status": "skipped", "reason": "no summaries collected"}
    output_dir.mkdir(parents=True, exist_ok=True)
    cmd = [
        sys.executable,
        str(AGGREGATOR),
        "--output-dir",
        str(output_dir),
        "--next-step-command",
        next_step_command,
    ]
    for sp in summary_paths:
        cmd.extend(["--summary-path", sp])
    proc = subprocess.run(
        cmd, env=os.environ.copy(), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
    )
    if proc.returncode != 0:
        return {
            "stage": "aggregate",
            "status": "failed",
            "exit_code": proc.returncode,
            "stdout": proc.stdout or "",
        }
    return {
        "stage": "aggregate",
        "status": "ok",
        "pipeline_summary_json": str(output_dir / "pipeline_summary.json"),
        "pipeline_summary_md": str(output_dir / "PIPELINE_SUMMARY.md"),
        "stdout": proc.stdout or "",
    }


# ---- staging command helper -------------------------------------------


def build_suggested_staging_command(
    *,
    include_jsonls: list[str],
    candidate_dir: Path,
    skip_exp5: bool = True,
    preset: str = "warmup10",
) -> str:
    """Return a printable (but NOT executed) staging warm-up command.

    Uses an explicit candidate path under candidate_dir to satisfy the
    W4.2 default-path guard. exp5 is skipped by default to protect the
    production-promoted NNUE; the operator must drop --skip-exp5 and add
    an explicit exp5 candidate path if they want exp5 staging training.
    """
    parts: list[str] = [
        sys.executable,
        str(SEED_TRAIN),
        "--preset",
        preset,
    ]
    for jsonl in include_jsonls:
        parts.extend(["--include-replay-jsonl", jsonl])
    pv_candidate = candidate_dir / "chess_experiment_4_pv_candidate.json"
    parts.extend(["--experiment-4-model-path", str(pv_candidate)])
    if skip_exp5:
        parts.append("--skip-exp5")
    return " ".join(shlex.quote(str(x)) for x in parts)


# ---- main orchestrator -------------------------------------------------


def run_pipeline(args: argparse.Namespace) -> dict:
    """Top-level entry. Returns a dict with the result of every stage."""
    output_root = Path(args.output_root).expanduser().resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    run_root = output_root / f"pipeline_run_{_now_dirname()}"
    run_root.mkdir(parents=True)
    log_dir = run_root / "logs"

    stages: list[dict] = []

    # Stage 1: PvP export
    pvp = run_pvp_export_stage(
        runtime_dir=args.runtime_dir or "",
        since=args.since or "",
        output_root=run_root / "01_pvp_export",
        log_dir=log_dir,
    )
    stages.append(pvp)

    # Stage 2: sparring
    sp = run_sparring_stage(
        exp4_model_path=args.exp4_model_path or "",
        exp5_model_path=args.exp5_model_path or "",
        mode=args.sparring_mode or "smoke",
        output_root=run_root / "02_sparring",
        log_dir=log_dir,
        max_plies=int(args.sparring_max_plies or 40),
    )
    stages.append(sp)

    # Stage 3: sparring → replay (only if sparring produced a run dir)
    sparring_to_replay = run_sparring_to_replay_stage(
        sparring_run_dir=sp.get("run_dir") or "",
        output_root=run_root / "03_sparring_to_replay",
        log_dir=log_dir,
    )
    stages.append(sparring_to_replay)

    # Stage 4: seed_train dry-run with whatever replay JSONLs we have
    include_jsonls = [
        pvp.get("training_eligible_jsonl") or "",
        sparring_to_replay.get("training_eligible_jsonl") or "",
    ]
    dry_run = run_seed_train_dryrun_stage(
        include_jsonls=include_jsonls,
        report_dir=run_root / "04_seed_train_dryrun" / "reports",
        log_dir=log_dir,
    )
    stages.append(dry_run)

    # Stage 5: aggregate
    summary_paths = [s.get("summary_path") for s in stages if s.get("summary_path")]
    candidate_dir = run_root / "05_staging_candidate_suggested"
    next_step = build_suggested_staging_command(
        include_jsonls=[p for p in include_jsonls if p],
        candidate_dir=candidate_dir,
        skip_exp5=not args.train_exp5_in_suggestion,
    )
    aggregate = run_aggregate_stage(
        summary_paths=[sp for sp in summary_paths if sp],
        output_dir=run_root / "06_aggregate",
        next_step_command=next_step,
    )
    stages.append(aggregate)

    return {
        "run_root": str(run_root),
        "stages": stages,
        "suggested_staging_command": next_step,
    }


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=(
            "End-to-end dry-run orchestrator for the chess replay/training "
            "pipeline. Never trains non-dry-run. Never mutates production "
            "models. Prints a suggested staging warm-up command for the "
            "operator to run manually."
        )
    )
    p.add_argument(
        "--output-root",
        default=str(Path.home() / "chess_results"),
        help="Parent dir for the timestamped pipeline_run_<ts>/ run root.",
    )
    p.add_argument(
        "--runtime-dir",
        default="",
        help=(
            "Optional HACKME_RUNTIME_DIR for the PvP export stage. "
            "Skipped if empty."
        ),
    )
    p.add_argument(
        "--since",
        default="",
        help="PvP export --since YYYY-MM-DD filter; empty = no filter.",
    )
    p.add_argument(
        "--exp4-model-path",
        default="",
        help="exp4 PV JSON to use for sparring. Skipped if empty.",
    )
    p.add_argument(
        "--exp5-model-path",
        default="",
        help="exp5 NNUE JSON to use for sparring. Skipped if empty.",
    )
    p.add_argument(
        "--sparring-mode",
        default="smoke",
        help="chess_exp4_vs_exp5_sparring --mode (default smoke).",
    )
    p.add_argument(
        "--sparring-max-plies",
        type=int,
        default=40,
        help="chess_exp4_vs_exp5_sparring --max-plies (default 40).",
    )
    p.add_argument(
        "--train-exp5-in-suggestion",
        action="store_true",
        help=(
            "Include --experiment-5-model-path in the suggested staging "
            "warm-up command (default skipped to protect production NNUE)."
        ),
    )
    return p.parse_args()


def main() -> int:
    args = parse_args()
    result = run_pipeline(args)
    print()
    print(f"=== pipeline run :: {result['run_root']} ===")
    for s in result["stages"]:
        status = s.get("status", "?")
        print(f"  [{s.get('stage')}] {status}", end="")
        if status == "ok":
            for key in ("run_dir", "summary_path", "pipeline_summary_md"):
                if s.get(key):
                    print(f" :: {key}={s[key]}", end="")
        elif s.get("reason"):
            print(f" :: {s['reason']}", end="")
        elif s.get("exit_code") is not None:
            print(f" :: exit_code={s['exit_code']}", end="")
        print()
    print()
    print("=== suggested next step (NOT executed) ===")
    print(result["suggested_staging_command"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
