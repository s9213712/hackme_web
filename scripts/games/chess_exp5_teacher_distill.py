#!/usr/bin/env python3
"""Distill teacher chess moves into exp5 NNUE-like FEN/move samples."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


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


def _distill_row(row: dict, *, teacher_depth: int, default_target: float, default_weight: float, default_source: str) -> dict | None:
    fen = str(row.get("fen") or row.get("board_fen") or "").strip()
    if not fen:
        return None
    side = _side_from_row(row, fen)
    move = choose_teacher_move({"__fen__": fen}, side, depth=max(1, int(teacher_depth)))
    if not move:
        return None
    move_uci = f"{move['from']}{move['to']}{move.get('promotion') or ''}".lower()
    return build_experiment_nnue_sample_from_position(
        fen=fen,
        side=side,
        move_uci=move_uci,
        target=float(row.get("target", default_target)),
        weight=float(row.get("weight", default_weight)),
        source=str(row.get("source") or default_source),
        hard_negatives=list(row.get("hard_negatives") or []),
        search_profile=str(row.get("search_profile") or "fast"),
    )


def main() -> int:
    args = parse_args()
    input_paths = [Path(item).expanduser().resolve() for item in args.input_jsonl]
    output_path = Path(args.output_jsonl).expanduser().resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    rows: list[dict] = []
    input_rows = 0
    skipped_rows = 0
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
            sample = _distill_row(
                row,
                teacher_depth=int(args.teacher_depth),
                default_target=float(args.target),
                default_weight=float(args.weight),
                default_source=str(args.source or "teacher_distill_exp5"),
            )
            if sample is None:
                skipped_rows += 1
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
        "accepted_samples": len(rows),
        "skipped_rows": skipped_rows,
        "output_jsonl": str(output_path),
        "sample_format": "exp5_nnue_position_move_v1",
        "retrain_input_compatible": True,
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
