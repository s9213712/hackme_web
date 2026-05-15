#!/usr/bin/env python3
"""Run complete Exp5 vs local Stockfish/Blockfish games.

Full replay rows are written to a private runtime path. The public summary is
aggregate-only and does not include FENs, moves, or PVs.
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
from services.games.chess_nnue import choose_experiment_nnue_move  # noqa: E402
from services.games.chess_stockfish_teacher import (  # noqa: E402
    UciStockfish,
    analysis_limit,
    resolve_stockfish_path,
    stockfish_reference,
)


DEFAULT_OPENINGS: list[tuple[str, list[str]]] = [
    ("start", []),
    ("open_game", ["e2e4", "e7e5"]),
    ("queen_pawn", ["d2d4", "d7d5"]),
    ("sicilian", ["e2e4", "c7c5"]),
    ("english", ["c2c4", "g8f6"]),
]


def _move_from_exp5(board: chess.Board, *, profile: str) -> tuple[chess.Move | None, dict[str, Any]]:
    side = "white" if board.turn == chess.WHITE else "black"
    state = codex_eval.state_from_chess_board(board)
    raw = choose_experiment_nnue_move(state, side, search_profile=profile)
    uci = codex_eval.chess_move_uci(raw)
    info = {"engine": "exp5", "profile": profile, "uci": uci}
    try:
        move = chess.Move.from_uci(uci)
    except Exception as exc:
        info["invalid"] = f"bad-uci:{type(exc).__name__}: {exc}"
        return None, info
    if move not in board.legal_moves:
        info["invalid"] = "not-legal"
        return None, info
    return move, info


def _move_from_blockfish(
    board: chess.Board,
    *,
    engine: UciStockfish,
    depth: int,
    movetime_ms: int,
) -> tuple[chess.Move | None, dict[str, Any]]:
    rows = engine.analyse(
        board,
        limit=analysis_limit(depth=max(0, int(depth)), movetime_ms=max(0, int(movetime_ms))),
        multipv=1,
    )
    row = rows[0] if rows else {}
    move_text = str(row.get("move") or "")
    info = {
        "engine": "blockfish",
        "depth": int(depth),
        "movetime_ms": int(movetime_ms),
        "uci": move_text,
        "score_cp": row.get("score_cp"),
        "mate": row.get("mate"),
    }
    try:
        move = chess.Move.from_uci(move_text)
    except Exception as exc:
        info["invalid"] = f"bad-uci:{type(exc).__name__}: {exc}"
        return None, info
    if move not in board.legal_moves:
        info["invalid"] = "not-legal"
        return None, info
    return move, info


def _push_book(board: chess.Board, opening_id: str, moves: list[str]) -> list[dict[str, Any]]:
    history: list[dict[str, Any]] = []
    for ply, move_text in enumerate(moves, start=1):
        move = chess.Move.from_uci(move_text)
        if move not in board.legal_moves:
            raise ValueError(f"illegal book move {move_text} in {opening_id}")
        before = board.fen()
        san = board.san(move)
        board.push(move)
        history.append(
            {
                "ply": ply,
                "actor": "book",
                "uci": move.uci(),
                "san": san,
                "fen_before": before,
                "fen_after": board.fen(),
                "decision": {"opening_id": opening_id},
            }
        )
    return history


def _result(board: chess.Board, *, exp5_color: chess.Color, invalid_actor: str | None, max_plies_reached: bool) -> dict[str, Any]:
    if invalid_actor:
        winner = "blockfish" if invalid_actor == "exp5" else "exp5"
        return {"reason": "invalid_move", "winner": winner, "result": f"{winner}_win"}
    outcome = board.outcome(claim_draw=True)
    if outcome is not None:
        reason = str(outcome.termination.name).lower()
        if outcome.winner is None:
            return {"reason": reason, "winner": "", "result": "draw"}
        winner = "exp5" if outcome.winner == exp5_color else "blockfish"
        return {"reason": reason, "winner": winner, "result": f"{winner}_win"}
    if max_plies_reached:
        return {"reason": "max_plies_reached", "winner": "", "result": "incomplete"}
    return {"reason": "unterminated", "winner": "", "result": "incomplete"}


def play_game(
    *,
    game_index: int,
    opening_id: str,
    opening_moves: list[str],
    exp5_color_name: str,
    profile: str,
    engine: UciStockfish,
    stockfish_depth: int,
    stockfish_movetime_ms: int,
    max_plies: int,
) -> dict[str, Any]:
    board = chess.Board()
    exp5_color = chess.WHITE if exp5_color_name == "white" else chess.BLACK
    history = _push_book(board, opening_id, opening_moves)
    invalid_actor: str | None = None
    started = time.perf_counter()
    max_plies_reached = False
    for ply in count(len(history) + 1):
        if board.is_game_over(claim_draw=True):
            break
        if ply > max_plies:
            max_plies_reached = True
            break
        actor = "exp5" if board.turn == exp5_color else "blockfish"
        before = board.fen()
        if actor == "exp5":
            move, decision = _move_from_exp5(board, profile=profile)
        else:
            move, decision = _move_from_blockfish(
                board,
                engine=engine,
                depth=stockfish_depth,
                movetime_ms=stockfish_movetime_ms,
            )
        if move is None:
            invalid_actor = actor
            history.append({"ply": ply, "actor": actor, "fen_before": before, "decision": decision})
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
                "decision": decision,
            }
        )
    result = _result(board, exp5_color=exp5_color, invalid_actor=invalid_actor, max_plies_reached=max_plies_reached)
    return {
        "game_index": int(game_index),
        "opening_id": opening_id,
        "opening_moves": opening_moves,
        "exp5_color": exp5_color_name,
        "profile": profile,
        "stockfish_depth": int(stockfish_depth),
        "stockfish_movetime_ms": int(stockfish_movetime_ms),
        "plies": len(history),
        "complete_game": result["result"] != "incomplete",
        "final_fen": board.fen(),
        "elapsed_ms": round((time.perf_counter() - started) * 1000.0, 3),
        "moves": history,
        **result,
    }


def _summary(
    games: list[dict[str, Any]],
    *,
    profile: str,
    stockfish_path: str,
    stockfish_depth: int,
    stockfish_movetime_ms: int,
    stockfish_depth_schedule: list[int] | None = None,
) -> dict[str, Any]:
    total = len(games)
    exp5_wins = sum(1 for game in games if game.get("result") == "exp5_win")
    stockfish_wins = sum(1 for game in games if game.get("result") == "blockfish_win")
    draws = sum(1 for game in games if game.get("result") == "draw")
    incomplete = sum(1 for game in games if game.get("result") == "incomplete")
    return {
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "kind": "redacted_exp5_blockfish_match_summary",
        "leak_policy": "redacted: no FEN, moves, PV, source game ids, or per-position answers",
        "profile": profile,
        "blockfish_reference": stockfish_reference(stockfish_path),
        "stockfish_depth": int(stockfish_depth),
        "stockfish_depth_schedule": list(stockfish_depth_schedule or []),
        "stockfish_movetime_ms": int(stockfish_movetime_ms),
        "games": total,
        "exp5_wins": exp5_wins,
        "blockfish_wins": stockfish_wins,
        "draws": draws,
        "incomplete": incomplete,
        "exp5_score_rate": round((exp5_wins + 0.5 * draws) / max(1, total), 4),
        "exp5_win_rate": round(exp5_wins / max(1, total), 4),
        "blockfish_win_rate": round(stockfish_wins / max(1, total), 4),
        "draw_rate": round(draws / max(1, total), 4),
        "avg_plies": round(sum(int(game.get("plies") or 0) for game in games) / max(1, total), 2),
        "reasons": sorted({str(game.get("reason") or "") for game in games}),
        "by_game_redacted": [
            {
                "game_index": int(game.get("game_index") or 0),
                "opening_id": str(game.get("opening_id") or ""),
                "exp5_color": str(game.get("exp5_color") or ""),
                "stockfish_depth": int(game.get("stockfish_depth") or stockfish_depth),
                "result": str(game.get("result") or ""),
                "winner": str(game.get("winner") or ""),
                "reason": str(game.get("reason") or ""),
                "plies": int(game.get("plies") or 0),
                "complete_game": bool(game.get("complete_game")),
            }
            for game in games
        ],
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", default="fixed_depth_fianchetto_tail_castle_guard")
    parser.add_argument("--stockfish-path", default="")
    parser.add_argument("--stockfish-depth", type=int, default=6)
    parser.add_argument("--stockfish-depth-schedule", default="", help="Comma-separated per-game depths, for staged Blockfish matches.")
    parser.add_argument("--stockfish-movetime-ms", type=int, default=0)
    parser.add_argument("--games", type=int, default=5)
    parser.add_argument("--max-plies", type=int, default=600)
    parser.add_argument("--private-jsonl", required=True)
    parser.add_argument("--summary-json", required=True)
    return parser.parse_args()


def _depth_schedule(text: str) -> list[int]:
    depths: list[int] = []
    for item in str(text or "").split(","):
        item = item.strip()
        if not item:
            continue
        try:
            depth = int(item)
        except ValueError:
            continue
        if depth > 0:
            depths.append(depth)
    return depths


def _running_score(games: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(games)
    exp5_wins = sum(1 for game in games if game.get("result") == "exp5_win")
    blockfish_wins = sum(1 for game in games if game.get("result") == "blockfish_win")
    draws = sum(1 for game in games if game.get("result") == "draw")
    incomplete = sum(1 for game in games if game.get("result") == "incomplete")
    return {
        "games": total,
        "exp5_wins": exp5_wins,
        "draws": draws,
        "blockfish_wins": blockfish_wins,
        "incomplete": incomplete,
        "exp5_score_rate": round((exp5_wins + 0.5 * draws) / max(1, total), 4),
    }


def _print_game_done(game: dict[str, Any], *, total_games: int, games: list[dict[str, Any]]) -> None:
    running = _running_score(games)
    print(
        "[exp5-blockfish] done "
        f"game={int(game.get('game_index') or 0)}/{int(total_games)} "
        f"result={str(game.get('result') or '')} "
        f"reason={str(game.get('reason') or '')} "
        f"plies={int(game.get('plies') or 0)} "
        f"elapsed_ms={float(game.get('elapsed_ms') or 0.0):.1f} "
        f"running={running['exp5_wins']}W/{running['draws']}D/{running['blockfish_wins']}L "
        f"score_rate={running['exp5_score_rate']:.4f}",
        flush=True,
    )


def main() -> int:
    args = parse_args()
    stockfish_path = resolve_stockfish_path(str(args.stockfish_path or ""))
    if not stockfish_path:
        raise SystemExit("Stockfish/Blockfish binary not found")
    depth_schedule = _depth_schedule(str(args.stockfish_depth_schedule or ""))
    games: list[dict[str, Any]] = []
    total_games = max(1, int(args.games))
    with UciStockfish(stockfish_path) as engine:
        for index in range(1, total_games + 1):
            opening_id, opening_moves = DEFAULT_OPENINGS[(index - 1) % len(DEFAULT_OPENINGS)]
            exp5_color = "white" if index % 2 == 1 else "black"
            stockfish_depth = depth_schedule[index - 1] if index - 1 < len(depth_schedule) else int(args.stockfish_depth)
            print(
                f"[exp5-blockfish] start game={index}/{total_games} opening={opening_id} exp5={exp5_color} depth={stockfish_depth}",
                flush=True,
            )
            game = play_game(
                game_index=index,
                opening_id=opening_id,
                opening_moves=list(opening_moves),
                exp5_color_name=exp5_color,
                profile=str(args.profile),
                engine=engine,
                stockfish_depth=int(stockfish_depth),
                stockfish_movetime_ms=int(args.stockfish_movetime_ms),
                max_plies=max(1, int(args.max_plies)),
            )
            games.append(game)
            _print_game_done(game, total_games=total_games, games=games)
    private_path = Path(args.private_jsonl)
    private_path.parent.mkdir(parents=True, exist_ok=True)
    private_path.write_text("\n".join(json.dumps(game, ensure_ascii=False, sort_keys=True) for game in games) + "\n", encoding="utf-8")
    summary = _summary(
        games,
        profile=str(args.profile),
        stockfish_path=stockfish_path,
        stockfish_depth=int(args.stockfish_depth),
        stockfish_movetime_ms=int(args.stockfish_movetime_ms),
        stockfish_depth_schedule=depth_schedule,
    )
    summary_path = Path(args.summary_json)
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"summary": str(summary_path), "private_jsonl": str(private_path)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
