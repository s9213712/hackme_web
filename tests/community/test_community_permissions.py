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
        return None
    return parsed


def _build_app(db_path, actor_box, detect_chat_violation=None, add_violation=None):
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
        "detect_chat_violation": detect_chat_violation or (lambda *args, **kwargs: (False, "")),
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
        "add_violation": add_violation,
    })
    return app


def _seed_community_db(db_path):
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        CREATE TABLE users (
            id INTEGER PRIMARY KEY,
            username TEXT NOT NULL,
            role TEXT NOT NULL,
            avatar_file_id TEXT,
            avatar_crop_json TEXT
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

    actor_box["actor"] = {"id": 3, "username": "alice", "role": "user", "member_level": "newbie"}
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
        "SELECT id, title, content, status, post_type, is_sticky, is_locked, is_curated, view_count, is_deleted, deleted_by, edited_by FROM forum_threads WHERE id=?",
        (thread_id,)
    ).fetchone()
    conn.close()
    return row


def _announcement_active(db_path, announcement_id):
    conn = sqlite3.connect(db_path)
    active = conn.execute("SELECT is_active FROM announcements WHERE id=?", (announcement_id,)).fetchone()[0]
    conn.close()
    return active


def test_community_routes_accept_sqlite_row_actor(tmp_path):
    db_path = tmp_path / "community.db"
    _seed_community_db(db_path)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        actor = conn.execute("SELECT id, username, role FROM users WHERE username='root'").fetchone()
    finally:
        conn.close()
    actor_box = {"actor": actor}
    client = _build_app(str(db_path), actor_box).test_client()

    announcements = client.get("/api/community/announcements")
    categories = client.get("/api/community/categories")
    boards = client.get("/api/community/boards")

    assert announcements.status_code == 200
    assert categories.status_code == 200
    assert boards.status_code == 200


def test_forum_board_schema_backfills_slug_and_visibility(tmp_path):
    db_path = tmp_path / "community.db"
    ids = _seed_community_db(db_path)
    actor_box = {"actor": {"id": 2, "username": "admin", "role": "manager"}}
    client = _build_app(str(db_path), actor_box).test_client()

    boards = client.get("/api/community/boards").get_json()["boards"]
    board = next(item for item in boards if item["title"] == "版面")

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
            role TEXT NOT NULL,
            avatar_file_id TEXT,
            avatar_crop_json TEXT
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
            role TEXT NOT NULL,
            avatar_file_id TEXT,
            avatar_crop_json TEXT
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


def test_root_can_delete_announcement_thread_and_post(tmp_path):
    db_path = tmp_path / "community.db"
    ids = _seed_community_db(db_path)
    actor_box = {"actor": {"id": 1, "username": "root", "role": "super_admin"}}
    client = _build_app(str(db_path), actor_box).test_client()

    announcement = client.delete(f"/api/community/announcements/{ids['announcement']}")
    assert announcement.status_code == 200
    assert announcement.get_json()["ok"] is True

    post = client.delete(f"/api/community/posts/{ids['post']}")
    assert post.status_code == 200
    assert post.get_json()["ok"] is True

    thread = client.delete(f"/api/community/threads/{ids['thread']}")
    assert thread.status_code == 200
    assert thread.get_json()["ok"] is True


def test_soft_deleted_thread_and_post_are_hidden_from_users(tmp_path):
    db_path = tmp_path / "community.db"
    ids = _seed_community_db(db_path)
    actor_box = {"actor": {"id": 2, "username": "admin", "role": "manager"}}
    client = _build_app(str(db_path), actor_box).test_client()

    delete_post = client.delete(f"/api/community/posts/{ids['post']}")
    assert delete_post.status_code == 200

    actor_box["actor"] = {"id": 3, "username": "alice", "role": "user", "member_level": "newbie"}
    detail = client.get(f"/api/community/threads/{ids['thread']}")
    assert detail.status_code == 200
    assert detail.get_json()["posts"] == []

    actor_box["actor"] = {"id": 2, "username": "admin", "role": "manager"}
    delete_thread = client.delete(f"/api/community/threads/{ids['thread']}")
    assert delete_thread.status_code == 200

    actor_box["actor"] = {"id": 3, "username": "alice", "role": "user", "member_level": "newbie"}
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


