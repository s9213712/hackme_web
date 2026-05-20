"""Real neural network evaluator for the Experiment 6 difficulty.

Phase-1 of the Exp6 architectural upgrade. Unlike Exp5's
``chess_nnue`` module (a sparse-JSON material + hand-tuned
NNUE-inspired heuristic eval), this module ships an actual
feedforward neural network with learned parameters, plus an
NNUE-style incremental accumulator that maintains the first hidden
layer pre-activation in O(pieces_changed) per move instead of
O(input_dim * hidden_dim) per move.

Architecture::

    input:    774-dim multi-hot board features
              (768 piece-square one-hots + 6 state bits:
               side-to-move, 4× castling rights, en-passant flag)
    layer 1:  774 -> 256  (clipped ReLU, clip to [0, 127])
    layer 2:  256 -> 32   (clipped ReLU)
    layer 3:  32 -> 1     (linear, scaled to centipawns)

The v4 state bits (audit fix #2) make the encoding move-asymmetric so
the network can learn tempo, castling-related king safety, and ep
tactics that 768-only piece-square encoding can't express.

Three upgrade paths the architecture is designed to enable
incrementally:

1. **Real NN eval** (this commit). ``NeuralEvaluator`` is the
   stateless full-recompute drop-in for ``search_best_move``'s
   ``evaluate`` argument.

2. **NNUE-style incremental update** (this commit, framework only).
   ``IncrementalAccumulator`` mirrors ``chess.Board.push`` / ``pop``
   with delta updates to the L1 pre-activation. The search can wire
   this in to amortize the dominant cost of full recompute, which
   matters once the network grows past the size where the L1
   matrix-multiply dominates per-move work.

3. **C extension hot path** (future commit). The output of L1 is
   designed so it can quantize to int8 without significant accuracy
   loss; the file format reserves keys ``W1_q``, ``b1_q``,
   ``W2_q``, ``b2_q`` for the quantized variants a C extension can
   consume directly. The Python fallback remains the source of
   truth; the C extension is a speed-up, not a correctness path.

Weight format: a single ``.npz`` (NumPy compressed) with keys
``W1``, ``b1``, ``W2``, ``b2``, ``W3``, ``b3`` and optional
``side_to_move_bias_cp``. ``load_weights`` validates the shapes
before returning.

Training: see ``scripts/games/chess_exp6_train.py``. The first
shipping weights are produced by ``make_initial_weights`` (random
He-normal init) so the inference path is fully exercised end-to-end
even before a teacher-labelled training run produces useful
parameters.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import chess
import numpy as np


# Architecture constants.
# v4 input layout (774 = 768 + 6):
#   indices 0..767      — piece-square (12 piece types × 64 squares)
#   index 768           — side-to-move = WHITE (1.0 if white to move)
#   index 769           — castling right: white kingside
#   index 770           — castling right: white queenside
#   index 771           — castling right: black kingside
#   index 772           — castling right: black queenside
#   index 773           — en-passant square exists
# Adding these bits (audit fix #2) lets the network learn move-dependent
# features that 768-only piece-square encoding can't express (tempo,
# castling-related king safety, ep tactics).
INPUT_DIM = 774
PIECE_FEATURE_DIM = 768
STATE_FEATURE_OFFSET = 768
IDX_STM_WHITE = 768
IDX_CASTLE_WK = 769
IDX_CASTLE_WQ = 770
IDX_CASTLE_BK = 771
IDX_CASTLE_BQ = 772
IDX_EP_EXISTS = 773
HIDDEN_1_DIM = 256
HIDDEN_2_DIM = 32
OUTPUT_DIM = 1

# Clipped-ReLU range. NNUE-style networks clip to [0, 127] so that the
# downstream multiplications can quantize to int8 in a future C
# extension hot path. The Python forward pass stays in float32; the
# clip is applied for numerical compatibility with that future path.
CRELU_LO = 0.0
CRELU_HI = 127.0

# Centipawn scale applied after the linear output layer. Training
# labels (Stockfish cp values) are divided by this scale so the
# network's internal range stays comfortable.
EVAL_SCALE = 100.0


def _piece_index(piece: chess.Piece) -> int:
    """Map a ``chess.Piece`` to its [0, 11] index for the feature
    vector. Order: white pawn, knight, bishop, rook, queen, king,
    then the same for black."""
    color_offset = 0 if piece.color == chess.WHITE else 6
    return color_offset + int(piece.piece_type) - 1


def feature_index(square: int, piece: chess.Piece) -> int:
    """Map (square, piece) → flat feature index in [0, 768)."""
    return _piece_index(piece) * 64 + int(square)


def _state_feature_indices(board: chess.Board) -> list[int]:
    """v4 audit fix #2: return indices for the 6 state bits (stm,
    castling rights × 4, ep flag)."""
    out: list[int] = []
    if board.turn == chess.WHITE:
        out.append(IDX_STM_WHITE)
    if board.has_kingside_castling_rights(chess.WHITE):
        out.append(IDX_CASTLE_WK)
    if board.has_queenside_castling_rights(chess.WHITE):
        out.append(IDX_CASTLE_WQ)
    if board.has_kingside_castling_rights(chess.BLACK):
        out.append(IDX_CASTLE_BK)
    if board.has_queenside_castling_rights(chess.BLACK):
        out.append(IDX_CASTLE_BQ)
    if board.ep_square is not None:
        out.append(IDX_EP_EXISTS)
    return out


def active_features(board: chess.Board) -> list[int]:
    """Return the list of active feature indices for ``board`` —
    piece-square one-hots plus the v4 state bits."""
    feats = [feature_index(sq, p) for sq, p in board.piece_map().items()]
    feats.extend(_state_feature_indices(board))
    return feats


def board_to_features(board: chess.Board) -> np.ndarray:
    """Encode ``board`` as an INPUT_DIM-dim float32 one-hot vector."""
    x = np.zeros(INPUT_DIM, dtype=np.float32)
    for idx in active_features(board):
        x[idx] = 1.0
    return x


def _clipped_relu(x: np.ndarray) -> np.ndarray:
    return np.clip(x, CRELU_LO, CRELU_HI)


@dataclass
class NeuralWeights:
    W1: np.ndarray   # (INPUT_DIM, HIDDEN_1_DIM)
    b1: np.ndarray   # (HIDDEN_1_DIM,)
    W2: np.ndarray   # (HIDDEN_1_DIM, HIDDEN_2_DIM)
    b2: np.ndarray   # (HIDDEN_2_DIM,)
    W3: np.ndarray   # (HIDDEN_2_DIM, OUTPUT_DIM)
    b3: np.ndarray   # (OUTPUT_DIM,)
    side_to_move_bias_cp: float = 0.0  # additive constant for tempo.

    def verify_shapes(self) -> None:
        assert self.W1.shape == (INPUT_DIM, HIDDEN_1_DIM), self.W1.shape
        assert self.b1.shape == (HIDDEN_1_DIM,), self.b1.shape
        assert self.W2.shape == (HIDDEN_1_DIM, HIDDEN_2_DIM), self.W2.shape
        assert self.b2.shape == (HIDDEN_2_DIM,), self.b2.shape
        assert self.W3.shape == (HIDDEN_2_DIM, OUTPUT_DIM), self.W3.shape
        assert self.b3.shape == (OUTPUT_DIM,), self.b3.shape


def load_weights(path: str | Path) -> NeuralWeights:
    with np.load(str(path)) as data:
        weights = NeuralWeights(
            W1=data["W1"].astype(np.float32),
            b1=data["b1"].astype(np.float32),
            W2=data["W2"].astype(np.float32),
            b2=data["b2"].astype(np.float32),
            W3=data["W3"].astype(np.float32),
            b3=data["b3"].astype(np.float32),
            side_to_move_bias_cp=(
                float(data["side_to_move_bias_cp"])
                if "side_to_move_bias_cp" in data.files
                else 0.0
            ),
        )
    weights.verify_shapes()
    return weights


def save_weights(path: str | Path, weights: NeuralWeights) -> None:
    weights.verify_shapes()
    np.savez_compressed(
        str(path),
        W1=weights.W1,
        b1=weights.b1,
        W2=weights.W2,
        b2=weights.b2,
        W3=weights.W3,
        b3=weights.b3,
        side_to_move_bias_cp=np.float32(weights.side_to_move_bias_cp),
    )


# v6 residual-eval baseline. The NN learns to predict the deviation
# from a material-balance baseline rather than absolute cp. This
# frees the 200K-parameter network from re-learning that a queen is
# worth more than a pawn — material is now encoded explicitly — and
# lets it spend its capacity on positional patterns (king safety,
# pawn structure, mobility) that need actual learning.
#
# Decisions:
# - Use the standard cp piece values. King has value 0 here (its
#   loss is represented separately by mate / stalemate handling).
# - Bishop slightly > knight (Stockfish convention).
# - Compute from white's perspective so it composes cleanly with
#   the existing white-then-flip cp output path.
PIECE_VALUES_CP: dict[int, int] = {
    chess.PAWN: 100,
    chess.KNIGHT: 320,
    chess.BISHOP: 330,
    chess.ROOK: 500,
    chess.QUEEN: 900,
    chess.KING: 0,
}


def material_balance_cp_white(board: chess.Board) -> float:
    """Return white's material advantage in centipawns. Positive =
    white is up material, negative = black is up. King = 0 (its loss
    is handled by the mate / stalemate branches of ``evaluate_board``).
    """
    total = 0
    for _sq, piece in board.piece_map().items():
        v = PIECE_VALUES_CP[piece.piece_type]
        total += v if piece.color == chess.WHITE else -v
    return float(total)


# v6.2: piece-square tables. Pure material eval was too "flat" — many
# distinct positions evaluate equal, so depth-2 alpha-beta tie-breaks
# arbitrarily and plays poorly. PSTs add per-square positional value
# (knights centralized, pawns advanced toward promotion, king tucked
# in opening / centralized endgame) which gives the search clear
# rankings. Values follow the chess-programming-wiki / Sunfish-style
# tables — well-established baselines, not tuned for this project.
#
# Tables are indexed [rank_from_white_perspective][file], where rank 0
# is white's 1st rank (back row), rank 7 is white's 8th rank. For
# black pieces the rank is mirrored. The square value is added to
# the side's material score.
_PST_PAWN = (
    (  0,  0,  0,  0,  0,  0,  0,  0),
    (  5, 10, 10,-20,-20, 10, 10,  5),
    (  5, -5,-10,  0,  0,-10, -5,  5),
    (  0,  0,  0, 20, 20,  0,  0,  0),
    (  5,  5, 10, 25, 25, 10,  5,  5),
    ( 10, 10, 20, 30, 30, 20, 10, 10),
    ( 50, 50, 50, 50, 50, 50, 50, 50),
    (  0,  0,  0,  0,  0,  0,  0,  0),
)
_PST_KNIGHT = (
    (-50,-40,-30,-30,-30,-30,-40,-50),
    (-40,-20,  0,  5,  5,  0,-20,-40),
    (-30,  5, 10, 15, 15, 10,  5,-30),
    (-30,  0, 15, 20, 20, 15,  0,-30),
    (-30,  5, 15, 20, 20, 15,  5,-30),
    (-30,  0, 10, 15, 15, 10,  0,-30),
    (-40,-20,  0,  0,  0,  0,-20,-40),
    (-50,-40,-30,-30,-30,-30,-40,-50),
)
_PST_BISHOP = (
    (-20,-10,-10,-10,-10,-10,-10,-20),
    (-10,  5,  0,  0,  0,  0,  5,-10),
    (-10, 10, 10, 10, 10, 10, 10,-10),
    (-10,  0, 10, 10, 10, 10,  0,-10),
    (-10,  5,  5, 10, 10,  5,  5,-10),
    (-10,  0,  5, 10, 10,  5,  0,-10),
    (-10,  0,  0,  0,  0,  0,  0,-10),
    (-20,-10,-10,-10,-10,-10,-10,-20),
)
_PST_ROOK = (
    (  0,  0,  0,  5,  5,  0,  0,  0),
    ( -5,  0,  0,  0,  0,  0,  0, -5),
    ( -5,  0,  0,  0,  0,  0,  0, -5),
    ( -5,  0,  0,  0,  0,  0,  0, -5),
    ( -5,  0,  0,  0,  0,  0,  0, -5),
    ( -5,  0,  0,  0,  0,  0,  0, -5),
    (  5, 10, 10, 10, 10, 10, 10,  5),
    (  0,  0,  0,  0,  0,  0,  0,  0),
)
_PST_QUEEN = (
    (-20,-10,-10, -5, -5,-10,-10,-20),
    (-10,  0,  5,  0,  0,  0,  0,-10),
    (-10,  5,  5,  5,  5,  5,  0,-10),
    (  0,  0,  5,  5,  5,  5,  0, -5),
    ( -5,  0,  5,  5,  5,  5,  0, -5),
    (-10,  0,  5,  5,  5,  5,  0,-10),
    (-10,  0,  0,  0,  0,  0,  0,-10),
    (-20,-10,-10, -5, -5,-10,-10,-20),
)
# Middlegame king PST — king tucked behind pawns on h-file / g-file
# is safest. The endgame variant centralizes the king. We use one
# table (midgame) for simplicity; this is the dominant phase the
# staged-test schedule covers.
_PST_KING = (
    ( 20, 30, 10,  0,  0, 10, 30, 20),
    ( 20, 20,  0,  0,  0,  0, 20, 20),
    (-10,-20,-20,-20,-20,-20,-20,-10),
    (-20,-30,-30,-40,-40,-30,-30,-20),
    (-30,-40,-40,-50,-50,-40,-40,-30),
    (-30,-40,-40,-50,-50,-40,-40,-30),
    (-30,-40,-40,-50,-50,-40,-40,-30),
    (-30,-40,-40,-50,-50,-40,-40,-30),
)
_PST_BY_PIECE = {
    chess.PAWN: _PST_PAWN,
    chess.KNIGHT: _PST_KNIGHT,
    chess.BISHOP: _PST_BISHOP,
    chess.ROOK: _PST_ROOK,
    chess.QUEEN: _PST_QUEEN,
    chess.KING: _PST_KING,
}


def piece_square_value_cp_white(board: chess.Board) -> float:
    """Sum the PST contribution from white's perspective. White pieces
    look up the PST directly; black pieces are mirrored vertically (we
    look up the same PST at the rank-flipped square) and subtracted.
    """
    total = 0
    for sq, piece in board.piece_map().items():
        table = _PST_BY_PIECE[piece.piece_type]
        rank = chess.square_rank(sq)
        file_ = chess.square_file(sq)
        if piece.color == chess.WHITE:
            total += table[rank][file_]
        else:
            total -= table[7 - rank][file_]
    return float(total)


def static_baseline_cp_white(board: chess.Board) -> float:
    """Composite hand-coded eval baseline = material + piece-square.
    Provides positional differentiation without needing NN learning.
    """
    return material_balance_cp_white(board) + piece_square_value_cp_white(board)


def evaluate_features(
    features: np.ndarray,
    weights: NeuralWeights,
    *,
    side_to_move: chess.Color,
    material_baseline_cp: float = 0.0,
) -> int:
    """Full forward pass on a 768-dim feature vector. Returns integer
    centipawn evaluation from ``side_to_move``'s perspective.

    v6: the NN output is treated as a RESIDUAL on top of
    ``material_baseline_cp`` (already from white's perspective).
    Callers that don't want the residual interpretation pass 0.0
    (backwards-compatible default).
    """
    h1 = _clipped_relu(features @ weights.W1 + weights.b1)
    h2 = _clipped_relu(h1 @ weights.W2 + weights.b2)
    o = h2 @ weights.W3 + weights.b3
    cp_white = float(o[0]) * EVAL_SCALE + weights.side_to_move_bias_cp + material_baseline_cp
    cp = cp_white if side_to_move == chess.WHITE else -cp_white
    return int(cp)


def evaluate_board(board: chess.Board, weights: NeuralWeights) -> int:
    """Full-recompute forward pass on a ``chess.Board``. Returns cp
    from ``board.turn``'s perspective so the value can be plugged
    directly into the negamax search.

    v6.2: composes static baseline (material + PST) + NN residual.
    The static baseline gives the search clear positional rankings
    even when the NN output is zero (which it is for our current
    snapshot — training a small NN to predict useful residuals at
    our data scale degraded performance vs the baseline alone).
    """
    if board.is_game_over():
        if board.is_checkmate():
            return -1_000_000  # mate-on-the-board penalty from our side.
        return 0  # stalemate / draw by rule.
    x = board_to_features(board)
    return evaluate_features(
        x, weights,
        side_to_move=board.turn,
        material_baseline_cp=static_baseline_cp_white(board),
    )


class IncrementalAccumulator:
    """NNUE-style L1 accumulator with push / pop.

    Maintains the L1 pre-activation as a 256-dim float32 vector. When
    a move is played, the accumulator is updated by subtracting the
    contributions of removed features and adding those of added
    features — O(pieces_changed) per move instead of O(INPUT_DIM ×
    HIDDEN_1_DIM) per move for the full recompute path.

    Usage::

        acc = IncrementalAccumulator(weights)
        acc.reset(board)
        # for each candidate move in search:
        acc.push_state()
        acc.push_move(board, move)
        board.push(move)
        score = acc.output(board.turn)
        board.pop()
        acc.pop_state()

    L2 and L3 are still fully recomputed inside ``output`` — they
    are tiny (256→32→1) and contribute a negligible per-move cost
    compared to the L1 savings. A future C extension can fuse all
    three layers; the Python fallback remains the spec.
    """

    def __init__(self, weights: NeuralWeights):
        self._W1 = weights.W1
        self._b1 = weights.b1
        self._W2 = weights.W2
        self._b2 = weights.b2
        self._W3 = weights.W3
        self._b3 = weights.b3
        self._weights = weights
        self._acc_stack: list[np.ndarray] = [self._b1.copy()]
        self._baseline_stack: list[float] = [0.0]

    def reset(self, board: chess.Board) -> None:
        """Rebuild the accumulator from scratch for ``board``. Call
        before a fresh search to drop any leftover state."""
        acc = self._b1.copy()
        for idx in active_features(board):
            acc += self._W1[idx]
        self._acc_stack = [acc]
        self._baseline_stack = [static_baseline_cp_white(board)]

    def stack_depth(self) -> int:
        return len(self._acc_stack)

    def push_state(self) -> None:
        """Mirror of ``chess.Board.push`` for the accumulator: clone
        the top state so the move can be tentatively applied."""
        self._acc_stack.append(self._acc_stack[-1].copy())
        self._baseline_stack.append(self._baseline_stack[-1])

    def pop_state(self) -> None:
        """Mirror of ``chess.Board.pop``: discard the top state."""
        if len(self._acc_stack) <= 1:
            raise IndexError("cannot pop the root accumulator state")
        self._acc_stack.pop()
        self._baseline_stack.pop()

    def _add_piece(self, square: int, piece: chess.Piece) -> None:
        self._acc_stack[-1] += self._W1[feature_index(square, piece)]

    def _remove_piece(self, square: int, piece: chess.Piece) -> None:
        self._acc_stack[-1] -= self._W1[feature_index(square, piece)]

    def push_move(self, board: chess.Board, move: chess.Move) -> None:
        """Update the top accumulator state to reflect ``move`` being
        played from ``board``. Caller MUST call ``push_state`` first
        and ``pop_state`` after retracting the move.

        ``board`` is the position BEFORE the move. We diff the complete
        feature sets before/after the move, so piece-square features,
        side-to-move, castling rights, and en-passant state all stay in
        lockstep with the full recompute path.
        """
        before_features = set(active_features(board))
        after_board = board.copy(stack=False)
        after_board.push(move)
        after_features = set(active_features(after_board))
        for idx in before_features - after_features:
            self._acc_stack[-1] -= self._W1[idx]
        for idx in after_features - before_features:
            self._acc_stack[-1] += self._W1[idx]
        self._baseline_stack[-1] = static_baseline_cp_white(after_board)

    def output(self, side_to_move: chess.Color, *, board: chess.Board | None = None) -> int:
        """Run L2 + L3 over the current accumulator and return cp.

        v6: pass ``board`` to apply the material-balance baseline that
        ``evaluate_board`` adds. Callers without ``board`` get the raw
        residual-only output (legacy behaviour) — not equivalent to
        ``evaluate_board`` but kept for backwards compat.
        """
        h1 = _clipped_relu(self._acc_stack[-1])
        h2 = _clipped_relu(h1 @ self._W2 + self._b2)
        o = h2 @ self._W3 + self._b3
        material_cp = static_baseline_cp_white(board) if board is not None else self._baseline_stack[-1]
        cp_white = float(o[0]) * EVAL_SCALE + self._weights.side_to_move_bias_cp + material_cp
        cp = cp_white if side_to_move == chess.WHITE else -cp_white
        return int(cp)


class NeuralEvaluator:
    """Stateless full-recompute evaluator. Drop-in replacement for
    the ``evaluate`` callable passed into
    ``chess_search.search_best_move``.

    Use ``IncrementalAccumulator`` directly when a search wants to
    exploit NNUE-style updates. Both code paths produce identical
    outputs (within floating-point round-off) on the same position.
    """

    def __init__(self, weights: NeuralWeights):
        self._weights = weights

    def __call__(self, board: chess.Board) -> int:
        return evaluate_board(board, self._weights)


def make_initial_weights(*, seed: int = 20260516, scale: float = 1.0) -> NeuralWeights:
    """Random He-normal weight initialisation for cold-start.

    Untrained: produces near-zero eval for any board, by design — the
    forward pass is fully exercised but the network has no chess
    knowledge yet. Use ``scripts/games/chess_exp6_train.py`` with
    Stockfish-teacher labels to fit useful parameters.
    """
    rng = np.random.default_rng(seed)
    sigma1 = float(np.sqrt(2.0 / INPUT_DIM)) * scale
    sigma2 = float(np.sqrt(2.0 / HIDDEN_1_DIM)) * scale
    sigma3 = float(np.sqrt(2.0 / HIDDEN_2_DIM)) * scale
    W1 = rng.normal(0.0, sigma1, (INPUT_DIM, HIDDEN_1_DIM)).astype(np.float32)
    b1 = np.zeros(HIDDEN_1_DIM, dtype=np.float32)
    W2 = rng.normal(0.0, sigma2, (HIDDEN_1_DIM, HIDDEN_2_DIM)).astype(np.float32)
    b2 = np.zeros(HIDDEN_2_DIM, dtype=np.float32)
    W3 = rng.normal(0.0, sigma3, (HIDDEN_2_DIM, OUTPUT_DIM)).astype(np.float32)
    b3 = np.zeros(OUTPUT_DIM, dtype=np.float32)
    return NeuralWeights(
        W1=W1, b1=b1, W2=W2, b2=b2, W3=W3, b3=b3,
        side_to_move_bias_cp=0.0,
    )
