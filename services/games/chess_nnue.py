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
_MOVE_HISTORY_KEY = "__move_history__"

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
    if repeat_margin < 500:
        return move
    repeat_score = float(score_move(move))
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
        if _material_margin_for_color(candidate_after, board.turn) < repeat_margin - 150:
            continue
        if float(score_move(candidate)) < repeat_score - 150.0:
            continue
        alternatives.append(candidate)
    if not alternatives:
        return move
    return sorted(alternatives, key=lambda candidate: (score_move(candidate), candidate.uci()), reverse=True)[0]


def _opponent_mate_in_one_moves(board: chess.Board) -> list[chess.Move]:
    mates: list[chess.Move] = []
    for reply in board.legal_moves:
        after = board.copy(stack=False)
        after.push(reply)
        if after.is_checkmate():
            mates.append(reply)
    return mates


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


def choose_experiment_nnue_move(board_state, side: str, *, model_path=None, search_profile="balanced"):
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
    if priority_move is not None:
        return _move_dict(board, priority_move)

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
    score_move = lambda move: _score_move_for_side(board, move, side, model, eval_cache, hasher)
    best_move = _opening_development_filter(board, best_move, score_move=score_move)
    best_move, _safety_report = choose_tactically_safe_move(
        board,
        best_move,
        score_move=score_move,
        max_direct_loss_cp=80,
        compensation_window_cp=40,
    )
    best_move = _avoid_allowing_mate_in_one_filter(board, best_move, score_move=score_move)
    best_move = _avoid_claimable_repetition_filter(board, best_move, score_move=score_move)
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
