#!/usr/bin/env python3
import argparse
import json
import math
import sqlite3
import tempfile
import time
from pathlib import Path

from flask import Flask, jsonify

from routes.trading import register_trading_routes
from services.points_chain import PointsLedgerService, ensure_points_economy_schema
from services.trading_engine import ASSET_SCALE, TradingEngineService, ensure_trading_schema, fee_points


def build_temp_services():
    temp_dir = Path(tempfile.mkdtemp(prefix="hackme_backtest_20000_"))
    db_path = temp_dir / "trading.db"

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
        "INSERT INTO users (username, role, status) VALUES "
        "('alice', 'user', 'active'), "
        "('root', 'super_admin', 'active')"
    )
    ensure_points_economy_schema(conn)
    ensure_trading_schema(conn)
    conn.commit()
    conn.close()

    points = PointsLedgerService(get_db=get_db, chain_secret="probe-secret", backup_dir=temp_dir / "points_chain_backups")
    trading = TradingEngineService(get_db=get_db, points_service=points)
    return temp_dir, points, trading


def actor(user_id=1, username="alice", role="user"):
    return {"id": user_id, "username": username, "role": role}


def candle_series(length, price_points, *, spike_map=None):
    spikes = spike_map or {}
    candles = []
    for index in range(length):
        price = int(spikes.get(index, price_points))
        candles.append(
            {
                "time_iso": f"2026-01-{1 + (index // 1440):02d}T{(index // 60) % 24:02d}:{index % 60:02d}:00+00:00",
                "open_points": price,
                "high_points": price,
                "low_points": price,
                "close_points": price,
            }
        )
    return candles


