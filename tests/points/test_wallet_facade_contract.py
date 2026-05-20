import sqlite3

import pytest

from services.platform.db_mode_triggers import register_app_mode_function
from services.points_chain import PointsLedgerService, WalletFacadeConflict, WalletServiceFacade, ensure_points_economy_schema
from services.points_chain.schema import utc_now


def _db(tmp_path):
    path = tmp_path / "wallet_facade.db"

    def get_db():
        conn = sqlite3.connect(path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        register_app_mode_function(conn, mode_reader=lambda: "production")
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
    conn.commit()
    conn.close()
    return get_db


def _services(tmp_path):
    points = PointsLedgerService(
        get_db=_db(tmp_path),
        chain_secret="test-secret",
        backup_dir=tmp_path / "points_chain_backups",
        mode_reader=lambda: "production",
    )
    return points, WalletServiceFacade(points_service=points)


def _ledger_row(points, ledger_uuid):
    conn = points.get_db()
    try:
        return dict(conn.execute("SELECT * FROM points_ledger WHERE ledger_uuid=?", (ledger_uuid,)).fetchone())
    finally:
        conn.close()


def _ledger_count(points):
    conn = points.get_db()
    try:
        return conn.execute("SELECT COUNT(*) FROM points_ledger").fetchone()[0]
    finally:
        conn.close()


def _idempotency_row(facade, points, key):
    conn = points.get_db()
    try:
        return dict(
            conn.execute(
                f"SELECT * FROM {facade.IDEMPOTENCY_TABLE} WHERE idempotency_key=?",
                (key,),
            ).fetchone()
        )
    finally:
        conn.close()


def test_wallet_facade_idempotency_is_enforced_by_database_unique_constraint(tmp_path):
    points, facade = _services(tmp_path)
    conn = points.get_db()
    try:
        facade.ensure_schema(conn)
        now = utc_now()
        conn.execute(
            f"""
            INSERT INTO {facade.IDEMPOTENCY_TABLE} (
                actor_user_id, operation, idempotency_key, request_hash, status, created_at, updated_at
            ) VALUES (?, ?, ?, ?, 'started', ?, ?)
            """,
            (1, "unit:test", "same-key", "hash-a", now, now),
        )

        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                f"""
                INSERT INTO {facade.IDEMPOTENCY_TABLE} (
                    actor_user_id, operation, idempotency_key, request_hash, status, created_at, updated_at
                ) VALUES (?, ?, ?, ?, 'started', ?, ?)
                """,
                (1, "unit:test", "same-key", "hash-a", now, now),
            )
    finally:
        conn.close()


def test_wallet_facade_replays_same_idempotent_request_without_duplicate_effect(tmp_path):
    points, facade = _services(tmp_path)
    calls = {"count": 0}

    def effect(conn):
        calls["count"] += 1
        return {"value": calls["count"], "ledger_ids": ["ledger-a"]}

    first = facade.execute_idempotent(
        actor_user_id=1,
        operation="unit:replay",
        idempotency_key="replay-key",
        request_payload={"amount": 5},
        effect=effect,
    )
    second = facade.execute_idempotent(
        actor_user_id=1,
        operation="unit:replay",
        idempotency_key="replay-key",
        request_payload={"amount": 5},
        effect=lambda conn: pytest.fail("same idempotency request must not execute again"),
    )

    assert first["created"] is True
    assert first["replayed"] is False
    assert second["created"] is False
    assert second["replayed"] is True
    assert second["result"] == {"value": 1, "ledger_ids": ["ledger-a"]}
    assert calls["count"] == 1
    assert _idempotency_row(facade, points, "replay-key")["result_ledger_ids_json"] == '["ledger-a"]'


def test_wallet_facade_rejects_same_idempotency_key_with_different_request_hash(tmp_path):
    _points, facade = _services(tmp_path)

    facade.execute_idempotent(
        actor_user_id=1,
        operation="unit:conflict",
        idempotency_key="conflict-key",
        request_payload={"amount": 5},
        effect=lambda conn: {"ok": True},
    )

    with pytest.raises(WalletFacadeConflict):
        facade.execute_idempotent(
            actor_user_id=1,
            operation="unit:conflict",
            idempotency_key="conflict-key",
            request_payload={"amount": 6},
            effect=lambda conn: {"ok": True},
        )


