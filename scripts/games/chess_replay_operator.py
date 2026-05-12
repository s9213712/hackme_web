#!/usr/bin/env python3
"""Operator UX wrapper for the W4.2-hardened replay pipeline.

Subcommands:

  detect                       Show resolved runtime / DB paths + table check.
  export                       Run chess_pvp_history_to_replay (writes JSONLs).
  dry-run                      Run chess_seed_train --dry-run on a run dir.
  review                       Browse rejected.jsonl grouped by reason.
  generate-staging-command     Emit the safe non-dry-run command (NOT executed).
  wizard                       Interactive menu chaining the above.

W5 is operator UX only:
  * does not add new training logic
  * does not auto-train
  * does not open the main DB read-write
  * does not write models — only `generate-staging-command` produces a string,
    leaving execution to the operator

The safety contract (services/games/external_replay_safety) is unchanged;
this CLI just makes the pipeline easier to drive without typing every flag.
"""
from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import sys
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

CONVERTER_PATH = REPO_ROOT / "scripts" / "games" / "chess_pvp_history_to_replay.py"
SEED_TRAIN_PATH = REPO_ROOT / "scripts" / "games" / "chess_seed_train.py"


# ---- runtime detection -------------------------------------------------


def detect_runtime(env: dict | None = None) -> dict:
    """Resolve the same paths the converter would use, plus DB sanity flags.

    Mirrors server.py:248-263 conventions and the converter's
    ``_resolve_db_path`` resolver so the wizard surfaces exactly the DB the
    next ``export`` subcommand would touch.
    """
    env = env if env is not None else os.environ
    runtime_dir = (env.get("HACKME_RUNTIME_DIR") or "").strip()
    db_dir_env = (env.get("HTML_LEARNING_DB_DIR") or "").strip()
    if db_dir_env:
        db_path = Path(db_dir_env).expanduser().resolve() / "database.db"
        db_source = "HTML_LEARNING_DB_DIR"
    elif runtime_dir:
        db_path = Path(runtime_dir).expanduser().resolve() / "database" / "database.db"
        db_source = "HACKME_RUNTIME_DIR/database/database.db"
    else:
        db_path = None
        db_source = "(none — set HACKME_RUNTIME_DIR or HTML_LEARNING_DB_DIR)"
    db_exists = bool(db_path and db_path.exists())
    has_game_matches = False
    if db_exists:
        try:
            uri = f"file:{db_path.as_posix()}?mode=ro"
            conn = sqlite3.connect(uri, uri=True)
            try:
                row = conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name='game_matches'"
                ).fetchone()
                has_game_matches = bool(row)
            finally:
                conn.close()
        except Exception:
            has_game_matches = False
    return {
        "runtime_dir": runtime_dir,
        "db_dir_env": db_dir_env,
        "db_path": str(db_path) if db_path else "",
        "db_source": db_source,
        "db_exists": db_exists,
        "has_game_matches": has_game_matches,
    }


# ---- artifact parsers --------------------------------------------------


def parse_converter_summary(summary_path: Path) -> dict:
    """Slim view of the converter's summary.json for operator display."""
    data = json.loads(Path(summary_path).read_text(encoding="utf-8"))
    counts = dict(data.get("counts") or {})
    quality = dict(data.get("quality_signal") or {})
    filter_cfg = dict(data.get("filter_config") or {})
    return {
        "timestamp": data.get("timestamp", ""),
        "output_dir": data.get("output_dir", ""),
        "matches_total": counts.get("matches_total", 0),
        "matches_accepted_pvp_filtered": counts.get("matches_accepted_pvp_filtered", 0),
        "matches_accepted_human_beat_engine": counts.get(
            "matches_accepted_human_beat_engine", 0
        ),
        "matches_rejected": counts.get("matches_rejected", 0),
        "samples_pvp_filtered": counts.get("samples_pvp_filtered", 0),
        "samples_human_beat_engine": counts.get("samples_human_beat_engine", 0),
        "reject_reasons": dict(counts.get("reject_reasons") or {}),
        "hve_whitelist": filter_cfg.get("hve_difficulty_whitelist"),
        "quality_union_size": quality.get("union_size", 0),
    }


