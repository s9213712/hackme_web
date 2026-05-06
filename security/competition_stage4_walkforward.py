#!/usr/bin/env python3
"""Stage 4 — Walk-forward by re-slicing Stage 2 equity curves.

Splits each (template, asset) equity curve into three windows defined in
competition_config.json (train 2020–2023 / validate 2024 / forward
2025–2026), and computes per-window return + DD + trade count.

Output: public/data/competition/walk_forward_matrix.csv

Note: workflow templates have no learnable parameters — "walk-forward"
here checks regime stability, not literal training. The forward-window
return drives a key verdict (FAIL if forward return is negative).
"""
from __future__ import annotations

import csv
import json
import sys

from competition_stage3_regime import (
    ASSETS,
    TEMPLATES,
    OUT_DIR,
    load_equity,
    load_trades,
    parse_iso_to_ts,
    slice_metrics,
)

from pathlib import Path
REPO_ROOT = Path(__file__).resolve().parents[1]
CONFIG = json.loads((REPO_ROOT / "security" / "competition_config.json").read_text())
WINDOWS = CONFIG["walk_forward"]


def main() -> int:
    raw_trades_path = OUT_DIR / "raw_trades.csv"
    trades_index = load_trades(raw_trades_path)
    print(f"[stage4] loaded {sum(len(v) for v in trades_index.values())} trades", file=sys.stderr)

    rows_out = []
    for template in TEMPLATES:
        for asset in ASSETS:
            equity = load_equity(template, asset)
            if not equity:
                continue
            trades = trades_index.get((template, asset), [])
            for win_key, win_def in WINDOWS.items():
                ts_start = parse_iso_to_ts(win_def["start"] + "T00:00:00+00:00")
                ts_end = parse_iso_to_ts(win_def["end"] + "T23:59:59+00:00")
                metrics = slice_metrics(equity, trades, ts_start=ts_start, ts_end=ts_end)
                rows_out.append({
                    "template": template,
                    "asset": asset,
                    "phase": win_key,
                    "phase_start": win_def["start"],
                    "phase_end": win_def["end"],
                    **metrics,
                })

    out_path = OUT_DIR / "walk_forward_matrix.csv"
    keys = ["template", "asset", "phase", "phase_start", "phase_end", "candle_count",
            "return_percent", "max_drawdown_percent", "trade_count", "first_iso", "last_iso", "insufficient_data"]
    with out_path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=keys, extrasaction="ignore")
        w.writeheader()
        for r in rows_out:
            w.writerow(r)
    print(f"[stage4] wrote {len(rows_out)} rows to {out_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
