"""Pre-existing threat detector for the V29r diagnostic / ordering / guard.

The hypothesis under test: V28e's existing guards check
"can my newly-moved piece be captured" (``tactical_safety_report``,
restricted to the moved piece's destination square) and "what is the
opponent's best capture worth in raw material after my move"
(``_worst_immediate_reply_material_margin``, capture-only with no
recapture accounting). Neither of them answers "did my move address a
threat the opponent had already set up BEFORE I moved" — the
canonical example from staged game 2 ply 24 is the engine playing
``a7a6`` while ignoring the standing ``Ng5xe6`` threat on the black
bishop.

This module exposes:

- ``PreExistingThreat`` — a typed record of one opponent move that
  would win material via static exchange evaluation if the side to
  move passed.
- ``find_pre_existing_threats(board, ...)`` — enumerate up to N such
  threats, sorted by SEE descending.
- ``neutralizes_threat(board, candidate, threat, ...)`` — does
  ``candidate`` remove the threat outright, or reduce its SEE below a
  small residual?

This is intentionally a thin detector, not a search. It is meant to
feed a root-level diagnostic first, then later an ordering bonus, and
only as a last resort a hard override gate. See ``chess_nnue``'s V29r
profiles for the wiring.

The two import-time dependencies on ``chess_nnue`` (``_static_exchange_eval``)
are lazily resolved inside the function bodies to avoid a circular
import at module load.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import chess


@dataclass(slots=True)
class PreExistingThreat:
    move: chess.Move
    see_cp: int
    kind: str
    victim_square: Optional[int]
    target_square: Optional[int]
    gives_check: bool


_KIND_CAPTURE = "capture"
_KIND_CAPTURE_CHECK = "capture_check"


def find_pre_existing_threats(
    board: chess.Board,
    *,
    max_threats: int = 4,
    min_see_cp: int = 250,
) -> list[PreExistingThreat]:
    """Return up to ``max_threats`` opponent capture moves whose static
    exchange evaluation from the opponent's side is at least
    ``min_see_cp``, sorted by SEE descending.

    Detection uses a null-move trick to flip the side to move. If the
    current side is already in check, returns an empty list — in-check
    positions are handled by other forcing-move logic and threat guard
    is not the right tool.

    Detection is deliberately conservative: capture moves only (no
    quiet attack-only threats, no fork pattern detection, no
    mate-net detection). Those are out of scope for the first cut and
    can be layered on once the capture-threat detector is proven by
    diagnostic logs.
    """
    if board.is_check():
        return []
    after_null = board.copy(stack=False)
    try:
        after_null.push(chess.Move.null())
    except Exception:
        return []

    from services.games.chess_nnue import _static_exchange_eval

    threshold = max(0, int(min_see_cp))
    found: list[PreExistingThreat] = []
    for move in after_null.legal_moves:
        if not after_null.is_capture(move):
            continue
        see = _static_exchange_eval(after_null, move)
        if see < threshold:
            continue
        gives_check = after_null.gives_check(move)
        kind = _KIND_CAPTURE_CHECK if gives_check else _KIND_CAPTURE
        found.append(
            PreExistingThreat(
                move=move,
                see_cp=int(see),
                kind=kind,
                victim_square=move.to_square,
                target_square=move.to_square,
                gives_check=gives_check,
            )
        )

    found.sort(key=lambda t: (-t.see_cp, t.move.uci()))
    cap = max(1, int(max_threats or 4))
    return found[:cap]


def neutralizes_threat(
    board: chess.Board,
    candidate: chess.Move,
    threat: PreExistingThreat,
    *,
    max_residual_see_cp: int = 100,
) -> bool:
    """Does ``candidate`` make ``threat`` no longer viable for opponent?

    A candidate neutralizes when either:
    - the threat move is no longer legal after the candidate is played
      (we captured the threatening piece, moved the victim, blocked
      the line, etc.); or
    - the threat move is still legal but its SEE after the candidate
      has dropped to ``max_residual_see_cp`` or less (e.g., the
      victim is now defended so the trade is roughly equal).
    """
    from services.games.chess_nnue import _static_exchange_eval

    residual_cap = int(max_residual_see_cp)
    board.push(candidate)
    try:
        if threat.move not in board.legal_moves:
            return True
        residual = _static_exchange_eval(board, threat.move)
        return residual <= residual_cap
    finally:
        board.pop()


def threat_response_tiebreak(
    board: chess.Board,
    chosen_move: chess.Move | None,
    *,
    score_move,
    max_gap_cp: int = 60,
    min_see_cp: int = 250,
    max_residual_see_cp: int = 100,
) -> chess.Move | None:
    """Tie-break the chosen move against a neutralizing alternative.

    Fires only when ALL of these hold:
    - a pre-existing opponent capture threat with SEE >= ``min_see_cp``
      exists in the current position;
    - ``chosen_move`` does not neutralize the top threat;
    - some legal move does neutralize it;
    - the chosen move's search-score advantage over the best
      neutralizer is at most ``max_gap_cp`` — i.e., the swap costs at
      most a small positional bonus.

    The asymmetric window (only ``0 <= gap <= max_gap_cp``) means: when
    the search already prefers the neutralizer (gap < 0) we keep the
    chosen pick, because the divergence is being driven by a filter
    later in the chain that has its own reason. When the search
    massively prefers the chosen pick (gap > max_gap_cp) we keep it
    too, on the assumption the engine has identified a stronger
    tactical reason to ignore the threat. This narrow band is by
    design: it should fire on canonical "blunder ignoring a threat"
    cases like staged game-2 ply-24 (a7a6 with gap=20cp to d8d7) while
    leaving baseline draw-cycle behavior untouched everywhere else.
    """
    if chosen_move is None:
        return chosen_move
    threats = find_pre_existing_threats(board, min_see_cp=min_see_cp, max_threats=4)
    if not threats:
        return chosen_move
    top = threats[0]
    if neutralizes_threat(board, chosen_move, top, max_residual_see_cp=max_residual_see_cp):
        return chosen_move
    try:
        chosen_score = float(score_move(chosen_move))
    except Exception:
        return chosen_move
    best_neut: chess.Move | None = None
    best_neut_score: float | None = None
    for candidate in board.legal_moves:
        if candidate == chosen_move:
            continue
        if not neutralizes_threat(board, candidate, top, max_residual_see_cp=max_residual_see_cp):
            continue
        try:
            cs = float(score_move(candidate))
        except Exception:
            continue
        if best_neut_score is None or cs > best_neut_score:
            best_neut_score = cs
            best_neut = candidate
    if best_neut is None or best_neut_score is None:
        return chosen_move
    gap = chosen_score - best_neut_score
    if 0.0 <= gap <= float(max_gap_cp):
        return best_neut
    return chosen_move
