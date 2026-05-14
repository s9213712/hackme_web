"""NNUE-like evaluator for the ``experiment 5:NNUE`` chess difficulty.

This is a lightweight, JSON-serializable NNUE-inspired route: sparse board
features feed an efficiently reusable evaluator, then the existing alpha-beta
search stack chooses the move. It is intentionally not a Stockfish-compatible
NNUE implementation; it gives us a clean exp5 surface for the NNUE + PVS line
without mixing that design into the exp3/exp4 learning gates.
"""

from __future__ import annotations

import json
import hashlib
import os
from datetime import datetime
from pathlib import Path

import chess

from services.games.chess import START_FEN, replay_board_from_history, to_chess_board
from services.games.chess_search import ZobristHasher, opening_sanity_filter, search_best_move
from services.games.chess_model_registry import bundled_seed_model_path, runtime_model_path
from services.games.chess_tactical_safety import choose_tactically_safe_move, tactical_safety_report


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
    # exp5_05a deterministic profiles: no time budget so PVS results are
    # bit-for-bit reproducible across runs. Same depth/quiescence as the
    # equivalent timed profile.
    "fixed_depth_fast": {"depth": 1, "quiescence_depth": 1, "time_budget_ms": None},
    "fixed_depth_balanced": {"depth": 2, "quiescence_depth": 2, "time_budget_ms": None},
    "fixed_depth_strong": {"depth": 3, "quiescence_depth": 4, "time_budget_ms": None},
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
_FLANK_FILES = {0, 7}
_NEAR_FLANK_FILES = {1, 6}
_OPENING_DEVELOPMENT_FULLMOVE_LIMIT = 10
_OPENING_KING_WALK_FULLMOVE_LIMIT = 12
_MOVE_HISTORY_KEY = "__move_history__"
_MATE_IN_TWO_MAX_PIECES = 12
_MATE_IN_TWO_MAX_LEGAL_MOVES = 45
_MATE_IN_TWO_MAX_REPLIES = 45
_CONVERSION_MARGIN_CP = 500
_CONVERSION_FULLMOVE = 20
_CONVERSION_TOTAL_MATERIAL_CP = 3600
_KING_ACTIVITY_WEIGHT = 42
_PASSED_PAWN_ADVANCE_WEIGHT = 26
_SEE_MAX_DEPTH = 8
_REPETITION_PROGRESS_MARGIN_CP = 300
_REPETITION_PROGRESS_SAFE_DROP_CP = 180
_REPETITION_PROGRESS_SCORE_DROP_CP = 1800.0
_ADAPTER_MODEL_PATH_ENV = "HTML_LEARNING_CHESS_ENGINE_NNUE_ADAPTER_MODEL_PATH"
_ADAPTER_ROWS_PATH_ENV = "HTML_LEARNING_CHESS_ENGINE_NNUE_ADAPTER_ROWS_PATH"
_ADAPTER_MODE_ENV = "HTML_LEARNING_CHESS_ENGINE_NNUE_ADAPTER_MODE"
_ADAPTER_ALLOW_EXACT_ENV = "HTML_LEARNING_CHESS_ENGINE_NNUE_ADAPTER_ALLOW_EXACT"
_ADAPTER_ALLOW_GENERAL_ENV = "HTML_LEARNING_CHESS_ENGINE_NNUE_ADAPTER_ALLOW_GENERAL"
_ADAPTER_REENTRY_ENV = "_HTML_LEARNING_CHESS_ENGINE_NNUE_ADAPTER_REENTRY"
_ADAPTER_MAX_MAIN_RANK_EXACT = 8
_ADAPTER_MAX_MAIN_SCORE_DROP_EXACT_CP = 220.0
_ADAPTER_MAX_MAIN_RANK_GENERAL = 2
_ADAPTER_MAX_MAIN_SCORE_DROP_GENERAL_CP = 80.0
_ADAPTER_MAX_MATERIAL_FLOOR_DROP_CP = 180
_ADAPTER_MEMORY_CACHE: dict[str, dict] = {}

# exp3-example2 lesson item 10: broader "post-castle haven" set, not just g1/c1.
# Example2 showed that exp3 never castled across 5/5 games and walked the king
# out by ply 8-21 in every one. Reward any king that has reached a corner-side
# squares typical of a castled-then-shuffled king; penalise a king that's
# still on the starting square after the opening.
_WHITE_KING_SAFE_SQUARES = {chess.G1, chess.H1, chess.G2, chess.H2, chess.F1, chess.F2,
                            chess.C1, chess.B1, chess.A1, chess.B2, chess.C2, chess.A2}
_BLACK_KING_SAFE_SQUARES = {chess.G8, chess.H8, chess.G7, chess.H7, chess.F8, chess.F7,
                            chess.C8, chess.B8, chess.A8, chess.B7, chess.C7, chess.A7}
# How late into the game an "uncastled, still on e1/e8" king starts being
# penalised. fullmove_number reaches 13 by ply 25 — clearly past opening.
_EARLY_KING_PENALTY_AFTER_FULLMOVE = 12
_REPLAY_PRIOR_MAX_FULLMOVE = 12
_REPLAY_PRIOR_LINES = (
    ("rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1", "white", "d2d4"),
    ("rnbqkbnr/pppppppp/8/8/3P4/8/PPP1PPPP/RNBQKBNR b KQkq - 0 1", "black", "g8f6"),
    ("rnbqkb1r/pppppppp/5n2/8/3P4/8/PPP1PPPP/RNBQKBNR w KQkq - 1 2", "white", "c2c4"),
    ("rnbqkb1r/pppppppp/5n2/8/2PP4/8/PP2PPPP/RNBQKBNR b KQkq - 0 2", "black", "c7c5"),
    ("rnbqkb1r/pp1ppppp/5n2/2p5/2PP4/8/PP2PPPP/RNBQKBNR w KQkq - 0 3", "white", "d4d5"),
    ("rnbqkb1r/pp1ppppp/5n2/2pP4/2P5/8/PP2PPPP/RNBQKBNR b KQkq - 0 3", "black", "e7e6"),
    ("rnbqkb1r/pp1p1ppp/4pn2/2pP4/2P5/8/PP2PPPP/RNBQKBNR w KQkq - 0 4", "white", "b1c3"),
    ("rnbqkb1r/pp1p1ppp/4pn2/2pP4/2P5/2N5/PP2PPPP/R1BQKBNR b KQkq - 1 4", "black", "e6d5"),
    ("rnbqkb1r/pp1p1ppp/5n2/2pp4/2P5/2N5/PP2PPPP/R1BQKBNR w KQkq - 0 5", "white", "c4d5"),
    ("rnbqkb1r/pp1p1ppp/5n2/2pP4/8/2N5/PP2PPPP/R1BQKBNR b KQkq - 0 5", "black", "d7d6"),
    ("rnbqkb1r/pp3ppp/3p1n2/2pP4/8/2N5/PP2PPPP/R1BQKBNR w KQkq - 0 6", "white", "e2e4"),
    ("rnbqkb1r/pp3ppp/3p1n2/2pP4/4P3/2N5/PP3PPP/R1BQKBNR b KQkq - 0 6", "black", "g7g6"),
    ("rnbqkb1r/pp3p1p/3p1np1/2pP4/4P3/2N5/PP3PPP/R1BQKBNR w KQkq - 0 7", "white", "f2f4"),
    ("rnbqkb1r/pp3p1p/3p1np1/2pP4/4PP2/2N5/PP4PP/R1BQKBNR b KQkq - 0 7", "black", "f8g7"),
    ("rnbqk2r/pp3pbp/3p1np1/2pP4/4PP2/2N5/PP4PP/R1BQKBNR w KQkq - 1 8", "white", "f1b5"),
    ("rnbqk2r/pp3pbp/3p1np1/1BpP4/4PP2/2N5/PP4PP/R1BQK1NR b KQkq - 2 8", "black", "f6d7"),
    ("rnbqk2r/pp1n1pbp/3p2p1/1BpP4/4PP2/2N5/PP4PP/R1BQK1NR w KQkq - 3 9", "white", "g1f3"),
    ("rnbqk2r/pp1n1pbp/3p2p1/1BpP4/4PP2/2N2N2/PP4PP/R1BQK2R b KQkq - 4 9", "black", "a7a6"),
    ("rnbqk2r/1p1n1pbp/p2p2p1/1BpP4/4PP2/2N2N2/PP4PP/R1BQK2R w KQkq - 0 10", "white", "b5d3"),
    ("rnbqk2r/1p1n1pbp/p2p2p1/2pP4/4PP2/2NB1N2/PP4PP/R1BQK2R b KQkq - 1 10", "black", "b7b5"),
    ("rnbqk2r/3n1pbp/p2p2p1/1ppP4/4PP2/2NB1N2/PP4PP/R1BQK2R w KQkq - 0 11", "white", "e1g1"),
    ("rnbqk2r/3n1pbp/p2p2p1/1ppP4/4PP2/2NB1N2/PP4PP/R1BQ1RK1 b kq - 1 11", "black", "e8g8"),
    ("rnbq1rk1/3n1pbp/p2p2p1/1ppP4/4PP2/2NB1N2/PP4PP/R1BQ1RK1 w - - 2 12", "white", "a2a3"),
    ("rnbq1rk1/3n1pbp/p2p2p1/1ppP4/4PP2/P1NB1N2/1P4PP/R1BQ1RK1 b - - 0 12", "black", "b5b4"),
)
_REPLAY_PRIOR_BY_POSITION = {
    (fen, side): move
    for fen, side, move in _REPLAY_PRIOR_LINES
}


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
        "opening_overlay": {},
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
        "opening_overlay": _normalize_opening_overlay(model.get("opening_overlay")),
        "tempo": tempo,
        "mobility_weight": mobility_weight,
        "king_safety_weight": king_safety_weight,
        "training_objective": str(model.get("training_objective") or "position_move_evaluator_delta"),
        "sample_count": max(0, int(model.get("sample_count") or 0)),
        "updated_at": str(model.get("updated_at") or _now()),
    }


