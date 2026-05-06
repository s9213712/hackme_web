#!/usr/bin/env python3
"""Stage 2 of the competition benchmark.

Loads pre-fetched 1h candles per asset (Stage 1 output) and runs every
competition template against every asset on the full 5y window. Computes
extended metrics (CAGR / Sharpe / Sortino / Profit Factor / Win Rate /
Avg Win/Loss / Exposure / Fee+Slippage adjustments) from the trade list
and equity curve produced by ``backtest_trading_bot``.

Output layout (under docs/COMPETITION/data/):
  raw_results.csv       1 row per (template × asset)
  raw_trades.csv        1 row per individual trade
  asset_matrix.csv      pivot of return_percent (templates × assets)
  equity/<template>__<asset>.csv  per-run equity curve
  stage2_summary.json   machine-readable

Stops with non-zero exit if a template raises an exception that we
suspect is a tester bug (and prints the full traceback so it gets filed).
"""
from __future__ import annotations

import csv
import json
import math
import sqlite3
import sys
import tempfile
import time
import traceback
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))

OUT_DIR = REPO_ROOT / "docs" / "COMPETITION" / "data"
EQUITY_DIR = OUT_DIR / "equity"
EQUITY_DIR.mkdir(parents=True, exist_ok=True)
DOCS_DIR = REPO_ROOT / "docs" / "COMPETITION"

CONFIG = json.loads((REPO_ROOT / "docs" / "COMPETITION" / "scripts" / "competition_config.json").read_text())
FEE_RATE_PERCENT = float(CONFIG["constants"]["fee_rate_percent"])
SLIPPAGE_PERCENT = float(CONFIG["constants"]["slippage_percent_main"])
INITIAL_CASH = int(CONFIG["constants"]["initial_cash_points"])

TEMPLATES = (
    CONFIG["competition_templates"]["original_12"]
    + CONFIG["competition_templates"]["codex_5"]
    + CONFIG["competition_templates"]["claude_5"]
)
ASSETS = CONFIG["assets"]


def load_candles(asset_display: str) -> list:
    p = OUT_DIR / f"candles_{asset_display}.json"
    if not p.exists():
        raise SystemExit(f"missing stage1 candles: {p}")
    data = json.loads(p.read_text())
    candles = data["candles"]
    return [
        {
            "time": int(c["ts"]),
            "time_iso": c["iso"],
            "open_points":  float(c["open"]),
            "high_points":  float(c["high"]),
            "low_points":   float(c["low"]),
            "close_points": float(c["close"]),
            "price_points": float(c["close"]),
            "volume": float(c["volume"]),
        }
        for c in candles
    ]


def load_template_workflow(name: str) -> dict:
    p = REPO_ROOT / "workflows" / "system" / f"{name}.json"
    return json.loads(p.read_text())["workflow"]


def build_runtime():
    from services.points_chain import PointsLedgerService, ensure_points_economy_schema
    from services.trading_engine import TradingEngineService, ensure_trading_schema

    tmp = Path(tempfile.mkdtemp(prefix="comp2_"))
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
    now = datetime.now().isoformat()
    # Lift the cap so 5y of 1h (43,800) fits, and set platform fee to 0.3%.
    conn.execute(
        "INSERT OR REPLACE INTO trading_settings (key, value, updated_at, updated_by) VALUES (?, ?, ?, ?)",
        ("trading.backtest_max_candles", "100000", now, "competition"),
    )
    conn.execute(
        "UPDATE trading_markets SET fee_rate_percent=?",
        (FEE_RATE_PERCENT,),
    )
    # Boot-ready gate: stamp all markets so backtest doesn't hit the gate.
    conn.execute(
        "UPDATE trading_markets SET live_price_confirmed_at=? WHERE live_price_confirmed_at IS NULL",
        ("2024-01-01T00:00:00",),
    )
    conn.commit()
    conn.close()

    points = PointsLedgerService(get_db=get_db, chain_secret="comp", backup_dir=tmp / "chain")
    trading = TradingEngineService(
        get_db=get_db,
        points_service=points,
        live_price_provider=lambda symbol: 50000.0,
    )
    trading.test_prices = {entry["market_symbol"]: 50000.0 for entry in ASSETS}
    return trading


