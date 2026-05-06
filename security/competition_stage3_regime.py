#!/usr/bin/env python3
"""Stage 3 — Regime breakdown.

Slices the per-(template, asset) equity curves produced by Stage 2 into
five regime windows defined in competition_config.json (BTC bull / bear
/ range / high-vol / low-vol). Computes per-regime return%, max
drawdown, trade count, and writes:

  public/data/competition/regime_matrix.csv  long-format rows

This stage does NOT re-run backtests — it just re-aggregates Stage 2
equity curves and trade logs against the regime calendar windows.
"""
from __future__ import annotations

import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = REPO_ROOT / "public" / "data" / "competition"
EQUITY_DIR = OUT_DIR / "equity"
CONFIG = json.loads((REPO_ROOT / "security" / "competition_config.json").read_text())
TEMPLATES = (
    CONFIG["competition_templates"]["original_12"]
    + CONFIG["competition_templates"]["codex_5"]
    + CONFIG["competition_templates"]["claude_5"]
)
ASSETS = [a["display"] for a in CONFIG["assets"]]
REGIMES = CONFIG["regimes"]


def parse_iso_to_ts(iso: str) -> int:
    dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp())


def regime_window_ts(regime_def: dict) -> tuple[int, int]:
    return (
        parse_iso_to_ts(regime_def["start"] + "T00:00:00+00:00"),
        parse_iso_to_ts(regime_def["end"]   + "T23:59:59+00:00"),
    )


def load_equity(template: str, asset: str) -> list:
    p = EQUITY_DIR / f"{template}__{asset}.csv"
    if not p.exists():
        return []
    rows = []
    with p.open() as f:
        reader = csv.DictReader(f)
        for r in reader:
            rows.append({
                "bar_index": int(r["bar_index"]),
                "ts": int(r["candle_time"]) if r["candle_time"] else 0,
                "iso": r["candle_iso"],
                "price": float(r["price"]) if r["price"] else 0,
                "equity": float(r["equity_points"]) if r["equity_points"] else 0,
            })
    return rows


def load_trades(raw_trades_csv: Path) -> dict:
    """Returns {(template, asset): [trades...]} from raw_trades.csv."""
    out: dict = {}
    if not raw_trades_csv.exists():
        return out
    with raw_trades_csv.open() as f:
        reader = csv.DictReader(f)
        for r in reader:
            key = (r["template"], r["asset"])
            out.setdefault(key, []).append(r)
    return out


def slice_metrics(equity_rows: list, trade_rows: list, *, ts_start: int, ts_end: int) -> dict:
    """Compute per-window return, max DD, trade count from equity curve slice."""
    sliced = [r for r in equity_rows if ts_start <= r["ts"] <= ts_end]
    if len(sliced) < 2:
        return {"insufficient_data": True}
    eq_start = sliced[0]["equity"]
    eq_end = sliced[-1]["equity"]
    return_percent = ((eq_end - eq_start) / eq_start * 100.0) if eq_start > 0 else 0.0
    peak = sliced[0]["equity"]
    max_dd_percent = 0.0
    for r in sliced:
        if r["equity"] > peak:
            peak = r["equity"]
        if peak > 0:
            dd = (peak - r["equity"]) / peak * 100.0
            if dd > max_dd_percent:
                max_dd_percent = dd
    trades_in = [t for t in trade_rows if int(t.get("time") or 0) >= ts_start and int(t.get("time") or 0) <= ts_end]
    return {
        "insufficient_data": False,
        "candle_count": len(sliced),
        "return_percent": round(return_percent, 4),
        "max_drawdown_percent": round(max_dd_percent, 4),
        "trade_count": len(trades_in),
        "first_iso": sliced[0]["iso"],
        "last_iso": sliced[-1]["iso"],
    }


def main() -> int:
    raw_trades_path = OUT_DIR / "raw_trades.csv"
    trades_index = load_trades(raw_trades_path)
    print(f"[stage3] loaded {sum(len(v) for v in trades_index.values())} trades from raw_trades.csv", file=sys.stderr)

    rows_out = []
    skipped = 0
    for template in TEMPLATES:
        for asset in ASSETS:
            equity = load_equity(template, asset)
            if not equity:
                skipped += 1
                continue
            trades = trades_index.get((template, asset), [])
            for regime_key, regime_def in REGIMES.items():
                ts_start, ts_end = regime_window_ts(regime_def)
                metrics = slice_metrics(equity, trades, ts_start=ts_start, ts_end=ts_end)
                row = {
                    "template": template,
                    "asset": asset,
                    "regime": regime_key,
                    "regime_label": regime_def["label"],
                    "regime_start": regime_def["start"],
                    "regime_end": regime_def["end"],
                    **metrics,
                }
                rows_out.append(row)

    out_path = OUT_DIR / "regime_matrix.csv"
    if rows_out:
        keys = ["template", "asset", "regime", "regime_label", "regime_start", "regime_end",
                "candle_count", "return_percent", "max_drawdown_percent", "trade_count",
                "first_iso", "last_iso", "insufficient_data"]
        with out_path.open("w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=keys, extrasaction="ignore")
            w.writeheader()
            for r in rows_out:
                w.writerow(r)
    print(f"[stage3] wrote {len(rows_out)} regime rows to {out_path}", file=sys.stderr)
    print(f"[stage3] skipped {skipped} (template, asset) pairs with no equity curve", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
