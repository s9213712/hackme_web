#!/usr/bin/env python3
"""Grid spacing mode (arithmetic vs geometric) comparison.

Same 5 configs × 5 assets × 5y as the sky-floor test, but each run
duplicated for both spacing modes. Goal: verify whether the auto-switch
to geometric for wide ranges is justified by the data.

Output:
  docs/COMPETITION/data/grid_spacing_comparison.csv
  docs/COMPETITION/GRID_SPACING_COMPARISON.md
"""
from __future__ import annotations

import csv
import json
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "docs" / "COMPETITION" / "scripts"))

from competition_stage2_matrix import build_runtime, load_candles, ASSETS, INITIAL_CASH

CONFIGS = [
    ("conservative",    0.80, 1.20, 10, 5000),
    ("balanced",        0.50, 1.50, 20, 5000),
    ("skyfloor_narrow", 0.20, 1.80, 50, 2000),
    ("skyfloor_mid",    0.10, 3.00, 50, 2000),
    ("skyfloor_wide",   0.10, 3.00, 100, 1000),
    ("skyfloor_5x",     0.05, 5.00, 100, 1000),
]
SPACING_MODES = ["arithmetic", "geometric"]


def main() -> int:
    trading = build_runtime()
    actor = {"id": 1, "username": "alice", "role": "user"}
    rows = []
    print(f"{'config':<18} {'asset':<5} {'mode':<10} {'ret%':>8} {'trades':>5}", file=sys.stderr)
    print("-" * 50, file=sys.stderr)
    for cfg_label, lo_f, up_f, grids, amt in CONFIGS:
        for asset in ASSETS:
            candles = load_candles(asset["display"])
            p0 = float(candles[0]["close_points"])
            lower = p0 * lo_f
            upper = p0 * up_f
            for mode in SPACING_MODES:
                t0 = time.perf_counter()
                try:
                    res = trading.backtest_trading_bot(actor=actor, payload={
                        "market_symbol": asset["market_symbol"], "strategy": "grid",
                        "lower_price_points": lower, "upper_price_points": upper,
                        "grid_count": grids, "order_amount_points": amt,
                        "spacing_mode": mode,
                        "candles": candles,
                    })
                    ret = float(res.get("return_percent") or 0)
                    tc = int(res.get("trade_count") or 0)
                    err = ""
                except Exception as exc:
                    ret, tc = 0.0, 0
                    err = str(exc)[:80]
                elapsed = time.perf_counter() - t0
                print(f"{cfg_label:<18} {asset['display']:<5} {mode:<10} {ret:>+7.2f} {tc:>5} {elapsed:>4.1f}s",
                      file=sys.stderr)
                rows.append({
                    "config": cfg_label, "asset": asset["display"], "spacing_mode": mode,
                    "lower": round(lower, 2), "upper": round(upper, 2),
                    "grids": grids, "order_amount": amt,
                    "return_percent": round(ret, 4), "trade_count": tc,
                    "wall_seconds": round(elapsed, 2), "error": err,
                })

    out_csv = REPO_ROOT / "docs" / "COMPETITION" / "data" / "grid_spacing_comparison.csv"
    keys = ["config", "asset", "spacing_mode", "lower", "upper", "grids", "order_amount",
            "return_percent", "trade_count", "wall_seconds", "error"]
    with out_csv.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=keys, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)
    print(f"\n[done] wrote {out_csv}", file=sys.stderr)

    # Markdown
    docs = REPO_ROOT / "docs" / "COMPETITION" / "GRID_SPACING_COMPARISON.md"
    lines = ["# 網格間距模式比較：等差 vs 等比", "",
             "對 6 個 grid 預設 × 5 資產 × 5y 1h candles 跑 arithmetic vs geometric 兩種間距，看哪個適合什麼配置。",
             "", "**統一條件**: fee 0.3%, initial cash 100K POINTS, ±範圍依各 config 設定。", "",
             "## 等差 vs 等比 數學差異", "",
             "- **等差 (arithmetic)**：每格絕對價差固定。`step = (upper - lower) / count`。",
             "- **等比 (geometric)**：每格百分比固定。`ratio = (upper / lower) ** (1 / (count - 1))`。",
             "", "範圍越寬，等差越會把格子擠在低價區（高價區格距變大），導致大半格子壓在底部，行情往上很快出格。等比反之，每格 % 變化均勻，整個範圍都能交易。",
             "", "## 報酬對照（5y return%）", ""]
    by_pair = {}
    for r in rows:
        key = (r["config"], r["asset"])
        by_pair.setdefault(key, {})[r["spacing_mode"]] = float(r["return_percent"])
    for cfg_label, lo_f, up_f, grids, amt in CONFIGS:
        lines.append(f"### `{cfg_label}` ({lo_f}× → {up_f}×, {grids} grids, {amt} 每格)")
        lines.append("")
        lines.append("| Asset | Arithmetic | Geometric | 差距 (geo - arith) |")
        lines.append("|---|---:|---:|---:|")
        for asset in ASSETS:
            d = by_pair.get((cfg_label, asset["display"]), {})
            a = d.get("arithmetic", 0)
            g = d.get("geometric", 0)
            diff = g - a
            sign = "✅" if diff > 0.5 else ("❌" if diff < -0.5 else "≈")
            lines.append(f"| {asset['display']} | {a:+.2f}% | {g:+.2f}% | {diff:+.2f}pp {sign} |")
        # avg per mode
        avg_a = sum(by_pair.get((cfg_label, a["display"]), {}).get("arithmetic", 0) for a in ASSETS) / len(ASSETS)
        avg_g = sum(by_pair.get((cfg_label, a["display"]), {}).get("geometric", 0) for a in ASSETS) / len(ASSETS)
        lines.append(f"| **平均** | **{avg_a:+.2f}%** | **{avg_g:+.2f}%** | **{avg_g - avg_a:+.2f}pp** |")
        lines.append("")

    lines.append("## 交易次數對照（孳息 fee 主因）")
    lines.append("")
    lines.append("| Config | Arith trades | Geo trades | Geo - Arith |")
    lines.append("|---|---:|---:|---:|")
    for cfg_label, _, _, _, _ in CONFIGS:
        a_total = sum(r["trade_count"] for r in rows if r["config"] == cfg_label and r["spacing_mode"] == "arithmetic")
        g_total = sum(r["trade_count"] for r in rows if r["config"] == cfg_label and r["spacing_mode"] == "geometric")
        lines.append(f"| `{cfg_label}` | {a_total} | {g_total} | {g_total - a_total:+d} |")
    lines.append("")
    docs.write_text("\n".join(lines))
    print(f"[done] wrote {docs}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