def dca_probe(trading):
    candles = candle_series(20_000, 100)
    result = trading.backtest_trading_bot(
        actor=actor(),
        payload={
            "market_symbol": "ETH/POINTS",
            "strategy": "dca",
            "initial_cash_points": 10_000,
            "order_points": 100,
            "interval_candles": 250,
            "candles": candles,
        },
    )
    expected_trades = ((len(candles) - 1) // 250) + 1
    expected_cash = 10_000 - (expected_trades * 100)
    expected_units = expected_trades * ASSET_SCALE
    expected_final = expected_cash + expected_trades * 100
    return {
        "scenario": "dca_constant_price_20000",
        "expected": {
            "trade_count": expected_trades,
            "cash_points": expected_cash,
            "end_units": expected_units,
            "final_value_points": expected_final,
            "segmented_backtest": True,
            "segmented_backtest_batches": 2,
        },
        "actual": {
            "trade_count": result["trade_count"],
            "cash_points": result["cash_points"],
            "end_units": result["end_units"],
            "final_value_points": result["final_value_points"],
            "segmented_backtest": result["segmented_backtest"],
            "segmented_backtest_batches": result["segmented_backtest_batches"],
        },
        "match": (
            result["trade_count"] == expected_trades
            and result["cash_points"] == expected_cash
            and result["end_units"] == expected_units
            and result["final_value_points"] == expected_final
            and result["segmented_backtest"] is True
            and result["segmented_backtest_batches"] == 2
        ),
    }


def conditional_probe(trading):
    candles = candle_series(20_000, 200, spike_map={9_999: 100})
    result = trading.backtest_trading_bot(
        actor=actor(),
        payload={
            "market_symbol": "ETH/POINTS",
            "strategy": "conditional",
            "initial_cash_points": 100,
            "order_points": 100,
            "trigger_type": "price_below",
            "trigger_price_points": 100,
            "candles": candles,
        },
    )
    return {
        "scenario": "conditional_single_cross_segment_buy_20000",
        "expected": {
            "trade_count": 1,
            "buy_price_points": 100,
            "buy_fee_points": 0,
            "cash_points": 0,
            "end_units": ASSET_SCALE,
            "final_value_points": 200,
            "segmented_backtest": True,
            "segmented_backtest_batches": 2,
        },
        "actual": {
            "trade_count": result["trade_count"],
            "buy_price_points": result["trades"][0]["price_points"] if result["trades"] else None,
            "buy_fee_points": result["trades"][0]["fee_points"] if result["trades"] else None,
            "cash_points": result["cash_points"],
            "end_units": result["end_units"],
            "final_value_points": result["final_value_points"],
            "segmented_backtest": result["segmented_backtest"],
            "segmented_backtest_batches": result["segmented_backtest_batches"],
        },
        "match": (
            result["trade_count"] == 1
            and result["trades"][0]["price_points"] == 100
            and result["trades"][0]["fee_points"] == 0
            and result["cash_points"] == 0
            and result["end_units"] == ASSET_SCALE
            and result["final_value_points"] == 200
            and result["segmented_backtest"] is True
            and result["segmented_backtest_batches"] == 2
        ),
    }


def workflow_definition():
    return {
        "version": 1,
        "strategy_kind": "workflow",
        "branches": [
            {
                "id": "buy_dip",
                "name": "跌破買進",
                "priority": 20,
                "logic": "AND",
                "cooldown_seconds": 0,
                "max_runs": 1,
                "conditions": [
                    {"type": "price_below", "value": 100},
                    {"type": "has_position", "value": False},
                ],
                "actions": [
                    {"type": "buy_percent", "percent": 100, "step": 1, "order_type": "market"},
                ],
            },
            {
                "id": "sell_rally",
                "name": "漲破賣出",
                "priority": 10,
                "logic": "AND",
                "cooldown_seconds": 0,
                "max_runs": 1,
                "conditions": [
                    {"type": "price_above", "value": 110},
                    {"type": "has_position", "value": True},
                ],
                "actions": [
                    {"type": "close_all", "step": 1, "order_type": "market"},
                ],
            },
        ],
    }


def workflow_probe(trading):
    candles = candle_series(20_000, 100, spike_map={**{idx: 200 for idx in range(9_999)}, 9_999: 90, 19_999: 120})
    result = trading.backtest_trading_bot(
        actor=actor(),
        payload={
            "market_symbol": "ETH/POINTS",
            "strategy": "workflow",
            "workflow_json": workflow_definition(),
            "initial_cash_points": 10_000,
            "order_points": 1_000,
            "candles": candles,
        },
    )
    buy_spend = 10_000
    buy_fee = fee_points(buy_spend, 0.1)
    buy_units = int(((buy_spend - buy_fee) * ASSET_SCALE) // 90)
    sell_gross = int(math.ceil((buy_units * 120) / ASSET_SCALE))
    sell_fee = fee_points(sell_gross, 0.1)
    expected_final = sell_gross - sell_fee
    return {
        "scenario": "workflow_branch_buy_then_sell_20000",
        "expected": {
            "trade_count": 2,
            "buy_price_points": 90,
            "sell_price_points": 120,
            "buy_fee_points": buy_fee,
            "sell_fee_points": sell_fee,
            "end_units": 0,
            "final_value_points": expected_final,
            "segmented_backtest": True,
            "segmented_backtest_batches": 2,
        },
        "actual": {
            "trade_count": result["trade_count"],
            "buy_price_points": result["trades"][0]["price_points"],
            "sell_price_points": result["trades"][1]["price_points"],
            "buy_fee_points": result["trades"][0]["fee_points"],
            "sell_fee_points": result["trades"][1]["fee_points"],
            "end_units": result["end_units"],
            "final_value_points": result["final_value_points"],
            "segmented_backtest": result["segmented_backtest"],
            "segmented_backtest_batches": result["segmented_backtest_batches"],
        },
        "match": (
            result["trade_count"] == 2
            and result["trades"][0]["price_points"] == 90
            and result["trades"][1]["price_points"] == 120
            and result["trades"][0]["fee_points"] == buy_fee
            and result["trades"][1]["fee_points"] == sell_fee
            and result["end_units"] == 0
            and result["final_value_points"] == expected_final
            and result["segmented_backtest"] is True
            and result["segmented_backtest_batches"] == 2
        ),
    }


def over_limit_probe(trading):
    candles = candle_series(20_001, 100)
    try:
        trading.backtest_trading_bot(
            actor=actor(),
            payload={
                "market_symbol": "ETH/POINTS",
                "strategy": "dca",
                "initial_cash_points": 10_000,
                "order_points": 100,
                "interval_candles": 250,
                "candles": candles,
            },
        )
    except ValueError as exc:
        message = str(exc)
        return {
            "scenario": "over_limit_20001_rejected",
            "status": "error",
            "message": message,
            "match": "candles length must be <= 20000" in message,
        }
    return {
        "scenario": "over_limit_20001_rejected",
        "status": "unexpected_success",
        "message": "backtest unexpectedly accepted more than 20,000 candles",
        "match": False,
    }


def grid_probe(trading):
    candles = candle_series(19_996, 100) + [
        {"time_iso": "2026-01-07T22:38:00+00:00", "open_points": 100, "high_points": 100, "low_points": 100, "close_points": 100},
        {"time_iso": "2026-01-07T22:39:00+00:00", "open_points": 100, "high_points": 100, "low_points": 90, "close_points": 90},
        {"time_iso": "2026-01-07T22:40:00+00:00", "open_points": 90, "high_points": 110, "low_points": 90, "close_points": 110},
        {"time_iso": "2026-01-07T22:41:00+00:00", "open_points": 110, "high_points": 120, "low_points": 80, "close_points": 100},
    ]
    result = trading.backtest_trading_bot(
        actor=actor(),
        payload={
            "market_symbol": "ETH/POINTS",
            "strategy": "grid",
            "initial_cash_points": 1_000,
            "lower_price_points": 80,
            "upper_price_points": 120,
            "grid_count": 5,
            "order_amount_points": 100,
            "candles": candles,
        },
    )
    return {
        "scenario": "grid_cross_segment_lifecycle_20000",
        "expected": {
            "trade_count": 7,
            "trade_sides": ["buy", "sell", "sell", "sell", "buy", "buy", "buy"],
            "final_value_points": 1_072,
            "segmented_backtest": True,
            "segmented_backtest_batches": 2,
        },
        "actual": {
            "trade_count": result["trade_count"],
            "trade_sides": [row["side"] for row in result["trades"]],
            "final_value_points": result["final_value_points"],
            "segmented_backtest": result["segmented_backtest"],
            "segmented_backtest_batches": result["segmented_backtest_batches"],
        },
        "match": (
            result["trade_count"] == 7
            and [row["side"] for row in result["trades"]] == ["buy", "sell", "sell", "sell", "buy", "buy", "buy"]
            and result["final_value_points"] == 1_072
            and result["segmented_backtest"] is True
            and result["segmented_backtest_batches"] == 2
        ),
    }


def route_probe(trading):
    app = Flask(__name__)
    app.testing = True

    def passthrough(fn):
        return fn

    def json_resp(payload, status=None):
        response = jsonify(payload)
        return (response, status) if status else response

    register_trading_routes(
        app,
        {
            "trading_service": trading,
            "get_current_user_ctx": lambda: actor(),
            "json_resp": json_resp,
            "require_csrf": passthrough,
            "require_csrf_safe": passthrough,
            "check_user_rate_limit": lambda *args, **kwargs: (False, {}),
            "audit": lambda *args, **kwargs: None,
        },
    )
    client = app.test_client()
    candles = candle_series(20_000, 100)
    response = client.post(
        "/api/trading/bots/backtest",
        json={
            "market_symbol": "ETH/POINTS",
            "strategy": "dca",
            "initial_cash_points": 10_000,
            "order_points": 100,
            "interval_candles": 250,
            "candles": candles,
        },
    )
    payload = response.get_json()
    return {
        "scenario": "route_payload_20000",
        "status_code": response.status_code,
        "payload_checks": {
            "ok": bool(payload.get("ok")),
            "candle_count": payload.get("candle_count"),
            "max_backtest_candles": payload.get("max_backtest_candles"),
            "max_backtest_candles_per_batch": payload.get("max_backtest_candles_per_batch"),
            "segmented_backtest": payload.get("segmented_backtest"),
            "segmented_backtest_batches": payload.get("segmented_backtest_batches"),
        },
        "match": (
            response.status_code == 200
            and payload.get("ok") is True
            and payload.get("candle_count") == 20_000
            and payload.get("max_backtest_candles") == 20_000
            and payload.get("max_backtest_candles_per_batch") == 10_000
            and payload.get("segmented_backtest") is True
            and payload.get("segmented_backtest_batches") == 2
        ),
    }


def parse_args():
    parser = argparse.ArgumentParser(description="Probe 20,000-candle segmented backtests for all four bot strategies.")
    parser.add_argument(
        "--case",
        choices=("all", "conditional", "dca", "workflow", "grid", "route", "over_limit"),
        default="all",
        help="Run one specific probe case or all cases.",
    )
    parser.add_argument(
        "--include-route",
        action="store_true",
        help="Also send one full 20,000-candle payload through /api/trading/bots/backtest.",
    )
    parser.add_argument(
        "--json-out",
        help="Optional path to write the JSON report.",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    temp_dir, _points, trading = build_temp_services()
    started = time.perf_counter()
    probe_map = {
        "conditional": conditional_probe,
        "dca": dca_probe,
        "workflow": workflow_probe,
        "grid": grid_probe,
        "route": route_probe,
        "over_limit": over_limit_probe,
    }
    if args.case == "all":
        case_names = ["conditional", "dca", "workflow", "grid", "over_limit"]
        if args.include_route:
            case_names.append("route")
    else:
        case_names = [args.case]
    cases = [probe_map[name](trading) for name in case_names]
    report = {
        "runtime_dir": str(temp_dir),
        "elapsed_ms": round((time.perf_counter() - started) * 1000, 2),
        "selected_case": args.case,
        "route_probe_included": bool(args.include_route or args.case == "route"),
        "cases": cases,
        "all_passed": all(case["match"] for case in cases),
    }
    if args.json_out:
        Path(args.json_out).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
