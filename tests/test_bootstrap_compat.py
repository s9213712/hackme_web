import sqlite3
from pathlib import Path

from services import bootstrap


def _get_db_factory(db_path):
    def get_db():
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        return conn

    return get_db


def _ensure_session_columns(conn):
    cols = {row["name"] for row in conn.execute("PRAGMA table_info(sessions)").fetchall()}
    if "is_revoked" not in cols:
        conn.execute("ALTER TABLE sessions ADD COLUMN is_revoked INTEGER NOT NULL DEFAULT 0")
    if "revoked_at" not in cols:
        conn.execute("ALTER TABLE sessions ADD COLUMN revoked_at TEXT")
    if "last_seen" not in cols:
        conn.execute("ALTER TABLE sessions ADD COLUMN last_seen TEXT")
    if "device_info" not in cols:
        conn.execute("ALTER TABLE sessions ADD COLUMN device_info TEXT")
    if "ip_country" not in cols:
        conn.execute("ALTER TABLE sessions ADD COLUMN ip_country TEXT")
    conn.execute("UPDATE sessions SET is_revoked=0 WHERE is_revoked IS NULL")
    conn.execute("UPDATE sessions SET last_seen=created_at WHERE last_seen IS NULL")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_sessions_expires_at ON sessions(expires_at)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_sessions_last_seen ON sessions(last_seen)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_sessions_revoked ON sessions(is_revoked)")


def _noop(*args, **kwargs):
    return None


