"""Unit tests for ``chess_exp5_threat_guard``.

These tests cover the four scenarios called out as must-haves for the
V29r line: the canonical staged-game-2 ply-24 regression, an
SEE-balanced trade that should NOT be flagged as a threat, calm
opening positions that should produce no triggers, and the V28e
fork-danger choice that the threat guard must not perturb.
"""

from __future__ import annotations

import sys
from pathlib import Path

import chess

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from services.games.chess_exp5_threat_guard import (  # noqa: E402
    PreExistingThreat,
    find_pre_existing_threats,
    neutralizes_threat,
    threat_response_tiebreak,
)


# Game-2 ply 24 position (after the staged Ng5 attacking Be6).
# This is the canonical case the V29r guard must understand.
GAME2_PLY24_FEN = (
    "r2q1rk1/ppp1n1pp/2n1b3/3pPpN1/3P4/2P1B1P1/P3BP1P/R2QK2R b KQ - 2 12"
)


def _board(fen: str) -> chess.Board:
    return chess.Board(fen)


def _move(uci: str) -> chess.Move:
    return chess.Move.from_uci(uci)


# Test 1 — game 2 ply 24 regression.
# At this position the staged engine played a7a6 and lost the bishop to
# Ng5xe6. The detector must report Ng5xe6 as a high-SEE threat, must
# judge a7a6 as NOT neutralizing it, and must judge a defending move
# (e6d7 = bishop retreat, d8d7 = queen defense) as neutralizing.

def test_game2_ply24_threat_detected():
    board = _board(GAME2_PLY24_FEN)
    threats = find_pre_existing_threats(board, max_threats=4, min_see_cp=250)
    assert threats, "expected at least one high-SEE threat at game-2 ply-24"
    top = threats[0]
    assert top.move == _move("g5e6"), f"expected top threat Ng5xe6, got {top.move.uci()}"
    assert top.see_cp >= 300, f"expected SEE >=300 (won bishop), got {top.see_cp}"
    assert top.victim_square == chess.E6


def test_game2_ply24_a7a6_does_not_neutralize():
    board = _board(GAME2_PLY24_FEN)
    threats = find_pre_existing_threats(board, max_threats=4, min_see_cp=250)
    assert threats
    assert not neutralizes_threat(board, _move("a7a6"), threats[0])


def test_game2_ply24_bishop_retreat_neutralizes():
    board = _board(GAME2_PLY24_FEN)
    threats = find_pre_existing_threats(board, max_threats=4, min_see_cp=250)
    assert threats
    assert neutralizes_threat(board, _move("e6d7"), threats[0])


def test_game2_ply24_queen_defense_neutralizes():
    board = _board(GAME2_PLY24_FEN)
    threats = find_pre_existing_threats(board, max_threats=4, min_see_cp=250)
    assert threats
    # After Qd7 the bishop is defended; Ng5xe6 is still legal but its SEE
    # drops to the recapture trade value (knight ~320 won, bishop ~335
    # lost, then we recapture knight ~+320). Residual cap of 100 should
    # accept the trade as "neutralized" in the SEE sense.
    assert neutralizes_threat(board, _move("d8d7"), threats[0])


# Test 2 — SEE-balanced trade should NOT be flagged.
# A position where the raw "worst opponent capture" metric would report
# a piece loss, but SEE reveals the recapture network keeps the trade
# small. The detector must treat that as not-a-threat.

def test_see_balanced_trade_not_flagged_as_threat():
    # White knight on f3 attacked by black knight on g5; white knight is
    # defended by pawn g2. Black NxN trade is SEE ~ 0 (320 won, 320 lost).
    # White to move; from white's perspective there is no high-SEE
    # threat against us — opponent's best capture nets ~0.
    fen = "rnbqkb1r/pppp1ppp/8/6n1/4P3/5N2/PPPP1PPP/RNBQKB1R w KQkq - 0 1"
    board = _board(fen)
    threats = find_pre_existing_threats(board, max_threats=4, min_see_cp=250)
    # A min_see=250 cutoff must drop the even-trade out. A 0-SEE
    # recapture must NOT appear as a threat.
    high_see = [t for t in threats if t.see_cp >= 250]
    assert not high_see, f"defended even trade should not flag as threat: {high_see}"


