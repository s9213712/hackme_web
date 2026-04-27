import sqlite3
from datetime import datetime, timedelta

from services import auth


def _get_db_factory(db_path):
    def get_db():
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        return conn

    return get_db


def _seed_db(db_path):
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        CREATE TABLE users (
            id INTEGER PRIMARY KEY,
            username TEXT NOT NULL UNIQUE,
            status TEXT NOT NULL DEFAULT 'active'
        );
        CREATE TABLE sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            token_hash TEXT NOT NULL UNIQUE,
            ip_address TEXT,
            user_agent TEXT,
            expires_at TEXT NOT NULL,
            is_revoked INTEGER NOT NULL DEFAULT 0,
            revoked_at TEXT,
            last_seen TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        """
    )
    conn.execute("INSERT INTO users (id, username, status) VALUES (1, 'alice', 'active')")
    conn.commit()
    conn.close()


def test_session_is_revoked_after_idle_timeout(tmp_path):
    db_path = tmp_path / "idle.db"
    _seed_db(db_path)
    original_state = dict(auth._STATE)

    try:
        auth.configure_auth_service(
            get_db=_get_db_factory(str(db_path)),
            get_user_by_username=lambda username: None,
            fernet=None,
            session_ttl=3600,
            csrf_token_ttl=3600,
            session_idle_timeout=180,
        )
        auth.db_save_session(1, "token", "127.0.0.1", "test-agent")

        stale_seen = (datetime.now() - timedelta(seconds=181)).isoformat()
        conn = sqlite3.connect(db_path)
        conn.execute("UPDATE sessions SET last_seen=? WHERE id=1", (stale_seen,))
        conn.commit()
        conn.close()

        assert auth.db_get_user_from_token("token") is None

        conn = sqlite3.connect(db_path)
        row = conn.execute("SELECT is_revoked, revoked_at FROM sessions WHERE id=1").fetchone()
        conn.close()
        assert row[0] == 1
        assert row[1]
    finally:
        auth._STATE.clear()
        auth._STATE.update(original_state)


def test_active_session_refreshes_last_seen(tmp_path):
    db_path = tmp_path / "idle.db"
    _seed_db(db_path)
    original_state = dict(auth._STATE)

    try:
        auth.configure_auth_service(
            get_db=_get_db_factory(str(db_path)),
            get_user_by_username=lambda username: None,
            fernet=None,
            session_ttl=3600,
            csrf_token_ttl=3600,
            session_idle_timeout=180,
        )
        auth.db_save_session(1, "token", "127.0.0.1", "test-agent")

        recent_seen = (datetime.now() - timedelta(seconds=30)).isoformat()
        conn = sqlite3.connect(db_path)
        conn.execute("UPDATE sessions SET last_seen=? WHERE id=1", (recent_seen,))
        conn.commit()
        conn.close()

        assert auth.db_get_user_from_token("token") == "alice"

        conn = sqlite3.connect(db_path)
        row = conn.execute("SELECT is_revoked, last_seen FROM sessions WHERE id=1").fetchone()
        conn.close()
        assert row[0] == 0
        assert row[1] > recent_seen
    finally:
        auth._STATE.clear()
        auth._STATE.update(original_state)


def test_db_save_session_stores_device_info_when_column_exists(tmp_path):
    db_path = tmp_path / "device.db"
    _seed_db(db_path)
    conn = sqlite3.connect(db_path)
    conn.execute("ALTER TABLE sessions ADD COLUMN device_info TEXT")
    conn.execute("ALTER TABLE sessions ADD COLUMN ip_country TEXT")
    conn.commit()
    conn.close()
    original_state = dict(auth._STATE)

    try:
        auth.configure_auth_service(
            get_db=_get_db_factory(str(db_path)),
            get_user_by_username=lambda username: None,
            fernet=None,
            session_ttl=3600,
            csrf_token_ttl=3600,
            session_idle_timeout=180,
        )
        auth.db_save_session(1, "token", "127.0.0.1", "Mozilla/5.0 Chrome/120 Windows")

        conn = sqlite3.connect(db_path)
        row = conn.execute("SELECT device_info FROM sessions WHERE id=1").fetchone()
        conn.close()

        assert "Chrome" in row[0]
        assert "Windows" in row[0]
    finally:
        auth._STATE.clear()
        auth._STATE.update(original_state)
