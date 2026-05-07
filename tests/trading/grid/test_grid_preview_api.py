import sqlite3

from flask import Flask, jsonify

from routes.trading import register_trading_routes
from services.points_chain import PointsLedgerService, ensure_points_economy_schema
from services.trading.trading_engine import TradingEngineService, ensure_trading_schema


def _db(tmp_path):
    path = tmp_path / "grid_preview_api.db"

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


def _app(tmp_path, actor):
    get_db = _db(tmp_path)
    points = PointsLedgerService(get_db=get_db, chain_secret="test-secret", backup_dir=tmp_path / "points_chain_backups")
    prices = {"BTC/POINTS": 77059, "ETH/POINTS": 5000}
    trading = TradingEngineService(get_db=get_db, points_service=points, live_price_provider=lambda symbol: prices[symbol])
    trading.test_prices = prices

    app = Flask(__name__)
    app.testing = True

    def passthrough(fn):
        return fn

    def json_resp(payload, status=None):
        response = jsonify(payload)
        return (response, status) if status else response

    register_trading_routes(app, {
        "trading_service": trading,
        "get_current_user_ctx": lambda: actor,
        "json_resp": json_resp,
        "require_csrf": passthrough,
        "require_csrf_safe": passthrough,
        "audit": lambda *args, **kwargs: None,
        "check_user_rate_limit": lambda *args, **kwargs: (False, {}),
    })
    return app


def test_grid_preview_api_returns_fee_break_even_and_risk_sections(tmp_path):
    client = _app(tmp_path, {"id": 1, "username": "alice", "role": "user"}).test_client()

    response = client.post("/api/trading/grid/preview", json={
        "market_symbol": "ETH/POINTS",
        "lower_price_points": 100000,
        "upper_price_points": 100200,
        "grid_count": 2,
        "order_amount_points": 10000,
        "order_mode": "maker",
    })

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["ok"] is True
    assert payload["market_symbol"] == "ETH/POINTS"
    assert payload["fee_model"]["buy_fee_percent"] == "0.075"
    assert payload["break_even"]["min_spread_percent"] == "0.1501"
    assert payload["grid_profit"]["estimated_net_spread_percent"] == "0.0499"
    assert payload["risk"]["status"] == "yellow"
    assert payload["risk"]["requires_confirmation"] is True


def test_grid_preview_api_rejects_nan_and_infinity_inputs(tmp_path):
    client = _app(tmp_path, {"id": 1, "username": "alice", "role": "user"}).test_client()

    nan_response = client.post("/api/trading/grid/preview", json={
        "market_symbol": "ETH/POINTS",
        "lower_price_points": 100,
        "upper_price_points": 101,
        "grid_count": 2,
        "order_amount_points": "NaN",
    })
    inf_response = client.post("/api/trading/grid/preview", json={
        "market_symbol": "ETH/POINTS",
        "lower_price_points": 100,
        "upper_price_points": 101,
        "grid_count": 2,
        "order_amount_points": "Infinity",
    })

    assert nan_response.status_code == 400
    assert "finite number" in nan_response.get_json()["msg"]
    assert inf_response.status_code == 400
    assert "finite number" in inf_response.get_json()["msg"]
