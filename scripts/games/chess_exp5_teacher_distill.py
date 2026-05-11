#!/usr/bin/env python3
"""Distill teacher chess moves into exp5 NNUE-like FEN/move samples."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

import chess


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.games.chess_nnue import build_experiment_nnue_sample_from_position  # noqa: E402
from services.games.self_play_training import DEFAULT_TEACHER_DEPTH, choose_teacher_move  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Distill teacher moves into exp5-compatible JSONL samples.")
    parser.add_argument("--input-jsonl", action="append", default=[], help="JSONL rows containing fen (+ optional side/weight/target).")
    parser.add_argument("--output-jsonl", required=True, help="Destination exp5 FEN/move JSONL.")
    parser.add_argument("--teacher-depth", type=int, default=DEFAULT_TEACHER_DEPTH)
    parser.add_argument("--target", type=float, default=1.0)
    parser.add_argument("--weight", type=float, default=1.4)
    parser.add_argument("--source", default="teacher_distill_exp5")
    parser.add_argument("--replace-output", action="store_true")
    parser.add_argument("--max-samples", type=int, default=0)
    return parser.parse_args()


def _progress(message: str) -> None:
    print(f"[chess-exp5-distill] {message}", file=sys.stderr, flush=True)


def _iter_jsonl(path: Path):
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except Exception as exc:
            raise ValueError(f"{path}:{line_no}: invalid JSON: {exc}") from exc
        if not isinstance(payload, dict):
            raise ValueError(f"{path}:{line_no}: row must be an object")
        yield payload


def _side_from_row(row: dict, fen: str) -> str:
    side = str(row.get("side") or "").strip().lower()
    if side in {"white", "black"}:
        return side
    return "white" if " w " in fen else "black"


def _opponent(side: str) -> str:
    return "black" if side == "white" else "white"


def _immediate_checkmate_moves(board: chess.Board) -> list[str]:
    moves: list[str] = []
    for move in board.legal_moves:
        board.push(move)
        is_mate = board.is_checkmate()
        board.pop()
        if is_mate:
            moves.append(move.uci())
    return sorted(moves)


def _teacher_move_quality(*, fen: str, side: str, move_uci: str) -> dict:
    try:
        board = chess.Board(fen)
        board.turn = chess.WHITE if side == "white" else chess.BLACK
        move = chess.Move.from_uci(move_uci)
    except Exception:
        return {"legal": False, "suspicious": True, "reasons": ["invalid_fen_or_move"], "opponent_mate_in_one": []}
    if move not in board.legal_moves:
        return {"legal": False, "suspicious": True, "reasons": ["illegal_teacher_move"], "opponent_mate_in_one": []}
    board.push(move)
    opponent_mates = _immediate_checkmate_moves(board) if board.turn == (chess.WHITE if _opponent(side) == "white" else chess.BLACK) else []
    reasons = ["allows_opponent_mate_in_one"] if opponent_mates else []
    return {
        "legal": True,
        "suspicious": bool(reasons),
        "reasons": reasons,
        "opponent_mate_in_one": opponent_mates,
    }


def _distill_row(row: dict, *, teacher_depth: int, default_target: float, default_weight: float, default_source: str) -> tuple[dict | None, dict]:
    fen = str(row.get("fen") or row.get("board_fen") or "").strip()
    if not fen:
        return None, {"accepted": False, "reason": "missing_fen"}
    side = _side_from_row(row, fen)
    move = choose_teacher_move({"__fen__": fen}, side, depth=max(1, int(teacher_depth)))
    if not move:
        return None, {"accepted": False, "reason": "teacher_no_move", "fen": fen, "side": side}
    move_uci = f"{move['from']}{move['to']}{move.get('promotion') or ''}".lower()
    quality = _teacher_move_quality(fen=fen, side=side, move_uci=move_uci)
    if not quality["legal"]:
        return None, {"accepted": False, "reason": "illegal_teacher_move", "fen": fen, "side": side, "move_uci": move_uci, "quality": quality}
    if quality["suspicious"]:
        return None, {"accepted": False, "reason": "suspicious_teacher_move", "fen": fen, "side": side, "move_uci": move_uci, "quality": quality}
    sample = build_experiment_nnue_sample_from_position(
        fen=fen,
        side=side,
        move_uci=move_uci,
        target=float(row.get("target", default_target)),
        weight=float(row.get("weight", default_weight)),
        source=str(row.get("source") or default_source),
        hard_negatives=list(row.get("hard_negatives") or []),
        search_profile=str(row.get("search_profile") or "fast"),
    )
    if sample is None:
        return None, {"accepted": False, "reason": "sample_normalization_failed", "fen": fen, "side": side, "move_uci": move_uci, "quality": quality}
    return sample, {"accepted": True, "reason": "accepted", "fen": fen, "side": side, "move_uci": move_uci, "quality": quality}


def _quality_summary(*, input_rows: int, rows: list[dict], audit_rows: list[dict], rejected_reasons: dict[str, int]) -> dict:
    unique_keys = {f"{row.get('fen')}|{row.get('side')}|{row.get('move_uci')}" for row in rows}
    legal_count = sum(1 for row in audit_rows if bool((row.get("quality") or {}).get("legal")))
    suspicious_count = sum(1 for row in audit_rows if bool((row.get("quality") or {}).get("suspicious")))
    accepted = len(rows)
    duplicate_ratio = round(0.0 if accepted <= 0 else 1.0 - (len(unique_keys) / accepted), 6)
    return {
        "input_fen_count": int(input_rows),
        "distilled_rows": accepted,
        "duplicate_ratio": duplicate_ratio,
        "legal_teacher_move_rate": round(legal_count / max(1, input_rows), 6),
        "suspicious_teacher_move_rate": round(suspicious_count / max(1, input_rows), 6),
        "teacher_top1_available_rate": round(len(audit_rows) / max(1, input_rows), 6),
        "teacher_score_available_rate": 0.0,
        "rejected_reasons": rejected_reasons,
        "clean_training_rows": accepted,
        "label_quality_summary": {
            "pass": accepted > 0 and suspicious_count == 0 and legal_count == len(audit_rows),
            "policy": "illegal or suspicious teacher rows are excluded from clean exp5 training targets",
        },
    }


def main() -> int:
    args = parse_args()
    input_paths = [Path(item).expanduser().resolve() for item in args.input_jsonl]
    output_path = Path(args.output_jsonl).expanduser().resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    rows: list[dict] = []
    audit_rows: list[dict] = []
    input_rows = 0
    skipped_rows = 0
    rejected_reasons: dict[str, int] = {}
    _progress(f"input files: {len(input_paths)}")
    _progress(f"output jsonl: {output_path}")
    _progress(f"teacher_depth: {int(args.teacher_depth)}")
    for input_path in input_paths:
        _progress(f"phase read input: {input_path}")
        for row in _iter_jsonl(input_path):
            input_rows += 1
            if int(args.max_samples or 0) > 0 and len(rows) >= int(args.max_samples):
                skipped_rows += 1
                continue
            sample, audit = _distill_row(
                row,
                teacher_depth=int(args.teacher_depth),
                default_target=float(args.target),
                default_weight=float(args.weight),
                default_source=str(args.source or "teacher_distill_exp5"),
            )
            audit_rows.append(audit)
            if sample is None:
                skipped_rows += 1
                reason = str(audit.get("reason") or "skipped")
                rejected_reasons[reason] = int(rejected_reasons.get(reason) or 0) + 1
                continue
            rows.append(sample)
        _progress(f"phase result read input: accepted={len(rows)} skipped={skipped_rows}")
    mode = "w" if args.replace_output else "a"
    with output_path.open(mode, encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    result = {
        "ok": True,
        "engine": "experiment 5:nnue",
        "teacher_depth": int(args.teacher_depth),
        "input_rows": input_rows,
        "input_fen_count": input_rows,
        "accepted_samples": len(rows),
        "distilled_rows": len(rows),
        "skipped_rows": skipped_rows,
        "output_jsonl": str(output_path),
        "sample_format": "exp5_nnue_position_move_v1",
        "retrain_input_compatible": True,
        "quality_audit": _quality_summary(input_rows=input_rows, rows=rows, audit_rows=audit_rows, rejected_reasons=rejected_reasons),
        "strength_validation_supported": False,
        "promotion_gate_supported": False,
    }
    _progress(f"phase result distill: accepted={len(rows)} output={output_path}")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        _progress(f"FAIL: {exc}")
        _progress("failure hint: check FEN rows, output path permissions, and teacher depth")
        raise
