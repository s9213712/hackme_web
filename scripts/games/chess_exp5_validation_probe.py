#!/usr/bin/env python3
"""Run held-out exp5 validation positions through a Stockfish teacher audit.

This probe is deliberately separate from the deterministic gauntlet used for
score tracking.  The question set is sensitive validation material and must be
provided as a local JSON file; this script intentionally does not embed FENs,
move sequences, question IDs, or teacher answers.
"""

from __future__ import annotations

import argparse
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
import time
from typing import Any

import chess


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.games.chess_nnue import choose_experiment_nnue_move  # noqa: E402
from services.games import chess_stockfish_teacher as stockfish_teacher  # noqa: E402


@dataclass(frozen=True)
class ValidationQuestion:
    question_id: str
    category: str
    moves: tuple[str, ...] = ()
    fen: str = ""
    note: str = ""


DEFAULT_PRIVATE_ROOT = Path(os.environ.get("HACKME_WEB_PRIVATE_ROOT", str(ROOT.parent / "hackme_web_private/runtime/private"))).expanduser()
DEFAULT_QUESTION_SET_PATH = DEFAULT_PRIVATE_ROOT / "exp5_heldout_validation_50_questions.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run held-out exp5 validation positions with Stockfish teacher audit.")
    parser.add_argument(
        "--profiles",
        default="fixed_depth_balanced,fixed_depth_piece_activity_midgame",
        help="Comma-separated exp5 search profiles to compare.",
    )
    parser.add_argument("--questions", type=int, default=50, help="Number of held-out questions to run from --question-set.")
    parser.add_argument(
        "--question-set",
        default=str(DEFAULT_QUESTION_SET_PATH),
        help="Sensitive local JSON question-set path. The question data is intentionally not embedded in this script.",
    )
    parser.add_argument(
        "--verbose-questions",
        action="store_true",
        help="Print sensitive question IDs and teacher moves for local debugging only.",
    )
    parser.add_argument(
        "--write-sensitive-output",
        action="store_true",
        help="Include FENs, move sequences, teacher PVs, and question IDs in JSON/JSONL outputs.",
    )
    parser.add_argument("--stockfish-path", default="", help="External local Stockfish-compatible UCI binary.")
    parser.add_argument("--depth", type=int, default=8, help="Stockfish teacher depth.")
    parser.add_argument("--movetime-ms", type=int, default=0, help="Optional Stockfish movetime per question.")
    parser.add_argument("--multipv", type=int, default=5, help="Stockfish MultiPV count.")
    parser.add_argument("--accept-topk", type=int, default=3, help="Clean if exp5 move is within this Stockfish rank.")
    parser.add_argument("--clean-cp-loss", type=int, default=60, help="Clean if exp5 move loses at most this many centipawns.")
    parser.add_argument("--review-cp-loss", type=int, default=160, help="Review if exp5 move loses at most this many centipawns.")
    parser.add_argument(
        "--output-json",
        default="docs/games/evidence/exp5/v20_heldout_validation_50_stockfish.json",
        help="Summary JSON output path.",
    )
    parser.add_argument(
        "--output-jsonl",
        default="docs/games/evidence/exp5/v20_heldout_validation_50_stockfish.jsonl",
        help="Per-profile/per-question JSONL output path.",
    )
    return parser.parse_args()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _progress(message: str) -> None:
    print(f"[chess-exp5-validation-probe] {message}", file=sys.stderr, flush=True)


def _load_questions(path: Path) -> list[ValidationQuestion]:
    if not path.exists():
        raise SystemExit(
            f"question set not found: {path}. Provide --question-set or create the private runtime question file."
        )
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise SystemExit(f"question set must be a JSON array: {path}")
    questions: list[ValidationQuestion] = []
    for index, item in enumerate(payload, start=1):
        if not isinstance(item, dict):
            raise SystemExit(f"question set row {index} must be an object")
        moves = item.get("moves") or []
        if not isinstance(moves, list):
            raise SystemExit(f"question set row {index} moves must be an array")
        questions.append(
            ValidationQuestion(
                question_id=str(item.get("question_id") or f"q{index:03d}"),
                category=str(item.get("category") or "unknown"),
                moves=tuple(str(move) for move in moves),
                fen=str(item.get("fen") or ""),
                note=str(item.get("note") or ""),
            )
        )
    return questions


def _move_uci(move: dict[str, Any] | None) -> str:
    if not move:
        return ""
    return f"{move.get('from') or ''}{move.get('to') or ''}{move.get('promotion') or ''}".lower()


def _state_from_board(board: chess.Board) -> dict[str, str]:
    state = {chess.square_name(square): piece.symbol() for square, piece in board.piece_map().items()}
    state["__fen__"] = board.fen()
    return state


def _side(board: chess.Board) -> str:
    return "white" if board.turn == chess.WHITE else "black"


