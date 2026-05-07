"""Boot-ready gate (2026-05-06): trading / liquidation / bots refuse to act
on a market until at least one live price has been confirmed.

These tests verify the high-risk guards added with the 2026-05-06 fix:
  - place_order
  - open_margin_position
  - match_open_limit_orders (skip when not boot-ready)
  - run_due_trading_bots / scan_margin_liquidations (skip when not boot-ready)
  - root contract open / close
  - grid bot create / scan
  - trial credit forced sell

The gate only relaxes after ``trading_markets.live_price_confirmed_at`` is
populated by two stable live-price observations. The first successful fetch
only starts warmup; it must not immediately release bots or other high-risk
paths.
"""

import sqlite3
from datetime import datetime

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


def _set_manual_root_price(trading, *, symbol, price_points):
    root = _actor(2, "root", "super_admin")
    trading.update_root_settings(actor=root, settings={"price_source": "manual_root"}, markets=[])
    trading.update_market(
        actor=root,
        symbol=symbol,
        manual_price_points=price_points,
        confirm_jump=True,
    )


def _prime_cached_live_price(trading, *, symbol, price_points):
    conn = trading.get_db()
    try:
        conn.execute(
            """
            UPDATE trading_markets
            SET manual_price_points=?, price_source='binance_public_api', updated_at=?, live_price_confirmed_at=COALESCE(live_price_confirmed_at, ?)
            WHERE symbol=?
            """,
            (price_points, datetime.now().isoformat(), "2024-01-01T00:00:00", symbol),
        )
        conn.commit()
    finally:
        conn.close()


def _force_live_provider_failure(trading, message="provider down"):
    def _raiser(_symbol):
        raise RuntimeError(message)

    trading.live_price_provider = _raiser


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


def test_live_price_fetch_requires_second_stable_sample_before_boot_ready(tmp_path):
    points, trading = _services(tmp_path)
    conn = trading.get_db()
    try:
        before = conn.execute(
            "SELECT live_price_warmup_started_at, live_price_confirmed_at FROM trading_markets WHERE symbol='ETH/POINTS'"
        ).fetchone()
    finally:
        conn.close()
    assert before["live_price_warmup_started_at"] is None
    assert before["live_price_confirmed_at"] is None

    # First live quote only starts warmup; it must not immediately release
    # high-risk trading paths.
    points.record_transaction(user_id=1, currency_type="points", direction="credit", amount=5000, action_type="seed")
    trading.place_order  # noqa  (sanity import)
    conn = trading.get_db()
    try:
        market = trading._market(conn, "ETH/POINTS")
        trading._current_market_price_points(conn, market, with_meta=True, high_risk=False)
        warmup = conn.execute(
            "SELECT live_price_warmup_started_at, live_price_confirmed_at FROM trading_markets WHERE symbol='ETH/POINTS'"
        ).fetchone()
        conn.commit()
    finally:
        conn.close()
    assert warmup["live_price_warmup_started_at"], (
        "the first real live fetch should start warmup so the seed/default "
        "price is no longer the pending candidate"
    )
    assert warmup["live_price_confirmed_at"] is None

    with pytest.raises(ValueError, match="尚未收到任何即時價格更新"):
        trading.place_order(
            actor=_actor(),
            market_symbol="ETH/POINTS",
            side="buy",
            order_type="market",
            quantity="0.1",
        )

    conn = trading.get_db()
    try:
        market = trading._market(conn, "ETH/POINTS")
        trading._current_market_price_points(conn, market, with_meta=True, high_risk=False)
        confirmed = conn.execute(
            "SELECT live_price_warmup_started_at, live_price_confirmed_at FROM trading_markets WHERE symbol='ETH/POINTS'"
        ).fetchone()
        conn.commit()
    finally:
        conn.close()
    assert confirmed["live_price_warmup_started_at"] is None
    assert confirmed["live_price_confirmed_at"], (
        "a second stable live quote should release the boot-ready gate"
    )


