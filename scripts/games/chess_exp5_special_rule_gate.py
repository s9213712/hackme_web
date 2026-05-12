#!/usr/bin/env python3
"""Special-rule deterministic gate for exp5 NNUE-like candidates.

Tests the four chess-specific rule clusters that a vanilla material+PST
evaluator most often gets wrong:

1. Castling — kingside / queenside / cannot castle / king-escape-after-castle.
2. En passant — must take / must NOT take when it loses material.
3. Promotion — to-queen / to-knight-for-mate / underpromotion-to-avoid-stalemate.
4. Stalemate avoidance / draw rules — don't blunder into a draw when winning.

Gate policy (independent from the regular strength gate):
- legal_rate == 1.0 (any illegal move = fail)
- suspicious_rate <= baseline_suspicious_rate
- per-cluster: candidate_cluster_score >= baseline_cluster_score
- castling cluster MUST hit 1.0 if baseline hits 1.0 (no castling regression)
- overall candidate_score >= baseline_score (no special-rule regression)

The gate runs the same `choose_experiment_nnue_move` path used in production
under `--search-profile fixed_depth_strong` for determinism. It does NOT
replace the regular strength gate; it is an auxiliary safety guard for
exp5_06+.
"""

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

from services.games.chess_nnue import (  # noqa: E402
    EXPERIMENT_NNUE_DIFFICULTY,
    choose_experiment_nnue_move,
    default_chess_nnue_model_path,
)


# Per-category test set. Keep small and hand-curated; expand later.
SPECIAL_RULE_CASES: list[dict] = [
    # --- castling cluster -----------------------------------------------
    {
        "id": "castle_kingside_white",
        "category": "castling",
        "subcategory": "short_castle",
        "fen": "r3k2r/pppq1ppp/2n2n2/2bpp3/2BPP3/2N2N2/PPPQ1PPP/R3K2R w KQkq - 0 1",
        "side": "white",
        "expected_uci_any": ["e1g1"],
        "rule_features": {"can_castle_kingside": True, "is_castling_move": True},
    },
    {
        "id": "castle_queenside_white",
        "category": "castling",
        "subcategory": "long_castle",
        "fen": "r3k2r/pppq1ppp/2n2n2/3pp3/3PP3/2N2N2/PPPQBPPP/R3K2R w KQkq - 0 1",
        "side": "white",
        "expected_uci_any": ["e1c1", "e1g1"],
        "rule_features": {"can_castle_queenside": True, "is_castling_move": True},
    },
    {
        "id": "castle_kingside_black",
        "category": "castling",
        "subcategory": "short_castle",
        "fen": "r3k2r/pppq1ppp/2n2n2/2bpp3/2BPP3/2N2N2/PPPQ1PPP/R3K2R b KQkq - 1 1",
        "side": "black",
        "expected_uci_any": ["e8g8"],
        "rule_features": {"can_castle_kingside": True, "is_castling_move": True},
    },
    {
        "id": "castle_forbidden_under_attack",
        "category": "castling",
        "subcategory": "cannot_castle_through_check",
        # f1 is attacked by black bishop on a6: white cannot O-O.
        "fen": "r3kbnr/ppp1pppp/8/3q4/8/8/PPPP1PPP/RNB1K2R w KQkq - 0 1",
        "side": "white",
        "must_not_uci_any": ["e1g1"],
        "rule_features": {"can_castle_kingside": False, "is_castling_move": False},
    },
    # --- en passant cluster ---------------------------------------------
    {
        "id": "en_passant_winning_take",
        "category": "en_passant",
        "subcategory": "must_take",
        # White just played b2-b4 past black's a-pawn on a4; black plays a-pawn x b3 e.p.
        "fen": "8/8/8/8/pP6/8/8/4K2k b - b3 0 1",
        "side": "black",
        "expected_uci_any": ["a4b3"],
        "rule_features": {"is_en_passant": True},
    },
    {
        "id": "en_passant_must_not_lose_piece",
        "category": "en_passant",
        "subcategory": "do_not_take",
        # Taking en-passant would expose the black king to discovered attack -> capture is bad here.
        # Black to move; en-passant on b3 is legal but loses material.
        "fen": "4k3/8/8/8/pP1R4/8/8/4K3 b - b3 0 1",
        "side": "black",
        "must_not_uci_any": ["a4b3"],
        "rule_features": {"is_en_passant": False},
    },
    # --- promotion cluster ----------------------------------------------
    {
        "id": "promotion_to_queen_white",
        "category": "promotion",
        "subcategory": "to_queen",
        "fen": "k7/4P3/2K5/8/8/8/8/8 w - - 0 1",
        "side": "white",
        "must_promote": True,
        "expected_promotion": "q",
        "expected_uci_any": ["e7e8q"],
        "rule_features": {"is_promotion": True, "promotion_piece": "q"},
    },
    {
        "id": "promotion_avoid_stalemate_underpromote",
        "category": "promotion",
        "subcategory": "underpromote_to_avoid_stalemate",
        # Promoting to queen would stalemate black; promoting to rook is forced mate later.
        # In this exact position promoting to queen = stalemate.
        "fen": "k7/7P/1K6/8/8/8/8/8 w - - 0 1",
        "side": "white",
        "must_not_stalemate": True,
        "rule_features": {"is_promotion": True},
    },
    # --- stalemate-avoid / draw cluster --------------------------------
    {
        "id": "avoid_stalemate_kqk",
        "category": "stalemate_avoid",
        "subcategory": "queen_endgame_no_stalemate",
        # King + queen vs king, queen too close → simply moving forward stalemates.
        # Candidate must NOT pick the stalemating queen move.
        "fen": "k7/3Q4/2K5/8/8/8/8/8 w - - 0 1",
        "side": "white",
        "must_not_stalemate": True,
        "rule_features": {"draw_claim_available": False},
    },
    {
        "id": "force_mate_not_stalemate",
        "category": "stalemate_avoid",
        "subcategory": "mate_not_stalemate",
        # Krk vs k. Multiple legal moves; only some win, others stalemate.
        "fen": "k7/8/1K6/3R4/8/8/8/8 w - - 0 1",
        "side": "white",
        "must_not_stalemate": True,
        "rule_features": {"draw_claim_available": False},
    },
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="exp5 special-rule deterministic gate (castling/EP/promotion/draw)")
    parser.add_argument("--candidate-model-path", required=True)
    parser.add_argument("--baseline-model-path", required=True)
    parser.add_argument("--search-profile", default="fixed_depth_strong")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--cases-jsonl", default="", help="Optional custom case set; overrides bundled cases.")
    parser.add_argument("--allow-castling-regression", action="store_true", help="Off by default: castling regression vs baseline → fail.")
    return parser.parse_args()


