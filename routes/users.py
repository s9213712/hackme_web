import re
from datetime import datetime, timedelta
from flask import request


def register_user_routes(app, deps):
    globals().update(deps)

    @app.route("/api/admin/users", methods=["GET","POST"])
    @require_csrf_safe
    def admin_users():
        actor = get_current_user_ctx()
        if not actor:
            return json_resp({"ok":False,"msg":"未登入"}), 401

        if actor["username"] == "root":
            actor_role = "super_admin"
        else:
            actor_role = actor["role"]

        # Manager can only view; super_admin can add / modify / delete
        if request.method == "GET":
            if role_rank(actor_role) < role_rank("manager"):
                return json_resp({"ok":False,"msg":"權限不足"}), 403
            conn = get_db()
            try:
                rows = conn.execute(
                    "SELECT id, username, email, nickname, real_name, birthdate, id_number, phone, status, role, blocked_until, violation_count "
                    "FROM users ORDER BY id ASC"
                ).fetchall()
                data = [user_public_payload(r) for r in rows]
            finally:
                conn.close()
            return json_resp({
                "ok": True,
                "users": data,
                "can_manage": role_rank(actor_role) >= role_rank("super_admin"),
                "can_review": role_rank(actor_role) >= role_rank("manager")
            })

        # POST — super_admin only
        if role_rank(actor_role) < role_rank("super_admin"):
            return json_resp({"ok":False,"msg":"只有最高權限可新增帳號"}), 403

        try:
            data = request.get_json(force=True)
        except Exception:
            return json_resp({"ok":False,"msg":"Invalid JSON"}), 400
        if not isinstance(data, dict):
            return json_resp({"ok":False,"msg":"Invalid request"}), 400

        username = normalize_text(data.get("username"))
        password = data.get("password", "") if isinstance(data.get("password"), str) else ""
        password_confirm = data.get("password_confirm","") if isinstance(data.get("password_confirm"), str) else ""
        nickname = normalize_text(data.get("nickname"))
        real_name = normalize_text(data.get("real_name"))
        id_number = normalize_text(data.get("id_number"))
        birthdate = parse_birthdate(data.get("birthdate"))
        phone = normalize_text(data.get("phone"))
        role = normalize_text(data.get("role")) or "user"
        status = normalize_text(data.get("status")) or "active"

        if role not in ROLE_RANK:
            return json_resp({"ok":False,"msg":"不支援的角色"}), 400
        if status not in ("active","inactive"):
            return json_resp({"ok":False,"msg":"帳號狀態錯誤"}), 400
        if not username or len(username) < 3:
            return json_resp({"ok":False,"msg":"帳號至少 3 字元"}), 400
        if len(username) > 32:
            return json_resp({"ok":False,"msg":"帳號最長 32 字元"}), 400
        if not re.fullmatch(r"[a-zA-Z0-9_\-]+", username):
            return json_resp({"ok":False,"msg":"帳號只能包含英文、數字、底線、減號"}), 400
        if not nickname:
            return json_resp({"ok":False,"msg":"暱稱不可為空"}), 400
        if not real_name:
            return json_resp({"ok":False,"msg":"真實姓名不可為空"}), 400
        if not validate_id_number(id_number):
            return json_resp({"ok":False,"msg":"身分證格式錯誤"}), 400
        if not birthdate:
            return json_resp({"ok":False,"msg":"生日需為 YYYY-MM-DD"}), 400
        if not validate_phone(phone):
            return json_resp({"ok":False,"msg":"電話格式錯誤"}), 400
        if password != password_confirm:
            return json_resp({"ok":False,"msg":"兩次輸入的密碼不一致"}), 400

        # 超級管理者可指定任意密碼（繞過複雜度規則，但仍截斷長度）
        is_super = actor_role == "super_admin"
        if password:
            password = password[:128]  # 截斷防止超長密碼
            if not is_super:
                ok, msg = validate_password(password)
                if not ok:
                    return json_resp({"ok":False,"msg":msg}), 400
        else:
            return json_resp({"ok":False,"msg":"新建帳號必須指定密碼"}), 400

        conn = get_db()
        try:
            existing = conn.execute("SELECT 1 FROM users WHERE username=?", (username,)).fetchone()
            if existing:
                return json_resp({"ok":False,"msg":"帳號已存在"}), 409
            now = datetime.now().isoformat()
            cur = conn.execute(
                "INSERT INTO users (username, nickname, real_name, birthdate, id_number, phone, role, status, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (username, encrypt_field(nickname), encrypt_field(real_name), encrypt_field(birthdate), encrypt_field(id_number), encrypt_field(phone), role, status, now, now)
            )
            conn.execute(
                "INSERT INTO user_passwords (user_id, password_hash, created_at) VALUES (?, ?, ?)",
                (cur.lastrowid, hash_password(password), now)
            )
            conn.commit()
            audit("ADMIN_CREATE_USER", get_client_ip(), user=actor["username"], success=True, ua=get_ua(),
                  detail=f"target={username}, role={role}")
            return json_resp({"ok":True,"msg":"帳號已建立"})
        finally:
            conn.close()

    @app.route("/api/admin/users/<int:user_id>", methods=["GET"])
    @require_csrf_safe
    def admin_user_item(user_id):
        actor = get_current_user_ctx()
        if not actor:
            return json_resp({"ok":False,"msg":"未登入"}), 401
        actor_role = "super_admin" if actor["username"] == "root" else actor["role"]
        is_self = actor["id"] == user_id
        if role_rank(actor_role) < role_rank("manager") and not is_self:
            return json_resp({"ok":False,"msg":"權限不足"}), 403

        conn = get_db()
        try:
            target = conn.execute(
                "SELECT id, username, nickname, real_name, birthdate, id_number, phone, role, status, blocked_until, violation_count FROM users WHERE id=?",
                (user_id,)
            ).fetchone()
            if not target:
                return json_resp({"ok":False,"msg":"找不到帳號"}), 404
            return json_resp({
                "ok": True,
                "user": {
                    "id": target["id"],
                    "username": target["username"],
                    "nickname": decrypt_field(target["nickname"]),
                    "real_name": decrypt_field(target["real_name"]),
                    "birthdate": decrypt_field(target["birthdate"]),
                    "id_number": decrypt_field(target["id_number"]),
                    "phone": decrypt_field(target["phone"]),
                    "role": target["role"],
                    "status": target["status"],
                    "blocked_until": target["blocked_until"],
                    "violation_count": target["violation_count"] or 0,
                }
            })
        finally:
            conn.close()

    @app.route("/api/admin/users/<int:user_id>", methods=["PUT", "DELETE"])
    @require_csrf
    def admin_user_item_mutate(user_id):
        actor = get_current_user_ctx()
        if not actor:
            return json_resp({"ok":False,"msg":"未登入"}), 401
        actor_role = "super_admin" if actor["username"] == "root" else actor["role"]
        is_self = actor["id"] == user_id
        if request.method == "DELETE" and role_rank(actor_role) < role_rank("super_admin"):
            return json_resp({"ok":False,"msg":"只有最高權限可刪除帳號"}), 403
        if request.method == "PUT" and not is_self and role_rank(actor_role) < role_rank("super_admin"):
            return json_resp({"ok":False,"msg":"只有最高權限可修改他人帳號"}), 403

        conn = get_db()
        try:
            target = conn.execute(
                "SELECT id, username, nickname, real_name, birthdate, id_number, phone, role, status, blocked_until, violation_count FROM users WHERE id=?",
                (user_id,)
            ).fetchone()
            if not target:
                return json_resp({"ok":False,"msg":"找不到帳號"}), 404

            if request.method == "DELETE":
                if target["username"] == "root":
                    return json_resp({"ok":False,"msg":"不可刪除最高管理者帳號"}), 403
                if target["username"] == actor["username"]:
                    return json_resp({"ok":False,"msg":"不可刪除目前登入中的帳號"}), 403
                conn.execute("DELETE FROM users WHERE id=?", (user_id,))
                conn.commit()
                audit("ADMIN_DELETE_USER", get_client_ip(), user=actor["username"], success=True, ua=get_ua(),
                      detail=f"target_id={user_id}")
                return json_resp({"ok":True,"msg":"帳號已刪除"})

            try:
                data = request.get_json(force=True)
            except Exception:
                return json_resp({"ok":False,"msg":"Invalid JSON"}), 400
            if not isinstance(data, dict):
                return json_resp({"ok":False,"msg":"Invalid request"}), 400

            updates = []
            params = []
            if "nickname" in data:
                updates.append("nickname=?")
                params.append(encrypt_field(normalize_text(data["nickname"])))
            if "real_name" in data:
                updates.append("real_name=?")
                params.append(encrypt_field(normalize_text(data["real_name"])))
            if "id_number" in data:
                val = normalize_text(data["id_number"])
                if not validate_id_number(val):
                    return json_resp({"ok":False,"msg":"身分證格式錯誤"}), 400
                updates.append("id_number=?")
                params.append(encrypt_field(val))
            if "birthdate" in data:
                val = parse_birthdate(data["birthdate"])
                if not val:
                    return json_resp({"ok":False,"msg":"生日需為 YYYY-MM-DD"}), 400
                updates.append("birthdate=?")
                params.append(encrypt_field(val))
            if "phone" in data:
                val = normalize_text(data["phone"])
                if not validate_phone(val):
                    return json_resp({"ok":False,"msg":"電話格式錯誤"}), 400
                updates.append("phone=?")
                params.append(encrypt_field(val))
            if "status" in data:
                if is_self:
                    return json_resp({"ok":False,"msg":"不可自行變更帳號狀態"}), 403
                val = normalize_text(data["status"])
                if val not in ("active","inactive","pending","rejected"):
                    return json_resp({"ok":False,"msg":"帳號狀態錯誤"}), 400
                updates.append("status=?")
                params.append(val)
            if "role" in data:
                if is_self:
                    return json_resp({"ok":False,"msg":"不可自行變更角色"}), 403
                val = normalize_text(data["role"])
                if val not in ROLE_RANK:
                    return json_resp({"ok":False,"msg":"不支援的角色"}), 400
                if target["username"] == "root" and val != "super_admin":
                    return json_resp({"ok":False,"msg":"最高管理者角色不可變更"}), 403
                updates.append("role=?")
                params.append(val)
            if "password" in data and isinstance(data["password"], str) and data["password"]:
                pw = data["password"][:128]  # 截斷防止超長密碼
                pw_confirm = data.get("password_confirm","") if isinstance(data.get("password_confirm"), str) else ""
                if pw_confirm and pw != pw_confirm:
                    return json_resp({"ok":False,"msg":"兩次密碼輸入不一致"}), 400
                if actor_role != "super_admin":
                    ok, msg = validate_password(pw)
                    if not ok:
                        return json_resp({"ok":False,"msg":msg}), 400
                conn.execute(
                    "INSERT INTO user_passwords (user_id, password_hash, created_at) VALUES (?, ?, ?)",
                    (user_id, hash_password(pw), datetime.now().isoformat())
                )
            if "username" in data:
                return json_resp({"ok":False,"msg":"不允許變更帳號名稱"}), 400

            pw_payload = "password" in data and isinstance(data["password"], str) and data["password"]
            if not updates and not pw_payload:
                return json_resp({"ok":False,"msg":"未提供可更新欄位"}), 400

            if pw_payload and not updates:
                conn.commit()
            elif updates:
                updates.append("updated_at=?")
                params.append(datetime.now().isoformat())
                params.append(user_id)
                sql = "UPDATE users SET " + ", ".join(updates) + " WHERE id=?"
                conn.execute(sql, params)
                conn.commit()
            audit("ADMIN_UPDATE_USER", get_client_ip(), user=actor["username"], success=True, ua=get_ua(),
                  detail=f"target_id={user_id},self={is_self}")
            return json_resp({"ok":True,"msg":"帳號已更新"})
        finally:
            conn.close()

    @app.route("/api/admin/users/<int:user_id>/review-registration", methods=["POST"])
    @require_csrf
    def review_registration(user_id):
        actor = get_current_user_ctx()
        if not actor:
            return json_resp({"ok":False,"msg":"未登入"}), 401
        actor_role = "super_admin" if actor["username"] == "root" else actor["role"]
        if role_rank(actor_role) < role_rank("manager"):
            return json_resp({"ok":False,"msg":"只有管理者以上可審核註冊"}), 403

        try:
            data = request.get_json(force=True)
        except Exception:
            return json_resp({"ok":False,"msg":"Invalid JSON"}), 400
        if not isinstance(data, dict):
            return json_resp({"ok":False,"msg":"Invalid request"}), 400

        action = normalize_text(data.get("action"))
        if action not in ("approve", "reject"):
            return json_resp({"ok":False,"msg":"不支援的審核動作"}), 400

        conn = get_db()
        try:
            target = conn.execute(
                "SELECT id, username, status FROM users WHERE id=?",
                (user_id,)
            ).fetchone()
            if not target:
                return json_resp({"ok":False,"msg":"找不到帳號"}), 404
            if target["status"] != "pending":
                return json_resp({"ok":False,"msg":"此帳號目前不是待審核狀態"}), 409

            new_status = "active" if action == "approve" else "rejected"
            conn.execute(
                "UPDATE users SET status=?, updated_at=? WHERE id=?",
                (new_status, datetime.now().isoformat(), user_id)
            )
            if action == "approve":
                ensure_user_official_room_membership(conn, user_id)
            conn.commit()
            audit(
                "REGISTRATION_REVIEWED",
                get_client_ip(),
                user=actor["username"],
                success=True,
                ua=get_ua(),
                detail=f"target={target['username']},action={action}"
            )
            return json_resp({"ok":True,"msg":"審核已完成","status":new_status})
        finally:
            conn.close()

    @app.route("/api/admin/users/<int:user_id>/block", methods=["POST"])
    @require_csrf
    def admin_user_block(user_id):
        actor = get_current_user_ctx()
        if not actor:
            return json_resp({"ok":False,"msg":"未登入"}), 401
        actor_role = "super_admin" if actor["username"] == "root" else actor["role"]
        if role_rank(actor_role) < role_rank("manager"):
            return json_resp({"ok":False,"msg":"權限不足"}), 403

        try:
            data = request.get_json(force=True)
        except Exception:
            return json_resp({"ok":False,"msg":"Invalid JSON"}), 400
        if not isinstance(data, dict):
            return json_resp({"ok":False,"msg":"Invalid request"}), 400

        action = normalize_text(data.get("action")).lower() or "block"
        minutes = data.get("minutes", 30)
        if not isinstance(minutes, int):
            try:
                minutes = int(minutes)
            except Exception:
                minutes = 30
        if minutes < 1: minutes = 1
        if minutes > 1440: minutes = 1440

        conn = get_db()
        try:
            target = conn.execute("SELECT id, username, role FROM users WHERE id=?", (user_id,)).fetchone()
            if not target:
                return json_resp({"ok":False,"msg":"找不到帳號"}), 404
            if target["username"] == "root" and actor_role != "super_admin":
                return json_resp({"ok":False,"msg":"無權限封鎖最高管理者"}), 403

            if action == "unblock":
                conn.execute("UPDATE users SET status='active', blocked_until=NULL WHERE id=?", (user_id,))
                conn.commit()
                audit("ADMIN_UNBLOCK_USER", get_client_ip(), user=actor["username"], success=True, ua=get_ua(),
                      detail=f"target_id={user_id}")
                return json_resp({"ok":True,"msg":"帳號已解除封鎖"})

            blocked_until = (datetime.now() + timedelta(minutes=minutes)).isoformat()
            conn.execute("UPDATE users SET status='inactive', blocked_until=? WHERE id=?", (blocked_until, user_id))
            conn.commit()
            audit("ADMIN_BLOCK_USER", get_client_ip(), user=actor["username"], success=True, ua=get_ua(),
                  detail=f"target_id={user_id}, minutes={minutes}")
            return json_resp({"ok":True,"msg":f"帳號已封鎖 {minutes} 分鐘"})
        finally:
            conn.close()

    # ── 推廣 / 降級（promote / demote）───────────────────────────────────────────────
    @app.route("/api/admin/users/<int:user_id>/promote", methods=["POST"])
    @require_csrf
    def admin_user_promote(user_id):
        """僅超級管理者可推廣帳號"""
        actor = get_current_user_ctx()
        if not actor:
            return json_resp({"ok":False,"msg":"未登入"}), 401
        actor_role = "super_admin" if actor["username"] == "root" else actor["role"]
        if role_rank(actor_role) < role_rank("super_admin"):
            return json_resp({"ok":False,"msg":"權限不足"}), 403

        conn = get_db()
        try:
            target = conn.execute(
                "SELECT id, username, role FROM users WHERE id=?", (user_id,)
            ).fetchone()
            if not target:
                return json_resp({"ok":False,"msg":"找不到帳號"}), 404

            from_role = target["role"]
            if from_role == "super_admin":
                return json_resp({"ok":False,"msg":"最高管理者無需推廣"}), 400
            if from_role == "manager" and role_rank(actor_role) < role_rank("super_admin"):
                return json_resp({"ok":False,"msg":"只有最高管理者可推廣管理者"}), 403

            to_role = "manager" if from_role == "user" else "super_admin"
            if to_role == "manager":
                limit = MAX_MANAGERS
                if count_role("manager") >= limit:
                    return json_resp({"ok":False,"msg":f"管理者已達上限（{limit} 人）"}), 400
            # super_admin 限額 1 不需要檢查（root 不可變）

            conn.execute("UPDATE users SET role=?, violation_count=0, updated_at=? WHERE id=?",
                         (to_role, datetime.now().isoformat(), user_id))
            conn.commit()
            audit("USER_PROMOTED", get_client_ip(), user=actor["username"],
                  success=True, detail=f"user_id={user_id} {from_role}→{to_role}")
            return json_resp({"ok":True,"msg":f"已升為 {ROLE_LABEL[to_role]}"})
        finally:
            conn.close()

    @app.route("/api/admin/users/<int:user_id>/demote", methods=["POST"])
    @require_csrf
    def admin_user_demote(user_id):
        """超級管理者可將管理者降為一般用戶（再次降級＝刪除，由系統自動判斷）"""
        actor = get_current_user_ctx()
        if not actor:
            return json_resp({"ok":False,"msg":"未登入"}), 401
        actor_role = "super_admin" if actor["username"] == "root" else actor["role"]
        if role_rank(actor_role) < role_rank("super_admin"):
            return json_resp({"ok":False,"msg":"只有最高管理者可降級帳號"}), 403

        conn = get_db()
        try:
            target = conn.execute(
                "SELECT id, username, role FROM users WHERE id=?", (user_id,)
            ).fetchone()
            if not target:
                return json_resp({"ok":False,"msg":"找不到帳號"}), 404
            if target["username"] == "root":
                return json_resp({"ok":False,"msg":"最高管理者帳號不可降級"}), 403
            from_role = target["role"]
            if from_role == "user":
                # 一般用戶 → 刪除
                audit("USER_DELETED_BY_ADMIN", get_client_ip(), user=actor["username"],
                      detail=f"user_id={user_id} demoted from user (delete)")
                conn.execute("DELETE FROM users WHERE id=?", (user_id,))
                conn.commit()
                return json_resp({"ok":True,"msg":"一般用戶已刪除"})
            # 管理者 → 一般用戶
            conn.execute("UPDATE users SET role='user', violation_count=0, updated_at=? WHERE id=?",
                         (datetime.now().isoformat(), user_id))
            conn.commit()
            audit("MANAGER_DEMOTED_BY_ADMIN", get_client_ip(), user=actor["username"],
                  detail=f"user_id={user_id} manager→user")
            return json_resp({"ok":True,"msg":"已降級為一般用戶"})
        finally:
            conn.close()

    # ── 違規計點（系統自動 or 超級管理者手動）─────────────────────────────────────
    @app.route("/api/admin/users/<int:user_id>/violation", methods=["POST"])
    @require_csrf
    def admin_user_violation(user_id):
        """管理者可對一般用戶計點；超級管理者可對任何帳號計點（root 除外）"""
        actor = get_current_user_ctx()
        if not actor:
            return json_resp({"ok":False,"msg":"未登入"}), 401
        actor_role = "super_admin" if actor["username"] == "root" else actor["role"]
        if role_rank(actor_role) < role_rank("manager"):
            return json_resp({"ok":False,"msg":"權限不足"}), 403

        try:
            data = request.get_json(force=True) or {}
        except:
            return json_resp({"ok":False,"msg":"Invalid JSON"}), 400

        if not isinstance(data, dict):
            return json_resp({"ok":False,"msg":"Invalid request"}), 400
        points = parse_positive_int(data.get("points", 1))
        if points is None:
            return json_resp({"ok":False,"msg":"違規點數格式錯誤"}), 400
        reason = str(data.get("reason", "手動計點"))[:200]
        triggered_by = "super_admin" if actor_role == "super_admin" else "manager"

        conn = get_db()
        try:
            target = conn.execute(
                "SELECT id, username, role FROM users WHERE id=?", (user_id,)
            ).fetchone()
            if not target:
                return json_resp({"ok":False,"msg":"找不到帳號"}), 404
            if target["username"] == "root":
                return json_resp({"ok":False,"msg":"無法對最高管理者計點"}), 403
            if actor_role == "manager" and target["role"] != "user":
                return json_resp({"ok":False,"msg":"無權對此角色計點"}), 403

            action, msg, new_count = add_violation(
                user_id, target["username"], target["role"],
                points=points, reason=reason,
                triggered_by=triggered_by, actor_username=actor["username"]
            )
            audit("VIOLATION_ADDED", get_client_ip(), user=actor["username"],
                  detail=f"target_id={user_id} action={action} points={points} reason={reason}")
            return json_resp({"ok":True,"msg":msg,"new_count":new_count})
        finally:
            conn.close()
