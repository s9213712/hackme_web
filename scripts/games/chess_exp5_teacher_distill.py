#!/usr/bin/env python3
"""Distill teacher chess moves into exp5 NNUE-like FEN/move samples."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

import chess


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.games.chess_nnue import (  # noqa: E402
    build_experiment_nnue_sample_from_position,
    default_chess_nnue_model_path,
    rank_experiment_nnue_policy_moves,
)
from services.games.chess_opening_book import book_candidates_for_chess_board  # noqa: E402
from services.games.chess_search import ZobristHasher, search_best_move  # noqa: E402
from services.games import chess_stockfish_teacher as stockfish_teacher  # noqa: E402
from services.games.self_play_training import (  # noqa: E402
    DEFAULT_TEACHER_DEPTH,
    _teacher_static_eval,
    _teacher_move_order,
    choose_teacher_move,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Distill teacher moves into exp5-compatible JSONL samples.")
    parser.add_argument("--input-jsonl", action="append", default=[], help="JSONL rows containing fen (+ optional side/weight/target).")
    parser.add_argument("--output-jsonl", required=True, help="Destination exp5 FEN/move JSONL.")
    parser.add_argument("--teacher-depth", type=int, default=DEFAULT_TEACHER_DEPTH)
    parser.add_argument(
        "--teacher-backend",
        default="static_depth3",
        choices=["static_depth3", "deeper_ab", "opening_book", "stockfish"],
        help=(
            "Teacher source for top1 labels. static_depth3 preserves the legacy self-play teacher; "
            "deeper_ab ranks root moves with a deeper alpha-beta static teacher; opening_book uses "
            "the curated deterministic opening book when available; stockfish uses UCI MultiPV when "
            "a local stockfish binary is available."
        ),
    )
    parser.add_argument(
        "--stockfish-path",
        default="",
        help="Path to a local Stockfish-compatible UCI binary for --teacher-backend stockfish. Defaults to $STOCKFISH_PATH or PATH lookup.",
    )
    parser.add_argument(
        "--stockfish-movetime-ms",
        type=int,
        default=80,
        help="Optional movetime for stockfish MultiPV labeling. If <=0, only --teacher-depth is used.",
    )
    parser.add_argument("--target", type=float, default=1.0)
    parser.add_argument("--weight", type=float, default=1.4)
    parser.add_argument("--source", default="teacher_distill_exp5")
    parser.add_argument("--replace-output", action="store_true")
    parser.add_argument("--max-samples", type=int, default=0)
    parser.add_argument(
        "--baseline-model-path",
        default="",
        help="Optional baseline NNUE model for emitting baseline_top1/top1_score and the label_quality classification (defaults to the bundled exp5 baseline).",
    )
    parser.add_argument(
        "--label-quality-far-above-cp",
        type=float,
        default=250.0,
        help="If baseline_top1_score minus baseline-eval-of-teacher-move is >= this many cp, label_quality=questionable.",
    )
    parser.add_argument(
        "--label-quality-review-cp",
        type=float,
        default=80.0,
        help="If baseline_top1 disagrees with teacher and the gap is between review_cp and far_above_cp, label_quality=review.",
    )
    parser.add_argument(
        "--drop-questionable",
        action="store_true",
        help="When set, label_quality=questionable rows are excluded from the output JSONL (still reported in the quality_audit).",
    )
    parser.add_argument(
        "--teacher-top-k",
        type=int,
        default=5,
        help="Emit teacher_top3/teacher_top5 (top-K is min of this and legal-move count) based on a 1-ply teacher static eval ranking.",
    )
    parser.add_argument(
        "--audit-jsonl",
        default="",
        help="Optional path to write per-row label-quality audit JSONL.",
    )
    parser.add_argument(
        "--baseline-probe-profile",
        default="fixed_depth_fast",
        help=(
            "Search profile used by the baseline NNUE policy probe for label-quality audit. "
            "Default fixed_depth_fast for determinism; do NOT use a timed profile here or the "
            "label-quality audit will inherit time-budget noise."
        ),
    )
    parser.add_argument(
        "--source-category",
        default="external",
        choices=["benchmark", "teacher_guidance", "self_play", "imported_dataset", "external", "user_games"],
        help=(
            "Maps to a baseline confidence_score per exp3 _confidence_score (benchmark 0.98, "
            "teacher_guidance 0.95, self_play 0.9, imported_dataset 0.88, external 0.75, user_games 0.42). "
            "Default external (0.75) because exp5's distill input is typically positions extracted from another experiment."
        ),
    )
    parser.add_argument(
        "--quarantine-jsonl",
        default="",
        help=(
            "Optional separate output for label_quality=questionable rows. Mirrors exp3's quarantine ledger so a "
            "future prepare-step can opt-in to re-mix them at reduced weight."
        ),
    )
    parser.add_argument(
        "--eval-mod",
        type=int,
        default=0,
        help=(
            "When >0, each row receives a deterministic split bucket via int(position_id[:8], 16) %% eval_mod; "
            "bucket=0 → eval, otherwise → train. Default 0 (disabled)."
        ),
    )
    return parser.parse_args()


_SOURCE_CATEGORY_CONFIDENCE = {
    "benchmark": 0.98,
    "teacher_guidance": 0.95,
    "self_play": 0.90,
    "imported_dataset": 0.88,
    "external": 0.75,
    "user_games": 0.42,
}


def _position_id(fen: str, side: str) -> str:
    """Stable per-position id v2.

    Includes:
      - board piece placement (`board.board_fen()`)
      - side-to-move on the board
      - castling rights (`board.castling_xfen()` — "KQkq" / "-" / etc.)
      - en passant square (uci square name or "-")
      - the row's `side` field (the side whose move we are training on)

    Castling rights and en-passant square change legal move semantics, so two
    boards with identical piece placement but different rights are NOT the
    same training position.
    """
    try:
        board = chess.Board(fen)
        ep = chess.square_name(board.ep_square) if board.ep_square is not None else "-"
        normalized = "|".join([
            board.board_fen(),
            "w" if board.turn else "b",
            board.castling_xfen() or "-",
            ep,
            side.strip().lower(),
        ])
    except Exception:
        normalized = f"{fen}|{side}"
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


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


def _teacher_top_k(board: chess.Board, side: str, *, k: int) -> list[dict]:
    """Rank legal moves by the teacher's 1-ply static eval. Returns top-K with scores."""
    color_sign = 1 if side == "white" else -1
    scored: list[tuple[str, int]] = []
    for move in board.legal_moves:
        after = board.copy(stack=False)
        after.push(move)
        if after.is_checkmate():
            eval_score = 1_000_000
        else:
            eval_score = color_sign * _teacher_static_eval(after)
        scored.append((move.uci(), int(eval_score)))
    scored.sort(key=lambda item: (-item[1], item[0]))
    return [{"move": uci, "teacher_eval_cp": int(score)} for uci, score in scored[: max(0, int(k))]]


