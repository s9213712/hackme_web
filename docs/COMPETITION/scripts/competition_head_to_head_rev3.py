#!/usr/bin/env python3
"""Head-to-head: Claude rev3 winner vs Codex contender.

Runs both workflows on the SAME 5 assets × 5y × 1h candles with the
SAME engine config (fee 0.3%, slippage 0.1% post-hoc) and prints a
side-by-side comparison table.
"""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "docs" / "COMPETITION" / "scripts"))

from competition_stage2_matrix import build_runtime, load_candles, ASSETS, INITIAL_CASH

CONTENDERS = [
    ("claude_rev3", "auto_search_winner_claude_rev3_return"),
    ("codex_late_tp15", "dipbuy_rsi35_70_size99_late_tp15_nopyr_codex"),
]
B_AND_H = {"BTC": 46.24, "ETH": -30.52, "XRP": -7.43, "BNB": 3.71, "PAXG": 153.80}
OUT_DIR = REPO_ROOT / "docs" / "COMPETITION" / "data"


def main() -> int:
    trading = build_runtime()
    actor = {"id": 1, "username": "alice", "role": "user"}

    results = {}
    for label, template_name in CONTENDERS:
        wf = json.loads((REPO_ROOT / "workflows" / "trading_bot" / f"{template_name}.json").read_text())["workflow"]
        per_asset = []
        for asset in ASSETS:
            candles = load_candles(asset["display"])
            try:
                res = trading.backtest_trading_bot(actor=actor, payload={
                    "market_symbol": asset["market_symbol"],
                    "strategy": "workflow",
                    "workflow_json": wf,
                    "initial_cash_points": INITIAL_CASH,
                    "candles": candles,
                })
                per_asset.append({
                    "asset": asset["display"],
                    "return_percent": float(res.get("return_percent") or 0),
                    "max_drawdown_percent": float(res.get("max_drawdown_percent") or 0),
                    "trade_count": int(res.get("trade_count") or 0),
                })
            except Exception as exc:
                per_asset.append({"asset": asset["display"], "error": str(exc)[:80]})
        rets = [a.get("return_percent", 0) for a in per_asset]
        dds = [a.get("max_drawdown_percent", 0) for a in per_asset]
        tcs = [a.get("trade_count", 0) for a in per_asset]
        results[label] = {
            "template_name": template_name,
            "per_asset": per_asset,
            "avg_ret": sum(rets) / len(rets),
            "max_dd": max(dds) if dds else 0,
            "avg_trades": sum(tcs) / len(tcs),
        }

    # Print head-to-head
    print()
    print(f"{'asset':<6} {'B&H':>9} {'Claude rev3':>13} {'Codex contender':>17} {'winner':>10}")
    print("-" * 70)
    asset_winners = {"claude_rev3": 0, "codex_late_tp15": 0, "tied": 0}
    for asset in ASSETS:
        a = asset["display"]
        bh = B_AND_H.get(a, 0)
        c_row = next((r for r in results["claude_rev3"]["per_asset"] if r.get("asset") == a), {})
        x_row = next((r for r in results["codex_late_tp15"]["per_asset"] if r.get("asset") == a), {})
        c_ret = c_row.get("return_percent", 0)
        x_ret = x_row.get("return_percent", 0)
        if abs(c_ret - x_ret) < 0.01:
            winner = "tie"
            asset_winners["tied"] += 1
        elif c_ret > x_ret:
            winner = "Claude"
            asset_winners["claude_rev3"] += 1
        else:
            winner = "Codex"
            asset_winners["codex_late_tp15"] += 1
        print(f"{a:<6} {bh:>+8.2f}% {c_ret:>+12.2f}% {x_ret:>+16.2f}%  {winner:>10}")
    print()

    c = results["claude_rev3"]
    x = results["codex_late_tp15"]
    print(f"{'metric':<25} {'Claude rev3':>15} {'Codex':>15} {'diff':>10}")
    print("-" * 70)
    print(f"{'avg return %':<25} {c['avg_ret']:>+14.2f}% {x['avg_ret']:>+14.2f}% {c['avg_ret']-x['avg_ret']:>+9.2f}pp")
    print(f"{'max DD %':<25} {c['max_dd']:>14.2f}% {x['max_dd']:>14.2f}% {c['max_dd']-x['max_dd']:>+9.2f}pp")
    print(f"{'avg trades':<25} {c['avg_trades']:>15.1f} {x['avg_trades']:>15.1f} {c['avg_trades']-x['avg_trades']:>+9.1f}")

    bh_avg = sum(B_AND_H.values()) / len(B_AND_H)
    print()
    print(f"vs B&H avg +{bh_avg:.2f}%:")
    print(f"  Claude rev3:    {c['avg_ret']-bh_avg:+.2f}pp")
    print(f"  Codex contender: {x['avg_ret']-bh_avg:+.2f}pp")
    print()
    print(f"Per-asset wins: Claude {asset_winners['claude_rev3']} / Codex {asset_winners['codex_late_tp15']} / Tied {asset_winners['tied']}")
    print()
    if c['avg_ret'] > x['avg_ret']:
        diff = c['avg_ret'] - x['avg_ret']
        print(f"🏆 OVERALL WINNER: Claude rev3 by {diff:+.2f}pp avg return")
    elif x['avg_ret'] > c['avg_ret']:
        diff = x['avg_ret'] - c['avg_ret']
        print(f"🏆 OVERALL WINNER: Codex contender by {diff:+.2f}pp avg return")
    else:
        print(f"🤝 TIE on avg return")

    out_path = OUT_DIR / "head_to_head_rev3.json"
    out_path.write_text(json.dumps({
        "results": results, "asset_wins": asset_winners,
    }, indent=2, ensure_ascii=False))
    print(f"\n[done] wrote {out_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
