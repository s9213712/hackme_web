"""Unit tests for the Experiment 6 neural evaluator.

Covers feature encoding, forward-pass shapes, save/load round-trip,
the NNUE-style incremental accumulator parity with full recompute,
and the engine-entry smoke through ``choose_experiment_neural_move``.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import chess
import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from services.games.chess_neural import (  # noqa: E402
    EVAL_SCALE,
    HIDDEN_1_DIM,
    HIDDEN_2_DIM,
    INPUT_DIM,
    IncrementalAccumulator,
    NeuralEvaluator,
    NeuralWeights,
    active_features,
    board_to_features,
    evaluate_board,
    feature_index,
    load_weights,
    make_initial_weights,
    save_weights,
)
from services.games.chess_exp6 import (  # noqa: E402
    EXPERIMENT_NEURAL_DIFFICULTY,
    EXP6_DEFAULT_SEARCH_PROFILE,
    choose_experiment_neural_move,
)
from services.games.chess import FEN_KEY  # noqa: E402


# ---------------- feature encoding ----------------


def test_feature_index_is_bijective_for_starting_position():
    board = chess.Board()
    indices = active_features(board)
    assert len(indices) == 32, "starting position has 32 pieces"
    assert len(set(indices)) == 32, "indices must be unique"
    # All indices in valid range.
    assert all(0 <= i < INPUT_DIM for i in indices)


def test_board_to_features_is_one_hot_per_piece():
    board = chess.Board()
    x = board_to_features(board)
    assert x.shape == (INPUT_DIM,)
    assert x.dtype == np.float32
    # Exactly 32 ones (pieces on the starting board), rest zero.
    assert int(x.sum()) == 32
    # Each piece occupies exactly one feature slot — no double counts.
    assert set(int(v) for v in x) <= {0, 1}


def test_feature_index_distinguishes_color_and_piece_type():
    white_knight_e4 = feature_index(chess.E4, chess.Piece(chess.KNIGHT, chess.WHITE))
    black_knight_e4 = feature_index(chess.E4, chess.Piece(chess.KNIGHT, chess.BLACK))
    white_bishop_e4 = feature_index(chess.E4, chess.Piece(chess.BISHOP, chess.WHITE))
    assert white_knight_e4 != black_knight_e4
    assert white_knight_e4 != white_bishop_e4
    assert black_knight_e4 != white_bishop_e4


# ---------------- forward pass shapes ----------------


def test_make_initial_weights_shapes_match_architecture():
    weights = make_initial_weights()
    weights.verify_shapes()
    assert weights.W1.shape == (INPUT_DIM, HIDDEN_1_DIM)
    assert weights.W2.shape == (HIDDEN_1_DIM, HIDDEN_2_DIM)
    assert weights.W3.shape == (HIDDEN_2_DIM, 1)


def test_evaluate_board_returns_integer_cp():
    weights = make_initial_weights()
    board = chess.Board()
    cp = evaluate_board(board, weights)
    assert isinstance(cp, int)
    # Untrained network: eval should be in a sane range, not blowing up.
    assert -10_000 < cp < 10_000


def test_evaluate_board_perspective_flips_with_side_to_move():
    weights = make_initial_weights()
    board = chess.Board()
    cp_white = evaluate_board(board, weights)
    board.turn = chess.BLACK
    cp_black = evaluate_board(board, weights)
    assert cp_white == -cp_black, f"perspective must flip; got {cp_white} vs {cp_black}"


def test_terminal_positions_return_known_constants():
    weights = make_initial_weights()
    # Stalemate-ish: black king alone in a corner with no legal moves
    # is hard to construct cleanly; instead check that a checkmated
    # position returns the mate constant.
    fen_mate = "7k/5KQ1/8/8/8/8/8/8 b - - 0 1"  # black king h8, white queen g7, white king f7
    board = chess.Board(fen_mate)
    assert board.is_checkmate()
    cp = evaluate_board(board, weights)
    assert cp == -1_000_000


# ---------------- save / load round-trip ----------------


def test_save_load_round_trip_preserves_weights():
    weights = make_initial_weights(seed=42)
    weights.side_to_move_bias_cp = 12.5
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "exp6.npz"
        save_weights(path, weights)
        loaded = load_weights(path)
    np.testing.assert_array_equal(weights.W1, loaded.W1)
    np.testing.assert_array_equal(weights.b1, loaded.b1)
    np.testing.assert_array_equal(weights.W2, loaded.W2)
    np.testing.assert_array_equal(weights.b2, loaded.b2)
    np.testing.assert_array_equal(weights.W3, loaded.W3)
    np.testing.assert_array_equal(weights.b3, loaded.b3)
    assert abs(loaded.side_to_move_bias_cp - 12.5) < 1e-6


# ---------------- incremental accumulator ----------------


def _eval_via_accumulator(board: chess.Board, weights: NeuralWeights) -> int:
    acc = IncrementalAccumulator(weights)
    acc.reset(board)
    return acc.output(board.turn)


def test_accumulator_reset_matches_full_recompute_starting_position():
    weights = make_initial_weights()
    board = chess.Board()
    cp_full = evaluate_board(board, weights)
    cp_acc = _eval_via_accumulator(board, weights)
    assert cp_full == cp_acc


def test_accumulator_push_move_matches_full_recompute_on_capture_sequence():
    """Play a short sequence with captures, castling-relevant moves, and
    promotion-relevant pawn pushes; at every position the accumulator
    output must equal the full recompute output.
    """
    weights = make_initial_weights()
    moves = ["e2e4", "e7e5", "g1f3", "b8c6", "f1b5", "a7a6", "b5c6", "d7c6", "e1g1"]
    board = chess.Board()
    acc = IncrementalAccumulator(weights)
    acc.reset(board)
    for uci in moves:
        move = chess.Move.from_uci(uci)
        acc.push_state()
        acc.push_move(board, move)
        board.push(move)
        cp_full = evaluate_board(board, weights)
        cp_inc = acc.output(board.turn)
        assert cp_full == cp_inc, f"divergence after {uci}: full={cp_full} inc={cp_inc}"


def test_accumulator_handles_en_passant():
    weights = make_initial_weights()
    board = chess.Board()
    for uci in ["e2e4", "d7d5", "e4e5", "f7f5"]:
        board.push_uci(uci)
    # Now white can play exf6 en passant.
    ep = chess.Move.from_uci("e5f6")
    assert board.is_en_passant(ep)
    acc = IncrementalAccumulator(weights)
    acc.reset(board)
    acc.push_state()
    acc.push_move(board, ep)
    board.push(ep)
    cp_full = evaluate_board(board, weights)
    cp_inc = acc.output(board.turn)
    assert cp_full == cp_inc


def test_accumulator_handles_castling():
    weights = make_initial_weights()
    moves = ["e2e4", "e7e5", "g1f3", "b8c6", "f1c4", "g8f6", "e1g1"]  # white short castles
    board = chess.Board()
    acc = IncrementalAccumulator(weights)
    acc.reset(board)
    for uci in moves:
        move = chess.Move.from_uci(uci)
        acc.push_state()
        acc.push_move(board, move)
        board.push(move)
    assert evaluate_board(board, weights) == acc.output(board.turn)


def test_accumulator_handles_promotion():
    weights = make_initial_weights()
    # Construct a near-promotion position quickly via FEN.
    board = chess.Board("8/P7/8/8/8/8/8/k6K w - - 0 1")
    promote = chess.Move.from_uci("a7a8q")
    acc = IncrementalAccumulator(weights)
    acc.reset(board)
    acc.push_state()
    acc.push_move(board, promote)
    board.push(promote)
    assert evaluate_board(board, weights) == acc.output(board.turn)


def test_accumulator_pop_restores_state():
    weights = make_initial_weights()
    board = chess.Board()
    acc = IncrementalAccumulator(weights)
    acc.reset(board)
    cp_before = acc.output(board.turn)
    acc.push_state()
    move = chess.Move.from_uci("e2e4")
    acc.push_move(board, move)
    board.push(move)
    _ = acc.output(board.turn)
    board.pop()
    acc.pop_state()
    cp_after = acc.output(board.turn)
    assert cp_before == cp_after


# ---------------- engine integration smoke ----------------


def _state_from_board(board: chess.Board) -> dict[str, str]:
    state = {chess.square_name(sq): p.symbol() for sq, p in board.piece_map().items()}
    state[FEN_KEY] = board.fen()
    return state


def test_choose_experiment_neural_move_returns_legal_move_from_start():
    board = chess.Board()
    state = _state_from_board(board)
    result = choose_experiment_neural_move(
        state, "white", search_profile=EXP6_DEFAULT_SEARCH_PROFILE,
    )
    assert result is not None
    uci = f"{result['from']}{result['to']}"
    if result.get("promotion"):
        uci += result["promotion"]
    move = chess.Move.from_uci(uci)
    assert move in board.legal_moves
    assert result.get("engine") == EXPERIMENT_NEURAL_DIFFICULTY
    assert result.get("piece")
    assert "captured" in result


def test_choose_experiment_neural_move_detects_forced_mate_in_one():
    # Classic back-rank mate: black king g8 boxed in by its own f7/g7/h7
    # pawns; white rook a1 plays Ra8# along the 8th rank.
    board = chess.Board("6k1/5ppp/8/8/8/8/8/R5K1 w - - 0 1")
    # Sanity: confirm the test position genuinely admits a mate-in-1.
    has_mate = False
    for mv in board.legal_moves:
        board.push(mv)
        if board.is_checkmate():
            has_mate = True
            board.pop()
            break
        board.pop()
    assert has_mate, "test FEN must contain a mate-in-1 move"

    state = _state_from_board(board)
    result = choose_experiment_neural_move(state, "white", search_profile="fast")
    assert result is not None
    chosen = chess.Move.from_uci(f"{result['from']}{result['to']}")
    board.push(chosen)
    assert board.is_checkmate(), f"engine missed mate-in-1: chose {chosen.uci()}"
