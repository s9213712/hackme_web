#!/usr/bin/env python3
"""Auto parameter search rev3 — same MA200+RSI entry as rev2, but with a
multi-stage take_profit ladder to control max drawdown.

Rev2 winner (+58.23% avg, 81.82% max DD) hit FAIL on max_DD > 25% because
"buy 99% and never sell" rides the full BTC 2022 bear. Rev3 keeps the
entry filter but layers a TP ladder on top so position size shrinks as
price rises, reducing exposure to drawdowns from peaks.

Search axes:
  initial_size_pct:  80, 99
  tp_ladder:         (20,40,60), (30,60,90), (50,100,200)
  tp_sell_pct:       25, 30, 50  (per stage, applied to remaining position)
  pyramid:           on (RSI<30 add) / off

= 2 × 3 × 3 × 2 = 36 candidates × 5 assets = 180 backtests.

Scoring: avg return % - 0.3 × max_DD %. Penalises DD enough to prefer
strategies that beat B&H AND have smaller drawdowns.
"""
from __future__ import annotations

import json
import sys
import time
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "docs" / "COMPETITION" / "scripts"))

from competition_stage2_matrix import (
    build_runtime, load_candles, ASSETS, INITIAL_CASH,
)

OUT_DIR = REPO_ROOT / "docs" / "COMPETITION" / "data"
B_AND_H = {"BTC": 46.24, "ETH": -30.52, "XRP": -7.43, "BNB": 3.71, "PAXG": 153.80}
B_AND_H_AVG = sum(B_AND_H.values()) / len(B_AND_H)


