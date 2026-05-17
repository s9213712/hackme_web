"""Experiment 6 — real neural network engine.

The Exp5 engine (``chess_nnue``) uses a sparse-JSON heuristic eval
plus a deep stack of post-search filters. Exp6 replaces only the
*evaluator* with a real feedforward neural network (see
``chess_neural``) and reuses the existing ``chess_search`` negamax
machinery (iterative deepening, aspiration windows, Zobrist
transposition table, killer/history move ordering, LMR, PVS,
quiescence). The point is to isolate one architectural change at a
time so the gain (or regression) can be cleanly attributed.

This module is the engine entry point that mirrors
``choose_experiment_nnue_move``'s surface so the rest of the
``hackme_web`` plumbing (routes, replay buffer, etc.) can wire it
with minimal changes.

This file does NOT:
- replace ``EXP5_PRODUCTION_SEARCH_PROFILE`` (Exp5 remains the
  production engine);
- import any Exp5-specific filter (Exp6 is a clean-room engine
  built from ``chess_search`` + ``chess_neural`` only);
- depend on Stockfish (the teacher is offline; runtime is pure
  NumPy CPU inference).
"""

from __future__ import annotations

import os
from pathlib import Path

import chess

from services.games.chess import START_FEN, replay_board_from_history, to_chess_board
from services.games.chess_model_registry import (
    bundled_seed_model_path,
    ensure_runtime_model_from_bundle,
    runtime_model_path,
)
from services.games.chess_neural import (
    NeuralEvaluator,
    NeuralWeights,
    load_weights,
    make_initial_weights,
    save_weights,
)
from services.games.chess_search import (
    ZobristHasher,
    opening_sanity_filter,
    search_best_move,
)


EXPERIMENT_NEURAL_DIFFICULTY = "experiment 6:neuralnet"
DEFAULT_NEURAL_WEIGHTS_NAME = "chess_experiment_6_neural.npz"


_MOVE_HISTORY_KEY = "__move_history__"

# Per-profile search settings. Kept smaller than Exp5's "strong"
# profile until the network is trained — an untrained net adds
# evaluation noise, and shallower search is more honest while we
# burn that in.
_SEARCH_PROFILES: dict[str, dict] = {
    "fast": {
        "depth": 1,
        "quiescence_depth": 1,
        "time_budget_ms": 150,
        "enable_pvs": False,
        "enable_lmr": False,
        "enable_null_move": False,
        "enable_futility": False,
    },
    "balanced": {
        "depth": 2,
        "quiescence_depth": 2,
        "time_budget_ms": 600,
        "enable_pvs": True,
        "enable_lmr": True,
        "enable_null_move": False,
        "enable_futility": True,
    },
    "strong": {
        "depth": 3,
        "quiescence_depth": 3,
        "time_budget_ms": 2500,
        "enable_pvs": True,
        "enable_lmr": True,
        "enable_null_move": True,
        "enable_futility": True,
    },
    # Deterministic profile mirroring V28e's "no time budget" shape so
    # post-promotion comparisons are bit-stable. NOT production yet.
    "fixed_depth_d2": {
        "depth": 2,
        "quiescence_depth": 2,
        "time_budget_ms": None,
        "enable_pvs": True,
        "enable_lmr": True,
        "enable_null_move": False,
        "enable_futility": True,
    },
    "fixed_depth_d3": {
        "depth": 3,
        "quiescence_depth": 3,
        "time_budget_ms": None,
        "enable_pvs": True,
        "enable_lmr": True,
        "enable_null_move": False,
        "enable_futility": True,
    },
}

# Default production profile for Exp6. NOT promoted to engine-wide
# default — Exp5 V28e remains the production engine; Exp6 is exposed
# as a separate difficulty option.
EXP6_DEFAULT_SEARCH_PROFILE = "balanced"

