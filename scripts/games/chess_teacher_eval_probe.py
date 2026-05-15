#!/usr/bin/env python3
"""Evaluate exp3/exp4 policy rank against teacher-selected chess rows."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.games.chess_dl import rank_experiment_dl_policy_moves  # noqa: E402
from services.games.chess_pv import rank_experiment_pv_policy_moves  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Probe model policy ranking on teacher JSONL rows.")
    parser.add_argument("--input-jsonl", required=True)
    parser.add_argument("--output-json", required=True)
    parser.add_argument("--max-samples", type=int, default=5)
    parser.add_argument("--exp3-baseline-model", default="")
    parser.add_argument("--exp3-candidate-model", default="")
    parser.add_argument("--exp4-baseline-model", default="")
    parser.add_argument("--exp4-candidate-model", default="")
    return parser.parse_args()


def _iter_rows(path: Path, limit: int) -> list[dict]:
    rows: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if not isinstance(row, dict):
            continue
        if not row.get("fen") or not row.get("move_uci") or str(row.get("side") or "").lower() not in {"white", "black"}:
            continue
        rows.append(row)
        if limit > 0 and len(rows) >= limit:
            break
    return rows


def _rank_expected(ranked: list[dict], expected: str) -> dict:
    moves = [str(row.get("move") or "") for row in ranked]
    rank = moves.index(expected) + 1 if expected in moves else 0
    top1 = moves[0] if moves else ""
    return {
        "top1": top1,
        "expected_rank": rank,
        "top1_hit": bool(rank == 1),
        "top3_hit": bool(rank and rank <= 3),
        "top5_hit": bool(rank and rank <= 5),
    }


def _probe_engine(engine: str, model_path: str, rows: list[dict]) -> dict:
    cases: list[dict] = []
    rank_sum = 0
    ranked_count = 0
    for index, row in enumerate(rows, start=1):
        expected = str(row.get("move_uci") or "").strip().lower()
        side = str(row.get("side") or "").strip().lower()
        board_state = {"__fen__": str(row.get("fen") or "")}
        try:
            ranked = (
                rank_experiment_dl_policy_moves(board_state, side, model_path=model_path)
                if engine == "exp3"
                else rank_experiment_pv_policy_moves(board_state, side, model_path=model_path)
            )
        except Exception as exc:
            cases.append({"index": index, "expected": expected, "error": repr(exc)})
            continue
        result = _rank_expected(ranked, expected)
        if result["expected_rank"]:
            rank_sum += int(result["expected_rank"])
            ranked_count += 1
        cases.append(
            {
                "index": index,
                "source_id": row.get("source_id", ""),
                "category": row.get("category", ""),
                "side": side,
                "expected": expected,
                **result,
            }
        )
    sample_count = len(rows)
    return {
        "engine": engine,
        "model_path": str(model_path),
        "samples": sample_count,
        "top1_hits": sum(1 for case in cases if case.get("top1_hit")),
        "top3_hits": sum(1 for case in cases if case.get("top3_hit")),
        "top5_hits": sum(1 for case in cases if case.get("top5_hit")),
        "missing_expected": sum(1 for case in cases if not case.get("expected_rank")),
        "avg_expected_rank": round(rank_sum / ranked_count, 4) if ranked_count else 0.0,
        "cases": cases,
    }


def _delta(before: dict, after: dict) -> dict:
    return {
        "top1_hits_delta": int(after.get("top1_hits") or 0) - int(before.get("top1_hits") or 0),
        "top3_hits_delta": int(after.get("top3_hits") or 0) - int(before.get("top3_hits") or 0),
        "top5_hits_delta": int(after.get("top5_hits") or 0) - int(before.get("top5_hits") or 0),
        "avg_expected_rank_delta": round(float(after.get("avg_expected_rank") or 0.0) - float(before.get("avg_expected_rank") or 0.0), 4),
    }


def main() -> int:
    args = parse_args()
    rows = _iter_rows(Path(args.input_jsonl).expanduser().resolve(), int(args.max_samples or 0))
    results: dict[str, dict] = {}
    if args.exp3_baseline_model:
        results["exp3_baseline"] = _probe_engine("exp3", args.exp3_baseline_model, rows)
    if args.exp3_candidate_model:
        results["exp3_candidate"] = _probe_engine("exp3", args.exp3_candidate_model, rows)
    if args.exp4_baseline_model:
        results["exp4_baseline"] = _probe_engine("exp4", args.exp4_baseline_model, rows)
    if args.exp4_candidate_model:
        results["exp4_candidate"] = _probe_engine("exp4", args.exp4_candidate_model, rows)
    comparisons = {}
    if "exp3_baseline" in results and "exp3_candidate" in results:
        comparisons["exp3_candidate_minus_baseline"] = _delta(results["exp3_baseline"], results["exp3_candidate"])
    if "exp4_baseline" in results and "exp4_candidate" in results:
        comparisons["exp4_candidate_minus_baseline"] = _delta(results["exp4_baseline"], results["exp4_candidate"])
    payload = {
        "ok": True,
        "input_jsonl": str(Path(args.input_jsonl).expanduser().resolve()),
        "sample_count": len(rows),
        "results": results,
        "comparisons": comparisons,
    }
    output_path = Path(args.output_json).expanduser().resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
