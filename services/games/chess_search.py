"""Shared chess search helpers for engine-style difficulties.

This module keeps the search stack reusable so ``teacher`` and ``experiment``
can evolve together instead of each carrying a slightly different negamax.
The first stage focuses on classic engine improvements that are cheap in
Python and materially improve tactical stability:

- iterative deepening
- aspiration windows
- zobrist-based transposition keys
- transposition table entries with bounds and best moves
- killer heuristic for non-capturing beta cutoffs
"""

from __future__ import annotations

from dataclasses import dataclass
import random
from time import perf_counter
from typing import Callable

import chess


_INFINITY = 10**9
_MATE_SCORE = 10**7
_TT_EXACT = "exact"
_TT_LOWER = "lower"
_TT_UPPER = "upper"
_KILLER_SLOTS = 2
_DEFAULT_ASPIRATION_WINDOW = 70
_DEFAULT_QUIESCENCE_DEPTH = 6
_DEFAULT_TT_MAX_ENTRIES = 50000
_HISTORY_MAX_BONUS = 200000
_ASPIRATION_MATE_MARGIN = 2000


@dataclass
class SearchStats:
    nodes: int = 0
    qnodes: int = 0
    tt_hits: int = 0
    tt_cutoffs: int = 0
    tt_stores: int = 0
    beta_cutoffs: int = 0
    history_updates: int = 0
    aspiration_retries: int = 0
    completed_depth: int = 0
    null_move_cutoffs: int = 0
    lmr_researches: int = 0
    futility_prunes: int = 0


@dataclass
class SearchResult:
    best_move: chess.Move | None
    score: int
    depth: int
    stats: SearchStats


@dataclass
class TTEntry:
    depth: int
    score: int
    flag: str
    best_move_uci: str | None