def _move_payload_to_uci(payload: dict | None) -> str:
    if not isinstance(payload, dict):
        return ""
    return f"{payload.get('from') or ''}{payload.get('to') or ''}{payload.get('promotion') or ''}".lower()


def _deeper_ab_top_k(board: chess.Board, side: str, *, depth: int, k: int) -> list[dict]:
    color_sign = 1 if side == "white" else -1
    ranked: list[tuple[int, str]] = []
    for move in board.legal_moves:
        after = board.copy(stack=False)
        after.push(move)
        if after.is_checkmate():
            score = 1_000_000
        elif after.is_stalemate() or after.is_insufficient_material():
            score = 0
        else:
            search = search_best_move(
                after,
                max_depth=max(1, int(depth or DEFAULT_TEACHER_DEPTH) - 1),
                evaluate=_teacher_static_eval,
                move_order_fn=lambda current_board, candidate, _ply: _teacher_move_order(current_board, candidate),
                hasher=ZobristHasher(seed=20260531),
                quiescence_depth=2,
                time_budget_ms=None,
            )
            score = -int(search.score)
        # Keep the same white/black-positive convention used by _teacher_top_k
        # in the output field name, but rank by the mover's perspective.
        ranked.append((score if color_sign else score, move.uci()))
    ranked.sort(key=lambda item: (-item[0], item[1]))
    return [{"move": uci, "teacher_eval_cp": int(score)} for score, uci in ranked[: max(0, int(k))]]


def _opening_book_top_k(board: chess.Board, *, k: int) -> list[dict]:
    rows: list[dict] = []
    for item in book_candidates_for_chess_board(board, max_candidates=max(1, int(k))):
        uci = str(item.get("uci") or "").strip().lower()
        if not uci:
            continue
        # Convert weighted book frequency into a monotonic pseudo-cp score so
        # downstream code can retain a single teacher_topK shape.
        rows.append({"move": uci, "teacher_eval_cp": int(item.get("weight") or 0) * 100})
    return rows


