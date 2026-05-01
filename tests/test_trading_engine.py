import sqlite3

import pytest

from services.points_chain import PointsLedgerService, ensure_points_economy_schema
from services.trading_engine import TradingEngineService, ensure_trading_schema


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


def test_spot_buy_uses_points_chain_and_updates_position(tmp_path):
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
    assert wallet["points_balance"] == 1498
    dashboard = trading.user_dashboard(user_id=1)
    assert dashboard["positions"][0]["market_symbol"] == "ETH/POINTS"
    assert dashboard["positions"][0]["quantity"] == "0.1"
    assert dashboard["futures_positions"] == []
    ledger_actions = [row["action_type"] for row in points.list_ledger(user_id=1, include_user_id=True)]
    assert "trading_freeze" in ledger_actions
    assert "trading_unfreeze" in ledger_actions
    assert "trading_spot_buy" in ledger_actions
    assert "trading_fee" in ledger_actions
    assert trading.root_report()["reserve_pool"]["balance_points"] == 2
    notes = _notifications(trading, 1)
    assert notes[-1]["type"] == "trading_order_filled"
    assert notes[-1]["title"] == "交易已成交"
    assert "ETH/POINTS 買入 0.1 已成交" in notes[-1]["body"]


def test_insufficient_trading_balance_creates_notification(tmp_path):
    _, trading = _services(tmp_path)

    with pytest.raises(ValueError, match="insufficient"):
        trading.place_order(
            actor=_actor(),
            market_symbol="ETH/POINTS",
            side="buy",
            order_type="market",
            quantity="0.1",
        )

    notes = _notifications(trading, 1)
    assert notes[-1]["type"] == "trading_balance_insufficient"
    assert notes[-1]["title"] == "交易未成立：餘額不足"
    assert "ETH/POINTS buy market 數量 0.1 未成立" in notes[-1]["body"]


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
    assert points.get_wallet(1)["points_balance"] == 1995
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
    assert points.get_wallet(1)["points_balance"] == 421


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
    assert trading.root_report()["reserve_pool"]["balance_points"] == 0
    conn = trading.get_db()
    try:
        assert conn.execute("SELECT COUNT(*) FROM points_ledger").fetchone()[0] == 0
    finally:
        conn.close()
    assert trading.verify_state()["ok"] is True

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
    assert points.get_wallet(1)["points_frozen"] == 402

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
    assert points.get_wallet(1)["points_frozen"] == 402

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
    assert trading.root_report()["reserve_pool"]["balance_points"] == 5

    trading.update_market(actor=_actor(3, "root", "super_admin"), symbol="ETH/POINTS", manual_price_points=5000, confirm_jump=True)
    trading.test_prices["ETH/POINTS"] = 5000

    points.record_transaction(user_id=1, currency_type="points", direction="credit", amount=2000, action_type="test_funding_again")
    trading.place_order(actor=_actor(), market_symbol="ETH/POINTS", side="buy", order_type="market", quantity="0.1")
    sold = trading.place_order(actor=_actor(), market_symbol="ETH/POINTS", side="sell", order_type="market", quantity="0.05")
    assert sold["order"]["status"] == "filled"
    ledger_actions = [row["action_type"] for row in points.list_ledger(user_id=1, include_user_id=True)]
    assert ledger_actions.count("trading_fee") == 4
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

    assert result["balance_points"] == 250
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
            "borrow_interest_bps_daily": 25,
            "margin_liquidation_enabled": True,
            "margin_maintenance_bps": 1200,
            "futures_enabled": False,
            "pvp_matching_enabled": False,
        },
        markets=[
            {
                "symbol": "ETH/POINTS",
                "enabled": True,
                "fee_bps": 45,
                "min_order_points": 10,
                "max_order_points": 500000,
            }
        ],
    )

    assert updated["settings"]["borrowing_enabled"] is True
    assert updated["settings"]["borrow_interest_bps_daily"] == 25
    assert updated["settings"]["margin_liquidation_enabled"] is True
    assert updated["settings"]["margin_maintenance_bps"] == 1200
    market = next(row for row in updated["markets"] if row["symbol"] == "ETH/POINTS")
    assert market["fee_bps"] == 45
    assert market["min_order_points"] == 10
    assert market["max_order_points"] == 500000
    report = trading.root_report()
    assert report["settings"]["borrowing_enabled"] is True
    assert report["audit_events"][0]["event_type"] in {"TRADING_MARKET_BILLING_UPDATED", "TRADING_SETTINGS_UPDATED"}