class TranspositionTable:
    def __init__(self, max_entries: int = _DEFAULT_TT_MAX_ENTRIES):
        self.max_entries = max(1000, int(max_entries or _DEFAULT_TT_MAX_ENTRIES))
        self._entries: dict[tuple[int, int], TTEntry] = {}

    def get(self, board_hash: int, color_sign: int) -> TTEntry | None:
        return self._entries.get((board_hash, color_sign))

    def store(self, board_hash: int, color_sign: int, entry: TTEntry) -> None:
        key = (board_hash, color_sign)
        existing = self._entries.get(key)
        if existing is not None and existing.depth > entry.depth and existing.flag == _TT_EXACT:
            return
        self._entries[key] = entry
        if len(self._entries) > self.max_entries:
            trim_count = max(1, self.max_entries // 10)
            shallowest = sorted(
                self._entries.items(),
                key=lambda item: (item[1].depth, 0 if item[1].flag == _TT_EXACT else 1),
            )[:trim_count]
            for trim_key, _entry in shallowest:
                self._entries.pop(trim_key, None)

    def __len__(self) -> int:
        return len(self._entries)


MoveOrderFn = Callable[[chess.Board, chess.Move, int], int]
EvalFn = Callable[[chess.Board], int]
QFilterFn = Callable[[chess.Board, chess.Move], bool]
MoveScoreFn = Callable[[chess.Move], int]
ExtensionFn = Callable[[chess.Board, chess.Move, int, int], int]


class SearchTimeout(RuntimeError):
    pass


def _check_deadline(deadline: float | None) -> None:
    if deadline is not None and perf_counter() >= deadline:
        raise SearchTimeout()


def _default_qmove_filter(board: chess.Board, move: chess.Move) -> bool:
    return bool(board.is_capture(move) or move.promotion)


def is_early_quiet_rook_move(board: chess.Board, move: chess.Move) -> bool:
    piece = board.piece_at(move.from_square)
    if piece is None or piece.piece_type != chess.ROOK:
        return False
    if board.fullmove_number > 10:
        return False
    if board.is_capture(move) or board.gives_check(move) or board.is_castling(move):
        return False
    king_square = board.king(piece.color)
    if king_square is None:
        return False
    castled_squares = {chess.G1, chess.C1} if piece.color == chess.WHITE else {chess.G8, chess.C8}
    return king_square not in castled_squares


def opening_sanity_filter(board: chess.Board, best_move: chess.Move | None, *, score_move: MoveScoreFn) -> chess.Move | None:
    if best_move is None or not is_early_quiet_rook_move(board, best_move):
        return best_move
    alternatives = [move for move in board.legal_moves if not is_early_quiet_rook_move(board, move)]
    if not alternatives:
        return best_move
    return max(alternatives, key=lambda move: (score_move(move), move.uci()))


def _terminal_score(board: chess.Board, *, color_sign: int, ply: int) -> int:
    if board.is_checkmate():
        mate_score = _MATE_SCORE - min(max(ply, 0), 1000)
        white_score = -mate_score if board.turn == chess.WHITE else mate_score
        return color_sign * white_score
    if (
        board.is_stalemate()
        or board.is_insufficient_material()
        or board.can_claim_threefold_repetition()
        or board.can_claim_fifty_moves()
    ):
        return 0
    return 0


class ZobristHasher:
    def __init__(self, seed: int = 20260508):
        rng = random.Random(seed)
        self._pieces = [
            [rng.getrandbits(64) for _square in range(64)]
            for _piece_index in range(12)
        ]
        self._castling = [rng.getrandbits(64) for _ in range(16)]
        self._ep_file = [rng.getrandbits(64) for _ in range(8)]
        self._turn = rng.getrandbits(64)

    @staticmethod
    def _piece_index(piece: chess.Piece) -> int:
        color_offset = 0 if piece.color == chess.WHITE else 6
        return color_offset + int(piece.piece_type) - 1

    def hash_board(self, board: chess.Board) -> int:
        value = 0
        for square, piece in board.piece_map().items():
            value ^= self._pieces[self._piece_index(piece)][square]
        castling_index = 0
        if board.has_kingside_castling_rights(chess.WHITE):
            castling_index |= 1
        if board.has_queenside_castling_rights(chess.WHITE):
            castling_index |= 2
        if board.has_kingside_castling_rights(chess.BLACK):
            castling_index |= 4
        if board.has_queenside_castling_rights(chess.BLACK):
            castling_index |= 8
        value ^= self._castling[castling_index]
        if board.ep_square is not None:
            value ^= self._ep_file[chess.square_file(board.ep_square)]
        if board.turn == chess.WHITE:
            value ^= self._turn
        return value


def _ordered_moves(
    board: chess.Board,
    moves,
    *,
    ply: int,
    tt_move_uci: str | None,
    killer_moves: dict[int, list[str]],
    history_heuristic: dict[tuple[bool, str], int],
    move_order_fn: MoveOrderFn | None,
):
    killers = killer_moves.get(ply, [])

    def sort_key(move: chess.Move):
        score = int(move_order_fn(board, move, ply) if move_order_fn else 0)
        move_uci = move.uci()
        if move_uci == tt_move_uci:
            score += 1_000_000
        if move_uci in killers:
            score += 200_000 - killers.index(move_uci) * 1_000
        score += int(history_heuristic.get((board.turn, move_uci), 0))
        if board.is_capture(move):
            score += 20_000
        if move.promotion:
            score += 15_000
        if board.gives_check(move):
            score += 4_000
        return score

    return sorted(moves, key=sort_key, reverse=True)


def _record_killer(killer_moves: dict[int, list[str]], ply: int, move_uci: str) -> None:
    killers = killer_moves.setdefault(ply, [])
    if move_uci in killers:
        killers.remove(move_uci)
    killers.insert(0, move_uci)
    del killers[_KILLER_SLOTS:]


def _record_history(
    history_heuristic: dict[tuple[bool, str], int],
    *,
    turn: bool,
    move_uci: str,
    depth: int,
) -> None:
    key = (turn, move_uci)
    bonus = max(1, int(depth)) * max(1, int(depth))
    updated = int(history_heuristic.get(key, 0)) + bonus
    history_heuristic[key] = min(updated, _HISTORY_MAX_BONUS)


def _has_non_pawn_material(board: chess.Board, color: chess.Color) -> bool:
    return bool(
        board.pieces(chess.KNIGHT, color)
        or board.pieces(chess.BISHOP, color)
        or board.pieces(chess.ROOK, color)
        or board.pieces(chess.QUEEN, color)
    )


def _is_quiet_move(board: chess.Board, move: chess.Move) -> bool:
    return not (board.is_capture(move) or move.promotion or board.gives_check(move))


def _quiescence(
    board: chess.Board,
    *,
    alpha: int,
    beta: int,
    color_sign: int,
    ply: int,
    remaining_depth: int,
    evaluate: EvalFn,
    qmove_filter: QFilterFn,
    stats: SearchStats,
    deadline: float | None,
) -> int:
    _check_deadline(deadline)
    stats.qnodes += 1
    if board.is_game_over():
        return _terminal_score(board, color_sign=color_sign, ply=ply)
    stand_pat = color_sign * int(evaluate(board))
    if stand_pat >= beta:
        return beta
    if stand_pat > alpha:
        alpha = stand_pat
    if remaining_depth <= 0:
        return alpha
    qmoves = [move for move in board.legal_moves if qmove_filter(board, move)]
    for move in qmoves:
        board.push(move)
        try:
            score = -_quiescence(
                board,
                alpha=-beta,
                beta=-alpha,
                color_sign=-color_sign,
                ply=ply + 1,
                remaining_depth=remaining_depth - 1,
                evaluate=evaluate,
                qmove_filter=qmove_filter,
                stats=stats,
                deadline=deadline,
            )
        finally:
            board.pop()
        if score >= beta:
            return beta
        if score > alpha:
            alpha = score
    return alpha


def _negamax(
    board: chess.Board,
    *,
    depth: int,
    alpha: int,
    beta: int,
    color_sign: int,
    ply: int,
    evaluate: EvalFn,
    move_order_fn: MoveOrderFn | None,
    qmove_filter: QFilterFn,
    extension_fn: ExtensionFn | None,
    extensions_remaining: int,
    stats: SearchStats,
    transposition: TranspositionTable,
    hasher: ZobristHasher,
    killer_moves: dict[int, list[str]],
    history_heuristic: dict[tuple[bool, str], int],
    quiescence_depth: int,
    deadline: float | None,
    enable_pvs: bool,
    enable_lmr: bool,
    enable_null_move: bool,
    enable_futility: bool,
    allow_null_move: bool,
) -> tuple[int, chess.Move | None]:
    _check_deadline(deadline)
    stats.nodes += 1
    original_alpha = alpha
    if board.is_game_over():
        return _terminal_score(board, color_sign=color_sign, ply=ply), None
    board_hash = hasher.hash_board(board)
    cached = transposition.get(board_hash, color_sign)
    tt_move_uci = None
    if cached is not None:
        stats.tt_hits += 1
        tt_move_uci = cached.best_move_uci
        if cached.depth >= depth and cached.flag == _TT_EXACT:
            return cached.score, chess.Move.from_uci(cached.best_move_uci) if cached.best_move_uci else None
        if cached.depth >= depth and cached.flag == _TT_LOWER:
            alpha = max(alpha, cached.score)
        elif cached.depth >= depth and cached.flag == _TT_UPPER:
            beta = min(beta, cached.score)
        if alpha >= beta:
            stats.tt_cutoffs += 1
            return cached.score, chess.Move.from_uci(cached.best_move_uci) if cached.best_move_uci else None
    if depth <= 0:
        return _quiescence(
            board,
            alpha=alpha,
            beta=beta,
            color_sign=color_sign,
            ply=ply,
            remaining_depth=quiescence_depth,
            evaluate=evaluate,
            qmove_filter=qmove_filter,
            stats=stats,
            deadline=deadline,
        ), None

    in_check = board.is_check()
    if (
        enable_null_move
        and allow_null_move
        and depth >= 3
        and not in_check
        and _has_non_pawn_material(board, board.turn)
    ):
        reduction = 2 if depth >= 5 else 1
        board.push(chess.Move.null())
        try:
            null_score, _null_move = _negamax(
                board,
                depth=max(0, depth - reduction - 1),
                alpha=-beta,
                beta=-beta + 1,
                color_sign=-color_sign,
                ply=ply + 1,
                evaluate=evaluate,
                move_order_fn=move_order_fn,
                qmove_filter=qmove_filter,
                extension_fn=extension_fn,
                extensions_remaining=extensions_remaining,
                stats=stats,
                transposition=transposition,
                hasher=hasher,
                killer_moves=killer_moves,
                history_heuristic=history_heuristic,
                quiescence_depth=quiescence_depth,
                deadline=deadline,
                enable_pvs=enable_pvs,
                enable_lmr=enable_lmr,
                enable_null_move=enable_null_move,
                enable_futility=enable_futility,
                allow_null_move=False,
            )
            null_score = -null_score
        finally:
            board.pop()
        if null_score >= beta:
            stats.null_move_cutoffs += 1
            return beta, None

    best_score = -_INFINITY
    best_move = None
    ordered = _ordered_moves(
        board,
        board.legal_moves,
        ply=ply,
        tt_move_uci=tt_move_uci,
        killer_moves=killer_moves,
        history_heuristic=history_heuristic,
        move_order_fn=move_order_fn,
    )
    static_eval = color_sign * int(evaluate(board)) if enable_futility and depth <= 1 and not in_check else None
    searched_moves = 0
    for move_index, move in enumerate(ordered):
        if (
            enable_futility
            and depth <= 1
            and static_eval is not None
            and best_move is not None
            and _is_quiet_move(board, move)
            and static_eval + 180 <= alpha
        ):
            stats.futility_prunes += 1
            continue
        moving_turn = board.turn
        extension = 0
        if extensions_remaining > 0 and extension_fn is not None:
            try:
                extension = max(0, min(1, int(extension_fn(board, move, ply, depth))))
            except Exception:
                extension = 0
        reduced_depth = depth - 1 + extension
        use_lmr = (
            enable_lmr
            and depth >= 3
            and extension == 0
            and move_index >= 4
            and _is_quiet_move(board, move)
            and not in_check
        )
        if use_lmr:
            reduced_depth = max(0, reduced_depth - (2 if depth >= 5 and move_index >= 8 else 1))
        board.push(move)
        try:
            if enable_pvs and searched_moves > 0 and depth >= 2:
                score, _child_move = _negamax(
                    board,
                    depth=reduced_depth,
                    alpha=-alpha - 1,
                    beta=-alpha,
                    color_sign=-color_sign,
                    ply=ply + 1,
                    evaluate=evaluate,
                    move_order_fn=move_order_fn,
                    qmove_filter=qmove_filter,
                    extension_fn=extension_fn,
                    extensions_remaining=max(0, extensions_remaining - extension),
                    stats=stats,
                    transposition=transposition,
                    hasher=hasher,
                    killer_moves=killer_moves,
                    history_heuristic=history_heuristic,
                    quiescence_depth=quiescence_depth,
                    deadline=deadline,
                    enable_pvs=enable_pvs,
                    enable_lmr=enable_lmr,
                    enable_null_move=enable_null_move,
                    enable_futility=enable_futility,
                    allow_null_move=True,
                )
                score = -score
                if score > alpha and score < beta:
                    stats.lmr_researches += 1 if use_lmr else 0
                    score, _child_move = _negamax(
                        board,
                        depth=depth - 1 + extension,
                        alpha=-beta,
                        beta=-alpha,
                        color_sign=-color_sign,
                        ply=ply + 1,
                        evaluate=evaluate,
                        move_order_fn=move_order_fn,
                        qmove_filter=qmove_filter,
                        extension_fn=extension_fn,
                        extensions_remaining=max(0, extensions_remaining - extension),
                        stats=stats,
                        transposition=transposition,
                        hasher=hasher,
                        killer_moves=killer_moves,
                        history_heuristic=history_heuristic,
                        quiescence_depth=quiescence_depth,
                        deadline=deadline,
                        enable_pvs=enable_pvs,
                        enable_lmr=enable_lmr,
                        enable_null_move=enable_null_move,
                        enable_futility=enable_futility,
                        allow_null_move=True,
                    )
                    score = -score
            else:
                score, _child_move = _negamax(
                    board,
                    depth=reduced_depth,
                    alpha=-beta,
                    beta=-alpha,
                    color_sign=-color_sign,
                    ply=ply + 1,
                    evaluate=evaluate,
                    move_order_fn=move_order_fn,
                    qmove_filter=qmove_filter,
                    extension_fn=extension_fn,
                    extensions_remaining=max(0, extensions_remaining - extension),
                    stats=stats,
                    transposition=transposition,
                    hasher=hasher,
                    killer_moves=killer_moves,
                    history_heuristic=history_heuristic,
                    quiescence_depth=quiescence_depth,
                    deadline=deadline,
                    enable_pvs=enable_pvs,
                    enable_lmr=enable_lmr,
                    enable_null_move=enable_null_move,
                    enable_futility=enable_futility,
                    allow_null_move=True,
                )
                score = -score
        finally:
            board.pop()
        searched_moves += 1
        if score > best_score or (score == best_score and best_move is not None and move.uci() < best_move.uci()):
            best_score = score
            best_move = move
        if best_score > alpha:
            alpha = best_score
        if alpha >= beta:
            stats.beta_cutoffs += 1
            if not board.is_capture(move):
                _record_killer(killer_moves, ply, move.uci())
                _record_history(history_heuristic, turn=moving_turn, move_uci=move.uci(), depth=depth)
                stats.history_updates += 1
            break

    flag = _TT_EXACT
    if best_score <= original_alpha:
        flag = _TT_UPPER
    elif best_score >= beta:
        flag = _TT_LOWER
    transposition.store(board_hash, color_sign, TTEntry(
        depth=depth,
        score=best_score,
        flag=flag,
        best_move_uci=best_move.uci() if best_move else None,
    ))
    stats.tt_stores += 1
    return best_score, best_move


def search_best_move(
    board: chess.Board,
    *,
    max_depth: int,
    evaluate: EvalFn,
    move_order_fn: MoveOrderFn | None = None,
    qmove_filter: QFilterFn | None = None,
    extension_fn: ExtensionFn | None = None,
    max_extensions: int = 0,
    aspiration_window: int = _DEFAULT_ASPIRATION_WINDOW,
    quiescence_depth: int = _DEFAULT_QUIESCENCE_DEPTH,
    use_iterative_deepening: bool = True,
    transposition: TranspositionTable | None = None,
    hasher: ZobristHasher | None = None,
    tt_max_entries: int = _DEFAULT_TT_MAX_ENTRIES,
    time_budget_ms: int | None = None,
    enable_pvs: bool = False,
    enable_lmr: bool = False,
    enable_null_move: bool = False,
    enable_futility: bool = False,
) -> SearchResult:
    if board.is_game_over():
        return SearchResult(best_move=None, score=0, depth=0, stats=SearchStats())

    max_depth = max(1, int(max_depth or 1))
    qmove_filter = qmove_filter or _default_qmove_filter
    hasher = hasher or ZobristHasher()
    transposition = transposition if transposition is not None else TranspositionTable(max_entries=tt_max_entries)
    killer_moves: dict[int, list[str]] = {}
    history_heuristic: dict[tuple[bool, str], int] = {}
    stats = SearchStats()
    root_sign = 1 if board.turn == chess.WHITE else -1
    best_move = None
    best_score = -_INFINITY
    deadline = None
    if time_budget_ms is not None:
        try:
            budget = int(time_budget_ms)
        except Exception:
            budget = 0
        if budget > 0:
            deadline = perf_counter() + (budget / 1000.0)

    fallback_moves = _ordered_moves(
        board,
        board.legal_moves,
        ply=0,
        tt_move_uci=None,
        killer_moves={},
        history_heuristic={},
        move_order_fn=move_order_fn,
    )
    fallback_move = fallback_moves[0] if fallback_moves else None

    depth_range = range(1, max_depth + 1) if use_iterative_deepening else [max_depth]
    for depth in depth_range:
        if deadline is not None and perf_counter() >= deadline:
            break
        window = max(20, int(aspiration_window or _DEFAULT_ASPIRATION_WINDOW))
        alpha = -_INFINITY
        beta = _INFINITY
        if best_move is not None and abs(best_score) < (_MATE_SCORE - _ASPIRATION_MATE_MARGIN):
            alpha = best_score - window
            beta = best_score + window
        while True:
            try:
                score, move = _negamax(
                    board,
                    depth=depth,
                    alpha=alpha,
                    beta=beta,
                    color_sign=root_sign,
                    ply=0,
                    evaluate=evaluate,
                    move_order_fn=move_order_fn,
                    qmove_filter=qmove_filter,
                    extension_fn=extension_fn,
                    extensions_remaining=max(0, int(max_extensions or 0)),
                    stats=stats,
                    transposition=transposition,
                    hasher=hasher,
                    killer_moves=killer_moves,
                    history_heuristic=history_heuristic,
                    quiescence_depth=max(0, int(quiescence_depth)),
                    deadline=deadline,
                    enable_pvs=bool(enable_pvs),
                    enable_lmr=bool(enable_lmr),
                    enable_null_move=bool(enable_null_move),
                    enable_futility=bool(enable_futility),
                    allow_null_move=True,
                )
            except SearchTimeout:
                return SearchResult(
                    best_move=best_move or fallback_move,
                    score=best_score if best_move is not None else 0,
                    depth=stats.completed_depth,
                    stats=stats,
                )
            if best_move is None or move is not None:
                candidate = move if move is not None else best_move
            else:
                candidate = best_move
            if alpha > -_INFINITY and score <= alpha:
                stats.aspiration_retries += 1
                alpha = max(-_INFINITY, alpha - window * 2)
                beta = min(_INFINITY, beta + window)
                window *= 2
                continue
            if beta < _INFINITY and score >= beta:
                stats.aspiration_retries += 1
                alpha = max(-_INFINITY, alpha - window)
                beta = min(_INFINITY, beta + window * 2)
                window *= 2
                continue
            best_score = score
            best_move = candidate
            stats.completed_depth = depth
            break
    return SearchResult(best_move=best_move, score=best_score, depth=stats.completed_depth, stats=stats)
