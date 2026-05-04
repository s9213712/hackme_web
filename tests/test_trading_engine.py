import sqlite3
import json
from datetime import datetime
from decimal import Decimal, ROUND_DOWN
from pathlib import Path

import pytest

import services.trading_engine as trading_engine_module
from services.points_chain import PointsLedgerService, ensure_points_economy_schema
from services.trading_engine import TradingEngineService, ensure_trading_schema, fee_points, notional_points


ROOT = Path(__file__).resolve().parents[1]


def _db(tmp_path):
    path = tmp_path / "trading.db"

    def get_db():
        conn = sqlite3.connect(path)
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
        "('bob', 'manager', 'active'), "
        "('root', 'super_admin', 'active')"
    )
    ensure_points_economy_schema(conn)
    ensure_trading_schema(conn)
    conn.commit()
    conn.close()
    return get_db


def _services(tmp_path):
    get_db = _db(tmp_path)
    points = PointsLedgerService(get_db=get_db, chain_secret="test-secret", backup_dir=tmp_path / "points_chain_backups")
    prices = {"BTC/POINTS": 77059, "ETH/POINTS": 5000}
    trading = TradingEngineService(get_db=get_db, points_service=points, live_price_provider=lambda symbol: prices[symbol])
    trading.test_prices = prices
    return points, trading


def _services_with_history(tmp_path, *, prices=None, candles=None):
    get_db = _db(tmp_path)
    points = PointsLedgerService(get_db=get_db, chain_secret="test-secret", backup_dir=tmp_path / "points_chain_backups")
    live_prices = {"BTC/POINTS": 77059, "ETH/POINTS": 5000}
    if prices:
        live_prices.update(prices)

    def history_provider(symbol, interval, limit):
        data = list(candles or [])
        return data[-int(limit or len(data)) :]

    trading = TradingEngineService(
        get_db=get_db,
        points_service=points,
        live_price_provider=lambda symbol: live_prices[symbol],
        historical_candles_provider=history_provider,
    )
    trading.test_prices = live_prices
    return points, trading


def _actor(user_id=1, username="alice", role="user"):
    return {"id": user_id, "username": username, "role": role}


def _depth_snapshot(trading, source, quantity_per_level, *, price=100.0):
    bids = [[price, quantity_per_level] for _ in range(10)] + [[price * 0.98, 9999]]
    asks = [[price, quantity_per_level] for _ in range(10)] + [[price * 1.02, 9999]]
    midpoint, depth_score = trading._depth_notional_score(bids, asks)
    return {
        "source": source,
        "price_points": trading._price_points_from_float(midpoint, source=source),
        "depth_score": depth_score,
    }


def _notifications(trading, user_id):
    conn = trading.get_db()
    try:
        return [
            dict(row)
            for row in conn.execute(
                "SELECT type, title, body, link FROM notifications WHERE user_id=? ORDER BY id",
                (user_id,),
            ).fetchall()
        ]
    finally:
        conn.close()


def _deplete_trial_credit(trading, user_id=1):
    dashboard = trading.user_dashboard(user_id=user_id)
    assert dashboard["funding"]["trial_credit"]
    conn = trading.get_db()
    try:
        conn.execute(
            """
            UPDATE trading_trial_credits
            SET available_points=0, locked_points=0, deployed_points=0,
                status='depleted', updated_at=datetime('now')
            WHERE user_id=?
            """,
            (int(user_id),),
        )
        conn.commit()
    finally:
        conn.close()


class _FakePriceResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        import json

        return json.dumps(self.payload).encode("utf-8")


def test_legacy_rate_unit_label_removed_from_repository_text():
    needle = "b" + "ps"
    ignored_dirs = {
        ".git", ".venv", "venv", "env", ".tox", ".eggs",
        "__pycache__", ".pytest_cache", "node_modules",
        "storage", "reports", "secure_backups", "build", "dist",
    }
    ignored_prefixes = {Path("security/reports")}
    ignored_suffixes = {".pyc", ".db", ".sqlite", ".png", ".jpg", ".jpeg", ".gif", ".webp", ".zip", ".gz"}
    offenders = []
    for path in ROOT.rglob("*"):
        if not path.is_file() or ignored_dirs & set(path.parts) or path.suffix.lower() in ignored_suffixes:
            continue
        relative = path.relative_to(ROOT)
        if any(relative == prefix or prefix in relative.parents for prefix in ignored_prefixes):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        if needle in text.lower():
            offenders.append(str(path.relative_to(ROOT)))
    assert offenders == []


def test_spot_buy_uses_trial_credit_before_points_chain_and_updates_position(tmp_path):
    points, trading = _services(tmp_path)
    points.record_transaction(
        user_id=1,
        currency_type="points",
        direction="credit",
        amount=2000,
        action_type="test_funding",
    )

    result = trading.place_order(
        actor=_actor(),
        market_symbol="ETH/POINTS",
        side="buy",
        order_type="market",
        quantity="0.1",
    )

    assert result["order"]["status"] == "filled"
    wallet = points.get_wallet(1)
    assert wallet["points_balance"] == 2000
    dashboard = trading.user_dashboard(user_id=1)
    assert dashboard["funding"]["trial_credit"]["available_points"] == 499
    assert dashboard["funding"]["trial_credit"]["deployed_points"] == 501
    assert dashboard["positions"][0]["market_symbol"] == "ETH/POINTS"
    assert dashboard["positions"][0]["quantity"] == "0.1"
    assert dashboard["futures_positions"] == []
    ledger_actions = [row["action_type"] for row in points.list_ledger(user_id=1, include_user_id=True)]
    assert "trading_spot_buy" not in ledger_actions
    report = trading.root_report()
    assert report["reserve_pool"]["balance_points"] == 10000
    assert report["funding_pool"]["available_points"] == 10000
    notes = _notifications(trading, 1)
    assert notes[-1]["type"] == "trading_order_filled"
    assert notes[-1]["title"] == "交易已成交"
    assert "ETH/POINTS 買入 0.1 已成交" in notes[-1]["body"]


def test_mixed_trial_and_real_points_buy_only_records_real_points_on_chain(tmp_path):
    points, trading = _services(tmp_path)
    points.record_transaction(
        user_id=1,
        currency_type="points",
        direction="credit",
        amount=2000,
        action_type="test_funding",
    )

    result = trading.place_order(
        actor=_actor(),
        market_symbol="ETH/POINTS",
        side="buy",
        order_type="market",
        quantity="0.25",
    )

    assert result["order"]["status"] == "filled"
    dashboard = trading.user_dashboard(user_id=1)
    fill = dashboard["fills"][0]
    assert fill["funding_mode"] == "trial_mixed"
    assert fill["notional_points"] == 1250
    assert fill["fee_points"] == 1
    assert dashboard["funding"]["trial_credit"]["available_points"] == 0
    assert dashboard["funding"]["trial_credit"]["deployed_points"] == 1000

    ledger_rows = points.list_ledger(user_id=1, include_user_id=True)
    trading_rows = [row for row in ledger_rows if row["reference_id"] == result["order"]["order_uuid"]]
    amounts_by_action = {row["action_type"]: row["amount"] for row in trading_rows}
    assert amounts_by_action == {
        "trading_freeze": 251,
        "trading_unfreeze": 251,
        "trading_spot_buy": 251,
    }
    assert points.get_wallet(1)["points_balance"] == 1749


def test_fee_points_rounds_half_up_for_integer_point_ledger():
    assert trading_engine_module.fee_points(100, 0.3) == 0
    assert trading_engine_module.fee_points(167, 0.3) == 1
    assert trading_engine_module.fee_points(334, 0.3) == 1
    assert trading_engine_module.fee_points(500, 0.3) == 2


def test_small_spot_buy_does_not_overcharge_integer_fee(tmp_path):
    _, trading = _services(tmp_path)

    result = trading.place_order(
        actor=_actor(),
        market_symbol="ETH/POINTS",
        side="buy",
        order_type="market",
        quantity="0.02",
    )

    assert result["order"]["status"] == "filled"
    assert result["order"]["fee_points"] == 0

    dashboard = trading.user_dashboard(user_id=1)
    fill = dashboard["fills"][0]
    assert fill["notional_points"] == 100
    assert fill["fee_points"] == 0
    assert dashboard["funding"]["trial_credit"]["available_points"] == 900


def test_backtest_accepts_full_year_hourly_window_under_new_limit(tmp_path):
    _, trading = _services(tmp_path)
    candles = [
        {
            "time": i,
            "time_iso": f"2024-01-01T{(i % 24):02d}:00:00+00:00",
            "open_points": 100 + (i % 5),
            "high_points": 101 + (i % 5),
            "low_points": 99 + (i % 5),
            "close_points": 100 + (i % 5),
            "price_points": 100 + (i % 5),
        }
        for i in range(8784)
    ]

    result = trading.backtest_trading_bot(
        actor=_actor(),
        payload={
            "market_symbol": "BTC/POINTS",
            "strategy": "conditional",
            "trigger_type": "price_below",
            "trigger_price_points": 0,
            "candles": candles,
        },
    )

    assert result["ok"] is True
    assert result["candle_count"] == 8784
    assert result["max_backtest_candles"] == trading_engine_module.MAX_BACKTEST_CANDLES


