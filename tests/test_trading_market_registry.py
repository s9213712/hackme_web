import json
import sqlite3
from pathlib import Path

import pytest
from flask import Flask, jsonify

import routes.trading as trading_routes
from routes.trading import register_trading_routes
from services.points_chain import PointsLedgerService, ensure_points_economy_schema
from services.trading_engine import TradingEngineService, ensure_trading_schema
from services.trading_markets import TRADING_MARKET_CATALOG_SEED_VERSION


def _db(tmp_path):
    path = tmp_path / "trading_market_registry.db"

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
        "('admin', 'manager', 'active'), "
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
    prices = {
        "BTC/POINTS": 77059,
        "ETH/POINTS": 5000,
        "SOL/POINTS": 120,
    }
    trading = TradingEngineService(get_db=get_db, points_service=points, live_price_provider=lambda symbol: prices[symbol])
    trading.test_prices = prices
    return get_db, points, trading


def _actor(user_id, username, role):
    return {"id": user_id, "username": username, "role": role}


def _client(trading_service, actor):
    app = Flask(__name__)
    app.testing = True

    def passthrough(fn):
        return fn

    def json_resp(payload, status=None):
        response = jsonify(payload)
        return (response, status) if status else response

    register_trading_routes(app, {
        "trading_service": trading_service,
        "get_current_user_ctx": lambda: actor,
        "json_resp": json_resp,
        "require_csrf": passthrough,
        "require_csrf_safe": passthrough,
        "check_user_rate_limit": lambda *args, **kwargs: (False, {}),
        "audit": lambda *args, **kwargs: None,
    })
    return app.test_client()


class _FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


def _find_market_id(trading, symbol):
    payload = trading.list_market_registry(include_disabled=True)
    row = next(item for item in payload["markets"] if item["symbol"] == symbol)
    return int(row["id"])


def _seed_sol_market(trading):
    root = _actor(3, "root", "super_admin")
    created = trading.create_market_registry(actor=root, payload={
        "symbol": "SOL/POINTS",
        "base_asset": "SOL",
        "quote_asset": "POINTS",
        "display_quote_currency": "USDT",
        "display_name": "SOL/USDT",
        "market_type": "spot",
        "enabled": True,
        "allow_spot": True,
        "allow_margin": True,
        "allow_bots": True,
        "allow_risk_grade_usage": False,
        "price_precision": 2,
        "quantity_precision": 2,
        "min_order_size": 0.25,
        "max_order_size": 1000,
        "lot_size": 0.25,
        "tick_size": 0.5,
        "sort_order": 35,
        "default_manual_price_points": 120,
        "live_price_enabled": True,
        "reference_price_enabled": True,
        "btc_trade_enabled": False,
    })
    market_id = int(created["market"]["id"])
    for priority, provider, symbol in (
        (10, "binance_public_api", "SOLUSDT"),
        (20, "okx_public_api", "SOL-USDT"),
        (30, "coinbase_exchange", "SOL-USD"),
    ):
        trading.create_market_provider_mapping(actor=root, market_id=market_id, payload={
            "provider": provider,
            "provider_symbol": symbol,
            "supports_ticker": True,
            "supports_depth": True,
            "supports_candles": True,
            "enabled": True,
            "priority": priority,
        })
    trading.update_market_registry(actor=root, market_id=market_id, payload={
        "symbol": "SOL/POINTS",
        "base_asset": "SOL",
        "quote_asset": "POINTS",
        "display_quote_currency": "USDT",
        "display_name": "SOL/USDT",
        "market_type": "spot",
        "enabled": True,
        "allow_spot": True,
        "allow_margin": True,
        "allow_bots": True,
        "allow_risk_grade_usage": True,
        "price_precision": 2,
        "quantity_precision": 2,
        "min_order_size": 0.25,
        "max_order_size": 1000,
        "lot_size": 0.25,
        "tick_size": 0.5,
        "sort_order": 35,
        "default_manual_price_points": 120,
        "live_price_enabled": True,
        "reference_price_enabled": True,
        "btc_trade_enabled": False,
    })
    return market_id


