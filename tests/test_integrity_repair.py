import sqlite3

from services.audit import audit, configure_audit_service, repair_audit_chain, reset_audit_chain_with_event, verify_audit_integrity
from services.violations import (
    configure_violations_service,
    repair_violation_chains,
    secure_add_violation,
    verify_violation_integrity,
)


def _get_db_factory(db_path):
    def get_db():
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        return conn

    return get_db


def test_repair_audit_chain_reseals_corrupted_entries(tmp_path):
    db_path = tmp_path / "audit.db"
    audit_log = tmp_path / "audit.log"
    anchor_log = tmp_path / "audit_head.jsonl"
    anchor_latest = tmp_path / "audit_head_latest.json"

    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        CREATE TABLE secure_audit (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT NOT NULL,
            action TEXT NOT NULL,
            ip TEXT,
            user TEXT,
            success INTEGER NOT NULL DEFAULT 0,
            ua TEXT,
            detail TEXT,
            prev_hash TEXT,
            entry_hash TEXT,
            chain_hash TEXT NOT NULL
        );
        """
    )
    conn.commit()
    conn.close()

    configure_audit_service(
        get_db=_get_db_factory(str(db_path)),
        chain_seed="seed",
        integrity_key=b"test-integrity-key",
        audit_log_path=str(audit_log),
        audit_anchor_path=str(anchor_log),
        audit_anchor_latest_path=str(anchor_latest),
        audit_anchor_interval_seconds=0,
    )
    audit("FIRST", "127.0.0.1", user="root", success=True, detail="ok")
    audit("SECOND", "127.0.0.1", user="root", success=True, detail="ok")
    assert verify_audit_integrity()[0] is True

    conn = sqlite3.connect(db_path)
    conn.execute("UPDATE secure_audit SET detail='tampered' WHERE id=1")
    conn.commit()
    conn.close()
    assert verify_audit_integrity()[0] is False

    result = repair_audit_chain(reason="test")

    assert result["entries_resealed"] == 2
    ok, broken_at, _ = verify_audit_integrity()
    assert ok is True
    assert broken_at is None


def test_reset_audit_chain_with_event_starts_new_chain_and_anchor(tmp_path):
    db_path = tmp_path / "audit.db"
    audit_log = tmp_path / "audit.log"
    anchor_log = tmp_path / "audit_head.jsonl"
    anchor_latest = tmp_path / "audit_head_latest.json"
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        CREATE TABLE secure_audit (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT NOT NULL,
            action TEXT NOT NULL,
            ip TEXT,
            user TEXT,
            success INTEGER NOT NULL DEFAULT 0,
            ua TEXT,
            detail TEXT,
            prev_hash TEXT,
            entry_hash TEXT,
            chain_hash TEXT NOT NULL
        );
        """
    )
    conn.commit()
    conn.close()
    configure_audit_service(
        get_db=_get_db_factory(str(db_path)),
        chain_seed="seed",
        integrity_key=b"test-integrity-key",
        audit_log_path=str(audit_log),
        audit_anchor_path=str(anchor_log),
        audit_anchor_latest_path=str(anchor_latest),
        audit_anchor_interval_seconds=0,
    )
    audit("OLD", "127.0.0.1", user="root", success=True, detail="old")

    result = reset_audit_chain_with_event("SYSTEM_RUNTIME_RESET", "-", user="root", success=True, detail="reset")

    assert result["ok"] is True
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT id, action, prev_hash FROM secure_audit ORDER BY id").fetchall()
    conn.close()
    assert [(row["id"], row["action"], row["prev_hash"]) for row in rows] == [(1, "SYSTEM_RUNTIME_RESET", "seed")]
    assert "SYSTEM_RUNTIME_RESET" in audit_log.read_text(encoding="utf-8")
    assert "OLD" not in audit_log.read_text(encoding="utf-8")
    ok, broken_at, _ = verify_audit_integrity()
    assert ok is True
    assert broken_at is None


def test_repair_violation_chains_reseals_corrupted_entries(tmp_path):
    db_path = tmp_path / "violations.db"
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        CREATE TABLE users (
            id INTEGER PRIMARY KEY,
            username TEXT NOT NULL,
            role TEXT NOT NULL,
            violation_count INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE secure_violations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            username TEXT NOT NULL,
            points INTEGER NOT NULL DEFAULT 1,
            reason TEXT NOT NULL,
            triggered_by TEXT NOT NULL,
            actor_username TEXT NOT NULL,
            created_at TEXT NOT NULL,
            prev_hash TEXT NOT NULL,
            entry_hash TEXT NOT NULL
        );
        """
    )
    conn.execute(
        "INSERT INTO users (id, username, role, violation_count) VALUES (1, 'alice', 'user', 0)"
    )
    conn.commit()
    conn.close()

    configure_violations_service(
        get_db=_get_db_factory(str(db_path)),
        get_system_settings=lambda: {},
        audit=lambda *args, **kwargs: None,
        get_client_ip=lambda: "127.0.0.1",
        chain_seed="seed",
        integrity_key=b"test-integrity-key",
    )
    secure_add_violation(1, "alice", "user", 1, "first", "system", "root")
    secure_add_violation(1, "alice", "user", 1, "second", "system", "root")
    assert verify_violation_integrity(1)[0] is True

    conn = sqlite3.connect(db_path)
    conn.execute("UPDATE secure_violations SET entry_hash='broken' WHERE id=1")
    conn.commit()
    conn.close()
    assert verify_violation_integrity(1)[0] is False

    result = repair_violation_chains()

    assert result == {"entries_resealed": 2, "users_resealed": 1}
    ok, broken_at, _ = verify_violation_integrity(1)
    assert ok is True
    assert broken_at is None
