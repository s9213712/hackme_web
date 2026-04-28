import sqlite3

from flask import Flask, jsonify

from routes.dm import register_dm_routes
from services.member_levels import ensure_member_level_rules_schema


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

    def passthrough(fn):
        return fn

    register_dm_routes(app, {
        "audit": lambda *args, **kwargs: None,
        "get_client_ip": lambda: "127.0.0.1",
        "get_current_user_ctx": lambda: actor_box["actor"],
        "get_db": get_db,
        "get_ua": lambda: "test-agent",
        "json_resp": lambda payload: jsonify(payload),
        "normalize_text": lambda value: value.strip() if isinstance(value, str) else "",
        "parse_positive_int": _parse_positive_int,
        "require_csrf": passthrough,
        "require_csrf_safe": passthrough,
    })
    return app


def _seed_db(db_path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE users (
            id INTEGER PRIMARY KEY,
            username TEXT NOT NULL UNIQUE,
            role TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'active',
            member_level TEXT NOT NULL DEFAULT 'normal',
            base_level TEXT NOT NULL DEFAULT 'normal',
            effective_level TEXT NOT NULL DEFAULT 'normal'
        );
        """
    )
    conn.executemany(
        "INSERT INTO users (id, username, role, member_level, base_level, effective_level) VALUES (?, ?, ?, ?, ?, ?)",
        [
            (1, "root", "super_admin", "normal", "normal", "normal"),
            (2, "alice", "user", "normal", "normal", "normal"),
            (3, "bob", "user", "normal", "normal", "normal"),
            (4, "restricted", "user", "restricted", "restricted", "restricted"),
        ],
    )
    ensure_member_level_rules_schema(conn)
    conn.commit()
    conn.close()


def test_dm_thread_send_read_delete_and_notification(tmp_path):
    db_path = tmp_path / "dm.db"
    _seed_db(db_path)
    actor_box = {"actor": {"id": 2, "username": "alice", "role": "user", "member_level": "normal"}}
    client = _build_app(db_path, actor_box).test_client()

    created = client.post("/api/dm/threads", json={"target_username": "bob"})
    assert created.status_code == 200
    thread_id = created.get_json()["thread"]["id"]

    sent = client.post(f"/api/dm/threads/{thread_id}/messages", json={"body": "hello bob"})
    assert sent.status_code == 200
    message_id = sent.get_json()["message"]["id"]

    actor_box["actor"] = {"id": 3, "username": "bob", "role": "user", "member_level": "normal"}
    inbox = client.get("/api/dm/threads")
    assert inbox.status_code == 200
    assert inbox.get_json()["threads"][0]["unread_count"] == 1

    messages = client.get(f"/api/dm/threads/{thread_id}/messages")
    assert messages.status_code == 200
    assert messages.get_json()["messages"][0]["body"] == "hello bob"

    read = client.post(f"/api/dm/threads/{thread_id}/read")
    assert read.status_code == 200
    assert client.get("/api/dm/threads").get_json()["threads"][0]["unread_count"] == 0

    deleted = client.delete(f"/api/dm/messages/{message_id}")
    assert deleted.status_code == 200
    assert client.get(f"/api/dm/threads/{thread_id}/messages").get_json()["messages"] == []

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    notification = conn.execute("SELECT type, user_id FROM notifications WHERE user_id=3").fetchone()
    conn.close()
    assert dict(notification) == {"type": "dm_message", "user_id": 3}


def test_dm_block_prevents_new_messages(tmp_path):
    db_path = tmp_path / "dm.db"
    _seed_db(db_path)
    actor_box = {"actor": {"id": 3, "username": "bob", "role": "user", "member_level": "normal"}}
    client = _build_app(db_path, actor_box).test_client()

    blocked = client.post("/api/dm/blocks", json={"target_username": "alice", "reason": "spam"})
    assert blocked.status_code == 200

    actor_box["actor"] = {"id": 2, "username": "alice", "role": "user", "member_level": "normal"}
    denied = client.post("/api/dm/threads", json={"target_username": "bob"})
    assert denied.status_code == 403
    assert "對方" in denied.get_json()["msg"]


def test_restricted_user_cannot_create_dm_thread(tmp_path):
    db_path = tmp_path / "dm.db"
    _seed_db(db_path)
    actor_box = {"actor": {"id": 4, "username": "restricted", "role": "user", "member_level": "restricted"}}
    client = _build_app(db_path, actor_box).test_client()

    denied = client.post("/api/dm/threads", json={"target_username": "bob"})
    assert denied.status_code == 403
