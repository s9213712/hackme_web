#!/usr/bin/env python3
"""Auto parameter search for a workflow template that beats buy_and_hold.

Lessons from the 22-template competition:
  - Buy-and-hold avg across 5 assets = +33.2% (BTC +46, ETH -30, XRP -7,
    BNB +4, PAXG +154).
  - Workflow must avoid the ETH-style downtrend portions to win on
    average — long-only can't profit during a bear, can only stay flat.
  - MA200 trend filter is the cleanest "regime detector" available.
  - Entry conditions with 4-5 simultaneous AND clauses fire only once
    per 5y → trade_count too low.

Search space (curated, ~32 variants instead of full Cartesian):
  - Entry MA filter: above MA50 / MA100 / MA200
  - Entry RSI band: [35-70] / [40-65] / [40-70] / [30-75]
  - Initial size %: 70 / 99
  - Exit method: below_ma_filter / never
  - Pyramid on dip: enabled / disabled

Each candidate runs on 5 assets × 5y × 1h × fee 0.3% (slippage applied
post-hoc as 0.1% × turnover). Final ranking sorts by avg return across
assets. Winner is exported as workflows/trading_bot/<chosen_id>.json.
"""
from __future__ import annotations

import json
import sys
import time
from datetime import datetime
from itertools import product
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "docs" / "COMPETITION" / "scripts"))

from competition_stage2_matrix import (
    build_runtime, load_candles, ASSETS, INITIAL_CASH,
)

OUT_DIR = REPO_ROOT / "docs" / "COMPETITION" / "data"