def test_first_quote_from_default_does_not_release_bot_gate(tmp_path):
    points, trading = _services(tmp_path)
    points.record_transaction(user_id=1, currency_type="points", direction="credit", amount=5000, action_type="seed")
    _stamp(trading, "ETH/POINTS")
    trading.save_trading_bot(
        actor=_actor(),
        payload={
            "name": "warmup gate bot",
            "market_symbol": "ETH/POINTS",
            "trigger_type": "price_above",
            "trigger_price_points": 100,
            "side": "buy",
            "order_type": "market",
            "quantity": "0.01",
            "max_runs": 1,
            "cooldown_seconds": 0,
            "enabled": True,
        },
    )
    conn = trading.get_db()
    try:
        conn.execute(
            "UPDATE trading_markets SET live_price_warmup_started_at=NULL, live_price_confirmed_at=NULL WHERE symbol='ETH/POINTS'"
        )
        conn.commit()
    finally:
        conn.close()

    quote = trading.get_live_market_quote(market_symbol="ETH/POINTS")
    assert quote["price_health"] == "boot_pending"
    assert quote["high_risk_blocked"] is True

    first_run = trading.run_trading_bots(actor=_actor(), limit=10)
    assert {row.get("reason") for row in first_run.get("skipped") or []} == {"market_boot_pending"}

    conn = trading.get_db()
    try:
        assert int(conn.execute("SELECT COUNT(*) FROM trading_orders").fetchone()[0] or 0) == 0
    finally:
        conn.close()

    second_quote = trading.get_live_market_quote(market_symbol="ETH/POINTS")
    assert second_quote["price_health"] != "boot_pending"

    second_run = trading.run_trading_bots(actor=_actor(), limit=10)
    assert len(second_run.get("triggered") or []) == 1


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


def test_manual_root_high_risk_price_blocked_until_market_boot_ready(tmp_path):
    _points, trading = _services(tmp_path)
    _set_manual_root_price(trading, symbol="ETH/POINTS", price_points=5000)
    conn = trading.get_db()
    try:
        market = trading._market(conn, "ETH/POINTS")
        _price, _source, meta = trading._current_market_price_points(
            conn,
            market,
            with_meta=True,
            high_risk=True,
        )
    finally:
        conn.close()
    assert meta["high_risk_blocked"] is True
    assert "手動價格" in meta["high_risk_block_reason"]

    _stamp(trading, "ETH/POINTS")
    conn = trading.get_db()
    try:
        market = trading._market(conn, "ETH/POINTS")
        _price, _source, stamped_meta = trading._current_market_price_points(
            conn,
            market,
            with_meta=True,
            high_risk=True,
        )
    finally:
        conn.close()
    assert stamped_meta["high_risk_blocked"] is True


def test_cached_fallback_high_risk_price_is_blocked(tmp_path):
    _points, trading = _services(tmp_path)
    _stamp(trading, "ETH/POINTS")
    _prime_cached_live_price(trading, symbol="ETH/POINTS", price_points=5000)
    _force_live_provider_failure(trading, message="cached fallback test")
    conn = trading.get_db()
    try:
        market = trading._market(conn, "ETH/POINTS")
        _price, _source, meta = trading._current_market_price_points(
            conn,
            market,
            with_meta=True,
            high_risk=True,
        )
    finally:
        conn.close()
    assert meta["high_risk_blocked"] is True
    assert meta["fallback"] is True
    assert meta["risk_grade_usable"] is False


def test_contract_open_rejects_market_boot_pending(tmp_path):
    _points, trading = _services(tmp_path)
    root = _actor(2, "root", "super_admin")
    trading.update_root_settings(
        actor=root,
        settings={"futures_enabled": True},
        markets=[{"symbol": "ETH/POINTS", "futures_enabled": True}],
    )

    with pytest.raises(ValueError, match="尚未收到任何即時價格更新"):
        trading.open_root_contract_position(
            actor=root,
            market_symbol="ETH/POINTS",
            side="long",
            quantity="0.01",
            leverage=2,
            margin_points=25,
        )


def test_contract_close_rejects_market_boot_pending(tmp_path):
    _points, trading = _services(tmp_path)
    root = _actor(2, "root", "super_admin")
    trading.update_root_settings(
        actor=root,
        settings={"futures_enabled": True},
        markets=[{"symbol": "ETH/POINTS", "futures_enabled": True}],
    )
    _stamp(trading, "ETH/POINTS")
    opened = trading.open_root_contract_position(
        actor=root,
        market_symbol="ETH/POINTS",
        side="long",
        quantity="0.01",
        leverage=2,
        margin_points=25,
    )
    conn = trading.get_db()
    try:
        conn.execute(
            "UPDATE trading_markets SET live_price_confirmed_at=NULL WHERE symbol='ETH/POINTS'"
        )
        conn.commit()
    finally:
        conn.close()

    with pytest.raises(ValueError, match="尚未收到任何即時價格更新"):
        trading.close_root_contract_position(
            actor=root,
            position_uuid=opened["position"]["position_uuid"],
        )


