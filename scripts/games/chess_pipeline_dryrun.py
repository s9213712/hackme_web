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

from services.games.chess import history_move_to_uci  # noqa: E402
from services.games.external_replay_safety import serialize_json_payload  # noqa: E402
import chess  # noqa: E402

PGN_CONVERTER = REPO_ROOT / "scripts" / "games" / "chess_pgn_to_replay.py"
PVP_CONVERTER = REPO_ROOT / "scripts" / "games" / "chess_pvp_history_to_replay.py"
SPARRING_RUNNER = REPO_ROOT / "scripts" / "games" / "chess_exp4_vs_exp5_sparring.py"
SPARRING_HARVESTER = REPO_ROOT / "scripts" / "games" / "chess_sparring_to_replay.py"
PGN_TEACHER_AUDIT = REPO_ROOT / "scripts" / "games" / "chess_imported_replay_teacher_audit.py"
SEED_TRAIN = REPO_ROOT / "scripts" / "games" / "chess_seed_train.py"
AGGREGATOR = REPO_ROOT / "scripts" / "games" / "chess_pipeline_report.py"


# Default scoring for PGN-derived samples. weight=0.5 sits between
# pvp_filtered (0.15) and unclamped trust (1.0); the W4 seed_train cap for
# trusted_source='imported_dataset' is 200 samples per warm-up run.
_PGN_DEFAULT_WEIGHT = 0.5


def _now_dirname() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S_%fZ")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


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


def _expand_game_level_to_per_ply(
    game_level_jsonl: Path,
    output_jsonl: Path,
    *,
    weight: float = _PGN_DEFAULT_WEIGHT,
) -> tuple[int, int]:
    """Expand chess_pgn_to_replay's game-level JSONL → canonical per-ply replay.

    For each decisive game (winner_color ∈ {white, black}), replay the
    move_history via python-chess and emit ONE replay sample per winner-side
    ply. Loser-side moves and draws are skipped to mirror
    [[feedback-pvp-replay-discipline]] (winner-side only when no teacher
    audit is wired in yet). Each emitted sample carries
    ``trusted_source='imported_dataset'`` (already in the W4 whitelist) and
    ``label_quality='clean'`` so chess_seed_train's normalize_validation
    accepts the row and the operator can tell at a glance where it came from.

    Returns (games_processed, samples_emitted).
    """
    games_processed = 0
    samples_emitted = 0
    output_jsonl.parent.mkdir(parents=True, exist_ok=True)
    with output_jsonl.open("w", encoding="utf-8") as out_fh:
        for raw in game_level_jsonl.read_text(encoding="utf-8").splitlines():
            raw = raw.strip()
            if not raw:
                continue
            try:
                rec = json.loads(raw)
            except Exception:
                continue
            games_processed += 1
            winner_color = str(rec.get("winner_color") or "")
            if winner_color not in {"white", "black"}:
                continue
            move_history = rec.get("move_history") or []
            if not isinstance(move_history, list) or not move_history:
                continue
            board = chess.Board()
            replay_id = str(rec.get("replay_id") or "")
            for ply_index, entry in enumerate(move_history):
                if not isinstance(entry, dict):
                    break
                try:
                    uci = history_move_to_uci(entry)
                    move = chess.Move.from_uci(uci)
                except Exception:
                    break
                if move not in board.legal_moves:
                    break
                side = "white" if board.turn == chess.WHITE else "black"
                fen_before = board.fen()
                if side == winner_color:
                    # Raw PGN-derived rows are diagnostic candidates, not
                    # training-safe. W8 commit 1's audit gate is what marks
                    # them training_eligible after teacher agreement; until
                    # then the row must look obviously *unaudited* so an
                    # operator who manually peeks at this JSONL cannot
                    # mistake it for a clean import.
                    sample = {
                        "fen": fen_before,
                        "move_uci": uci,
                        "side": side,
                        "target": 1.0,
                        "weight": float(weight),
                        "source": "imported_dataset",
                        "trusted_source": "imported_dataset",
                        "label_quality": "review",
                        "training_eligible": False,
                        "source_id": f"pgn:{replay_id or 'unknown'}:ply:{ply_index}",
                        "result_backed": True,
                        "teacher_audit_status": "not_run",
                        "winner_color": winner_color,
                    }
                    out_fh.write(json.dumps(sample, sort_keys=True) + "\n")
                    samples_emitted += 1
                board.push(move)
    return games_processed, samples_emitted


