#!/usr/bin/env python3
"""Train experiment 3:dl from external datasets and teacher-distilled FEN sets.

Accepted JSONL row formats:

1. Direct replay sample:
   {"features":[...49 floats...], "target":1.0, "weight":1.2, "source":"external"}

2. Position + chosen move:
   {"fen":"...", "move_uci":"e2e4", "side":"white", "target":1.0, "weight":1.0}

3. Teacher distillation seed:
   {"fen":"...", "side":"white"}
   Used only with ``--teacher-distill-jsonl``; the script will query the teacher
   engine and turn its chosen move into an exp3 replay sample.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

import chess


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.games.chess_dl import (  # noqa: E402
    build_experiment_dl_sample_from_position,
    default_chess_dl_model_path,
    default_chess_dl_replay_path,
    train_experiment_dl_from_replay_samples,
)
from services.games import chess_stockfish_teacher as stockfish_teacher  # noqa: E402
from services.games.self_play_training import DEFAULT_TEACHER_DEPTH, choose_teacher_move  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Train exp3 from external datasets or teacher-distilled positions.")
    parser.add_argument("--input-jsonl", action="append", default=[], help="JSONL rows already containing features or fen+move samples.")
    parser.add_argument("--teacher-distill-jsonl", action="append", default=[], help="JSONL rows containing fen (+ optional side) for teacher distillation.")
    parser.add_argument("--teacher-depth", type=int, default=DEFAULT_TEACHER_DEPTH)
    parser.add_argument(
        "--teacher-backend",
        default="static_depth3",
        choices=["static_depth3", "stockfish"],
        help="Teacher backend for --teacher-distill-jsonl rows. Stockfish requires a local external UCI binary.",
    )
    parser.add_argument("--stockfish-path", default="", help="Local Stockfish-compatible UCI binary for --teacher-backend stockfish.")
    parser.add_argument("--stockfish-movetime-ms", type=int, default=0)
    parser.add_argument("--teacher-top-k", type=int, default=5)
    parser.add_argument("--model-path", default="")
    parser.add_argument("--replay-path", default="")
    parser.add_argument("--replace-replay", action="store_true")
    parser.add_argument("--max-samples", type=int, default=0, help="Optional cap after all rows are expanded.")
    return parser.parse_args()


def _progress(message: str) -> None:
    print(f"[chess-exp3-train] {message}", file=sys.stderr, flush=True)


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


def _teacher_distilled_samples(path: Path, *, teacher_depth: int) -> list[dict]:
    samples: list[dict] = []
    for row in _iter_jsonl(path):
        fen = str(row.get("fen") or row.get("board_fen") or "").strip()
        side = str(row.get("side") or "").strip().lower()
        if side not in {"white", "black"}:
            side = "white" if " w " in fen else "black"
        if not fen:
            continue
        move = choose_teacher_move({"__fen__": fen}, side, depth=teacher_depth)
        if not move:
            continue
        move_uci = f"{move['from']}{move['to']}{move.get('promotion') or ''}"
        sample = build_experiment_dl_sample_from_position(
            fen=fen,
            move_uci=move_uci,
            side=side,
            target=float(row.get("target") or 1.0),
            weight=float(row.get("weight") or 1.4),
            source=str(row.get("source") or "teacher_distill_external"),
        )
        if sample is not None:
            samples.append(sample)
    return samples


def _row_side(row: dict, fen: str) -> str:
    side = str(row.get("side") or "").strip().lower()
    if side in {"white", "black"}:
        return side
    return "white" if " w " in fen else "black"


def _source_move_hard_negative(row: dict, board: chess.Board, best_move: str, top_moves: list[str]) -> list[str]:
    hard_negatives = [str(item).strip().lower() for item in (row.get("hard_negatives") or []) if str(item).strip()]
    source_move = str(row.get("move_uci") or row.get("uci") or row.get("move") or "").strip().lower()
    if not source_move or source_move == best_move or source_move in top_moves:
        return hard_negatives
    try:
        move = chess.Move.from_uci(source_move)
    except Exception:
        return hard_negatives
    if move in board.legal_moves and move.uci() not in hard_negatives:
        hard_negatives.append(move.uci())
    return hard_negatives


def _stockfish_distilled_samples(
    path: Path,
    *,
    teacher_depth: int,
    stockfish_path: str,
    stockfish_movetime_ms: int,
    teacher_top_k: int,
) -> list[dict]:
    engine_path = stockfish_teacher.resolve_stockfish_path(stockfish_path)
    if not engine_path:
        raise RuntimeError("Stockfish binary not found; pass --stockfish-path or set STOCKFISH_PATH")
    samples: list[dict] = []
    limit = stockfish_teacher.analysis_limit(depth=int(teacher_depth or 0), movetime_ms=int(stockfish_movetime_ms or 0))
    with stockfish_teacher.UciStockfish(engine_path) as engine:
        for row in _iter_jsonl(path):
            fen = str(row.get("fen") or row.get("board_fen") or "").strip()
            if not fen:
                continue
            side = _row_side(row, fen)
            try:
                board = chess.Board(fen)
                board.turn = chess.WHITE if side == "white" else chess.BLACK
            except Exception:
                continue
            ranking = engine.analyse(board, limit=limit, multipv=max(1, int(teacher_top_k or 1)))
            if not ranking:
                continue
            best_move = str(ranking[0].get("move") or "").strip().lower()
            top_moves = [str(item.get("move") or "").strip().lower() for item in ranking if item.get("move")]
            sample = build_experiment_dl_sample_from_position(
                fen=board.fen(),
                move_uci=best_move,
                side=side,
                target=float(row.get("target") or 1.0),
                weight=float(row.get("weight") or 1.4),
                source=str(row.get("source") or "stockfish_teacher_distill_exp3"),
                hard_negatives=_source_move_hard_negative(row, board, best_move, top_moves),
                invariance_group_id=str(row.get("invariance_group_id") or row.get("position_id") or ""),
                expected_semantic=str(row.get("expected_semantic") or row.get("semantic_class") or ""),
            )
            if sample is None:
                continue
            sample.update(
                {
                    "trusted_source": str(row.get("trusted_source") or "stockfish_teacher_audited"),
                    "teacher_backend": "stockfish",
                    "teacher_top3": top_moves[:3],
                    "teacher_top5": top_moves[:5],
                    "teacher_eval_cp": int(ranking[0].get("teacher_eval_cp") or 0),
                    "teacher_depth": int(teacher_depth or 0),
                    "teacher_movetime_ms": int(stockfish_movetime_ms or 0),
                }
            )
            samples.append(sample)
    return samples


def _plain_samples(path: Path) -> list[dict]:
    return list(_iter_jsonl(path))


def main() -> int:
    args = parse_args()
    input_paths = [Path(item).expanduser().resolve() for item in args.input_jsonl]
    teacher_paths = [Path(item).expanduser().resolve() for item in args.teacher_distill_jsonl]
    model_path = Path(args.model_path).expanduser().resolve() if args.model_path else default_chess_dl_model_path()
    replay_path = Path(args.replay_path).expanduser().resolve() if args.replay_path else default_chess_dl_replay_path()
    _progress(f"target model: {model_path}")
    _progress(f"target replay: {replay_path}")
    _progress(f"input files: {len(input_paths)} teacher files: {len(teacher_paths)} teacher_depth={int(args.teacher_depth)}")
    samples: list[dict] = []
    for input_path in input_paths:
        _progress(f"phase read input: {input_path}")
        before = len(samples)
        samples.extend(_plain_samples(input_path))
        _progress(f"phase result read input: {len(samples) - before} rows")
    for input_path in teacher_paths:
        _progress(f"phase teacher distill input: {input_path}")
        before = len(samples)
        if str(args.teacher_backend) == "stockfish":
            samples.extend(
                _stockfish_distilled_samples(
                    input_path,
                    teacher_depth=int(args.teacher_depth),
                    stockfish_path=str(args.stockfish_path or ""),
                    stockfish_movetime_ms=int(args.stockfish_movetime_ms or 0),
                    teacher_top_k=int(args.teacher_top_k or 5),
                )
            )
        else:
            samples.extend(_teacher_distilled_samples(input_path, teacher_depth=int(args.teacher_depth)))
        _progress(f"phase result teacher distill: {len(samples) - before} rows")
    if args.max_samples and int(args.max_samples) > 0:
        samples = samples[: int(args.max_samples)]
        _progress(f"phase cap samples: {len(samples)} rows")
    _progress(f"phase train started: {len(samples)} rows replace_replay={bool(args.replace_replay)}")
    result = train_experiment_dl_from_replay_samples(
        samples,
        model_path=model_path,
        replay_path=replay_path,
        replace_replay=bool(args.replace_replay),
    )
    result["teacher_depth"] = int(args.teacher_depth)
    result["teacher_backend"] = str(args.teacher_backend)
    result["input_rows"] = len(samples)
    _progress(f"phase result train: ok artifact={model_path} replay={replay_path}")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        _progress(f"FAIL: {exc}")
        _progress("failure hint: check input JSONL schema, teacher FEN rows, and target model/replay path permissions")
        raise