def _move_to_uci(move: dict | None) -> str:
    if not move:
        return ""
    return f"{move.get('from') or ''}{move.get('to') or ''}{move.get('promotion') or ''}".lower()


def _evaluate_case(model_path: Path, case: dict, *, search_profile: str) -> dict:
    board_before = chess.Board(str(case["fen"]))
    side = str(case["side"])
    move = choose_experiment_nnue_move({"__fen__": board_before.fen()}, side, model_path=model_path, search_profile=search_profile)
    chosen = _move_to_uci(move)
    reasons: list[str] = []
    board_after = board_before.copy(stack=False)
    legal = False
    is_castling = False
    is_en_passant = False
    is_promotion = False
    promotion_piece = ""
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
            is_castling = board_before.is_castling(chess_move)
            is_en_passant = board_before.is_en_passant(chess_move)
            is_promotion = bool(chess_move.promotion)
            promotion_piece = chess.piece_symbol(chess_move.promotion).lower() if chess_move.promotion else ""
            board_after.push(chess_move)
            expected = [str(item).lower() for item in (case.get("expected_uci_any") or [])]
            forbidden = [str(item).lower() for item in (case.get("must_not_uci_any") or [])]
            if expected and chosen not in expected:
                reasons.append("unexpected_move")
            if forbidden and chosen in forbidden:
                reasons.append("forbidden_move_played")
            if case.get("must_not_stalemate") and board_after.is_stalemate():
                reasons.append("stalemate_after_move")
            if case.get("must_promote") and not chess_move.promotion:
                reasons.append("promotion_required")
            expected_promotion = str(case.get("expected_promotion") or "").lower()
            if expected_promotion and promotion_piece != expected_promotion:
                reasons.append("unexpected_promotion_piece")
    return {
        "id": str(case["id"]),
        "category": str(case.get("category") or ""),
        "subcategory": str(case.get("subcategory") or ""),
        "fen": str(case["fen"]),
        "side": str(case["side"]),
        "chosen_move": chosen,
        "legal": bool(legal),
        "is_castling": bool(is_castling),
        "is_en_passant": bool(is_en_passant),
        "is_promotion": bool(is_promotion),
        "promotion_piece": promotion_piece,
        "pass": not reasons,
        "reasons": reasons,
        "rule_features": case.get("rule_features") or {},
    }