def test_registry_schema_seeds_markets_and_exposes_audit_tables(tmp_path):
    get_db, _points, trading = _services(tmp_path)

    registry = trading.list_market_registry(include_disabled=True)
    symbols = [row["symbol"] for row in registry["markets"]]

    assert "BTC/POINTS" in symbols
    assert "ETH/POINTS" in symbols

    conn = get_db()
    try:
        tables = {
            row["name"]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        }
    finally:
        conn.close()

    assert {"trading_markets_registry", "trading_market_provider_mappings", "trading_market_registry_audit"} <= tables
    btc = next(row for row in registry["markets"] if row["symbol"] == "BTC/POINTS")
    assert btc["registry_source"] == "catalog_seed"
    assert btc["seed_version"] == TRADING_MARKET_CATALOG_SEED_VERSION
    assert btc["catalog_seed_version"] == TRADING_MARKET_CATALOG_SEED_VERSION
    assert btc["seed_sync_status"] == "current"


def test_root_can_add_market_and_public_market_list_reflects_registry(tmp_path, monkeypatch):
    _get_db, _points, trading = _services(tmp_path)
    market_id = _seed_sol_market(trading)
    registry = trading.list_market_registry(include_disabled=True)
    sol_registry = next(row for row in registry["markets"] if row["symbol"] == "SOL/POINTS")
    assert sol_registry["registry_source"] == "custom"
    assert sol_registry["seed_version"] == 0
    assert sol_registry["seed_sync_status"] == "custom"

    trading_routes.REFERENCE_PRICE_CACHE.clear()
    candles = [
        [1715000000000 + idx * 900000, "100", "103", "99", str(100 + idx)]
        for idx in range(12)
    ]

    def fake_urlopen(_req, timeout=5):
        return _FakeResponse(candles)

    monkeypatch.setattr(trading_routes, "urlopen", fake_urlopen)

    root_client = _client(trading, _actor(3, "root", "super_admin"))
    user_client = _client(trading, _actor(1, "alice", "user"))

    markets = user_client.get("/api/trading/markets").get_json()
    assert markets["ok"] is True
    sol = next(row for row in markets["markets"] if row["symbol"] == "SOL/POINTS")
    assert sol["display_symbol"] == "SOL/USDT"

    probe = root_client.post(f"/api/admin/trading/markets/{market_id}/probe").get_json()
    assert probe["ok"] is True
    assert probe["probe"]["risk_grade_ready"] is True

    reference = user_client.get("/api/trading/reference-prices?market=SOL/USDT&interval=15m&limit=12").get_json()
    assert reference["ok"] is True
    assert reference["market"] == "SOL/POINTS"
    assert reference["display_market"] == "SOL/USDT"
    assert reference["source"] == "binance_public_api"


def test_seeded_market_updates_are_reported_as_catalog_drift(tmp_path):
    _get_db, _points, trading = _services(tmp_path)
    root = _actor(3, "root", "super_admin")
    market_id = _find_market_id(trading, "BTC/POINTS")
    trading.update_market_registry(actor=root, market_id=market_id, payload={
        "symbol": "BTC/POINTS",
        "base_asset": "BTC",
        "quote_asset": "POINTS",
        "display_quote_currency": "USDT",
        "display_name": "BTC / custom drift",
        "market_type": "spot",
        "enabled": True,
        "allow_spot": True,
        "allow_margin": True,
        "allow_bots": True,
        "allow_risk_grade_usage": True,
        "price_precision": 8,
        "quantity_precision": 8,
        "min_order_size": 0.00000001,
        "max_order_size": 1000000,
        "lot_size": 0.00000001,
        "tick_size": 0.00000001,
        "sort_order": 10,
        "default_manual_price_points": 100000,
        "live_price_enabled": True,
        "reference_price_enabled": True,
        "btc_trade_enabled": True,
    })
    registry = trading.list_market_registry(include_disabled=True)
    btc = next(row for row in registry["markets"] if row["symbol"] == "BTC/POINTS")
    assert btc["registry_source"] == "catalog_seed"
    assert btc["seed_sync_status"] == "drifted"
    assert "display_name" in btc["seed_sync_reasons"]


