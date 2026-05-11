"""Policy/value-backed helpers for the ``experiment 4:PV`` chess difficulty.

This module is the pragmatic final-phase prototype:

- better board encoding than the move-feature-only NN/DL engines
- a dual-head model with policy prior + value estimation
- integration with the shared alpha-beta search stack
- a deterministic root MCTS/PUCT decision mode for the policy/value route

It deliberately stays CPU-friendly and JSON-serializable so it fits the
current Python repo without introducing heavyweight external dependencies.
"""

from __future__ import annotations

import json
import math
import os
import random
from datetime import datetime
from pathlib import Path

import chess

from services.games.chess import initial_board, move_to_uci, opponent, to_chess_board, validate_move
from services.games.chess_nn import _candidate_features, _clip
from services.games.chess_search import ZobristHasher, search_best_move
from services.games.chess_model_registry import bundled_seed_model_path, runtime_model_path


EXPERIMENT_PV_DIFFICULTY = "experiment 4:pv"
DEFAULT_CHESS_PV_MODEL_NAME = "chess_experiment_4_pv.json"
_BOARD_INPUT_SIZE = 12 * 64 + 1 + 4 + 8
_MOVE_INPUT_SIZE = 49
_SHARED_HIDDEN_SIZE = 96
_LEARNING_RATE = 0.008
_MAX_ABS_WEIGHT = 4.0
_PV_VERSION = 1
_SEARCH_DEPTH = 2
_SEARCH_QUIESCENCE_DEPTH = 4
_SEARCH_PROFILES = {
    "fast": {"depth": 1, "quiescence_depth": 1, "time_budget_ms": 150},
    "balanced": {"depth": 2, "quiescence_depth": 2, "time_budget_ms": 340},
    "strong": {"depth": 2, "quiescence_depth": 4, "time_budget_ms": 1100},
}
_MCTS_SIMULATIONS = {
    "fast": 32,
    "balanced": 72,
    "strong": 160,
}
_CONTRASTIVE_NEGATIVE_TARGET = -0.45
_CONTRASTIVE_MAX_NEGATIVES = 32
_MOVE_MEMORY_LEARNING_RATE = 0.22
_MAX_MOVE_MEMORY_BIAS = 1.4
_INVARIANCE_MEMORY_LEARNING_RATE = 0.08
_MAX_INVARIANCE_MEMORY_BIAS = 0.85
_POLICY_OVERRIDE_MIN_SCORE = 0.95
_POLICY_OVERRIDE_MIN_MARGIN = 0.20
_FUSION_MODES = {
    "strict_search": {"policy_weight": 0, "min_score": 1.20, "min_margin": 9.0},
    "balanced_fusion": {"policy_weight": 45, "min_score": 0.88, "min_margin": 0.02},
    "policy_preferred": {"policy_weight": 120, "min_score": 0.82, "min_margin": 0.01},
}
_VALUE_SCORE_SCALE = 180.0
_PIECE_VALUES = {
    chess.PAWN: 100,
    chess.KNIGHT: 320,
    chess.BISHOP: 335,
    chess.ROOK: 500,
    chess.QUEEN: 900,
    chess.KING: 20000,
}
_WHITE_KNIGHT_STARTS = {chess.B1, chess.G1}
_BLACK_KNIGHT_STARTS = {chess.B8, chess.G8}
_WHITE_BISHOP_STARTS = {chess.C1, chess.F1}
_BLACK_BISHOP_STARTS = {chess.C8, chess.F8}
_WHITE_ROOK_STARTS = {chess.A1, chess.H1}
_BLACK_ROOK_STARTS = {chess.A8, chess.H8}
_WHITE_QUEEN_START = chess.D1
_BLACK_QUEEN_START = chess.D8
_WHITE_KING_HOME = chess.E1
_BLACK_KING_HOME = chess.E8
_WHITE_CASTLED_SQUARES = {chess.G1, chess.C1}
_BLACK_CASTLED_SQUARES = {chess.G8, chess.C8}
_CENTER_SQUARES = {chess.D4, chess.E4, chess.D5, chess.E5}
_HOME_PAWN_RANKS = {chess.WHITE: 1, chess.BLACK: 6}
_HOME_MINOR_RANKS = {chess.WHITE: 0, chess.BLACK: 7}


def default_chess_pv_model_path() -> Path:
    return runtime_model_path(DEFAULT_CHESS_PV_MODEL_NAME, env_var="HTML_LEARNING_CHESS_ENGINE_PV_MODEL_PATH")


def bundled_chess_pv_model_path() -> Path:
    return bundled_seed_model_path(DEFAULT_CHESS_PV_MODEL_NAME)


def _now() -> str:
    return datetime.now().isoformat()


def _random_matrix(rows: int, cols: int, *, rng: random.Random) -> list[list[float]]:
    return [[rng.uniform(-0.05, 0.05) for _ in range(cols)] for _ in range(rows)]


def experiment_pv_model_template() -> dict:
    rng = random.Random(20260508)
    return {
        "version": _PV_VERSION,
        "architecture": "board-planes-policy-value-781x96",
        "board_input_size": _BOARD_INPUT_SIZE,
        "move_input_size": _MOVE_INPUT_SIZE,
        "shared_hidden_size": _SHARED_HIDDEN_SIZE,
        "shared_w": _random_matrix(_SHARED_HIDDEN_SIZE, _BOARD_INPUT_SIZE, rng=rng),
        "shared_b": [rng.uniform(-0.01, 0.01) for _ in range(_SHARED_HIDDEN_SIZE)],
        "value_w": [rng.uniform(-0.05, 0.05) for _ in range(_SHARED_HIDDEN_SIZE)],
        "value_b": rng.uniform(-0.01, 0.01),
        "policy_shared_w": [rng.uniform(-0.05, 0.05) for _ in range(_SHARED_HIDDEN_SIZE)],
        "policy_move_w": [rng.uniform(-0.05, 0.05) for _ in range(_MOVE_INPUT_SIZE)],
        "policy_b": rng.uniform(-0.01, 0.01),
        "policy_move_memory": {},
        "policy_invariance_memory": {},
        "sample_count": 0,
        "updated_at": _now(),
    }


def _normalize_float_vector(values, expected_len: int) -> list[float] | None:
    if not isinstance(values, list) or len(values) != expected_len:
        return None
    try:
        return [float(value) for value in values]
    except Exception:
        return None


def _normalize_float_matrix(values, rows: int, cols: int) -> list[list[float]] | None:
    if not isinstance(values, list) or len(values) != rows:
        return None
    matrix: list[list[float]] = []
    for row in values:
        normalized = _normalize_float_vector(row, cols)
        if normalized is None:
            return None
        matrix.append(normalized)
    return matrix


