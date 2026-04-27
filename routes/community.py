from datetime import datetime

from flask import request


def register_community_routes(app, deps):
    COMMUNITY_POST_AUTO_HIDE_DISLIKES = 3
    audit = deps["audit"]
    check_user_rate_limit = deps["check_user_rate_limit"]
    get_client_ip = deps["get_client_ip"]
    get_current_user_ctx = deps["get_current_user_ctx"]
    get_db = deps["get_db"]
    get_ua = deps["get_ua"]
    json_resp = deps["json_resp"]
    normalize_text = deps["normalize_text"]
    parse_positive_int = deps["parse_positive_int"]
    require_csrf = deps["require_csrf"]
    require_csrf_safe = deps["require_csrf_safe"]
    role_rank = deps["role_rank"]

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
            status           TEXT NOT NULL DEFAULT 'approved',
            review_note      TEXT,
            reviewed_by      TEXT,
            reviewed_at      TEXT,
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
            is_pinned        INTEGER NOT NULL DEFAULT 0,
            is_hidden        INTEGER NOT NULL DEFAULT 0,
            hidden_reason    TEXT,
            created_at       TEXT NOT NULL,
            updated_at       TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS forum_post_reactions (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            post_id        INTEGER NOT NULL REFERENCES forum_posts(id) ON DELETE CASCADE,
            user_id        INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            value          INTEGER NOT NULL,
            created_at     TEXT NOT NULL,
            updated_at     TEXT NOT NULL,
            UNIQUE(post_id, user_id)
        );

        CREATE TABLE IF NOT EXISTS forum_post_reports (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            post_id          INTEGER NOT NULL REFERENCES forum_posts(id) ON DELETE CASCADE,
            thread_id        INTEGER NOT NULL REFERENCES forum_threads(id) ON DELETE CASCADE,
            reporter_user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
            reported_user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            reason           TEXT NOT NULL,
            status           TEXT NOT NULL DEFAULT 'pending',
            reviewed_by      TEXT,
            reviewed_at      TEXT,
            review_note      TEXT,
            created_at       TEXT NOT NULL DEFAULT (datetime('now')),
            UNIQUE(post_id, reason)
        );

        CREATE INDEX IF NOT EXISTS idx_announcements_active ON announcements(is_active, created_at);
        CREATE INDEX IF NOT EXISTS idx_forum_boards_status ON forum_boards(status, created_at);
        CREATE INDEX IF NOT EXISTS idx_forum_threads_board ON forum_threads(board_id, created_at);
        CREATE INDEX IF NOT EXISTS idx_forum_posts_thread ON forum_posts(thread_id, created_at);
        CREATE INDEX IF NOT EXISTS idx_forum_posts_visible ON forum_posts(thread_id, is_hidden, is_pinned, created_at);
        CREATE INDEX IF NOT EXISTS idx_forum_post_reactions_post ON forum_post_reactions(post_id);
        CREATE INDEX IF NOT EXISTS idx_forum_post_reports_status ON forum_post_reports(status, created_at);
        """)
        cols = {row["name"] for row in conn.execute("PRAGMA table_info(announcements)").fetchall()}
        if "is_pinned" not in cols:
            conn.execute("ALTER TABLE announcements ADD COLUMN is_pinned INTEGER NOT NULL DEFAULT 0")
        cols = {row["name"] for row in conn.execute("PRAGMA table_info(forum_boards)").fetchall()}
        if "rules" not in cols:
            conn.execute("ALTER TABLE forum_boards ADD COLUMN rules TEXT")
        cols = {row["name"] for row in conn.execute("PRAGMA table_info(forum_threads)").fetchall()}
        if "status" not in cols:
            conn.execute("ALTER TABLE forum_threads ADD COLUMN status TEXT NOT NULL DEFAULT 'approved'")
        if "review_note" not in cols:
            conn.execute("ALTER TABLE forum_threads ADD COLUMN review_note TEXT")
        if "reviewed_by" not in cols:
            conn.execute("ALTER TABLE forum_threads ADD COLUMN reviewed_by TEXT")
        if "reviewed_at" not in cols:
            conn.execute("ALTER TABLE forum_threads ADD COLUMN reviewed_at TEXT")
        if "is_locked" not in cols:
            conn.execute("ALTER TABLE forum_threads ADD COLUMN is_locked INTEGER NOT NULL DEFAULT 0")
        cols = {row["name"] for row in conn.execute("PRAGMA table_info(forum_posts)").fetchall()}
        for name, ddl in (
            ("is_pinned", "INTEGER NOT NULL DEFAULT 0"),
            ("is_hidden", "INTEGER NOT NULL DEFAULT 0"),
            ("hidden_reason", "TEXT"),
        ):
            if name not in cols:
                conn.execute(f"ALTER TABLE forum_posts ADD COLUMN {name} {ddl}")

    def actor_role(actor):
        return "super_admin" if actor["username"] == "root" else actor["role"]

    def can_manage_community(actor):
        return role_rank(actor_role(actor)) >= role_rank("manager")

    def can_delete_community_content(actor, author_user_id=None, owner_user_id=None):
        if not actor:
            return False
        if can_manage_community(actor):
            return True
        return actor["id"] in (author_user_id, owner_user_id)

    def ensure_auto_hidden_post_report(conn, post_id, actor_id, dislike_count):
        post = conn.execute(
            "SELECT p.id, p.thread_id, p.author_user_id, p.author_username, p.content "
            "FROM forum_posts p WHERE p.id=?",
            (post_id,)
        ).fetchone()
        if not post:
            return
        reason = f"倒讚過多自動隱藏（{dislike_count}）"
        conn.execute(
            "INSERT OR IGNORE INTO forum_post_reports "
            "(post_id, thread_id, reporter_user_id, reported_user_id, reason, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (post_id, post["thread_id"], actor_id, post["author_user_id"], reason, datetime.now().isoformat())
        )

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

    def thread_payload(row):
        return {
            "id": row["id"],
            "board_id": row["board_id"],
            "title": row["title"],
            "content": row["content"],
            "status": row["status"],
            "review_note": row["review_note"],
            "reviewed_by": row["reviewed_by"],
            "reviewed_at": row["reviewed_at"],
            "is_locked": bool(row["is_locked"]),
            "author_user_id": row["author_user_id"],
            "author_username": row["author_username"],
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
            if not can_manage_community(actor):
                return json_resp({"ok": False, "msg": "目前只有管理員以上可建立討論版面"}), 403
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
                q = (normalize_text(request.args.get("q")) or "")[:120]
                page = parse_positive_int(request.args.get("page", 0), default=0, min_value=0)
                if page is None:
                    return json_resp({"ok": False, "msg": "page 參數格式錯誤"}), 400
                limit = parse_positive_int(request.args.get("limit", 10), default=10, min_value=1, max_value=20)
                if limit is None:
                    return json_resp({"ok": False, "msg": "limit 參數格式錯誤"}), 400
                like = f"%{q}%"
                where = "board_id=?"
                params = [board_id]
                if manageable:
                    status_filter = normalize_text(request.args.get("status")) or ""
                    if status_filter in ("pending", "approved", "rejected"):
                        where += " AND status=?"
                        params.append(status_filter)
                else:
                    where += " AND (status='approved' OR author_user_id=?)"
                    params.append(actor["id"])
                if q:
                    where += " AND (title LIKE ? OR content LIKE ? OR author_username LIKE ?)"
                    params.extend([like, like, like])
                total = conn.execute(
                    f"SELECT COUNT(*) AS c FROM forum_threads WHERE {where}",
                    tuple(params)
                ).fetchone()["c"]
                rows = conn.execute(
                    f"SELECT id, board_id, title, content, status, review_note, reviewed_by, reviewed_at, is_locked, "
                    f"author_user_id, author_username, created_at, updated_at "
                    f"FROM forum_threads WHERE {where} ORDER BY created_at DESC LIMIT ? OFFSET ?",
                    tuple(params + [limit, page * limit])
                ).fetchall()
                threads = []
                for row in rows:
                    reply_count = conn.execute(
                        "SELECT COUNT(*) AS c FROM forum_posts WHERE thread_id=?",
                        (row["id"],)
                    ).fetchone()["c"]
                    item = thread_payload(row)
                    item["reply_count"] = reply_count or 0
                    threads.append(item)
                return json_resp({
                    "ok": True,
                    "board": board_payload(board),
                    "threads": threads,
                    "total": total,
                    "page": page,
                    "limit": limit,
                    "query": q,
                    "can_post_directly": manageable,
                })

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
            blocked, info = check_user_rate_limit(actor["id"], "community_thread_create", max_req=5, window_sec=300)
            if blocked:
                return json_resp({"ok": False, "msg": f"發文太頻繁（{info['limit']} 次 / 5 分鐘）"}), 429
            now = datetime.now().isoformat()
            status = "approved" if manageable else "pending"
            conn.execute(
                "INSERT INTO forum_threads (board_id, title, content, status, author_user_id, author_username, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (board_id, title, content, status, actor["id"], actor["username"], now, now)
            )
            conn.commit()
            audit(
                "COMMUNITY_THREAD_CREATE",
                get_client_ip(),
                user=actor["username"],
                success=True,
                ua=get_ua(),
                detail=f"board_id={board_id}, title={title}, status={status}"
            )
            return json_resp({"ok": True, "msg": "主題已建立" if manageable else "主題已送審，待管理員核准後公開"})
        finally:
            conn.close()

    @app.route("/api/community/threads/reviews", methods=["GET"])
    @require_csrf_safe
    def community_thread_reviews():
        actor = get_current_user_ctx()
        if not actor:
            return json_resp({"ok": False, "msg": "未登入"}), 401
        if not can_manage_community(actor):
            return json_resp({"ok": False, "msg": "只有管理員以上可審核主題"}), 403

        conn = get_db()
        try:
            ensure_community_schema(conn)
            rows = conn.execute(
                "SELECT id, board_id, title, content, status, review_note, reviewed_by, reviewed_at, is_locked, "
                "author_user_id, author_username, created_at, updated_at "
                "FROM forum_threads WHERE status='pending' ORDER BY created_at ASC"
            ).fetchall()
            return json_resp({"ok": True, "items": [thread_payload(row) for row in rows]})
        finally:
            conn.close()

    @app.route("/api/community/threads/<int:thread_id>/review", methods=["POST"])
    @require_csrf
    def community_thread_review(thread_id):
        actor = get_current_user_ctx()
        if not actor:
            return json_resp({"ok": False, "msg": "未登入"}), 401
        if not can_manage_community(actor):
            return json_resp({"ok": False, "msg": "只有管理員以上可審核主題"}), 403

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
            row = conn.execute(
                "SELECT id, title, status FROM forum_threads WHERE id=?",
                (thread_id,)
            ).fetchone()
            if not row:
                return json_resp({"ok": False, "msg": "找不到主題"}), 404
            if row["status"] != "pending":
                return json_resp({"ok": False, "msg": "此主題已審核"}), 409
            new_status = "approved" if action == "approve" else "rejected"
            now = datetime.now().isoformat()
            conn.execute(
                "UPDATE forum_threads SET status=?, review_note=?, reviewed_by=?, reviewed_at=?, updated_at=? WHERE id=?",
                (new_status, note or None, actor["username"], now, now, thread_id)
            )
            conn.commit()
            audit(
                "COMMUNITY_THREAD_REVIEW",
                get_client_ip(),
                user=actor["username"],
                success=True,
                ua=get_ua(),
                detail=f"thread_id={thread_id}, action={new_status}"
            )
            return json_resp({"ok": True, "msg": "主題審核完成"})
        finally:
            conn.close()

    @app.route("/api/community/threads/<int:thread_id>", methods=["GET", "DELETE"])
    @require_csrf_safe
    def community_thread_detail(thread_id):
        actor = get_current_user_ctx()
        if not actor:
            return json_resp({"ok": False, "msg": "未登入"}), 401

        conn = get_db()
        try:
            ensure_community_schema(conn)
            thread = conn.execute(
                "SELECT t.id, t.board_id, t.title, t.content, t.status, t.review_note, t.reviewed_by, t.reviewed_at, "
                "t.author_user_id, t.author_username, t.created_at, t.updated_at, t.is_locked, "
                "b.status AS board_status, b.owner_user_id, b.owner_username, b.title AS board_title "
                "FROM forum_threads t JOIN forum_boards b ON b.id=t.board_id WHERE t.id=?",
                (thread_id,)
            ).fetchone()
            if not thread:
                return json_resp({"ok": False, "msg": "找不到主題"}), 404
            manageable = can_manage_community(actor)
            accessible = thread["board_status"] == "approved" or manageable or thread["owner_user_id"] == actor["id"]
            if not accessible:
                return json_resp({"ok": False, "msg": "權限不足"}), 403
            if thread["status"] != "approved" and not manageable and thread["author_user_id"] != actor["id"]:
                return json_resp({"ok": False, "msg": "此主題尚未公開"}), 403

            if request.method == "DELETE":
                if not can_delete_community_content(actor, thread["author_user_id"], thread["owner_user_id"]):
                    return json_resp({"ok": False, "msg": "你沒有刪除此主題的權限"}), 403
                conn.execute("DELETE FROM forum_threads WHERE id=?", (thread_id,))
                conn.commit()
                audit(
                    "COMMUNITY_THREAD_DELETE",
                    get_client_ip(),
                    user=actor["username"],
                    success=True,
                    ua=get_ua(),
                    detail=f"thread_id={thread_id}, title={thread['title']}"
                )
                return json_resp({"ok": True, "msg": "主題已刪除"})

            post_where = "p.thread_id=?"
            post_params = [thread_id]
            if not manageable:
                post_where += " AND p.is_hidden=0"
            posts = conn.execute(
                "SELECT p.id, p.content, p.author_user_id, p.author_username, p.is_pinned, p.is_hidden, p.hidden_reason, "
                "p.created_at, p.updated_at, "
                "COALESCE(SUM(CASE WHEN r.value=1 THEN 1 ELSE 0 END), 0) AS like_count, "
                "COALESCE(SUM(CASE WHEN r.value=-1 THEN 1 ELSE 0 END), 0) AS dislike_count, "
                "COALESCE(MAX(CASE WHEN r.user_id=? THEN r.value ELSE 0 END), 0) AS user_reaction "
                "FROM forum_posts p "
                "LEFT JOIN forum_post_reactions r ON r.post_id=p.id "
                f"WHERE {post_where} "
                "GROUP BY p.id "
                "ORDER BY p.is_pinned DESC, p.created_at ASC",
                tuple([actor["id"]] + post_params)
            ).fetchall()
            return json_resp({
                "ok": True,
                "thread": {
                    "id": thread["id"],
                    "board_id": thread["board_id"],
                    "board_title": thread["board_title"],
                    "title": thread["title"],
                    "content": thread["content"],
                    "status": thread["status"],
                    "review_note": thread["review_note"],
                    "reviewed_by": thread["reviewed_by"],
                    "reviewed_at": thread["reviewed_at"],
                    "is_locked": bool(thread["is_locked"]),
                    "author_user_id": thread["author_user_id"],
                    "author_username": thread["author_username"],
                    "created_at": thread["created_at"],
                    "updated_at": thread["updated_at"],
                    "board_status": thread["board_status"],
                },
                "posts": [{
                    "id": row["id"],
                    "content": row["content"],
                    "author_user_id": row["author_user_id"],
                    "author_username": row["author_username"],
                    "is_pinned": bool(row["is_pinned"]),
                    "is_hidden": bool(row["is_hidden"]),
                    "hidden_reason": row["hidden_reason"],
                    "like_count": row["like_count"],
                    "dislike_count": row["dislike_count"],
                    "user_reaction": row["user_reaction"],
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
        blocked, info = check_user_rate_limit(actor["id"], "community_thread_reply", max_req=10, window_sec=300)
        if blocked:
            return json_resp({"ok": False, "msg": f"留言太頻繁（{info['limit']} 次 / 5 分鐘）"}), 429

        conn = get_db()
        try:
            ensure_community_schema(conn)
            thread = conn.execute(
                "SELECT t.id, t.board_id, t.status, t.is_locked, b.status AS board_status FROM forum_threads t "
                "JOIN forum_boards b ON b.id=t.board_id WHERE t.id=?",
                (thread_id,)
            ).fetchone()
            if not thread:
                return json_resp({"ok": False, "msg": "找不到主題"}), 404
            if thread["board_status"] != "approved":
                return json_resp({"ok": False, "msg": "此討論區尚未開放留言"}), 403
            if thread["status"] != "approved":
                return json_resp({"ok": False, "msg": "此主題尚未公開留言"}), 403
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

    @app.route("/api/community/posts/<int:post_id>/reaction", methods=["POST"])
    @require_csrf
    def community_post_reaction(post_id):
        actor = get_current_user_ctx()
        if not actor:
            return json_resp({"ok": False, "msg": "未登入"}), 401
        try:
            data = request.get_json(force=True)
        except Exception:
            return json_resp({"ok": False, "msg": "Invalid JSON"}), 400
        value = data.get("value") if isinstance(data, dict) else None
        if value not in (-1, 0, 1):
            return json_resp({"ok": False, "msg": "反應值錯誤"}), 400

        conn = get_db()
        try:
            ensure_community_schema(conn)
            post = conn.execute(
                "SELECT p.id, p.thread_id, p.is_hidden, t.status AS thread_status, b.status AS board_status, b.owner_user_id "
                "FROM forum_posts p "
                "JOIN forum_threads t ON t.id=p.thread_id "
                "JOIN forum_boards b ON b.id=t.board_id "
                "WHERE p.id=?",
                (post_id,)
            ).fetchone()
            if not post:
                return json_resp({"ok": False, "msg": "找不到留言"}), 404
            manageable = can_manage_community(actor)
            accessible = post["board_status"] == "approved" or manageable or post["owner_user_id"] == actor["id"]
            if not accessible or (post["thread_status"] != "approved" and not manageable):
                return json_resp({"ok": False, "msg": "權限不足"}), 403
            if post["is_hidden"] and not manageable:
                return json_resp({"ok": False, "msg": "留言已隱藏"}), 403

            now = datetime.now().isoformat()
            if value == 0:
                conn.execute(
                    "DELETE FROM forum_post_reactions WHERE post_id=? AND user_id=?",
                    (post_id, actor["id"])
                )
            else:
                conn.execute(
                    "INSERT INTO forum_post_reactions (post_id, user_id, value, created_at, updated_at) "
                    "VALUES (?, ?, ?, ?, ?) "
                    "ON CONFLICT(post_id, user_id) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
                    (post_id, actor["id"], value, now, now)
                )

            counts = conn.execute(
                "SELECT "
                "COALESCE(SUM(CASE WHEN value=1 THEN 1 ELSE 0 END), 0) AS like_count, "
                "COALESCE(SUM(CASE WHEN value=-1 THEN 1 ELSE 0 END), 0) AS dislike_count "
                "FROM forum_post_reactions WHERE post_id=?",
                (post_id,)
            ).fetchone()
            like_count = counts["like_count"] or 0
            dislike_count = counts["dislike_count"] or 0
            auto_hidden = False
            if dislike_count >= COMMUNITY_POST_AUTO_HIDE_DISLIKES and not post["is_hidden"]:
                auto_hidden = True
                reason = f"倒讚過多自動隱藏（{dislike_count}）"
                conn.execute(
                    "UPDATE forum_posts SET is_hidden=1, hidden_reason=?, updated_at=? WHERE id=?",
                    (reason, now, post_id)
                )
                ensure_auto_hidden_post_report(conn, post_id, actor["id"], dislike_count)
            conn.commit()
            if auto_hidden:
                audit("COMMUNITY_POST_AUTO_HIDDEN", get_client_ip(), user="system", success=True, ua=get_ua(),
                      detail=f"post_id={post_id}, dislikes={dislike_count}")
            return json_resp({
                "ok": True,
                "msg": "已更新反應",
                "like_count": like_count,
                "dislike_count": dislike_count,
                "user_reaction": value,
                "auto_hidden": auto_hidden,
            })
        finally:
            conn.close()

    @app.route("/api/community/posts/<int:post_id>/pin", methods=["POST"])
    @require_csrf
    def community_pin_post(post_id):
        actor = get_current_user_ctx()
        if not actor:
            return json_resp({"ok": False, "msg": "未登入"}), 401
        if not can_manage_community(actor):
            return json_resp({"ok": False, "msg": "只有管理員以上可置頂留言"}), 403
        try:
            data = request.get_json(force=True)
        except Exception:
            return json_resp({"ok": False, "msg": "Invalid JSON"}), 400
        pinned = 1 if isinstance(data, dict) and bool(data.get("pinned")) else 0

        conn = get_db()
        try:
            ensure_community_schema(conn)
            post = conn.execute("SELECT id, thread_id FROM forum_posts WHERE id=?", (post_id,)).fetchone()
            if not post:
                return json_resp({"ok": False, "msg": "找不到留言"}), 404
            conn.execute(
                "UPDATE forum_posts SET is_pinned=?, updated_at=? WHERE id=?",
                (pinned, datetime.now().isoformat(), post_id)
            )
            conn.commit()
            audit("COMMUNITY_POST_PIN", get_client_ip(), user=actor["username"], success=True, ua=get_ua(),
                  detail=f"post_id={post_id}, pinned={pinned}")
            return json_resp({"ok": True, "msg": "留言已置頂" if pinned else "留言已取消置頂"})
        finally:
            conn.close()

    @app.route("/api/community/posts/<int:post_id>", methods=["DELETE"])
    @require_csrf
    def community_delete_post(post_id):
        actor = get_current_user_ctx()
        if not actor:
            return json_resp({"ok": False, "msg": "未登入"}), 401

        conn = get_db()
        try:
            ensure_community_schema(conn)
            post = conn.execute(
                "SELECT p.id, p.thread_id, p.author_user_id, p.author_username, t.author_user_id AS thread_author_user_id, "
                "b.owner_user_id, b.status AS board_status "
                "FROM forum_posts p "
                "JOIN forum_threads t ON t.id=p.thread_id "
                "JOIN forum_boards b ON b.id=t.board_id "
                "WHERE p.id=?",
                (post_id,)
            ).fetchone()
            if not post:
                return json_resp({"ok": False, "msg": "找不到留言"}), 404
            accessible = post["board_status"] == "approved" or can_manage_community(actor) or post["owner_user_id"] == actor["id"]
            if not accessible:
                return json_resp({"ok": False, "msg": "權限不足"}), 403
            if not can_delete_community_content(actor, post["author_user_id"], post["owner_user_id"]):
                return json_resp({"ok": False, "msg": "你沒有刪除此留言的權限"}), 403

            conn.execute("DELETE FROM forum_posts WHERE id=?", (post_id,))
            conn.commit()
            audit(
                "COMMUNITY_POST_DELETE",
                get_client_ip(),
                user=actor["username"],
                success=True,
                ua=get_ua(),
                detail=f"post_id={post_id}, thread_id={post['thread_id']}, author={post['author_username']}"
            )
            return json_resp({"ok": True, "msg": "留言已刪除"})
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
