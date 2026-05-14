#!/usr/bin/env python3
"""Backtest the current shipped system workflow templates over multiple intervals.

Fetches BTC/USDT candles from Binance, runs each template's backtest at
4 time horizons (6mo / 1yr / 3yr / 5yr where the dataset allows), and
writes a JSON ranking. Optionally rewrites the 4 templates that ship with
hardcoded absolute price thresholds to use relative-only conditions.

Usage:
    python scripts/trading/competition/workflow_template_backtest_benchmark.py \
        --interval 1h \
        [--use-relative-thresholds] \
        [--out PATH]

Supported intervals: 5m, 15m, 1h, 4h, 4d (4d is resampled from 1d locally;
Binance does not expose 4d natively).

Default output contract:
    - 1h, default thresholds  -> public/data/workflow_template_benchmarks.json
    - anything else           -> public/data/workflow_template_benchmarks_<variant>.json
"""
from __future__ import annotations

import argparse
import copy
import json
import sqlite3
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))

WORKFLOWS_DIR = REPO_ROOT / "workflows" / "trading_bot"
# Plan B (N=11 keep set) — covers head-to-head finalists + 4 trend
# followers + 2 mean-reversion + 3 exit-only tools.  Order matters only
# for report aesthetics: finalists first, then by composite score.
TEMPLATES = [
    "dipbuy_rsi35_70_size99_late_tp15_nopyr_codex",  # head-to-head winner
    "auto_search_winner_claude_rev3_return",          # head-to-head runner-up
    "ma200_trend_entry",                              # trend follower
    "breakout_buy",                                   # trend follower
    "ma_pullback",                                    # trend follower
    "dip_buy",                                        # mid trend
    "kd_momentum",                                    # mid trend
    "bollinger_reversion",                            # mean reversion
    "risk_guard",                                     # exit-only tool
    "staged_profit_taking",                           # exit-only tool
    "stop_loss",                                      # exit-only tool
]

# Each interval's K-bars-per-day for slicing windows; 4d is custom.
INTERVAL_BARS_PER_DAY = {
    "5m": 24 * 12,
    "15m": 24 * 4,
    "1h": 24,
    "4h": 6,
    "4d": 1 / 4.0,
}
WINDOWS = [("6mo", 6 * 30), ("1yr", 365), ("3yr", 3 * 365), ("5yr", 5 * 365)]
INITIAL_CASH = 100_000
CANONICAL_BENCHMARK_FILENAME = "workflow_template_benchmarks.json"


# ─── Relative-threshold rewrites ──────────────────────────────────────────────
# The currently shipped templates are already relative-only and do not need
# automatic rewrites for benchmark variants.
RELATIVE_THRESHOLD_REWRITES = {}


def maybe_rewrite_to_relative(template_name: str, workflow: dict, *, use_relative: bool) -> dict:
    """Return a (possibly modified) workflow with absolute thresholds replaced."""
    if not use_relative:
        return workflow
    rewrite = RELATIVE_THRESHOLD_REWRITES.get(template_name)
    if not rewrite:
        return workflow
    new_wf = copy.deepcopy(workflow)
    target = rewrite["find"]
    replacement = rewrite["replace"]
    for node in new_wf.get("nodes", []):
        cond = node.get("condition") or {}
        if cond.get("type") == target["type"] and cond.get("value") == target.get("value"):
            node["condition"] = dict(replacement)
    return new_wf


def default_output_path(interval: str, *, use_relative_thresholds: bool = False) -> Path:
    """Return the default benchmark asset path for the given variant.

    The frontend currently consumes the canonical 1h/default-threshold asset.
    Other interval/variant outputs stay as explicitly suffixed auxiliary files so
    local benchmark reruns do not silently diverge from the shipped frontend
    contract.
    """
    if interval == "1h" and not use_relative_thresholds:
        return REPO_ROOT / "public" / "data" / CANONICAL_BENCHMARK_FILENAME
    variant = interval
    if use_relative_thresholds:
        variant = f"{variant}_relative"
    return REPO_ROOT / "public" / "data" / f"workflow_template_benchmarks_{variant}.json"


# ─── Data fetch ────────────────────────────────────────────────────────────────
def _http_get_json(url: str) -> object:
    req = Request(url, headers={"User-Agent": "workflow-bench/1.0"})
    with urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def fetch_binance_candles(interval: str, total: int) -> list:
    """Fetch the most recent ``total`` candles for BTC/USDT at the given interval.

    For 4d, fetches 1d and resamples locally (Binance has no 4d endpoint).
    """
    binance_interval = "1d" if interval == "4d" else interval
    fetch_total = total * 4 if interval == "4d" else total
    candles_raw = []
    end_ms = int(time.time() * 1000)
    fetched = 0
    while fetched < fetch_total:
        chunk = min(1000, fetch_total - fetched)
        params = {"symbol": "BTCUSDT", "interval": binance_interval, "limit": chunk, "endTime": end_ms}
        url = "https://api.binance.com/api/v3/klines?" + urlencode(params)
        rows = _http_get_json(url)
        if not isinstance(rows, list) or not rows:
            break
        candles_raw = rows + candles_raw
        end_ms = rows[0][0] - 1
        fetched += len(rows)
        time.sleep(0.15)
        print(f"  fetched {fetched}/{fetch_total} {binance_interval} candles...", file=sys.stderr)
    candles_raw.sort(key=lambda r: r[0])
    if interval == "4d":
        candles_raw = _resample_to_4d(candles_raw)
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


