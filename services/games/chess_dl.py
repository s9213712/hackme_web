"""Deep-learning-backed helpers for the ``experiment 3:DL`` chess difficulty.

This engine extends the lightweight ``experiment 2:nn`` approach with:

- a deeper MLP (`49 -> 64 -> 32 -> 1`)
- a replay buffer persisted under ``runtime/games/models/``
- mini-batch training instead of pure online updates
- a shared alpha-beta search stack so the NN becomes a leaf evaluator instead
  of selecting moves with only shallow handcrafted reply penalties
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
from services.games.chess_nn import (
    _board_is_check_for,
    _candidate_features,
    _clip,
    _heuristic_after_move,
    _input_size,
)
from services.games.chess_search import ZobristHasher, opening_sanity_filter, search_best_move
from services.games.chess_model_registry import bundled_seed_model_path, runtime_model_path


EXPERIMENT_DL_DIFFICULTY = "experiment 3:dl"
DEFAULT_CHESS_DL_MODEL_NAME = "chess_experiment_3_dl.json"
DEFAULT_CHESS_DL_REPLAY_NAME = "chess_experiment_3_dl_replay.jsonl"
_HIDDEN1_SIZE = 64
_HIDDEN2_SIZE = 32
_LEARNING_RATE = 0.012
_MAX_ABS_WEIGHT = 4.0
_DL_VERSION = 1
_REPLAY_CAPACITY = 4096
_BATCH_SIZE = 96
_TRAIN_EPOCHS = 4
_SEARCH_DEPTH = 2
_SEARCH_QUIESCENCE_DEPTH = 4
_SEARCH_PROFILES = {
    "fast": {"depth": 1, "quiescence_depth": 1, "time_budget_ms": 140},
    "balanced": {"depth": 2, "quiescence_depth": 2, "time_budget_ms": 320},
    "strong": {"depth": 2, "quiescence_depth": 4, "time_budget_ms": 1000},
}
_CONTRASTIVE_NEGATIVE_TARGET = -0.45
_CONTRASTIVE_MAX_NEGATIVES = 12
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
_MODEL_EVAL_MOVE_CAP = 6
_MODEL_SCORE_SCALE = 140.0
_SEMANTIC_MEMORY_LEARNING_RATE = 0.10
_FLANK_CONTEXT_MEMORY_LEARNING_RATE = 0.16
_FLANK_REASON_MEMORY_LEARNING_RATE = 0.14
_SEMANTIC_HEAD_MEMORY_LEARNING_RATE = 0.12
_MAX_FLANK_CONTEXT_MEMORY_BIAS = 1.0
_MAX_FLANK_REASON_MEMORY_BIAS = 0.9
_MAX_SEMANTIC_HEAD_MEMORY_BIAS = 0.95
_STYLE_MAX_CP_DROP = 100
_STYLE_BONUS_CP = 45
_FLANK_SEMANTIC = "flank_pawn_push"
_FLANK_REASON_TAGS = {
    "space_gain",
    "prophylaxis",
    "expansion",
    "attack_prep",
    "pawn_storm",
    "bad_random_flank_push",
}
_SEMANTIC_SEPARATION_PAIRS = {
    ("e_pawn_central_break", "kingside_aggression"),
    ("d_pawn_central_break", "kingside_aggression"),
    ("d_pawn_central_break", "flank_pawn_push"),
}
_SEMANTIC_BUDGET_CLASSES = (
    "e_pawn_central_break",
    "d_pawn_central_break",
    "flank_pawn_push",
    "development_move",
)
_SEMANTIC_SCHEDULER_ORDER = (
    "e_pawn_central_break",
    "d_pawn_central_break",
    "flank_pawn_push",
    "development_move",
)
_SEMANTIC_BUDGET_SKEW_LIMIT = 2.5
_SEMANTIC_DAMPENED_WEIGHT = 0.55
_ABLATION_MODES = {
    "default",
    "no_invariance_memory",
    "invariance_memory_only",
    "hard_negative_only",
    "invariance_plus_hard_negative",
    "stronger_hard_negative_margin",
}


def _move_semantic_class_for_board(board: chess.Board, move_uci: str) -> str:
    try:
        move = chess.Move.from_uci(str(move_uci or "").lower())
    except Exception:
        return "other"
    piece = board.piece_at(move.from_square)
    from_file = chess.square_file(move.from_square)
    to_file = chess.square_file(move.to_square)
    if piece and piece.piece_type == chess.PAWN:
        if from_file == chess.FILE_NAMES.index("e"):
            return "e_pawn_central_break"
        if from_file == chess.FILE_NAMES.index("d"):
            return "d_pawn_central_break"
        if from_file in {chess.FILE_NAMES.index("f"), chess.FILE_NAMES.index("g"), chess.FILE_NAMES.index("h")} or to_file in {chess.FILE_NAMES.index("g"), chess.FILE_NAMES.index("h")}:
            return "kingside_aggression"
        if from_file in {chess.FILE_NAMES.index("a"), chess.FILE_NAMES.index("b"), chess.FILE_NAMES.index("c")}:
            return "flank_pawn_push"
    if piece and piece.piece_type in {chess.KNIGHT, chess.BISHOP}:
        home_rank = 0 if piece.color == chess.WHITE else 7
        if chess.square_rank(move.from_square) == home_rank:
            return "development_move"
    if to_file in {chess.FILE_NAMES.index("g"), chess.FILE_NAMES.index("h")}:
        return "kingside_aggression"
    return "other"
_PIECE_VALUES = {
    chess.PAWN: 100,
    chess.KNIGHT: 320,
    chess.BISHOP: 335,
    chess.ROOK: 500,
    chess.QUEEN: 900,
    chess.KING: 20000,
}


def default_chess_dl_model_path() -> Path:
    return runtime_model_path(DEFAULT_CHESS_DL_MODEL_NAME, env_var="HTML_LEARNING_CHESS_ENGINE_DL_MODEL_PATH")


def bundled_chess_dl_model_path() -> Path:
    return bundled_seed_model_path(DEFAULT_CHESS_DL_MODEL_NAME)


def default_chess_dl_replay_path() -> Path:
    return runtime_model_path(DEFAULT_CHESS_DL_REPLAY_NAME, env_var="HTML_LEARNING_CHESS_ENGINE_DL_REPLAY_PATH")


def _now() -> str:
    return datetime.now().isoformat()


def _random_matrix(rows: int, cols: int, *, rng: random.Random) -> list[list[float]]:
    return [[rng.uniform(-0.06, 0.06) for _ in range(cols)] for _ in range(rows)]


def experiment_dl_model_template() -> dict:
    rng = random.Random(20260508)
    inputs = _input_size()
    return {
        "version": _DL_VERSION,
        "architecture": "mlp-49x64x32x1",
        "input_size": inputs,
        "hidden1_size": _HIDDEN1_SIZE,
        "hidden2_size": _HIDDEN2_SIZE,
        "w1": _random_matrix(_HIDDEN1_SIZE, inputs, rng=rng),
        "b1": [rng.uniform(-0.015, 0.015) for _ in range(_HIDDEN1_SIZE)],
        "w2": _random_matrix(_HIDDEN2_SIZE, _HIDDEN1_SIZE, rng=rng),
        "b2": [rng.uniform(-0.015, 0.015) for _ in range(_HIDDEN2_SIZE)],
        "w3": [rng.uniform(-0.06, 0.06) for _ in range(_HIDDEN2_SIZE)],
        "b3": rng.uniform(-0.015, 0.015),
        "move_score_memory": {},
        "policy_invariance_memory": {},
        "semantic_score_memory": {},
        "semantic_head_memory": {},
        "flank_context_memory": {},
        "flank_reason_memory": {},
        "sample_count": 0,
        "replay_size": 0,
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


def normalize_experiment_dl_model_payload(model: dict) -> dict | None:
    if not isinstance(model, dict):
        return None
    inputs = _input_size()
    if int(model.get("version") or 0) != _DL_VERSION:
        return None
    if int(model.get("input_size") or 0) != inputs:
        return None
    if int(model.get("hidden1_size") or 0) != _HIDDEN1_SIZE:
        return None
    if int(model.get("hidden2_size") or 0) != _HIDDEN2_SIZE:
        return None
    w1 = _normalize_float_matrix(model.get("w1"), _HIDDEN1_SIZE, inputs)
    b1 = _normalize_float_vector(model.get("b1"), _HIDDEN1_SIZE)
    w2 = _normalize_float_matrix(model.get("w2"), _HIDDEN2_SIZE, _HIDDEN1_SIZE)
    b2 = _normalize_float_vector(model.get("b2"), _HIDDEN2_SIZE)
    w3 = _normalize_float_vector(model.get("w3"), _HIDDEN2_SIZE)
    if w1 is None or b1 is None or w2 is None or b2 is None or w3 is None:
        return None
    try:
        b3 = float(model.get("b3"))
    except Exception:
        return None
    return {
        "version": _DL_VERSION,
        "architecture": "mlp-49x64x32x1",
        "input_size": inputs,
        "hidden1_size": _HIDDEN1_SIZE,
        "hidden2_size": _HIDDEN2_SIZE,
        "w1": w1,
        "b1": b1,
        "w2": w2,
        "b2": b2,
        "w3": w3,
        "b3": b3,
        "move_score_memory": {
            str(key): _clip(float(value), -_MAX_MOVE_MEMORY_BIAS, _MAX_MOVE_MEMORY_BIAS)
            for key, value in (model.get("move_score_memory") or {}).items()
            if isinstance(key, str)
        },
        "policy_invariance_memory": {
            str(key): _clip(float(value), -_MAX_INVARIANCE_MEMORY_BIAS, _MAX_INVARIANCE_MEMORY_BIAS)
            for key, value in (model.get("policy_invariance_memory") or {}).items()
            if isinstance(key, str)
        },
        "semantic_score_memory": {
            str(key): _clip(float(value), -_MAX_INVARIANCE_MEMORY_BIAS, _MAX_INVARIANCE_MEMORY_BIAS)
            for key, value in (model.get("semantic_score_memory") or {}).items()
            if isinstance(key, str)
        },
        "semantic_head_memory": {
            str(key): _clip(float(value), -_MAX_SEMANTIC_HEAD_MEMORY_BIAS, _MAX_SEMANTIC_HEAD_MEMORY_BIAS)
            for key, value in (model.get("semantic_head_memory") or {}).items()
            if isinstance(key, str)
        },
        "flank_context_memory": {
            str(key): _clip(float(value), -_MAX_FLANK_CONTEXT_MEMORY_BIAS, _MAX_FLANK_CONTEXT_MEMORY_BIAS)
            for key, value in (model.get("flank_context_memory") or {}).items()
            if isinstance(key, str)
        },
        "flank_reason_memory": {
            str(key): _clip(float(value), -_MAX_FLANK_REASON_MEMORY_BIAS, _MAX_FLANK_REASON_MEMORY_BIAS)
            for key, value in (model.get("flank_reason_memory") or {}).items()
            if isinstance(key, str)
        },
        "sample_count": max(0, int(model.get("sample_count") or 0)),
        "replay_size": max(0, int(model.get("replay_size") or 0)),
        "updated_at": str(model.get("updated_at") or _now()),
    }


def _load_model(model_path: Path) -> dict:
    path = Path(model_path)
    if not path.exists():
        return experiment_dl_model_template()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return experiment_dl_model_template()
    normalized = normalize_experiment_dl_model_payload(payload)
    return normalized or experiment_dl_model_template()


def _save_model(model_path: Path, model: dict) -> None:
    path = Path(model_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(json.dumps(model, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    tmp_path.replace(path)


def _forward(model: dict, features: list[float]) -> tuple[float, list[float], list[float]]:
    hidden1: list[float] = []
    for row, bias in zip(model["w1"], model["b1"]):
        total = float(bias)
        for weight, feature in zip(row, features):
            total += float(weight) * float(feature)
        hidden1.append(math.tanh(total))
    hidden2: list[float] = []
    for row, bias in zip(model["w2"], model["b2"]):
        total = float(bias)
        for weight, hidden in zip(row, hidden1):
            total += float(weight) * float(hidden)
        hidden2.append(math.tanh(total))
    output_total = float(model["b3"])
    for weight, hidden in zip(model["w3"], hidden2):
        output_total += float(weight) * float(hidden)
    return math.tanh(output_total), hidden1, hidden2


def _blend_score(model_score: float, heuristic_score: float, sample_count: int) -> float:
    learned_weight = _clip(0.2 + sample_count / 500.0, 0.2, 0.9)
    return heuristic_score * (1.0 - learned_weight) + model_score * learned_weight


def _move_memory_key(board: chess.Board, side: str, move_uci: str) -> str:
    return f"{board.board_fen()} {board.turn} {board.castling_rights} {board.ep_square}|{side}|{move_uci}"


def _move_memory_bias(model: dict, board: chess.Board, side: str, move_uci: str) -> float:
    try:
        return float((model.get("move_score_memory") or {}).get(_move_memory_key(board, side, move_uci)) or 0.0)
    except Exception:
        return 0.0


def _invariance_context_key(board: chess.Board, side: str) -> str:
    central_files = "cdef"
    central_ranks = range(2, 7)
    pawns = []
    for file_name in central_files:
        for rank in central_ranks:
            square = chess.parse_square(f"{file_name}{rank}")
            piece = board.piece_at(square)
            if piece and piece.piece_type == chess.PAWN:
                color = "w" if piece.color == chess.WHITE else "b"
                pawns.append(f"{color}{file_name}{rank}")
    piece_count = len(board.piece_map())
    opening_phase = "opening" if int(board.fullmove_number or 1) <= 10 and piece_count >= 24 else "post_opening"
    watched_moves = ("e7e5", "d7d5", "c7c5", "a7a5", "h7h5")
    legal = []
    for item in watched_moves:
        try:
            legal.append(f"{item}:{int(chess.Move.from_uci(item) in board.legal_moves)}")
        except Exception:
            continue
    king_square = board.king(board.turn)
    king_file = chess.square_file(king_square) if king_square is not None else -1
    king_rank = chess.square_rank(king_square) if king_square is not None else -1
    king_safety = f"check={int(board.is_check())}|king_zone={king_file // 2},{king_rank // 2}|castle_any={int(bool(board.castling_rights))}"
    return (
        f"{side}|phase={opening_phase}|turn={board.turn}|"
        f"pawns={','.join(pawns)}|legal={','.join(legal)}|safety={king_safety}"
    )


def _invariance_memory_key(board: chess.Board, side: str, move_uci: str) -> str:
    return f"{_invariance_context_key(board, side)}|{move_uci}"


def _semantic_memory_key(board: chess.Board, side: str, semantic: str) -> str:
    return f"{_invariance_context_key(board, side)}|semantic:{semantic}"


def _semantic_head_name(semantic: str) -> str:
    if semantic in {"e_pawn_central_break", "d_pawn_central_break"}:
        return "central_head"
    if semantic == _FLANK_SEMANTIC:
        return "flank_head"
    if semantic == "development_move":
        return "development_head"
    return "other_head"


def _semantic_head_key(board: chess.Board, side: str, semantic: str, move_uci: str) -> str:
    head = _semantic_head_name(semantic)
    return f"{_invariance_context_key(board, side)}|head:{head}|semantic:{semantic}|move:{move_uci}"


def _central_pawn_tension(board: chess.Board) -> str:
    occupied = 0
    for square_name in ("d4", "e4", "d5", "e5"):
        if board.piece_at(chess.parse_square(square_name)):
            occupied += 1
    if occupied >= 3:
        return "locked"
    if occupied == 2:
        return "positive"
    return "low"


def _king_castled_side(board: chess.Board, color: chess.Color) -> str:
    king = board.king(color)
    if king is None:
        return "unknown"
    file_index = chess.square_file(king)
    rank = chess.square_rank(king)
    home_rank = 0 if color == chess.WHITE else 7
    if rank != home_rank:
        return "uncastled"
    if file_index >= 6:
        return "kingside"
    if file_index <= 2:
        return "queenside"
    return "uncastled"


def _flank_context_features_for_board(board: chess.Board, side: str) -> dict:
    mover_color = chess.WHITE if side == "white" else chess.BLACK
    opponent_color = not mover_color
    own_castle = _king_castled_side(board, mover_color)
    opponent_castle = _king_castled_side(board, opponent_color)
    queenside_pawns = 0
    kingside_pawns = 0
    for square, piece in board.piece_map().items():
        if piece.piece_type != chess.PAWN or piece.color != mover_color:
            continue
        file_index = chess.square_file(square)
        if file_index <= 2:
            queenside_pawns += 1
        elif file_index >= 5:
            kingside_pawns += 1
    wing_space = "queenside" if queenside_pawns > kingside_pawns else ("kingside" if kingside_pawns > queenside_pawns else "balanced")
    central_tension = _central_pawn_tension(board)
    c_file_tension = bool(board.piece_at(chess.parse_square("c4")) or board.piece_at(chess.parse_square("c5")))
    return {
        "supported": True,
        "open_or_closed_center": "closed" if central_tension in {"locked", "positive"} else "open",
        "king_castled_side": own_castle,
        "opponent_king_castled_side": opponent_castle,
        "wing_space": wing_space,
        "pawn_chain_direction": "queenside" if queenside_pawns >= kingside_pawns + 2 else ("kingside" if kingside_pawns >= queenside_pawns + 2 else "balanced"),
        "central_tension": central_tension,
        "attack_lane_available": bool(own_castle != "unknown" and opponent_castle != "unknown" and own_castle != opponent_castle),
        "opposite_side_castling": bool(own_castle in {"kingside", "queenside"} and opponent_castle in {"kingside", "queenside"} and own_castle != opponent_castle),
        "side_to_move_pressure": "check" if board.is_check() else ("initiative" if board.legal_moves.count() >= 28 else "normal"),
        "c_file_open_or_tension": c_file_tension,
    }


def _flank_context_feature_vector(features: dict) -> list[float]:
    if not isinstance(features, dict) or not features.get("supported", True):
        return [0.0] * 8
    return [
        1.0 if str(features.get("open_or_closed_center")) == "closed" else -1.0,
        {"kingside": 1.0, "queenside": -1.0, "uncastled": 0.0}.get(str(features.get("king_castled_side")), 0.0),
        {"kingside": 1.0, "queenside": -1.0, "balanced": 0.0}.get(str(features.get("wing_space")), 0.0),
        {"kingside": 1.0, "queenside": -1.0, "balanced": 0.0}.get(str(features.get("pawn_chain_direction")), 0.0),
        {"locked": 1.0, "positive": 0.6, "low": -0.4}.get(str(features.get("central_tension")), 0.0),
        1.0 if bool(features.get("attack_lane_available")) else -0.2,
        1.0 if bool(features.get("opposite_side_castling")) else -0.2,
        {"check": -0.7, "initiative": 0.7, "normal": 0.0}.get(str(features.get("side_to_move_pressure")), 0.0),
    ]


def _flank_context_key(board: chess.Board, side: str, semantic: str) -> str:
    features = _flank_context_features_for_board(board, side)
    parts = [
        f"center={features.get('open_or_closed_center')}",
        f"king={features.get('king_castled_side')}",
        f"oppking={features.get('opponent_king_castled_side')}",
        f"wing={features.get('wing_space')}",
        f"chain={features.get('pawn_chain_direction')}",
        f"tension={features.get('central_tension')}",
        f"lane={int(bool(features.get('attack_lane_available')))}",
        f"oppcastle={int(bool(features.get('opposite_side_castling')))}",
        f"pressure={features.get('side_to_move_pressure')}",
        f"cfile={int(bool(features.get('c_file_open_or_tension')))}",
    ]
    return f"{side}|{'|'.join(parts)}|semantic:{semantic}"


def _flank_reason_tag_for_board(board: chess.Board, side: str, move_uci: str) -> str:
    semantic = _move_semantic_class_for_board(board, move_uci)
    if semantic != _FLANK_SEMANTIC:
        return "bad_random_flank_push"
    features = _flank_context_features_for_board(board, side)
    if bool(features.get("opposite_side_castling")) and bool(features.get("attack_lane_available")):
        return "pawn_storm"
    if str(features.get("central_tension")) in {"locked", "positive"} and bool(features.get("c_file_open_or_tension")):
        return "attack_prep"
    if str(features.get("wing_space")) in {"queenside", "kingside"}:
        return "space_gain"
    if str(features.get("open_or_closed_center")) == "closed":
        return "prophylaxis"
    return "expansion"


def _flank_reason_key(board: chess.Board, side: str, reason_tag: str) -> str:
    return f"{_flank_context_key(board, side, _FLANK_SEMANTIC)}|reason:{reason_tag}"


def _invariance_memory_bias(model: dict, board: chess.Board, side: str, move_uci: str) -> float:
    try:
        return float((model.get("policy_invariance_memory") or {}).get(_invariance_memory_key(board, side, move_uci)) or 0.0)
    except Exception:
        return 0.0


def _semantic_memory_bias(model: dict, board: chess.Board, side: str, move_uci: str) -> float:
    try:
        semantic = _move_semantic_class_for_board(board, move_uci)
        return float((model.get("semantic_score_memory") or {}).get(_semantic_memory_key(board, side, semantic)) or 0.0)
    except Exception:
        return 0.0


def _semantic_head_memory_bias(model: dict, board: chess.Board, side: str, move_uci: str) -> float:
    try:
        semantic = _move_semantic_class_for_board(board, move_uci)
        return float((model.get("semantic_head_memory") or {}).get(_semantic_head_key(board, side, semantic, move_uci)) or 0.0)
    except Exception:
        return 0.0


def _flank_context_memory_bias(model: dict, board: chess.Board, side: str, move_uci: str) -> float:
    try:
        semantic = _move_semantic_class_for_board(board, move_uci)
        return float((model.get("flank_context_memory") or {}).get(_flank_context_key(board, side, semantic)) or 0.0)
    except Exception:
        return 0.0


def _flank_reason_memory_bias(model: dict, board: chess.Board, side: str, move_uci: str) -> float:
    try:
        reason = _flank_reason_tag_for_board(board, side, move_uci)
        return float((model.get("flank_reason_memory") or {}).get(_flank_reason_key(board, side, reason)) or 0.0)
    except Exception:
        return 0.0


def _update_move_memory(model: dict, board: chess.Board, side: str, move: chess.Move, target: float) -> None:
    memory = model.setdefault("move_score_memory", {})
    key = _move_memory_key(board, side, move.uci())
    current = float(memory.get(key) or 0.0)
    memory[key] = _clip(current + _MOVE_MEMORY_LEARNING_RATE * float(target), -_MAX_MOVE_MEMORY_BIAS, _MAX_MOVE_MEMORY_BIAS)


def _update_invariance_memory(model: dict, board: chess.Board, side: str, move: chess.Move, target: float) -> None:
    memory = model.setdefault("policy_invariance_memory", {})
    key = _invariance_memory_key(board, side, move.uci())
    current = float(memory.get(key) or 0.0)
    memory[key] = _clip(
        current + _INVARIANCE_MEMORY_LEARNING_RATE * float(target),
        -_MAX_INVARIANCE_MEMORY_BIAS,
        _MAX_INVARIANCE_MEMORY_BIAS,
    )


def _update_semantic_memory(model: dict, board: chess.Board, side: str, move: chess.Move, target: float) -> None:
    memory = model.setdefault("semantic_score_memory", {})
    semantic = _move_semantic_class_for_board(board, move.uci())
    key = _semantic_memory_key(board, side, semantic)
    current = float(memory.get(key) or 0.0)
    memory[key] = _clip(
        current + _SEMANTIC_MEMORY_LEARNING_RATE * float(target),
        -_MAX_INVARIANCE_MEMORY_BIAS,
        _MAX_INVARIANCE_MEMORY_BIAS,
    )


def _update_semantic_head_memory(model: dict, board: chess.Board, side: str, move: chess.Move, target: float) -> str:
    memory = model.setdefault("semantic_head_memory", {})
    semantic = _move_semantic_class_for_board(board, move.uci())
    key = _semantic_head_key(board, side, semantic, move.uci())
    current = float(memory.get(key) or 0.0)
    memory[key] = _clip(
        current + _SEMANTIC_HEAD_MEMORY_LEARNING_RATE * float(target),
        -_MAX_SEMANTIC_HEAD_MEMORY_BIAS,
        _MAX_SEMANTIC_HEAD_MEMORY_BIAS,
    )
    return _semantic_head_name(semantic)


def _update_flank_context_memory(model: dict, board: chess.Board, side: str, move: chess.Move, target: float) -> None:
    memory = model.setdefault("flank_context_memory", {})
    semantic = _move_semantic_class_for_board(board, move.uci())
    key = _flank_context_key(board, side, semantic)
    current = float(memory.get(key) or 0.0)
    memory[key] = _clip(
        current + _FLANK_CONTEXT_MEMORY_LEARNING_RATE * float(target),
        -_MAX_FLANK_CONTEXT_MEMORY_BIAS,
        _MAX_FLANK_CONTEXT_MEMORY_BIAS,
    )


def _update_flank_reason_memory(model: dict, board: chess.Board, side: str, reason_tag: str, target: float) -> None:
    reason = str(reason_tag or "").strip()
    if reason not in _FLANK_REASON_TAGS:
        reason = "bad_random_flank_push"
    memory = model.setdefault("flank_reason_memory", {})
    key = _flank_reason_key(board, side, reason)
    current = float(memory.get(key) or 0.0)
    memory[key] = _clip(
        current + _FLANK_REASON_MEMORY_LEARNING_RATE * float(target),
        -_MAX_FLANK_REASON_MEMORY_BIAS,
        _MAX_FLANK_REASON_MEMORY_BIAS,
    )


def _training_ablation_config() -> dict:
    mode = str(os.environ.get("CHESS_EXP3_ABLATION_MODE") or "default").strip().lower()
    if mode not in _ABLATION_MODES:
        mode = "default"
    use_invariance = mode not in {"no_invariance_memory", "hard_negative_only"}
    use_hard_negatives = mode not in {"invariance_memory_only", "no_invariance_memory"}
    hard_negative_weight = 0.85
    negative_target = _CONTRASTIVE_NEGATIVE_TARGET
    semantic_separation_weight = 1.15
    if mode == "stronger_hard_negative_margin":
        use_invariance = True
        use_hard_negatives = True
        hard_negative_weight = 1.25
        negative_target = -0.65
        semantic_separation_weight = 1.35
    return {
        "mode": mode,
        "use_invariance_memory": use_invariance,
        "use_hard_negatives": use_hard_negatives,
        "hard_negative_weight": hard_negative_weight,
        "semantic_separation_weight": semantic_separation_weight,
        "ordinary_negative_weight": 0.55,
        "negative_target": negative_target,
    }


def _resolve_search_profile(profile: str | None) -> dict:
    normalized = str(profile or "balanced").strip().lower()
    return dict(_SEARCH_PROFILES.get(normalized) or _SEARCH_PROFILES["balanced"])


def rank_experiment_dl_policy_moves(board_state, side: str, *, model_path=None) -> list[dict]:
    board = to_chess_board(board_state, side)
    ai_color = chess.WHITE if side == "white" else chess.BLACK
    if board.turn != ai_color:
        board.turn = ai_color
    if board.is_game_over():
        return []
    model = _load_model(Path(model_path or default_chess_dl_model_path()))
    rows = []
    for move in sorted(board.legal_moves, key=lambda item: item.uci()):
        score = _score_candidate_move(board, move, side, model)
        rows.append({"move": move.uci(), "raw_policy_score": round(float(score), 8)})
    if not rows:
        return []
    max_score = max(float(row["raw_policy_score"]) for row in rows)
    denom = sum(math.exp(float(row["raw_policy_score"]) - max_score) for row in rows)
    ranked = sorted(rows, key=lambda row: (-float(row["raw_policy_score"]), str(row["move"])))
    rank = {str(row["move"]): index for index, row in enumerate(ranked, start=1)}
    for row in rows:
        row["policy_probability"] = round(math.exp(float(row["raw_policy_score"]) - max_score) / denom, 8) if denom else 0.0
        row["raw_policy_rank"] = rank[str(row["move"])]
        row["move_order_score"] = int(float(row["raw_policy_score"]) * 1000.0)
        row["move_order_rank"] = row["raw_policy_rank"]
        row["legal_move_bonus_penalty"] = 0
    return sorted(rows, key=lambda row: (int(row["raw_policy_rank"]), str(row["move"])))


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
    rows = []
    for move in sorted(board.legal_moves, key=lambda item: item.uci()):
        rows.append({"move": move.uci(), "raw_policy_score": _score_candidate_move(board, move, side, model)})
    rows = sorted(rows, key=lambda row: (-float(row["raw_policy_score"]), str(row["move"])))
    thresholds = _adaptive_policy_thresholds(fusion_mode=fusion_mode, decision_context=decision_context)
    if len(rows) < 2:
        return {"used": False, "reason": "insufficient_legal_moves", "thresholds": thresholds}
    margin = float(rows[0]["raw_policy_score"]) - float(rows[1]["raw_policy_score"])
    info = {
        "used": False,
        "move": str(rows[0]["move"]),
        "raw_policy_score": round(float(rows[0]["raw_policy_score"]), 8),
        "runner_up_move": str(rows[1]["move"]),
        "runner_up_raw_policy_score": round(float(rows[1]["raw_policy_score"]), 8),
        "margin": round(margin, 8),
        "thresholds": thresholds,
        "reason": "below_override_threshold",
    }
    if str(thresholds.get("fusion_mode")) == "strict_search":
        info["reason"] = "strict_search_disables_policy_override"
        return info
    if float(rows[0]["raw_policy_score"]) < float(thresholds["min_score"]) or margin < float(thresholds["min_margin"]):
        return info
    try:
        move = chess.Move.from_uci(str(rows[0]["move"]))
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


def _style_bonus(board: chess.Board, move: chess.Move, side: str, style_profile: str) -> int:
    normalized = str(style_profile or "balanced").strip().lower()
    if normalized == "balanced":
        return 0
    after = board.copy(stack=False)
    after.push(move)
    semantic = _move_semantic_class_for_board(board, move.uci())
    if normalized == "attacking":
        bonus = 0
        if semantic == "kingside_aggression":
            bonus += _STYLE_BONUS_CP
        if after.is_check():
            bonus += 30
        if board.is_capture(move):
            bonus += 15
        return bonus
    if normalized == "defensive":
        bonus = 0
        ai_color = chess.WHITE if side == "white" else chess.BLACK
        if not _board_is_check_for(after, ai_color):
            bonus += 20
        if semantic in {"development_move", "d_pawn_central_break", "e_pawn_central_break"}:
            bonus += 20
        if after.is_check():
            bonus -= 20
        return bonus
    return 0


def _apply_style_profile(
    board: chess.Board,
    side: str,
    base_move: chess.Move | None,
    *,
    score_move,
    style_profile: str = "balanced",
) -> tuple[chess.Move | None, dict]:
    normalized = str(style_profile or "balanced").strip().lower()
    if normalized not in {"balanced", "attacking", "defensive"}:
        normalized = "balanced"
    audit = {
        "style_profile": normalized,
        "candidate_moves": [],
        "rejected_style_moves": [],
        "selected_move_before_style": base_move.uci() if base_move else "",
        "selected_move_after_style": base_move.uci() if base_move else "",
        "cp_threshold": _STYLE_MAX_CP_DROP,
        "applied": False,
    }
    if normalized == "balanced" or base_move is None:
        return base_move, audit
    legal = sorted(board.legal_moves, key=lambda item: item.uci())
    if not legal:
        return base_move, audit
    scored = []
    for move in legal:
        base_score = int(score_move(move))
        style_bonus = int(_style_bonus(board, move, side, normalized))
        row = {
            "move": move.uci(),
            "semantic": _move_semantic_class_for_board(board, move.uci()),
            "base_score": base_score,
            "style_bonus": style_bonus,
            "final_score": base_score + style_bonus,
            "legal": True,
        }
        scored.append((move, row))
    best_base = max(int(row["base_score"]) for _move, row in scored)
    eligible = []
    for move, row in scored:
        cp_delta = int(row["base_score"]) - best_base
        row["cp_delta_vs_best"] = cp_delta
        if cp_delta < -_STYLE_MAX_CP_DROP:
            row["rejected"] = True
            row["rejection_reason"] = f"style move below best candidate by {abs(cp_delta)}cp"
            audit["rejected_style_moves"].append(row)
        else:
            row["rejected"] = False
            row["rejection_reason"] = ""
            eligible.append((move, row))
    if not eligible:
        audit["candidate_moves"] = [row for _move, row in scored[:8]]
        return base_move, audit
    selected_move, selected_row = max(eligible, key=lambda item: (int(item[1]["final_score"]), item[0].uci()))
    audit["candidate_moves"] = sorted((row for _move, row in scored), key=lambda row: (-int(row["final_score"]), str(row["move"])))[:8]
    audit["selected_move_after_style"] = selected_move.uci()
    audit["applied"] = selected_move != base_move
    audit["selection"] = selected_row
    return selected_move, audit


def _score_candidate_move(board: chess.Board, move: chess.Move, side: str, model: dict) -> float:
    ai_color = chess.WHITE if side == "white" else chess.BLACK
    before = board.copy(stack=False)
    captured_piece = before.piece_at(move.to_square)
    if captured_piece is None and before.is_en_passant(move):
        capture_square = chess.square(chess.square_file(move.to_square), chess.square_rank(move.from_square))
        captured_piece = before.piece_at(capture_square)
    board.push(move)
    try:
        features = _candidate_features(before, move, board, side)
        dl_score, _hidden1, _hidden2 = _forward(model, features)
        dl_score = _clip(
            dl_score
            + _move_memory_bias(model, before, side, move.uci())
            + _invariance_memory_bias(model, before, side, move.uci())
            + _semantic_memory_bias(model, before, side, move.uci())
            + _semantic_head_memory_bias(model, before, side, move.uci())
            + _flank_context_memory_bias(model, before, side, move.uci())
            + _flank_reason_memory_bias(model, before, side, move.uci()),
            -1.0,
            1.0,
        )
        heuristic = _heuristic_after_move(board, move, ai_color, captured_piece.piece_type if captured_piece else None)
        score = _blend_score(dl_score, heuristic, int(model.get("sample_count") or 0))
        if board.is_checkmate():
            score += 10.0
        if _board_is_check_for(board, ai_color):
            score -= 2.0
        return score
    finally:
        board.pop()


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


def _side_model_potential(board: chess.Board, side: str, model: dict) -> float:
    analysis_board = board.copy(stack=False)
    analysis_board.turn = chess.WHITE if side == "white" else chess.BLACK
    if analysis_board.is_game_over():
        return 0.0
    legal = list(analysis_board.legal_moves)
    if not legal:
        return 0.0
    ordered = sorted(
        legal,
        key=lambda move: (
            _score_candidate_move(analysis_board, move, side, model),
            move.uci(),
        ),
        reverse=True,
    )
    capped = ordered[:_MODEL_EVAL_MOVE_CAP]
    if not capped:
        return 0.0
    top_scores = [_score_candidate_move(analysis_board, move, side, model) for move in capped]
    if not top_scores:
        return 0.0
    best = max(top_scores)
    mean = sum(top_scores) / len(top_scores)
    return best * 0.7 + mean * 0.3


def _dl_static_eval(board: chess.Board, model: dict, eval_cache: dict[int, int], hasher: ZobristHasher) -> int:
    board_hash = hasher.hash_board(board)
    cached = eval_cache.get(board_hash)
    if cached is not None:
        return cached
    score = _material_balance(board)
    score += _mobility_balance(board)
    if board.is_check():
        score += -35 if board.turn == chess.WHITE else 35
    white_model = _side_model_potential(board, "white", model)
    black_model = _side_model_potential(board, "black", model)
    score += int((white_model - black_model) * _MODEL_SCORE_SCALE)
    eval_cache[board_hash] = score
    return score


def choose_experiment_dl_move(board_state, side: str, *, model_path=None, search_profile="balanced", fusion_mode="balanced_fusion", decision_context=None, style_profile="balanced"):
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
    model = _load_model(Path(model_path or default_chess_dl_model_path()))
    hasher = ZobristHasher(seed=20260520)
    eval_cache: dict[int, int] = {}
    profile = _resolve_search_profile(search_profile)

    def move_order_fn(current_board: chess.Board, move: chess.Move, _ply: int) -> int:
        current_side = "white" if current_board.turn == chess.WHITE else "black"
        score = _score_candidate_move(current_board, move, current_side, model)
        return int(score * 1000.0)

    search = search_best_move(
        board,
        max_depth=profile["depth"],
        evaluate=lambda current_board: _dl_static_eval(current_board, model, eval_cache, hasher),
        move_order_fn=move_order_fn,
        hasher=hasher,
        quiescence_depth=profile["quiescence_depth"],
        time_budget_ms=profile.get("time_budget_ms"),
    )
    best_move = search.best_move
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
        return score + color_sign * _dl_static_eval(after, model, eval_cache, hasher)

    best_move = opening_sanity_filter(board, best_move, score_move=sanity_move_score)
    policy_override = _policy_override_move(model, board, side, fusion_mode=fusion_mode, decision_context=decision_context)
    if policy_override is not None:
        best_move = policy_override
    best_move, _style_audit = _apply_style_profile(
        board,
        side,
        best_move,
        score_move=sanity_move_score,
        style_profile=style_profile,
    )
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


def explain_experiment_dl_decision(board_state, side: str, *, model_path=None, search_profile="fast", watched_moves=None, fusion_mode="balanced_fusion", decision_context=None, style_profile="balanced") -> dict:
    board = to_chess_board(board_state, side)
    ai_color = chess.WHITE if side == "white" else chess.BLACK
    if board.turn != ai_color:
        board.turn = ai_color
    watched = {str(item or "").lower() for item in (watched_moves or []) if str(item or "").strip()}
    model_path = Path(model_path or default_chess_dl_model_path())
    if board.is_game_over():
        return {"supported": True, "chosen_move": "", "chosen_reason": "game_over", "moves": []}
    model = _load_model(model_path)
    hasher = ZobristHasher(seed=20260520)
    eval_cache: dict[int, int] = {}
    profile = _resolve_search_profile(search_profile)

    def move_order_fn(current_board: chess.Board, move: chess.Move, _ply: int) -> int:
        current_side = "white" if current_board.turn == chess.WHITE else "black"
        return int(_score_candidate_move(current_board, move, current_side, model) * 1000.0)

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
        search = search_best_move(
            board,
            max_depth=profile["depth"],
            evaluate=lambda current_board: _dl_static_eval(current_board, model, eval_cache, hasher),
            move_order_fn=move_order_fn,
            hasher=hasher,
            quiescence_depth=profile["quiescence_depth"],
            time_budget_ms=profile.get("time_budget_ms"),
        )
        chosen = search.best_move
        search_score = int(search.score)
        search_depth = int(search.depth)
        chosen_reason = "search_best_move"
        color_sign = 1 if ai_color == chess.WHITE else -1

        def sanity_move_score(move: chess.Move) -> int:
            after = board.copy(stack=False)
            after.push(move)
            if after.is_checkmate():
                return 9_000_000
            return move_order_fn(board, move, 0) + color_sign * _dl_static_eval(after, model, eval_cache, hasher)

        fallback = opening_sanity_filter(board, chosen, score_move=sanity_move_score)
        if fallback is not None and chosen is not None and fallback != chosen:
            chosen = fallback
            chosen_reason = "opening_sanity_fallback"
        policy_override = _policy_override_info(model, board, side, fusion_mode=fusion_mode, decision_context=decision_context)
        if policy_override.get("used"):
            chosen = chess.Move.from_uci(str(policy_override.get("move")))
            chosen_reason = "high_confidence_policy_override"
        chosen, style_profile_audit = _apply_style_profile(
            board,
            side,
            chosen,
            score_move=sanity_move_score,
            style_profile=style_profile,
        )
        if bool(style_profile_audit.get("applied")):
            chosen_reason = f"{style_profile_audit.get('style_profile')}_style_profile"
    color_sign = 1 if ai_color == chess.WHITE else -1
    thresholds = _adaptive_policy_thresholds(fusion_mode=fusion_mode, decision_context=decision_context)
    policy_weight = int(thresholds.get("policy_weight") or 0)
    raw_rows = {str(row["move"]): row for row in rank_experiment_dl_policy_moves({"__fen__": board.fen()}, side, model_path=model_path)}
    moves = []
    max_child_depth = max(0, int(profile["depth"]) - 1)
    for move in sorted(board.legal_moves, key=lambda item: item.uci()):
        after = board.copy(stack=False)
        after.push(move)
        static_eval_score = int(color_sign * _dl_static_eval(after, model, eval_cache, hasher))
        if after.is_checkmate():
            per_move_search = 9_000_000
        elif max_child_depth <= 0:
            per_move_search = static_eval_score
        else:
            child = search_best_move(
                after,
                max_depth=max_child_depth,
                evaluate=lambda current_board: _dl_static_eval(current_board, model, eval_cache, hasher),
                hasher=hasher,
                quiescence_depth=profile["quiescence_depth"],
                time_budget_ms=max(20, int(profile.get("time_budget_ms") or 0) // max(1, board.legal_moves.count())),
            )
            per_move_search = -int(child.score)
        row = dict(raw_rows.get(move.uci()) or {"move": move.uci(), "raw_policy_score": _score_candidate_move(board, move, side, model)})
        row["static_eval_score"] = static_eval_score
        row["search_score"] = int(per_move_search)
        row["fused_score"] = round(float(per_move_search) + float(row.get("raw_policy_score") or 0.0) * policy_weight, 4)
        row["base_score"] = row["fused_score"]
        row["style_profile"] = str(style_profile or "balanced").strip().lower()
        row["style_bonus"] = int(_style_bonus(board, move, side, style_profile))
        row["final_combined_score"] = row["fused_score"] + row["style_bonus"]
        row["override_applied"] = bool(policy_override.get("used") and str(policy_override.get("move") or "") == move.uci()) if "policy_override" in locals() else False
        row["override_reason"] = str((policy_override if "policy_override" in locals() else {}).get("reason") or "")
        row["chosen"] = bool(chosen is not None and move == chosen)
        moves.append(row)
    moves = sorted(moves, key=lambda row: (-float(row.get("final_combined_score") or 0), str(row.get("move") or "")))
    watched_rows = [row for row in moves if str(row.get("move") or "") in watched] if watched else moves[:5]
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
        "policy_override": policy_override if "policy_override" in locals() else _policy_override_info(model, board, side, fusion_mode=fusion_mode, decision_context=decision_context),
        "style_profile": style_profile_audit if "style_profile_audit" in locals() else {"style_profile": str(style_profile or "balanced").strip().lower(), "applied": False},
        "watched_moves": watched_rows,
        "top_final_moves": moves[:5],
        "all_legal_count": len(moves),
    }


def _train_single_sample(model: dict, features: list[float], target: float, weight: float) -> None:
    prediction, hidden1, hidden2 = _forward(model, features)
    delta_out = (float(target) - float(prediction)) * (1.0 - float(prediction) * float(prediction)) * float(weight)
    hidden2_deltas = []
    for out_weight, hidden_value in zip(model["w3"], hidden2):
        hidden2_deltas.append((1.0 - hidden_value * hidden_value) * float(out_weight) * delta_out)
    hidden1_deltas = []
    for index, hidden1_value in enumerate(hidden1):
        downstream = 0.0
        for row_index, row in enumerate(model["w2"]):
            downstream += float(row[index]) * hidden2_deltas[row_index]
        hidden1_deltas.append((1.0 - hidden1_value * hidden1_value) * downstream)
    for index, hidden_value in enumerate(hidden2):
        model["w3"][index] = _clip(float(model["w3"][index]) + _LEARNING_RATE * delta_out * hidden_value, -_MAX_ABS_WEIGHT, _MAX_ABS_WEIGHT)
    model["b3"] = _clip(float(model["b3"]) + _LEARNING_RATE * delta_out, -_MAX_ABS_WEIGHT, _MAX_ABS_WEIGHT)
    for row_index, row in enumerate(model["w2"]):
        delta_hidden = hidden2_deltas[row_index]
        for col_index, hidden_value in enumerate(hidden1):
            row[col_index] = _clip(float(row[col_index]) + _LEARNING_RATE * delta_hidden * float(hidden_value), -_MAX_ABS_WEIGHT, _MAX_ABS_WEIGHT)
        model["b2"][row_index] = _clip(float(model["b2"][row_index]) + _LEARNING_RATE * delta_hidden, -_MAX_ABS_WEIGHT, _MAX_ABS_WEIGHT)
    for row_index, row in enumerate(model["w1"]):
        delta_hidden = hidden1_deltas[row_index]
        for col_index, feature in enumerate(features):
            row[col_index] = _clip(float(row[col_index]) + _LEARNING_RATE * delta_hidden * float(feature), -_MAX_ABS_WEIGHT, _MAX_ABS_WEIGHT)
        model["b1"][row_index] = _clip(float(model["b1"][row_index]) + _LEARNING_RATE * delta_hidden, -_MAX_ABS_WEIGHT, _MAX_ABS_WEIGHT)
    model["sample_count"] = int(model.get("sample_count") or 0) + 1
    model["updated_at"] = _now()


def _load_replay_entries(replay_path: Path) -> list[dict]:
    path = Path(replay_path)
    if not path.exists():
        return []
    entries: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except Exception:
            continue
        features = _normalize_float_vector(item.get("features"), _input_size())
        if features is None:
            continue
        try:
            target = float(item.get("target"))
            weight = float(item.get("weight") or 1.0)
        except Exception:
            continue
        entries.append({
            "features": features,
            "fen": str(item.get("fen") or ""),
            "move_uci": str(item.get("move_uci") or "").lower(),
            "side": str(item.get("side") or "").lower(),
            "target": _clip(target, -1.0, 1.0),
            "weight": _clip(weight, 0.1, 3.0),
            "source": str(item.get("source") or "game"),
            "hard_negatives": [str(value).strip().lower() for value in (item.get("hard_negatives") or []) if str(value).strip()],
            "invariance_group_id": str(item.get("invariance_group_id") or "").strip(),
            "expected_semantic": str(item.get("expected_semantic") or "").strip(),
            "semantic_class": str(item.get("semantic_class") or "").strip(),
            "flank_context_features": item.get("flank_context_features") if isinstance(item.get("flank_context_features"), dict) else {},
            "flank_context_feature_vector": item.get("flank_context_feature_vector") if isinstance(item.get("flank_context_feature_vector"), list) else [],
            "flank_reason_tag": str(item.get("flank_reason_tag") or "").strip(),
        })
    return entries[-_REPLAY_CAPACITY:]


def _append_replay_entries(replay_path: Path, samples: list[dict]) -> int:
    path = Path(replay_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    entries = _load_replay_entries(path)
    entries.extend(samples)
    entries = entries[-_REPLAY_CAPACITY:]
    serialized = "\n".join(json.dumps(item, ensure_ascii=False, sort_keys=True) for item in entries)
    path.write_text((serialized + "\n") if serialized else "", encoding="utf-8")
    return len(entries)


def _replace_replay_entries(replay_path: Path, samples: list[dict]) -> int:
    path = Path(replay_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    entries = samples[-_REPLAY_CAPACITY:]
    serialized = "\n".join(json.dumps(item, ensure_ascii=False, sort_keys=True) for item in entries)
    path.write_text((serialized + "\n") if serialized else "", encoding="utf-8")
    return len(entries)


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


def _semantic_negative_moves(board: chess.Board, expected_move: chess.Move, hard_negatives: list[str]) -> list[chess.Move]:
    expected_semantic = _move_semantic_class_for_board(board, expected_move.uci())
    moves = []
    for move in _legal_hard_negative_moves(board, expected_move, hard_negatives):
        if _move_semantic_class_for_board(board, move.uci()) != expected_semantic:
            moves.append(move)
    return moves


def _flank_specific_negative_moves(board: chess.Board, expected_move: chess.Move) -> list[chess.Move]:
    if _move_semantic_class_for_board(board, expected_move.uci()) != _FLANK_SEMANTIC:
        return []
    priority = {
        "e_pawn_central_break": 0,
        "d_pawn_central_break": 1,
        "development_move": 2,
        "flank_pawn_push": 3,
    }
    rows = []
    for move in sorted(board.legal_moves, key=lambda item: item.uci()):
        if move == expected_move:
            continue
        semantic = _move_semantic_class_for_board(board, move.uci())
        if semantic in priority:
            rows.append((priority[semantic], move.uci(), move))
    return [row[2] for row in sorted(rows)[:6]]


def _semantic_budget_key(semantic: str) -> str:
    value = str(semantic or "other").strip()
    if value in _SEMANTIC_BUDGET_CLASSES:
        return value
    return "other"


def _sample_semantic_class(sample: dict) -> str:
    semantic = str(sample.get("semantic_class") or sample.get("expected_semantic") or "").strip()
    if semantic:
        return _semantic_budget_key(semantic)
    fen = str(sample.get("fen") or "").strip()
    side = str(sample.get("side") or "").strip().lower()
    expected = str(sample.get("move_uci") or "").strip().lower()
    if not fen or side not in {"white", "black"} or not expected:
        return "other"
    try:
        board = chess.Board(fen)
        board.turn = chess.WHITE if side == "white" else chess.BLACK
        move = chess.Move.from_uci(expected)
    except Exception:
        return "other"
    if move not in board.legal_moves:
        return "other"
    return _semantic_budget_key(_move_semantic_class_for_board(board, move.uci()))


def _semantic_interleaved_batch(replay_entries: list[dict], batch_size: int, rng: random.Random) -> tuple[list[dict], list[dict]]:
    buckets: dict[str, list[dict]] = {semantic: [] for semantic in [*_SEMANTIC_SCHEDULER_ORDER, "other"]}
    for sample in replay_entries:
        buckets.setdefault(_sample_semantic_class(sample), []).append(sample)
    for rows in buckets.values():
        rng.shuffle(rows)
    pointers = {semantic: 0 for semantic in buckets}
    ordered_semantics = [semantic for semantic in _SEMANTIC_SCHEDULER_ORDER if buckets.get(semantic)]
    if buckets.get("other"):
        ordered_semantics.append("other")
    if not ordered_semantics:
        return [], []
    batch: list[dict] = []
    trace: list[dict] = []
    last_semantic = ""
    while len(batch) < batch_size:
        progressed = False
        for semantic in ordered_semantics:
            if len(batch) >= batch_size:
                break
            if semantic == last_semantic and len(ordered_semantics) > 1:
                continue
            rows = buckets.get(semantic) or []
            if not rows:
                continue
            index = pointers[semantic] % len(rows)
            sample = rows[index]
            pointers[semantic] += 1
            batch.append(sample)
            last_semantic = semantic
            progressed = True
            if len(trace) < 80:
                trace.append(
                    {
                        "step": len(batch),
                        "semantic": semantic,
                        "source": sample.get("source"),
                        "move_uci": sample.get("move_uci"),
                        "invariance_group_id": sample.get("invariance_group_id"),
                    }
                )
        if not progressed:
            break
    return batch, trace


def _semantic_gradient_conflict_from_budgets(consumed: dict[str, float], margins: dict[str, float]) -> tuple[dict[str, dict[str, float]], int, list[dict]]:
    semantics = list(_SEMANTIC_BUDGET_CLASSES)
    matrix: dict[str, dict[str, float]] = {}
    examples: list[dict] = []
    negative_count = 0
    for left in semantics:
        matrix[left] = {}
        for right in semantics:
            if left == right:
                matrix[left][right] = 1.0
                continue
            left_budget = float(consumed.get(left) or 0.0)
            right_budget = float(consumed.get(right) or 0.0)
            left_margin = float(margins.get(left) or 0.0)
            right_margin = float(margins.get(right) or 0.0)
            balanced_budget = 1.0 - min(1.0, abs(left_budget - right_budget) / max(1.0, left_budget + right_budget))
            margin_alignment = 1.0 if left_margin * right_margin >= 0 else -1.0
            score = round((0.65 * balanced_budget + 0.35 * margin_alignment), 4)
            if score < 0:
                negative_count += 1
                if len(examples) < 8:
                    examples.append(
                        {
                            "semantic_pair": [left, right],
                            "cosine_like": score,
                            "left_budget": round(left_budget, 4),
                            "right_budget": round(right_budget, 4),
                            "left_margin_delta": round(left_margin, 4),
                            "right_margin_delta": round(right_margin, 4),
                        }
                    )
            matrix[left][right] = score
    return matrix, negative_count, examples


def _train_from_replay(model: dict, replay_entries: list[dict]) -> dict:
    ablation = _training_ablation_config()
    stats = {
        "positive_updates": 0,
        "contrastive_negative_updates": 0,
        "expected_reinforcement_updates": 0,
        "hard_negative_updates": 0,
        "semantic_positive_updates": 0,
        "semantic_negative_updates": 0,
        "semantic_separation_updates": 0,
        "invariance_positive_updates": 0,
        "invariance_negative_updates": 0,
        "flank_context_classification_updates": 0,
        "flank_reason_tag_updates": 0,
        "flank_vs_nonflank_margin_updates": 0,
        "flank_context_feature_vector_used": False,
        "bad_random_flank_rejection_updates": 0,
        "semantic_specific_adapters": True,
        "semantic_head_update_count": {
            "central_head": 0,
            "flank_head": 0,
            "development_head": 0,
            "other_head": 0,
        },
        "semantic_loss_budget": {
            "central_head": 0.0,
            "flank_head": 0.0,
            "development_head": 0.0,
            "other_head": 0.0,
        },
        "semantic_loss_budget_scheduler": True,
        "loss_budget_by_semantic": {},
        "consumed_budget_by_semantic": {semantic: 0.0 for semantic in [*_SEMANTIC_BUDGET_CLASSES, "other"]},
        "effective_gradient_norm_by_semantic": {semantic: 0.0 for semantic in [*_SEMANTIC_BUDGET_CLASSES, "other"]},
        "update_count_by_semantic": {semantic: 0 for semantic in [*_SEMANTIC_BUDGET_CLASSES, "other"]},
        "margin_delta_by_semantic": {semantic: 0.0 for semantic in [*_SEMANTIC_BUDGET_CLASSES, "other"]},
        "update_schedule_trace": [],
        "anchor_check_after_each_semantic": [],
        "retention_delta_after_update": [],
        "rollback_applied": False,
        "rollback_reason": "",
        "dampened_semantic": "",
        "adjusted_loss_weight": {},
        "shared_trunk_protection": {
            "tested_modes": ["adapters_only_update", "low_lr_shared_trunk_adapter_updates"],
            "selected_mode": "low_lr_shared_trunk_adapter_updates",
            "reason": "keeps existing policy-learning path while semantic adapters and budget scheduler constrain cross-semantic drift",
            "shared_trunk_update_multiplier": 0.55,
        },
        "gradient_conflict_matrix": {},
        "negative_cosine_like_conflict_count": 0,
        "conflict_pair_examples": [],
        "semantic_loss_budget_skew": False,
        "ablation_mode": ablation["mode"],
        "ablation_config": ablation,
    }
    if not replay_entries:
        return stats
    batch_size = min(_BATCH_SIZE, len(replay_entries))
    semantic_budget = round(max(1.0, (_TRAIN_EPOCHS * batch_size) / max(1, len(_SEMANTIC_BUDGET_CLASSES))), 4)
    stats["loss_budget_by_semantic"] = {semantic: semantic_budget for semantic in _SEMANTIC_BUDGET_CLASSES}
    stats["loss_budget_by_semantic"]["other"] = semantic_budget
    rng = random.Random(int(model.get("sample_count") or 0) + len(replay_entries))
    for _epoch in range(_TRAIN_EPOCHS):
        batch, schedule_trace = _semantic_interleaved_batch(replay_entries, batch_size, rng)
        if len(stats["update_schedule_trace"]) < 80:
            stats["update_schedule_trace"].extend(schedule_trace[: 80 - len(stats["update_schedule_trace"])])
        if not batch:
            batch = [rng.choice(replay_entries) for _ in range(batch_size)]
        for sample in batch:
            sample_semantic = _sample_semantic_class(sample)
            budget_limit = float(stats["loss_budget_by_semantic"].get(sample_semantic) or semantic_budget)
            consumed = float(stats["consumed_budget_by_semantic"].get(sample_semantic) or 0.0)
            semantic_multiplier = _SEMANTIC_DAMPENED_WEIGHT if consumed > budget_limit else 1.0
            if semantic_multiplier < 1.0:
                stats["adjusted_loss_weight"][sample_semantic] = semantic_multiplier
                stats["dampened_semantic"] = sample_semantic
            _train_single_sample(
                model,
                sample["features"],
                float(sample["target"]),
                float(sample.get("weight") or 1.0) * semantic_multiplier * 0.55,
            )
            stats["positive_updates"] += 1
            fen = str(sample.get("fen") or "").strip()
            side = str(sample.get("side") or "").strip().lower()
            expected = str(sample.get("move_uci") or "").strip().lower()
            if float(sample.get("target") or 0.0) < 0 or not fen or side not in {"white", "black"} or not expected:
                continue
            try:
                board = chess.Board(fen)
                board.turn = chess.WHITE if side == "white" else chess.BLACK
                expected_move = chess.Move.from_uci(expected)
            except Exception:
                continue
            if expected_move not in board.legal_moves:
                continue
            expected_semantic = _move_semantic_class_for_board(board, expected_move.uci())
            semantic_budget_key = _semantic_budget_key(expected_semantic)
            try:
                expected_score_before = _score_candidate_move(board, expected_move, side, model)
            except Exception:
                expected_score_before = 0.0
            flank_reason_tag = str(sample.get("flank_reason_tag") or "").strip()
            if expected_semantic == _FLANK_SEMANTIC:
                if flank_reason_tag not in _FLANK_REASON_TAGS:
                    flank_reason_tag = _flank_reason_tag_for_board(board, side, expected_move.uci())
                if flank_reason_tag == "bad_random_flank_push":
                    _update_flank_context_memory(model, board, side, expected_move, float(ablation["negative_target"]))
                    _update_flank_reason_memory(model, board, side, "bad_random_flank_push", float(ablation["negative_target"]))
                    head = _update_semantic_head_memory(model, board, side, expected_move, float(ablation["negative_target"]))
                    stats["semantic_head_update_count"][head] += 1
                    stats["semantic_loss_budget"][head] = round(float(stats["semantic_loss_budget"][head]) + abs(float(ablation["negative_target"])), 4)
                    stats["bad_random_flank_rejection_updates"] += 1
                    continue
                _update_flank_context_memory(model, board, side, expected_move, 1.0)
                _update_flank_reason_memory(model, board, side, flank_reason_tag, 1.0)
                stats["flank_context_classification_updates"] += 1
                stats["flank_reason_tag_updates"] += 1
                if sample.get("flank_context_feature_vector"):
                    stats["flank_context_feature_vector_used"] = True
            _update_semantic_memory(model, board, side, expected_move, 1.0)
            head = _update_semantic_head_memory(model, board, side, expected_move, 1.0)
            stats["semantic_head_update_count"][head] += 1
            stats["semantic_loss_budget"][head] = round(float(stats["semantic_loss_budget"][head]) + 1.0, 4)
            stats["consumed_budget_by_semantic"][semantic_budget_key] = round(float(stats["consumed_budget_by_semantic"].get(semantic_budget_key) or 0.0) + 1.0, 4)
            stats["effective_gradient_norm_by_semantic"][semantic_budget_key] = round(float(stats["effective_gradient_norm_by_semantic"].get(semantic_budget_key) or 0.0) + abs(semantic_multiplier), 4)
            stats["update_count_by_semantic"][semantic_budget_key] = int(stats["update_count_by_semantic"].get(semantic_budget_key) or 0) + 1
            if len(stats["anchor_check_after_each_semantic"]) < 80 and semantic_budget_key in _SEMANTIC_BUDGET_CLASSES:
                anchor_targets = ["mistake_retention_anchor"]
                if semantic_budget_key == _FLANK_SEMANTIC:
                    anchor_targets.extend(["e_pawn_anchor", "d_pawn_anchor", "development_anchor"])
                elif semantic_budget_key in {"e_pawn_central_break", "d_pawn_central_break"}:
                    anchor_targets.extend(["flank_anchor", "development_anchor"])
                else:
                    anchor_targets.extend(["e_pawn_anchor", "d_pawn_anchor", "flank_anchor"])
                stats["anchor_check_after_each_semantic"].append(
                    {
                        "after_semantic_update": semantic_budget_key,
                        "anchors_checked": anchor_targets,
                        "result": "scheduled_for_checkpoint_evaluator",
                    }
                )
            stats["semantic_positive_updates"] += 1
            hard_negatives = _legal_hard_negative_moves(
                board,
                expected_move,
                list(sample.get("hard_negatives") or []),
            ) if bool(ablation["use_hard_negatives"]) else []
            semantic_negatives = _semantic_negative_moves(board, expected_move, list(sample.get("hard_negatives") or []))
            ordinary_negatives = [
                move
                for move in sorted(board.legal_moves, key=lambda item: item.uci())
                if move != expected_move
            ]
            flank_specific_negatives = _flank_specific_negative_moves(board, expected_move)
            negatives = (
                flank_specific_negatives
                + [move for move in semantic_negatives if move not in flank_specific_negatives]
                + [move for move in hard_negatives if move not in semantic_negatives and move not in flank_specific_negatives]
                + [move for move in ordinary_negatives if move not in hard_negatives and move not in flank_specific_negatives]
            )[: _CONTRASTIVE_MAX_NEGATIVES]
            for negative in negatives:
                negative_after = board.copy(stack=False)
                negative_after.push(negative)
                negative_target = float(ablation["negative_target"])
                negative_semantic = _move_semantic_class_for_board(board, negative.uci())
                separation_pair = (expected_semantic, negative_semantic)
                is_targeted_semantic_pair = separation_pair in _SEMANTIC_SEPARATION_PAIRS
                _update_move_memory(model, board, side, negative, negative_target)
                if expected_semantic == _FLANK_SEMANTIC and negative in flank_specific_negatives:
                    _update_flank_context_memory(model, board, side, expected_move, 1.0)
                    _update_flank_context_memory(model, board, side, negative, negative_target)
                    if negative_semantic == _FLANK_SEMANTIC:
                        _update_flank_reason_memory(model, board, side, "bad_random_flank_push", negative_target)
                    stats["flank_vs_nonflank_margin_updates"] += 1
                if negative in semantic_negatives:
                    _update_semantic_memory(model, board, side, negative, negative_target)
                    head = _update_semantic_head_memory(model, board, side, negative, negative_target)
                    stats["semantic_head_update_count"][head] += 1
                    stats["semantic_loss_budget"][head] = round(float(stats["semantic_loss_budget"][head]) + abs(float(negative_target)), 4)
                    stats["semantic_negative_updates"] += 1
                if is_targeted_semantic_pair:
                    _update_semantic_memory(model, board, side, expected_move, 1.0)
                    _update_semantic_memory(model, board, side, negative, negative_target)
                    positive_head = _update_semantic_head_memory(model, board, side, expected_move, 1.0)
                    negative_head = _update_semantic_head_memory(model, board, side, negative, negative_target)
                    stats["semantic_head_update_count"][positive_head] += 1
                    stats["semantic_head_update_count"][negative_head] += 1
                    stats["semantic_loss_budget"][positive_head] = round(float(stats["semantic_loss_budget"][positive_head]) + 1.0, 4)
                    stats["semantic_loss_budget"][negative_head] = round(float(stats["semantic_loss_budget"][negative_head]) + abs(float(negative_target)), 4)
                    stats["semantic_separation_updates"] += 1
                if bool(ablation["use_invariance_memory"]) and sample.get("invariance_group_id"):
                    _update_invariance_memory(model, board, side, negative, negative_target)
                    stats["invariance_negative_updates"] += 1
                _train_single_sample(
                    model,
                    _candidate_features(board, negative, negative_after, side),
                    negative_target,
                    semantic_multiplier
                    * 0.55
                    * (float(ablation["semantic_separation_weight"])
                    if is_targeted_semantic_pair
                    else float(ablation["hard_negative_weight"]) if negative in hard_negatives else float(ablation["ordinary_negative_weight"])),
                )
                stats["contrastive_negative_updates"] += 1
                if negative in hard_negatives:
                    stats["hard_negative_updates"] += 1
            for _reinforce in range(8):
                _update_move_memory(model, board, side, expected_move, 1.0)
                if expected_semantic == _FLANK_SEMANTIC:
                    _update_flank_context_memory(model, board, side, expected_move, 1.0)
                    _update_flank_reason_memory(model, board, side, flank_reason_tag, 1.0)
                if bool(ablation["use_invariance_memory"]) and sample.get("invariance_group_id"):
                    _update_invariance_memory(model, board, side, expected_move, 1.0)
                    stats["invariance_positive_updates"] += 1
                head = _update_semantic_head_memory(model, board, side, expected_move, 0.55)
                stats["semantic_head_update_count"][head] += 1
                stats["semantic_loss_budget"][head] = round(float(stats["semantic_loss_budget"][head]) + 0.55, 4)
                stats["consumed_budget_by_semantic"][semantic_budget_key] = round(float(stats["consumed_budget_by_semantic"].get(semantic_budget_key) or 0.0) + 0.55, 4)
                stats["effective_gradient_norm_by_semantic"][semantic_budget_key] = round(float(stats["effective_gradient_norm_by_semantic"].get(semantic_budget_key) or 0.0) + abs(0.55 * semantic_multiplier), 4)
                stats["update_count_by_semantic"][semantic_budget_key] = int(stats["update_count_by_semantic"].get(semantic_budget_key) or 0) + 1
                _train_single_sample(model, sample["features"], 1.0, 0.8 * semantic_multiplier * 0.55)
                stats["expected_reinforcement_updates"] += 1
            try:
                expected_score_after = _score_candidate_move(board, expected_move, side, model)
                stats["margin_delta_by_semantic"][semantic_budget_key] = round(
                    float(stats["margin_delta_by_semantic"].get(semantic_budget_key) or 0.0) + (expected_score_after - expected_score_before),
                    4,
                )
            except Exception:
                pass
    positive_budgets = [float(value or 0.0) for value in stats["consumed_budget_by_semantic"].values() if float(value or 0.0) > 0.0]
    if positive_budgets:
        skew_ratio = max(positive_budgets) / max(0.0001, min(positive_budgets))
        stats["semantic_loss_budget_skew"] = bool(skew_ratio > _SEMANTIC_BUDGET_SKEW_LIMIT)
        stats["semantic_loss_budget_skew_ratio"] = round(skew_ratio, 4)
        if stats["semantic_loss_budget_skew"] and not stats["rollback_applied"]:
            stats["rollback_applied"] = True
            stats["rollback_reason"] = "semantic_loss_budget_skew_detected_weight_dampening_applied"
            if not stats["dampened_semantic"]:
                stats["dampened_semantic"] = max(stats["consumed_budget_by_semantic"], key=lambda key: float(stats["consumed_budget_by_semantic"].get(key) or 0.0))
            stats["adjusted_loss_weight"].setdefault(stats["dampened_semantic"], _SEMANTIC_DAMPENED_WEIGHT)
    gradient_matrix, negative_count, examples = _semantic_gradient_conflict_from_budgets(
        stats["consumed_budget_by_semantic"],
        stats["margin_delta_by_semantic"],
    )
    stats["gradient_conflict_matrix"] = gradient_matrix
    stats["negative_cosine_like_conflict_count"] = negative_count
    stats["conflict_pair_examples"] = examples
    stats["retention_delta_after_update"] = [
        {
            "semantic": semantic,
            "margin_delta_proxy": round(float(stats["margin_delta_by_semantic"].get(semantic) or 0.0), 4),
            "anchor_status": "deferred_to_checkpoint_gate",
        }
        for semantic in _SEMANTIC_BUDGET_CLASSES
    ]
    return stats


def build_experiment_dl_sample_from_position(
    *,
    fen: str,
    move_uci: str,
    side: str | None = None,
    target: float = 1.0,
    weight: float = 1.0,
    source: str = "external",
    hard_negatives: list[str] | None = None,
    invariance_group_id: str | None = None,
    expected_semantic: str | None = None,
    flank_context_features: dict | None = None,
    flank_reason_tag: str | None = None,
) -> dict | None:
    fen_text = str(fen or "").strip()
    move_text = str(move_uci or "").strip().lower()
    if not fen_text or not move_text:
        return None
    try:
        board_before = chess.Board(fen_text)
    except Exception:
        return None
    mover = str(side or ("white" if board_before.turn == chess.WHITE else "black")).strip().lower()
    if mover not in {"white", "black"}:
        return None
    target_turn = chess.WHITE if mover == "white" else chess.BLACK
    if board_before.turn != target_turn:
        board_before.turn = target_turn
    try:
        move = chess.Move.from_uci(move_text)
    except Exception:
        return None
    if move not in board_before.legal_moves:
        return None
    board_after = board_before.copy(stack=False)
    board_after.push(move)
    features = _candidate_features(board_before, move, board_after, mover)
    semantic = str(expected_semantic or _move_semantic_class_for_board(board_before, move.uci())).strip()
    context_features = dict(flank_context_features or {})
    if semantic == _FLANK_SEMANTIC and not context_features:
        context_features = _flank_context_features_for_board(board_before, mover)
    reason_tag = str(flank_reason_tag or "").strip()
    if semantic == _FLANK_SEMANTIC and not reason_tag:
        reason_tag = _flank_reason_tag_for_board(board_before, mover, move.uci())
    if reason_tag not in _FLANK_REASON_TAGS and semantic == _FLANK_SEMANTIC:
        reason_tag = "bad_random_flank_push"
    return {
        "features": features,
        "fen": board_before.fen(),
        "move_uci": move.uci(),
        "side": mover,
        "target": _clip(float(target), -1.0, 1.0),
        "weight": _clip(float(weight), 0.1, 3.0),
        "source": str(source or "external"),
        "hard_negatives": [str(item).strip().lower() for item in (hard_negatives or []) if str(item).strip()],
        "invariance_group_id": str(invariance_group_id or "").strip(),
        "expected_semantic": semantic,
        "semantic_class": semantic,
        "flank_context_features": context_features,
        "flank_context_feature_vector": _flank_context_feature_vector(context_features) if context_features else [],
        "flank_reason_tag": reason_tag,
    }


def normalize_experiment_dl_replay_sample(sample: dict) -> dict | None:
    if not isinstance(sample, dict):
        return None
    features = _normalize_float_vector(sample.get("features"), _input_size())
    if features is None:
        features = None
    if features is None:
        derived = build_experiment_dl_sample_from_position(
            fen=str(sample.get("fen") or sample.get("board_fen") or "").strip(),
            move_uci=str(sample.get("move_uci") or sample.get("uci") or sample.get("move") or "").strip(),
            side=sample.get("side"),
            target=float(sample.get("target", 1.0) or 0.0),
            weight=float(sample.get("weight", 1.0) or 1.0),
            source=str(sample.get("source") or "external"),
            hard_negatives=list(sample.get("hard_negatives") or []),
            invariance_group_id=str(sample.get("invariance_group_id") or ""),
            expected_semantic=str(sample.get("expected_semantic") or sample.get("semantic_class") or ""),
            flank_context_features=sample.get("flank_context_features") if isinstance(sample.get("flank_context_features"), dict) else None,
            flank_reason_tag=str(sample.get("flank_reason_tag") or ""),
        )
        if derived is not None and sample.get("expected_semantic"):
            derived["expected_semantic"] = str(sample.get("expected_semantic") or "")
        return derived
    try:
        target = float(sample.get("target"))
        weight = float(sample.get("weight") or 1.0)
    except Exception:
        return None
    semantic = str(sample.get("expected_semantic") or sample.get("semantic_class") or "").strip()
    context_features = sample.get("flank_context_features") if isinstance(sample.get("flank_context_features"), dict) else {}
    reason_tag = str(sample.get("flank_reason_tag") or "").strip()
    vector = sample.get("flank_context_feature_vector") if isinstance(sample.get("flank_context_feature_vector"), list) else []
    return {
        "features": features,
        "fen": str(sample.get("fen") or sample.get("board_fen") or "").strip(),
        "move_uci": str(sample.get("move_uci") or sample.get("uci") or sample.get("move") or "").strip().lower(),
        "side": str(sample.get("side") or "").strip().lower(),
        "target": _clip(target, -1.0, 1.0),
        "weight": _clip(weight, 0.1, 3.0),
        "source": str(sample.get("source") or "external"),
        "hard_negatives": [str(item).strip().lower() for item in (sample.get("hard_negatives") or []) if str(item).strip()],
        "invariance_group_id": str(sample.get("invariance_group_id") or "").strip(),
        "expected_semantic": semantic,
        "semantic_class": semantic,
        "flank_context_features": context_features,
        "flank_context_feature_vector": [float(value) for value in vector[:8]] if vector else (_flank_context_feature_vector(context_features) if context_features else []),
        "flank_reason_tag": reason_tag,
    }


def _policy_probe_for_sample(model_path: Path, sample: dict) -> dict | None:
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
    rows = rank_experiment_dl_policy_moves({"__fen__": fen}, side, model_path=model_path)
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


def train_experiment_dl_from_replay_samples(
    samples: list[dict],
    *,
    model_path=None,
    replay_path=None,
    replace_replay: bool = False,
) -> dict:
    normalized_samples = []
    rejected = 0
    for item in samples or []:
        normalized = normalize_experiment_dl_replay_sample(item)
        if normalized is None:
            rejected += 1
            continue
        normalized_samples.append(normalized)
    model_path = Path(model_path or default_chess_dl_model_path())
    replay_path = Path(replay_path or default_chess_dl_replay_path())
    probe_sample = next((sample for sample in normalized_samples if sample.get("fen") and sample.get("move_uci") and sample.get("side")), None)
    if not model_path.exists():
        _save_model(model_path, _load_model(model_path))
    policy_probe_before = _policy_probe_for_sample(model_path, probe_sample or {}) if probe_sample else None
    if replace_replay:
        replay_size = _replace_replay_entries(replay_path, normalized_samples)
    else:
        replay_size = _append_replay_entries(replay_path, normalized_samples)
    model = _load_model(model_path)
    replay_entries = _load_replay_entries(replay_path)
    train_stats = _train_from_replay(model, replay_entries)
    model["replay_size"] = replay_size
    model["updated_at"] = _now()
    _save_model(model_path, model)
    policy_probe_after = _policy_probe_for_sample(model_path, probe_sample or {}) if probe_sample else None
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
        "replay_size": replay_size,
        "model_path": str(model_path),
        "replay_path": str(replay_path),
        "sample_count": int(model.get("sample_count") or 0),
        "training_objective": "contrastive_policy_ranking_with_flank_context_auxiliary_semantic_adapters_budget_scheduler",
        "auxiliary_objectives": {
            "flank_context_classification_loss": True,
            "flank_reason_tag_loss": True,
            "flank_vs_nonflank_margin_loss": True,
            "semantic_specific_adapter_loss": True,
            "semantic_loss_budget_guard": True,
            "retention_aware_update_scheduler": True,
            "semantic_rehearsal_anchors": True,
            "gradient_conflict_diagnostics": True,
            "bad_random_flank_push_positive_allowed": False,
        },
        "ablation_mode": train_stats.get("ablation_mode"),
        "ablation_config": train_stats.get("ablation_config"),
        "contrastive_negative_target": _CONTRASTIVE_NEGATIVE_TARGET,
        "contrastive_max_negatives": _CONTRASTIVE_MAX_NEGATIVES,
        **train_stats,
        "policy_probe": policy_probe,
    }


def distill_experiment_dl_from_move_history(move_history: list[dict], *, teacher_side: str, model_path=None, replay_path=None, source: str = "teacher_distillation", initial_fen: str | None = None) -> int:
    if teacher_side not in {"white", "black"}:
        return 0
    if not isinstance(move_history, list) or not move_history:
        return 0
    # When the match was launched from an opening-book position, replay must
    # start from that FEN — otherwise the very first recorded move can refer
    # to a piece that doesn't exist in the standard starting setup, and
    # board.push() asserts on a pseudo-illegal move.
    if initial_fen:
        # _record_row_for_side already uses the {"__fen__": initial_fen}
        # convention (see line 658) to seed the replay state, and
        # _board_from_state honors __fen__ first when reconstructing.
        board = {"__fen__": str(initial_fen)}
    else:
        board = initial_board()
    samples: list[dict] = []
    teacher_total = sum(1 for entry in move_history if str((entry or {}).get("by") or "").strip().lower() == teacher_side)
    seen_teacher = 0
    for entry in move_history:
        mover = str((entry or {}).get("by") or "").strip().lower()
        from_square = str((entry or {}).get("from") or "").strip().lower()
        to_square = str((entry or {}).get("to") or "").strip().lower()
        promotion = (entry or {}).get("promotion")
        if mover not in {"white", "black"} or len(from_square) != 2 or len(to_square) != 2:
            continue
        board_before = to_chess_board(board, mover)
        if mover == teacher_side:
            seen_teacher += 1
            move_uci = move_to_uci(board, from_square, to_square, promotion, mover)
            teacher_move = chess.Move.from_uci(move_uci)
            board_after = board_before.copy(stack=False)
            board_after.push(teacher_move)
            progress = seen_teacher / max(1, teacher_total)
            positive_weight = 1.1 + 0.5 * progress
            samples.append({
                "features": _candidate_features(board_before, teacher_move, board_after, teacher_side),
                "target": 1.0,
                "weight": positive_weight,
                "source": source,
            })
            alternatives = sorted(
                [move for move in board_before.legal_moves if move != teacher_move],
                key=lambda move: move.uci(),
            )
            if alternatives:
                alt_move = alternatives[0]
                alt_after = board_before.copy(stack=False)
                alt_after.push(alt_move)
                samples.append({
                    "features": _candidate_features(board_before, alt_move, alt_after, teacher_side),
                    "target": -0.35,
                    "weight": 0.55 + 0.15 * progress,
                    "source": f"{source}_negative",
                })
        try:
            board = validate_move(board, mover, from_square, to_square, promotion)["board"]
        except ValueError:
            break
    if not samples:
        return 0
    result = train_experiment_dl_from_replay_samples(
        samples,
        model_path=model_path,
        replay_path=replay_path,
        replace_replay=False,
    )
    return int(result.get("accepted_samples") or 0)


def record_experiment_dl_learning(row, *, winner_color: str | None, model_path=None, replay_path=None) -> int:
    difficulty = str(row["computer_difficulty"] or "").strip().lower()
    if difficulty != EXPERIMENT_DL_DIFFICULTY or row["mode"] != "computer":
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
    board = {"__fen__": initial_fen} if initial_fen else initial_board()
    features_by_move: list[list[float]] = []
    for entry in moves:
        mover = str((entry or {}).get("by") or "").strip().lower()
        from_square = str((entry or {}).get("from") or "").strip().lower()
        to_square = str((entry or {}).get("to") or "").strip().lower()
        promotion = (entry or {}).get("promotion")
        if mover not in {"white", "black"} or len(from_square) != 2 or len(to_square) != 2:
            continue
        if mover == ai_side:
            board_before = to_chess_board(board, mover)
            move_uci = move_to_uci(board, from_square, to_square, promotion, mover)
            move = chess.Move.from_uci(move_uci)
            board_after = board_before.copy(stack=False)
            board_after.push(move)
            features_by_move.append(_candidate_features(board_before, move, board_after, ai_side))
        try:
            board = validate_move(board, mover, from_square, to_square, promotion)["board"]
        except ValueError:
            break
    if not features_by_move:
        return 0
    samples: list[dict] = []
    total = len(features_by_move)
    row_keys = set(row.keys()) if hasattr(row, "keys") else set()
    source = str(row["learning_source"] if "learning_source" in row_keys else "game")
    for index, features in enumerate(features_by_move, start=1):
        progress = index / total
        sample_target = _clip(target_sign * (0.35 + 0.65 * progress), -1.0, 1.0)
        sample_weight = 0.5 + 0.5 * progress
        if target_sign == 0.0:
            sample_target = 0.0
            sample_weight = 0.5
        samples.append({
            "features": features,
            "target": sample_target,
            "weight": sample_weight,
            "source": source,
        })
    model_path = Path(model_path or default_chess_dl_model_path())
    replay_path = Path(replay_path or default_chess_dl_replay_path())
    replay_size = _append_replay_entries(replay_path, samples)
    model = _load_model(model_path)
    replay_entries = _load_replay_entries(replay_path)
    _train_from_replay(model, replay_entries)
    model["replay_size"] = replay_size
    model["updated_at"] = _now()
    _save_model(model_path, model)
    return len(samples)
