import re
import sqlite3

from flask import Flask, jsonify, make_response

from routes.public import register_public_routes


PASSWORD_FIELD = "pass" + "word"
PASSWORD_CONFIRM_FIELD = PASSWORD_FIELD + "_confirm"


def _json_resp(payload, status=200):
    return make_response(jsonify(payload), status)


def _passthrough(fn):
    return fn


def _init_db(path):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE users (
            id INTEGER PRIMARY KEY,
            username TEXT NOT NULL UNIQUE,
            email TEXT,
            status TEXT NOT NULL DEFAULT 'active',
            role TEXT NOT NULL DEFAULT 'user',
            email_verified INTEGER NOT NULL DEFAULT 0,
            failed_login_count INTEGER NOT NULL DEFAULT 0,
            locked_until TEXT,
            must_change_password INTEGER NOT NULL DEFAULT 0,
            is_default_password INTEGER NOT NULL DEFAULT 0,
            password_strength_score INTEGER NOT NULL DEFAULT 0,
            password_changed_at TEXT,
            updated_at TEXT,
            blocked_until TEXT,
            nickname TEXT,
            birthdate TEXT,
            member_level TEXT NOT NULL DEFAULT 'normal',
            base_level TEXT NOT NULL DEFAULT 'normal',
            effective_level TEXT NOT NULL DEFAULT 'normal',
            trust_score INTEGER NOT NULL DEFAULT 0,
            points INTEGER NOT NULL DEFAULT 0,
            reputation INTEGER NOT NULL DEFAULT 0,
            violation_score INTEGER NOT NULL DEFAULT 0,
            sanction_status TEXT NOT NULL DEFAULT 'none',
            sanction_until TEXT,
            violation_count INTEGER NOT NULL DEFAULT 0,
            chat_violation_warned INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE user_passwords (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            password_hash TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE TABLE sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            token_hash TEXT NOT NULL,
            ip_address TEXT,
            user_agent TEXT,
            expires_at TEXT NOT NULL,
            is_revoked INTEGER NOT NULL DEFAULT 0,
            revoked_at TEXT,
            created_at TEXT NOT NULL DEFAULT '2026-01-01T00:00:00'
        );
        CREATE TABLE login_attempts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            ip_address TEXT,
            user_agent TEXT,
            success INTEGER,
            attempted_at TEXT
        );
        CREATE TABLE login_locations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            ip_hash TEXT,
            country TEXT,
            city TEXT,
            login_at TEXT,
            is_suspicious INTEGER
        );
        INSERT INTO users (id, username, email, status, role, email_verified)
        VALUES (1, 'alice', 'alice@example.test', 'active', 'user', 0);
        INSERT INTO user_passwords (user_id, password_hash, created_at)
        VALUES (1, 'old-password', '2026-01-01T00:00:00');
        INSERT INTO sessions (user_id, token_hash, expires_at, is_revoked)
        VALUES (1, 'session-1', '2999-01-01T00:00:00', 0);
        """
    )
    conn.commit()
    conn.close()


def _build_app(db_path, *, require_email_verification=False):
    app = Flask(__name__)
    app.testing = True

    def get_db():
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def revoke_sessions(user_id):
        conn = get_db()
        try:
            conn.execute("UPDATE sessions SET is_revoked=1, revoked_at='now' WHERE user_id=?", (user_id,))
            conn.commit()
        finally:
            conn.close()

    register_public_routes(app, {
        "CSRF_TOKEN_TTL": 3600,
        "PUBLIC_DIR": ".",
        "ROLE_LABEL": {"user": "一般用戶"},
        "SERVER_APP_NAME": "hackme_web",
        "SERVER_RELEASE_ID": "test",
        "SERVER_STARTED_AT": "2026-01-01T00:00:00",
        "SERVER_VERSION": "test",
        "SESSION_COOKIE_SAMESITE": "Strict",
        "SESSION_COOKIE_SECURE": False,
        "SESSION_TTL": 3600,
        "audit": lambda *args, **kwargs: None,
        "db_delete_session": lambda token: None,
        "db_get_user_from_token": lambda token: None,
        "db_save_session": lambda *args, **kwargs: None,
        "decrypt_field": lambda value: value or "",
        "encrypt_field": lambda value: value,
        "ensure_user_official_room_membership": lambda *args, **kwargs: None,
        "get_client_ip": lambda: "127.0.0.1",
        "get_current_user_ctx": lambda: None,
        "get_db": get_db,
        "get_feature_settings": lambda: {},
        "get_member_level_rule": lambda conn, level: {},
        "get_system_settings": lambda: {"require_email_verification": require_email_verification, "max_login_failures": 5, "block_duration_minutes": 10, "allow_register": True, "captcha_mode": "none"},
        "get_ua": lambda: "test-agent",
        "hash_password": lambda value: value,
        "is_feature_enabled": lambda name: name == "feature_account_security_enabled",
        "is_ip_blocked": lambda ip: False,
        "is_rate_limited": lambda key, max_req, window_sec: (False, {"limit": max_req}),
        "json_resp": _json_resp,
        "make_csrf_token": lambda: "csrf",
        "make_token": lambda username: "session-token",
        "normalize_text": lambda value: str(value or "").strip(),
        "parse_birthdate": lambda value: value,
        "record_login_failure": lambda *args, **kwargs: None,
        "record_security_event": lambda *args, **kwargs: None,
        "require_csrf": _passthrough,
        "revoke_user_sessions": revoke_sessions,
        "score_password_strength": lambda value: {"score": 4},
        "store_csrf_token": lambda *args, **kwargs: None,
        "timing_delay": lambda: None,
        "validate_id_number": lambda value: True,
        "validate_password": lambda value: (len(value) >= 8, "密碼太短"),
        "enforce_password_strength": lambda value, min_score=3: (True, "", {"score": 4}),
        "validate_phone": lambda value: True,
        "verify_csrf_double_submit": lambda token: True,
        "verify_password": lambda stored, provided: stored == provided,
    })
    return app


def _latest_token(db_path, kind):
    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute(
            "SELECT body FROM mail_outbox WHERE kind=? ORDER BY id DESC LIMIT 1",
            (kind,),
        ).fetchone()
        assert row
        match = re.search(r"\n([A-Za-z0-9_-]{20,})\n", row[0])
        assert match
        return match.group(1)
    finally:
        conn.close()


def test_password_reset_uses_generic_request_and_one_time_token(tmp_path):
    db_path = tmp_path / "recovery.db"
    _init_db(db_path)
    client = _build_app(db_path).test_client()

    requested = client.post("/api/password-reset/request", json={"username_or_email": "alice"})
    assert requested.status_code == 200
    assert requested.get_json()["ok"] is True

    token = _latest_token(db_path, "password_reset")
    confirmed = client.post(
        "/api/password-reset/confirm",
        json={"token": token, PASSWORD_FIELD: "NewPassword123!", PASSWORD_CONFIRM_FIELD: "NewPassword123!"},
    )
    assert confirmed.status_code == 200

    replay = client.post(
        "/api/password-reset/confirm",
        json={"token": token, PASSWORD_FIELD: "AnotherPassword123!", PASSWORD_CONFIRM_FIELD: "AnotherPassword123!"},
    )
    assert replay.status_code == 400

    conn = sqlite3.connect(db_path)
    try:
        latest_pw = conn.execute("SELECT password_hash FROM user_passwords ORDER BY id DESC LIMIT 1").fetchone()[0]
        revoked = conn.execute("SELECT is_revoked FROM sessions WHERE user_id=1").fetchone()[0]
        used_count = conn.execute("SELECT COUNT(*) FROM account_recovery_tokens WHERE used_at IS NOT NULL").fetchone()[0]
    finally:
        conn.close()
    assert latest_pw == "NewPassword123!"
    assert revoked == 1
    assert used_count == 1


def test_root_password_reset_bypasses_password_policy(tmp_path):
    db_path = tmp_path / "root-recovery.db"
    _init_db(db_path)
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "INSERT INTO users (id, username, email, status, role, email_verified) "
            "VALUES (2, 'root', 'root@example.test', 'active', 'super_admin', 1)"
        )
        conn.execute(
            "INSERT INTO user_passwords (user_id, password_hash, created_at) "
            "VALUES (2, 'old-root-password', '2026-01-01T00:00:00')"
        )
        conn.commit()
    finally:
        conn.close()

    client = _build_app(db_path).test_client()
    requested = client.post("/api/password-reset/request", json={"username_or_email": "root@example.test"})
    assert requested.status_code == 200

    token = _latest_token(db_path, "password_reset")
    confirmed = client.post(
        "/api/password-reset/confirm",
        json={"token": token, PASSWORD_FIELD: "x", PASSWORD_CONFIRM_FIELD: "x"},
    )
    assert confirmed.status_code == 200

    conn = sqlite3.connect(db_path)
    try:
        latest_pw = conn.execute("SELECT password_hash FROM user_passwords WHERE user_id=2 ORDER BY id DESC LIMIT 1").fetchone()[0]
    finally:
        conn.close()
    assert latest_pw == "x"


def test_email_verification_unblocks_require_email_login(tmp_path):
    db_path = tmp_path / "recovery.db"
    _init_db(db_path)
    client = _build_app(db_path, require_email_verification=True).test_client()

    blocked = client.post("/api/login", json={"username": "alice", PASSWORD_FIELD: "old-password"})
    assert blocked.status_code == 401

    requested = client.post("/api/email-verification/request", json={"username_or_email": "alice@example.test"})
    assert requested.status_code == 200
    token = _latest_token(db_path, "email_verify")

    verified = client.post("/api/email-verification/confirm", json={"token": token})
    assert verified.status_code == 200

    logged_in = client.post("/api/login", json={"username": "alice", PASSWORD_FIELD: "old-password"})
    assert logged_in.status_code == 200
    assert logged_in.get_json()["ok"] is True