def test_contract_open_rejects_manual_root_price(tmp_path):
    _points, trading = _services(tmp_path)
    root = _actor(2, "root", "super_admin")
    trading.update_root_settings(
        actor=root,
        settings={"futures_enabled": True},
        markets=[{"symbol": "ETH/POINTS", "futures_enabled": True}],
    )
    _stamp(trading, "ETH/POINTS")
    _set_manual_root_price(trading, symbol="ETH/POINTS", price_points=5000)

    with pytest.raises(ValueError, match="手動價格"):
        trading.open_root_contract_position(
            actor=root,
            market_symbol="ETH/POINTS",
            side="long",
            quantity="0.01",
            leverage=2,
            margin_points=25,
        )


def test_contract_close_rejects_cached_fallback_price(tmp_path):
    _points, trading = _services(tmp_path)
    root = _actor(2, "root", "super_admin")
    trading.update_root_settings(
        actor=root,
        settings={"futures_enabled": True},
        markets=[{"symbol": "ETH/POINTS", "futures_enabled": True}],
    )
    _stamp(trading, "ETH/POINTS")
    opened = trading.open_root_contract_position(
        actor=root,
        market_symbol="ETH/POINTS",
        side="long",
        quantity="0.01",
        leverage=2,
        margin_points=25,
    )
    _prime_cached_live_price(trading, symbol="ETH/POINTS", price_points=5000)
    _force_live_provider_failure(trading, message="cached fallback contract close")

    with pytest.raises(ValueError, match="conservative mode|快取|cached"):
        trading.close_root_contract_position(
            actor=root,
            position_uuid=opened["position"]["position_uuid"],
        )


def test_grid_create_rejects_market_boot_pending(tmp_path):
    _points, trading = _services(tmp_path)

    with pytest.raises(ValueError, match="尚未收到任何即時價格更新"):
        trading.create_grid_bot(
            actor=_actor(),
            payload={
                "name": "boot gate grid",
                "market_symbol": "ETH/POINTS",
                "lower_price_points": 4900,
                "upper_price_points": 5100,
                "grid_count": 3,
                "order_amount_points": 100,
            },
        )


def test_grid_scan_rejects_market_boot_pending(tmp_path):
    points, trading = _services(tmp_path)
    points.record_transaction(user_id=1, currency_type="points", direction="credit", amount=1000, action_type="seed")
    _stamp(trading, "ETH/POINTS")
    created = trading.create_grid_bot(
        actor=_actor(),
        payload={
            "name": "boot gate grid scan",
            "market_symbol": "ETH/POINTS",
            "lower_price_points": 4900,
            "upper_price_points": 5100,
            "grid_count": 3,
            "order_amount_points": 100,
        },
    )
    assert created["ok"] is True
    conn = trading.get_db()
    try:
        conn.execute(
            "UPDATE trading_markets SET live_price_confirmed_at=NULL WHERE symbol='ETH/POINTS'"
        )
        conn.commit()
    finally:
        conn.close()

    scanned = trading.scan_grid_bots(actor=_actor())
    assert scanned["results"]
    assert "尚未收到任何即時價格更新" in str(scanned["results"][0].get("grid_scan_blocked_reason") or "")


def test_grid_scan_rejects_manual_root_price(tmp_path):
    points, trading = _services(tmp_path)
    points.record_transaction(user_id=1, currency_type="points", direction="credit", amount=1000, action_type="seed")
    _stamp(trading, "ETH/POINTS")
    trading.create_grid_bot(
        actor=_actor(),
        payload={
            "name": "manual root grid scan",
            "market_symbol": "ETH/POINTS",
            "lower_price_points": 4900,
            "upper_price_points": 5100,
            "grid_count": 3,
            "order_amount_points": 100,
        },
    )
    _set_manual_root_price(trading, symbol="ETH/POINTS", price_points=5000)

    scanned = trading.scan_grid_bots(actor=_actor())
    assert scanned["results"]
    assert "手動價格" in str(scanned["results"][0].get("grid_scan_blocked_reason") or "")


