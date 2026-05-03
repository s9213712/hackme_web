import csv
import io
import sqlite3

from flask import Flask, jsonify

from routes.economy import register_economy_routes
from routes.trading import register_trading_routes
from services.points_chain import PointsLedgerService, ensure_points_economy_schema
from services.trading_engine import TradingEngineService, ensure_trading_schema, quantity_to_units


def _json_resp(payload, status=None):
    response = jsonify(payload)
    return (response, status) if status else response


def _passthrough(fn):
    return fn


def _get_db_factory(path):
    def get_db():
        conn = sqlite3.connect(path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    return get_db


def _init_db(path):
    get_db = _get_db_factory(path)
    conn = get_db()
    conn.execute(
        "CREATE TABLE users (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT NOT NULL UNIQUE, role TEXT NOT NULL DEFAULT 'user', status TEXT NOT NULL DEFAULT 'active')"
    )
    conn.execute(
        "INSERT INTO users (username, role, status) VALUES ('alice', 'user', 'active'), ('bob', 'user', 'active')"
    )
    ensure_points_economy_schema(conn)
    ensure_trading_schema(conn)
    conn.commit()
    conn.close()
    return get_db


def _csv_rows(response):
    text = response.data.decode("utf-8-sig")
    return list(csv.DictReader(io.StringIO(text)))


def test_user_can_download_own_points_wallet_and_ledger_csv(tmp_path):
    get_db = _init_db(tmp_path / "export.db")
    points = PointsLedgerService(get_db=get_db, chain_secret="test-secret", backup_dir=tmp_path / "backups")
    points.record_transaction(
        user_id=1,
        currency_type="points",
        direction="credit",
        amount=25,
        action_type="test_credit",
        reference_type="test",
        reference_id="alice-credit",
        reason="alice export seed",
        actor={"id": 1, "username": "alice", "role": "user"},
    )
    points.record_transaction(
        user_id=2,
        currency_type="points",
        direction="credit",
        amount=99,
        action_type="test_credit",
        reference_type="test",
        reference_id="bob-credit",
        reason="bob export seed",
        actor={"id": 2, "username": "bob", "role": "user"},
    )

    app = Flask(__name__)
    app.testing = True
    register_economy_routes(app, {
        "get_current_user_ctx": lambda: {"id": 1, "username": "alice", "role": "user"},
        "json_resp": _json_resp,
        "require_csrf": _passthrough,
        "require_csrf_safe": _passthrough,
        "points_service": points,
        "role_rank": lambda role: {"user": 0, "manager": 1, "super_admin": 2}.get(role or "user", 0),
        "audit": lambda *args, **kwargs: None,
    })

    response = app.test_client().get("/api/points/wallet/export.csv")
    assert response.status_code == 200
    assert response.mimetype == "text/csv"
    assert "points_wallet_alice.csv" in response.headers["Content-Disposition"]
    rows = _csv_rows(response)
    assert rows[0]["record_type"] == "wallet_summary"
    assert rows[0]["points_balance"] == "25"
    ledger_rows = [row for row in rows if row["record_type"] == "ledger"]
    assert len(ledger_rows) == 1
    assert ledger_rows[0]["reference_id"] == "alice-credit"
    assert "bob-credit" not in response.data.decode("utf-8-sig")


def test_user_can_download_own_trading_history_csv(tmp_path):
    get_db = _init_db(tmp_path / "trading-export.db")
    points = PointsLedgerService(get_db=get_db, chain_secret="test-secret", backup_dir=tmp_path / "backups")
    trading = TradingEngineService(get_db=get_db, points_service=points, live_price_provider=lambda symbol: 100)

    conn = get_db()
    try:
        now = "2026-05-03T00:00:00"
        conn.execute(
            """
            INSERT OR REPLACE INTO trading_markets
            (symbol, base_asset, quote_currency, enabled, spot_enabled, manual_price_points, updated_at)
            VALUES ('BTC/USDT', 'BTC', 'USDT', 1, 1, 100, ?)
            """,
            (now,),
        )
        qty = quantity_to_units("0.5")
        cur = conn.execute(
            """
            INSERT INTO trading_orders
            (order_uuid, user_id, market_symbol, side, order_type, quantity_units, execution_price_points, status, fee_points, filled_quantity_units, reason, created_at, updated_at)
            VALUES ('alice-order', 1, 'BTC/USDT', 'buy', 'market', ?, 100, 'filled', 1, ?, 'alice order', ?, ?)
            """,
            (qty, qty, now, now),
        )
        conn.execute(
            """
            INSERT INTO trading_fills
            (fill_uuid, order_id, user_id, market_symbol, side, quantity_units, price_points, notional_points, fee_points, points_ledger_uuids_json, created_at)
            VALUES ('alice-fill', ?, 1, 'BTC/USDT', 'buy', ?, 100, 50, 1, '["ledger-a"]', ?)
            """,
            (cur.lastrowid, qty, now),
        )
        conn.execute(
            """
            INSERT INTO trading_orders
            (order_uuid, user_id, market_symbol, side, order_type, quantity_units, status, fee_points, filled_quantity_units, reason, created_at, updated_at)
            VALUES ('bob-order', 2, 'BTC/USDT', 'buy', 'market', ?, 'filled', 1, ?, 'bob order', ?, ?)
            """,
            (qty, qty, now, now),
        )
        conn.commit()
    finally:
        conn.close()

    app = Flask(__name__)
    app.testing = True
    register_trading_routes(app, {
        "trading_service": trading,
        "get_current_user_ctx": lambda: {"id": 1, "username": "alice", "role": "user"},
        "json_resp": _json_resp,
        "require_csrf": _passthrough,
        "require_csrf_safe": _passthrough,
        "check_user_rate_limit": lambda *args, **kwargs: (False, {}),
        "audit": lambda *args, **kwargs: None,
    })

    response = app.test_client().get("/api/trading/history/export.csv")
    assert response.status_code == 200
    assert response.mimetype == "text/csv"
    assert "trading_history_alice.csv" in response.headers["Content-Disposition"]
    rows = _csv_rows(response)
    assert {row["record_type"] for row in rows} == {"order", "fill"}
    body = response.data.decode("utf-8-sig")
    assert "alice-order" in body
    assert "alice-fill" in body
    assert "ledger-a" in body
    assert "bob-order" not in body