def test_community_sensitive_filter_exempts_only_comfyui_threads(tmp_path):
    db_path = tmp_path / "community.db"
    _seed_community_db(db_path)
    violation_calls = []

    def detect_sensitive(text):
        return ("badword" in (text or "").lower(), "測試敏感詞")

    def add_violation(*args, **kwargs):
        violation_calls.append({"args": args, "kwargs": kwargs})
        return "counted", "違規計點 +1", len(violation_calls)

    actor_box = {"actor": {"id": 1, "username": "root", "role": "super_admin"}}
    client = _build_app(str(db_path), actor_box, detect_sensitive, add_violation).test_client()
    boards = client.get("/api/community/boards")
    assert boards.status_code == 200

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    normal_board_id = conn.execute("SELECT id FROM forum_boards WHERE title='遊戲專區'").fetchone()["id"]
    comfyui_board_id = conn.execute("SELECT id FROM forum_boards WHERE title='ComfyUI專區'").fetchone()["id"]
    conn.close()

    actor_box["actor"] = {"id": 3, "username": "alice", "role": "user", "member_level": "normal"}
    blocked_thread = client.post(
        f"/api/community/boards/{normal_board_id}/threads",
        json={"title": "normal badword", "content": "clean body"},
    )
    assert blocked_thread.status_code == 403
    assert blocked_thread.get_json()["ok"] is False
    assert "敏感詞" in blocked_thread.get_json()["msg"]

    comfyui_thread = client.post(
        f"/api/community/boards/{comfyui_board_id}/threads",
        json={"title": "ComfyUI badword prompt", "content": "badword workflow parameters"},
    )
    assert comfyui_thread.status_code == 200
    assert comfyui_thread.get_json()["ok"] is True

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    thread_id = conn.execute(
        "SELECT id FROM forum_threads WHERE board_id=? ORDER BY id DESC LIMIT 1",
        (comfyui_board_id,),
    ).fetchone()["id"]
    conn.close()

    blocked_reply = client.post(
        f"/api/community/threads/{thread_id}/posts",
        json={"content": "badword reply is not exempt"},
    )
    assert blocked_reply.status_code == 403
    assert blocked_reply.get_json()["ok"] is False
    assert "敏感詞" in blocked_reply.get_json()["msg"]

    clean_reply = client.post(
        f"/api/community/threads/{thread_id}/posts",
        json={"content": "clean reply"},
    )
    assert clean_reply.status_code == 200

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    post_id = conn.execute("SELECT id FROM forum_posts WHERE thread_id=? LIMIT 1", (thread_id,)).fetchone()["id"]
    conn.close()
    blocked_edit = client.put(
        f"/api/community/posts/{post_id}",
        json={"content": "edited badword reply"},
    )
    assert blocked_edit.status_code == 403
    assert blocked_edit.get_json()["ok"] is False
    assert len(violation_calls) == 3


def test_manager_can_pin_post(tmp_path):
    db_path = tmp_path / "community.db"
    ids = _seed_community_db(db_path)
    actor_box = {"actor": {"id": 2, "username": "admin", "role": "manager"}}
    client = _build_app(str(db_path), actor_box).test_client()

    res = client.post(f"/api/community/posts/{ids['post']}/pin", json={"pinned": True})

    assert res.status_code == 200
    assert res.get_json()["ok"] is True
    assert _post_row(db_path, ids["post"])["is_pinned"] == 1


