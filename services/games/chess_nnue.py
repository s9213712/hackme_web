"""NNUE-like evaluator for the ``experiment 5:NNUE`` chess difficulty.

This is a lightweight, JSON-serializable NNUE-inspired route: sparse board
features feed an efficiently reusable evaluator, then the existing alpha-beta
search stack chooses the move. It is intentionally not a Stockfish-compatible
NNUE implementation; it gives us a clean exp5 surface for the NNUE + PVS line
without mixing that design into the exp3/exp4 learning gates.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import chess

from services.games.chess import to_chess_board
from services.games.chess_search import ZobristHasher, opening_sanity_filter, search_best_move
from services.games.chess_model_registry import bundled_seed_model_path, runtime_model_path


EXPERIMENT_NNUE_DIFFICULTY = "experiment 5:nnue"
DEFAULT_CHESS_NNUE_MODEL_NAME = "chess_experiment_5_nnue.json"
DEFAULT_CHESS_NNUE_REPLAY_NAME = "chess_experiment_5_nnue_replay.jsonl"
_NNUE_VERSION = 1
_LEARNING_RATE = 18.0
_MAX_ABS_WEIGHT = 350.0
_SEARCH_PROFILES = {
    "fast": {"depth": 1, "quiescence_depth": 1, "time_budget_ms": 140},
    "balanced": {"depth": 2, "quiescence_depth": 2, "time_budget_ms": 320},
    "strong": {"depth": 3, "quiescence_depth": 4, "time_budget_ms": 1100},
}
_PIECE_VALUES = {
    chess.PAWN: 100,
    chess.KNIGHT: 320,
    chess.BISHOP: 335,
    chess.ROOK: 500,
    chess.QUEEN: 900,
    chess.KING: 20000,
}
_CENTER = {chess.D4, chess.E4, chess.D5, chess.E5}
_EXTENDED_CENTER = {chess.C3, chess.D3, chess.E3, chess.F3, chess.C4, chess.F4, chess.C5, chess.F5, chess.C6, chess.D6, chess.E6, chess.F6}


def default_chess_nnue_model_path() -> Path:
    return runtime_model_path(DEFAULT_CHESS_NNUE_MODEL_NAME, env_var="HTML_LEARNING_CHESS_ENGINE_NNUE_MODEL_PATH")


def default_chess_nnue_replay_path() -> Path:
    return runtime_model_path(DEFAULT_CHESS_NNUE_REPLAY_NAME, env_var="HTML_LEARNING_CHESS_ENGINE_NNUE_REPLAY_PATH")


def bundled_chess_nnue_model_path() -> Path:
    return bundled_seed_model_path(DEFAULT_CHESS_NNUE_MODEL_NAME)


def _now() -> str:
    return datetime.now().isoformat()


def experiment_nnue_model_template() -> dict:
    return {
        "version": _NNUE_VERSION,
        "architecture": "nnue-like-sparse-accumulator-v1",
        "feature_weights": {},
        "piece_square_weights": {},
        "tempo": 12,
        "mobility_weight": 3,
        "king_safety_weight": 18,
        "training_objective": "position_move_evaluator_delta",
        "sample_count": 0,
        "updated_at": _now(),
    }


def _clip(value: float, low: float, high: float) -> float:
    return max(low, min(high, float(value)))


def normalize_experiment_nnue_model_payload(model: dict) -> dict | None:
    if not isinstance(model, dict):
        return None
    if int(model.get("version") or 0) != _NNUE_VERSION:
        return None
    feature_weights = model.get("feature_weights") if isinstance(model.get("feature_weights"), dict) else {}
    piece_square_weights = model.get("piece_square_weights") if isinstance(model.get("piece_square_weights"), dict) else {}
    try:
        tempo = int(model.get("tempo", 12))
        mobility_weight = int(model.get("mobility_weight", 3))
        king_safety_weight = int(model.get("king_safety_weight", 18))
    except Exception:
        return None
    return {
        "version": _NNUE_VERSION,
        "architecture": "nnue-like-sparse-accumulator-v1",
        "feature_weights": {str(key): float(value) for key, value in feature_weights.items()},
        "piece_square_weights": {str(key): float(value) for key, value in piece_square_weights.items()},
        "tempo": tempo,
        "mobility_weight": mobility_weight,
        "king_safety_weight": king_safety_weight,
        "training_objective": str(model.get("training_objective") or "position_move_evaluator_delta"),
        "sample_count": max(0, int(model.get("sample_count") or 0)),
        "updated_at": str(model.get("updated_at") or _now()),
    }


def _load_model(model_path: Path) -> dict:
    path = Path(model_path)
    if not path.exists():
        return experiment_nnue_model_template()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return experiment_nnue_model_template()
    return normalize_experiment_nnue_model_payload(payload) or experiment_nnue_model_template()


def _save_model(model_path: Path, model: dict) -> None:
    normalized = normalize_experiment_nnue_model_payload(model) or experiment_nnue_model_template()
    path = Path(model_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(json.dumps(normalized, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    tmp_path.replace(path)


def _resolve_search_profile(profile: str | None) -> dict:
    normalized = str(profile or "balanced").strip().lower()
    return dict(_SEARCH_PROFILES.get(normalized) or _SEARCH_PROFILES["balanced"])


def _piece_feature_key(square: int, piece: chess.Piece) -> str:
    return f"{'w' if piece.color == chess.WHITE else 'b'}:{piece.symbol().lower()}:{chess.square_name(square)}"


def _material_score(board: chess.Board) -> int:
    score = 0
    for piece in board.piece_map().values():
        value = _PIECE_VALUES[piece.piece_type]
        score += value if piece.color == chess.WHITE else -value
    return score


def _sparse_feature_score(board: chess.Board, model: dict) -> int:
    feature_weights = model.get("feature_weights") or {}
    piece_square_weights = model.get("piece_square_weights") or {}
    score = 0.0
    for square, piece in board.piece_map().items():
        sign = 1.0 if piece.color == chess.WHITE else -1.0
        score += sign * float(piece_square_weights.get(_piece_feature_key(square, piece), 0.0))
        if square in _CENTER and piece.piece_type in {chess.PAWN, chess.KNIGHT, chess.BISHOP}:
            score += sign * float(feature_weights.get("center_control", 18.0))
        elif square in _EXTENDED_CENTER and piece.piece_type in {chess.PAWN, chess.KNIGHT, chess.BISHOP}:
            score += sign * float(feature_weights.get("extended_center_control", 8.0))
    return int(round(score))


def _mobility_score(board: chess.Board, model: dict) -> int:
    current_turn = board.turn
    current = board.legal_moves.count()
    board.turn = not current_turn
    try:
        other = board.legal_moves.count()
    finally:
        board.turn = current_turn
    weight = int(model.get("mobility_weight") or 0)
    white_score = (current - other) * weight if current_turn == chess.WHITE else (other - current) * weight
    return int(white_score)


def _king_safety_score(board: chess.Board, model: dict) -> int:
    weight = int(model.get("king_safety_weight") or 0)
    score = 0
    if board.king(chess.WHITE) in {chess.G1, chess.C1}:
        score += weight
    if board.king(chess.BLACK) in {chess.G8, chess.C8}:
        score -= weight
    if board.is_check():
        score += -weight if board.turn == chess.WHITE else weight
    return score


def _nnue_eval(board: chess.Board, model: dict, eval_cache: dict[int, int], hasher: ZobristHasher) -> int:
    board_hash = hasher.hash_board(board)
    cached = eval_cache.get(board_hash)
    if cached is not None:
        return cached
    score = _material_score(board)
    score += _sparse_feature_score(board, model)
    score += _mobility_score(board, model)
    score += _king_safety_score(board, model)
    score += int(model.get("tempo") or 0) if board.turn == chess.WHITE else -int(model.get("tempo") or 0)
    eval_cache[board_hash] = score
    return score


def _move_order_score(board: chess.Board, move: chess.Move) -> int:
    score = 0
    if board.is_capture(move):
        captured = board.piece_at(move.to_square)
        attacker = board.piece_at(move.from_square)
        if captured is not None:
            score += _PIECE_VALUES.get(captured.piece_type, 0) * 10
        if attacker is not None:
            score -= _PIECE_VALUES.get(attacker.piece_type, 0)
    if move.promotion:
        score += 8_000
    if board.gives_check(move):
        score += 1_500
    piece = board.piece_at(move.from_square)
    if piece and piece.piece_type in {chess.KNIGHT, chess.BISHOP} and chess.square_rank(move.from_square) in {0, 7}:
        score += 500
    if move.to_square in _CENTER:
        score += 240
    return score


def _move_dict(board: chess.Board, move: chess.Move) -> dict:
    piece = board.piece_at(move.from_square)
    captured = board.piece_at(move.to_square)
    if board.is_en_passant(move):
        capture_square = chess.square(chess.square_file(move.to_square), chess.square_rank(move.from_square))
        captured = board.piece_at(capture_square)
    return {
        "from": chess.square_name(move.from_square),
        "to": chess.square_name(move.to_square),
        "piece": piece.symbol() if piece else "",
        "captured": captured.symbol() if captured else None,
        "promotion": chess.piece_symbol(move.promotion) if move.promotion else None,
        "castle": bool(board.is_castling(move)),
        "en_passant": bool(board.is_en_passant(move)),
    }


def _score_move_for_side(board: chess.Board, move: chess.Move, side: str, model: dict, eval_cache: dict[int, int], hasher: ZobristHasher) -> float:
    after = board.copy(stack=False)
    after.push(move)
    side_sign = 1.0 if str(side or "white").lower() == "white" else -1.0
    score = side_sign * float(_nnue_eval(after, model, eval_cache, hasher))
    score += float(_move_order_score(board, move))
    return score


def rank_experiment_nnue_policy_moves(board_state, side: str, *, model_path=None, search_profile="fast") -> list[dict]:
    board = to_chess_board(board_state, side)
    ai_color = chess.WHITE if side == "white" else chess.BLACK
    if board.turn != ai_color:
        board.turn = ai_color
    if board.is_game_over():
        return []
    model = _load_model(Path(model_path or default_chess_nnue_model_path()))
    hasher = ZobristHasher(seed=20260530)
    eval_cache: dict[int, int] = {}
    rows = []
    for move in sorted(board.legal_moves, key=lambda item: item.uci()):
        score = _score_move_for_side(board, move, side, model, eval_cache, hasher)
        rows.append({"move": move.uci(), "raw_policy_score": round(float(score), 8)})
    if not rows:
        return []
    max_score = max(float(row["raw_policy_score"]) for row in rows)
    denom = sum(pow(2.718281828459045, (float(row["raw_policy_score"]) - max_score) / 400.0) for row in rows)
    ranked = sorted(rows, key=lambda row: (-float(row["raw_policy_score"]), str(row["move"])))
    rank = {str(row["move"]): index for index, row in enumerate(ranked, start=1)}
    for row in rows:
        row["policy_probability"] = (
            round(pow(2.718281828459045, (float(row["raw_policy_score"]) - max_score) / 400.0) / denom, 8)
            if denom
            else 0.0
        )
        row["raw_policy_rank"] = rank[str(row["move"])]
        row["move_order_score"] = int(round(float(row["raw_policy_score"])))
        row["move_order_rank"] = row["raw_policy_rank"]
        row["legal_move_bonus_penalty"] = 0
    return sorted(rows, key=lambda row: (int(row["raw_policy_rank"]), str(row["move"])))


def explain_experiment_nnue_decision(
    board_state,
    side: str,
    *,
    model_path=None,
    search_profile="fast",
    watched_moves: list[str] | None = None,
    **_kwargs,
) -> dict:
    rows = rank_experiment_nnue_policy_moves(board_state, side, model_path=model_path, search_profile=search_profile)
    move = choose_experiment_nnue_move(board_state, side, model_path=model_path, search_profile=search_profile)
    chosen = f"{move['from']}{move['to']}{move.get('promotion') or ''}".lower() if move else ""
    watched = {str(item or "").strip().lower() for item in (watched_moves or []) if str(item or "").strip()}
    return {
        "supported": True,
        "engine": EXPERIMENT_NNUE_DIFFICULTY,
        "architecture": "nnue-like-sparse-accumulator-v1",
        "search_profile": str(search_profile or "fast"),
        "chosen_move": chosen,
        "chosen_reason": "alpha_beta_with_nnue_like_sparse_eval",
        "chosen_breakdown": next((row for row in rows if str(row.get("move") or "") == chosen), {}),
        "top_final_moves": rows[:5],
        "watched_moves": [row for row in rows if str(row.get("move") or "") in watched],
    }


def choose_experiment_nnue_move(board_state, side: str, *, model_path=None, search_profile="balanced"):
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
        return _move_dict(board, sorted(forced_mates, key=lambda item: item.uci())[0])

    model = _load_model(Path(model_path or default_chess_nnue_model_path()))
    profile = _resolve_search_profile(search_profile)
    hasher = ZobristHasher(seed=20260530)
    eval_cache: dict[int, int] = {}
    result = search_best_move(
        board,
        max_depth=profile["depth"],
        evaluate=lambda current_board: _nnue_eval(current_board, model, eval_cache, hasher),
        move_order_fn=lambda current_board, move, _ply: _move_order_score(current_board, move),
        hasher=hasher,
        quiescence_depth=profile["quiescence_depth"],
        time_budget_ms=profile.get("time_budget_ms"),
    )
    best_move = opening_sanity_filter(board, result.best_move, score_move=lambda move: _move_order_score(board, move))
    return _move_dict(board, best_move) if best_move is not None else None


def build_experiment_nnue_sample_from_position(
    *,
    fen: str,
    move_uci: str,
    side: str | None = None,
    target: float = 1.0,
    weight: float = 1.0,
    source: str = "external",
    hard_negatives: list[str] | None = None,
    search_profile: str = "fast",
) -> dict | None:
    fen_text = str(fen or "").strip()
    move_text = str(move_uci or "").strip().lower()
    if not fen_text or len(move_text) < 4:
        return None
    try:
        board_before = chess.Board(fen_text)
    except Exception:
        return None
    mover = str(side or ("white" if board_before.turn == chess.WHITE else "black")).strip().lower()
    if mover not in {"white", "black"}:
        return None
    board_before.turn = chess.WHITE if mover == "white" else chess.BLACK
    try:
        move = chess.Move.from_uci(move_text)
    except Exception:
        return None
    if move not in board_before.legal_moves:
        return None
    return {
        "fen": board_before.fen(),
        "move_uci": move.uci(),
        "side": mover,
        "target": _clip(float(target), -1.0, 1.0),
        "weight": _clip(float(weight), 0.1, 8.0),
        "source": str(source or "external"),
        "hard_negatives": [str(item).strip().lower() for item in (hard_negatives or []) if str(item).strip()],
        "search_profile": str(search_profile or "fast"),
        "sample_format": "exp5_nnue_position_move_v1",
    }


def normalize_experiment_nnue_replay_sample(sample: dict) -> dict | None:
    if not isinstance(sample, dict):
        return None
    try:
        target = float(sample.get("target", 1.0) or 0.0)
        weight = float(sample.get("weight", 1.0) or 1.0)
    except Exception:
        return None
    return build_experiment_nnue_sample_from_position(
        fen=str(sample.get("fen") or sample.get("board_fen") or "").strip(),
        move_uci=str(sample.get("move_uci") or sample.get("uci") or sample.get("move") or "").strip(),
        side=sample.get("side"),
        target=target,
        weight=weight,
        source=str(sample.get("source") or "external"),
        hard_negatives=list(sample.get("hard_negatives") or []),
        search_profile=str(sample.get("search_profile") or "fast"),
    )


def _load_replay_entries(replay_path: Path) -> list[dict]:
    path = Path(replay_path)
    if not path.exists():
        return []
    rows: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except Exception:
            continue
        normalized = normalize_experiment_nnue_replay_sample(payload)
        if normalized is not None:
            rows.append(normalized)
    return rows


def _write_replay_entries(replay_path: Path, entries: list[dict]) -> int:
    path = Path(replay_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    body = "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in entries)
    path.write_text(body, encoding="utf-8")
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


def _adjust_weight(mapping: dict, key: str, delta: float) -> None:
    mapping[key] = round(_clip(float(mapping.get(key) or 0.0) + float(delta), -_MAX_ABS_WEIGHT, _MAX_ABS_WEIGHT), 6)


def _train_position_move(model: dict, sample: dict, *, target_override: float | None = None, weight_override: float | None = None) -> bool:
    try:
        board = chess.Board(str(sample.get("fen") or ""))
        side = str(sample.get("side") or "white").strip().lower()
        board.turn = chess.WHITE if side == "white" else chess.BLACK
        move = chess.Move.from_uci(str(sample.get("move_uci") or ""))
    except Exception:
        return False
    if side not in {"white", "black"} or move not in board.legal_moves:
        return False
    target = float(sample.get("target") or 0.0) if target_override is None else float(target_override)
    weight = float(sample.get("weight") or 1.0) if weight_override is None else float(weight_override)
    side_sign = 1.0 if side == "white" else -1.0
    delta = side_sign * _clip(target, -1.0, 1.0) * _clip(weight, 0.1, 8.0) * _LEARNING_RATE
    after = board.copy(stack=False)
    after.push(move)
    moved_piece = after.piece_at(move.to_square)
    if moved_piece is not None:
        _adjust_weight(model.setdefault("piece_square_weights", {}), _piece_feature_key(move.to_square, moved_piece), delta)
        if move.to_square in _CENTER and moved_piece.piece_type in {chess.PAWN, chess.KNIGHT, chess.BISHOP}:
            _adjust_weight(model.setdefault("feature_weights", {}), "center_control", delta * 0.12)
        elif move.to_square in _EXTENDED_CENTER and moved_piece.piece_type in {chess.PAWN, chess.KNIGHT, chess.BISHOP}:
            _adjust_weight(model.setdefault("feature_weights", {}), "extended_center_control", delta * 0.08)
    if board.is_castling(move):
        model["king_safety_weight"] = int(round(_clip(int(model.get("king_safety_weight") or 0) + abs(delta) * 0.04, -80, 120)))
    if board.fullmove_number <= 8:
        model["tempo"] = int(round(_clip(int(model.get("tempo") or 0) + side_sign * _clip(target, -1.0, 1.0) * 0.2, -40, 40)))
    model["sample_count"] = int(model.get("sample_count") or 0) + 1
    model["updated_at"] = _now()
    return True


def _policy_probe_for_sample(model_path: Path, sample: dict) -> dict | None:
    fen = str(sample.get("fen") or "").strip()
    side = str(sample.get("side") or "").strip().lower()
    expected = str(sample.get("move_uci") or "").strip().lower()
    if not fen or side not in {"white", "black"} or not expected:
        return None
    rows = rank_experiment_nnue_policy_moves({"__fen__": fen}, side, model_path=model_path, search_profile=str(sample.get("search_profile") or "fast"))
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


def train_experiment_nnue_from_replay_samples(
    samples: list[dict],
    *,
    model_path=None,
    replay_path=None,
    replace_replay: bool = False,
) -> dict:
    normalized_samples = []
    rejected = 0
    for item in samples or []:
        normalized = normalize_experiment_nnue_replay_sample(item)
        if normalized is None:
            rejected += 1
            continue
        normalized_samples.append(normalized)
    model_path = Path(model_path or default_chess_nnue_model_path())
    replay_path = Path(replay_path or default_chess_nnue_replay_path())
    if not model_path.exists():
        _save_model(model_path, experiment_nnue_model_template())
    existing = [] if replace_replay else _load_replay_entries(replay_path)
    replay_entries = existing + normalized_samples
    replay_size = _write_replay_entries(replay_path, replay_entries)
    probe_sample = next((sample for sample in normalized_samples if sample.get("fen") and sample.get("move_uci") and sample.get("side")), None)
    policy_probe_before = _policy_probe_for_sample(model_path, probe_sample or {}) if probe_sample else None
    model = _load_model(model_path)
    positive_updates = 0
    hard_negative_updates = 0
    for sample in replay_entries:
        repeat = max(1, int(round(float(sample.get("weight") or 1.0))))
        for _index in range(repeat):
            if _train_position_move(model, sample):
                positive_updates += 1
        try:
            board = chess.Board(str(sample.get("fen") or ""))
            side = str(sample.get("side") or "white").strip().lower()
            board.turn = chess.WHITE if side == "white" else chess.BLACK
            expected = chess.Move.from_uci(str(sample.get("move_uci") or ""))
        except Exception:
            continue
        if expected not in board.legal_moves:
            continue
        for negative in _legal_hard_negative_moves(board, expected, list(sample.get("hard_negatives") or [])):
            negative_sample = dict(sample)
            negative_sample["move_uci"] = negative.uci()
            if _train_position_move(
                model,
                negative_sample,
                target_override=-abs(float(sample.get("target") or 1.0)),
                weight_override=max(1.0, float(sample.get("weight") or 1.0)),
            ):
                hard_negative_updates += 1
    if replay_entries:
        _save_model(model_path, model)
    policy_probe_after = _policy_probe_for_sample(model_path, probe_sample or {}) if probe_sample else None
    policy_probe = {
        "supported": bool(policy_probe_before and policy_probe_after),
        "before": policy_probe_before or {},
        "after": policy_probe_after or {},
        "training_applied": bool(replay_entries),
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
        "engine": EXPERIMENT_NNUE_DIFFICULTY,
        "retrain_supported": True,
        "training_applied": bool(replay_entries),
        "reason": "basic exp5 NNUE-like replay trainer; strength validation and promotion gates are pending exp5-specific design",
        "accepted_samples": len(normalized_samples),
        "rejected_samples": rejected,
        "replay_size": replay_size,
        "model_path": str(model_path),
        "replay_path": str(replay_path),
        "sample_count": int(model.get("sample_count") or 0),
        "sample_format": "exp5_nnue_position_move_v1",
        "training_objective": "position_move_evaluator_delta",
        "positive_updates": positive_updates,
        "hard_negative_updates": hard_negative_updates,
        "policy_probe": policy_probe,
    }
