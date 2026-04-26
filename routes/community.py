from datetime import datetime

from flask import request


def register_community_routes(app, deps):
    globals().update(deps)

    def ensure_community_schema(conn):
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS announcements (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            title            TEXT NOT NULL,
            content          TEXT NOT NULL,
            author_user_id   INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            author_username  TEXT NOT NULL,
            is_pinned        INTEGER NOT NULL DEFAULT 0,
            is_active        INTEGER NOT NULL DEFAULT 1,
            created_at       TEXT NOT NULL,
            updated_at       TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS forum_boards (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            title            TEXT NOT NULL,
            description      TEXT NOT NULL,
            rules            TEXT,
            owner_user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            owner_username   TEXT NOT NULL,
            status           TEXT NOT NULL DEFAULT 'pending',
            review_note      TEXT,
            reviewed_by      TEXT,
            reviewed_at      TEXT,
            created_at       TEXT NOT NULL,
            updated_at       TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS forum_threads (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            board_id         INTEGER NOT NULL REFERENCES forum_boards(id) ON DELETE CASCADE,
            title            TEXT NOT NULL,
            content          TEXT NOT NULL,
            is_locked        INTEGER NOT NULL DEFAULT 0,
            author_user_id   INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            author_username  TEXT NOT NULL,
            created_at       TEXT NOT NULL,
            updated_at       TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS forum_posts (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            thread_id        INTEGER NOT NULL REFERENCES forum_threads(id) ON DELETE CASCADE,
            content          TEXT NOT NULL,
            author_user_id   INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            author_username  TEXT NOT NULL,
            created_at       TEXT NOT NULL,
            updated_at       TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_announcements_active ON announcements(is_active, created_at);
        CREATE INDEX IF NOT EXISTS idx_forum_boards_status ON forum_boards(status, created_at);
        CREATE INDEX IF NOT EXISTS idx_forum_threads_board ON forum_threads(board_id, created_at);
        CREATE INDEX IF NOT EXISTS idx_forum_posts_thread ON forum_posts(thread_id, created_at);
        """)
        cols = {row["name"] for row in conn.execute("PRAGMA table_info(announcements)").fetchall()}
        if "is_pinned" not in cols:
            conn.execute("ALTER TABLE announcements ADD COLUMN is_pinned INTEGER NOT NULL DEFAULT 0")
        cols = {row["name"] for row in conn.execute("PRAGMA table_info(forum_boards)").fetchall()}
        if "rules" not in cols:
            conn.execute("ALTER TABLE forum_boards ADD COLUMN rules TEXT")
        cols = {row["name"] for row in conn.execute("PRAGMA table_info(forum_threads)").fetchall()}
        if "is_locked" not in cols:
            conn.execute("ALTER TABLE forum_threads ADD COLUMN is_locked INTEGER NOT NULL DEFAULT 0")

    def actor_role(actor):
        return "super_admin" if actor["username"] == "root" else actor["role"]

    def can_manage_community(actor):
        return role_rank(actor_role(actor)) >= role_rank("manager")

    def board_payload(row):
        return {
            "id": row["id"],
            "title": row["title"],
            "description": row["description"],
            "rules": row["rules"] or "",
            "owner_user_id": row["owner_user_id"],
            "owner_username": row["owner_username"],
            "status": row["status"],
            "review_note": row["review_note"],
            "reviewed_by": row["reviewed_by"],
            "reviewed_at": row["reviewed_at"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    @app.route("/api/community/announcements", methods=["GET", "POST"])
    @require_csrf_safe
    def community_announcements():
        actor = get_current_user_ctx()
        if not actor:
            return json_resp({"ok": False, "msg": "未登入"}), 401

        conn = get_db()
        try:
            ensure_community_schema(conn)
            if request.method == "GET":
                rows = conn.execute(
                    "SELECT id, title, content, author_username, is_pinned, created_at, updated_at "
                    "FROM announcements WHERE is_active=1 ORDER BY is_pinned DESC, created_at DESC LIMIT 30"
                ).fetchall()
                return json_resp({
                    "ok": True,
                    "announcements": [{
                        "id": row["id"],
                        "title": row["title"],
                        "content": row["content"],
                        "author_username": row["author_username"],
                        "is_pinned": bool(row["is_pinned"]),
                        "created_at": row["created_at"],
                        "updated_at": row["updated_at"],
                    } for row in rows],
                    "can_publish": can_manage_community(actor),
                })

            if not can_manage_community(actor):
                return json_resp({"ok": False, "msg": "只有管理員以上可發布公告"}), 403

            try:
                data = request.get_json(force=True)
            except Exception:
                return json_resp({"ok": False, "msg": "Invalid JSON"}), 400
            title = normalize_text(data.get("title"))[:80]
            content = normalize_text(data.get("content"))[:3000]
            is_pinned = 1 if bool(data.get("is_pinned")) else 0
            if not title or not content:
                return json_resp({"ok": False, "msg": "公告標題與內容不可為空"}), 400
            now = datetime.now().isoformat()
            conn.execute(
                "INSERT INTO announcements (title, content, author_user_id, author_username, is_pinned, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (title, content, actor["id"], actor["username"], is_pinned, now, now)
            )
            conn.commit()
            audit("COMMUNITY_ANNOUNCEMENT_CREATE", get_client_ip(), user=actor["username"], success=True, ua=get_ua(), detail=title)
            return json_resp({"ok": True, "msg": "公告已發布"})
        finally:
            conn.close()

    @app.route("/api/community/announcements/<int:announcement_id>", methods=["DELETE"])
    @require_csrf
    def community_delete_announcement(announcement_id):
        actor = get_current_user_ctx()
        if not actor:
            return json_resp({"ok": False, "msg": "未登入"}), 401
        if not can_manage_community(actor):
            return json_resp({"ok": False, "msg": "只有管理員以上可刪除公告"}), 403

        conn = get_db()
        try:
            ensure_community_schema(conn)
            row = conn.execute("SELECT id, title FROM announcements WHERE id=? AND is_active=1", (announcement_id,)).fetchone()
            if not row:
                return json_resp({"ok": False, "msg": "找不到公告"}), 404
            conn.execute(
                "UPDATE announcements SET is_active=0, updated_at=? WHERE id=?",
                (datetime.now().isoformat(), announcement_id)
            )
            conn.commit()
            audit("COMMUNITY_ANNOUNCEMENT_DELETE", get_client_ip(), user=actor["username"], success=True, ua=get_ua(), detail=row["title"])
            return json_resp({"ok": True, "msg": "公告已刪除"})
        finally:
            conn.close()

    @app.route("/api/community/boards", methods=["GET", "POST"])
    @require_csrf_safe
    def community_boards():
        actor = get_current_user_ctx()
        if not actor:
            return json_resp({"ok": False, "msg": "未登入"}), 401

        conn = get_db()
        try:
            ensure_community_schema(conn)
            if request.method == "GET":
                if can_manage_community(actor):
                    rows = conn.execute("SELECT * FROM forum_boards ORDER BY created_at DESC").fetchall()
                else:
                    rows = conn.execute(
                        "SELECT * FROM forum_boards WHERE status='approved' OR owner_user_id=? ORDER BY "
                        "CASE status WHEN 'approved' THEN 0 WHEN 'pending' THEN 1 ELSE 2 END, created_at DESC",
                        (actor["id"],)
                    ).fetchall()
                boards = []
                for row in rows:
                    payload = board_payload(row)
                    counts = conn.execute(
                        "SELECT "
                        "(SELECT COUNT(*) FROM forum_threads WHERE board_id=?) AS thread_count, "
                        "(SELECT COUNT(*) FROM forum_posts WHERE thread_id IN (SELECT id FROM forum_threads WHERE board_id=?)) AS post_count",
                        (row["id"], row["id"])
                    ).fetchone()
                    payload["thread_count"] = counts["thread_count"] or 0
                    payload["post_count"] = counts["post_count"] or 0
                    boards.append(payload)
                return json_resp({"ok": True, "boards": boards, "can_review": can_manage_community(actor)})

            try:
                data = request.get_json(force=True)
            except Exception:
                return json_resp({"ok": False, "msg": "Invalid JSON"}), 400
            title = normalize_text(data.get("title"))[:80]
            description = normalize_text(data.get("description"))[:1200]
            rules = normalize_text(data.get("rules"))[:2000]
            if not title or not description:
                return json_resp({"ok": False, "msg": "討論區名稱與說明不可為空"}), 400
            existing = conn.execute(
                "SELECT 1 FROM forum_boards WHERE owner_user_id=? AND status='pending'",
                (actor["id"],)
            ).fetchone()
            if existing:
                return json_resp({"ok": False, "msg": "你已有待審核的討論區申請"}), 409
            now = datetime.now().isoformat()
            conn.execute(
                "INSERT INTO forum_boards (title, description, rules, owner_user_id, owner_username, status, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, 'pending', ?, ?)",
                (title, description, rules, actor["id"], actor["username"], now, now)
            )
            conn.commit()
            audit("COMMUNITY_BOARD_REQUEST", get_client_ip(), user=actor["username"], success=True, ua=get_ua(), detail=title)
            return json_resp({"ok": True, "msg": "討論區申請已送出，待管理員審核"})
        finally:
            conn.close()

    @app.route("/api/community/boards/reviews", methods=["GET"])
    @require_csrf_safe
    def community_board_reviews():
        actor = get_current_user_ctx()
        if not actor:
            return json_resp({"ok": False, "msg": "未登入"}), 401
        if not can_manage_community(actor):
            return json_resp({"ok": False, "msg": "權限不足"}), 403

        conn = get_db()
        try:
            ensure_community_schema(conn)
            rows = conn.execute(
                "SELECT * FROM forum_boards WHERE status='pending' ORDER BY created_at ASC"
            ).fetchall()
            return json_resp({"ok": True, "items": [board_payload(row) for row in rows]})
        finally:
            conn.close()

    @app.route("/api/community/boards/<int:board_id>/review", methods=["POST"])
    @require_csrf
    def community_board_review(board_id):
        actor = get_current_user_ctx()
        if not actor:
            return json_resp({"ok": False, "msg": "未登入"}), 401
        if not can_manage_community(actor):
            return json_resp({"ok": False, "msg": "只有管理員以上可審核討論區"}), 403

        try:
            data = request.get_json(force=True)
        except Exception:
            return json_resp({"ok": False, "msg": "Invalid JSON"}), 400
        action = normalize_text(data.get("action"))
        note = normalize_text(data.get("note"))[:200]
        if action not in ("approve", "reject"):
            return json_resp({"ok": False, "msg": "審核動作錯誤"}), 400

        conn = get_db()
        try:
            ensure_community_schema(conn)
            row = conn.execute("SELECT * FROM forum_boards WHERE id=?", (board_id,)).fetchone()
            if not row:
                return json_resp({"ok": False, "msg": "找不到討論區申請"}), 404
            if row["status"] != "pending":
                return json_resp({"ok": False, "msg": "此討論區已審核"}), 409
            new_status = "approved" if action == "approve" else "rejected"
            now = datetime.now().isoformat()
            conn.execute(
                "UPDATE forum_boards SET status=?, review_note=?, reviewed_by=?, reviewed_at=?, updated_at=? WHERE id=?",
                (new_status, note or None, actor["username"], now, now, board_id)
            )
            conn.commit()
            audit("COMMUNITY_BOARD_REVIEW", get_client_ip(), user=actor["username"], success=True, ua=get_ua(),
                  detail=f"board_id={board_id}, action={new_status}")
            return json_resp({"ok": True, "msg": "討論區審核完成"})
        finally:
            conn.close()

    @app.route("/api/community/boards/<int:board_id>/threads", methods=["GET", "POST"])
    @require_csrf_safe
    def community_threads(board_id):
        actor = get_current_user_ctx()
        if not actor:
            return json_resp({"ok": False, "msg": "未登入"}), 401

        conn = get_db()
        try:
            ensure_community_schema(conn)
            board = conn.execute("SELECT * FROM forum_boards WHERE id=?", (board_id,)).fetchone()
            if not board:
                return json_resp({"ok": False, "msg": "找不到討論區"}), 404
            manageable = can_manage_community(actor)
            accessible = board["status"] == "approved" or manageable or board["owner_user_id"] == actor["id"]
            if not accessible:
                return json_resp({"ok": False, "msg": "權限不足"}), 403

            if request.method == "GET":
                q = normalize_text(request.args.get("q"))[:120]
                page = max(0, int(request.args.get("page", 0) or 0))
                limit = min(20, max(1, int(request.args.get("limit", 10) or 10)))
                like = f"%{q}%"
                where = "board_id=?"
                params = [board_id]
                if q:
                    where += " AND (title LIKE ? OR content LIKE ? OR author_username LIKE ?)"
                    params.extend([like, like, like])
                total = conn.execute(
                    f"SELECT COUNT(*) AS c FROM forum_threads WHERE {where}",
                    tuple(params)
                ).fetchone()["c"]
                rows = conn.execute(
                    f"SELECT id, title, content, is_locked, author_username, created_at, updated_at "
                    f"FROM forum_threads WHERE {where} ORDER BY created_at DESC LIMIT ? OFFSET ?",
                    tuple(params + [limit, page * limit])
                ).fetchall()
                threads = []
                for row in rows:
                    reply_count = conn.execute(
                        "SELECT COUNT(*) AS c FROM forum_posts WHERE thread_id=?",
                        (row["id"],)
                    ).fetchone()["c"]
                    threads.append({
                        "id": row["id"],
                        "title": row["title"],
                        "content": row["content"],
                        "is_locked": bool(row["is_locked"]),
                        "author_username": row["author_username"],
                        "created_at": row["created_at"],
                        "updated_at": row["updated_at"],
                        "reply_count": reply_count or 0,
                    })
                return json_resp({"ok": True, "board": board_payload(board), "threads": threads, "total": total, "page": page, "limit": limit, "query": q})

            if board["status"] != "approved":
                return json_resp({"ok": False, "msg": "討論區尚未開放"}), 403
            try:
                data = request.get_json(force=True)
            except Exception:
                return json_resp({"ok": False, "msg": "Invalid JSON"}), 400
            title = normalize_text(data.get("title"))[:120]
            content = normalize_text(data.get("content"))[:4000]
            if not title or not content:
                return json_resp({"ok": False, "msg": "主題標題與內容不可為空"}), 400
            now = datetime.now().isoformat()
            conn.execute(
                "INSERT INTO forum_threads (board_id, title, content, author_user_id, author_username, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (board_id, title, content, actor["id"], actor["username"], now, now)
            )
            conn.commit()
            audit("COMMUNITY_THREAD_CREATE", get_client_ip(), user=actor["username"], success=True, ua=get_ua(), detail=f"board_id={board_id}, title={title}")
            return json_resp({"ok": True, "msg": "主題已建立"})
        finally:
            conn.close()

    @app.route("/api/community/threads/<int:thread_id>", methods=["GET"])
    @require_csrf_safe
    def community_thread_detail(thread_id):
        actor = get_current_user_ctx()
        if not actor:
            return json_resp({"ok": False, "msg": "未登入"}), 401

        conn = get_db()
        try:
            ensure_community_schema(conn)
            thread = conn.execute(
                "SELECT t.id, t.board_id, t.title, t.content, t.author_username, t.created_at, t.updated_at, "
                "t.is_locked, b.status AS board_status, b.owner_user_id, b.owner_username, b.title AS board_title "
                "FROM forum_threads t JOIN forum_boards b ON b.id=t.board_id WHERE t.id=?",
                (thread_id,)
            ).fetchone()
            if not thread:
                return json_resp({"ok": False, "msg": "找不到主題"}), 404
            manageable = can_manage_community(actor)
            accessible = thread["board_status"] == "approved" or manageable or thread["owner_user_id"] == actor["id"]
            if not accessible:
                return json_resp({"ok": False, "msg": "權限不足"}), 403
            posts = conn.execute(
                "SELECT id, content, author_username, created_at, updated_at FROM forum_posts WHERE thread_id=? ORDER BY created_at ASC",
                (thread_id,)
            ).fetchall()
            return json_resp({
                "ok": True,
                "thread": {
                    "id": thread["id"],
                    "board_id": thread["board_id"],
                    "board_title": thread["board_title"],
                    "title": thread["title"],
                    "content": thread["content"],
                    "is_locked": bool(thread["is_locked"]),
                    "author_username": thread["author_username"],
                    "created_at": thread["created_at"],
                    "updated_at": thread["updated_at"],
                    "board_status": thread["board_status"],
                },
                "posts": [{
                    "id": row["id"],
                    "content": row["content"],
                    "author_username": row["author_username"],
                    "created_at": row["created_at"],
                    "updated_at": row["updated_at"],
                } for row in posts]
            })
        finally:
            conn.close()

    @app.route("/api/community/threads/<int:thread_id>/posts", methods=["POST"])
    @require_csrf
    def community_thread_reply(thread_id):
        actor = get_current_user_ctx()
        if not actor:
            return json_resp({"ok": False, "msg": "未登入"}), 401

        try:
            data = request.get_json(force=True)
        except Exception:
            return json_resp({"ok": False, "msg": "Invalid JSON"}), 400
        content = normalize_text(data.get("content"))[:3000]
        if not content:
            return json_resp({"ok": False, "msg": "留言內容不可為空"}), 400

        conn = get_db()
        try:
            ensure_community_schema(conn)
            thread = conn.execute(
                "SELECT t.id, t.board_id, t.is_locked, b.status AS board_status FROM forum_threads t "
                "JOIN forum_boards b ON b.id=t.board_id WHERE t.id=?",
                (thread_id,)
            ).fetchone()
            if not thread:
                return json_resp({"ok": False, "msg": "找不到主題"}), 404
            if thread["board_status"] != "approved":
                return json_resp({"ok": False, "msg": "此討論區尚未開放留言"}), 403
            if bool(thread["is_locked"]):
                return json_resp({"ok": False, "msg": "此主題已鎖定，暫停留言"}), 403
            now = datetime.now().isoformat()
            conn.execute(
                "INSERT INTO forum_posts (thread_id, content, author_user_id, author_username, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (thread_id, content, actor["id"], actor["username"], now, now)
            )
            conn.commit()
            audit("COMMUNITY_THREAD_REPLY", get_client_ip(), user=actor["username"], success=True, ua=get_ua(), detail=f"thread_id={thread_id}")
            return json_resp({"ok": True, "msg": "留言已送出"})
        finally:
            conn.close()

    @app.route("/api/community/threads/<int:thread_id>/lock", methods=["POST"])
    @require_csrf
    def community_thread_lock(thread_id):
        actor = get_current_user_ctx()
        if not actor:
            return json_resp({"ok": False, "msg": "未登入"}), 401
        if not can_manage_community(actor):
            return json_resp({"ok": False, "msg": "只有管理員以上可鎖定主題"}), 403
        try:
            data = request.get_json(force=True)
        except Exception:
            return json_resp({"ok": False, "msg": "Invalid JSON"}), 400
        locked = 1 if bool(data.get("locked")) else 0
        conn = get_db()
        try:
            ensure_community_schema(conn)
            thread = conn.execute("SELECT id, title FROM forum_threads WHERE id=?", (thread_id,)).fetchone()
            if not thread:
                return json_resp({"ok": False, "msg": "找不到主題"}), 404
            conn.execute(
                "UPDATE forum_threads SET is_locked=?, updated_at=? WHERE id=?",
                (locked, datetime.now().isoformat(), thread_id)
            )
            conn.commit()
            audit("COMMUNITY_THREAD_LOCK", get_client_ip(), user=actor["username"], success=True, ua=get_ua(),
                  detail=f"thread_id={thread_id}, locked={locked}")
            return json_resp({"ok": True, "msg": "主題狀態已更新"})
        finally:
            conn.close()