def _resample_to_4d(daily_rows: list) -> list:
    """Bucket every 4 daily candles into one 4d candle (open=first, high=max, low=min, close=last)."""
    out = []
    for i in range(0, len(daily_rows), 4):
        chunk = daily_rows[i:i + 4]
        if len(chunk) < 4:
            continue  # drop the trailing incomplete bucket
        out.append([
            chunk[0][0],                                   # open time = first day open ms
            chunk[0][1],                                   # open
            max(float(r[2]) for r in chunk),               # high
            min(float(r[3]) for r in chunk),               # low
            chunk[-1][4],                                  # close
            sum(float(r[5]) for r in chunk),               # volume
        ])
    return out


# ─── Runtime + run ────────────────────────────────────────────────────────────
def build_runtime():
    from services.points_chain.schema import ensure_points_economy_schema
    from services.points_chain.service import PointsLedgerService
    from services.trading.engine import TradingEngineService, ensure_trading_schema

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
    # Lift the cap so even 5y of 5m (~525K candles) fits.
    conn.execute(
        "INSERT OR REPLACE INTO trading_settings (key, value, updated_at, updated_by) VALUES (?, ?, ?, ?)",
        ("trading.backtest_max_candles", "1000000", datetime.now().isoformat(), "bench"),
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
    return json.loads((WORKFLOWS_DIR / f"{name}.json").read_text())


def run_backtest(trading, *, template_name: str, candles: list, use_relative: bool) -> dict:
    template = load_template(template_name)
    workflow = maybe_rewrite_to_relative(template_name, template["workflow"], use_relative=use_relative)
    payload = {
        "market_symbol": "BTC/POINTS",
        "strategy": "workflow",
        "workflow_json": workflow,
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


def derive_window_sizes(interval: str, available: int) -> list:
    bars_per_day = INTERVAL_BARS_PER_DAY[interval]
    out = []
    for label, days in WINDOWS:
        size = max(2, int(round(days * bars_per_day))) if bars_per_day >= 1 else max(2, int(round(days * bars_per_day)))
        if size > available:
            continue
        out.append((label, size))
    return out


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--interval", required=True, choices=list(INTERVAL_BARS_PER_DAY.keys()))
    parser.add_argument("--use-relative-thresholds", action="store_true",
                        help="Rewrite the 4 absolute-threshold templates to relative versions before running")
    parser.add_argument("--out", default=None,
                        help="Output JSON path (default: canonical 1h asset or interval-suffixed variant)")
    parser.add_argument("--total-candles", type=int, default=None,
                        help="How many candles of this interval to fetch (default: 5y or what's available)")
    args = parser.parse_args()

    bars_per_day = INTERVAL_BARS_PER_DAY[args.interval]
    if args.total_candles is None:
        target = int(round(5 * 365 * bars_per_day))
    else:
        target = args.total_candles

    print(f"\n=== Workflow template benchmark — interval={args.interval}, "
          f"relative_thresholds={'on' if args.use_relative_thresholds else 'off'} ===", file=sys.stderr)
    print(f"Target candle count: {target:,}", file=sys.stderr)
    fetch_started = time.perf_counter()
    candles_full = fetch_binance_candles(args.interval, target)
    fetch_elapsed = time.perf_counter() - fetch_started
    print(f"Got {len(candles_full)} candles, {candles_full[0]['time_iso']} → {candles_full[-1]['time_iso']} "
          f"(fetch {fetch_elapsed:.1f}s)", file=sys.stderr)

    trading = build_runtime()
    out = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "data_source": f"binance_btcusdt_{args.interval}",
        "interval": args.interval,
        "use_relative_thresholds": bool(args.use_relative_thresholds),
        "candle_count_total": len(candles_full),
        "first_candle_iso": candles_full[0]["time_iso"],
        "last_candle_iso":  candles_full[-1]["time_iso"],
        "initial_cash_points": INITIAL_CASH,
        "fetch_seconds": round(fetch_elapsed, 2),
        "windows": [],
        "relative_threshold_rewrites": (
            {
                k: {"label_change": v["label_change"]}
                for k, v in RELATIVE_THRESHOLD_REWRITES.items()
            } if args.use_relative_thresholds else {}
        ),
    }

    bench_started = time.perf_counter()
    for window_label, window_size in derive_window_sizes(args.interval, len(candles_full)):
        sliced = candles_full[-window_size:]
        actual = len(sliced)
        print(f"\n--- Window {window_label} ({actual} candles) ---", file=sys.stderr)
        runs = []
        for tname in TEMPLATES:
            row = run_backtest(trading, template_name=tname, candles=sliced,
                               use_relative=args.use_relative_thresholds)
            print(f"  {row['label']:<32} pnl={row.get('pnl_percent', 'ERR'):>9} "
                  f"trades={row.get('trade_count', 'ERR')}", file=sys.stderr)
            runs.append(row)
        runs.sort(key=lambda r: r.get("pnl_percent", -1e9), reverse=True)
        out["windows"].append({
            "label": window_label,
            "candle_count": actual,
            "rankings": runs,
        })
    bench_elapsed = time.perf_counter() - bench_started
    out["benchmark_seconds"] = round(bench_elapsed, 2)
    out["total_seconds"] = round(fetch_elapsed + bench_elapsed, 2)

    out_path = Path(args.out) if args.out else default_output_path(
        args.interval,
        use_relative_thresholds=args.use_relative_thresholds,
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2))
    print(f"\nFetch={fetch_elapsed:.1f}s  Bench={bench_elapsed:.1f}s  Total={fetch_elapsed + bench_elapsed:.1f}s",
          file=sys.stderr)
    print(f"Wrote {out_path}", file=sys.stderr)


if __name__ == "__main__":
    main()
