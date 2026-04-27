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


def _post_row(db_path, post_id):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT id, content, is_pinned, is_hidden, hidden_reason, is_deleted, deleted_by, edited_by FROM forum_posts WHERE id=?",
        (post_id,)
    ).fetchone()
    conn.close()
    return row


def _thread_row(db_path, thread_id):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT id, title, content, is_deleted, deleted_by, edited_by FROM forum_threads WHERE id=?",
        (thread_id,)
    ).fetchone()
    conn.close()
    return row


def _announcement_active(db_path, announcement_id):
    conn = sqlite3.connect(db_path)
    active = conn.execute("SELECT is_active FROM announcements WHERE id=?", (announcement_id,)).fetchone()[0]
    conn.close()
    return active


def test_forum_board_schema_backfills_slug_and_visibility(tmp_path):
    db_path = tmp_path / "community.db"
    ids = _seed_community_db(db_path)
    actor_box = {"actor": {"id": 2, "username": "admin", "role": "manager"}}
    client = _build_app(str(db_path), actor_box).test_client()

    boards = client.get("/api/community/boards").get_json()["boards"]
    board = next(item for item in boards if item["id"])

    assert board["slug"].startswith("board-")
    assert board["visibility"] == "public"
    assert board["sort_order"] == 100
    assert board["is_active"] is True
    assert board["last_activity_at"]


def test_manager_can_update_board_visibility_and_inactive_blocks_users(tmp_path):
    db_path = tmp_path / "community.db"
    ids = _seed_community_db(db_path)
    conn = sqlite3.connect(db_path)
    board_id = conn.execute("SELECT board_id FROM forum_threads WHERE id=?", (ids["thread"],)).fetchone()[0]
    conn.close()

    actor_box = {"actor": {"id": 2, "username": "admin", "role": "manager"}}
    client = _build_app(str(db_path), actor_box).test_client()
    update = client.put(
        f"/api/community/boards/{board_id}",
        json={"visibility": "private", "is_active": False, "sort_order": 5},
    )
    assert update.status_code == 200
    assert update.get_json()["ok"] is True

    actor_box["actor"] = {"id": 4, "username": "bob", "role": "user"}
    listed = client.get("/api/community/boards").get_json()["boards"]
    assert all(item["id"] != board_id for item in listed)
    blocked = client.get(f"/api/community/boards/{board_id}/threads")
    assert blocked.status_code == 403


def test_non_manager_cannot_update_board(tmp_path):
    db_path = tmp_path / "community.db"
    ids = _seed_community_db(db_path)
    conn = sqlite3.connect(db_path)
    board_id = conn.execute("SELECT board_id FROM forum_threads WHERE id=?", (ids["thread"],)).fetchone()[0]
    conn.close()

    actor_box = {"actor": {"id": 3, "username": "alice", "role": "user"}}
    client = _build_app(str(db_path), actor_box).test_client()

    res = client.put(f"/api/community/boards/{board_id}", json={"visibility": "private"})

    assert res.status_code == 403
    assert res.get_json()["ok"] is False