def _stockfish_top_k(
    board: chess.Board,
    *,
    k: int,
    depth: int,
    stockfish_path: str,
    movetime_ms: int,
) -> tuple[list[dict], str]:
    engine_path = _resolve_stockfish_path(stockfish_path)
    if not engine_path:
        return [], "stockfish_binary_not_found"
    try:
        rows = stockfish_teacher.stockfish_top_k(
            board,
            stockfish_path=engine_path,
            k=max(1, int(k)),
            depth=int(depth or 0),
            movetime_ms=int(movetime_ms or 0),
        )
    except Exception as exc:
        return [], f"stockfish_error:{exc.__class__.__name__}"
    return [{"move": str(row.get("move") or ""), "teacher_eval_cp": int(row.get("teacher_eval_cp") or 0)} for row in rows], ""


def _teacher_top_weights_from_ranking(ranking: list[dict]) -> dict[str, float]:
    if not ranking:
        return {}
    best_score = ranking[0].get("teacher_eval_cp")
    weights: dict[str, float] = {}
    for index, item in enumerate(ranking[:5]):
        move = str(item.get("move") or "").strip().lower()
        if not move:
            continue
        score = item.get("teacher_eval_cp")
        if best_score is None or score is None:
            weight = 1.0 if index == 0 else 0.8 if index == 1 else 0.6 if index == 2 else 0.3
        else:
            loss = max(0.0, float(best_score) - float(score))
            if index == 0:
                weight = 1.0
            elif loss <= 25:
                weight = 0.85
            elif loss <= 60:
                weight = 0.65
            elif loss <= 120:
                weight = 0.35
            else:
                weight = 0.15
        weights[move] = round(float(weight), 4)
    return weights


def _source_move_hard_negatives(row: dict, board: chess.Board, teacher_move: str, teacher_top5: list[str]) -> list[str]:
    hard_negatives = [str(item).strip().lower() for item in (row.get("hard_negatives") or []) if str(item).strip()]
    source_move = str(row.get("move_uci") or row.get("uci") or row.get("move") or "").strip().lower()
    if not source_move or source_move == teacher_move or source_move in teacher_top5:
        return hard_negatives
    try:
        move = chess.Move.from_uci(source_move)
    except Exception:
        return hard_negatives
    if move in board.legal_moves and move.uci() not in hard_negatives:
        hard_negatives.append(move.uci())
    return hard_negatives


def _select_teacher_move_and_topk(
    *,
    board: chess.Board,
    side: str,
    backend: str,
    teacher_depth: int,
    teacher_top_k: int,
    stockfish_path: str,
    stockfish_movetime_ms: int,
) -> tuple[str, list[dict], dict]:
    requested = str(backend or "static_depth3").strip().lower()
    k = max(3, int(teacher_top_k or 5))
    meta = {
        "teacher_backend_requested": requested,
        "teacher_backend_used": requested,
        "teacher_backend_fallback_reason": "",
        "teacher_top_k_method": "",
    }
    if requested == "opening_book":
        ranking = _opening_book_top_k(board, k=k)
        if ranking:
            meta["teacher_top_k_method"] = "deterministic_opening_book"
            return ranking[0]["move"], ranking, meta
        meta["teacher_backend_fallback_reason"] = "opening_book_miss"
        meta["teacher_backend_used"] = "static_depth3"
    elif requested == "stockfish":
        ranking, reason = _stockfish_top_k(
            board,
            k=k,
            depth=max(1, int(teacher_depth or DEFAULT_TEACHER_DEPTH)),
            stockfish_path=stockfish_path,
            movetime_ms=int(stockfish_movetime_ms or 0),
        )
        if ranking:
            meta["teacher_top_k_method"] = "stockfish_multipv"
            return ranking[0]["move"], ranking, meta
        meta["teacher_backend_fallback_reason"] = reason or "stockfish_no_move"
        meta["teacher_backend_used"] = "deeper_ab"
        requested = "deeper_ab"

    if requested == "deeper_ab":
        ranking = _deeper_ab_top_k(
            board,
            side,
            depth=max(2, int(teacher_depth or DEFAULT_TEACHER_DEPTH)),
            k=k,
        )
        if ranking:
            meta["teacher_top_k_method"] = "deeper_alpha_beta_static_eval"
            meta["teacher_backend_used"] = "deeper_ab"
            return ranking[0]["move"], ranking, meta
        meta["teacher_backend_fallback_reason"] = meta["teacher_backend_fallback_reason"] or "deeper_ab_no_move"
        meta["teacher_backend_used"] = "static_depth3"

    payload = choose_teacher_move({"__fen__": board.fen()}, side, depth=max(1, int(teacher_depth or DEFAULT_TEACHER_DEPTH)))
    move_uci = _move_payload_to_uci(payload)
    ranking = _teacher_top_k(board, side, k=k)
    if move_uci and move_uci not in {row["move"] for row in ranking}:
        ranking.insert(0, {"move": move_uci, "teacher_eval_cp": None})
    meta["teacher_top_k_method"] = "static_depth_ab_top1_plus_one_ply_static_topk"
    meta["teacher_backend_used"] = "static_depth3"
    return move_uci, ranking[:k], meta