def test_dca_backtest_preserves_interval_across_segment_boundaries(tmp_path):
    _, trading = _services(tmp_path)
    candle_count = trading_engine_module.BACKTEST_SEGMENT_CANDLES + 5
    candles = [
        {
            "time": i,
            "time_iso": f"2024-01-01T{(i % 24):02d}:00:00+00:00",
            "open_points": 100,
            "high_points": 100,
            "low_points": 100,
            "close_points": 100,
            "price_points": 100,
        }
        for i in range(candle_count)
    ]

    result = trading.backtest_trading_bot(
        actor=_actor(),
        payload={
            "market_symbol": "BTC/POINTS",
            "strategy": "dca",
            "interval_candles": 3,
            "order_points": 1,
            "initial_cash_points": 5000,
            "candles": candles,
        },
    )

    expected_trades = ((candle_count - 1) // 3) + 1
    assert result["ok"] is True
    assert result["segmented_backtest"] is True
    assert result["segmented_backtest_batches"] == 2
    assert result["candle_count"] == candle_count
    assert result["trade_count"] == expected_trades


def test_workflow_backtest_preserves_position_across_segment_boundaries(tmp_path):
    _, trading = _services(tmp_path)
    candles = [
        {
            "time": i,
            "time_iso": f"2024-01-01T{(i % 24):02d}:00:00+00:00",
            "open_points": 200,
            "high_points": 200,
            "low_points": 200,
            "close_points": 200,
            "price_points": 200,
        }
        for i in range(trading_engine_module.BACKTEST_SEGMENT_CANDLES - 1)
    ]
    candles.extend([
        {
            "time": trading_engine_module.BACKTEST_SEGMENT_CANDLES - 1,
            "time_iso": "2024-02-20T00:00:00+00:00",
            "open_points": 90,
            "high_points": 90,
            "low_points": 90,
            "close_points": 90,
            "price_points": 90,
        },
        {
            "time": trading_engine_module.BACKTEST_SEGMENT_CANDLES,
            "time_iso": "2024-02-20T01:00:00+00:00",
            "open_points": 120,
            "high_points": 120,
            "low_points": 120,
            "close_points": 120,
            "price_points": 120,
        },
    ])
    workflow = {
        "version": "1",
        "strategy_kind": "workflow_graph",
        "start_node_id": "start",
        "nodes": [
            {"id": "start", "type": "start"},
            {"id": "buy_cond", "type": "condition", "condition": {"type": "price_below", "value": 100}},
            {"id": "no_pos", "type": "condition", "condition": {"type": "has_position", "value": False}},
            {"id": "buy_and", "type": "logic", "operator": "AND"},
            {"id": "buy_act", "type": "action", "priority": 10, "action": {"type": "buy_percent", "percent": 100, "order_type": "market"}},
            {"id": "sell_cond", "type": "condition", "condition": {"type": "price_above", "value": 110}},
            {"id": "has_pos", "type": "condition", "condition": {"type": "has_position", "value": True}},
            {"id": "sell_and", "type": "logic", "operator": "AND"},
            {"id": "sell_act", "type": "action", "priority": 20, "action": {"type": "sell_percent", "percent": 100, "order_type": "market"}},
        ],
        "edges": [
            {"id": "e1", "from": "start", "from_port": "out", "to": "buy_cond", "to_port": "in"},
            {"id": "e2", "from": "start", "from_port": "out", "to": "no_pos", "to_port": "in"},
            {"id": "e3", "from": "buy_cond", "from_port": "true", "to": "buy_and", "to_port": "in"},
            {"id": "e4", "from": "no_pos", "from_port": "true", "to": "buy_and", "to_port": "in"},
            {"id": "e5", "from": "buy_and", "from_port": "true", "to": "buy_act", "to_port": "in"},
            {"id": "e6", "from": "start", "from_port": "out", "to": "sell_cond", "to_port": "in"},
            {"id": "e7", "from": "start", "from_port": "out", "to": "has_pos", "to_port": "in"},
            {"id": "e8", "from": "sell_cond", "from_port": "true", "to": "sell_and", "to_port": "in"},
            {"id": "e9", "from": "has_pos", "from_port": "true", "to": "sell_and", "to_port": "in"},
            {"id": "e10", "from": "sell_and", "from_port": "true", "to": "sell_act", "to_port": "in"},
        ],
    }

    result = trading.backtest_trading_bot(
        actor=_actor(),
        payload={
            "market_symbol": "BTC/POINTS",
            "strategy": "workflow",
            "workflow_json": workflow,
            "initial_cash_points": 1000,
            "candles": candles,
        },
    )

    assert result["ok"] is True
    assert result["segmented_backtest"] is True
    assert result["trade_count"] == 2
    assert result["end_units"] == 0
    assert result["final_value_points"] > result["initial_cash_points"]


def test_workflow_backtest_does_not_false_trigger_bollinger_on_flat_sequence(tmp_path):
    _, trading = _services(tmp_path)
    candles = [
        {
            "time": i,
            "time_iso": f"2024-01-01T{(i % 24):02d}:00:00+00:00",
            "open_points": 100,
            "high_points": 100,
            "low_points": 100,
            "close_points": 100,
            "price_points": 100,
        }
        for i in range(30)
    ]
    workflow = {
        "version": "1",
        "strategy_kind": "workflow_graph",
        "start_node_id": "start",
        "nodes": [
            {"id": "start", "type": "start"},
            {
                "id": "bb_flat_guard",
                "type": "condition",
                "condition": {"type": "bb_position", "position": "below_lower"},
            },
            {"id": "no_pos", "type": "condition", "condition": {"type": "has_position", "value": False}},
            {"id": "buy_and", "type": "logic", "operator": "AND"},
            {"id": "buy_act", "type": "action", "priority": 10, "action": {"type": "buy_percent", "percent": 100, "order_type": "market"}},
        ],
        "edges": [
            {"id": "e1", "from": "start", "from_port": "out", "to": "bb_flat_guard", "to_port": "in"},
            {"id": "e2", "from": "start", "from_port": "out", "to": "no_pos", "to_port": "in"},
            {"id": "e3", "from": "bb_flat_guard", "from_port": "true", "to": "buy_and", "to_port": "in"},
            {"id": "e4", "from": "no_pos", "from_port": "true", "to": "buy_and", "to_port": "in"},
            {"id": "e5", "from": "buy_and", "from_port": "true", "to": "buy_act", "to_port": "in"},
        ],
    }

    result = trading.backtest_trading_bot(
        actor=_actor(),
        payload={
            "market_symbol": "BTC/POINTS",
            "strategy": "workflow",
            "workflow_json": workflow,
            "initial_cash_points": 1000,
            "candles": candles,
        },
    )

    assert result["ok"] is True
    assert result["trade_count"] == 0
    assert result["final_value_points"] == result["initial_cash_points"]


def test_backtest_skips_outlier_jump_candles_instead_of_booking_fake_profit(tmp_path):
    _, trading = _services(tmp_path)
    candles = [
        {"time_iso": "2024-01-01T00:00:00+00:00", "close_points": 100, "price_points": 100},
        {"time_iso": "2024-01-01T00:15:00+00:00", "close_points": 10, "price_points": 10},
        {"time_iso": "2024-01-01T00:30:00+00:00", "close_points": 150, "price_points": 150},
    ]

    result = trading.backtest_trading_bot(
        actor=_actor(),
        payload={
            "market_symbol": "BTC/POINTS",
            "strategy": "conditional",
            "trigger_type": "price_below",
            "trigger_price_points": 50,
            "initial_cash_points": 1000,
            "order_points": 100,
            "candles": candles,
        },
    )

    assert result["ok"] is True
    assert result["trade_count"] == 0
    assert result["outlier_skipped_count"] == 1
    assert result["final_value_points"] == result["initial_cash_points"]
    assert any("已略過跳價" in warning for warning in result["range_warnings"])


def test_bot_audit_dashboard_marks_new_bot_as_unaudited_until_trade_or_24h(tmp_path):
    _, trading = _services(tmp_path)
    created = trading.save_trading_bot(
        actor=_actor(),
        payload={
            "market_symbol": "ETH/POINTS",
            "bot_type": "dca",
            "name": "fresh dca",
            "budget_points": 100,
            "interval_hours": 24,
            "enabled": True,
            "max_runs": -1,
        },
    )

    dashboard = trading.get_bot_audit_dashboard(limit=20)
    item = next(row for row in dashboard["items"] if row["bot_uuid"] == created["bot"]["bot_uuid"])

    assert item["audit_status"] == "unaudited"
    assert item["eligible"] is False
    assert item["eligible_reason"] == "awaiting_first_trade"


def test_bot_audit_runs_green_after_first_successful_trade(tmp_path):
    _, trading = _services(tmp_path)
    created = trading.save_trading_bot(
        actor=_actor(),
        payload={
            "market_symbol": "ETH/POINTS",
            "bot_type": "dca",
            "name": "audited dca",
            "budget_points": 100,
            "interval_hours": 24,
            "enabled": True,
            "max_runs": -1,
        },
    )
    bot_uuid = created["bot"]["bot_uuid"]
    trading.run_trading_bot_once(actor=_actor(), bot_uuid=bot_uuid)

    result = trading.run_due_bot_audits(force=True)
    dashboard = trading.get_bot_audit_dashboard(limit=20)
    item = next(row for row in dashboard["items"] if row["bot_uuid"] == bot_uuid)

    assert any(row["bot_uuid"] == bot_uuid for row in result["audited"])
    assert item["audit_status"] == "green"
    assert item["eligible"] is True
    assert item["eligible_reason"] == "has_trade"


def test_bot_audit_warns_after_24_hours_without_any_trade(tmp_path):
    _, trading = _services(tmp_path)
    created = trading.save_trading_bot(
        actor=_actor(),
        payload={
            "market_symbol": "ETH/POINTS",
            "bot_type": "dca",
            "name": "idle dca",
            "budget_points": 100,
            "interval_hours": 24,
            "enabled": True,
            "max_runs": -1,
        },
    )
    bot_uuid = created["bot"]["bot_uuid"]
    conn = trading.get_db()
    try:
        conn.execute("UPDATE trading_bots SET enabled_at='2024-01-01T00:00:00' WHERE bot_uuid=?", (bot_uuid,))
        conn.commit()
    finally:
        conn.close()

    result = trading.run_due_bot_audits(force=True)
    dashboard = trading.get_bot_audit_dashboard(limit=20)
    item = next(row for row in dashboard["items"] if row["bot_uuid"] == bot_uuid)

    assert any(row["bot_uuid"] == bot_uuid for row in result["audited"])
    assert item["audit_status"] == "yellow"
    assert item["warning_count"] >= 1
    assert item["eligible_reason"] == "aged_24h"


def test_grid_bot_audit_marks_orphan_open_orders_as_red(tmp_path):
    _, trading = _services(tmp_path)
    created = trading.create_grid_bot(
        actor=_actor(),
        payload={
            "name": "grid orphan",
            "market_symbol": "ETH/POINTS",
            "upper_price_points": 120,
            "lower_price_points": 80,
            "grid_count": 5,
            "order_amount_points": 100,
        },
    )
    bot_uuid = created["bot"]["bot_uuid"]
    conn = trading.get_db()
    try:
        bot_row = conn.execute("SELECT id FROM trading_grid_bots WHERE bot_uuid=?", (bot_uuid,)).fetchone()
        conn.execute("UPDATE trading_grid_bots SET enabled_at='2024-01-01T00:00:00' WHERE id=?", (int(bot_row["id"]),))
        open_row = conn.execute(
            "SELECT * FROM trading_grid_orders WHERE grid_bot_id=? AND status='open' ORDER BY id ASC LIMIT 1",
            (int(bot_row["id"]),),
        ).fetchone()
        conn.execute("UPDATE trading_orders SET status='cancelled' WHERE order_uuid=?", (open_row["trading_order_uuid"],))
        conn.commit()
    finally:
        conn.close()

    trading.run_due_bot_audits(force=True)
    dashboard = trading.get_bot_audit_dashboard(limit=20)
    item = next(row for row in dashboard["items"] if row["bot_uuid"] == bot_uuid)

    assert item["audit_status"] == "red"
    assert item["blocker_count"] >= 1


def test_dca_backtest_matches_exact_math_at_full_20000_candle_limit(tmp_path):
    get_db = _db(tmp_path)
    points = PointsLedgerService(get_db=get_db, chain_secret="test-secret", backup_dir=tmp_path / "points_chain_backups")
    trading = TradingEngineService(get_db=get_db, points_service=points)

    candles = [
        {
            "time_iso": f"2026-01-{1 + (idx // 1440):02d}T{(idx // 60) % 24:02d}:{idx % 60:02d}:00+00:00",
            "open_points": 100,
            "high_points": 100,
            "low_points": 100,
            "close_points": 100,
        }
        for idx in range(trading_engine_module.MAX_BACKTEST_CANDLES)
    ]

    result = trading.backtest_trading_bot(
        actor=_actor(),
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
    assert len(candles) == trading_engine_module.MAX_BACKTEST_CANDLES == 20_000
    assert result["segmented_backtest"] is True
    assert result["segmented_backtest_batches"] == 2
    assert result["trade_count"] == expected_trades == 80
    assert result["cash_points"] == 2_000
    assert result["end_units"] == 80 * trading_engine_module.ASSET_SCALE
    assert result["position_value_points"] == 8_000
    assert result["final_value_points"] == 10_000
    assert result["pnl_points"] == 0


def test_conditional_backtest_matches_exact_math_at_full_20000_candle_limit(tmp_path):
    get_db = _db(tmp_path)
    points = PointsLedgerService(get_db=get_db, chain_secret="test-secret", backup_dir=tmp_path / "points_chain_backups")
    trading = TradingEngineService(get_db=get_db, points_service=points)

    candles = [
        {
            "time_iso": f"2026-01-{1 + (idx // 1440):02d}T{(idx // 60) % 24:02d}:{idx % 60:02d}:00+00:00",
            "open_points": 100 if idx == 9_999 else 200,
            "high_points": 100 if idx == 9_999 else 200,
            "low_points": 100 if idx == 9_999 else 200,
            "close_points": 100 if idx == 9_999 else 200,
        }
        for idx in range(trading_engine_module.MAX_BACKTEST_CANDLES)
    ]

    result = trading.backtest_trading_bot(
        actor=_actor(),
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

    assert result["segmented_backtest"] is True
    assert result["segmented_backtest_batches"] == 2
    assert result["trade_count"] == 1
    assert result["trades"][0]["price_points"] == 100
    assert result["trades"][0]["fee_points"] == 0
    assert result["cash_points"] == 0
    assert result["end_units"] == trading_engine_module.ASSET_SCALE
    assert result["position_value_points"] == 200
    assert result["final_value_points"] == 200
    assert result["pnl_points"] == 100


def test_grid_backtest_matches_exact_math_at_full_20000_candle_limit(tmp_path):
    get_db = _db(tmp_path)
    points = PointsLedgerService(get_db=get_db, chain_secret="test-secret", backup_dir=tmp_path / "points_chain_backups")
    trading = TradingEngineService(get_db=get_db, points_service=points)

    candles = [
        {
            "time_iso": f"2026-01-{1 + (idx // 1440):02d}T{(idx // 60) % 24:02d}:{idx % 60:02d}:00+00:00",
            "open_points": 100,
            "high_points": 100,
            "low_points": 100,
            "close_points": 100,
        }
        for idx in range(19_996)
    ] + [
        {"time_iso": "2026-01-07T22:38:00+00:00", "open_points": 100, "high_points": 100, "low_points": 100, "close_points": 100},
        {"time_iso": "2026-01-07T22:39:00+00:00", "open_points": 100, "high_points": 100, "low_points": 90, "close_points": 90},
        {"time_iso": "2026-01-07T22:40:00+00:00", "open_points": 90, "high_points": 110, "low_points": 90, "close_points": 110},
        {"time_iso": "2026-01-07T22:41:00+00:00", "open_points": 110, "high_points": 120, "low_points": 80, "close_points": 100},
    ]

    result = trading.backtest_trading_bot(
        actor=_actor(),
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

    assert len(candles) == trading_engine_module.MAX_BACKTEST_CANDLES == 20_000
    assert result["segmented_backtest"] is True
    assert result["segmented_backtest_batches"] == 2
    assert result["trade_count"] == 7
    assert [row["side"] for row in result["trades"]] == ["buy", "sell", "sell", "sell", "buy", "buy", "buy"]
    assert result["final_value_points"] == 1_073
    assert result["pnl_points"] == 73


def test_workflow_backtest_matches_exact_math_at_full_20000_candle_limit_without_legacy_indicator_hot_path(tmp_path):
    get_db = _db(tmp_path)
    points = PointsLedgerService(get_db=get_db, chain_secret="test-secret", backup_dir=tmp_path / "points_chain_backups")
    trading = TradingEngineService(get_db=get_db, points_service=points)

    candles = [
        {
            "time_iso": f"2026-01-{1 + (idx // 1440):02d}T{(idx // 60) % 24:02d}:{idx % 60:02d}:00+00:00",
            "open_points": 90 if idx == 9_999 else 120 if idx == 19_999 else 200 if idx < 9_999 else 100,
            "high_points": 90 if idx == 9_999 else 120 if idx == 19_999 else 200 if idx < 9_999 else 100,
            "low_points": 90 if idx == 9_999 else 120 if idx == 19_999 else 200 if idx < 9_999 else 100,
            "close_points": 90 if idx == 9_999 else 120 if idx == 19_999 else 200 if idx < 9_999 else 100,
        }
        for idx in range(trading_engine_module.MAX_BACKTEST_CANDLES)
    ]
    workflow = {
        "version": 1,
        "strategy_kind": "workflow",
        "branches": [
            {
                "id": "buy_dip",
                "name": "跌破買入",
                "priority": 100,
                "logic": "AND",
                "cooldown_seconds": 0,
                "max_runs": 1,
                "conditions": [{"type": "price_below", "value": 100}],
                "actions": [{"type": "buy_percent", "percent": 100, "step": 1, "order_type": "market"}],
            },
            {
                "id": "sell_rally",
                "name": "漲破賣出",
                "priority": 10,
                "logic": "AND",
                "cooldown_seconds": 0,
                "max_runs": 1,
                "conditions": [{"type": "price_above", "value": 110}, {"type": "has_position", "value": True}],
                "actions": [{"type": "close_all", "step": 1, "order_type": "market"}],
            },
        ],
    }

    def _legacy_context_should_not_run(*args, **kwargs):
        raise AssertionError("legacy workflow indicator context should not be used during 20k workflow backtest")

    trading._workflow_indicator_context = _legacy_context_should_not_run

    result = trading.backtest_trading_bot(
        actor=_actor(),
        payload={
            "market_symbol": "ETH/POINTS",
            "strategy": "workflow",
            "workflow_json": workflow,
            "initial_cash_points": 10_000,
            "order_points": 1_000,
            "candles": candles,
        },
    )

    buy_spend = 10_000
    buy_fee = fee_points(buy_spend, 0.1)
    buy_units = int((Decimal(str(buy_spend - buy_fee)) * Decimal(trading_engine_module.ASSET_SCALE) / Decimal("90")).quantize(Decimal("1"), rounding=ROUND_DOWN))
    sell_gross = notional_points(buy_units, 120)
    sell_fee = fee_points(sell_gross, 0.1)
    expected_final = sell_gross - sell_fee

    assert result["segmented_backtest"] is True
    assert result["segmented_backtest_batches"] == 2
    assert result["trade_count"] == 2
    assert result["trades"][0]["price_points"] == 90
    assert result["trades"][1]["price_points"] == 120
    assert result["trades"][0]["fee_points"] == buy_fee
    assert result["trades"][1]["fee_points"] == sell_fee
    assert result["end_units"] == 0
    assert result["final_value_points"] == expected_final


def test_trading_bot_workflow_triggers_existing_order_path(tmp_path):
    _, trading = _services(tmp_path)
    bot = trading.save_trading_bot(
        actor=_actor(),
        payload={
            "name": "ETH dip buyer",
            "market_symbol": "ETH/POINTS",
            "trigger_type": "price_below",
            "trigger_price_points": 5000,
            "side": "buy",
            "order_type": "market",
            "quantity": "0.01",
            "max_runs": 1,
            "cooldown_seconds": 0,
            "enabled": True,
        },
    )

    assert bot["bot"]["bot_uuid"]
    scanned = trading.run_trading_bots(actor=_actor(), limit=10)

    assert scanned["ok"] is True
    assert scanned["scanned"] == 1
    assert len(scanned["triggered"]) == 1
    dashboard = trading.user_dashboard(user_id=1)
    assert dashboard["bots"][0]["run_count"] == 1
    assert dashboard["orders"][0]["status"] == "filled"
    assert dashboard["bot_runs"][0]["status"] == "triggered"


def test_trading_bot_auto_scan_runs_due_bots_for_all_users(tmp_path):
    _, trading = _services(tmp_path)
    trading.save_trading_bot(
        actor=_actor(),
        payload={
            "name": "Alice ETH dip buyer",
            "market_symbol": "ETH/POINTS",
            "trigger_type": "price_below",
            "trigger_price_points": 5000,
            "side": "buy",
            "order_type": "market",
            "quantity": "0.01",
            "max_runs": 1,
            "cooldown_seconds": 0,
            "enabled": True,
        },
    )
    trading.save_trading_bot(
        actor=_actor(user_id=2, username="bob", role="manager"),
        payload={
            "name": "Bob ETH dip buyer",
            "market_symbol": "ETH/POINTS",
            "trigger_type": "price_below",
            "trigger_price_points": 5000,
            "side": "buy",
            "order_type": "market",
            "quantity": "0.01",
            "max_runs": 1,
            "cooldown_seconds": 0,
            "enabled": True,
        },
    )

    scanned = trading.run_due_trading_bots(actor={"username": "system", "role": "system"}, limit=10)

    assert scanned["ok"] is True
    assert scanned["enabled"] is True
    assert scanned["scanned"] == 2
    assert len(scanned["triggered"]) == 2
    assert trading.user_dashboard(user_id=1)["bots"][0]["run_count"] == 1
    assert trading.user_dashboard(user_id=2)["bots"][0]["run_count"] == 1


def test_trading_bot_auto_scan_respects_root_setting(tmp_path):
    _, trading = _services(tmp_path)
    trading.save_trading_bot(
        actor=_actor(),
        payload={
            "name": "Disabled auto scan bot",
            "market_symbol": "ETH/POINTS",
            "trigger_type": "price_below",
            "trigger_price_points": 5000,
            "side": "buy",
            "order_type": "market",
            "quantity": "0.01",
            "max_runs": 1,
            "cooldown_seconds": 0,
            "enabled": True,
        },
    )
    trading.update_root_settings(
        actor=_actor(user_id=3, username="root", role="super_admin"),
        settings={"bot_auto_scan_enabled": False},
    )

    scanned = trading.run_due_trading_bots(actor={"username": "system", "role": "system"}, limit=10)

    assert scanned["ok"] is True
    assert scanned["enabled"] is False
    assert scanned["reason"] == "bot_auto_scan_disabled"
    assert trading.user_dashboard(user_id=1)["bots"][0]["run_count"] == 0


def test_trading_bot_workflow_records_skipped_condition(tmp_path):
    _, trading = _services(tmp_path)
    trading.save_trading_bot(
        actor=_actor(),
        payload={
            "name": "ETH expensive buyer",
            "market_symbol": "ETH/POINTS",
            "trigger_type": "price_below",
            "trigger_price_points": 1,
            "side": "buy",
            "order_type": "market",
            "quantity": "0.01",
            "max_runs": 1,
            "cooldown_seconds": 0,
            "enabled": True,
        },
    )

    scanned = trading.run_trading_bots(actor=_actor(), limit=10)

    assert scanned["ok"] is True
    assert scanned["triggered"] == []
    assert scanned["skipped"][0]["reason"] == "condition_not_met"
    dashboard = trading.user_dashboard(user_id=1)
    assert dashboard["bots"][0]["run_count"] == 0
    assert dashboard["bot_runs"][0]["status"] == "skipped"


def test_trading_bot_failure_counts_run_and_notifies_user(tmp_path):
    _, trading = _services(tmp_path)
    trading.save_trading_bot(
        actor=_actor(),
        payload={
            "name": "oversized ETH buyer",
            "market_symbol": "ETH/POINTS",
            "trigger_type": "price_below",
            "trigger_price_points": 6000,
            "side": "sell",
            "order_type": "market",
            "quantity": "1",
            "max_runs": 1,
            "cooldown_seconds": 0,
            "enabled": True,
        },
    )

    first = trading.run_trading_bots(actor=_actor(), limit=10)
    second = trading.run_trading_bots(actor=_actor(), limit=10)

    assert first["ok"] is False
    assert len(first["failed"]) == 1
    assert second["scanned"] == 0
    dashboard = trading.user_dashboard(user_id=1)
    assert dashboard["bots"][0]["run_count"] == 1
    assert dashboard["bot_runs"][0]["status"] == "failed"
    notes = _notifications(trading, 1)
    assert notes[-1]["type"] == "trading_bot_failed"
    assert "oversized ETH buyer" in notes[-1]["body"]


def test_dca_trading_bot_converts_budget_to_market_order(tmp_path):
    _, trading = _services(tmp_path)
    bot = trading.save_trading_bot(
        actor=_actor(),
        payload={
            "bot_type": "dca",
            "name": "Daily ETH DCA",
            "market_symbol": "ETH/POINTS",
            "budget_points": 100,
            "interval_hours": 24,
            "max_runs": 1,
            "enabled": True,
        },
    )

    assert bot["bot"]["bot_type"] == "dca"
    scanned = trading.run_trading_bots(actor=_actor(), limit=10)

    assert scanned["ok"] is True
    assert len(scanned["triggered"]) == 1
    dashboard = trading.user_dashboard(user_id=1)
    assert dashboard["orders"][0]["side"] == "buy"
    assert dashboard["orders"][0]["order_type"] == "market"
    assert dashboard["bots"][0]["run_count"] == 1


def test_run_single_dca_bot_once_executes_created_bot_immediately(tmp_path):
    _, trading = _services(tmp_path)
    bot = trading.save_trading_bot(
        actor=_actor(),
        payload={
            "bot_type": "dca",
            "name": "Immediate ETH DCA",
            "market_symbol": "ETH/POINTS",
            "budget_points": 100,
            "interval_hours": 24,
            "max_runs": 2,
            "enabled": True,
        },
    )["bot"]

    result = trading.run_trading_bot_once(actor=_actor(), bot_uuid=bot["bot_uuid"])

    assert result["ok"] is True
    assert result["scanned"] == 1
    assert len(result["triggered"]) == 1
    dashboard = trading.user_dashboard(user_id=1)
    assert dashboard["orders"][0]["side"] == "buy"
    assert dashboard["bots"][0]["run_count"] == 1
    assert dashboard["bots"][0]["next_run_at"]


def test_workflow_rsi_uses_wilder_smoothing(tmp_path):
    _, trading = _services(tmp_path)
    closes = [44, 44.15, 43.9, 44.35, 44.6, 44.3, 44.8, 45.0, 44.7, 45.2, 45.4, 45.1, 45.6, 45.8, 46.0, 45.7, 46.3]
    candles = [{"close_points": value, "high_points": value + 0.2, "low_points": value - 0.2} for value in closes]
    context = trading._workflow_indicator_context(candles, len(candles) - 1)
    gains = []
    losses = []
    for index in range(1, len(closes)):
        delta = closes[index] - closes[index - 1]
        gains.append(max(delta, 0))
        losses.append(abs(min(delta, 0)))
    period = 14
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    for index in range(period, len(gains)):
        avg_gain = ((avg_gain * (period - 1)) + gains[index]) / period
        avg_loss = ((avg_loss * (period - 1)) + losses[index]) / period
    expected = 100 - (100 / (1 + (avg_gain / avg_loss)))

    assert context["rsi"] == pytest.approx(expected)
    simple_gain = sum(gains[-period:]) / period
    simple_loss = sum(losses[-period:]) / period
    simple_rsi = 100 - (100 / (1 + (simple_gain / simple_loss)))
    assert context["rsi"] != pytest.approx(simple_rsi)


def test_workflow_indicator_series_matches_legacy_context(tmp_path):
    _, trading = _services(tmp_path)
    candles = [
        {
            "close_points": 4000 + (index * 7.5) + ((index % 5) * 0.2),
            "high_points": 4001 + (index * 7.5) + ((index % 3) * 0.4),
            "low_points": 3999 + (index * 7.5) - ((index % 4) * 0.3),
        }
        for index in range(240)
    ]

    series = trading._build_workflow_indicator_series(candles)

    for index in (19, 50, 120, 220):
        legacy = trading._workflow_indicator_context(candles, index)
        built = series[index]
        for key in ("price", "ma20", "ma50", "ma200", "bb_mid", "bb_upper", "bb_lower", "bb_std", "rsi", "kd"):
            if legacy[key] is None:
                assert built[key] is None
            else:
                assert built[key] == pytest.approx(legacy[key])


def test_workflow_bot_uses_branch_priority_and_percent_action(tmp_path):
    _, trading = _services(tmp_path)
    workflow = {
        "version": 1,
        "strategy_kind": "workflow",
        "branches": [
            {
                "id": "stop",
                "name": "too low",
                "priority": 100,
                "logic": "AND",
                "conditions": [{"type": "price_below", "value": 1}],
                "actions": [{"type": "close_all", "step": 1}],
            },
            {
                "id": "entry",
                "name": "entry",
                "priority": 10,
                "logic": "AND",
                "cooldown_seconds": 0,
                "conditions": [{"type": "price_below", "value": 6000}],
                "actions": [{"type": "buy_percent", "percent": 10, "step": 1}],
            },
        ],
    }
    bot = trading.save_trading_bot(
        actor=_actor(),
        payload={
            "bot_type": "conditional",
            "name": "Workflow ETH buyer",
            "market_symbol": "ETH/POINTS",
            "side": "buy",
            "order_type": "market",
            "quantity": "0.00000001",
            "trigger_type": "always",
            "workflow_json": workflow,
            "max_runs": 2,
            "cooldown_seconds": 0,
            "enabled": True,
        },
    )

    assert bot["bot"]["workflow"]["branches"][0]["id"] == "stop"
    scanned = trading.run_trading_bots(actor=_actor(), limit=10)

    assert scanned["ok"] is True
    assert len(scanned["triggered"]) == 1
    dashboard = trading.user_dashboard(user_id=1)
    assert dashboard["bots"][0]["workflow"]["strategy_kind"] == "workflow"
    assert dashboard["orders"][0]["side"] == "buy"
    assert dashboard["orders"][0]["status"] == "filled"


def test_node_graph_bot_live_scan_uses_indicator_context_and_steps(tmp_path):
    _, trading = _services(tmp_path)
    trading.historical_candles_provider = lambda symbol, interval, limit: [
        {"close_points": 4000, "high_points": 4100, "low_points": 3900}
        for _ in range(60)
    ]
    workflow = {
        "version": 2,
        "strategy_kind": "workflow_graph",
        "start_node_id": "start",
        "nodes": [
            {"id": "start", "type": "start", "label": "Start"},
            {"id": "price", "type": "condition", "label": "價格低於", "condition": {"type": "price_below", "value": 6000}},
            {"id": "ma", "type": "condition", "label": "MA20 上方", "condition": {"type": "ma_position", "period": 20, "position": "above"}},
            {"id": "logic", "type": "logic", "label": "進場 AND", "operator": "AND", "priority": 10},
            {"id": "buy_1", "type": "action", "label": "第一段", "action": {"type": "buy_percent", "percent": 10, "step": 1}, "priority": 10},
            {"id": "buy_2", "type": "action", "label": "第二段", "action": {"type": "buy_percent", "percent": 20, "step": 2}, "priority": 10},
        ],
        "edges": [
            {"from": "start", "from_port": "out", "to": "price", "to_port": "in"},
            {"from": "start", "from_port": "out", "to": "ma", "to_port": "in"},
            {"from": "price", "from_port": "true", "to": "logic", "to_port": "in"},
            {"from": "ma", "from_port": "true", "to": "logic", "to_port": "in"},
            {"from": "logic", "from_port": "true", "to": "buy_1", "to_port": "in"},
            {"from": "logic", "from_port": "true", "to": "buy_2", "to_port": "in"},
        ],
    }
    trading.save_trading_bot(
        actor=_actor(),
        payload={
            "bot_type": "conditional",
            "name": "Graph live indicator buyer",
            "market_symbol": "ETH/POINTS",
            "side": "buy",
            "order_type": "market",
            "quantity": "0.00000001",
            "trigger_type": "always",
            "workflow_json": workflow,
            "max_runs": 2,
            "cooldown_seconds": 0,
            "enabled": True,
        },
    )

    first = trading.run_trading_bots(actor=_actor(), limit=10)
    second = trading.run_trading_bots(actor=_actor(), limit=10)

    assert first["ok"] is True
    assert second["ok"] is True
    assert len(first["triggered"]) == 1
    assert len(second["triggered"]) == 1
    dashboard = trading.user_dashboard(user_id=1)
    assert dashboard["bots"][0]["run_count"] == 2
    assert [row["status"] for row in dashboard["orders"]] == ["filled", "filled"]
    assert len(dashboard["fills"]) == 2


def test_workflow_live_scan_uses_window_low_for_stop_loss_after_previous_scan(tmp_path):
    base_ms = 1_700_000_000_000
    candles = [
        {"time_ms": base_ms, "close_points": 100.0, "high_points": 100.0, "low_points": 100.0},
        {"time_ms": base_ms + 60_000, "close_points": 110.0, "high_points": 110.0, "low_points": 94.0},
    ]
    points, trading = _services_with_history(tmp_path, prices={"ETH/POINTS": 100.0}, candles=candles)
    points.record_transaction(user_id=1, currency_type="points", direction="credit", amount=1000, action_type="test_funding")
    trading.place_order(actor=_actor(), market_symbol="ETH/POINTS", side="buy", order_type="market", quantity="1.0")
    trading.test_prices["ETH/POINTS"] = 110.0
    workflow = {
        "version": 1,
        "strategy_kind": "workflow",
        "branches": [
            {
                "id": "stop",
                "name": "stop",
                "priority": 100,
                "logic": "AND",
                "conditions": [{"type": "stop_loss_percent", "value": 5}],
                "actions": [{"type": "close_all", "step": 1}],
            }
        ],
    }
    bot = trading.save_trading_bot(
        actor=_actor(),
        payload={
            "bot_type": "conditional",
            "name": "stop loss replay",
            "market_symbol": "ETH/POINTS",
            "side": "sell",
            "order_type": "market",
            "quantity": "0.00000001",
            "trigger_type": "always",
            "workflow_json": workflow,
            "cooldown_seconds": 0,
            "max_runs": 2,
            "enabled": True,
        },
    )["bot"]
    conn = trading.get_db()
    try:
        conn.execute(
            "UPDATE trading_bots SET last_scan_at=? WHERE bot_uuid=?",
            (datetime.fromtimestamp((base_ms + 30_000) / 1000).isoformat(), bot["bot_uuid"]),
        )
        conn.commit()
    finally:
        conn.close()

    scanned = trading.run_trading_bots(actor=_actor(), limit=10)

    assert scanned["ok"] is True
    assert len(scanned["triggered"]) == 1
    dashboard = trading.user_dashboard(user_id=1)
    assert dashboard["positions"][0]["quantity_units"] == 0


def test_workflow_live_scan_does_not_false_trigger_from_pre_scan_window_break(tmp_path):
    base_ms = 1_700_000_000_000
    candles = [
        {"time_ms": base_ms + 60_000, "close_points": 110.0, "high_points": 110.0, "low_points": 94.0},
        {"time_ms": base_ms + 120_000, "close_points": 110.0, "high_points": 110.0, "low_points": 105.0},
    ]
    points, trading = _services_with_history(tmp_path, prices={"ETH/POINTS": 100.0}, candles=candles)
    points.record_transaction(user_id=1, currency_type="points", direction="credit", amount=1000, action_type="test_funding")
    trading.place_order(actor=_actor(), market_symbol="ETH/POINTS", side="buy", order_type="market", quantity="1.0")
    trading.test_prices["ETH/POINTS"] = 110.0
    workflow = {
        "version": 1,
        "strategy_kind": "workflow",
        "branches": [
            {
                "id": "stop",
                "name": "stop",
                "priority": 100,
                "logic": "AND",
                "conditions": [{"type": "stop_loss_percent", "value": 5}],
                "actions": [{"type": "close_all", "step": 1}],
            }
        ],
    }
    bot = trading.save_trading_bot(
        actor=_actor(),
        payload={
            "bot_type": "conditional",
            "name": "no false stop",
            "market_symbol": "ETH/POINTS",
            "side": "sell",
            "order_type": "market",
            "quantity": "0.00000001",
            "trigger_type": "always",
            "workflow_json": workflow,
            "cooldown_seconds": 0,
            "max_runs": 2,
            "enabled": True,
        },
    )["bot"]
    conn = trading.get_db()
    try:
        conn.execute(
            "UPDATE trading_bots SET last_scan_at=? WHERE bot_uuid=?",
            (datetime.fromtimestamp((base_ms + 120_000) / 1000).isoformat(), bot["bot_uuid"]),
        )
        conn.commit()
    finally:
        conn.close()

    scanned = trading.run_trading_bots(actor=_actor(), limit=10)

    assert scanned["ok"] is True
    assert scanned["triggered"] == []
    assert scanned["skipped"][0]["reason"] in {"workflow_not_matched", "condition_not_met"}


def test_workflow_live_scan_uses_window_high_for_take_profit(tmp_path):
    base_ms = 1_700_000_000_000
    candles = [
        {"time_ms": base_ms, "close_points": 100.0, "high_points": 100.0, "low_points": 100.0},
        {"time_ms": base_ms + 60_000, "close_points": 96.0, "high_points": 106.0, "low_points": 95.0},
    ]
    points, trading = _services_with_history(tmp_path, prices={"ETH/POINTS": 100.0}, candles=candles)
    points.record_transaction(user_id=1, currency_type="points", direction="credit", amount=1000, action_type="test_funding")
    trading.place_order(actor=_actor(), market_symbol="ETH/POINTS", side="buy", order_type="market", quantity="1.0")
    trading.test_prices["ETH/POINTS"] = 96.0
    workflow = {
        "version": 1,
        "strategy_kind": "workflow",
        "branches": [
            {
                "id": "tp",
                "name": "take profit",
                "priority": 100,
                "logic": "AND",
                "conditions": [{"type": "take_profit_percent", "value": 5}],
                "actions": [{"type": "close_all", "step": 1}],
            }
        ],
    }
    bot = trading.save_trading_bot(
        actor=_actor(),
        payload={
            "bot_type": "conditional",
            "name": "take profit replay",
            "market_symbol": "ETH/POINTS",
            "side": "sell",
            "order_type": "market",
            "quantity": "0.00000001",
            "trigger_type": "always",
            "workflow_json": workflow,
            "cooldown_seconds": 0,
            "max_runs": 2,
            "enabled": True,
        },
    )["bot"]
    conn = trading.get_db()
    try:
        conn.execute(
            "UPDATE trading_bots SET last_scan_at=? WHERE bot_uuid=?",
            (datetime.fromtimestamp((base_ms + 30_000) / 1000).isoformat(), bot["bot_uuid"]),
        )
        conn.commit()
    finally:
        conn.close()

    scanned = trading.run_trading_bots(actor=_actor(), limit=10)

    assert scanned["ok"] is True
    assert len(scanned["triggered"]) == 1


def test_trading_bot_failed_scan_does_not_advance_last_scan_at_on_live_price_error(tmp_path):
    get_db = _db(tmp_path)
    points = PointsLedgerService(get_db=get_db, chain_secret="test-secret", backup_dir=tmp_path / "points_chain_backups")

    def _fail_live_price(symbol):
        raise ValueError("live price down")

    trading = TradingEngineService(
        get_db=get_db,
        points_service=points,
        live_price_provider=_fail_live_price,
        historical_candles_provider=lambda symbol, interval, limit: [],
    )
    trading.update_root_settings(
        actor=_actor(3, "root", "super_admin"),
        settings={"max_price_staleness_seconds": 0},
        markets=[],
    )
    trading.save_trading_bot(
        actor=_actor(),
        payload={
            "name": "price failure bot",
            "market_symbol": "ETH/POINTS",
            "trigger_type": "always",
            "side": "buy",
            "order_type": "market",
            "quantity": "0.01",
            "max_runs": 2,
            "cooldown_seconds": 0,
            "enabled": True,
        },
    )

    result = trading.run_trading_bots(actor=_actor(), limit=10)

    conn = trading.get_db()
    try:
        row = conn.execute("SELECT last_scan_at, last_error FROM trading_bots WHERE user_id=1 LIMIT 1").fetchone()
    finally:
        conn.close()

    assert result["ok"] is False
    assert result["failed"]
    assert row["last_scan_at"] in (None, "")
    assert "live price down" in str(row["last_error"] or "")


def test_trading_bot_failed_scan_does_not_advance_last_scan_at_on_candle_fetch_error(tmp_path):
    get_db = _db(tmp_path)
    points = PointsLedgerService(get_db=get_db, chain_secret="test-secret", backup_dir=tmp_path / "points_chain_backups")

    def _history_provider(symbol, interval, limit):
        raise ValueError("history fetch failed")

    trading = TradingEngineService(
        get_db=get_db,
        points_service=points,
        live_price_provider=lambda symbol: 100.0,
        historical_candles_provider=_history_provider,
    )
    workflow = {
        "version": 1,
        "strategy_kind": "workflow",
        "branches": [
            {
                "id": "entry",
                "name": "entry",
                "priority": 10,
                "logic": "AND",
                "conditions": [{"type": "price_below", "value": 200}],
                "actions": [{"type": "buy_percent", "percent": 10, "step": 1}],
            }
        ],
    }
    trading.save_trading_bot(
        actor=_actor(),
        payload={
            "bot_type": "conditional",
            "name": "history failure bot",
            "market_symbol": "ETH/POINTS",
            "side": "buy",
            "order_type": "market",
            "quantity": "0.00000001",
            "trigger_type": "always",
            "workflow_json": workflow,
            "max_runs": 2,
            "cooldown_seconds": 0,
            "enabled": True,
        },
    )

    result = trading.run_trading_bots(actor=_actor(), limit=10)

    conn = trading.get_db()
    try:
        row = conn.execute("SELECT last_scan_at, last_error FROM trading_bots WHERE user_id=1 LIMIT 1").fetchone()
    finally:
        conn.close()

    assert result["ok"] is False
    assert result["failed"]
    assert row["last_scan_at"] in (None, "")
    assert "history fetch failed" in str(row["last_error"] or "")


def test_workflow_backtest_can_sell_without_mutating_orders(tmp_path):
    _, trading = _services(tmp_path)
    result = trading.backtest_trading_bot(
        actor=_actor(),
        payload={
            "market_symbol": "ETH/POINTS",
            "strategy": "workflow",
            "initial_cash_points": 1000,
            "workflow_json": {
                "version": 1,
                "branches": [
                    {
                        "id": "entry",
                        "name": "buy",
                        "priority": 10,
                        "logic": "AND",
                        "conditions": [{"type": "price_below", "value": 5000}],
                        "actions": [{"type": "buy_percent", "percent": 50, "step": 1}],
                    },
                    {
                        "id": "exit",
                        "name": "sell",
                        "priority": 20,
                        "logic": "AND",
                        "conditions": [{"type": "has_position", "value": True}, {"type": "price_above", "value": 5200}],
                        "actions": [{"type": "sell_percent", "percent": 100, "step": 1}],
                    },
                ],
            },
            "candles": [
                {"time": 1, "close_points": 4900},
                {"time": 2, "close_points": 5300},
            ],
        },
    )

    assert result["ok"] is True
    assert [row["side"] for row in result["trades"]] == ["buy", "sell"]
    dashboard = trading.user_dashboard(user_id=1)
    assert dashboard["orders"] == []
    assert dashboard["fills"] == []


def test_workflow_graph_backtest_supports_nested_logic_priority_and_steps(tmp_path):
    _, trading = _services(tmp_path)
    workflow = {
        "version": 2,
        "strategy_kind": "workflow_graph",
        "start_node_id": "start",
        "nodes": [
            {"id": "start", "type": "start", "label": "Start"},
                {"id": "entry_price", "type": "condition", "label": "Nested AND/OR", "condition": {"AND": [{"type": "price_below", "value": 5000}, {"OR": [{"type": "always"}, {"type": "rsi_below", "value": 60}]}]}},
                {"id": "entry_logic", "type": "logic", "label": "巢狀進場", "operator": "AND", "priority": 10},
            {"id": "buy_1", "type": "action", "label": "第一段買入", "action": {"type": "buy_percent", "percent": 40, "step": 1}, "priority": 10},
            {"id": "buy_2", "type": "action", "label": "第二段買入", "action": {"type": "buy_percent", "percent": 40, "step": 2}, "priority": 10},
            {"id": "stop", "type": "condition", "label": "強制止損", "condition": {"type": "price_below", "value": 3000}},
            {"id": "close", "type": "action", "label": "全部平倉", "action": {"type": "close_all", "step": 1}, "priority": 100},
        ],
        "edges": [
            {"from": "start", "from_port": "out", "to": "entry_price", "to_port": "in"},
            {"from": "entry_price", "from_port": "true", "to": "entry_logic", "to_port": "in"},
            {"from": "entry_logic", "from_port": "true", "to": "buy_1", "to_port": "in"},
            {"from": "entry_logic", "from_port": "true", "to": "buy_2", "to_port": "in"},
            {"from": "start", "from_port": "out", "to": "stop", "to_port": "in"},
            {"from": "stop", "from_port": "true", "to": "close", "to_port": "in"},
        ],
    }
    result = trading.backtest_trading_bot(
        actor=_actor(),
        payload={
            "market_symbol": "ETH/POINTS",
            "strategy": "workflow",
            "initial_cash_points": 1000,
            "workflow_json": workflow,
            "candles": [
                {"time": 1, "close_points": 4900},
                {"time": 2, "close_points": 4800},
                {"time": 3, "close_points": 2900},
            ],
        },
    )

    assert result["ok"] is True
    assert [row["side"] for row in result["trades"]] == ["buy", "buy", "sell"]
    assert result["trade_count"] == 3
    assert result["max_drawdown_percent"] >= 0
    assert len(result["equity_curve"]) >= 3


def test_backtest_trading_bot_does_not_create_orders(tmp_path):
    _, trading = _services(tmp_path)
    result = trading.backtest_trading_bot(
        actor=_actor(),
        payload={
            "market_symbol": "ETH/POINTS",
            "strategy": "dca",
            "initial_cash_points": 1000,
            "order_points": 100,
            "interval_candles": 1,
            "candles": [
                {"time": 1, "close_points": 5000},
                {"time": 2, "close_points": 4000},
                {"time": 3, "close_points": 4500},
            ],
        },
    )

    assert result["ok"] is True
    assert result["trade_count"] == 3
    assert result["final_value_points"] > 0
    dashboard = trading.user_dashboard(user_id=1)
    assert dashboard["orders"] == []
    assert dashboard["fills"] == []


def test_dca_backtest_reports_metrics_and_equity_curve(tmp_path):
    _, trading = _services(tmp_path)
    result = trading.backtest_trading_bot(
        actor=_actor(),
        payload={
            "market_symbol": "ETH/POINTS",
            "strategy": "dca",
            "bot_config": {"order_points": 100, "interval_candles": 2},
            "initial_cash_points": 1000,
            "candles": [
                {"time": "2026-01-01T00:00:00+00:00", "close_points": 5000},
                {"time": "2026-01-01T00:15:00+00:00", "close_points": 5100},
                {"time": "2026-01-01T00:30:00+00:00", "close_points": 5200},
                {"time": "2026-01-01T00:45:00+00:00", "close_points": 5300},
            ],
        },
    )

    assert result["ok"] is True
    assert result["strategy"] == "dca"
    assert result["trade_count"] == 2
    assert len(result["equity_curve"]) == 4
    assert "return_percent" in result
    assert "win_rate_percent" in result
    assert result["candle_count"] == 4
    assert result["data_source"] == "provided_candles"
    assert result["first_candle_time"] == "2026-01-01T00:00:00+00:00"
    assert result["last_candle_time"] == "2026-01-01T00:45:00+00:00"


def test_grid_backtest_matches_live_grid_order_lifecycle(tmp_path):
    _, trading = _services(tmp_path)
    result = trading.backtest_trading_bot(
        actor=_actor(),
        payload={
            "market_symbol": "ETH/POINTS",
            "strategy": "grid",
            "initial_cash_points": 1000,
            "lower_price_points": 80,
            "upper_price_points": 120,
            "grid_count": 5,
            "order_amount_points": 100,
            "candles": [
                {"time": 1, "open_points": 100, "high_points": 100, "low_points": 100, "close_points": 100},
                {"time": 2, "open_points": 100, "high_points": 100, "low_points": 90, "close_points": 90},
                {"time": 3, "open_points": 90, "high_points": 110, "low_points": 90, "close_points": 110},
                {"time": 4, "open_points": 110, "high_points": 120, "low_points": 80, "close_points": 100},
            ],
        },
    )

    assert result["ok"] is True
    assert result["strategy"] == "grid"
    assert result["trade_count"] == 7
    assert result["final_value_points"] == 1073
    assert result["trades"][0]["index"] == 1
    assert [row["side"] for row in result["trades"]] == ["buy", "sell", "sell", "sell", "buy", "buy", "buy"]
    assert all(not (row["index"] == 0 and row["price_points"] == 100) for row in result["trades"])
    assert len(result["equity_curve"]) == 4


def test_grid_bot_scans_and_fills_when_price_crosses_level_in_cfd_mode(tmp_path):
    points, trading = _services(tmp_path)
    root = _actor(3, "root", "super_admin")
    points.record_transaction(
        user_id=1,
        currency_type="points",
        direction="credit",
        amount=5000,
        action_type="test_funding",
    )
    trading.test_prices["ETH/POINTS"] = 100
    trading.update_market(actor=root, symbol="ETH/POINTS", manual_price_points=100, confirm_jump=True)
    trading.place_order(
        actor=_actor(),
        market_symbol="ETH/POINTS",
        side="buy",
        order_type="market",
        quantity="2.0",
    )
    created = trading.create_grid_bot(
        actor=_actor(),
        payload={
            "name": "CFD grid",
            "market_symbol": "ETH/POINTS",
            "lower_price_points": 80,
            "upper_price_points": 120,
            "grid_count": 5,
            "order_amount_points": 100,
        },
    )

    assert created["ok"] is True
    trading.test_prices["ETH/POINTS"] = 85
    trading.update_market(actor=root, symbol="ETH/POINTS", manual_price_points=85, confirm_jump=True)
    scanned = trading.scan_grid_bots(actor=_actor())

    assert scanned["ok"] is True
    assert scanned["results"][0]["fills_processed"] == [
        {"level_index": 1, "side": "buy", "price_points": 90}
    ]
    assert scanned["results"][0]["counter_orders_placed"] == [
        {"level_index": 2, "side": "sell", "price_points": 100}
    ]

    bots = trading.list_grid_bots(actor=_actor())["bots"]
    bot = next(row for row in bots if row["bot_uuid"] == created["bot"]["bot_uuid"])
    level_90 = next(row for row in bot["orders"] if row["level_index"] == 1)
    level_100 = next(row for row in bot["orders"] if row["level_index"] == 2 and row["side"] == "sell")
    assert level_90["status"] == "filled"
    assert level_100["status"] == "open"

    dashboard = trading.user_dashboard(user_id=1)
    grid_fill = next(fill for fill in dashboard["fills"] if fill.get("bot_name") == "CFD grid")
    assert grid_fill["order_uuid"] == level_90["trading_order_uuid"]
    assert grid_fill["price_points"] == 90
    assert trading.verify_state()["ok"] is True


def test_grid_bot_scan_window_low_can_fill_buy_limit(tmp_path):
    candles = [
        {"time_ms": 1_700_000_000_000, "close_points": 100.0, "high_points": 100.0, "low_points": 90.0},
    ]
    points, trading = _services_with_history(tmp_path, prices={"ETH/POINTS": 100.0}, candles=candles)
    points.record_transaction(user_id=1, currency_type="points", direction="credit", amount=5000, action_type="test_funding")
    created = trading.create_grid_bot(
        actor=_actor(),
        payload={
            "name": "grid window buy",
            "market_symbol": "ETH/POINTS",
            "lower_price_points": 80,
            "upper_price_points": 120,
            "grid_count": 5,
            "order_amount_points": 100,
        },
    )

    scanned = trading.scan_grid_bots(actor=_actor())

    assert scanned["ok"] is True
    assert scanned["results"][0]["scan_window_low_points"] == pytest.approx(90.0)
    assert scanned["results"][0]["fills_processed"] == [{"level_index": 1, "side": "buy", "price_points": 90}]
    assert scanned["results"][0]["counter_orders_placed"] == [{"level_index": 2, "side": "sell", "price_points": 100}]
    assert created["ok"] is True


def test_grid_bot_scan_window_high_can_fill_sell_limit(tmp_path):
    candles = [
        {"time_ms": 1_700_000_000_000, "close_points": 100.0, "high_points": 110.0, "low_points": 100.0},
    ]
    points, trading = _services_with_history(tmp_path, prices={"ETH/POINTS": 100.0}, candles=candles)
    points.record_transaction(user_id=1, currency_type="points", direction="credit", amount=5000, action_type="test_funding")
    trading.place_order(actor=_actor(), market_symbol="ETH/POINTS", side="buy", order_type="market", quantity="2.0")
    trading.create_grid_bot(
        actor=_actor(),
        payload={
            "name": "grid window sell",
            "market_symbol": "ETH/POINTS",
            "lower_price_points": 80,
            "upper_price_points": 120,
            "grid_count": 5,
            "order_amount_points": 100,
        },
    )

    scanned = trading.scan_grid_bots(actor=_actor())

    assert scanned["ok"] is True
    assert scanned["results"][0]["scan_window_high_points"] == pytest.approx(110.0)
    assert scanned["results"][0]["fills_processed"] == [{"level_index": 3, "side": "sell", "price_points": 110}]
    assert scanned["results"][0]["counter_orders_placed"] == [{"level_index": 2, "side": "buy", "price_points": 100}]


def test_increase_trading_bot_max_runs_updates_limit(tmp_path):
    _, trading = _services(tmp_path)
    created = trading.save_trading_bot(
        actor=_actor(),
        payload={
            "name": "runs bot",
            "market_symbol": "ETH/POINTS",
            "trigger_type": "always",
            "side": "buy",
            "order_type": "market",
            "quantity": "0.01",
            "max_runs": 1,
            "cooldown_seconds": 0,
            "enabled": True,
        },
    )
    bot_uuid = created["bot"]["bot_uuid"]

    updated = trading.increase_trading_bot_max_runs(actor=_actor(), bot_uuid=bot_uuid, delta=3)

    assert updated["ok"] is True
    assert updated["delta"] == 3
    assert updated["bot"]["max_runs"] == 4


def test_dca_bot_accepts_unlimited_max_runs_and_can_continue_running(tmp_path):
    _, trading = _services(tmp_path)
    created = trading.save_trading_bot(
        actor=_actor(),
        payload={
            "bot_type": "dca",
            "name": "unlimited dca",
            "market_symbol": "ETH/POINTS",
            "budget_points": 100,
            "interval_hours": 24,
            "max_runs": -1,
            "enabled": True,
        },
    )
    bot_uuid = created["bot"]["bot_uuid"]

    assert created["bot"]["max_runs"] == -1

    first = trading.run_trading_bots(actor=_actor(), limit=10)
    assert first["ok"] is True
    assert len(first["triggered"]) == 1

    conn = trading.get_db()
    try:
        conn.execute("UPDATE trading_bots SET last_run_at='2000-01-01T00:00:00' WHERE bot_uuid=?", (bot_uuid,))
        conn.commit()
    finally:
        conn.close()

    second = trading.run_trading_bots(actor=_actor(), limit=10)
    assert second["ok"] is True
    assert len(second["triggered"]) == 1

    dashboard = trading.user_dashboard(user_id=1)
    bot = next(row for row in dashboard["bots"] if row["bot_uuid"] == bot_uuid)
    assert bot["max_runs"] == -1
    assert bot["run_count"] == 2
    assert bot["can_run"] is True


def test_increase_trading_bot_max_runs_is_noop_for_unlimited_dca(tmp_path):
    _, trading = _services(tmp_path)
    created = trading.save_trading_bot(
        actor=_actor(),
        payload={
            "bot_type": "dca",
            "name": "unlimited dca",
            "market_symbol": "ETH/POINTS",
            "budget_points": 100,
            "interval_hours": 24,
            "max_runs": -1,
            "enabled": True,
        },
    )

    updated = trading.increase_trading_bot_max_runs(actor=_actor(), bot_uuid=created["bot"]["bot_uuid"], delta=3)

    assert updated["ok"] is True
    assert updated["delta"] == 0
    assert updated["unlimited"] is True
    assert updated["bot"]["max_runs"] == -1


def test_workflow_backtest_supports_take_profit_and_stop_loss_percent(tmp_path):
    _, trading = _services(tmp_path)
    workflow = {
        "version": 2,
        "strategy_kind": "workflow_graph",
        "start_node_id": "start",
        "nodes": [
            {"id": "start", "type": "start", "label": "Start"},
            {"id": "entry", "type": "condition", "label": "entry", "condition": {"type": "price_below", "value": 100}},
            {"id": "buy", "type": "action", "label": "buy", "action": {"type": "buy_percent", "percent": 50, "step": 1}},
            {"id": "profit", "type": "condition", "label": "take profit", "condition": {"type": "take_profit_percent", "value": 10}},
            {"id": "sell", "type": "action", "label": "sell half", "priority": 50, "action": {"type": "sell_percent", "percent": 50, "step": 1}},
            {"id": "loss", "type": "condition", "label": "stop loss", "condition": {"type": "stop_loss_percent", "value": 5}},
            {"id": "close", "type": "action", "label": "close", "priority": 100, "action": {"type": "close_all", "step": 1}},
        ],
        "edges": [
            {"from": "start", "from_port": "out", "to": "entry", "to_port": "in"},
            {"from": "entry", "from_port": "true", "to": "buy", "to_port": "in"},
            {"from": "start", "from_port": "out", "to": "profit", "to_port": "in"},
            {"from": "profit", "from_port": "true", "to": "sell", "to_port": "in"},
            {"from": "start", "from_port": "out", "to": "loss", "to_port": "in"},
            {"from": "loss", "from_port": "true", "to": "close", "to_port": "in"},
        ],
    }

    result = trading.backtest_trading_bot(
        actor=_actor(),
        payload={
            "market_symbol": "ETH/POINTS",
            "strategy": "workflow",
            "initial_cash_points": 1000,
            "workflow_json": workflow,
            "candles": [
                {"time": 1, "close_points": 90},
                {"time": 2, "close_points": 110},
                {"time": 3, "close_points": 80},
            ],
        },
    )

    assert result["ok"] is True
    assert [row["side"] for row in result["trades"]] == ["buy", "sell", "sell"]
    assert result["trade_count"] == 3


def test_backtest_trading_bot_rejects_excessive_candle_count(tmp_path):
    _, trading = _services(tmp_path)

    with pytest.raises(ValueError, match="candles length"):
        trading.backtest_trading_bot(
            actor=_actor(),
            payload={
                "market_symbol": "ETH/POINTS",
                "strategy": "dca",
                "candles": [
                    {"time": index, "close_points": 5000}
                    for index in range(trading_engine_module.MAX_BACKTEST_CANDLES + 1)
                ],
            },
        )


def test_insufficient_trading_balance_creates_notification(tmp_path):
    _, trading = _services(tmp_path)

    with pytest.raises(ValueError, match="交易資金不足"):
        trading.place_order(
            actor=_actor(),
            market_symbol="ETH/POINTS",
            side="buy",
            order_type="market",
            quantity="0.3",
        )

    notes = _notifications(trading, 1)
    assert notes[-1]["type"] == "trading_balance_insufficient"
    assert notes[-1]["title"] == "交易未成立：餘額不足"
    assert "ETH/POINTS buy market 數量 0.3 未成立" in notes[-1]["body"]
    assert "需要" in notes[-1]["body"]
    assert "目前可用" in notes[-1]["body"]


def test_emergency_market_close_sells_all_with_double_fee(tmp_path):
    points, trading = _services(tmp_path)
    points.record_transaction(user_id=1, currency_type="points", direction="credit", amount=2000, action_type="test_funding")
    trading.place_order(
        actor=_actor(),
        market_symbol="ETH/POINTS",
        side="buy",
        order_type="market",
        quantity="0.1",
    )

    close = trading.place_order(
        actor=_actor(),
        market_symbol="ETH/POINTS",
        side="sell",
        order_type="market",
        quantity="0.1",
        emergency_close=True,
    )

    assert close["order"]["status"] == "filled"
    assert close["order"]["reason"] == "EMERGENCY_MARKET_CLOSE"
    assert close["order"]["fee_points"] == 1
    dashboard = trading.user_dashboard(user_id=1)
    assert dashboard["positions"][0]["quantity"] == "0"
    assert dashboard["fills"][0]["fee_points"] == 1
    assert points.get_wallet(1)["points_balance"] == 2000
    assert dashboard["funding"]["trial_credit"]["available_points"] == 998
    assert dashboard["funding"]["trial_credit"]["deployed_points"] == 0
    with pytest.raises(ValueError, match="emergency close only supports market sell"):
        trading.place_order(
            actor=_actor(),
            market_symbol="ETH/POINTS",
            side="sell",
            order_type="limit",
            quantity="0.1",
            limit_price_points=5000,
            emergency_close=True,
        )


def test_trial_credit_expiry_reclaims_principal_but_keeps_profit(tmp_path):
    points, trading = _services(tmp_path)
    root = _actor(3, "root", "super_admin")
    trading.update_root_settings(actor=root, settings={"price_source": "manual_root"}, markets=[])
    trading.update_market(actor=root, symbol="ETH/POINTS", manual_price_points=5000, confirm_jump=True)
    trading.place_order(actor=_actor(), market_symbol="ETH/POINTS", side="buy", order_type="market", quantity="0.1")

    trading.update_market(actor=root, symbol="ETH/POINTS", manual_price_points=6000, confirm_jump=True)
    conn = trading.get_db()
    conn.execute("UPDATE trading_trial_credits SET expires_at='2000-01-01T00:00:00' WHERE user_id=1")
    conn.commit()
    conn.close()

    dashboard = trading.user_dashboard(user_id=1)

    assert dashboard["funding"]["trial_credit"]["status"] == "expired"
    assert dashboard["funding"]["trial_credit"]["available_points"] == 0
    assert dashboard["funding"]["trial_credit"]["deployed_points"] == 0
    assert dashboard["positions"][0]["quantity"] == "0"
    assert points.get_wallet(1)["points_balance"] == 98
    report = trading.root_report()
    audit_types = [row["event_type"] for row in report["audit_events"]]
    assert "TRADING_TRIAL_CREDIT_FORCED_SELL" in audit_types
    assert "TRADING_TRIAL_CREDIT_RECLAIMED" in audit_types


def test_trial_credit_expiry_cancels_open_sell_orders_before_reclaim(tmp_path):
    points, trading = _services(tmp_path)
    root = _actor(3, "root", "super_admin")
    trading.update_root_settings(actor=root, settings={"price_source": "manual_root"}, markets=[])
    trading.update_market(actor=root, symbol="ETH/POINTS", manual_price_points=5000, confirm_jump=True)
    trading.place_order(actor=_actor(), market_symbol="ETH/POINTS", side="buy", order_type="market", quantity="0.1")
    sell = trading.place_order(
        actor=_actor(),
        market_symbol="ETH/POINTS",
        side="sell",
        order_type="limit",
        quantity="0.1",
        limit_price_points=9000,
    )["order"]
    assert sell["status"] == "open"
    assert trading.user_dashboard(user_id=1)["positions"][0]["locked_quantity_units"] == 10000000

    conn = trading.get_db()
    conn.execute("UPDATE trading_trial_credits SET expires_at='2000-01-01T00:00:00' WHERE user_id=1")
    conn.commit()
    conn.close()

    dashboard = trading.user_dashboard(user_id=1)

    assert dashboard["funding"]["trial_credit"]["status"] == "expired"
    assert dashboard["funding"]["trial_credit"]["available_points"] == 0
    assert dashboard["funding"]["trial_credit"]["deployed_points"] == 0
    assert dashboard["positions"][0]["quantity"] == "0"
    orders = {row["order_uuid"]: row for row in dashboard["orders"]}
    assert orders[sell["order_uuid"]]["status"] == "cancelled"
    audit_types = [row["event_type"] for row in trading.root_report()["audit_events"]]
    assert "TRADING_TRIAL_CREDIT_SELL_ORDER_CANCELLED" in audit_types
    assert "TRADING_TRIAL_CREDIT_FORCED_SELL" in audit_types
    assert trading.verify_state()["ok"] is True


def test_spot_dashboard_reports_backend_pnl_and_fees(tmp_path):
    points, trading = _services(tmp_path)
    root = _actor(3, "root", "super_admin")
    points.record_transaction(user_id=1, currency_type="points", direction="credit", amount=2000, action_type="test_funding")
    trading.update_root_settings(actor=root, settings={"price_source": "manual_root"}, markets=[])
    trading.update_market(actor=root, symbol="ETH/POINTS", manual_price_points=5000, confirm_jump=True)

    trading.place_order(actor=_actor(), market_symbol="ETH/POINTS", side="buy", order_type="market", quantity="0.1")
    trading.update_market(actor=root, symbol="ETH/POINTS", manual_price_points=6000, confirm_jump=True)
    dashboard_after_buy = trading.user_dashboard(user_id=1)
    position = dashboard_after_buy["positions"][0]
    assert position["quantity"] == "0.1"
    assert position["gross_cost_points"] == 500
    assert position["current_value_points"] == 600
    assert position["estimated_buy_fee_points"] == 1
    assert position["estimated_exit_fee_points"] == 1
    assert position["cost_basis_points"] == 502
    assert position["unrealized_pnl_points"] == 98
    assert dashboard_after_buy["spot_summary"]["unrealized_pnl_points"] == 98

    trading.place_order(actor=_actor(), market_symbol="ETH/POINTS", side="sell", order_type="market", quantity="0.04")

    dashboard_after_sell = trading.user_dashboard(user_id=1)
    position_after_sell = dashboard_after_sell["positions"][0]
    assert position_after_sell["quantity"] == "0.06"
    assert position_after_sell["gross_cost_points"] == 300
    assert position_after_sell["current_value_points"] == 360
    assert position_after_sell["estimated_buy_fee_points"] == 0
    assert position_after_sell["estimated_exit_fee_points"] == 0
    assert position_after_sell["cost_basis_points"] == 300
    assert position_after_sell["unrealized_pnl_points"] == 60
    assert position_after_sell["realized_pnl_points"] == 40
    assert position_after_sell["total_fee_points"] == 1
    assert dashboard_after_sell["spot_summary"]["realized_pnl_points"] == 40
    assert dashboard_after_sell["fills"][0]["realized_pnl_points"] == 40
    assert trading.verify_state()["ok"] is True


def test_market_order_uses_live_price_instead_of_stale_manual_price(tmp_path):
    points, trading = _services(tmp_path)
    points.record_transaction(user_id=1, currency_type="points", direction="credit", amount=500, action_type="test_funding")

    result = trading.place_order(
        actor=_actor(),
        market_symbol="BTC/POINTS",
        side="buy",
        order_type="market",
        quantity="0.001",
    )

    assert result["order"]["status"] == "filled"
    assert result["order"]["execution_price_points"] == 77059
    fills = trading.user_dashboard(user_id=1)["fills"]
    assert fills[0]["price_points"] == 77059
    assert points.get_wallet(1)["points_balance"] == 500


def test_live_price_failure_uses_recent_last_good_price(tmp_path):
    points, trading = _services(tmp_path)
    points.record_transaction(user_id=1, currency_type="points", direction="credit", amount=2000, action_type="test_funding")

    first = trading.place_order(
        actor=_actor(),
        market_symbol="ETH/POINTS",
        side="buy",
        order_type="market",
        quantity="0.01",
    )
    assert first["order"]["execution_price_points"] == 5000

    def fail_price(symbol):
        raise RuntimeError("price feed down")

    trading.live_price_provider = fail_price
    second = trading.place_order(
        actor=_actor(),
        market_symbol="ETH/POINTS",
        side="buy",
        order_type="market",
        quantity="0.01",
    )

    assert second["order"]["execution_price_points"] == 5000
    assert trading.verify_state()["ok"] is True


def test_live_price_provider_falls_back_to_coinbase_when_binance_is_down(tmp_path, monkeypatch):
    get_db = _db(tmp_path)
    points = PointsLedgerService(get_db=get_db, chain_secret="test-secret", backup_dir=tmp_path / "points_chain_backups")
    trading = TradingEngineService(get_db=get_db, points_service=points)
    points.record_transaction(user_id=1, currency_type="points", direction="credit", amount=2000, action_type="test_funding")
    urls = []

    def fake_urlopen(request, timeout=0):
        urls.append(request.full_url)
        if "api.binance.com" in request.full_url:
            raise OSError("binance down")
        if "api.exchange.coinbase.com" in request.full_url:
            return _FakePriceResponse({"price": "5100"})
        raise AssertionError(f"unexpected fallback URL: {request.full_url}")

    monkeypatch.setattr(trading_engine_module, "urlopen", fake_urlopen)

    result = trading.place_order(
        actor=_actor(),
        market_symbol="ETH/POINTS",
        side="buy",
        order_type="market",
        quantity="0.01",
    )

    assert result["order"]["status"] == "filled"
    assert result["order"]["execution_price_points"] == 5100
    market = trading.list_markets()[1]
    assert market["symbol"] == "ETH/POINTS"
    assert market["price_source"] == "coinbase_exchange"
    assert any("api.binance.com" in url for url in urls)
    assert any("api.exchange.coinbase.com/products/ETH-USD/ticker" in url for url in urls)


def test_live_price_provider_walks_public_fallback_chain_to_bitstamp(tmp_path, monkeypatch):
    get_db = _db(tmp_path)
    points = PointsLedgerService(get_db=get_db, chain_secret="test-secret", backup_dir=tmp_path / "points_chain_backups")
    trading = TradingEngineService(get_db=get_db, points_service=points)
    points.record_transaction(user_id=1, currency_type="points", direction="credit", amount=2000, action_type="test_funding")
    urls = []

    def fake_urlopen(request, timeout=0):
        urls.append(request.full_url)
        if "bitstamp.net" in request.full_url:
            return _FakePriceResponse({"last": "5100"})
        raise OSError("provider unavailable")

    monkeypatch.setattr(trading_engine_module, "urlopen", fake_urlopen)

    result = trading.place_order(
        actor=_actor(),
        market_symbol="ETH/POINTS",
        side="buy",
        order_type="market",
        quantity="0.01",
    )

    assert result["order"]["status"] == "filled"
    assert result["order"]["execution_price_points"] == 5100
    market = trading.list_markets()[1]
    assert market["price_source"] == "bitstamp_public_api"
    expected_hosts = (
        "api.binance.com",
        "okx.com",
        "api.exchange.coinbase.com",
        "api.kraken.com",
        "api.gemini.com",
        "bitstamp.net",
    )
    seen_hosts = [host for host in expected_hosts if any(host in url for url in urls)]
    assert seen_hosts == list(expected_hosts)


def test_live_price_fusion_auto_depth_weights_surviving_exchanges(tmp_path, monkeypatch):
    get_db = _db(tmp_path)
    points = PointsLedgerService(get_db=get_db, chain_secret="test-secret", backup_dir=tmp_path / "points_chain_backups")
    trading = TradingEngineService(get_db=get_db, points_service=points)
    root = _actor(3, "root", "super_admin")
    trading.update_root_settings(actor=root, settings={"price_source": "fused_weighted", "price_fusion_mode": "auto_depth"}, markets=[])

    def boom(_market_symbol):
        raise OSError("provider unavailable")

    monkeypatch.setattr(trading, "_fetch_binance_orderbook_snapshot", lambda _symbol: {"source": "binance_public_api", "price_points": 100, "depth_score": 1.0})
    monkeypatch.setattr(trading, "_fetch_okx_orderbook_snapshot", lambda _symbol: {"source": "okx_public_api", "price_points": 200, "depth_score": 3.0})
    monkeypatch.setattr(trading, "_fetch_coinbase_orderbook_snapshot", boom)
    monkeypatch.setattr(trading, "_fetch_kraken_orderbook_snapshot", boom)
    monkeypatch.setattr(trading, "_fetch_gemini_orderbook_snapshot", boom)
    monkeypatch.setattr(trading, "_fetch_bitstamp_orderbook_snapshot", boom)

    conn = trading.get_db()
    try:
        trading.ensure_schema(conn)
        market = trading._market(conn, "ETH/POINTS")
        price, source = trading._current_market_price_points(conn, market)
        updated = trading._market(conn, "ETH/POINTS")
    finally:
        conn.close()

    assert price == 175
    assert source == "fused_weighted"
    assert updated["manual_price_points"] == 175
    assert updated["price_source"] == "fused_weighted"


def test_root_trading_settings_default_to_fused_weighted_auto_depth(tmp_path):
    get_db = _db(tmp_path)
    points = PointsLedgerService(get_db=get_db, chain_secret="test-secret", backup_dir=tmp_path / "points_chain_backups")
    trading = TradingEngineService(get_db=get_db, points_service=points)

    settings = trading.get_root_settings()["settings"]
    markets = trading.list_markets()

    assert settings["price_source"] == "fused_weighted"
    assert settings["price_fusion_mode"] == "auto_depth"
    assert settings["price_fusion_live_markets"] == ["BTC/POINTS", "ETH/POINTS"]
    assert [row["symbol"] for row in markets] == ["BTC/POINTS", "ETH/POINTS"]
    assert markets[0]["display_symbol"] == "BTC/USDT"
    assert markets[0]["live_price_supported"] is True
    assert markets[0]["btc_trade_supported"] is True
    assert markets[1]["display_symbol"] == "ETH/USDT"
    assert markets[1]["btc_trade_supported"] is False


def test_price_fusion_auto_depth_status_uses_depth_scores_and_sums_to_hundred(tmp_path, monkeypatch):
    get_db = _db(tmp_path)
    points = PointsLedgerService(get_db=get_db, chain_secret="test-secret", backup_dir=tmp_path / "points_chain_backups")
    trading = TradingEngineService(get_db=get_db, points_service=points)
    root = _actor(3, "root", "super_admin")
    trading.update_root_settings(actor=root, settings={"price_source": "fused_weighted", "price_fusion_mode": "auto_depth"}, markets=[])

    monkeypatch.setattr(trading, "_fetch_binance_orderbook_snapshot", lambda _symbol: _depth_snapshot(trading, "binance_public_api", 1))
    monkeypatch.setattr(trading, "_fetch_okx_orderbook_snapshot", lambda _symbol: _depth_snapshot(trading, "okx_public_api", 2))
    monkeypatch.setattr(trading, "_fetch_coinbase_orderbook_snapshot", lambda _symbol: _depth_snapshot(trading, "coinbase_exchange", 3))
    monkeypatch.setattr(trading, "_fetch_kraken_orderbook_snapshot", lambda _symbol: _depth_snapshot(trading, "kraken_public_api", 4))
    monkeypatch.setattr(trading, "_fetch_gemini_orderbook_snapshot", lambda _symbol: _depth_snapshot(trading, "gemini_public_api", 5))
    monkeypatch.setattr(trading, "_fetch_bitstamp_orderbook_snapshot", lambda _symbol: _depth_snapshot(trading, "bitstamp_public_api", 6))

    status = trading.get_root_price_fusion_status(market_symbol="BTC/POINTS")
    used = {row["source"]: row for row in status["providers_used"]}

    assert status["configured_source"] == "fused_weighted"
    assert status["requested_mode"] == "auto_depth"
    assert status["resolved_mode"] == "auto_depth"
    assert status["state"] == "healthy"
    assert status["degraded"] is False
    assert status["excluded_providers"] == []
    assert status["weights_sum_percent"] == pytest.approx(100.0, abs=0.01)
    assert used["bitstamp_public_api"]["normalized_weight_percent"] > used["gemini_public_api"]["normalized_weight_percent"] > used["kraken_public_api"]["normalized_weight_percent"] > used["coinbase_exchange"]["normalized_weight_percent"] > used["okx_public_api"]["normalized_weight_percent"] > used["binance_public_api"]["normalized_weight_percent"]
    assert used["binance_public_api"]["normalized_weight_percent"] == pytest.approx(100.0 / 21.0, abs=0.01)
    assert used["bitstamp_public_api"]["normalized_weight_percent"] == pytest.approx((6.0 / 21.0) * 100.0, abs=0.01)


def test_price_fusion_status_and_audit_mark_excluded_failed_sources(tmp_path, monkeypatch):
    get_db = _db(tmp_path)
    points = PointsLedgerService(get_db=get_db, chain_secret="test-secret", backup_dir=tmp_path / "points_chain_backups")
    trading = TradingEngineService(get_db=get_db, points_service=points)
    root = _actor(3, "root", "super_admin")
    trading.update_root_settings(actor=root, settings={"price_source": "fused_weighted", "price_fusion_mode": "auto_depth"}, markets=[])

    def boom(_symbol):
        raise TimeoutError("timeout")

    monkeypatch.setattr(trading, "_fetch_binance_orderbook_snapshot", lambda _symbol: _depth_snapshot(trading, "binance_public_api", 2))
    monkeypatch.setattr(trading, "_fetch_okx_orderbook_snapshot", lambda _symbol: _depth_snapshot(trading, "okx_public_api", 3))
    monkeypatch.setattr(trading, "_fetch_coinbase_orderbook_snapshot", boom)
    monkeypatch.setattr(trading, "_fetch_kraken_orderbook_snapshot", boom)
    monkeypatch.setattr(trading, "_fetch_gemini_orderbook_snapshot", lambda _symbol: _depth_snapshot(trading, "gemini_public_api", 5))
    monkeypatch.setattr(trading, "_fetch_bitstamp_orderbook_snapshot", lambda _symbol: _depth_snapshot(trading, "bitstamp_public_api", 7))

    status = trading.get_root_price_fusion_status(market_symbol="ETH/POINTS")
    excluded = {row["source"]: row for row in status["excluded_providers"]}
    assert status["state"] == "degraded"
    assert status["degraded"] is True
    assert status["weights_sum_percent"] == pytest.approx(100.0, abs=0.01)
    assert excluded["coinbase_exchange"]["reason"] == "fetch_failed"
    assert excluded["kraken_public_api"]["reason"] == "fetch_failed"

    conn = trading.get_db()
    try:
        trading.ensure_schema(conn)
        market = trading._market(conn, "ETH/POINTS")
        price, source = trading._current_market_price_points(conn, market)
        conn.commit()
    finally:
        conn.close()

    assert price > 0
    assert source == "fused_weighted"
    audit = next(row for row in trading.root_report()["audit_events"] if row["event_type"] == "TRADING_PRICE_FUSION_DEGRADED")
    metadata = json.loads(audit["metadata_json"] or "{}")
    excluded_sources = {row["source"] for row in metadata.get("excluded_providers") or []}
    assert {"coinbase_exchange", "kraken_public_api"} <= excluded_sources


def test_live_price_fusion_manual_weights_renormalize_after_provider_failure(tmp_path, monkeypatch):
    get_db = _db(tmp_path)
    points = PointsLedgerService(get_db=get_db, chain_secret="test-secret", backup_dir=tmp_path / "points_chain_backups")
    trading = TradingEngineService(get_db=get_db, points_service=points)
    root = _actor(3, "root", "super_admin")
    trading.update_root_settings(
        actor=root,
        settings={
            "price_source": "fused_weighted",
            "price_fusion_mode": "manual_weights",
            "price_fusion_manual_weights": {
                "binance_public_api": 1,
                "okx_public_api": 3,
                "coinbase_exchange": 0,
                "kraken_public_api": 0,
                "gemini_public_api": 0,
                "bitstamp_public_api": 0,
            },
        },
        markets=[],
    )

    def boom(_market_symbol):
        raise OSError("provider unavailable")

    monkeypatch.setattr(trading, "_fetch_binance_orderbook_snapshot", lambda _symbol: {"source": "binance_public_api", "price_points": 123, "depth_score": 10.0})
    monkeypatch.setattr(trading, "_fetch_okx_orderbook_snapshot", boom)
    monkeypatch.setattr(trading, "_fetch_coinbase_orderbook_snapshot", boom)
    monkeypatch.setattr(trading, "_fetch_kraken_orderbook_snapshot", boom)
    monkeypatch.setattr(trading, "_fetch_gemini_orderbook_snapshot", boom)
    monkeypatch.setattr(trading, "_fetch_bitstamp_orderbook_snapshot", boom)

    conn = trading.get_db()
    try:
        trading.ensure_schema(conn)
        market = trading._market(conn, "ETH/POINTS")
        price, source = trading._current_market_price_points(conn, market)
    finally:
        conn.close()

    assert price == 123
    assert source == "fused_weighted"
    settings = trading.get_root_settings()["settings"]
    assert settings["price_fusion_mode"] == "manual_weights"
    assert settings["price_fusion_manual_weights"]["okx_public_api"] == 3


def test_price_fusion_manual_weights_default_equal_weight_and_zero_weight_exclusion(tmp_path, monkeypatch):
    get_db = _db(tmp_path)
    points = PointsLedgerService(get_db=get_db, chain_secret="test-secret", backup_dir=tmp_path / "points_chain_backups")
    trading = TradingEngineService(get_db=get_db, points_service=points)
    root = _actor(3, "root", "super_admin")
    trading.update_root_settings(actor=root, settings={"price_source": "fused_weighted", "price_fusion_mode": "manual_weights"}, markets=[])

    monkeypatch.setattr(trading, "_fetch_binance_orderbook_snapshot", lambda _symbol: _depth_snapshot(trading, "binance_public_api", 1))
    monkeypatch.setattr(trading, "_fetch_okx_orderbook_snapshot", lambda _symbol: _depth_snapshot(trading, "okx_public_api", 1))
    monkeypatch.setattr(trading, "_fetch_coinbase_orderbook_snapshot", lambda _symbol: _depth_snapshot(trading, "coinbase_exchange", 1))
    monkeypatch.setattr(trading, "_fetch_kraken_orderbook_snapshot", lambda _symbol: _depth_snapshot(trading, "kraken_public_api", 1))
    monkeypatch.setattr(trading, "_fetch_gemini_orderbook_snapshot", lambda _symbol: _depth_snapshot(trading, "gemini_public_api", 1))
    monkeypatch.setattr(trading, "_fetch_bitstamp_orderbook_snapshot", lambda _symbol: _depth_snapshot(trading, "bitstamp_public_api", 1))

    equal_status = trading.get_root_price_fusion_status(market_symbol="BTC/POINTS")
    assert equal_status["requested_mode"] == "manual_weights"
    assert equal_status["resolved_mode"] == "manual_weights"
    for row in equal_status["providers_used"]:
        assert row["normalized_weight_percent"] == pytest.approx(100.0 / 6.0, abs=0.02)

    trading.update_root_settings(
        actor=root,
        settings={
            "price_source": "fused_weighted",
            "price_fusion_mode": "manual_weights",
            "price_fusion_manual_weights": {
                "binance_public_api": 2,
                "okx_public_api": 1,
                "coinbase_exchange": 0,
                "kraken_public_api": 0,
                "gemini_public_api": 0,
                "bitstamp_public_api": 0,
            },
        },
        markets=[],
    )
    partial_status = trading.get_root_price_fusion_status(market_symbol="BTC/POINTS")
    used_sources = {row["source"] for row in partial_status["providers_used"]}
    excluded_sources = {row["source"]: row for row in partial_status["excluded_providers"]}
    assert used_sources == {"binance_public_api", "okx_public_api"}
    assert excluded_sources["coinbase_exchange"]["reason"] == "manual_weight_zero"
    assert excluded_sources["kraken_public_api"]["reason"] == "manual_weight_zero"


def test_price_fusion_manual_all_zero_reports_invalid_and_logs_auto_depth_fallback(tmp_path, monkeypatch):
    get_db = _db(tmp_path)
    points = PointsLedgerService(get_db=get_db, chain_secret="test-secret", backup_dir=tmp_path / "points_chain_backups")
    trading = TradingEngineService(get_db=get_db, points_service=points)
    root = _actor(3, "root", "super_admin")
    trading.update_root_settings(
        actor=root,
        settings={
            "price_source": "fused_weighted",
            "price_fusion_mode": "manual_weights",
            "price_fusion_manual_weights": {provider: 0 for provider in trading_engine_module.WEIGHTED_PRICE_PROVIDERS},
        },
        markets=[],
    )

    monkeypatch.setattr(trading, "_fetch_binance_orderbook_snapshot", lambda _symbol: _depth_snapshot(trading, "binance_public_api", 1))
    monkeypatch.setattr(trading, "_fetch_okx_orderbook_snapshot", lambda _symbol: _depth_snapshot(trading, "okx_public_api", 2))
    monkeypatch.setattr(trading, "_fetch_coinbase_orderbook_snapshot", lambda _symbol: _depth_snapshot(trading, "coinbase_exchange", 3))
    monkeypatch.setattr(trading, "_fetch_kraken_orderbook_snapshot", lambda _symbol: _depth_snapshot(trading, "kraken_public_api", 4))
    monkeypatch.setattr(trading, "_fetch_gemini_orderbook_snapshot", lambda _symbol: _depth_snapshot(trading, "gemini_public_api", 5))
    monkeypatch.setattr(trading, "_fetch_bitstamp_orderbook_snapshot", lambda _symbol: _depth_snapshot(trading, "bitstamp_public_api", 6))

    status = trading.get_root_price_fusion_status(market_symbol="BTC/POINTS")
    assert status["resolved_mode"] == "auto_depth_fallback"
    assert status["warning_code"] == "manual_weights_invalid"
    assert "手動權重全部為 0" in status["message"]

    conn = trading.get_db()
    try:
        trading.ensure_schema(conn)
        market = trading._market(conn, "BTC/POINTS")
        _price, source = trading._current_market_price_points(conn, market)
        conn.commit()
    finally:
        conn.close()

    assert source == "fused_weighted"
    audit = next(row for row in trading.root_report()["audit_events"] if row["event_type"] == "TRADING_PRICE_FUSION_DEGRADED")
    metadata = json.loads(audit["metadata_json"] or "{}")
    assert metadata["warning_code"] == "manual_weights_invalid"
    assert metadata["resolved_mode"] == "auto_depth_fallback"


def test_price_fusion_orderbook_total_failure_enters_conservative_single_source_fallback(tmp_path, monkeypatch):
    get_db = _db(tmp_path)
    points = PointsLedgerService(get_db=get_db, chain_secret="test-secret", backup_dir=tmp_path / "points_chain_backups")
    trading = TradingEngineService(get_db=get_db, points_service=points)
    root = _actor(3, "root", "super_admin")
    trading.update_root_settings(actor=root, settings={"price_source": "fused_weighted", "price_fusion_mode": "auto_depth"}, markets=[])

    def boom(_symbol):
        raise ValueError("malformed response")

    monkeypatch.setattr(trading, "_fetch_binance_orderbook_snapshot", boom)
    monkeypatch.setattr(trading, "_fetch_okx_orderbook_snapshot", boom)
    monkeypatch.setattr(trading, "_fetch_coinbase_orderbook_snapshot", boom)
    monkeypatch.setattr(trading, "_fetch_kraken_orderbook_snapshot", boom)
    monkeypatch.setattr(trading, "_fetch_gemini_orderbook_snapshot", boom)
    monkeypatch.setattr(trading, "_fetch_bitstamp_orderbook_snapshot", boom)
    monkeypatch.setattr(trading, "_fetch_live_price_points", lambda _symbol: (321, "coingecko_simple_price"))

    status = trading.get_root_price_fusion_status(market_symbol="ETH/POINTS")
    assert status["state"] == "conservative"
    assert status["fallback_active"] is True
    assert status["conservative_mode"] is True
    assert status["resolved_source"] == "coingecko_simple_price"
    assert "降級" in status["message"]

    conn = trading.get_db()
    try:
        trading.ensure_schema(conn)
        market = trading._market(conn, "ETH/POINTS")
        price, source = trading._current_market_price_points(conn, market)
        conn.commit()
    finally:
        conn.close()

    assert price == 321
    assert source == "coingecko_simple_price"
    audit = next(row for row in trading.root_report()["audit_events"] if row["event_type"] == "TRADING_PRICE_FUSION_DEGRADED")
    metadata = json.loads(audit["metadata_json"] or "{}")
    assert audit["event_type"] == "TRADING_PRICE_FUSION_DEGRADED"
    assert metadata["fallback_active"] is True
    assert metadata["conservative_mode"] is True
    assert metadata["resolved_source"] == "coingecko_simple_price"


def test_cached_fallback_preserves_fractional_subunit_price(tmp_path, monkeypatch):
    get_db = _db(tmp_path)
    points = PointsLedgerService(get_db=get_db, chain_secret="test-secret", backup_dir=tmp_path / "points_chain_backups")
    trading = TradingEngineService(get_db=get_db, points_service=points)
    root = _actor(3, "root", "super_admin")
    trading.update_root_settings(actor=root, settings={"price_source": "binance_public_api", "max_price_staleness_seconds": 900}, markets=[])

    def boom(_symbol):
        raise OSError("provider unavailable")

    monkeypatch.setattr(trading, "_fetch_live_price_points", boom)

    conn = trading.get_db()
    try:
        trading.ensure_schema(conn)
        market = trading._market_payload(trading._market(conn, "BTC/POINTS"))
        market["manual_price_points"] = "0.12345678"
        market["price_source"] = "binance_public_api"
        price, source = trading._current_market_price_points(conn, market)
    finally:
        conn.close()

    assert price == pytest.approx(0.12345678)
    assert source == "binance_public_api_cached"


def test_cached_fallback_preserves_decimal_part_for_whole_point_price(tmp_path, monkeypatch):
    get_db = _db(tmp_path)
    points = PointsLedgerService(get_db=get_db, chain_secret="test-secret", backup_dir=tmp_path / "points_chain_backups")
    trading = TradingEngineService(get_db=get_db, points_service=points)
    root = _actor(3, "root", "super_admin")
    trading.update_root_settings(actor=root, settings={"price_source": "binance_public_api", "max_price_staleness_seconds": 900}, markets=[])

    def boom(_symbol):
        raise OSError("provider unavailable")

    monkeypatch.setattr(trading, "_fetch_live_price_points", boom)

    conn = trading.get_db()
    try:
        trading.ensure_schema(conn)
        market = trading._market_payload(trading._market(conn, "BTC/POINTS"))
        market["manual_price_points"] = "123.99"
        market["price_source"] = "binance_public_api"
        price, source = trading._current_market_price_points(conn, market)
    finally:
        conn.close()

    assert price == pytest.approx(123.99)
    assert price != 123
    assert source == "binance_public_api_cached"


def test_live_market_quote_with_fractional_cached_fallback_is_json_serializable(tmp_path, monkeypatch):
    get_db = _db(tmp_path)
    points = PointsLedgerService(get_db=get_db, chain_secret="test-secret", backup_dir=tmp_path / "points_chain_backups")
    trading = TradingEngineService(get_db=get_db, points_service=points)

    monkeypatch.setattr(
        trading,
        "_current_market_price_points",
        lambda conn, market, with_meta=False: (
            (0.12345678, "binance_public_api_cached", {"price_health": "fallback", "fallback_reason": "provider unavailable", "excluded_sources": []})
            if with_meta else
            (0.12345678, "binance_public_api_cached")
        ),
    )

    quote = trading.get_live_market_quote(market_symbol="BTC/POINTS")

    assert quote["market"]["manual_price_points"] == pytest.approx(0.12345678)
    assert quote["price_health"] == "fallback"
    assert json.dumps(quote)


def test_live_price_provider_preserves_fractional_price_points(tmp_path):
    _, trading = _services(tmp_path)
    assert trading._price_points_from_float("123.45678901", source="test_source") == pytest.approx(123.45678901)


def test_update_market_and_limit_order_preserve_decimal_price_points(tmp_path):
    points, trading = _services(tmp_path)
    root = _actor(3, "root", "super_admin")
    points.record_transaction(user_id=1, currency_type="points", direction="credit", amount=2000, action_type="test_funding")
    trading.update_root_settings(actor=root, settings={"price_source": "manual_root"}, markets=[])
    updated = trading.update_market(actor=root, symbol="ETH/POINTS", manual_price_points="5000.125", confirm_jump=True)

    assert updated["market"]["manual_price_points"] == pytest.approx(5000.125)

    result = trading.place_order(
        actor=_actor(),
        market_symbol="ETH/POINTS",
        side="buy",
        order_type="limit",
        quantity="0.1",
        limit_price_points="5000.125",
    )

    assert result["executed"] is True
    assert result["order"]["execution_price_points"] == pytest.approx(5000.125)

    dashboard = trading.user_dashboard(user_id=1)
    assert dashboard["positions"][0]["avg_cost_points"] == pytest.approx(5000.125)


def test_bot_condition_checks_preserve_decimal_trigger_price(tmp_path):
    _, trading = _services(tmp_path)
    checks = trading._bot_condition_checks(
        {
            "trigger_type": "price_below",
            "trigger_price_points": "5000.55",
            "run_count": 0,
            "max_runs": 1,
        },
        5000.5,
    )

    assert checks[0]["met"] is True
    assert "5000.55" in checks[0]["label"]
    assert "5000.5" in checks[0]["label"]


def test_grid_preview_accepts_decimal_price_bounds(tmp_path):
    _, trading = _services(tmp_path)
    preview = trading.preview_grid_bot(
        actor=_actor(),
        payload={
            "market_symbol": "ETH/POINTS",
            "lower_price_points": "99.5",
            "upper_price_points": "100.5",
            "grid_count": 3,
            "order_amount_points": 1000,
            "spacing_mode": "arithmetic",
            "order_mode": "maker",
        },
    )

    assert preview["levels"][0] == pytest.approx(99.5)
    assert preview["levels"][1] == pytest.approx(100.0)
    assert preview["levels"][2] == pytest.approx(100.5)
    assert Decimal(preview["grid_profit"]["reference_buy_price_points"]) in {Decimal("99.5"), Decimal("100")}
    assert Decimal(preview["grid_profit"]["reference_sell_price_points"]) in {Decimal("100"), Decimal("100.5")}


def test_root_spot_and_contract_use_simulated_points_outside_points_chain(tmp_path):
    points, trading = _services(tmp_path)
    root = _actor(3, "root", "super_admin")

    result = trading.place_order(
        actor=root,
        market_symbol="ETH/POINTS",
        side="buy",
        order_type="market",
        quantity="0.1",
    )

    assert result["order"]["status"] == "filled"
    assert result["order"]["funding_mode"] == "root_simulated"
    dashboard = trading.user_dashboard(user_id=3)
    assert dashboard["funding"]["mode"] == "root_simulated"
    assert dashboard["funding"]["available_points"] == 9499
    assert dashboard["funding"]["locked_points"] == 0
    assert dashboard["positions"][0]["quantity"] == "0.1"
    assert trading.root_report()["reserve_pool"]["balance_points"] == 10000
    conn = trading.get_db()
    try:
        assert conn.execute("SELECT COUNT(*) FROM points_ledger").fetchone()[0] == 0
    finally:
        conn.close()
    assert trading.verify_state()["ok"] is True

    trading.update_root_settings(
        actor=root,
        settings={"futures_enabled": True},
        markets=[{"symbol": "ETH/POINTS", "futures_enabled": True}],
    )
    contract = trading.open_root_contract_position(
        actor=root,
        market_symbol="ETH/POINTS",
        side="long",
        quantity="0.01",
        leverage=2,
        margin_points=25,
    )
    assert contract["position"]["status"] == "open"
    assert contract["funding"]["available_points"] == 9474
    conn = trading.get_db()
    try:
        assert conn.execute("SELECT COUNT(*) FROM points_ledger").fetchone()[0] == 0
    finally:
        conn.close()
    closed = trading.close_root_contract_position(actor=root, position_uuid=contract["position"]["position_uuid"])
    assert closed["position"]["status"] == "closed"
    assert closed["credited_points"] == 25

    margin = trading.open_margin_position(
        actor=root,
        market_symbol="ETH/POINTS",
        position_type="margin_long",
        quantity="0.1",
        collateral_points=300,
    )
    assert margin["position"]["status"] == "open"
    assert margin["position"]["collateral_trial_points"] == 0
    assert margin["position"]["collateral_chain_points"] == 0
    assert trading.verify_state()["ok"] is True

    with pytest.raises(ValueError, match="only root"):
        trading.open_root_contract_position(
            actor=_actor(1, "alice", "user"),
            market_symbol="ETH/POINTS",
            side="long",
            quantity="0.01",
            leverage=2,
            margin_points=25,
        )

    reset = trading.reset_root_simulated_balance(actor=root)
    assert reset["funding"]["available_points"] == 10000
    assert reset["funding"]["locked_points"] == 0
    assert reset["deleted"]["orders"] >= 1
    assert reset["deleted"]["fills"] >= 1
    assert reset["deleted"]["spot_positions"] >= 1
    assert reset["deleted"]["futures_positions"] >= 1
    assert reset["deleted"]["margin_positions"] >= 1
    dashboard_after_reset = trading.user_dashboard(user_id=3)
    assert dashboard_after_reset["funding"]["mode"] == "root_simulated"
    assert dashboard_after_reset["funding"]["available_points"] == 10000
    assert dashboard_after_reset["funding"]["locked_points"] == 0
    assert dashboard_after_reset["orders"] == []
    assert dashboard_after_reset["fills"] == []
    assert dashboard_after_reset["positions"] == []
    assert dashboard_after_reset["futures_positions"] == []
    conn = trading.get_db()
    try:
        assert conn.execute("SELECT COUNT(*) FROM points_ledger").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM trading_orders WHERE user_id=3").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM trading_fills WHERE user_id=3").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM trading_spot_positions WHERE user_id=3").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM trading_futures_positions WHERE user_id=3").fetchone()[0] == 0
    finally:
        conn.close()


def test_root_contract_open_respects_futures_enabled(tmp_path):
    _points, trading = _services(tmp_path)
    root = _actor(3, "root", "super_admin")

    with pytest.raises(ValueError, match="contract trading is disabled"):
        trading.open_root_contract_position(
            actor=root,
            market_symbol="ETH/POINTS",
            side="long",
            quantity="0.01",
            leverage=2,
            margin_points=25,
        )

    trading.update_root_settings(actor=root, settings={"futures_enabled": True}, markets=[{"symbol": "ETH/POINTS", "futures_enabled": False}])
    with pytest.raises(ValueError, match="contract trading is disabled"):
        trading.open_root_contract_position(
            actor=root,
            market_symbol="ETH/POINTS",
            side="long",
            quantity="0.01",
            leverage=2,
            margin_points=25,
        )


def test_limit_buy_can_be_cancelled_and_unfreezes_points(tmp_path):
    points, trading = _services(tmp_path)
    points.record_transaction(user_id=1, currency_type="points", direction="credit", amount=2000, action_type="test_funding")

    order = trading.place_order(
        actor=_actor(),
        market_symbol="ETH/POINTS",
        side="buy",
        order_type="limit",
        quantity="0.1",
        limit_price_points=4000,
    )["order"]
    assert order["status"] == "open"
    assert points.get_wallet(1)["points_frozen"] == 0
    assert order["trial_frozen_points"] == 400

    cancelled = trading.cancel_order(actor=_actor(), order_uuid=order["order_uuid"])
    assert cancelled["status"] == "cancelled"
    wallet = points.get_wallet(1)
    assert wallet["points_balance"] == 2000
    assert wallet["points_frozen"] == 0


def test_limit_order_matcher_executes_when_price_reaches_limit(tmp_path):
    points, trading = _services(tmp_path)
    root = _actor(3, "root", "super_admin")
    points.record_transaction(user_id=1, currency_type="points", direction="credit", amount=1000, action_type="test_funding")
    trading.update_root_settings(actor=root, settings={"price_source": "manual_root"}, markets=[])
    trading.update_market(actor=root, symbol="ETH/POINTS", manual_price_points=5000, confirm_jump=True)

    order = trading.place_order(
        actor=_actor(),
        market_symbol="ETH/POINTS",
        side="buy",
        order_type="limit",
        quantity="0.1",
        limit_price_points=4000,
    )["order"]
    assert order["status"] == "open"
    assert points.get_wallet(1)["points_frozen"] == 0
    assert order["trial_frozen_points"] == 400

    trading.update_market(actor=root, symbol="ETH/POINTS", manual_price_points=3900, confirm_jump=True)
    matched = trading.match_open_limit_orders(actor={"username": "system", "role": "system"}, limit=10)

    assert matched["ok"] is True
    assert matched["matched"][0]["order_uuid"] == order["order_uuid"]
    dashboard = trading.user_dashboard(user_id=1)
    assert dashboard["orders"][0]["status"] == "filled"
    assert dashboard["orders"][0]["execution_price_points"] == 3900
    assert dashboard["positions"][0]["quantity"] == "0.1"
    assert points.get_wallet(1)["points_frozen"] == 0
    assert trading.verify_state()["ok"] is True


def test_sell_payout_does_not_consume_experimental_reserve_pool(tmp_path):
    points, trading = _services(tmp_path)
    points.record_transaction(user_id=1, currency_type="points", direction="credit", amount=2000, action_type="test_funding")
    trading.place_order(actor=_actor(), market_symbol="ETH/POINTS", side="buy", order_type="market", quantity="0.1")

    trading.update_market(
        actor=_actor(3, "root", "super_admin"),
        symbol="ETH/POINTS",
        manual_price_points=20000,
        max_order_points=1000000,
        confirm_jump=True,
    )
    trading.test_prices["ETH/POINTS"] = 20000

    high_price_sell = trading.place_order(actor=_actor(), market_symbol="ETH/POINTS", side="sell", order_type="market", quantity="0.05")
    assert high_price_sell["order"]["status"] == "filled"
    assert trading.root_report()["reserve_pool"]["balance_points"] == 10001

    trading.update_market(actor=_actor(3, "root", "super_admin"), symbol="ETH/POINTS", manual_price_points=5000, confirm_jump=True)
    trading.test_prices["ETH/POINTS"] = 5000

    points.record_transaction(user_id=1, currency_type="points", direction="credit", amount=2000, action_type="test_funding_again")
    trading.place_order(actor=_actor(), market_symbol="ETH/POINTS", side="buy", order_type="market", quantity="0.1")
    sold = trading.place_order(actor=_actor(), market_symbol="ETH/POINTS", side="sell", order_type="market", quantity="0.05")
    assert sold["order"]["status"] == "filled"
    ledger_actions = [row["action_type"] for row in points.list_ledger(user_id=1, include_user_id=True)]
    assert ledger_actions.count("trading_spot_sell") >= 1
    assert trading.verify_state()["ok"] is True


def test_root_reserve_allocation_debits_source_wallet_and_audits(tmp_path):
    points, trading = _services(tmp_path)
    points.record_transaction(user_id=2, currency_type="points", direction="credit", amount=1000, action_type="test_funding")

    result = trading.allocate_reserve(
        actor=_actor(3, "root", "super_admin"),
        source_user_id=2,
        amount_points=250,
        reason="ROOT_RESERVE_ALLOCATION",
    )

    assert result["balance_points"] == 10250
    assert points.get_wallet(2)["points_balance"] == 750
    report = trading.root_report()
    assert report["reserve_events"][0]["reason"] == "ROOT_RESERVE_ALLOCATION"
    assert report["audit_events"][0]["event_type"] == "TRADING_RESERVE_ALLOCATED"


def test_price_jump_requires_explicit_confirmation(tmp_path):
    _, trading = _services(tmp_path)
    root = _actor(3, "root", "super_admin")

    with pytest.raises(ValueError, match="confirmation required"):
        trading.update_market(actor=root, symbol="ETH/POINTS", manual_price_points=20000)

    updated = trading.update_market(actor=root, symbol="ETH/POINTS", manual_price_points=20000, confirm_jump=True)
    assert updated["market"]["manual_price_points"] == 20000
    assert updated["market"]["price_source"] == "manual_root"


def test_root_can_update_trading_billing_settings_and_market_limits(tmp_path):
    _, trading = _services(tmp_path)
    root = _actor(3, "root", "super_admin")

    updated = trading.update_root_settings(
        actor=root,
        settings={
            "enabled": True,
            "borrowing_enabled": True,
            "borrow_apr_btc_eth_percent": 8.25,
            "borrow_apr_usdt_points_percent": 10.5,
            "borrow_interest_interval_hours": 1,
            "borrow_interest_minimum_hours": 1,
            "grid_fee_discount_percent": 25,
            "margin_liquidation_enabled": True,
            "margin_maintenance_percent": 12,
            "futures_enabled": False,
            "pvp_matching_enabled": False,
        },
        markets=[
            {
                "symbol": "ETH/POINTS",
                "enabled": True,
                "fee_rate_percent": 0.45,
                "min_order_points": 10,
                "max_order_points": 500000,
            }
        ],
    )

    assert updated["settings"]["borrowing_enabled"] is True
    assert updated["settings"]["borrow_apr_btc_eth_percent"] == pytest.approx(8.25)
    assert updated["settings"]["borrow_apr_usdt_points_percent"] == pytest.approx(10.5)
    assert updated["settings"]["borrow_interest_percent_daily"] == pytest.approx(10.5 / 365.0)
    assert updated["settings"]["borrow_interest_interval_hours"] == 1
    assert updated["settings"]["borrow_interest_minimum_hours"] == 1
    assert updated["settings"]["grid_fee_discount_percent"] == pytest.approx(25.0)
    assert updated["settings"]["margin_liquidation_enabled"] is True
    assert updated["settings"]["margin_maintenance_percent"] == 12
    market = next(row for row in updated["markets"] if row["symbol"] == "ETH/POINTS")
    assert market["fee_rate_percent"] == 0.45
    assert market["min_order_points"] == 10
    assert market["max_order_points"] == 500000
    report = trading.root_report()
    assert report["settings"]["borrowing_enabled"] is True
    assert report["audit_events"][0]["event_type"] in {"TRADING_MARKET_BILLING_UPDATED", "TRADING_SETTINGS_UPDATED"}


def test_borrowing_trading_is_enabled_by_default(tmp_path):
    _, trading = _services(tmp_path)

    report = trading.get_root_settings()
    settings = report["settings"]
    eth_market = next(row for row in report["markets"] if row["symbol"] == "ETH/POINTS")

    assert settings["borrowing_enabled"] is True
    assert settings["borrow_apr_btc_eth_percent"] == pytest.approx(8.0)
    assert settings["borrow_apr_usdt_points_percent"] == pytest.approx(10.0)
    assert settings["borrow_interest_interval_hours"] == 1
    assert settings["borrow_interest_minimum_hours"] == 1
    assert settings["grid_fee_discount_percent"] == pytest.approx(25.0)
    assert eth_market["fee_rate_percent"] == pytest.approx(0.1)
    assert trading._grid_fee_rate_percent(eth_market["fee_rate_percent"], settings) == pytest.approx(0.075)


def test_margin_positions_use_asset_specific_apr_groups_and_hourly_interest_metadata(tmp_path):
    _, trading = _services(tmp_path)
    trading.update_root_settings(
        actor=_actor(3, "root", "super_admin"),
        settings={
            "borrowing_enabled": True,
            "borrow_apr_btc_eth_percent": 8,
            "borrow_apr_usdt_points_percent": 10,
            "borrow_interest_pool_pressure_multiplier": 0,
            "borrow_interest_interval_hours": 1,
            "borrow_interest_minimum_hours": 1,
            "price_source": "manual_root",
        },
        markets=[],
    )

    opened_long = trading.open_margin_position(
        actor=_actor(),
        market_symbol="ETH/POINTS",
        position_type="margin_long",
        quantity="0.1",
        collateral_points=200,
    )
    long_position = trading.user_dashboard(user_id=1)["margin_positions"][0]

    assert opened_long["position"]["borrowed_asset_symbol"] == "POINTS"
    assert opened_long["position"]["interest_percent_daily"] == pytest.approx(10.0 / 365.0)
    assert long_position["interest_apr_percent"] == pytest.approx(10.0)
    assert long_position["interest_interval_hours"] == 1
    assert long_position["interest_minimum_hours"] == 1
    assert long_position["next_interest_at"]

    trading.close_margin_position(actor=_actor(), position_uuid=opened_long["position"]["position_uuid"])

    opened_short = trading.open_margin_position(
        actor=_actor(),
        market_symbol="ETH/POINTS",
        position_type="short",
        quantity="0.1",
        collateral_points=300,
    )
    short_position = trading.user_dashboard(user_id=1)["margin_positions"][0]

    assert opened_short["position"]["borrowed_asset_symbol"] == "ETH"
    assert opened_short["position"]["interest_percent_daily"] == pytest.approx(8.0 / 365.0)
    assert short_position["interest_apr_percent"] == pytest.approx(8.0)
    assert short_position["interest_interval_hours"] == 1
    assert short_position["interest_minimum_hours"] == 1


def test_trading_volume_stats_accumulate_spot_and_margin_activity_for_future_vip_logic(tmp_path):
    points, trading = _services(tmp_path)
    points.record_transaction(user_id=1, currency_type="points", direction="credit", amount=2000, action_type="test_funding")
    trading.update_root_settings(
        actor=_actor(3, "root", "super_admin"),
        settings={"borrowing_enabled": True, "price_source": "manual_root"},
        markets=[],
    )

    spot = trading.place_order(
        actor=_actor(),
        market_symbol="ETH/POINTS",
        side="buy",
        order_type="market",
        quantity="0.1",
    )
    opened = trading.open_margin_position(
        actor=_actor(),
        market_symbol="ETH/POINTS",
        position_type="margin_long",
        quantity="0.1",
        collateral_points=200,
    )
    closed = trading.close_margin_position(actor=_actor(), position_uuid=opened["position"]["position_uuid"])

    stats = trading.user_dashboard(user_id=1)["volume_stats"]

    assert stats["spot_notional_points"] == 500
    assert stats["margin_notional_points"] == 1000
    assert stats["total_notional_points"] == 1500
    assert stats["total_trade_count"] == 3
    assert stats["total_fee_points"] == (
        spot["order"]["fee_points"]
        + opened["position"]["open_fee_points"]
        + closed["close_fee_points"]
    )

    root_summary = trading.root_report()["volume_summary"]
    assert root_summary["totals"]["spot_notional_points"] == 500
    assert root_summary["totals"]["margin_notional_points"] == 1000
    assert root_summary["totals"]["total_notional_points"] == 1500
    assert root_summary["totals"]["total_trade_count"] == 3
    assert root_summary["top_users"][0]["username"] == "alice"


def test_margin_long_requires_root_enabled_borrowing_and_closes_with_fee_stats(tmp_path):
    points, trading = _services(tmp_path)
    points.record_transaction(user_id=1, currency_type="points", direction="credit", amount=1000, action_type="test_funding")

    trading.update_root_settings(
        actor=_actor(3, "root", "super_admin"),
        settings={"borrowing_enabled": False},
        markets=[],
    )
    with pytest.raises(ValueError, match="borrow trading is disabled"):
        trading.open_margin_position(
            actor=_actor(),
            market_symbol="ETH/POINTS",
            position_type="margin_long",
            quantity="0.1",
            collateral_points=200,
        )

    trading.update_root_settings(
        actor=_actor(3, "root", "super_admin"),
        settings={"borrowing_enabled": True, "borrow_interest_percent_daily": 10},
        markets=[],
    )
    opened = trading.open_margin_position(
        actor=_actor(),
        market_symbol="ETH/POINTS",
        position_type="margin_long",
        quantity="0.1",
        collateral_points=200,
    )

    assert opened["position"]["position_type"] == "margin_long"
    assert opened["position"]["principal_points"] == 300
    assert opened["position"]["collateral_trial_points"] == 200
    assert opened["position"]["open_fee_trial_points"] == 1
    assert points.get_wallet(1)["points_balance"] == 1000
    assert points.get_wallet(1)["points_frozen"] == 0
    assert opened["funding"]["trial_credit"]["available_points"] == 799
    assert opened["funding"]["trial_credit"]["deployed_points"] == 200
    assert opened["position"]["interest_percent_daily"] == pytest.approx(11.2)
    assert trading.root_report()["reserve_pool"]["balance_points"] == 9701

    closed = trading.close_margin_position(actor=_actor(), position_uuid=opened["position"]["position_uuid"])
    assert closed["position"]["status"] == "closed"
    assert closed["interest_points"] == 0
    assert closed["position"]["interest_paid_points"] == 1
    assert closed["delta_points"] == -1
    assert points.get_wallet(1)["points_frozen"] == 0
    assert closed["funding"]["trial_credit"]["available_points"] == 998
    assert closed["funding"]["trial_credit"]["deployed_points"] == 0
    assert trading.root_report()["reserve_pool"]["balance_points"] == 10003
    assert trading.verify_state()["ok"] is True


def test_margin_open_and_close_are_included_in_trade_history(tmp_path):
    points, trading = _services(tmp_path)
    points.record_transaction(user_id=1, currency_type="points", direction="credit", amount=1000, action_type="test_funding")
    trading.update_root_settings(
        actor=_actor(3, "root", "super_admin"),
        settings={"borrowing_enabled": True},
        markets=[],
    )

    opened = trading.open_margin_position(
        actor=_actor(),
        market_symbol="ETH/POINTS",
        position_type="margin_long",
        quantity="0.1",
        collateral_points=200,
    )
    dashboard_after_open = trading.user_dashboard(user_id=1)

    assert dashboard_after_open["spot_fills"] == []
    assert [row["record_type"] for row in dashboard_after_open["margin_trade_records"]] == ["margin_open"]
    assert dashboard_after_open["fills"][0]["record_type"] == "margin_open"
    assert dashboard_after_open["fills"][0]["side"] == "融資做多開倉"
    assert dashboard_after_open["fills"][0]["position_uuid"] == opened["position"]["position_uuid"]

    closed = trading.close_margin_position(actor=_actor(), position_uuid=opened["position"]["position_uuid"])
    dashboard_after_close = trading.user_dashboard(user_id=1)
    record_types = [row["record_type"] for row in dashboard_after_close["margin_trade_records"]]
    close_record = next(row for row in dashboard_after_close["margin_trade_records"] if row["record_type"] == "margin_close")

    assert record_types == ["margin_close", "margin_open"]
    assert dashboard_after_close["fills"][0]["record_type"] == "margin_close"
    assert close_record["side"] == "融資做多平倉"
    assert close_record["position_uuid"] == opened["position"]["position_uuid"]
    assert close_record["price_points"] == closed["position"]["exit_price_points"]
    assert close_record["realized_pnl_points"] == closed["delta_points"]
    assert close_record["fee_points"] == closed["close_fee_points"]


def test_margin_interest_charges_by_started_hour_not_whole_day(tmp_path):
    points, trading = _services(tmp_path)
    points.record_transaction(user_id=1, currency_type="points", direction="credit", amount=1000, action_type="test_funding")
    trading.update_root_settings(
        actor=_actor(3, "root", "super_admin"),
        settings={"borrowing_enabled": True, "borrow_interest_percent_daily": 24},
        markets=[],
    )
    opened = trading.open_margin_position(
        actor=_actor(),
        market_symbol="ETH/POINTS",
        position_type="margin_long",
        quantity="0.1",
        collateral_points=200,
    )

    conn = trading.get_db()
    try:
        conn.execute(
            "UPDATE trading_margin_positions SET opened_at='2026-05-02T10:00:00' WHERE position_uuid=?",
            (opened["position"]["position_uuid"],),
        )
        conn.commit()
        row = conn.execute(
            "SELECT * FROM trading_margin_positions WHERE position_uuid=?",
            (opened["position"]["position_uuid"],),
        ).fetchone()
        assert trading._margin_interest_points(row, now_text="2026-05-02T10:00:01") == 3
        assert trading._margin_interest_points(row, now_text="2026-05-02T10:59:59") == 3
        assert trading._margin_interest_points(row, now_text="2026-05-02T11:00:00") == 3
        assert trading._margin_interest_points(row, now_text="2026-05-02T11:00:01") == 6
        assert trading._margin_interest_points(row, now_text="2026-05-03T09:59:59") == 80
    finally:
        conn.close()


def test_margin_interest_accumulates_fractional_carry_for_small_principal(tmp_path):
    _, trading = _services(tmp_path)
    trading.update_root_settings(
        actor=_actor(3, "root", "super_admin"),
        settings={
            "borrowing_enabled": True,
            "borrow_interest_percent_daily": 1,
            "borrow_interest_pool_pressure_multiplier": 0,
            "price_source": "manual_root",
        },
        markets=[{"symbol": "ETH/POINTS", "manual_price_points": 5000}],
    )
    opened = trading.open_margin_position(
        actor=_actor(),
        market_symbol="ETH/POINTS",
        position_type="margin_long",
        quantity="0.02",
        collateral_points=50,
    )

    conn = trading.get_db()
    try:
        conn.execute(
            "UPDATE trading_margin_positions SET opened_at='2026-05-02T10:00:00' WHERE position_uuid=?",
            (opened["position"]["position_uuid"],),
        )
        conn.commit()
        row = conn.execute(
            "SELECT * FROM trading_margin_positions WHERE position_uuid=?",
            (opened["position"]["position_uuid"],),
        ).fetchone()
        conn.execute("BEGIN IMMEDIATE")
        accrued = trading._accrue_margin_interest(conn, row, actor={"username": "system"}, now_text="2026-05-03T10:00:00")
        conn.commit()
    finally:
        conn.close()

    assert accrued["interest_points"] == 0
    assert accrued["interest_paid_points"] == 0
    assert accrued["interest_carry_micropoints"] == 500000

    conn = trading.get_db()
    try:
        row = conn.execute(
            "SELECT * FROM trading_margin_positions WHERE position_uuid=?",
            (opened["position"]["position_uuid"],),
        ).fetchone()
        conn.execute("BEGIN IMMEDIATE")
        accrued_again = trading._accrue_margin_interest(conn, row, actor={"username": "system"}, now_text="2026-05-04T10:00:00")
        conn.commit()
    finally:
        conn.close()

    assert accrued_again["interest_points"] == 1
    assert accrued_again["interest_carry_micropoints"] == 0
    assert trading.verify_state()["ok"] is True


def test_margin_open_rejects_when_funding_pool_is_insufficient(tmp_path):
    points, trading = _services(tmp_path)
    points.record_transaction(user_id=1, currency_type="points", direction="credit", amount=1000, action_type="test_funding")
    trading.update_root_settings(
        actor=_actor(3, "root", "super_admin"),
        settings={"borrowing_enabled": True},
        markets=[],
    )
    conn = trading.get_db()
    try:
        conn.execute("BEGIN")
        trading._reserve_delta(
            conn,
            delta=-9950,
            event_type="test_funding_pool_drain",
            reason="TEST_FUNDING_POOL_DRAIN",
            actor=_actor(3, "root", "super_admin"),
        )
        conn.commit()
    finally:
        conn.close()

    assert trading.user_dashboard(user_id=1)["funding_pool"]["available_points"] == 50
    with pytest.raises(ValueError, match="funding pool is insufficient"):
        trading.open_margin_position(
            actor=_actor(),
            market_symbol="ETH/POINTS",
            position_type="margin_long",
            quantity="0.1",
            collateral_points=200,
        )
    assert trading.verify_state()["ok"] is True


def test_margin_open_requires_buffer_so_liquidation_price_starts_beyond_entry(tmp_path):
    points, trading = _services(tmp_path)
    points.record_transaction(user_id=1, currency_type="points", direction="credit", amount=2000, action_type="test_funding")
    trading.update_root_settings(
        actor=_actor(3, "root", "super_admin"),
        settings={
            "borrowing_enabled": True,
            "margin_long_financing_percent": 90,
            "short_collateral_percent": 10,
            "margin_maintenance_percent": 15,
            "price_source": "manual_root",
        },
        markets=[],
    )

    with pytest.raises(ValueError, match="collateral below minimum 77"):
        trading.open_margin_position(
            actor=_actor(),
            market_symbol="ETH/POINTS",
            position_type="margin_long",
            quantity="0.1",
            collateral_points=76,
        )
    with pytest.raises(ValueError, match="collateral must be lower than notional 500"):
        trading.open_margin_position(
            actor=_actor(),
            market_symbol="ETH/POINTS",
            position_type="margin_long",
            quantity="0.1",
            collateral_points=500,
        )
    long_position = trading.open_margin_position(
        actor=_actor(),
        market_symbol="ETH/POINTS",
        position_type="margin_long",
        quantity="0.1",
        collateral_points=77,
    )
    long_risk = trading.user_dashboard(user_id=1)["margin_positions"][0]["risk"]
    assert long_risk["liquidation_price_points"] < long_position["position"]["entry_price_points"]
    trading.close_margin_position(actor=_actor(), position_uuid=long_position["position"]["position_uuid"])

    with pytest.raises(ValueError, match="collateral below minimum 77"):
        trading.open_margin_position(
            actor=_actor(),
            market_symbol="ETH/POINTS",
            position_type="short",
            quantity="0.1",
            collateral_points=76,
        )
    short_position = trading.open_margin_position(
        actor=_actor(),
        market_symbol="ETH/POINTS",
        position_type="short",
        quantity="0.1",
        collateral_points=77,
    )
    short_risk = trading.user_dashboard(user_id=1)["margin_positions"][0]["risk"]
    assert short_risk["liquidation_price_points"] > short_position["position"]["entry_price_points"]
    assert trading.verify_state()["ok"] is True


def test_margin_open_is_idempotent_for_client_key(tmp_path):
    points, trading = _services(tmp_path)
    points.record_transaction(user_id=1, currency_type="points", direction="credit", amount=1000, action_type="test_funding")

    first = trading.open_margin_position(
        actor=_actor(),
        market_symbol="ETH/POINTS",
        position_type="margin_long",
        quantity="0.1",
        collateral_points=200,
        idempotency_key="open-margin-click-1",
    )
    second = trading.open_margin_position(
        actor=_actor(),
        market_symbol="ETH/POINTS",
        position_type="margin_long",
        quantity="0.1",
        collateral_points=200,
        idempotency_key="open-margin-click-1",
    )

    assert second["position"]["position_uuid"] == first["position"]["position_uuid"]
    dashboard = trading.user_dashboard(user_id=1)
    assert len([row for row in dashboard["margin_positions"] if row["status"] == "open"]) == 1
    assert dashboard["margin_positions"][0]["interest_paid_points"] == 0
    assert trading.root_report()["reserve_pool"]["balance_points"] == 9701
    assert trading.verify_state()["ok"] is True


def test_hourly_margin_interest_capitalizes_when_wallet_balance_is_insufficient(tmp_path):
    points, trading = _services(tmp_path)
    trading.update_root_settings(
        actor=_actor(3, "root", "super_admin"),
        settings={"borrowing_enabled": True, "borrow_interest_percent_daily": 24},
        markets=[],
    )
    opened = trading.open_margin_position(
        actor=_actor(),
        market_symbol="ETH/POINTS",
        position_type="margin_long",
        quantity="0.1",
        collateral_points=200,
    )
    assert points.get_wallet(1)["points_balance"] == 0

    conn = trading.get_db()
    try:
        conn.execute(
            "UPDATE trading_margin_positions SET opened_at='2026-05-02T10:00:00' WHERE position_uuid=?",
            (opened["position"]["position_uuid"],),
        )
        conn.commit()
        row = conn.execute(
            "SELECT * FROM trading_margin_positions WHERE position_uuid=?",
            (opened["position"]["position_uuid"],),
        ).fetchone()
        conn.execute("BEGIN IMMEDIATE")
        accrued = trading._accrue_margin_interest(conn, row, actor={"username": "system"}, now_text="2026-05-02T11:00:01")
        conn.commit()
    finally:
        conn.close()

    assert accrued["interest_accrued_hours"] == 2
    assert accrued["interest_paid_points"] == 0
    assert accrued["interest_points"] == 6
    assert accrued["interest_carry_micropoints"] == 720000
    conn = trading.get_db()
    try:
        position = conn.execute(
            "SELECT * FROM trading_margin_positions WHERE position_uuid=?",
            (opened["position"]["position_uuid"],),
        ).fetchone()
    finally:
        conn.close()
    assert position["interest_points"] == 6
    assert position["interest_carry_micropoints"] == 720000
    assert trading.verify_state()["ok"] is True


def test_margin_collateral_add_is_idempotent_with_client_key(tmp_path):
    points, trading = _services(tmp_path)
    points.record_transaction(user_id=1, currency_type="points", direction="credit", amount=1000, action_type="test_funding")
    opened = trading.open_margin_position(
        actor=_actor(),
        market_symbol="ETH/POINTS",
        position_type="margin_long",
        quantity="0.1",
        collateral_points=200,
    )

    first = trading.add_margin_collateral(
        actor=_actor(),
        position_uuid=opened["position"]["position_uuid"],
        amount_points=100,
        idempotency_key="same-click-key",
    )
    second = trading.add_margin_collateral(
        actor=_actor(),
        position_uuid=opened["position"]["position_uuid"],
        amount_points=100,
        idempotency_key="same-click-key",
    )

    assert first["position"]["collateral_points"] == 300
    assert second["position"]["collateral_points"] == 300
    dashboard = trading.user_dashboard(user_id=1)
    assert dashboard["margin_positions"][0]["collateral_points"] == 300
    assert dashboard["funding"]["trial_credit"]["deployed_points"] == 300


def test_margin_collateral_add_is_idempotent_without_client_key(tmp_path):
    points, trading = _services(tmp_path)
    points.record_transaction(user_id=1, currency_type="points", direction="credit", amount=1000, action_type="test_funding")
    opened = trading.open_margin_position(
        actor=_actor(),
        market_symbol="ETH/POINTS",
        position_type="margin_long",
        quantity="0.1",
        collateral_points=200,
    )

    first = trading.add_margin_collateral(
        actor=_actor(),
        position_uuid=opened["position"]["position_uuid"],
        amount_points=100,
    )
    second = trading.add_margin_collateral(
        actor=_actor(),
        position_uuid=opened["position"]["position_uuid"],
        amount_points=100,
    )

    assert first["position"]["collateral_points"] == 300
    assert second["position"]["collateral_points"] == 300
    dashboard = trading.user_dashboard(user_id=1)
    assert dashboard["margin_positions"][0]["collateral_points"] == 300
    assert dashboard["funding"]["trial_credit"]["deployed_points"] == 300


def test_expired_trial_margin_collateral_can_be_closed_without_negative_accounting(tmp_path):
    points, trading = _services(tmp_path)
    points.record_transaction(user_id=1, currency_type="points", direction="credit", amount=1000, action_type="test_funding")
    opened = trading.open_margin_position(
        actor=_actor(),
        market_symbol="ETH/POINTS",
        position_type="margin_long",
        quantity="0.1",
        collateral_points=200,
    )
    conn = trading.get_db()
    conn.execute("UPDATE trading_trial_credits SET expires_at='2000-01-01T00:00:00' WHERE user_id=1")
    conn.commit()
    conn.close()

    expired = trading.user_dashboard(user_id=1)["funding"]["trial_credit"]
    assert expired["status"] == "expired"
    assert expired["available_points"] == 0
    assert expired["deployed_points"] == 200
    closed = trading.close_margin_position(actor=_actor(), position_uuid=opened["position"]["position_uuid"])

    assert closed["position"]["status"] == "closed"
    assert closed["funding"]["trial_credit"]["status"] == "expired"
    assert closed["funding"]["trial_credit"]["available_points"] == 0
    assert closed["funding"]["trial_credit"]["deployed_points"] == 0
    assert trading.verify_state()["ok"] is True


def test_short_borrow_position_profit_and_interest_enter_reserve_pool(tmp_path):
    points, trading = _services(tmp_path)
    points.record_transaction(user_id=1, currency_type="points", direction="credit", amount=1000, action_type="test_funding")
    trading.update_root_settings(
        actor=_actor(3, "root", "super_admin"),
        settings={
            "borrowing_enabled": True,
            "borrow_apr_btc_eth_percent": 100,
            "borrow_interest_pool_pressure_multiplier": 0,
            "price_source": "manual_root",
        },
        markets=[],
    )
    opened = trading.open_margin_position(
        actor=_actor(),
        market_symbol="ETH/POINTS",
        position_type="short",
        quantity="0.1",
        collateral_points=300,
    )

    conn = trading.get_db()
    try:
        conn.execute(
            "UPDATE trading_margin_positions SET opened_at=datetime(opened_at, '-2 days') WHERE position_uuid=?",
            (opened["position"]["position_uuid"],),
        )
        conn.commit()
    finally:
        conn.close()
    trading.update_market(actor=_actor(3, "root", "super_admin"), symbol="ETH/POINTS", manual_price_points=4000, confirm_jump=True)
    closed = trading.close_margin_position(actor=_actor(), position_uuid=opened["position"]["position_uuid"])

    assert closed["position"]["status"] == "closed"
    assert closed["interest_points"] == 0
    assert closed["position"]["interest_paid_points"] == 2
    assert closed["delta_points"] == 100
    assert trading.root_report()["reserve_pool"]["balance_points"] == 9903
    assert trading.verify_state()["ok"] is True


def test_margin_liquidation_scan_closes_underwater_position(tmp_path):
    points, trading = _services(tmp_path)
    points.record_transaction(user_id=1, currency_type="points", direction="credit", amount=202, action_type="test_funding")
    _deplete_trial_credit(trading, user_id=1)
    trading.update_root_settings(
        actor=_actor(3, "root", "super_admin"),
        settings={
            "borrowing_enabled": True,
            "borrow_interest_percent_daily": 0,
            "margin_liquidation_enabled": True,
            "margin_maintenance_percent": 15,
            "price_source": "manual_root",
        },
        markets=[],
    )
    opened = trading.open_margin_position(
        actor=_actor(),
        market_symbol="ETH/POINTS",
        position_type="margin_long",
        quantity="0.1",
        collateral_points=200,
    )

    trading.update_market(actor=_actor(3, "root", "super_admin"), symbol="ETH/POINTS", manual_price_points=3300, confirm_jump=True)
    result = trading.scan_margin_liquidations(actor={"username": "system", "role": "system"}, limit=10)

    assert result["ok"] is True
    assert result["scanned"] == 1
    assert result["liquidated"][0]["position_uuid"] == opened["position"]["position_uuid"]
    assert result["liquidated"][0]["account_risk"]["liquidation_required"] is True
    dashboard = trading.user_dashboard(user_id=1)
    assert dashboard["margin_positions"][0]["status"] == "liquidated"
    assert points.get_wallet(1)["points_frozen"] == 0
    notices = _notifications(trading, 1)
    assert any(row["type"] == "trading_margin_liquidated" for row in notices)
    assert trading.root_report()["reserve_pool"]["balance_points"] == 10001
    assert trading.verify_state()["ok"] is True


def test_margin_liquidation_scan_uses_window_low_for_recovered_price(tmp_path):
    candles = [
        {"time_ms": 1_700_000_000_000, "close_points": 5000.0, "high_points": 5000.0, "low_points": 3300.0},
    ]
    points, trading = _services_with_history(tmp_path, prices={"ETH/POINTS": 5000.0}, candles=candles)
    points.record_transaction(user_id=1, currency_type="points", direction="credit", amount=202, action_type="test_funding")
    _deplete_trial_credit(trading, user_id=1)
    trading.update_root_settings(
        actor=_actor(3, "root", "super_admin"),
        settings={
            "borrowing_enabled": True,
            "borrow_interest_percent_daily": 0,
            "margin_liquidation_enabled": True,
            "margin_maintenance_percent": 15,
        },
        markets=[],
    )
    opened = trading.open_margin_position(
        actor=_actor(),
        market_symbol="ETH/POINTS",
        position_type="margin_long",
        quantity="0.1",
        collateral_points=200,
    )

    result = trading.scan_margin_liquidations(actor={"username": "system", "role": "system"}, limit=10)

    assert result["ok"] is True
    assert result["liquidated"][0]["position_uuid"] == opened["position"]["position_uuid"]
    assert result["liquidated"][0]["risk"]["price_points"] == pytest.approx(3300.0)


def test_cross_margin_free_margin_prevents_single_position_liquidation(tmp_path):
    points, trading = _services(tmp_path)
    points.record_transaction(user_id=1, currency_type="points", direction="credit", amount=1000, action_type="test_funding")
    _deplete_trial_credit(trading, user_id=1)
    trading.update_root_settings(
        actor=_actor(3, "root", "super_admin"),
        settings={
            "borrowing_enabled": True,
            "borrow_interest_percent_daily": 0,
            "margin_liquidation_enabled": True,
            "margin_maintenance_percent": 15,
            "price_source": "manual_root",
        },
        markets=[],
    )
    opened = trading.open_margin_position(
        actor=_actor(),
        market_symbol="ETH/POINTS",
        position_type="margin_long",
        quantity="0.1",
        collateral_points=200,
    )

    trading.update_market(actor=_actor(3, "root", "super_admin"), symbol="ETH/POINTS", manual_price_points=3300, confirm_jump=True)
    dashboard = trading.user_dashboard(user_id=1)
    position_risk = dashboard["margin_positions"][0]["risk"]
    account_risk = dashboard["margin_summary"]
    result = trading.scan_margin_liquidations(actor={"username": "system", "role": "system"}, limit=10)

    assert position_risk["liquidation_required"] is True
    assert account_risk["mode"] == "cross_margin"
    assert account_risk["liquidation_required"] is False
    assert account_risk["free_margin_points"] > 0
    assert result["liquidated"] == []
    assert trading.user_dashboard(user_id=1)["margin_positions"][0]["position_uuid"] == opened["position"]["position_uuid"]
    assert trading.user_dashboard(user_id=1)["margin_positions"][0]["status"] == "open"


def test_margin_scan_notifies_user_when_position_is_near_liquidation(tmp_path):
    points, trading = _services(tmp_path)
    points.record_transaction(user_id=1, currency_type="points", direction="credit", amount=2000, action_type="test_funding")
    trading.update_root_settings(
        actor=_actor(3, "root", "super_admin"),
        settings={
            "borrowing_enabled": True,
            "margin_liquidation_enabled": True,
            "margin_maintenance_percent": 15,
            "price_source": "manual_root",
        },
        markets=[],
    )
    opened = trading.open_margin_position(
        actor=_actor(),
        market_symbol="ETH/POINTS",
        position_type="margin_long",
        quantity="0.1",
        collateral_points=120,
    )

    trading.update_market(actor=_actor(3, "root", "super_admin"), symbol="ETH/POINTS", manual_price_points=4550, confirm_jump=True)
    first_scan = trading.scan_margin_liquidations(actor={"username": "system", "role": "system"}, limit=10)
    second_scan = trading.scan_margin_liquidations(actor={"username": "system", "role": "system"}, limit=10)

    assert first_scan["liquidated"] == []
    assert second_scan["liquidated"] == []
    notes = [row for row in _notifications(trading, 1) if row["type"] == "trading_margin_near_liquidation"]
    assert len(notes) == 1
    assert "進階交易接近強平" == notes[0]["title"]
    assert opened["position"]["position_uuid"] in notes[0]["body"]
    assert "強平價" in notes[0]["body"]


def test_margin_scan_notifies_user_when_price_jumps_sharply(tmp_path):
    points, trading = _services(tmp_path)
    points.record_transaction(user_id=1, currency_type="points", direction="credit", amount=2000, action_type="test_funding")
    trading.update_root_settings(
        actor=_actor(3, "root", "super_admin"),
        settings={
            "borrowing_enabled": True,
            "margin_liquidation_enabled": True,
            "price_source": "manual_root",
        },
        markets=[],
    )
    trading.update_market(
        actor=_actor(3, "root", "super_admin"),
        symbol="ETH/POINTS",
        max_price_jump_percent=10,
        confirm_jump=True,
    )
    opened = trading.open_margin_position(
        actor=_actor(),
        market_symbol="ETH/POINTS",
        position_type="margin_long",
        quantity="0.1",
        collateral_points=200,
    )

    trading.update_market(actor=_actor(3, "root", "super_admin"), symbol="ETH/POINTS", manual_price_points=5700, confirm_jump=True)
    trading.scan_margin_liquidations(actor={"username": "system", "role": "system"}, limit=10)
    trading.scan_margin_liquidations(actor={"username": "system", "role": "system"}, limit=10)

    notes = [row for row in _notifications(trading, 1) if row["type"] == "trading_margin_price_jump"]
    assert len(notes) == 1
    assert "進階交易價格大幅波動" == notes[0]["title"]
    assert opened["position"]["position_uuid"] in notes[0]["body"]
    assert "14.00%" in notes[0]["body"]


def test_force_liquidation_rechecks_recovered_position(tmp_path):
    points, trading = _services(tmp_path)
    points.record_transaction(user_id=1, currency_type="points", direction="credit", amount=1000, action_type="test_funding")
    trading.update_root_settings(
        actor=_actor(3, "root", "super_admin"),
        settings={"borrowing_enabled": True, "margin_liquidation_enabled": True, "margin_maintenance_percent": 15},
        markets=[],
    )
    opened = trading.open_margin_position(
        actor=_actor(),
        market_symbol="ETH/POINTS",
        position_type="margin_long",
        quantity="0.1",
        collateral_points=200,
    )

    with pytest.raises(ValueError, match="recovered above liquidation"):
        trading.close_margin_position(
            actor={"username": "system", "role": "system"},
            position_uuid=opened["position"]["position_uuid"],
            force_liquidation=True,
        )
    assert trading.user_dashboard(user_id=1)["margin_positions"][0]["status"] == "open"


def test_margin_collateral_tampering_enters_trading_safe_mode(tmp_path):
    points, trading = _services(tmp_path)
    points.record_transaction(user_id=1, currency_type="points", direction="credit", amount=1000, action_type="test_funding")
    trading.update_root_settings(actor=_actor(3, "root", "super_admin"), settings={"borrowing_enabled": True}, markets=[])
    opened = trading.open_margin_position(
        actor=_actor(),
        market_symbol="ETH/POINTS",
        position_type="margin_long",
        quantity="0.1",
        collateral_points=200,
    )
    conn = trading.get_db()
    conn.execute("UPDATE trading_margin_positions SET collateral_points=1 WHERE position_uuid=?", (opened["position"]["position_uuid"],))
    conn.commit()
    conn.close()

    verification = trading.verify_state()

    assert verification["ok"] is False
    assert any(error["type"] == "margin_collateral_lock_mismatch" for error in verification["errors"])


def test_position_replay_mismatch_enters_trading_safe_mode(tmp_path):
    points, trading = _services(tmp_path)
    points.record_transaction(user_id=1, currency_type="points", direction="credit", amount=2000, action_type="test_funding")
    trading.place_order(actor=_actor(), market_symbol="ETH/POINTS", side="buy", order_type="market", quantity="0.1")

    conn = trading.get_db()
    conn.execute("UPDATE trading_spot_positions SET quantity_units=1 WHERE user_id=1 AND market_symbol='ETH/POINTS'")
    conn.commit()
    conn.close()

    verification = trading.verify_state()
    assert verification["ok"] is False
    with pytest.raises(ValueError, match="safe mode"):
        trading.place_order(actor=_actor(), market_symbol="ETH/POINTS", side="buy", order_type="market", quantity="0.01")


def test_reserve_pool_tampering_enters_trading_safe_mode(tmp_path):
    points, trading = _services(tmp_path)
    points.record_transaction(user_id=1, currency_type="points", direction="credit", amount=2000, action_type="test_funding")
    trading.place_order(actor=_actor(), market_symbol="ETH/POINTS", side="buy", order_type="market", quantity="0.1")

    conn = trading.get_db()
    conn.execute("UPDATE trading_reserve_pool SET balance_points=1 WHERE id=1")
    conn.commit()
    conn.close()

    verification = trading.verify_state()
    assert verification["ok"] is False
    assert any(error["type"] == "reserve_pool_replay_mismatch" for error in verification["errors"])
    updated = trading.update_market(actor=_actor(3, "root", "super_admin"), symbol="ETH/POINTS", enabled=False)
    assert updated["market"]["enabled"] is False


def test_open_order_frozen_tampering_enters_trading_safe_mode(tmp_path):
    points, trading = _services(tmp_path)
    points.record_transaction(user_id=1, currency_type="points", direction="credit", amount=2000, action_type="test_funding")
    order = trading.place_order(
        actor=_actor(),
        market_symbol="ETH/POINTS",
        side="buy",
        order_type="limit",
        quantity="0.1",
        limit_price_points=4000,
    )["order"]

    conn = trading.get_db()
    conn.execute("UPDATE trading_orders SET frozen_points=1 WHERE order_uuid=?", (order["order_uuid"],))
    conn.commit()
    conn.close()

    verification = trading.verify_state()
    assert verification["ok"] is False
    assert any(error["type"] == "open_order_total_frozen_points_mismatch" for error in verification["errors"])


def test_sell_order_rejects_zero_net_credit_before_locking_position(tmp_path):
    points, trading = _services(tmp_path)
    points.record_transaction(user_id=1, currency_type="points", direction="credit", amount=2000, action_type="test_funding")
    trading.place_order(actor=_actor(), market_symbol="ETH/POINTS", side="buy", order_type="market", quantity="0.00000001")
    trading.update_market(actor=_actor(3, "root", "super_admin"), symbol="ETH/POINTS", fee_rate_percent=50)

    with pytest.raises(ValueError, match="sell notional after fee"):
        trading.place_order(
            actor=_actor(),
            market_symbol="ETH/POINTS",
            side="sell",
            order_type="limit",
            quantity="0.00000001",
            limit_price_points=5000,
        )

    dashboard = trading.user_dashboard(user_id=1)
    assert dashboard["positions"][0]["locked_quantity_units"] == 0


def test_trading_writes_stop_when_pointschain_enters_safe_mode(tmp_path):
    points, trading = _services(tmp_path)
    points.record_transaction(user_id=1, currency_type="points", direction="credit", amount=2000, action_type="test_funding")

    conn = trading.get_db()
    points.ensure_schema(conn)
    conn.execute(
        """
        INSERT OR REPLACE INTO points_chain_recovery_state (
            id, safe_mode, reason, verification_json, forensic_bundle_id,
            restore_plan_json, created_at, updated_at
        ) VALUES (1, 1, 'chain_verification_failed', '{}', 'bundle-test', '{}', '2026-01-01T00:00:00', '2026-01-01T00:00:00')
        """
    )
    conn.commit()
    conn.close()

    with pytest.raises(ValueError, match="PointsChain safe mode active"):
        trading.place_order(actor=_actor(), market_symbol="ETH/POINTS", side="buy", order_type="market", quantity="0.01")


def test_workflow_branch_steps_are_persisted_and_do_not_repeat(tmp_path):
    _, trading = _services(tmp_path)
    workflow = {
        "version": 1,
        "strategy_kind": "workflow",
        "branches": [{
            "id": "entry",
            "name": "分批進場",
            "priority": 10,
            "logic": "AND",
            "cooldown_seconds": 0,
            "conditions": [{"type": "price_below", "value": 6000}],
            "actions": [
                {"type": "buy_amount", "amount_points": 50, "step": 1},
                {"type": "buy_amount", "amount_points": 60, "step": 2},
            ],
        }],
    }
    trading.save_trading_bot(
        actor=_actor(),
        payload={
            "name": "two step workflow",
            "market_symbol": "ETH/POINTS",
            "side": "buy",
            "order_type": "market",
            "quantity": "0.01",
            "max_runs": 3,
            "cooldown_seconds": 0,
            "workflow_json": workflow,
            "enabled": True,
        },
    )

    first = trading.run_trading_bots(actor=_actor(), limit=10)
    second = trading.run_trading_bots(actor=_actor(), limit=10)
    third = trading.run_trading_bots(actor=_actor(), limit=10)

    assert len(first["triggered"]) == 1
    assert len(second["triggered"]) == 1
    assert third["triggered"] == []
    assert third["skipped"][0]["reason"] == "workflow_not_matched"
    dashboard = trading.user_dashboard(user_id=1)
    assert len(dashboard["orders"]) == 2
    assert dashboard["bots"][0]["run_count"] == 2
    assert dashboard["bots"][0]["execution_state"]["branch_step_counts"]["entry"] == 2


def test_workflow_graph_rejects_action_unreachable_from_start(tmp_path):
    _, trading = _services(tmp_path)
    workflow = {
        "version": 2,
        "strategy_kind": "workflow_graph",
        "start_node_id": "start",
        "nodes": [
            {"id": "start", "type": "start", "outputs": ["out"]},
            {"id": "gate", "type": "condition", "condition": {"type": "price_below", "value": 6000}, "outputs": ["true", "false"]},
            {"id": "buy", "type": "action", "action": {"type": "buy_amount", "amount_points": 50, "step": 1}},
        ],
        "edges": [{"from": "gate", "from_port": "true", "to": "buy", "to_port": "in"}],
    }

    with pytest.raises(ValueError, match="reachable from start"):
        trading.save_trading_bot(
            actor=_actor(),
            payload={
                "name": "unreachable action",
                "market_symbol": "ETH/POINTS",
                "side": "buy",
                "order_type": "market",
                "quantity": "0.01",
                "workflow_json": workflow,
                "enabled": True,
            },
        )