def test_wallet_facade_write_guard_blocks_safe_mode_and_sanctioned_wallets(tmp_path):
    points, facade = _services(tmp_path)

    conn = points.get_db()
    try:
        facade.ensure_schema(conn)
        now = utc_now()
        conn.execute(
            """
            INSERT OR REPLACE INTO points_chain_recovery_state (id, safe_mode, reason, created_at, updated_at)
            VALUES (1, 1, 'unit safe mode', ?, ?)
            """,
            (now, now),
        )
        conn.commit()
    finally:
        conn.close()

    with pytest.raises(ValueError, match="safe mode"):
        facade.execute_idempotent(
            actor_user_id=1,
            operation="unit:safe-mode",
            idempotency_key="safe-mode-key",
            request_payload={},
            effect=lambda conn: {"ok": True},
        )

    conn = points.get_db()
    try:
        conn.execute("UPDATE points_chain_recovery_state SET safe_mode=0 WHERE id=1")
        points.ensure_wallet(conn, 1)
        conn.execute("UPDATE points_wallets SET wallet_status='frozen' WHERE user_id=1")
        conn.commit()
    finally:
        conn.close()

    with pytest.raises(ValueError, match="wallet is frozen"):
        facade.execute_idempotent(
            actor_user_id=1,
            operation="unit:frozen-wallet",
            idempotency_key="frozen-key",
            request_payload={},
            effect=lambda conn: {"ok": True},
        )

    conn = points.get_db()
    try:
        conn.execute("UPDATE points_wallets SET wallet_status='closed' WHERE user_id=1")
        conn.commit()
    finally:
        conn.close()

    with pytest.raises(ValueError, match="wallet is closed"):
        facade.execute_idempotent(
            actor_user_id=1,
            operation="unit:closed-wallet",
            idempotency_key="closed-key",
            request_payload={},
            effect=lambda conn: {"ok": True},
        )


def test_wallet_facade_refund_is_append_only_and_idempotent(tmp_path):
    points, facade = _services(tmp_path)
    actor = {"id": 3, "username": "root", "role": "super_admin"}
    points.record_transaction(
        user_id=1,
        currency_type="points",
        direction="credit",
        amount=50,
        action_type="unit_seed",
        idempotency_key="refund-seed",
    )
    debit = points.record_transaction(
        user_id=1,
        currency_type="points",
        direction="debit",
        amount=20,
        action_type="unit_spend",
        idempotency_key="refund-debit",
    )
    original_uuid = debit["ledger"]["ledger_uuid"]
    before_original = _ledger_row(points, original_uuid)
    before_count = _ledger_count(points)

    first = facade.refund(
        actor=actor,
        original_ledger_uuid=original_uuid,
        reason="delivery failed",
        idempotency_key="refund-key",
    )
    second = facade.refund(
        actor=actor,
        original_ledger_uuid=original_uuid,
        reason="delivery failed",
        idempotency_key="refund-key",
    )

    assert first["created"] is True
    assert second["created"] is False
    assert _ledger_count(points) == before_count + 1
    assert _ledger_row(points, original_uuid) == before_original
    refund_ledger = first["result"]["ledger"]
    assert refund_ledger["direction"] == "credit"
    assert refund_ledger["reference_type"] == "ledger_refund"
    assert refund_ledger["reference_id"] == original_uuid


def test_wallet_facade_rollback_is_append_only_and_idempotent(tmp_path):
    points, facade = _services(tmp_path)
    actor = {"id": 3, "username": "root", "role": "super_admin"}
    credit = points.record_transaction(
        user_id=1,
        currency_type="points",
        direction="credit",
        amount=15,
        action_type="unit_credit",
        idempotency_key="rollback-credit",
    )
    original_uuid = credit["ledger"]["ledger_uuid"]
    before_original = _ledger_row(points, original_uuid)
    before_count = _ledger_count(points)

    first = facade.rollback(
        actor=actor,
        original_ledger_uuid=original_uuid,
        reason="audit correction",
        idempotency_key="rollback-key",
    )
    second = facade.rollback(
        actor=actor,
        original_ledger_uuid=original_uuid,
        reason="audit correction",
        idempotency_key="rollback-key",
    )

    assert first["created"] is True
    assert second["created"] is False
    assert _ledger_count(points) == before_count + 1
    assert _ledger_row(points, original_uuid) == before_original
    rollback_ledger = first["result"]["ledger"]
    assert rollback_ledger["direction"] == "reverse"
    assert rollback_ledger["reference_type"] == "ledger_rollback"
    assert rollback_ledger["reference_id"] == original_uuid
    assert rollback_ledger["action_type"] == "rollback:unit_credit"