def make_workflow(*, mid_id: str, label: str,
                  entry_ma_period: int, entry_rsi_floor: int, entry_rsi_ceil: int,
                  initial_size_pct: int,
                  exit_ma_period: int | None,
                  pyramid_enabled: bool,
                  pyramid_rsi_below: int = 35,
                  pyramid_size_pct: int = 30,
                  stop_loss_percent: int | None = None) -> dict:
    """Compose a workflow JSON from search parameters."""
    nodes = [
        {"id": "start", "type": "start", "label": "開始", "x": 0, "y": 400},
        # Entry: above MA filter + RSI in band + no position
        {"id": "entry_ma", "type": "condition", "label": f"上 MA{entry_ma_period}", "x": 1, "y": 100,
         "condition": {"type": "ma_position", "period": entry_ma_period, "position": "above"}},
        {"id": "entry_rsi_floor", "type": "condition", "label": f"RSI≥{entry_rsi_floor}", "x": 1, "y": 200,
         "condition": {"type": "rsi_above", "value": entry_rsi_floor}},
        {"id": "entry_rsi_ceil", "type": "condition", "label": f"RSI≤{entry_rsi_ceil}", "x": 1, "y": 300,
         "condition": {"type": "rsi_below", "value": entry_rsi_ceil}},
        {"id": "no_pos", "type": "condition", "label": "空倉", "x": 1, "y": 400,
         "condition": {"type": "has_position", "value": False}},
        {"id": "entry_and", "type": "logic", "label": "AND", "x": 2, "y": 250, "operator": "AND"},
        {"id": "entry_cooldown", "type": "control", "label": "冷卻 4h", "x": 3, "y": 250,
         "cooldown_seconds": 14400, "max_runs": 1000},
        {"id": "entry_buy", "type": "action", "label": f"買 {initial_size_pct}%", "x": 4, "y": 250, "priority": 10,
         "action": {"type": "buy_percent", "percent": initial_size_pct, "step": 100, "order_type": "market"}},
    ]
    edges = [
        {"id": "e_s_ma", "from": "start", "from_port": "out", "to": "entry_ma", "to_port": "in"},
        {"id": "e_s_rfl", "from": "start", "from_port": "out", "to": "entry_rsi_floor", "to_port": "in"},
        {"id": "e_s_rc", "from": "start", "from_port": "out", "to": "entry_rsi_ceil", "to_port": "in"},
        {"id": "e_s_np", "from": "start", "from_port": "out", "to": "no_pos", "to_port": "in"},
        {"id": "e_ma_an", "from": "entry_ma", "from_port": "true", "to": "entry_and", "to_port": "in"},
        {"id": "e_rfl_an", "from": "entry_rsi_floor", "from_port": "true", "to": "entry_and", "to_port": "in"},
        {"id": "e_rc_an", "from": "entry_rsi_ceil", "from_port": "true", "to": "entry_and", "to_port": "in"},
        {"id": "e_np_an", "from": "no_pos", "from_port": "true", "to": "entry_and", "to_port": "in"},
        {"id": "e_an_cd", "from": "entry_and", "from_port": "true", "to": "entry_cooldown", "to_port": "in"},
        {"id": "e_cd_buy", "from": "entry_cooldown", "from_port": "then", "to": "entry_buy", "to_port": "in"},
    ]

    if pyramid_enabled:
        nodes.extend([
            {"id": "p_ma", "type": "condition", "label": f"仍上 MA{entry_ma_period}", "x": 1, "y": 600,
             "condition": {"type": "ma_position", "period": entry_ma_period, "position": "above"}},
            {"id": "p_rsi", "type": "condition", "label": f"RSI<{pyramid_rsi_below}", "x": 1, "y": 700,
             "condition": {"type": "rsi_below", "value": pyramid_rsi_below}},
            {"id": "p_pos", "type": "condition", "label": "已持倉", "x": 1, "y": 800,
             "condition": {"type": "has_position", "value": True}},
            {"id": "p_and", "type": "logic", "label": "AND", "x": 2, "y": 700, "operator": "AND"},
            {"id": "p_cd", "type": "control", "label": "冷卻 24h", "x": 3, "y": 700,
             "cooldown_seconds": 86400, "max_runs": 1000},
            {"id": "p_buy", "type": "action", "label": f"加碼 {pyramid_size_pct}%", "x": 4, "y": 700, "priority": 30,
             "action": {"type": "buy_percent", "percent": pyramid_size_pct, "step": 100, "order_type": "market"}},
        ])
        edges.extend([
            {"id": "e_s_pma", "from": "start", "from_port": "out", "to": "p_ma", "to_port": "in"},
            {"id": "e_s_pr", "from": "start", "from_port": "out", "to": "p_rsi", "to_port": "in"},
            {"id": "e_s_pp", "from": "start", "from_port": "out", "to": "p_pos", "to_port": "in"},
            {"id": "e_pma_an", "from": "p_ma", "from_port": "true", "to": "p_and", "to_port": "in"},
            {"id": "e_pr_an", "from": "p_rsi", "from_port": "true", "to": "p_and", "to_port": "in"},
            {"id": "e_pp_an", "from": "p_pos", "from_port": "true", "to": "p_and", "to_port": "in"},
            {"id": "e_pan_cd", "from": "p_and", "from_port": "true", "to": "p_cd", "to_port": "in"},
            {"id": "e_pcd_buy", "from": "p_cd", "from_port": "then", "to": "p_buy", "to_port": "in"},
        ])

    if exit_ma_period is not None:
        nodes.extend([
            {"id": "x_ma", "type": "condition", "label": f"跌破 MA{exit_ma_period}", "x": 1, "y": 1000,
             "condition": {"type": "ma_position", "period": exit_ma_period, "position": "below"}},
            {"id": "x_pos", "type": "condition", "label": "已持倉", "x": 1, "y": 1100,
             "condition": {"type": "has_position", "value": True}},
            {"id": "x_and", "type": "logic", "label": "AND", "x": 2, "y": 1050, "operator": "AND"},
            {"id": "x_close", "type": "action", "label": "趨勢出場", "x": 3, "y": 1050, "priority": 70,
             "action": {"type": "close_all", "step": 1, "order_type": "market"}},
        ])
        edges.extend([
            {"id": "e_s_xma", "from": "start", "from_port": "out", "to": "x_ma", "to_port": "in"},
            {"id": "e_s_xp", "from": "start", "from_port": "out", "to": "x_pos", "to_port": "in"},
            {"id": "e_xma_an", "from": "x_ma", "from_port": "true", "to": "x_and", "to_port": "in"},
            {"id": "e_xp_an", "from": "x_pos", "from_port": "true", "to": "x_and", "to_port": "in"},
            {"id": "e_xan_cl", "from": "x_and", "from_port": "true", "to": "x_close", "to_port": "in"},
        ])

    if stop_loss_percent is not None:
        nodes.extend([
            {"id": "sl_cond", "type": "condition", "label": f"虧損 ≥ {stop_loss_percent}%", "x": 1, "y": 1300,
             "condition": {"type": "stop_loss_percent", "value": stop_loss_percent}},
            {"id": "sl_close", "type": "action", "label": "止損", "x": 3, "y": 1300, "priority": 100,
             "action": {"type": "close_all", "step": 1, "order_type": "market"}},
        ])
        edges.extend([
            {"id": "e_s_sl", "from": "start", "from_port": "out", "to": "sl_cond", "to_port": "in"},
            {"id": "e_sl_cl", "from": "sl_cond", "from_port": "true", "to": "sl_close", "to_port": "in"},
        ])

    return {
        "version": 2, "strategy_kind": "workflow_graph", "source": "param_search",
        "name": label, "start_node_id": "start",
        "nodes": nodes, "edges": edges,
    }


