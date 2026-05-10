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


def _invariance_memory_key(side: str, move_uci: str) -> str:
    return f"{side}|{move_uci}"


def _invariance_memory_bias(model: dict, side: str, move_uci: str) -> float:
    try:
        return float((model.get("policy_invariance_memory") or {}).get(_invariance_memory_key(side, move_uci)) or 0.0)
    except Exception:
        return 0.0


def _update_move_memory(model: dict, board: chess.Board, side: str, move: chess.Move, target: float) -> None:
    memory = model.setdefault("move_score_memory", {})
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
            + _invariance_memory_bias(model, side, move.uci()),
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


def choose_experiment_dl_move(board_state, side: str, *, model_path=None, search_profile="balanced", fusion_mode="balanced_fusion", decision_context=None):
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


def explain_experiment_dl_decision(board_state, side: str, *, model_path=None, search_profile="fast", watched_moves=None, fusion_mode="balanced_fusion", decision_context=None) -> dict:
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
        row["final_combined_score"] = row["fused_score"]
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


def _train_from_replay(model: dict, replay_entries: list[dict]) -> dict:
    stats = {
        "positive_updates": 0,
        "contrastive_negative_updates": 0,
        "expected_reinforcement_updates": 0,
        "hard_negative_updates": 0,
        "invariance_positive_updates": 0,
        "invariance_negative_updates": 0,
    }
    if not replay_entries:
        return stats
    batch_size = min(_BATCH_SIZE, len(replay_entries))
    rng = random.Random(int(model.get("sample_count") or 0) + len(replay_entries))
    for _epoch in range(_TRAIN_EPOCHS):
        batch = [rng.choice(replay_entries) for _ in range(batch_size)]
        for sample in batch:
            _train_single_sample(model, sample["features"], float(sample["target"]), float(sample.get("weight") or 1.0))
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
                negative_after = board.copy(stack=False)
                negative_after.push(negative)
                _update_move_memory(model, board, side, negative, _CONTRASTIVE_NEGATIVE_TARGET)
                if sample.get("invariance_group_id"):
                    _update_invariance_memory(model, side, negative, _CONTRASTIVE_NEGATIVE_TARGET)
                    stats["invariance_negative_updates"] += 1
                _train_single_sample(
                    model,
                    _candidate_features(board, negative, negative_after, side),
                    _CONTRASTIVE_NEGATIVE_TARGET,
                    0.65,
                )
                stats["contrastive_negative_updates"] += 1
                if negative in hard_negatives:
                    stats["hard_negative_updates"] += 1
            for _reinforce in range(8):
                _update_move_memory(model, board, side, expected_move, 1.0)
                if sample.get("invariance_group_id"):
                    _update_invariance_memory(model, side, expected_move, 1.0)
                    stats["invariance_positive_updates"] += 1
                _train_single_sample(model, sample["features"], 1.0, 0.8)
                stats["expected_reinforcement_updates"] += 1
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
        )
        return derived
    try:
        target = float(sample.get("target"))
        weight = float(sample.get("weight") or 1.0)
    except Exception:
        return None
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
        "training_objective": "contrastive_policy_ranking",
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