def parse_dry_run_payload(payload: dict | str | Path) -> dict:
    """Reduce the seed_train dry-run payload to PASS/FAIL + key metrics.

    The PASS contract here mirrors the verbal acceptance criteria the
    operator should be checking:

      - dry_run is True
      - rows_kept > 0 (the JSONL actually had usable rows)
      - total_kept > 0 (caps did not zero everything out)
      - both engines' normalize_failed == 0
      - train_result.skipped_reason == "dry_run"
      - dry_run_artifact exists on disk
    """
    if isinstance(payload, dict):
        p = payload
    else:
        p = json.loads(Path(payload).read_text(encoding="utf-8"))
    er = dict(p.get("external_replay") or {})
    nv = dict(er.get("normalize_validation") or {})
    train = dict(er.get("train_result") or {})
    rows_kept = int((er.get("load_stats") or {}).get("rows_kept") or 0)
    total_kept = int((er.get("cap_stats") or {}).get("total_kept") or 0)
    exp4_failed = int(nv.get("exp4_failed") or 0)
    exp5_failed = int(nv.get("exp5_failed") or 0)
    artifact = str(p.get("dry_run_artifact") or "")
    artifact_exists = bool(artifact) and Path(artifact).exists()
    checks = [
        p.get("dry_run") is True,
        rows_kept > 0,
        total_kept > 0,
        exp4_failed == 0,
        exp5_failed == 0,
        train.get("skipped_reason") == "dry_run",
        artifact_exists,
    ]
    return {
        "status": "PASS" if all(checks) else "FAIL",
        "rows_kept": rows_kept,
        "total_kept": total_kept,
        "exp4_ok": int(nv.get("exp4_ok") or 0),
        "exp4_failed": exp4_failed,
        "exp5_ok": int(nv.get("exp5_ok") or 0),
        "exp5_failed": exp5_failed,
        "exp4_failed_samples": list(nv.get("exp4_failed_samples") or []),
        "exp5_failed_samples": list(nv.get("exp5_failed_samples") or []),
        "train_skipped_reason": str(train.get("skipped_reason") or ""),
        "dry_run_artifact": artifact,
        "artifact_exists": artifact_exists,
    }


def group_rejected_by_reason(rejected_path: Path) -> dict[str, list[dict]]:
    """Read rejected.jsonl + bucket rows by ``rejection_reason``."""
    by_reason: dict[str, list[dict]] = {}
    p = Path(rejected_path)
    if not p.exists():
        return {}
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except Exception:
            continue
        reason = str(row.get("rejection_reason") or "(unknown)")
        by_reason.setdefault(reason, []).append(row)
    return by_reason


# ---- rejection-reason explanations -------------------------------------


_REJECTION_EXPLANATIONS = {
    "no_winner_or_drawn": "Draw or no winner recorded; no winner-side moves to collect.",
    "not_finished": "Game status is not 'finished'.",
    "missing_player_id": "white_user_id or black_user_id is NULL.",
    "winner_user_id_not_in_match_players": (
        "winner_user_id does not match either player in this match."
    ),
    "missing_human_id_in_computer_mode": (
        "mode='computer' but white_user_id is NULL (no human player)."
    ),
    "computer_won_or_not_human_winner": (
        "mode='computer' but winner is not the human player "
        "(computer won, or winner mismatch)."
    ),
}


