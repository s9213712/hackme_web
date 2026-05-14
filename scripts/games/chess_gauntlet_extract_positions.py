#!/usr/bin/env python3
"""Extract per-position rows from exp5 gauntlet JSONL replays.

The output format is intentionally compatible with
``chess_stockfish_teacher_audit.py``: each row has ``fen`` + ``move_uci`` +
``side`` and can be filtered by actor/result/reason before Stockfish analysis.
"""

from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import sys
from typing import Iterable

import chess


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Extract FEN/move rows from chess gauntlet JSONL.")
    parser.add_argument("--input-jsonl", action="append", required=True, help="Gauntlet JSONL replay path.")
    parser.add_argument("--output-jsonl", required=True, help="Destination per-position JSONL path.")
    parser.add_argument("--summary-json", default="", help="Optional summary JSON path.")
    parser.add_argument("--actor", action="append", default=[], help="Actor filter, e.g. ai or codex. Repeatable.")
    parser.add_argument("--result", action="append", default=[], help="Game result filter, e.g. draw or ai_win.")
    parser.add_argument("--reason", action="append", default=[], help="Game reason filter, e.g. threefold_repetition.")
    parser.add_argument("--opening", action="append", default=[], help="Opening id filter. Repeatable.")
    parser.add_argument("--min-ply", type=int, default=0)
    parser.add_argument("--max-ply", type=int, default=0)
    parser.add_argument(
        "--tail-actor-moves",
        type=int,
        default=0,
        help="Keep only the final N moves per selected game after actor/ply filters; useful for endgame/tail audits.",
    )
    parser.add_argument("--max-games", type=int, default=0)
    return parser.parse_args()


def _read_jsonl(path: Path) -> Iterable[tuple[int, dict]]:
    for line_no, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), start=1):
        if not line.strip():
            continue
        payload = json.loads(line)
        if isinstance(payload, dict):
            yield line_no, payload


def _normalized_set(values: list[str]) -> set[str]:
    return {str(item).strip().lower() for item in values if str(item).strip()}


def _side_from_fen(fen: str) -> str:
    board = chess.Board(fen)
    return "white" if board.turn == chess.WHITE else "black"


def _entry_uci(entry: dict) -> str:
    direct = str(entry.get("uci") or "").strip().lower()
    if direct:
        return direct
    return f"{entry.get('from') or ''}{entry.get('to') or ''}{entry.get('promotion') or ''}".strip().lower()


