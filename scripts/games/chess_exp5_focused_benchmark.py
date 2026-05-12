#!/usr/bin/env python3
"""exp5_09 focused benchmark — per-cluster pass/fail audit.

Runs both BASELINE and CANDIDATE against a curated case set, splits results
by cluster (endgame / opening / quiet_positional / tactic / special_rule /
smoke / blunder_avoid), and emits a benchmark report JSON in the format
that `chess_exp5_strength_gate.py` consumes via `--benchmark-report-path`.

Why "focused" not "round-robin":
- exp5 strength gate already runs deterministic move-by-move scoring.
- exp5_09 just needs an independently-named benchmark artefact that:
  - is reproducible (`fixed_depth_strong`, no randomness),
  - is cluster-aware so we can see whether endgame gains carry over,
  - emits the `benchmark.standings` shape the gate already expects.

Output JSON shape (compatible with `_load_benchmark_gate`):

```jsonc
{
  "benchmark": {
    "standings": [
      {"engine": "experiment 5:nnue", "games": N, "score_rate": X, "passed": P, "failed": F, ...},
      {"engine": "experiment 5:nnue:baseline", "games": N, "score_rate": Y, ...}
    ],
    "suspicious_matches": []
  },
  "clusters": {
    "endgame": {"baseline_score": ..., "candidate_score": ..., "score_delta": ..., "rows": [...]},
    ...
  },
  "overall": {
    "baseline_score": ..., "candidate_score": ..., "score_delta": ...,
    "legal_rate": ..., "suspicious_rate": ..., "regression_rate": ..., ...
  }
}
```
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

from services.games.chess_nnue import EXPERIMENT_NNUE_DIFFICULTY, choose_experiment_nnue_move


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="exp5_09 focused per-cluster benchmark.")
    p.add_argument("--candidate-model-path", required=True)
    p.add_argument("--baseline-model-path", required=True)
    p.add_argument("--cases-jsonl", required=True, help="Case set with at least fen/side/category/teacher_move (or expected_uci_any). Multi-file allowed via repeating the flag.", action="append")
    p.add_argument("--search-profile", default="fixed_depth_strong")
    p.add_argument("--output-json", required=True)
    p.add_argument("--engine-name", default=EXPERIMENT_NNUE_DIFFICULTY)
    p.add_argument("--baseline-engine-name", default=f"{EXPERIMENT_NNUE_DIFFICULTY}:baseline")
    return p.parse_args()


def _iter_jsonl(paths: list[str]) -> list[dict]:
    rows: list[dict] = []
    for p in paths:
        path = Path(p).expanduser().resolve()
        if not path.exists():
            continue
        for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if not line.strip():
                continue
            try:
                payload = json.loads(line)
            except Exception as exc:
                raise ValueError(f"{path}:{line_no}: {exc}") from exc
            if isinstance(payload, dict):
                rows.append(payload)
    return rows


def _normalize_case(raw: dict) -> dict:
    teacher_move = str(raw.get("teacher_move") or "").strip().lower()
    expected = raw.get("teacher_top3") or raw.get("teacher_top_moves") or raw.get("expected_uci_any") or []
    if isinstance(expected, (list, tuple)):
        expected_uci = [str(x).strip().lower() for x in expected if str(x).strip()]
    else:
        expected_uci = []
    if teacher_move and teacher_move not in expected_uci:
        expected_uci.insert(0, teacher_move)
    fen = str(raw.get("fen") or "").strip()
    side = str(raw.get("side") or ("white" if " w " in fen else "black")).strip().lower()
    category = str(raw.get("category") or "").strip().lower()
    if not category:
        # fall through using flags
        if raw.get("must_checkmate") or raw.get("requires_capture"):
            category = "tactic"
        elif raw.get("must_promote") or raw.get("must_not_stalemate"):
            category = "endgame"
        else:
            category = "unlabeled"
    return {
        "id": str(raw.get("id") or "").strip(),
        "fen": fen,
        "side": side,
        "category": category,
        "subcategory": str(raw.get("subcategory") or "").strip(),
        "label_quality": str(raw.get("label_quality") or "").strip().lower(),
        "teacher_move": teacher_move,
        "expected_uci_any": expected_uci,
        "must_checkmate": bool(raw.get("must_checkmate")),
        "must_not_stalemate": bool(raw.get("must_not_stalemate")),
        "must_promote": bool(raw.get("must_promote")),
        "expected_promotion": str(raw.get("expected_promotion") or "").strip().lower(),
        "requires_capture": bool(raw.get("requires_capture")),
        "must_not_uci_any": [str(x).strip().lower() for x in (raw.get("must_not_uci_any") or [])],
    }


def _evaluate(model_path: Path, case: dict, *, search_profile: str) -> dict:
    board = chess.Board(str(case["fen"]))
    side = str(case["side"])
    try:
        move = choose_experiment_nnue_move({"__fen__": board.fen()}, side, model_path=model_path, search_profile=search_profile)
    except Exception:
        move = None
    chosen = ""
    legal = False
    is_mate = False
    is_stalemate = False
    is_promotion = False
    is_capture = False
    if move:
        chosen = f"{move.get('from','')}{move.get('to','')}{move.get('promotion') or ''}".lower()
    reasons: list[str] = []
    if not chosen:
        reasons.append("engine_no_move")
    else:
        try:
            mv = board.parse_uci(chosen)
        except Exception:
            mv = None
        if mv is None or mv not in board.legal_moves:
            reasons.append("illegal_move")
        else:
            legal = True
            is_promotion = bool(mv.promotion)
            is_capture = board.is_capture(mv)
            after = board.copy(stack=False)
            after.push(mv)
            is_mate = after.is_checkmate()
            is_stalemate = after.is_stalemate()
            expected = case["expected_uci_any"]
            forbidden = case["must_not_uci_any"]
            if expected and chosen not in expected:
                reasons.append("unexpected_move")
            if forbidden and chosen in forbidden:
                reasons.append("forbidden_move_played")
            if case["must_checkmate"] and not is_mate:
                reasons.append("mate_not_found")
            if case["must_not_stalemate"] and is_stalemate:
                reasons.append("stalemate_after_move")
            if case["must_promote"] and not is_promotion:
                reasons.append("promotion_required")
            if case["requires_capture"] and not is_capture:
                reasons.append("capture_required")
            if case["expected_promotion"]:
                pp = chess.piece_symbol(mv.promotion).lower() if mv.promotion else ""
                if pp != case["expected_promotion"]:
                    reasons.append("unexpected_promotion_piece")
    return {
        "chosen_move": chosen,
        "legal": legal,
        "is_mate": is_mate,
        "is_stalemate": is_stalemate,
        "is_promotion": is_promotion,
        "is_capture": is_capture,
        "reasons": reasons,
        "pass": not reasons,
    }


def main() -> int:
    args = parse_args()
    candidate_path = Path(args.candidate_model_path).expanduser().resolve()
    baseline_path = Path(args.baseline_model_path).expanduser().resolve()
    output_path = Path(args.output_json).expanduser().resolve()

    raw_cases = _iter_jsonl(args.cases_jsonl)
    cases = [_normalize_case(c) for c in raw_cases if isinstance(c, dict)]

    # Group by cluster
    clusters: dict[str, list[dict]] = {}
    rows = []
    suspicious_matches: list[dict] = []
    for c in cases:
        cat = c["category"] or "unlabeled"
        b = _evaluate(baseline_path, c, search_profile=args.search_profile)
        cand = _evaluate(candidate_path, c, search_profile=args.search_profile)
        row = {
            **c,
            "baseline": b,
            "candidate": cand,
            "score_delta": (1 if cand["pass"] else 0) - (1 if b["pass"] else 0),
            "candidate_regressed": (not cand["pass"]) and b["pass"],
            "candidate_improved": cand["pass"] and (not b["pass"]),
            "candidate_illegal": not cand["legal"],
            "candidate_suspicious": cand["is_stalemate"] or (not cand["legal"]),
        }
        rows.append(row)
        clusters.setdefault(cat, []).append(row)
        if row["candidate_illegal"]:
            suspicious_matches.append({"id": c["id"], "reason": "candidate_illegal_move"})

    # Aggregate
    def cluster_summary(rows: list[dict]) -> dict:
        n = max(1, len(rows))
        b_passed = sum(1 for r in rows if r["baseline"]["pass"])
        c_passed = sum(1 for r in rows if r["candidate"]["pass"])
        return {
            "cases": len(rows),
            "baseline_passed": b_passed,
            "candidate_passed": c_passed,
            "baseline_score": round(b_passed / n, 6),
            "candidate_score": round(c_passed / n, 6),
            "score_delta": round((c_passed - b_passed) / n, 6),
            "candidate_improved": sum(1 for r in rows if r["candidate_improved"]),
            "candidate_regressed": sum(1 for r in rows if r["candidate_regressed"]),
            "candidate_illegal": sum(1 for r in rows if r["candidate_illegal"]),
            "candidate_suspicious": sum(1 for r in rows if r["candidate_suspicious"]),
        }

    overall = cluster_summary(rows)
    cluster_reports = {cat: {**cluster_summary(rs), "rows": [
        {
            "id": r["id"], "fen": r["fen"], "side": r["side"], "category": r["category"],
            "subcategory": r["subcategory"], "label_quality": r["label_quality"],
            "teacher_move": r["teacher_move"],
            "baseline_move": r["baseline"]["chosen_move"], "baseline_pass": r["baseline"]["pass"],
            "candidate_move": r["candidate"]["chosen_move"], "candidate_pass": r["candidate"]["pass"],
            "candidate_reasons": r["candidate"]["reasons"],
            "score_delta": r["score_delta"],
        }
        for r in rs
    ]} for cat, rs in sorted(clusters.items())}

    # Strength-gate-compatible standings
    games_count = len(rows)
    standings = [
        {
            "engine": args.engine_name,
            "passed": overall["candidate_passed"],
            "failed": games_count - overall["candidate_passed"],
            "games": games_count,
            "score_rate": overall["candidate_score"],
            "points": overall["candidate_passed"],  # one point per pass
            "wins": overall["candidate_passed"],
            "losses": games_count - overall["candidate_passed"],
            "draws": 0,
        },
        {
            "engine": args.baseline_engine_name,
            "passed": overall["baseline_passed"],
            "failed": games_count - overall["baseline_passed"],
            "games": games_count,
            "score_rate": overall["baseline_score"],
            "points": overall["baseline_passed"],
            "wins": overall["baseline_passed"],
            "losses": games_count - overall["baseline_passed"],
            "draws": 0,
        },
    ]

    payload = {
        "ok": True,
        "finished_at": datetime.utcnow().isoformat() + "Z",
        "engine": args.engine_name,
        "baseline_engine": args.baseline_engine_name,
        "candidate_model_path": str(candidate_path),
        "baseline_model_path": str(baseline_path),
        "search_profile": str(args.search_profile),
        "cases_count": games_count,
        "benchmark": {
            "type": "focused_deterministic",
            "search_profile": str(args.search_profile),
            "standings": standings,
            "suspicious_matches": suspicious_matches,
        },
        "overall": overall,
        "clusters": cluster_reports,
        "candidate_illegal_count": overall["candidate_illegal"],
        "suspicious_match_count": len(suspicious_matches),
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