def _baseline_policy_probe(
    *, fen: str, side: str, teacher_move_uci: str, baseline_model_path: Path,
    probe_profile: str = "fixed_depth_fast",
) -> dict:
    """Use the bundled NNUE policy ranker to surface baseline top1/top1_score and the
    raw_policy_score the baseline gives to the teacher move.

    Note: `rank_experiment_nnue_policy_moves` does NOT run alpha-beta search — it
    enumerates legal moves and scores each via the static NNUE evaluator. The
    profile only carries through if the caller later upgrades the ranker to a
    search-based ranker; for now we record the profile so timed-noise concerns
    are explicit. The default is `fixed_depth_fast` for determinism.
    """
    rows = rank_experiment_nnue_policy_moves(
        {"__fen__": fen},
        side,
        model_path=baseline_model_path,
        search_profile=str(probe_profile or "fixed_depth_fast"),
    )
    if not rows:
        return {"baseline_top1": "", "baseline_top1_score": 0.0, "baseline_teacher_score": 0.0, "baseline_teacher_rank": 0}
    top = rows[0]
    teacher_row = next((row for row in rows if str(row.get("move") or "") == teacher_move_uci), None)
    return {
        "baseline_top1": str(top.get("move") or ""),
        "baseline_top1_score": float(top.get("raw_policy_score") or 0.0),
        "baseline_teacher_score": float((teacher_row or {}).get("raw_policy_score") or 0.0),
        "baseline_teacher_rank": int((teacher_row or {}).get("raw_policy_rank") or 0),
    }


def _classify_label_quality(
    *, baseline_top1_score: float, baseline_teacher_score: float,
    baseline_top1: str, teacher_move: str,
    far_above_cp: float, review_cp: float,
) -> tuple[str, float, bool, str]:
    """Classify a row by the *baseline policy gap* — the centipawn gap between the
    baseline NNUE's top-1 move and the teacher move under the baseline's eval.

    A large gap does NOT prove the teacher is wrong; it means the cheap NNUE
    eval cannot justify the teacher's choice. We label such rows
    `questionable_by_baseline_policy_gap` and let the caller decide whether to
    drop them from the training target.
    """
    gap = float(baseline_top1_score) - float(baseline_teacher_score)
    questionable_by_baseline_policy_gap = gap >= float(far_above_cp)
    if baseline_top1 == teacher_move:
        quality = "clean"
        reason = "baseline_top1_matches_teacher"
    elif questionable_by_baseline_policy_gap:
        quality = "questionable"
        reason = "questionable_by_baseline_policy_gap"
    elif gap >= float(review_cp):
        quality = "review"
        reason = "baseline_policy_gap_in_review_window"
    else:
        quality = "clean"
        reason = "baseline_policy_gap_within_clean_window"
    return quality, gap, questionable_by_baseline_policy_gap, reason


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