def _build_board(question: ValidationQuestion) -> chess.Board:
    if question.fen:
        board = chess.Board(question.fen)
    else:
        board = chess.Board()
        for san in question.moves:
            board.push_san(san)
    if not board.is_valid():
        raise ValueError(f"{question.question_id}: invalid board: {board.fen()}")
    if board.is_game_over(claim_draw=True):
        raise ValueError(f"{question.question_id}: game already over: {board.fen()}")
    if not any(board.legal_moves):
        raise ValueError(f"{question.question_id}: no legal moves: {board.fen()}")
    return board


def _analyse_root_move(
    engine: stockfish_teacher.UciStockfish,
    board: chess.Board,
    move: chess.Move,
    *,
    limit: dict[str, int],
) -> dict[str, Any]:
    rows = engine.analyse(board, limit=limit, multipv=1, root_moves=[move])
    if not rows:
        return {"move": move.uci(), "teacher_eval_cp": None, "rank": None, "pv": []}
    row = dict(rows[0])
    row["move"] = move.uci()
    return row


def _teacher_audit_status(
    *,
    rank: int | None,
    cp_loss: int | None,
    accept_topk: int,
    clean_cp_loss: int,
    review_cp_loss: int,
) -> str:
    if rank is not None and rank <= accept_topk:
        return "clean"
    if cp_loss is not None and cp_loss <= clean_cp_loss:
        return "clean"
    if cp_loss is not None and cp_loss <= review_cp_loss:
        return "review"
    return "rejected"


def _category_summary(rows: list[dict[str, Any]]) -> dict[str, dict[str, int]]:
    summary: dict[str, dict[str, int]] = defaultdict(lambda: {"total": 0, "clean": 0, "review": 0, "rejected": 0, "top1": 0, "top3": 0, "top5": 0})
    for row in rows:
        bucket = summary[str(row.get("category") or "unknown")]
        bucket["total"] += 1
        status = str(row.get("status") or "rejected")
        bucket[status] = bucket.get(status, 0) + 1
        rank = row.get("teacher_rank")
        if isinstance(rank, int):
            if rank <= 1:
                bucket["top1"] += 1
            if rank <= 3:
                bucket["top3"] += 1
            if rank <= 5:
                bucket["top5"] += 1
    return dict(summary)