def extract_trade_pnl(trades: list) -> tuple[list, dict]:
    """Walk the trade list as a long-only sequence and pair each sell with the
    most recent buy(s) (FIFO). Returns (per_trade_pnl, totals)."""
    from collections import deque
    open_lots = deque()  # entries: {"qty": float, "price": float}
    closed = []
    total_buy_notional = 0.0
    total_sell_notional = 0.0
    total_fee = 0.0
    for tr in trades:
        side = tr.get("side")
        qty = float(tr.get("quantity") or 0)  # decimal string in engine result
        price = float(tr.get("price_points") or 0)
        fee = float(tr.get("fee_points") or 0)
        notional = qty * price
        total_fee += fee
        if side == "buy":
            total_buy_notional += notional
            open_lots.append({"qty": qty, "price": price})
        elif side == "sell":
            total_sell_notional += notional
            remaining = qty
            entry_cost = 0.0
            while remaining > 1e-12 and open_lots:
                lot = open_lots[0]
                used = min(remaining, lot["qty"])
                entry_cost += used * lot["price"]
                lot["qty"] -= used
                remaining -= used
                if lot["qty"] <= 1e-12:
                    open_lots.popleft()
            pnl = notional - entry_cost - fee
            closed.append({"pnl": pnl, "side": "sell"})
    return closed, {
        "total_buy_notional": total_buy_notional,
        "total_sell_notional": total_sell_notional,
        "total_fee": total_fee,
        "open_lot_count": len(open_lots),
    }


def compute_exposure(trades: list, equity_curve: list) -> float:
    """Count bars that had any position. Walk trades sorted by `index` field
    and track running quantity, then mark each bar between trades."""
    if not equity_curve:
        return 0.0
    sorted_trades = sorted(trades, key=lambda t: int(t.get("index") or 0))
    n = len(equity_curve)
    qty = 0.0
    exposed_bars = 0
    trade_iter = iter(sorted_trades)
    next_trade = next(trade_iter, None)
    for bar in range(n):
        # Apply any trades that fired at this bar.
        while next_trade is not None and int(next_trade.get("index") or 0) <= bar:
            tq = float(next_trade.get("quantity") or 0)
            qty = qty + tq if next_trade.get("side") == "buy" else max(0.0, qty - tq)
            next_trade = next(trade_iter, None)
        if qty > 1e-12:
            exposed_bars += 1
    return exposed_bars / n