def test_grid_scan_does_not_fill_or_counter_order_on_fallback_price(tmp_path):
    points, trading = _services(tmp_path)
    points.record_transaction(user_id=1, currency_type="points", direction="credit", amount=1000, action_type="seed")
    _stamp(trading, "ETH/POINTS")
    created = trading.create_grid_bot(
        actor=_actor(),
        payload={
            "name": "cached fallback grid scan",
            "market_symbol": "ETH/POINTS",
            "lower_price_points": 4900,
            "upper_price_points": 5100,
            "grid_count": 3,
            "order_amount_points": 100,
        },
    )
    bot_uuid = created["bot"]["bot_uuid"]
    conn = trading.get_db()
    try:
        before = conn.execute(
            "SELECT COUNT(*) FROM trading_grid_orders WHERE grid_bot_id=(SELECT id FROM trading_grid_bots WHERE bot_uuid=?)",
            (bot_uuid,),
        ).fetchone()[0]
        open_before = conn.execute(
            "SELECT COUNT(*) FROM trading_grid_orders WHERE grid_bot_id=(SELECT id FROM trading_grid_bots WHERE bot_uuid=?) AND status='open'",
            (bot_uuid,),
        ).fetchone()[0]
    finally:
        conn.close()
    _prime_cached_live_price(trading, symbol="ETH/POINTS", price_points=5000)
    _force_live_provider_failure(trading, message="cached fallback grid scan")

    scanned = trading.scan_grid_bots(actor=_actor())
    assert scanned["results"]
    assert "快取" in str(scanned["results"][0].get("grid_scan_blocked_reason") or "")
    conn = trading.get_db()
    try:
        after = conn.execute(
            "SELECT COUNT(*) FROM trading_grid_orders WHERE grid_bot_id=(SELECT id FROM trading_grid_bots WHERE bot_uuid=?)",
            (bot_uuid,),
        ).fetchone()[0]
        open_after = conn.execute(
            "SELECT COUNT(*) FROM trading_grid_orders WHERE grid_bot_id=(SELECT id FROM trading_grid_bots WHERE bot_uuid=?) AND status='open'",
            (bot_uuid,),
        ).fetchone()[0]
    finally:
        conn.close()
    assert after == before
    assert open_after == open_before


def test_trial_credit_forced_sell_rejects_market_boot_pending(tmp_path):
    _points, trading = _services(tmp_path)
    _stamp(trading, "ETH/POINTS")
    trading.place_order(
        actor=_actor(),
        market_symbol="ETH/POINTS",
        side="buy",
        order_type="market",
        quantity="0.1",
    )
    conn = trading.get_db()
    try:
        conn.execute("UPDATE trading_markets SET live_price_confirmed_at=NULL WHERE symbol='ETH/POINTS'")
        conn.execute("UPDATE trading_trial_credits SET expires_at='2000-01-01T00:00:00' WHERE user_id=1")
        conn.commit()
    finally:
        conn.close()

    dashboard = trading.user_dashboard(user_id=1)
    trial = dashboard["funding"]["trial_credit"]
    assert trial["pending_reclaim"] is True
    assert "尚未收到任何即時價格更新" in trial["reclaim_blocked_reason"]


def test_trial_credit_forced_sell_rejects_manual_root_price(tmp_path):
    _points, trading = _services(tmp_path)
    root = _actor(2, "root", "super_admin")
    _stamp(trading, "ETH/POINTS")
    trading.place_order(
        actor=_actor(),
        market_symbol="ETH/POINTS",
        side="buy",
        order_type="market",
        quantity="0.1",
    )
    trading.update_root_settings(actor=root, settings={"price_source": "manual_root"}, markets=[])
    trading.update_market(actor=root, symbol="ETH/POINTS", manual_price_points=5000, confirm_jump=True)
    conn = trading.get_db()
    try:
        conn.execute("UPDATE trading_trial_credits SET expires_at='2000-01-01T00:00:00' WHERE user_id=1")
        conn.commit()
    finally:
        conn.close()

    dashboard = trading.user_dashboard(user_id=1)
    trial = dashboard["funding"]["trial_credit"]
    assert trial["pending_reclaim"] is True
    assert "手動價格" in trial["reclaim_blocked_reason"]


def test_trial_credit_forced_sell_records_reclaim_blocked_reason(tmp_path):
    _points, trading = _services(tmp_path)
    root = _actor(2, "root", "super_admin")
    _stamp(trading, "ETH/POINTS")
    trading.place_order(
        actor=_actor(),
        market_symbol="ETH/POINTS",
        side="buy",
        order_type="market",
        quantity="0.1",
    )
    trading.update_root_settings(actor=root, settings={"price_source": "manual_root"}, markets=[])
    trading.update_market(actor=root, symbol="ETH/POINTS", manual_price_points=5000, confirm_jump=True)
    conn = trading.get_db()
    try:
        conn.execute("UPDATE trading_trial_credits SET expires_at='2000-01-01T00:00:00' WHERE user_id=1")
        conn.commit()
    finally:
        conn.close()

    dashboard = trading.user_dashboard(user_id=1)
    trial = dashboard["funding"]["trial_credit"]
    assert trial["pending_reclaim"] is True
    assert trial["reclaim_blocked_at"]
    audit_types = [row["event_type"] for row in trading.root_report()["audit_events"]]
    assert "TRADING_TRIAL_CREDIT_RECLAIM_BLOCKED" in audit_types