def test_newbie_thread_requires_review_but_normal_thread_is_approved(tmp_path):
    db_path = tmp_path / "community.db"
    ids = _seed_community_db(db_path)
    conn = sqlite3.connect(db_path)
    board_id = conn.execute("SELECT board_id FROM forum_threads WHERE id=?", (ids["thread"],)).fetchone()[0]
    conn.close()

    actor_box = {"actor": {"id": 3, "username": "alice", "role": "user", "member_level": "newbie"}}
    client = _build_app(str(db_path), actor_box).test_client()
    newbie = client.post(
        f"/api/community/boards/{board_id}/threads",
        json={"title": "新手待審", "content": "需要審核", "post_type": "question"},
    )
    assert newbie.status_code == 200
    assert newbie.get_json()["status"] == "pending"

    actor_box["actor"] = {"id": 4, "username": "bob", "role": "user", "member_level": "normal"}
    normal = client.post(
        f"/api/community/boards/{board_id}/threads",
        json={"title": "一般直接公開", "content": "可直接公開", "post_type": "howto"},
    )
    assert normal.status_code == 200
    assert normal.get_json()["status"] == "approved"

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    rows = {
        row["title"]: dict(row)
        for row in conn.execute("SELECT title, status, post_type FROM forum_threads WHERE title IN (?, ?)", ("新手待審", "一般直接公開")).fetchall()
    }
    conn.close()
    assert rows["新手待審"]["status"] == "pending"
    assert rows["新手待審"]["post_type"] == "question"
    assert rows["一般直接公開"]["status"] == "approved"
    assert rows["一般直接公開"]["post_type"] == "howto"


def test_manager_can_sticky_curate_and_view_count_dedupes(tmp_path):
    db_path = tmp_path / "community.db"
    ids = _seed_community_db(db_path)
    actor_box = {"actor": {"id": 2, "username": "admin", "role": "manager"}}
    client = _build_app(str(db_path), actor_box).test_client()

    sticky = client.post(f"/api/community/threads/{ids['thread']}/sticky", json={"sticky": True})
    curate = client.post(f"/api/community/threads/{ids['thread']}/curate", json={"curated": True})
    assert sticky.status_code == 200
    assert curate.status_code == 200
    row = _thread_row(db_path, ids["thread"])
    assert row["is_sticky"] == 1
    assert row["is_curated"] == 1

    actor_box["actor"] = {"id": 4, "username": "bob", "role": "user"}
    first = client.get(f"/api/community/threads/{ids['thread']}")
    second = client.get(f"/api/community/threads/{ids['thread']}")
    assert first.status_code == 200
    assert second.status_code == 200
    assert first.get_json()["thread"]["view_counted"] is True
    assert second.get_json()["thread"]["view_counted"] is False
    assert second.get_json()["thread"]["view_count"] == first.get_json()["thread"]["view_count"]


def test_manager_can_assign_board_moderator_with_scoped_permissions(tmp_path):
    db_path = tmp_path / "community.db"
    ids = _seed_community_db(db_path)
    conn = sqlite3.connect(db_path)
    board_id = conn.execute("SELECT board_id FROM forum_threads WHERE id=?", (ids["thread"],)).fetchone()[0]
    conn.close()

    actor_box = {"actor": {"id": 2, "username": "admin", "role": "manager"}}
    client = _build_app(str(db_path), actor_box).test_client()
    assigned = client.post(
        f"/api/community/boards/{board_id}/moderators",
        json={"user_id": 4, "can_pin_posts": True, "can_lock_threads": True, "can_delete_posts": True},
    )
    assert assigned.status_code == 200
    listed = client.get(f"/api/community/boards/{board_id}/moderators")
    assert any(item["user_id"] == 4 for item in listed.get_json()["moderators"])

    actor_box["actor"] = {"id": 4, "username": "bob", "role": "user"}
    pin = client.post(f"/api/community/posts/{ids['post']}/pin", json={"pinned": True})
    lock = client.post(f"/api/community/threads/{ids['thread']}/lock", json={"locked": True})
    delete = client.delete(f"/api/community/posts/{ids['post']}")

    assert pin.status_code == 200
    assert lock.status_code == 200
    assert delete.status_code == 200
    assert _post_row(db_path, ids["post"])["is_deleted"] == 1


