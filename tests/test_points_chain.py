import sqlite3

import pytest

from services.points_chain import PointsLedgerService, ensure_points_economy_schema


def _db(tmp_path):
    path = tmp_path / "points.db"

    def get_db():
        conn = sqlite3.connect(path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    conn = get_db()
    conn.execute("CREATE TABLE users (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT NOT NULL UNIQUE)")
    conn.execute("INSERT INTO users (username) VALUES ('alice'), ('bob'), ('root')")
    ensure_points_economy_schema(conn)
    conn.commit()
    conn.close()
    return get_db


def _service(tmp_path):
    return PointsLedgerService(get_db=_db(tmp_path), chain_secret="test-secret")


def test_points_transaction_updates_wallet_and_hash_chain(tmp_path):
    service = _service(tmp_path)

    first = service.record_transaction(
        user_id=1,
        currency_type="soft",
        direction="credit",
        amount=10,
        action_type="test_credit",
        idempotency_key="credit:1",
    )
    second = service.record_transaction(
        user_id=1,
        currency_type="soft",
        direction="debit",
        amount=3,
        action_type="test_debit",
        idempotency_key="debit:1",
    )

    assert first["wallet"]["soft_balance"] == 10
    assert second["wallet"]["soft_balance"] == 7
    assert second["ledger"]["previous_ledger_hash"] == first["ledger"]["ledger_hash"]
    assert service.verify_chain()["ok"] is True


def test_points_idempotency_prevents_duplicate_credit(tmp_path):
    service = _service(tmp_path)

    first = service.record_transaction(
        user_id=1,
        currency_type="hard",
        direction="credit",
        amount=5,
        action_type="test_credit",
        idempotency_key="same-key",
    )
    second = service.record_transaction(
        user_id=1,
        currency_type="hard",
        direction="credit",
        amount=5,
        action_type="test_credit",
        idempotency_key="same-key",
    )

    assert first["created"] is True
    assert second["created"] is False
    assert second["wallet"]["hard_balance"] == 5


def test_points_debit_cannot_make_wallet_negative(tmp_path):
    service = _service(tmp_path)

    with pytest.raises(ValueError, match="insufficient balance"):
        service.record_transaction(
            user_id=1,
            currency_type="soft",
            direction="debit",
            amount=1,
            action_type="test_debit",
        )

    assert service.get_wallet(1)["soft_balance"] == 0


def test_points_ledger_is_append_only(tmp_path):
    service = _service(tmp_path)
    tx = service.record_transaction(
        user_id=1,
        currency_type="soft",
        direction="credit",
        amount=10,
        action_type="test_credit",
    )
    conn = service.get_db()
    try:
        with pytest.raises(sqlite3.DatabaseError, match="append-only"):
            conn.execute("DELETE FROM points_ledger WHERE ledger_uuid=?", (tx["ledger"]["ledger_uuid"],))
        with pytest.raises(sqlite3.DatabaseError, match="immutable"):
            conn.execute("UPDATE points_ledger SET amount=99 WHERE ledger_uuid=?", (tx["ledger"]["ledger_uuid"],))
    finally:
        conn.close()


def test_points_chain_seal_verify_and_proof(tmp_path):
    service = _service(tmp_path)
    tx = service.record_transaction(
        user_id=1,
        currency_type="soft",
        direction="credit",
        amount=10,
        action_type="test_credit",
    )

    sealed = service.seal_block(actor={"id": 3, "username": "root", "role": "super_admin"}, limit=100)
    proof = service.ledger_proof(tx["ledger"]["ledger_uuid"])
    verification = service.verify_chain()

    assert sealed["sealed"] is True
    assert sealed["block"]["ledger_count"] == 1
    assert proof["sealed"] is True
    assert proof["block_number"] == sealed["block"]["block_number"]
    assert proof["ledger_hash"] == tx["ledger"]["ledger_hash"]
    assert verification["ok"] is True
    assert verification["counts"]["unsealed_entries"] == 0