def run_pgn_input_stage(
    *,
    pgn_paths: list[str],
    prepared_jsonls: list[str],
    output_root: Path,
    log_dir: Path,
    weight: float = _PGN_DEFAULT_WEIGHT,
    pgn_source_urls: list[str] | None = None,
    pgn_download_dir: str = "",
    pgn_refresh_downloads: bool = False,
) -> dict:
    """Stage 00: convert PGN sources to canonical per-ply replay JSONL.

    Three parallel input lanes:
      * ``--pgn-path``: raw local PGN(s) → chess_pgn_to_replay → game-level
        JSONL → expand to per-ply via :func:`_expand_game_level_to_per_ply`.
      * ``--pgn-source-url`` (W9): remote PGN/archive URL → downloaded into
        ``--pgn-download-dir`` (or chess_pgn_to_replay's default cache) →
        same conversion + expansion pipeline. Each URL gets its own
        ``pgn_url_<i>`` subdir. ``policy.raw_internet_download`` flips to
        True for the run when any URL is given so the aggregator can
        surface the network event as a cross-stage invariant.
      * ``--prepared-replay-jsonl``: already-canonical per-ply JSONL,
        passed straight through; the seed_train normalize_validation
        step is the bouncer.

    Whether the input is a local file or a downloaded URL, the row still
    leaves stage 00 stamped ``training_eligible=False`` /
    ``label_quality='review'`` — stage 00b's teacher audit is the only
    gate that can produce training-safe rows.
    """
    url_list = list(pgn_source_urls or [])
    if not pgn_paths and not prepared_jsonls and not url_list:
        return {
            "stage": "pgn_to_replay",
            "status": "skipped",
            "reason": "no --pgn-path / --pgn-source-url / --prepared-replay-jsonl",
        }
    output_root.mkdir(parents=True, exist_ok=True)
    output_jsonls: list[str] = []
    games_imported = 0
    samples_emitted = 0

    def _convert(
        sub_dir: Path,
        *,
        cmd_args: list[str],
        log_name: str,
    ) -> tuple[int, int] | None:
        sub_dir.mkdir(parents=True, exist_ok=True)
        game_level = sub_dir / "pgn_game_level.jsonl"
        cmd = [sys.executable, str(PGN_CONVERTER), *cmd_args,
               "--output-jsonl", str(game_level),
               "--replace-output", "--allow-empty-output"]
        rc = _run_subprocess(cmd, label=log_name, log_file=log_dir / f"{log_name}.log")
        if rc != 0:
            return None
        if not game_level.exists():
            return (0, 0)
        per_ply = sub_dir / "pgn_per_ply_replay.jsonl"
        g, s = _expand_game_level_to_per_ply(game_level, per_ply, weight=weight)
        if s > 0:
            output_jsonls.append(str(per_ply))
        return g, s

    for i, pgn_path in enumerate(pgn_paths):
        result = _convert(
            output_root / f"pgn_path_{i:02d}",
            cmd_args=["--input-pgn", pgn_path],
            log_name=f"00_pgn_to_replay_path_{i:02d}",
        )
        if result is None:
            return {
                "stage": "pgn_to_replay",
                "status": "failed",
                "exit_code": 1,
                "log": str(log_dir / f"00_pgn_to_replay_path_{i:02d}.log"),
            }
        g, s = result
        games_imported += g
        samples_emitted += s

    for i, url in enumerate(url_list):
        cmd_args = ["--source-url", url]
        if pgn_download_dir:
            cmd_args.extend(["--download-dir", pgn_download_dir])
        if pgn_refresh_downloads:
            cmd_args.append("--refresh-downloads")
        result = _convert(
            output_root / f"pgn_url_{i:02d}",
            cmd_args=cmd_args,
            log_name=f"00_pgn_to_replay_url_{i:02d}",
        )
        if result is None:
            return {
                "stage": "pgn_to_replay",
                "status": "failed",
                "exit_code": 1,
                "log": str(log_dir / f"00_pgn_to_replay_url_{i:02d}.log"),
            }
        g, s = result
        games_imported += g
        samples_emitted += s

    prepared_attached: list[str] = []
    for p in prepared_jsonls:
        path = Path(p).expanduser()
        if path.exists():
            output_jsonls.append(str(path))
            prepared_attached.append(str(path))

    network_download_used = bool(url_list)
    summary = {
        "stage": "pgn_to_replay",
        "timestamp": _now_iso(),
        "output_dir": str(output_root),
        "input_pgn_paths": list(pgn_paths),
        "input_source_urls": url_list,
        "download_dir": pgn_download_dir or "",
        "refresh_downloads": bool(pgn_refresh_downloads),
        "prepared_replay_jsonls": prepared_attached,
        "output_jsonls": output_jsonls,
        "counts": {
            "pgn_paths_processed": len(pgn_paths),
            "source_urls_processed": len(url_list),
            "prepared_jsonls_attached": len(prepared_attached),
            "games_imported": games_imported,
            "per_ply_samples_emitted": samples_emitted,
        },
        "policy": {
            "diagnostic_only": True,
            "production_runtime_mutation": False,
            "raw_internet_download": network_download_used,
            "audit_gate_required": True,
        },
    }
    summary_path = output_root / "summary.json"
    summary_path.write_text(serialize_json_payload(summary), encoding="utf-8")
    return {
        "stage": "pgn_to_replay",
        "status": "ok",
        "summary_path": str(summary_path),
        "output_jsonls": output_jsonls,
        "games_imported": games_imported,
        "samples_emitted": samples_emitted,
    }


