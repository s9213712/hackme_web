#!/usr/bin/env python3
"""Supplementary Codex-vs-game-AI sparring audit.

This script records short games where a transparent "Codex reviewer" policy
plays each exposed hackme_web game AI difficulty. It is deliberately not an
external engine and should not be used as a strength oracle. Its purpose is to
preserve reproducible evidence for subjective reviewer impressions: whether an
AI feels coherent, whether it misses obvious threats, and which fixes would
make it a better training opponent.
"""

from __future__ import annotations

import argparse
import json
import math
import random
import sys
import time
from itertools import count
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import chess


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from routes import games as game_routes  # noqa: E402
from services.games import board_ai as board_ai_service  # noqa: E402
from services.games import board_arena  # noqa: E402
from services.games.chess import FEN_KEY  # noqa: E402


BOARD_DIFFICULTIES = ("easy", "normal", "hard")
CHESS_DIFFICULTIES = (
    "normal",
    "hard",
    "experiment",
    "experiment 3:dl",
    "experiment 4:pv",
    "experiment 5:nnue",
)
GAME_LABELS = {"reversi": "黑白棋", "go": "圍棋", "gomoku": "五子棋", "chess": "西洋棋"}
DIFFICULTY_LABELS = {
    "easy": "簡單",
    "normal": "普通",
    "hard": "困難",
    "experiment": "實驗",
    "experiment 3:dl": "實驗 3：DL 語義平衡",
    "experiment 4:pv": "實驗 4：Policy/Value + MCTS",
    "experiment 5:nnue": "實驗 5：NNUE + AlphaBeta/PVS",
}
PIECE_VALUES = {
    chess.PAWN: 100,
    chess.KNIGHT: 320,
    chess.BISHOP: 330,
    chess.ROOK: 500,
    chess.QUEEN: 900,
    chess.KING: 0,
}


def stable_seed(*parts: Any) -> int:
    value = 0
    for idx, char in enumerate("|".join(str(part) for part in parts)):
        value = (value + (idx + 1) * ord(char)) % (2**31 - 1)
    return value


def board_size(game_key: str) -> int:
    return board_ai_service.BOARD_AI_SIZES[game_key]


def idx(game_key: str, x: int, y: int) -> int:
    return y * board_size(game_key) + x


def xy(game_key: str, index: int) -> tuple[int, int]:
    size = board_size(game_key)
    return int(index) % size, int(index) // size


def neighbors(game_key: str, index: int):
    size = board_size(game_key)
    x, y = xy(game_key, index)
    for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
        nx, ny = x + dx, y + dy
        if 0 <= nx < size and 0 <= ny < size:
            yield idx(game_key, nx, ny)


def move_label(game_key: str, move: int | None) -> str:
    if move is None:
        return "-"
    x, y = xy(game_key, int(move))
    return f"{int(move)} ({x},{y})"


def choose_ai_board_move(game_key: str, board: tuple[str, ...], turn: str, difficulty: str) -> dict[str, Any]:
    return board_ai_service.choose_board_game_ai_move(game_key, list(board), turn, difficulty)


def codex_reversi_move(board: tuple[str, ...], turn: str) -> tuple[int | None, str]:
    moves = board_arena.legal_moves("reversi", board, turn)
    if not moves:
        return None, "pass"
    other = board_ai_service.opponent(turn)
    corners = {0, 7, 56, 63}
    x_squares = {9: 0, 14: 7, 49: 56, 54: 63}
    c_squares = {1: 0, 8: 0, 6: 7, 15: 7, 48: 56, 57: 56, 55: 63, 62: 63}
    best: tuple[float, int, str] | None = None
    for move in moves:
        next_board, _meta = board_arena.apply_board_move("reversi", board, move, turn)
        if next_board is None:
            continue
        opponent_moves = len(board_arena.legal_moves("reversi", next_board, other))
        own_moves = len(board_arena.legal_moves("reversi", next_board, turn))
        score = 0.0
        score += 220.0 if move in corners else 0.0
        score += 18.0 * (own_moves - opponent_moves)
        score += 10.0 * sum(1 for c in corners if next_board[c] == turn)
        score += 2.0 * (next_board.count(turn) - next_board.count(other))
        if move in x_squares and not board[x_squares[move]]:
            score -= 160.0
        if move in c_squares and not board[c_squares[move]]:
            score -= 90.0
        reason = "corner/mobility/avoid-xc"
        candidate = (score, -move, reason)
        if best is None or candidate > best:
            best = candidate
    if best is None:
        return moves[0], "fallback-legal"
    return -best[1], best[2]


