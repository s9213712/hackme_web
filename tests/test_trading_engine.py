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
    trading = TradingEngineService(get_db=get_db, points_service=points)
    return points, trading


def _actor(user_id=1, username="alice", role="user"):
    return {"id": user_id, "username": username, "role": role}


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
    ledger_actions = [row["action_type"] for row in points.list_ledger(user_id=1, include_user_id=True)]
    assert "trading_freeze" in ledger_actions
    assert "trading_unfreeze" in ledger_actions
    assert "trading_spot_buy" in ledger_actions
    assert "trading_fee" in ledger_actions
    assert trading.root_report()["reserve_pool"]["balance_points"] == 502


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


def test_sell_requires_reserve_pool_and_never_mints_points(tmp_path):
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

    with pytest.raises(ValueError, match="reserve pool is insufficient"):
        trading.place_order(actor=_actor(), market_symbol="ETH/POINTS", side="sell", order_type="market", quantity="0.05")

    trading.update_market(actor=_actor(3, "root", "super_admin"), symbol="ETH/POINTS", manual_price_points=5000, confirm_jump=True)

    sold = trading.place_order(actor=_actor(), market_symbol="ETH/POINTS", side="sell", order_type="market", quantity="0.05")
    assert sold["order"]["status"] == "filled"
    assert points.get_wallet(1)["points_balance"] == 1747
    ledger_actions = [row["action_type"] for row in points.list_ledger(user_id=1, include_user_id=True)]
    assert ledger_actions.count("trading_fee") == 2
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
    with pytest.raises(ValueError, match="safe mode"):
        trading.update_market(actor=_actor(3, "root", "super_admin"), symbol="ETH/POINTS", fee_bps=20)


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