def normalize_experiment_pv_model_payload(model: dict) -> dict | None:
    if not isinstance(model, dict):
        return None
    if int(model.get("version") or 0) != _PV_VERSION:
        return None
    if int(model.get("board_input_size") or 0) != _BOARD_INPUT_SIZE:
        return None
    if int(model.get("move_input_size") or 0) != _MOVE_INPUT_SIZE:
        return None
    if int(model.get("shared_hidden_size") or 0) != _SHARED_HIDDEN_SIZE:
        return None
    shared_w = _normalize_float_matrix(model.get("shared_w"), _SHARED_HIDDEN_SIZE, _BOARD_INPUT_SIZE)
    shared_b = _normalize_float_vector(model.get("shared_b"), _SHARED_HIDDEN_SIZE)
    value_w = _normalize_float_vector(model.get("value_w"), _SHARED_HIDDEN_SIZE)
    policy_shared_w = _normalize_float_vector(model.get("policy_shared_w"), _SHARED_HIDDEN_SIZE)
    policy_move_w = _normalize_float_vector(model.get("policy_move_w"), _MOVE_INPUT_SIZE)
    if any(item is None for item in (shared_w, shared_b, value_w, policy_shared_w, policy_move_w)):
        return None
    try:
        value_b = float(model.get("value_b"))
        policy_b = float(model.get("policy_b"))
    except Exception:
        return None
    return {
        "version": _PV_VERSION,
        "architecture": "board-planes-policy-value-781x96",
        "board_input_size": _BOARD_INPUT_SIZE,
        "move_input_size": _MOVE_INPUT_SIZE,
        "shared_hidden_size": _SHARED_HIDDEN_SIZE,
        "shared_w": shared_w,
        "shared_b": shared_b,
        "value_w": value_w,
        "value_b": value_b,
        "policy_shared_w": policy_shared_w,
        "policy_move_w": policy_move_w,
        "policy_b": policy_b,
        "policy_move_memory": {
            str(key): _clip(float(value), -_MAX_MOVE_MEMORY_BIAS, _MAX_MOVE_MEMORY_BIAS)
            for key, value in (model.get("policy_move_memory") or {}).items()
            if isinstance(key, str)
        },
        "policy_invariance_memory": {
            str(key): _clip(float(value), -_MAX_INVARIANCE_MEMORY_BIAS, _MAX_INVARIANCE_MEMORY_BIAS)
            for key, value in (model.get("policy_invariance_memory") or {}).items()
            if isinstance(key, str)
        },
        "sample_count": max(0, int(model.get("sample_count") or 0)),
        "updated_at": str(model.get("updated_at") or _now()),
    }


def _load_model(model_path: Path) -> dict:
    path = Path(model_path)
    if not path.exists():
        return experiment_pv_model_template()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return experiment_pv_model_template()
    normalized = normalize_experiment_pv_model_payload(payload)
    return normalized or experiment_pv_model_template()


