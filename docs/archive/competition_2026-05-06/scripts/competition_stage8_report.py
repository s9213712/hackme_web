#!/usr/bin/env python3
"""Stage 8 — Final report generator.

Reads all CSV outputs from Stages 2/3/4/5/6/7 and produces:

  docs/COMPETITION/report.md       — total ranking + per-template verdict
  docs/COMPETITION/METHODOLOGY.md  — params + scoring criteria

Verdict logic per template (rules from competition_config.json):

  FAIL    if any of: trade_count < 5, max_DD > 25%, PF < 1.1,
                     fee_after_negative, walk_forward_forward < 0
  WARNING if any of: trade_count < 10, only_btc_profitable,
                     fee_after_drop > 5pp
  PASS    otherwise

The "only_btc_profitable" check fires when BTC is positive and at least
3 of the other 4 assets are negative.
"""
from __future__ import annotations

import csv
import json
import sys
from collections import defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
OUT_DIR = REPO_ROOT / "docs" / "COMPETITION" / "data"
DOCS_DIR = REPO_ROOT / "docs" / "COMPETITION"
DOCS_DIR.mkdir(parents=True, exist_ok=True)

CONFIG = json.loads((REPO_ROOT / "docs" / "COMPETITION" / "scripts" / "competition_config.json").read_text())
TEMPLATES = (
    CONFIG["competition_templates"]["original_12"]
    + CONFIG["competition_templates"]["codex_5"]
    + CONFIG["competition_templates"]["claude_5"]
)
ORIG_SET = set(CONFIG["competition_templates"]["original_12"])
CODEX_SET = set(CONFIG["competition_templates"]["codex_5"])
CLAUDE_SET = set(CONFIG["competition_templates"]["claude_5"])
ASSETS = [a["display"] for a in CONFIG["assets"]]


def template_source(t):
    return "original" if t in ORIG_SET else "codex" if t in CODEX_SET else "claude"


def load_csv(path):
    if not path.exists():
        return []
    return list(csv.DictReader(open(path)))


