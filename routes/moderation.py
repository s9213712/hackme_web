import json
import os
import threading
import time
from datetime import datetime
from flask import request

_VIOLATION_INTEGRITY_CACHE = {
    "head_id": None,
    "checked_at": 0.0,
    "payload": None,
}
_VIOLATION_INTEGRITY_CACHE_LOCK = threading.Lock()


def register_moderation_routes(app, deps):
    AUDIT_LOG_PATH = deps["AUDIT_LOG_PATH"]
    activate_emergency_lockdown = deps["activate_emergency_lockdown"]
    add_violation = deps["add_violation"]
    audit = deps["audit"]
    get_client_ip = deps["get_client_ip"]
    get_current_user_ctx = deps["get_current_user_ctx"]
    get_db = deps["get_db"]
    is_audit_chain_enabled = deps["is_audit_chain_enabled"]
    json_resp = deps["json_resp"]
    normalize_text = deps["normalize_text"]
    parse_positive_int = deps["parse_positive_int"]
    require_csrf = deps["require_csrf"]
    require_csrf_safe = deps["require_csrf_safe"]
    role_rank = deps["role_rank"]
    secure_add_violation = deps["secure_add_violation"]
    verify_audit_integrity = deps["verify_audit_integrity"]
    verify_violation_integrity = deps["verify_violation_integrity"]

    def ensure_community_report_schema(conn):
        post_table = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='forum_posts' LIMIT 1"
        ).fetchone()
        thread_table = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='forum_threads' LIMIT 1"
        ).fetchone()
        if not post_table or not thread_table:
            return False
        conn.execute(
            """
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
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_forum_post_reports_status ON forum_post_reports(status, created_at)")
        return True

    # ── 查詢所有違規記錄（可驗證 integrity）──────────────────────────────────────
    @app.route("/api/admin/violations", methods=["GET"])
    @require_csrf_safe
    def admin_violations():
        """列出所有用戶的最新違規狀態 + integrity 驗證結果"""
        actor = get_current_user_ctx()
        if not actor:
            return json_resp({"ok":False,"msg":"未登入"}), 401
        actor_role = "super_admin" if actor["username"] == "root" else actor["role"]
        if role_rank(actor_role) < role_rank("manager"):
            return json_resp({"ok":False,"msg":"權限不足"}), 403

        page = parse_positive_int(request.args.get("page", 0), min_value=0)
        if page is None:
            return json_resp({"ok":False,"msg":"page 參數格式錯誤"}), 400
        limit = parse_positive_int(request.args.get("limit", 50), max_value=200)
        if limit is None:
            return json_resp({"ok":False,"msg":"limit 參數格式錯誤"}), 400
        offset = page * limit
        username_filter = request.args.get("username", "").strip() or None

        conn = get_db()
        try:
            users_all = conn.execute(
                "SELECT username, violation_count FROM users WHERE username<>'root' ORDER BY id ASC"
            ).fetchall()
            where = "WHERE username<>'root'"
            params = []
            if username_filter:
                where += " AND username=?"
                params.append(username_filter)
            total = conn.execute(
                f"SELECT COUNT(*) as c FROM secure_violations {where}",
                tuple(params)
            ).fetchone()["c"]
            rows = conn.execute(
                "SELECT id, user_id, username, points, reason, triggered_by, actor_username, created_at, entry_hash "
                f"FROM secure_violations {where} ORDER BY id DESC LIMIT ? OFFSET ?",
                tuple(params + [limit, offset])
            ).fetchall()
            result = [{
                "id": r["id"],
                "user_id": r["user_id"],
                "username": r["username"],
                "points": r["points"],
                "reason": r["reason"],
                "triggered_by": r["triggered_by"],
                "actor": r["actor_username"],
                "timestamp": r["created_at"],
                "created_at": r["created_at"],
                "chain_hash": r["entry_hash"][:32] + "...",
                "_chain_hash": r["entry_hash"],
            } for r in rows]

            integrity_ok = True
            integrity_broken = None
            integrity_details = "no entries"
            if username_filter:
                target = conn.execute(
                    "SELECT id FROM users WHERE username=?", (username_filter,)
                ).fetchone()
                if target:
                    integrity_ok, integrity_broken, integrity_details = verify_violation_integrity(target["id"])
            else:
                head_row = conn.execute("SELECT MAX(id) AS head_id FROM secure_violations").fetchone()
                head_id = head_row["head_id"] if head_row else None
                cached = None
                with _VIOLATION_INTEGRITY_CACHE_LOCK:
                    if (
                        _VIOLATION_INTEGRITY_CACHE["payload"] is not None
                        and _VIOLATION_INTEGRITY_CACHE["head_id"] == head_id
                        and time.monotonic() - _VIOLATION_INTEGRITY_CACHE["checked_at"] < 300
                    ):
                        cached = dict(_VIOLATION_INTEGRITY_CACHE["payload"])
                if cached is None:
                    cached = {"ok": True, "broken_at": None, "details": "integrity OK"}
                    for u in conn.execute("SELECT id FROM users WHERE username<>'root' ORDER BY id ASC").fetchall():
                        ok, broken_at, details = verify_violation_integrity(u["id"])
                        if not ok:
                            cached = {"ok": False, "broken_at": broken_at, "details": details}
                            break
                    with _VIOLATION_INTEGRITY_CACHE_LOCK:
                        _VIOLATION_INTEGRITY_CACHE.update({
                            "head_id": head_id,
                            "checked_at": time.monotonic(),
                            "payload": dict(cached),
                        })
                integrity_ok = cached["ok"]
                integrity_broken = cached["broken_at"]
                integrity_details = cached["details"]

            return json_resp({
                "ok":      True,
                "entries": result,
                "total":   total,
                "page":    page,
                "limit":   limit,
                "users":   [{"username": u["username"], "violation_count": u["violation_count"]} for u in users_all],
                "integrity": {
                    "ok":        integrity_ok,
                    "broken_at": integrity_broken,
                    "details":   integrity_details,
                }
            })
        finally:
            conn.close()

    # ── 重置單一用戶違規計次（super_admin only）────────────────────────────────────
    @app.route("/api/admin/users/<int:user_id>/reset-violations", methods=["POST"])
    @require_csrf
    def admin_reset_violations(user_id):
        """超級管理者將用戶違規歸零"""
        actor = get_current_user_ctx()
        if not actor or actor["username"] != "root":
            return json_resp({"ok":False,"msg":"只有最高管理者可執行此操作"}), 403

        conn = get_db()
        try:
            target = conn.execute(
                "SELECT id, username, role, violation_count FROM users WHERE id=?", (user_id,)
            ).fetchone()
            if not target:
                return json_resp({"ok":False,"msg":"找不到帳號"}), 404

            secure_add_violation(
                user_id,
                target["username"],
                target["role"],
                0,
                f"violations_reset by {actor['username']} (previous: {target['violation_count']})",
                "super_admin",
                actor["username"],
                update_user_counter=False,
            )
            conn.execute("UPDATE users SET violation_count=0 WHERE id=?", (user_id,))
            conn.commit()
            audit("VIOLATIONS_RESET", get_client_ip(), user=actor["username"],
                  detail=f"target_id={user_id} previous_count={target['violation_count']}")
            return json_resp({"ok":True,"msg":f"已重置 {target['username']} 的違規計次"})
        finally:
            conn.close()

    # ── 審計日誌（manager + super_admin 皆可檢視）────────────────────────────────
    @app.route("/api/admin/audit", methods=["GET"])
    @require_csrf_safe
    def admin_audit():
        actor = get_current_user_ctx()
        if not actor:
            return json_resp({"ok":False,"msg":"未登入"}), 401
        actor_role = "super_admin" if actor["username"] == "root" else actor["role"]
        if role_rank(actor_role) < role_rank("manager"):
            return json_resp({"ok":False,"msg":"權限不足"}), 403

        page = parse_positive_int(request.args.get("page", 0), min_value=0)
        if page is None:
            return json_resp({"ok":False,"msg":"page 參數格式錯誤"}), 400
        limit = parse_positive_int(request.args.get("limit", 50), max_value=200)
        if limit is None:
            return json_resp({"ok":False,"msg":"limit 參數格式錯誤"}), 400
        offset = page * limit

        # 讀取 secure_audit 表（hash chain）
        conn = get_db()
        try:
            total = conn.execute("SELECT COUNT(*) as c FROM secure_audit").fetchone()["c"]
            rows  = conn.execute(
                "SELECT id, ts, action, ip, user, success, ua, detail, chain_hash "
                "FROM secure_audit ORDER BY id DESC LIMIT ? OFFSET ?",
                (limit, offset)
            ).fetchall()
            entries = []
            for r in rows:
                entries.append({
                    "id":        r["id"],
                    "ts":        r["ts"],
                    "timestamp": r["ts"],
                    "action":    r["action"],
                    "actor":     r["user"],
                    "ip":        r["ip"],
                    "user":      r["user"],
                    "success":   bool(r["success"]),
                    "ua":        r["ua"],
                    "detail":    r["detail"],
                    "details":   r["detail"],
                    "chain_hash": r["chain_hash"][:32] + "...",  # 只顯示前 32 字符
                    "_chain_hash": r["chain_hash"],
                })

            # Legacy fallback：audit.log JSONL（避免 table 還沒同步時前端顯示空白）
            if total == 0 and not entries:
                if os.path.exists(AUDIT_LOG_PATH):
                    with open(AUDIT_LOG_PATH, "r", encoding="utf-8") as f:
                        raw_lines = [ln.strip() for ln in f if ln.strip()]
                    normalized_lines = list(reversed(raw_lines))
                    page_lines = normalized_lines[offset:offset + limit]
                    for idx, line in enumerate(page_lines):
                        try:
                            obj = json.loads(line)
                        except Exception:
                            continue
                        entries.append({
                            "id":            total + idx + 1,
                            "ts":            obj.get("ts", ""),
                            "timestamp":     obj.get("ts", ""),
                            "action":        obj.get("action", ""),
                            "actor":         obj.get("user", ""),
                            "ip":            obj.get("ip", ""),
                            "user":          obj.get("user", ""),
                            "success":       bool(obj.get("success", False)),
                            "ua":            obj.get("ua", ""),
                            "detail":        obj.get("detail", ""),
                            "details":       obj.get("detail", ""),
                            "chain_hash":    "",
                            "_chain_hash":    "",
                            "source":        "legacy_log",
                        })
                    total = len(raw_lines)

            # Integrity 驗證
            if is_audit_chain_enabled():
                ok, broken_at, details = verify_audit_integrity()
                if not ok:
                    activate_emergency_lockdown(f"audit_chain_broken_at={broken_at}; {details}")
                integrity = {"enabled": True, "ok": ok, "broken_at": broken_at, "details": details}
            else:
                integrity = {"enabled": False, "ok": None, "broken_at": None, "details": "audit chain disabled"}

            return json_resp({
                "ok": True,
                "entries": entries,
                "total": total,
                "page": page,
                "limit": limit,
                "integrity": integrity
            })
        finally:
            conn.close()

    @app.route("/api/admin/message-reports", methods=["GET"])
    @require_csrf_safe
    def admin_message_reports():
        actor = get_current_user_ctx()
        if not actor:
            return json_resp({"ok":False,"msg":"未登入"}), 401
        actor_role = "super_admin" if actor["username"] == "root" else actor["role"]
        if role_rank(actor_role) < role_rank("super_admin"):
            return json_resp({"ok":False,"msg":"只有最高管理者可審核檢舉"}), 403
        status = normalize_text(request.args.get("status")) or "pending"
        if status not in ("pending", "approved", "rejected"):
            return json_resp({"ok":False,"msg":"狀態參數錯誤"}), 400
        page = parse_positive_int(request.args.get("page", 0), min_value=0)
        if page is None:
            return json_resp({"ok":False,"msg":"page 參數格式錯誤"}), 400
        limit = parse_positive_int(request.args.get("limit", 30), min_value=1, max_value=100)
        if limit is None:
            return json_resp({"ok":False,"msg":"limit 參數格式錯誤"}), 400
        offset = page * limit

        conn = get_db()
        try:
            has_community_reports = ensure_community_report_schema(conn)
            chat_total = conn.execute(
                "SELECT COUNT(*) AS c FROM chat_message_reports WHERE status=?", (status,)
            ).fetchone()["c"]
            community_total = 0
            chat_rows = conn.execute(
                "SELECT r.id, r.message_id, r.room_id, r.reason, r.status, r.reviewed_by, r.reviewed_at, r.review_note, r.created_at, "
                "reporter.username AS reporter_username, reported.username AS reported_username, m.content "
                "FROM chat_message_reports r "
                "LEFT JOIN users reporter ON reporter.id=r.reporter_user_id "
                "LEFT JOIN users reported ON reported.id=r.reported_user_id "
                "LEFT JOIN chat_messages m ON m.id=r.message_id "
                "WHERE r.status=? ORDER BY r.id DESC LIMIT ? OFFSET ?",
                (status, limit, offset)
            ).fetchall()
            community_rows = []
            if has_community_reports:
                community_total = conn.execute(
                    "SELECT COUNT(*) AS c FROM forum_post_reports WHERE status=?", (status,)
                ).fetchone()["c"]
                community_rows = conn.execute(
                    "SELECT r.id, r.post_id, r.thread_id, r.reason, r.status, r.reviewed_by, r.reviewed_at, r.review_note, r.created_at, "
                    "reporter.username AS reporter_username, reported.username AS reported_username, p.content "
                    "FROM forum_post_reports r "
                    "LEFT JOIN users reporter ON reporter.id=r.reporter_user_id "
                    "LEFT JOIN users reported ON reported.id=r.reported_user_id "
                    "LEFT JOIN forum_posts p ON p.id=r.post_id "
                    "WHERE r.status=? ORDER BY r.id DESC LIMIT ? OFFSET ?",
                    (status, limit, offset)
                ).fetchall()
            items = [{
                "kind": "chat",
                "id": r["id"],
                "message_id": r["message_id"],
                "room_id": r["room_id"],
                "reason": r["reason"],
                "status": r["status"],
                "reporter_username": r["reporter_username"] or "",
                "reported_username": r["reported_username"] or "",
                "content": r["content"] or "",
                "reviewed_by": r["reviewed_by"],
                "reviewed_at": r["reviewed_at"],
                "review_note": r["review_note"],
                "created_at": r["created_at"],
            } for r in chat_rows]
            items.extend({
                "kind": "community_post",
                "id": r["id"],
                "message_id": r["post_id"],
                "room_id": r["thread_id"],
                "reason": r["reason"],
                "status": r["status"],
                "reporter_username": r["reporter_username"] or "system",
                "reported_username": r["reported_username"] or "",
                "content": r["content"] or "",
                "reviewed_by": r["reviewed_by"],
                "reviewed_at": r["reviewed_at"],
                "review_note": r["review_note"],
                "created_at": r["created_at"],
            } for r in community_rows)
            items.sort(key=lambda item: item.get("created_at") or "", reverse=True)
            items = items[:limit]
            return json_resp({
                "ok": True,
                "total": chat_total + community_total,
                "page": page,
                "limit": limit,
                "items": items
            })
        finally:
            conn.close()

    @app.route("/api/admin/message-reports/<int:report_id>/review", methods=["POST"])
    @require_csrf
    def admin_message_report_review(report_id):
        actor = get_current_user_ctx()
        if not actor:
            return json_resp({"ok":False,"msg":"未登入"}), 401
        actor_role = "super_admin" if actor["username"] == "root" else actor["role"]
        if role_rank(actor_role) < role_rank("super_admin"):
            return json_resp({"ok":False,"msg":"只有最高管理者可審核檢舉"}), 403
        try:
            data = request.get_json(force=True)
        except Exception:
            return json_resp({"ok":False,"msg":"Invalid JSON"}), 400
        if not isinstance(data, dict):
            return json_resp({"ok":False,"msg":"Invalid request"}), 400
        action = normalize_text(data.get("action"))
        note = normalize_text(data.get("note"))
        if action not in ("approve", "reject"):
            return json_resp({"ok":False,"msg":"審核動作錯誤"}), 400

        conn = get_db()
        try:
            report = conn.execute(
                "SELECT r.*, u.username AS reported_username, u.role AS reported_role "
                "FROM chat_message_reports r LEFT JOIN users u ON u.id=r.reported_user_id WHERE r.id=?",
                (report_id,)
            ).fetchone()
            if not report:
                return json_resp({"ok":False,"msg":"找不到檢舉"}), 404
            if report["status"] != "pending":
                return json_resp({"ok":False,"msg":"此檢舉已審核"}), 409
            final_status = "approved" if action == "approve" else "rejected"
            reviewed_at = datetime.now().isoformat()
            msg = "已駁回檢舉"
            if action == "approve":
                role = "super_admin" if report["reported_username"] == "root" else (report["reported_role"] or "user")
                _, msg, _ = add_violation(
                    report["reported_user_id"], report["reported_username"], role, points=1,
                    reason=f"訊息檢舉成立：{report['reason']}", triggered_by="message_report", actor_username=actor["username"]
                )
            conn.execute(
                "UPDATE chat_message_reports SET status=?, reviewed_by=?, reviewed_at=?, review_note=? WHERE id=?",
                (final_status, actor["username"], reviewed_at, note, report_id)
            )
            conn.commit()
            audit("CHAT_MESSAGE_REPORT_REVIEWED", get_client_ip(), user=actor["username"],
                  detail=f"report_id={report_id},action={action},reported={report['reported_username']}")
            return json_resp({"ok":True,"msg":msg})
        finally:
            conn.close()

    @app.route("/api/admin/community-post-reports/<int:report_id>/review", methods=["POST"])
    @require_csrf
    def admin_community_post_report_review(report_id):
        actor = get_current_user_ctx()
        if not actor:
            return json_resp({"ok":False,"msg":"未登入"}), 401
        actor_role = "super_admin" if actor["username"] == "root" else actor["role"]
        if role_rank(actor_role) < role_rank("super_admin"):
            return json_resp({"ok":False,"msg":"只有最高管理者可審核檢舉"}), 403
        try:
            data = request.get_json(force=True)
        except Exception:
            return json_resp({"ok":False,"msg":"Invalid JSON"}), 400
        if not isinstance(data, dict):
            return json_resp({"ok":False,"msg":"Invalid request"}), 400
        action = normalize_text(data.get("action"))
        note = normalize_text(data.get("note"))
        if action not in ("approve", "reject"):
            return json_resp({"ok":False,"msg":"審核動作錯誤"}), 400

        conn = get_db()
        try:
            if not ensure_community_report_schema(conn):
                return json_resp({"ok":False,"msg":"找不到社群留言檢舉"}), 404
            report = conn.execute(
                "SELECT r.*, u.username AS reported_username, u.role AS reported_role "
                "FROM forum_post_reports r LEFT JOIN users u ON u.id=r.reported_user_id WHERE r.id=?",
                (report_id,)
            ).fetchone()
            if not report:
                return json_resp({"ok":False,"msg":"找不到檢舉"}), 404
            if report["status"] != "pending":
                return json_resp({"ok":False,"msg":"此檢舉已審核"}), 409
            final_status = "approved" if action == "approve" else "rejected"
            reviewed_at = datetime.now().isoformat()
            msg = "已駁回檢舉，留言已恢復顯示"
            if action == "approve":
                role = "super_admin" if report["reported_username"] == "root" else (report["reported_role"] or "user")
                _, msg, _ = add_violation(
                    report["reported_user_id"], report["reported_username"], role, points=1,
                    reason=f"社群留言檢舉成立：{report['reason']}", triggered_by="community_post_report", actor_username=actor["username"]
                )
            else:
                conn.execute(
                    "UPDATE forum_posts SET is_hidden=0, hidden_reason=NULL, updated_at=? WHERE id=?",
                    (reviewed_at, report["post_id"])
                )
            conn.execute(
                "UPDATE forum_post_reports SET status=?, reviewed_by=?, reviewed_at=?, review_note=? WHERE id=?",
                (final_status, actor["username"], reviewed_at, note, report_id)
            )
            conn.commit()
            audit("COMMUNITY_POST_REPORT_REVIEWED", get_client_ip(), user=actor["username"],
                  detail=f"report_id={report_id},action={action},reported={report['reported_username']}")
            return json_resp({"ok":True,"msg":msg})
        finally:
            conn.close()
