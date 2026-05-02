#!/usr/bin/env python3
"""Validate official trading workflow templates with trigger and backtest checks.

This script is intentionally read-only for production data. It builds a temporary
SQLite database, loads templates from workflows/system, downloads public BTC
K-lines, runs the backend backtest engine, then compares the result with a
small independent accounting replay over the same candles.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.points_chain import PointsLedgerService, ensure_points_economy_schema  # noqa: E402
from services.trading_engine import (  # noqa: E402
    ASSET_SCALE,
    MAX_BACKTEST_CANDLES,
    TradingEngineService,
    ensure_trading_schema,
    fee_points,
    notional_points,
    units_to_quantity,
)


REPORT_DIR = ROOT / "security" / "reports"
WORKFLOW_DIR = ROOT / "workflows" / "system"
TRIGGER_CASES = {
    "dip_buy": ({"price": 85000, "has_position": False}, "buy_percent"),
    "breakout_buy": ({"price": 110000, "ma50": 100000, "has_position": False}, "buy_percent"),
    "stop_loss": ({"price": 70000, "has_position": True, "pnl_percent": -20}, "close_all"),
    "rsi_scale": ({"price": 90000, "rsi": 25, "has_position": False}, "buy_percent"),
    "ma_pullback": ({"price": 100000, "ma50": 90000, "rsi": 40, "has_position": False}, "buy_percent"),
    "bollinger_reversion": ({"price": 80000, "bb_lower": 90000, "bb_mid": 100000, "has_position": False}, "buy_percent"),
    "kd_momentum": ({"price": 100000, "kd": 70, "ma20": 90000, "has_position": False}, "buy_percent"),
    "risk_guard": ({"price": 90000, "has_position": True, "pnl_percent": -6}, "close_all"),
    "full_entry_exit": ({"price": 80000, "has_position": False}, "buy_percent"),
    "ma200_trend_entry": ({"price": 100000, "ma200": 85000, "ma50": 90000, "rsi": 50, "has_position": False}, "buy_percent"),
    "staged_profit_taking": ({"price": 120000, "has_position": True, "pnl_percent": 12}, "sell_percent"),
    "swing_bb_ma50": ({"price": 80000, "bb_lower": 90000, "ma50": 70000, "has_position": False}, "buy_percent"),
}


def utc_iso_from_ms(value: int) -> str:
    return datetime.fromtimestamp(value / 1000, tz=timezone.utc).isoformat()


def fetch_json(url: str, timeout: float = 20.0):
    req = Request(url, headers={"User-Agent": "hackme-web-workflow-validation/1.0"})
    with urlopen(req, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def download_binance_candles(symbol: str, interval: str, limit: int):
    query = urlencode({"symbol": symbol, "interval": interval, "limit": limit})
    payload = fetch_json(f"https://api.binance.com/api/v3/klines?{query}")
    candles = []
    for row in payload:
        candles.append({
            "time": int(row[0]),
            "time_iso": utc_iso_from_ms(int(row[0])),
            "open_points": round(float(row[1])),
            "high_points": round(float(row[2])),
            "low_points": round(float(row[3])),
            "close_points": round(float(row[4])),
            "volume": float(row[5]),
        })
    return {"source": "binance_public_api", "symbol": symbol, "candles": candles}


def download_okx_candles(instrument: str, interval: str, limit: int):
    bars = {"5m": "5m", "15m": "15m", "1h": "1H", "4h": "4H", "1d": "1D"}
    query = urlencode({"instId": instrument, "bar": bars[interval], "limit": limit})
    payload = fetch_json(f"https://www.okx.com/api/v5/market/candles?{query}")
    rows = sorted(payload.get("data") or [], key=lambda item: int(item[0]))
    candles = []
    for row in rows:
        candles.append({
            "time": int(row[0]),
            "time_iso": utc_iso_from_ms(int(row[0])),
            "open_points": round(float(row[1])),
            "high_points": round(float(row[2])),
            "low_points": round(float(row[3])),
            "close_points": round(float(row[4])),
            "volume": float(row[5]) if len(row) > 5 else 0,
        })
    return {"source": "okx_public_api", "symbol": instrument, "candles": candles}


def download_candles(interval: str, limit: int):
    errors = []
    for fetcher, args in (
        (download_binance_candles, ("BTCUSDT", interval, limit)),
        (download_okx_candles, ("BTC-USDT", interval, limit)),
    ):
        try:
            result = fetcher(*args)
            if len(result["candles"]) >= 2:
                return result
            errors.append(f"{fetcher.__name__}: too few candles")
        except Exception as exc:
            errors.append(f"{fetcher.__name__}: {exc}")
    raise RuntimeError("; ".join(errors))


def get_test_services(tmp_dir: Path):
    db_path = tmp_dir / "workflow_validation.db"

    def get_db():
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    conn = get_db()
    conn.execute(
        "CREATE TABLE users (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT NOT NULL UNIQUE, role TEXT NOT NULL DEFAULT 'user', status TEXT NOT NULL DEFAULT 'active')"
    )
    conn.execute(
        "INSERT INTO users (username, role, status) VALUES ('alice', 'user', 'active'), ('root', 'super_admin', 'active')"
    )
    ensure_points_economy_schema(conn)
    ensure_trading_schema(conn)
    conn.commit()
    conn.close()

    points = PointsLedgerService(get_db=get_db, chain_secret="validation-secret", backup_dir=tmp_dir / "points_chain_backups")
    trading = TradingEngineService(get_db=get_db, points_service=points, live_price_provider=lambda symbol: 100000)
    return trading


def load_templates(trading: TradingEngineService):
    templates = []
    for path in sorted(WORKFLOW_DIR.glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        workflow = trading._validate_workflow(payload.get("workflow"))
        templates.append({"id": payload.get("id") or path.stem, "label": payload.get("label") or path.stem, "path": path, "workflow": workflow})
    return templates


def validate_trigger(trading: TradingEngineService, template):
    template_id = template["id"]
    context, expected_action = TRIGGER_CASES.get(template_id, ({"price": 100000, "has_position": False}, None))
    decision = trading._workflow_decision(template["workflow"], context=context, run_count=0, last_run_at=None, execution_state={"executed_action_ids": set(), "branch_step_counts": {}})
    action = (decision or {}).get("action") or {}
    actual_action = action.get("type")
    ok = bool(decision) and (expected_action is None or actual_action == expected_action)
    return {
        "ok": ok,
        "expected_action": expected_action,
        "actual_action": actual_action,
        "reason": (decision or {}).get("reason") or "",
        "context": context,
    }


def update_workflow_state(state, decision):
    action = (decision or {}).get("action") or {}
    action_id = (decision or {}).get("action_id") or ((decision or {}).get("branch") or {}).get("id")
    if action_id:
        state["branch_step_counts"][action_id] = int(state["branch_step_counts"].get(action_id, 0)) + 1
        if action.get("type") != "close_all":
            state["executed_action_ids"].add(action_id)


def independent_replay(trading: TradingEngineService, workflow, candles, *, fee_rate_percent=0.3, initial_cash=10000):
    cash = int(initial_cash)
    units = 0
    avg_cost = 0
    trades = []
    curve = []
    peak = cash
    max_drawdown = 0.0
    wins = 0
    sells = 0
    state = {"executed_action_ids": set(), "branch_step_counts": {}}
    for index, candle in enumerate(candles):
        try:
            price = int(round(float(candle.get("close_points") or candle.get("price_points") or candle.get("close_usdt") or candle.get("price_usdt"))))
        except Exception:
            continue
        if price <= 0:
            continue
        context = trading._workflow_indicator_context(candles, index)
        context["price"] = price
        context["has_position"] = units > 0
        context["avg_cost"] = avg_cost
        context["pnl_percent"] = round((price - avg_cost) * 100.0 / avg_cost, 4) if units > 0 and avg_cost > 0 else None
        decision = trading._workflow_decision(workflow, context=context, run_count=len(trades), last_run_at=None, execution_state=state)
        action = (decision or {}).get("action") or {}
        atype = str(action.get("type") or "hold")
        if atype in {"sell_percent", "close_all"} and units > 0:
            percent = 100.0 if atype == "close_all" else max(0.0, min(float(action.get("percent") or 0), 100.0))
            sell_units = int(units * percent / 100)
            if sell_units > 0:
                gross = notional_points(sell_units, price)
                fee = fee_points(gross, fee_rate_percent)
                cash += max(0, gross - fee)
                units -= sell_units
                if units <= 0:
                    avg_cost = 0
                trades.append({
                    "index": index,
                    "time": candle.get("time") or candle.get("time_iso") or index,
                    "side": "sell",
                    "price_points": price,
                    "spend_points": 0,
                    "fee_points": fee,
                    "pnl_points": max(0, gross - fee),
                    "quantity": units_to_quantity(sell_units),
                })
                sells += 1
                if gross - fee > 0:
                    wins += 1
                update_workflow_state(state, decision)
                equity = cash + notional_points(units, price)
                peak = max(peak, equity)
                max_drawdown = max(max_drawdown, round((peak - equity) * 100 / peak, 4)) if peak else max_drawdown
                curve.append({"index": index, "time": candle.get("time") or candle.get("time_iso") or index, "equity_points": equity, "price_points": price})
            continue
        if atype not in {"buy_percent", "buy_amount"} or cash <= 0:
            equity = cash + notional_points(units, price)
            peak = max(peak, equity)
            max_drawdown = max(max_drawdown, round((peak - equity) * 100 / peak, 4)) if peak else max_drawdown
            curve.append({"index": index, "time": candle.get("time") or candle.get("time_iso") or index, "equity_points": equity, "price_points": price})
            continue
        spend = int(float(action.get("amount_points") or 0))
        if atype == "buy_percent":
            spend = int(cash * max(0.0, min(float(action.get("percent") or 0), 100.0)) / 100)
        spend = min(spend, cash)
        fee = fee_points(spend, fee_rate_percent)
        net_spend = max(0, spend - fee)
        buy_units = int((net_spend * ASSET_SCALE) // price)
        if buy_units <= 0:
            continue
        cash -= spend
        previous_units = units
        units += buy_units
        if units > 0:
            avg_cost = int((previous_units * avg_cost + buy_units * price) // units)
        trades.append({
            "index": index,
            "time": candle.get("time") or candle.get("time_iso") or index,
            "side": "buy",
            "price_points": price,
            "spend_points": spend,
            "fee_points": fee,
            "quantity": units_to_quantity(buy_units),
        })
        update_workflow_state(state, decision)
        equity = cash + notional_points(units, price)
        peak = max(peak, equity)
        max_drawdown = max(max_drawdown, round((peak - equity) * 100 / peak, 4)) if peak else max_drawdown
        curve.append({"index": index, "time": candle.get("time") or candle.get("time_iso") or index, "equity_points": equity, "price_points": price})
    last_price = 0
    for candle in reversed(candles):
        try:
            last_price = int(round(float(candle.get("close_points") or candle.get("price_points") or candle.get("close_usdt") or candle.get("price_usdt"))))
            if last_price > 0:
                break
        except Exception:
            continue
    position_value = notional_points(units, last_price) if last_price else 0
    final_value = cash + position_value
    return {
        "cash_points": cash,
        "position_quantity": units_to_quantity(units),
        "position_value_points": position_value,
        "final_value_points": final_value,
        "pnl_points": final_value - int(initial_cash),
        "return_percent": round(((final_value - int(initial_cash)) * 100) / int(initial_cash), 4),
        "max_drawdown_percent": max_drawdown,
        "win_rate_percent": round((wins * 100 / sells), 4) if sells else 0.0,
        "trade_count": len(trades),
        "trades": trades,
        "equity_curve": curve,
    }


def compare_results(engine_result, replay_result):
    keys = [
        "cash_points",
        "position_quantity",
        "position_value_points",
        "final_value_points",
        "pnl_points",
        "return_percent",
        "max_drawdown_percent",
        "win_rate_percent",
        "trade_count",
    ]
    mismatches = []
    for key in keys:
        if engine_result.get(key) != replay_result.get(key):
            mismatches.append({"field": key, "engine": engine_result.get(key), "replay": replay_result.get(key)})
    return mismatches


def write_reports(report):
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    json_path = REPORT_DIR / f"workflow_template_validation_{stamp}.json"
    md_path = REPORT_DIR / f"workflow_template_validation_{stamp}.md"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    lines = [
        "# Workflow Template Validation Report",
        "",
        f"- Generated at: {report['generated_at']}",
        f"- Data source: {report['data_source']} {report['provider_symbol']}",
        f"- Candle count: {report['candle_count']}",
        f"- Range: {report['first_candle_time']} -> {report['last_candle_time']}",
        f"- Engine max candles: {report['limits']['engine_max_backtest_candles']}",
        f"- Automatic provider request limit: {report['limits']['automatic_provider_request_limit']}",
        "",
        "## Results",
        "",
    ]
    for item in report["templates"]:
        status = "PASS" if item["ok"] else "FAIL"
        lines.append(f"- {status} `{item['id']}`: trigger={item['trigger']['actual_action']} trades={item['engine_backtest']['trade_count']} final={item['engine_backtest']['final_value_points']} mismatches={len(item['mismatches'])}")
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return json_path, md_path


def main():
    parser = argparse.ArgumentParser(description="Validate official trading workflow templates.")
    parser.add_argument("--interval", default="15m", choices=["5m", "15m", "1h", "4h", "1d"])
    parser.add_argument("--limit", type=int, default=500)
    parser.add_argument("--no-download", action="store_true", help="Use synthetic candles only.")
    args = parser.parse_args()
    if args.limit < 2 or args.limit > 1000:
        raise SystemExit("--limit must be between 2 and 1000 for one provider request")

    with tempfile.TemporaryDirectory(prefix="hackme-workflow-validation-") as tmp:
        trading = get_test_services(Path(tmp))
        templates = load_templates(trading)
        if args.no_download:
            candles = [
                {"time": i, "time_iso": f"synthetic-{i:04d}", "open_points": 90000 + i, "high_points": 90500 + i, "low_points": 89500 + i, "close_points": 90000 + i}
                for i in range(args.limit)
            ]
            source = {"source": "synthetic", "symbol": "BTCUSDT", "candles": candles}
        else:
            source = download_candles(args.interval, args.limit)
            candles = source["candles"]

        report = {
            "ok": True,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "data_source": source["source"],
            "provider_symbol": source["symbol"],
            "candle_count": len(candles),
            "first_candle_time": candles[0].get("time_iso") if candles else "",
            "last_candle_time": candles[-1].get("time_iso") if candles else "",
            "limits": {
                "engine_max_backtest_candles": MAX_BACKTEST_CANDLES,
                "automatic_provider_request_limit": 1000,
                "script_limit": args.limit,
                "period_limit_note": "No calendar-duration limit is enforced; candle count is limited.",
            },
            "templates": [],
        }
        actor = {"id": 1, "username": "alice", "role": "user"}
        for template in templates:
            trigger = validate_trigger(trading, template)
            engine_result = trading.backtest_trading_bot(
                actor=actor,
                payload={
                    "market_symbol": "BTC/POINTS",
                    "strategy": "workflow",
                    "workflow_json": template["workflow"],
                    "candles": candles,
                    "initial_cash_points": 10000,
                    "data_source": source["source"],
                    "provider_symbol": source["symbol"],
                },
            )
            replay_result = independent_replay(trading, template["workflow"], candles, initial_cash=10000)
            mismatches = compare_results(engine_result, replay_result)
            ok = trigger["ok"] and not mismatches
            report["templates"].append({
                "id": template["id"],
                "label": template["label"],
                "ok": ok,
                "trigger": trigger,
                "engine_backtest": {
                    "trade_count": engine_result["trade_count"],
                    "final_value_points": engine_result["final_value_points"],
                    "pnl_points": engine_result["pnl_points"],
                    "return_percent": engine_result["return_percent"],
                    "max_drawdown_percent": engine_result["max_drawdown_percent"],
                    "win_rate_percent": engine_result["win_rate_percent"],
                },
                "independent_replay": {
                    "trade_count": replay_result["trade_count"],
                    "final_value_points": replay_result["final_value_points"],
                    "pnl_points": replay_result["pnl_points"],
                    "return_percent": replay_result["return_percent"],
                    "max_drawdown_percent": replay_result["max_drawdown_percent"],
                    "win_rate_percent": replay_result["win_rate_percent"],
                },
                "mismatches": mismatches,
            })
            if not ok:
                report["ok"] = False

        json_path, md_path = write_reports(report)
        print(json.dumps({
            "ok": report["ok"],
            "templates": len(report["templates"]),
            "data_source": report["data_source"],
            "candle_count": report["candle_count"],
            "json_report": str(json_path),
            "md_report": str(md_path),
        }, ensure_ascii=False, indent=2))
        raise SystemExit(0 if report["ok"] else 1)


if __name__ == "__main__":
    main()
