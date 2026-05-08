"""Engine-backed chess helpers for the experimental self-learning difficulty."""

from __future__ import annotations

import chess
from datetime import datetime
from pathlib import Path
import os
import sqlite3

from services.games.chess import (
    initial_board,
    move_to_uci,
    opponent,
    to_chess_board,
    validate_move,
)
from services.games.chess_model_registry import bundled_seed_database_path, runtime_model_path
from services.games.chess_search import ZobristHasher, opening_sanity_filter, search_best_move
from services.server.runtime import default_runtime_root_path


EXPERIMENT_DIFFICULTY = "experiment"
DEFAULT_CHESS_ENGINE_DB_NAME = "chess_experiment.db"
_INFINITY = 10 ** 9
_MATE_SCORE = 10 ** 7
_SEARCH_PROFILES = {
    "fast": {"depth": 2, "time_budget_ms": 120},
    "balanced": {"depth": 2, "time_budget_ms": 260},
    "strong": {"depth": 3, "time_budget_ms": 900},
}
_PIECE_VALUES = {
    chess.PAWN: 100,
    chess.KNIGHT: 320,
    chess.BISHOP: 330,
    chess.ROOK: 500,
    chess.QUEEN: 900,
    chess.KING: 20000,
}
_PIECE_SQUARE = {
    chess.PAWN: [
        0, 0, 0, 0, 0, 0, 0, 0,
        5, 10, 10, -20, -20, 10, 10, 5,
        5, -5, -10, 0, 0, -10, -5, 5,
        0, 0, 0, 20, 20, 0, 0, 0,
        5, 5, 10, 25, 25, 10, 5, 5,
        10, 10, 20, 30, 30, 20, 10, 10,
        50, 50, 50, 50, 50, 50, 50, 50,
        0, 0, 0, 0, 0, 0, 0, 0,
    ],
    chess.KNIGHT: [
        -50, -40, -30, -30, -30, -30, -40, -50,
        -40, -20, 0, 5, 5, 0, -20, -40,
        -30, 5, 10, 15, 15, 10, 5, -30,
        -30, 0, 15, 20, 20, 15, 0, -30,
        -30, 5, 15, 20, 20, 15, 5, -30,
        -30, 0, 10, 15, 15, 10, 0, -30,
        -40, -20, 0, 0, 0, 0, -20, -40,
        -50, -40, -30, -30, -30, -30, -40, -50,
    ],
    chess.BISHOP: [
        -20, -10, -10, -10, -10, -10, -10, -20,
        -10, 5, 0, 0, 0, 0, 5, -10,
        -10, 10, 10, 10, 10, 10, 10, -10,
        -10, 0, 10, 10, 10, 10, 0, -10,
        -10, 5, 5, 10, 10, 5, 5, -10,
        -10, 0, 5, 10, 10, 5, 0, -10,
        -10, 0, 0, 0, 0, 0, 0, -10,
        -20, -10, -10, -10, -10, -10, -10, -20,
    ],
    chess.ROOK: [
        0, 0, 0, 5, 5, 0, 0, 0,
        -5, 0, 0, 0, 0, 0, 0, -5,
        -5, 0, 0, 0, 0, 0, 0, -5,
        -5, 0, 0, 0, 0, 0, 0, -5,
        -5, 0, 0, 0, 0, 0, 0, -5,
        -5, 0, 0, 0, 0, 0, 0, -5,
        5, 10, 10, 10, 10, 10, 10, 5,
        0, 0, 0, 0, 0, 0, 0, 0,
    ],
    chess.QUEEN: [
        -20, -10, -10, -5, -5, -10, -10, -20,
        -10, 0, 0, 0, 0, 0, 0, -10,
        -10, 0, 5, 5, 5, 5, 0, -10,
        -5, 0, 5, 5, 5, 5, 0, -5,
        0, 0, 5, 5, 5, 5, 0, -5,
        -10, 5, 5, 5, 5, 5, 0, -10,
        -10, 0, 5, 0, 0, 0, 0, -10,
        -20, -10, -10, -5, -5, -10, -10, -20,
    ],
    chess.KING: [
        -30, -40, -40, -50, -50, -40, -40, -30,
        -30, -40, -40, -50, -50, -40, -40, -30,
        -30, -40, -40, -50, -50, -40, -40, -30,
        -30, -40, -40, -50, -50, -40, -40, -30,
        -20, -30, -30, -40, -40, -30, -30, -20,
        -10, -20, -20, -20, -20, -20, -20, -10,
        20, 20, 0, 0, 0, 0, 20, 20,
        20, 30, 10, 0, 0, 10, 30, 20,
    ],
}


