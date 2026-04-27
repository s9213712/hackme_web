import sqlite3

from flask import Flask, jsonify, make_response

from routes.public import register_public_routes


def _build_app(db_path, settings):
    app = Flask(__name__)
    app.testing = True

    def get_db():
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def json_resp(payload, status=200):
        return make_response(jsonify(payload), status)

    register_public_routes(app, {
        "CSRF_TOKEN_TTL": 3600,
        "PUBLIC_DIR": ".",
        "ROLE_LABEL": {},
        "SERVER_STARTED_AT": "2026-01-01T00:00:00",
        "SERVER_VERSION": "test",
        "SESSION_COOKIE_SAMESITE": "Lax",
        "SESSION_COOKIE_SECURE": False,
        "SESSION_TTL": 3600,
        "audit": lambda *args, **kwargs: None,
        "db_delete_session": lambda *args, **kwargs: None,
        "db_get_user_from_token": lambda *args, **kwargs: None,
        "db_save_session": lambda *args, **kwargs: None,
        "decrypt_field": lambda value: value,
        "encrypt_field": lambda value: value,
        "ensure_user_official_room_membership": lambda *args, **kwargs: None,
        "get_client_ip": lambda: "127.0.0.1",
        "get_current_user_ctx": lambda: None,
        "get_db": get_db,
        "get_feature_settings": lambda: {},
        "get_system_settings": lambda: settings,
        "get_ua": lambda: "test-agent",
        "hash_password": lambda value: value,
        "is_feature_enabled": lambda key: key == "feature_account_security_enabled",
        "is_ip_blocked": lambda ip: False,
        "is_rate_limited": lambda *args, **kwargs: (False, {"limit": 30}),
        "json_resp": json_resp,
        "make_csrf_token": lambda: "csrf",
        "make_token": lambda username: f"token-{username}",
        "normalize_text": lambda value: value.strip() if isinstance(value, str) else "",
        "parse_birthdate": lambda value: value,
        "record_login_failure": lambda *args, **kwargs: None,
        "require_csrf": lambda fn: fn,
        "score_password_strength": lambda value: {"score": 4, "missing": []},
        "role_rank": lambda role: 0,
        "store_csrf_token": lambda *args, **kwargs: None,
        "timing_delay": lambda: None,
        "validate_id_number": lambda value: True,
        "validate_password": lambda value: (True, "OK"),
        "enforce_password_strength": lambda value, min_score=3: (True, "OK", {"score": 4}),
        "validate_phone": lambda value: True,
        "verify_csrf_double_submit": lambda value: True,
        "verify_password": lambda stored, provided: stored == provided,
    })
    return app


def _seed_db(db_path):
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        CREATE TABLE users (
            id INTEGER PRIMARY KEY,
            username TEXT NOT NULL UNIQUE,
            status TEXT NOT NULL,
            role TEXT NOT NULL,
            blocked_until TEXT,
            locked_until TEXT,
            failed_login_count INTEGER NOT NULL DEFAULT 0,
            last_login_at TEXT,
            updated_at TEXT
        );
        CREATE TABLE user_passwords (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            password_hash TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE TABLE login_attempts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            ip_address TEXT,
            user_agent TEXT,
            success INTEGER NOT NULL,
            attempted_at TEXT NOT NULL
        );
        """
    )
    conn.execute(
        "INSERT INTO users (id, username, status, role) VALUES (1, 'alice', 'active', 'user')"
    )
    conn.execute(
        "INSERT INTO user_passwords (user_id, password_hash, created_at) VALUES (1, 'correct', '2026-01-01T00:00:00')"
    )
    conn.commit()
    conn.close()


def test_account_security_locks_user_after_repeated_bad_passwords(tmp_path):
    db_path = tmp_path / "lockout.db"
    _seed_db(db_path)
    client = _build_app(
        str(db_path),
        {"max_login_failures": 2, "block_duration_minutes": 10},
    ).test_client()

    first = client.post("/api/login", json={"username": "alice", "password": "bad"})
    second = client.post("/api/login", json={"username": "alice", "password": "bad"})
    locked = client.post("/api/login", json={"username": "alice", "password": "correct"})

    assert first.status_code == 401
    assert second.status_code == 401
    assert locked.status_code == 401

    conn = sqlite3.connect(db_path)
    row = conn.execute(
        "SELECT failed_login_count, locked_until FROM users WHERE username='alice'"
    ).fetchone()
    conn.close()

    assert row[0] == 2
    assert row[1]
