#!/usr/bin/env python3
"""Run the exp5-specific strength gate for NNUE-like candidates."""

from __future__ import annotations

import argparse
import json
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


def _rank_for_move(model_path: Path, case: dict, move_uci: str, *, search_profile: str) -> int:
    rows = rank_experiment_nnue_policy_moves(
        {"__fen__": str(case["fen"])},
        str(case["side"]),
        model_path=model_path,
        search_profile=search_profile,
    )
    row = next((item for item in rows if str(item.get("move") or "") == move_uci), None)
    return int((row or {}).get("raw_policy_rank") or 0)


def _evaluate_case(candidate_path: Path, baseline_path: Path, case: dict, *, search_profile: str) -> dict:
    board_before = chess.Board(str(case["fen"]))
    side = str(case["side"])
    move = choose_experiment_nnue_move({"__fen__": board_before.fen()}, side, model_path=candidate_path, search_profile=search_profile)
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
    baseline_rank = _rank_for_move(baseline_path, case, chosen, search_profile=search_profile) if chosen else 0
    candidate_rank = _rank_for_move(candidate_path, case, chosen, search_profile=search_profile) if chosen else 0
    explanation = explain_experiment_nnue_decision(
        {"__fen__": str(case["fen"])},
        side,
        model_path=candidate_path,
        search_profile=search_profile,
        watched_moves=[chosen] if chosen else [],
    )
    return {
        "id": str(case["id"]),
        "side": side,
        "fen": str(case["fen"]),
        "pass": not reasons,
        "reasons": reasons,
        "chosen_move": chosen,
        "legal": legal,
        "material_gain": material_gain,
        "baseline_rank_for_chosen": baseline_rank,
        "candidate_rank_for_chosen": candidate_rank,
        "candidate_top_moves": explanation.get("top_final_moves", [])[:3],
        "final_fen": board_after.fen() if legal else board_before.fen(),
    }


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
        f"- case_pass_rate: `{summary['case_pass_rate']}`",
        f"- benchmark_gate_pass: `{summary['benchmark_gate'].get('pass')}`",
        "",
        "## Standard Policy",
        "",
        "- Exp5 reuses common safety floors: legal play, suspicious benchmark guard, score-rate floor when benchmark is provided.",
        "- Exp5 does not reuse exp3 semantic replay/promotion evidence.",
        "- Exp5 adds deterministic NNUE/PVS case checks and candidate-vs-baseline rank traces.",
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
    rows = [
        _evaluate_case(candidate_path, baseline_path, case, search_profile=str(args.search_profile or "strong"))
        for case in EXP5_STRENGTH_CASES
    ]
    passed = sum(1 for row in rows if row["pass"])
    case_pass_rate = round(passed / max(1, len(rows)), 4)
    benchmark_gate = _load_benchmark_gate(
        benchmark_path,
        min_score_rate=float(args.min_benchmark_score_rate),
        min_games=int(args.min_benchmark_games),
    )
    reasons: list[str] = []
    if not consistency.get("pass"):
        reasons.extend([f"consistency:{reason}" for reason in consistency.get("reasons") or []])
    if case_pass_rate < float(args.min_case_pass_rate):
        reasons.append("deterministic_case_pass_rate_too_low")
    if benchmark_gate.get("provided") and not benchmark_gate.get("pass"):
        reasons.extend([f"benchmark:{reason}" for reason in benchmark_gate.get("reasons") or []])
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
        "case_pass_rate": case_pass_rate,
        "min_case_pass_rate": float(args.min_case_pass_rate),
        "cases_passed": passed,
        "cases_total": len(rows),
        "case_results": rows,
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
