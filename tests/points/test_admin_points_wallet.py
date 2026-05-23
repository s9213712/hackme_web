import sqlite3

from flask import Flask, jsonify, make_response

from routes.economy import register_economy_routes
from services.points_chain import DISPLAY_CURRENCY, PointsLedgerService, ensure_points_economy_schema


def _json_resp(payload, status=200):
    return make_response(jsonify(payload), status)


def _passthrough(fn):
    return fn


def _get_db_factory(path):
    def get_db():
        conn = sqlite3.connect(path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    return get_db


def test_admin_points_wallet_user_id_lookup_is_disabled(tmp_path):
    db_path = tmp_path / "wallets.db"
    get_db = _get_db_factory(db_path)
    conn = get_db()
    conn.execute(
        "CREATE TABLE users (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT NOT NULL UNIQUE, role TEXT NOT NULL DEFAULT 'user', status TEXT NOT NULL DEFAULT 'active')"
    )
    conn.execute("INSERT INTO users (id, username, role, status) VALUES (1, 'root', 'super_admin', 'active')")
    ensure_points_economy_schema(conn)
    conn.commit()
    conn.close()

    points = PointsLedgerService(get_db=get_db, chain_secret="test-secret", backup_dir=tmp_path / "backups")
    app = Flask(__name__)
    app.testing = True
    register_economy_routes(app, {
        "get_current_user_ctx": lambda: {"id": 1, "username": "root", "role": "super_admin"},
        "json_resp": _json_resp,
        "require_csrf": _passthrough,
        "require_csrf_safe": _passthrough,
        "points_service": points,
        "role_rank": lambda role: {"user": 0, "manager": 1, "super_admin": 2}.get(role or "user", 0),
        "audit": lambda *args, **kwargs: None,
        "get_db": get_db,
    })

    res_zero = app.test_client().get("/api/admin/points/wallets/0")
    res_missing = app.test_client().get("/api/admin/points/wallets/999999")

    assert res_zero.status_code == 410
    assert res_zero.get_json()["code"] == "blockchain_permission_model"
    assert res_missing.status_code == 410
    assert res_missing.get_json()["code"] == "blockchain_permission_model"


def test_admin_points_wallet_does_not_expose_user_balance_or_reward_ledger(tmp_path):
    db_path = tmp_path / "wallets.db"
    get_db = _get_db_factory(db_path)
    conn = get_db()
    conn.execute(
        "CREATE TABLE users (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT NOT NULL UNIQUE, role TEXT NOT NULL DEFAULT 'user', status TEXT NOT NULL DEFAULT 'active')"
    )
    conn.execute("INSERT INTO users (id, username, role, status) VALUES (1, 'root', 'super_admin', 'active')")
    conn.execute("INSERT INTO users (id, username, role, status) VALUES (2, 'test', 'user', 'active')")
    ensure_points_economy_schema(conn)
    conn.commit()
    conn.close()

    points = PointsLedgerService(get_db=get_db, chain_secret="test-secret", backup_dir=tmp_path / "backups")
    points.record_transaction(
        user_id=2,
        currency_type=DISPLAY_CURRENCY,
        direction="credit",
        amount=25,
        action_type="game_daily_challenge_reward",
        reference_type="game_daily_challenge",
        reference_id="gomoku:gomoku-daily-2026-05-14",
        idempotency_key="game_daily_reward:gomoku:gomoku-daily-2026-05-14:2",
        reason="gomoku 每日任務完成獎勵",
        public_metadata={"game_key": "gomoku", "difficulty": "daily-rush", "score": 1500},
        actor={"id": 2, "username": "test", "role": "user"},
    )

    app = Flask(__name__)
    app.testing = True
    register_economy_routes(app, {
        "get_current_user_ctx": lambda: {"id": 1, "username": "root", "role": "super_admin"},
        "json_resp": _json_resp,
        "require_csrf": _passthrough,
        "require_csrf_safe": _passthrough,
        "points_service": points,
        "role_rank": lambda role: {"user": 0, "manager": 1, "super_admin": 2}.get(role or "user", 0),
        "audit": lambda *args, **kwargs: None,
        "get_db": get_db,
    })

    res = app.test_client().get("/api/admin/points/wallets/2")
    payload = res.get_json()

    assert res.status_code == 410
    assert payload["code"] == "blockchain_permission_model"
    assert "wallet" not in payload
    assert "ledger" not in payload

    adjustments = points.list_admin_adjustments(limit=20)
    assert any(row["action_type"] == "game_daily_challenge_reward" and row["amount"] == 25 for row in adjustments)