def explain_rejection_reason(reason: str) -> str:
    """Translate a converter reason code into one human-readable sentence."""
    reason = str(reason or "")
    if reason in _REJECTION_EXPLANATIONS:
        return _REJECTION_EXPLANATIONS[reason]
    if reason.startswith("too_short:"):
        plies = reason.split(":", 1)[1]
        return f"Game had only {plies} plies (below --min-plies threshold)."
    if reason.startswith("non_target_engine:"):
        diff = reason.split(":", 1)[1]
        return (
            f"Computer opponent was '{diff}', not in --hve-difficulties whitelist "
            f"(default 'experiment 4:pv,experiment 5:nnue')."
        )
    if reason.startswith("non_normal_end:"):
        sub = reason.split(":", 1)[1] or "(unknown)"
        return f"Game ended abnormally via '{sub}'; signal not reliable."
    if reason.startswith("no_player_quality:"):
        side = reason.split(":", 1)[1] or "(unspecified)"
        return (
            f"{side} player has no top-30% leaderboard signal "
            "in the last 4 weeks."
        )
    if reason.startswith("move_history_json_invalid:"):
        return "move_history_json could not be parsed; data may be corrupted."
    if reason.startswith("reconstruction_error:"):
        return (
            "move_history failed to replay legally via python-chess; "
            "investigate for corrupted moves."
        )
    return f"(no explanation registered for reason code: {reason})"


# ---- staging command generator -----------------------------------------


def generate_staging_command(
    *,
    run_dir: Path,
    candidate_dir: Path,
    preset: str = "warmup10",
    skip_exp5: bool = True,
    train_exp5: bool = False,
) -> str:
    """Compose the safe non-dry-run chess_seed_train command.

    Safe defaults:
      * uses an explicit candidate path under ``candidate_dir`` (must be
        outside ``services/games/models/`` and the runtime defaults, or the
        W4.2 safety guard will reject the run);
      * defaults to ``--skip-exp5`` so the production-promoted exp5 NNUE
        cannot be touched without the operator explicitly passing
        ``--train-exp5`` to this generator;
      * never executes the command — only returns the string for the
        operator to copy/paste after review.
    """
    eligible = Path(run_dir).expanduser().resolve() / "pvp_replay_training_eligible.jsonl"
    pv_candidate = Path(candidate_dir).expanduser().resolve() / "chess_experiment_4_pv_candidate.json"
    parts: list[str] = [
        sys.executable,
        str(SEED_TRAIN_PATH),
        "--preset",
        preset,
        "--include-replay-jsonl",
        str(eligible),
        "--experiment-4-model-path",
        str(pv_candidate),
    ]
    if skip_exp5 and not train_exp5:
        parts.append("--skip-exp5")
    elif train_exp5:
        nnue_candidate = Path(candidate_dir).expanduser().resolve() / "chess_experiment_5_nnue_candidate.json"
        parts.extend(["--experiment-5-model-path", str(nnue_candidate)])
    return " ".join(shlex.quote(str(x)) for x in parts)


# ---- subcommand handlers -----------------------------------------------


def _print_section(name: str, body: list[str]) -> None:
    print(f"[{name}]")
    for line in body:
        print(f"  {line}")


def cmd_detect(args: argparse.Namespace) -> int:
    info = detect_runtime()
    _print_section(
        "runtime",
        [
            f"HACKME_RUNTIME_DIR: {info['runtime_dir'] or '(unset)'}",
            f"HTML_LEARNING_DB_DIR: {info['db_dir_env'] or '(unset)'}",
            f"resolved DB path: {info['db_path'] or '(no DB resolvable)'}",
            f"DB source: {info['db_source']}",
            f"DB exists: {info['db_exists']}",
            f"game_matches table present: {info['has_game_matches']}",
        ],
    )
    return 0 if (info["db_exists"] and info["has_game_matches"]) else 2


