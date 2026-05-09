"""Neural-network-backed helpers for the ``experiment 2:NN`` chess difficulty.

This engine is intentionally lightweight:

- It keeps all generated state under ``runtime/`` via a dedicated model file.
- It does not replace the existing ``experiment`` difficulty.
- It starts from a heuristic bootstrap and gradually gives more weight to the
  learned model as more games are recorded.
- The JSON payload is intentionally stable so external training programs can
  emit a compatible model file without importing the app itself.
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
from services.games.chess_model_registry import bundled_seed_model_path, runtime_model_path


EXPERIMENT_NN_DIFFICULTY = "experiment 2:nn"
DEFAULT_CHESS_NN_MODEL_NAME = "chess_experiment_2_nn.json"
_HIDDEN_SIZE = 16
_LEARNING_RATE = 0.035
_MAX_ABS_WEIGHT = 3.0
_NN_VERSION = 1
_PIECE_VALUES = {
    chess.PAWN: 100,
    chess.KNIGHT: 320,
    chess.BISHOP: 330,
    chess.ROOK: 500,
    chess.QUEEN: 900,
    chess.KING: 20000,
}
_TRACKED_PIECES = (
    chess.PAWN,
    chess.KNIGHT,
    chess.BISHOP,
    chess.ROOK,
    chess.QUEEN,
)


def default_chess_nn_model_path() -> Path:
    return runtime_model_path(DEFAULT_CHESS_NN_MODEL_NAME, env_var="HTML_LEARNING_CHESS_ENGINE_NN_MODEL_PATH")


def bundled_chess_nn_model_path() -> Path:
    return bundled_seed_model_path(DEFAULT_CHESS_NN_MODEL_NAME)


def _now() -> str:
    return datetime.now().isoformat()


def _perspective_square(square: int, ai_color: bool) -> int:
    return chess.square_mirror(square) if ai_color == chess.BLACK else square


def _normalized_coord(square: int, ai_color: bool) -> tuple[float, float]:
    view = _perspective_square(square, ai_color)
    file_index = chess.square_file(view)
    rank_index = chess.square_rank(view)
    return ((file_index - 3.5) / 3.5, (rank_index - 3.5) / 3.5)


def _one_hot(index: int, size: int) -> list[float]:
    return [1.0 if i == index else 0.0 for i in range(size)]


def _piece_index(piece_type: int | None) -> int:
    order = {
        chess.PAWN: 0,
        chess.KNIGHT: 1,
        chess.BISHOP: 2,
        chess.ROOK: 3,
        chess.QUEEN: 4,
        chess.KING: 5,
    }
    return order.get(piece_type or 0, 5)


def _tracked_piece_index(piece_type: int | None) -> int:
    order = {
        None: 0,
        chess.PAWN: 1,
        chess.KNIGHT: 2,
        chess.BISHOP: 3,
        chess.ROOK: 4,
        chess.QUEEN: 5,
        chess.KING: 6,
    }
    return order.get(piece_type, 0)


def _promotion_index(piece_type: int | None) -> int:
    order = {
        None: 0,
        chess.KNIGHT: 1,
        chess.BISHOP: 2,
        chess.ROOK: 3,
        chess.QUEEN: 4,
    }
    return order.get(piece_type, 0)


def _clip(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _board_legal_count(board: chess.Board, color: bool) -> float:
    original_turn = board.turn
    board.turn = color
    try:
        return float(board.legal_moves.count())
    finally:
        board.turn = original_turn


def _board_is_check_for(board: chess.Board, color: bool) -> bool:
    original_turn = board.turn
    board.turn = color
    try:
        return bool(board.is_check())
    finally:
        board.turn = original_turn


def _material_balance(board: chess.Board, ai_color: bool) -> float:
    score = 0
    for piece in board.piece_map().values():
        value = _PIECE_VALUES[piece.piece_type]
        score += value if piece.color == ai_color else -value
    return score / 4000.0


def _piece_count_features(board: chess.Board, ai_color: bool) -> list[float]:
    own = {piece_type: 0 for piece_type in _TRACKED_PIECES}
    opp = {piece_type: 0 for piece_type in _TRACKED_PIECES}
    for piece in board.piece_map().values():
        target = own if piece.color == ai_color else opp
        if piece.piece_type in target:
            target[piece.piece_type] += 1
    features: list[float] = []
    for piece_type in _TRACKED_PIECES:
        features.append(own[piece_type] / 8.0)
    for piece_type in _TRACKED_PIECES:
        features.append(opp[piece_type] / 8.0)
    return features


def _heuristic_after_move(board_after: chess.Board, move: chess.Move, ai_color: bool, captured_piece_type: int | None) -> float:
    if board_after.is_checkmate():
        return 1.5
    if board_after.is_stalemate() or board_after.is_insufficient_material():
        return 0.0
    static_balance = _material_balance(board_after, ai_color)
    ai_mobility = _board_legal_count(board_after, ai_color) / 40.0
    opp_mobility = _board_legal_count(board_after, not ai_color) / 40.0
    capture_bonus = (_PIECE_VALUES.get(captured_piece_type or 0, 0) / 2000.0) if captured_piece_type else 0.0
    promotion_bonus = (_PIECE_VALUES.get(move.promotion or 0, 0) / 2000.0) if move.promotion else 0.0
    score = static_balance + (ai_mobility - opp_mobility) * 0.35 + capture_bonus + promotion_bonus
    if board_after.is_check():
        score += 0.12
    if _board_is_check_for(board_after, ai_color):
        score -= 0.35
    if board_after.is_castling(move):
        score += 0.05
    return _clip(score, -1.75, 1.75)


def _candidate_features(board_before: chess.Board, move: chess.Move, board_after: chess.Board, ai_side: str) -> list[float]:
    ai_color = chess.WHITE if ai_side == "white" else chess.BLACK
    moving_piece = board_before.piece_at(move.from_square)
    captured_piece = board_before.piece_at(move.to_square)
    if captured_piece is None and board_before.is_en_passant(move):
        capture_square = chess.square(chess.square_file(move.to_square), chess.square_rank(move.from_square))
        captured_piece = board_before.piece_at(capture_square)

    from_file, from_rank = _normalized_coord(move.from_square, ai_color)
    to_file, to_rank = _normalized_coord(move.to_square, ai_color)
    ai_mobility = _board_legal_count(board_after, ai_color) / 40.0
    opp_mobility = _board_legal_count(board_after, not ai_color) / 40.0
    center_distance = abs(to_file) + abs(to_rank)
    center_score = _clip(1.0 - center_distance / 2.0, -1.0, 1.0)
    features: list[float] = []
    features.extend(_piece_count_features(board_after, ai_color))
    features.append(_material_balance(board_after, ai_color))
    features.append(ai_mobility)
    features.append(opp_mobility)
    features.extend(
        [
            1.0 if board_after.has_kingside_castling_rights(ai_color) else 0.0,
            1.0 if board_after.has_queenside_castling_rights(ai_color) else 0.0,
            1.0 if board_after.has_kingside_castling_rights(not ai_color) else 0.0,
            1.0 if board_after.has_queenside_castling_rights(not ai_color) else 0.0,
        ]
    )
    features.append(1.0 if board_after.is_check() else 0.0)
    features.append(1.0 if _board_is_check_for(board_after, ai_color) else 0.0)
    features.extend([from_file, from_rank, to_file, to_rank, to_file - from_file, to_rank - from_rank])
    features.extend(_one_hot(_piece_index(moving_piece.piece_type if moving_piece else None), 6))
    features.extend(_one_hot(_tracked_piece_index(captured_piece.piece_type if captured_piece else None), 7))
    features.extend(_one_hot(_promotion_index(move.promotion), 5))
    features.extend(
        [
            1.0 if captured_piece else 0.0,
            1.0 if board_before.is_castling(move) else 0.0,
            1.0 if board_before.is_en_passant(move) else 0.0,
            1.0 if board_after.is_check() else 0.0,
        ]
    )
    features.append(center_score)
    features.append(_heuristic_after_move(board_after, move, ai_color, captured_piece.piece_type if captured_piece else None))
    return features


def _input_size() -> int:
    sample_board = chess.Board()
    sample_move = chess.Move.from_uci("e2e4")
    sample_after = sample_board.copy(stack=False)
    sample_after.push(sample_move)
    return len(_candidate_features(sample_board, sample_move, sample_after, "white"))


def _random_matrix(rows: int, cols: int, *, rng: random.Random) -> list[list[float]]:
    return [[rng.uniform(-0.08, 0.08) for _ in range(cols)] for _ in range(rows)]


def experiment_nn_model_template() -> dict:
    rng = random.Random(20260507)
    inputs = _input_size()
    return {
        "version": _NN_VERSION,
        "architecture": "mlp-49x16x1",
        "input_size": inputs,
        "hidden_size": _HIDDEN_SIZE,
        "w1": _random_matrix(_HIDDEN_SIZE, inputs, rng=rng),
        "b1": [rng.uniform(-0.02, 0.02) for _ in range(_HIDDEN_SIZE)],
        "w2": [rng.uniform(-0.08, 0.08) for _ in range(_HIDDEN_SIZE)],
        "b2": rng.uniform(-0.02, 0.02),
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


def normalize_experiment_nn_model_payload(model: dict) -> dict | None:
    if not isinstance(model, dict):
        return None
    inputs = _input_size()
    if int(model.get("version") or 0) != _NN_VERSION:
        return None
    if int(model.get("input_size") or 0) != inputs:
        return None
    if int(model.get("hidden_size") or 0) != _HIDDEN_SIZE:
        return None
    w1 = _normalize_float_matrix(model.get("w1"), _HIDDEN_SIZE, inputs)
    b1 = _normalize_float_vector(model.get("b1"), _HIDDEN_SIZE)
    w2 = _normalize_float_vector(model.get("w2"), _HIDDEN_SIZE)
    if w1 is None or b1 is None or w2 is None:
        return None
    try:
        b2 = float(model.get("b2"))
    except Exception:
        return None
    return {
        "version": _NN_VERSION,
        "architecture": "mlp-49x16x1",
        "input_size": inputs,
        "hidden_size": _HIDDEN_SIZE,
        "w1": w1,
        "b1": b1,
        "w2": w2,
        "b2": b2,
        "sample_count": max(0, int(model.get("sample_count") or 0)),
        "updated_at": str(model.get("updated_at") or _now()),
    }


def _initial_model() -> dict:
    return experiment_nn_model_template()


def _load_model(model_path: Path) -> dict:
    path = Path(model_path)
    if not path.exists():
        return _initial_model()
    try:
        model = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return _initial_model()
    normalized = normalize_experiment_nn_model_payload(model)
    return normalized or _initial_model()


def _save_model(model_path: Path, model: dict) -> None:
    path = Path(model_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(json.dumps(model, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    tmp_path.replace(path)


def _forward(model: dict, features: list[float]) -> tuple[float, list[float]]:
    hidden_values: list[float] = []
    for row, bias in zip(model["w1"], model["b1"]):
        total = float(bias)
        for weight, feature in zip(row, features):
            total += float(weight) * float(feature)
        hidden_values.append(math.tanh(total))
    output_total = float(model["b2"])
    for weight, hidden in zip(model["w2"], hidden_values):
        output_total += float(weight) * float(hidden)
    return math.tanh(output_total), hidden_values


def _training_target(ai_side: str, winner_color: str | None) -> float:
    if winner_color == ai_side:
        return 1.0
    if winner_color is None:
        return 0.0
    return -1.0


def choose_experiment_nn_move(board_state, side: str, *, model_path=None):
    board = to_chess_board(board_state, side)
    ai_color = chess.WHITE if side == "white" else chess.BLACK
    if board.turn != ai_color:
        board.turn = ai_color
    if board.is_game_over():
        return None
    model = _load_model(Path(model_path or default_chess_nn_model_path()))
    sample_count = int(model.get("sample_count") or 0)
    learned_weight = _clip(sample_count / 200.0, 0.0, 0.75)
    best_move = None
    best_score = -10.0
    for move in board.legal_moves:
        before = board.copy(stack=False)
        moving_piece = before.piece_at(move.from_square)
        captured_piece = before.piece_at(move.to_square)
        if captured_piece is None and before.is_en_passant(move):
            capture_square = chess.square(chess.square_file(move.to_square), chess.square_rank(move.from_square))
            captured_piece = before.piece_at(capture_square)
        board.push(move)
        features = _candidate_features(before, move, board, side)
        nn_score, _hidden = _forward(model, features)
        heuristic = _heuristic_after_move(board, move, ai_color, captured_piece.piece_type if captured_piece else None)
        score = heuristic * (1.0 - learned_weight) + nn_score * learned_weight
        if board.is_checkmate():
            score += 10.0
        if _board_is_check_for(board, ai_color):
            score -= 2.0
        board.pop()
        if best_move is None or score > best_score or (abs(score - best_score) < 1e-9 and move.uci() < best_move.uci()):
            best_move = move
            best_score = score
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


def _train_single_sample(model: dict, features: list[float], target: float, weight: float = 1.0) -> None:
    prediction, hidden = _forward(model, features)
    delta_out = (float(target) - float(prediction)) * (1.0 - float(prediction) * float(prediction)) * float(weight)
    hidden_deltas = []
    for weight, hidden_value in zip(model["w2"], hidden):
        hidden_deltas.append((1.0 - hidden_value * hidden_value) * float(weight) * delta_out)
    for index, hidden_value in enumerate(hidden):
        model["w2"][index] = _clip(float(model["w2"][index]) + _LEARNING_RATE * delta_out * hidden_value, -_MAX_ABS_WEIGHT, _MAX_ABS_WEIGHT)
    model["b2"] = _clip(float(model["b2"]) + _LEARNING_RATE * delta_out, -_MAX_ABS_WEIGHT, _MAX_ABS_WEIGHT)
    for row_index, row in enumerate(model["w1"]):
        delta_hidden = hidden_deltas[row_index]
        for col_index, feature in enumerate(features):
            row[col_index] = _clip(float(row[col_index]) + _LEARNING_RATE * delta_hidden * float(feature), -_MAX_ABS_WEIGHT, _MAX_ABS_WEIGHT)
        model["b1"][row_index] = _clip(float(model["b1"][row_index]) + _LEARNING_RATE * delta_hidden, -_MAX_ABS_WEIGHT, _MAX_ABS_WEIGHT)
    model["sample_count"] = int(model.get("sample_count") or 0) + 1
    model["updated_at"] = _now()


def build_experiment_nn_sample_from_position(
    *,
    fen: str,
    move_uci: str,
    side: str | None = None,
    target: float = 1.0,
    weight: float = 1.0,
    source: str = "external",
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
    return {
        "features": _candidate_features(board_before, move, board_after, mover),
        "target": _clip(float(target), -1.0, 1.0),
        "weight": _clip(float(weight), 0.1, 3.0),
        "source": str(source or "external"),
    }


def normalize_experiment_nn_replay_sample(sample: dict) -> dict | None:
    if not isinstance(sample, dict):
        return None
    features = _normalize_float_vector(sample.get("features"), _input_size())
    if features is None:
        return build_experiment_nn_sample_from_position(
            fen=str(sample.get("fen") or sample.get("board_fen") or "").strip(),
            move_uci=str(sample.get("move_uci") or sample.get("uci") or sample.get("move") or "").strip(),
            side=sample.get("side"),
            target=float(sample.get("target", 1.0) or 0.0),
            weight=float(sample.get("weight", 1.0) or 1.0),
            source=str(sample.get("source") or "external"),
        )
    try:
        target = float(sample.get("target"))
        weight = float(sample.get("weight") or 1.0)
    except Exception:
        return None
    return {
        "features": features,
        "target": _clip(target, -1.0, 1.0),
        "weight": _clip(weight, 0.1, 3.0),
        "source": str(sample.get("source") or "external"),
    }


def train_experiment_nn_from_replay_samples(samples: list[dict], *, model_path=None) -> dict:
    normalized_samples = []
    rejected = 0
    for item in samples or []:
        normalized = normalize_experiment_nn_replay_sample(item)
        if normalized is None:
            rejected += 1
            continue
        normalized_samples.append(normalized)
    model_path = Path(model_path or default_chess_nn_model_path())
    model = _load_model(model_path)
    for sample in normalized_samples:
        _train_single_sample(
            model,
            sample["features"],
            float(sample["target"]),
            float(sample.get("weight") or 1.0),
        )
    if normalized_samples:
        _save_model(model_path, model)
    return {
        "ok": True,
        "accepted_samples": len(normalized_samples),
        "rejected_samples": rejected,
        "model_path": str(model_path),
        "sample_count": int(model.get("sample_count") or 0),
    }


def record_experiment_nn_learning(row, *, winner_color: str | None, model_path=None) -> int:
    difficulty = str(row["computer_difficulty"] or "").strip().lower()
    if difficulty != EXPERIMENT_NN_DIFFICULTY or row["mode"] != "computer":
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
    ai_color = chess.WHITE if ai_side == "white" else chess.BLACK
    target = _training_target(ai_side, winner_color)
    model = _load_model(Path(model_path or default_chess_nn_model_path()))
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
            board_before = to_chess_board(board, mover)
            move_uci = move_to_uci(board, from_square, to_square, promotion, mover)
            move = chess.Move.from_uci(move_uci)
            board_after = board_before.copy(stack=False)
            board_after.push(move)
            features = _candidate_features(board_before, move, board_after, ai_side)
            _train_single_sample(model, features, target)
            updated += 1
        try:
            board = validate_move(board, mover, from_square, to_square, promotion)["board"]
        except ValueError:
            break
    if updated:
        _save_model(Path(model_path or default_chess_nn_model_path()), model)
    return updated
