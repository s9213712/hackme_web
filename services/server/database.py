"""Database and schema helpers extracted from ``server.py``."""

from __future__ import annotations

import re
import sqlite3
from datetime import datetime


def get_db(db_path, *, register_app_mode=None):
    conn = sqlite3.connect(db_path, timeout=15)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA busy_timeout = 15000")
    except Exception:
        pass
    try:
        if register_app_mode is not None:
            register_app_mode(conn)
    except Exception:
        pass
    return conn


def count_role(role, *, get_db):
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT COUNT(*) as c FROM users WHERE role=? AND username<>'root'",
            (role,),
        ).fetchone()
        return row["c"] if row else 0
    finally:
        conn.close()


def get_user_by_username(username, *, get_db):
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT id, username, email, nickname, real_name, birthdate, id_number, phone, status, role, "
            "member_level, base_level, effective_level, trust_score, points, reputation, violation_score, "
            "sanction_status, sanction_until, level_updated_at, level_updated_by, level_update_reason, "
            "password_strength_score, must_change_password, is_default_password, avatar_file_id, avatar_crop_json, blocked_until, violation_count, chat_violation_warned "
            "FROM users WHERE username=?",
            (username,),
        ).fetchone()
        if not row:
            return None
        return row
    finally:
        conn.close()


def ensure_user_columns(conn, *, ensure_user_identity_columns):
    ensure_user_identity_columns(conn)


def ensure_secure_audit_columns(conn):
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(secure_audit)").fetchall()}
    for name in ("prev_hash", "entry_hash"):
        if name not in cols:
            conn.execute(f"ALTER TABLE secure_audit ADD COLUMN {name} TEXT")


def ensure_appeal_columns(conn):
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(violation_appeals)").fetchall()}
    additions = [
        ("latest_violation_id", "INTEGER"),
        ("violation_count_snapshot", "INTEGER NOT NULL DEFAULT 0"),
        ("penalty_points", "INTEGER NOT NULL DEFAULT 0"),
        ("pre_status", "TEXT NOT NULL DEFAULT 'active'"),
        ("pre_role", "TEXT NOT NULL DEFAULT 'user'"),
        ("review_note", "TEXT"),
    ]
    for name, ddl in additions:
        if name not in cols:
            conn.execute(f"ALTER TABLE violation_appeals ADD COLUMN {name} {ddl}")


def ensure_session_columns(conn):
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(sessions)").fetchall()}
    additions = [
        ("is_revoked", "INTEGER NOT NULL DEFAULT 0"),
        ("revoked_at", "TEXT"),
        ("last_seen", "TEXT"),
        ("device_info", "TEXT"),
        ("ip_country", "TEXT"),
        ("session_epoch", "INTEGER NOT NULL DEFAULT 0"),
    ]
    for name, ddl in additions:
        if name not in cols:
            conn.execute(f"ALTER TABLE sessions ADD COLUMN {name} {ddl}")
    conn.execute("UPDATE sessions SET is_revoked=0 WHERE is_revoked IS NULL")
    conn.execute("UPDATE sessions SET last_seen=created_at WHERE last_seen IS NULL")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_sessions_expires_at ON sessions(expires_at)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_sessions_last_seen ON sessions(last_seen)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_sessions_revoked ON sessions(is_revoked)")


def ensure_security_support_schema(
    conn,
    *,
    ensure_member_level_rules_schema,
    ensure_moderation_proposals_schema,
    ensure_governance_records_schema,
    ensure_snapshot_schema,
    ensure_upload_security_schema,
    ensure_integrity_schema,
    ensure_account_recovery_schema,
):
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS ip_blocks (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            ip_address     TEXT NOT NULL UNIQUE,
            blocked_until  TEXT NOT NULL,
            reason         TEXT,
            created_at     TEXT NOT NULL DEFAULT (datetime('now'))
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS login_locations (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id       INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            ip_hash       TEXT NOT NULL,
            country       TEXT,
            city          TEXT,
            login_at      TEXT NOT NULL,
            is_suspicious INTEGER NOT NULL DEFAULT 0
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_ip_blocks_ip ON ip_blocks(ip_address)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_ip_blocks_until ON ip_blocks(blocked_until)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_login_locations_user ON login_locations(user_id, login_at)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_login_locations_ip ON login_locations(ip_hash)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_csrf_expires_at ON csrf_tokens(expires_at)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_sec_event_type_ip_time ON security_events(event_type, ip_address, created_at)")
    ensure_member_level_rules_schema(conn)
    ensure_moderation_proposals_schema(conn)
    ensure_governance_records_schema(conn)
    ensure_snapshot_schema(conn)
    ensure_upload_security_schema(conn)
    ensure_integrity_schema(conn)
    ensure_account_recovery_schema(conn)

    legacy_rows = conn.execute(
        "SELECT ip_address, detail, created_at FROM security_events "
        "WHERE event_type='ip_block' ORDER BY id DESC"
    ).fetchall()
    seen = set()
    for row in legacy_rows:
        ip = row["ip_address"]
        if not ip or ip in seen:
            continue
        seen.add(ip)
        detail = row["detail"] or ""
        match = re.search(r"blocked_until=([0-9T:\-\.]+)", detail)
        if not match:
            continue
        blocked_until = match.group(1)
        conn.execute(
            "INSERT OR IGNORE INTO ip_blocks (ip_address, blocked_until, reason, created_at) VALUES (?, ?, ?, ?)",
            (ip, blocked_until, detail, row["created_at"] or datetime.now().isoformat()),
        )


def db_get_user_role(username, *, get_db):
    conn = get_db()
    try:
        row = conn.execute("SELECT role FROM users WHERE username=?", (username,)).fetchone()
        return row["role"] if row else None
    finally:
        conn.close()


def activate_emergency_lockdown(
    reason,
    *,
    get_db,
    init_system_settings_table,
    refresh_system_settings,
    audit,
    get_client_ip_func,
):
    conn = get_db()
    try:
        init_system_settings_table(conn)
        conn.execute(
            "INSERT OR REPLACE INTO system_settings (key, value, updated_at, updated_by) VALUES (?, ?, ?, ?)",
            ("maintenance_mode", "True", datetime.now().isoformat(), "audit_guard"),
        )
        conn.commit()
        refresh_system_settings()
    finally:
        conn.close()
    try:
        audit("EMERGENCY_LOCKDOWN_ENABLED", get_client_ip_func(), user="audit_guard", success=True, detail=reason)
    except Exception:
        pass