def default_chess_engine_db_path():
    return runtime_model_path(DEFAULT_CHESS_ENGINE_DB_NAME, env_var="HTML_LEARNING_CHESS_ENGINE_DB_PATH")


def bundled_chess_engine_db_path() -> Path:
    return bundled_seed_database_path(DEFAULT_CHESS_ENGINE_DB_NAME)


def _open_store_conn(db_path):
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=15)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA busy_timeout = 15000")
    except Exception:
        pass
    ensure_chess_engine_schema(conn)
    return conn


class ChessExperimentStore:
    """Persist experiment difficulty learning data outside the main app DB."""

    def __init__(self, db_path=None):
        self.db_path = Path(db_path or default_chess_engine_db_path())

    def connect(self):
        return _open_store_conn(self.db_path)

    def choose_move(self, board_state, side, *, difficulty=EXPERIMENT_DIFFICULTY):
        conn = self.connect()
        try:
            return _choose_experiment_move_with_conn(board_state, side, conn=conn, difficulty=difficulty)
        finally:
            conn.close()

    def record_learning(self, row, *, winner_color):
        conn = self.connect()
        try:
            updated = _record_experiment_learning_with_conn(conn, row, winner_color=winner_color)
            conn.commit()
            return updated
        finally:
            conn.close()


def ensure_chess_engine_schema(conn):
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS game_chess_engine_memory (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            position_key TEXT NOT NULL,
            side TEXT NOT NULL,
            move_uci TEXT NOT NULL,
            sample_count INTEGER NOT NULL DEFAULT 0,
            win_count INTEGER NOT NULL DEFAULT 0,
            draw_count INTEGER NOT NULL DEFAULT 0,
            loss_count INTEGER NOT NULL DEFAULT 0,
            score_total INTEGER NOT NULL DEFAULT 0,
            updated_at TEXT NOT NULL,
            UNIQUE(position_key, side, move_uci)
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_game_chess_engine_memory_lookup "
        "ON game_chess_engine_memory(position_key, side, sample_count DESC, updated_at DESC)"
    )


def position_key(board):
    ep = chess.square_name(board.ep_square) if board.ep_square is not None else "-"
    return f"{board.board_fen()} {'w' if board.turn else 'b'} {board.castling_xfen()} {ep}"


def _mirror(square, color):
    return chess.square_mirror(square) if color == chess.BLACK else square


def _material_and_position_score(board):
    score = 0
    for square, piece in board.piece_map().items():
        base = _PIECE_VALUES[piece.piece_type]
        table = _PIECE_SQUARE[piece.piece_type][_mirror(square, piece.color)]
        contribution = base + table
        score += contribution if piece.color == chess.WHITE else -contribution
    return score


def _mobility_score(board):
    turn = board.turn
    legal_count = board.legal_moves.count()
    board.turn = not turn
    reply_count = board.legal_moves.count()
    board.turn = turn
    sign = 1 if turn == chess.WHITE else -1
    return sign * (legal_count - reply_count) * 4


def _static_eval(board):
    if board.is_checkmate():
        return -_MATE_SCORE if board.turn == chess.WHITE else _MATE_SCORE
    if board.is_stalemate() or board.is_insufficient_material():
        return 0
    score = _material_and_position_score(board)
    score += _mobility_score(board)
    if board.is_check():
        score += -35 if board.turn == chess.WHITE else 35
    return score


def _load_learning_bias(conn, board, side):
    if conn is None:
        return {}
    ensure_chess_engine_schema(conn)
    rows = conn.execute(
        """
        SELECT move_uci, sample_count, win_count, draw_count, loss_count, score_total
        FROM game_chess_engine_memory
        WHERE position_key=? AND side=?
        """,
        (position_key(board), side),
    ).fetchall()
    bias = {}
    for row in rows:
        samples = max(1, int(row["sample_count"] or 0))
        average = int(row["score_total"] or 0) / samples
        reliability = min(samples, 12)
        bias[str(row["move_uci"])] = int(round(average * 18 + reliability * 2))
    return bias