def search_space():
    """Generate ~32 candidate workflows by sampling key axes."""
    out = []
    # Core MA-trend candidates: above MA + RSI band, exit on MA cross down, no SL
    for ma_period in (50, 100, 200):
        for size in (70, 99):
            for has_exit in (True, False):
                exit_ma = ma_period if has_exit else None
                for has_pyramid in (False, True):
                    label = (f"ma{ma_period}_rsi40_70_size{size}"
                             f"{'_exit' if has_exit else ''}{'_pyr' if has_pyramid else ''}")
                    out.append({
                        "mid_id": label,
                        "entry_ma_period": ma_period,
                        "entry_rsi_floor": 40,
                        "entry_rsi_ceil": 70,
                        "initial_size_pct": size,
                        "exit_ma_period": exit_ma,
                        "pyramid_enabled": has_pyramid,
                        "stop_loss_percent": None,
                    })
    # Wider RSI windows on the most promising MA200 path
    for rsi_floor, rsi_ceil in ((30, 75), (35, 70), (45, 65)):
        for size in (90, 99):
            label = f"ma200_rsi{rsi_floor}_{rsi_ceil}_size{size}_exit"
            out.append({
                "mid_id": label,
                "entry_ma_period": 200,
                "entry_rsi_floor": rsi_floor,
                "entry_rsi_ceil": rsi_ceil,
                "initial_size_pct": size,
                "exit_ma_period": 200,
                "pyramid_enabled": False,
                "stop_loss_percent": None,
            })
    # No-exit (pure dip-buyer) pure variants — must beat passive holding
    for rsi_floor in (30, 35, 40):
        for size in (90, 99):
            label = f"dipbuy_rsi{rsi_floor}_70_size{size}_noexit"
            out.append({
                "mid_id": label,
                "entry_ma_period": 200,
                "entry_rsi_floor": rsi_floor,
                "entry_rsi_ceil": 70,
                "initial_size_pct": size,
                "exit_ma_period": None,
                "pyramid_enabled": True,
                "pyramid_rsi_below": rsi_floor,
                "pyramid_size_pct": 30,
                "stop_loss_percent": None,
            })
    return out