def test_manager_can_edit_announcement(tmp_path):
    db_path = tmp_path / "community.db"
    ids = _seed_community_db(db_path)
    actor_box = {"actor": {"id": 2, "username": "admin", "role": "manager"}}
    client = _build_app(str(db_path), actor_box).test_client()

    edited = client.put(
        f"/api/community/announcements/{ids['announcement']}",
        json={"title": "更新公告", "content": "更新內容", "is_pinned": True},
    )

    assert edited.status_code == 200
    payload = edited.get_json()
    assert payload["ok"] is True
    assert payload["msg"] == "公告已更新"
    assert payload["announcement"]["title"] == "更新公告"
    assert payload["announcement"]["is_pinned"] is True

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT title, content, is_pinned FROM announcements WHERE id=?",
        (ids["announcement"],),
    ).fetchone()
    conn.close()
    assert row["title"] == "更新公告"
    assert row["content"] == "更新內容"
    assert row["is_pinned"] == 1


def test_non_manager_cannot_edit_announcement(tmp_path):
    db_path = tmp_path / "community.db"
    ids = _seed_community_db(db_path)
    actor_box = {"actor": {"id": 3, "username": "alice", "role": "user"}}
    client = _build_app(str(db_path), actor_box).test_client()

    edited = client.put(
        f"/api/community/announcements/{ids['announcement']}",
        json={"title": "偷改", "content": "不應成功", "is_pinned": False},
    )

    assert edited.status_code == 403
    assert edited.get_json()["ok"] is False

def test_board_moderator_can_pin_thread_without_pin_post_permission(tmp_path):
    db_path = tmp_path / "community.db"
    ids = _seed_community_db(db_path)
    conn = sqlite3.connect(db_path)
    board_id = conn.execute("SELECT board_id FROM forum_threads WHERE id=?", (ids["thread"],)).fetchone()[0]
    conn.close()

    actor_box = {"actor": {"id": 2, "username": "admin", "role": "manager"}}
    client = _build_app(str(db_path), actor_box).test_client()
    assigned = client.post(
        f"/api/community/boards/{board_id}/moderators",
        json={"user_id": 4, "can_pin_threads": True, "can_pin_posts": False},
    )
    assert assigned.status_code == 200
    moderator = next(
        item for item in client.get(f"/api/community/boards/{board_id}/moderators").get_json()["moderators"]
        if item["user_id"] == 4
    )
    assert moderator["can_pin_threads"] is True
    assert moderator["can_pin_posts"] is False

    actor_box["actor"] = {"id": 4, "username": "bob", "role": "user"}
    sticky = client.post(f"/api/community/threads/{ids['thread']}/sticky", json={"sticky": True})
    post_pin = client.post(f"/api/community/posts/{ids['post']}/pin", json={"pinned": True})

    assert sticky.status_code == 200
    assert post_pin.status_code == 403
    assert _thread_row(db_path, ids["thread"])["is_sticky"] == 1
    assert _post_row(db_path, ids["post"])["is_pinned"] == 0