def cmd_export(args: argparse.Namespace) -> int:
    cli: list[str] = [sys.executable, str(CONVERTER_PATH)]
    if args.since:
        cli.extend(["--since", args.since])
    if args.output_root:
        cli.extend(["--output-root", args.output_root])
    if args.min_plies:
        cli.extend(["--min-plies", str(args.min_plies)])
    if args.quality_weeks:
        cli.extend(["--quality-weeks", str(args.quality_weeks)])
    if args.quality_top_pct:
        cli.extend(["--quality-top-pct", str(args.quality_top_pct)])
    if args.hve_difficulties is not None:
        cli.extend(["--hve-difficulties", args.hve_difficulties])
    proc = subprocess.run(cli, env=os.environ.copy())
    if proc.returncode != 0:
        return proc.returncode

    out_root = Path(args.output_root or Path.home() / "chess_results").expanduser().resolve()
    runs = sorted(out_root.glob("pvp_replay_*"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not runs:
        print(
            f"WARN: export ran but no pvp_replay_* dir found under {out_root}",
            file=sys.stderr,
        )
        return 0
    run_dir = runs[0]
    summary = parse_converter_summary(run_dir / "summary.json")
    print()
    print(f"=== export summary :: {run_dir} ===")
    _print_section(
        "counts",
        [
            f"matches_total: {summary['matches_total']}",
            f"accepted (pvp_filtered): {summary['matches_accepted_pvp_filtered']}",
            f"accepted (human_beat_engine): {summary['matches_accepted_human_beat_engine']}",
            f"rejected: {summary['matches_rejected']}",
            f"samples_pvp_filtered: {summary['samples_pvp_filtered']}",
            f"samples_human_beat_engine: {summary['samples_human_beat_engine']}",
            f"quality_signal.union_size: {summary['quality_union_size']}",
            f"hve_difficulty_whitelist: {summary['hve_whitelist']}",
        ],
    )
    if summary["reject_reasons"]:
        _print_section(
            "reject_reasons",
            [f"{k}: {v}" for k, v in sorted(summary["reject_reasons"].items())],
        )
    _print_section(
        "next",
        [
            f"chess_replay_operator.py dry-run --run-dir {run_dir}",
            f"chess_replay_operator.py review  --run-dir {run_dir}",
        ],
    )
    return 0


def cmd_dry_run(args: argparse.Namespace) -> int:
    run_dir = Path(args.run_dir).expanduser().resolve()
    eligible = run_dir / "pvp_replay_training_eligible.jsonl"
    if not eligible.exists():
        print(f"error: {eligible} not found", file=sys.stderr)
        return 2
    cli = [
        sys.executable,
        str(SEED_TRAIN_PATH),
        "--preset",
        args.preset or "warmup10",
        "--include-replay-jsonl",
        str(eligible),
        "--dry-run",
    ]
    if args.report_dir:
        cli.extend(["--report-dir", args.report_dir])
    proc = subprocess.run(cli, env=os.environ.copy(), capture_output=True, text=True)
    if proc.returncode != 0:
        sys.stderr.write(proc.stderr)
        return proc.returncode
    try:
        payload = json.loads(proc.stdout)
    except Exception as exc:
        print(f"error: could not parse seed_train stdout as JSON: {exc!r}", file=sys.stderr)
        sys.stderr.write(proc.stdout[:2000])
        return 2
    result = parse_dry_run_payload(payload)
    print()
    print(f"=== dry-run validation :: {result['status']} ===")
    _print_section(
        "rows",
        [
            f"rows_kept: {result['rows_kept']}",
            f"total_kept (after caps): {result['total_kept']}",
        ],
    )
    _print_section(
        "normalize",
        [
            f"exp4: {result['exp4_ok']} ok / {result['exp4_failed']} failed",
            f"exp5: {result['exp5_ok']} ok / {result['exp5_failed']} failed",
        ],
    )
    if result["exp4_failed_samples"] or result["exp5_failed_samples"]:
        _print_section(
            "first failed source_ids",
            [
                *(f"exp4: {s}" for s in result["exp4_failed_samples"][:5]),
                *(f"exp5: {s}" for s in result["exp5_failed_samples"][:5]),
            ],
        )
    _print_section(
        "training",
        [f"skipped_reason: {result['train_skipped_reason']}"],
    )
    _print_section(
        "artifact",
        [
            result["dry_run_artifact"] or "(none)",
            f"exists: {result['artifact_exists']}",
        ],
    )
    if result["status"] == "PASS":
        _print_section(
            "next",
            [
                "chess_replay_operator.py generate-staging-command "
                f"--run-dir {run_dir} --candidate-dir <staging-dir>",
            ],
        )
    else:
        _print_section(
            "next",
            [
                "DO NOT run staging warm-up until normalize failures are 0 and "
                "the dry-run artifact is present.",
            ],
        )
    return 0 if result["status"] == "PASS" else 1


def cmd_review(args: argparse.Namespace) -> int:
    run_dir = Path(args.run_dir).expanduser().resolve()
    rejected = run_dir / "pvp_replay_rejected.jsonl"
    by_reason = group_rejected_by_reason(rejected)
    if not by_reason:
        print(f"no rejections under {rejected}")
        return 0
    keys = sorted(by_reason.keys(), key=lambda k: -len(by_reason[k]))
    print()
    print(f"=== rejected reasons under {run_dir} ===")
    for i, k in enumerate(keys, start=1):
        print(f"  [{i}] {k}: {len(by_reason[k])}")
    if args.reason:
        focus = [args.reason] if args.reason in by_reason else []
        if not focus:
            print(f"\nno rejected rows under reason '{args.reason}'", file=sys.stderr)
            return 2
    elif args.all:
        focus = list(keys)
    else:
        try:
            choice = input("\nChoose reason number to inspect (or blank to exit): ").strip()
        except EOFError:
            choice = ""
        if not choice:
            return 0
        try:
            idx = int(choice)
        except ValueError:
            print("invalid choice", file=sys.stderr)
            return 2
        if not (1 <= idx <= len(keys)):
            print("invalid choice", file=sys.stderr)
            return 2
        focus = [keys[idx - 1]]

    for reason in focus:
        rows = by_reason.get(reason, [])
        explanation = explain_rejection_reason(reason)
        print()
        print(f"--- {reason} ({len(rows)} matches) ---")
        print(f"meaning: {explanation}")
        for row in rows[: args.limit]:
            print(
                f"  match_id={row.get('match_id')} "
                f"mode={row.get('mode')} "
                f"plies={row.get('plies')} "
                f"finished_at={row.get('finished_at')}"
            )
        if len(rows) > args.limit:
            print(f"  ... ({len(rows) - args.limit} more)")
    return 0


def cmd_generate_staging_command(args: argparse.Namespace) -> int:
    run_dir = Path(args.run_dir).expanduser().resolve()
    candidate_dir = Path(args.candidate_dir).expanduser().resolve()
    cmd_str = generate_staging_command(
        run_dir=run_dir,
        candidate_dir=candidate_dir,
        preset=args.preset or "warmup10",
        skip_exp5=not args.train_exp5,
        train_exp5=bool(args.train_exp5),
    )
    print()
    print("=== staging warm-up command (NOT executed) ===")
    print(cmd_str)
    _print_section(
        "notes",
        [
            "Trains a staging candidate only — does not write bundled or runtime-default models.",
            (
                "exp5 NNUE is skipped by default; pass --train-exp5 to generate a "
                "command that ALSO writes an exp5 staging candidate."
            ),
            "Inspect the dry-run JSON artifact before running this command.",
        ],
    )
    return 0


# ---- wizard ------------------------------------------------------------


def _prompt(message: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    try:
        raw = input(f"{message}{suffix}: ").strip()
    except EOFError:
        raw = ""
    return raw or default


def _wizard_export() -> int:
    info = detect_runtime()
    if not info["db_exists"]:
        print("DB not found — set HACKME_RUNTIME_DIR or HTML_LEARNING_DB_DIR first.")
        return 2
    since = _prompt("Since date (YYYY-MM-DD)", "2026-04-01")
    return cmd_export(
        argparse.Namespace(
            since=since,
            output_root="",
            min_plies=0,
            quality_weeks=0,
            quality_top_pct=0,
            hve_difficulties=None,
        )
    )


def _wizard_dry_run() -> int:
    run_dir = _prompt("Run dir (pvp_replay_*)")
    if not run_dir:
        return 0
    return cmd_dry_run(
        argparse.Namespace(run_dir=run_dir, preset="warmup10", report_dir="")
    )


def _wizard_review() -> int:
    run_dir = _prompt("Run dir (pvp_replay_*)")
    if not run_dir:
        return 0
    return cmd_review(
        argparse.Namespace(run_dir=run_dir, reason="", limit=10, all=False)
    )


def _wizard_staging() -> int:
    run_dir = _prompt("Run dir (pvp_replay_*)")
    if not run_dir:
        return 0
    default_stage = (
        Path.home()
        / "chess_results"
        / f"pvp_replay_warmup_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
    )
    candidate_dir = _prompt("Candidate dir (will hold the new exp4 model)", str(default_stage))
    train_exp5 = _prompt("Also train exp5? (y/N)", "n").lower().startswith("y")
    return cmd_generate_staging_command(
        argparse.Namespace(
            run_dir=run_dir,
            candidate_dir=candidate_dir,
            preset="warmup10",
            train_exp5=train_exp5,
        )
    )


def cmd_wizard(args: argparse.Namespace) -> int:
    print("=== Chess Replay Pipeline Operator Wizard ===")
    while True:
        print()
        print("[1] Detect runtime / DB")
        print("[2] Export PvP / human-vs-engine replay")
        print("[3] Dry-run validation on an existing run dir")
        print("[4] Review rejected matches")
        print("[5] Generate staging warm-up command")
        print("[6] Exit")
        try:
            choice = input("Choose: ").strip()
        except EOFError:
            return 0
        if choice == "1":
            cmd_detect(argparse.Namespace())
        elif choice == "2":
            _wizard_export()
        elif choice == "3":
            _wizard_dry_run()
        elif choice == "4":
            _wizard_review()
        elif choice == "5":
            _wizard_staging()
        elif choice in ("6", ""):
            return 0
        else:
            print("invalid choice")


# ---- main --------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Operator UX wrapper for the W4.2-hardened replay pipeline. "
            "Wraps chess_pvp_history_to_replay + chess_seed_train --dry-run; "
            "never writes models, never trains."
        )
    )
    sub = parser.add_subparsers(dest="subcommand", required=True)

    p = sub.add_parser("detect", help="Show resolved runtime / DB paths.")
    p.set_defaults(func=cmd_detect)

    p = sub.add_parser("export", help="Run chess_pvp_history_to_replay.")
    p.add_argument("--since", default="")
    p.add_argument("--output-root", default="")
    p.add_argument("--min-plies", type=int, default=0)
    p.add_argument("--quality-weeks", type=int, default=0)
    p.add_argument("--quality-top-pct", type=float, default=0)
    p.add_argument("--hve-difficulties", default=None)
    p.set_defaults(func=cmd_export)

    p = sub.add_parser("dry-run", help="Run chess_seed_train --dry-run on a run dir.")
    p.add_argument("--run-dir", required=True)
    p.add_argument("--preset", default="warmup10")
    p.add_argument("--report-dir", default="")
    p.set_defaults(func=cmd_dry_run)

    p = sub.add_parser("review", help="Browse rejected.jsonl by reason.")
    p.add_argument("--run-dir", required=True)
    p.add_argument("--reason", default="")
    p.add_argument("--limit", type=int, default=10)
    p.add_argument("--all", action="store_true", help="Inspect every reason group.")
    p.set_defaults(func=cmd_review)

    p = sub.add_parser(
        "generate-staging-command",
        help="Emit the safe non-dry-run warm-up command (NOT executed).",
    )
    p.add_argument("--run-dir", required=True)
    p.add_argument("--candidate-dir", required=True)
    p.add_argument("--preset", default="warmup10")
    p.add_argument(
        "--train-exp5",
        action="store_true",
        help="Opt in to also train exp5 NNUE (default: skip to protect production).",
    )
    p.set_defaults(func=cmd_generate_staging_command)

    p = sub.add_parser("wizard", help="Interactive menu chaining the subcommands.")
    p.set_defaults(func=cmd_wizard)

    args = parser.parse_args()
    return int(args.func(args) or 0)


if __name__ == "__main__":
    raise SystemExit(main())