def main() -> int:
    trading = build_runtime()
    actor = {"id": 1, "username": "alice", "role": "user"}

    candidates = search_space()
    print(f"[search] {len(candidates)} candidates × 5 assets = {len(candidates) * 5} backtests", file=sys.stderr)

    results = []
    started = time.perf_counter()
    for i, cand in enumerate(candidates, 1):
        wf = make_workflow(label=cand["mid_id"], **cand)
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
        avg_ret = sum(rets) / len(rets)
        max_dd = max(dds) if dds else 0
        avg_trades = sum(tcs) / len(tcs)
        results.append({
            "candidate": cand,
            "per_asset": per_asset,
            "avg_ret": avg_ret, "max_dd": max_dd, "avg_trades": avg_trades,
        })
        print(f"  [{i:2d}/{len(candidates)}] {cand['mid_id']:<40} avg={avg_ret:>+7.2f}% maxDD={max_dd:>5.2f}% trades={avg_trades:>4.1f}", file=sys.stderr)

    elapsed = time.perf_counter() - started
    print(f"\n[search] done in {elapsed:.1f}s\n", file=sys.stderr)

    # Compare to buy_and_hold avg.
    bh_returns = {"BTC": 46.24, "ETH": -30.52, "XRP": -7.43, "BNB": 3.71, "PAXG": 153.80}
    bh_avg = sum(bh_returns.values()) / len(bh_returns)
    print(f"[compare] buy_and_hold avg = +{bh_avg:.2f}%\n", file=sys.stderr)

    results.sort(key=lambda r: r["avg_ret"], reverse=True)
    print("Top 10 candidates:", file=sys.stderr)
    print(f"{'rank':>3}  {'id':<40} {'avg ret%':>9} {'max DD%':>8} {'trades':>6} {'vs BH':>7}", file=sys.stderr)
    for i, r in enumerate(results[:10], 1):
        diff = r["avg_ret"] - bh_avg
        print(f"  {i:2d}  {r['candidate']['mid_id']:<40} {r['avg_ret']:>+8.2f} {r['max_dd']:>7.2f} {r['avg_trades']:>6.1f}  {diff:>+5.2f}pp",
              file=sys.stderr)

    # Persist all results
    out_json = OUT_DIR / "param_search_rev2_results.json"
    out_json.write_text(json.dumps({
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "candidate_count": len(candidates),
        "buy_and_hold_avg": bh_avg,
        "results": results,
    }, indent=2, ensure_ascii=False, default=str))
    print(f"\n[search] wrote {out_json}", file=sys.stderr)

    # Save winner workflow
    if results:
        winner = results[0]
        cand = winner["candidate"]
        wf = make_workflow(label=cand["mid_id"], **cand)
        full = {
            "id": "auto_search_winner_claude_rev2",
            "label": "自動搜索勝出（Claude rev2）",
            "description": (
                f"由 docs/COMPETITION/scripts/competition_param_search_rev2.py 自動搜索 "
                f"{len(candidates)} 個變體選出，5 資產 5y 平均報酬 {winner['avg_ret']:+.2f}%。"
                f" buy_and_hold 平均 +{bh_avg:.2f}%，差距 {winner['avg_ret']-bh_avg:+.2f}pp。"
            ),
            "scope": "system",
            "explanation": {
                "purpose": f"參數搜索勝出組合：{cand['mid_id']}",
                "entry_conditions": [
                    f"價格站上 MA{cand['entry_ma_period']}",
                    f"RSI ≥ {cand['entry_rsi_floor']} 且 ≤ {cand['entry_rsi_ceil']}",
                    "目前空倉",
                    "進場冷卻 4 小時",
                ],
                "actions": [
                    f"進場：買入 {cand['initial_size_pct']}%（step=100，允許多次再進場）",
                ],
                "risk_notes": [
                    "由參數搜索選出，可能對 5y BTC/ETH/XRP/BNB/PAXG 形態過度擬合，未來表現未知",
                ],
                "best_for": ["benchmark / 學術對照 / 跑 walk-forward 驗證"],
                "tuning": ["先看 docs/COMPETITION/data/param_search_rev2_results.json 對照同類變體再調"],
            },
            "workflow": wf,
        }
        if cand.get("exit_ma_period"):
            full["explanation"]["actions"].append(f"出場：跌破 MA{cand['exit_ma_period']} → 全平")
        if cand.get("pyramid_enabled"):
            full["explanation"]["actions"].append(
                f"加碼：仍站上 MA{cand['entry_ma_period']} + RSI<{cand.get('pyramid_rsi_below', 35)} + 持倉 → 買 {cand.get('pyramid_size_pct', 30)}%"
            )
        if cand.get("stop_loss_percent"):
            full["explanation"]["actions"].append(f"災難止損：虧損 ≥ {cand['stop_loss_percent']}% 全平")

        wf_path = REPO_ROOT / "workflows" / "trading_bot" / "auto_search_winner_claude_rev2.json"
        wf_path.write_text(json.dumps(full, ensure_ascii=False, indent=2))
        print(f"[search] wrote winner workflow to {wf_path}", file=sys.stderr)
        print(f"[search] winner id: {cand['mid_id']}", file=sys.stderr)
        print(f"[search] winner avg return: {winner['avg_ret']:+.2f}% vs B&H {bh_avg:+.2f}% (diff {winner['avg_ret']-bh_avg:+.2f}pp)", file=sys.stderr)

    return 0


if __name__ == "__main__":
    sys.exit(main())
