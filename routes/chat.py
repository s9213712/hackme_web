import sqlite3
from datetime import datetime
from flask import request


def register_chat_routes(app, deps):
    globals().update(deps)

    @app.route("/api/chat/rooms", methods=["GET", "POST"], strict_slashes=False)
    @require_csrf_safe
    def chat_rooms():
        actor = get_current_user_ctx()
        if not actor:
            return json_resp({"ok":False,"msg":"未登入"}), 401
        ip = get_client_ip()
        urow_id = actor["id"]

        if request.method == "GET":
            conn = get_db()
            try:
                ensure_user_official_room_membership(conn, urow_id)
                conn.commit()
                rows = conn.execute(
                    "SELECT r.id, r.name, r.owner_user_id, r.created_at, u.username AS owner_username "
                    "FROM chat_rooms r "
                    "LEFT JOIN users u ON u.id = r.owner_user_id "
                    "INNER JOIN chat_room_members m ON m.room_id = r.id "
                    "WHERE m.user_id = ? "
                    "ORDER BY r.created_at DESC",
                    (urow_id,)
                ).fetchall()
                return json_resp({
                    "ok": True,
                    "rooms": [
                        {
                            "id": r["id"],
                            "name": r["name"],
                            "owner_user_id": r["owner_user_id"],
                            "owner_username": r["owner_username"] or "未知",
                            "created_at": r["created_at"]
                        } for r in rows
                    ]
                })
            finally:
                conn.close()

        try:
            data = request.get_json(force=True)
        except Exception:
            return json_resp({"ok":False,"msg":"Invalid JSON"}), 400
        if not isinstance(data, dict):
            return json_resp({"ok":False,"msg":"Invalid request"}), 400
        name = normalize_text(data.get("name"))
        target_user = normalize_text(data.get("target_user"))
        if not name:
            return json_resp({"ok":False,"msg":"聊天室名稱不可為空"}), 400
        if len(name) > 48:
            return json_resp({"ok":False,"msg":"聊天室名稱最多 48 字元"}), 400
        if target_user == actor["username"]:
            return json_resp({"ok":False,"msg":"不能指定自己為對象"}), 400

        conn = get_db()
        try:
            target_row = None
            if target_user:
                target_row = conn.execute(
                    "SELECT id, username FROM users WHERE username=? AND status='active'",
                    (target_user,)
                ).fetchone()
                if not target_row:
                    return json_resp({"ok":False,"msg":"找不到指定對象帳號"}), 404
            cur = conn.execute(
                "INSERT INTO chat_rooms (name, owner_user_id, created_at) VALUES (?, ?, ?)",
                (name, urow_id, datetime.now().isoformat())
            )
            room_id = cur.lastrowid
            now = datetime.now().isoformat()
            conn.execute(
                "INSERT OR IGNORE INTO chat_room_members (room_id, user_id, joined_at) VALUES (?, ?, ?)",
                (room_id, urow_id, now)
            )
            if target_row:
                conn.execute(
                    "INSERT OR IGNORE INTO chat_room_members (room_id, user_id, joined_at) VALUES (?, ?, ?)",
                    (room_id, target_row["id"], now)
                )
            conn.commit()
            detail = f"room_id={room_id}, name={name}"
            if target_row:
                detail += f", target={target_row['username']}"
            audit("CHAT_ROOM_CREATED", ip, user=actor["username"], detail=detail)
            invite_username = target_row["username"] if target_row else None
            return json_resp({
                "ok": True,
                "msg": "聊天室已建立",
                "room": {
                    "id": room_id,
                    "name": name,
                    "owner_user_id": urow_id,
                    "owner_username": actor["username"],
                    "target_username": invite_username
                }
            })
        except Exception:
            return json_resp({"ok":False,"msg":"建立聊天室失敗"}), 500
        finally:
            conn.close()

    @app.route("/api/chat/rooms/<int:room_id>/join", methods=["POST"], strict_slashes=False)
    @require_csrf
    def chat_room_join(room_id):
        actor = get_current_user_ctx()
        if not actor:
            return json_resp({"ok":False,"msg":"未登入"}), 401
        actor_id = actor["id"]
        conn = get_db()
        try:
            room = conn.execute(
                "SELECT r.id, r.name, r.owner_user_id, u.username AS owner_username "
                "FROM chat_rooms r LEFT JOIN users u ON u.id=r.owner_user_id WHERE r.id=?",
                (room_id,)
            ).fetchone()
            if not room:
                return json_resp({"ok":False,"msg":"找不到聊天室"}), 404
            existing_member = conn.execute(
                "SELECT 1 FROM chat_room_members WHERE room_id=? AND user_id=?",
                (room_id, actor_id)
            ).fetchone()
            if existing_member:
                return json_resp({"ok":True,"msg":"已加入聊天室","room":{"id":room["id"],"name":room["name"]}})
            is_public_official = room["name"] == OFFICIAL_CHAT_ROOM_NAME and room["owner_username"] == "root"
            if not is_public_official:
                audit("CHAT_JOIN_DENIED", get_client_ip(), user=actor["username"], detail=f"room_id={room_id},owner={room['owner_username'] or '-'}")
                return json_resp({"ok":False,"msg":"你沒有權限加入此聊天室"}), 403
            conn.execute(
                "INSERT OR IGNORE INTO chat_room_members (room_id, user_id, joined_at) VALUES (?, ?, ?)",
                (room_id, actor_id, datetime.now().isoformat())
            )
            conn.commit()
            audit("CHAT_ROOM_JOIN", get_client_ip(), user=actor["username"], detail=f"room_id={room_id}")
            return json_resp({"ok":True,"msg":"已加入聊天室","room":{"id":room["id"],"name":room["name"]}})
        finally:
            conn.close()

    @app.route("/api/chat/rooms/<int:room_id>/messages", methods=["GET", "POST"], strict_slashes=False)
    @require_csrf_safe
    def chat_messages(room_id):
        actor = get_current_user_ctx()
        if not actor:
            return json_resp({"ok":False,"msg":"未登入"}), 401

        conn = get_db()
        try:
            ensure_user_official_room_membership(conn, actor["id"])
            conn.commit()
            room = conn.execute("SELECT id, name FROM chat_rooms WHERE id=?", (room_id,)).fetchone()
            if not room:
                return json_resp({"ok":False,"msg":"找不到聊天室"}), 404

            member = conn.execute(
                "SELECT 1 FROM chat_room_members WHERE room_id=? AND user_id=?",
                (room_id, actor["id"])
            ).fetchone()
            if not member:
                return json_resp({"ok":False,"msg":"你尚未加入此聊天室"}), 403

            if request.method == "GET":
                limit = parse_positive_int(request.args.get("limit", 50), default=50, min_value=1, max_value=200)
                if limit is None:
                    return json_resp({"ok":False,"msg":"limit 參數錯誤"}), 400
                rows = conn.execute(
                    "SELECT m.id, m.sender_id, u.username, m.content, m.created_at "
                    "FROM chat_messages m "
                    "LEFT JOIN users u ON u.id = m.sender_id "
                    "WHERE m.room_id = ? AND m.is_blocked = 0 "
                    "ORDER BY m.id DESC LIMIT ?",
                    (room_id, limit)
                ).fetchall()
                messages = [
                    {
                        "id": r["id"],
                        "sender_id": r["sender_id"],
                        "sender": r["username"] or "系統",
                        "content": r["content"],
                        "created_at": r["created_at"]
                    } for r in reversed(rows)
                ]
                return json_resp({
                    "ok": True,
                    "room": {"id": room["id"], "name": room["name"]},
                    "messages": messages
                })

            csrf_tok = get_request_csrf_token()
            if not verify_csrf_token(csrf_tok, actor["username"]):
                return json_resp({"ok":False,"msg":"CSRF token 無效或已過期"}), 403
            delete_csrf_token(csrf_tok)

            try:
                data = request.get_json(force=True)
            except Exception:
                return json_resp({"ok":False,"msg":"Invalid JSON"}), 400
            if not isinstance(data, dict):
                return json_resp({"ok":False,"msg":"Invalid request"}), 400
            content = (data.get("content") or "").strip()
            if not content:
                return json_resp({"ok":False,"msg":"訊息不可為空"}), 400
            if len(content) > CHAT_MESSAGE_MAX_LEN:
                return json_resp({"ok":False,"msg":f"訊息過長，最多 {CHAT_MESSAGE_MAX_LEN} 字"}), 400

            is_bad, bad_reason = detect_chat_violation(content)
            if is_bad:
                warning_count = int(dict(actor).get("chat_violation_warned") or 0)
                if warning_count == 0:
                    conn.execute(
                        "UPDATE users SET chat_violation_warned = 1, updated_at=? WHERE id=?",
                        (datetime.now().isoformat(), actor["id"])
                    )
                    conn.commit()
                    audit("CHAT_WARNING", get_client_ip(), user=actor["username"], detail=f"room_id={room_id},reason={bad_reason}")
                    return json_resp({
                        "ok":False,
                        "warned":True,
                        "reason":bad_reason,
                        "msg":"訊息含違規內容，已警告一次，請修改後再送出"
                    }), 403

                role = "super_admin" if actor["username"] == "root" else actor["role"]
                action, msg, total = add_violation(
                    actor["id"], actor["username"], role, points=1,
                    reason=f"聊天違規：{bad_reason}", triggered_by="system", actor_username=actor["username"]
                )
                audit("CHAT_VIOLATION", get_client_ip(), user=actor["username"],
                      detail=f"room_id={room_id},reason={bad_reason},action={action},total={total}")
                return json_resp({
                    "ok":False,
                    "warned":True,
                    "reason":bad_reason,
                    "violation_count": total,
                    "msg":msg
                }), 403

            created_at = datetime.now().isoformat()
            cur = conn.execute(
                "INSERT INTO chat_messages (room_id, sender_id, content, created_at) VALUES (?, ?, ?, ?)",
                (room_id, actor["id"], content, created_at)
            )
            conn.commit()
            append_chat_record(room_id, cur.lastrowid, actor["username"], content, created_at)
            return json_resp({"ok":True,"msg":"訊息已送出"})
        finally:
            conn.close()

    @app.route("/api/chat/messages/<int:message_id>/report", methods=["POST"], strict_slashes=False)
    @require_csrf
    def report_chat_message(message_id):
        actor = get_current_user_ctx()
        if not actor:
            return json_resp({"ok":False,"msg":"未登入"}), 401
        try:
            data = request.get_json(force=True)
        except Exception:
            return json_resp({"ok":False,"msg":"Invalid JSON"}), 400
        if not isinstance(data, dict):
            return json_resp({"ok":False,"msg":"Invalid request"}), 400
        reason = normalize_text(data.get("reason")) or "使用者檢舉"
        if len(reason) > 200:
            return json_resp({"ok":False,"msg":"檢舉原因請控制在 200 字以內"}), 400

        conn = get_db()
        try:
            msg = conn.execute(
                "SELECT m.id, m.room_id, m.sender_id, m.content, u.username AS sender_username "
                "FROM chat_messages m LEFT JOIN users u ON u.id=m.sender_id WHERE m.id=?",
                (message_id,)
            ).fetchone()
            if not msg:
                return json_resp({"ok":False,"msg":"找不到訊息"}), 404
            if msg["sender_id"] == actor["id"]:
                return json_resp({"ok":False,"msg":"不能檢舉自己的訊息"}), 400
            member = conn.execute(
                "SELECT 1 FROM chat_room_members WHERE room_id=? AND user_id=?",
                (msg["room_id"], actor["id"])
            ).fetchone()
            if not member:
                return json_resp({"ok":False,"msg":"你不在此聊天室"}), 403
            try:
                conn.execute(
                    "INSERT INTO chat_message_reports "
                    "(message_id, room_id, reporter_user_id, reported_user_id, reason, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (message_id, msg["room_id"], actor["id"], msg["sender_id"], reason, datetime.now().isoformat())
                )
                conn.commit()
            except sqlite3.IntegrityError:
                return json_resp({"ok":False,"msg":"你已檢舉過這則訊息"}), 409
            audit("CHAT_MESSAGE_REPORTED", get_client_ip(), user=actor["username"],
                  detail=f"message_id={message_id},reported={msg['sender_username']},reason={reason}")
            return json_resp({"ok":True,"msg":"檢舉已送出，等待超級管理員審核"})
        finally:
            conn.close()

    @app.route("/api/audit", methods=["GET"])
    def api_audit():
        tok = request.cookies.get("session_token")
        user = db_get_user_from_token(tok) if tok else None
        if not user: return json_resp({"ok":False,"msg":"未授權"}), 401
        if role_rank(db_get_user_role(user) or "user") < role_rank("manager"):
            audit("AUDIT_FORBIDDEN", get_client_ip(), user, detail="non-manager attempted audit access")
            return json_resp({"ok":False,"msg":"需要管理者或最高管理者權限"}), 403

        conn = get_db()
        try:
            rows = conn.execute(
                "SELECT u.username, la.ip_address, la.user_agent, la.success, la.attempted_at "
                "FROM login_attempts la LEFT JOIN users u ON u.id=la.user_id "
                "ORDER BY la.attempted_at DESC LIMIT 200"
            ).fetchall()
        finally:
            conn.close()

        entries = []
        for r in rows:
            entries.append({
                "user":      r["username"] or "(未知)",
                "ip":        r["ip_address"],
                "ua":        r["user_agent"],
                "success":   bool(r["success"]),
                "time":      r["attempted_at"],
            })
        return json_resp({"ok":True,"entries":entries})
