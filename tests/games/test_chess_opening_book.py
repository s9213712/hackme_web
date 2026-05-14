"""Tests for the static chess opening book (P2).

The book is purely additive — it must not crash on any legal position and
must always return a move that is legal at the current side-to-move.
"""

import random

import chess
import pytest

from services.games.chess import initial_board, to_chess_board, validate_move
from services.games.chess_opening_book import (
    book_move,
    book_size,
    has_position,
)


def _apply_uci(board_dict, uci, side):
    """Apply a UCI move to the route-layer dict board and return the new dict."""
    move = chess.Move.from_uci(uci)
    from_sq = chess.square_name(move.from_square)
    to_sq = chess.square_name(move.to_square)
    promotion = None
    if move.promotion:
        promo_map = {chess.QUEEN: "q", chess.ROOK: "r", chess.BISHOP: "b", chess.KNIGHT: "n"}
        promotion = promo_map[move.promotion]
    result = validate_move(board_dict, side, from_sq, to_sq, promotion)
    return result["board"]


def test_book_has_entries():
    assert book_size() >= 40, "book should cover at least 40 positions"


def test_book_returns_move_for_starting_position():
    move = book_move(initial_board(), "white", rng=random.Random(0))
    assert move is not None
    assert move["from"] in {"e2", "d2", "c2", "g1", "b2"}, move
    assert move["piece"] in {"P", "N"}


def test_book_returns_move_for_e4_response():
    board = initial_board()
    board = _apply_uci(board, "e2e4", "white")
    move = book_move(board, "black", rng=random.Random(0))
    assert move is not None
    # Any of the main responses we encoded.
    assert (move["from"], move["to"]) in {
        ("e7", "e5"),
        ("c7", "c5"),
        ("e7", "e6"),
        ("c7", "c6"),
        ("d7", "d5"),
        ("d7", "d6"),
        ("g7", "g6"),
        ("g8", "f6"),
    }, move


def test_book_does_not_play_a5_against_e4():
    """The reason this book exists: stop ``e4 a5`` style answers."""
    rng = random.Random(0)
    board = initial_board()
    board = _apply_uci(board, "e2e4", "white")
    for _ in range(50):
        move = book_move(board, "black", rng=rng)
        assert move is not None
        assert not (move["from"] == "a7" and move["to"] == "a5"), \
            "book should never play a5 against e4"


def test_book_returns_none_when_out_of_book():
    """After a deliberately weird opening sequence the book should miss
    cleanly (return None) instead of guessing or crashing."""
    board = initial_board()
    # 1.h4 a5 — a sequence not in any opening line.
    board = _apply_uci(board, "h2h4", "white")
    board = _apply_uci(board, "a7a5", "black")
    move = book_move(board, "white")
    assert move is None
    assert has_position(board, "white") is False


def test_every_book_move_is_legal_in_its_position():
    """For each position in the book, the recommended move must be legal."""
    from services.games.chess_opening_book import _BOOK
    for epd, entries in _BOOK.items():
        board = chess.Board(epd + " 0 1")
        legal = {m.uci() for m in board.legal_moves}
        for _weight, uci in entries:
            assert uci in legal, f"illegal book move {uci} at {epd}"


def test_book_handles_invalid_inputs_without_crashing():
    assert book_move(None, "white") is None
    assert book_move({}, "white") is None
    assert book_move(initial_board(), "purple") is None


def test_book_move_is_deterministic_with_seeded_rng():
    rng_a = random.Random(42)
    rng_b = random.Random(42)
    board = initial_board()
    assert book_move(board, "white", rng=rng_a) == book_move(board, "white", rng=rng_b)


def test_book_covers_both_sides_after_d4():
    """Both 1.d4 (white's perspective is in book) and the position after 1.d4
    (black's perspective) should be in book."""
    start = initial_board()
    assert has_position(start, "white")
    after_d4 = _apply_uci(start, "d2d4", "white")
    assert has_position(after_d4, "black")