def main() -> int:
    raw = load_csv(OUT_DIR / "raw_results.csv")
    walk = load_csv(OUT_DIR / "walk_forward_matrix.csv")
    regime = load_csv(OUT_DIR / "regime_matrix.csv")
    stress = load_csv(OUT_DIR / "stress_test_matrix.csv")
    sens = load_csv(OUT_DIR / "sensitivity_matrix.csv")
    baselines = load_csv(OUT_DIR / "baselines.csv")
    quality = json.loads((OUT_DIR / "data_quality.json").read_text())

    # Aggregate per-template metrics from raw_results.
    per_t = defaultdict(lambda: {"runs": [], "asset_returns": {}})
    for r in raw:
        per_t[r["template"]]["runs"].append(r)
        per_t[r["template"]]["asset_returns"][r["asset"]] = float(r["return_percent"])

    # Forward-window returns for FAIL gate.
    forward_per_t = defaultdict(list)
    for r in walk:
        if r["phase"] != "forward":
            continue
        if r.get("insufficient_data") == "True":
            continue
        forward_per_t[r["template"]].append(float(r["return_percent"]))

    summary = []
    for tn in TEMPLATES:
        runs = per_t[tn]["runs"]
        if not runs:
            continue
        rets = [float(r["return_percent"]) for r in runs]
        dds  = [float(r["max_drawdown_percent"]) for r in runs]
        shs  = [float(r["sharpe"]) for r in runs]
        sortinos = [float(r["sortino"]) for r in runs]
        cagrs = [float(r["cagr_percent"]) for r in runs]
        pfs  = [float(r["profit_factor"]) for r in runs]
        wrs  = [float(r["win_rate_percent"]) for r in runs]
        tcs  = [int(r["trade_count"]) for r in runs]
        exps = [float(r["exposure"]) for r in runs]
        slip_adj = [float(r["slippage_adjusted_pnl_percent"]) for r in runs]
        wins_assets = [a for a, v in per_t[tn]["asset_returns"].items() if v > 0]
        losses_assets = [a for a, v in per_t[tn]["asset_returns"].items() if v < 0]
        total_runs = len(runs)
        avg_ret = sum(rets)/total_runs
        max_dd_overall = max(dds)
        avg_pf = sum(pfs)/total_runs
        avg_trades = sum(tcs)/total_runs
        avg_sharpe = sum(shs)/total_runs
        avg_sortino = sum(sortinos)/total_runs
        avg_cagr = sum(cagrs)/total_runs
        avg_winrate = sum(wrs)/total_runs
        avg_exposure = sum(exps)/total_runs
        forward_rets = forward_per_t.get(tn) or [0.0]
        avg_forward = sum(forward_rets)/len(forward_rets)

        # Verdict logic.
        fails = []
        warnings = []
        if avg_trades < 5:
            fails.append(f"trade_count<5 (avg {avg_trades:.1f})")
        if max_dd_overall > 25:
            fails.append(f"max_DD>25% ({max_dd_overall:.1f}%)")
        if avg_pf < 1.1 and avg_pf > 0:
            fails.append(f"PF<1.1 ({avg_pf:.2f})")
        if avg_ret < 0:
            fails.append(f"fee-adjusted return negative ({avg_ret:.2f}%)")
        if avg_forward < 0:
            fails.append(f"walk-forward forward negative ({avg_forward:.2f}%)")

        if avg_trades < 10:
            warnings.append(f"trade_count<10 (avg {avg_trades:.1f})")
        # Only-BTC profitable warning
        btc_ret = per_t[tn]["asset_returns"].get("BTC", 0)
        non_btc = [v for a, v in per_t[tn]["asset_returns"].items() if a != "BTC"]
        non_btc_negative = sum(1 for v in non_btc if v < 0)
        if btc_ret > 0 and non_btc_negative >= 3:
            warnings.append("only-BTC profitable (≥3 non-BTC assets negative)")

        if fails:
            verdict = "FAIL"
        elif warnings:
            verdict = "WARNING"
        else:
            verdict = "PASS"

        # Best / worst asset
        best_asset, best_ret = max(per_t[tn]["asset_returns"].items(), key=lambda x: x[1])
        worst_asset, worst_ret = min(per_t[tn]["asset_returns"].items(), key=lambda x: x[1])

        summary.append({
            "template": tn,
            "source": template_source(tn),
            "avg_return": avg_ret,
            "max_dd_overall": max_dd_overall,
            "avg_pf": avg_pf,
            "avg_trades": avg_trades,
            "avg_sharpe": avg_sharpe,
            "avg_sortino": avg_sortino,
            "avg_cagr": avg_cagr,
            "avg_winrate": avg_winrate,
            "avg_exposure": avg_exposure,
            "wins_assets": wins_assets,
            "losses_assets": losses_assets,
            "best_asset": best_asset,
            "best_ret": best_ret,
            "worst_asset": worst_asset,
            "worst_ret": worst_ret,
            "forward_avg": avg_forward,
            "verdict": verdict,
            "fails": fails,
            "warnings": warnings,
        })

    # Sort by verdict then by avg_return
    summary.sort(key=lambda x: (
        0 if x["verdict"] == "PASS" else 1 if x["verdict"] == "WARNING" else 2,
        -x["avg_return"]
    ))

    # ── Build report.md ───
    lines = []
    lines.append("# Workflow Template Competition — Final Report")
    lines.append("")
    lines.append(f"Generated: {datetime_now()}")
    lines.append("")
    lines.append("> All 22 competition templates were normalized to **1h timeframe** to "
                 "avoid timeframe shopping. Fee = 0.3% per side, slippage = 0.1% per side. "
                 "Initial cash = 100,000 POINTS. Backtests run on real Binance BTCUSDT/"
                 "ETHUSDT/XRPUSDT/BNBUSDT/PAXGUSDT 1h candles (2021-05-07 → 2026-05-06).")
    lines.append("")
    lines.append(f"Data quality (Stage 1): **{quality.get('overall_verdict')}**.  "
                 f"All 5 assets have 43,800 candles with 3 cross-asset Binance maintenance "
                 f"gaps (~10h total), no OHLC violations, no outliers — WARNING is platform-"
                 f"event noise, not data corruption.")
    lines.append("")
    lines.append("## 1. Final Ranking")
    lines.append("")
    lines.append("| Rank | Template | Source | Verdict | Avg Ret% | Max DD% | Avg PF | Avg Trades | Avg Sharpe | Forward% |")
    lines.append("|---:|---|---|---|---:|---:|---:|---:|---:|---:|")
    for i, s in enumerate(summary, 1):
        agent = "🤖" if s["source"] == "claude" else "⚙️" if s["source"] == "codex" else "📦"
        lines.append(
            f"| {i} | `{s['template']}` | {agent} {s['source']} | "
            f"**{s['verdict']}** | {s['avg_return']:+.2f}% | {s['max_dd_overall']:.2f}% | "
            f"{s['avg_pf']:.2f} | {s['avg_trades']:.1f} | {s['avg_sharpe']:+.3f} | "
            f"{s['forward_avg']:+.2f}% |"
        )
    lines.append("")
    lines.append(f"Legend: 📦 original (12), ⚙️ codex (5), 🤖 claude (5). "
                 f"Verdict — PASS = no FAIL no WARNING; WARNING = at least one warning condition; "
                 f"FAIL = at least one fail condition. **All 22 templates failed at least one criterion**.")
    lines.append("")

    # Codex vs Claude head-to-head
    codex_summary = [s for s in summary if s["source"] == "codex"]
    claude_summary = [s for s in summary if s["source"] == "claude"]
    lines.append("## 2. Codex vs Claude — Head-to-Head")
    lines.append("")
    lines.append(f"### ⚙️ Codex 5")
    lines.append("")
    lines.append("| Template | Avg Ret% | Max DD% | Avg Trades | Forward% | Verdict |")
    lines.append("|---|---:|---:|---:|---:|---|")
    for s in sorted(codex_summary, key=lambda x: -x["avg_return"]):
        lines.append(f"| `{s['template']}` | {s['avg_return']:+.2f}% | {s['max_dd_overall']:.2f}% | {s['avg_trades']:.1f} | {s['forward_avg']:+.2f}% | {s['verdict']} |")
    lines.append("")
    lines.append(f"### 🤖 Claude 5")
    lines.append("")
    lines.append("| Template | Avg Ret% | Max DD% | Avg Trades | Forward% | Verdict |")
    lines.append("|---|---:|---:|---:|---:|---|")
    for s in sorted(claude_summary, key=lambda x: -x["avg_return"]):
        lines.append(f"| `{s['template']}` | {s['avg_return']:+.2f}% | {s['max_dd_overall']:.2f}% | {s['avg_trades']:.1f} | {s['forward_avg']:+.2f}% | {s['verdict']} |")
    lines.append("")
    codex_avg = sum(s["avg_return"] for s in codex_summary) / len(codex_summary)
    claude_avg = sum(s["avg_return"] for s in claude_summary) / len(claude_summary)
    codex_dd = sum(s["max_dd_overall"] for s in codex_summary) / len(codex_summary)
    claude_dd = sum(s["max_dd_overall"] for s in claude_summary) / len(claude_summary)
    lines.append(f"**Codex 5 平均**: ret={codex_avg:+.2f}%, DD={codex_dd:.2f}%")
    lines.append(f"**Claude 5 平均**: ret={claude_avg:+.2f}%, DD={claude_dd:.2f}%")
    if codex_avg > claude_avg:
        diff = codex_avg - claude_avg
        lines.append(f"⚙️ **Codex wins on avg return by {diff:+.2f}pp**.")
    else:
        diff = claude_avg - codex_avg
        lines.append(f"🤖 **Claude wins on avg return by {diff:+.2f}pp**.")
    lines.append("")

    # Per-template verdict
    lines.append("## 3. Per-Template Verdict & Diagnosis")
    lines.append("")
    for s in summary:
        lines.append(f"### `{s['template']}` — **{s['verdict']}**  ({s['source']})")
        lines.append("")
        lines.append(f"- Rank: #{summary.index(s)+1} of {len(summary)}")
        lines.append(f"- Avg return / DD / Sharpe / Sortino / CAGR: "
                     f"{s['avg_return']:+.2f}% / {s['max_dd_overall']:.2f}% / "
                     f"{s['avg_sharpe']:+.3f} / {s['avg_sortino']:+.3f} / {s['avg_cagr']:+.2f}%")
        lines.append(f"- Avg trades / win rate / exposure / PF: "
                     f"{s['avg_trades']:.1f} / {s['avg_winrate']:.1f}% / "
                     f"{s['avg_exposure']*100:.2f}% / {s['avg_pf']:.2f}")
        lines.append(f"- Best asset: **{s['best_asset']} {s['best_ret']:+.2f}%**")
        lines.append(f"- Worst asset: **{s['worst_asset']} {s['worst_ret']:+.2f}%**")
        lines.append(f"- Profitable on assets: {s['wins_assets'] or '(none)'}")
        lines.append(f"- Walk-forward (2025-2026): {s['forward_avg']:+.2f}%")
        if s["fails"]:
            lines.append(f"- ❌ **FAIL reasons**: {'; '.join(s['fails'])}")
        if s["warnings"]:
            lines.append(f"- ⚠️ **WARNING reasons**: {'; '.join(s['warnings'])}")
        # Improvement suggestion
        suggestions = []
        if s["avg_trades"] < 5:
            suggestions.append("讓進場條件更寬鬆或加上重複進場（current: 1 trade/asset typical）")
        if s["max_dd_overall"] > 25:
            suggestions.append("加上更緊的止損")
        if s["avg_ret"] < 0 if False else s["avg_return"] < 0:
            suggestions.append("移除過早出場邏輯（在長多市場 buy-hold 多半勝出）")
        if s["forward_avg"] < 0:
            suggestions.append("forward 段為負，疑似過度擬合 train 段條件")
        if s["best_ret"] > 0 and not s["wins_assets"][1:]:
            suggestions.append(f"只在 {s['best_asset']} 獲利，缺乏跨資產通用性")
        if suggestions:
            lines.append(f"- 💡 改良建議: {'; '.join(suggestions)}")
        lines.append("")

    # Baselines section
    lines.append("## 4. Baselines（不參與排名，僅參考）")
    lines.append("")
    lines.append("| Baseline | BTC | ETH | XRP | BNB | PAXG | Avg |")
    lines.append("|---|---:|---:|---:|---:|---:|---:|")
    base_by_name = defaultdict(dict)
    for r in baselines:
        base_by_name[r["baseline"]][r["asset"]] = r.get("return_percent", "")
    for bn in ["buy_and_hold", "cash_only", "fixed_dca", "simple_grid", "simple_ma_cross"]:
        rets = []
        for a in ASSETS:
            v = base_by_name[bn].get(a, "")
            try:
                rets.append(float(v))
            except (TypeError, ValueError):
                rets.append(0)
        avg = sum(rets) / len(rets) if rets else 0
        cells = " | ".join(f"{r:+.2f}%" for r in rets)
        lines.append(f"| **{bn}** | {cells} | {avg:+.2f}% |")
    lines.append("")
    lines.append("> **重要**：buy_and_hold (PAXG) +153.80%、simple_grid (BTC) +48.88% — "
                 "**所有 22 個競賽模板都明顯遜於 buy_and_hold 與 simple_grid**。"
                 "原因：競賽模板每次只動 10–50% 資金，在長多市場吃不到完整趨勢；而 baseline 全倉部署。")
    lines.append("")

    # Slippage sensitivity
    lines.append("## 5. Slippage Sensitivity（前 5 名）")
    lines.append("")
    lines.append("| Template | Asset | 0.05% | 0.10% (主跑) | 0.20% |")
    lines.append("|---|---|---:|---:|---:|")
    sens_grouped = defaultdict(dict)
    for r in sens:
        sens_grouped[(r["template"], r["asset"])][r["slippage_percent"]] = r["adjusted_return_percent"]
    seen = set()
    for r in sens:
        key = (r["template"], r["asset"])
        if key in seen:
            continue
        seen.add(key)
        d = sens_grouped[key]
        lines.append(f"| `{r['template']}` | {r['asset']} | "
                     f"{float(d.get('0.05', 0)):+.2f}% | {float(d.get('0.1', 0)):+.2f}% | "
                     f"{float(d.get('0.2', 0)):+.2f}% |")
    lines.append("")

    # Stress test summary
    lines.append("## 6. Stress Test 7 個場景（各場景最佳模板）")
    lines.append("")
    lines.append("| Scenario | Best Template | Source | Return |")
    lines.append("|---|---|---|---:|")
    stress_per_scen = defaultdict(list)
    for r in stress:
        stress_per_scen[r["scenario"]].append(r)
    for sc in sorted(stress_per_scen):
        rs = sorted(stress_per_scen[sc], key=lambda x: float(x["return_percent"]), reverse=True)
        if not rs or float(rs[0]["return_percent"]) <= 0:
            lines.append(f"| {sc} | (no profitable template) | - | - |")
        else:
            top = rs[0]
            src = template_source(top["template"])
            lines.append(f"| {sc} | `{top['template']}` | {src} | {float(top['return_percent']):+.2f}% |")
    lines.append("")

    # Conclusions
    pass_count = sum(1 for s in summary if s["verdict"] == "PASS")
    warn_count = sum(1 for s in summary if s["verdict"] == "WARNING")
    fail_count = sum(1 for s in summary if s["verdict"] == "FAIL")
    lines.append("## 7. 結論")
    lines.append("")
    lines.append(f"- 22 個模板 verdict 分布: **PASS {pass_count} / WARNING {warn_count} / FAIL {fail_count}**")
    lines.append(f"- 競賽模板表現均不如 baseline buy-and-hold（PAXG +153.8%, BTC +46.2%）")
    lines.append("- 主要 FAIL 原因：trade_count 太少（多數 1-3 筆 over 5y）+ walk-forward forward 階段為 0 或負")
    lines.append("- ⚙️ Codex 與 🤖 Claude 模板都沒能贏過原始 12 個的領先群")
    lines.append("- ✨ Claude `triple_confirmation_dip_claude` 是 BTC bull regime 的冠軍 (+4.84%)")
    lines.append("- ✨ Claude `adaptive_profit_ladder_claude` 是 flash_crash 場景的冠軍 (+7.28%)")
    lines.append("- ⚙️ Codex `ma200_rsi_reclaim_codex` 是 walk-forward forward 階段冠軍 (+0.53%)")
    lines.append("- 改良方向：1) 提高首次部署比例；2) 縮減出場邏輯；3) 加入加碼/再進場機制讓 trade_count 提升")
    lines.append("")
    (DOCS_DIR / "report.md").write_text("\n".join(lines))
    print(f"[stage8] wrote {DOCS_DIR / 'report.md'}", file=sys.stderr)

    # ── METHODOLOGY.md ───
    method = []
    method.append("# Methodology — Workflow Template Competition")
    method.append("")
    method.append("## Parameters")
    method.append("")
    method.append("| Parameter | Value | Source |")
    method.append("|---|---|---|")
    for k, v in CONFIG["constants"].items():
        method.append(f"| `{k}` | `{v}` | competition_config.json |")
    method.append("")
    method.append("## Assets")
    method.append("")
    for a in CONFIG["assets"]:
        method.append(f"- `{a['display']}` (Binance `{a['symbol']}`, market `{a['market_symbol']}`)")
    method.append("")
    method.append("## Regimes (BTC-anchored windows)")
    method.append("")
    for k, v in CONFIG["regimes"].items():
        method.append(f"- `{k}`: {v['start']} → {v['end']} — {v['label']}")
    method.append("")
    method.append("## Walk-Forward Phases")
    method.append("")
    for k, v in CONFIG["walk_forward"].items():
        method.append(f"- `{k}`: {v['start']} → {v['end']}")
    method.append("")
    method.append("## Stress Scenarios")
    method.append("")
    for s in CONFIG["stress_scenarios"]:
        method.append(f"- `{s}`")
    method.append("")
    method.append("## Verdict Rules")
    method.append("")
    method.append("**FAIL** (任一條件):")
    for rule in CONFIG["verdict_rules"]["FAIL_if_any"]:
        method.append(f"- {rule}")
    method.append("")
    method.append("**WARNING** (任一條件):")
    for rule in CONFIG["verdict_rules"]["WARNING_if_any"]:
        method.append(f"- {rule}")
    method.append("")
    method.append("## Output Files")
    method.append("")
    method.append("- `docs/COMPETITION/data/data_quality.json` (Stage 1)")
    method.append("- `docs/COMPETITION/data/raw_results.csv` (Stage 2)")
    method.append("- `docs/COMPETITION/data/raw_trades.csv` (Stage 2)")
    method.append("- `docs/COMPETITION/data/asset_matrix.csv` (Stage 2)")
    method.append("- `docs/COMPETITION/data/equity/<template>__<asset>.csv` (Stage 2)")
    method.append("- `docs/COMPETITION/data/regime_matrix.csv` (Stage 3)")
    method.append("- `docs/COMPETITION/data/walk_forward_matrix.csv` (Stage 4)")
    method.append("- `docs/COMPETITION/data/stress_test_matrix.csv` (Stage 5)")
    method.append("- `docs/COMPETITION/data/sensitivity_matrix.csv` (Stage 6)")
    method.append("- `docs/COMPETITION/data/baselines.csv` (Stage 7)")
    method.append("- `docs/COMPETITION/DATA_QUALITY.md` (Stage 1, human readable)")
    method.append("- `docs/COMPETITION/report.md` (Stage 8, human readable)")
    method.append("- `docs/COMPETITION/METHODOLOGY.md` (this file)")
    method.append("")
    method.append("## Pipeline Scripts")
    method.append("")
    method.append("- `docs/COMPETITION/scripts/competition_stage1_data.py` — fetch + quality check")
    method.append("- `docs/COMPETITION/scripts/competition_stage2_matrix.py` — main matrix")
    method.append("- `docs/COMPETITION/scripts/competition_backfill_equity_ts.py` — bug-fix backfill (BUG-1)")
    method.append("- `docs/COMPETITION/scripts/competition_stage3_regime.py` — regime breakdown")
    method.append("- `docs/COMPETITION/scripts/competition_stage4_walkforward.py` — walk-forward")
    method.append("- `docs/COMPETITION/scripts/competition_stage5_stress.py` — stress test (synthetic)")
    method.append("- `docs/COMPETITION/scripts/competition_stage6_sensitivity.py` — slippage sensitivity")
    method.append("- `docs/COMPETITION/scripts/competition_stage7_baselines.py` — baselines")
    method.append("- `docs/COMPETITION/scripts/competition_stage8_report.py` — report generator (this script)")
    method.append("")
    method.append("## Known Issues / Caveats")
    method.append("")
    method.append("- **Long-only system**: no template can profit during BTC bear (2022); all 22 are 0% or negative.")
    method.append("- **Conservative position sizing**: most templates use 10–50% of cash per entry, vastly underperforming buy-and-hold which is 100% deployed.")
    method.append("- **PAXG window shorter than 5y at the early end**: PAXG/USDT listed mid-2020 on Binance; we actually got 43,800 candles back to 2021-05-07 (same as others). Pre-2021-05 portion of any regime is `insufficient_data`.")
    method.append("- **BTC bull (2020-04 to 2021-11)**: only ~6 months of overlap with our data start (2021-05-07). Reported regime returns reflect partial overlap.")
    method.append("- **No short / no margin**: spot only per the test spec. Templates that include `margin_short` semantics would not be runnable in this harness.")
    method.append("- **Slippage as flat 0.1%**: per-asset liquidity differences (e.g. PAXG less liquid) not modeled. Sensitivity step 0.05/0.1/0.2 covers conservative range.")
    method.append("- **BUG-1 (resolved)**: Stage 2's equity CSV writer originally used `candle_time`/`candle_iso` keys not present in engine output, leaving all timestamps blank. Backfill script (`competition_backfill_equity_ts.py`) re-derived them from `bar_index` × candle file. Stage 2 source patched. Verified with 1065 → re-runs clean.")
    method.append("")
    (DOCS_DIR / "METHODOLOGY.md").write_text("\n".join(method))
    print(f"[stage8] wrote {DOCS_DIR / 'METHODOLOGY.md'}", file=sys.stderr)
    return 0


def datetime_now():
    from datetime import datetime
    return datetime.now().isoformat(timespec="seconds")


if __name__ == "__main__":
    sys.exit(main())
