#!/usr/bin/env python3
"""Stage 6 — Slippage sensitivity for top 5 templates.

Re-computes slippage-adjusted return at 0.05% / 0.1% / 0.2% from the
existing turnover and return numbers in raw_results.csv. No backtest
re-run needed because slippage is a linear post-process: total_cost =
turnover × rate.

Output: public/data/competition/sensitivity_matrix.csv
"""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = REPO_ROOT / "public" / "data" / "competition"
CONFIG = json.loads((REPO_ROOT / "security" / "competition_config.json").read_text())
SLIPPAGES = CONFIG["constants"]["slippage_percent_sensitivity"]
INITIAL_CASH = CONFIG["constants"]["initial_cash_points"]


def main() -> int:
    rows = list(csv.DictReader(open(OUT_DIR / "raw_results.csv")))
    # Compute average return per template and pick top 5.
    from collections import defaultdict
    per_t = defaultdict(list)
    for r in rows:
        per_t[r["template"]].append(float(r["return_percent"]))
    avg = sorted(((tn, sum(v)/len(v)) for tn, v in per_t.items()), key=lambda x: x[1], reverse=True)
    top5 = [t[0] for t in avg[:5]]
    print(f"[stage6] top 5 templates by avg return: {top5}", file=sys.stderr)

    out_rows = []
    for r in rows:
        if r["template"] not in top5:
            continue
        ret = float(r["return_percent"])
        turnover = float(r["total_turnover_points"])
        for slip_pct in SLIPPAGES:
            cost = turnover * (slip_pct / 100.0)
            adj = ret - (cost / INITIAL_CASH * 100.0)
            out_rows.append({
                "template": r["template"],
                "asset": r["asset"],
                "slippage_percent": slip_pct,
                "raw_return_percent": ret,
                "turnover_points": turnover,
                "slippage_cost_points": round(cost, 2),
                "adjusted_return_percent": round(adj, 4),
            })

    out_path = OUT_DIR / "sensitivity_matrix.csv"
    with out_path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(out_rows[0].keys()))
        w.writeheader()
        for r in out_rows:
            w.writerow(r)
    print(f"[stage6] wrote {len(out_rows)} rows to {out_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