def codex_go_move(board: tuple[str, ...], turn: str) -> tuple[int | None, str]:
    moves = board_arena.legal_moves("go", board, turn)
    if not moves:
        return None, "pass"
    best: tuple[float, int, str] | None = None
    center = (board_size("go") - 1) / 2
    for move in moves:
        next_board, meta = board_arena.apply_board_move("go", board, move, turn)
        if next_board is None:
            continue
        group, liberties = board_ai_service.go_group_and_liberties(next_board, move)
        adjacent_allies = sum(1 for n in neighbors("go", move) if board[n] == turn)
        adjacent_enemies = sum(1 for n in neighbors("go", move) if board[n] == board_ai_service.opponent(turn))
        x, y = xy("go", move)
        center_score = 8 - abs(x - center) - abs(y - center)
        score = (
            float(meta.get("captured", 0)) * 140.0
            + len(liberties) * 12.0
            + adjacent_allies * 8.0
            + adjacent_enemies * 4.0
            + center_score * 3.0
        )
        if len(group) >= 3 and len(liberties) <= 1:
            score -= 80.0
        reason = "capture/liberties/center"
        candidate = (score, -move, reason)
        if best is None or candidate > best:
            best = candidate
    if best is None:
        return moves[0], "fallback-legal"
    return -best[1], best[2]


