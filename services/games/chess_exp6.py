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


def _resolve_search_profile(profile: str | None) -> dict:
    name = str(profile or EXP6_DEFAULT_SEARCH_PROFILE).strip()
    if name not in _SEARCH_PROFILES:
        name = EXP6_DEFAULT_SEARCH_PROFILE
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

    profile = _resolve_search_profile(search_profile)
    hasher = ZobristHasher(seed=20260601)

    result = search_best_move(
        board,
        max_depth=int(profile["depth"]),
        evaluate=evaluator,
        move_order_fn=_move_order_score,
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
        score_move=lambda mv: _move_order_score(board, mv, 0),
    )
    if best_move is None:
        return None
    return _move_dict(board, best_move)
