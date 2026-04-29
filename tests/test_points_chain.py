import json
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


def _service(tmp_path):
    return PointsLedgerService(get_db=_db(tmp_path), chain_secret="test-secret")


def test_points_transaction_updates_wallet_and_hash_chain(tmp_path):
    service = _service(tmp_path)

    first = service.record_transaction(
        user_id=1,
        currency_type="points",
        direction="credit",
        amount=10,
        action_type="test_credit",
        idempotency_key="credit:1",
    )
    second = service.record_transaction(
        user_id=1,
        currency_type="points",
        direction="debit",
        amount=3,
        action_type="test_debit",
        idempotency_key="debit:1",
    )

    assert first["wallet"]["points_balance"] == 10
    assert second["wallet"]["points_balance"] == 7
    assert second["ledger"]["currency_type"] == "points"
    assert second["ledger"]["previous_ledger_hash"] == first["ledger"]["ledger_hash"]
    assert service.verify_chain()["ok"] is True


def test_legacy_hard_currency_is_merged_into_single_points_balance(tmp_path):
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
    assert second["wallet"]["points_balance"] == 5
    assert second["wallet"]["hard_balance"] == 0
    assert second["ledger"]["currency_type"] == "points"


def test_points_debit_cannot_make_wallet_negative(tmp_path):
    service = _service(tmp_path)

    with pytest.raises(ValueError, match="insufficient balance"):
        service.record_transaction(
            user_id=1,
            currency_type="points",
            direction="debit",
            amount=1,
            action_type="test_debit",
        )

    assert service.get_wallet(1)["points_balance"] == 0


def test_signup_bonus_is_single_currency_and_idempotent(tmp_path):
    service = _service(tmp_path)

    first = service.award_signup_bonus(user_id=1, actor={"id": 1, "username": "alice", "role": "user"})
    second = service.award_signup_bonus(user_id=1, actor={"id": 1, "username": "alice", "role": "user"})

    assert first["created"] is True
    assert second["created"] is False
    assert second["wallet"]["points_balance"] == 100
    assert second["ledger"]["currency_type"] == "points"


def test_admin_initial_grants_create_genesis_block_once_for_non_root_admins(tmp_path):
    service = _service(tmp_path)

    first = service.bootstrap_admin_initial_grants(actor={"username": "system", "role": "system"}, seal_genesis=True)
    second = service.bootstrap_admin_initial_grants(actor={"username": "system", "role": "system"}, seal_genesis=True)

    assert first["created_count"] == 1
    assert first["created"][0]["username"] == "bob"
    assert first["sealed"]["sealed"] is True
    assert first["sealed"]["block"]["block_number"] == 1
    assert second["created_count"] == 0
    assert service.get_wallet(2)["points_balance"] == 1000
    assert service.get_wallet(3)["points_balance"] == 0
    assert service.verify_chain()["counts"]["sealed_blocks"] == 1
    assert service.root_report()["adjustments"][0]["action_type"] == "admin_initial_grant"


def test_admin_weekly_salary_is_idempotent_by_week(tmp_path):
    service = _service(tmp_path)

    first = service.award_admin_weekly_salaries(salary_week="2026-W18", actor={"username": "system", "role": "system"})
    second = service.award_admin_weekly_salaries(salary_week="2026-W18", actor={"username": "system", "role": "system"})

    assert first["created_count"] == 1
    assert second["created_count"] == 0
    assert service.get_wallet(2)["points_balance"] == 100
    assert service.get_wallet(3)["points_balance"] == 0


