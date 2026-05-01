import sqlite3
from datetime import datetime, timedelta

from flask import Flask, jsonify

from routes.chat import register_chat_routes
from services.cloud_drive import ensure_cloud_drive_attachment_schema


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


def _message_revoked_state(db_path, message_id):
    conn = sqlite3.connect(db_path)
    row = conn.execute("SELECT is_revoked, revoked_at FROM chat_messages WHERE id=?", (message_id,)).fetchone()
    conn.close()
    return row


def _message_row(db_path, message_id):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM chat_messages WHERE id=?", (message_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def _message_count(db_path):
    conn = sqlite3.connect(db_path)
    count = conn.execute("SELECT COUNT(*) FROM chat_messages").fetchone()[0]
    conn.close()
    return count


def _seed_uploaded_file(db_path, file_id="file-1", owner_user_id=3):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE uploaded_files (
            id TEXT PRIMARY KEY,
            owner_user_id INTEGER NOT NULL,
            storage_path TEXT NOT NULL,
            privacy_mode TEXT NOT NULL,
            risk_level TEXT NOT NULL,
            scan_status TEXT NOT NULL,
            size_bytes INTEGER NOT NULL,
            original_filename_plain_for_public TEXT,
            mime_type_plain_for_public TEXT,
            deleted_at TEXT,
            created_at TEXT NOT NULL
        )
        """
    )
    ensure_cloud_drive_attachment_schema(conn)
    conn.execute(
        """
        INSERT INTO uploaded_files (
            id, owner_user_id, storage_path, privacy_mode, risk_level, scan_status,
            size_bytes, original_filename_plain_for_public, mime_type_plain_for_public,
            deleted_at, created_at
        ) VALUES (?, ?, ?, 'private_scannable', 'low', 'clean', 12, 'chat-note.txt', 'text/plain', NULL, '2026-01-01T00:00:00')
        """,
        (file_id, owner_user_id, f"users/{owner_user_id}/{file_id}/chat-note.txt"),
    )
    conn.commit()
    conn.close()


def test_group_chat_create_invite_password_join_and_export(tmp_path):
    db_path = tmp_path / "chat.db"
    _seed_chat_db(db_path)
    actor_box = {"actor": {"id": 3, "username": "alice", "role": "user", "member_level": "normal"}}
    client = _build_app(db_path, actor_box).test_client()

    created = client.post(
        "/api/chat/rooms",
        json={"name": "group room", "invite_usernames": ["bob"], "join_password": "room-pass"},
    )
    assert created.status_code == 200
    room_id = created.get_json()["room"]["id"]

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        members = {
            row["user_id"]
            for row in conn.execute("SELECT user_id FROM chat_room_members WHERE room_id=?", (room_id,)).fetchall()
        }
        assert members == {3, 4}
        assert conn.execute("SELECT * FROM notifications WHERE user_id=4 AND type='chat_room_added'").fetchone() is not None
    finally:
        conn.close()

    actor_box["actor"] = {"id": 2, "username": "admin", "role": "manager", "member_level": "normal"}
    denied = client.post(f"/api/chat/rooms/{room_id}/join", json={"password": "wrong"})
    assert denied.status_code == 403
    joined = client.post(f"/api/chat/rooms/{room_id}/join", json={"password": "room-pass"})
    assert joined.status_code == 200

    sent = client.post(f"/api/chat/rooms/{room_id}/messages", json={"content": "hello group"})
    assert sent.status_code == 200
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        notes = conn.execute(
            "SELECT user_id, type, title FROM notifications WHERE type='chat_group_message' ORDER BY user_id"
        ).fetchall()
        assert [(row["user_id"], row["title"]) for row in notes] == [(3, "群聊有新訊息"), (4, "群聊有新訊息")]
    finally:
        conn.close()
    exported = client.get(f"/api/chat/rooms/{room_id}/export")
    assert exported.status_code == 200
    payload = exported.get_json()
    assert payload["room"]["name"] == "group room"
    assert payload["messages"][0]["content"] == "hello group"


def test_chat_room_invite_creates_notification(tmp_path):
    db_path = tmp_path / "chat.db"
    _seed_chat_db(db_path)
    actor_box = {"actor": {"id": 3, "username": "alice", "role": "user", "member_level": "normal"}}
    client = _build_app(db_path, actor_box).test_client()

    created = client.post("/api/chat/rooms", json={"name": "invite room"})
    assert created.status_code == 200
    room_id = created.get_json()["room"]["id"]
    invited = client.post(f"/api/chat/rooms/{room_id}/invites", json={"usernames": "bob"})
    assert invited.status_code == 200

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        invite = conn.execute("SELECT * FROM chat_room_invites WHERE room_id=? AND invitee_user_id=4", (room_id,)).fetchone()
        assert invite is not None
        note = conn.execute("SELECT * FROM notifications WHERE user_id=4 AND type='chat_room_invite'").fetchone()
        assert note is not None
    finally:
        conn.close()


def _room_active(db_path, room_id):
    conn = sqlite3.connect(db_path)
    row = conn.execute("SELECT is_active FROM chat_rooms WHERE id=?", (room_id,)).fetchone()
    conn.close()
    return row[0] if row else None


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


def test_root_can_delete_message_even_when_not_room_member(tmp_path):
    db_path = tmp_path / "chat.db"
    _seed_chat_db(db_path)
    conn = sqlite3.connect(db_path)
    conn.execute(
        "INSERT INTO chat_rooms (id, name, owner_user_id, is_private, is_active, created_at) VALUES (2, 'private', 3, 1, 1, '2026-01-01T00:00:00')"
    )
    conn.execute(
        "INSERT INTO chat_room_members (room_id, user_id, joined_at) VALUES (2, 3, '2026-01-01T00:00:00')"
    )
    conn.execute(
        "INSERT INTO chat_messages (id, room_id, sender_id, content, is_blocked, blocked_reason, created_at) VALUES (4, 2, 3, 'hidden', 0, NULL, '2026-01-01T00:00:00')"
    )
    conn.commit()
    conn.close()
    actor_box = {"actor": {"id": 1, "username": "root", "role": "super_admin"}}
    client = _build_app(str(db_path), actor_box).test_client()

    res = client.delete("/api/chat/messages/4")

    assert res.status_code == 200
    assert res.get_json()["ok"] is True
    assert _message_block_state(db_path, 4) == 1


def test_owner_can_delete_chat_room_and_it_disappears_from_rooms(tmp_path):
    db_path = tmp_path / "chat.db"
    _seed_chat_db(db_path)
    conn = sqlite3.connect(db_path)
    conn.execute(
        "INSERT INTO chat_rooms (id, name, owner_user_id, is_private, is_active, created_at) VALUES (2, 'alice-room', 3, 0, 1, '2026-01-01T00:00:00')"
    )
    conn.execute(
        "INSERT INTO chat_room_members (room_id, user_id, joined_at) VALUES (2, 3, '2026-01-01T00:00:00')"
    )
    conn.commit()
    conn.close()
    actor_box = {"actor": {"id": 3, "username": "alice", "role": "user"}}
    client = _build_app(str(db_path), actor_box).test_client()

    res = client.delete("/api/chat/rooms/2")
    rooms = client.get("/api/chat/rooms")
    messages = client.get("/api/chat/rooms/2/messages")

    assert res.status_code == 200
    assert res.get_json()["ok"] is True
    assert _room_active(db_path, 2) == 0
    assert all(room["id"] != 2 for room in rooms.get_json()["rooms"])
    assert messages.status_code == 404


def test_official_chat_room_cannot_be_deleted(tmp_path):
    db_path = tmp_path / "chat.db"
    _seed_chat_db(db_path)
    actor_box = {"actor": {"id": 1, "username": "root", "role": "super_admin"}}
    client = _build_app(str(db_path), actor_box).test_client()

    res = client.delete("/api/chat/rooms/1")

    assert res.status_code == 403
    assert res.get_json()["ok"] is False
    assert _room_active(db_path, 1) == 1


def test_chat_rooms_marks_official_room_for_frontend(tmp_path):
    db_path = tmp_path / "chat.db"
    _seed_chat_db(db_path)
    actor_box = {"actor": {"id": 1, "username": "root", "role": "super_admin"}}
    client = _build_app(str(db_path), actor_box).test_client()

    res = client.get("/api/chat/rooms")
    official = next(room for room in res.get_json()["rooms"] if room["id"] == 1)

    assert res.status_code == 200
    assert official["is_official"] is True


def test_member_cannot_delete_someone_else_chat_room(tmp_path):
    db_path = tmp_path / "chat.db"
    _seed_chat_db(db_path)
    conn = sqlite3.connect(db_path)
    conn.execute(
        "INSERT INTO chat_rooms (id, name, owner_user_id, is_private, is_active, created_at) VALUES (2, 'alice-room', 3, 0, 1, '2026-01-01T00:00:00')"
    )
    conn.execute(
        "INSERT INTO chat_room_members (room_id, user_id, joined_at) VALUES (2, 4, '2026-01-01T00:00:00')"
    )
    conn.commit()
    conn.close()
    actor_box = {"actor": {"id": 4, "username": "bob", "role": "user"}}
    client = _build_app(str(db_path), actor_box).test_client()

    res = client.delete("/api/chat/rooms/2")

    assert res.status_code == 403
    assert res.get_json()["ok"] is False
    assert _room_active(db_path, 2) == 1


def test_restricted_member_cannot_send_chat_message(tmp_path):
    db_path = tmp_path / "chat.db"
    _seed_chat_db(db_path)
    actor_box = {
        "actor": {
            "id": 3,
            "username": "alice",
            "role": "user",
            "status": "active",
            "member_level": "restricted",
        }
    }
    client = _build_app(str(db_path), actor_box).test_client()

    res = client.post("/api/chat/rooms/1/messages", json={"content": "hello"})

    assert res.status_code == 403
    assert res.get_json()["ok"] is False
    assert _message_count(db_path) == 3


def test_member_can_recall_own_message_within_five_minutes(tmp_path):
    db_path = tmp_path / "chat.db"
    _seed_chat_db(db_path)
    recent = (datetime.now() - timedelta(minutes=2)).isoformat()
    conn = sqlite3.connect(db_path)
    conn.execute(
        "INSERT INTO chat_messages (id, room_id, sender_id, content, is_blocked, blocked_reason, created_at) VALUES (5, 1, 3, 'recent', 0, NULL, ?)",
        (recent,),
    )
    conn.commit()
    conn.close()
    actor_box = {"actor": {"id": 3, "username": "alice", "role": "user"}}
    client = _build_app(str(db_path), actor_box).test_client()

    res = client.delete("/api/chat/messages/5")
    messages = client.get("/api/chat/rooms/1/messages")

    assert res.status_code == 200
    assert res.get_json()["msg"] == "訊息已收回"
    revoked = _message_revoked_state(db_path, 5)
    assert revoked[0] == 1
    rendered = [m for m in messages.get_json()["messages"] if m["id"] == 5][0]
    assert rendered["is_revoked"] is True
    assert rendered["content"] == "（訊息已收回）"


def test_member_cannot_recall_own_message_after_five_minutes(tmp_path):
    db_path = tmp_path / "chat.db"
    _seed_chat_db(db_path)
    old = (datetime.now() - timedelta(minutes=6)).isoformat()
    conn = sqlite3.connect(db_path)
    conn.execute(
        "INSERT INTO chat_messages (id, room_id, sender_id, content, is_blocked, blocked_reason, created_at) VALUES (5, 1, 3, 'old', 0, NULL, ?)",
        (old,),
    )
    conn.commit()
    conn.close()
    actor_box = {"actor": {"id": 3, "username": "alice", "role": "user"}}
    client = _build_app(str(db_path), actor_box).test_client()

    res = client.delete("/api/chat/messages/5")

    assert res.status_code == 403
    assert "5 分鐘" in res.get_json()["msg"]
    assert _message_revoked_state(db_path, 5)[0] == 0


def test_member_can_send_chat_sticker(tmp_path):
    db_path = tmp_path / "chat.db"
    _seed_chat_db(db_path)
    actor_box = {"actor": {"id": 3, "username": "alice", "role": "user"}}
    client = _build_app(str(db_path), actor_box).test_client()

    res = client.post("/api/chat/rooms/1/messages", json={"message_type": "sticker", "sticker_key": "smile"})

    assert res.status_code == 200
    assert res.get_json()["ok"] is True
    row = _message_row(db_path, 4)
    assert row["message_type"] == "sticker"
    assert row["sticker_key"] == "smile"


def test_member_can_send_chat_message_with_attachment(tmp_path):
    db_path = tmp_path / "chat.db"
    _seed_chat_db(db_path)
    _seed_uploaded_file(db_path)
    actor_box = {"actor": {"id": 3, "username": "alice", "role": "user"}}
    client = _build_app(str(db_path), actor_box).test_client()

    sent = client.post("/api/chat/rooms/1/messages", json={"content": "see file", "attachment_file_ids": ["file-1"]})
    message_id = sent.get_json()["message_id"]
    actor_box["actor"] = {"id": 4, "username": "bob", "role": "user"}
    messages = client.get("/api/chat/rooms/1/messages")
    rendered = [m for m in messages.get_json()["messages"] if m["id"] == message_id][0]

    assert sent.status_code == 200
    assert rendered["attachments"][0]["file_id"] == "file-1"
    assert rendered["attachments"][0]["original_filename_plain_for_public"] == "chat-note.txt"
    assert rendered["attachments"][0]["can_download"] is True


def test_private_chat_room_can_be_created_without_name_when_target_user_is_set(tmp_path):
    db_path = tmp_path / "chat.db"
    _seed_chat_db(db_path)
    actor_box = {"actor": {"id": 1, "username": "root", "role": "super_admin"}}
    client = _build_app(str(db_path), actor_box).test_client()

    res = client.post("/api/chat/rooms", json={"name": None, "target_user": "alice"})

    assert res.status_code == 200
    payload = res.get_json()
    assert payload["ok"] is True
    assert payload["room"]["is_private"] == 1
    assert payload["room"]["target_username"] == "alice"
    assert payload["room"]["name"] == "PM: alice | root"


def test_member_can_send_attachment_only_chat_message(tmp_path):
    db_path = tmp_path / "chat.db"
    _seed_chat_db(db_path)
    _seed_uploaded_file(db_path)
    actor_box = {"actor": {"id": 3, "username": "alice", "role": "user"}}
    client = _build_app(str(db_path), actor_box).test_client()

    sent = client.post("/api/chat/rooms/1/messages", json={"attachment_file_ids": ["file-1"]})

    assert sent.status_code == 200
    row = _message_row(db_path, sent.get_json()["message_id"])
    assert row["content"] == "已分享附件"


def test_friend_request_accept_and_remove(tmp_path):
    db_path = tmp_path / "chat.db"
    _seed_chat_db(db_path)
    actor_box = {"actor": {"id": 3, "username": "alice", "role": "user"}}
    client = _build_app(str(db_path), actor_box).test_client()

    created = client.post("/api/chat/friends/requests", json={"username": "bob"})
    actor_box["actor"] = {"id": 4, "username": "bob", "role": "user"}
    pending = client.get("/api/chat/friends")
    request_id = pending.get_json()["incoming"][0]["id"]
    accepted = client.post(f"/api/chat/friends/requests/{request_id}/accept")
    friends = client.get("/api/chat/friends")
    removed = client.delete("/api/chat/friends/3")

    assert created.status_code == 200
    assert accepted.status_code == 200
    assert friends.get_json()["friends"][0]["other_username"] == "alice"
    assert removed.status_code == 200
