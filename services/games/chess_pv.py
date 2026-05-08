"""Policy/value-backed helpers for the ``experiment 4:PV`` chess difficulty.

This module is the pragmatic final-phase prototype:

- better board encoding than the move-feature-only NN/DL engines
- a dual-head model with policy prior + value estimation
- integration with the shared alpha-beta search stack

It deliberately stays CPU-friendly and JSON-serializable so it fits the
current Python repo without introducing heavyweight NNUE/MCTS machinery.
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
_VALUE_SCORE_SCALE = 180.0
_PIECE_VALUES = {
    chess.PAWN: 100,
    chess.KNIGHT: 320,
    chess.BISHOP: 335,
    chess.ROOK: 500,
    chess.QUEEN: 900,
    chess.KING: 20000,
}


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
    if board.is_check():
        score += -30 if board.turn == chess.WHITE else 30
    score += int(value_score * _VALUE_SCORE_SCALE)
    eval_cache[board_hash] = score
    return score


def _candidate_move_features(board: chess.Board, move: chess.Move, side: str) -> list[float]:
    before = board.copy(stack=False)
    after = before.copy(stack=False)
    after.push(move)
    return _candidate_features(before, move, after, side)


def choose_experiment_pv_move(board_state, side: str, *, model_path=None):
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

        def move_order_fn(current_board: chess.Board, move: chess.Move, _ply: int) -> int:
            current_side = "white" if current_board.turn == chess.WHITE else "black"
            board_features = _board_planes(current_board)
            hidden = _forward_shared(model, board_features)
            move_features = _candidate_move_features(current_board, move, current_side)
            return int(_policy_from_hidden(model, hidden, move_features) * 1000.0)

        search = search_best_move(
            board,
            max_depth=_SEARCH_DEPTH,
            evaluate=lambda current_board: _pv_static_eval(current_board, model, eval_cache, hasher),
            move_order_fn=move_order_fn,
            hasher=hasher,
            quiescence_depth=_SEARCH_QUIESCENCE_DEPTH,
        )
        best_move = search.best_move
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


def _train_single_sample(model: dict, board_features: list[float], move_features: list[float], *, value_target: float, policy_target: float) -> None:
    hidden = _forward_shared(model, board_features)
    value_pred = _value_from_hidden(model, hidden)
    policy_pred = _policy_from_hidden(model, hidden, move_features)

    delta_value = (float(value_target) - float(value_pred)) * (1.0 - float(value_pred) * float(value_pred))
    delta_policy = (float(policy_target) - float(policy_pred)) * (1.0 - float(policy_pred) * float(policy_pred))

    shared_deltas: list[float] = []
    for hidden_index, hidden_value in enumerate(hidden):
        downstream = float(model["value_w"][hidden_index]) * delta_value
        downstream += float(model["policy_shared_w"][hidden_index]) * delta_policy
        shared_deltas.append((1.0 - hidden_value * hidden_value) * downstream)

    for index, hidden_value in enumerate(hidden):
        model["value_w"][index] = _clip(float(model["value_w"][index]) + _LEARNING_RATE * delta_value * hidden_value, -_MAX_ABS_WEIGHT, _MAX_ABS_WEIGHT)
        model["policy_shared_w"][index] = _clip(float(model["policy_shared_w"][index]) + _LEARNING_RATE * delta_policy * hidden_value, -_MAX_ABS_WEIGHT, _MAX_ABS_WEIGHT)
    for index, feature in enumerate(move_features):
        model["policy_move_w"][index] = _clip(float(model["policy_move_w"][index]) + _LEARNING_RATE * delta_policy * feature, -_MAX_ABS_WEIGHT, _MAX_ABS_WEIGHT)
    model["value_b"] = _clip(float(model["value_b"]) + _LEARNING_RATE * delta_value, -_MAX_ABS_WEIGHT, _MAX_ABS_WEIGHT)
    model["policy_b"] = _clip(float(model["policy_b"]) + _LEARNING_RATE * delta_policy, -_MAX_ABS_WEIGHT, _MAX_ABS_WEIGHT)

    for row_index, row in enumerate(model["shared_w"]):
        delta_hidden = shared_deltas[row_index]
        for col_index, feature in enumerate(board_features):
            row[col_index] = _clip(float(row[col_index]) + _LEARNING_RATE * delta_hidden * feature, -_MAX_ABS_WEIGHT, _MAX_ABS_WEIGHT)
        model["shared_b"][row_index] = _clip(float(model["shared_b"][row_index]) + _LEARNING_RATE * delta_hidden, -_MAX_ABS_WEIGHT, _MAX_ABS_WEIGHT)

    model["sample_count"] = int(model.get("sample_count") or 0) + 1
    model["updated_at"] = _now()


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
