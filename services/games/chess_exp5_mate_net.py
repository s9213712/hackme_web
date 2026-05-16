"""Mate-net helpers extracted from ``chess_nnue``.

This module hosts the bounded forced-mate / mate-net detectors used by the
Exp5 engine:

- ``_opponent_mate_in_one_moves`` — list opponent replies that mate immediately.
- ``_forced_single_reply_mate_net_move`` — short forcing-net hook.
- ``_forced_mate_in_two_priority_move`` — conservative mate-in-2 in simple
  positions.
- ``_forced_checking_mate_priority_move`` — bounded checking-only mate search.
- ``_has_bounded_opponent_forced_mate`` — wrapper used by post-search filters.
- ``_avoid_opponent_forced_mate_net_filter`` — post-search guard against
  walking into a bounded mate net.
- ``_low_legal_check_escape_filter`` — final narrow guard for low-legal
  check evasions, including the V28e fast-king-mobility4 branch.

The original extraction was behavior-preserving. A second pass introduces
``MateNetContext`` so multiple ``_has_bounded_opponent_forced_mate`` queries
inside one post-search filter share a single Zobrist-keyed memo and a single
set of counters. The default-None contract on the ``ctx`` keyword preserves
the original per-call semantics for any caller that does not opt in.

A third pass adds ``_is_critical_root_position`` plus opt-in
``critical_widen=True`` kwargs on the two filters that consume the
mate-net detector. The critical-position trigger and the widened
``max_root_checks`` are not enabled by the V28e production profile; they
are framework only, to be wired in by a future experiment after promotion
gating.

Helpers shared with ``chess_nnue`` (``_would_stalemate``,
``_move_order_score``, ``_captured_piece_value``,
``_material_margin_for_color``, ``_worst_immediate_reply_material_margin``,
``_promotion_priority``) are imported lazily inside each entry point to
avoid a circular import at module load time.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import chess

from services.games.chess_search import ZobristHasher


_MATE_IN_TWO_MAX_PIECES = 12
_MATE_IN_TWO_MAX_LEGAL_MOVES = 45
_MATE_IN_TWO_MAX_REPLIES = 45

# Default widened ``max_root_checks`` used when a caller opts in to
# ``critical_widen=True`` and the position passes
# ``_is_critical_root_position``. Kept here as a single source of truth so a
# future experiment that wires this into a search profile only changes one
# value.
_CRITICAL_WIDEN_MAX_ROOT_CHECKS = 12


@dataclass
class MateNetContext:
    """Shared memo + counters across mate-net queries from one root call.

    The original ``_forced_checking_mate_priority_move`` allocated a fresh
    ``{(fen, depth, turn): bool}`` memo per call and serialized the position
    to FEN inside the recursion. This context replaces that with a
    Zobrist-keyed memo that can be reused across multiple queries issued by
    the same filter (e.g. the chosen-move check plus ``scan_limit``
    alternatives in ``_avoid_opponent_forced_mate_net_filter``).

    Each call still enforces its own ``max_nodes`` budget with a local
    counter — only the memo and the cumulative reporting counters are
    shared. That preserves the original per-call budget semantics: a memo
    hit avoids re-walking a subtree, but the ``max_nodes`` cap remains.

    Counters give a promotion-gate harness a way to distinguish "this
    candidate regressed because we ran out of nodes" from "we never even
    tried because the root trigger gated us out".
    """

    hasher: ZobristHasher = field(default_factory=ZobristHasher)
    # Key: (zobrist_hash, depth, attacker_color_is_white).
    # ``attacker`` must be part of the key — the same position can be
    # queried by different filters with different attackers in principle,
    # and the answer ("can this attacker mate in ``depth``") differs.
    memo: dict[tuple[int, int, bool], bool] = field(default_factory=dict)
    nodes: int = 0
    memo_hits: int = 0
    memo_misses: int = 0
    root_checking_moves_seen: int = 0
    root_checking_moves_scanned: int = 0
    budget_cutoffs: int = 0


def _is_critical_root_position(
    board: chess.Board,
    *,
    min_opponent_checks: int = 2,
    max_own_legal_after_check: int = 8,
    preview_check_limit: int = 5,
) -> bool:
    """Heuristic: is this a tactically dangerous root for mate-net widening?

    Called on a position where the opponent is to move. Returns True when
    the opponent has at least ``min_opponent_checks`` checking moves and
    at least one of those checks leaves us with at most
    ``max_own_legal_after_check`` legal replies. The cap on previewed
    checks keeps the cost O(few × push/pop) rather than O(all_checks).

    This is the cheap "is the cheap mate-net helper at risk of dropping a
    real mate net here?" trigger. It is intentionally opt-in: V28e profile
    does not call any filter with ``critical_widen=True``, so default
    engine behavior is unchanged.
    """
    opponent_checks: list[chess.Move] = []
    for move in board.legal_moves:
        if board.gives_check(move):
            opponent_checks.append(move)
            if len(opponent_checks) >= max(min_opponent_checks, preview_check_limit):
                break
    if len(opponent_checks) < int(min_opponent_checks or 2):
        return False
    cap = max(1, int(preview_check_limit or 5))
    for check_move in opponent_checks[:cap]:
        next_board = board.copy(stack=False)
        next_board.push(check_move)
        if next_board.legal_moves.count() <= int(max_own_legal_after_check or 8):
            return True
    return False


def _opponent_mate_in_one_moves(board: chess.Board) -> list[chess.Move]:
    mates: list[chess.Move] = []
    for reply in board.legal_moves:
        after = board.copy(stack=False)
        after.push(reply)
        if after.is_checkmate():
            mates.append(reply)
    return mates


def _forced_single_reply_mate_net_move(board: chess.Board) -> chess.Move | None:
    """Find a checking move where the only legal reply allows mate in one."""
    from services.games.chess_nnue import (
        _would_stalemate,
        _move_order_score,
        _captured_piece_value,
    )

    if board.legal_moves.count() > 90:
        return None
    candidates: list[tuple[int, int, str, chess.Move]] = []
    for move in board.legal_moves:
        if not board.gives_check(move) or _would_stalemate(board, move):
            continue
        after = board.copy(stack=False)
        after.push(move)
        if after.is_checkmate() or after.is_stalemate():
            continue
        replies = list(after.legal_moves)
        if len(replies) != 1:
            continue
        reply_board = after.copy(stack=False)
        reply_board.push(replies[0])
        mate_replies = _opponent_mate_in_one_moves(reply_board)
        if not mate_replies:
            continue
        candidates.append((
            _move_order_score(board, move),
            _captured_piece_value(board, move),
            move.uci(),
            move,
        ))
    if not candidates:
        return None
    return sorted(candidates, reverse=True)[0][3]


def _forced_mate_in_two_priority_move(
    board: chess.Board,
    *,
    max_pieces: int = _MATE_IN_TWO_MAX_PIECES,
    max_legal_moves: int = _MATE_IN_TWO_MAX_LEGAL_MOVES,
    max_replies: int = _MATE_IN_TWO_MAX_REPLIES,
    min_material_margin_cp: int = 0,
) -> chess.Move | None:
    """Find a conservative forced mate-in-two move in simplified positions.

    This is deliberately bounded to low-material or otherwise small legal-move
    spaces. Exp5's default live profile is shallow, so this fills an important
    human-visible gap in simple endgames without adding a broad expensive
    tactical solver to every middlegame move.
    """
    from services.games.chess_nnue import (
        _material_margin_for_color,
        _move_order_score,
        _captured_piece_value,
    )

    if len(board.piece_map()) > int(max_pieces or _MATE_IN_TWO_MAX_PIECES):
        return None
    if int(min_material_margin_cp or 0) > 0 and _material_margin_for_color(board, board.turn) < int(min_material_margin_cp):
        return None
    legal_moves = sorted(board.legal_moves, key=lambda item: item.uci())
    if not legal_moves or len(legal_moves) > int(max_legal_moves or _MATE_IN_TWO_MAX_LEGAL_MOVES):
        return None

    candidates: list[chess.Move] = []
    for move in legal_moves:
        after = board.copy(stack=False)
        after.push(move)
        if after.is_checkmate() or after.is_stalemate():
            continue
        replies = list(after.legal_moves)
        if not replies or len(replies) > int(max_replies or _MATE_IN_TWO_MAX_REPLIES):
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


def _forced_checking_mate_priority_move(
    board: chess.Board,
    *,
    max_depth_plies: int = 7,
    max_pieces: int = 18,
    max_legal_moves: int = 70,
    min_material_margin_cp: int = 700,
    max_nodes: int = 30_000,
    max_root_checks: int = 5,
    ctx: MateNetContext | None = None,
) -> chess.Move | None:
    """Find a bounded checking sequence that forces mate.

    This is a tail/endgame helper, not a full tactical search. It only considers
    checking attacker moves, then requires every defender reply to remain inside
    the forced mate tree. That keeps the search small and avoids changing quiet
    middlegame choices.

    When ``ctx`` is provided, the recursion's memo and the reporting counters
    are taken from the shared context, so repeated queries from the same
    filter (e.g. chosen-move check + scan_limit alternatives in
    ``_avoid_opponent_forced_mate_net_filter``) can reuse work. Each call
    still keeps its own ``max_nodes`` budget via a local counter; the
    context only stores cumulative totals.

    When ``ctx`` is None, a private context is created for this call —
    behavior is byte-identical to the pre-context implementation (per-call
    fresh memo, per-call private budget), only with the memo key switched
    from ``(fen, depth, turn)`` to ``(zobrist_hash, depth, attacker)``.
    """
    from services.games.chess_nnue import (
        _material_margin_for_color,
        _promotion_priority,
        _captured_piece_value,
        _move_order_score,
    )

    if len(board.piece_map()) > int(max_pieces or 18):
        return None
    legal_count = board.legal_moves.count()
    if legal_count <= 0 or legal_count > int(max_legal_moves or 70):
        return None
    if _material_margin_for_color(board, board.turn) < int(min_material_margin_cp or 0):
        return None

    attacker = board.turn
    max_depth_plies = max(1, int(max_depth_plies or 1))
    max_nodes_budget = max(1000, int(max_nodes or 30_000))
    if ctx is None:
        ctx = MateNetContext()
    memo = ctx.memo
    hasher = ctx.hasher
    nodes = 0  # local budget counter — preserves original per-call budget

    def checking_moves(current: chess.Board) -> list[chess.Move]:
        moves = [move for move in current.legal_moves if current.gives_check(move)]
        return sorted(
            moves,
            key=lambda move: (
                current.is_capture(move),
                bool(move.promotion),
                _promotion_priority(move),
                _captured_piece_value(current, move),
                _move_order_score(current, move),
                move.uci(),
            ),
            reverse=True,
        )

    def can_force(current: chess.Board, depth: int) -> bool:
        nonlocal nodes
        nodes += 1
        ctx.nodes += 1
        if nodes > max_nodes_budget:
            ctx.budget_cutoffs += 1
            return False
        if current.is_checkmate():
            return current.turn != attacker
        if current.is_stalemate() or depth <= 0:
            return False
        key = (hasher.hash_board(current), depth, attacker == chess.WHITE)
        cached = memo.get(key)
        if cached is not None:
            ctx.memo_hits += 1
            return cached
        ctx.memo_misses += 1
        if current.turn == attacker:
            for move in checking_moves(current):
                current.push(move)
                ok = can_force(current, depth - 1)
                current.pop()
                if ok:
                    memo[key] = True
                    return True
            memo[key] = False
            return False

        replies = list(current.legal_moves)
        if not replies or len(replies) > int(max_legal_moves or 70):
            memo[key] = False
            return False
        for reply in replies:
            current.push(reply)
            ok = can_force(current, depth - 1)
            current.pop()
            if not ok:
                memo[key] = False
                return False
        memo[key] = True
        return True

    root_checks = checking_moves(board)
    ctx.root_checking_moves_seen += len(root_checks)
    if not root_checks or len(root_checks) > int(max_root_checks or 5):
        return None
    ctx.root_checking_moves_scanned += len(root_checks)
    candidates: list[chess.Move] = []
    for move in root_checks:
        board.push(move)
        ok = can_force(board, max_depth_plies - 1)
        board.pop()
        if ok:
            candidates.append(move)
    if not candidates:
        return None
    return sorted(
        candidates,
        key=lambda move: (
            board.is_capture(move),
            bool(move.promotion),
            _promotion_priority(move),
            _captured_piece_value(board, move),
            _move_order_score(board, move),
            move.uci(),
        ),
        reverse=True,
    )[0]


def _has_bounded_opponent_forced_mate(
    board: chess.Board,
    *,
    max_depth_plies: int,
    max_pieces: int,
    max_nodes: int,
    ctx: MateNetContext | None = None,
    max_root_checks: int = 6,
) -> bool:
    return (
        _forced_checking_mate_priority_move(
            board,
            max_depth_plies=max_depth_plies,
            max_pieces=max_pieces,
            max_legal_moves=70,
            min_material_margin_cp=-3000,
            max_nodes=max_nodes,
            max_root_checks=max_root_checks,
            ctx=ctx,
        )
        is not None
    )


def _avoid_opponent_forced_mate_net_filter(
    board: chess.Board,
    move: chess.Move | None,
    *,
    side: str,
    score_move,
    max_depth_plies: int = 7,
    max_pieces: int = 30,
    max_nodes: int = 12_000,
    scan_limit: int = 16,
    critical_widen: bool = False,
    ctx: MateNetContext | None = None,
) -> chess.Move | None:
    """Avoid candidate moves that allow a bounded checking forced mate.

    This is deliberately narrower than a general tactical solver: it first
    tests only the already selected move. Alternative scanning happens only if
    that move fails the bounded mate-net check.

    All ``_has_bounded_opponent_forced_mate`` queries in this call share a
    single ``MateNetContext`` (created here when none is supplied) so the
    chosen-move check and the up-to-``scan_limit`` alternative checks reuse
    one Zobrist-keyed memo and one set of counters. Each query still
    enforces its own ``max_nodes`` budget.

    ``critical_widen``: opt-in. When True and the post-move position passes
    ``_is_critical_root_position``, the bounded mate-net detector runs with
    ``max_root_checks = _CRITICAL_WIDEN_MAX_ROOT_CHECKS`` (default 12)
    instead of the conservative 6. V28e does not pass this flag; it exists
    so a future experiment can flip the trigger after promotion gating.
    """
    from services.games.chess_nnue import (
        _would_stalemate,
        _worst_immediate_reply_material_margin,
        _material_margin_for_color,
    )

    if move is None:
        return None
    if len(board.piece_map()) > int(max_pieces or 30) or board.legal_moves.count() > 70:
        return move
    color = chess.WHITE if str(side or "white").lower() == "white" else chess.BLACK
    if ctx is None:
        ctx = MateNetContext()
    after = board.copy(stack=False)
    after.push(move)
    if after.is_checkmate() or after.is_stalemate():
        return move

    def _root_checks_for(post_move_board: chess.Board) -> int:
        if critical_widen and _is_critical_root_position(post_move_board):
            return _CRITICAL_WIDEN_MAX_ROOT_CHECKS
        return 6

    if not _has_bounded_opponent_forced_mate(
        after,
        max_depth_plies=max_depth_plies,
        max_pieces=max_pieces,
        max_nodes=max_nodes,
        ctx=ctx,
        max_root_checks=_root_checks_for(after),
    ):
        return move

    chosen_score = float(score_move(move))
    candidates: list[tuple[float, int, str, chess.Move]] = []
    ordered = sorted(
        [candidate for candidate in board.legal_moves if candidate != move],
        key=lambda candidate: (float(score_move(candidate)), candidate.uci()),
        reverse=True,
    )[: max(1, int(scan_limit or 16))]
    for candidate in ordered:
        if _would_stalemate(board, candidate):
            continue
        candidate_after = board.copy(stack=False)
        candidate_after.push(candidate)
        if candidate_after.is_checkmate():
            return candidate
        if _opponent_mate_in_one_moves(candidate_after):
            continue
        if _has_bounded_opponent_forced_mate(
            candidate_after,
            max_depth_plies=max_depth_plies,
            max_pieces=max_pieces,
            max_nodes=max_nodes,
            ctx=ctx,
            max_root_checks=_root_checks_for(candidate_after),
        ):
            continue
        floor = _worst_immediate_reply_material_margin(candidate_after, color)
        candidate_score = float(score_move(candidate))
        if candidate_score < chosen_score - 1800.0 and floor < _material_margin_for_color(board, color) - 900:
            continue
        candidates.append((candidate_score, floor, candidate.uci(), candidate))
    if not candidates:
        return move
    return sorted(candidates, reverse=True)[0][3]


def _low_legal_check_escape_filter(
    board: chess.Board,
    move: chess.Move | None,
    *,
    side: str,
    score_move,
    max_legal: int = 4,
    max_pieces: int = 30,
    max_depth_plies: int = 7,
    max_nodes: int = 12_000,
    enable_king_mobility4: bool = False,
    critical_widen: bool = False,
    ctx: MateNetContext | None = None,
) -> chess.Move | None:
    """Final narrow guard for low-legal check evasions.

    Earlier post-search filters may replace a safe search result. This guard
    only runs in check with very few legal moves, where scanning every evasion
    is cheap and avoids obvious forced-mate funnels.

    All ``_has_bounded_opponent_forced_mate`` queries (one per scored
    candidate, up to ``max_legal``) share a single ``MateNetContext`` so
    the candidate scoring loop reuses memo entries from earlier candidates.
    See ``_avoid_opponent_forced_mate_net_filter`` for the ``critical_widen``
    contract.
    """
    from services.games.chess_nnue import _captured_piece_value

    if move is None or not board.is_check():
        return move
    legal_moves = list(board.legal_moves)
    if len(legal_moves) <= 1 or len(legal_moves) > int(max_legal or 4):
        return move
    if len(board.piece_map()) > int(max_pieces or 30):
        return move
    color = chess.WHITE if str(side or "white").lower() == "white" else chess.BLACK

    def king_edge_distance(after: chess.Board) -> int:
        square = after.king(color)
        if square is None:
            return 0
        file_index = chess.square_file(square)
        rank_index = chess.square_rank(square)
        return min(file_index, 7 - file_index, rank_index, 7 - rank_index)

    risk_cache: dict[str, tuple[bool, bool]] = {}
    depth_limit = max(0, int(max_depth_plies if max_depth_plies is not None else 7))
    node_limit = max(0, int(max_nodes if max_nodes is not None else 12_000))
    if ctx is None:
        ctx = MateNetContext()

    def candidate_risk(candidate: chess.Move) -> tuple[bool, bool]:
        uci = candidate.uci()
        cached = risk_cache.get(uci)
        if cached is not None:
            return cached
        after = board.copy(stack=False)
        after.push(candidate)
        mate_in_one = not after.is_checkmate() and bool(_opponent_mate_in_one_moves(after))
        forced_mate = False
        if not mate_in_one and depth_limit > 0 and node_limit > 0:
            root_checks_cap = 6
            if critical_widen and _is_critical_root_position(after):
                root_checks_cap = _CRITICAL_WIDEN_MAX_ROOT_CHECKS
            forced_mate = _has_bounded_opponent_forced_mate(
                after,
                max_depth_plies=depth_limit,
                max_pieces=int(max_pieces or 30),
                max_nodes=node_limit,
                ctx=ctx,
                max_root_checks=root_checks_cap,
            )
        risk_cache[uci] = (mate_in_one, forced_mate)
        return risk_cache[uci]

    def candidate_tuple(candidate: chess.Move) -> tuple[int, float, str, chess.Move]:
        after = board.copy(stack=False)
        after.push(candidate)
        if after.is_checkmate():
            return (10_000_000, float(score_move(candidate)), candidate.uci(), candidate)
        mate_in_one, forced_mate = candidate_risk(candidate)
        moving_piece = board.piece_at(candidate.from_square)
        is_king_move = bool(moving_piece and moving_piece.piece_type == chess.KING)
        opponent_check_count = sum(1 for reply in after.legal_moves if after.gives_check(reply))
        score = 0
        if mate_in_one:
            score -= 1_000_000
        if forced_mate:
            score -= 250_000
        score += king_edge_distance(after) * 900
        score -= opponent_check_count * 35
        if is_king_move and king_edge_distance(after) == 0:
            score -= 700
        if not is_king_move:
            score += 450
        if board.is_capture(candidate):
            score += min(900, _captured_piece_value(board, candidate))
        if candidate.promotion:
            score += 1200
        score += int(max(-5000.0, min(5000.0, float(score_move(candidate)))))
        return (score, float(score_move(candidate)), candidate.uci(), candidate)

    chosen_mate_in_one, chosen_forced_mate = candidate_risk(move)
    if not chosen_mate_in_one and not chosen_forced_mate:
        if not bool(enable_king_mobility4) or len(legal_moves) != 4:
            return move
        chosen_piece = board.piece_at(move.from_square)
        if not chosen_piece or chosen_piece.piece_type != chess.KING:
            return move
        chosen_after = board.copy(stack=False)
        chosen_after.push(move)
        if king_edge_distance(chosen_after) != 0:
            return move
        chosen_score = candidate_tuple(move)[0]
        king_candidates: list[tuple[int, float, str, chess.Move]] = []
        for candidate in legal_moves:
            if candidate == move:
                continue
            moving_piece = board.piece_at(candidate.from_square)
            if not moving_piece or moving_piece.piece_type != chess.KING:
                continue
            after = board.copy(stack=False)
            after.push(candidate)
            if king_edge_distance(after) <= 0:
                continue
            mate_in_one, forced_mate = candidate_risk(candidate)
            if mate_in_one or forced_mate:
                continue
            score = candidate_tuple(candidate)[0]
            king_candidates.append((score, float(score_move(candidate)), candidate.uci(), candidate))
        if not king_candidates:
            return move
        best_king = sorted(king_candidates, reverse=True)[0]
        if best_king[0] <= chosen_score + 250:
            return move
        return best_king[3]

    chosen = candidate_tuple(move)
    chosen_score = chosen[0]
    candidates = [candidate_tuple(candidate) for candidate in legal_moves]
    best = sorted(candidates, reverse=True)[0]
    if best[3] == move:
        return move
    if best[0] <= chosen_score + 650:
        return move
    return best[3]
