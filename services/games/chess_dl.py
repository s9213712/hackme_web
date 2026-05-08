"""Deep-learning-backed helpers for the ``experiment 3:DL`` chess difficulty.

This engine extends the lightweight ``experiment 2:nn`` approach with:

- a deeper MLP (`49 -> 64 -> 32 -> 1`)
- a replay buffer persisted under ``runtime/models/``
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
from services.games.chess_search import ZobristHasher, search_best_move
from services.server.runtime import default_runtime_root_path


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
_MODEL_EVAL_MOVE_CAP = 6
_MODEL_SCORE_SCALE = 140.0
_PIECE_VALUES = {
    chess.PAWN: 100,
    chess.KNIGHT: 320,
    chess.BISHOP: 335,
    chess.ROOK: 500,
    chess.QUEEN: 900,
    chess.KING: 20000,
}


def default_chess_dl_model_path() -> Path:
    runtime_dir = os.environ.get("HACKME_RUNTIME_DIR", "").strip()
    if not runtime_dir:
        runtime_dir = str(default_runtime_root_path())
    override = os.environ.get("HTML_LEARNING_CHESS_ENGINE_DL_MODEL_PATH", "").strip()
    return Path(override or os.path.join(runtime_dir, "models", DEFAULT_CHESS_DL_MODEL_NAME))


def default_chess_dl_replay_path() -> Path:
    runtime_dir = os.environ.get("HACKME_RUNTIME_DIR", "").strip()
    if not runtime_dir:
        runtime_dir = str(default_runtime_root_path())
    override = os.environ.get("HTML_LEARNING_CHESS_ENGINE_DL_REPLAY_PATH", "").strip()
    return Path(override or os.path.join(runtime_dir, "models", DEFAULT_CHESS_DL_REPLAY_NAME))


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


def choose_experiment_dl_move(board_state, side: str, *, model_path=None):
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

    def move_order_fn(current_board: chess.Board, move: chess.Move, _ply: int) -> int:
        current_side = "white" if current_board.turn == chess.WHITE else "black"
        score = _score_candidate_move(current_board, move, current_side, model)
        return int(score * 1000.0)

    search = search_best_move(
        board,
        max_depth=_SEARCH_DEPTH,
        evaluate=lambda current_board: _dl_static_eval(current_board, model, eval_cache, hasher),
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
            "target": _clip(target, -1.0, 1.0),
            "weight": _clip(weight, 0.1, 2.0),
            "source": str(item.get("source") or "game"),
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


def _train_from_replay(model: dict, replay_entries: list[dict]) -> None:
    if not replay_entries:
        return
    batch_size = min(_BATCH_SIZE, len(replay_entries))
    rng = random.Random(int(model.get("sample_count") or 0) + len(replay_entries))
    for _epoch in range(_TRAIN_EPOCHS):
        batch = [rng.choice(replay_entries) for _ in range(batch_size)]
        for sample in batch:
            _train_single_sample(model, sample["features"], float(sample["target"]), float(sample.get("weight") or 1.0))


def build_experiment_dl_sample_from_position(*, fen: str, move_uci: str, side: str | None = None, target: float = 1.0, weight: float = 1.0, source: str = "external") -> dict | None:
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
    return {
        "features": features,
        "target": _clip(float(target), -1.0, 1.0),
        "weight": _clip(float(weight), 0.1, 3.0),
        "source": str(source or "external"),
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
        )
        return derived
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
    if replace_replay:
        replay_size = _replace_replay_entries(replay_path, normalized_samples)
    else:
        replay_size = _append_replay_entries(replay_path, normalized_samples)
    model = _load_model(model_path)
    replay_entries = _load_replay_entries(replay_path)
    _train_from_replay(model, replay_entries)
    model["replay_size"] = replay_size
    model["updated_at"] = _now()
    _save_model(model_path, model)
    return {
        "ok": True,
        "accepted_samples": len(normalized_samples),
        "rejected_samples": rejected,
        "replay_size": replay_size,
        "model_path": str(model_path),
        "replay_path": str(replay_path),
        "sample_count": int(model.get("sample_count") or 0),
    }


def distill_experiment_dl_from_move_history(move_history: list[dict], *, teacher_side: str, model_path=None, replay_path=None, source: str = "teacher_distillation") -> int:
    if teacher_side not in {"white", "black"}:
        return 0
    if not isinstance(move_history, list) or not move_history:
        return 0
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