def test_points_ledger_is_append_only(tmp_path):
    service = _service(tmp_path)
    tx = service.record_transaction(
        user_id=1,
        currency_type="points",
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
        currency_type="points",
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


def test_points_chain_verify_identifies_tampered_ledger(tmp_path):
    service = _service(tmp_path)
    tx = service.record_transaction(
        user_id=1,
        currency_type="points",
        direction="credit",
        amount=10,
        action_type="test_credit",
    )
    conn = service.get_db()
    try:
        conn.execute("DROP TRIGGER trg_points_ledger_core_immutable")
        conn.execute("UPDATE points_ledger SET amount=99 WHERE ledger_uuid=?", (tx["ledger"]["ledger_uuid"],))
        conn.commit()
    finally:
        conn.close()

    verification = service.verify_chain()
    assert verification["ok"] is False
    error = next(row for row in verification["errors"] if row["type"] == "ledger_hash")
    assert error["ledger_uuid"] == tx["ledger"]["ledger_uuid"]
    assert error["ledger"]["amount"] == 99
    assert error["expected_ledger_hash"]
    assert error["actual_ledger_hash"] == tx["ledger"]["ledger_hash"]

    report = service.root_report()
    flagged = next(row for row in report["high_risk_ledger"] if row["ledger_uuid"] == tx["ledger"]["ledger_uuid"])
    assert flagged["verification_status"] == "tampered"
    assert flagged["verification_errors"][0]["type"] == "ledger_hash"


def test_points_chain_seal_adds_local_signature_and_root_report(tmp_path):
    service = _service(tmp_path)
    service.record_transaction(
        user_id=1,
        currency_type="points",
        direction="credit",
        amount=10,
        action_type="test_credit",
    )

    sealed = service.seal_block(actor={"id": 3, "username": "root", "role": "super_admin"}, limit=100)
    service.admin_adjust(
        actor={"id": 3, "username": "root", "role": "super_admin"},
        user_id=1,
        currency_type="points",
        direction="credit",
        amount=7,
        reason="manual bonus",
    )
    report = service.root_report()

    assert sealed["sealed"] is True
    assert report["verification"]["ok"] is True
    assert report["blocks"][0]["signature_algorithm"] == "hmac-sha256"
    assert report["audit_logs"][0]["event_type"] in {"POINTS_BLOCK_SEALED", "LEDGER_APPEND"}
    assert report["block_schedule"]["mode"] == "hybrid"
    assert report["block_schedule"]["ledger_threshold"] == 30
    assert report["block_schedule"]["max_interval_minutes"] == 24 * 60
    assert report["block_schedule"]["unsealed_entries"] == 0
    assert report["adjustments"][0]["actor_username"] == "root"
    assert report["adjustments"][0]["target_username"] == "alice"
    assert report["adjustments"][0]["signed_amount"] == 7
    assert report["adjustments"][0]["reason"] == "manual bonus"
    report_json = json.dumps(report, ensure_ascii=False)
    assert '"soft"' not in report_json
    assert '"hard"' not in report_json


def test_root_report_sanitizes_legacy_currency_audit_text(tmp_path):
    service = _service(tmp_path)
    service.record_transaction(
        user_id=1,
        currency_type="points",
        direction="credit",
        amount=10,
        action_type="test_credit",
    )
    conn = service.get_db()
    try:
        conn.execute(
            """
            INSERT INTO points_chain_audit_logs (
                event_type, severity, actor_user_id, actor_role, target_user_id,
                related_ledger_id, related_block_id, message, metadata_json, created_at
            ) VALUES ('LEGACY_AUDIT', 'info', NULL, NULL, 1, NULL, NULL, ?, ?, '2026-04-29T00:00:00Z')
            """,
            (
                "credit 10 soft for user 1",
                json.dumps({"currency_type": "soft", "note": "legacy hard reward"}),
            ),
        )
        conn.commit()
    finally:
        conn.close()

    report = service.root_report()
    legacy = next(row for row in report["audit_logs"] if row["event_type"] == "LEGACY_AUDIT")

    assert legacy["message"] == "credit 10 points for user 1"
    assert legacy["metadata"]["currency_type"] == "points"
    assert legacy["metadata"]["note"] == "legacy points reward"
    assert '"soft"' not in json.dumps(report, ensure_ascii=False)
    assert '"hard"' not in json.dumps(report, ensure_ascii=False)


def test_root_rollback_creates_compensating_append_only_ledger(tmp_path):
    service = _service(tmp_path)
    tx = service.record_transaction(
        user_id=1,
        currency_type="points",
        direction="credit",
        amount=10,
        action_type="test_credit",
    )

    rollback = service.rollback_ledger(
        actor={"id": 3, "username": "root", "role": "super_admin"},
        ledger_uuid=tx["ledger"]["ledger_uuid"],
        reason="emergency correction",
    )

    assert rollback["rollback_ledger"]["direction"] == "reverse"
    assert rollback["rollback_ledger"]["reference_id"] == tx["ledger"]["ledger_uuid"]
    assert rollback["wallet"]["points_balance"] == 0
    assert service.verify_chain()["ok"] is True
    audit_events = [row["event_type"] for row in service.list_chain_audit_logs(limit=10)]
    assert "LEDGER_ROLLBACK" in audit_events

    with pytest.raises(ValueError, match="already reversed"):
        service.rollback_ledger(
            actor={"id": 3, "username": "root", "role": "super_admin"},
            ledger_uuid=tx["ledger"]["ledger_uuid"],
            reason="duplicate correction",
        )


def test_root_can_sanction_wallet_and_freeze_points(tmp_path):
    service = _service(tmp_path)
    root_actor = {"id": 3, "username": "root", "role": "super_admin"}
    service.record_transaction(
        user_id=1,
        currency_type="points",
        direction="credit",
        amount=20,
        action_type="test_credit",
    )

    frozen = service.sanction_wallet(
        actor=root_actor,
        user_id=1,
        wallet_status="frozen",
        risk_level="high",
        reason="abuse investigation",
        freeze_amount=7,
    )

    assert frozen["wallet"]["wallet_status"] == "frozen"
    assert frozen["wallet"]["risk_level"] == "high"
    assert frozen["wallet"]["points_balance"] == 13
    assert frozen["wallet"]["points_frozen"] == 7
    assert frozen["ledgers"][0]["direction"] == "freeze"

    with pytest.raises(ValueError, match="wallet is frozen"):
        service.record_transaction(
            user_id=1,
            currency_type="points",
            direction="debit",
            amount=1,
            action_type="test_debit",
        )

    active = service.sanction_wallet(
        actor=root_actor,
        user_id=1,
        wallet_status="active",
        risk_level="normal",
        reason="appeal accepted",
        unfreeze_amount=7,
    )

    assert active["wallet"]["wallet_status"] == "active"
    assert active["wallet"]["risk_level"] == "normal"
    assert active["wallet"]["points_balance"] == 20
    assert active["wallet"]["points_frozen"] == 0
    assert active["ledgers"][0]["direction"] == "unfreeze"
    audit_events = [row["event_type"] for row in service.list_chain_audit_logs(limit=20)]
    assert "WALLET_SANCTION" in audit_events

    limited = service.sanction_wallet(
        actor=root_actor,
        user_id=1,
        wallet_status="limited",
        risk_level="watch",
        reason="temporary spend limit",
    )
    assert limited["wallet"]["wallet_status"] == "limited"
    with pytest.raises(ValueError, match="wallet is limited"):
        service.record_transaction(
            user_id=1,
            currency_type="points",
            direction="debit",
            amount=1,
            action_type="test_limited_spend",
        )

    with pytest.raises(ValueError, match="root wallet cannot be sanctioned"):
        service.sanction_wallet(
            actor=root_actor,
            user_id=3,
            wallet_status="closed",
            risk_level="blocked",
            reason="root should not be point-sanctioned",
        )


def test_points_chain_auto_seals_when_hybrid_count_threshold_is_met(tmp_path):
    service = _service(tmp_path)
    actor = {"id": 3, "username": "root", "role": "super_admin"}
    for idx in range(9):
        service.record_transaction(
            user_id=1,
            currency_type="points",
            direction="credit",
            amount=1,
            action_type=f"test_credit_{idx}",
        )

    pending = service.seal_due_block(actor=actor, ledger_threshold=10)
    assert pending["sealed"] is False
    assert pending["schedule"]["unsealed_entries"] == 9
    assert pending["schedule"]["entries_remaining"] == 1

    service.record_transaction(
        user_id=1,
        currency_type="points",
        direction="credit",
        amount=1,
        action_type="test_credit_9",
    )
    sealed = service.seal_due_block(actor=actor, ledger_threshold=10)

    assert sealed["sealed"] is True
    assert sealed["block"]["ledger_count"] == 10
    assert service.verify_chain()["counts"]["unsealed_entries"] == 0


def test_high_risk_admin_adjust_forces_block(tmp_path):
    service = _service(tmp_path)
    result = service.admin_adjust(
        actor={"id": 3, "username": "root", "role": "super_admin"},
        user_id=1,
        currency_type="points",
        direction="credit",
        amount=5,
        reason="manual correction",
    )

    assert result["forced_block"]["sealed"] is True
    assert result["forced_block"]["reason"] == "admin_adjust"
    assert service.verify_chain()["counts"]["unsealed_entries"] == 0