def run_pgn_teacher_audit_stage(
    *,
    raw_jsonls: list[str],
    output_dir: Path,
    log_dir: Path,
    exp4_model_path: str,
    exp5_model_path: str,
    audit_profile: str,
    top_k: int,
) -> dict:
    """Stage 00b (W8): teacher-audit the raw PGN per-ply JSONLs.

    Wraps ``chess_imported_replay_teacher_audit.py``. Only the
    ``accepted_replay.jsonl`` produced here is fed into stage 4
    (``seed_train --dry-run``) by default — raw PGN-derived rows from
    stage 00 are diagnostic only and would fail the seed_train
    normalize_validation step if loaded directly because they are
    stamped ``training_eligible=False`` and the validator wouldn't
    re-stamp them.
    """
    if not raw_jsonls:
        return {
            "stage": "pgn_teacher_audit",
            "status": "skipped",
            "reason": "no raw pgn jsonls upstream",
        }
    real_jsonls = [p for p in raw_jsonls if p and Path(p).exists()]
    if not real_jsonls:
        return {
            "stage": "pgn_teacher_audit",
            "status": "skipped",
            "reason": "upstream raw jsonls missing on disk",
        }
    output_dir.mkdir(parents=True, exist_ok=True)
    cmd = [
        sys.executable,
        str(PGN_TEACHER_AUDIT),
        "--output-dir",
        str(output_dir),
        "--audit-profile",
        audit_profile,
        "--top-k",
        str(top_k),
    ]
    if exp4_model_path:
        cmd.extend(["--exp4-model-path", exp4_model_path])
    if exp5_model_path:
        cmd.extend(["--exp5-model-path", exp5_model_path])
    for jsonl in real_jsonls:
        cmd.extend(["--input-jsonl", jsonl])
    log = log_dir / "00b_pgn_teacher_audit.log"
    rc = _run_subprocess(cmd, label="pgn_teacher_audit", log_file=log)
    if rc != 0:
        return {
            "stage": "pgn_teacher_audit",
            "status": "failed",
            "exit_code": rc,
            "log": str(log),
        }
    accepted = output_dir / "accepted_replay.jsonl"
    return {
        "stage": "pgn_teacher_audit",
        "status": "ok",
        "summary_path": str(output_dir / "summary.json"),
        "accepted_jsonl": str(accepted) if accepted.exists() else "",
        "log": str(log),
    }


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
    # chess_seed_train prints JSON payload to stdout and progress to stderr.
    # Capture them SEPARATELY so the JSON parse below doesn't choke on
    # progress lines (the original bug was stderr=STDOUT — fixed now).
    proc = subprocess.run(
        cmd,
        env=os.environ.copy(),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    with log.open("w", encoding="utf-8") as fh:
        fh.write("# seed_train_dryrun\n# cmd: " + " ".join(shlex.quote(c) for c in cmd) + "\n\n")
        fh.write("# stderr (progress):\n")
        fh.write(proc.stderr or "")
        fh.write("\n# stdout (JSON payload):\n")
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

    # Stage 00: PGN / prepared replay input (W7) + optional URL download (W9)
    pgn_input = run_pgn_input_stage(
        pgn_paths=list(args.pgn_path or []),
        prepared_jsonls=list(args.prepared_replay_jsonl or []),
        output_root=run_root / "00_pgn_input",
        log_dir=log_dir,
        pgn_source_urls=list(args.pgn_source_url or []),
        pgn_download_dir=str(args.pgn_download_dir or ""),
        pgn_refresh_downloads=bool(args.pgn_refresh_downloads),
    )
    stages.append(pgn_input)

    # Stage 00b (W8): teacher-audit raw PGN-derived rows. Skipped by
    # --pgn-skip-audit; otherwise runs whenever stage 00 emitted raw JSONLs.
    raw_pgn_jsonls = list(pgn_input.get("output_jsonls") or [])
    pgn_audit: dict = {
        "stage": "pgn_teacher_audit",
        "status": "skipped",
        "reason": "no upstream pgn output",
    }
    if raw_pgn_jsonls and not args.pgn_skip_audit:
        pgn_audit = run_pgn_teacher_audit_stage(
            raw_jsonls=raw_pgn_jsonls,
            output_dir=run_root / "00b_pgn_teacher_audit",
            log_dir=log_dir,
            exp4_model_path=str(
                args.pgn_audit_exp4_model_path or args.exp4_model_path or ""
            ),
            exp5_model_path=str(
                args.pgn_audit_exp5_model_path or args.exp5_model_path or ""
            ),
            audit_profile=str(args.pgn_audit_profile or "strict"),
            top_k=int(args.pgn_audit_top_k or 3),
        )
    elif raw_pgn_jsonls and args.pgn_skip_audit:
        pgn_audit = {
            "stage": "pgn_teacher_audit",
            "status": "skipped",
            "reason": "--pgn-skip-audit opted out (raw PGN diagnostic only)",
        }
    stages.append(pgn_audit)

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

    # Stage 4: seed_train dry-run with whatever replay JSONLs we have.
    # By default we feed only the audit-accepted PGN stream + the safe
    # PvP / sparring streams. Raw PGN output is diagnostic only and is
    # included only when the operator passes --include-unaudited-pgn-in-
    # dryrun-diagnostic. That flag is explicit and the aggregator records
    # the resulting "unaudited_imported_dataset_used_for_seed_train"
    # invariant for downstream review.
    audit_accepted = pgn_audit.get("accepted_jsonl") or ""
    pgn_stream: list[str] = []
    if audit_accepted:
        pgn_stream.append(audit_accepted)
    if args.include_unaudited_pgn_in_dryrun_diagnostic:
        pgn_stream.extend(raw_pgn_jsonls)
    include_jsonls = (
        pgn_stream
        + [pvp.get("training_eligible_jsonl") or ""]
        + [sparring_to_replay.get("training_eligible_jsonl") or ""]
    )
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
        "--pgn-path",
        action="append",
        default=[],
        help=(
            "Local PGN file. Repeatable. The orchestrator runs "
            "chess_pgn_to_replay on each path, then expands the game-level "
            "JSONL to canonical per-ply replay samples "
            "(winner-side only, trusted_source='imported_dataset')."
        ),
    )
    p.add_argument(
        "--prepared-replay-jsonl",
        action="append",
        default=[],
        help=(
            "Pre-prepared canonical per-ply replay JSONL. Repeatable. "
            "Passed straight through to stage 4 (seed_train --dry-run) "
            "without re-conversion."
        ),
    )
    p.add_argument(
        "--pgn-source-url",
        action="append",
        default=[],
        help=(
            "W9: PGN/ZIP/GZ/BZ2 URL to download into the local cache and "
            "process the same way as --pgn-path. Repeatable. The "
            "downloaded content still flows through stage 00b teacher "
            "audit before reaching seed_train; only audited rows become "
            "training-safe."
        ),
    )
    p.add_argument(
        "--pgn-download-dir",
        default="",
        help=(
            "Local cache directory for --pgn-source-url downloads. "
            "Empty defaults to chess_pgn_to_replay's "
            "~/chess_results/pgn_sources/."
        ),
    )
    p.add_argument(
        "--pgn-refresh-downloads",
        action="store_true",
        help="Force re-download even if the URL is already cached locally.",
    )
    p.add_argument(
        "--pgn-skip-audit",
        action="store_true",
        help=(
            "W8 opt-out: skip the teacher-audit stage 00b. Raw PGN-derived "
            "rows will NOT be fed into stage 4 unless you also pass "
            "--include-unaudited-pgn-in-dryrun-diagnostic."
        ),
    )
    p.add_argument(
        "--pgn-audit-profile",
        default="strict",
        choices=["strict", "very_strict", "diagnostic"],
        help=(
            "Audit profile for stage 00b. strict (default): accept if "
            "candidate is top-K of either exp4 or exp5; very_strict: "
            "require both; diagnostic: classify only, never accept."
        ),
    )
    p.add_argument("--pgn-audit-top-k", type=int, default=3)
    p.add_argument(
        "--pgn-audit-exp4-model-path",
        default="",
        help="Optional exp4 PV model path used only by the audit stage.",
    )
    p.add_argument(
        "--pgn-audit-exp5-model-path",
        default="",
        help="Optional exp5 NNUE model path used only by the audit stage.",
    )
    p.add_argument(
        "--include-unaudited-pgn-in-dryrun-diagnostic",
        action="store_true",
        help=(
            "W8 explicit unsafe-override: also feed RAW PGN-derived JSONLs "
            "into stage 4 dry-run. Marked in the aggregator's invariants "
            "block as unaudited_imported_dataset_used_for_seed_train=True. "
            "Never use this for a staging warm-up command."
        ),
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
