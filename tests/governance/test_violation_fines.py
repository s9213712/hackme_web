import sqlite3
from datetime import datetime, timedelta, timezone

import pytest
from services.governance import violations
from services.governance.violation_fines import (
    active_feature_restrictions,
    assert_user_feature_allowed,
    ensure_violation_fine_schema,
    list_violation_fines,
    mark_violation_fine_paid,
    review_violation_fine_appeal,
    submit_violation_fine_appeal,
    waive_violation_fine,
)
from services.security.permissions import require_member_action


def _connect(path):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def _seed_db(path):
    conn = _connect(path)
    conn.executescript(
        """
        CREATE TABLE users (
            id INTEGER PRIMARY KEY,
            username TEXT NOT NULL UNIQUE,
            role TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'active',
            violation_count INTEGER NOT NULL DEFAULT 0,
            member_level TEXT NOT NULL DEFAULT 'normal',
            updated_at TEXT
        );
        CREATE TABLE secure_violations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            username TEXT NOT NULL,
            points INTEGER NOT NULL,
            reason TEXT NOT NULL,
            triggered_by TEXT NOT NULL,
            actor_username TEXT NOT NULL,
            created_at TEXT NOT NULL,
            prev_hash TEXT NOT NULL,
            entry_hash TEXT NOT NULL
        );
        """
    )
    conn.executemany(
        "INSERT INTO users (id, username, role) VALUES (?, ?, ?)",
        [
            (1, "root", "super_admin"),
            (2, "admin", "manager"),
            (3, "alice", "user"),
        ],
    )
    ensure_violation_fine_schema(conn)
    conn.commit()
    conn.close()


def _configure(path, audits):
    violations.configure_violations_service(
        get_db=lambda: _connect(path),
        get_system_settings=lambda: {},
        audit=lambda *args, **kwargs: audits.append((args, kwargs)),
        get_client_ip=lambda: "127.0.0.1",
        chain_seed="test-chain-seed",
        integrity_key=b"test-integrity-key",
    )


def test_three_strikes_create_fine_and_overdue_restricts_selected_features(tmp_path):
    db_path = tmp_path / "violations.db"
    audits = []
    _seed_db(db_path)
    _configure(str(db_path), audits)

    for idx in range(3):
        result = violations.add_violation(
            3,
            "alice",
            "user",
            points=1,
            reason=f"spam {idx}",
            triggered_by="manager",
            actor_username="admin",
        )
        assert result[0] == "counted"

    conn = _connect(db_path)
    try:
        fines, total = list_violation_fines(conn, user_id=3)
        assert total == 1
        fine = fines[0]
        assert fine["policy_key"] == "three_strikes_unlock"
        assert fine["amount_points"] == 300
        assert fine["status"] == "pending"

        past = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
        conn.execute("UPDATE violation_fines SET due_at=? WHERE fine_uuid=?", (past, fine["fine_uuid"]))
        conn.commit()

        restrictions = active_feature_restrictions(conn, user_id=3, feature_key="community_post")
        assert len(restrictions) == 1
        ok, msg, status = require_member_action(
            {"id": 3, "username": "alice", "role": "user", "status": "active", "member_level": "normal"},
            "community_thread_create",
            conn=conn,
        )
        assert ok is False
        assert status == 423
        assert "功能已暫停" in msg
    finally:
        conn.close()


def test_fine_payment_releases_overdue_feature_restrictions(tmp_path):
    db_path = tmp_path / "violations.db"
    audits = []
    _seed_db(db_path)
    _configure(str(db_path), audits)
    for idx in range(3):
        violations.add_violation(3, "alice", "user", points=1, reason=f"abuse {idx}", triggered_by="manager", actor_username="admin")

    conn = _connect(db_path)
    try:
        fine = list_violation_fines(conn, user_id=3)[0][0]
        past = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
        conn.execute("UPDATE violation_fines SET due_at=? WHERE fine_uuid=?", (past, fine["fine_uuid"]))
        active_feature_restrictions(conn, user_id=3, feature_key="service_spend")

        updated = mark_violation_fine_paid(
            conn,
            fine_uuid=fine["fine_uuid"],
            payment_ledger_uuid="ledger-1",
            payment_charge_uuid="charge-1",
            payment_source_wallet_address="pc1payer",
        )
        conn.commit()

        assert updated["status"] == "paid"
        assert active_feature_restrictions(conn, user_id=3, feature_key="service_spend") == []
    finally:
        conn.close()


