import sqlite3

from flask import Flask, jsonify

from routes.community import register_community_routes


def _role_rank(role):
    return {"user": 0, "manager": 1, "super_admin": 2}.get(role or "user", 0)


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

    register_community_routes(app, {
        "audit": lambda *args, **kwargs: None,
        "check_user_rate_limit": lambda *args, **kwargs: (False, {"limit": 10}),
        "get_client_ip": lambda: "127.0.0.1",
        "get_current_user_ctx": lambda: actor_box["actor"],
        "get_db": get_db,
        "get_ua": lambda: "test-agent",
        "json_resp": json_resp,
        "normalize_text": lambda value: value.strip() if isinstance(value, str) else "",
        "parse_positive_int": _parse_positive_int,
        "require_csrf": passthrough,
        "require_csrf_safe": passthrough,
        "role_rank": _role_rank,
    })
    return app


def _seed_community_db(db_path):
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        CREATE TABLE users (
            id INTEGER PRIMARY KEY,
            username TEXT NOT NULL,
            role TEXT NOT NULL
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
    conn.commit()
    conn.close()

    actor_box = {"actor": {"id": 1, "username": "root", "role": "super_admin"}}
    client = _build_app(str(db_path), actor_box).test_client()
    client.post(
        "/api/community/announcements",
        json={"title": "公告", "content": "內容", "is_pinned": False},
    )
    client.post(
        "/api/community/boards",
        json={"title": "版面", "description": "說明", "rules": "規則"},
    )

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    board_id = conn.execute("SELECT id FROM forum_boards LIMIT 1").fetchone()["id"]
    conn.execute("UPDATE forum_boards SET status='approved' WHERE id=?", (board_id,))
    conn.commit()
    conn.close()

    actor_box["actor"] = {"id": 3, "username": "alice", "role": "user"}
    client.post(
        f"/api/community/boards/{board_id}/threads",
        json={"title": "主題", "content": "主題內容"},
    )

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    thread_id = conn.execute("SELECT id FROM forum_threads LIMIT 1").fetchone()["id"]
    conn.execute("UPDATE forum_threads SET status='approved' WHERE id=?", (thread_id,))
    conn.commit()
    conn.close()

    client.post(
        f"/api/community/threads/{thread_id}/posts",
        json={"content": "alice 回覆"},
    )
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    ids = {
        "announcement": conn.execute("SELECT id FROM announcements LIMIT 1").fetchone()["id"],
        "thread": thread_id,
        "post": conn.execute("SELECT id FROM forum_posts LIMIT 1").fetchone()["id"],
    }
    conn.close()
    return ids


def _count(db_path, table_name):
    conn = sqlite3.connect(db_path)
    count = conn.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()[0]
    conn.close()
    return count


def _announcement_active(db_path, announcement_id):
    conn = sqlite3.connect(db_path)
    active = conn.execute("SELECT is_active FROM announcements WHERE id=?", (announcement_id,)).fetchone()[0]
    conn.close()
    return active


def test_manager_can_delete_announcement_thread_and_post(tmp_path):
    db_path = tmp_path / "community.db"
    ids = _seed_community_db(db_path)
    actor_box = {"actor": {"id": 2, "username": "admin", "role": "manager"}}
    client = _build_app(str(db_path), actor_box).test_client()

    announcement = client.delete(f"/api/community/announcements/{ids['announcement']}")
    assert announcement.status_code == 200
    assert announcement.get_json()["ok"] is True
    assert _announcement_active(db_path, ids["announcement"]) == 0

    post = client.delete(f"/api/community/posts/{ids['post']}")
    assert post.status_code == 200
    assert post.get_json()["ok"] is True
    assert _count(db_path, "forum_posts") == 0

    thread = client.delete(f"/api/community/threads/{ids['thread']}")
    assert thread.status_code == 200
    assert thread.get_json()["ok"] is True
    assert _count(db_path, "forum_threads") == 0


def test_user_cannot_delete_other_user_thread_or_post(tmp_path):
    db_path = tmp_path / "community.db"
    ids = _seed_community_db(db_path)
    actor_box = {"actor": {"id": 4, "username": "bob", "role": "user"}}
    client = _build_app(str(db_path), actor_box).test_client()

    post = client.delete(f"/api/community/posts/{ids['post']}")
    assert post.status_code == 403
    assert post.get_json()["ok"] is False

    thread = client.delete(f"/api/community/threads/{ids['thread']}")
    assert thread.status_code == 403
    assert thread.get_json()["ok"] is False
