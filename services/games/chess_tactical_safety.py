"""Runtime tactical safety helpers for chess engines.

The guard blocks direct one-ply hanging-piece losses unless the move has
immediate legal compensation after the obvious recapture.
"""

from __future__ import annotations

from typing import Callable

import chess


PIECE_VALUES_CP = {
    chess.PAWN: 100,
    chess.KNIGHT: 320,
    chess.BISHOP: 335,
    chess.ROOK: 500,
    chess.QUEEN: 900,
    chess.KING: 20_000,
}

DEFAULT_MAX_DIRECT_LOSS_CP = 80
DEFAULT_COMPENSATION_WINDOW_CP = 40


def material_cp(board: chess.Board, color: chess.Color) -> int:
    score = 0
    for piece in board.piece_map().values():
        value = PIECE_VALUES_CP.get(piece.piece_type, 0)
        score += value if piece.color == color else -value
    return score


def _captured_square(board: chess.Board, move: chess.Move) -> int | None:
    if board.is_en_passant(move):
        return chess.square(chess.square_file(move.to_square), chess.square_rank(move.from_square))
    if board.is_capture(move):
        return move.to_square
    return None


def _best_immediate_response_score(board: chess.Board, color: chess.Color) -> tuple[int, str]:
    if board.is_checkmate():
        return (-9_000_000 if board.turn == color else 9_000_000), ""
    if board.is_game_over():
        return material_cp(board, color), ""
    best_score = -9_000_000
    best_move = ""
    for response in sorted(board.legal_moves, key=lambda item: item.uci()):
        after = board.copy(stack=False)
        after.push(response)
        if after.is_checkmate():
            score = 9_000_000 if after.turn != color else -9_000_000
        else:
            score = material_cp(after, color)
        if score > best_score or (score == best_score and response.uci() < best_move):
            best_score = score
            best_move = response.uci()
    return best_score, best_move


def tactical_safety_report(
    board: chess.Board,
    move: chess.Move | None,
    *,
    color: chess.Color | None = None,
    max_direct_loss_cp: int = DEFAULT_MAX_DIRECT_LOSS_CP,
    compensation_window_cp: int = DEFAULT_COMPENSATION_WINDOW_CP,
) -> dict:
    if move is None:
        return {"safe": False, "reason": "missing_move"}
    if move not in board.legal_moves:
        return {"safe": False, "reason": "illegal_move", "move": move.uci()}

    mover = board.turn if color is None else color
    before_score = material_cp(board, mover)
    after = board.copy(stack=False)
    after.push(move)
    if after.is_checkmate():
        return {
            "safe": True,
            "reason": "immediate_checkmate",
            "move": move.uci(),
            "before_score_cp": before_score,
            "after_score_cp": 9_000_000,
        }

    moved_piece = after.piece_at(move.to_square)
    if moved_piece is None or moved_piece.color != mover or moved_piece.piece_type == chess.KING:
        return {
            "safe": True,
            "reason": "no_hanging_moved_piece",
            "move": move.uci(),
            "before_score_cp": before_score,
            "after_score_cp": material_cp(after, mover),
        }

    direct_replies: list[dict] = []
    for reply in sorted(after.legal_moves, key=lambda item: item.uci()):
        if _captured_square(after, reply) != move.to_square:
            continue
        reply_board = after.copy(stack=False)
        reply_board.push(reply)
        reply_score = -9_000_000 if reply_board.is_checkmate() and reply_board.turn == mover else material_cp(reply_board, mover)
        response_score, response_move = _best_immediate_response_score(reply_board, mover)
        direct_replies.append(
            {
                "reply": reply.uci(),
                "score_after_reply_cp": int(reply_score),
                "loss_from_before_cp": int(before_score - reply_score),
                "best_response": response_move,
                "best_response_score_cp": int(response_score),
            }
        )

    if not direct_replies:
        return {
            "safe": True,
            "reason": "no_direct_recapture",
            "move": move.uci(),
            "before_score_cp": before_score,
            "after_score_cp": material_cp(after, mover),
        }

    worst = max(direct_replies, key=lambda row: (int(row["loss_from_before_cp"]), row["reply"]))
    max_loss = int(worst["loss_from_before_cp"])
    if max_loss <= int(max_direct_loss_cp):
        return {
            "safe": True,
            "reason": "direct_loss_within_window",
            "move": move.uci(),
            "before_score_cp": before_score,
            "after_score_cp": material_cp(after, mover),
            "worst_reply": worst,
            "max_direct_loss_cp": int(max_direct_loss_cp),
        }

    compensation_floor = before_score - abs(int(compensation_window_cp))
    if int(worst["best_response_score_cp"]) >= compensation_floor:
        return {
            "safe": True,
            "reason": "immediate_compensation_after_recapture",
            "move": move.uci(),
            "before_score_cp": before_score,
            "after_score_cp": material_cp(after, mover),
            "worst_reply": worst,
            "compensation_floor_cp": int(compensation_floor),
        }

    return {
        "safe": False,
        "reason": "direct_hanging_piece_without_compensation",
        "move": move.uci(),
        "before_score_cp": before_score,
        "after_score_cp": material_cp(after, mover),
        "moved_piece_value_cp": PIECE_VALUES_CP.get(moved_piece.piece_type, 0),
        "worst_reply": worst,
        "direct_replies": direct_replies[:5],
        "max_direct_loss_cp": int(max_direct_loss_cp),
        "compensation_floor_cp": int(compensation_floor),
    }


def choose_tactically_safe_move(
    board: chess.Board,
    proposed_move: chess.Move | None,
    *,
    score_move: Callable[[chess.Move], float] | None = None,
    max_direct_loss_cp: int = DEFAULT_MAX_DIRECT_LOSS_CP,
    compensation_window_cp: int = DEFAULT_COMPENSATION_WINDOW_CP,
) -> tuple[chess.Move | None, dict]:
    report = tactical_safety_report(
        board,
        proposed_move,
        max_direct_loss_cp=max_direct_loss_cp,
        compensation_window_cp=compensation_window_cp,
    )
    if bool(report.get("safe")):
        report["fallback_applied"] = False
        return proposed_move, report

    safe_candidates: list[tuple[float, str, chess.Move, dict]] = []
    for candidate in sorted(board.legal_moves, key=lambda item: item.uci()):
        candidate_report = tactical_safety_report(
            board,
            candidate,
            max_direct_loss_cp=max_direct_loss_cp,
            compensation_window_cp=compensation_window_cp,
        )
        if not bool(candidate_report.get("safe")):
            continue
        try:
            score = float(score_move(candidate) if score_move is not None else 0.0)
        except Exception:
            score = 0.0
        safe_candidates.append((score, candidate.uci(), candidate, candidate_report))

    if not safe_candidates:
        report["fallback_applied"] = False
        report["fallback_reason"] = "no_safe_legal_alternative"
        return proposed_move, report

    _score, _uci, fallback, fallback_report = max(safe_candidates, key=lambda item: (item[0], item[1]))
    return fallback, {
        "safe": True,
        "reason": "fallback_selected",
        "fallback_applied": True,
        "blocked_move": proposed_move.uci() if proposed_move is not None else "",
        "blocked_report": report,
        "fallback_move": fallback.uci(),
        "fallback_report": fallback_report,
    }
