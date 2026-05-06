#!/usr/bin/env python3
"""Standalone evaluation of `triple_trend_recovery_claude_rev`.

Same methodology as the competition (5 assets × 1h × 5y, fee 0.3%,
slippage 0.1%, stress test 7 scenarios, regime breakdown, walk-forward
3 phases) but for ONE template only — no mutation of competition CSVs.

Output: docs/COMPETITION/REV_STANDALONE_REPORT.md
"""
from __future__ import annotations

import csv
import json
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "security"))

from competition_stage2_matrix import (
    build_runtime, load_candles, load_template_workflow, run_one,
    ASSETS, INITIAL_CASH,
)
from competition_stage3_regime import slice_metrics, parse_iso_to_ts, regime_window_ts
from competition_stage5_stress import SCENARIOS

CONFIG = json.loads((REPO_ROOT / "security" / "competition_config.json").read_text())
TEMPLATE = "triple_trend_recovery_claude_rev"
TEMPLATE_LABEL = "趨勢三重接力（Claude rev）"
OUT_DIR = REPO_ROOT / "public" / "data" / "competition"
DOCS_DIR = REPO_ROOT / "docs" / "COMPETITION"


def main_matrix(trading):
    """5 backtests on full 5y."""
    runs = []
    equity_curves = {}
    for asset in ASSETS:
        candles = load_candles(asset["display"])
        t0 = time.perf_counter()
        metrics, trades, equity = run_one(
            trading, template_name=TEMPLATE, asset=asset, candles=candles
        )
        elapsed = time.perf_counter() - t0
        print(f"  {asset['display']:<5}  ret={metrics['return_percent']:>+8.2f}% "
              f"trades={metrics['trade_count']:>2}  DD={metrics['max_drawdown_percent']:>5.2f}%  "
              f"PF={metrics['profit_factor']:>7.2f}  Sharpe={metrics['sharpe']:>+5.2f}  "
              f"{elapsed:>4.1f}s",
              file=sys.stderr)
        runs.append((asset["display"], metrics, trades))
        equity_curves[asset["display"]] = (equity, trades, candles)
    return runs, equity_curves


def stress_test(trading):
    actor = {"id": 1, "username": "alice", "role": "user"}
    wf = load_template_workflow(TEMPLATE)
    out = []
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
        print(f"  {scen_name:<28}  ret={ret:>+7.2f}%  trades={tc}  DD={dd:>5.2f}%", file=sys.stderr)
        out.append((scen_name, ret, tc, dd, err))
    return out


def slice_to_metrics_local(equity_rows_dicts, trade_rows, *, ts_start, ts_end):
    sliced = [r for r in equity_rows_dicts if ts_start <= r["ts"] <= ts_end]
    if len(sliced) < 2:
        return None
    eq_start = sliced[0]["equity"]
    eq_end = sliced[-1]["equity"]
    return_pct = (eq_end - eq_start) / eq_start * 100 if eq_start > 0 else 0
    peak = sliced[0]["equity"]; max_dd = 0
    for r in sliced:
        if r["equity"] > peak:
            peak = r["equity"]
        if peak > 0:
            dd = (peak - r["equity"]) / peak * 100
            if dd > max_dd:
                max_dd = dd
    trades_in = [t for t in trade_rows if int(t.get("time") or 0) >= ts_start and int(t.get("time") or 0) <= ts_end]
    return {"return_percent": return_pct, "max_dd_percent": max_dd,
            "trade_count": len(trades_in), "candle_count": len(sliced),
            "first_iso": sliced[0]["iso"], "last_iso": sliced[-1]["iso"]}


def equity_to_dicts(equity_curve):
    """Convert engine's equity_curve list to ts/iso/equity dicts."""
    out = []
    for p in equity_curve:
        ts = int(p.get("time") or 0)
        iso = datetime.utcfromtimestamp(ts).isoformat() + "+00:00" if ts else ""
        out.append({
            "ts": ts, "iso": iso,
            "equity": float(p.get("equity_points") or 0),
            "price": float(p.get("price_points") or 0),
        })
    return out


def regime_breakdown(equity_curves):
    out = []
    for asset, (equity, trades, _) in equity_curves.items():
        eq_dicts = equity_to_dicts(equity)
        for regime_key, regime_def in CONFIG["regimes"].items():
            ts_start, ts_end = regime_window_ts(regime_def)
            m = slice_to_metrics_local(eq_dicts, trades, ts_start=ts_start, ts_end=ts_end)
            if m is None:
                out.append((regime_key, asset, None, None, 0, "insufficient_data"))
            else:
                out.append((regime_key, asset, m["return_percent"], m["max_dd_percent"],
                            m["trade_count"], "ok"))
    return out


