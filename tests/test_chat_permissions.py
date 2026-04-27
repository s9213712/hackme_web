import sqlite3

from flask import Flask, jsonify

from routes.chat import register_chat_routes


def _role_rank(role):
    return {"user": 1, "manager": 2, "super_admin": 3}.get(role or "user", 1)


def _parse_positive_int(value, default=None, min_value=None, max_value=None):
    try:
        parsed = int(value)
    except Exception:
        return default
    if min_value is not None and parsed < min_value:
        return default
    if max_value is not None and parsed > max_value:
        return default
    return parsed


def _build_app(db_path, actor_box):
    app = Flask(__name__)
    app.testing = True

    def get_db():
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def json_resp(payload):
        return jsonify(payload)

    def passthrough(fn):
        return fn

    register_chat_routes(app, {
        "CHAT_MESSAGE_MAX_LEN": 500,
        "OFFICIAL_CHAT_ROOM_NAME": "大廳",
        "add_violation": lambda *args, **kwargs: ("warn", "noop", 0),
        "append_chat_record": lambda *args, **kwargs: True,
        "audit": lambda *args, **kwargs: None,
        "check_user_rate_limit": lambda *args, **kwargs: (False, {"limit": 20}),
        "db_get_user_from_token": lambda *args, **kwargs: None,
        "db_get_user_role": lambda *args, **kwargs: "user",
        "delete_csrf_token": lambda *args, **kwargs: None,
        "detect_chat_violation": lambda *args, **kwargs: (False, ""),
        "ensure_user_official_room_membership": lambda *args, **kwargs: None,
        "get_client_ip": lambda: "127.0.0.1",
        "get_current_user_ctx": lambda: actor_box["actor"],
        "get_db": get_db,
        "get_request_csrf_token": lambda: "csrf",
        "json_resp": json_resp,
        "normalize_text": lambda value: value.strip() if isinstance(value, str) else "",
        "parse_positive_int": _parse_positive_int,
        "require_csrf": passthrough,
        "require_csrf_safe": passthrough,
        "role_rank": _role_rank,
        "verify_csrf_token": lambda *args, **kwargs: True,
    })
    return app


def _seed_chat_db(db_path):
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        CREATE TABLE users (
            id INTEGER PRIMARY KEY,
            username TEXT NOT NULL UNIQUE,
            role TEXT NOT NULL
        );
        CREATE TABLE chat_rooms (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            owner_user_id INTEGER NOT NULL,
            is_private INTEGER NOT NULL DEFAULT 0,
            is_active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL
        );
        CREATE TABLE chat_room_members (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            room_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            joined_at TEXT NOT NULL,
            UNIQUE(room_id, user_id)
        );
        CREATE TABLE chat_messages (
            id INTEGER PRIMARY KEY,
            room_id INTEGER NOT NULL,
            sender_id INTEGER,
            content TEXT NOT NULL,
            is_blocked INTEGER NOT NULL DEFAULT 0,
            blocked_reason TEXT,
            created_at TEXT NOT NULL
        );
        CREATE TABLE chat_message_reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            message_id INTEGER NOT NULL,
            room_id INTEGER NOT NULL,
            reporter_user_id INTEGER NOT NULL,
            reported_user_id INTEGER NOT NULL,
            reason TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            reviewed_by TEXT,
            reviewed_at TEXT,
            review_note TEXT,
            created_at TEXT NOT NULL
        );
        """
    )
    conn.executemany(
        "INSERT INTO users (id, username, role) VALUES (?, ?, ?)",
        [
            (1, "root", "super_admin"),
            (2, "admin", "manager"),
            (3, "alice", "user"),
            (4, "bob", "user"),
        ],
    )
    conn.execute(
        "INSERT INTO chat_rooms (id, name, owner_user_id, is_private, is_active, created_at) VALUES (1, '大廳', 1, 0, 1, '2026-01-01T00:00:00')"
    )
    conn.executemany(
        "INSERT INTO chat_room_members (room_id, user_id, joined_at) VALUES (1, ?, '2026-01-01T00:00:00')",
        [(1,), (2,), (3,), (4,)],
    )
    conn.executemany(
        "INSERT INTO chat_messages (id, room_id, sender_id, content, is_blocked, blocked_reason, created_at) VALUES (?, 1, ?, ?, 0, NULL, '2026-01-01T00:00:00')",
        [
            (1, 3, "alice message"),
            (2, 1, "root message"),
            (3, 2, "admin message"),
        ],
    )
    conn.commit()
    conn.close()


def _message_block_state(db_path, message_id):
    conn = sqlite3.connect(db_path)
    row = conn.execute("SELECT is_blocked FROM chat_messages WHERE id=?", (message_id,)).fetchone()
    conn.close()
    return row[0]


def test_manager_can_delete_user_message(tmp_path):
    db_path = tmp_path / "chat.db"
    _seed_chat_db(db_path)
    actor_box = {"actor": {"id": 2, "username": "admin", "role": "manager"}}
    client = _build_app(str(db_path), actor_box).test_client()

    res = client.delete("/api/chat/messages/1")

    assert res.status_code == 200
    assert res.get_json()["ok"] is True
    assert _message_block_state(db_path, 1) == 1


def test_manager_cannot_delete_root_message(tmp_path):
    db_path = tmp_path / "chat.db"
    _seed_chat_db(db_path)
    actor_box = {"actor": {"id": 2, "username": "admin", "role": "manager"}}
    client = _build_app(str(db_path), actor_box).test_client()

    res = client.delete("/api/chat/messages/2")

    assert res.status_code == 403
    assert res.get_json()["ok"] is False
    assert _message_block_state(db_path, 2) == 0


def test_root_can_delete_manager_message(tmp_path):
    db_path = tmp_path / "chat.db"
    _seed_chat_db(db_path)
    actor_box = {"actor": {"id": 1, "username": "root", "role": "super_admin"}}
    client = _build_app(str(db_path), actor_box).test_client()

    res = client.delete("/api/chat/messages/3")

    assert res.status_code == 200
    assert res.get_json()["ok"] is True
    assert _message_block_state(db_path, 3) == 1
