import hashlib
import sqlite3

from flask import Flask, jsonify, make_response

from routes.users import register_user_routes


def _hash_token(token):
    return hashlib.sha256(token.encode()).hexdigest()


def _build_app(db_path, actor_box, revoke_user_sessions=None):
    app = Flask(__name__)
    app.testing = True

    def get_db():
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def json_resp(payload, status=200):
        return make_response(jsonify(payload), status)

    register_user_routes(app, {
        "ACCOUNT_STATUSES": {"active", "inactive", "pending", "rejected"},
        "MAX_MANAGERS": 5,
        "MAX_EXTRA_SUPER_ADMINS": 2,
        "MEMBER_LEVELS": {"newbie", "normal", "trusted", "vip", "restricted", "suspended"},
        "PASSWORD_HISTORY_LIMIT": 5,
        "ROLE_LABEL": {"user": "一般用戶", "manager": "管理者", "super_admin": "最高管理者"},
        "ROLE_RANK": {"user": 0, "manager": 1, "super_admin": 2},
        "add_violation": lambda *args, **kwargs: ("none", "ok", 0),
        "audit": lambda *args, **kwargs: None,
        "check_user_rate_limit": lambda *args, **kwargs: (False, {"limit": 10}),
        "count_role": lambda role: 0,
        "db_get_user_from_token": lambda *args, **kwargs: None,
        "db_get_user_role": lambda *args, **kwargs: "user",
        "decrypt_field": lambda value: value or "",
        "encrypt_field": lambda value: value,
        "ensure_user_official_room_membership": lambda *args, **kwargs: None,
        "get_client_ip": lambda: "127.0.0.1",
        "get_current_user_ctx": lambda: actor_box["actor"],
        "get_db": get_db,
        "get_ua": lambda: "test-agent",
        "hash_password": lambda value: value,
        "hash_token": _hash_token,
        "is_feature_enabled": lambda key: key == "feature_account_security_enabled",
        "json_resp": json_resp,
        "normalize_text": lambda value: value.strip() if isinstance(value, str) else "",
        "parse_birthdate": lambda value: value,
        "parse_positive_int": lambda value, default=None, **kwargs: int(value) if value is not None else default,
        "revoke_user_sessions": revoke_user_sessions or (lambda *args, **kwargs: None),
        "require_csrf": lambda fn: fn,
        "require_csrf_safe": lambda fn: fn,
        "SESSION_COOKIE_SAMESITE": "Lax",
        "SESSION_COOKIE_SECURE": False,
        "enforce_password_strength": lambda value, min_score=3: (True, "OK", {"score": 4}),
        "score_password_strength": lambda value: {"score": 4},
        "role_rank": lambda role: {"user": 0, "manager": 1, "super_admin": 2}.get(role or "user", 0),
        "user_public_payload": lambda row, include_sensitive=False: dict(row),
        "validate_id_number": lambda value: True,
        "validate_password": lambda value: (True, "OK"),
        "validate_phone": lambda value: True,
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
            role TEXT NOT NULL
        );
        CREATE TABLE sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            token_hash TEXT NOT NULL UNIQUE,
            ip_address TEXT,
            user_agent TEXT,
            device_info TEXT,
            ip_country TEXT,
            expires_at TEXT NOT NULL,
            is_revoked INTEGER NOT NULL DEFAULT 0,
            revoked_at TEXT,
            last_seen TEXT,
            created_at TEXT NOT NULL
        );
        """
    )
    conn.execute("INSERT INTO users (id, username, status, role) VALUES (1, 'alice', 'active', 'user')")
    conn.executemany(
        "INSERT INTO sessions (user_id, token_hash, ip_address, user_agent, device_info, ip_country, expires_at, is_revoked, last_seen, created_at) "
        "VALUES (1, ?, ?, ?, ?, ?, ?, 0, ?, ?)",
        [
            (_hash_token("current"), "127.0.0.1", "Chrome", '{"browser":"Chrome","os":"Linux","device":"Desktop"}', None, "2999-01-01T00:00:00", "2026-01-01T00:00:00", "2026-01-01T00:00:00"),
            (_hash_token("remote"), "10.0.0.2", "Firefox", '{"browser":"Firefox","os":"Windows","device":"Desktop"}', "TW", "2999-01-01T00:00:00", "2026-01-01T00:00:00", "2026-01-01T00:00:00"),
        ],
    )
    conn.commit()
    conn.close()


def test_account_sessions_list_marks_current_and_revokes_remote(tmp_path):
    db_path = tmp_path / "sessions.db"
    _seed_db(db_path)
    actor_box = {"actor": {"id": 1, "username": "alice", "role": "user", "status": "active"}}
    client = _build_app(str(db_path), actor_box).test_client()
    client.set_cookie("session_token", "current")

    listed = client.get("/api/account/sessions")
    assert listed.status_code == 200
    sessions = listed.get_json()["sessions"]
    assert len(sessions) == 2
    assert [item for item in sessions if item["is_current"]][0]["device_info"]["browser"] == "Chrome"

    deleted = client.delete("/api/account/sessions/2")
    assert deleted.status_code == 200
    assert deleted.get_json()["current_revoked"] is False

    conn = sqlite3.connect(db_path)
    revoked = conn.execute("SELECT is_revoked FROM sessions WHERE id=2").fetchone()[0]
    current = conn.execute("SELECT is_revoked FROM sessions WHERE id=1").fetchone()[0]
    conn.close()
    assert revoked == 1
    assert current == 0


def test_account_sessions_logout_all_can_keep_current(tmp_path):
    db_path = tmp_path / "sessions.db"
    _seed_db(db_path)
    actor_box = {"actor": {"id": 1, "username": "alice", "role": "user", "status": "active"}}
    client = _build_app(str(db_path), actor_box).test_client()
    client.set_cookie("session_token", "current")

    res = client.post("/api/account/sessions/logout-all", json={"keep_current": True})
    assert res.status_code == 200
    assert res.get_json()["current_revoked"] is False

    conn = sqlite3.connect(db_path)
    rows = conn.execute("SELECT id, is_revoked FROM sessions ORDER BY id").fetchall()
    conn.close()
    assert rows == [(1, 0), (2, 1)]


def test_password_change_revokes_existing_sessions(tmp_path):
    db_path = tmp_path / "password-change.db"
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        CREATE TABLE users (
            id INTEGER PRIMARY KEY,
            username TEXT NOT NULL UNIQUE,
            nickname TEXT,
            real_name TEXT,
            birthdate TEXT,
            id_number TEXT,
            phone TEXT,
            role TEXT NOT NULL,
            status TEXT NOT NULL,
            member_level TEXT NOT NULL DEFAULT 'normal',
            trust_score INTEGER NOT NULL DEFAULT 0,
            points INTEGER NOT NULL DEFAULT 0,
            reputation INTEGER NOT NULL DEFAULT 0,
            password_strength_score INTEGER NOT NULL DEFAULT 0,
            blocked_until TEXT,
            violation_count INTEGER NOT NULL DEFAULT 0,
            password_changed_at TEXT,
            must_change_password INTEGER NOT NULL DEFAULT 1,
            is_default_password INTEGER NOT NULL DEFAULT 1,
            updated_at TEXT
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
            token_hash TEXT NOT NULL UNIQUE,
            ip_address TEXT,
            user_agent TEXT,
            device_info TEXT,
            ip_country TEXT,
            expires_at TEXT NOT NULL,
            is_revoked INTEGER NOT NULL DEFAULT 0,
            revoked_at TEXT,
            last_seen TEXT,
            created_at TEXT NOT NULL
        );
        """
    )
    conn.execute(
        "INSERT INTO users (id, username, role, status, must_change_password, is_default_password, updated_at) "
        "VALUES (1, 'alice', 'user', 'active', 1, 1, '2026-01-01T00:00:00')"
    )
    conn.execute(
        "INSERT INTO user_passwords (user_id, password_hash, created_at) VALUES (1, 'oldpass', '2026-01-01T00:00:00')"
    )
    conn.executemany(
        "INSERT INTO sessions (user_id, token_hash, expires_at, is_revoked, created_at) VALUES (1, ?, '2999-01-01T00:00:00', 0, '2026-01-01T00:00:00')",
        [(_hash_token("current"),), (_hash_token("remote"),)],
    )
    conn.commit()
    conn.close()

    def revoke_sessions(user_id):
        conn = sqlite3.connect(db_path)
        conn.execute("UPDATE sessions SET is_revoked=1, revoked_at='now' WHERE user_id=?", (user_id,))
        conn.commit()
        conn.close()

    actor_box = {"actor": {"id": 1, "username": "alice", "role": "user", "status": "active"}}
    client = _build_app(str(db_path), actor_box, revoke_user_sessions=revoke_sessions).test_client()
    res = client.put(
        "/api/admin/users/1",
        json={"current_password": "oldpass", "password": "Newpass@123", "password_confirm": "Newpass@123"},
    )

    assert res.status_code == 200

    conn = sqlite3.connect(db_path)
    user_flags = conn.execute("SELECT must_change_password, is_default_password FROM users WHERE id=1").fetchone()
    revoked = conn.execute("SELECT COUNT(*) FROM sessions WHERE is_revoked=1").fetchone()[0]
    passwords = conn.execute("SELECT COUNT(*) FROM user_passwords WHERE user_id=1").fetchone()[0]
    conn.close()
    assert revoked == 2
    assert passwords == 2
    assert user_flags == (0, 0)