@pytest.mark.parametrize(
    ("actor", "expected_status"),
    [
        (_actor(2, "admin", "manager"), 403),
        (_actor(1, "alice", "user"), 403),
    ],
)
def test_non_root_cannot_manage_market_registry_via_route(tmp_path, actor, expected_status):
    _get_db, _points, trading = _services(tmp_path)
    client = _client(trading, actor)

    response = client.post("/api/admin/trading/markets", json={
        "symbol": "SOL/POINTS",
        "base_asset": "SOL",
        "quote_asset": "POINTS",
    })

    assert response.status_code == expected_status
    assert response.get_json()["ok"] is False


def test_market_registry_rejects_risk_grade_enable_without_enough_depth_providers(tmp_path):
    _get_db, _points, trading = _services(tmp_path)
    root = _actor(3, "root", "super_admin")
    created = trading.create_market_registry(actor=root, payload={
        "symbol": "SOL/POINTS",
        "base_asset": "SOL",
        "quote_asset": "POINTS",
        "display_quote_currency": "USDT",
        "display_name": "SOL/USDT",
        "allow_risk_grade_usage": False,
    })
    market_id = int(created["market"]["id"])
    trading.create_market_provider_mapping(actor=root, market_id=market_id, payload={
        "provider": "binance_public_api",
        "provider_symbol": "SOLUSDT",
        "supports_ticker": True,
        "supports_depth": True,
        "supports_candles": True,
        "enabled": True,
        "priority": 10,
    })

    with pytest.raises(ValueError, match="risk-grade"):
        trading.update_market_registry(actor=root, market_id=market_id, payload={
            "symbol": "SOL/POINTS",
            "base_asset": "SOL",
            "quote_asset": "POINTS",
            "display_quote_currency": "USDT",
            "display_name": "SOL/USDT",
            "allow_risk_grade_usage": True,
        })


def test_disable_market_preserves_history_and_prevents_new_orders(tmp_path):
    _get_db, points, trading = _services(tmp_path)
    trading.update_root_settings(
        actor=_actor(3, "root", "super_admin"),
        settings={"price_source": "manual_root"},
        markets=[{"symbol": "ETH/POINTS", "manual_price_points": 5000}],
    )
    points.record_transaction(user_id=1, currency_type="points", direction="credit", amount=5000, action_type="seed")
    trading.place_order(actor=_actor(1, "alice", "user"), market_symbol="ETH/POINTS", side="buy", order_type="market", quantity="0.1")

    market_id = _find_market_id(trading, "ETH/POINTS")
    trading.disable_market_registry(actor=_actor(3, "root", "super_admin"), market_id=market_id)

    with pytest.raises(ValueError, match="spot trading is disabled for this market"):
        trading.place_order(actor=_actor(1, "alice", "user"), market_symbol="ETH/POINTS", side="buy", order_type="market", quantity="0.1")

    conn = trading.get_db()
    try:
        history_count = conn.execute(
            "SELECT COUNT(*) FROM trading_spot_positions WHERE user_id=? AND market_symbol='ETH/POINTS'",
            (1,),
        ).fetchone()[0]
    finally:
        conn.close()
    assert history_count == 1


def test_market_registry_precision_and_lot_size_affect_order_validation(tmp_path):
    _get_db, points, trading = _services(tmp_path)
    _seed_sol_market(trading)
    points.record_transaction(user_id=1, currency_type="points", direction="credit", amount=10000, action_type="seed")

    with pytest.raises(ValueError, match="quantity exceeds quantity precision 2"):
        trading.place_order(actor=_actor(1, "alice", "user"), market_symbol="SOL/USDT", side="buy", order_type="market", quantity="0.251")

    with pytest.raises(ValueError, match="tick size 0.5"):
        trading.place_order(actor=_actor(1, "alice", "user"), market_symbol="SOL/USDT", side="buy", order_type="limit", quantity="0.5", limit_price_points="120.3")

    result = trading.place_order(
        actor=_actor(1, "alice", "user"),
        market_symbol="SOL/USDT",
        side="buy",
        order_type="limit",
        quantity="0.5",
        limit_price_points="120.5",
    )

    assert result["ok"] is True
    assert result["order"]["market_symbol"] == "SOL/POINTS"
