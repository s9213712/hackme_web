#!/usr/bin/env python3
"""Backtest the 12 system workflow templates over 6mo/1yr/3yr/5yr windows.

Fetches BTC/USDT 1h candles from Binance, then for each template runs the
backtest at 4 time horizons. Outputs a JSON summary suitable for embedding
in the frontend as user reference.

Usage:
    python security/workflow_template_backtest_benchmark.py [--out PATH]

Defaults:
    --out  public/data/workflow_template_benchmarks.json

The frontend (public/js/56-trading.js → renderTradingWorkflowTemplateBenchmark)
fetches this JSON to display per-template historical PnL next to the
template explanation panel.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

WORKFLOWS_DIR = REPO_ROOT / "workflows" / "system"
TEMPLATES = [
    "bollinger_reversion",
    "breakout_buy",
    "dip_buy",
    "full_entry_exit",
    "kd_momentum",
    "ma200_trend_entry",
    "ma_pullback",
    "risk_guard",
    "rsi_scale",
    "staged_profit_taking",
    "stop_loss",
    "swing_bb_ma50",
]
WINDOWS = [
    ("6mo",  6 * 30 * 24),     # 4,320 candles
    ("1yr",  365 * 24),         # 8,760
    ("3yr",  3 * 365 * 24),     # 26,280
    ("5yr",  5 * 365 * 24),     # 43,800
]
INITIAL_CASH = 100_000


def _http_get_json(url: str) -> object:
    req = Request(url, headers={"User-Agent": "workflow-bench/1.0"})
    with urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def fetch_binance_1h_candles(total: int) -> list:
    """Fetch the most recent ``total`` 1h candles for BTC/USDT in ascending order."""
    candles_raw = []
    end_ms = int(time.time() * 1000)
    fetched = 0
    while fetched < total:
        chunk = min(1000, total - fetched)
        params = {"symbol": "BTCUSDT", "interval": "1h", "limit": chunk, "endTime": end_ms}
        url = "https://api.binance.com/api/v3/klines?" + urlencode(params)
        rows = _http_get_json(url)
        if not isinstance(rows, list) or not rows:
            break
        candles_raw = rows + candles_raw
        end_ms = rows[0][0] - 1
        fetched += len(rows)
        time.sleep(0.15)  # be polite
        print(f"  fetched {fetched}/{total} 1h candles...", file=sys.stderr)
    candles_raw.sort(key=lambda r: r[0])
    return [
        {
            "time": int(row[0] // 1000),
            "time_iso": datetime.fromtimestamp(row[0] / 1000, tz=timezone.utc).isoformat(),
            "open_points":  float(row[1]),
            "high_points":  float(row[2]),
            "low_points":   float(row[3]),
            "close_points": float(row[4]),
            "price_points": float(row[4]),
            "volume": float(row[5]),
        }
        for row in candles_raw
    ]


def build_runtime():
    from services.points_chain import PointsLedgerService, ensure_points_economy_schema
    from services.trading_engine import TradingEngineService, ensure_trading_schema

    tmp = Path(tempfile.mkdtemp(prefix="wfbench_"))
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
    # raise the cap so 5-year (43,800) backtests fit
    conn.execute(
        "INSERT OR REPLACE INTO trading_settings (key, value, updated_at, updated_by) VALUES (?, ?, ?, ?)",
        ("trading.backtest_max_candles", "100000", datetime.now().isoformat(), "bench"),
    )
    conn.commit()
    conn.close()

    points = PointsLedgerService(get_db=get_db, chain_secret="bench", backup_dir=tmp / "chain")
    trading = TradingEngineService(
        get_db=get_db,
        points_service=points,
        live_price_provider=lambda symbol: 50000.0,
    )
    trading.test_prices = {"BTC/POINTS": 50000.0}
    return trading


def load_template(name: str) -> dict:
    path = WORKFLOWS_DIR / f"{name}.json"
    return json.loads(path.read_text())


def run_backtest(trading, *, template_name: str, candles: list) -> dict:
    template = load_template(template_name)
    payload = {
        "market_symbol": "BTC/POINTS",
        "strategy": "workflow",
        "workflow_json": template["workflow"],
        "initial_cash_points": INITIAL_CASH,
        "candles": candles,
    }
    actor = {"id": 1, "username": "alice", "role": "user"}
    t0 = time.perf_counter()
    try:
        result = trading.backtest_trading_bot(actor=actor, payload=payload)
    except Exception as exc:
        return {
            "template": template_name,
            "label": template.get("label") or template_name,
            "error": str(exc)[:200],
            "candle_count": len(candles),
        }
    elapsed = time.perf_counter() - t0
    final_equity = result.get("final_equity_points") or result.get("final_value_points") or 0
    initial = result.get("initial_cash_points") or INITIAL_CASH
    pnl_percent = ((final_equity - initial) / initial * 100.0) if initial else 0.0
    return {
        "template": template_name,
        "label": template.get("label") or template_name,
        "candle_count": len(candles),
        "trade_count": result.get("trade_count") or 0,
        "final_equity_points": final_equity,
        "initial_cash_points": initial,
        "pnl_percent": round(pnl_percent, 2),
        "max_drawdown_percent": round(float(result.get("max_drawdown_percent") or 0), 2),
        "wall_seconds": round(elapsed, 2),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default=str(REPO_ROOT / "public" / "data" / "workflow_template_benchmarks.json"))
    parser.add_argument("--total-candles", type=int, default=WINDOWS[-1][1])
    args = parser.parse_args()

    print(f"Fetching {args.total_candles} 1h BTC/USDT candles from Binance...", file=sys.stderr)
    candles_full = fetch_binance_1h_candles(args.total_candles)
    print(f"  got {len(candles_full)} candles, {candles_full[0]['time_iso']} → {candles_full[-1]['time_iso']}", file=sys.stderr)

    trading = build_runtime()
    out = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "data_source": "binance_btcusdt_1h",
        "candle_count_total": len(candles_full),
        "first_candle_iso": candles_full[0]["time_iso"],
        "last_candle_iso":  candles_full[-1]["time_iso"],
        "initial_cash_points": INITIAL_CASH,
        "windows": [],
    }
    for window_label, window_size in WINDOWS:
        sliced = candles_full[-window_size:] if window_size <= len(candles_full) else candles_full
        actual = len(sliced)
        print(f"\n=== Window {window_label} ({actual} candles) ===", file=sys.stderr)
        runs = []
        for tname in TEMPLATES:
            row = run_backtest(trading, template_name=tname, candles=sliced)
            print(f"  {row['label']:<32} pnl={row.get('pnl_percent', 'ERR'):>8} trades={row.get('trade_count', 'ERR')}", file=sys.stderr)
            runs.append(row)
        runs.sort(key=lambda r: r.get("pnl_percent", -1e9), reverse=True)
        out["windows"].append({
            "label": window_label,
            "candle_count": actual,
            "rankings": runs,
        })

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2))
    print(f"\nWrote {out_path}", file=sys.stderr)


if __name__ == "__main__":
    main()