def test_fine_appeal_can_waive_fine_and_release_restrictions(tmp_path):
    db_path = tmp_path / "violations.db"
    audits = []
    _seed_db(db_path)
    _configure(str(db_path), audits)
    for idx in range(3):
        violations.add_violation(3, "alice", "user", points=1, reason=f"case {idx}", triggered_by="manager", actor_username="admin")

    conn = _connect(db_path)
    try:
        fine = list_violation_fines(conn, user_id=3)[0][0]
        conn.execute(
            "UPDATE violation_fines SET due_at=? WHERE fine_uuid=?",
            ((datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat(), fine["fine_uuid"]),
        )
        active_feature_restrictions(conn, user_id=3, feature_key="trading_order")
        appeal, created = submit_violation_fine_appeal(
            conn,
            fine_uuid=fine["fine_uuid"],
            user_id=3,
            username="alice",
            reason="罰單依據已撤銷，請重新審查",
        )
        assert created is True

        reviewed, waived_fine = review_violation_fine_appeal(
            conn,
            appeal_id=appeal["id"],
            actor_username="admin",
            action="approve",
            note="違規證據不足",
        )
        conn.commit()

        assert reviewed["status"] == "approved"
        assert waived_fine["status"] == "waived"
        assert active_feature_restrictions(conn, user_id=3, feature_key="trading_order") == []
    finally:
        conn.close()


def test_no_duplicate_three_strike_fine_after_more_violations(tmp_path):
    db_path = tmp_path / "violations.db"
    audits = []
    _seed_db(db_path)
    _configure(str(db_path), audits)

    for idx in range(5):
        violations.add_violation(3, "alice", "user", points=1, reason=f"repeat {idx}", triggered_by="manager", actor_username="admin")

    conn = _connect(db_path)
    try:
        fines, total = list_violation_fines(conn, user_id=3)
        three_strike_fines = [fine for fine in fines if fine["policy_key"] == "three_strikes_unlock"]
        assert len(three_strike_fines) == 1
    finally:
        conn.close()


def test_restriction_only_applies_after_due_at(tmp_path):
    db_path = tmp_path / "violations.db"
    audits = []
    _seed_db(db_path)
    _configure(str(db_path), audits)
    for idx in range(3):
        violations.add_violation(3, "alice", "user", points=1, reason=f"not overdue {idx}", triggered_by="manager", actor_username="admin")

    conn = _connect(db_path)
    try:
        assert active_feature_restrictions(conn, user_id=3, feature_key="community_post") == []
        ok, msg, status = require_member_action(
            {"id": 3, "username": "alice", "role": "user", "status": "active", "member_level": "normal"},
            "community_thread_create",
            conn=conn,
        )
        assert ok is True
        assert msg == ""
        assert status == 200
    finally:
        conn.close()


def test_permission_check_blocks_overdue_fine_without_materializing_restrictions(tmp_path):
    db_path = tmp_path / "violations.db"
    audits = []
    _seed_db(db_path)
    _configure(str(db_path), audits)
    for idx in range(3):
        violations.add_violation(3, "alice", "user", points=1, reason=f"hot path {idx}", triggered_by="manager", actor_username="admin")

    conn = _connect(db_path)
    try:
        fine = list_violation_fines(conn, user_id=3)[0][0]
        past = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
        conn.execute("UPDATE violation_fines SET status='pending', due_at=? WHERE fine_uuid=?", (past, fine["fine_uuid"]))
        conn.execute("DELETE FROM user_feature_restrictions WHERE user_id=3")
        conn.commit()

        allowed, msg, restrictions = assert_user_feature_allowed(conn, user_id=3, feature_key="community_post")

        assert allowed is False
        assert "功能已暫停" in msg
        assert restrictions[0]["source_ref"] == fine["fine_uuid"]
        materialized_count = conn.execute("SELECT COUNT(*) AS c FROM user_feature_restrictions WHERE user_id=3").fetchone()["c"]
        assert materialized_count == 0
    finally:
        conn.close()


def test_rejected_fine_appeal_keeps_fine_and_restrictions(tmp_path):
    db_path = tmp_path / "violations.db"
    audits = []
    _seed_db(db_path)
    _configure(str(db_path), audits)
    for idx in range(3):
        violations.add_violation(3, "alice", "user", points=1, reason=f"reject {idx}", triggered_by="manager", actor_username="admin")

    conn = _connect(db_path)
    try:
        fine = list_violation_fines(conn, user_id=3)[0][0]
        conn.execute(
            "UPDATE violation_fines SET due_at=? WHERE fine_uuid=?",
            ((datetime.now(timezone.utc) - timedelta(days=2)).isoformat(), fine["fine_uuid"]),
        )
        assert active_feature_restrictions(conn, user_id=3, feature_key="trading_order")
        appeal, _created = submit_violation_fine_appeal(
            conn,
            fine_uuid=fine["fine_uuid"],
            user_id=3,
            username="alice",
            reason="請重新審查罰單理由",
        )
        reviewed, waived_fine = review_violation_fine_appeal(
            conn,
            appeal_id=appeal["id"],
            actor_username="admin",
            action="reject",
            note="維持罰單",
        )
        conn.commit()

        fine_after = list_violation_fines(conn, user_id=3)[0][0]
        assert reviewed["status"] == "rejected"
        assert waived_fine is None
        assert fine_after["status"] == "overdue"
        assert active_feature_restrictions(conn, user_id=3, feature_key="trading_order")
    finally:
        conn.close()


def test_paid_fine_cannot_be_waived_or_appealed_again(tmp_path):
    db_path = tmp_path / "violations.db"
    audits = []
    _seed_db(db_path)
    _configure(str(db_path), audits)
    for idx in range(3):
        violations.add_violation(3, "alice", "user", points=1, reason=f"paid {idx}", triggered_by="manager", actor_username="admin")

    conn = _connect(db_path)
    try:
        fine = list_violation_fines(conn, user_id=3)[0][0]
        mark_violation_fine_paid(
            conn,
            fine_uuid=fine["fine_uuid"],
            payment_ledger_uuid="ledger-paid",
            payment_charge_uuid="charge-paid",
            payment_source_wallet_address="pc1payer",
        )
        conn.commit()

        with pytest.raises(ValueError, match="already closed"):
            submit_violation_fine_appeal(conn, fine_uuid=fine["fine_uuid"], user_id=3, username="alice", reason="已繳後再申覆")
        with pytest.raises(ValueError, match="already closed"):
            waive_violation_fine(conn, fine_uuid=fine["fine_uuid"], actor_username="admin", reason="late waive")
    finally:
        conn.close()


def test_mark_paid_requires_payable_status_and_interest_is_added_after_overdue(tmp_path):
    db_path = tmp_path / "violations.db"
    audits = []
    _seed_db(db_path)
    _configure(str(db_path), audits)
    for idx in range(3):
        violations.add_violation(3, "alice", "user", points=1, reason=f"interest {idx}", triggered_by="manager", actor_username="admin")

    conn = _connect(db_path)
    try:
        fine = list_violation_fines(conn, user_id=3)[0][0]
        conn.execute(
            "UPDATE violation_fines SET due_at=? WHERE fine_uuid=?",
            ((datetime.now(timezone.utc) - timedelta(hours=72, minutes=1)).isoformat(), fine["fine_uuid"]),
        )
        refreshed = list_violation_fines(conn, user_id=3)[0][0]
        assert refreshed["status"] == "overdue"
        # Current policy snapshot: 5% per 24h, capped at 50%, for three elapsed periods.
        assert refreshed["overdue_interest_points"] == 45
        assert refreshed["amount_due_points"] == 345

        waive_violation_fine(conn, fine_uuid=fine["fine_uuid"], actor_username="admin", reason="test waive")
        conn.commit()
        with pytest.raises(ValueError, match="not payable"):
            mark_violation_fine_paid(
                conn,
                fine_uuid=fine["fine_uuid"],
                payment_ledger_uuid="ledger-after-waive",
                payment_charge_uuid="charge-after-waive",
                payment_source_wallet_address="pc1payer",
            )
    finally:
        conn.close()