def _save_model(model_path: Path, model: dict) -> None:
    path = Path(model_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(json.dumps(model, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    tmp_path.replace(path)


def _board_planes(board: chess.Board) -> list[float]:
    features = [0.0] * _BOARD_INPUT_SIZE
    for square, piece in board.piece_map().items():
        piece_index = (0 if piece.color == chess.WHITE else 6) + piece.piece_type - 1
        features[piece_index * 64 + square] = 1.0
    cursor = 12 * 64
    features[cursor] = 1.0 if board.turn == chess.WHITE else 0.0
    cursor += 1
    features[cursor] = 1.0 if board.has_kingside_castling_rights(chess.WHITE) else 0.0
    features[cursor + 1] = 1.0 if board.has_queenside_castling_rights(chess.WHITE) else 0.0
    features[cursor + 2] = 1.0 if board.has_kingside_castling_rights(chess.BLACK) else 0.0
    features[cursor + 3] = 1.0 if board.has_queenside_castling_rights(chess.BLACK) else 0.0
    cursor += 4
    if board.ep_square is not None:
        features[cursor + chess.square_file(board.ep_square)] = 1.0
    return features


def _forward_shared(model: dict, board_features: list[float]) -> list[float]:
    hidden: list[float] = []
    for row, bias in zip(model["shared_w"], model["shared_b"]):
        total = float(bias)
        for weight, feature in zip(row, board_features):
            total += float(weight) * float(feature)
        hidden.append(math.tanh(total))
    return hidden


def _value_from_hidden(model: dict, hidden: list[float]) -> float:
    total = float(model["value_b"])
    for weight, value in zip(model["value_w"], hidden):
        total += float(weight) * float(value)
    return math.tanh(total)


def _policy_from_hidden(model: dict, hidden: list[float], move_features: list[float]) -> float:
    total = float(model["policy_b"])
    for weight, value in zip(model["policy_shared_w"], hidden):
        total += float(weight) * float(value)
    for weight, feature in zip(model["policy_move_w"], move_features):
        total += float(weight) * float(feature)
    return math.tanh(total)


def _move_memory_key(board: chess.Board, side: str, move_uci: str) -> str:
    return f"{board.board_fen()} {board.turn} {board.castling_rights} {board.ep_square}|{side}|{move_uci}"


def _move_memory_bias(model: dict, board: chess.Board, side: str, move_uci: str) -> float:
    memory = model.get("policy_move_memory") or {}
    try:
        return float(memory.get(_move_memory_key(board, side, move_uci)) or 0.0)
    except Exception:
        return 0.0


def _invariance_memory_key(side: str, move_uci: str) -> str:
    return f"{side}|{move_uci}"


def _invariance_memory_bias(model: dict, side: str, move_uci: str) -> float:
    memory = model.get("policy_invariance_memory") or {}
    try:
        return float(memory.get(_invariance_memory_key(side, move_uci)) or 0.0)
    except Exception:
        return 0.0


def _policy_score_for_move(model: dict, hidden: list[float], board: chess.Board, move: chess.Move, side: str) -> float:
    base = _policy_from_hidden(model, hidden, _candidate_move_features(board, move, side))
    return _clip(base + _move_memory_bias(model, board, side, move.uci()) + _invariance_memory_bias(model, side, move.uci()), -1.0, 1.0)


def _update_move_memory(model: dict, board: chess.Board, side: str, move: chess.Move, target: float) -> None:
    memory = model.setdefault("policy_move_memory", {})
    key = _move_memory_key(board, side, move.uci())
    current = float(memory.get(key) or 0.0)
    memory[key] = _clip(current + _MOVE_MEMORY_LEARNING_RATE * float(target), -_MAX_MOVE_MEMORY_BIAS, _MAX_MOVE_MEMORY_BIAS)


def _update_invariance_memory(model: dict, side: str, move: chess.Move, target: float) -> None:
    memory = model.setdefault("policy_invariance_memory", {})
    key = _invariance_memory_key(side, move.uci())
    current = float(memory.get(key) or 0.0)
    memory[key] = _clip(
        current + _INVARIANCE_MEMORY_LEARNING_RATE * float(target),
        -_MAX_INVARIANCE_MEMORY_BIAS,
        _MAX_INVARIANCE_MEMORY_BIAS,
    )


def _policy_rank_rows(model: dict, board: chess.Board, side: str) -> list[dict]:
    hidden = _forward_shared(model, _board_planes(board))
    rows: list[dict] = []
    for move in sorted(board.legal_moves, key=lambda item: item.uci()):
        raw_policy = _policy_score_for_move(model, hidden, board, move, side)
        development = _move_development_bias(board, move)
        rows.append(
            {
                "move": move.uci(),
                "raw_policy_score": round(raw_policy, 8),
                "legal_move_bonus_penalty": int(development),
                "move_order_score": int(raw_policy * 1000.0) + int(development),
            }
        )
    if not rows:
        return []
    max_score = max(float(row["raw_policy_score"]) for row in rows)
    denom = sum(math.exp(float(row["raw_policy_score"]) - max_score) for row in rows)
    ranked_raw = sorted(rows, key=lambda row: (-float(row["raw_policy_score"]), str(row["move"])))
    ranked_order = sorted(rows, key=lambda row: (-int(row["move_order_score"]), str(row["move"])))
    raw_rank = {str(row["move"]): index for index, row in enumerate(ranked_raw, start=1)}
    order_rank = {str(row["move"]): index for index, row in enumerate(ranked_order, start=1)}
    for row in rows:
        row["policy_probability"] = round(math.exp(float(row["raw_policy_score"]) - max_score) / denom, 8) if denom else 0.0
        row["raw_policy_rank"] = raw_rank[str(row["move"])]
        row["move_order_rank"] = order_rank[str(row["move"])]
    return sorted(rows, key=lambda row: (int(row["raw_policy_rank"]), str(row["move"])))


def rank_experiment_pv_policy_moves(board_state, side: str, *, model_path=None) -> list[dict]:
    board = to_chess_board(board_state, side)
    ai_color = chess.WHITE if side == "white" else chess.BLACK
    if board.turn != ai_color:
        board.turn = ai_color
    if board.is_game_over():
        return []
    model = _load_model(Path(model_path or default_chess_pv_model_path()))
    return _policy_rank_rows(model, board, side)


def _material_balance(board: chess.Board) -> int:
    score = 0
    for piece in board.piece_map().values():
        value = _PIECE_VALUES[piece.piece_type]
        score += value if piece.color == chess.WHITE else -value
    return score


def _mobility_balance(board: chess.Board) -> int:
    current_turn = board.turn
    current_mobility = board.legal_moves.count()
    board.turn = not current_turn
    try:
        other_mobility = board.legal_moves.count()
    finally:
        board.turn = current_turn
    return int((current_mobility - other_mobility) * 4 if current_turn == chess.WHITE else (other_mobility - current_mobility) * 4)


def _side_minor_development(board: chess.Board, color: bool) -> int:
    knight_starts = _WHITE_KNIGHT_STARTS if color == chess.WHITE else _BLACK_KNIGHT_STARTS
    bishop_starts = _WHITE_BISHOP_STARTS if color == chess.WHITE else _BLACK_BISHOP_STARTS
    developed = 0
    for square in knight_starts:
        piece = board.piece_at(square)
        if piece is None or piece.color != color or piece.piece_type != chess.KNIGHT:
            developed += 1
    for square in bishop_starts:
        piece = board.piece_at(square)
        if piece is None or piece.color != color or piece.piece_type != chess.BISHOP:
            developed += 1
    return developed


def _file_is_open_for_rook(board: chess.Board, square: int) -> bool:
    file_index = chess.square_file(square)
    for rank_index in range(8):
        occupant = board.piece_at(chess.square(file_index, rank_index))
        if occupant and occupant.piece_type == chess.PAWN:
            return False
    return True


def _development_balance(board: chess.Board) -> int:
    score = 0
    white_developed = _side_minor_development(board, chess.WHITE)
    black_developed = _side_minor_development(board, chess.BLACK)
    score += (white_developed - black_developed) * 36

    for square in _CENTER_SQUARES:
        piece = board.piece_at(square)
        if piece and piece.piece_type in {chess.PAWN, chess.KNIGHT, chess.BISHOP}:
            score += 14 if piece.color == chess.WHITE else -14

    white_king_square = board.king(chess.WHITE)
    black_king_square = board.king(chess.BLACK)
    if white_king_square in _WHITE_CASTLED_SQUARES:
        score += 46
    elif white_king_square == _WHITE_KING_HOME and white_developed >= 2:
        score -= 20
    if black_king_square in _BLACK_CASTLED_SQUARES:
        score -= 46
    elif black_king_square == _BLACK_KING_HOME and black_developed >= 2:
        score += 20

    opening_phase = board.fullmove_number <= 12
    if not opening_phase:
        return score

    for square in chess.SquareSet(board.pieces(chess.ROOK, chess.WHITE)):
        if square not in _WHITE_ROOK_STARTS and white_king_square not in _WHITE_CASTLED_SQUARES:
            score -= 150 if not _file_is_open_for_rook(board, square) else 95
    for square in chess.SquareSet(board.pieces(chess.ROOK, chess.BLACK)):
        if square not in _BLACK_ROOK_STARTS and black_king_square not in _BLACK_CASTLED_SQUARES:
            score += 150 if not _file_is_open_for_rook(board, square) else 95

    white_queen_square = next(iter(board.pieces(chess.QUEEN, chess.WHITE)), None)
    black_queen_square = next(iter(board.pieces(chess.QUEEN, chess.BLACK)), None)
    if white_queen_square is not None and white_queen_square != _WHITE_QUEEN_START and white_developed < 2:
        score -= 18
    if black_queen_square is not None and black_queen_square != _BLACK_QUEEN_START and black_developed < 2:
        score += 18
    return score


def _value_scale_for_phase(board: chess.Board) -> float:
    if board.fullmove_number <= 4:
        return 24.0
    if board.fullmove_number <= 8:
        return 54.0
    if board.fullmove_number <= 14:
        return 96.0
    return _VALUE_SCORE_SCALE


def _resolve_search_profile(profile: str | None) -> dict:
    normalized = str(profile or "balanced").strip().lower()
    return dict(_SEARCH_PROFILES.get(normalized) or _SEARCH_PROFILES["balanced"])


def _move_development_bias(board: chess.Board, move: chess.Move) -> int:
    piece = board.piece_at(move.from_square)
    if piece is None:
        return 0
    score = 0
    opening_phase = board.fullmove_number <= 12
    if board.is_castling(move):
        score += 280
    if piece.piece_type in {chess.KNIGHT, chess.BISHOP}:
        starts = (
            _WHITE_KNIGHT_STARTS if piece.piece_type == chess.KNIGHT and piece.color == chess.WHITE else
            _BLACK_KNIGHT_STARTS if piece.piece_type == chess.KNIGHT else
            _WHITE_BISHOP_STARTS if piece.color == chess.WHITE else
            _BLACK_BISHOP_STARTS
        )
        if move.from_square in starts:
            score += 120
        if move.to_square in _CENTER_SQUARES:
            score += 35
    if not opening_phase:
        return score
    if piece.piece_type == chess.ROOK and not board.is_capture(move) and not board.gives_check(move):
        score -= 950 if move.from_square in (_WHITE_ROOK_STARTS | _BLACK_ROOK_STARTS) else 540
    if piece.piece_type == chess.QUEEN:
        developed = _side_minor_development(board, piece.color)
        if developed < 2 and not board.is_capture(move) and not board.gives_check(move):
            score -= 140
    if piece.piece_type == chess.KING and not board.is_castling(move):
        score -= 120
    if piece.piece_type == chess.PAWN and move.to_square in _CENTER_SQUARES:
        score += 28
    return score


def _opening_principle_score(board: chess.Board, move: chess.Move) -> int:
    if board.fullmove_number > 8:
        return 0
    piece = board.piece_at(move.from_square)
    if piece is None:
        return 0
    from_file = chess.square_file(move.from_square)
    from_rank = chess.square_rank(move.from_square)
    to_file = chess.square_file(move.to_square)
    to_rank = chess.square_rank(move.to_square)
    advance = abs(to_rank - from_rank)
    score = 0
    if piece.piece_type == chess.PAWN:
        if from_file in {chess.FILE_NAMES.index("d"), chess.FILE_NAMES.index("e")}:
            score += 1450 if advance == 2 and from_rank == _HOME_PAWN_RANKS[piece.color] else 520
        elif from_file == chess.FILE_NAMES.index("c"):
            score += 1300 if advance == 2 and from_rank == _HOME_PAWN_RANKS[piece.color] else 430
        elif from_file in {chess.FILE_NAMES.index("a"), chess.FILE_NAMES.index("h")}:
            score -= 900
        elif from_file in {chess.FILE_NAMES.index("b"), chess.FILE_NAMES.index("g")}:
            score -= 380
        elif from_file == chess.FILE_NAMES.index("f"):
            score -= 180
    elif piece.piece_type == chess.KNIGHT:
        if from_rank == _HOME_MINOR_RANKS[piece.color]:
            score += 920
        if move.to_square in _CENTER_SQUARES or to_file in {chess.FILE_NAMES.index("c"), chess.FILE_NAMES.index("f")}:
            score += 180
    elif piece.piece_type == chess.BISHOP:
        if from_rank == _HOME_MINOR_RANKS[piece.color]:
            score += 700
        if to_file in {
            chess.FILE_NAMES.index("b"),
            chess.FILE_NAMES.index("c"),
            chess.FILE_NAMES.index("e"),
            chess.FILE_NAMES.index("g"),
        }:
            score += 90
    elif piece.piece_type == chess.QUEEN and board.fullmove_number <= 5 and not board.is_capture(move) and not board.gives_check(move):
        score -= 500
    elif piece.piece_type == chess.ROOK and board.fullmove_number <= 10 and not board.is_castling(move):
        score -= 700
    if board.is_castling(move):
        score += 780
    if board.is_capture(move):
        score += 160
    if board.gives_check(move):
        score += 120
    return score


def _opening_principle_fallback(board: chess.Board, best_move: chess.Move | None) -> chess.Move | None:
    if best_move is None or board.fullmove_number > 8:
        return best_move
    legal = sorted(board.legal_moves, key=lambda item: item.uci())
    if not legal:
        return best_move
    principled = max(legal, key=lambda move: (_opening_principle_score(board, move), move.uci()))
    if _opening_principle_score(board, principled) >= _opening_principle_score(board, best_move) + 500:
        return principled
    return best_move


def _is_early_quiet_rook_move(board: chess.Board, move: chess.Move) -> bool:
    piece = board.piece_at(move.from_square)
    if piece is None or piece.piece_type != chess.ROOK:
        return False
    if board.fullmove_number > 10:
        return False
    if board.is_capture(move) or board.gives_check(move) or board.is_castling(move):
        return False
    king_square = board.king(piece.color)
    castled_squares = _WHITE_CASTLED_SQUARES if piece.color == chess.WHITE else _BLACK_CASTLED_SQUARES
    return king_square not in castled_squares


def _sanity_move_score(
    board: chess.Board,
    move: chess.Move,
    *,
    ai_color: bool,
    model: dict,
    eval_cache: dict[int, int],
    hasher: ZobristHasher,
) -> int:
    score = _move_development_bias(board, move) + _opening_principle_score(board, move)
    if board.is_capture(move):
        captured = board.piece_at(move.to_square)
        if captured is not None:
            score += _PIECE_VALUES.get(captured.piece_type, 0) * 2
    after = board.copy(stack=False)
    after.push(move)
    if after.is_checkmate():
        return 9_000_000
    color_sign = 1 if ai_color == chess.WHITE else -1
    score += color_sign * _pv_static_eval(after, model, eval_cache, hasher)
    return score


def _opening_sanity_fallback(
    board: chess.Board,
    *,
    ai_color: bool,
    best_move: chess.Move,
    model: dict,
    eval_cache: dict[int, int],
    hasher: ZobristHasher,
) -> chess.Move:
    if not _is_early_quiet_rook_move(board, best_move):
        return best_move
    alternatives = [move for move in board.legal_moves if not _is_early_quiet_rook_move(board, move)]
    if not alternatives:
        return best_move
    return max(
        alternatives,
        key=lambda move: (_sanity_move_score(board, move, ai_color=ai_color, model=model, eval_cache=eval_cache, hasher=hasher), move.uci()),
    )


def _adaptive_policy_thresholds(*, fusion_mode: str, decision_context: dict | None = None) -> dict:
    mode = str(fusion_mode or "balanced_fusion")
    base = dict(_FUSION_MODES.get(mode) or _FUSION_MODES["balanced_fusion"])
    context = decision_context or {}
    difficulty = str(context.get("variant_difficulty") or "")
    prior_stable = bool(context.get("prior_retention_stable", True))
    confidence = float(context.get("deterministic_confidence") or 0.75)
    if difficulty == "hard":
        base["min_score"] += 0.04
        base["min_margin"] += 0.03
    elif difficulty in {"exact", "easy", "medium"}:
        base["min_score"] -= 0.02
        base["min_margin"] -= 0.01
    if not prior_stable:
        base["min_score"] += 0.08
        base["min_margin"] += 0.08
    if confidence >= 0.75:
        base["min_score"] -= 0.02
        base["min_margin"] -= 0.01
    return {
        "min_score": round(max(0.0, float(base["min_score"])), 4),
        "min_margin": round(max(0.0, float(base["min_margin"])), 4),
        "policy_weight": int(base["policy_weight"]),
        "fusion_mode": mode,
        "variant_difficulty": difficulty,
        "prior_retention_stable": prior_stable,
        "deterministic_confidence": round(confidence, 4),
    }


def _policy_override_info(model: dict, board: chess.Board, side: str, *, fusion_mode: str = "balanced_fusion", decision_context: dict | None = None) -> dict:
    rows = _policy_rank_rows(model, board, side)
    thresholds = _adaptive_policy_thresholds(fusion_mode=fusion_mode, decision_context=decision_context)
    if len(rows) < 2:
        return {"used": False, "reason": "insufficient_legal_moves", "thresholds": thresholds}
    top = rows[0]
    runner_up = rows[1]
    margin = float(top.get("raw_policy_score") or 0.0) - float(runner_up.get("raw_policy_score") or 0.0)
    info = {
        "used": False,
        "move": str(top.get("move") or ""),
        "raw_policy_score": round(float(top.get("raw_policy_score") or 0.0), 8),
        "runner_up_move": str(runner_up.get("move") or ""),
        "runner_up_raw_policy_score": round(float(runner_up.get("raw_policy_score") or 0.0), 8),
        "margin": round(margin, 8),
        "thresholds": thresholds,
        "reason": "below_override_threshold",
    }
    if str(thresholds.get("fusion_mode")) == "strict_search":
        info["reason"] = "strict_search_disables_policy_override"
        return info
    if float(top.get("raw_policy_score") or 0.0) < float(thresholds["min_score"]) or margin < float(thresholds["min_margin"]):
        return info
    try:
        move = chess.Move.from_uci(str(top.get("move") or ""))
    except Exception:
        info["reason"] = "invalid_policy_move"
        return info
    if move not in board.legal_moves:
        info["reason"] = "illegal_policy_move"
        return info
    info["used"] = True
    info["reason"] = "adaptive_policy_score_and_margin_met_threshold"
    return info


def _policy_override_move(model: dict, board: chess.Board, side: str, *, fusion_mode: str = "balanced_fusion", decision_context: dict | None = None) -> chess.Move | None:
    info = _policy_override_info(model, board, side, fusion_mode=fusion_mode, decision_context=decision_context)
    if not bool(info.get("used")):
        return None
    return chess.Move.from_uci(str(info.get("move") or ""))


def _pv_static_eval(board: chess.Board, model: dict, eval_cache: dict[int, int], hasher: ZobristHasher) -> int:
    board_hash = hasher.hash_board(board)
    cached = eval_cache.get(board_hash)
    if cached is not None:
        return cached
    board_features = _board_planes(board)
    hidden = _forward_shared(model, board_features)
    value_score = _value_from_hidden(model, hidden)
    score = _material_balance(board)
    score += _mobility_balance(board)
    score += _development_balance(board)
    if board.is_check():
        score += -30 if board.turn == chess.WHITE else 30
    score += int(value_score * _value_scale_for_phase(board))
    eval_cache[board_hash] = score
    return score


def _policy_value_mcts_root_analysis(
    board: chess.Board,
    *,
    model: dict,
    side: str,
    profile_name: str,
    hasher: ZobristHasher,
    eval_cache: dict[int, int],
) -> dict:
    legal = sorted(board.legal_moves, key=lambda item: item.uci())
    if not legal:
        return {"best_move": None, "stats": [], "simulations": 0}
    hidden = _forward_shared(model, _board_planes(board))
    priors: dict[str, float] = {}
    for move in legal:
        raw = _policy_score_for_move(model, hidden, board, move, side)
        priors[move.uci()] = math.exp(float(raw))
    prior_total = sum(priors.values()) or 1.0
    for move_uci in list(priors):
        priors[move_uci] = priors[move_uci] / prior_total

    color_sign = 1 if board.turn == chess.WHITE else -1
    stats = {
        move.uci(): {
            "move": move,
            "visits": 0,
            "total": 0.0,
            "prior": float(priors.get(move.uci()) or 0.0),
        }
        for move in legal
    }
    simulations = int(_MCTS_SIMULATIONS.get(str(profile_name or "balanced"), _MCTS_SIMULATIONS["balanced"]))
    exploration = 1.25
    for _index in range(max(1, simulations)):
        total_visits = sum(int(row["visits"]) for row in stats.values())

        def select_score(row: dict) -> tuple[float, str]:
            visits = int(row["visits"])
            average = float(row["total"]) / visits if visits else 0.0
            prior_bonus = exploration * float(row["prior"]) * math.sqrt(total_visits + 1.0) / (1.0 + visits)
            return average + prior_bonus, str(row["move"].uci())

        selected = max(stats.values(), key=select_score)
        move = selected["move"]
        after = board.copy(stack=False)
        after.push(move)
        if after.is_checkmate():
            value = 1_000_000.0
        else:
            value = float(color_sign * _pv_static_eval(after, model, eval_cache, hasher))
        value += float(_move_development_bias(board, move) * 10)
        value += float(_opening_principle_score(board, move) * 4)
        piece = board.piece_at(move.from_square)
        if board.fullmove_number <= 4 and piece and piece.piece_type == chess.PAWN:
            from_file = chess.square_file(move.from_square)
            if from_file in {chess.FILE_NAMES.index("d"), chess.FILE_NAMES.index("e")}:
                value += 420.0
            elif from_file in {chess.FILE_NAMES.index("a"), chess.FILE_NAMES.index("b"), chess.FILE_NAMES.index("g"), chess.FILE_NAMES.index("h")}:
                value -= 320.0
        selected["visits"] = int(selected["visits"]) + 1
        selected["total"] = float(selected["total"]) + value

    def final_score(row: dict) -> tuple[float, int, str]:
        visits = int(row["visits"])
        average = float(row["total"]) / visits if visits else -1_000_000.0
        policy_bonus = float(row["prior"]) * 35.0
        return average + policy_bonus, visits, str(row["move"].uci())

    rows = []
    for row in stats.values():
        visits = int(row["visits"])
        q_value = float(row["total"]) / visits if visits else -1_000_000.0
        score, _visits, _uci = final_score(row)
        rows.append(
            {
                "move": row["move"].uci(),
                "mcts_prior": round(float(row["prior"]), 8),
                "mcts_visit_count": visits,
                "mcts_q_value": round(q_value, 4),
                "mcts_final_score": round(float(score), 4),
            }
        )
    rows.sort(key=lambda item: (-float(item["mcts_final_score"]), -int(item["mcts_visit_count"]), str(item["move"])))
    best = rows[0]["move"] if rows else ""
    return {
        "best_move": chess.Move.from_uci(best) if best else None,
        "best_move_uci": best,
        "stats": rows,
        "simulations": max(1, simulations),
    }


def _policy_value_mcts_move(
    board: chess.Board,
    *,
    model: dict,
    side: str,
    profile_name: str,
    hasher: ZobristHasher,
    eval_cache: dict[int, int],
) -> chess.Move | None:
    return _policy_value_mcts_root_analysis(
        board,
        model=model,
        side=side,
        profile_name=profile_name,
        hasher=hasher,
        eval_cache=eval_cache,
    )["best_move"]


def _candidate_move_features(board: chess.Board, move: chess.Move, side: str) -> list[float]:
    before = board.copy(stack=False)
    after = before.copy(stack=False)
    after.push(move)
    return _candidate_features(before, move, after, side)


def choose_experiment_pv_move(
    board_state,
    side: str,
    *,
    model_path=None,
    search_profile="balanced",
    fusion_mode="balanced_fusion",
    decision_context=None,
    decision_mode="alpha_beta",
):
    board = to_chess_board(board_state, side)
    ai_color = chess.WHITE if side == "white" else chess.BLACK
    if board.turn != ai_color:
        board.turn = ai_color
    if board.is_game_over():
        return None
    forced_mates: list[chess.Move] = []
    for move in board.legal_moves:
        board.push(move)
        if board.is_checkmate():
            forced_mates.append(move)
        board.pop()
    if forced_mates:
        best_move = sorted(forced_mates, key=lambda mv: mv.uci())[0]
    else:
        model = _load_model(Path(model_path or default_chess_pv_model_path()))
        hasher = ZobristHasher(seed=20260521)
        eval_cache: dict[int, int] = {}
        profile_name = str(search_profile or "balanced").strip().lower()
        profile = _resolve_search_profile(profile_name)
        hidden_cache: dict[int, list[float]] = {}

        def move_order_fn(current_board: chess.Board, move: chess.Move, _ply: int) -> int:
            current_side = "white" if current_board.turn == chess.WHITE else "black"
            board_hash = hasher.hash_board(current_board)
            hidden = hidden_cache.get(board_hash)
            if hidden is None:
                board_features = _board_planes(current_board)
                hidden = _forward_shared(model, board_features)
                hidden_cache[board_hash] = hidden
            score = int(_policy_score_for_move(model, hidden, current_board, move, current_side) * 1000.0)
            score += _move_development_bias(current_board, move)
            score += _opening_principle_score(current_board, move)
            return score

        if str(decision_mode or "alpha_beta").strip().lower() == "mcts":
            best_move = _policy_value_mcts_move(
                board,
                model=model,
                side=side,
                profile_name=profile_name,
                hasher=hasher,
                eval_cache=eval_cache,
            )
        else:
            search = search_best_move(
                board,
                max_depth=profile["depth"],
                evaluate=lambda current_board: _pv_static_eval(current_board, model, eval_cache, hasher),
                move_order_fn=move_order_fn,
                hasher=hasher,
                quiescence_depth=profile["quiescence_depth"],
                time_budget_ms=profile.get("time_budget_ms"),
            )
            best_move = search.best_move
        if best_move is not None:
            best_move = _opening_sanity_fallback(
                board,
                ai_color=ai_color,
                best_move=best_move,
                model=model,
                eval_cache=eval_cache,
                hasher=hasher,
            )
            best_move = _opening_principle_fallback(board, best_move)
        policy_override = _policy_override_move(model, board, side, fusion_mode=fusion_mode, decision_context=decision_context)
        if policy_override is not None and (
            best_move is None
            or _opening_principle_score(board, policy_override) + 500 >= _opening_principle_score(board, best_move)
        ):
            best_move = policy_override
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


def explain_experiment_pv_decision(
    board_state,
    side: str,
    *,
    model_path=None,
    search_profile="fast",
    watched_moves=None,
    fusion_mode="balanced_fusion",
    decision_context=None,
    decision_mode="alpha_beta",
) -> dict:
    board = to_chess_board(board_state, side)
    ai_color = chess.WHITE if side == "white" else chess.BLACK
    if board.turn != ai_color:
        board.turn = ai_color
    watched = {str(item or "").lower() for item in (watched_moves or []) if str(item or "").strip()}
    model_path = Path(model_path or default_chess_pv_model_path())
    if board.is_game_over():
        return {"supported": True, "chosen_move": "", "chosen_reason": "game_over", "moves": []}
    model = _load_model(model_path)
    hasher = ZobristHasher(seed=20260521)
    eval_cache: dict[int, int] = {}
    profile = _resolve_search_profile(search_profile)
    policy_rows = {str(row["move"]): row for row in _policy_rank_rows(model, board, side)}
    forced_mates = []
    for move in board.legal_moves:
        board.push(move)
        if board.is_checkmate():
            forced_mates.append(move)
        board.pop()
    if forced_mates:
        chosen = sorted(forced_mates, key=lambda item: item.uci())[0]
        search_score = 9_000_000
        search_depth = 0
        chosen_reason = "forced_mate"
    else:
        def move_order_fn(current_board: chess.Board, move: chess.Move, _ply: int) -> int:
            current_side = "white" if current_board.turn == chess.WHITE else "black"
            hidden = _forward_shared(model, _board_planes(current_board))
            raw = _policy_score_for_move(model, hidden, current_board, move, current_side)
            return int(raw * 1000.0) + _move_development_bias(current_board, move)

        mcts_analysis = {"stats": [], "simulations": 0}
        if str(decision_mode or "alpha_beta").strip().lower() == "mcts":
            mcts_analysis = _policy_value_mcts_root_analysis(
                board,
                model=model,
                side=side,
                profile_name=str(search_profile or "fast").strip().lower(),
                hasher=hasher,
                eval_cache=eval_cache,
            )
            chosen = mcts_analysis["best_move"]
            search_score = 0
            search_depth = 0
            chosen_reason = "policy_value_mcts"
        else:
            search = search_best_move(
                board,
                max_depth=profile["depth"],
                evaluate=lambda current_board: _pv_static_eval(current_board, model, eval_cache, hasher),
                move_order_fn=move_order_fn,
                hasher=hasher,
                quiescence_depth=profile["quiescence_depth"],
                time_budget_ms=profile.get("time_budget_ms"),
            )
            chosen = search.best_move
            search_score = int(search.score)
            search_depth = int(search.depth)
            chosen_reason = "search_best_move"
        fallback = _opening_sanity_fallback(
            board,
            ai_color=ai_color,
            best_move=chosen,
            model=model,
            eval_cache=eval_cache,
            hasher=hasher,
        ) if chosen is not None else None
        if fallback is not None and chosen is not None and fallback != chosen:
            chosen = fallback
            chosen_reason = "opening_sanity_fallback"
        principled = _opening_principle_fallback(board, chosen)
        if principled is not None and chosen is not None and principled != chosen:
            chosen = principled
            chosen_reason = "opening_principle_fallback"
        policy_override = _policy_override_info(model, board, side, fusion_mode=fusion_mode, decision_context=decision_context)
        if policy_override.get("used"):
            override_move = chess.Move.from_uci(str(policy_override.get("move")))
            if chosen is None or _opening_principle_score(board, override_move) + 500 >= _opening_principle_score(board, chosen):
                chosen = override_move
                chosen_reason = "high_confidence_policy_override"
    color_sign = 1 if ai_color == chess.WHITE else -1
    thresholds = _adaptive_policy_thresholds(fusion_mode=fusion_mode, decision_context=decision_context)
    policy_weight = int(thresholds.get("policy_weight") or 0)
    moves = []
    max_child_depth = max(0, int(profile["depth"]) - 1)
    mcts_stats_by_move = {
        str(row.get("move") or ""): row
        for row in (mcts_analysis.get("stats") if "mcts_analysis" in locals() else []) or []
    }
    for move in sorted(board.legal_moves, key=lambda item: item.uci()):
        after = board.copy(stack=False)
        after.push(move)
        static_eval_score = int(color_sign * _pv_static_eval(after, model, eval_cache, hasher))
        mcts_row = mcts_stats_by_move.get(move.uci()) or {}
        if str(decision_mode or "alpha_beta").strip().lower() == "mcts":
            # Root MCTS already evaluated all legal moves; avoid an extra alpha-beta
            # search per candidate when this function is used for audit reports.
            per_move_search = int(float(mcts_row.get("mcts_final_score") or static_eval_score))
        elif after.is_checkmate():
            per_move_search = 9_000_000
        elif max_child_depth <= 0:
            per_move_search = static_eval_score
        else:
            child = search_best_move(
                after,
                max_depth=max_child_depth,
                evaluate=lambda current_board: _pv_static_eval(current_board, model, eval_cache, hasher),
                hasher=hasher,
                quiescence_depth=profile["quiescence_depth"],
                time_budget_ms=max(20, int(profile.get("time_budget_ms") or 0) // max(1, board.legal_moves.count())),
            )
            per_move_search = -int(child.score)
        policy = dict(policy_rows.get(move.uci()) or {"move": move.uci()})
        policy["static_eval_score"] = static_eval_score
        policy["search_score"] = int(per_move_search)
        policy.update(mcts_row)
        policy["opening_principle_score"] = int(_opening_principle_score(board, move))
        policy["fused_score"] = round(
            float(per_move_search)
            + float(policy.get("raw_policy_score") or 0.0) * policy_weight
            + float(policy["opening_principle_score"]),
            4,
        )
        policy["final_combined_score"] = policy["fused_score"]
        policy["override_applied"] = bool(policy_override.get("used") and str(policy_override.get("move") or "") == move.uci()) if "policy_override" in locals() else False
        policy["override_reason"] = str((policy_override if "policy_override" in locals() else {}).get("reason") or "")
        policy["chosen"] = bool(chosen is not None and move == chosen)
        moves.append(policy)
    moves = sorted(moves, key=lambda row: (-float(row.get("final_combined_score") or 0), str(row.get("move") or "")))
    if watched:
        watched_moves_rows = [row for row in moves if str(row.get("move") or "") in watched]
    else:
        watched_moves_rows = moves[:5]
    chosen_move = chosen.uci() if chosen is not None else ""
    chosen_row = next((row for row in moves if str(row.get("move") or "") == chosen_move), None)
    return {
        "supported": True,
        "model_path": str(model_path),
        "side": side,
        "fen": board.fen(),
        "chosen_move": chosen_move,
        "chosen_reason": chosen_reason if chosen_move else "no_legal_move",
        "search_score": search_score if chosen_move else None,
        "search_depth": search_depth if chosen_move else 0,
        "chosen_breakdown": chosen_row or {},
        "fusion_mode": str(fusion_mode or "balanced_fusion"),
        "decision_mode": str(decision_mode or "alpha_beta"),
        "mcts": (
            {**mcts_analysis, "best_move": str(mcts_analysis.get("best_move_uci") or "")}
            if "mcts_analysis" in locals()
            else {"stats": [], "simulations": 0}
        ),
        "policy_override": policy_override if "policy_override" in locals() else _policy_override_info(model, board, side, fusion_mode=fusion_mode, decision_context=decision_context),
        "watched_moves": watched_moves_rows,
        "top_final_moves": moves[:5],
        "all_legal_count": len(moves),
    }


def _train_single_sample(
    model: dict,
    board_features: list[float],
    move_features: list[float],
    *,
    value_target: float,
    policy_target: float,
    train_value: bool = True,
    train_shared: bool = True,
    train_policy_bias: bool = True,
) -> None:
    hidden = _forward_shared(model, board_features)
    value_pred = _value_from_hidden(model, hidden)
    policy_pred = _policy_from_hidden(model, hidden, move_features)

    delta_value = (float(value_target) - float(value_pred)) * (1.0 - float(value_pred) * float(value_pred)) if train_value else 0.0
    delta_policy = (float(policy_target) - float(policy_pred)) * (1.0 - float(policy_pred) * float(policy_pred))

    shared_deltas: list[float] = []
    for hidden_index, hidden_value in enumerate(hidden):
        downstream = float(model["value_w"][hidden_index]) * delta_value
        if train_shared:
            downstream += float(model["policy_shared_w"][hidden_index]) * delta_policy
        shared_deltas.append((1.0 - hidden_value * hidden_value) * downstream)

    for index, hidden_value in enumerate(hidden):
        if train_value:
            model["value_w"][index] = _clip(float(model["value_w"][index]) + _LEARNING_RATE * delta_value * hidden_value, -_MAX_ABS_WEIGHT, _MAX_ABS_WEIGHT)
        if train_shared:
            model["policy_shared_w"][index] = _clip(float(model["policy_shared_w"][index]) + _LEARNING_RATE * delta_policy * hidden_value, -_MAX_ABS_WEIGHT, _MAX_ABS_WEIGHT)
    for index, feature in enumerate(move_features):
        model["policy_move_w"][index] = _clip(float(model["policy_move_w"][index]) + _LEARNING_RATE * delta_policy * feature, -_MAX_ABS_WEIGHT, _MAX_ABS_WEIGHT)
    if train_value:
        model["value_b"] = _clip(float(model["value_b"]) + _LEARNING_RATE * delta_value, -_MAX_ABS_WEIGHT, _MAX_ABS_WEIGHT)
    if train_policy_bias:
        model["policy_b"] = _clip(float(model["policy_b"]) + _LEARNING_RATE * delta_policy, -_MAX_ABS_WEIGHT, _MAX_ABS_WEIGHT)

    if train_shared:
        for row_index, row in enumerate(model["shared_w"]):
            delta_hidden = shared_deltas[row_index]
            for col_index, feature in enumerate(board_features):
                row[col_index] = _clip(float(row[col_index]) + _LEARNING_RATE * delta_hidden * feature, -_MAX_ABS_WEIGHT, _MAX_ABS_WEIGHT)
            model["shared_b"][row_index] = _clip(float(model["shared_b"][row_index]) + _LEARNING_RATE * delta_hidden, -_MAX_ABS_WEIGHT, _MAX_ABS_WEIGHT)

    model["sample_count"] = int(model.get("sample_count") or 0) + 1
    model["updated_at"] = _now()


def build_experiment_pv_sample_from_position(
    *,
    fen: str,
    move_uci: str,
    side: str,
    target: float = 1.0,
    weight: float = 1.0,
    source: str = "external",
    hard_negatives: list[str] | None = None,
    invariance_group_id: str | None = None,
) -> dict | None:
    fen = str(fen or "").strip()
    move_uci = str(move_uci or "").strip().lower()
    side = str(side or "").strip().lower()
    if not fen or side not in {"white", "black"} or len(move_uci) < 4:
        return None
    try:
        board_before = chess.Board(fen)
        board_before.turn = chess.WHITE if side == "white" else chess.BLACK
        move = chess.Move.from_uci(move_uci)
    except Exception:
        return None
    if move not in board_before.legal_moves:
        return None
    return {
        "board_features": _board_planes(board_before),
        "move_features": _candidate_move_features(board_before, move, side),
        "fen": board_before.fen(),
        "move_uci": move.uci(),
        "side": side,
        "target": _clip(float(target), -1.0, 1.0),
        "weight": _clip(float(weight), 0.1, 3.0),
        "source": str(source or "external"),
        "hard_negatives": [str(item).strip().lower() for item in (hard_negatives or []) if str(item).strip()],
        "invariance_group_id": str(invariance_group_id or "").strip(),
    }


def normalize_experiment_pv_replay_sample(sample: dict) -> dict | None:
    if not isinstance(sample, dict):
        return None
    board_features = sample.get("board_features")
    move_features = sample.get("move_features")
    normalized_board = _normalize_float_vector(board_features, _BOARD_INPUT_SIZE) if isinstance(board_features, list) else None
    normalized_move = _normalize_float_vector(move_features, _MOVE_INPUT_SIZE) if isinstance(move_features, list) else None
    if normalized_board is None or normalized_move is None:
        return build_experiment_pv_sample_from_position(
            fen=str(sample.get("fen") or sample.get("board_fen") or "").strip(),
            move_uci=str(sample.get("move_uci") or sample.get("uci") or sample.get("move") or "").strip(),
            side=sample.get("side"),
            target=float(sample.get("target", 1.0) or 0.0),
            weight=float(sample.get("weight", 1.0) or 1.0),
            source=str(sample.get("source") or "external"),
            hard_negatives=list(sample.get("hard_negatives") or []),
            invariance_group_id=str(sample.get("invariance_group_id") or ""),
        )
    try:
        target = float(sample.get("target"))
        weight = float(sample.get("weight") or 1.0)
    except Exception:
        return None
    return {
        "board_features": normalized_board,
        "move_features": normalized_move,
        "fen": str(sample.get("fen") or sample.get("board_fen") or "").strip(),
        "move_uci": str(sample.get("move_uci") or sample.get("uci") or sample.get("move") or "").strip().lower(),
        "side": str(sample.get("side") or "").strip().lower(),
        "target": _clip(target, -1.0, 1.0),
        "weight": _clip(weight, 0.1, 3.0),
        "source": str(sample.get("source") or "external"),
        "hard_negatives": [str(item).strip().lower() for item in (sample.get("hard_negatives") or []) if str(item).strip()],
        "invariance_group_id": str(sample.get("invariance_group_id") or "").strip(),
    }


def _legal_hard_negative_moves(board: chess.Board, expected_move: chess.Move, hard_negatives: list[str]) -> list[chess.Move]:
    moves: list[chess.Move] = []
    seen: set[str] = set()
    for item in hard_negatives or []:
        try:
            move = chess.Move.from_uci(str(item or "").strip().lower())
        except Exception:
            continue
        if move == expected_move or move not in board.legal_moves or move.uci() in seen:
            continue
        seen.add(move.uci())
        moves.append(move)
    return moves


def _policy_probe_for_sample(model: dict, sample: dict) -> dict | None:
    fen = str(sample.get("fen") or "").strip()
    side = str(sample.get("side") or "").strip().lower()
    expected = str(sample.get("move_uci") or "").strip().lower()
    if not fen or side not in {"white", "black"} or not expected:
        return None
    try:
        board = chess.Board(fen)
        board.turn = chess.WHITE if side == "white" else chess.BLACK
        expected_move = chess.Move.from_uci(expected)
    except Exception:
        return None
    if expected_move not in board.legal_moves:
        return None
    rows = _policy_rank_rows(model, board, side)
    expected_row = next((row for row in rows if str(row.get("move") or "") == expected), None)
    if expected_row is None:
        return None
    top1 = str(rows[0].get("move") or "") if rows else ""
    old_row = next((row for row in rows if str(row.get("move") or "") == top1), None)
    return {
        "fen": fen,
        "side": side,
        "expected_move": expected,
        "raw_policy_top1": top1,
        "expected_move_rank": int(expected_row.get("raw_policy_rank") or 0),
        "expected_move_probability": float(expected_row.get("policy_probability") or 0.0),
        "expected_move_logit": float(expected_row.get("raw_policy_score") or 0.0),
        "old_move": top1,
        "old_move_rank": int((old_row or {}).get("raw_policy_rank") or 0),
        "margin_vs_old_move": round(float(expected_row.get("raw_policy_score") or 0.0) - float((old_row or {}).get("raw_policy_score") or 0.0), 8),
    }


def train_experiment_pv_from_replay_samples(samples: list[dict], *, model_path=None) -> dict:
    normalized_samples = []
    rejected = 0
    for item in samples or []:
        normalized = normalize_experiment_pv_replay_sample(item)
        if normalized is None:
            rejected += 1
            continue
        normalized_samples.append(normalized)
    model_path = Path(model_path or default_chess_pv_model_path())
    model = _load_model(model_path)
    probe_sample = next((sample for sample in normalized_samples if sample.get("fen") and sample.get("move_uci") and sample.get("side")), None)
    policy_probe_before = _policy_probe_for_sample(model, probe_sample or {}) if probe_sample else None
    contrastive_negative_updates = 0
    contrastive_positive_updates = 0
    hard_negative_updates = 0
    invariance_positive_updates = 0
    invariance_negative_updates = 0
    for sample in normalized_samples:
        repeat = max(1, int(round(float(sample.get("weight") or 1.0))))
        for _ in range(repeat):
            _train_single_sample(
                model,
                sample["board_features"],
                sample["move_features"],
                value_target=float(sample["target"]),
                policy_target=1.0 if float(sample["target"]) >= 0 else -0.35,
            )
            contrastive_positive_updates += 1
            fen = str(sample.get("fen") or "").strip()
            side = str(sample.get("side") or "").strip().lower()
            expected = str(sample.get("move_uci") or "").strip().lower()
            if float(sample["target"]) >= 0 and fen and side in {"white", "black"} and expected:
                try:
                    board = chess.Board(fen)
                    board.turn = chess.WHITE if side == "white" else chess.BLACK
                    expected_move = chess.Move.from_uci(expected)
                except Exception:
                    board = None
                    expected_move = None
                if board is not None and expected_move in board.legal_moves:
                    hard_negatives = _legal_hard_negative_moves(
                        board,
                        expected_move,
                        list(sample.get("hard_negatives") or []),
                    )
                    ordinary_negatives = [
                        move
                        for move in sorted(board.legal_moves, key=lambda item: item.uci())
                        if move != expected_move
                    ]
                    negatives = (hard_negatives + [move for move in ordinary_negatives if move not in hard_negatives])[: _CONTRASTIVE_MAX_NEGATIVES]
                    for negative in negatives:
                        _update_move_memory(model, board, side, negative, _CONTRASTIVE_NEGATIVE_TARGET)
                        if sample.get("invariance_group_id"):
                            _update_invariance_memory(model, side, negative, _CONTRASTIVE_NEGATIVE_TARGET)
                            invariance_negative_updates += 1
                        _train_single_sample(
                            model,
                            sample["board_features"],
                            _candidate_move_features(board, negative, side),
                            value_target=0.0,
                            policy_target=_CONTRASTIVE_NEGATIVE_TARGET,
                            train_value=False,
                            train_shared=False,
                            train_policy_bias=False,
                        )
                        contrastive_negative_updates += 1
                        if negative in hard_negatives:
                            hard_negative_updates += 1
                    for _positive_reinforcement in range(48):
                        _update_move_memory(model, board, side, expected_move, 1.0)
                        if sample.get("invariance_group_id"):
                            _update_invariance_memory(model, side, expected_move, 1.0)
                            invariance_positive_updates += 1
                        _train_single_sample(
                            model,
                            sample["board_features"],
                            sample["move_features"],
                            value_target=0.0,
                            policy_target=1.0,
                            train_value=False,
                            train_shared=False,
                            train_policy_bias=False,
                        )
                        contrastive_positive_updates += 1
    if normalized_samples:
        _save_model(model_path, model)
    policy_probe_after = _policy_probe_for_sample(model, probe_sample or {}) if probe_sample else None
    policy_probe = {
        "supported": bool(policy_probe_before and policy_probe_after),
        "before": policy_probe_before or {},
        "after": policy_probe_after or {},
    }
    if policy_probe_before and policy_probe_after:
        policy_probe.update(
            {
                "expected_rank_delta": int(policy_probe_after["expected_move_rank"]) - int(policy_probe_before["expected_move_rank"]),
                "expected_margin_delta": round(float(policy_probe_after["margin_vs_old_move"]) - float(policy_probe_before["margin_vs_old_move"]), 8),
                "raw_policy_top1_changed_to_expected": bool(policy_probe_after["raw_policy_top1"] == policy_probe_after["expected_move"]),
            }
        )
    return {
        "ok": True,
        "accepted_samples": len(normalized_samples),
        "rejected_samples": rejected,
        "model_path": str(model_path),
        "sample_count": int(model.get("sample_count") or 0),
        "training_objective": "contrastive_policy_ranking",
        "contrastive_negative_target": _CONTRASTIVE_NEGATIVE_TARGET,
        "contrastive_max_negatives": _CONTRASTIVE_MAX_NEGATIVES,
        "contrastive_positive_updates": contrastive_positive_updates,
        "contrastive_negative_updates": contrastive_negative_updates,
        "hard_negative_updates": hard_negative_updates,
        "invariance_positive_updates": invariance_positive_updates,
        "invariance_negative_updates": invariance_negative_updates,
        "policy_probe": policy_probe,
    }


def record_experiment_pv_learning(row, *, winner_color: str | None, model_path=None) -> int:
    difficulty = str(row["computer_difficulty"] or "").strip().lower()
    if difficulty != EXPERIMENT_PV_DIFFICULTY or row["mode"] != "computer":
        return 0
    history = row["move_history_json"]
    if not history:
        return 0
    try:
        moves = json.loads(history)
    except Exception:
        return 0
    if not isinstance(moves, list) or not moves:
        return 0
    human_side = row["human_side"] if "human_side" in row.keys() else "white"
    ai_side = opponent(human_side)
    target_sign = 1.0 if winner_color == ai_side else (-1.0 if winner_color and winner_color != ai_side else 0.0)
    initial_fen = str(row["initial_fen"] if "initial_fen" in row.keys() else "").strip()
    board_state = {"__fen__": initial_fen} if initial_fen else initial_board()
    model = _load_model(Path(model_path or default_chess_pv_model_path()))
    updated = 0
    total_ai_moves = sum(1 for entry in moves if str((entry or {}).get("by") or "").strip().lower() == ai_side)
    seen_ai_moves = 0

    for entry in moves:
        mover = str((entry or {}).get("by") or "").strip().lower()
        from_square = str((entry or {}).get("from") or "").strip().lower()
        to_square = str((entry or {}).get("to") or "").strip().lower()
        promotion = (entry or {}).get("promotion")
        if mover not in {"white", "black"} or len(from_square) != 2 or len(to_square) != 2:
            continue
        if mover == ai_side:
            board_before = to_chess_board(board_state, mover)
            move_uci = move_to_uci(board_state, from_square, to_square, promotion, mover)
            move = chess.Move.from_uci(move_uci)
            board_features = _board_planes(board_before)
            move_features = _candidate_move_features(board_before, move, mover)
            seen_ai_moves += 1
            progress = seen_ai_moves / max(1, total_ai_moves)
            value_target = _clip(target_sign * (0.35 + 0.65 * progress), -1.0, 1.0)
            _train_single_sample(
                model,
                board_features,
                move_features,
                value_target=value_target,
                policy_target=1.0,
            )
            alternatives = sorted([candidate for candidate in board_before.legal_moves if candidate != move], key=lambda candidate: candidate.uci())
            if alternatives:
                alt_features = _candidate_move_features(board_before, alternatives[0], mover)
                _train_single_sample(
                    model,
                    board_features,
                    alt_features,
                    value_target=value_target * 0.5,
                    policy_target=-0.35,
                )
            updated += 1
        try:
            board_state = validate_move(board_state, mover, from_square, to_square, promotion)["board"]
        except ValueError:
            break

    if updated:
        _save_model(Path(model_path or default_chess_pv_model_path()), model)
    return updated
