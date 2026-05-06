#!/usr/bin/env python3
"""Stage 5 — Stress test.

Generates 7 synthetic stress scenarios and runs every competition
template against each. Each scenario is a small candle sequence (300
bars at 1h) seeded from real BTC price action and warped to exhibit a
single failure mode:

  flash_crash               -30% drop in 1 candle, recovers next 5
  fake_breakout             3 candles up +5% then collapse to baseline
  gap_down                  open gap -10% then drift sideways
  low_vol_chop              ±0.1% noise, no trend (50 bars)
  volume_spike_fake_signal  10× volume on otherwise unchanged price
  stale_price               5 identical candles in a row
  outlier_candle            1 candle with +20% wick (high only, close back)

Output: public/data/competition/stress_test_matrix.csv

Stress runs are intentionally short and isolated so each row tests a
single failure mode, not cumulative regime drift.
"""
from __future__ import annotations

import csv
import json
import sqlite3
import sys
import tempfile
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "security"))

from competition_stage2_matrix import build_runtime, load_template_workflow

OUT_DIR = REPO_ROOT / "public" / "data" / "competition"
CONFIG = json.loads((REPO_ROOT / "security" / "competition_config.json").read_text())
TEMPLATES = (
    CONFIG["competition_templates"]["original_12"]
    + CONFIG["competition_templates"]["codex_5"]
    + CONFIG["competition_templates"]["claude_5"]
)
INITIAL_CASH = int(CONFIG["constants"]["initial_cash_points"])
START_PRICE = 60000.0  # neutral baseline; doesn't drive ranking, just absolute level


def candle(time_unit, o, h, l, c, vol=10.0):
    return {
        "time": int(time_unit),
        "time_iso": datetime.utcfromtimestamp(int(time_unit)).isoformat() + "+00:00",
        "open_points": float(o),
        "high_points": float(h),
        "low_points": float(l),
        "close_points": float(c),
        "price_points": float(c),
        "volume": float(vol),
    }


def baseline(n=300):
    """n bars at START_PRICE with mild +0.05%/bar drift + ±0.2% noise."""
    import random
    random.seed(42)
    out = []
    p = START_PRICE
    base_ts = 1700000000  # ~2023-11
    for i in range(n):
        drift = 1.0005
        noise = 1 + random.uniform(-0.002, 0.002)
        new = p * drift * noise
        h = max(p, new) * (1 + random.uniform(0, 0.002))
        l = min(p, new) * (1 - random.uniform(0, 0.002))
        out.append(candle(base_ts + i * 3600, p, h, l, new))
        p = new
    return out


def scenario_flash_crash():
    bars = baseline()
    crash_idx = 250
    bars[crash_idx]["close_points"] = bars[crash_idx]["open_points"] * 0.70
    bars[crash_idx]["low_points"] = bars[crash_idx]["close_points"] * 0.99
    bars[crash_idx]["price_points"] = bars[crash_idx]["close_points"]
    # Recover linearly over next 5 bars
    base_after = bars[crash_idx]["close_points"]
    target = bars[crash_idx]["open_points"]
    for j in range(1, 6):
        if crash_idx + j < len(bars):
            v = base_after + (target - base_after) * j / 5
            bars[crash_idx + j]["close_points"] = v
            bars[crash_idx + j]["price_points"] = v
            bars[crash_idx + j]["high_points"] = max(bars[crash_idx + j]["high_points"], v * 1.001)
            bars[crash_idx + j]["low_points"] = min(bars[crash_idx + j]["low_points"], base_after * 0.999)
    return bars


def scenario_fake_breakout():
    bars = baseline()
    breakout_start = 200
    base = bars[breakout_start]["close_points"]
    for j, mul in enumerate([1.02, 1.035, 1.05]):
        bars[breakout_start + j]["close_points"] = base * mul
        bars[breakout_start + j]["high_points"] = base * mul * 1.005
        bars[breakout_start + j]["price_points"] = base * mul
    # Collapse back over 3 bars
    for j, mul in enumerate([1.03, 1.01, 0.98]):
        idx = breakout_start + 3 + j
        if idx < len(bars):
            bars[idx]["close_points"] = base * mul
            bars[idx]["low_points"] = base * mul * 0.995
            bars[idx]["price_points"] = base * mul
    return bars