_OPENING_PRINCIPLE_ENV = "EXP6_OPENING_PRINCIPLES"
_OPENING_PRINCIPLE_DEFAULT = "0"
_PIECE_ORDER_VALUE_CP = {
    chess.PAWN: 100,
    chess.KNIGHT: 320,
    chess.BISHOP: 330,
    chess.ROOK: 500,
    chess.QUEEN: 900,
    chess.KING: 0,
}


def bundled_neural_weights_path() -> Path:
    """Read-only seed weights shipped with the repo. Mirrors
    ``chess_nnue.bundled_chess_nnue_model_path``."""
    return bundled_seed_model_path(DEFAULT_NEURAL_WEIGHTS_NAME)


def runtime_neural_weights_path() -> Path:
    """Online-updated runtime weights path. Mirrors
    ``chess_nnue.default_chess_nnue_model_path``. Resolves
    ``$HTML_LEARNING_CHESS_MODEL_DIR`` then ``$HACKME_RUNTIME_DIR``
    so per-deployment training output is kept outside the bundled
    seed."""
    return runtime_model_path(
        DEFAULT_NEURAL_WEIGHTS_NAME,
        env_var="EXP6_NEURAL_WEIGHTS_PATH",
    )


def default_neural_weights_path() -> Path:
    """Resolve the Exp6 weights file in use for runtime inference.

    Precedence:
    1. ``$EXP6_NEURAL_WEIGHTS_PATH`` (explicit override).
    2. ``runtime_chess_models_dir / chess_experiment_6_neural.npz``
       — the online-updated path written by training; created from
       the bundled seed on first call via
       ``ensure_runtime_model_from_bundle``.
    3. ``bundled_chess_models_dir / chess_experiment_6_neural.npz``
       — the read-only shipped seed.
    """
    override = os.environ.get("EXP6_NEURAL_WEIGHTS_PATH", "").strip()
    if override:
        return Path(override)
    runtime_path = runtime_neural_weights_path()
    bundle_path = bundled_neural_weights_path()
    ensure_runtime_model_from_bundle(runtime_path, bundle_path)
    if runtime_path.exists():
        return runtime_path
    return bundle_path


def _resolve_search_profile(profile: str | None, *, board: chess.Board | None = None) -> dict:
    name = str(profile or EXP6_DEFAULT_SEARCH_PROFILE).strip()
    if name not in _SEARCH_PROFILES:
        name = EXP6_DEFAULT_SEARCH_PROFILE
    # v9.4 hybrid: when EXP6_HYBRID_ENDGAME_D3 is set and the board has
    # ≤ EXP6_HYBRID_PIECE_THRESHOLD pieces (default 10), upgrade depth-2
    # profiles to depth-3 (fixed_depth_d3). Endgame depth-3 wall-clock
    # is ~245 ms median (vs middlegame 3000+ ms), acceptable for web.
    if board is not None and os.environ.get("EXP6_HYBRID_ENDGAME_D3", "").strip():
        threshold = int(os.environ.get("EXP6_HYBRID_PIECE_THRESHOLD", "10"))
        if len(board.piece_map()) <= threshold:
            if name in ("balanced", "fixed_depth_d2") and "fixed_depth_d3" in _SEARCH_PROFILES:
                name = "fixed_depth_d3"
    return dict(_SEARCH_PROFILES[name])


def _to_neural_board(board_state, side: str) -> chess.Board:
    if isinstance(board_state, dict) and isinstance(board_state.get(_MOVE_HISTORY_KEY), list):
        try:
            return replay_board_from_history(board_state.get(_MOVE_HISTORY_KEY), initial_fen=START_FEN)
        except Exception:
            pass
    return to_chess_board(board_state, side)


def _move_dict(board: chess.Board, move: chess.Move) -> dict:
    from_sq = chess.square_name(move.from_square)
    to_sq = chess.square_name(move.to_square)
    payload = {
        "from": from_sq,
        "to": to_sq,
        "engine": EXPERIMENT_NEURAL_DIFFICULTY,
    }
    if move.promotion is not None:
        payload["promotion"] = chess.piece_symbol(move.promotion).lower()
    return payload