def _distill_row(
    row: dict,
    *,
    teacher_depth: int,
    default_target: float,
    default_weight: float,
    default_source: str,
    baseline_model_path: Path | None = None,
    far_above_cp: float = 250.0,
    review_cp: float = 80.0,
    teacher_top_k: int = 5,
    baseline_probe_profile: str = "fixed_depth_fast",
    source_category: str = "external",
    eval_mod: int = 0,
    teacher_backend: str = "static_depth3",
    stockfish_path: str = "",
    stockfish_movetime_ms: int = 80,
) -> tuple[dict | None, dict]:
    fen = str(row.get("fen") or row.get("board_fen") or "").strip()
    if not fen:
        return None, {"accepted": False, "reason": "missing_fen"}
    side = _side_from_row(row, fen)
    try:
        board = chess.Board(fen)
        board.turn = chess.WHITE if side == "white" else chess.BLACK
    except Exception:
        return None, {"accepted": False, "reason": "invalid_fen", "fen": fen, "side": side}
    move_uci, teacher_ranking, teacher_meta = _select_teacher_move_and_topk(
        board=board,
        side=side,
        backend=teacher_backend,
        teacher_depth=int(teacher_depth),
        teacher_top_k=int(teacher_top_k),
        stockfish_path=str(stockfish_path or ""),
        stockfish_movetime_ms=int(stockfish_movetime_ms or 0),
    )
    if not move_uci:
        return None, {"accepted": False, "reason": "teacher_no_move", "fen": fen, "side": side}
    quality = _teacher_move_quality(fen=fen, side=side, move_uci=move_uci)
    if not quality["legal"]:
        return None, {"accepted": False, "reason": "illegal_teacher_move", "fen": fen, "side": side, "move_uci": move_uci, "quality": quality}
    if quality["suspicious"]:
        return None, {"accepted": False, "reason": "suspicious_teacher_move", "fen": fen, "side": side, "move_uci": move_uci, "quality": quality}

    top_k = max(3, int(teacher_top_k or 0))
    teacher_top3 = [item["move"] for item in teacher_ranking[:3]]
    teacher_top5 = [item["move"] for item in teacher_ranking[:5]]
    teacher_top3_present = move_uci in teacher_top3
    teacher_eval_of_teacher_move = next(
        (item["teacher_eval_cp"] for item in teacher_ranking if item["move"] == move_uci),
        None,
    )
    teacher_top_eval_cp = teacher_ranking[0].get("teacher_eval_cp") if teacher_ranking else None
    teacher_second_eval_cp = teacher_ranking[1].get("teacher_eval_cp") if len(teacher_ranking) > 1 else None
    teacher_margin_to_top2_cp = (
        float(teacher_top_eval_cp) - float(teacher_second_eval_cp)
        if teacher_top_eval_cp is not None and teacher_second_eval_cp is not None
        else None
    )

    baseline_probe = _baseline_policy_probe(
        fen=fen, side=side, teacher_move_uci=move_uci,
        baseline_model_path=baseline_model_path or default_chess_nnue_model_path(),
        probe_profile=str(baseline_probe_profile or "fixed_depth_fast"),
    )
    label_quality, baseline_policy_gap_cp, questionable_by_gap, label_quality_reason = _classify_label_quality(
        baseline_top1_score=baseline_probe["baseline_top1_score"],
        baseline_teacher_score=baseline_probe["baseline_teacher_score"],
        baseline_top1=baseline_probe["baseline_top1"],
        teacher_move=move_uci,
        far_above_cp=far_above_cp,
        review_cp=review_cp,
    )

    sample = build_experiment_nnue_sample_from_position(
        fen=fen,
        side=side,
        move_uci=move_uci,
        target=float(row.get("target", default_target)),
        weight=float(row.get("weight", default_weight)),
        source=str(row.get("source") or default_source),
        hard_negatives=_source_move_hard_negatives(row, board, move_uci, teacher_top5),
        search_profile=str(row.get("search_profile") or "fast"),
    )
    if sample is None:
        return None, {"accepted": False, "reason": "sample_normalization_failed", "fen": fen, "side": side, "move_uci": move_uci, "quality": quality}

    # Enrich the sample with label-quality + teacher_top3/top5 fields so the
    # downstream trainer's auto-hard-negative logic can honour them.
    # NOTE: teacher_top3 / teacher_top5 are produced by a *1-ply static teacher
    # eval ranker* (see `_teacher_top_k`), NOT a deep alpha-beta search. The
    # `static_teacher_top_k` flag below documents that explicitly so consumers
    # don't treat the ranking as the teacher's true search-strength top-K.
    sample["teacher_top3"] = teacher_top3
    sample["teacher_top5"] = teacher_top5
    sample["teacher_top_weights"] = _teacher_top_weights_from_ranking(teacher_ranking)
    sample["teacher_backend"] = teacher_meta["teacher_backend_used"]
    sample["teacher_backend_requested"] = teacher_meta["teacher_backend_requested"]
    sample["teacher_backend_fallback_reason"] = teacher_meta["teacher_backend_fallback_reason"]
    sample["teacher_top_k_method"] = teacher_meta["teacher_top_k_method"]
    sample["static_teacher_top_k"] = teacher_meta["teacher_top_k_method"] == "static_depth_ab_top1_plus_one_ply_static_topk"
    sample["teacher_eval_cp"] = teacher_eval_of_teacher_move
    sample["teacher_top_eval_cp"] = teacher_top_eval_cp
    sample["teacher_margin_to_top2_cp"] = teacher_margin_to_top2_cp
    sample["teacher_score_available"] = teacher_eval_of_teacher_move is not None and not sample["static_teacher_top_k"]
    sample["source_move_uci"] = str(row.get("move_uci") or row.get("uci") or row.get("move") or "").strip().lower()
    sample["source_move_promoted_to_hard_negative"] = sample["source_move_uci"] in set(sample.get("hard_negatives") or [])
    sample["baseline_top1"] = baseline_probe["baseline_top1"]
    sample["baseline_top1_score"] = baseline_probe["baseline_top1_score"]
    sample["baseline_teacher_score"] = baseline_probe["baseline_teacher_score"]
    sample["baseline_teacher_rank"] = baseline_probe["baseline_teacher_rank"]
    sample["baseline_policy_gap_cp"] = baseline_policy_gap_cp
    sample["label_quality"] = label_quality
    sample["label_quality_reason"] = label_quality_reason
    sample["questionable_by_baseline_policy_gap"] = bool(questionable_by_gap)

    # exp3-style provenance fields so future audits can trace each row to a
    # stable id, source category, and (when enabled) a deterministic train/eval
    # split bucket.
    pos_id = _position_id(fen, side)
    sample["position_id"] = pos_id
    sample["source_category"] = source_category
    sample["confidence_score_baseline"] = _SOURCE_CATEGORY_CONFIDENCE.get(source_category, 0.4)
    if eval_mod and int(eval_mod) > 1:
        bucket = "eval" if (int(pos_id[:8], 16) % int(eval_mod) == 0) else "train"
        sample["dataset_split_bucket"] = bucket
        sample["eval_mod"] = int(eval_mod)

    audit = {
        "accepted": True,
        "included_in_output": True,
        "reason": "accepted",
        "drop_reason": "",
        "fen": fen,
        "side": side,
        "move_uci": move_uci,
        "quality": quality,
        "teacher_top3": teacher_top3,
        "teacher_top5": teacher_top5,
        "teacher_backend": teacher_meta["teacher_backend_used"],
        "teacher_backend_requested": teacher_meta["teacher_backend_requested"],
        "teacher_backend_fallback_reason": teacher_meta["teacher_backend_fallback_reason"],
        "teacher_top_k_method": teacher_meta["teacher_top_k_method"],
        "static_teacher_top_k": teacher_meta["teacher_top_k_method"] == "static_depth_ab_top1_plus_one_ply_static_topk",
        "teacher_eval_cp": teacher_eval_of_teacher_move,
        "teacher_top_eval_cp": teacher_top_eval_cp,
        "teacher_margin_to_top2_cp": teacher_margin_to_top2_cp,
        "teacher_score_available": teacher_eval_of_teacher_move is not None and teacher_meta["teacher_top_k_method"] != "static_depth_ab_top1_plus_one_ply_static_topk",
        "source_move_uci": sample["source_move_uci"],
        "source_move_promoted_to_hard_negative": bool(sample["source_move_promoted_to_hard_negative"]),
        "teacher_top3_contains_teacher_move": bool(teacher_top3_present),
        "baseline_top1": baseline_probe["baseline_top1"],
        "baseline_top1_score": baseline_probe["baseline_top1_score"],
        "baseline_teacher_score": baseline_probe["baseline_teacher_score"],
        "baseline_teacher_rank": baseline_probe["baseline_teacher_rank"],
        "baseline_policy_gap_cp": baseline_policy_gap_cp,
        "label_quality": label_quality,
        "label_quality_reason": label_quality_reason,
        "questionable_by_baseline_policy_gap": bool(questionable_by_gap),
        "position_id": pos_id,
        "source_category": source_category,
        "confidence_score_baseline": _SOURCE_CATEGORY_CONFIDENCE.get(source_category, 0.4),
        "dataset_split_bucket": sample.get("dataset_split_bucket", ""),
    }
    return sample, audit