def walk_forward(equity_curves):
    out = []
    for asset, (equity, trades, _) in equity_curves.items():
        eq_dicts = equity_to_dicts(equity)
        for phase_key, phase_def in CONFIG["walk_forward"].items():
            ts_start = parse_iso_to_ts(phase_def["start"] + "T00:00:00+00:00")
            ts_end = parse_iso_to_ts(phase_def["end"] + "T23:59:59+00:00")
            m = slice_to_metrics_local(eq_dicts, trades, ts_start=ts_start, ts_end=ts_end)
            if m is None:
                out.append((phase_key, asset, None, None, 0, "insufficient_data"))
            else:
                out.append((phase_key, asset, m["return_percent"], m["max_dd_percent"],
                            m["trade_count"], "ok"))
    return out


def verdict_check(runs, walk_forward_rows):
    """Apply the same verdict rules used in Stage 8."""
    rets = [m["return_percent"] for _, m, _ in runs]
    dds = [m["max_drawdown_percent"] for _, m, _ in runs]
    pfs = [m["profit_factor"] for _, m, _ in runs]
    tcs = [m["trade_count"] for _, m, _ in runs]
    avg_ret = sum(rets) / len(rets)
    max_dd = max(dds)
    avg_pf = sum(pfs) / len(pfs)
    avg_trades = sum(tcs) / len(tcs)
    forward_rets = [r[2] for r in walk_forward_rows if r[0] == "forward" and r[5] == "ok"]
    avg_forward = sum(forward_rets) / len(forward_rets) if forward_rets else 0
    btc_ret = next((m["return_percent"] for a, m, _ in runs if a == "BTC"), 0)
    non_btc_neg = sum(1 for a, m, _ in runs if a != "BTC" and m["return_percent"] < 0)

    fails, warnings = [], []
    if avg_trades < 5:
        fails.append(f"trade_count<5 (avg {avg_trades:.1f})")
    if max_dd > 25:
        fails.append(f"max_DD>25% ({max_dd:.1f}%)")
    if avg_pf < 1.1 and avg_pf > 0:
        fails.append(f"PF<1.1 ({avg_pf:.2f})")
    if avg_ret < 0:
        fails.append(f"fee-adjusted return negative ({avg_ret:.2f}%)")
    if avg_forward < 0:
        fails.append(f"walk-forward forward negative ({avg_forward:.2f}%)")
    if avg_trades < 10:
        warnings.append(f"trade_count<10 (avg {avg_trades:.1f})")
    if btc_ret > 0 and non_btc_neg >= 3:
        warnings.append("only-BTC profitable")

    verdict = "FAIL" if fails else ("WARNING" if warnings else "PASS")
    return verdict, fails, warnings, {
        "avg_ret": avg_ret, "max_dd": max_dd, "avg_pf": avg_pf,
        "avg_trades": avg_trades, "avg_forward": avg_forward,
    }