def run(args: argparse.Namespace) -> dict:
    input_paths = [Path(item).expanduser().resolve() for item in args.input_jsonl]
    actor_filter = _normalized_set(args.actor)
    result_filter = _normalized_set(args.result)
    reason_filter = _normalized_set(args.reason)
    opening_filter = _normalized_set(args.opening)
    min_ply = max(0, int(args.min_ply or 0))
    max_ply = max(0, int(args.max_ply or 0))
    tail_actor_moves = max(0, int(args.tail_actor_moves or 0))
    max_games = max(0, int(args.max_games or 0))

    output_rows: list[dict] = []
    counts: Counter[str] = Counter()
    by_result: Counter[str] = Counter()
    by_reason: Counter[str] = Counter()
    by_actor: Counter[str] = Counter()
    by_opening: Counter[str] = Counter()
    games_seen = 0
    games_selected = 0

    for input_path in input_paths:
        for line_no, game in _read_jsonl(input_path):
            games_seen += 1
            if max_games and games_seen > max_games:
                continue
            result = str(game.get("result") or "").strip().lower()
            reason = str(game.get("reason") or "").strip().lower()
            opening_id = str(game.get("opening_id") or "").strip().lower()
            if result_filter and result not in result_filter:
                continue
            if reason_filter and reason not in reason_filter:
                continue
            if opening_filter and opening_id not in opening_filter:
                continue
            moves = game.get("moves") or []
            if not isinstance(moves, list):
                continue
            games_selected += 1
            by_result[result or "unknown"] += 1
            by_reason[reason or "unknown"] += 1
            by_opening[opening_id or "unknown"] += 1
            replay_id = str(game.get("replay_id") or f"{input_path.stem}:{line_no}")
            tail_allowed_indexes: set[int] | None = None
            if tail_actor_moves:
                eligible_indexes: list[int] = []
                for move_index, entry in enumerate(moves, start=1):
                    if not isinstance(entry, dict):
                        continue
                    actor = str(entry.get("actor") or "").strip().lower()
                    if actor_filter and actor not in actor_filter:
                        continue
                    ply = int(entry.get("ply") or move_index)
                    if min_ply and ply < min_ply:
                        continue
                    if max_ply and ply > max_ply:
                        continue
                    eligible_indexes.append(move_index)
                tail_allowed_indexes = set(eligible_indexes[-tail_actor_moves:])
            for move_index, entry in enumerate(moves, start=1):
                if not isinstance(entry, dict):
                    continue
                if tail_allowed_indexes is not None and move_index not in tail_allowed_indexes:
                    continue
                actor = str(entry.get("actor") or "").strip().lower()
                if actor_filter and actor not in actor_filter:
                    continue
                ply = int(entry.get("ply") or move_index)
                if min_ply and ply < min_ply:
                    continue
                if max_ply and ply > max_ply:
                    continue
                fen = str(entry.get("fen_before") or "").strip()
                move_uci = _entry_uci(entry)
                if not fen or not move_uci:
                    counts["missing_fen_or_move"] += 1
                    continue
                try:
                    side = _side_from_fen(fen)
                    board = chess.Board(fen)
                    parsed_move = chess.Move.from_uci(move_uci)
                    if parsed_move not in board.legal_moves:
                        counts["illegal_move_rows"] += 1
                        continue
                except Exception:
                    counts["invalid_position_rows"] += 1
                    continue
                by_actor[actor or "unknown"] += 1
                output_rows.append(
                    {
                        "fen": fen,
                        "move_uci": move_uci,
                        "uci": move_uci,
                        "side": side,
                        "actor": actor,
                        "source": "exp5_gauntlet_extract_positions",
                        "source_id": f"{input_path.name}:{line_no}:ply:{ply}",
                        "source_path": str(input_path),
                        "source_game_index": games_seen,
                        "source_move_index": move_index,
                        "replay_id": replay_id,
                        "ply": ply,
                        "opening_id": opening_id,
                        "result": result,
                        "reason": reason,
                        "codex_color": str(game.get("codex_color") or ""),
                        "difficulty": str(game.get("difficulty") or ""),
                        "fen_after": str(entry.get("fen_after") or ""),
                        "san": str(entry.get("san") or ""),
                    }
                )

    output_path = Path(args.output_jsonl).expanduser().resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as handle:
        for row in output_rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")

    summary = {
        "ok": True,
        "input_jsonls": [str(path) for path in input_paths],
        "output_jsonl": str(output_path),
        "games_seen": games_seen,
        "games_selected": games_selected,
        "rows_written": len(output_rows),
        "filters": {
            "actor": sorted(actor_filter),
            "result": sorted(result_filter),
            "reason": sorted(reason_filter),
            "opening": sorted(opening_filter),
            "min_ply": min_ply,
            "max_ply": max_ply,
            "tail_actor_moves": tail_actor_moves,
            "max_games": max_games,
        },
        "counts": dict(counts),
        "by_result": dict(by_result),
        "by_reason": dict(by_reason),
        "by_actor": dict(by_actor),
        "by_opening": dict(by_opening),
    }
    if args.summary_json:
        summary_path = Path(args.summary_json).expanduser().resolve()
        summary_path.parent.mkdir(parents=True, exist_ok=True)
        summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        summary["summary_json"] = str(summary_path)
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    return summary


def main() -> int:
    run(parse_args())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