def test_margin_long_requires_root_enabled_borrowing_and_closes_with_fee_stats(tmp_path):
    points, trading = _services(tmp_path)
    points.record_transaction(user_id=1, currency_type="points", direction="credit", amount=1000, action_type="test_funding")

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
        settings={"borrowing_enabled": True, "borrow_interest_bps_daily": 10},
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
    assert points.get_wallet(1)["points_balance"] == 798
    assert points.get_wallet(1)["points_frozen"] == 200
    assert trading.root_report()["reserve_pool"]["balance_points"] == 2

    closed = trading.close_margin_position(actor=_actor(), position_uuid=opened["position"]["position_uuid"])
    assert closed["position"]["status"] == "closed"
    assert closed["delta_points"] == -2
    assert points.get_wallet(1)["points_frozen"] == 0
    assert trading.root_report()["reserve_pool"]["balance_points"] == 4
    assert trading.verify_state()["ok"] is True


def test_short_borrow_position_profit_and_interest_enter_reserve_pool(tmp_path):
    points, trading = _services(tmp_path)
    points.record_transaction(user_id=1, currency_type="points", direction="credit", amount=1000, action_type="test_funding")
    trading.update_root_settings(
        actor=_actor(3, "root", "super_admin"),
        settings={"borrowing_enabled": True, "borrow_interest_bps_daily": 100, "price_source": "manual_root"},
        markets=[],
    )
    opened = trading.open_margin_position(
        actor=_actor(),
        market_symbol="ETH/POINTS",
        position_type="short",
        quantity="0.1",
        collateral_points=200,
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
    assert closed["interest_points"] == 10
    assert closed["delta_points"] == 88
    assert trading.root_report()["reserve_pool"]["balance_points"] == 14
    assert trading.verify_state()["ok"] is True


def test_margin_liquidation_scan_closes_underwater_position(tmp_path):
    points, trading = _services(tmp_path)
    points.record_transaction(user_id=1, currency_type="points", direction="credit", amount=1000, action_type="test_funding")
    trading.update_root_settings(
        actor=_actor(3, "root", "super_admin"),
        settings={
            "borrowing_enabled": True,
            "borrow_interest_bps_daily": 0,
            "margin_liquidation_enabled": True,
            "margin_maintenance_bps": 1500,
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
    assert result["liquidated"][0]["risk"]["liquidation_required"] is True
    dashboard = trading.user_dashboard(user_id=1)
    assert dashboard["margin_positions"][0]["status"] == "liquidated"
    assert points.get_wallet(1)["points_frozen"] == 0
    notices = _notifications(trading, 1)
    assert any(row["type"] == "trading_margin_liquidated" for row in notices)
    assert trading.root_report()["reserve_pool"]["balance_points"] == 3
    assert trading.verify_state()["ok"] is True


def test_force_liquidation_rechecks_recovered_position(tmp_path):
    points, trading = _services(tmp_path)
    points.record_transaction(user_id=1, currency_type="points", direction="credit", amount=1000, action_type="test_funding")
    trading.update_root_settings(
        actor=_actor(3, "root", "super_admin"),
        settings={"borrowing_enabled": True, "margin_liquidation_enabled": True, "margin_maintenance_bps": 1500},
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
    assert any(error["type"] == "open_order_frozen_points_mismatch" for error in verification["errors"])


def test_sell_order_rejects_zero_net_credit_before_locking_position(tmp_path):
    points, trading = _services(tmp_path)
    points.record_transaction(user_id=1, currency_type="points", direction="credit", amount=2000, action_type="test_funding")
    trading.place_order(actor=_actor(), market_symbol="ETH/POINTS", side="buy", order_type="market", quantity="0.00000001")
    trading.update_market(actor=_actor(3, "root", "super_admin"), symbol="ETH/POINTS", fee_bps=5000)

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
