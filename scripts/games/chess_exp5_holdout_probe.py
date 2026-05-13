#!/usr/bin/env python3
"""Holdout-style behavioral probes for chess ``experiment 5:nnue``.

These cases are deliberately reported separately from the main score probe.
They stress broad behavioral properties (mate prevention, mate finding,
recapture discipline, and promotion-pawn cleanup) rather than exact opening
replay agreement, so they are useful for spotting overfitting to the fixed
score cases.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import chess


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.games.chess import FEN_KEY  # noqa: E402
from services.games.chess_nnue import choose_experiment_nnue_move  # noqa: E402


EXP5 = "experiment 5:nnue"
PIECE_VALUES = {
    chess.PAWN: 100,
    chess.KNIGHT: 320,
    chess.BISHOP: 330,
    chess.ROOK: 500,
    chess.QUEEN: 900,
    chess.KING: 0,
}


@dataclass(frozen=True)
class HoldoutCase:
    case_id: str
    fen: str
    side: str
    kind: str
    description: str
    min_capture_value: int = 0


def _board_state(board: chess.Board) -> dict[str, str]:
    state = {chess.square_name(square): piece.symbol() for square, piece in board.piece_map().items()}
    state[FEN_KEY] = board.fen()
    return state


def _move_uci(move: dict[str, Any] | None) -> str:
    if not move:
        return ""
    return f"{move.get('from')}{move.get('to')}{move.get('promotion') or ''}".lower()


def _mate_in_one_moves(board: chess.Board) -> list[str]:
    mates: list[str] = []
    for move in board.legal_moves:
        after = board.copy(stack=False)
        after.push(move)
        if after.is_checkmate():
            mates.append(move.uci())
    return sorted(mates)


def _mate_threats_if_side_passed(board: chess.Board) -> list[str]:
    other = board.copy(stack=False)
    other.turn = not board.turn
    return _mate_in_one_moves(other)


def _blunders_allowing_mate_in_one(board: chess.Board) -> list[str]:
    blunders: list[str] = []
    for move in board.legal_moves:
        after = board.copy(stack=False)
        after.push(move)
        if _mate_in_one_moves(after):
            blunders.append(move.uci())
    return sorted(blunders)


def _captured_value(board: chess.Board, move: chess.Move) -> int:
    if board.is_en_passant(move):
        square = chess.square(chess.square_file(move.to_square), chess.square_rank(move.from_square))
    else:
        square = move.to_square
    captured = board.piece_at(square)
    return PIECE_VALUES.get(captured.piece_type, 0) if captured else 0


def _dangerous_pawn_capture(board: chess.Board, move: chess.Move) -> bool:
    captured = board.piece_at(move.to_square)
    if captured is None or captured.piece_type != chess.PAWN:
        return False
    rank = chess.square_rank(move.to_square)
    return (captured.color == chess.BLACK and rank <= 1) or (captured.color == chess.WHITE and rank >= 6)


def _mirror_case(case: HoldoutCase) -> HoldoutCase:
    board = chess.Board(case.fen)
    mirrored = board.mirror()
    return HoldoutCase(
        case_id=f"{case.case_id}_mirror",
        fen=mirrored.fen(),
        side="white" if case.side == "black" else "black",
        kind=case.kind,
        description=f"Mirrored holdout: {case.description}",
        min_capture_value=case.min_capture_value,
    )


def base_cases() -> list[HoldoutCase]:
    return [
        HoldoutCase(
            "scholar_qh5_c4",
            "rnbqkbnr/pppp1ppp/8/4p2Q/2B1P3/8/PPPP1PPP/RNB1K1NR b KQkq - 3 2",
            "black",
            "prevent_mate_in_one",
            "Black must address Qxf7# without relying on the exact fixed-case position.",
        ),
        HoldoutCase(
            "scholar_qf3_c4",
            "rnbqkbnr/pppp1ppp/8/4p3/2B1P3/5Q2/PPPP1PPP/RNB1K1NR b KQkq - 3 2",
            "black",
            "prevent_mate_in_one",
            "Queen on f3 and bishop on c4 create the same f7 mate threat.",
        ),
        HoldoutCase(
            "diagonal_qe1_trap_extra_pawn",
            "6k1/5ppp/3b4/8/7q/8/5PPP/6K1 w - - 0 1",
            "white",
            "avoid_creating_mate_in_one",
            "White must not open the diagonal to Qe1#.",
        ),
        HoldoutCase(
            "diagonal_qe1_capture_defense",
            "6k1/5ppp/8/8/7q/5b2/6PP/6K1 w - - 0 1",
            "white",
            "prevent_mate_in_one",
            "White can solve the mate threat by capturing the attacking bishop.",
        ),
        HoldoutCase(
            "simple_queen_mate_white",
            "6k1/5Q2/6K1/8/8/8/8/8 w - - 0 1",
            "white",
            "find_mate_in_one",
            "White has multiple queen mates and should choose one.",
        ),
        HoldoutCase(
            "corner_queen_mate_white",
            "k7/8/KQ6/8/8/8/8/8 w - - 0 1",
            "white",
            "find_mate_in_one",
            "White must convert a simple corner mate.",
        ),
        HoldoutCase(
            "minor_recapture_center",
            "r2k1b1r/p1p1ppp1/p6p/3p4/5P2/2N5/PP1B2PP/2Rb1RK1 w - - 0 12",
            "white",
            "capture_material",
            "White should not ignore the bishop that invaded d1.",
            min_capture_value=PIECE_VALUES[chess.BISHOP],
        ),
        HoldoutCase(
            "queen_hang_rook_capture",
            "k7/8/8/8/8/8/4R2q/4K3 w - - 0 1",
            "white",
            "capture_material",
            "White should capture the hanging queen.",
            min_capture_value=PIECE_VALUES[chess.QUEEN],
        ),
        HoldoutCase(
            "black_pawn_one_step_from_promotion",
            "8/8/8/8/8/8/R1p5/4K2k w - - 0 1",
            "white",
            "capture_dangerous_pawn",
            "White should clean up a black pawn one move from promotion.",
        ),
        HoldoutCase(
            "white_pawn_one_step_from_promotion",
            "4k3/r4P2/8/8/8/8/8/4K3 b - - 0 1",
            "black",
            "capture_dangerous_pawn",
            "Black should clean up a white pawn one move from promotion.",
        ),
    ]


def holdout_cases(*, include_mirrors: bool) -> list[HoldoutCase]:
    cases = base_cases()
    if include_mirrors:
        cases = [case for base in cases for case in (base, _mirror_case(base))]
    return cases


def evaluate_case(case: HoldoutCase, *, search_profile: str) -> dict[str, Any]:
    board = chess.Board(case.fen)
    board.turn = chess.WHITE if case.side == "white" else chess.BLACK
    move_dict = choose_experiment_nnue_move(_board_state(board), case.side, search_profile=search_profile)
    chosen = _move_uci(move_dict)
    valid = False
    passed = False
    reason = ""
    chosen_san = ""
    legal_mates_before = _mate_threats_if_side_passed(board)
    try:
        move = chess.Move.from_uci(chosen)
        valid = move in board.legal_moves
    except Exception:
        move = None
    if valid and move is not None:
        chosen_san = board.san(move)
        after = board.copy(stack=False)
        after.push(move)
        opponent_mates_after = _mate_in_one_moves(after)
        if case.kind == "prevent_mate_in_one":
            passed = bool(legal_mates_before) and not opponent_mates_after
            reason = "prevents_mate_in_one" if passed else "opponent_still_has_mate_in_one"
        elif case.kind == "avoid_creating_mate_in_one":
            blunders = _blunders_allowing_mate_in_one(board)
            passed = bool(blunders) and not opponent_mates_after
            reason = "avoids_creating_mate_in_one" if passed else "created_or_failed_to_validate_mate_in_one"
        elif case.kind == "find_mate_in_one":
            passed = after.is_checkmate()
            reason = "chosen_move_checkmates" if passed else "missed_mate_in_one"
        elif case.kind == "capture_material":
            captured_value = _captured_value(board, move)
            passed = captured_value >= int(case.min_capture_value)
            reason = f"captured_value={captured_value}"
        elif case.kind == "capture_dangerous_pawn":
            passed = _dangerous_pawn_capture(board, move)
            reason = "captured_dangerous_pawn" if passed else "did_not_capture_dangerous_pawn"
        else:
            reason = f"unknown_kind:{case.kind}"
    else:
        opponent_mates_after = []
        reason = "invalid_or_illegal_move"
    return {
        "case_id": case.case_id,
        "fen": case.fen,
        "side": case.side,
        "kind": case.kind,
        "description": case.description,
        "chosen": chosen,
        "chosen_san": chosen_san,
        "valid": valid,
        "passed": bool(passed),
        "reason": reason,
        "mate_threats_if_side_passed": legal_mates_before,
        "blunders_allowing_mate_in_one": _blunders_allowing_mate_in_one(board),
        "opponent_mates_after_chosen": opponent_mates_after,
    }


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    by_kind: dict[str, dict[str, int]] = {}
    for row in rows:
        bucket = by_kind.setdefault(str(row["kind"]), {"cases": 0, "passed": 0})
        bucket["cases"] += 1
        bucket["passed"] += 1 if row.get("passed") else 0
    for bucket in by_kind.values():
        bucket["pass_rate"] = round(bucket["passed"] / max(1, bucket["cases"]), 4)
    passed = sum(1 for row in rows if row.get("passed"))
    return {
        "cases": len(rows),
        "passed": passed,
        "pass_rate": round(passed / max(1, len(rows)), 4),
        "by_kind": by_kind,
        "failed": [row for row in rows if not row.get("passed")],
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run exp5 holdout behavioral probes.")
    parser.add_argument("--search-profile", default="balanced")
    parser.add_argument("--no-mirrors", action="store_true")
    parser.add_argument("--output", default=str(ROOT / "docs" / "games" / "2026-05-13_exp5_holdout_probe.json"))
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    rows = [
        evaluate_case(case, search_profile=str(args.search_profile or "balanced"))
        for case in holdout_cases(include_mirrors=not bool(args.no_mirrors))
    ]
    artifact = {
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "engine": EXP5,
        "search_profile": str(args.search_profile or "balanced"),
        "summary": summarize(rows),
        "cases": rows,
    }
    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(artifact, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(out_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