def compute_metrics(result: dict, *, candles: list) -> dict:
    """Derive Sharpe / Sortino / Profit Factor / Win Rate / Exposure /
    CAGR + slippage adjustment from the engine's backtest result."""
    initial = float(result.get("initial_cash_points") or INITIAL_CASH)
    final_value = float(result.get("final_value_points") or initial)
    return_percent = float(result.get("return_percent") or 0)
    max_dd = float(result.get("max_drawdown_percent") or 0)
    trade_count = int(result.get("trade_count") or 0)
    trades = result.get("trades") or []
    equity_curve = result.get("equity_curve") or []

    # Hourly returns from equity curve (ratio-based, no negative noise from cash).
    eq_values = [float(p.get("equity_points") or 0) for p in equity_curve]
    if len(eq_values) >= 2:
        hourly_returns = []
        for i in range(1, len(eq_values)):
            prev = eq_values[i - 1]
            if prev > 0:
                hourly_returns.append((eq_values[i] - prev) / prev)
            else:
                hourly_returns.append(0.0)
    else:
        hourly_returns = []

    # Sharpe / Sortino at annual scale (1h candles → sqrt(365*24)).
    annual_factor = math.sqrt(365.0 * 24.0)
    if hourly_returns:
        mean_r = sum(hourly_returns) / len(hourly_returns)
        var = sum((r - mean_r) ** 2 for r in hourly_returns) / len(hourly_returns)
        std = math.sqrt(var)
        downside = [r for r in hourly_returns if r < 0]
        if downside:
            d_mean = sum(downside) / len(downside)
            d_var = sum((r - d_mean) ** 2 for r in downside) / len(downside)
            d_std = math.sqrt(d_var)
        else:
            d_std = 0.0
        sharpe = (mean_r / std * annual_factor) if std > 0 else 0.0
        sortino = (mean_r / d_std * annual_factor) if d_std > 0 else 0.0
    else:
        sharpe = sortino = 0.0

    # CAGR over the candle span.
    span_seconds = (
        (candles[-1]["time"] - candles[0]["time"])
        if candles and len(candles) > 1
        else 0
    )
    span_years = span_seconds / (365.25 * 86400) if span_seconds else 0
    if span_years > 0 and initial > 0 and final_value > 0:
        cagr = (final_value / initial) ** (1 / span_years) - 1
        cagr_percent = cagr * 100
    else:
        cagr_percent = 0.0

    # Win/loss + profit factor from per-sell PnL.
    closed_trades, totals = extract_trade_pnl(trades)
    winning = [t["pnl"] for t in closed_trades if t["pnl"] > 0]
    losing = [t["pnl"] for t in closed_trades if t["pnl"] < 0]
    win_count = len(winning)
    loss_count = len(losing)
    win_total = sum(winning) if winning else 0.0
    loss_total = abs(sum(losing)) if losing else 0.0
    profit_factor = (win_total / loss_total) if loss_total > 0 else (float("inf") if win_total > 0 else 0.0)
    win_rate = (win_count / (win_count + loss_count) * 100.0) if (win_count + loss_count) else 0.0
    avg_win = (win_total / win_count) if win_count else 0.0
    avg_loss = (loss_total / loss_count) if loss_count else 0.0

    # Exposure: fraction of candles where we held any position (derived from
    # trade index vs bar index, since equity_curve doesn't expose position).
    exposure = compute_exposure(trades, equity_curve)

    # Fee + slippage adjustments (slippage = SLIPPAGE_PERCENT × total turnover).
    turnover = totals["total_buy_notional"] + totals["total_sell_notional"]
    slippage_cost = turnover * (SLIPPAGE_PERCENT / 100.0)
    fee_adjusted_pnl_percent = return_percent - 0  # fees already in engine
    slippage_adjusted_pnl_percent = (
        return_percent - (slippage_cost / initial * 100.0) if initial else return_percent
    )
    fee_after_negative = (return_percent < 0)  # already fee-after; flag if engine PnL negative
    slippage_after_negative = (slippage_adjusted_pnl_percent < 0)

    return {
        "return_percent": round(return_percent, 4),
        "cagr_percent": round(cagr_percent, 4),
        "sharpe": round(sharpe, 4),
        "sortino": round(sortino, 4),
        "max_drawdown_percent": round(max_dd, 4),
        "trade_count": trade_count,
        "win_count": win_count,
        "loss_count": loss_count,
        "win_rate_percent": round(win_rate, 4),
        "avg_win_points": round(avg_win, 2),
        "avg_loss_points": round(avg_loss, 2),
        "profit_factor": (round(profit_factor, 4) if profit_factor != float("inf") else 99999.0),
        "exposure": round(exposure, 4),
        "total_fee_points": round(totals["total_fee"], 2),
        "total_turnover_points": round(turnover, 2),
        "slippage_cost_points": round(slippage_cost, 2),
        "fee_adjusted_pnl_percent": round(fee_adjusted_pnl_percent, 4),
        "slippage_adjusted_pnl_percent": round(slippage_adjusted_pnl_percent, 4),
        "fee_after_negative": fee_after_negative,
        "slippage_after_negative": slippage_after_negative,
    }


def run_one(trading, *, template_name: str, asset: dict, candles: list) -> tuple[dict, list, list]:
    market_symbol = asset["market_symbol"]
    workflow = load_template_workflow(template_name)
    actor = {"id": 1, "username": "alice", "role": "user"}
    payload = {
        "market_symbol": market_symbol,
        "strategy": "workflow",
        "workflow_json": workflow,
        "initial_cash_points": INITIAL_CASH,
        "candles": candles,
    }
    t0 = time.perf_counter()
    result = trading.backtest_trading_bot(actor=actor, payload=payload)
    elapsed = time.perf_counter() - t0
    metrics = compute_metrics(result, candles=candles)
    metrics["wall_seconds"] = round(elapsed, 2)
    metrics["template"] = template_name
    metrics["asset"] = asset["display"]
    metrics["interval"] = "1h"
    metrics["candle_count"] = len(candles)
    return metrics, (result.get("trades") or []), (result.get("equity_curve") or [])