def _move_order(board, move, learning_bias):
    captured = board.piece_at(move.to_square)
    capture_score = _PIECE_VALUES.get(captured.piece_type, 0) if captured else 0
    moving = board.piece_at(move.from_square)
    move_score = capture_score * 10
    if moving:
        move_score -= _PIECE_VALUES.get(moving.piece_type, 0) // 20
    if move.promotion:
        move_score += _PIECE_VALUES.get(move.promotion, 0) * 8
    if board.gives_check(move):
        move_score += 45
    move_score += learning_bias.get(move.uci(), 0)
    return move_score


def _resolve_search_profile(profile: str | None, difficulty: str) -> dict:
    normalized = str(profile or "balanced").strip().lower()
    selected = dict(_SEARCH_PROFILES.get(normalized) or _SEARCH_PROFILES["balanced"])
    if difficulty != EXPERIMENT_DIFFICULTY:
        selected["depth"] = min(int(selected["depth"]), 2)
    return selected


def _choose_experiment_move_with_conn(board_state, side, *, conn=None, difficulty=EXPERIMENT_DIFFICULTY, search_profile="balanced"):
    board = to_chess_board(board_state, side)
    if board.turn != (chess.WHITE if side == "white" else chess.BLACK):
        board.turn = chess.WHITE if side == "white" else chess.BLACK
    if board.is_game_over():
        return None
    profile = _resolve_search_profile(search_profile, difficulty)
    depth = int(profile["depth"])
    bias_cache = {}

    def learning_bias_for(current_board, current_side):
        key = (position_key(current_board), current_side)
        cached = bias_cache.get(key)
        if cached is not None:
            return cached
        cached = _load_learning_bias(conn, current_board, current_side)
        bias_cache[key] = cached
        return cached

    def move_order_fn(current_board, move, _ply):
        current_side = "white" if current_board.turn == chess.WHITE else "black"
        return _move_order(current_board, move, learning_bias_for(current_board, current_side))

    search = search_best_move(
        board,
        max_depth=depth,
        evaluate=_static_eval,
        move_order_fn=move_order_fn,
        hasher=ZobristHasher(seed=20260518),
        time_budget_ms=profile.get("time_budget_ms"),
    )
    best_move = search.best_move
    ai_color = chess.WHITE if side == "white" else chess.BLACK
    color_sign = 1 if ai_color == chess.WHITE else -1

    def sanity_move_score(move: chess.Move) -> int:
        score = move_order_fn(board, move, 0)
        if board.is_capture(move):
            captured = board.piece_at(move.to_square)
            if captured is not None:
                score += _PIECE_VALUES.get(captured.piece_type, 0) * 2
        after = board.copy(stack=False)
        after.push(move)
        if after.is_checkmate():
            return 9_000_000
        return score + color_sign * _static_eval(after)

    best_move = opening_sanity_filter(board, best_move, score_move=sanity_move_score)
    root_learning_bias = learning_bias_for(board, side)
    if root_learning_bias:
        best_bias_uci, best_bias_value = max(
            root_learning_bias.items(),
            key=lambda item: (item[1], item[0]),
        )
        current_bias_value = root_learning_bias.get(best_move.uci(), 0) if best_move is not None else 0
        try:
            biased_move = chess.Move.from_uci(best_bias_uci)
        except Exception:
            biased_move = None
        if biased_move in board.legal_moves and best_bias_value >= 60 and best_bias_value > current_bias_value:
            best_move = biased_move
    if best_move is None:
        return None
    piece = board.piece_at(best_move.from_square)
    captured = board.piece_at(best_move.to_square)
    if board.is_en_passant(best_move):
        capture_square = chess.square(chess.square_file(best_move.to_square), chess.square_rank(best_move.from_square))
        captured = board.piece_at(capture_square)
    return {
        "from": chess.square_name(best_move.from_square),
        "to": chess.square_name(best_move.to_square),
        "piece": piece.symbol() if piece else "",
        "captured": captured.symbol() if captured else None,
        "promotion": chess.piece_symbol(best_move.promotion) if best_move.promotion else None,
        "castle": bool(board.is_castling(best_move)),
        "en_passant": bool(board.is_en_passant(best_move)),
    }