def test_manager_can_create_category_and_assign_board(tmp_path):
    db_path = tmp_path / "community.db"
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        CREATE TABLE users (
            id INTEGER PRIMARY KEY,
            username TEXT NOT NULL,
            role TEXT NOT NULL
        );
        INSERT INTO users (id, username, role) VALUES (1, 'root', 'super_admin');
        """
    )
    conn.commit()
    conn.close()

    actor_box = {"actor": {"id": 1, "username": "root", "role": "super_admin"}}
    client = _build_app(str(db_path), actor_box).test_client()

    created = client.post(
        "/api/community/categories",
        json={"name": "技術交流", "description": "工程討論", "sort_order": 10},
    )
    assert created.status_code == 200
    assert created.get_json()["ok"] is True

    categories = client.get("/api/community/categories")
    category = next(item for item in categories.get_json()["categories"] if item["name"] == "技術交流")

    board = client.post(
        "/api/community/boards",
        json={"category_id": category["id"], "title": "Python", "description": "Python 討論", "rules": "友善"},
    )
    assert board.status_code == 200
    assert board.get_json()["ok"] is True

    boards = client.get("/api/community/boards").get_json()["boards"]
    python_board = next(item for item in boards if item["title"] == "Python")
    assert python_board["category_id"] == category["id"]
    assert python_board["category"]["name"] == "技術交流"


def test_non_manager_cannot_create_category(tmp_path):
    db_path = tmp_path / "community.db"
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        CREATE TABLE users (
            id INTEGER PRIMARY KEY,
            username TEXT NOT NULL,
            role TEXT NOT NULL
        );
        INSERT INTO users (id, username, role) VALUES (3, 'alice', 'user');
        """
    )
    conn.commit()
    conn.close()

    actor_box = {"actor": {"id": 3, "username": "alice", "role": "user"}}
    client = _build_app(str(db_path), actor_box).test_client()

    res = client.post("/api/community/categories", json={"name": "私人分類"})

    assert res.status_code == 403
    assert res.get_json()["ok"] is False


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
    assert _count(db_path, "forum_posts") == 1
    assert _post_row(db_path, ids["post"])["is_deleted"] == 1

    thread = client.delete(f"/api/community/threads/{ids['thread']}")
    assert thread.status_code == 200
    assert thread.get_json()["ok"] is True
    assert _count(db_path, "forum_threads") == 1
    assert _thread_row(db_path, ids["thread"])["is_deleted"] == 1


def test_soft_deleted_thread_and_post_are_hidden_from_users(tmp_path):
    db_path = tmp_path / "community.db"
    ids = _seed_community_db(db_path)
    actor_box = {"actor": {"id": 2, "username": "admin", "role": "manager"}}
    client = _build_app(str(db_path), actor_box).test_client()

    delete_post = client.delete(f"/api/community/posts/{ids['post']}")
    assert delete_post.status_code == 200

    actor_box["actor"] = {"id": 3, "username": "alice", "role": "user"}
    detail = client.get(f"/api/community/threads/{ids['thread']}")
    assert detail.status_code == 200
    assert detail.get_json()["posts"] == []

    actor_box["actor"] = {"id": 2, "username": "admin", "role": "manager"}
    delete_thread = client.delete(f"/api/community/threads/{ids['thread']}")
    assert delete_thread.status_code == 200

    actor_box["actor"] = {"id": 3, "username": "alice", "role": "user"}
    hidden_detail = client.get(f"/api/community/threads/{ids['thread']}")
    assert hidden_detail.status_code == 404

    conn = sqlite3.connect(db_path)
    board_id = conn.execute("SELECT board_id FROM forum_threads WHERE id=?", (ids["thread"],)).fetchone()[0]
    conn.close()
    listed = client.get(f"/api/community/boards/{board_id}/threads")
    assert all(item["id"] != ids["thread"] for item in listed.get_json()["threads"])


def test_author_can_update_own_thread_and_post(tmp_path):
    db_path = tmp_path / "community.db"
    ids = _seed_community_db(db_path)
    actor_box = {"actor": {"id": 3, "username": "alice", "role": "user"}}
    client = _build_app(str(db_path), actor_box).test_client()

    thread = client.put(
        f"/api/community/threads/{ids['thread']}",
        json={"title": "更新主題", "content": "更新內容"},
    )
    post = client.put(
        f"/api/community/posts/{ids['post']}",
        json={"content": "更新留言"},
    )

    assert thread.status_code == 200
    assert post.status_code == 200
    thread_row = _thread_row(db_path, ids["thread"])
    post_row = _post_row(db_path, ids["post"])
    assert thread_row["title"] == "更新主題"
    assert thread_row["content"] == "更新內容"
    assert thread_row["edited_by"] == "alice"
    assert post_row["content"] == "更新留言"
    assert post_row["edited_by"] == "alice"