def _normalize_opening_overlay(raw) -> dict:
    if not isinstance(raw, dict):
        return {}
    positions_raw = raw.get("positions")
    if not isinstance(positions_raw, dict):
        return {}
    positions: dict[str, dict] = {}
    for key, payload in positions_raw.items():
        key_text = str(key or "").strip()
        if not key_text or not isinstance(payload, dict):
            continue
        moves_raw = payload.get("moves") or payload.get("expected_uci_any") or []
        moves: list[dict] = []
        for index, item in enumerate(moves_raw):
            if isinstance(item, dict):
                uci = str(item.get("uci") or item.get("move") or "").strip().lower()
                weight = float(item.get("weight") or max(1, 100 - index))
            else:
                uci = str(item or "").strip().lower()
                weight = float(max(1, 100 - index))
            if len(uci) < 4:
                continue
            moves.append({"uci": uci, "weight": round(_clip(weight, 0.0, 10000.0), 6)})
        if not moves:
            continue
        positions[key_text] = {
            "id": str(payload.get("id") or key_text),
            "fen": str(payload.get("fen") or ""),
            "side": str(payload.get("side") or "").strip().lower(),
            "source": str(payload.get("source") or "opening_overlay"),
            "label_quality": str(payload.get("label_quality") or ""),
            "moves": moves,
        }
    if not positions:
        return {}
    try:
        max_fullmove = max(1, int(raw.get("max_fullmove") or 12))
    except Exception:
        max_fullmove = 12
    return {
        "enabled": bool(raw.get("enabled", True)),
        "version": str(raw.get("version") or "exp5_opening_overlay_v1"),
        "mode": str(raw.get("mode") or "exact_position_book_prior"),
        "max_fullmove": max_fullmove,
        "positions": positions,
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


def _non_king_material_total(board: chess.Board) -> int:
    total = 0
    for piece in board.piece_map().values():
        if piece.piece_type != chess.KING:
            total += _PIECE_VALUES[piece.piece_type]
    return total


def _is_conversion_phase(board: chess.Board, color: chess.Color) -> bool:
    margin = _material_margin_for_color(board, color)
    if margin < _CONVERSION_MARGIN_CP:
        return False
    return (
        board.fullmove_number >= _CONVERSION_FULLMOVE
        or _non_king_material_total(board) <= _CONVERSION_TOTAL_MATERIAL_CP
    )


def _king_center_activity(square: int | None) -> int:
    if square is None:
        return 0
    file_distance = abs(chess.square_file(square) - 3.5)
    rank_distance = abs(chess.square_rank(square) - 3.5)
    # 0 at a corner, 42 at the four central squares.
    return int(round((7.0 - (file_distance + rank_distance)) * 12.0))


def _passed_pawn_advance_score(board: chess.Board, color: chess.Color) -> int:
    score = 0
    direction = 1 if color == chess.WHITE else -1
    enemy = not color
    for square in board.pieces(chess.PAWN, color):
        file = chess.square_file(square)
        rank = chess.square_rank(square)
        blocked = False
        for enemy_square in board.pieces(chess.PAWN, enemy):
            enemy_file = chess.square_file(enemy_square)
            enemy_rank = chess.square_rank(enemy_square)
            if abs(enemy_file - file) > 1:
                continue
            if (enemy_rank - rank) * direction > 0:
                blocked = True
                break
        if blocked:
            continue
        advancement = rank if color == chess.WHITE else 7 - rank
        score += max(0, advancement - 1)
    return score


def _endgame_conversion_score(board: chess.Board) -> int:
    """White-positive score for converting a clear material edge.

    Earlier exp5 builds learned to avoid losses, but complete reviewer games
    showed a second-order weakness: when ahead in rook/pawn endings the engine
    kept its king on the rim and accepted perpetual-check repetitions. This
    term only activates in low-material or late positions with a clear material
    lead, so it does not rewrite opening king-safety behavior.
    """
    score = 0
    for color, sign in ((chess.WHITE, 1), (chess.BLACK, -1)):
        if not _is_conversion_phase(board, color):
            continue
        own_king = board.king(color)
        enemy_king = board.king(not color)
        margin = min(1800, max(_CONVERSION_MARGIN_CP, _material_margin_for_color(board, color)))
        scale = margin / 900.0
        king_delta = _king_center_activity(own_king) - (_king_center_activity(enemy_king) // 3)
        passed = _passed_pawn_advance_score(board, color)
        score += sign * int(round(king_delta * scale))
        score += sign * int(round(passed * _PASSED_PAWN_ADVANCE_WEIGHT * scale))
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
    """King-safety eval term (centipawns, white-positive).

    Upgraded for exp5_06 (exp3-example2 lesson item 10):

    1. Reward the king for being inside a *post-castle haven* — a set of
       squares typical of a castled (and possibly slightly shuffled) king,
       NOT just g1/c1. This generalises "the king is safe" beyond the
       strict O-O/O-O-O target squares, so the model doesn't lose all
       reward when the king moves Kg1→h1 or Kg1→f1 after castling.

    2. Penalise an *uncastled* king that is still on its starting square
       after the opening (fullmove_number > 12). exp3 example2 showed the
       failure mode where a candidate model walks the king from e1 in the
       early middlegame because the eval surface has no incentive to
       castle. The penalty is `weight // 2` so it's smaller than the
       safe-haven reward but big enough that a same-difference safe move
       (e.g. Ke1-e2) doesn't look neutral.

    3. The is-check penalty is unchanged: still `-weight` for whichever
       side is currently in check.
    """
    weight = int(model.get("king_safety_weight") or 0)
    score = 0

    wk = board.king(chess.WHITE)
    bk = board.king(chess.BLACK)
    if wk in _WHITE_KING_SAFE_SQUARES:
        score += weight
    if bk in _BLACK_KING_SAFE_SQUARES:
        score -= weight

    # Uncastled-king penalty after the opening.
    fm = board.fullmove_number
    if fm > _EARLY_KING_PENALTY_AFTER_FULLMOVE and weight > 0:
        if wk == chess.E1 and board.has_castling_rights(chess.WHITE) is False:
            # K has moved (no rights) but is back on e1: an unusual case;
            # still treat as exposed.
            score -= weight // 2
        elif wk == chess.E1:
            # K hasn't moved at all — castling never happened; penalise.
            score -= weight // 2
        if bk == chess.E8 and board.has_castling_rights(chess.BLACK) is False:
            score += weight // 2
        elif bk == chess.E8:
            score += weight // 2

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
    score += _endgame_conversion_score(board)
    score += int(model.get("tempo") or 0) if board.turn == chess.WHITE else -int(model.get("tempo") or 0)
    eval_cache[board_hash] = score
    return score


def _move_order_score(board: chess.Board, move: chess.Move) -> int:
    score = 0
    if board.is_capture(move):
        captured = _captured_piece(board, move)
        attacker = board.piece_at(move.from_square)
        if captured is not None:
            score += _PIECE_VALUES.get(captured.piece_type, 0) * 10
        if attacker is not None:
            score -= _PIECE_VALUES.get(attacker.piece_type, 0)
        see = _static_exchange_eval(board, move)
        score += see * 4
        if see < -80:
            score += see * 5
    if move.promotion:
        score += 8_000 + _promotion_priority(move) * 250
    if board.is_en_passant(move):
        score += 3_000
    if board.gives_check(move):
        score += 1_500
    # exp3-example2 lesson item 10: castling itself is desirable. Without this
    # bonus the cheap eval has no reason to pick e1g1 over a center pawn move
    # in the opening — exp3 castled 0/5 across the dirty replay set; the exp5
    # baseline (pre-fix) castled in 1/4 special-rule cases for the same
    # reason. The bonus is large enough to compete with the +500 develop-
    # minor-piece bonus + the +240 to-center bonus that often win on move 5.
    if board.is_castling(move):
        score += 700
    piece = board.piece_at(move.from_square)
    if piece and piece.piece_type in {chess.KNIGHT, chess.BISHOP} and chess.square_rank(move.from_square) in {0, 7}:
        score += 500
    if piece and piece.piece_type == chess.KING and _is_conversion_phase(board, piece.color):
        before_activity = _king_center_activity(move.from_square)
        after_activity = _king_center_activity(move.to_square)
        score += (after_activity - before_activity) * _KING_ACTIVITY_WEIGHT
    if move.to_square in _CENTER:
        score += 240
    return score


def _opening_development_bonus(board: chess.Board, move: chess.Move) -> int:
    """Prefer normal off-book development over flank pawn/rook wandering.

    The static route-level book handles common openings. This guard covers
    off-book positions, where the shallow NNUE eval has been prone to moves
    like ...a5/...a4 or early rook captures that win a pawn but leave
    development and king safety behind.
    """
    if board.fullmove_number > _OPENING_DEVELOPMENT_FULLMOVE_LIMIT or board.is_check():
        return 0
    piece = board.piece_at(move.from_square)
    if piece is None:
        return 0
    score = 0
    if board.is_castling(move):
        score += 2200
    if piece.piece_type in {chess.KNIGHT, chess.BISHOP}:
        home_rank = 0 if piece.color == chess.WHITE else 7
        if chess.square_rank(move.from_square) == home_rank:
            score += 1500
        if move.to_square in _CENTER or move.to_square in _EXTENDED_CENTER:
            score += 500
    if piece.piece_type == chess.PAWN:
        from_file = chess.square_file(move.from_square)
        to_rank = chess.square_rank(move.to_square)
        if from_file in {3, 4}:
            score += 1250
        elif from_file in {2, 5}:
            score += 450
        elif from_file in _NEAR_FLANK_FILES:
            score -= 300
        elif from_file in _FLANK_FILES:
            score -= 1100
        if move.to_square in _CENTER or move.to_square in _EXTENDED_CENTER:
            score += 350
        if to_rank in {3, 4}:
            score += 150
    if piece.piece_type == chess.ROOK:
        captured_value = _captured_piece_value(board, move)
        if not board.is_castling(move) and captured_value < _PIECE_VALUES[chess.ROOK] and not board.gives_check(move):
            score -= 2200
    if piece.piece_type == chess.QUEEN and not board.gives_check(move) and not board.is_capture(move):
        score -= 800
    return score


def _is_early_flank_pawn_drift(board: chess.Board, move: chess.Move) -> bool:
    if board.fullmove_number > _OPENING_DEVELOPMENT_FULLMOVE_LIMIT or board.is_check():
        return False
    piece = board.piece_at(move.from_square)
    if piece is None or piece.piece_type != chess.PAWN:
        return False
    from_file = chess.square_file(move.from_square)
    if from_file not in _FLANK_FILES:
        return False
    return not board.is_capture(move) and not board.gives_check(move) and move.promotion is None


def _is_early_rook_excursion(board: chess.Board, move: chess.Move) -> bool:
    if board.fullmove_number > _OPENING_DEVELOPMENT_FULLMOVE_LIMIT or board.is_check():
        return False
    piece = board.piece_at(move.from_square)
    if piece is None or piece.piece_type != chess.ROOK:
        return False
    if board.is_castling(move) or board.gives_check(move):
        return False
    return _captured_piece_value(board, move) < _PIECE_VALUES[chess.ROOK]


def _opening_development_filter(board: chess.Board, best_move: chess.Move | None, *, score_move) -> chess.Move | None:
    if best_move is None:
        return None
    if not (_is_early_flank_pawn_drift(board, best_move) or _is_early_rook_excursion(board, best_move)):
        return best_move
    alternatives = [
        move
        for move in board.legal_moves
        if (
            not _would_stalemate(board, move)
            and not _is_early_flank_pawn_drift(board, move)
            and not _is_early_rook_excursion(board, move)
        )
    ]
    if not alternatives:
        return best_move

    def candidate_score(move: chess.Move) -> float:
        return float(score_move(move)) + float(_opening_development_bonus(board, move))

    return max(alternatives, key=lambda move: (candidate_score(move), move.uci()))


def _opening_king_walk_filter(board: chess.Board, best_move: chess.Move | None, *, score_move) -> chess.Move | None:
    """Avoid early non-castling king walks when a sane non-king answer exists.

    The complete-game gauntlet exposed a French-defense loss where exp5 met
    opening checks with Kd2/Kd3/Ke2 while ordinary blocks or developing moves
    were legal. This guard is intentionally early-game only and keeps forced
    king escapes, castling, mates, and clearly profitable king captures intact.
    """
    if (
        best_move is None
        or not board.is_check()
        or board.fullmove_number > _OPENING_KING_WALK_FULLMOVE_LIMIT
    ):
        return best_move
    piece = board.piece_at(best_move.from_square)
    if piece is None or piece.piece_type != chess.KING or board.is_castling(best_move):
        return best_move
    home_square = chess.E1 if piece.color == chess.WHITE else chess.E8
    if best_move.from_square != home_square:
        return best_move
    after_best = board.copy(stack=False)
    after_best.push(best_move)
    if after_best.is_checkmate():
        return best_move
    if board.is_capture(best_move) and _captured_piece_value(board, best_move) >= _PIECE_VALUES[chess.ROOK]:
        if _static_exchange_eval(board, best_move) >= 0:
            return best_move
    color = piece.color
    chosen_floor = _worst_immediate_reply_material_margin(after_best, color)
    allowed_floor_drop = 700 if board.is_check() else 220
    chosen_score = float(score_move(best_move))
    candidates: list[tuple[float, int, str, chess.Move]] = []
    for candidate in board.legal_moves:
        if candidate == best_move or _would_stalemate(board, candidate):
            continue
        candidate_piece = board.piece_at(candidate.from_square)
        if candidate_piece is None or candidate_piece.piece_type == chess.KING:
            continue
        if board.is_capture(candidate) and _static_exchange_eval(board, candidate) < -150:
            continue
        after = board.copy(stack=False)
        after.push(candidate)
        if after.is_checkmate():
            return candidate
        if _opponent_mate_in_one_moves(after):
            continue
        floor = _worst_immediate_reply_material_margin(after, color)
        if floor < chosen_floor - allowed_floor_drop:
            continue
        score = float(score_move(candidate))
        score += float(_opening_development_bonus(board, candidate))
        if board.is_check():
            score += 1300.0
        if candidate_piece.piece_type in {chess.KNIGHT, chess.BISHOP}:
            home_rank = 0 if candidate_piece.color == chess.WHITE else 7
            if chess.square_rank(candidate.from_square) == home_rank:
                score += 700.0
            if candidate.to_square in _CENTER or candidate.to_square in _EXTENDED_CENTER:
                score += 300.0
        if candidate_piece.piece_type == chess.PAWN and candidate.to_square in _EXTENDED_CENTER:
            score += 450.0
        if candidate_piece.piece_type == chess.QUEEN and board.is_check():
            score -= 250.0
        candidates.append((score, floor, candidate.uci(), candidate))
    if not candidates:
        return best_move
    best_score, _floor, _uci, candidate = sorted(candidates, reverse=True)[0]
    if board.is_check() or best_score >= chosen_score - 120.0:
        return candidate
    return best_move


def _promotion_priority(move: chess.Move) -> int:
    return {
        chess.QUEEN: 4,
        chess.ROOK: 3,
        chess.BISHOP: 2,
        chess.KNIGHT: 1,
    }.get(move.promotion, 0)


def _captured_piece(board: chess.Board, move: chess.Move) -> chess.Piece | None:
    if board.is_en_passant(move):
        capture_square = chess.square(chess.square_file(move.to_square), chess.square_rank(move.from_square))
        return board.piece_at(capture_square)
    return board.piece_at(move.to_square)


def _captured_piece_value(board: chess.Board, move: chess.Move) -> int:
    captured = _captured_piece(board, move)
    return _PIECE_VALUES.get(captured.piece_type, 0) if captured else 0


def _move_piece_value(board: chess.Board, move: chess.Move) -> int:
    piece = board.piece_at(move.from_square)
    if piece is None:
        return 0
    if move.promotion:
        return _PIECE_VALUES.get(move.promotion, _PIECE_VALUES[piece.piece_type])
    return _PIECE_VALUES[piece.piece_type]


def _least_valuable_capture_to(board: chess.Board, target_square: int) -> list[chess.Move]:
    captures = [
        move
        for move in board.legal_moves
        if board.is_capture(move) and move.to_square == target_square
    ]
    return sorted(
        captures,
        key=lambda move: (
            _move_piece_value(board, move),
            -_captured_piece_value(board, move),
            move.uci(),
        ),
    )


def _see_reply_gain(board: chess.Board, target_square: int, depth: int = 0) -> int:
    """Best material gain available by continuing captures on one square.

    This is a deliberately small legal-move SEE approximation. It is slower
    than bitboard SEE, but it is accurate enough for exp5's shallow Python
    search and avoids another hand-written "safe capture" special case.
    """
    if depth >= _SEE_MAX_DEPTH or board.is_game_over():
        return 0
    best = 0
    for reply in _least_valuable_capture_to(board, target_square):
        captured = _captured_piece_value(board, reply)
        if captured <= 0:
            continue
        after = board.copy(stack=False)
        after.push(reply)
        gain = captured - _see_reply_gain(after, target_square, depth + 1)
        if gain > best:
            best = gain
    return max(0, best)


def _static_exchange_eval(board: chess.Board, move: chess.Move) -> int:
    """Approximate centipawn exchange result for the side to move."""
    if move not in board.legal_moves:
        return -_PIECE_VALUES[chess.QUEEN]
    captured = _captured_piece_value(board, move)
    promotion_gain = 0
    piece = board.piece_at(move.from_square)
    if piece is not None and move.promotion:
        promotion_gain = _PIECE_VALUES.get(move.promotion, _PIECE_VALUES[piece.piece_type]) - _PIECE_VALUES[piece.piece_type]
    if captured <= 0 and promotion_gain <= 0:
        return 0
    after = board.copy(stack=False)
    after.push(move)
    if after.is_checkmate():
        return _PIECE_VALUES[chess.KING]
    return int(captured + promotion_gain - _see_reply_gain(after, move.to_square))


def _captured_pawn_promotion_danger(board: chess.Board, move: chess.Move) -> int:
    captured = _captured_piece(board, move)
    if captured is None or captured.piece_type != chess.PAWN:
        return 0
    rank = chess.square_rank(move.to_square)
    if captured.color == chess.BLACK and rank <= 2:
        return 3 - rank
    if captured.color == chess.WHITE and rank >= 5:
        return rank - 4
    return 0


def _material_margin_for_color(board: chess.Board, color: chess.Color) -> int:
    margin = 0
    for piece_type, value in _PIECE_VALUES.items():
        if piece_type == chess.KING:
            continue
        margin += len(board.pieces(piece_type, color)) * value
        margin -= len(board.pieces(piece_type, not color)) * value
    return margin


def _worst_immediate_reply_material_margin(board: chess.Board, color: chess.Color) -> int:
    """Worst material margin after the opponent's immediate forcing reply."""
    worst = _material_margin_for_color(board, color)
    for reply in board.legal_moves:
        after = board.copy(stack=False)
        after.push(reply)
        if after.is_checkmate():
            return -_PIECE_VALUES[chess.KING]
        if board.is_capture(reply):
            worst = min(worst, _material_margin_for_color(after, color))
    return worst


def _legal_after_move(board: chess.Board, move: chess.Move) -> chess.Board:
    after = board.copy(stack=False)
    after.push(move)
    return after


def _to_nnue_board(board_state, side: str) -> chess.Board:
    if isinstance(board_state, dict) and isinstance(board_state.get(_MOVE_HISTORY_KEY), list):
        try:
            return replay_board_from_history(board_state.get(_MOVE_HISTORY_KEY), initial_fen=START_FEN)
        except Exception:
            pass
    return to_chess_board(board_state, side)


def _would_stalemate(board: chess.Board, move: chess.Move) -> bool:
    return _legal_after_move(board, move).is_stalemate()


def _opening_overlay_position_id(board: chess.Board, side: str) -> str:
    ep = chess.square_name(board.ep_square) if board.ep_square is not None else "-"
    text = "|".join([
        board.board_fen(),
        "w" if board.turn == chess.WHITE else "b",
        board.castling_xfen() or "-",
        ep,
        str(side or "").strip().lower(),
    ])
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _opening_overlay_priority_move(board: chess.Board, side: str, model: dict) -> chess.Move | None:
    overlay = model.get("opening_overlay") if isinstance(model.get("opening_overlay"), dict) else {}
    if not overlay or not overlay.get("enabled", True):
        return None
    if board.is_check():
        return None
    try:
        max_fullmove = int(overlay.get("max_fullmove") or 12)
    except Exception:
        max_fullmove = 12
    if board.fullmove_number > max_fullmove:
        return None
    positions = overlay.get("positions") if isinstance(overlay.get("positions"), dict) else {}
    position_id = _opening_overlay_position_id(board, side)
    entry = positions.get(position_id)
    if not isinstance(entry, dict):
        return None
    ranked = []
    for index, item in enumerate(entry.get("moves") or []):
        if not isinstance(item, dict):
            continue
        try:
            move = chess.Move.from_uci(str(item.get("uci") or "").strip().lower())
        except Exception:
            continue
        if move not in board.legal_moves or _would_stalemate(board, move):
            continue
        ranked.append((float(item.get("weight") or 0.0), -index, move.uci(), move))
    if not ranked:
        return None
    return sorted(ranked, reverse=True)[0][3]


def _replay_prior_priority_move(board: chess.Board, side: str) -> chess.Move | None:
    if board.fullmove_number > _REPLAY_PRIOR_MAX_FULLMOVE:
        return None
    move_uci = _REPLAY_PRIOR_BY_POSITION.get((board.fen(), str(side or "").strip().lower()))
    if not move_uci:
        return None
    try:
        move = chess.Move.from_uci(move_uci)
    except Exception:
        return None
    if move not in board.legal_moves or _would_stalemate(board, move):
        return None
    return move


def _avoid_stalemate_filter(board: chess.Board, move: chess.Move | None, *, score_move) -> chess.Move | None:
    if move is None or not _would_stalemate(board, move):
        return move
    alternatives = [candidate for candidate in board.legal_moves if not _would_stalemate(board, candidate)]
    if not alternatives:
        return move
    mates = []
    for candidate in alternatives:
        after = _legal_after_move(board, candidate)
        if after.is_checkmate():
            mates.append(candidate)
    if mates:
        return sorted(mates, key=lambda candidate: candidate.uci())[0]
    return sorted(alternatives, key=lambda candidate: (score_move(candidate), candidate.uci()), reverse=True)[0]


def _avoid_claimable_repetition_filter(board: chess.Board, move: chess.Move | None, *, score_move) -> chess.Move | None:
    if move is None:
        return None
    after = board.copy(stack=True)
    after.push(move)
    if after.is_checkmate() or not after.can_claim_threefold_repetition():
        return move
    # A claimable repetition is a legitimate draw resource. Do not reject it
    # unless the AI is clearly ahead and has a materially safe alternative.
    repeat_margin = _material_margin_for_color(after, board.turn)
    if repeat_margin < -250:
        return move
    repeat_score = float(score_move(move))
    if repeat_margin >= _REPETITION_PROGRESS_MARGIN_CP:
        allowed_score_drop = _REPETITION_PROGRESS_SCORE_DROP_CP
        allowed_material_drop = _REPETITION_PROGRESS_SAFE_DROP_CP
    else:
        allowed_score_drop = 150.0
        allowed_material_drop = 150
    alternatives = []
    for candidate in board.legal_moves:
        candidate_after = board.copy(stack=True)
        candidate_after.push(candidate)
        if candidate_after.is_checkmate():
            return candidate
        if candidate_after.can_claim_threefold_repetition():
            continue
        if _would_stalemate(board, candidate):
            continue
        if _material_margin_for_color(candidate_after, board.turn) < repeat_margin - allowed_material_drop:
            continue
        if repeat_margin >= _REPETITION_PROGRESS_MARGIN_CP:
            floor = _worst_immediate_reply_material_margin(candidate_after, board.turn)
            if floor < repeat_margin - allowed_material_drop:
                continue
            if _opponent_claimable_repetition_replies(candidate_after):
                continue
            if _opponent_mate_in_one_moves(candidate_after):
                continue
        if float(score_move(candidate)) < repeat_score - allowed_score_drop:
            continue
        alternatives.append(candidate)
    if not alternatives:
        return move
    return sorted(alternatives, key=lambda candidate: (score_move(candidate), candidate.uci()), reverse=True)[0]


def _claimable_draw_resource_filter(board: chess.Board, move: chess.Move | None, *, side: str, score_move) -> chess.Move | None:
    if move is None:
        return None
    color = chess.WHITE if str(side or "white").lower() == "white" else chess.BLACK
    if _material_margin_for_color(board, color) > -250:
        return move
    after_chosen = board.copy(stack=True)
    after_chosen.push(move)
    if after_chosen.is_checkmate() or after_chosen.can_claim_threefold_repetition():
        return move
    candidates = []
    for candidate in board.legal_moves:
        candidate_after = board.copy(stack=True)
        candidate_after.push(candidate)
        if candidate_after.can_claim_threefold_repetition():
            candidates.append(candidate)
    if not candidates:
        return move
    return sorted(candidates, key=lambda candidate: (score_move(candidate), candidate.uci()), reverse=True)[0]


def _avoid_reversible_cycle_when_ahead_filter(
    board: chess.Board,
    move: chess.Move | None,
    *,
    side: str,
    score_move,
) -> chess.Move | None:
    if move is None or len(board.move_stack) < 2:
        return move
    color = chess.WHITE if str(side or "white").lower() == "white" else chess.BLACK
    if _material_margin_for_color(board, color) < 300:
        return move
    own_previous = board.move_stack[-2]
    if not (
        own_previous.from_square == move.to_square
        and own_previous.to_square == move.from_square
        and move.promotion is None
        and not board.is_capture(move)
        and not board.gives_check(move)
    ):
        return move
    chosen_score = float(score_move(move))
    candidates: list[tuple[float, str, chess.Move]] = []
    for candidate in board.legal_moves:
        if candidate == move:
            continue
        if _would_stalemate(board, candidate):
            continue
        if (
            own_previous.from_square == candidate.to_square
            and own_previous.to_square == candidate.from_square
            and candidate.promotion is None
            and not board.is_capture(candidate)
            and not board.gives_check(candidate)
        ):
            continue
        after = board.copy(stack=True)
        after.push(candidate)
        if after.is_checkmate():
            return candidate
        if _opponent_mate_in_one_moves(after):
            continue
        if _material_margin_for_color(after, color) < _material_margin_for_color(board, color) - 180:
            continue
        score = float(score_move(candidate))
        if score >= chosen_score - 320.0:
            candidates.append((score, candidate.uci(), candidate))
    if not candidates:
        return move
    return sorted(candidates, reverse=True)[0][2]


def _opponent_claimable_repetition_replies(board: chess.Board) -> list[chess.Move]:
    replies: list[chess.Move] = []
    for reply in board.legal_moves:
        after_reply = board.copy(stack=True)
        after_reply.push(reply)
        if after_reply.can_claim_threefold_repetition():
            replies.append(reply)
    return replies


def _opponent_promotion_moves(board: chess.Board) -> list[chess.Move]:
    return [reply for reply in board.legal_moves if reply.promotion]


def _opponent_checking_promotion_moves(board: chess.Board) -> list[chess.Move]:
    return [reply for reply in _opponent_promotion_moves(board) if board.gives_check(reply)]


def _avoid_unanswered_immediate_promotion_filter(
    board: chess.Board,
    move: chess.Move | None,
    *,
    side: str,
    score_move,
) -> chess.Move | None:
    if move is None:
        return move
    color = chess.WHITE if str(side or "white").lower() == "white" else chess.BLACK
    chosen_after = board.copy(stack=True)
    chosen_after.push(move)
    if chosen_after.is_checkmate() or not _opponent_checking_promotion_moves(chosen_after):
        return move

    margin = _material_margin_for_color(board, color)
    chosen_score = float(score_move(move))
    candidates: list[tuple[float, int, str, chess.Move]] = []
    for candidate in board.legal_moves:
        if candidate == move or _would_stalemate(board, candidate):
            continue
        after = board.copy(stack=True)
        after.push(candidate)
        if after.is_checkmate():
            return candidate
        if _opponent_mate_in_one_moves(after):
            continue
        if _opponent_checking_promotion_moves(after):
            continue
        floor = _worst_immediate_reply_material_margin(after, color)
        if floor < margin - 360:
            continue
        score = float(score_move(candidate))
        if board.gives_check(candidate):
            score += 450.0
        if score < chosen_score - 900.0:
            continue
        candidates.append((score, floor, candidate.uci(), candidate))
    if not candidates:
        return move
    return sorted(candidates, reverse=True)[0][3]


def _avoid_enabling_opponent_repetition_when_ahead_filter(
    board: chess.Board,
    move: chess.Move | None,
    *,
    side: str,
    score_move,
) -> chess.Move | None:
    if move is None or len(board.move_stack) < 6:
        return move
    color = chess.WHITE if str(side or "white").lower() == "white" else chess.BLACK
    margin = _material_margin_for_color(board, color)
    if margin < 300:
        return move
    chosen_after = board.copy(stack=True)
    chosen_after.push(move)
    if chosen_after.is_checkmate():
        return move
    if not _opponent_claimable_repetition_replies(chosen_after):
        return move

    chosen_score = float(score_move(move))
    if margin >= _REPETITION_PROGRESS_MARGIN_CP:
        allowed_score_drop = _REPETITION_PROGRESS_SCORE_DROP_CP
        allowed_floor_drop = _REPETITION_PROGRESS_SAFE_DROP_CP
    else:
        allowed_score_drop = 900.0 if margin >= 900 else 550.0
        allowed_floor_drop = 320
    candidates: list[tuple[float, int, str, chess.Move]] = []
    for candidate in board.legal_moves:
        if candidate == move or _would_stalemate(board, candidate):
            continue
        after = board.copy(stack=True)
        after.push(candidate)
        if after.is_checkmate():
            return candidate
        if after.can_claim_threefold_repetition():
            continue
        if _opponent_claimable_repetition_replies(after):
            continue
        if _opponent_mate_in_one_moves(after):
            continue
        floor = _worst_immediate_reply_material_margin(after, color)
        if floor < margin - allowed_floor_drop:
            continue
        score = float(score_move(candidate))
        if score < chosen_score - allowed_score_drop:
            continue
        candidates.append((score, floor, candidate.uci(), candidate))
    if not candidates:
        return move
    return sorted(candidates, reverse=True)[0][3]


def _opponent_mate_in_one_moves(board: chess.Board) -> list[chess.Move]:
    mates: list[chess.Move] = []
    for reply in board.legal_moves:
        after = board.copy(stack=False)
        after.push(reply)
        if after.is_checkmate():
            mates.append(reply)
    return mates


def _forced_mate_in_two_priority_move(board: chess.Board) -> chess.Move | None:
    """Find a conservative forced mate-in-two move in simplified positions.

    This is deliberately bounded to low-material or otherwise small legal-move
    spaces. Exp5's default live profile is shallow, so this fills an important
    human-visible gap in simple endgames without adding a broad expensive
    tactical solver to every middlegame move.
    """
    if len(board.piece_map()) > _MATE_IN_TWO_MAX_PIECES:
        return None
    legal_moves = sorted(board.legal_moves, key=lambda item: item.uci())
    if not legal_moves or len(legal_moves) > _MATE_IN_TWO_MAX_LEGAL_MOVES:
        return None

    candidates: list[chess.Move] = []
    for move in legal_moves:
        after = board.copy(stack=False)
        after.push(move)
        if after.is_checkmate() or after.is_stalemate():
            continue
        replies = list(after.legal_moves)
        if not replies or len(replies) > _MATE_IN_TWO_MAX_REPLIES:
            continue
        forced = True
        for reply in replies:
            reply_board = after.copy(stack=False)
            reply_board.push(reply)
            if not _opponent_mate_in_one_moves(reply_board):
                forced = False
                break
        if forced:
            candidates.append(move)
    if not candidates:
        return None
    return sorted(
        candidates,
        key=lambda move: (
            board.gives_check(move),
            _move_order_score(board, move),
            _captured_piece_value(board, move),
            move.uci(),
        ),
        reverse=True,
    )[0]


def _avoid_allowing_mate_in_one_filter(board: chess.Board, move: chess.Move | None, *, score_move) -> chess.Move | None:
    if move is None:
        return None
    after = board.copy(stack=False)
    after.push(move)
    if after.is_checkmate() or not _opponent_mate_in_one_moves(after):
        return move
    alternatives: list[chess.Move] = []
    for candidate in board.legal_moves:
        candidate_after = board.copy(stack=False)
        candidate_after.push(candidate)
        if candidate_after.is_checkmate():
            return candidate
        if _would_stalemate(board, candidate):
            continue
        if _opponent_mate_in_one_moves(candidate_after):
            continue
        alternatives.append(candidate)
    if not alternatives:
        return move
    return sorted(alternatives, key=lambda candidate: (score_move(candidate), candidate.uci()), reverse=True)[0]


def _avoid_immediate_material_drop_filter(
    board: chess.Board,
    move: chess.Move | None,
    *,
    side: str,
    score_move,
) -> chess.Move | None:
    if move is None:
        return None
    chosen_after = board.copy(stack=False)
    chosen_after.push(move)
    if chosen_after.is_checkmate():
        return move
    color = chess.WHITE if str(side or "white").lower() == "white" else chess.BLACK
    chosen_floor = _worst_immediate_reply_material_margin(chosen_after, color)

    candidates: list[tuple[int, float, str, chess.Move]] = []
    best_floor = chosen_floor
    for candidate in board.legal_moves:
        if _would_stalemate(board, candidate):
            continue
        after = board.copy(stack=False)
        after.push(candidate)
        if after.is_checkmate():
            return candidate
        if _opponent_mate_in_one_moves(after):
            continue
        floor = _worst_immediate_reply_material_margin(after, color)
        best_floor = max(best_floor, floor)
        candidates.append((floor, float(score_move(candidate)), candidate.uci(), candidate))
    if best_floor - chosen_floor < _PIECE_VALUES[chess.KNIGHT]:
        return move
    safer = [item for item in candidates if item[0] >= best_floor - 80]
    if not safer:
        return move
    return sorted(safer, reverse=True)[0][3]


def _conversion_check_evasion_filter(
    board: chess.Board,
    move: chess.Move | None,
    *,
    side: str,
    score_move,
) -> chess.Move | None:
    if move is None or not board.is_check():
        return move
    color = chess.WHITE if str(side or "white").lower() == "white" else chess.BLACK
    if not _is_conversion_phase(board, color):
        return move
    piece = board.piece_at(move.from_square)
    if piece is None or piece.piece_type != chess.KING:
        return move

    chosen_score = float(score_move(move))
    candidates: list[tuple[float, str, chess.Move]] = []
    for candidate in board.legal_moves:
        candidate_piece = board.piece_at(candidate.from_square)
        if candidate_piece is None or candidate_piece.piece_type != chess.KING:
            continue
        if _would_stalemate(board, candidate):
            continue
        after = board.copy(stack=True)
        after.push(candidate)
        if after.is_checkmate() or _opponent_mate_in_one_moves(after):
            continue
        opponent_claim_replies = 0
        opponent_check_replies = 0
        for reply in after.legal_moves:
            reply_board = after.copy(stack=True)
            reply_board.push(reply)
            if reply_board.can_claim_threefold_repetition():
                opponent_claim_replies += 1
            if after.gives_check(reply):
                opponent_check_replies += 1
        score = float(score_move(candidate))
        score -= opponent_claim_replies * 220.0
        score -= opponent_check_replies * 18.0
        candidates.append((score, candidate.uci(), candidate))
    if not candidates:
        return move
    best_score, _best_uci, best_move = sorted(candidates, reverse=True)[0]
    if best_move == move:
        return move
    # Only override alpha-beta when the conversion-aware score strongly prefers
    # another king escape. This keeps ordinary tactical check evasions intact.
    if best_score >= chosen_score + 140.0:
        return best_move
    return move


def _special_rule_priority_move(board: chess.Board) -> chess.Move | None:
    """Conservative rule/tactic priority before the shallow NNUE/PVS search.

    The NNUE-like eval is intentionally small, so depth-limited search can miss
    rule-specific forcing moves that are obvious to humans: promotion, legal
    en-passant, and high-value captures. This helper only preempts search for
    clear, legal, non-stalemating moves; normal positional choices still go
    through alpha-beta/PVS.
    """
    legal_moves = sorted(board.legal_moves, key=lambda item: item.uci())
    if not legal_moves:
        return None

    promotions = [move for move in legal_moves if move.promotion and not _legal_after_move(board, move).is_stalemate()]
    if promotions:
        return sorted(
            promotions,
            key=lambda move: (
                _legal_after_move(board, move).is_checkmate(),
                move.promotion == chess.QUEEN,
                _promotion_priority(move),
                board.gives_check(move),
                _captured_piece_value(board, move),
                -ord(move.uci()[0]),
            ),
            reverse=True,
        )[0]

    en_passant = [move for move in legal_moves if board.is_en_passant(move) and not _would_stalemate(board, move)]
    if en_passant:
        return en_passant[0]

    material_captures = [
        move
        for move in legal_moves
        if (
            board.is_capture(move)
            and _captured_piece_value(board, move) >= _PIECE_VALUES[chess.KNIGHT]
            and not _would_stalemate(board, move)
        )
    ]
    safe_material_captures = [
        move
        for move in material_captures
        if tactical_safety_report(
            board,
            move,
            max_direct_loss_cp=120,
            compensation_window_cp=60,
        ).get("safe")
        and _static_exchange_eval(board, move) >= -120
    ]
    if safe_material_captures:
        return sorted(
            safe_material_captures,
            key=lambda move: (
                _captured_piece_value(board, move),
                board.gives_check(move),
                -_PIECE_VALUES.get((board.piece_at(move.from_square) or chess.Piece(chess.PAWN, board.turn)).piece_type, 0),
                move.uci(),
            ),
            reverse=True,
        )[0]

    dangerous_pawn_captures = [
        move
        for move in legal_moves
        if (
            board.is_capture(move)
            and _captured_pawn_promotion_danger(board, move) >= 2
            and not _would_stalemate(board, move)
            and tactical_safety_report(
                board,
                move,
                max_direct_loss_cp=120,
                compensation_window_cp=60,
            ).get("safe")
            and _static_exchange_eval(board, move) >= -120
        )
    ]
    if dangerous_pawn_captures:
        return sorted(
            dangerous_pawn_captures,
            key=lambda move: (
                _captured_pawn_promotion_danger(board, move),
                board.gives_check(move),
                -_PIECE_VALUES.get((board.piece_at(move.from_square) or chess.Piece(chess.PAWN, board.turn)).piece_type, 0),
                move.uci(),
            ),
            reverse=True,
        )[0]

    castles = [move for move in legal_moves if board.is_castling(move) and not _would_stalemate(board, move)]
    if castles and board.fullmove_number <= 12 and not board.is_check():
        kingside = [move for move in castles if chess.square_file(move.to_square) > chess.square_file(move.from_square)]
        return sorted(kingside or castles, key=lambda item: item.uci())[0]

    return None


def _move_dict(board: chess.Board, move: chess.Move) -> dict:
    piece = board.piece_at(move.from_square)
    captured = _captured_piece(board, move)
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
    score += float(_opening_development_bonus(board, move))
    return score


def _exp5_qmove_filter(board: chess.Board, move: chess.Move) -> bool:
    if move.promotion:
        return True
    if board.gives_check(move):
        return True
    if not board.is_capture(move):
        return False
    captured = _captured_piece_value(board, move)
    if captured >= _PIECE_VALUES[chess.KNIGHT]:
        return True
    return _static_exchange_eval(board, move) >= 0


def _exp5_search_extension(board: chess.Board, move: chess.Move, ply: int, depth: int) -> int:
    if depth <= 0:
        return 0
    if board.gives_check(move):
        return 1
    if move.promotion:
        return 1
    if board.is_capture(move):
        if _captured_piece_value(board, move) >= _PIECE_VALUES[chess.ROOK]:
            return 1
        if board.move_stack:
            previous = board.peek()
            if move.to_square == previous.to_square and _static_exchange_eval(board, move) >= -80:
                return 1
    return 0


def rank_experiment_nnue_policy_moves(board_state, side: str, *, model_path=None, search_profile="fast") -> list[dict]:
    board = _to_nnue_board(board_state, side)
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


def _move_payload_to_chess_move(board: chess.Board, payload: dict | None) -> chess.Move | None:
    if not isinstance(payload, dict):
        return None
    uci = f"{payload.get('from') or ''}{payload.get('to') or ''}{payload.get('promotion') or ''}".lower()
    try:
        move = chess.Move.from_uci(uci)
    except Exception:
        return None
    return move if move in board.legal_moves else None


def _adapter_cache_key(path: Path) -> str:
    try:
        stat = path.stat()
    except OSError:
        return f"{path}|missing"
    return f"{path}|{stat.st_mtime_ns}|{stat.st_size}"


def _load_adapter_memory(rows_path: Path | None) -> dict[str, dict]:
    if rows_path is None:
        return {}
    path = Path(rows_path)
    if not path.exists():
        return {}
    cache_key = _adapter_cache_key(path)
    cached = _ADAPTER_MEMORY_CACHE.get(cache_key)
    if isinstance(cached, dict):
        return cached
    memory: dict[str, dict] = {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except Exception:
        lines = []
    for line in lines:
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except Exception:
            continue
        if not isinstance(row, dict):
            continue
        fen = str(row.get("fen") or "").strip()
        side = str(row.get("side") or ("white" if " w " in fen else "black")).strip().lower()
        move_uci = str(row.get("move_uci") or row.get("teacher_move") or "").strip().lower()
        if not fen or side not in {"white", "black"} or len(move_uci) < 4:
            continue
        key = f"{fen}|{side}"
        current = memory.get(key)
        quality = str(row.get("label_quality") or "clean").strip().lower()
        priority = 2 if quality == "clean" else 1 if quality == "review" else 0
        if current is not None and int(current.get("_priority") or 0) > priority:
            continue
        teacher_top3 = [str(item).strip().lower() for item in (row.get("teacher_top3") or []) if str(item).strip()]
        if move_uci not in teacher_top3:
            teacher_top3.insert(0, move_uci)
        memory[key] = {
            "move_uci": move_uci,
            "teacher_top3": teacher_top3[:3],
            "teacher_top5": [str(item).strip().lower() for item in (row.get("teacher_top5") or []) if str(item).strip()],
            "label_quality": quality,
            "baseline_teacher_rank": row.get("baseline_teacher_rank"),
            "baseline_policy_gap_cp": row.get("baseline_policy_gap_cp"),
            "label_quality_reason": str(row.get("label_quality_reason") or ""),
            "source": str(row.get("source") or ""),
            "position_id": str(row.get("position_id") or ""),
            "_priority": priority,
        }
    _ADAPTER_MEMORY_CACHE.clear()
    _ADAPTER_MEMORY_CACHE[cache_key] = memory
    return memory


def _policy_row_for_move(rows: list[dict], move: chess.Move | None) -> dict:
    if move is None:
        return {}
    wanted = move.uci()
    return next((row for row in rows if str(row.get("move") or "") == wanted), {})


def _adapter_move_safety_report(
    board: chess.Board,
    *,
    side: str,
    main_move: chess.Move | None,
    adapter_move: chess.Move,
) -> dict:
    if main_move is not None:
        main_after = board.copy(stack=True)
        main_after.push(main_move)
    else:
        main_after = None
    adapter_after = board.copy(stack=True)
    adapter_after.push(adapter_move)
    color = chess.WHITE if str(side or "white").lower() == "white" else chess.BLACK
    reasons: list[str] = []
    if main_after is not None and main_after.is_checkmate():
        reasons.append("main_already_checkmates")
    if adapter_after.is_stalemate():
        reasons.append("adapter_stalemates")
    if _opponent_mate_in_one_moves(adapter_after):
        reasons.append("adapter_allows_mate_in_one")
    if main_after is not None:
        main_floor = _worst_immediate_reply_material_margin(main_after, color)
        adapter_floor = _worst_immediate_reply_material_margin(adapter_after, color)
        if adapter_floor < main_floor - _ADAPTER_MAX_MATERIAL_FLOOR_DROP_CP:
            reasons.append("adapter_material_floor_too_low")
    else:
        main_floor = None
        adapter_floor = _worst_immediate_reply_material_margin(adapter_after, color)
    if (
        adapter_after.can_claim_threefold_repetition()
        and (main_after is None or not main_after.can_claim_threefold_repetition())
        and _material_margin_for_color(board, color) > -250
    ):
        reasons.append("adapter_claimable_repetition_without_need")
    if _material_margin_for_color(board, color) >= 300 and _opponent_claimable_repetition_replies(adapter_after):
        reasons.append("adapter_enables_opponent_repetition_when_ahead")
    return {
        "safe": not reasons,
        "reasons": reasons,
        "main_material_floor": main_floor,
        "adapter_material_floor": adapter_floor,
    }


def _choose_experiment_nnue_move_with_adapter(board_state, side: str, *, search_profile="balanced") -> dict | None:
    adapter_path_text = os.environ.get(_ADAPTER_MODEL_PATH_ENV, "").strip()
    mode = os.environ.get(_ADAPTER_MODE_ENV, "guarded").strip().lower()
    if not adapter_path_text or mode not in {"guarded", "exact", "shadow"}:
        return None
    adapter_path = Path(adapter_path_text)
    if not adapter_path.exists():
        return None
    rows_text = os.environ.get(_ADAPTER_ROWS_PATH_ENV, "").strip()
    rows_path = Path(rows_text) if rows_text else None
    main_model_path = default_chess_nnue_model_path()

    previous_reentry = os.environ.get(_ADAPTER_REENTRY_ENV)
    os.environ[_ADAPTER_REENTRY_ENV] = "1"
    try:
        main_payload = choose_experiment_nnue_move(board_state, side, model_path=None, search_profile=search_profile)
    finally:
        if previous_reentry is None:
            os.environ.pop(_ADAPTER_REENTRY_ENV, None)
        else:
            os.environ[_ADAPTER_REENTRY_ENV] = previous_reentry

    board = _to_nnue_board(board_state, side)
    ai_color = chess.WHITE if side == "white" else chess.BLACK
    if board.turn != ai_color:
        board.turn = ai_color
    if board.is_game_over():
        return main_payload
    main_move = _move_payload_to_chess_move(board, main_payload)
    memory = _load_adapter_memory(rows_path)
    memory_row = memory.get(f"{board.fen()}|{side}")
    memory_move: chess.Move | None = None
    if memory_row:
        try:
            parsed = chess.Move.from_uci(str(memory_row.get("move_uci") or ""))
        except Exception:
            parsed = None
        if parsed is not None and parsed in board.legal_moves:
            memory_move = parsed
    allow_exact = (
        mode == "exact"
        or os.environ.get(_ADAPTER_ALLOW_EXACT_ENV, "").strip().lower() in {"1", "true", "yes", "on"}
    )
    allow_general = os.environ.get(_ADAPTER_ALLOW_GENERAL_ENV, "").strip().lower() in {"1", "true", "yes", "on"}
    model_adapter_move: chess.Move | None = None
    adapter_payload: dict | None = None
    if mode == "shadow" or (memory_move is None and allow_general):
        previous_reentry = os.environ.get(_ADAPTER_REENTRY_ENV)
        os.environ[_ADAPTER_REENTRY_ENV] = "1"
        try:
            adapter_payload = choose_experiment_nnue_move(board_state, side, model_path=adapter_path, search_profile=search_profile)
        finally:
            if previous_reentry is None:
                os.environ.pop(_ADAPTER_REENTRY_ENV, None)
            else:
                os.environ[_ADAPTER_REENTRY_ENV] = previous_reentry
        model_adapter_move = _move_payload_to_chess_move(board, adapter_payload)
    adapter_move = memory_move or model_adapter_move
    adapter_source = "exact_memory" if memory_move is not None else "adapter_model" if model_adapter_move is not None else "none"
    audit = {
        "enabled": True,
        "mode": mode,
        "allow_exact_memory_adoption": allow_exact,
        "allow_general_adapter_model": allow_general,
        "main_model_path": str(main_model_path),
        "adapter_model_path": str(adapter_path),
        "adapter_rows_path": str(rows_path or ""),
        "source": adapter_source,
        "memory_label_quality": str((memory_row or {}).get("label_quality") or ""),
        "memory_label_quality_reason": str((memory_row or {}).get("label_quality_reason") or ""),
        "memory_baseline_teacher_rank": (memory_row or {}).get("baseline_teacher_rank"),
        "memory_baseline_policy_gap_cp": (memory_row or {}).get("baseline_policy_gap_cp"),
        "main_move": main_move.uci() if main_move else "",
        "adapter_model_move": model_adapter_move.uci() if model_adapter_move else "",
        "adapter_move": adapter_move.uci() if adapter_move else "",
        "adopted": False,
        "reasons": [],
    }
    if memory_move is None and mode != "shadow" and not allow_general:
        audit["reasons"].append("no_exact_memory")
        payload = dict(main_payload or {})
        payload["adapter_decision"] = audit
        return payload
    if mode == "shadow":
        payload = dict(main_payload or {})
        payload["adapter_decision"] = audit
        return payload
    if adapter_source == "exact_memory" and not allow_exact:
        audit["reasons"].append("exact_memory_shadow_only")
        payload = dict(main_payload or {})
        payload["adapter_decision"] = audit
        return payload
    if adapter_move is None:
        audit["reasons"].append("adapter_no_legal_move")
        payload = dict(main_payload or {})
        payload["adapter_decision"] = audit
        return payload
    if main_move == adapter_move:
        audit["reasons"].append("same_as_main")
        payload = dict(main_payload or {})
        payload["adapter_decision"] = audit
        return payload

    safety = _adapter_move_safety_report(board, side=side, main_move=main_move, adapter_move=adapter_move)
    audit["safety"] = safety
    if not safety.get("safe"):
        audit["reasons"].extend(safety.get("reasons") or ["adapter_safety_failed"])
        payload = dict(main_payload or {})
        payload["adapter_decision"] = audit
        return payload

    main_rows = rank_experiment_nnue_policy_moves({"__fen__": board.fen()}, side, model_path=main_model_path, search_profile="fast")
    adapter_rows = rank_experiment_nnue_policy_moves({"__fen__": board.fen()}, side, model_path=adapter_path, search_profile="fast")
    main_row = _policy_row_for_move(main_rows, main_move)
    adapter_under_main = _policy_row_for_move(main_rows, adapter_move)
    adapter_under_adapter = _policy_row_for_move(adapter_rows, adapter_move)
    main_score = float(main_row.get("raw_policy_score") or 0.0)
    adapter_main_score = float(adapter_under_main.get("raw_policy_score") or 0.0)
    main_rank_for_adapter = int(adapter_under_main.get("raw_policy_rank") or 9999)
    adapter_rank = int(adapter_under_adapter.get("raw_policy_rank") or 9999)
    score_drop = main_score - adapter_main_score
    audit["main_rank_for_adapter"] = main_rank_for_adapter
    audit["adapter_rank_under_adapter"] = adapter_rank
    audit["main_score"] = main_score
    audit["adapter_move_main_score"] = adapter_main_score
    audit["main_score_drop_for_adapter"] = round(score_drop, 6)
    if adapter_source == "exact_memory":
        support = (
            main_rank_for_adapter <= _ADAPTER_MAX_MAIN_RANK_EXACT
            or score_drop <= _ADAPTER_MAX_MAIN_SCORE_DROP_EXACT_CP
        )
    else:
        support = (
            mode == "guarded"
            and adapter_rank == 1
            and main_rank_for_adapter <= _ADAPTER_MAX_MAIN_RANK_GENERAL
            and score_drop <= _ADAPTER_MAX_MAIN_SCORE_DROP_GENERAL_CP
        )
    if mode == "exact" and adapter_source != "exact_memory":
        support = False
    if not support:
        audit["reasons"].append("insufficient_main_model_support")
        payload = dict(main_payload or {})
        payload["adapter_decision"] = audit
        return payload

    payload = _move_dict(board, adapter_move)
    audit["adopted"] = True
    payload["adapter_decision"] = audit
    return payload


def choose_experiment_nnue_move(board_state, side: str, *, model_path=None, search_profile="balanced"):
    if (
        model_path is None
        and not os.environ.get(_ADAPTER_REENTRY_ENV)
        and os.environ.get(_ADAPTER_MODEL_PATH_ENV, "").strip()
    ):
        adapter_payload = _choose_experiment_nnue_move_with_adapter(board_state, side, search_profile=search_profile)
        if adapter_payload is not None:
            return adapter_payload
    board = _to_nnue_board(board_state, side)
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
        best_mate = sorted(
            forced_mates,
            key=lambda move: (
                bool(move.promotion),
                _promotion_priority(move),
                board.gives_check(move),
                _captured_piece_value(board, move),
                move.uci(),
            ),
            reverse=True,
        )[0]
        return _move_dict(board, best_mate)
    model = _load_model(Path(model_path or default_chess_nnue_model_path()))
    if model_path is None:
        replay_prior_move = _replay_prior_priority_move(board, side)
        if replay_prior_move is not None:
            return _move_dict(board, replay_prior_move)
    overlay_move = _opening_overlay_priority_move(board, side, model)
    priority_move = _special_rule_priority_move(board)
    if overlay_move is not None:
        # Exact curated opening overlays may override the broad "castle early"
        # heuristic and ordinary minor-piece trades, but not forcing rule/tactic
        # priorities such as promotion, en-passant, or high-value captures.
        priority_is_ordinary_minor_capture = (
            priority_move is not None
            and board.is_capture(priority_move)
            and _captured_piece_value(board, priority_move) < _PIECE_VALUES[chess.ROOK]
            and not board.is_en_passant(priority_move)
            and priority_move.promotion is None
        )
        if priority_move is None or board.is_castling(priority_move) or priority_is_ordinary_minor_capture:
            return _move_dict(board, overlay_move)
    forced_mate_two = _forced_mate_in_two_priority_move(board)
    if priority_move is not None:
        if board.is_castling(priority_move) and forced_mate_two is not None:
            return _move_dict(board, forced_mate_two)
        return _move_dict(board, priority_move)
    if forced_mate_two is not None:
        return _move_dict(board, forced_mate_two)

    profile = _resolve_search_profile(search_profile)
    hasher = ZobristHasher(seed=20260530)
    eval_cache: dict[int, int] = {}
    result = search_best_move(
        board,
        max_depth=profile["depth"],
        evaluate=lambda current_board: _nnue_eval(current_board, model, eval_cache, hasher),
        move_order_fn=lambda current_board, move, _ply: _move_order_score(current_board, move),
        qmove_filter=_exp5_qmove_filter,
        extension_fn=_exp5_search_extension,
        max_extensions=2,
        hasher=hasher,
        quiescence_depth=profile["quiescence_depth"],
        time_budget_ms=profile.get("time_budget_ms"),
    )
    best_move = opening_sanity_filter(board, result.best_move, score_move=lambda move: _move_order_score(board, move))
    score_move = lambda move: _score_move_for_side(board, move, side, model, eval_cache, hasher)
    best_move = _opening_development_filter(board, best_move, score_move=score_move)
    best_move = _opening_king_walk_filter(board, best_move, score_move=score_move)
    best_move, _safety_report = choose_tactically_safe_move(
        board,
        best_move,
        score_move=score_move,
        max_direct_loss_cp=80,
        compensation_window_cp=40,
    )
    best_move = _conversion_check_evasion_filter(board, best_move, side=side, score_move=score_move)
    best_move = _avoid_allowing_mate_in_one_filter(board, best_move, score_move=score_move)
    best_move = _avoid_immediate_material_drop_filter(board, best_move, side=side, score_move=score_move)
    best_move = _avoid_unanswered_immediate_promotion_filter(board, best_move, side=side, score_move=score_move)
    best_move = _claimable_draw_resource_filter(board, best_move, side=side, score_move=score_move)
    best_move = _avoid_claimable_repetition_filter(board, best_move, score_move=score_move)
    best_move = _avoid_reversible_cycle_when_ahead_filter(board, best_move, side=side, score_move=score_move)
    best_move = _avoid_enabling_opponent_repetition_when_ahead_filter(board, best_move, side=side, score_move=score_move)
    best_move = _opening_king_walk_filter(board, best_move, score_move=score_move)
    best_move = _avoid_stalemate_filter(board, best_move, score_move=score_move)
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
    # Piece-square and shared center weights are evaluated with the piece color
    # sign in _sparse_feature_score. A positive target should therefore
    # increase the moved piece's own feature weight for BOTH colors: white gets
    # +weight in eval, black gets -weight in eval. The tempo term is still
    # side-signed below because tempo is keyed to side-to-move rather than a
    # piece-color feature.
    delta = _clip(target, -1.0, 1.0) * _clip(weight, 0.1, 8.0) * _LEARNING_RATE
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
    epochs: int = 1,
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
    effective_epochs = max(1, int(epochs or 1))
    for _epoch in range(effective_epochs):
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
        "epochs": effective_epochs,
        "policy_probe": policy_probe,
    }
