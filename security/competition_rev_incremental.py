#!/usr/bin/env python3
"""Incrementally add `triple_trend_recovery_claude_rev` to all competition
CSV outputs without re-running the full 110-row main matrix.

Steps:
  - Run main matrix on rev × 5 assets (5 backtests) → append to raw_results.csv,
    raw_trades.csv, asset_matrix.csv, equity/*.csv
  - Run stress test on rev × 7 scenarios → append to stress_test_matrix.csv
"""
from __future__ import annotations

import csv
import json
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "security"))

from datetime import datetime, timezone
from competition_stage2_matrix import (
    build_runtime, load_candles, load_template_workflow, run_one,
    ASSETS, INITIAL_CASH,
)
from competition_stage5_stress import SCENARIOS

OUT_DIR = REPO_ROOT / "public" / "data" / "competition"
EQUITY_DIR = OUT_DIR / "equity"
TEMPLATE = "triple_trend_recovery_claude_rev"


def append_main_matrix(trading) -> None:
    raw_results_path = OUT_DIR / "raw_results.csv"
    raw_trades_path = OUT_DIR / "raw_trades.csv"
    matrix_path = OUT_DIR / "asset_matrix.csv"

    existing_keys = list(csv.DictReader(open(raw_results_path)).fieldnames or [])

    new_rows = []
    new_trades = []
    asset_returns = {}
    for asset in ASSETS:
        candles = load_candles(asset["display"])
        t0 = time.perf_counter()
        metrics, trades, equity = run_one(
            trading, template_name=TEMPLATE, asset=asset, candles=candles
        )
        elapsed = time.perf_counter() - t0
        print(f"  rev × {asset['display']:<5}  ret={metrics['return_percent']:>+8.2f}  trades={metrics['trade_count']:>3}  DD={metrics['max_drawdown_percent']:>5.2f}  PF={metrics['profit_factor']:>7.2f}  {elapsed:.1f}s",
              file=sys.stderr)
        new_rows.append(metrics)
        for tr in trades:
            tr_row = dict(tr)
            tr_row["template"] = TEMPLATE
            tr_row["asset"] = asset["display"]
            new_trades.append(tr_row)
        eq_path = EQUITY_DIR / f"{TEMPLATE}__{asset['display']}.csv"
        with eq_path.open("w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["bar_index", "candle_time", "candle_iso", "price", "equity_points"])
            for i, p in enumerate(equity):
                ts = int(p.get("time") or 0)
                iso = (datetime.utcfromtimestamp(ts).isoformat() + "+00:00") if ts else ""
                w.writerow([i, ts, iso, p.get("price_points", ""), p.get("equity_points", "")])
        asset_returns[asset["display"]] = metrics["return_percent"]

    # Append to raw_results.csv
    with raw_results_path.open("a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=existing_keys, extrasaction="ignore")
        for row in new_rows:
            w.writerow(row)

    # Append to raw_trades.csv
    if new_trades:
        keys = list(csv.DictReader(open(raw_trades_path)).fieldnames or [])
        with raw_trades_path.open("a", newline="") as f:
            w = csv.DictWriter(f, fieldnames=keys, extrasaction="ignore")
            for row in new_trades:
                w.writerow(row)

    # Append to asset_matrix.csv
    with matrix_path.open("a", newline="") as f:
        w = csv.writer(f)
        w.writerow([TEMPLATE] + [asset_returns.get(a["display"], "") for a in ASSETS])

    print(f"\n[main] appended {len(new_rows)} runs, {len(new_trades)} trades", file=sys.stderr)


def append_stress(trading) -> None:
    stress_path = OUT_DIR / "stress_test_matrix.csv"
    actor = {"id": 1, "username": "alice", "role": "user"}
    wf = load_template_workflow(TEMPLATE)
    new_rows = []
    for scen_name, gen in SCENARIOS.items():
        candles = gen()
        try:
            result = trading.backtest_trading_bot(actor=actor, payload={
                "market_symbol": "BTC/POINTS", "strategy": "workflow",
                "workflow_json": wf, "initial_cash_points": INITIAL_CASH,
                "candles": candles,
            })
            ret = float(result.get("return_percent") or 0)
            tc = int(result.get("trade_count") or 0)
            dd = float(result.get("max_drawdown_percent") or 0)
            err = ""
        except Exception as exc:
            ret, tc, dd = 0.0, 0, 0.0
            err = str(exc)[:120]
        print(f"  stress × {scen_name:<25}  ret={ret:>+7.2f}%  trades={tc}  DD={dd:>5.2f}%", file=sys.stderr)
        new_rows.append({
            "template": TEMPLATE, "scenario": scen_name,
            "candle_count": len(candles),
            "return_percent": round(ret, 4), "trade_count": tc,
            "max_drawdown_percent": round(dd, 4), "error": err,
        })

    keys = list(csv.DictReader(open(stress_path)).fieldnames or [])
    with stress_path.open("a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=keys, extrasaction="ignore")
        for row in new_rows:
            w.writerow(row)
    print(f"\n[stress] appended {len(new_rows)} rows", file=sys.stderr)


def main() -> int:
    trading = build_runtime()
    print(f"=== Adding {TEMPLATE} to all competition CSVs ===\n", file=sys.stderr)
    append_main_matrix(trading)
    print()
    append_stress(trading)
    return 0


if __name__ == "__main__":
    sys.exit(main())