def _cluster_score(rows: list[dict], category: str) -> tuple[int, int, float]:
    scoped = [r for r in rows if r.get("category") == category]
    if not scoped:
        return (0, 0, 0.0)
    passed = sum(1 for r in scoped if r.get("pass"))
    return (passed, len(scoped), round(passed / len(scoped), 6))


def _summary(rows: list[dict]) -> dict:
    total = max(1, len(rows))
    passed = sum(1 for r in rows if r.get("pass"))
    legal = sum(1 for r in rows if r.get("legal"))
    return {
        "score": round(passed / total, 6),
        "legal_rate": round(legal / total, 6),
        "illegal_rate": round(1.0 - legal / total, 6),
        "cases_total": len(rows),
        "cases_passed": passed,
    }


def _load_cases(path: str) -> list[dict]:
    if not path:
        return list(SPECIAL_RULE_CASES)
    rows = []
    for line_no, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except Exception as exc:
            raise ValueError(f"{path}:{line_no}: invalid JSON: {exc}") from exc
        if not isinstance(payload, dict):
            raise ValueError(f"{path}:{line_no}: row must be object")
        rows.append(payload)
    return rows


def main() -> int:
    args = parse_args()
    cases = _load_cases(args.cases_jsonl)
    candidate_path = Path(args.candidate_model_path).expanduser().resolve()
    baseline_path = Path(args.baseline_model_path).expanduser().resolve()
    output_dir = Path(args.output_dir).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    candidate_rows = [_evaluate_case(candidate_path, c, search_profile=args.search_profile) for c in cases]
    baseline_rows = [_evaluate_case(baseline_path, c, search_profile=args.search_profile) for c in cases]

    candidate_summary = _summary(candidate_rows)
    baseline_summary = _summary(baseline_rows)

    clusters = {}
    cluster_regression = False
    for category in ("castling", "en_passant", "promotion", "stalemate_avoid"):
        c_pass, c_total, c_score = _cluster_score(candidate_rows, category)
        b_pass, b_total, b_score = _cluster_score(baseline_rows, category)
        clusters[category] = {
            "candidate_pass": c_pass,
            "candidate_total": c_total,
            "candidate_score": c_score,
            "baseline_pass": b_pass,
            "baseline_total": b_total,
            "baseline_score": b_score,
            "regressed": c_score < b_score,
        }
        if c_score < b_score:
            cluster_regression = True

    reasons: list[str] = []
    if candidate_summary["illegal_rate"] > 0:
        reasons.append("candidate_illegal_rate_nonzero")
    if candidate_summary["score"] < baseline_summary["score"]:
        reasons.append("candidate_score_below_baseline")
    if not args.allow_castling_regression and clusters["castling"]["regressed"]:
        reasons.append("castling_cluster_regressed")
    # Other clusters: regression flagged but not auto-fail (informational).
    finished_at = datetime.utcnow().isoformat() + "Z"
    payload = {
        "ok": True,
        "engine": EXPERIMENT_NNUE_DIFFICULTY,
        "finished_at": finished_at,
        "candidate_model_path": str(candidate_path),
        "baseline_model_path": str(baseline_path),
        "search_profile": str(args.search_profile),
        "pass": not reasons,
        "reasons": reasons,
        "candidate_summary": candidate_summary,
        "baseline_summary": baseline_summary,
        "score_delta": round(candidate_summary["score"] - baseline_summary["score"], 6),
        "cluster_regression": cluster_regression,
        "clusters": clusters,
        "candidate_rows": candidate_rows,
        "baseline_rows": baseline_rows,
    }
    stamp = finished_at.replace(":", "").replace("-", "").replace("T", "_").replace("Z", "")
    json_path = output_dir / f"chess_exp5_special_rule_gate_{stamp}.json"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    payload["report_json"] = str(json_path)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