def _summarize_profile(profile: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(rows)
    clean = sum(1 for row in rows if row.get("status") == "clean")
    review = sum(1 for row in rows if row.get("status") == "review")
    rejected = sum(1 for row in rows if row.get("status") == "rejected")
    top1 = sum(1 for row in rows if row.get("teacher_rank") == 1)
    top3 = sum(1 for row in rows if isinstance(row.get("teacher_rank"), int) and row["teacher_rank"] <= 3)
    top5 = sum(1 for row in rows if isinstance(row.get("teacher_rank"), int) and row["teacher_rank"] <= 5)
    cp_losses = [int(row["cp_loss"]) for row in rows if isinstance(row.get("cp_loss"), int)]
    return {
        "profile": profile,
        "questions": total,
        "clean": clean,
        "review": review,
        "rejected": rejected,
        "clean_rate": round(clean / max(1, total), 4),
        "review_or_better_rate": round((clean + review) / max(1, total), 4),
        "top1": top1,
        "top3": top3,
        "top5": top5,
        "top1_rate": round(top1 / max(1, total), 4),
        "top3_rate": round(top3 / max(1, total), 4),
        "top5_rate": round(top5 / max(1, total), 4),
        "avg_cp_loss": round(sum(cp_losses) / max(1, len(cp_losses)), 3),
        "max_cp_loss": max(cp_losses or [None]),
        "by_category": _category_summary(rows),
    }


def _validate_question_set(questions: list[ValidationQuestion], *, sensitive: bool) -> list[dict[str, Any]]:
    manifest: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, question in enumerate(questions, start=1):
        if question.question_id in seen:
            raise ValueError(f"duplicate question id: {question.question_id}")
        seen.add(question.question_id)
        board = _build_board(question)
        row = {"question_index": index, "category": question.category, "side": _side(board), "ply": board.ply()}
        if sensitive:
            row.update(
                {
                    "question_id": question.question_id,
                    "fen": board.fen(),
                    "moves": list(question.moves),
                    "note": question.note,
                }
            )
        manifest.append(row)
    return manifest


def main() -> int:
    args = parse_args()
    started = time.perf_counter()
    profiles = [item.strip() for item in str(args.profiles or "").split(",") if item.strip()]
    if not profiles:
        raise SystemExit("--profiles must include at least one exp5 search profile")
    all_questions = _load_questions(Path(args.question_set).expanduser())
    questions = list(all_questions[: max(0, int(args.questions or 0))])
    if len(questions) < int(args.questions or 0):
        raise SystemExit(f"requested {args.questions} questions, but only {len(all_questions)} are defined")
    manifest = _validate_question_set(questions, sensitive=bool(args.write_sensitive_output))
    stockfish_path = stockfish_teacher.resolve_stockfish_path(args.stockfish_path)
    if not stockfish_path or not Path(stockfish_path).exists():
        raise SystemExit("Stockfish binary not found; pass --stockfish-path or set STOCKFISH_PATH/HTML_LEARNING_CHESS_STOCKFISH_PATH")

    output_json = Path(args.output_json)
    output_jsonl = Path(args.output_jsonl)
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_jsonl.parent.mkdir(parents=True, exist_ok=True)
    limit = stockfish_teacher.analysis_limit(depth=int(args.depth or 0), movetime_ms=int(args.movetime_ms or 0))
    rows: list[dict[str, Any]] = []

    _progress(f"running {len(questions)} held-out questions with profiles={profiles}, stockfish={stockfish_path}")
    with stockfish_teacher.UciStockfish(stockfish_path) as engine:
        for index, question in enumerate(questions, start=1):
            board = _build_board(question)
            teacher_rows = engine.analyse(board, limit=limit, multipv=max(1, int(args.multipv or 1)))
            if not teacher_rows:
                raise RuntimeError(f"{question.question_id}: Stockfish returned no legal PV rows")
            best_eval = int(teacher_rows[0].get("teacher_eval_cp") or 0)
            teacher_gap_cp = None
            if len(teacher_rows) >= 2:
                teacher_gap_cp = best_eval - int(teacher_rows[1].get("teacher_eval_cp") or 0)
            if args.verbose_questions:
                _progress(f"{index:02d}/{len(questions)} {question.question_id}: teacher best={teacher_rows[0].get('move')}")
            else:
                _progress(f"{index:02d}/{len(questions)} analyzed")
            for profile in profiles:
                decision = choose_experiment_nnue_move(_state_from_board(board), _side(board), search_profile=profile)
                chosen_uci = _move_uci(decision)
                try:
                    chosen_move = chess.Move.from_uci(chosen_uci)
                except Exception:
                    chosen_move = None
                legal = bool(chosen_move and chosen_move in board.legal_moves)
                teacher_match = next((row for row in teacher_rows if str(row.get("move") or "") == chosen_uci), None)
                teacher_rank = int(teacher_match["rank"]) if teacher_match and teacher_match.get("rank") is not None else None
                chosen_eval = int(teacher_match.get("teacher_eval_cp")) if teacher_match and teacher_match.get("teacher_eval_cp") is not None else None
                root_row: dict[str, Any] | None = None
                if legal and teacher_match is None and chosen_move is not None:
                    root_row = _analyse_root_move(engine, board, chosen_move, limit=limit)
                    if root_row.get("teacher_eval_cp") is not None:
                        chosen_eval = int(root_row["teacher_eval_cp"])
                cp_loss = max(0, best_eval - chosen_eval) if chosen_eval is not None else None
                status = "illegal" if not legal else _teacher_audit_status(
                    rank=teacher_rank,
                    cp_loss=cp_loss,
                    accept_topk=int(args.accept_topk or 0),
                    clean_cp_loss=int(args.clean_cp_loss or 0),
                    review_cp_loss=int(args.review_cp_loss or 0),
                )
                if status == "illegal":
                    status = "rejected"
                row = {
                    "question_index": index,
                    "category": question.category,
                    "profile": profile,
                    "side": _side(board),
                    "ply": board.ply(),
                    "legal": legal,
                    "status": status,
                    "teacher_rank": teacher_rank,
                    "teacher_best_eval_cp": best_eval,
                    "teacher_gap_cp": teacher_gap_cp,
                    "chosen_eval_cp": chosen_eval,
                    "cp_loss": cp_loss,
                }
                if args.write_sensitive_output:
                    row.update(
                        {
                            "question_id": question.question_id,
                            "note": question.note,
                            "fen": board.fen(),
                            "moves": list(question.moves),
                            "chosen_move": chosen_uci,
                            "teacher_best_move": str(teacher_rows[0].get("move") or ""),
                            "teacher_top": teacher_rows,
                            "root_row": root_row,
                            "decision": decision,
                        }
                    )
                rows.append(row)

    summaries = [_summarize_profile(profile, [row for row in rows if row.get("profile") == profile]) for profile in profiles]
    report = {
        "created_at": _now(),
        "script": "scripts/games/chess_exp5_validation_probe.py",
        "purpose": "held_out_stockfish_teacher_validation",
        "question_count": len(questions),
        "question_policy": "sensitive local line-ending/key positions; not used by exp5 gauntlet scoring or model priors",
        "sensitive_output_written": bool(args.write_sensitive_output),
        "question_set_path": str(Path(args.question_set).expanduser()) if args.write_sensitive_output else "redacted",
        "teacher": {
            "backend": "stockfish_uci",
            "path": stockfish_path,
            "reference": stockfish_teacher.stockfish_reference(stockfish_path),
            "limit": limit,
            "multipv": int(args.multipv or 1),
            "accept_topk": int(args.accept_topk or 0),
            "clean_cp_loss": int(args.clean_cp_loss or 0),
            "review_cp_loss": int(args.review_cp_loss or 0),
        },
        "profiles": profiles,
        "summary": summaries,
        "manifest": manifest,
        "elapsed_ms": round((time.perf_counter() - started) * 1000.0, 3),
    }
    output_json.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    with output_jsonl.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    _progress(f"wrote {output_json}")
    _progress(f"wrote {output_jsonl}")
    print(json.dumps({"output_json": str(output_json), "output_jsonl": str(output_jsonl), "summary": summaries}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