def gomoku_candidates(board: tuple[str, ...]) -> list[int]:
    size = board_size("gomoku")
    stones = [i for i, value in enumerate(board) if value]
    if not stones:
        return [idx("gomoku", size // 2, size // 2)]
    candidates: set[int] = set()
    for stone in stones:
        sx, sy = xy("gomoku", stone)
        for dy in range(-2, 3):
            for dx in range(-2, 3):
                nx, ny = sx + dx, sy + dy
                if 0 <= nx < size and 0 <= ny < size:
                    move = idx("gomoku", nx, ny)
                    if not board[move]:
                        candidates.add(move)
    center = (size - 1) / 2
    return sorted(candidates, key=lambda move: (abs(xy("gomoku", move)[0] - center) + abs(xy("gomoku", move)[1] - center), move))


def has_gomoku_win_after(board: tuple[str, ...], move: int, color: str) -> bool:
    next_board = list(board)
    next_board[move] = color
    return board_ai_service.gomoku_has_five(tuple(next_board), move, color)


def gomoku_window_score(board: tuple[str, ...], move: int, color: str) -> float:
    size = board_size("gomoku")
    other = board_ai_service.opponent(color)
    score = 0.0
    mx, my = xy("gomoku", move)
    test = list(board)
    test[move] = color
    test_board = tuple(test)
    for dx, dy in ((1, 0), (0, 1), (1, 1), (1, -1)):
        for start in range(-4, 1):
            cells = []
            for step in range(5):
                x = mx + (start + step) * dx
                y = my + (start + step) * dy
                if not (0 <= x < size and 0 <= y < size):
                    cells = []
                    break
                cells.append(test_board[idx("gomoku", x, y)])
            if not cells:
                continue
            own = cells.count(color)
            theirs = cells.count(other)
            if own and theirs:
                continue
            if own:
                score += (0, 3, 18, 120, 900, 100000)[own]
            elif theirs:
                score -= (0, 2, 14, 90, 700, 100000)[theirs]
    return score


def codex_gomoku_move(board: tuple[str, ...], turn: str) -> tuple[int | None, str]:
    candidates = gomoku_candidates(board)
    other = board_ai_service.opponent(turn)
    for move in candidates:
        if has_gomoku_win_after(board, move, turn):
            return move, "win-now"
    for move in candidates:
        if has_gomoku_win_after(board, move, other):
            return move, "block-five"
    best: tuple[float, int, str] | None = None
    for move in candidates[:48]:
        score = gomoku_window_score(board, move, turn)
        score -= 0.75 * gomoku_window_score(board, move, other)
        candidate = (score, -move, "threat-shape")
        if best is None or candidate > best:
            best = candidate
    if best is None:
        return None, "finish"
    return -best[1], best[2]


def codex_board_move(game_key: str, board: tuple[str, ...], turn: str) -> tuple[int | None, str]:
    if game_key == "reversi":
        return codex_reversi_move(board, turn)
    if game_key == "go":
        return codex_go_move(board, turn)
    return codex_gomoku_move(board, turn)


def play_board_codex_game(
    game_key: str,
    difficulty: str,
    *,
    codex_color: str,
    seed: int,
    max_plies: int,
) -> dict[str, Any]:
    random.seed(seed)
    board = board_arena.initial_board(game_key)
    turn = "black"
    history: list[dict[str, Any]] = []
    illegal: list[dict[str, Any]] = []
    pass_count = 0
    winner_color = ""
    reason = "max_plies"
    started = time.perf_counter()
    for ply in range(1, max_plies + 1):
        actor = "codex" if turn == codex_color else "ai"
        if actor == "codex":
            move, why = codex_board_move(game_key, board, turn)
            action = "pass" if move is None else "move"
            decision = {"action": action, "move": move, "reason": why}
        else:
            ai_decision = choose_ai_board_move(game_key, board, turn, difficulty)
            action = str(ai_decision.get("action") or "")
            move_payload = ai_decision.get("move") if isinstance(ai_decision.get("move"), dict) else {}
            move = move_payload.get("index")
            decision = ai_decision
        if action in {"pass", "finish"}:
            pass_count += 1
            history.append({"ply": ply, "turn": turn, "actor": actor, "action": action, "decision": decision})
            if action == "finish" or pass_count >= 2:
                reason = action if action == "finish" else "double-pass"
                break
            turn = board_ai_service.opponent(turn)
            continue
        if move is None or int(move) not in board_arena.legal_moves(game_key, board, turn):
            illegal.append({"ply": ply, "actor": actor, "turn": turn, "move": move, "decision": decision})
            winner_color = board_ai_service.opponent(turn)
            reason = "illegal-move"
            break
        move = int(move)
        next_board, meta = board_arena.apply_board_move(game_key, board, move, turn)
        if next_board is None:
            illegal.append({"ply": ply, "actor": actor, "turn": turn, "move": move, "meta": meta, "decision": decision})
            winner_color = board_ai_service.opponent(turn)
            reason = "apply-failed"
            break
        board = next_board
        pass_count = 0
        history.append({
            "ply": ply,
            "turn": turn,
            "actor": actor,
            "action": "move",
            "move": move,
            "move_label": move_label(game_key, move),
            "decision": decision,
        })
        if game_key == "gomoku" and meta.get("made_five"):
            winner_color = turn
            reason = "five-in-row"
            break
        if game_key == "reversi" and not board_arena.legal_moves("reversi", board, "black") and not board_arena.legal_moves("reversi", board, "white"):
            reason = "reversi-terminal"
            break
        turn = board_ai_service.opponent(turn)
    black_score, white_score = board_arena.score_board(game_key, board)
    if not winner_color:
        if black_score > white_score:
            winner_color = "black"
        elif white_score > black_score:
            winner_color = "white"
    result = "draw"
    if winner_color == codex_color:
        result = "codex_win"
    elif winner_color:
        result = "ai_win"
    return {
        "game_key": game_key,
        "game_label": GAME_LABELS[game_key],
        "difficulty": difficulty,
        "difficulty_label": DIFFICULTY_LABELS[difficulty],
        "codex_color": codex_color,
        "result": result,
        "winner_color": winner_color,
        "reason": reason,
        "plies": len(history),
        "black_score": black_score,
        "white_score": white_score,
        "illegal": illegal,
        "elapsed_ms": round((time.perf_counter() - started) * 1000.0, 3),
        "moves": history,
    }


def state_from_chess_board(board: chess.Board) -> dict[str, str]:
    state = {chess.square_name(square): piece.symbol() for square, piece in board.piece_map().items()}
    state[FEN_KEY] = board.fen()
    return state


def chess_move_uci(move: dict[str, Any] | None) -> str:
    if not move:
        return ""
    return f"{move.get('from')}{move.get('to')}{move.get('promotion') or ''}"


def material_score(board: chess.Board, color: chess.Color) -> int:
    total = 0
    for piece in board.piece_map().values():
        value = PIECE_VALUES.get(piece.piece_type, 0)
        total += value if piece.color == color else -value
    return total


def max_opponent_capture_value(board: chess.Board, color: chess.Color) -> int:
    values = []
    for reply in board.legal_moves:
        if not board.is_capture(reply):
            continue
        captured = board.piece_at(reply.to_square)
        if captured and captured.color == color:
            values.append(PIECE_VALUES.get(captured.piece_type, 0))
    return max(values or [0])


def codex_chess_move(board: chess.Board) -> tuple[chess.Move | None, str]:
    color = board.turn
    legal = list(board.legal_moves)
    if not legal:
        return None, "no-legal-move"
    best: tuple[float, str, chess.Move] | None = None
    center = {chess.D4, chess.E4, chess.D5, chess.E5, chess.C4, chess.F4, chess.C5, chess.F5}
    for move in legal:
        before_piece = board.piece_at(move.from_square)
        captured = board.piece_at(move.to_square)
        trial = board.copy(stack=False)
        san = board.san(move)
        trial.push(move)
        score = float(material_score(trial, color))
        if trial.is_checkmate():
            score += 100000.0
        if board.gives_check(move):
            score += 45.0
        if captured:
            score += PIECE_VALUES.get(captured.piece_type, 0) * 0.35
        if move.promotion:
            score += PIECE_VALUES.get(move.promotion, 0) - PIECE_VALUES[chess.PAWN]
        if before_piece and before_piece.piece_type in {chess.KNIGHT, chess.BISHOP}:
            home_ranks = {chess.WHITE: 0, chess.BLACK: 7}
            if chess.square_rank(move.from_square) == home_ranks[color]:
                score += 24.0
        if move.to_square in center:
            score += 18.0
        if board.is_castling(move):
            score += 60.0
        if trial.is_check():
            score += 10.0
        if trial.outcome(claim_draw=True) and trial.outcome(claim_draw=True).winner is False:
            score -= 5.0
        if any(reply_board_is_mate(trial, reply, not color) for reply in list(trial.legal_moves)[:80]):
            score -= 100000.0
        score -= max_opponent_capture_value(trial, color) * 0.45
        candidate = (score, san, move)
        if best is None or candidate > best:
            best = candidate
    assert best is not None
    return best[2], "material/development/tactical-safety"


def reply_board_is_mate(board: chess.Board, move: chess.Move, color: chess.Color) -> bool:
    if board.turn != color:
        return False
    trial = board.copy(stack=False)
    trial.push(move)
    return trial.is_checkmate()


def choose_ai_chess_move(board: chess.Board, difficulty: str, move_history: list[dict[str, Any]] | None = None) -> tuple[chess.Move | None, dict[str, Any]]:
    side = "white" if board.turn == chess.WHITE else "black"
    random.seed(stable_seed("ai-chess", board.fen(), difficulty))
    state = state_from_chess_board(board)
    if move_history is not None:
        state["__move_history__"] = [
            {
                "from": str(item.get("uci") or "")[:2],
                "to": str(item.get("uci") or "")[2:4],
                "promotion": str(item.get("uci") or "")[4:] or None,
            }
            for item in move_history
            if len(str(item.get("uci") or "")) >= 4
        ]
    raw = game_routes.choose_computer_move(state, side, difficulty)
    uci = chess_move_uci(raw)
    info = dict(raw or {})
    info["uci"] = uci
    try:
        move = chess.Move.from_uci(uci)
    except Exception as exc:
        info["invalid"] = f"bad-uci:{type(exc).__name__}: {exc}"
        return None, info
    if move not in board.legal_moves:
        info["invalid"] = "not-legal"
        return None, info
    return move, info


def play_chess_codex_game(
    difficulty: str,
    *,
    codex_color_name: str,
    seed: int,
    max_plies: int | None,
) -> dict[str, Any]:
    random.seed(seed)
    board = chess.Board()
    codex_color = chess.WHITE if codex_color_name == "white" else chess.BLACK
    history: list[dict[str, Any]] = []
    invalid: list[dict[str, Any]] = []
    started = time.perf_counter()
    for ply in count(1):
        if max_plies is not None and ply > max_plies:
            break
        if board.is_game_over(claim_draw=True):
            break
        if max_plies is None and ply > 1 and ply % 100 == 0:
            progress(f"chess full-game progress difficulty={difficulty} codex={codex_color_name} ply={ply}")
        actor = "codex" if board.turn == codex_color else "ai"
        before = board.fen()
        if actor == "codex":
            move, reason = codex_chess_move(board)
            info = {"uci": move.uci() if move else "", "reason": reason}
        else:
            move, info = choose_ai_chess_move(board, difficulty, history)
        if move is None:
            invalid.append({"ply": ply, "actor": actor, "fen": before, "decision": info})
            break
        san = board.san(move)
        board.push(move)
        history.append({"ply": ply, "actor": actor, "uci": move.uci(), "san": san, "fen_before": before, "fen_after": board.fen(), "decision": info})
    outcome = board.outcome(claim_draw=True)
    winner = ""
    reason = "incomplete"
    result = "draw"
    if invalid:
        reason = "invalid-move"
        result = "ai_win" if invalid[-1]["actor"] == "codex" else "codex_win"
    elif outcome:
        reason = str(outcome.termination.name).lower()
        if outcome.winner is None:
            result = "draw"
        elif outcome.winner == codex_color:
            winner = codex_color_name
            result = "codex_win"
        else:
            winner = "black" if codex_color_name == "white" else "white"
            result = "ai_win"
    else:
        if max_plies is None:
            reason = "unterminated"
        else:
            reason = "material_at_ply_cap"
        material = material_score(board, codex_color)
        if material > 120:
            result = "codex_win"
            winner = codex_color_name
        elif material < -120:
            result = "ai_win"
            winner = "black" if codex_color_name == "white" else "white"
        reason = "material_at_ply_cap"
    return {
        "game_key": "chess",
        "game_label": GAME_LABELS["chess"],
        "difficulty": difficulty,
        "difficulty_label": DIFFICULTY_LABELS[difficulty],
        "codex_color": codex_color_name,
        "result": result,
        "winner_color": winner,
        "reason": reason,
        "complete_game": bool(outcome) or bool(invalid),
        "plies": len(history),
        "final_fen": board.fen(),
        "codex_material_cp": material_score(board, codex_color),
        "invalid": invalid,
        "elapsed_ms": round((time.perf_counter() - started) * 1000.0, 3),
        "moves": history,
    }


def summarize(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    buckets: dict[str, dict[str, Any]] = {}
    for row in rows:
        key = f"{row['game_key']}::{row['difficulty']}"
        bucket = buckets.setdefault(key, {
            "game_key": row["game_key"],
            "game_label": row["game_label"],
            "difficulty": row["difficulty"],
            "difficulty_label": row["difficulty_label"],
            "games": 0,
            "codex_wins": 0,
            "draws": 0,
            "ai_wins": 0,
            "score": 0.0,
            "avg_plies": 0.0,
            "avg_elapsed_ms": 0.0,
            "_plies": 0,
            "_elapsed": 0.0,
        })
        bucket["games"] += 1
        result = row.get("result")
        if result == "codex_win":
            bucket["codex_wins"] += 1
            bucket["score"] += 1.0
        elif result == "draw":
            bucket["draws"] += 1
            bucket["score"] += 0.5
        else:
            bucket["ai_wins"] += 1
        bucket["_plies"] += int(row.get("plies") or 0)
        bucket["_elapsed"] += float(row.get("elapsed_ms") or 0.0)
    out = []
    for bucket in buckets.values():
        games = max(1, int(bucket["games"]))
        bucket["codex_score_rate"] = round(bucket["score"] / games, 4)
        bucket["avg_plies"] = round(bucket.pop("_plies") / games, 2)
        bucket["avg_elapsed_ms"] = round(bucket.pop("_elapsed") / games, 3)
        out.append(bucket)
    return sorted(out, key=lambda item: (item["game_key"], item["difficulty"]))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Codex reviewer games against every hackme_web game AI difficulty.")
    parser.add_argument("--games-per-ai", type=int, default=5)
    parser.add_argument("--seed", type=int, default=20260513)
    parser.add_argument("--reversi-max-plies", type=int, default=64)
    parser.add_argument("--go-max-plies", type=int, default=14)
    parser.add_argument("--gomoku-max-plies", type=int, default=24)
    parser.add_argument("--chess-max-plies", type=int, default=50)
    parser.add_argument("--chess-complete-games", action="store_true", help="For chess, ignore --chess-max-plies and play until checkmate or a chess draw condition.")
    parser.add_argument("--output", default=str(ROOT / "docs" / "games" / "2026-05-13_game_ai_codex_play_eval.json"))
    parser.add_argument("--jsonl-output", default=str(ROOT / "docs" / "games" / "2026-05-13_game_ai_codex_play_replays.jsonl"))
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    rows: list[dict[str, Any]] = []
    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    jsonl_path = Path(args.jsonl_output)
    jsonl_path.parent.mkdir(parents=True, exist_ok=True)
    chess_max_plies = None if args.chess_complete_games else int(args.chess_max_plies)
    max_plies = {
        "reversi": int(args.reversi_max_plies),
        "go": int(args.go_max_plies),
        "gomoku": int(args.gomoku_max_plies),
        "chess": chess_max_plies,
    }
    games_per_ai = max(1, int(args.games_per_ai))

    def write_checkpoint(stage: str, *, complete: bool = False) -> None:
        artifact = {
            "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
            "seed": int(args.seed),
            "stage": stage,
            "complete": bool(complete),
            "method": {
                "games_per_ai": games_per_ai,
                "codex_policy": "transparent heuristic reviewer policy; no external engines; not a human rating oracle",
                "max_plies": max_plies,
                "chess_complete_games": bool(args.chess_complete_games),
            },
            "summary": summarize(rows),
            "games": rows,
        }
        out_path.write_text(json.dumps(artifact, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        jsonl_payload = "\n".join(json.dumps(row, ensure_ascii=False, sort_keys=True) for row in rows)
        jsonl_path.write_text((jsonl_payload + "\n") if jsonl_payload else "", encoding="utf-8")
        progress(f"checkpoint wrote {out_path} stage={stage}")

    for game_key in ("reversi", "go", "gomoku"):
        for difficulty in BOARD_DIFFICULTIES:
            for game_no in range(1, games_per_ai + 1):
                codex_color = "black" if game_no % 2 == 1 else "white"
                progress(f"{game_key} {difficulty} game={game_no}/{games_per_ai} codex={codex_color}")
                rows.append(play_board_codex_game(
                    game_key,
                    difficulty,
                    codex_color=codex_color,
                    seed=stable_seed(args.seed, game_key, difficulty, game_no),
                    max_plies=max_plies[game_key],
                ))
                write_checkpoint(f"{game_key}:{difficulty}:game-{game_no}")
    for difficulty in CHESS_DIFFICULTIES:
        for game_no in range(1, games_per_ai + 1):
            codex_color = "white" if game_no % 2 == 1 else "black"
            progress(f"chess {difficulty} game={game_no}/{games_per_ai} codex={codex_color}")
            rows.append(play_chess_codex_game(
                difficulty,
                codex_color_name=codex_color,
                seed=stable_seed(args.seed, "chess", difficulty, game_no),
                max_plies=chess_max_plies,
            ))
            write_checkpoint(f"chess:{difficulty}:game-{game_no}")
    write_checkpoint("complete", complete=True)
    print(out_path)
    return 0


def progress(message: str) -> None:
    sys.stderr.write(f"[game-ai-codex-play] {message}\n")
    sys.stderr.flush()


if __name__ == "__main__":
    raise SystemExit(main())
