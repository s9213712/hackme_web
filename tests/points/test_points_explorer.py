import sqlite3
from datetime import datetime, timedelta, timezone
from functools import wraps

from flask import Flask, jsonify, make_response

from routes.economy import register_economy_routes
from services.points_chain import (
    DISPLAY_CURRENCY,
    PointsLedgerService,
    create_official_hot_wallet,
    ensure_points_economy_schema,
)


def _json_resp(payload, status=200):
    return make_response(jsonify(payload), status)


def _passthrough(fn):
    return fn


def _blocked_safe_get_guard(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        return _json_resp({"ok": False, "msg": "unexpected safe csrf guard"}, 418)

    return wrapper


def _get_db_factory(path):
    def get_db():
        conn = sqlite3.connect(path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    return get_db


def _build_app(tmp_path, *, require_csrf_safe=None):
    db_path = tmp_path / "explorer.db"
    get_db = _get_db_factory(db_path)
    conn = get_db()
    conn.execute(
        "CREATE TABLE users (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT NOT NULL UNIQUE, role TEXT NOT NULL DEFAULT 'user', status TEXT NOT NULL DEFAULT 'active')"
    )
    conn.execute("INSERT INTO users (id, username, role, status) VALUES (1, 'root', 'super_admin', 'active')")
    conn.execute("INSERT INTO users (id, username, role, status) VALUES (2, 'test', 'user', 'active')")
    conn.execute("INSERT INTO users (id, username, role, status) VALUES (3, 'recipient', 'user', 'active')")
    ensure_points_economy_schema(conn)
    conn.commit()
    conn.close()

    points = PointsLedgerService(get_db=get_db, chain_secret="test-secret", backup_dir=tmp_path / "backups")
    auto_ledger = points.record_transaction(
        user_id=2,
        currency_type=DISPLAY_CURRENCY,
        direction="credit",
        amount=100,
        action_type="user_initial_grant",
        reference_type="test",
        reference_id="initial",
        idempotency_key="explorer:test:initial",
        reason="test initial points",
        actor={"id": 1, "username": "root", "role": "super_admin"},
    )["ledger"]
    manual_ledger = points.record_transaction(
        user_id=2,
        currency_type=DISPLAY_CURRENCY,
        direction="credit",
        amount=20,
        action_type="admin_adjust_credit",
        reference_type="admin_adjustment",
        reference_id="manual-root-credit",
        idempotency_key="explorer:test:manual-root-credit",
        reason="root manual official wallet credit",
        actor={"id": 1, "username": "root", "role": "super_admin"},
    )["ledger"]

    current = {"id": 2, "username": "test", "role": "user"}
    app = Flask(__name__)
    app.testing = True
    register_economy_routes(app, {
        "get_current_user_ctx": lambda: current,
        "json_resp": _json_resp,
        "require_csrf": _passthrough,
        "require_csrf_safe": require_csrf_safe or _passthrough,
        "points_service": points,
        "role_rank": lambda role: {"user": 0, "manager": 1, "super_admin": 2}.get(role or "user", 0),
        "audit": lambda *args, **kwargs: None,
        "get_db": get_db,
    })
    return app, points, auto_ledger, manual_ledger, current


def test_points_explorer_get_routes_are_public_safe_gets(tmp_path):
    app, points, ledger, _manual_ledger, current = _build_app(
        tmp_path,
        require_csrf_safe=_blocked_safe_get_guard,
    )
    current.clear()
    client = app.test_client()

    wallet_address = points.get_wallet(2)["public_account_id"]

    search_res = client.get(f"/api/points/explorer/search?q={ledger['ledger_uuid']}")
    tx_res = client.get(f"/api/points/explorer/tx/{ledger['ledger_uuid']}")
    wallet_res = client.get(f"/api/points/explorer/wallet/{wallet_address}")
    block_res = client.get("/api/points/explorer/block/999999")

    assert search_res.status_code == 200
    assert tx_res.status_code == 200
    assert wallet_res.status_code == 200
    assert block_res.status_code == 404


def test_points_explorer_searches_transaction_and_wallet_with_finality_rule(tmp_path):
    app, points, ledger, _manual_ledger, _current = _build_app(tmp_path)
    client = app.test_client()

    tx_res = client.get(f"/api/points/explorer/search?q={ledger['ledger_uuid']}")
    tx_payload = tx_res.get_json()

    assert tx_res.status_code == 200
    assert tx_payload["result"]["kind"] == "transaction"
    tx = tx_payload["result"]["transaction"]
    assert tx["ledger_uuid"] == ledger["ledger_uuid"]
    assert tx["finality"]["target_proved_count"] == 20
    assert tx["finality"]["base_seconds_min"] == 120
    assert tx["finality"]["base_seconds_max"] == 180
    assert tx["finality"]["human_rule"] == "20 Proved 約 2-3 分鐘成交"
    assert tx["finality"]["chain_fee_policy"]["base_fee_exempt"] is True
    assert tx["finality"]["chain_fee_policy"]["acceleration_allowed"] is False
    assert tx["finality"]["chain_fee_policy"]["exemption_reason"] == "設定自動發放交易免鏈上費用"
    assert "wallet_flow_snapshot" not in tx["input_data"]
    assert tx["wallet_flow"]["destination_wallet_address"]

    wallet_address = points.get_wallet(2)["public_account_id"]
    wallet_res = client.get(f"/api/points/explorer/search?q={wallet_address}")
    wallet_payload = wallet_res.get_json()

    assert wallet_res.status_code == 200
    assert wallet_payload["result"]["kind"] == "wallet"
    wallet = wallet_payload["result"]["wallet"]
    assert wallet["address"] == wallet_address
    assert wallet["points_balance"] == 120
    assert wallet["transaction_count"] == 2
    assert wallet["human_rule"] == "20 Proved 約 2-3 分鐘成交"


def test_points_explorer_acceleration_is_append_only_and_idempotent(tmp_path):
    app, points, _auto_ledger, ledger, _current = _build_app(tmp_path)
    client = app.test_client()

    first = client.post(
        "/api/points/explorer/accelerate",
        json={"ledger_ref": ledger["ledger_uuid"], "fee_points": 10, "request_uuid": "accel-test-1"},
    )
    first_payload = first.get_json()

    assert first.status_code == 200
    assert first_payload["created"] is True
    assert first_payload["acceleration"]["fee_points"] == 10
    assert first_payload["result"]["transaction"]["finality"]["acceleration_fee_paid_points"] == 10
    assert first_payload["result"]["transaction"]["finality"]["acceleration_fee_destination_fund_key"] == "burn"
    assert first_payload["result"]["transaction"]["finality"]["transaction_fee_points"] == 10
    assert first_payload["result"]["transaction"]["finality"]["gas_price_points_per_proved"] == 0.5
    assert first_payload["result"]["transaction"]["finality"]["chain_fee_policy"]["acceleration_allowed"] is True
    assert first_payload["fee_ledger"]["action_type"] == "chain_acceleration_fee"

    second = client.post(
        "/api/points/explorer/accelerate",
        json={"ledger_ref": ledger["ledger_uuid"], "fee_points": 10, "request_uuid": "accel-test-1"},
    )
    second_payload = second.get_json()

    assert second.status_code == 200
    assert second_payload["created"] is False
    assert points.get_wallet(2)["points_balance"] == 110

    conflict = client.post(
        "/api/points/explorer/accelerate",
        json={"ledger_ref": ledger["ledger_uuid"], "fee_points": 11, "request_uuid": "accel-test-1"},
    )
    assert conflict.status_code == 400
    assert "idempotency key conflict" in conflict.get_json()["msg"]
    assert points.get_wallet(2)["points_balance"] == 110

    wallet_address = points.get_wallet(2)["public_account_id"]
    wallet_res = client.get(f"/api/points/explorer/wallet/{wallet_address}")
    wallet = wallet_res.get_json()["result"]["wallet"]
    assert wallet["points_balance"] == 110
    assert wallet["transaction_count"] == 3


def test_points_explorer_auto_distribution_is_chain_fee_exempt(tmp_path):
    app, points, ledger, _manual_ledger, _current = _build_app(tmp_path)
    client = app.test_client()

    res = client.post(
        "/api/points/explorer/accelerate",
        json={"ledger_ref": ledger["ledger_uuid"], "fee_points": 10, "request_uuid": "auto-exempt-1"},
    )

    assert res.status_code == 400
    assert "設定自動發放交易免鏈上費用" in res.get_json()["msg"]
    assert points.get_wallet(2)["points_balance"] == 120


def test_points_explorer_pending_proved_count_uses_stable_realistic_schedule(tmp_path):
    _app, points, _auto_ledger, ledger, _current = _build_app(tmp_path)
    created_at = (datetime.now(timezone.utc) - timedelta(seconds=20)).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    fake_ledger = {**dict(ledger), "created_at": created_at}
    conn = points.get_db()
    try:
        first = points._explorer_finality_for_ledger(conn, fake_ledger)
        second = points._explorer_finality_for_ledger(conn, fake_ledger)
    finally:
        conn.close()

    assert first["finality_simulation"] == "deterministic_proved_schedule_v1"
    assert first["settlement_seconds"] >= first["estimated_seconds_min"]
    assert first["settlement_seconds"] <= first["estimated_seconds_max"]
    assert 1 <= first["proved_count"] < 20
    assert first["proved_count"] == second["proved_count"]
    assert first["next_proof_eta_seconds"] >= 0
    assert first["eta_seconds"] <= first["settlement_seconds"]


def test_wallet_transfer_pending_does_not_credit_recipient_until_proved(tmp_path):
    app, points, _auto_ledger, _manual_ledger, current = _build_app(tmp_path)
    client = app.test_client()
    conn = points.get_db()
    try:
        points.ensure_schema(conn)
        sender_wallet = create_official_hot_wallet(conn, user_id=2, chain_secret="test-secret", label="sender hot")
        recipient_wallet = create_official_hot_wallet(conn, user_id=3, chain_secret="test-secret", label="recipient hot")
        conn.commit()
    finally:
        conn.close()

    points.record_transaction(
        user_id=2,
        currency_type=DISPLAY_CURRENCY,
        direction="credit",
        amount=200,
        action_type="admin_adjust_credit",
        reference_type="test",
        reference_id="transfer-funding",
        idempotency_key="explorer:test:transfer-funding",
        reason="fund transfer source",
        actor={"id": 1, "username": "root", "role": "super_admin"},
    )

    current.update({"id": 2, "username": "test", "role": "user"})
    res = client.post(
        "/api/points/transactions/submit",
        json={
            "source_wallet_address": sender_wallet["address"],
            "destination_wallet_address": recipient_wallet["address"],
            "amount_points": 30,
            "fee_points": 1,
            "request_uuid": "pending-transfer-1",
            "memo": "acceptance transfer",
        },
    )
    payload = res.get_json()

    assert res.status_code == 200
    assert payload["created"] is True
    tx_hash = payload["tx_group_hash"]
    assert payload["transaction"]["status"] == "pending"
    assert payload["transaction"]["finality"]["proved_count"] < 20

    sender_pending = points.explorer_wallet(sender_wallet["address"])["wallet"]
    recipient_pending = points.explorer_wallet(recipient_wallet["address"])["wallet"]
    assert sender_pending["points_balance"] == 200
    assert recipient_pending["points_balance"] == 0

    conn = points.get_db()
    try:
        rows = conn.execute(
            "SELECT user_id, type, body FROM notifications WHERE type='points_chain_transfer_pending' ORDER BY user_id"
        ).fetchall()
    finally:
        conn.close()
    assert [int(row["user_id"]) for row in rows] == [2, 3]
    assert all(tx_hash in row["body"] for row in rows)

    proved_at = (datetime.now(timezone.utc) - timedelta(seconds=600)).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    conn = points.get_db()
    try:
        points.ensure_schema(conn)
        conn.execute(
            "UPDATE points_chain_transfer_requests SET created_at=? WHERE tx_group_hash=?",
            (proved_at, tx_hash),
        )
        conn.commit()
    finally:
        conn.close()

    proved_res = client.get(f"/api/points/explorer/search?q={tx_hash}")
    assert proved_res.status_code == 200, proved_res.get_json()
    proved = proved_res.get_json()["result"]["transaction"]
    assert proved["status"] == "confirmed"
    assert proved["finality"]["finality_status"] == "proved"
    assert proved["finality"]["proved_count"] == 20

    sender_final = points.explorer_wallet(sender_wallet["address"])["wallet"]
    recipient_final = points.explorer_wallet(recipient_wallet["address"])["wallet"]
    assert sender_final["points_balance"] == 169
    assert recipient_final["points_balance"] == 30

    conn = points.get_db()
    try:
        rows = conn.execute(
            "SELECT user_id, type, body FROM notifications WHERE type='points_chain_transfer_completed' ORDER BY user_id"
        ).fetchall()
    finally:
        conn.close()
    assert [int(row["user_id"]) for row in rows] == [2, 3]
    assert all(tx_hash in row["body"] for row in rows)