def test_board_moderator_can_review_only_assigned_board_threads(tmp_path):
    db_path = tmp_path / "community.db"
    ids = _seed_community_db(db_path)
    conn = sqlite3.connect(db_path)
    board_id = conn.execute("SELECT board_id FROM forum_threads WHERE id=?", (ids["thread"],)).fetchone()[0]
    conn.close()

    actor_box = {"actor": {"id": 2, "username": "admin", "role": "manager"}}
    client = _build_app(str(db_path), actor_box).test_client()
    assigned = client.post(
        f"/api/community/boards/{board_id}/moderators",
        json={"user_id": 4, "can_review_threads": True},
    )
    assert assigned.status_code == 200

    actor_box["actor"] = {"id": 3, "username": "alice", "role": "user", "member_level": "newbie"}
    pending = client.post(
        f"/api/community/boards/{board_id}/threads",
        json={"title": "待審主題", "content": "需要版主審核"},
    )
    assert pending.status_code == 200
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    pending_id = conn.execute(
        "SELECT id FROM forum_threads WHERE title=?",
        ("待審主題",)
    ).fetchone()["id"]
    conn.close()

    actor_box["actor"] = {"id": 4, "username": "bob", "role": "user"}
    reviews = client.get("/api/community/threads/reviews")
    assert any(item["id"] == pending_id for item in reviews.get_json()["items"])
    approved = client.post(f"/api/community/threads/{pending_id}/review", json={"action": "approve"})
    assert approved.status_code == 200
    assert _thread_row(db_path, pending_id)["title"] == "待審主題"


def test_board_moderator_reward_and_penalty_permissions_are_scoped(tmp_path):
    db_path = tmp_path / "community.db"
    ids = _seed_community_db(db_path)
    conn = sqlite3.connect(db_path)
    board_id = conn.execute("SELECT board_id FROM forum_threads WHERE id=?", (ids["thread"],)).fetchone()[0]
    conn.close()

    actor_box = {"actor": {"id": 2, "username": "admin", "role": "manager"}}
    client = _build_app(str(db_path), actor_box).test_client()
    assigned = client.post(
        f"/api/community/boards/{board_id}/moderators",
        json={
            "user_id": 4,
            "can_reward_authors": False,
            "can_penalize_posts": False,
            "can_pin_threads": False,
            "can_pin_posts": True,
            "can_delete_posts": True,
        },
    )
    assert assigned.status_code == 200

    listed = client.get(f"/api/community/boards/{board_id}/moderators")
    moderator = next(item for item in listed.get_json()["moderators"] if item["user_id"] == 4)
    assert moderator["can_reward_authors"] is False
    assert moderator["can_penalize_posts"] is False
    assert moderator["can_pin_threads"] is False
    assert moderator["can_pin_posts"] is True
    assert moderator["can_delete_posts"] is True

    actor_box["actor"] = {"id": 4, "username": "bob", "role": "user"}
    reward_denied = client.post(f"/api/community/threads/{ids['thread']}/reward", json={"points": 1})
    penalty_denied = client.post(f"/api/community/posts/{ids['post']}/penalty", json={"points": 1})
    assert reward_denied.status_code == 403
    assert penalty_denied.status_code == 403

    actor_box["actor"] = {"id": 2, "username": "admin", "role": "manager"}
    updated = client.post(
        f"/api/community/boards/{board_id}/moderators",
        json={"user_id": 4, "can_reward_authors": True, "can_penalize_posts": True},
    )
    assert updated.status_code == 200

    actor_box["actor"] = {"id": 4, "username": "bob", "role": "user"}
    reward_ok = client.post(f"/api/community/threads/{ids['thread']}/reward", json={"points": 1})
    penalty_ok = client.post(f"/api/community/posts/{ids['post']}/penalty", json={"points": 1})
    assert reward_ok.status_code == 200
    assert penalty_ok.status_code == 200


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


def test_default_forum_boards_have_moderator(tmp_path):
    db_path = tmp_path / "community.db"
    _seed_community_db(db_path)
    actor_box = {"actor": {"id": 1, "username": "root", "role": "super_admin"}}
    client = _build_app(str(db_path), actor_box).test_client()

    res = client.get("/api/community/boards")
    assert res.status_code == 200
    boards = res.get_json()["boards"]
    by_title = {item["title"]: item for item in boards}

    for title in ("遊戲專區", "二次元專區", "ComfyUI專區", "程式設計區", "AI新知區"):
        assert title in by_title
        assert by_title[title]["status"] == "approved"
        assert by_title[title]["moderator_count"] >= 1
        assert "root" in by_title[title]["moderators"]