def _move_order_score(board: chess.Board, move: chess.Move, _ply: int) -> int:
    """Simple capture-first move ordering. The neural eval is not
    used for ordering here — TT and killer/history come from the
    search itself. This keeps Exp6's move-ordering surface minimal
    and avoids inheriting Exp5's heuristic stack."""
    score = 0
    if board.is_capture(move):
        score += 1_000_000
        captured = board.piece_at(move.to_square)
        if captured is not None:
            score += int(captured.piece_type) * 100
        attacker = board.piece_at(move.from_square)
        if attacker is not None:
            score -= int(attacker.piece_type) * 10
    if move.promotion is not None:
        score += 800_000
    if board.gives_check(move):
        score += 50_000
    return score


def _center_bonus(square: int) -> int:
    file = chess.square_file(square)
    rank = chess.square_rank(square)
    return int(28 - 4 * (abs(file - 3.5) + abs(rank - 3.5)))


def _opening_principles_enabled() -> bool:
    value = os.environ.get(_OPENING_PRINCIPLE_ENV, _OPENING_PRINCIPLE_DEFAULT).strip().lower()
    return value not in {"", "0", "false", "no", "off"}


def _opening_principle_score(board: chess.Board, move: chess.Move) -> int:
    if board.fullmove_number > 12 or board.is_check():
        return 0
    moving = board.piece_at(move.from_square)
    if moving is None:
        return 0
    score = 0
    if board.is_capture(move):
        captured = board.piece_at(move.to_square)
        if captured is None and board.is_en_passant(move):
            captured = chess.Piece(chess.PAWN, not board.turn)
        if captured is not None:
            score += 200 + _PIECE_ORDER_VALUE_CP.get(captured.piece_type, 0)
    if board.gives_check(move):
        score += 120
    if move.promotion:
        score += 900
    if board.is_castling(move):
        score += 1200

    to_file = chess.square_file(move.to_square)
    from_rank = chess.square_rank(move.from_square)
    to_rank = chess.square_rank(move.to_square)
    home_rank = 0 if moving.color == chess.WHITE else 7
    if moving.piece_type in (chess.KNIGHT, chess.BISHOP):
        if from_rank == home_rank:
            score += 800
        score += _center_bonus(move.to_square) * 6
    elif moving.piece_type == chess.PAWN:
        direction = 1 if moving.color == chess.WHITE else -1
        advanced = (to_rank - from_rank) * direction
        if to_file in (3, 4):
            score += 650 if advanced == 2 else 520
        elif to_file in (2, 5):
            score += 220
        elif to_file in (0, 7):
            score -= 520
        elif to_file in (1, 6):
            score -= 240
    elif moving.piece_type == chess.QUEEN:
        score -= 460
    elif moving.piece_type == chess.ROOK:
        score -= 520
    elif moving.piece_type == chess.KING and not board.is_castling(move):
        score -= 700
    return score


def _principled_move_order_score(board: chess.Board, move: chess.Move, ply: int) -> int:
    return _move_order_score(board, move, ply) + _opening_principle_score(board, move)


def _is_bad_early_principle_move(board: chess.Board, move: chess.Move) -> bool:
    if board.fullmove_number > 12 or board.is_check():
        return False
    if board.is_capture(move) or board.gives_check(move) or move.promotion or board.is_castling(move):
        return False
    moving = board.piece_at(move.from_square)
    if moving is None:
        return False
    to_file = chess.square_file(move.to_square)
    if moving.piece_type == chess.PAWN and to_file in (0, 7):
        return True
    if moving.piece_type == chess.PAWN and to_file in (1, 6) and board.fullmove_number <= 8:
        return True
    if moving.piece_type in (chess.QUEEN, chess.ROOK):
        return True
    if moving.piece_type == chess.KING and not board.is_castling(move):
        return True
    return False