def test_init_db_repairs_legacy_sessions_before_schema_replay(tmp_path, monkeypatch):
    db_path = tmp_path / "legacy.db"
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        CREATE TABLE schema_migrations (
            version     INTEGER PRIMARY KEY,
            name        TEXT NOT NULL,
            applied_at  TEXT NOT NULL
        );
        INSERT INTO schema_migrations (version, name, applied_at) VALUES
            (1, 'bootstrap schema_migrations metadata table', '2026-01-01T00:00:00'),
            (2, 'ensure legacy-compatible users columns', '2026-01-01T00:00:00'),
            (3, 'ensure violation_appeals columns', '2026-01-01T00:00:00'),
            (4, 'ensure system_settings baseline rows', '2026-01-01T00:00:00');

        CREATE TABLE sessions (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id      INTEGER NOT NULL,
            token_hash   TEXT    NOT NULL UNIQUE,
            ip_address   TEXT,
            user_agent   TEXT,
            expires_at   TEXT    NOT NULL,
            created_at   TEXT    NOT NULL DEFAULT (datetime('now'))
        );

        CREATE TABLE chat_rooms (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            name           TEXT    NOT NULL UNIQUE,
            owner_user_id  INTEGER,
            is_active      INTEGER NOT NULL DEFAULT 1,
            created_at     TEXT    NOT NULL DEFAULT (datetime('now'))
        );
        """
    )
    conn.commit()
    conn.close()

    schema_path = Path(__file__).resolve().parents[1] / "database" / "bootstrap.schema.sql"
    missing_json = str(tmp_path / "missing.json")
    original_state = dict(bootstrap._STATE)

    monkeypatch.setenv("HTML_LEARNING_ROOT_PASSWORD", "root")

    try:
        bootstrap.configure_bootstrap_service(
            get_db=_get_db_factory(str(db_path)),
            db_path=str(db_path),
            schema_path=str(schema_path),
            legacy_fail_log=missing_json,
            legacy_blocked_ips=missing_json,
            legacy_rate_limit=missing_json,
            legacy_audit_log=missing_json,
            chain_seed="seed",
            chain_hash=lambda prev_hash, entry_json: f"{prev_hash}:{len(entry_json)}",
            load_json=lambda path: {},
            normalize_text=lambda value: value if isinstance(value, str) else "",
            hash_password=lambda value: f"hash:{value}",
            audit=_noop,
            refresh_system_settings=_noop,
            init_system_settings_table=_noop,
            seed_missing_settings=_noop,
            import_legacy_settings_files=_noop,
            default_settings={},
        )
        bootstrap.init_db(
            ensure_secure_audit_columns=_noop,
            ensure_user_columns=_noop,
            ensure_appeal_columns=_noop,
            ensure_session_columns=_ensure_session_columns,
            ensure_security_support_schema=_noop,
            ensure_official_chat_room=_noop,
            hash_password=lambda value: f"hash:{value}",
        )
    finally:
        bootstrap._STATE.clear()
        bootstrap._STATE.update(original_state)

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    session_cols = {row["name"] for row in conn.execute("PRAGMA table_info(sessions)").fetchall()}
    chat_room_cols = {row["name"] for row in conn.execute("PRAGMA table_info(chat_rooms)").fetchall()}
    user_cols = {row["name"] for row in conn.execute("PRAGMA table_info(users)").fetchall()}
    login_location_cols = {row["name"] for row in conn.execute("PRAGMA table_info(login_locations)").fetchall()}
    migration_versions = [row["version"] for row in conn.execute("SELECT version FROM schema_migrations ORDER BY version").fetchall()]
    root_user = conn.execute("SELECT username FROM users WHERE username='root'").fetchone()
    conn.close()

    assert {"is_revoked", "revoked_at", "last_seen", "device_info", "ip_country"} <= session_cols
    assert "is_private" in chat_room_cols
    assert {"member_level", "trust_score", "points", "reputation", "locked_until", "password_strength_score", "deleted_at"} <= user_cols
    assert {"ip_hash", "login_at", "is_suspicious"} <= login_location_cols
    assert migration_versions == [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11]
    assert root_user["username"] == "root"


def test_init_db_allows_existing_root_password_without_bootstrap_env(tmp_path, monkeypatch):
    db_path = tmp_path / "existing-root.db"
    schema_path = Path(__file__).resolve().parents[1] / "database" / "bootstrap.schema.sql"

    conn = sqlite3.connect(db_path)
    conn.executescript(schema_path.read_text(encoding="utf-8"))
    now = "2026-01-01T00:00:00"
    cur = conn.execute(
        "INSERT INTO users (username, status, role, created_at, updated_at) VALUES (?, 'active', 'super_admin', ?, ?)",
        ("root", now, now),
    )
    conn.execute(
        "INSERT INTO user_passwords (user_id, password_hash, created_at) VALUES (?, ?, ?)",
        (cur.lastrowid, "hash:root", now),
    )
    conn.commit()
    conn.close()

    missing_json = str(tmp_path / "missing.json")
    original_state = dict(bootstrap._STATE)
    monkeypatch.delenv("HTML_LEARNING_ROOT_PASSWORD", raising=False)

    try:
        bootstrap.configure_bootstrap_service(
            get_db=_get_db_factory(str(db_path)),
            db_path=str(db_path),
            schema_path=str(schema_path),
            legacy_fail_log=missing_json,
            legacy_blocked_ips=missing_json,
            legacy_rate_limit=missing_json,
            legacy_audit_log=missing_json,
            chain_seed="seed",
            chain_hash=lambda prev_hash, entry_json: f"{prev_hash}:{len(entry_json)}",
            load_json=lambda path: {},
            normalize_text=lambda value: value if isinstance(value, str) else "",
            hash_password=lambda value: f"hash:{value}",
            audit=_noop,
            refresh_system_settings=_noop,
            init_system_settings_table=_noop,
            seed_missing_settings=_noop,
            import_legacy_settings_files=_noop,
            default_settings={},
        )
        bootstrap.init_db(
            ensure_secure_audit_columns=_noop,
            ensure_user_columns=_noop,
            ensure_appeal_columns=_noop,
            ensure_session_columns=_ensure_session_columns,
            ensure_security_support_schema=_noop,
            ensure_official_chat_room=_noop,
            hash_password=lambda value: f"hash:{value}",
        )
    finally:
        bootstrap._STATE.clear()
        bootstrap._STATE.update(original_state)

    conn = sqlite3.connect(db_path)
    count = conn.execute("SELECT COUNT(*) FROM user_passwords").fetchone()[0]
    conn.close()
    assert count == 1
