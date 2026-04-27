from datetime import datetime

from flask import request

from services.notifications import create_notification
from services.permissions import can_dm, require_member_action


DM_MESSAGE_MAX_LEN = 1000


def ensure_dm_schema(conn):
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS dm_threads (
            id                 INTEGER PRIMARY KEY AUTOINCREMENT,
            participant_a_id   INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            participant_b_id   INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            created_by_user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
            created_at         TEXT NOT NULL,
            updated_at         TEXT NOT NULL,
            UNIQUE(participant_a_id, participant_b_id)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS direct_messages (
            id                   INTEGER PRIMARY KEY AUTOINCREMENT,
            thread_id            INTEGER NOT NULL REFERENCES dm_threads(id) ON DELETE CASCADE,
            sender_user_id       INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            recipient_user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            body                 TEXT NOT NULL,
            is_read              INTEGER NOT NULL DEFAULT 0,
            read_at              TEXT,
            sender_deleted_at    TEXT,
            recipient_deleted_at TEXT,
            created_at           TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS blocked_users (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            blocker_user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            blocked_user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            reason          TEXT,
            created_at      TEXT NOT NULL,
            UNIQUE(blocker_user_id, blocked_user_id)
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_dm_threads_a ON dm_threads(participant_a_id, updated_at)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_dm_threads_b ON dm_threads(participant_b_id, updated_at)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_direct_messages_thread ON direct_messages(thread_id, created_at)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_direct_messages_unread ON direct_messages(recipient_user_id, is_read)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_blocked_users_pair ON blocked_users(blocker_user_id, blocked_user_id)")


def register_dm_routes(app, deps):
    audit = deps.get("audit", lambda *args, **kwargs: None)
    get_client_ip = deps["get_client_ip"]
    get_current_user_ctx = deps["get_current_user_ctx"]
    get_db = deps["get_db"]
    get_ua = deps.get("get_ua", lambda: "")
    json_resp = deps["json_resp"]
    normalize_text = deps["normalize_text"]
    parse_positive_int = deps["parse_positive_int"]
    require_csrf = deps["require_csrf"]
    require_csrf_safe = deps["require_csrf_safe"]

    def user_by_username(conn, username):
        return conn.execute(
            "SELECT id, username, role, status, member_level, base_level, effective_level FROM users WHERE username=?",
            (username,),
        ).fetchone()

    def user_by_id(conn, user_id):
        return conn.execute(
            "SELECT id, username, role, status, member_level, base_level, effective_level FROM users WHERE id=?",
            (user_id,),
        ).fetchone()

    def normalized_pair(a, b):
        a_id = int(a)
        b_id = int(b)
        return (a_id, b_id) if a_id < b_id else (b_id, a_id)

    def block_row(conn, blocker_id, blocked_id):
        return conn.execute(
            "SELECT id FROM blocked_users WHERE blocker_user_id=? AND blocked_user_id=?",
            (blocker_id, blocked_id),
        ).fetchone()

    def dm_block_state(conn, actor_id, target_id):
        if block_row(conn, actor_id, target_id):
            return "你已封鎖此使用者"
        if block_row(conn, target_id, actor_id):
            return "對方不接受你的私訊"
        return ""

    def thread_for_actor(conn, thread_id, actor_id):
        row = conn.execute("SELECT * FROM dm_threads WHERE id=?", (thread_id,)).fetchone()
        if not row:
            return None
        if int(row["participant_a_id"]) != int(actor_id) and int(row["participant_b_id"]) != int(actor_id):
            return None
        return row

    def other_user_id(thread, actor_id):
        return thread["participant_b_id"] if int(thread["participant_a_id"]) == int(actor_id) else thread["participant_a_id"]

    def serialize_message(row, actor_id):
        return {
            "id": row["id"],
            "thread_id": row["thread_id"],
            "sender_user_id": row["sender_user_id"],
            "recipient_user_id": row["recipient_user_id"],
            "body": row["body"],
            "is_read": bool(row["is_read"]),
            "read_at": row["read_at"],
            "created_at": row["created_at"],
            "is_self": int(row["sender_user_id"]) == int(actor_id),
        }

    def serialize_thread(conn, thread, actor_id):
        target_id = other_user_id(thread, actor_id)
        target = user_by_id(conn, target_id)
        last = conn.execute(
            """
            SELECT * FROM direct_messages
            WHERE thread_id=?
              AND ((sender_user_id=? AND sender_deleted_at IS NULL)
                OR (recipient_user_id=? AND recipient_deleted_at IS NULL))
            ORDER BY created_at DESC, id DESC
            LIMIT 1
            """,
            (thread["id"], actor_id, actor_id),
        ).fetchone()
        unread = conn.execute(
            "SELECT COUNT(*) AS c FROM direct_messages WHERE thread_id=? AND recipient_user_id=? AND is_read=0 AND recipient_deleted_at IS NULL",
            (thread["id"], actor_id),
        ).fetchone()["c"]
        return {
            "id": thread["id"],
            "other_user_id": target_id,
            "other_username": target["username"] if target else "unknown",
            "created_at": thread["created_at"],
            "updated_at": thread["updated_at"],
            "unread_count": unread,
            "last_message": serialize_message(last, actor_id) if last else None,
        }

    @app.route("/api/dm/threads", methods=["GET", "POST"])
    @require_csrf_safe
    def dm_threads():
        actor = get_current_user_ctx()
        if not actor:
            return json_resp({"ok": False, "msg": "未登入"}), 401
        conn = get_db()
        try:
            ensure_dm_schema(conn)
            if request.method == "GET":
                rows = conn.execute(
                    """
                    SELECT * FROM dm_threads
                    WHERE participant_a_id=? OR participant_b_id=?
                    ORDER BY updated_at DESC, id DESC
                    """,
                    (actor["id"], actor["id"]),
                ).fetchall()
                return json_resp({"ok": True, "threads": [serialize_thread(conn, row, actor["id"]) for row in rows]})

            data = request.get_json(force=True)
            if not isinstance(data, dict):
                return json_resp({"ok": False, "msg": "Invalid request"}), 400
            target_username = normalize_text(data.get("target_username"))
            if not target_username:
                return json_resp({"ok": False, "msg": "請提供收件人帳號"}), 400
            target = user_by_username(conn, target_username)
            if not target or target["status"] != "active":
                return json_resp({"ok": False, "msg": "找不到可私訊的使用者"}), 404
            if int(target["id"]) == int(actor["id"]):
                return json_resp({"ok": False, "msg": "不能私訊自己"}), 400
            if not can_dm(actor, target=target, conn=conn):
                return json_resp({"ok": False, "msg": "會員等級規則不允許私訊"}), 403
            blocked_msg = dm_block_state(conn, actor["id"], target["id"])
            if blocked_msg:
                return json_resp({"ok": False, "msg": blocked_msg}), 403
            a_id, b_id = normalized_pair(actor["id"], target["id"])
            now = datetime.now().isoformat()
            conn.execute(
                """
                INSERT OR IGNORE INTO dm_threads (
                    participant_a_id, participant_b_id, created_by_user_id, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (a_id, b_id, actor["id"], now, now),
            )
            thread = conn.execute(
                "SELECT * FROM dm_threads WHERE participant_a_id=? AND participant_b_id=?",
                (a_id, b_id),
            ).fetchone()
            conn.commit()
            return json_resp({"ok": True, "thread": serialize_thread(conn, thread, actor["id"])})
        finally:
            conn.close()

    @app.route("/api/dm/threads/<int:thread_id>/messages", methods=["GET", "POST"])
    @require_csrf_safe
    def dm_thread_messages(thread_id):
        actor = get_current_user_ctx()
        if not actor:
            return json_resp({"ok": False, "msg": "未登入"}), 401
        conn = get_db()
        try:
            ensure_dm_schema(conn)
            thread = thread_for_actor(conn, thread_id, actor["id"])
            if not thread:
                return json_resp({"ok": False, "msg": "找不到私訊串或權限不足"}), 404
            target_id = other_user_id(thread, actor["id"])
            target = user_by_id(conn, target_id)
            if request.method == "GET":
                limit = parse_positive_int(request.args.get("limit", 50), default=50, min_value=1, max_value=200)
                rows = conn.execute(
                    """
                    SELECT * FROM direct_messages
                    WHERE thread_id=?
                      AND ((sender_user_id=? AND sender_deleted_at IS NULL)
                        OR (recipient_user_id=? AND recipient_deleted_at IS NULL))
                    ORDER BY created_at ASC, id ASC
                    LIMIT ?
                    """,
                    (thread_id, actor["id"], actor["id"], limit),
                ).fetchall()
                return json_resp({"ok": True, "messages": [serialize_message(row, actor["id"]) for row in rows]})

            ok, msg, status = require_member_action(actor, "chat_dm_create", conn=conn, target=target)
            if not ok:
                return json_resp({"ok": False, "msg": msg}), status
            blocked_msg = dm_block_state(conn, actor["id"], target_id)
            if blocked_msg:
                return json_resp({"ok": False, "msg": blocked_msg}), 403
            data = request.get_json(force=True)
            if not isinstance(data, dict):
                return json_resp({"ok": False, "msg": "Invalid request"}), 400
            body = normalize_text(data.get("body"))[:DM_MESSAGE_MAX_LEN]
            if not body:
                return json_resp({"ok": False, "msg": "訊息不可為空"}), 400
            now = datetime.now().isoformat()
            cur = conn.execute(
                """
                INSERT INTO direct_messages (
                    thread_id, sender_user_id, recipient_user_id, body, is_read, created_at
                ) VALUES (?, ?, ?, ?, 0, ?)
                """,
                (thread_id, actor["id"], target_id, body, now),
            )
            conn.execute("UPDATE dm_threads SET updated_at=? WHERE id=?", (now, thread_id))
            create_notification(
                conn,
                user_id=target_id,
                type="dm_message",
                title="新的站內信",
                body=f"{actor['username']} 傳送了一則站內信。",
                link=f"/dm/{thread_id}",
            )
            conn.commit()
            audit("DM_MESSAGE_SENT", get_client_ip(), user=actor["username"], success=True, ua=get_ua(), detail=f"thread_id={thread_id}, message_id={cur.lastrowid}")
            row = conn.execute("SELECT * FROM direct_messages WHERE id=?", (cur.lastrowid,)).fetchone()
            return json_resp({"ok": True, "message": serialize_message(row, actor["id"])})
        finally:
            conn.close()

    @app.route("/api/dm/threads/<int:thread_id>/read", methods=["POST"])
    @require_csrf
    def dm_thread_read(thread_id):
        actor = get_current_user_ctx()
        if not actor:
            return json_resp({"ok": False, "msg": "未登入"}), 401
        conn = get_db()
        try:
            ensure_dm_schema(conn)
            thread = thread_for_actor(conn, thread_id, actor["id"])
            if not thread:
                return json_resp({"ok": False, "msg": "找不到私訊串或權限不足"}), 404
            now = datetime.now().isoformat()
            conn.execute(
                "UPDATE direct_messages SET is_read=1, read_at=? WHERE thread_id=? AND recipient_user_id=? AND is_read=0",
                (now, thread_id, actor["id"]),
            )
            conn.commit()
            return json_resp({"ok": True, "msg": "已標記為已讀"})
        finally:
            conn.close()

    @app.route("/api/dm/messages/<int:message_id>", methods=["DELETE"])
    @require_csrf
    def dm_message_delete(message_id):
        actor = get_current_user_ctx()
        if not actor:
            return json_resp({"ok": False, "msg": "未登入"}), 401
        conn = get_db()
        try:
            ensure_dm_schema(conn)
            row = conn.execute("SELECT * FROM direct_messages WHERE id=?", (message_id,)).fetchone()
            if not row:
                return json_resp({"ok": False, "msg": "找不到訊息"}), 404
            thread = thread_for_actor(conn, row["thread_id"], actor["id"])
            if not thread:
                return json_resp({"ok": False, "msg": "權限不足"}), 403
            now = datetime.now().isoformat()
            if int(row["sender_user_id"]) == int(actor["id"]):
                conn.execute("UPDATE direct_messages SET sender_deleted_at=? WHERE id=?", (now, message_id))
            elif int(row["recipient_user_id"]) == int(actor["id"]):
                conn.execute("UPDATE direct_messages SET recipient_deleted_at=? WHERE id=?", (now, message_id))
            else:
                return json_resp({"ok": False, "msg": "權限不足"}), 403
            conn.commit()
            return json_resp({"ok": True, "msg": "訊息已刪除"})
        finally:
            conn.close()

    @app.route("/api/dm/blocks", methods=["GET", "POST"])
    @require_csrf_safe
    def dm_blocks():
        actor = get_current_user_ctx()
        if not actor:
            return json_resp({"ok": False, "msg": "未登入"}), 401
        conn = get_db()
        try:
            ensure_dm_schema(conn)
            if request.method == "GET":
                rows = conn.execute(
                    """
                    SELECT b.id, b.blocked_user_id, b.reason, b.created_at, u.username AS blocked_username
                    FROM blocked_users b
                    LEFT JOIN users u ON u.id=b.blocked_user_id
                    WHERE b.blocker_user_id=?
                    ORDER BY b.created_at DESC
                    """,
                    (actor["id"],),
                ).fetchall()
                return json_resp({"ok": True, "blocks": [dict(row) for row in rows]})
            data = request.get_json(force=True)
            if not isinstance(data, dict):
                return json_resp({"ok": False, "msg": "Invalid request"}), 400
            target_username = normalize_text(data.get("target_username"))
            target = user_by_username(conn, target_username)
            if not target:
                return json_resp({"ok": False, "msg": "找不到使用者"}), 404
            if int(target["id"]) == int(actor["id"]):
                return json_resp({"ok": False, "msg": "不能封鎖自己"}), 400
            now = datetime.now().isoformat()
            conn.execute(
                "INSERT OR IGNORE INTO blocked_users (blocker_user_id, blocked_user_id, reason, created_at) VALUES (?, ?, ?, ?)",
                (actor["id"], target["id"], normalize_text(data.get("reason"))[:300] or None, now),
            )
            conn.commit()
            return json_resp({"ok": True, "msg": "已封鎖使用者"})
        finally:
            conn.close()

    @app.route("/api/dm/blocks/<int:blocked_user_id>", methods=["DELETE"])
    @require_csrf
    def dm_unblock(blocked_user_id):
        actor = get_current_user_ctx()
        if not actor:
            return json_resp({"ok": False, "msg": "未登入"}), 401
        conn = get_db()
        try:
            ensure_dm_schema(conn)
            conn.execute(
                "DELETE FROM blocked_users WHERE blocker_user_id=? AND blocked_user_id=?",
                (actor["id"], blocked_user_id),
            )
            conn.commit()
            return json_resp({"ok": True, "msg": "已解除封鎖"})
        finally:
            conn.close()