def test_user_cannot_update_other_user_thread_or_post(tmp_path):
    db_path = tmp_path / "community.db"
    ids = _seed_community_db(db_path)
    actor_box = {"actor": {"id": 4, "username": "bob", "role": "user"}}
    client = _build_app(str(db_path), actor_box).test_client()

    thread = client.put(
        f"/api/community/threads/{ids['thread']}",
        json={"title": "惡意修改", "content": "不應成功"},
    )
    post = client.put(
        f"/api/community/posts/{ids['post']}",
        json={"content": "不應成功"},
    )

    assert thread.status_code == 403
    assert post.status_code == 403


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


def test_restricted_member_cannot_create_thread_or_reply(tmp_path):
    db_path = tmp_path / "community.db"
    ids = _seed_community_db(db_path)
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

    create = client.post(
        "/api/community/boards/1/threads",
        json={"title": "受限發文", "content": "不應成功"},
    )
    reply = client.post(
        f"/api/community/threads/{ids['thread']}/posts",
        json={"content": "受限留言"},
    )

    assert create.status_code == 403
    assert create.get_json()["ok"] is False
    assert reply.status_code == 403
    assert reply.get_json()["ok"] is False


def test_manager_can_pin_post(tmp_path):
    db_path = tmp_path / "community.db"
    ids = _seed_community_db(db_path)
    actor_box = {"actor": {"id": 2, "username": "admin", "role": "manager"}}
    client = _build_app(str(db_path), actor_box).test_client()

    res = client.post(f"/api/community/posts/{ids['post']}/pin", json={"pinned": True})

    assert res.status_code == 200
    assert res.get_json()["ok"] is True
    assert _post_row(db_path, ids["post"])["is_pinned"] == 1


def test_dislikes_auto_hide_post_and_create_root_report(tmp_path):
    db_path = tmp_path / "community.db"
    ids = _seed_community_db(db_path)
    actor_box = {"actor": {"id": 2, "username": "admin", "role": "manager"}}
    client = _build_app(str(db_path), actor_box).test_client()

    for actor in (
        {"id": 2, "username": "admin", "role": "manager"},
        {"id": 3, "username": "alice", "role": "user"},
        {"id": 4, "username": "bob", "role": "user"},
    ):
        actor_box["actor"] = actor
        res = client.post(f"/api/community/posts/{ids['post']}/reaction", json={"value": -1})
        assert res.status_code == 200
        assert res.get_json()["ok"] is True

    post = _post_row(db_path, ids["post"])
    assert post["is_hidden"] == 1
    assert "倒讚過多" in post["hidden_reason"]

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    report = conn.execute(
        "SELECT post_id, status, reason FROM forum_post_reports WHERE post_id=?",
        (ids["post"],)
    ).fetchone()
    conn.close()
    assert report["post_id"] == ids["post"]
    assert report["status"] == "pending"
    assert "倒讚過多" in report["reason"]


def test_dislike_auto_hide_threshold_scales_with_active_users(tmp_path):
    db_path = tmp_path / "community.db"
    ids = _seed_community_db(db_path)
    conn = sqlite3.connect(db_path)
    conn.executemany(
        "INSERT INTO users (id, username, role) VALUES (?, ?, 'user')",
        [(user_id, f"user{user_id}") for user_id in range(5, 41)]
    )
    conn.commit()
    conn.close()

    actor_box = {"actor": {"id": 2, "username": "admin", "role": "manager"}}
    client = _build_app(str(db_path), actor_box).test_client()

    for actor in (
        {"id": 2, "username": "admin", "role": "manager"},
        {"id": 3, "username": "alice", "role": "user"},
        {"id": 4, "username": "bob", "role": "user"},
    ):
        actor_box["actor"] = actor
        res = client.post(f"/api/community/posts/{ids['post']}/reaction", json={"value": -1})
        assert res.status_code == 200

    assert _post_row(db_path, ids["post"])["is_hidden"] == 0

    actor_box["actor"] = {"id": 5, "username": "user5", "role": "user"}
    res = client.post(f"/api/community/posts/{ids['post']}/reaction", json={"value": -1})

    assert res.status_code == 200
    assert res.get_json()["auto_hidden"] is True
    post = _post_row(db_path, ids["post"])
    assert post["is_hidden"] == 1
    assert "4/4" in post["hidden_reason"]
