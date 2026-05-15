"""Tiny static opening book for chess practice games (P2).

This module is intentionally **additive**: it does not modify any of the
existing engine files (``chess_engine.py``, ``chess_nn.py``, ``chess_dl.py``,
``chess_pv.py``, ``chess_nnue.py`` or anything under ``services/games/models/``)
because there is active research work in flight on those. Instead, the route
layer in ``routes/games.py`` consults this book first; only on a miss does it
fall through to the existing engine choices.

Design choices:

- Keyed by EPD (FEN piece-placement + side-to-move + castling + en passant),
  which is stable across half-move / full-move counters.
- Lines covered: the most common 1-4 ply main-line responses to ``1.e4`` and
  ``1.d4`` plus a handful of flank openings. Roughly 60 positions — enough to
  stop the engine from playing ``a5`` against ``e4`` while staying small.
- Each entry is ``(weight, uci)`` so the book can prefer the main line but
  still play side variations for variety.
- ``book_move`` accepts the route-layer board dict and a ``side`` string and
  returns a move dict shaped like ``choose_computer_move`` consumers expect.
"""

from __future__ import annotations

import random
from typing import Optional, Tuple

import chess

from services.games.chess import to_chess_board


# Each top-level entry is a list of opening lines. Each line is a list of
# UCI moves played in order from the starting position. The book builder
# walks each line, expanding the table with every reachable position and
# the move that line plays from that position.
_LINES: Tuple[Tuple[str, ...], ...] = (
    # --- 1.e4 e5 (Open Game) ---
    ("e2e4", "e7e5"),
    ("e2e4", "e7e5", "g1f3", "b8c6"),
    ("e2e4", "e7e5", "g1f3", "b8c6", "f1b5", "a7a6"),     # Ruy Lopez main
    ("e2e4", "e7e5", "g1f3", "b8c6", "f1b5", "g8f6"),     # Berlin
    ("e2e4", "e7e5", "g1f3", "b8c6", "f1c4", "g8f6"),     # Italian / Two Knights
    ("e2e4", "e7e5", "g1f3", "b8c6", "f1c4", "f8c5"),     # Giuoco
    ("e2e4", "e7e5", "g1f3", "g8f6"),                     # Petroff
    ("e2e4", "e7e5", "f2f4"),                             # King's Gambit accepted line: drop here, then go on if accepted

    # --- 1.e4 c5 (Sicilian) ---
    ("e2e4", "c7c5"),
    ("e2e4", "c7c5", "g1f3"),
    ("e2e4", "c7c5", "g1f3", "d7d6"),                     # Najdorf prep
    ("e2e4", "c7c5", "g1f3", "d7d6", "d2d4", "c5d4"),
    ("e2e4", "c7c5", "g1f3", "b8c6"),                     # Open Sicilian
    ("e2e4", "c7c5", "g1f3", "b8c6", "d2d4", "c5d4"),
    ("e2e4", "c7c5", "g1f3", "e7e6"),                     # Taimanov / Kan
    ("e2e4", "c7c5", "g1f3", "g7g6"),                     # Hyper-accelerated
    ("e2e4", "c7c5", "b1c3"),                             # Closed Sicilian

    # --- 1.e4 e6 (French) ---
    ("e2e4", "e7e6"),
    ("e2e4", "e7e6", "d2d4", "d7d5"),
    ("e2e4", "e7e6", "d2d4", "d7d5", "b1c3", "g8f6"),     # Classical
    ("e2e4", "e7e6", "d2d4", "d7d5", "e4e5"),             # Advance
    ("e2e4", "e7e6", "d2d4", "d7d5", "e4d5", "e6d5"),     # Exchange

    # --- 1.e4 c6 (Caro-Kann) ---
    ("e2e4", "c7c6"),
    ("e2e4", "c7c6", "d2d4", "d7d5"),
    ("e2e4", "c7c6", "d2d4", "d7d5", "b1c3", "d5e4"),     # Classical / Main
    ("e2e4", "c7c6", "d2d4", "d7d5", "e4e5"),             # Advance

    # --- 1.e4 d5 (Scandinavian) ---
    ("e2e4", "d7d5"),
    ("e2e4", "d7d5", "e4d5", "d8d5"),
    ("e2e4", "d7d5", "e4d5", "g8f6"),                     # Modern Scandi
    ("e2e4", "d7d5", "e4d5", "d8d5", "b1c3", "d5a5"),

    # --- 1.e4 Nf6 (Alekhine) ---
    ("e2e4", "g8f6"),
    ("e2e4", "g8f6", "e4e5", "f6d5"),
    ("e2e4", "g8f6", "e4e5", "f6d5", "d2d4", "d7d6"),

    # --- 1.e4 d6 (Pirc) ---
    ("e2e4", "d7d6"),
    ("e2e4", "d7d6", "d2d4", "g8f6"),

    # --- 1.e4 g6 (Modern) ---
    ("e2e4", "g7g6"),
    ("e2e4", "g7g6", "d2d4", "f8g7"),

    # --- 1.d4 d5 (Queen's Pawn) ---
    ("d2d4", "d7d5"),
    ("d2d4", "d7d5", "c2c4"),                             # Queen's Gambit offered
    ("d2d4", "d7d5", "c2c4", "e7e6"),                     # QGD
    ("d2d4", "d7d5", "c2c4", "e7e6", "b1c3", "g8f6"),
    ("d2d4", "d7d5", "c2c4", "c7c6"),                     # Slav
    ("d2d4", "d7d5", "c2c4", "d5c4"),                     # QGA
    ("d2d4", "d7d5", "g1f3"),                             # Quiet system

    # --- 1.d4 Nf6 (Indian Defences) ---
    ("d2d4", "g8f6"),
    ("d2d4", "g8f6", "c2c4", "e7e6"),                     # Nimzo / QID setup
    ("d2d4", "g8f6", "c2c4", "g7g6"),                     # King's Indian / Grünfeld setup
    ("d2d4", "g8f6", "c2c4", "g7g6", "b1c3", "f8g7"),     # KID
    ("d2d4", "g8f6", "c2c4", "g7g6", "b1c3", "d7d5"),     # Grünfeld
    ("d2d4", "g8f6", "c2c4", "c7c5"),                     # Benoni
    ("d2d4", "g8f6", "g1f3"),

    # --- 1.d4 f5 (Dutch) ---
    ("d2d4", "f7f5"),
    ("d2d4", "f7f5", "c2c4", "g8f6"),

    # --- Flank openings: white side ---
    ("c2c4",),                                            # English
    ("c2c4", "e7e5"),
    ("c2c4", "g8f6"),
    ("c2c4", "c7c5"),
    ("g1f3",),                                            # Réti
    ("g1f3", "d7d5"),
    ("g1f3", "g8f6"),
    ("b2b3",),                                            # Larsen — okay sideline reply
)


