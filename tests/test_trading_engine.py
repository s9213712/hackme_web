import sqlite3
from pathlib import Path

import pytest

import services.trading_engine as trading_engine_module
from services.points_chain import PointsLedgerService, ensure_points_economy_schema
from services.trading_engine import TradingEngineService, ensure_trading_schema


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


def _actor(user_id=1, username="alice", role="user"):
    return {"id": user_id, "username": username, "role": role}


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
    ignored_dirs = {".git", "__pycache__", ".pytest_cache", "node_modules", "storage", "reports", "secure_backups"}
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
    assert dashboard["funding"]["trial_credit"]["available_points"] == 498
    assert dashboard["funding"]["trial_credit"]["deployed_points"] == 502
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
    assert fill["fee_points"] == 4
    assert dashboard["funding"]["trial_credit"]["available_points"] == 0
    assert dashboard["funding"]["trial_credit"]["deployed_points"] == 1000

    ledger_rows = points.list_ledger(user_id=1, include_user_id=True)
    trading_rows = [row for row in ledger_rows if row["reference_id"] == result["order"]["order_uuid"]]
    amounts_by_action = {row["action_type"]: row["amount"] for row in trading_rows}
    assert amounts_by_action == {
        "trading_freeze": 254,
        "trading_unfreeze": 254,
        "trading_spot_buy": 254,
    }
    assert points.get_wallet(1)["points_balance"] == 1746


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


def test_backtest_trading_bot_rejects_excessive_candle_count(tmp_path):
    _, trading = _services(tmp_path)

    with pytest.raises(ValueError, match="candles length"):
        trading.backtest_trading_bot(
            actor=_actor(),
            payload={
                "market_symbol": "ETH/POINTS",
                "strategy": "dca",
                "candles": [{"time": index, "close_points": 5000} for index in range(5001)],
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
    assert close["order"]["fee_points"] == 3
    dashboard = trading.user_dashboard(user_id=1)
    assert dashboard["positions"][0]["quantity"] == "0"
    assert dashboard["fills"][0]["fee_points"] == 3
    assert points.get_wallet(1)["points_balance"] == 2000
    assert dashboard["funding"]["trial_credit"]["available_points"] == 995
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
    assert points.get_wallet(1)["points_balance"] == 96
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
    assert position["estimated_buy_fee_points"] == 2
    assert position["estimated_exit_fee_points"] == 2
    assert position["cost_basis_points"] == 504
    assert position["unrealized_pnl_points"] == 96
    assert dashboard_after_buy["spot_summary"]["unrealized_pnl_points"] == 96

    trading.place_order(actor=_actor(), market_symbol="ETH/POINTS", side="sell", order_type="market", quantity="0.04")

    dashboard_after_sell = trading.user_dashboard(user_id=1)
    position_after_sell = dashboard_after_sell["positions"][0]
    assert position_after_sell["quantity"] == "0.06"
    assert position_after_sell["gross_cost_points"] == 300
    assert position_after_sell["current_value_points"] == 360
    assert position_after_sell["estimated_buy_fee_points"] == 1
    assert position_after_sell["estimated_exit_fee_points"] == 2
    assert position_after_sell["cost_basis_points"] == 303
    assert position_after_sell["unrealized_pnl_points"] == 57
    assert position_after_sell["realized_pnl_points"] == 38
    assert position_after_sell["total_fee_points"] == 3
    assert dashboard_after_sell["spot_summary"]["realized_pnl_points"] == 38
    assert dashboard_after_sell["fills"][0]["realized_pnl_points"] == 38
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
    assert dashboard["funding"]["available_points"] == 9498
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
    assert contract["funding"]["available_points"] == 9473
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
    assert order["trial_frozen_points"] == 402

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
    assert order["trial_frozen_points"] == 402

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
    assert trading.root_report()["reserve_pool"]["balance_points"] == 10003

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
            "borrow_interest_percent_daily": 0.25,
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
    assert updated["settings"]["borrow_interest_percent_daily"] == 0.25
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

    settings = trading.get_root_settings()["settings"]

    assert settings["borrowing_enabled"] is True


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
    assert opened["position"]["open_fee_trial_points"] == 2
    assert points.get_wallet(1)["points_balance"] == 1000
    assert points.get_wallet(1)["points_frozen"] == 0
    assert opened["funding"]["trial_credit"]["available_points"] == 798
    assert opened["funding"]["trial_credit"]["deployed_points"] == 200
    assert opened["position"]["interest_percent_daily"] == pytest.approx(11.2)
    assert trading.root_report()["reserve_pool"]["balance_points"] == 9702

    closed = trading.close_margin_position(actor=_actor(), position_uuid=opened["position"]["position_uuid"])
    assert closed["position"]["status"] == "closed"
    assert closed["interest_points"] == 0
    assert closed["position"]["interest_paid_points"] == 2
    assert closed["delta_points"] == -2
    assert points.get_wallet(1)["points_frozen"] == 0
    assert closed["funding"]["trial_credit"]["available_points"] == 996
    assert closed["funding"]["trial_credit"]["deployed_points"] == 0
    assert trading.root_report()["reserve_pool"]["balance_points"] == 10006
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
        assert trading._margin_interest_points(row, now_text="2026-05-02T10:00:01") == 4
        assert trading._margin_interest_points(row, now_text="2026-05-02T10:59:59") == 4
        assert trading._margin_interest_points(row, now_text="2026-05-02T11:00:00") == 4
        assert trading._margin_interest_points(row, now_text="2026-05-02T11:00:01") == 7
        assert trading._margin_interest_points(row, now_text="2026-05-03T09:59:59") == 81
    finally:
        conn.close()


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

    with pytest.raises(ValueError, match="collateral below minimum 78"):
        trading.open_margin_position(
            actor=_actor(),
            market_symbol="ETH/POINTS",
            position_type="margin_long",
            quantity="0.1",
            collateral_points=77,
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
        collateral_points=78,
    )
    long_risk = trading.user_dashboard(user_id=1)["margin_positions"][0]["risk"]
    assert long_risk["liquidation_price_points"] < long_position["position"]["entry_price_points"]
    trading.close_margin_position(actor=_actor(), position_uuid=long_position["position"]["position_uuid"])

    with pytest.raises(ValueError, match="collateral below minimum 78"):
        trading.open_margin_position(
            actor=_actor(),
            market_symbol="ETH/POINTS",
            position_type="short",
            quantity="0.1",
            collateral_points=77,
        )
    short_position = trading.open_margin_position(
        actor=_actor(),
        market_symbol="ETH/POINTS",
        position_type="short",
        quantity="0.1",
        collateral_points=78,
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
    assert dashboard["margin_positions"][0]["interest_paid_points"] == 1
    assert trading.root_report()["reserve_pool"]["balance_points"] == 9703
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
    assert accrued["interest_points"] == 7
    conn = trading.get_db()
    try:
        position = conn.execute(
            "SELECT * FROM trading_margin_positions WHERE position_uuid=?",
            (opened["position"]["position_uuid"],),
        ).fetchone()
    finally:
        conn.close()
    assert position["interest_points"] == 7
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
        settings={"borrowing_enabled": True, "borrow_interest_percent_daily": 1, "price_source": "manual_root"},
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
    assert closed["position"]["interest_paid_points"] == 13
    assert closed["delta_points"] == 98
    assert trading.root_report()["reserve_pool"]["balance_points"] == 9919
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
    assert trading.root_report()["reserve_pool"]["balance_points"] == 10003
    assert trading.verify_state()["ok"] is True


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
