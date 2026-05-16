import sqlite3
from datetime import datetime, timedelta

from flask import Flask

from services.users import auth


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


def test_db_save_session_exposes_internal_test_scope_metadata(tmp_path):
    db_path = tmp_path / "scope.db"
    _seed_db(db_path)
    conn = sqlite3.connect(db_path)
    conn.execute("ALTER TABLE sessions ADD COLUMN auth_scope TEXT NOT NULL DEFAULT ''")
    conn.execute("ALTER TABLE sessions ADD COLUMN allowed_features_json TEXT NOT NULL DEFAULT '[]'")
    conn.commit()
    conn.close()
    original_state = dict(auth._STATE)
    app = Flask(__name__)

    def get_user_by_username(username):
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        try:
            return conn.execute("SELECT id, username, status FROM users WHERE username=?", (username,)).fetchone()
        finally:
            conn.close()

    try:
        auth.configure_auth_service(
            get_db=_get_db_factory(str(db_path)),
            get_user_by_username=get_user_by_username,
            fernet=None,
            session_ttl=3600,
            csrf_token_ttl=3600,
            session_idle_timeout=180,
        )
        auth.db_save_session(
            1,
            "token",
            "127.0.0.1",
            "test-agent",
            auth_scope="internal_test_token",
            allowed_features=["feature_chat_enabled"],
        )

        with app.test_request_context("/", headers={"User-Agent": "test-agent", "Cookie": "session_token=token"}):
            assert auth.db_get_user_from_token("token") == "alice"
            user = auth.get_current_user_ctx()

        assert user["username"] == "alice"
        assert user["auth_scope"] == "internal_test_token"
        assert user["allowed_features"] == ["feature_chat_enabled"]
    finally:
        auth._STATE.clear()
        auth._STATE.update(original_state)


def test_session_ip_mismatch_is_logged_but_soft_binding_keeps_session(tmp_path, monkeypatch):
    db_path = tmp_path / "binding.db"
    _seed_db(db_path)
    original_state = dict(auth._STATE)
    events = []

    try:
        auth.configure_auth_service(
            get_db=_get_db_factory(str(db_path)),
            get_user_by_username=lambda username: None,
            fernet=None,
            get_client_ip=lambda: "203.0.113.7",
            session_ttl=3600,
            csrf_token_ttl=3600,
            session_idle_timeout=180,
        )
        monkeypatch.setattr(auth, "record_security_event", lambda event_type, ip, **kwargs: events.append((event_type, ip, kwargs)))
        auth.db_save_session(1, "token", "127.0.0.1", "test-agent")
        app = Flask(__name__)

        with app.test_request_context("/", headers={"User-Agent": "test-agent"}):
            assert auth.db_get_user_from_token("token") == "alice"

        assert any(event_type == "session_ip_mismatch" and ip == "203.0.113.7" for event_type, ip, _ in events)

        conn = sqlite3.connect(db_path)
        row = conn.execute("SELECT is_revoked FROM sessions WHERE id=1").fetchone()
        conn.close()
        assert row[0] == 0
    finally:
        auth._STATE.clear()
        auth._STATE.update(original_state)


def test_session_strict_ip_binding_revokes_mismatched_session(tmp_path, monkeypatch):
    db_path = tmp_path / "binding.db"
    _seed_db(db_path)
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE system_settings (key TEXT PRIMARY KEY, value TEXT)")
    conn.execute("INSERT INTO system_settings (key, value) VALUES ('session_strict_ip_binding', 'true')")
    conn.commit()
    conn.close()
    original_state = dict(auth._STATE)
    events = []

    try:
        auth.configure_auth_service(
            get_db=_get_db_factory(str(db_path)),
            get_user_by_username=lambda username: None,
            fernet=None,
            get_client_ip=lambda: "203.0.113.7",
            session_ttl=3600,
            csrf_token_ttl=3600,
            session_idle_timeout=180,
        )
        monkeypatch.setattr(auth, "record_security_event", lambda event_type, ip, **kwargs: events.append((event_type, ip, kwargs)))
        auth.db_save_session(1, "token", "127.0.0.1", "test-agent")
        app = Flask(__name__)

        with app.test_request_context("/", headers={"User-Agent": "test-agent"}):
            assert auth.db_get_user_from_token("token") is None

        assert any(event_type == "session_ip_mismatch" for event_type, _, _ in events)
        assert any(event_type == "session_revoked" for event_type, _, _ in events)

        conn = sqlite3.connect(db_path)
        row = conn.execute("SELECT is_revoked, revoked_at FROM sessions WHERE id=1").fetchone()
        conn.close()
        assert row[0] == 1
        assert row[1]
    finally:
        auth._STATE.clear()
        auth._STATE.update(original_state)