# Test 3 — calm position no-op.
# Fresh starting position and a couple of quiet opening positions
# should produce zero high-SEE threats. This is the key guarantee
# that the V29r guard won't disrupt baseline draw cycles.

def test_starting_position_no_threats():
    threats = find_pre_existing_threats(chess.Board(), max_threats=4, min_see_cp=250)
    assert threats == []


def test_quiet_italian_no_threats():
    fen = (
        "r1bqkbnr/pppp1ppp/2n5/4p3/2B1P3/5N2/PPPP1PPP/RNBQK2R b KQkq - 3 3"
    )
    threats = find_pre_existing_threats(_board(fen), max_threats=4, min_see_cp=250)
    assert threats == []


# Test 4 — game-5 ply-5 fork-danger position.
# After ``c2c4 g8f6 b1a3 e7e5`` white to move. V28e correctly plays
# g1f3 here, driven by ``_opponent_knight_fork_danger`` (a non-immediate
# tactical signal). The threat guard sees only immediate captures, so it
# must report no high-SEE threat for white — the previous bug fixed
# in V29h_see5 was exactly that an over-eager precondition flagged
# this position and let the SEE filter overrule V28e's anti-fork
# choice.

def test_game5_ply5_no_immediate_see_threat():
    board = chess.Board()
    for uci in ("c2c4", "g8f6", "b1a3", "e7e5"):
        board.push_uci(uci)
    threats = find_pre_existing_threats(board, max_threats=4, min_see_cp=250)
    assert threats == [], f"calm english-opening start should not flag: {threats}"


# Test 5 — threat_response_tiebreak narrow firing.
# At game-2 ply-24 with gap=20cp (a7a6 score -215, d8d7 score -235 per
# V29r_diag log), a +60 bonus must swap; a +0 bonus must not; a -10
# would also block. Use a synthetic score_move to keep the contract
# decoupled from the real evaluator.

def _scores_g2_ply24(move: chess.Move) -> float:
    table = {"a7a6": -215.0, "d8d7": -235.0, "e6d7": -240.0, "h7h6": -260.0}
    return table.get(move.uci(), -1000.0)


def test_tiebreak_swaps_at_small_positive_gap():
    board = _board(GAME2_PLY24_FEN)
    out = threat_response_tiebreak(
        board, _move("a7a6"),
        score_move=_scores_g2_ply24,
        max_gap_cp=60,
    )
    # a7a6 doesn't neutralize; d8d7 does and has best score among
    # neutralizers (-235 > -240). gap = -215 - (-235) = 20 <= 60 -> swap.
    assert out is not None
    assert out.uci() == "d8d7", f"expected d8d7, got {out.uci()}"


def test_tiebreak_holds_at_zero_window():
    board = _board(GAME2_PLY24_FEN)
    out = threat_response_tiebreak(
        board, _move("a7a6"),
        score_move=_scores_g2_ply24,
        max_gap_cp=0,
    )
    # 20 > 0 -> don't swap.
    assert out == _move("a7a6")


def test_tiebreak_holds_when_chosen_neutralizes():
    board = _board(GAME2_PLY24_FEN)
    # Bishop retreat already neutralizes.
    out = threat_response_tiebreak(
        board, _move("e6d7"),
        score_move=_scores_g2_ply24,
        max_gap_cp=60,
    )
    assert out == _move("e6d7")


def test_tiebreak_holds_in_calm_position():
    # No threat -> filter returns chosen unchanged.
    board = chess.Board()
    out = threat_response_tiebreak(
        board, _move("e2e4"),
        score_move=lambda m: 0.0,
        max_gap_cp=60,
    )
    assert out == _move("e2e4")


# Test 6 — pre-existing threat detector signature contract.
# Confirms PreExistingThreat fields are filled correctly for the canonical case.

def test_threat_record_shape():
    board = _board(GAME2_PLY24_FEN)
    threats = find_pre_existing_threats(board, max_threats=4, min_see_cp=250)
    top = threats[0]
    assert isinstance(top, PreExistingThreat)
    assert top.kind in {"capture", "capture_check"}
    assert top.victim_square == top.target_square
    assert isinstance(top.gives_check, bool)
    assert isinstance(top.see_cp, int)