def test_thread_reactions_are_available_on_thread_itself(tmp_path):
    db_path = tmp_path / "community.db"
    ids = _seed_community_db(db_path)
    actor_box = {"actor": {"id": 4, "username": "bob", "role": "user"}}
    client = _build_app(str(db_path), actor_box).test_client()

    liked = client.post(f"/api/community/threads/{ids['thread']}/reaction", json={"value": 1})
    assert liked.status_code == 200
    assert liked.get_json()["like_count"] == 1

    detail = client.get(f"/api/community/threads/{ids['thread']}")
    assert detail.status_code == 200
    thread = detail.get_json()["thread"]
    assert thread["like_count"] == 1
    assert thread["dislike_count"] == 0
    assert thread["user_reaction"] == 1


def test_moderator_can_reward_thread_author_and_penalize_post_author(tmp_path):
    db_path = tmp_path / "community.db"
    ids = _seed_community_db(db_path)
    actor_box = {"actor": {"id": 2, "username": "admin", "role": "manager"}}
    client = _build_app(str(db_path), actor_box).test_client()

    reward = client.post(
        f"/api/community/threads/{ids['thread']}/reward",
        json={"points": 3, "reason": "good topic"},
    )
    assert reward.status_code == 200
    penalty = client.post(
        f"/api/community/posts/{ids['post']}/penalty",
        json={"points": 2, "reason": "bad reply"},
    )
    assert penalty.status_code == 200

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    alice = conn.execute("SELECT reputation, violation_count FROM users WHERE id=3").fetchone()
    actions = conn.execute("SELECT action_type, target_type FROM moderation_actions ORDER BY id ASC").fetchall()
    conn.close()
    assert alice["reputation"] == 3
    assert alice["violation_count"] == 2
    assert ("reward_thread_author", "forum_thread") in [(row["action_type"], row["target_type"]) for row in actions]
    assert ("penalize_post_author", "forum_post") in [(row["action_type"], row["target_type"]) for row in actions]


def test_reward_and_penalty_reject_out_of_range_points(tmp_path):
    db_path = tmp_path / "community.db"
    ids = _seed_community_db(db_path)
    actor_box = {"actor": {"id": 2, "username": "admin", "role": "manager"}}
    client = _build_app(str(db_path), actor_box).test_client()

    reward = client.post(f"/api/community/threads/{ids['thread']}/reward", json={"points": 999})
    penalty = client.post(f"/api/community/posts/{ids['post']}/penalty", json={"points": 999})

    assert reward.status_code == 400
    assert penalty.status_code == 400
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    alice = conn.execute("SELECT reputation, violation_count FROM users WHERE id=3").fetchone()
    conn.close()
    assert alice["reputation"] == 0
    assert alice["violation_count"] == 0


def test_unlisted_board_reply_requires_owner_or_moderator(tmp_path):
    db_path = tmp_path / "community.db"
    ids = _seed_community_db(db_path)
    conn = sqlite3.connect(db_path)
    board_id = conn.execute("SELECT board_id FROM forum_threads WHERE id=?", (ids["thread"],)).fetchone()[0]
    conn.execute("UPDATE forum_boards SET visibility='unlisted' WHERE id=?", (board_id,))
    conn.commit()
    conn.close()

    actor_box = {"actor": {"id": 4, "username": "bob", "role": "user"}}
    client = _build_app(str(db_path), actor_box).test_client()
    denied = client.post(f"/api/community/threads/{ids['thread']}/posts", json={"content": "should not enter"})
    assert denied.status_code == 403

    actor_box["actor"] = {"id": 2, "username": "admin", "role": "manager"}
    manager_reply = client.post(f"/api/community/threads/{ids['thread']}/posts", json={"content": "manager can still reply"})
    assert manager_reply.status_code == 200


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