def test_password_change_rejects_same_as_current_password(tmp_path):
    db_path = tmp_path / "app.db"
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        CREATE TABLE users (
            id INTEGER PRIMARY KEY,
            username TEXT NOT NULL UNIQUE,
            nickname TEXT,
            real_name TEXT,
            birthdate TEXT,
            id_number TEXT,
            phone TEXT,
            status TEXT NOT NULL,
            role TEXT NOT NULL,
            member_level TEXT NOT NULL DEFAULT 'normal',
            trust_score INTEGER NOT NULL DEFAULT 0,
            points INTEGER NOT NULL DEFAULT 0,
            reputation INTEGER NOT NULL DEFAULT 0,
            password_strength_score INTEGER NOT NULL DEFAULT 0,
            blocked_until TEXT,
            violation_count INTEGER NOT NULL DEFAULT 0,
            password_changed_at TEXT,
            must_change_password INTEGER NOT NULL DEFAULT 1,
            is_default_password INTEGER NOT NULL DEFAULT 1,
            updated_at TEXT
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
            token_hash TEXT NOT NULL UNIQUE,
            ip_address TEXT,
            user_agent TEXT,
            device_info TEXT,
            ip_country TEXT,
            expires_at TEXT NOT NULL,
            is_revoked INTEGER NOT NULL DEFAULT 0,
            revoked_at TEXT,
            last_seen TEXT,
            created_at TEXT NOT NULL
        );
        """
    )
    conn.execute(
        "INSERT INTO users (id, username, role, status, must_change_password, is_default_password, updated_at) "
        "VALUES (1, 'alice', 'user', 'active', 1, 1, '2026-01-01T00:00:00')"
    )
    conn.execute(
        "INSERT INTO user_passwords (user_id, password_hash, created_at) VALUES (1, 'oldpass', '2026-01-01T00:00:00')"
    )
    conn.commit()
    conn.close()

    actor_box = {"actor": {"id": 1, "username": "alice", "role": "user", "status": "active"}}
    client = _build_app(str(db_path), actor_box).test_client()
    res = client.put(
        "/api/admin/users/1",
        json={"current_password": "oldpass", "password": "oldpass", "password_confirm": "oldpass"},
    )

    assert res.status_code == 400
    assert res.get_json()["msg"] == "新密碼不可與目前密碼相同"

    conn = sqlite3.connect(db_path)
    passwords = conn.execute("SELECT COUNT(*) FROM user_passwords WHERE user_id=1").fetchone()[0]
    conn.close()
    assert passwords == 1