def _quality_summary(
    *,
    input_rows: int,
    rows: list[dict],
    audit_rows: list[dict],
    rejected_reasons: dict[str, int],
    excluded_questionable_rows: int = 0,
    far_above_cp: float = 250.0,
    review_cp: float = 80.0,
) -> dict:
    unique_keys = {f"{row.get('fen')}|{row.get('side')}|{row.get('move_uci')}" for row in rows}
    legal_count = sum(1 for row in audit_rows if bool((row.get("quality") or {}).get("legal")))
    suspicious_count = sum(1 for row in audit_rows if bool((row.get("quality") or {}).get("suspicious")))
    accepted = len(rows)
    duplicate_ratio = round(0.0 if accepted <= 0 else 1.0 - (len(unique_keys) / accepted), 6)

    classified_audits = [a for a in audit_rows if a.get("label_quality")]
    output_audits = [a for a in classified_audits if a.get("included_in_output")]
    clean_count = sum(1 for a in classified_audits if a.get("label_quality") == "clean")
    review_count = sum(1 for a in classified_audits if a.get("label_quality") == "review")
    questionable_count = sum(1 for a in classified_audits if a.get("label_quality") == "questionable")
    questionable_by_gap_count = sum(
        1 for a in classified_audits if a.get("questionable_by_baseline_policy_gap")
    )
    missing_top3_marker = sum(
        1 for a in classified_audits if not a.get("teacher_top3_contains_teacher_move")
    )
    backend_counts: dict[str, int] = {}
    topk_method_counts: dict[str, int] = {}
    fallback_count = 0
    score_available_count = 0
    for audit in classified_audits:
        backend = str(audit.get("teacher_backend") or "unknown")
        method = str(audit.get("teacher_top_k_method") or "unknown")
        backend_counts[backend] = int(backend_counts.get(backend) or 0) + 1
        topk_method_counts[method] = int(topk_method_counts.get(method) or 0) + 1
        if audit.get("teacher_backend_fallback_reason"):
            fallback_count += 1
        if audit.get("teacher_score_available"):
            score_available_count += 1
    gaps = [
        float(a.get("baseline_policy_gap_cp") or 0.0)
        for a in classified_audits
        if a.get("baseline_policy_gap_cp") is not None
    ]
    baseline_policy_gap_avg = round(sum(gaps) / len(gaps), 4) if gaps else 0.0
    baseline_policy_gap_max = round(max(gaps), 4) if gaps else 0.0

    clean_ratio = round(clean_count / max(1, len(classified_audits)), 6) if classified_audits else 0.0

    return {
        "input_fen_count": int(input_rows),
        "distilled_rows": accepted,
        "duplicate_ratio": duplicate_ratio,
        "legal_teacher_move_rate": round(legal_count / max(1, input_rows), 6),
        "suspicious_teacher_move_rate": round(suspicious_count / max(1, input_rows), 6),
        "teacher_top1_available_rate": round(len(audit_rows) / max(1, input_rows), 6),
        "teacher_score_available_rate": round(score_available_count / max(1, len(classified_audits)), 6) if classified_audits else 0.0,
        "rejected_reasons": rejected_reasons,
        "clean_training_rows": accepted,
        "label_quality_summary": {
            "pass": accepted > 0 and suspicious_count == 0 and legal_count == len(audit_rows),
            "policy": "illegal or suspicious teacher rows are excluded from clean exp5 training targets",
            "raw_rows": int(input_rows),
            "output_rows": int(len(output_audits)),
            "clean_rows": int(clean_count),
            "review_rows": int(review_count),
            "questionable_rows": int(questionable_count),
            "dropped_questionable_rows": int(excluded_questionable_rows),
            "clean_ratio": clean_ratio,
            "questionable_by_baseline_policy_gap_count": int(questionable_by_gap_count),
            "teacher_top3_does_not_contain_teacher_move_count": int(missing_top3_marker),
            "missing_teacher_top3_count": int(missing_top3_marker),
            "teacher_backend_counts": backend_counts,
            "teacher_top_k_method_counts": topk_method_counts,
            "teacher_backend_fallback_count": int(fallback_count),
            "baseline_policy_gap_avg": baseline_policy_gap_avg,
            "baseline_policy_gap_max": baseline_policy_gap_max,
            "far_above_threshold_cp": float(far_above_cp),
            "review_threshold_cp": float(review_cp),
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
    baseline_model_path = (
        Path(args.baseline_model_path).expanduser().resolve()
        if args.baseline_model_path
        else default_chess_nnue_model_path()
    )
    excluded_questionable = 0
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
                baseline_model_path=baseline_model_path,
                far_above_cp=float(args.label_quality_far_above_cp),
                review_cp=float(args.label_quality_review_cp),
                teacher_top_k=int(args.teacher_top_k),
                baseline_probe_profile=str(args.baseline_probe_profile or "fixed_depth_fast"),
                source_category=str(args.source_category or "external"),
                eval_mod=int(args.eval_mod or 0),
                teacher_backend=str(args.teacher_backend or "static_depth3"),
                stockfish_path=str(args.stockfish_path or ""),
                stockfish_movetime_ms=int(args.stockfish_movetime_ms or 0),
            )
            if (
                sample is not None
                and bool(args.drop_questionable)
                and audit.get("label_quality") == "questionable"
            ):
                excluded_questionable += 1
                rejected_reasons["label_questionable_dropped"] = (
                    int(rejected_reasons.get("label_questionable_dropped") or 0) + 1
                )
                audit = dict(audit)
                # row was successfully distilled but is being dropped from the
                # output JSONL — keep the full audit row so a follow-up can see
                # exactly which rows were filtered and why.
                audit["included_in_output"] = False
                audit["drop_reason"] = "questionable_by_baseline_policy_gap"
                audit_rows.append(audit)
                skipped_rows += 1
                continue
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
    quarantine_written = 0
    if args.quarantine_jsonl:
        # Mirror exp3 quarantine ledger: even if --drop-questionable was NOT
        # passed, write the rows that classified as questionable into the
        # quarantine file so a downstream prepare step can opt-in to re-mix
        # them at a reduced weight (e.g. via exp3's `--include-quarantine`).
        quarantine_path = Path(args.quarantine_jsonl).expanduser().resolve()
        quarantine_path.parent.mkdir(parents=True, exist_ok=True)
        with quarantine_path.open("w", encoding="utf-8") as handle:
            for row in rows:
                if str(row.get("label_quality") or "") == "questionable":
                    handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
                    quarantine_written += 1
            # Also include rows we dropped via --drop-questionable so the
            # quarantine ledger is exhaustive even when the output JSONL has
            # already removed them.
            for audit in audit_rows:
                if audit.get("drop_reason") == "questionable_by_baseline_policy_gap":
                    handle.write(
                        json.dumps(
                            {
                                "fen": audit.get("fen"),
                                "side": audit.get("side"),
                                "move_uci": audit.get("move_uci"),
                                "label_quality": audit.get("label_quality"),
                                "label_quality_reason": audit.get("label_quality_reason"),
                                "baseline_policy_gap_cp": audit.get("baseline_policy_gap_cp"),
                                "position_id": audit.get("position_id"),
                                "source_category": audit.get("source_category"),
                                "confidence_score_baseline": audit.get("confidence_score_baseline"),
                                "dataset_split_bucket": audit.get("dataset_split_bucket"),
                                "drop_reason": audit.get("drop_reason"),
                            },
                            ensure_ascii=False,
                            sort_keys=True,
                        )
                        + "\n"
                    )
                    quarantine_written += 1
    if args.audit_jsonl:
        audit_path = Path(args.audit_jsonl).expanduser().resolve()
        audit_path.parent.mkdir(parents=True, exist_ok=True)
        with audit_path.open("w", encoding="utf-8") as handle:
            for row in audit_rows:
                handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    result = {
        "ok": True,
        "engine": "experiment 5:nnue",
        "teacher_depth": int(args.teacher_depth),
        "teacher_backend": str(args.teacher_backend or "static_depth3"),
        "stockfish_path": str(args.stockfish_path or ""),
        "stockfish_movetime_ms": int(args.stockfish_movetime_ms or 0),
        "input_rows": input_rows,
        "input_fen_count": input_rows,
        "accepted_samples": len(rows),
        "distilled_rows": len(rows),
        "skipped_rows": skipped_rows,
        "output_jsonl": str(output_path),
        "sample_format": "exp5_nnue_position_move_v1",
        "retrain_input_compatible": True,
        "baseline_model_path": str(baseline_model_path),
        "drop_questionable": bool(args.drop_questionable),
        "label_quality_far_above_cp": float(args.label_quality_far_above_cp),
        "label_quality_review_cp": float(args.label_quality_review_cp),
        "teacher_top_k": int(args.teacher_top_k),
        "teacher_top_k_method": "backend_dependent",
        "static_teacher_top_k": str(args.teacher_backend or "static_depth3") == "static_depth3",
        "baseline_probe_profile": str(args.baseline_probe_profile or "fixed_depth_fast"),
        "audit_jsonl": str(args.audit_jsonl or ""),
        "quarantine_jsonl": str(args.quarantine_jsonl or ""),
        "quarantine_rows_written": int(quarantine_written),
        "source_category": str(args.source_category or "external"),
        "confidence_score_baseline": _SOURCE_CATEGORY_CONFIDENCE.get(str(args.source_category or "external"), 0.4),
        "eval_mod": int(args.eval_mod or 0),
        "quality_audit": _quality_summary(
            input_rows=input_rows,
            rows=rows,
            audit_rows=audit_rows,
            rejected_reasons=rejected_reasons,
            excluded_questionable_rows=excluded_questionable,
            far_above_cp=float(args.label_quality_far_above_cp),
            review_cp=float(args.label_quality_review_cp),
        ),
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