def main() -> int:
    print("[stage2] loading candles for all 5 assets...", file=sys.stderr)
    candles_by_asset = {a["display"]: load_candles(a["display"]) for a in ASSETS}

    trading = build_runtime()

    raw_results = []
    raw_trades = []
    matrix_rows = {}

    started = time.perf_counter()
    total_runs = len(TEMPLATES) * len(ASSETS)
    done = 0

    for template_name in TEMPLATES:
        matrix_rows[template_name] = {}
        for asset in ASSETS:
            done += 1
            try:
                metrics, trades, equity = run_one(
                    trading,
                    template_name=template_name,
                    asset=asset,
                    candles=candles_by_asset[asset["display"]],
                )
            except Exception as exc:
                tb = traceback.format_exc()
                print(f"\n[stage2] FATAL error on {template_name} × {asset['display']}:\n{tb}", file=sys.stderr)
                # Save state for issue filing.
                err_path = OUT_DIR / "stage2_error.txt"
                err_path.write_text(f"{template_name} × {asset['display']}\n\n{tb}")
                print(f"[stage2] wrote {err_path}", file=sys.stderr)
                return 3

            print(
                f"  [{done:3d}/{total_runs}] {template_name:<35} {asset['display']:<5} "
                f"ret={metrics['return_percent']:>+8.2f}%  trades={metrics['trade_count']:>3}  "
                f"DD={metrics['max_drawdown_percent']:>5.2f}%  "
                f"PF={metrics['profit_factor']:>7.2f}  "
                f"Sharpe={metrics['sharpe']:>+5.2f}  "
                f"{metrics['wall_seconds']:>5.1f}s",
                file=sys.stderr,
            )
            raw_results.append(metrics)
            for tr in trades:
                tr_row = dict(tr)
                tr_row["template"] = template_name
                tr_row["asset"] = asset["display"]
                raw_trades.append(tr_row)
            # Persist equity curve as compact CSV. Engine's equity_curve uses
            # ``time`` (unix ts) and ``price_points`` keys; derive ISO from ts.
            eq_path = EQUITY_DIR / f"{template_name}__{asset['display']}.csv"
            with eq_path.open("w", newline="") as f:
                w = csv.writer(f)
                w.writerow(["bar_index", "candle_time", "candle_iso", "price", "equity_points"])
                for i, p in enumerate(equity):
                    ts = int(p.get("time") or 0)
                    iso = (
                        datetime.utcfromtimestamp(ts).isoformat() + "+00:00"
                        if ts else ""
                    )
                    w.writerow([
                        i,
                        ts,
                        iso,
                        p.get("price_points", ""),
                        p.get("equity_points", ""),
                    ])
            matrix_rows[template_name][asset["display"]] = metrics["return_percent"]

    elapsed_total = time.perf_counter() - started

    # Write outputs.
    raw_results_path = OUT_DIR / "raw_results.csv"
    metric_keys = list(raw_results[0].keys()) if raw_results else []
    with raw_results_path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=metric_keys)
        w.writeheader()
        for row in raw_results:
            w.writerow(row)

    raw_trades_path = OUT_DIR / "raw_trades.csv"
    if raw_trades:
        keys = sorted({k for tr in raw_trades for k in tr.keys()})
        with raw_trades_path.open("w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=keys)
            w.writeheader()
            for row in raw_trades:
                w.writerow(row)

    matrix_path = OUT_DIR / "asset_matrix.csv"
    with matrix_path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["template"] + [a["display"] for a in ASSETS])
        for tn in TEMPLATES:
            w.writerow([tn] + [matrix_rows[tn].get(a["display"], "") for a in ASSETS])

    summary = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "total_runs": total_runs,
        "wall_seconds": round(elapsed_total, 2),
        "fee_rate_percent": FEE_RATE_PERCENT,
        "slippage_percent": SLIPPAGE_PERCENT,
        "initial_cash_points": INITIAL_CASH,
        "templates": TEMPLATES,
        "assets": [a["display"] for a in ASSETS],
    }
    (OUT_DIR / "stage2_summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False))

    print(f"\n[stage2] complete: {total_runs} runs in {elapsed_total:.1f}s", file=sys.stderr)
    print(f"  → {raw_results_path}", file=sys.stderr)
    print(f"  → {raw_trades_path}  ({len(raw_trades)} trades)", file=sys.stderr)
    print(f"  → {matrix_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