def _opening_principle_filter(board: chess.Board, best_move: chess.Move | None) -> chess.Move | None:
    if best_move is None or not _is_bad_early_principle_move(board, best_move):
        return best_move
    legal = list(board.legal_moves)
    if not legal:
        return best_move
    scored = [(move, _opening_principle_score(board, move)) for move in legal]
    candidate, candidate_score = max(scored, key=lambda item: (item[1], item[0].uci()))
    best_score = _opening_principle_score(board, best_move)
    if candidate != best_move and candidate_score >= max(450, best_score + 500):
        return candidate
    return best_move


def _ensure_default_weights() -> Path:
    """Make sure usable weights exist at the resolved runtime path.

    Three-stage fallback:

    1. ``default_neural_weights_path()`` honours
       ``$EXP6_NEURAL_WEIGHTS_PATH``, then tries to populate the
       runtime path from the bundled seed via
       ``ensure_runtime_model_from_bundle``.
    2. If both runtime and bundle are missing (fresh environment
       with no shipping seed), we synthesise a deterministic random
       init at the BUNDLED location so the engine remains invocable
       and subsequent training output stays in the runtime path —
       not the read-only seed.
    3. ``load_weights`` later catches corrupt files. This guard
       protects ``choose_experiment_neural_move`` from raising on
       startup; it does NOT validate that the weights produce useful
       play (training does that).
    """
    path = default_neural_weights_path()
    if path.exists():
        return path
    seed_path = bundled_neural_weights_path()
    seed_path.parent.mkdir(parents=True, exist_ok=True)
    save_weights(seed_path, make_initial_weights())
    # Re-resolve so the runtime copy is established for online
    # updates without forcing every caller to know the seed path.
    return default_neural_weights_path()


def choose_experiment_neural_move(
    board_state,
    side: str,
    *,
    weights_path: str | Path | None = None,
    search_profile: str = EXP6_DEFAULT_SEARCH_PROFILE,
):
    """Pick a move using the Exp6 neural-network evaluator.

    Mirrors ``choose_experiment_nnue_move``'s call surface so the
    routes layer can dispatch on difficulty without engine-specific
    plumbing.
    """
    board = _to_neural_board(board_state, side)
    ai_color = chess.WHITE if side == "white" else chess.BLACK
    if board.turn != ai_color:
        board.turn = ai_color
    if board.is_game_over():
        return None

    # Forced mate-in-one short-circuit — cheap and saves the search
    # from missing it at depth 1. Mirrors the Exp5 forced-mates
    # opener but without any of the heuristic post-filters.
    for move in board.legal_moves:
        board.push(move)
        is_mate = board.is_checkmate()
        board.pop()
        if is_mate:
            return _move_dict(board, move)

    weights_file = Path(weights_path) if weights_path is not None else _ensure_default_weights()
    weights = load_weights(weights_file)
    evaluator = NeuralEvaluator(weights)

    profile = _resolve_search_profile(search_profile, board=board)
    hasher = ZobristHasher(seed=20260601)

    opening_principles = _opening_principles_enabled()
    move_order_fn = _principled_move_order_score if opening_principles else _move_order_score
    result = search_best_move(
        board,
        max_depth=int(profile["depth"]),
        evaluate=evaluator,
        move_order_fn=move_order_fn,
        quiescence_depth=int(profile["quiescence_depth"]),
        hasher=hasher,
        time_budget_ms=profile.get("time_budget_ms"),
        enable_pvs=bool(profile.get("enable_pvs")),
        enable_lmr=bool(profile.get("enable_lmr")),
        enable_null_move=bool(profile.get("enable_null_move")),
        enable_futility=bool(profile.get("enable_futility")),
    )
    if result.best_move is None:
        return None

    best_move = opening_sanity_filter(
        board,
        result.best_move,
        score_move=lambda mv: move_order_fn(board, mv, 0),
    )
    if opening_principles:
        best_move = _opening_principle_filter(board, best_move)
    if best_move is None:
        return None
    return _move_dict(board, best_move)