def _expand(lines):
    table: dict[str, list[tuple[int, str]]] = {}
    for line in lines:
        board = chess.Board()
        for ply, uci in enumerate(line):
            try:
                move = chess.Move.from_uci(uci)
            except ValueError:
                break
            if move not in board.legal_moves:
                break
            # Only seed positions where the side-to-move is the one this line
            # is suggesting a move for. Skip the position-after-the-move; the
            # *next* iteration will record that position with the line's
            # follow-up move.
            key = board.epd()
            weight = 5 if ply == 0 else 3 if ply == 1 else 2
            bucket = table.setdefault(key, [])
            existing = next((i for i, item in enumerate(bucket) if item[1] == uci), None)
            if existing is None:
                bucket.append((weight, uci))
            else:
                old_weight, old_uci = bucket[existing]
                bucket[existing] = (old_weight + weight, old_uci)
            board.push(move)
    return table


_BOOK: dict[str, list[tuple[int, str]]] = _expand(_LINES)


def _board_to_chess(board_dict, side):
    """Convert the route-layer dict board to a python-chess board with the
    given side-to-move so EPD lookups are correct. ``to_chess_board``
    expects the colour as the ``"white"`` / ``"black"`` string."""
    return to_chess_board(board_dict, turn=side)


def _square_index_to_name(idx):
    return chess.square_name(idx)


def book_move(board_dict, side, *, rng: Optional[random.Random] = None):
    """Return a move dict from the book for ``board_dict`` (route format) or
    ``None`` if the position is out of book.

    Move dict shape matches what ``choose_computer_move`` returns:
        ``{"from": "e2", "to": "e4", "piece": "P", "promotion": <optional>}``
    """
    if not isinstance(board_dict, dict):
        return None
    if side not in ("white", "black"):
        return None
    try:
        board = _board_to_chess(board_dict, side)
    except Exception:
        return None
    if board is None or not isinstance(board, chess.Board):
        return None
    key = board.epd()
    entries = _BOOK.get(key)
    if not entries:
        return None
    # Filter to legal moves only (defensive).
    legal_uci = {m.uci() for m in board.legal_moves}
    candidates = [(w, uci) for w, uci in entries if uci in legal_uci]
    if not candidates:
        return None
    rng = rng or random
    total = sum(weight for weight, _uci in candidates)
    pick = rng.uniform(0, total)
    cumulative = 0.0
    chosen_uci = candidates[-1][1]
    for weight, uci in candidates:
        cumulative += weight
        if pick <= cumulative:
            chosen_uci = uci
            break
    move = chess.Move.from_uci(chosen_uci)
    from_sq = _square_index_to_name(move.from_square)
    to_sq = _square_index_to_name(move.to_square)
    piece = board.piece_at(move.from_square)
    if piece is None:
        return None
    piece_letter = piece.symbol()
    move_dict = {
        "from": from_sq,
        "to": to_sq,
        "piece": piece_letter,
    }
    if move.promotion:
        promo_map = {chess.QUEEN: "q", chess.ROOK: "r", chess.BISHOP: "b", chess.KNIGHT: "n"}
        promo_letter = promo_map.get(move.promotion, "q")
        move_dict["promotion"] = promo_letter.upper() if piece.color == chess.WHITE else promo_letter
    return move_dict


def book_size() -> int:
    """Number of distinct positions in the book — used by tests."""
    return len(_BOOK)


def book_candidates_for_chess_board(board: chess.Board, *, max_candidates: int = 5) -> list[dict]:
    """Return deterministic book candidates for an already-built board.

    Route-layer ``book_move`` intentionally uses weighted randomness for game
    variety. Engine evaluation and distillation need repeatability, so exp5
    calls this helper instead and receives legal UCI candidates sorted by book
    weight, then UCI.
    """
    if not isinstance(board, chess.Board):
        return []
    entries = _BOOK.get(board.epd())
    if not entries:
        return []
    legal = {move.uci(): move for move in board.legal_moves}
    candidates: list[dict] = []
    for weight, uci in entries:
        move = legal.get(str(uci))
        if move is None:
            continue
        candidates.append({
            "uci": move.uci(),
            "weight": int(weight),
            "move": move,
        })
    candidates.sort(key=lambda item: (-int(item["weight"]), str(item["uci"])))
    return candidates[: max(1, int(max_candidates or 1))]


def has_position(board_dict, side) -> bool:
    if not isinstance(board_dict, dict) or side not in ("white", "black"):
        return False
    try:
        board = _board_to_chess(board_dict, side)
    except Exception:
        return False
    return board is not None and board.epd() in _BOOK
