import sqlite3
from pathlib import Path

from services.points_chain import PointsLedgerService, ensure_points_economy_schema
from services.trading.trading_engine import TradingEngineService, ensure_trading_schema


ROOT = Path(__file__).resolve().parents[3]


def _db(tmp_path):
    path = tmp_path / "trading_price_contexts.db"

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
    # Boot-ready gate: stamp markets so tests don't have to round-trip a
    # live-price fetch before exercising place_order / open_margin_position.
    conn = trading.get_db()
    try:
        trading.ensure_schema(conn)
        conn.execute(
            "INSERT OR REPLACE INTO trading_settings (key, value, updated_at, updated_by) VALUES (?, ?, '2024-01-01T00:00:00', 'test')",
            ("trading.price_source", "binance_public_api"),
        )
        conn.execute(
            "UPDATE trading_markets SET live_price_confirmed_at=COALESCE(live_price_confirmed_at, ?)",
            ("2024-01-01T00:00:00",),
        )
        conn.commit()
    finally:
        conn.close()
    return get_db, points, trading


def _actor(user_id=1, username="alice", role="user"):
    return {"id": user_id, "username": username, "role": role}


def test_dashboard_markets_and_positions_expose_reference_and_risk_grade_contexts(tmp_path):
    _, points, trading = _services(tmp_path)
    points.record_transaction(user_id=1, currency_type="points", direction="credit", amount=5000, action_type="seed")
    trading.place_order(actor=_actor(), market_symbol="ETH/POINTS", side="buy", order_type="market", quantity="0.1")

    dashboard = trading.user_dashboard(user_id=1)
    market = next(row for row in dashboard["markets"] if row["symbol"] == "ETH/POINTS")
    position = next(row for row in dashboard["positions"] if row["market_symbol"] == "ETH/POINTS")

    assert market["reference_price_context"]["price_type"] == "reference"
    assert market["risk_grade_price_context"]["price_type"] == "risk_grade"
    assert position["reference_price_context"]["price_type"] == "reference"
    assert position["risk_grade_price_context"]["price_type"] == "risk_grade"
    assert "reference_current_value_points" in position
    assert "risk_grade_unrealized_pnl_points" in position


def test_margin_risk_payload_uses_high_risk_price_mode_and_context(tmp_path, monkeypatch):
    get_db, points, trading = _services(tmp_path)
    points.record_transaction(user_id=1, currency_type="points", direction="credit", amount=5000, action_type="seed")
    trading.update_root_settings(
        actor=_actor(2, "root", "super_admin"),
        settings={"borrowing_enabled": True},
        markets=[{"symbol": "ETH/POINTS", "manual_price_points": 5000}],
    )
    opened = trading.open_margin_position(
        actor=_actor(),
        market_symbol="ETH/POINTS",
        position_type="margin_long",
        quantity="0.1",
        collateral_points=120,
    )

    captured = {}

    def fake_current_market_price_points(conn, market, with_meta=False, high_risk=False):
        captured["high_risk"] = high_risk
        meta = {
            "price_health": "healthy",
            "fallback_reason": "",
            "excluded_sources": [],
            "warnings": [],
            "high_risk_blocked": False,
            "resolved_source": "fused_weighted",
            "requested_price_mode": "risk_grade" if high_risk else "reference",
            "reference_provider_count": 4,
            "risk_grade_provider_count": 3,
            "stale": False,
            "degraded": False,
        }
        if with_meta:
            return 5100, "fused_weighted", meta
        return 5100, "fused_weighted"

    monkeypatch.setattr(trading, "_current_market_price_points", fake_current_market_price_points)

    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM trading_margin_positions WHERE position_uuid=?",
            (opened["position"]["position_uuid"],),
        ).fetchone()
        market = conn.execute("SELECT * FROM trading_markets WHERE symbol='ETH/POINTS'").fetchone()
        risk = trading._margin_risk_payload(conn, row, market=market)

    assert captured["high_risk"] is True
    assert risk["price_points"] == 5100
    assert risk["price_context"]["price_type"] == "risk_grade"
    assert risk["price_context"]["provider_count"] == 3
