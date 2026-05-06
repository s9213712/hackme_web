#!/usr/bin/env python3
"""Stage 7 — Baselines (NOT in competition rankings; reference only).

Five baselines, each on the 5 assets at 1h × 5y:

  buy_and_hold    : math from candles[0].close → candles[-1].close
  cash_only       : flat 0% return (sanity floor)
  fixed_dca       : engine's `dca` strategy, every 24h buy 1000 POINTS
  simple_grid     : engine's `grid` strategy, ±5% × 10 levels around start
  simple_ma_cross : tiny workflow — buy on MA20 cross above MA50, sell on cross back

Output: public/data/competition/baselines.csv
"""
from __future__ import annotations

import csv
import json
import sys
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "security"))

from competition_stage2_matrix import build_runtime, load_candles

OUT_DIR = REPO_ROOT / "public" / "data" / "competition"
CONFIG = json.loads((REPO_ROOT / "security" / "competition_config.json").read_text())
ASSETS = CONFIG["assets"]
INITIAL_CASH = int(CONFIG["constants"]["initial_cash_points"])
FEE_RATE_PERCENT = CONFIG["constants"]["fee_rate_percent"]


def buy_and_hold(candles):
    """100% deployed at candle[0] close, valued at candle[-1] close."""
    p0, p1 = float(candles[0]["close_points"]), float(candles[-1]["close_points"])
    fee = INITIAL_CASH * (FEE_RATE_PERCENT / 100.0)
    units = (INITIAL_CASH - fee) / p0
    final_value = units * p1
    ret = (final_value - INITIAL_CASH) / INITIAL_CASH * 100.0
    return {"return_percent": round(ret, 4), "trade_count": 1}


def cash_only(_):
    return {"return_percent": 0.0, "trade_count": 0}


SIMPLE_MA_CROSS = {
    "version": 2,
    "strategy_kind": "workflow_graph",
    "source": "system_template",
    "name": "simple ma cross",
    "start_node_id": "start",
    "nodes": [
        {"id": "start", "type": "start", "label": "start", "x": 0, "y": 0},
        {"id": "above50", "type": "condition", "label": "MA20>50", "x": 1, "y": 1, "condition": {"type": "ma_position", "period": 20, "position": "above"}},
        {"id": "no_pos", "type": "condition", "label": "no pos", "x": 1, "y": 2, "condition": {"type": "has_position", "value": False}},
        {"id": "and_in", "type": "logic", "label": "AND", "x": 2, "y": 1, "operator": "AND"},
        {"id": "buy", "type": "action", "label": "buy 80%", "x": 3, "y": 1, "priority": 10, "action": {"type": "buy_percent", "percent": 80, "step": 1, "order_type": "market"}},
        {"id": "below50", "type": "condition", "label": "MA20<50", "x": 1, "y": 4, "condition": {"type": "ma_position", "period": 20, "position": "below"}},
        {"id": "has_pos", "type": "condition", "label": "has pos", "x": 1, "y": 5, "condition": {"type": "has_position", "value": True}},
        {"id": "and_out", "type": "logic", "label": "AND", "x": 2, "y": 4, "operator": "AND"},
        {"id": "close", "type": "action", "label": "close", "x": 3, "y": 4, "priority": 50, "action": {"type": "close_all", "step": 1, "order_type": "market"}},
    ],
    "edges": [
        {"id": "e1", "from": "start", "from_port": "out", "to": "above50", "to_port": "in"},
        {"id": "e2", "from": "start", "from_port": "out", "to": "no_pos", "to_port": "in"},
        {"id": "e3", "from": "above50", "from_port": "true", "to": "and_in", "to_port": "in"},
        {"id": "e4", "from": "no_pos", "from_port": "true", "to": "and_in", "to_port": "in"},
        {"id": "e5", "from": "and_in", "from_port": "true", "to": "buy", "to_port": "in"},
        {"id": "e6", "from": "start", "from_port": "out", "to": "below50", "to_port": "in"},
        {"id": "e7", "from": "start", "from_port": "out", "to": "has_pos", "to_port": "in"},
        {"id": "e8", "from": "below50", "from_port": "true", "to": "and_out", "to_port": "in"},
        {"id": "e9", "from": "has_pos", "from_port": "true", "to": "and_out", "to_port": "in"},
        {"id": "e10", "from": "and_out", "from_port": "true", "to": "close", "to_port": "in"},
    ],
}


def main() -> int:
    trading = build_runtime()
    actor = {"id": 1, "username": "alice", "role": "user"}
    rows = []
    for asset in ASSETS:
        candles = load_candles(asset["display"])
        market_symbol = asset["market_symbol"]
        # Buy & hold (analytic)
        r = buy_and_hold(candles)
        rows.append({"baseline": "buy_and_hold", "asset": asset["display"],
                     "return_percent": r["return_percent"], "trade_count": r["trade_count"]})
        # Cash only
        rows.append({"baseline": "cash_only", "asset": asset["display"], "return_percent": 0.0, "trade_count": 0})
        # Fixed DCA: every 24h buy ~1000 points worth
        try:
            res = trading.backtest_trading_bot(actor=actor, payload={
                "market_symbol": market_symbol, "strategy": "dca", "interval_seconds": 86400,
                "order_amount_points": 1000, "candles": candles,
            })
            rows.append({"baseline": "fixed_dca", "asset": asset["display"],
                         "return_percent": round(float(res.get("return_percent") or 0), 4),
                         "trade_count": int(res.get("trade_count") or 0)})
        except Exception as exc:
            rows.append({"baseline": "fixed_dca", "asset": asset["display"], "error": str(exc)[:100]})
        # Simple grid: ±5% × 10
        p0 = float(candles[0]["close_points"])
        try:
            res = trading.backtest_trading_bot(actor=actor, payload={
                "market_symbol": market_symbol, "strategy": "grid",
                "lower_price_points": p0 * 0.95, "upper_price_points": p0 * 1.05,
                "grid_count": 10, "order_amount_points": 1000,
                "candles": candles,
            })
            rows.append({"baseline": "simple_grid", "asset": asset["display"],
                         "return_percent": round(float(res.get("return_percent") or 0), 4),
                         "trade_count": int(res.get("trade_count") or 0)})
        except Exception as exc:
            rows.append({"baseline": "simple_grid", "asset": asset["display"], "error": str(exc)[:100]})
        # Simple MA cross
        try:
            res = trading.backtest_trading_bot(actor=actor, payload={
                "market_symbol": market_symbol, "strategy": "workflow",
                "workflow_json": SIMPLE_MA_CROSS, "candles": candles,
            })
            rows.append({"baseline": "simple_ma_cross", "asset": asset["display"],
                         "return_percent": round(float(res.get("return_percent") or 0), 4),
                         "trade_count": int(res.get("trade_count") or 0)})
        except Exception as exc:
            rows.append({"baseline": "simple_ma_cross", "asset": asset["display"], "error": str(exc)[:100]})
        for r in rows[-5:]:
            err = r.get("error", "")
            print(f"  {r['baseline']:<20} {asset['display']:<5} ret={r.get('return_percent', 'ERR'):>+10}  trades={r.get('trade_count', '-')}  {err}", file=sys.stderr)

    out_path = OUT_DIR / "baselines.csv"
    keys = ["baseline", "asset", "return_percent", "trade_count", "error"]
    with out_path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=keys, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)
    print(f"[stage7] wrote {len(rows)} rows to {out_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
