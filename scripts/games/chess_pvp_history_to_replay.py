#!/usr/bin/env python3
"""Offline converter: hackme_web game_matches → canonical replay JSONL.

Phase 1 PvP / human-vs-engine replay v1 (diagnostic-only, offline). DOES NOT
auto-train. DOES NOT mutate the production runtime model. DOES NOT install a
finish-hook.

Pipeline (per [[feedback-pvp-replay-discipline]] memory):

    game_matches(mode IN ('pvp','computer'), status='finished')
        │
        ▼  W1 (this script)
    pvp_replay_candidates.jsonl       (every parsed match, with filter outcome)
    pvp_replay_training_eligible.jsonl (per-ply samples ready for chess_seed_train)
    pvp_replay_rejected.jsonl         (matches dropped before training, with reason)
    summary.json + SUMMARY.md

Two harvest paths in one converter:

  pvp_filtered (mode='pvp')
    - both players in last K weeks leaderboard top X%
    - winner-side moves only → target=1.0
    - trusted_source='pvp_filtered', label_quality='review'
    - weight defaults to 0.15 (capped 0.20)

  human_beat_engine (mode='computer', human won)
    - the human player must be in the leaderboard quality set
    - human-side moves only → target=1.0  (these are real exploits of engine
      weaknesses, e.g. the rook-underpromotion bug B fair smoke v2 surfaced)
    - trusted_source='human_beat_engine', label_quality='clean'
    - weight defaults to 0.20 (capped 0.25; higher than pvp because the
      outcome is an objective engine-loss signal, not just a human-vs-human
      result that could reflect mutual blunders)

Common filter gates (all must pass):
    - status = 'finished'
    - winner_user_id is not null (no draws in v1)
    - result_reason not in {timeout, abandoned, disconnect, resign_too_early,
      cancelled}
    - plies >= --min-plies (default 20)
    - move_history reconstructs cleanly via python-chess (no illegal moves)

Loser moves are NOT collected as negatives in v1 (no teacher audit).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

import chess

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.games.chess import (  # noqa: E402
    START_FEN,
    history_move_to_uci,
    replay_board_from_history,
)


DEFAULT_OUTPUT_ROOT = Path.home() / "chess_results"
DEFAULT_MIN_PLIES = 20
DEFAULT_QUALITY_WEEKS = 4
DEFAULT_QUALITY_TOP_PCT = 30.0
DEFAULT_PVP_SAMPLE_WEIGHT = 0.15
DEFAULT_HVE_SAMPLE_WEIGHT = 0.20
PVP_SAMPLE_WEIGHT_CAP = 0.20
HVE_SAMPLE_WEIGHT_CAP = 0.25

NON_NORMAL_RESULT_REASONS = {
    "timeout",
    "abandoned",
    "disconnect",
    "resign_too_early",
    "cancelled",
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _timestamp_dirname() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def _say(msg: str) -> None:
    print(msg, flush=True)


def _warn(msg: str) -> None:
    print(f"[WARN] {msg}", file=sys.stderr, flush=True)


def _err(msg: str) -> None:
    print(f"[ERROR] {msg}", file=sys.stderr, flush=True)


def _resolve_db_path(cli_db_path: str) -> Path:
    if cli_db_path:
        return Path(cli_db_path).expanduser().resolve()
    runtime_dir = os.environ.get("HACKME_RUNTIME_DIR", "").strip()
    if runtime_dir:
        return Path(runtime_dir).expanduser().resolve() / "database.db"
    raise SystemExit(
        "error: provide --db-path or set HACKME_RUNTIME_DIR (which contains database.db)"
    )


def _open_db(db_path: Path) -> sqlite3.Connection:
    if not db_path.exists():
        raise SystemExit(f"error: db path does not exist: {db_path}")
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    return conn


def _ordered_recent_week_keys(conn: sqlite3.Connection, *, weeks: int) -> list[str]:
    rows = conn.execute(
        "SELECT DISTINCT week_key FROM game_leaderboard_rewards WHERE game_key='chess' "
        "ORDER BY week_key DESC LIMIT ?",
        (int(weeks),),
    ).fetchall()
    return [str(r["week_key"]) for r in rows]


def _quality_user_set(
    conn: sqlite3.Connection,
    *,
    weeks: int,
    top_pct: float,
) -> tuple[set[int], dict]:
    """Return user_ids that landed in the top-X% of leaderboard rewards for at
    least one of the last K weeks. Also return a debug dict for SUMMARY.md."""
    week_keys = _ordered_recent_week_keys(conn, weeks=weeks)
    by_week: dict[str, dict] = {}
    qualified: set[int] = set()
    for wk in week_keys:
        rows = conn.execute(
            "SELECT user_id, rank, score FROM game_leaderboard_rewards "
            "WHERE game_key='chess' AND week_key=? ORDER BY rank ASC",
            (wk,),
        ).fetchall()
        n = len(rows)
        if n == 0:
            by_week[wk] = {"population": 0, "cutoff": 0, "qualified": []}
            continue
        cutoff = max(1, int(round(n * float(top_pct) / 100.0)))
        winners = [int(r["user_id"]) for r in rows[:cutoff]]
        by_week[wk] = {"population": n, "cutoff": cutoff, "qualified": winners}
        qualified.update(winners)
    return qualified, {
        "weeks_considered": list(week_keys),
        "top_pct": top_pct,
        "by_week": by_week,
        "union_size": len(qualified),
    }


def _classify_match(
    match: sqlite3.Row,
    *,
    move_history: list[dict],
    quality_users: set[int],
    min_plies: int,
) -> tuple[str, str]:
    """Return (path_type, reason).

    path_type ∈ {'pvp_filtered', 'human_beat_engine', 'reject'}.
    Common gates apply to both accept paths. Mode-specific quality rules:
      - PvP: both players must be in quality set
      - human_beat_engine: only the (human) winner must be in quality set
        AND the human must have won (winner_user_id matches a real player)
    """
    status = str(match["status"] or "")
    if status != "finished":
        return ("reject", "not_finished")
    result_reason = str(match["result_reason"] or "").strip().lower()
    if result_reason in NON_NORMAL_RESULT_REASONS:
        return ("reject", f"non_normal_end:{result_reason or 'unknown'}")
    if match["winner_user_id"] is None:
        return ("reject", "no_winner_or_drawn")
    if len(move_history) < min_plies:
        return ("reject", f"too_short:{len(move_history)}")

    mode = str(match["mode"] or "")
    white_id = match["white_user_id"]
    black_id = match["black_user_id"]

    if mode == "pvp":
        if white_id is None or black_id is None:
            return ("reject", "missing_player_id")
        if int(white_id) not in quality_users:
            return ("reject", "no_player_quality:white")
        if int(black_id) not in quality_users:
            return ("reject", "no_player_quality:black")
        return ("pvp_filtered", "")

    if mode == "computer":
        # mode='computer': only white_user_id is the human (black_user_id is
        # always NULL since the engine isn't a user).
        if white_id is None:
            return ("reject", "missing_human_id_in_computer_mode")
        if int(white_id) != int(match["winner_user_id"]):
            return ("reject", "computer_won_or_not_human_winner")
        if int(white_id) not in quality_users:
            return ("reject", "no_player_quality:human")
        return ("human_beat_engine", "")

    return ("reject", f"unsupported_mode:{mode}")


def _winner_side(match: sqlite3.Row) -> str | None:
    winner_id = match["winner_user_id"]
    if winner_id is None:
        return None
    mode = str(match["mode"] or "")
    if mode == "computer":
        if match["white_user_id"] is not None and int(winner_id) == int(match["white_user_id"]):
            return str(match["human_side"] or "white")
        return None
    if int(winner_id) == int(match["white_user_id"]):
        return "white"
    if match["black_user_id"] is not None and int(winner_id) == int(match["black_user_id"]):
        return "black"
    return None


_PATH_LABELS = {
    "pvp_filtered": {
        "source": "pvp",
        "label_quality": "review",
        "trusted_source": "pvp_filtered",
    },
    "human_beat_engine": {
        "source": "human_vs_engine",
        "label_quality": "clean",
        "trusted_source": "human_beat_engine",
    },
}


def _samples_for_match(
    match: sqlite3.Row,
    *,
    move_history: list[dict],
    winner_side: str,
    sample_weight: float,
    path_type: str,
) -> tuple[list[dict], str]:
    """Reconstruct fen_before per ply, collect winner-side samples only.

    Returns (samples, reconstruction_error). If reconstruction_error is
    non-empty, samples may be partial — caller treats it as rejection.
    """
    labels = _PATH_LABELS[path_type]
    samples: list[dict] = []
    board = chess.Board(START_FEN)
    match_id = int(match["id"])
    computer_difficulty = (
        str(match["computer_difficulty"]) if str(match["mode"] or "") == "computer" else ""
    )
    for ply_index, entry in enumerate(move_history):
        try:
            uci = history_move_to_uci(entry)
            move = chess.Move.from_uci(uci)
        except Exception as exc:
            return [], f"history_parse_error:ply={ply_index}:{exc!r}"
        if move not in board.legal_moves:
            return [], f"illegal_move:ply={ply_index}:{uci}"
        side = "white" if board.turn == chess.WHITE else "black"
        fen_before = board.fen()
        if side == winner_side:
            sample = {
                "fen": fen_before,
                "move_uci": uci,
                "side": side,
                "target": 1.0,
                "weight": float(sample_weight),
                "source": labels["source"],
                "source_id": f"match:{match_id}:ply:{ply_index}",
                "label_quality": labels["label_quality"],
                "trusted_source": labels["trusted_source"],
                "training_eligible": True,
                "match_id": match_id,
                "ply_index": ply_index,
                "winner_side": winner_side,
                "result_backed": True,
                "teacher_audit_status": "not_run",
                "match_mode": str(match["mode"] or ""),
                "computer_difficulty_if_any": computer_difficulty,
            }
            samples.append(sample)
        board.push(move)
    return samples, ""


def _hash_match(match: sqlite3.Row) -> str:
    payload = json.dumps(
        {
            "id": int(match["id"]),
            "white": match["white_user_id"],
            "black": match["black_user_id"],
            "winner": match["winner_user_id"],
            "finished_at": match["finished_at"],
        },
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Offline converter from game_matches PvP history to canonical replay JSONL."
    )
    p.add_argument("--db-path", default="", help="Path to main app SQLite DB (default $HACKME_RUNTIME_DIR/database.db).")
    p.add_argument("--since", default="", help="ISO date string (YYYY-MM-DD); only finished_at >= this is considered.")
    p.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    p.add_argument("--min-plies", type=int, default=DEFAULT_MIN_PLIES)
    p.add_argument("--quality-weeks", type=int, default=DEFAULT_QUALITY_WEEKS)
    p.add_argument("--quality-top-pct", type=float, default=DEFAULT_QUALITY_TOP_PCT)
    p.add_argument(
        "--pvp-sample-weight",
        type=float,
        default=DEFAULT_PVP_SAMPLE_WEIGHT,
        help=f"Weight for pvp_filtered samples (cap {PVP_SAMPLE_WEIGHT_CAP}).",
    )
    p.add_argument(
        "--hve-sample-weight",
        type=float,
        default=DEFAULT_HVE_SAMPLE_WEIGHT,
        help=f"Weight for human_beat_engine samples (cap {HVE_SAMPLE_WEIGHT_CAP}).",
    )
    p.add_argument(
        "--limit",
        type=int,
        default=0,
        help="If >0, process at most this many candidate matches (debug).",
    )
    return p.parse_args()


def run_export(
    *,
    db_path: Path,
    since: str,
    output_root: Path,
    min_plies: int,
    quality_weeks: int,
    quality_top_pct: float,
    pvp_sample_weight: float,
    hve_sample_weight: float,
    limit: int,
) -> dict:
    """Core export entry. Exposed for tests so callers can override paths."""
    if pvp_sample_weight > PVP_SAMPLE_WEIGHT_CAP:
        raise SystemExit(
            f"error: --pvp-sample-weight {pvp_sample_weight} exceeds policy cap {PVP_SAMPLE_WEIGHT_CAP}"
        )
    if hve_sample_weight > HVE_SAMPLE_WEIGHT_CAP:
        raise SystemExit(
            f"error: --hve-sample-weight {hve_sample_weight} exceeds policy cap {HVE_SAMPLE_WEIGHT_CAP}"
        )

    output_root.mkdir(parents=True, exist_ok=True)
    run_dir = output_root / f"pvp_replay_{_timestamp_dirname()}"
    run_dir.mkdir(parents=True, exist_ok=False)

    conn = _open_db(db_path)
    try:
        quality_users, quality_debug = _quality_user_set(
            conn, weeks=quality_weeks, top_pct=quality_top_pct
        )

        where = [
            "mode IN ('pvp', 'computer')",
            "status='finished'",
            "game_key='chess'",
        ]
        params: list = []
        if since:
            where.append("finished_at >= ?")
            params.append(since)
        sql = (
            "SELECT id, mode, status, white_user_id, black_user_id, human_side, "
            "computer_difficulty, winner_user_id, result_reason, move_history_json, "
            "created_at, updated_at, finished_at "
            "FROM game_matches WHERE " + " AND ".join(where) + " ORDER BY finished_at ASC"
        )
        if limit > 0:
            sql += f" LIMIT {int(limit)}"
        rows = list(conn.execute(sql, params))
    finally:
        conn.close()

    candidates_path = run_dir / "pvp_replay_candidates.jsonl"
    eligible_path = run_dir / "pvp_replay_training_eligible.jsonl"
    rejected_path = run_dir / "pvp_replay_rejected.jsonl"

    counts = {
        "matches_total": 0,
        "matches_accepted_pvp_filtered": 0,
        "matches_accepted_human_beat_engine": 0,
        "matches_rejected": 0,
        "samples_pvp_filtered": 0,
        "samples_human_beat_engine": 0,
        "reject_reasons": {},
    }

    def _write_reject(fh_c, fh_r, candidate_row, reason, plies):
        counts["matches_rejected"] += 1
        counts["reject_reasons"][reason] = counts["reject_reasons"].get(reason, 0) + 1
        candidate_row["filter_outcome"] = "reject"
        candidate_row["filter_reason"] = reason
        fh_c.write(json.dumps(candidate_row, sort_keys=True) + "\n")
        fh_r.write(
            json.dumps(
                {
                    "match_id": candidate_row["match_id"],
                    "rejection_reason": reason,
                    "finished_at": candidate_row["finished_at"],
                    "plies": plies,
                    "mode": candidate_row["mode"],
                },
                sort_keys=True,
            )
            + "\n"
        )

    with (
        candidates_path.open("w", encoding="utf-8") as fh_c,
        eligible_path.open("w", encoding="utf-8") as fh_e,
        rejected_path.open("w", encoding="utf-8") as fh_r,
    ):
        for match in rows:
            counts["matches_total"] += 1
            candidate_row = {
                "match_id": int(match["id"]),
                "mode": match["mode"],
                "status": match["status"],
                "white_user_id": match["white_user_id"],
                "black_user_id": match["black_user_id"],
                "winner_user_id": match["winner_user_id"],
                "result_reason": match["result_reason"],
                "computer_difficulty": match["computer_difficulty"],
                "human_side": match["human_side"],
                "finished_at": match["finished_at"],
                "match_hash": _hash_match(match),
                "filter_outcome": "",
                "filter_reason": "",
                "training_eligible": False,
            }

            try:
                move_history = json.loads(match["move_history_json"] or "[]")
            except Exception as exc:
                _write_reject(fh_c, fh_r, candidate_row, f"move_history_json_invalid:{exc!r}", 0)
                continue
            if not isinstance(move_history, list):
                move_history = []
            candidate_row["plies"] = len(move_history)

            path_type, reason = _classify_match(
                match,
                move_history=move_history,
                quality_users=quality_users,
                min_plies=min_plies,
            )
            if path_type == "reject":
                _write_reject(fh_c, fh_r, candidate_row, reason, len(move_history))
                continue

            winner_side = _winner_side(match)
            if winner_side is None:
                _write_reject(
                    fh_c, fh_r, candidate_row, "winner_user_id_not_in_match_players", len(move_history)
                )
                continue

            sample_weight = (
                pvp_sample_weight if path_type == "pvp_filtered" else hve_sample_weight
            )
            samples, recon_err = _samples_for_match(
                match,
                move_history=move_history,
                winner_side=winner_side,
                sample_weight=sample_weight,
                path_type=path_type,
            )
            if recon_err:
                _write_reject(
                    fh_c, fh_r, candidate_row, f"reconstruction_error:{recon_err}", len(move_history)
                )
                continue

            if path_type == "pvp_filtered":
                counts["matches_accepted_pvp_filtered"] += 1
                counts["samples_pvp_filtered"] += len(samples)
            else:
                counts["matches_accepted_human_beat_engine"] += 1
                counts["samples_human_beat_engine"] += len(samples)
            candidate_row["filter_outcome"] = path_type
            candidate_row["filter_reason"] = ""
            candidate_row["training_eligible"] = True
            candidate_row["training_samples"] = len(samples)
            candidate_row["winner_side"] = winner_side
            fh_c.write(json.dumps(candidate_row, sort_keys=True) + "\n")
            for sample in samples:
                fh_e.write(json.dumps(sample, sort_keys=True) + "\n")

    summary = {
        "timestamp": _now_iso(),
        "db_path": str(db_path),
        "output_dir": str(run_dir),
        "filter_config": {
            "min_plies": min_plies,
            "quality_weeks": quality_weeks,
            "quality_top_pct": quality_top_pct,
            "pvp_sample_weight": pvp_sample_weight,
            "hve_sample_weight": hve_sample_weight,
            "non_normal_result_reasons": sorted(NON_NORMAL_RESULT_REASONS),
        },
        "quality_signal": quality_debug,
        "counts": counts,
        "policy": {
            "diagnostic_only": True,
            "auto_train_hook": False,
            "production_runtime_mutation": False,
            "winner_side_only": True,
            "loser_side_collected_as_negative": False,
            "draws_collected_as_negative": False,
        },
    }
    (run_dir / "summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8"
    )

    lines = [
        "# PvP replay export — v1 offline filtered (diagnostic only)",
        "",
        f"- timestamp: {summary['timestamp']}",
        f"- db_path: {db_path}",
        f"- output_dir: {run_dir}",
        "",
        "## Filter config",
        f"- min_plies: {min_plies}",
        f"- quality_weeks: {quality_weeks}",
        f"- quality_top_pct: {quality_top_pct}",
        f"- pvp_sample_weight: {pvp_sample_weight}",
        f"- hve_sample_weight: {hve_sample_weight}",
        f"- non_normal_result_reasons: {sorted(NON_NORMAL_RESULT_REASONS)}",
        "",
        "## Quality signal",
        f"- weeks_considered: {quality_debug['weeks_considered']}",
        f"- union_size (eligible players): {quality_debug['union_size']}",
        "",
        "## Counts",
        f"- matches_total: {counts['matches_total']}",
        f"- matches_accepted_pvp_filtered: {counts['matches_accepted_pvp_filtered']}",
        f"- matches_accepted_human_beat_engine: {counts['matches_accepted_human_beat_engine']}",
        f"- matches_rejected: {counts['matches_rejected']}",
        f"- samples_pvp_filtered: {counts['samples_pvp_filtered']}",
        f"- samples_human_beat_engine: {counts['samples_human_beat_engine']}",
        "",
        "### reject_reasons",
    ]
    if counts["reject_reasons"]:
        for k in sorted(counts["reject_reasons"]):
            lines.append(f"- {k}: {counts['reject_reasons'][k]}")
    else:
        lines.append("- (none)")
    lines.extend(
        [
            "",
            "## Policy (hard-coded)",
            "- diagnostic_only = True",
            "- auto_train_hook = False (no PvP finish-hook in v1)",
            "- production_runtime_mutation = False",
            "- winner_side_only = True (loser moves not collected as negatives)",
            "- draws_collected_as_negative = False",
            "",
            "## Artifacts",
            f"- candidates: {candidates_path.name}",
            f"- training_eligible: {eligible_path.name}",
            f"- rejected: {rejected_path.name}",
            "",
            "Feed `pvp_replay_training_eligible.jsonl` to `chess_seed_train.py` via",
            "`--include-replay-jsonl PATH` for warm-up (downsampled per source cap).",
        ]
    )
    (run_dir / "SUMMARY.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    return summary


def main() -> int:
    args = parse_args()
    db_path = _resolve_db_path(args.db_path)
    output_root = Path(args.output_root).expanduser().resolve()

    _say("=== chess_pvp_history_to_replay (v1 offline, diagnostic only) ===")
    _say(f"db_path: {db_path}")
    _say(f"output_root: {output_root}")
    _say(f"min_plies: {args.min_plies}, quality_weeks: {args.quality_weeks}, top_pct: {args.quality_top_pct}")
    _say(f"pvp_sample_weight: {args.pvp_sample_weight}, hve_sample_weight: {args.hve_sample_weight}")
    summary = run_export(
        db_path=db_path,
        since=args.since.strip(),
        output_root=output_root,
        min_plies=int(args.min_plies),
        quality_weeks=int(args.quality_weeks),
        quality_top_pct=float(args.quality_top_pct),
        pvp_sample_weight=float(args.pvp_sample_weight),
        hve_sample_weight=float(args.hve_sample_weight),
        limit=int(args.limit),
    )
    counts = summary["counts"]
    _say(f"\ntotal: {counts['matches_total']} matches")
    _say(f"accepted (pvp_filtered): {counts['matches_accepted_pvp_filtered']}")
    _say(f"accepted (human_beat_engine): {counts['matches_accepted_human_beat_engine']}")
    _say(f"rejected: {counts['matches_rejected']}")
    _say(f"samples emitted: pvp={counts['samples_pvp_filtered']} hve={counts['samples_human_beat_engine']}")
    _say(f"\nartifacts: {summary['output_dir']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
