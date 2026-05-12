"""Guarded overlay helpers for experiment 4 PV chess.

The overlay keeps a stable baseline move as default and only adopts a candidate
PV move when runtime-feasible safety guards pass. The pure guard functions do
not read expected labels or benchmark pass/fail outcomes.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import chess


DEFAULT_STATIC_SCORE_WINDOW_CP = 150


def guarded_overlay_enabled() -> bool:
    return str(os.environ.get("HTML_LEARNING_CHESS_EXP4_GUARDED_OVERLAY", "")).strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def exp4_overlay_candidate_model_path() -> Path | None:
    raw = str(os.environ.get("HTML_LEARNING_CHESS_EXP4_OVERLAY_CANDIDATE_MODEL_PATH", "")).strip()
    return Path(raw) if raw else None


def _parse_legal_uci_move(board: chess.Board, move_uci: str) -> chess.Move | None:
    try:
        move = chess.Move.from_uci(str(move_uci or "").lower())
    except ValueError:
        return None
    return move if move in board.legal_moves else None


def _material_cp(board: chess.Board, color: chess.Color) -> int:
    values = {
        chess.PAWN: 100,
        chess.KNIGHT: 320,
        chess.BISHOP: 330,
        chess.ROOK: 500,
        chess.QUEEN: 900,
    }
    score = 0
    for piece in board.piece_map().values():
        value = values.get(piece.piece_type, 0)
        score += value if piece.color == color else -value
    return score


def exp4_static_score_after_move(board: chess.Board, move: chess.Move, side: str) -> int:
    """Small deterministic score source for runtime overlay guard comparisons."""
    color = chess.WHITE if str(side or "white").lower() == "white" else chess.BLACK
    after = board.copy(stack=False)
    after.push(move)
    if after.is_checkmate():
        # after.turn is the side that got mated.
        return 100_000 if after.turn != color else -100_000
    if after.is_stalemate() or after.is_insufficient_material():
        return 0
    return _material_cp(after, color)


def exp4_promotion_subtype_guard(
    board: chess.Board,
    baseline_move: chess.Move | None,
    final_move: chess.Move,
) -> tuple[bool, str]:
    """Allow non-queen promotions only with a runtime-verifiable tactical reason."""
    if not final_move.promotion or final_move.promotion == chess.QUEEN:
        return True, "not_nonqueen_promotion"

    after_final = board.copy(stack=False)
    after_final.push(final_move)
    if after_final.is_checkmate():
        return True, "nonqueen_promotion_gives_immediate_mate"

    queen_move = chess.Move(final_move.from_square, final_move.to_square, promotion=chess.QUEEN)
    if queen_move in board.legal_moves:
        after_queen = board.copy(stack=False)
        after_queen.push(queen_move)
        if after_queen.is_stalemate() and not after_final.is_stalemate():
            return True, "nonqueen_promotion_avoids_queen_stalemate"

    if baseline_move and baseline_move.promotion == chess.QUEEN:
        return False, "nonqueen_promotion_downgrade_without_runtime_tactical_reason"
    return False, "nonqueen_promotion_without_runtime_tactical_reason"


def exp4_runtime_overlay_allows_final(
    *,
    fen: str,
    side: str,
    baseline_move_uci: str,
    final_move_uci: str,
    baseline_score_cp: int | float | None = None,
    final_score_cp: int | float | None = None,
    final_illegal: bool = False,
    static_score_window_cp: int = DEFAULT_STATIC_SCORE_WINDOW_CP,
) -> tuple[bool, str, dict[str, Any]]:
    """No-label runtime guard used by validation and the optional runtime path."""
    if not final_move_uci:
        return False, "final_missing", {}
    if final_move_uci == baseline_move_uci:
        return True, "same_move", {"same_move": True}
    if final_illegal:
        return False, "final_illegal", {}
    try:
        board = chess.Board(str(fen or ""))
    except ValueError:
        return False, "invalid_fen", {}
    baseline_move = _parse_legal_uci_move(board, baseline_move_uci)
    final_move = _parse_legal_uci_move(board, final_move_uci)
    if final_move is None:
        return False, "final_not_legal_in_position", {}

    promotion_allowed, promotion_reason = exp4_promotion_subtype_guard(board, baseline_move, final_move)
    if not promotion_allowed:
        return False, promotion_reason, {"promotion_subtype_guard": promotion_reason}

    if baseline_score_cp is None:
        baseline_score_cp = exp4_static_score_after_move(board, baseline_move, side) if baseline_move else None
    if final_score_cp is None:
        final_score_cp = exp4_static_score_after_move(board, final_move, side)

    if baseline_score_cp is None or final_score_cp is None:
        return False, "runtime_score_missing", {
            "baseline_score_cp": baseline_score_cp,
            "final_score_cp": final_score_cp,
            "promotion_subtype_guard": promotion_reason,
            "static_score_window_cp": int(static_score_window_cp),
        }

    score_delta = float(final_score_cp) - float(baseline_score_cp)
    if score_delta < -abs(int(static_score_window_cp)):
        return False, "static_score_delta_below_runtime_window", {
            "score_delta": round(score_delta, 4),
            "baseline_score_cp": baseline_score_cp,
            "final_score_cp": final_score_cp,
            "promotion_subtype_guard": promotion_reason,
            "static_score_window_cp": int(static_score_window_cp),
        }

    return True, "runtime_static_and_rule_guard_passed", {
        "score_delta": round(score_delta, 4),
        "baseline_score_cp": baseline_score_cp,
        "final_score_cp": final_score_cp,
        "promotion_subtype_guard": promotion_reason,
        "static_score_window_cp": int(static_score_window_cp),
    }


def _move_uci(move: dict | None) -> str:
    return f"{(move or {}).get('from') or ''}{(move or {}).get('to') or ''}{(move or {}).get('promotion') or ''}".lower()


def choose_experiment_pv_guarded_overlay_move(
    board_state,
    side: str,
    *,
    baseline_model_path=None,
    candidate_model_path=None,
    search_profile: str = "fast",
    fusion_mode: str = "balanced_fusion",
    decision_mode: str = "mcts",
) -> dict | None:
    """Optional exp4 runtime overlay path.

    This helper is intentionally opt-in. It keeps the baseline PV model as
    default and adopts the candidate PV model only when the shared no-label
    guard passes.
    """
    from services.games.chess import to_chess_board
    from services.games.chess_pv import choose_experiment_pv_move, default_chess_pv_model_path

    baseline_path = baseline_model_path or default_chess_pv_model_path()
    candidate_path = candidate_model_path or exp4_overlay_candidate_model_path()
    baseline_move = choose_experiment_pv_move(
        board_state,
        side,
        model_path=baseline_path,
        search_profile=search_profile,
        fusion_mode=fusion_mode,
        decision_mode=decision_mode,
    )
    if not candidate_path:
        return baseline_move
    final_move = choose_experiment_pv_move(
        board_state,
        side,
        model_path=candidate_path,
        search_profile=search_profile,
        fusion_mode=fusion_mode,
        decision_mode=decision_mode,
    )
    if not final_move:
        return baseline_move
    board = to_chess_board(board_state, side)
    ai_color = chess.WHITE if side == "white" else chess.BLACK
    if board.turn != ai_color:
        board.turn = ai_color
    fen = board.fen()
    baseline_uci = _move_uci(baseline_move)
    final_uci = _move_uci(final_move)
    baseline_chess_move = _parse_legal_uci_move(board, baseline_uci)
    final_chess_move = _parse_legal_uci_move(board, final_uci)
    baseline_score = exp4_static_score_after_move(board, baseline_chess_move, side) if baseline_chess_move else None
    final_score = exp4_static_score_after_move(board, final_chess_move, side) if final_chess_move else None
    allowed, _reason, _detail = exp4_runtime_overlay_allows_final(
        fen=fen,
        side=side,
        baseline_move_uci=baseline_uci,
        final_move_uci=final_uci,
        baseline_score_cp=baseline_score,
        final_score_cp=final_score,
        final_illegal=final_chess_move is None,
    )
    return final_move if allowed and final_uci != baseline_uci else baseline_move
