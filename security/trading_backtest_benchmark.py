#!/usr/bin/env python3
"""Benchmark backtest_trading_bot performance vs candle count.

Goal: find the largest candle count that finishes in 1 minute on this host.
We bypass the 20_000 hard cap by monkey-patching MAX_BACKTEST_CANDLES so
the limit doesn't reject the input; the backtest engine itself handles
segments of BACKTEST_SEGMENT_CANDLES (10_000) internally.
"""

from __future__ import annotations

import sqlite3
import sys
import tempfile
import time
from pathlib import Path

REPO_ROOT = Path("/home/s92137/hackme_web").resolve()
sys.path.insert(0, str(REPO_ROOT))

import services.trading_engine as trading_engine_module
from services.points_chain import PointsLedgerService, ensure_points_economy_schema
from services.trading_engine import TradingEngineService, ensure_trading_schema


def _build_runtime():
    tmp = Path(tempfile.mkdtemp(prefix="bench_bt_"))
    db_path = tmp / "trading.db"

    def get_db():
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    conn = get_db()
    conn.execute(
        "CREATE TABLE users (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT NOT NULL UNIQUE, "
        "role TEXT NOT NULL DEFAULT 'user', status TEXT NOT NULL DEFAULT 'active')"
    )
    conn.execute("INSERT INTO users (username, role) VALUES ('alice', 'user')")
    ensure_points_economy_schema(conn)
    ensure_trading_schema(conn)
    conn.commit()
    conn.close()

    points = PointsLedgerService(get_db=get_db, chain_secret="bench", backup_dir=tmp / "chain")
    prices = {"BTC/POINTS": 77059}
    trading = TradingEngineService(
        get_db=get_db,
        points_service=points,
        live_price_provider=lambda symbol: prices[symbol],
    )
    trading.test_prices = prices
    return trading


def _make_candles(n: int) -> list:
    # Realistic-ish synthetic candles: cyclic mild up/down, no flat that would short-circuit indicators
    return [
        {
            "time": i,
            "time_iso": f"2024-01-01T{(i % 24):02d}:00:00+00:00",
            "open_points": 100 + (i % 7),
            "high_points": 102 + (i % 7),
            "low_points":  98 + (i % 7),
            "close_points":101 + (i % 7),
            "price_points":101 + (i % 7),
        }
        for i in range(n)
    ]


def _bench(trading, candles, *, strategy="conditional"):
    payload = {
        "market_symbol": "BTC/POINTS",
        "strategy": strategy,
        "trigger_type": "price_below",
        "trigger_price_points": 0,           # never triggers — measures pure scan cost
        "candles": candles,
    }
    actor = {"id": 1, "username": "alice", "role": "user"}
    t0 = time.perf_counter()
    result = trading.backtest_trading_bot(actor=actor, payload=payload)
    elapsed = time.perf_counter() - t0
    return elapsed, result


def main(time_budget_seconds: float = 60.0) -> int:
    # Lift the cap so we can measure beyond 20_000.
    original_cap = trading_engine_module.MAX_BACKTEST_CANDLES
    trading_engine_module.MAX_BACKTEST_CANDLES = 10_000_000
    print(f"[bench] original MAX_BACKTEST_CANDLES = {original_cap:,}")
    print(f"[bench] BACKTEST_SEGMENT_CANDLES = {trading_engine_module.BACKTEST_SEGMENT_CANDLES:,}")
    print(f"[bench] test cap set to {trading_engine_module.MAX_BACKTEST_CANDLES:,}")
    print(f"[bench] target time budget = {time_budget_seconds} s")
    print()

    trading = _build_runtime()

    # Warm up so first-call import / cache cost doesn't pollute the small sizes.
    print("[bench] warming up (1,000 candles)...")
    _bench(trading, _make_candles(1_000))

    sizes = [10_000, 50_000, 200_000, 1_000_000, 3_000_000, 7_500_000, 10_000_000]
    strategies = [
        # (label, payload_extra)
        ("conditional", {"strategy": "conditional", "trigger_type": "price_below", "trigger_price_points": 0}),
        ("dca",         {"strategy": "dca", "interval_seconds": 3600, "order_amount_points": 100}),
        ("grid",        {"strategy": "grid", "grid_levels": 10, "grid_lower_price_points": 100, "grid_upper_price_points": 110}),
    ]
    print(f"{'strategy':>14}  {'candles':>12}  {'wall (s)':>10}  {'k/sec':>12}  {'verdict':>15}")
    print("-" * 70)
    summary = []  # (strategy, max_candles_under_budget, rate)
    for label, extra in strategies:
        last_under_budget = None
        for n in sizes:
            try:
                payload = {
                    "market_symbol": "BTC/POINTS",
                    "candles": _make_candles(n),
                    **extra,
                }
                actor = {"id": 1, "username": "alice", "role": "user"}
                t0 = time.perf_counter()
                trading.backtest_trading_bot(actor=actor, payload=payload)
                elapsed = time.perf_counter() - t0
            except Exception as exc:
                print(f"{label:>14}  {n:>12,}  ERROR: {type(exc).__name__}: {str(exc)[:60]}")
                break
            rate = n / elapsed if elapsed > 0 else 0
            verdict = "✓ ok" if elapsed <= time_budget_seconds else "✗ over budget"
            if elapsed <= time_budget_seconds:
                last_under_budget = (n, elapsed, rate)
            print(f"{label:>14}  {n:>12,}  {elapsed:>10.2f}  {rate:>12,.0f}  {verdict:>15}")
            if elapsed > time_budget_seconds * 1.5:
                print(f"               (stopping {label} early — {n:,} took {elapsed:.1f}s)")
                break
        if last_under_budget:
            summary.append((label, *last_under_budget))
        print()

    last_under_budget = summary[-1] if summary else None

    print()
    print("=== Per-strategy summary (largest size completing in budget) ===")
    print(f"{'strategy':>14}  {'max candles':>14}  {'wall (s)':>10}  {'k/sec':>12}  {'projected@60s':>16}")
    for label, n, t, r in summary:
        projected = int(time_budget_seconds * r)
        print(f"{label:>14}  {n:>14,}  {t:>10.2f}  {r:>12,.0f}  {projected:>16,}")

    print()
    print("[bench] note: this is single-thread Python, no DB writes during scan,")
    print("        in-memory candles, no live-price lookup, no fee deduction events.")
    print("        Real backtests with order execution + ledger writes will be slower.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
