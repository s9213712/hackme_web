#!/usr/bin/env python3
"""Sky-floor grid (天地網格) baseline comparison.

Tests multiple grid configurations against the same 5 assets / 5y / 1h
candles used in the main competition. The aim is to see whether a wider
range or more grids materially improves the simple_grid baseline.

Configs (`(label, lower_factor, upper_factor, grid_count, order_amount)`):
  baseline_50pct   ±50% × 20 × 5K   (current report's baseline)
  skyfloor_narrow  ±80% × 50 × 2K   (wider range, more grids, same deploy)
  skyfloor_mid     0.1×p0 → 3.0×p0 × 50 × 2K   (covers -90% / +200%)
  skyfloor_wide    0.1×p0 → 3.0×p0 × 100 × 1K  (100 levels, 100% max deploy)
  skyfloor_5x      0.05×p0 → 5.0×p0 × 100 × 1K (extreme: cover -95% / +400%)

Output: docs/COMPETITION/GRID_SKYFLOOR_COMPARISON.md
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

from competition_stage2_matrix import build_runtime, load_candles, ASSETS, INITIAL_CASH

CONFIGS = [
    ("baseline_50pct",  0.50, 1.50,  20, 5000),
    ("skyfloor_narrow", 0.20, 1.80,  50, 2000),
    ("skyfloor_mid",    0.10, 3.00,  50, 2000),
    ("skyfloor_wide",   0.10, 3.00, 100, 1000),
    ("skyfloor_5x",     0.05, 5.00, 100, 1000),
]


def main() -> int:
    trading = build_runtime()
    actor = {"id": 1, "username": "alice", "role": "user"}

    rows = []
    print(f"{'config':<20} {'asset':<5} {'lower':>10} {'upper':>10} {'grids':>5} {'amt':>5}  {'ret%':>9} {'trades':>5} {'wall':>5}")
    print("-" * 95)
    for cfg_label, lo_f, up_f, grids, amt in CONFIGS:
        for asset in ASSETS:
            candles = load_candles(asset["display"])
            p0 = float(candles[0]["close_points"])
            lower = p0 * lo_f
            upper = p0 * up_f
            t0 = time.perf_counter()
            try:
                res = trading.backtest_trading_bot(actor=actor, payload={
                    "market_symbol": asset["market_symbol"], "strategy": "grid",
                    "lower_price_points": lower, "upper_price_points": upper,
                    "grid_count": grids, "order_amount_points": amt,
                    "candles": candles,
                })
                ret = float(res.get("return_percent") or 0)
                tc = int(res.get("trade_count") or 0)
                err = ""
            except Exception as exc:
                ret, tc = 0.0, 0
                err = str(exc)[:80]
            elapsed = time.perf_counter() - t0
            print(f"{cfg_label:<20} {asset['display']:<5} {lower:>10.2f} {upper:>10.2f} {grids:>5} {amt:>5}  {ret:>+8.2f} {tc:>5} {elapsed:>4.1f}s")
            rows.append({
                "config": cfg_label, "asset": asset["display"],
                "lower": round(lower, 2), "upper": round(upper, 2),
                "grids": grids, "order_amount": amt,
                "return_percent": round(ret, 4), "trade_count": tc,
                "wall_seconds": round(elapsed, 2), "error": err,
            })

    out_csv = REPO_ROOT / "public" / "data" / "competition" / "grid_skyfloor_comparison.csv"
    keys = ["config", "asset", "lower", "upper", "grids", "order_amount", "return_percent", "trade_count", "wall_seconds", "error"]
    with out_csv.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=keys, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)
    print(f"\n[done] wrote {out_csv}", file=sys.stderr)

    # Build markdown
    docs = REPO_ROOT / "docs" / "COMPETITION" / "GRID_SKYFLOOR_COMPARISON.md"
    lines = ["# Grid 天地網格參數比較", "",
             "對 5 個資產 5y 1h candles 跑不同 grid 設定，看「拉寬範圍 / 增加格數」對 simple_grid baseline 的影響。",
             "", "**統一條件**: fee 0.3%，slippage 0.1%（事後計算），initial cash 100K POINTS。", "",
             "## 配置對照", "",
             "| Config | 範圍 | 格數 | 每格金額 | 最大 deploy（半邊填滿）|",
             "|---|---|---:|---:|---:|"]
    for cfg_label, lo_f, up_f, grids, amt in CONFIGS:
        max_deploy = (grids // 2) * amt
        lines.append(f"| `{cfg_label}` | {lo_f}×p0 → {up_f}×p0 | {grids} | {amt} | {max_deploy} ({max_deploy/INITIAL_CASH*100:.0f}%) |")
    lines.append("")
    lines.append("## 報酬對照 (5y return%)")
    lines.append("")
    lines.append("| Config | BTC | ETH | XRP | BNB | PAXG | 平均 |")
    lines.append("|---|---:|---:|---:|---:|---:|---:|")
    by_cfg = {cfg: {} for cfg, _, _, _, _ in CONFIGS}
    for r in rows:
        by_cfg[r["config"]][r["asset"]] = float(r["return_percent"])
    for cfg, _, _, _, _ in CONFIGS:
        d = by_cfg[cfg]
        cells = " | ".join(f"{d.get(a, 0):+.2f}%" for a in [a["display"] for a in ASSETS])
        avg = sum(d.values()) / len(d) if d else 0
        lines.append(f"| `{cfg}` | {cells} | {avg:+.2f}% |")
    lines.append("")
    lines.append("## 交易次數對照")
    lines.append("")
    lines.append("| Config | BTC | ETH | XRP | BNB | PAXG | 總計 |")
    lines.append("|---|---:|---:|---:|---:|---:|---:|")
    for cfg, _, _, _, _ in CONFIGS:
        tcs = {r["asset"]: r["trade_count"] for r in rows if r["config"] == cfg}
        cells = " | ".join(str(tcs.get(a, 0)) for a in [a["display"] for a in ASSETS])
        total = sum(tcs.values())
        lines.append(f"| `{cfg}` | {cells} | {total} |")
    lines.append("")
    docs.write_text("\n".join(lines))
    print(f"[done] wrote {docs}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