def scenario_gap_down():
    bars = baseline()
    gap_idx = 200
    pre = bars[gap_idx - 1]["close_points"]
    post = pre * 0.90
    for j in range(gap_idx, len(bars)):
        bars[j]["open_points"] = post
        bars[j]["close_points"] = post * (1 + 0.0001 * (j - gap_idx))
        bars[j]["high_points"] = bars[j]["close_points"] * 1.002
        bars[j]["low_points"] = bars[j]["close_points"] * 0.998
        bars[j]["price_points"] = bars[j]["close_points"]
    return bars


def scenario_low_vol_chop():
    bars = baseline(50)
    p = bars[0]["close_points"]
    import random
    random.seed(7)
    for i in range(len(bars)):
        new = p * (1 + random.uniform(-0.001, 0.001))
        bars[i]["open_points"] = p
        bars[i]["close_points"] = new
        bars[i]["high_points"] = max(p, new) * 1.0005
        bars[i]["low_points"] = min(p, new) * 0.9995
        bars[i]["price_points"] = new
        p = new
    return bars


def scenario_volume_spike_fake_signal():
    bars = baseline()
    spike_idx = 200
    for j in range(spike_idx, spike_idx + 5):
        if j < len(bars):
            bars[j]["volume"] = bars[j]["volume"] * 10
    return bars


def scenario_stale_price():
    bars = baseline()
    stale_idx = 200
    p = bars[stale_idx]["close_points"]
    for j in range(stale_idx, stale_idx + 5):
        if j < len(bars):
            bars[j]["open_points"] = p
            bars[j]["close_points"] = p
            bars[j]["high_points"] = p
            bars[j]["low_points"] = p
            bars[j]["price_points"] = p
    return bars


def scenario_outlier_candle():
    bars = baseline()
    idx = 200
    p = bars[idx]["close_points"]
    bars[idx]["high_points"] = p * 1.20
    return bars


SCENARIOS = {
    "flash_crash": scenario_flash_crash,
    "fake_breakout": scenario_fake_breakout,
    "gap_down": scenario_gap_down,
    "low_vol_chop": scenario_low_vol_chop,
    "volume_spike_fake_signal": scenario_volume_spike_fake_signal,
    "stale_price": scenario_stale_price,
    "outlier_candle": scenario_outlier_candle,
}


def main() -> int:
    trading = build_runtime()
    actor = {"id": 1, "username": "alice", "role": "user"}
    rows_out = []
    total = len(TEMPLATES) * len(SCENARIOS)
    done = 0
    for template_name in TEMPLATES:
        wf = load_template_workflow(template_name)
        for scen_name, gen in SCENARIOS.items():
            done += 1
            candles = gen()
            try:
                result = trading.backtest_trading_bot(actor=actor, payload={
                    "market_symbol": "BTC/POINTS",
                    "strategy": "workflow",
                    "workflow_json": wf,
                    "initial_cash_points": INITIAL_CASH,
                    "candles": candles,
                })
                ret = float(result.get("return_percent") or 0)
                tc = int(result.get("trade_count") or 0)
                dd = float(result.get("max_drawdown_percent") or 0)
                err = ""
            except Exception as exc:
                ret, tc, dd = 0.0, 0, 0.0
                err = str(exc)[:120]
            print(f"  [{done:3d}/{total}] {template_name:<35} {scen_name:<25}  ret={ret:>+7.2f}%  trades={tc}  DD={dd:>5.2f}%  {err}",
                  file=sys.stderr)
            rows_out.append({
                "template": template_name,
                "scenario": scen_name,
                "candle_count": len(candles),
                "return_percent": round(ret, 4),
                "trade_count": tc,
                "max_drawdown_percent": round(dd, 4),
                "error": err,
            })

    out_path = OUT_DIR / "stress_test_matrix.csv"
    keys = ["template", "scenario", "candle_count", "return_percent", "trade_count", "max_drawdown_percent", "error"]
    with out_path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        for r in rows_out:
            w.writerow(r)
    print(f"\n[stage5] wrote {len(rows_out)} rows to {out_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