def choose_experiment_move(board_state, side, *, conn=None, store=None, difficulty=EXPERIMENT_DIFFICULTY, search_profile="balanced"):
    if conn is not None:
        return _choose_experiment_move_with_conn(board_state, side, conn=conn, difficulty=difficulty, search_profile=search_profile)
    if store is not None:
        if search_profile == "balanced":
            return store.choose_move(board_state, side, difficulty=difficulty)
        store_conn = store.connect()
        try:
            return _choose_experiment_move_with_conn(board_state, side, conn=store_conn, difficulty=difficulty, search_profile=search_profile)
        finally:
            store_conn.close()
    return _choose_experiment_move_with_conn(board_state, side, conn=None, difficulty=difficulty, search_profile=search_profile)


def _outcome_bucket(ai_side, winner_color):
    if winner_color == ai_side:
        return "win", 6
    if winner_color is None:
        return "draw", 1
    return "loss", -5


def _record_experiment_learning_with_conn(conn, row, *, winner_color):
    difficulty = str(row["computer_difficulty"] or "").strip().lower()
    if difficulty != EXPERIMENT_DIFFICULTY or row["mode"] != "computer":
        return 0
    ensure_chess_engine_schema(conn)
    history = row["move_history_json"]
    if not history:
        return 0
    import json

    try:
        moves = json.loads(history)
    except Exception:
        return 0
    if not isinstance(moves, list) or not moves:
        return 0
    human_side = row["human_side"] if "human_side" in row.keys() else "white"
    ai_side = opponent(human_side)
    bucket, score_delta = _outcome_bucket(ai_side, winner_color)
    initial_fen = str(row["initial_fen"] if "initial_fen" in row.keys() else "").strip()
    board = {"__fen__": initial_fen} if initial_fen else initial_board()
    updated = 0
    for entry in moves:
        mover = str((entry or {}).get("by") or "").strip().lower()
        from_square = str((entry or {}).get("from") or "").strip().lower()
        to_square = str((entry or {}).get("to") or "").strip().lower()
        promotion = (entry or {}).get("promotion")
        if mover not in {"white", "black"} or len(from_square) != 2 or len(to_square) != 2:
            continue
        if mover == ai_side:
            board_obj = to_chess_board(board, mover)
            move_uci = move_to_uci(board, from_square, to_square, promotion, mover)
            now = datetime.now().isoformat()
            existing = conn.execute(
                "SELECT id, sample_count, win_count, draw_count, loss_count, score_total FROM game_chess_engine_memory "
                "WHERE position_key=? AND side=? AND move_uci=?",
                (position_key(board_obj), mover, move_uci),
            ).fetchone()
            if existing:
                conn.execute(
                    """
                    UPDATE game_chess_engine_memory
                    SET sample_count=?, win_count=?, draw_count=?, loss_count=?, score_total=?, updated_at=?
                    WHERE id=?
                    """,
                    (
                        int(existing["sample_count"] or 0) + 1,
                        int(existing["win_count"] or 0) + (1 if bucket == "win" else 0),
                        int(existing["draw_count"] or 0) + (1 if bucket == "draw" else 0),
                        int(existing["loss_count"] or 0) + (1 if bucket == "loss" else 0),
                        int(existing["score_total"] or 0) + score_delta,
                        now,
                        existing["id"],
                    ),
                )
            else:
                conn.execute(
                    """
                    INSERT INTO game_chess_engine_memory (
                        position_key, side, move_uci, sample_count, win_count, draw_count,
                        loss_count, score_total, updated_at
                    ) VALUES (?, ?, ?, 1, ?, ?, ?, ?, ?)
                    """,
                    (
                        position_key(board_obj),
                        mover,
                        move_uci,
                        1 if bucket == "win" else 0,
                        1 if bucket == "draw" else 0,
                        1 if bucket == "loss" else 0,
                        score_delta,
                        now,
                    ),
                )
            updated += 1
        try:
            board = validate_move(board, mover, from_square, to_square, promotion)["board"]
        except ValueError:
            break
    return updated


def record_experiment_learning(row, *, winner_color, conn=None, store=None):
    if conn is not None:
        return _record_experiment_learning_with_conn(conn, row, winner_color=winner_color)
    if store is not None:
        return store.record_learning(row, winner_color=winner_color)
    return 0
