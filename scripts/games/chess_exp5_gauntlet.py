#!/usr/bin/env python3
"""Complete-game gauntlet for chess ``experiment 5:nnue``.

This is stronger than the original five-game reviewer smoke: it starts from a
small set of opening surfaces, alternates colors, records every move, and keeps
the result auditable under docs/games.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from itertools import count
from pathlib import Path
from typing import Any

import chess


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import scripts.games.game_ai_codex_play_eval as codex_eval  # noqa: E402


EXP5 = "experiment 5:nnue"
OPENING_LINES: dict[str, list[str]] = {
    "start": [],
    "open_game": ["e2e4", "e7e5"],
    "sicilian": ["e2e4", "c7c5"],
    "french": ["e2e4", "e7e6", "d2d4", "d7d5"],
    "caro_kann": ["e2e4", "c7c6", "d2d4", "d7d5"],
    "scandinavian": ["e2e4", "d7d5", "e4d5", "d8d5"],
    "queen_pawn": ["d2d4", "d7d5"],
    "queens_gambit": ["d2d4", "d7d5", "c2c4", "e7e6"],
    "kings_indian": ["d2d4", "g8f6", "c2c4", "g7g6"],
    "english": ["c2c4", "g8f6"],
    "reti": ["g1f3", "d7d5"],
    "fianchetto": ["g2g3", "d7d5"],
    "kings_gambit": ["e2e4", "e7e5", "f2f4", "e5f4"],
    "flank_probe": ["a2a4", "g8f6"],
    "early_queen_probe": ["e2e4", "e7e5", "d1h5", "b8c6"],
}


def _push_opening(board: chess.Board, opening_id: str, line: list[str]) -> list[dict[str, Any]]:
    history: list[dict[str, Any]] = []
    for ply, uci in enumerate(line, start=1):
        move = chess.Move.from_uci(uci)
        if move not in board.legal_moves:
            raise ValueError(f"illegal opening move {uci} in {opening_id} at ply {ply}")
        san = board.san(move)
        before = board.fen()
        board.push(move)
        history.append(
            {
                "ply": ply,
                "actor": "book",
                "uci": uci,
                "san": san,
                "fen_before": before,
                "fen_after": board.fen(),
                "decision": {"opening_id": opening_id},
            }
        )
    return history


def _result_from_board(
    board: chess.Board,
    *,
    codex_color_name: str,
    invalid: list[dict[str, Any]],
    max_plies_reached: bool,
) -> tuple[str, str, str]:
    codex_color = chess.WHITE if codex_color_name == "white" else chess.BLACK
    outcome = board.outcome(claim_draw=True)
    if invalid:
        return ("invalid-move", "ai_win" if invalid[-1]["actor"] == "codex" else "codex_win", "")
    if outcome:
        reason = str(outcome.termination.name).lower()
        if outcome.winner is None:
            return reason, "draw", ""
        if outcome.winner == codex_color:
            return reason, "codex_win", codex_color_name
        return reason, "ai_win", "black" if codex_color_name == "white" else "white"
    if max_plies_reached:
        material = codex_eval.material_score(board, codex_color)
        if material > 120:
            return "material_at_ply_cap", "codex_win", codex_color_name
        if material < -120:
            return "material_at_ply_cap", "ai_win", "black" if codex_color_name == "white" else "white"
        return "material_at_ply_cap", "draw", ""
    return "unterminated", "draw", ""


def play_game(
    *,
    opening_id: str,
    line: list[str],
    codex_color_name: str,
    seed: int,
    max_plies: int,
) -> dict[str, Any]:
    board = chess.Board()
    codex_color = chess.WHITE if codex_color_name == "white" else chess.BLACK
    history = _push_opening(board, opening_id, line)
    invalid: list[dict[str, Any]] = []
    started = time.perf_counter()
    max_plies_reached = False
    for ply in count(len(history) + 1):
        if board.is_game_over(claim_draw=True):
            break
        if ply > max_plies:
            max_plies_reached = True
            break
        actor = "codex" if board.turn == codex_color else "ai"
        before = board.fen()
        if actor == "codex":
            move, reason = codex_eval.codex_chess_move(board)
            info = {"uci": move.uci() if move else "", "reason": reason}
        else:
            move, info = codex_eval.choose_ai_chess_move(board, EXP5, history)
        if move is None:
            invalid.append({"ply": ply, "actor": actor, "fen": before, "decision": info})
            break
        san = board.san(move)
        board.push(move)
        history.append(
            {
                "ply": ply,
                "actor": actor,
                "uci": move.uci(),
                "san": san,
                "fen_before": before,
                "fen_after": board.fen(),
                "decision": info,
            }
        )
    reason, result, winner = _result_from_board(
        board,
        codex_color_name=codex_color_name,
        invalid=invalid,
        max_plies_reached=max_plies_reached,
    )
    return {
        "game_key": "chess",
        "difficulty": EXP5,
        "opening_id": opening_id,
        "opening_line": line,
        "codex_color": codex_color_name,
        "seed": int(seed),
        "result": result,
        "winner_color": winner,
        "reason": reason,
        "complete_game": bool(board.outcome(claim_draw=True)) or bool(invalid),
        "plies": len(history),
        "final_fen": board.fen(),
        "codex_material_cp": codex_eval.material_score(board, codex_color),
        "invalid": invalid,
        "elapsed_ms": round((time.perf_counter() - started) * 1000.0, 3),
        "moves": history,
    }


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    games = len(rows)
    ai_wins = sum(1 for row in rows if row.get("result") == "ai_win")
    draws = sum(1 for row in rows if row.get("result") == "draw")
    codex_wins = sum(1 for row in rows if row.get("result") == "codex_win")
    threefold = sum(1 for row in rows if row.get("reason") == "threefold_repetition")
    checkmates = sum(1 for row in rows if row.get("reason") == "checkmate")
    complete = sum(1 for row in rows if row.get("complete_game"))
    return {
        "games": games,
        "ai_wins": ai_wins,
        "draws": draws,
        "codex_wins": codex_wins,
        "ai_score_rate": round((ai_wins + 0.5 * draws) / max(1, games), 4),
        "ai_win_rate": round(ai_wins / max(1, games), 4),
        "draw_rate": round(draws / max(1, games), 4),
        "loss_rate": round(codex_wins / max(1, games), 4),
        "threefold_rate": round(threefold / max(1, games), 4),
        "checkmate_rate": round(checkmates / max(1, games), 4),
        "complete_game_rate": round(complete / max(1, games), 4),
        "avg_plies": round(sum(int(row.get("plies") or 0) for row in rows) / max(1, games), 2),
        "avg_elapsed_ms": round(sum(float(row.get("elapsed_ms") or 0.0) for row in rows) / max(1, games), 3),
        "reasons": sorted({str(row.get("reason") or "") for row in rows}),
        "by_opening": {
            opening: {
                "games": len(items),
                "ai_wins": sum(1 for row in items if row.get("result") == "ai_win"),
                "draws": sum(1 for row in items if row.get("result") == "draw"),
                "codex_wins": sum(1 for row in items if row.get("result") == "codex_win"),
            }
            for opening in sorted({str(row.get("opening_id") or "") for row in rows})
            for items in [[row for row in rows if row.get("opening_id") == opening]]
        },
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run exp5 complete-game gauntlet.")
    parser.add_argument("--games-per-opening", type=int, default=2)
    parser.add_argument("--max-plies", type=int, default=220)
    parser.add_argument("--seed", type=int, default=20260513)
    parser.add_argument("--openings", default=",".join(OPENING_LINES))
    parser.add_argument("--output", default=str(ROOT / "docs" / "games" / "2026-05-13_exp5_gauntlet.json"))
    parser.add_argument("--jsonl-output", default=str(ROOT / "docs" / "games" / "2026-05-13_exp5_gauntlet_replays.jsonl"))
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    openings = [item.strip() for item in str(args.openings or "").split(",") if item.strip()]
    rows: list[dict[str, Any]] = []
    for opening_id in openings:
        line = OPENING_LINES.get(opening_id)
        if line is None:
            raise SystemExit(f"unknown opening id: {opening_id}")
        for game_no in range(1, max(1, int(args.games_per_opening)) + 1):
            codex_color = "white" if game_no % 2 == 1 else "black"
            rows.append(
                play_game(
                    opening_id=opening_id,
                    line=line,
                    codex_color_name=codex_color,
                    seed=codex_eval.stable_seed(args.seed, EXP5, opening_id, game_no),
                    max_plies=max(1, int(args.max_plies)),
                )
            )
    artifact = {
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "engine": EXP5,
        "method": {
            "games_per_opening": max(1, int(args.games_per_opening)),
            "max_plies": max(1, int(args.max_plies)),
            "openings": openings,
        },
        "summary": summarize(rows),
        "games": rows,
    }
    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(artifact, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    jsonl_path = Path(args.jsonl_output)
    jsonl_path.parent.mkdir(parents=True, exist_ok=True)
    jsonl_path.write_text("\n".join(json.dumps(row, ensure_ascii=False, sort_keys=True) for row in rows) + "\n", encoding="utf-8")
    print(out_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