def main() -> int:
    trading = build_runtime()
    print(f"=== Standalone evaluation of {TEMPLATE} ===", file=sys.stderr)
    print(f"\n[1/3] Main matrix (5 assets × 1h × 5y, fee 0.3%, slip 0.1%)", file=sys.stderr)
    runs, equity_curves = main_matrix(trading)

    print(f"\n[2/3] Regime breakdown (5 regimes × 5 assets)", file=sys.stderr)
    regime_rows = regime_breakdown(equity_curves)

    print(f"\n[3/3] Walk-forward (3 phases × 5 assets)", file=sys.stderr)
    walk_rows = walk_forward(equity_curves)

    print(f"\n[4/3] Stress test (7 scenarios)", file=sys.stderr)
    stress_rows = stress_test(trading)

    verdict, fails, warns, agg = verdict_check(runs, walk_rows)

    # Build report.
    lines = []
    lines.append(f"# Standalone Evaluation: `{TEMPLATE}`")
    lines.append("")
    lines.append(f"Generated: {datetime.now().isoformat(timespec='seconds')}")
    lines.append("")
    lines.append(f"**模板標籤**: {TEMPLATE_LABEL}")
    lines.append(f"**設計依據**: 競賽 22 模板全 FAIL 的教訓 — 提高 trade_count、移除固定%止盈、首倉 90%、加碼 50%、step=100、MA50 主動出場、18% 寬鬆止損")
    lines.append("")
    lines.append(f"## Verdict: **{verdict}**")
    lines.append("")
    if fails:
        lines.append(f"❌ **FAIL reasons**: {'; '.join(fails)}")
        lines.append("")
    if warns:
        lines.append(f"⚠️ **WARNING reasons**: {'; '.join(warns)}")
        lines.append("")
    lines.append(f"- 平均報酬: {agg['avg_ret']:+.2f}%")
    lines.append(f"- 最大回撤: {agg['max_dd']:.2f}%")
    lines.append(f"- 平均 PF: {agg['avg_pf']:.2f}")
    lines.append(f"- 平均交易次數: {agg['avg_trades']:.1f}")
    lines.append(f"- Walk-forward forward 平均: {agg['avg_forward']:+.2f}%")
    lines.append("")

    lines.append("## 1. 主矩陣（5 資產 × 1h × 5y）")
    lines.append("")
    lines.append("| Asset | Ret% | Trades | Max DD% | PF | Sharpe | Sortino | Win% | Exposure% |")
    lines.append("|---|---:|---:|---:|---:|---:|---:|---:|---:|")
    for asset, m, _ in runs:
        lines.append(
            f"| {asset} | {m['return_percent']:+.2f} | {m['trade_count']} | "
            f"{m['max_drawdown_percent']:.2f} | {m['profit_factor']:.2f} | "
            f"{m['sharpe']:+.3f} | {m['sortino']:+.3f} | "
            f"{m['win_rate_percent']:.1f} | {m['exposure']*100:.2f} |"
        )
    lines.append("")

    lines.append("## 2. Regime Breakdown")
    lines.append("")
    lines.append("| Regime | Asset | Ret% | DD% | Trades | Note |")
    lines.append("|---|---|---:|---:|---:|---|")
    for regime, asset, ret, dd, tc, note in regime_rows:
        if note == "ok":
            lines.append(f"| {regime} | {asset} | {ret:+.2f} | {dd:.2f} | {tc} | ok |")
        else:
            lines.append(f"| {regime} | {asset} | - | - | - | {note} |")
    lines.append("")

    lines.append("## 3. Walk-Forward")
    lines.append("")
    lines.append("| Phase | Asset | Ret% | DD% | Trades | Note |")
    lines.append("|---|---|---:|---:|---:|---|")
    for phase, asset, ret, dd, tc, note in walk_rows:
        if note == "ok":
            lines.append(f"| {phase} | {asset} | {ret:+.2f} | {dd:.2f} | {tc} | ok |")
        else:
            lines.append(f"| {phase} | {asset} | - | - | - | {note} |")
    lines.append("")

    lines.append("## 4. Stress Test 7 場景")
    lines.append("")
    lines.append("| Scenario | Ret% | Trades | DD% | Error |")
    lines.append("|---|---:|---:|---:|---|")
    for scen, ret, tc, dd, err in stress_rows:
        lines.append(f"| {scen} | {ret:+.2f} | {tc} | {dd:.2f} | {err or '-'} |")
    lines.append("")

    lines.append("## 5. 對比既有 5 個 Claude 模板（5y 平均）")
    lines.append("")
    raw = list(csv.DictReader(open(OUT_DIR / "raw_results.csv")))
    claude_orig = CONFIG["competition_templates"]["claude_5"]
    per_t = defaultdict(list)
    for r in raw:
        if r["template"] in claude_orig:
            per_t[r["template"]].append(float(r["return_percent"]))
    lines.append("| Template | 5y avg Ret% | 平均交易次數 | 來源 |")
    lines.append("|---|---:|---:|---|")
    rows_for_table = []
    for tn in claude_orig:
        rets = per_t[tn]
        tc_rows = [int(r["trade_count"]) for r in raw if r["template"] == tn]
        rows_for_table.append((tn, sum(rets)/len(rets), sum(tc_rows)/len(tc_rows), "claude (v1)"))
    rows_for_table.append((TEMPLATE, agg["avg_ret"], agg["avg_trades"], "**claude rev**"))
    rows_for_table.sort(key=lambda x: x[1], reverse=True)
    for tn, avg, tc, src in rows_for_table:
        lines.append(f"| `{tn}` | {avg:+.2f}% | {tc:.1f} | {src} |")
    lines.append("")

    out_path = DOCS_DIR / "REV_STANDALONE_REPORT.md"
    out_path.write_text("\n".join(lines))
    print(f"\n[done] wrote {out_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