def make_workflow(*, mid_id, initial_size_pct, tp1, tp2, tp3, tp_sell_pct,
                  pyramid_enabled, pyramid_rsi=30, pyramid_size=30):
    """MA200 + RSI 40-70 entry + size 80/99 + 3-stage TP ladder + optional pyramid."""
    nodes = [
        {"id": "start", "type": "start", "label": "開始", "x": 0, "y": 400},
        # Entry
        {"id": "above_ma200", "type": "condition", "label": "上 MA200", "x": 1, "y": 100,
         "condition": {"type": "ma_position", "period": 200, "position": "above"}},
        {"id": "rsi_floor", "type": "condition", "label": "RSI≥40", "x": 1, "y": 200,
         "condition": {"type": "rsi_above", "value": 40}},
        {"id": "rsi_ceil", "type": "condition", "label": "RSI≤70", "x": 1, "y": 300,
         "condition": {"type": "rsi_below", "value": 70}},
        {"id": "no_pos", "type": "condition", "label": "空倉", "x": 1, "y": 400,
         "condition": {"type": "has_position", "value": False}},
        {"id": "entry_and", "type": "logic", "label": "AND", "x": 2, "y": 250, "operator": "AND"},
        {"id": "entry_cooldown", "type": "control", "label": "冷卻 4h", "x": 3, "y": 250,
         "cooldown_seconds": 14400, "max_runs": 1000},
        {"id": "entry_buy", "type": "action", "label": f"買 {initial_size_pct}%", "x": 4, "y": 250, "priority": 10,
         "action": {"type": "buy_percent", "percent": initial_size_pct, "step": 100, "order_type": "market"}},
    ]
    edges = [
        {"id": "e_s_ma", "from": "start", "from_port": "out", "to": "above_ma200", "to_port": "in"},
        {"id": "e_s_rfl", "from": "start", "from_port": "out", "to": "rsi_floor", "to_port": "in"},
        {"id": "e_s_rc", "from": "start", "from_port": "out", "to": "rsi_ceil", "to_port": "in"},
        {"id": "e_s_np", "from": "start", "from_port": "out", "to": "no_pos", "to_port": "in"},
        {"id": "e_ma_an", "from": "above_ma200", "from_port": "true", "to": "entry_and", "to_port": "in"},
        {"id": "e_rfl_an", "from": "rsi_floor", "from_port": "true", "to": "entry_and", "to_port": "in"},
        {"id": "e_rc_an", "from": "rsi_ceil", "from_port": "true", "to": "entry_and", "to_port": "in"},
        {"id": "e_np_an", "from": "no_pos", "from_port": "true", "to": "entry_and", "to_port": "in"},
        {"id": "e_an_cd", "from": "entry_and", "from_port": "true", "to": "entry_cooldown", "to_port": "in"},
        {"id": "e_cd_buy", "from": "entry_cooldown", "from_port": "then", "to": "entry_buy", "to_port": "in"},
    ]

    # TP ladder: 3 stages, each has condition (take_profit_percent X + has_position) → sell Y%
    for i, tp_value in enumerate([tp1, tp2, tp3], 1):
        nodes.extend([
            {"id": f"tp{i}_cond", "type": "condition", "label": f"獲利≥{tp_value}%", "x": 1, "y": 600 + i*200,
             "condition": {"type": "take_profit_percent", "value": tp_value}},
            {"id": f"tp{i}_pos", "type": "condition", "label": "已持倉", "x": 1, "y": 600 + i*200 + 80,
             "condition": {"type": "has_position", "value": True}},
            {"id": f"tp{i}_and", "type": "logic", "label": "AND", "x": 2, "y": 600 + i*200 + 40, "operator": "AND"},
            {"id": f"tp{i}_sell", "type": "action", "label": f"賣 {tp_sell_pct}%", "x": 3, "y": 600 + i*200 + 40,
             "priority": 40 + i*10,
             "action": {"type": "sell_percent", "percent": tp_sell_pct, "step": 100, "order_type": "market"}},
        ])
        edges.extend([
            {"id": f"e_s_tp{i}c", "from": "start", "from_port": "out", "to": f"tp{i}_cond", "to_port": "in"},
            {"id": f"e_s_tp{i}p", "from": "start", "from_port": "out", "to": f"tp{i}_pos", "to_port": "in"},
            {"id": f"e_tp{i}c_an", "from": f"tp{i}_cond", "from_port": "true", "to": f"tp{i}_and", "to_port": "in"},
            {"id": f"e_tp{i}p_an", "from": f"tp{i}_pos", "from_port": "true", "to": f"tp{i}_and", "to_port": "in"},
            {"id": f"e_tp{i}_sell", "from": f"tp{i}_and", "from_port": "true", "to": f"tp{i}_sell", "to_port": "in"},
        ])

    # Optional pyramid
    if pyramid_enabled:
        nodes.extend([
            {"id": "p_ma", "type": "condition", "label": "仍上 MA200", "x": 1, "y": 1700,
             "condition": {"type": "ma_position", "period": 200, "position": "above"}},
            {"id": "p_rsi", "type": "condition", "label": f"RSI<{pyramid_rsi}", "x": 1, "y": 1800,
             "condition": {"type": "rsi_below", "value": pyramid_rsi}},
            {"id": "p_pos", "type": "condition", "label": "已持倉", "x": 1, "y": 1900,
             "condition": {"type": "has_position", "value": True}},
            {"id": "p_and", "type": "logic", "label": "AND", "x": 2, "y": 1800, "operator": "AND"},
            {"id": "p_cd", "type": "control", "label": "冷卻 24h", "x": 3, "y": 1800,
             "cooldown_seconds": 86400, "max_runs": 1000},
            {"id": "p_buy", "type": "action", "label": f"加碼 {pyramid_size}%", "x": 4, "y": 1800, "priority": 30,
             "action": {"type": "buy_percent", "percent": pyramid_size, "step": 100, "order_type": "market"}},
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

    return {"version": 2, "strategy_kind": "workflow_graph", "source": "param_search",
            "name": mid_id, "start_node_id": "start", "nodes": nodes, "edges": edges}


def search_space():
    out = []
    for size in (80, 99):
        for tp1, tp2, tp3 in [(20, 40, 60), (30, 60, 90), (50, 100, 200)]:
            for tp_sell in (25, 30, 50):
                for pyramid in (False, True):
                    label = f"size{size}_tp{tp1}_{tp2}_{tp3}_sell{tp_sell}{'_pyr' if pyramid else ''}"
                    out.append({
                        "mid_id": label,
                        "initial_size_pct": size,
                        "tp1": tp1, "tp2": tp2, "tp3": tp3,
                        "tp_sell_pct": tp_sell,
                        "pyramid_enabled": pyramid,
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
        wf = make_workflow(**cand)
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
        # Risk-adjusted score: penalise DD, reward return
        score = avg_ret - 0.3 * max_dd
        results.append({
            "candidate": cand,
            "per_asset": per_asset,
            "avg_ret": avg_ret, "max_dd": max_dd, "avg_trades": avg_trades,
            "score": score,
        })
        print(f"  [{i:2d}/{len(candidates)}] {cand['mid_id']:<45} avg={avg_ret:>+7.2f}% maxDD={max_dd:>5.2f}% trades={avg_trades:>4.1f} score={score:>+7.2f}",
              file=sys.stderr)

    elapsed = time.perf_counter() - started
    print(f"\n[search] done in {elapsed:.1f}s", file=sys.stderr)
    print(f"[compare] buy_and_hold avg = +{B_AND_H_AVG:.2f}%\n", file=sys.stderr)

    # Two rankings: by raw return and by score (risk-adjusted)
    by_return = sorted(results, key=lambda r: r["avg_ret"], reverse=True)
    by_score = sorted(results, key=lambda r: r["score"], reverse=True)

    print("Top 10 by avg return:", file=sys.stderr)
    print(f"{'rank':>3}  {'id':<45} {'avg ret%':>9} {'max DD%':>8} {'vs BH':>7}", file=sys.stderr)
    for i, r in enumerate(by_return[:10], 1):
        print(f"  {i:2d}  {r['candidate']['mid_id']:<45} {r['avg_ret']:>+8.2f} {r['max_dd']:>7.2f}  {r['avg_ret'] - B_AND_H_AVG:>+5.2f}pp",
              file=sys.stderr)

    print("\nTop 10 by score (avg_ret - 0.3 × max_DD):", file=sys.stderr)
    print(f"{'rank':>3}  {'id':<45} {'score':>7} {'avg ret%':>9} {'max DD%':>8}", file=sys.stderr)
    for i, r in enumerate(by_score[:10], 1):
        print(f"  {i:2d}  {r['candidate']['mid_id']:<45} {r['score']:>+7.2f} {r['avg_ret']:>+8.2f} {r['max_dd']:>7.2f}",
              file=sys.stderr)

    # Persist all
    out_json = OUT_DIR / "param_search_rev3_results.json"
    out_json.write_text(json.dumps({
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "candidate_count": len(candidates),
        "buy_and_hold_avg": B_AND_H_AVG,
        "results": results,
    }, indent=2, ensure_ascii=False, default=str))
    print(f"\n[search] wrote {out_json}", file=sys.stderr)

    # Save BOTH winners (raw return + risk-adjusted)
    for label_suffix, winner_list in (("rev3_return", by_return), ("rev3_score", by_score)):
        if not winner_list:
            continue
        winner = winner_list[0]
        cand = winner["candidate"]
        wf = make_workflow(**cand)
        full = {
            "id": f"auto_search_winner_claude_{label_suffix}",
            "label": f"自動搜索勝出（Claude {label_suffix}）",
            "description": (
                f"由 docs/COMPETITION/scripts/competition_param_search_rev3.py 自動搜索 "
                f"{len(candidates)} 個 TP-ladder 變體選出 ({label_suffix})，"
                f"5 資產 5y 平均報酬 {winner['avg_ret']:+.2f}%，最大回撤 {winner['max_dd']:.2f}%。"
                f" buy_and_hold 平均 +{B_AND_H_AVG:.2f}%。"
            ),
            "scope": "system",
            "explanation": {
                "purpose": f"參數搜索勝出組合 ({label_suffix}): {cand['mid_id']}",
                "entry_conditions": [
                    "價格站上 MA200",
                    "RSI 40–70 區間",
                    "目前空倉",
                    "進場冷卻 4 小時",
                ],
                "actions": [
                    f"進場：買入 {cand['initial_size_pct']}%",
                    f"TP1：獲利 ≥ {cand['tp1']}% → 賣 {cand['tp_sell_pct']}%",
                    f"TP2：獲利 ≥ {cand['tp2']}% → 賣 {cand['tp_sell_pct']}%",
                    f"TP3：獲利 ≥ {cand['tp3']}% → 賣 {cand['tp_sell_pct']}%",
                ],
                "risk_notes": [f"由參數搜索選出 ({label_suffix} 標準)，可能對 5y 形態過擬合"],
                "best_for": ["benchmark / 對比 rev2 看 TP ladder 是否能降 DD"],
                "tuning": ["看 docs/COMPETITION/data/param_search_rev3_results.json 對照 36 個變體"],
            },
            "workflow": wf,
        }
        if cand.get("pyramid_enabled"):
            full["explanation"]["actions"].append("加碼：仍上 MA200 + RSI<30 + 持倉 → 買 30%")

        wf_path = REPO_ROOT / "workflows" / "trading_bot" / f"auto_search_winner_claude_{label_suffix}.json"
        wf_path.write_text(json.dumps(full, ensure_ascii=False, indent=2))
        print(f"[search] wrote {label_suffix} winner to {wf_path}", file=sys.stderr)
        print(f"   id: {cand['mid_id']}", file=sys.stderr)
        print(f"   ret: {winner['avg_ret']:+.2f}% / DD: {winner['max_dd']:.2f}% / score: {winner['score']:+.2f}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    sys.exit(main())
