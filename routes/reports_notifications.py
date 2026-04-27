from datetime import datetime

from flask import request

from services.notifications import (
    create_notification,
    ensure_notifications_schema,
    serialize_notification,
)
from services.permissions import require_member_action


REPORT_TARGET_TYPES = {"chat_message", "forum_post", "forum_thread", "user", "other"}
REPORT_STATUSES = {"pending", "approved", "rejected"}


def register_reports_notification_routes(app, deps):
    add_violation = deps.get("add_violation", lambda *args, **kwargs: ("noop", "ok", 0))
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
    role_rank = deps["role_rank"]

    def actor_role(actor):
        return "super_admin" if actor and actor.get("username") == "root" else (actor or {}).get("role", "user")

    def is_moderator(actor):
        return bool(actor) and role_rank(actor_role(actor)) >= role_rank("manager")

    def ensure_reports_schema(conn):
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS reports (
                id                   INTEGER PRIMARY KEY AUTOINCREMENT,
                target_type          TEXT NOT NULL,
                target_id            INTEGER,
                reporter_user_id     INTEGER REFERENCES users(id) ON DELETE SET NULL,
                reported_user_id     INTEGER REFERENCES users(id) ON DELETE SET NULL,
                reason               TEXT NOT NULL,
                status               TEXT NOT NULL DEFAULT 'pending',
                claimed_by_user_id   INTEGER REFERENCES users(id) ON DELETE SET NULL,
                claimed_by_username  TEXT,
                claimed_at           TEXT,
                reviewed_by          TEXT,
                reviewed_at          TEXT,
                review_note          TEXT,
                created_at           TEXT NOT NULL,
                updated_at           TEXT NOT NULL,
                UNIQUE(target_type, target_id, reporter_user_id, reason)
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_reports_status ON reports(status, created_at)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_reports_claimed ON reports(claimed_by_user_id, status)")
        ensure_notifications_schema(conn)

    def user_exists(conn, user_id):
        if not user_id:
            return None
        return conn.execute("SELECT id, username, role FROM users WHERE id=?", (int(user_id),)).fetchone()

    def resolve_reported_user(conn, target_type, target_id, fallback_user_id=None):
        if target_type == "user":
            return user_exists(conn, target_id)
        if target_type == "chat_message":
            has_table = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='chat_messages'").fetchone()
            if has_table:
                return conn.execute(
                    "SELECT u.id, u.username, u.role FROM chat_messages m JOIN users u ON u.id=m.sender_id WHERE m.id=?",
                    (target_id,),
                ).fetchone()
        if target_type == "forum_post":
            has_table = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='forum_posts'").fetchone()
            if has_table:
                return conn.execute(
                    "SELECT u.id, u.username, u.role FROM forum_posts p JOIN users u ON u.id=p.author_user_id WHERE p.id=?",
                    (target_id,),
                ).fetchone()
        if target_type == "forum_thread":
            has_table = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='forum_threads'").fetchone()
            if has_table:
                return conn.execute(
                    "SELECT u.id, u.username, u.role FROM forum_threads t JOIN users u ON u.id=t.author_user_id WHERE t.id=?",
                    (target_id,),
                ).fetchone()
        return user_exists(conn, fallback_user_id)

    def report_payload(row):
        return {
            "id": row["id"],
            "target_type": row["target_type"],
            "target_id": row["target_id"],
            "reporter_user_id": row["reporter_user_id"],
            "reported_user_id": row["reported_user_id"],
            "reason": row["reason"],
            "status": row["status"],
            "claimed_by_user_id": row["claimed_by_user_id"],
            "claimed_by_username": row["claimed_by_username"],
            "claimed_at": row["claimed_at"],
            "reviewed_by": row["reviewed_by"],
            "reviewed_at": row["reviewed_at"],
            "review_note": row["review_note"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    @app.route("/api/reports", methods=["POST"])
    @require_csrf
    def submit_report():
        actor = get_current_user_ctx()
        if not actor:
            return json_resp({"ok": False, "msg": "未登入"}), 401
        try:
            data = request.get_json(force=True)
        except Exception:
            return json_resp({"ok": False, "msg": "Invalid JSON"}), 400
        if not isinstance(data, dict):
            return json_resp({"ok": False, "msg": "Invalid request"}), 400
        target_type = normalize_text(data.get("target_type")) or ""
        if target_type not in REPORT_TARGET_TYPES:
            return json_resp({"ok": False, "msg": "檢舉目標類型錯誤"}), 400
        target_id = parse_positive_int(data.get("target_id"), default=None, min_value=1)
        if target_type != "other" and not target_id:
            return json_resp({"ok": False, "msg": "target_id 格式錯誤"}), 400
        reason = normalize_text(data.get("reason"))[:500]
        if not reason:
            return json_resp({"ok": False, "msg": "檢舉原因不可為空"}), 400

        conn = get_db()
        try:
            ensure_reports_schema(conn)
            ok, msg, status_code = require_member_action(actor, "report_create", conn=conn)
            if not ok:
                return json_resp({"ok": False, "msg": msg}), status_code
            reported = resolve_reported_user(conn, target_type, target_id, data.get("reported_user_id"))
            if reported and int(reported["id"]) == int(actor["id"]):
                return json_resp({"ok": False, "msg": "不能檢舉自己"}), 400
            now = datetime.now().isoformat()
            try:
                cur = conn.execute(
                    """
                    INSERT INTO reports (
                        target_type, target_id, reporter_user_id, reported_user_id,
                        reason, status, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, 'pending', ?, ?)
                    """,
                    (
                        target_type,
                        target_id,
                        actor["id"],
                        reported["id"] if reported else None,
                        reason,
                        now,
                        now,
                    ),
                )
            except Exception:
                return json_resp({"ok": False, "msg": "你已提交過相同檢舉"}), 409
            create_notification(
                conn,
                user_id=actor["id"],
                type="report_submitted",
                title="檢舉已送出",
                body="你的檢舉已進入待處理佇列。",
                link=f"/reports/{cur.lastrowid}",
            )
            conn.commit()
            audit("REPORT_SUBMITTED", get_client_ip(), user=actor["username"], success=True, ua=get_ua(), detail=f"report_id={cur.lastrowid}, target={target_type}:{target_id}")
            return json_resp({"ok": True, "msg": "檢舉已送出", "report_id": cur.lastrowid})
        finally:
            conn.close()

    @app.route("/api/admin/reports", methods=["GET"])
    @require_csrf_safe
    def admin_reports():
        actor = get_current_user_ctx()
        if not is_moderator(actor):
            return json_resp({"ok": False, "msg": "權限不足"}), 403
        status = normalize_text(request.args.get("status")) or "pending"
        if status not in REPORT_STATUSES:
            return json_resp({"ok": False, "msg": "狀態參數錯誤"}), 400
        page = parse_positive_int(request.args.get("page", 0), default=0, min_value=0)
        limit = parse_positive_int(request.args.get("limit", 30), default=30, min_value=1, max_value=100)
        conn = get_db()
        try:
            ensure_reports_schema(conn)
            total = conn.execute("SELECT COUNT(*) AS c FROM reports WHERE status=?", (status,)).fetchone()["c"]
            rows = conn.execute(
                "SELECT * FROM reports WHERE status=? ORDER BY created_at DESC LIMIT ? OFFSET ?",
                (status, limit, page * limit),
            ).fetchall()
            return json_resp({"ok": True, "reports": [report_payload(row) for row in rows], "total": total, "page": page, "limit": limit})
        finally:
            conn.close()

    @app.route("/api/admin/reports/<int:report_id>/claim", methods=["POST"])
    @require_csrf
    def admin_claim_report(report_id):
        actor = get_current_user_ctx()
        if not is_moderator(actor):
            return json_resp({"ok": False, "msg": "權限不足"}), 403
        conn = get_db()
        try:
            ensure_reports_schema(conn)
            row = conn.execute("SELECT * FROM reports WHERE id=?", (report_id,)).fetchone()
            if not row:
                return json_resp({"ok": False, "msg": "找不到檢舉"}), 404
            if row["status"] != "pending":
                return json_resp({"ok": False, "msg": "此檢舉已結案"}), 409
            if row["claimed_by_user_id"] and int(row["claimed_by_user_id"]) != int(actor["id"]):
                return json_resp({"ok": False, "msg": "此檢舉已被其他管理員領取"}), 409
            now = datetime.now().isoformat()
            conn.execute(
                "UPDATE reports SET claimed_by_user_id=?, claimed_by_username=?, claimed_at=?, updated_at=? WHERE id=?",
                (actor["id"], actor["username"], now, now, report_id),
            )
            conn.commit()
            audit("REPORT_CLAIMED", get_client_ip(), user=actor["username"], success=True, ua=get_ua(), detail=f"report_id={report_id}")
            return json_resp({"ok": True, "msg": "檢舉已領取"})
        finally:
            conn.close()

    @app.route("/api/admin/reports/<int:report_id>/resolve", methods=["POST"])
    @require_csrf
    def admin_resolve_report(report_id):
        actor = get_current_user_ctx()
        if not is_moderator(actor):
            return json_resp({"ok": False, "msg": "權限不足"}), 403
        try:
            data = request.get_json(force=True)
        except Exception:
            return json_resp({"ok": False, "msg": "Invalid JSON"}), 400
        action = normalize_text(data.get("action"))
        note = normalize_text(data.get("note"))[:500]
        if action not in {"approve", "reject"}:
            return json_resp({"ok": False, "msg": "處理動作錯誤"}), 400
        conn = get_db()
        try:
            ensure_reports_schema(conn)
            row = conn.execute("SELECT * FROM reports WHERE id=?", (report_id,)).fetchone()
            if not row:
                return json_resp({"ok": False, "msg": "找不到檢舉"}), 404
            if row["status"] != "pending":
                return json_resp({"ok": False, "msg": "此檢舉已結案"}), 409
            if row["claimed_by_user_id"] and int(row["claimed_by_user_id"]) != int(actor["id"]):
                return json_resp({"ok": False, "msg": "只有領取此檢舉的管理員可結案"}), 409
            final_status = "approved" if action == "approve" else "rejected"
            now = datetime.now().isoformat()
            msg = "檢舉已駁回"
            if action == "approve" and row["reported_user_id"]:
                reported = user_exists(conn, row["reported_user_id"])
                if reported:
                    role = "super_admin" if reported["username"] == "root" else (reported["role"] or "user")
                    _, msg, _ = add_violation(
                        reported["id"],
                        reported["username"],
                        role,
                        points=1,
                        reason=f"檢舉成立：{row['reason']}",
                        triggered_by="report",
                        actor_username=actor["username"],
                    )
            conn.execute(
                "UPDATE reports SET status=?, reviewed_by=?, reviewed_at=?, review_note=?, updated_at=? WHERE id=?",
                (final_status, actor["username"], now, note or None, now, report_id),
            )
            if row["reporter_user_id"]:
                create_notification(
                    conn,
                    user_id=row["reporter_user_id"],
                    type="report_resolved",
                    title="檢舉已處理",
                    body=f"你的檢舉已被標記為 {final_status}。",
                    link=f"/reports/{report_id}",
                )
            if final_status == "approved" and row["reported_user_id"]:
                create_notification(
                    conn,
                    user_id=row["reported_user_id"],
                    type="report_approved",
                    title="檢舉成立",
                    body="你被檢舉的內容已由管理員判定成立。",
                    link=f"/reports/{report_id}",
                )
            conn.commit()
            audit("REPORT_RESOLVED", get_client_ip(), user=actor["username"], success=True, ua=get_ua(), detail=f"report_id={report_id}, action={action}")
            return json_resp({"ok": True, "msg": msg})
        finally:
            conn.close()

    @app.route("/api/notifications", methods=["GET"])
    @require_csrf_safe
    def notifications_list():
        actor = get_current_user_ctx()
        if not actor:
            return json_resp({"ok": False, "msg": "未登入"}), 401
        unread_only = request.args.get("unread") in {"1", "true", "yes"}
        limit = parse_positive_int(request.args.get("limit", 30), default=30, min_value=1, max_value=100)
        conn = get_db()
        try:
            ensure_notifications_schema(conn)
            where = "user_id=?"
            params = [actor["id"]]
            if unread_only:
                where += " AND is_read=0"
            rows = conn.execute(
                f"SELECT * FROM notifications WHERE {where} ORDER BY created_at DESC LIMIT ?",
                tuple(params + [limit]),
            ).fetchall()
            unread_count = conn.execute("SELECT COUNT(*) AS c FROM notifications WHERE user_id=? AND is_read=0", (actor["id"],)).fetchone()["c"]
            return json_resp({"ok": True, "notifications": [serialize_notification(row) for row in rows], "unread_count": unread_count})
        finally:
            conn.close()

    @app.route("/api/notifications/<int:notification_id>/read", methods=["POST"])
    @require_csrf
    def notification_mark_read(notification_id):
        actor = get_current_user_ctx()
        if not actor:
            return json_resp({"ok": False, "msg": "未登入"}), 401
        conn = get_db()
        try:
            ensure_notifications_schema(conn)
            row = conn.execute("SELECT id FROM notifications WHERE id=? AND user_id=?", (notification_id, actor["id"])).fetchone()
            if not row:
                return json_resp({"ok": False, "msg": "找不到通知"}), 404
            conn.execute("UPDATE notifications SET is_read=1, read_at=? WHERE id=? AND user_id=?", (datetime.now().isoformat(), notification_id, actor["id"]))
            conn.commit()
            return json_resp({"ok": True, "msg": "通知已讀"})
        finally:
            conn.close()

    @app.route("/api/notifications/read-all", methods=["POST"])
    @require_csrf
    def notifications_read_all():
        actor = get_current_user_ctx()
        if not actor:
            return json_resp({"ok": False, "msg": "未登入"}), 401
        conn = get_db()
        try:
            ensure_notifications_schema(conn)
            conn.execute("UPDATE notifications SET is_read=1, read_at=? WHERE user_id=? AND is_read=0", (datetime.now().isoformat(), actor["id"]))
            conn.commit()
            return json_resp({"ok": True, "msg": "所有通知已讀"})
        finally:
            conn.close()
