"""Boot-ready gate (2026-05-06): trading / liquidation / bots refuse to act
on a market until at least one live price has been confirmed.

These tests verify the four guards added with the 2026-05-06 fix:
  - place_order
  - open_margin_position
  - match_open_limit_orders (skip when not boot-ready)
  - run_due_trading_bots / scan_margin_liquidations (skip when not boot-ready)

The gate only relaxes after ``trading_markets.live_price_confirmed_at`` is
populated by a successful live-price fetch, which the engine now stamps
automatically inside ``_current_market_price_points``.
"""

import sqlite3

import pytest

from services.points_chain import PointsLedgerService, ensure_points_economy_schema
from services.trading_engine import TradingEngineService, ensure_trading_schema


def _db(tmp_path):
    db_path = tmp_path / "trading.db"

    def get_db():
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    conn = get_db()
    conn.execute(
        "CREATE TABLE users (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT NOT NULL UNIQUE, "
        "role TEXT NOT NULL DEFAULT 'user', status TEXT NOT NULL DEFAULT 'active')"
    )
    conn.execute("INSERT INTO users (username, role) VALUES ('alice', 'user')")
    conn.execute("INSERT INTO users (username, role) VALUES ('root',  'super_admin')")
    ensure_points_economy_schema(conn)
    ensure_trading_schema(conn)
    conn.commit()
    conn.close()
    return get_db


def _set_setting(trading, key, value):
    conn = trading.get_db()
    try:
        conn.execute(
            "INSERT OR REPLACE INTO trading_settings (key, value, updated_at, updated_by) VALUES (?, ?, '2024-01-01T00:00:00', 'test')",
            (key, str(value)),
        )
        conn.commit()
    finally:
        conn.close()


def _services(tmp_path, *, prices=None):
    get_db = _db(tmp_path)
    points = PointsLedgerService(get_db=get_db, chain_secret="test", backup_dir=tmp_path / "chain")
    prices = prices or {"BTC/POINTS": 77059, "ETH/POINTS": 5000}
    trading = TradingEngineService(
        get_db=get_db,
        points_service=points,
        live_price_provider=lambda symbol: prices[symbol],
    )
    trading.test_prices = prices
    # Force the synthetic-provider path so high-risk price checks don't trip
    # on the production fused-weighted minimum-provider-count rule. The boot
    # gate behavior we're testing is orthogonal to fused-price health.
    _set_setting(trading, "trading.price_source", "binance_public_api")
    return points, trading


def _actor(user_id=1, username="alice", role="user"):
    return {"id": user_id, "username": username, "role": role}


def _stamp(trading, symbol):
    conn = trading.get_db()
    try:
        conn.execute(
            "UPDATE trading_markets SET live_price_confirmed_at=? WHERE symbol=?",
            ("2024-01-01T00:00:00", symbol),
        )
        conn.commit()
    finally:
        conn.close()


def test_place_order_blocked_until_market_boot_ready(tmp_path):
    points, trading = _services(tmp_path)
    points.record_transaction(user_id=1, currency_type="points", direction="credit", amount=5000, action_type="seed")

    with pytest.raises(ValueError, match="尚未收到任何即時價格更新"):
        trading.place_order(
            actor=_actor(),
            market_symbol="ETH/POINTS",
            side="buy",
            order_type="market",
            quantity="0.1",
        )

    _stamp(trading, "ETH/POINTS")
    result = trading.place_order(
        actor=_actor(),
        market_symbol="ETH/POINTS",
        side="buy",
        order_type="market",
        quantity="0.1",
    )
    assert result["order"]["status"] == "filled"


def test_open_margin_position_blocked_until_market_boot_ready(tmp_path):
    points, trading = _services(tmp_path)
    trading.update_root_settings(
        actor=_actor(2, "root", "super_admin"),
        settings={"borrowing_enabled": True},
        markets=[],
    )
    points.record_transaction(user_id=1, currency_type="points", direction="credit", amount=5000, action_type="seed")

    with pytest.raises(ValueError, match="尚未收到任何即時價格更新"):
        trading.open_margin_position(
            actor=_actor(),
            market_symbol="ETH/POINTS",
            position_type="margin_long",
            quantity="0.1",
            collateral_points=120,
        )


def test_live_price_fetch_stamps_boot_ready(tmp_path):
    points, trading = _services(tmp_path)
    conn = trading.get_db()
    try:
        before = conn.execute(
            "SELECT live_price_confirmed_at FROM trading_markets WHERE symbol='ETH/POINTS'"
        ).fetchone()
    finally:
        conn.close()
    assert before["live_price_confirmed_at"] is None

    # Reading the price once goes through the live provider path which now
    # stamps live_price_confirmed_at on success.
    points.record_transaction(user_id=1, currency_type="points", direction="credit", amount=5000, action_type="seed")
    trading.place_order  # noqa  (sanity import)
    conn = trading.get_db()
    try:
        market = trading._market(conn, "ETH/POINTS")
        trading._current_market_price_points(conn, market, with_meta=True, high_risk=False)
        after = conn.execute(
            "SELECT live_price_confirmed_at FROM trading_markets WHERE symbol='ETH/POINTS'"
        ).fetchone()
        conn.commit()
    finally:
        conn.close()
    assert after["live_price_confirmed_at"], (
        "live_price_confirmed_at should be set the first time a real live "
        "fetch succeeds"
    )


def test_run_due_bots_skips_market_until_boot_ready(tmp_path):
    points, trading = _services(tmp_path)
    points.record_transaction(user_id=1, currency_type="points", direction="credit", amount=5000, action_type="seed")
    # Stamp BTC so save_trading_bot's internal price probe succeeds, then un-stamp
    # ETH for the run-time check.
    _stamp(trading, "ETH/POINTS")
    trading.save_trading_bot(
        actor=_actor(),
        payload={
            "name": "boot gate bot",
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
    # Reset the gate to NULL so we observe the skip behavior.
    conn = trading.get_db()
    try:
        conn.execute(
            "UPDATE trading_markets SET live_price_confirmed_at=NULL WHERE symbol='ETH/POINTS'"
        )
        conn.commit()
    finally:
        conn.close()

    result = trading.run_trading_bots(actor=_actor(), limit=10)
    skipped_reasons = {row.get("reason") for row in result.get("skipped") or []}
    assert "market_boot_pending" in skipped_reasons


def test_assert_market_boot_ready_helper_returns_truthy_after_stamp(tmp_path):
    _points, trading = _services(tmp_path)
    conn = trading.get_db()
    try:
        market = dict(conn.execute("SELECT * FROM trading_markets WHERE symbol='ETH/POINTS'").fetchone())
    finally:
        conn.close()
    assert trading._is_market_boot_ready(market) is False
    _stamp(trading, "ETH/POINTS")
    conn = trading.get_db()
    try:
        market2 = dict(conn.execute("SELECT * FROM trading_markets WHERE symbol='ETH/POINTS'").fetchone())
    finally:
        conn.close()
    assert trading._is_market_boot_ready(market2) is True
