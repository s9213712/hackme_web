#!/usr/bin/env python3
"""Run the exp5-specific strength gate for NNUE-like candidates."""

from __future__ import annotations

import argparse
import json
import hashlib
from datetime import datetime
from pathlib import Path
import sys

import chess


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.games.chess_arena import default_chess_reports_dir  # noqa: E402
from services.games.chess_nnue import (  # noqa: E402
    EXPERIMENT_NNUE_DIFFICULTY,
    default_chess_nnue_model_path,
    explain_experiment_nnue_decision,
    rank_experiment_nnue_policy_moves,
    choose_experiment_nnue_move,
)
from services.games.chess_promotion import promotion_report_consistency  # noqa: E402


EXP5_STRENGTH_CASES = (
    {
        "id": "baseline_castling_awareness",
        "fen": "r3k2r/8/8/8/8/8/4PPPP/R3K2R b KQkq - 0 1",
        "side": "black",
        "expected_uci_any": ["e8c8", "e8g8"],
        "category": "tactic",
    },
    {
        "id": "mate_in_one_white",
        "fen": "6k1/5Q2/6K1/8/8/8/8/8 w - - 0 1",
        "side": "white",
        "expected_uci_any": ["f7e8", "f7f8"],
        "must_checkmate": True,
    },
    {
        "id": "mate_in_one_black",
        "fen": "8/8/8/8/8/6k1/5q2/6K1 b - - 0 1",
        "side": "black",
        "expected_uci_any": ["f2e1", "f2f1"],
        "must_checkmate": True,
    },
    {
        "id": "forced_queen_capture",
        "fen": "4k3/4Q3/8/8/8/8/8/4K3 b - - 0 1",
        "side": "black",
        "expected_uci_any": ["e8e7"],
        "requires_capture": True,
        "min_material_gain": 800,
    },
    {
        "id": "king_safety_capture",
        "fen": "4k3/8/8/8/8/8/4q3/4K1R1 w - - 0 1",
        "side": "white",
        "expected_uci_any": ["e1e2"],
        "requires_capture": True,
        "min_material_gain": 800,
    },
    {
        "id": "avoid_stalemate",
        "fen": "k7/3Q4/2K5/8/8/8/8/8 w - - 0 1",
        "side": "white",
        "must_not_stalemate": True,
    },
    {
        "id": "promotion_white",
        "fen": "k7/4P3/2K5/8/8/8/8/8 w - - 0 1",
        "side": "white",
        "must_promote": True,
        "expected_promotion": "q",
    },
)

_PIECE_VALUES = {
    chess.PAWN: 100,
    chess.KNIGHT: 320,
    chess.BISHOP: 335,
    chess.ROOK: 500,
    chess.QUEEN: 900,
    chess.KING: 20000,
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Exp5 deterministic strength gate.")
    parser.add_argument("--candidate-model-path", default="")
    parser.add_argument("--baseline-model-path", default="")
    parser.add_argument("--strength-cases-jsonl", action="append", default=[], help="Optional case set JSONL (default built-in deterministic cases).")
    parser.add_argument("--train-rows-jsonl", action="append", default=[], help="Optional distilled rows for per-row train agreement sanity.")
    parser.add_argument("--held-out-rows-jsonl", action="append", default=[], help="Optional held-out rows for leakage guard.")
    parser.add_argument("--benchmark-report-path", default="")
    parser.add_argument("--output-dir", default="")
    parser.add_argument("--min-case-pass-rate", type=float, default=0.70)
    parser.add_argument("--min-benchmark-score-rate", type=float, default=0.45)
    parser.add_argument("--min-benchmark-games", type=int, default=2)
    parser.add_argument("--search-profile", default="strong")
    return parser.parse_args()


def _progress(message: str) -> None:
    print(f"[chess-exp5-strength-gate] {message}", file=sys.stderr, flush=True)


def _move_to_uci(move: dict | None) -> str:
    if not move:
        return ""
    return f"{move.get('from') or ''}{move.get('to') or ''}{move.get('promotion') or ''}".lower()


def _material_score(board: chess.Board) -> int:
    score = 0
    for piece in board.piece_map().values():
        value = _PIECE_VALUES[piece.piece_type]
        score += value if piece.color == chess.WHITE else -value
    return score


def _material_gain(board_before: chess.Board, board_after: chess.Board, side: str) -> int:
    delta = _material_score(board_after) - _material_score(board_before)
    return delta if side == "white" else -delta


def _iter_jsonl_rows(paths: list[Path]) -> list[dict]:
    rows: list[dict] = []
    for input_path in paths:
        if not input_path.exists():
            continue
        for line_no, line in enumerate(input_path.read_text(encoding="utf-8").splitlines(), start=1):
            if not line.strip():
                continue
            try:
                payload = json.loads(line)
            except Exception as exc:
                raise ValueError(f"{input_path}:{line_no}: invalid JSON: {exc}") from exc
            if not isinstance(payload, dict):
                raise ValueError(f"{input_path}:{line_no}: row must be an object")
            rows.append(payload)
    return rows


def _normalize_case_input(raw: dict) -> dict:
    teacher_move = raw.get("teacher_move")
    expected = raw.get("teacher_top3") or raw.get("teacher_top_moves")
    if teacher_move:
        if isinstance(expected, (list, tuple)):
            expected_uci_any = [str(item).lower() for item in expected if str(item).strip()]
            if str(teacher_move).strip().lower() not in expected_uci_any:
                expected_uci_any.insert(0, str(teacher_move).strip().lower())
        else:
            expected_uci_any = [str(teacher_move).strip().lower()]
    else:
        expected_uci_any = [str(item).lower() for item in (raw.get("expected_uci_any") or []) if str(item).strip()]
    fen = str(raw.get("fen") or "").strip()
    side = str(raw.get("side") or ("white" if " w " in fen else "black")).strip().lower()
    return {
        "id": str(raw.get("id") or f"case_{hashlib.sha256((fen + side).encode('utf-8')).hexdigest()[:12]}"),
        "fen": fen,
        "side": side,
        "category": str(raw.get("category") or ""),
        "expected_uci_any": expected_uci_any,
        "must_checkmate": bool(raw.get("must_checkmate")),
        "requires_capture": bool(raw.get("requires_capture")),
        "must_not_stalemate": bool(raw.get("must_not_stalemate")),
        "must_promote": bool(raw.get("must_promote")),
        "expected_promotion": str(raw.get("expected_promotion") or "").lower(),
        "min_material_gain": raw.get("min_material_gain"),
        "teacher_move": str(teacher_move or "").strip().lower(),
        "teacher_top3": [str(item).lower() for item in (raw.get("teacher_top3") or []) if str(item).strip()],
        "teacher_score": float(raw.get("teacher_score") or 0.0),
        "baseline_teacher_disagreement": bool(raw.get("baseline_teacher_disagreement") or False),
        "label_quality": str(raw.get("label_quality") or "clean"),
        "confidence": float(raw.get("confidence") or 0.0),
    }


def _normalize_strength_cases(paths: list[Path]) -> list[dict]:
    cases = [_normalize_case_input(dict(case)) for case in EXP5_STRENGTH_CASES]
    if not paths:
        return cases
    custom = [_normalize_case_input(dict(row)) for row in _iter_jsonl_rows(paths)]
    return custom or cases


def _policy_probe_for_move(model_path: Path, fen: str, side: str, move_uci: str, *, search_profile: str) -> dict:
    rows = rank_experiment_nnue_policy_moves(
        {"__fen__": fen},
        side,
        model_path=model_path,
        search_profile=search_profile,
    )
    if not rows:
        return {
            "exists": False,
            "raw_policy_rank": 0,
            "raw_policy_score": 0.0,
            "policy_probability": 0.0,
            "top_move": "",
            "top_score": 0.0,
            "top1_gap": 0.0,
        }
    top = rows[0]
    move = str(move_uci).strip().lower()
    row = next((item for item in rows if str(item.get("move") or "") == move), None)
    raw_top_score = float(top.get("raw_policy_score") or 0.0)
    raw_row_score = float(row.get("raw_policy_score") or 0.0) if row is not None else 0.0
    return {
        "exists": bool(row),
        "raw_policy_rank": int((row or {}).get("raw_policy_rank") or 0),
        "raw_policy_score": float(raw_row_score),
        "policy_probability": float((row or {}).get("policy_probability") or 0.0) if row is not None else 0.0,
        "top_move": str(top.get("move") or ""),
        "top_score": raw_top_score,
        "top1_gap": round(raw_row_score - raw_top_score, 8) if row is not None else 0.0,
    }


def _score_for_move(row: dict | None) -> float:
    if not isinstance(row, dict):
        return 0.0
    return 1.0 if bool(row.get("pass")) else 0.0


def _case_category(case: dict) -> str:
    explicit = str(case.get("category") or "").strip().lower()
    if explicit in {"tactic", "endgame", "smoke", "opening", "blunder_avoid", "teacher_hard", "baseline_teacher_disagreement", "quiet_positional"}:
        return explicit
    if case.get("must_checkmate") or case.get("requires_capture"):
        return "tactic"
    if case.get("must_promote") or case.get("must_not_stalemate"):
        return "endgame"
    return "smoke"


def _evaluate_model_case(model_path: Path, case: dict, *, search_profile: str) -> dict:
    board_before = chess.Board(str(case["fen"]))
    side = str(case["side"])
    move = choose_experiment_nnue_move({"__fen__": board_before.fen()}, side, model_path=model_path, search_profile=search_profile)
    chosen = _move_to_uci(move)
    reasons: list[str] = []
    board_after = board_before.copy(stack=False)
    legal = False
    material_gain = 0
    if not chosen:
        reasons.append("engine_no_move")
    else:
        try:
            chess_move = chess.Move.from_uci(chosen)
        except Exception:
            chess_move = None
        if chess_move is None or chess_move not in board_before.legal_moves:
            reasons.append("illegal_move")
        else:
            legal = True
            board_after.push(chess_move)
            material_gain = _material_gain(board_before, board_after, side)
            expected = [str(item).lower() for item in (case.get("expected_uci_any") or [])]
            if expected and chosen not in expected:
                reasons.append("unexpected_move")
            if case.get("requires_capture") and not board_before.is_capture(chess_move):
                reasons.append("capture_required")
            if case.get("must_checkmate") and not board_after.is_checkmate():
                reasons.append("mate_not_found")
            if case.get("must_not_stalemate") and board_after.is_stalemate():
                reasons.append("stalemate_after_move")
            if case.get("must_promote") and not chess_move.promotion:
                reasons.append("promotion_required")
            expected_promotion = str(case.get("expected_promotion") or "").lower()
            promotion = chess.piece_symbol(chess_move.promotion).lower() if chess_move.promotion else ""
            if expected_promotion and promotion != expected_promotion:
                reasons.append("unexpected_promotion_piece")
            if case.get("min_material_gain") is not None and material_gain < int(case["min_material_gain"]):
                reasons.append("material_gain_below_min")
    explanation = explain_experiment_nnue_decision(
        {"__fen__": str(case["fen"])},
        side,
        model_path=model_path,
        search_profile=search_profile,
        watched_moves=[chosen] if chosen else [],
    )
    policy_probe = _policy_probe_for_move(model_path, board_before.fen(), side, chosen, search_profile=search_profile) if chosen else {}
    teacher_probe = _policy_probe_for_move(
        model_path,
        board_before.fen(),
        side,
        str((case.get("expected_uci_any") or [""])[0]),
        search_profile=search_profile,
    )
    expected = [str(item).lower() for item in (case.get("expected_uci_any") or [])]
    teacher_agreement = bool(chosen in expected) if expected else bool(not reasons)
    return {
        "pass": not reasons,
        "reasons": reasons,
        "chosen_move": chosen,
        "selected_reason": str(explanation.get("chosen_reason") or ""),
        "legal": legal,
        "suspicious": bool((not legal) or "stalemate_after_move" in reasons),
        "teacher_agreement": teacher_agreement,
        "pvs_selected_move": bool(chosen and legal),
        "material_gain": material_gain,
        "rank_for_chosen": int(policy_probe.get("raw_policy_rank") or 0),
        "score_for_chosen": float(policy_probe.get("raw_policy_score") or 0.0),
        "policy_probability_for_chosen": float(policy_probe.get("policy_probability") or 0.0),
        "top_move": str(policy_probe.get("top_move") or ""),
        "top_score": float(policy_probe.get("top_score") or 0.0),
        "margin_vs_top": float(policy_probe.get("top1_gap") or 0.0),
        "top_moves": explanation.get("top_final_moves", [])[:3],
        "final_fen": board_after.fen() if legal else board_before.fen(),
        "teacher_move": str((case.get("teacher_move") or (expected[0] if expected else ""))),
        "teacher_rank": int(teacher_probe.get("raw_policy_rank") or 0),
        "teacher_score": float(teacher_probe.get("raw_policy_score") or 0.0),
        "teacher_probability": float(teacher_probe.get("policy_probability") or 0.0),
    }


def _evaluate_case(candidate_path: Path, baseline_path: Path, case: dict, *, search_profile: str) -> dict:
    baseline = _evaluate_model_case(baseline_path, case, search_profile=search_profile)
    candidate = _evaluate_model_case(candidate_path, case, search_profile=search_profile)
    baseline_score = _score_for_move(baseline)
    candidate_score = _score_for_move(candidate)
    teacher_move = str((case.get("teacher_move") or (case.get("expected_uci_any") or [""])[0]).strip().lower())
    baseline_teacher_agreement = bool(baseline.get("teacher_agreement"))
    candidate_teacher_agreement = bool(candidate.get("teacher_agreement"))
    score_delta = round(candidate_score - baseline_score, 6)
    baseline_expected_rank = int(baseline.get("teacher_rank") or 0)
    candidate_expected_rank = int(candidate.get("teacher_rank") or 0)
    baseline_pvs_move = bool(baseline.get("pvs_selected_move") and baseline.get("legal"))
    candidate_pvs_move = bool(candidate.get("pvs_selected_move") and candidate.get("legal"))
    if not case.get("expected_uci_any"):
        diff_category = "teacher_label_questionable"
    elif candidate_score >= 1.0 and baseline_score >= 1.0:
        diff_category = "unchanged_correct" if candidate.get("chosen_move") == baseline.get("chosen_move") else "multi_good_tie"
    elif candidate_score >= 1.0 and baseline_score < 1.0:
        diff_category = "candidate_improved"
    elif candidate_score < 1.0 and baseline_score >= 1.0:
        diff_category = "candidate_regressed"
    elif candidate.get("chosen_move") == baseline.get("chosen_move"):
        diff_category = "unchanged_wrong"
    else:
        diff_category = "teacher_label_questionable"
    return {
        "id": str(case["id"]),
        "category": _case_category(case),
        "side": str(case["side"]),
        "fen": str(case["fen"]),
        "label_quality": str(case.get("label_quality") or "clean"),
        "pass": bool(candidate["pass"]),
        "reasons": list(candidate["reasons"]),
        "case_category": _case_category(case),
        "teacher_move": teacher_move,
        "baseline": baseline,
        "candidate": candidate,
        "chosen_move": candidate["chosen_move"],
        "legal": bool(candidate["legal"]),
        "suspicious": bool(candidate["suspicious"]),
        "teacher_agreement": bool(candidate["teacher_agreement"]),
        "teacher_moves": list(case.get("expected_uci_any") or []),
        "baseline_teacher_agreement": baseline_teacher_agreement,
        "candidate_teacher_agreement": candidate_teacher_agreement,
        "pvs_selected_move": bool(candidate["pvs_selected_move"]),
        "material_gain": int(candidate["material_gain"]),
        "baseline_score": baseline_score,
        "candidate_score": candidate_score,
        "score_delta": score_delta,
        "baseline_teacher_rank": baseline_expected_rank,
        "candidate_teacher_rank": candidate_expected_rank,
        "baseline_pvs_move": baseline_pvs_move,
        "candidate_pvs_move": candidate_pvs_move,
        "baseline_eval": float(baseline.get("score_for_chosen") or 0.0),
        "candidate_eval": float(candidate.get("score_for_chosen") or 0.0),
        "candidate_rank_for_candidate_move": int(candidate["rank_for_chosen"]),
        "candidate_top_moves": candidate["top_moves"],
        "selected_reason": str(candidate.get("selected_reason") or ""),
        "decision_category": diff_category,
        "candidate_top_score": float(candidate.get("score_for_chosen") or 0.0),
        "baseline_top_score": float(baseline.get("score_for_chosen") or 0.0),
        "final_fen": candidate["final_fen"],
    }


def _score_rows(rows: list[dict], *, key: str) -> dict:
    total = max(1, len(rows))
    selected = [row[key] for row in rows]
    passed = sum(1 for row in selected if bool(row.get("pass")))
    legal = sum(1 for row in selected if bool(row.get("legal")))
    suspicious = sum(1 for row in selected if bool(row.get("suspicious")))
    teacher_agreement = sum(1 for row in selected if bool(row.get("teacher_agreement")))
    pvs_selected = sum(1 for row in selected if bool(row.get("pvs_selected_move")))
    categories = {}
    for category in ("tactic", "endgame", "smoke"):
        scoped = [row[key] for row in rows if row.get("category") == category]
        categories[category] = round(sum(1 for row in scoped if bool(row.get("pass"))) / max(1, len(scoped)), 6)
    return {
        "score": round(passed / total, 6),
        "legal_rate": round(legal / total, 6),
        "illegal_rate": round(1.0 - (legal / total), 6),
        "suspicious_rate": round(suspicious / total, 6),
        "teacher_agreement_rate": round(teacher_agreement / total, 6),
        "pvs_selected_move_rate": round(pvs_selected / total, 6),
        "tactic_score": categories["tactic"],
        "endgame_score": categories["endgame"],
        "smoke_score": categories["smoke"],
    }


def _train_row_signature(row: dict) -> str:
    fen = str(row.get("fen") or "")
    side = str(row.get("side") or ("white" if " w " in fen else "black")).strip().lower()
    try:
        board = chess.Board(fen)
        material = "".join(str(piece) for piece in board.piece_map().values())
        normalized_fen = board.board_fen()
        side_to_move = "w" if board.turn else "b"
        text = f"{normalized_fen}|{side_to_move}|{side}|{sorted(material)}"
    except Exception:
        text = f"{fen}|{side}"
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _normalize_fen_signature(row: dict) -> dict[str, str]:
    fen = str(row.get("fen") or "").strip()
    return {
        "fen_hash": hashlib.sha256(fen.encode("utf-8")).hexdigest(),
        "normalized_fen_hash": _train_row_signature(row),
        "side_to_move": str(row.get("side") or ("white" if " w " in fen else "black")).strip().lower(),
    }


def _train_rows_learning_summary(
    baseline_path: Path,
    candidate_path: Path,
    train_rows: list[dict],
    *,
    search_profile: str,
) -> dict:
    if not train_rows:
        return {
            "enabled": False,
            "train_rows": 0,
            "baseline_teacher_agreement_on_train": 0.0,
            "candidate_teacher_agreement_on_train": 0.0,
            "train_agreement_delta": 0.0,
            "baseline_teacher_margin": 0.0,
            "candidate_teacher_margin": 0.0,
            "margin_delta": 0.0,
            "rows": [],
            "retrain_effect_not_visible": False,
            "learned_train_not_generalized": False,
            "case_results": [],
        }
    rows = []
    baseline_agreements = 0
    candidate_agreements = 0
    baseline_margins: list[float] = []
    candidate_margins: list[float] = []
    for item in train_rows:
        fen = str(item.get("fen") or item.get("board_fen") or "").strip()
        side = str(item.get("side") or ("white" if " w " in fen else "black")).strip().lower()
        expected = str((item.get("move_uci") or item.get("teacher_move") or item.get("move") or "")).strip().lower()
        candidate_probe = _policy_probe_for_move(candidate_path, fen, side, expected, search_profile=search_profile)
        baseline_probe = _policy_probe_for_move(baseline_path, fen, side, expected, search_profile=search_profile)
        baseline_agree = bool((baseline_probe.get("raw_policy_rank") or 0) == 1)
        candidate_agree = bool((candidate_probe.get("raw_policy_rank") or 0) == 1)
        baseline_margin = float(baseline_probe.get("top1_gap") or 0.0)
        candidate_margin = float(candidate_probe.get("top1_gap") or 0.0)
        row_report = {
            "fen": fen,
            "side": side,
            "teacher_move": expected,
            "baseline_top_move": str(baseline_probe.get("top_move") or ""),
            "candidate_top_move": str(candidate_probe.get("top_move") or ""),
            "baseline_teacher_agreement": baseline_agree,
            "candidate_teacher_agreement": candidate_agree,
            "candidate_matches_teacher": candidate_agree,
            "teacher_margin_before": baseline_margin,
            "teacher_margin_after": candidate_margin,
            "margin_delta": round(candidate_margin - baseline_margin, 8),
            "baseline_teacher_margin": baseline_margin,
            "candidate_teacher_margin": candidate_margin,
            "baseline_teacher_rank": int(baseline_probe.get("raw_policy_rank") or 0),
            "candidate_teacher_rank": int(candidate_probe.get("raw_policy_rank") or 0),
            "signatures": _normalize_fen_signature({"fen": fen, "side": side}),
        }
        baseline_agreements += int(baseline_agree)
        candidate_agreements += int(candidate_agree)
        baseline_margins.append(baseline_margin)
        candidate_margins.append(candidate_margin)
        rows.append(row_report)

    baseline_teacher_agreement = round(baseline_agreements / len(rows), 6)
    candidate_teacher_agreement = round(candidate_agreements / len(rows), 6)
    baseline_teacher_margin = round(sum(baseline_margins) / max(1, len(baseline_margins)), 6)
    candidate_teacher_margin = round(sum(candidate_margins) / max(1, len(candidate_margins)), 6)
    train_agreement_delta = round(candidate_teacher_agreement - baseline_teacher_agreement, 6)
    margin_delta = round(candidate_teacher_margin - baseline_teacher_margin, 6)
    return {
        "enabled": True,
        "train_rows": len(rows),
        "validation_rows": 0,
        "baseline_teacher_agreement_on_train": baseline_teacher_agreement,
        "candidate_teacher_agreement_on_train": candidate_teacher_agreement,
        "train_agreement_delta": train_agreement_delta,
        "baseline_teacher_margin": baseline_teacher_margin,
        "candidate_teacher_margin": candidate_teacher_margin,
        "margin_delta": margin_delta,
        "rows": rows,
        "retrain_effect_not_visible": not train_agreement_delta > 0,
        "learned_train_not_generalized": False,
    }


def _leakage_guard(train_rows: list[dict], held_out_rows: list[dict]) -> dict:
    train_signatures = {_train_row_signature(row) for row in train_rows}
    held_out_signatures = {_train_row_signature(row) for row in held_out_rows}
    overlap_count = len(train_signatures.intersection(held_out_signatures))
    overlap_examples = []
    train_index: dict[str, dict] = {}
    for row in train_rows:
        train_index[_train_row_signature(row)] = row
    for row in held_out_rows:
        signature = _train_row_signature(row)
        if signature in train_index:
            overlap_examples.append({
                "fen": str(row.get("fen") or row.get("board_fen") or ""),
                "side": str(row.get("side") or ""),
                "signature": signature,
            })
    return {
        "train_rows": len(train_rows),
        "validation_rows": 0,
        "held_out_rows": len(held_out_rows),
        "overlap_count": overlap_count,
        "held_out_in_training": overlap_count > 0,
        "overlap_examples": overlap_examples[:5],
    }


def _smoke_audit(case_rows: list[dict]) -> list[dict]:
    audits: list[dict] = []
    for row in [item for item in case_rows if item.get("category") == "smoke"]:
        baseline = row.get("baseline", {})
        candidate = row.get("candidate", {})
        if not row.get("teacher_moves"):
            reason = "teacher_label_questionable"
        elif bool(candidate.get("pass")) and not bool(baseline.get("pass")):
            reason = "scoring_bug"
        elif bool(candidate.get("pass")) and bool(baseline.get("pass")):
            reason = "multi_good_tie"
        elif (not bool(candidate.get("pass"))) and bool(baseline.get("pass")):
            reason = "candidate_fail"
        elif (not bool(candidate.get("pass"))) and (not bool(baseline.get("pass"))):
            reason = "baseline_also_fail"
        else:
            reason = "smoke_case_too_hard"
        audits.append({
            "smoke_case_id": str(row.get("id")),
            "fen": str(row.get("fen")),
            "expected_or_teacher_move": str(row.get("teacher_moves")[0] if row.get("teacher_moves") else ""),
            "baseline_move": str(row.get("baseline", {}).get("chosen_move", "")),
            "candidate_move": str(row.get("candidate", {}).get("chosen_move", "")),
            "failure_reason": reason,
        })
    return audits


def _load_benchmark_gate(path: Path | None, *, min_score_rate: float, min_games: int) -> dict:
    if path is None or not path.exists():
        return {
            "provided": False,
            "pass": False,
            "reasons": ["benchmark_report_not_provided"],
        }
    payload = json.loads(path.read_text(encoding="utf-8"))
    benchmark = payload.get("benchmark") if isinstance(payload.get("benchmark"), dict) else payload
    standings = benchmark.get("standings") if isinstance(benchmark.get("standings"), list) else []
    row = next((item for item in standings if str(item.get("engine") or "") == EXPERIMENT_NNUE_DIFFICULTY), None)
    suspicious = len(benchmark.get("suspicious_matches") or [])
    reasons: list[str] = []
    if not row:
        reasons.append("exp5_not_found_in_benchmark")
    else:
        if int(row.get("games") or 0) < int(min_games):
            reasons.append("benchmark_games_too_few")
        if float(row.get("score_rate") or 0.0) < float(min_score_rate):
            reasons.append("benchmark_score_rate_too_low")
    if suspicious:
        reasons.append("benchmark_suspicious_matches_present")
    return {
        "provided": True,
        "path": str(path),
        "pass": not reasons,
        "reasons": reasons,
        "engine_row": row or {},
        "suspicious_matches": suspicious,
        "min_score_rate": float(min_score_rate),
        "min_games": int(min_games),
    }


def _write_report(summary: dict, output_dir: Path) -> dict:
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = summary["finished_at"].replace(":", "").replace("-", "").replace("T", "_").replace("Z", "")
    json_path = output_dir / f"chess_exp5_strength_gate_{stamp}.json"
    md_path = output_dir / f"chess_exp5_strength_gate_{stamp}.md"
    json_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    lines = [
        "# chess_exp5_strength_gate",
        "",
        f"- candidate_model_path: `{summary['candidate_model_path']}`",
        f"- baseline_model_path: `{summary['baseline_model_path']}`",
        f"- pass: `{summary['pass']}`",
        f"- baseline_score: `{summary['baseline_score']}`",
        f"- candidate_score: `{summary['candidate_score']}`",
        f"- score_delta: `{summary['score_delta']}`",
        f"- case_pass_rate: `{summary['case_pass_rate']}`",
        f"- benchmark_gate_pass: `{summary['benchmark_gate'].get('pass')}`",
        "",
        "## Standard Policy",
        "",
        "- Exp5 reuses common safety floors: legal play, suspicious benchmark guard, score-rate floor when benchmark is provided.",
        "- Exp5 does not reuse exp3 semantic replay/promotion evidence.",
        "- Exp5 adds deterministic NNUE/PVS case checks and candidate-vs-baseline rank traces.",
        "",
        "## Case Decision Diff Snapshot",
        "",
        f"- case_count: `{summary.get('cases_total', 0)}`",
        f"- case_pass_rate: `{summary.get('case_pass_rate', 0.0)}`",
        f"- deterministic_improvement: `{summary.get('score_delta', 0.0)}`",
        "",
        "## Train Row Learning",
        "",
        f"- enabled: `{summary.get('train_rows_learning', {}).get('enabled', False)}`",
        f"- train_rows: `{summary.get('train_rows_learning', {}).get('train_rows', 0)}`",
        f"- baseline_teacher_agreement_on_train: `{summary.get('train_rows_learning', {}).get('baseline_teacher_agreement_on_train', 0.0)}`",
        f"- candidate_teacher_agreement_on_train: `{summary.get('train_rows_learning', {}).get('candidate_teacher_agreement_on_train', 0.0)}`",
        f"- train_agreement_delta: `{summary.get('train_rows_learning', {}).get('train_agreement_delta', 0.0)}`",
        f"- retrain_effect_not_visible: `{summary.get('train_rows_learning', {}).get('retrain_effect_not_visible', False)}`",
        f"- learned_train_not_generalized: `{summary.get('train_rows_learning', {}).get('learned_train_not_generalized', False)}`",
        "",
        "## Leak Guard",
        "",
        f"- train_rows: `{summary.get('leakage_guard', {}).get('train_rows', 0)}`",
        f"- held_out_rows: `{summary.get('leakage_guard', {}).get('held_out_rows', 0)}`",
        f"- overlap_count: `{summary.get('leakage_guard', {}).get('overlap_count', 0)}`",
        f"- held_out_in_training: `{summary.get('leakage_guard', {}).get('held_out_in_training', False)}`",
    ]
    md_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return {"json_report": str(json_path), "md_report": str(md_path)}


def main() -> int:
    args = parse_args()
    candidate_path = Path(args.candidate_model_path).expanduser().resolve() if args.candidate_model_path else default_chess_nnue_model_path()
    baseline_path = Path(args.baseline_model_path).expanduser().resolve() if args.baseline_model_path else default_chess_nnue_model_path()
    benchmark_path = Path(args.benchmark_report_path).expanduser().resolve() if args.benchmark_report_path else None
    output_dir = Path(args.output_dir).expanduser().resolve() if args.output_dir else default_chess_reports_dir()
    _progress(f"candidate model: {candidate_path}")
    _progress(f"baseline model: {baseline_path}")
    _progress(f"benchmark report: {benchmark_path if benchmark_path else '<none>'}")
    consistency = promotion_report_consistency(engine=EXPERIMENT_NNUE_DIFFICULTY, candidate_path=candidate_path, benchmark_report_path=benchmark_path if benchmark_path else None)
    cases = _normalize_strength_cases([Path(item).expanduser().resolve() for item in args.strength_cases_jsonl])
    train_rows = _iter_jsonl_rows([Path(item).expanduser().resolve() for item in args.train_rows_jsonl])
    held_out_rows = _iter_jsonl_rows([Path(item).expanduser().resolve() for item in args.held_out_rows_jsonl])
    rows = [
        _evaluate_case(candidate_path, baseline_path, case, search_profile=str(args.search_profile or "strong"))
        for case in cases
    ]
    passed = sum(1 for row in rows if row["pass"])
    case_pass_rate = round(passed / max(1, len(rows)), 4)
    baseline_metrics = _score_rows(rows, key="baseline")
    candidate_metrics = _score_rows(rows, key="candidate")
    score_delta = round(float(candidate_metrics["score"]) - float(baseline_metrics["score"]), 6)
    benchmark_gate = _load_benchmark_gate(
        benchmark_path,
        min_score_rate=float(args.min_benchmark_score_rate),
        min_games=int(args.min_benchmark_games),
    )
    reasons: list[str] = []
    gate_skipped = not bool(args.benchmark_report_path)
    if not consistency.get("pass"):
        reasons.extend([f"consistency:{reason}" for reason in consistency.get("reasons") or []])
    if gate_skipped:
        reasons.append("strength_gate_skipped_no_benchmark_report")
    if case_pass_rate < float(args.min_case_pass_rate):
        reasons.append("deterministic_case_pass_rate_too_low")
    if float(candidate_metrics["score"]) <= float(baseline_metrics["score"]):
        reasons.append("candidate_score_not_above_baseline")
    if float(candidate_metrics["illegal_rate"]) > 0:
        reasons.append("candidate_illegal_rate_nonzero")
    if float(candidate_metrics["suspicious_rate"]) > float(baseline_metrics["suspicious_rate"]):
        reasons.append("candidate_suspicious_rate_regressed")
    if float(candidate_metrics["tactic_score"]) < float(baseline_metrics["tactic_score"]):
        reasons.append("candidate_tactic_regression")
    if float(candidate_metrics["endgame_score"]) < float(baseline_metrics["endgame_score"]):
        reasons.append("candidate_endgame_regression")
    if benchmark_gate.get("provided") and not benchmark_gate.get("pass"):
        reasons.extend([f"benchmark:{reason}" for reason in benchmark_gate.get("reasons") or []])
    train_learning = _train_rows_learning_summary(
        baseline_path=baseline_path,
        candidate_path=candidate_path,
        train_rows=train_rows,
        search_profile=str(args.search_profile or "strong"),
    )
    leakage = _leakage_guard(train_rows=train_rows, held_out_rows=held_out_rows)
    if leakage.get("held_out_in_training"):
        reasons.append("held_out_leakage_detected")
    smoke_audit = _smoke_audit(rows)
    smoke_too_hard = sum(1 for item in smoke_audit if item.get("failure_reason") == "smoke_case_too_hard")
    candidate_fail = sum(1 for item in smoke_audit if item.get("failure_reason") == "candidate_fail")
    if smoke_too_hard and not candidate_fail:
        reasons.append("smoke_case_too_hard_no_candidate_signal")
    if smoke_candidate_fail := any(item.get("failure_reason") == "candidate_fail" for item in smoke_audit):
        reasons.append("smoke_candidate_failures")
    if any(item.get("category") == "smoke" for item in rows) and baseline_metrics["smoke_score"] == 0.0 and candidate_metrics["smoke_score"] == 0.0:
        reasons.append("smoke_score_zero")

    if train_learning.get("train_rows"):
        train_learning["retrain_effect_not_visible"] = (
            float(train_learning.get("train_agreement_delta") or 0.0) <= 0.0
        )
        if (
            float(train_learning.get("train_agreement_delta") or 0.0) > 0.0
            and float(candidate_metrics["score"]) <= float(baseline_metrics["score"])
        ):
            train_learning["learned_train_not_generalized"] = True
    finished_at = datetime.utcnow().isoformat() + "Z"
    summary = {
        "ok": True,
        "engine": EXPERIMENT_NNUE_DIFFICULTY,
        "finished_at": finished_at,
        "candidate_model_path": str(candidate_path),
        "baseline_model_path": str(baseline_path),
        "search_profile": str(args.search_profile or "strong"),
        "standard_policy": {
            "same_as_exp3_exp4": False,
            "common_safety_floor_shared": True,
            "exp5_specific_deterministic_gate_required": True,
            "reason": "Exp5 can share legal/suspicious/score safety floors, but not exp3 semantic replay evidence or exp4 policy/value feature assumptions.",
        },
        "promotion_gate_supported": True,
        "promotion_gate": {
            "passed": not reasons,
            "blocked_by_strength_gate": bool(reasons),
            "blocked_by_gate_skipped": gate_skipped,
            "candidate_can_be_staged": not reasons and not gate_skipped,
            "candidate_can_be_promoted": not reasons and not gate_skipped,
        },
        "baseline_score": baseline_metrics["score"],
        "candidate_score": candidate_metrics["score"],
        "score_delta": score_delta,
        "baseline_metrics": baseline_metrics,
        "candidate_metrics": candidate_metrics,
        "legal_rate": candidate_metrics["legal_rate"],
        "illegal_rate": candidate_metrics["illegal_rate"],
        "suspicious_rate": candidate_metrics["suspicious_rate"],
        "teacher_agreement_rate": candidate_metrics["teacher_agreement_rate"],
        "pvs_selected_move_rate": candidate_metrics["pvs_selected_move_rate"],
        "endgame_score": candidate_metrics["endgame_score"],
        "tactic_score": candidate_metrics["tactic_score"],
        "smoke_score": candidate_metrics["smoke_score"],
        "safety_guard": {
            "pass": not any(reason in reasons for reason in {
                "candidate_illegal_rate_nonzero",
                "candidate_suspicious_rate_regressed",
                "candidate_tactic_regression",
                "candidate_endgame_regression",
            }),
            "illegal_rate_zero": float(candidate_metrics["illegal_rate"]) == 0.0,
            "suspicious_rate_not_worse": float(candidate_metrics["suspicious_rate"]) <= float(baseline_metrics["suspicious_rate"]),
            "score_rate_not_below_baseline": float(candidate_metrics["score"]) >= float(baseline_metrics["score"]),
            "tactic_not_regressed": float(candidate_metrics["tactic_score"]) >= float(baseline_metrics["tactic_score"]),
            "endgame_not_regressed": float(candidate_metrics["endgame_score"]) >= float(baseline_metrics["endgame_score"]),
        },
        "case_pass_rate": case_pass_rate,
        "min_case_pass_rate": float(args.min_case_pass_rate),
        "cases_passed": passed,
        "cases_total": len(rows),
        "case_results": rows,
        "train_rows_learning": train_learning,
        "leakage_guard": leakage,
        "smoke_audit": smoke_audit,
        "smoke_case_too_hard_count": smoke_too_hard,
        "smoke_candidate_fail_count": candidate_fail,
        "smoke_candidates": [
            {
                "case_id": item.get("smoke_case_id"),
                "fen": item.get("fen"),
                "expected_or_teacher_move": item.get("expected_or_teacher_move"),
                "baseline_move": item.get("baseline_move"),
                "candidate_move": item.get("candidate_move"),
                "failure_reason": item.get("failure_reason"),
            }
            for item in smoke_audit
            if item.get("failure_reason") and item.get("failure_reason") != "multi_good_tie"
        ],
        "benchmark_gate": benchmark_gate,
        "promotion_report_consistency": consistency,
        "pass": not reasons,
        "reasons": reasons,
    }
    summary["reports"] = _write_report(summary, output_dir)
    _progress(f"phase result report: {summary['reports']['json_report']}")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        _progress(f"FAIL: {exc}")
        _progress("failure hint: check exp5 candidate schema, deterministic case output, and benchmark report path")
        raise
