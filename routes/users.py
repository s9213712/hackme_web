import json
import re
from datetime import datetime, timedelta
from flask import request, send_file

from services.member_levels import apply_member_level_change, ensure_member_level_user_columns
from services.cloud_drive import ensure_cloud_drive_attachment_schema, resolve_file_storage_path, store_cloud_upload
from services.sanction_notices import record_admin_sanction_notice


def register_user_routes(app, deps):
    ACCOUNT_STATUSES = deps["ACCOUNT_STATUSES"]
    MAX_MANAGERS = deps["MAX_MANAGERS"]
    MAX_EXTRA_SUPER_ADMINS = deps["MAX_EXTRA_SUPER_ADMINS"]
    MEMBER_LEVELS = deps["MEMBER_LEVELS"]
    PASSWORD_HISTORY_LIMIT = deps["PASSWORD_HISTORY_LIMIT"]
    ROLE_LABEL = deps["ROLE_LABEL"]
    ROLE_RANK = deps["ROLE_RANK"]
    add_violation = deps["add_violation"]
    audit = deps["audit"]
    check_user_rate_limit = deps["check_user_rate_limit"]
    count_role = deps["count_role"]
    decrypt_field = deps["decrypt_field"]
    encrypt_field = deps["encrypt_field"]
    ensure_user_official_room_membership = deps["ensure_user_official_room_membership"]
    get_client_ip = deps["get_client_ip"]
    get_current_user_ctx = deps["get_current_user_ctx"]
    get_db = deps["get_db"]
    get_ua = deps["get_ua"]
    hash_password = deps["hash_password"]
    hash_token = deps["hash_token"]
    is_feature_enabled = deps["is_feature_enabled"]
    json_resp = deps["json_resp"]
    normalize_text = deps["normalize_text"]
    parse_birthdate = deps["parse_birthdate"]
    parse_positive_int = deps["parse_positive_int"]
    points_service = deps.get("points_service")
    revoke_user_sessions = deps["revoke_user_sessions"]
    require_csrf = deps["require_csrf"]
    require_csrf_safe = deps["require_csrf_safe"]
    SESSION_COOKIE_SAMESITE = deps["SESSION_COOKIE_SAMESITE"]
    SESSION_COOKIE_SECURE = deps["SESSION_COOKIE_SECURE"]
    enforce_password_strength = deps["enforce_password_strength"]
    role_rank = deps["role_rank"]
    score_password_strength = deps["score_password_strength"]
    user_public_payload = deps["user_public_payload"]
    validate_id_number = deps["validate_id_number"]
    validate_password = deps["validate_password"]
    validate_phone = deps["validate_phone"]
    verify_password = deps["verify_password"]
    get_member_level_rule = deps.get("get_member_level_rule")
    storage_root = deps.get("STORAGE_DIR", ".")

    def trim_password_history(conn, user_id):
        conn.execute(
            "DELETE FROM user_passwords WHERE user_id=? AND id NOT IN ("
            "SELECT id FROM user_passwords WHERE user_id=? ORDER BY created_at DESC, id DESC LIMIT ?"
            ")",
            (user_id, user_id, PASSWORD_HISTORY_LIMIT)
        )

    def parse_device_info(raw):
        if not raw:
            return {}
        try:
            import json
            parsed = json.loads(raw)
            return parsed if isinstance(parsed, dict) else {}
        except Exception:
            return {}

    def current_session_hash():
        tok = request.cookies.get("session_token")
        return hash_token(tok) if tok else ""

    def _row_snapshot(row):
        return {key: row[key] for key in row.keys()} if row else {}

    def _sanction_label(data, target):
        parts = []
        if "sanction_status" in data:
            parts.append(f"處分狀態 {target['sanction_status'] or 'none'} -> {normalize_text(data.get('sanction_status')) or 'none'}")
        if data.get("sanction_until"):
            parts.append(f"處分期限 {normalize_text(data.get('sanction_until'))}")
        if "status" in data:
            parts.append(f"帳號狀態 {target['status'] or '-'} -> {normalize_text(data.get('status')) or '-'}")
        if "base_level" in data or "member_level" in data:
            next_level = normalize_text(data.get("base_level") or data.get("member_level"))
            if next_level:
                parts.append(f"會員等級 {target['base_level'] or target['member_level'] or '-'} -> {next_level}")
        return "；".join(parts) or "會員管理處分"

    def _is_punitive_member_update(data, target):
        if "sanction_status" in data:
            next_sanction = normalize_text(data.get("sanction_status")) or "none"
            if next_sanction in {"restricted", "suspended"} and next_sanction != (target["sanction_status"] or "none"):
                return True
        if "status" in data:
            next_status = normalize_text(data.get("status"))
            if next_status and next_status not in {"active", "pending"} and next_status != target["status"]:
                return True
        next_level = normalize_text(data.get("base_level") or data.get("member_level"))
        if next_level in {"restricted", "suspended"} and next_level != (target["base_level"] or target["member_level"]):
            return True
        return False

    def _send_admin_sanction_notice(conn, *, actor, actor_role, target, previous, data):
        reason = normalize_text(data.get("level_update_reason") or data.get("reason") or "會員管理處分")
        action_label = _sanction_label(data, target)
        add_violation(
            target["id"],
            target["username"],
            target["role"],
            points=0,
            reason=f"會員管理處分：{action_label}；原因：{reason}",
            triggered_by=actor_role,
            actor_username=actor["username"],
        )
        latest = conn.execute(
            "SELECT id FROM secure_violations WHERE user_id=? ORDER BY id DESC LIMIT 1",
            (target["id"],),
        ).fetchone()
        if not latest:
            return
        record_admin_sanction_notice(
            conn,
            actor=actor,
            target=target,
            previous=previous,
            violation_id=latest["id"],
            action_label=action_label,
            reason=reason,
        )

    def ensure_avatar_user_columns(conn):
        cols = {row["name"] for row in conn.execute("PRAGMA table_info(users)").fetchall()}
        if "avatar_file_id" not in cols:
            conn.execute("ALTER TABLE users ADD COLUMN avatar_file_id TEXT")
        if "avatar_crop_json" not in cols:
            conn.execute("ALTER TABLE users ADD COLUMN avatar_crop_json TEXT")
        if "updated_at" not in cols:
            conn.execute("ALTER TABLE users ADD COLUMN updated_at TEXT")

    @app.route("/api/account/sessions", methods=["GET"])
    @require_csrf_safe
    def account_sessions():
        actor = get_current_user_ctx()
        if not actor:
            return json_resp({"ok":False,"msg":"未登入"}), 401
        if not is_feature_enabled("feature_account_security_enabled"):
            return json_resp({"ok":False,"msg":"帳號安全功能目前已關閉"}), 503

        token_hash = current_session_hash()
        now = datetime.now().isoformat()
        conn = get_db()
        try:
            rows = conn.execute(
                "SELECT id, token_hash, ip_address, user_agent, device_info, ip_country, expires_at, is_revoked, revoked_at, last_seen, created_at "
                "FROM sessions WHERE user_id=? ORDER BY COALESCE(last_seen, created_at) DESC",
                (actor["id"],)
            ).fetchall()
            sessions = []
            for row in rows:
                sessions.append({
                    "id": row["id"],
                    "ip_address": row["ip_address"] or "",
                    "user_agent": row["user_agent"] or "",
                    "device_info": parse_device_info(row["device_info"] if "device_info" in row.keys() else ""),
                    "ip_country": row["ip_country"] if "ip_country" in row.keys() else None,
                    "expires_at": row["expires_at"],
                    "is_revoked": bool(row["is_revoked"]),
                    "revoked_at": row["revoked_at"],
                    "last_seen": row["last_seen"],
                    "created_at": row["created_at"],
                    "is_current": bool(token_hash and row["token_hash"] == token_hash),
                    "is_active": bool(not row["is_revoked"] and row["expires_at"] > now),
                })
            return json_resp({"ok":True,"sessions":sessions})
        finally:
            conn.close()

    @app.route("/api/account/sessions/<int:session_id>", methods=["DELETE"])
    @require_csrf
    def account_session_revoke(session_id):
        actor = get_current_user_ctx()
        if not actor:
            return json_resp({"ok":False,"msg":"未登入"}), 401
        if not is_feature_enabled("feature_account_security_enabled"):
            return json_resp({"ok":False,"msg":"帳號安全功能目前已關閉"}), 503

        token_hash = current_session_hash()
        conn = get_db()
        try:
            row = conn.execute(
                "SELECT id, token_hash, is_revoked FROM sessions WHERE id=? AND user_id=?",
                (session_id, actor["id"])
            ).fetchone()
            if not row:
                return json_resp({"ok":False,"msg":"找不到 session"}), 404
            conn.execute(
                "UPDATE sessions SET is_revoked=1, revoked_at=? WHERE id=? AND user_id=?",
                (datetime.now().isoformat(), session_id, actor["id"])
            )
            conn.commit()
            audit("ACCOUNT_SESSION_REVOKED", get_client_ip(), user=actor["username"], success=True, ua=get_ua(),
                  detail=f"session_id={session_id},self={row['token_hash'] == token_hash}")
            resp = json_resp({"ok":True,"msg":"裝置 session 已登出","current_revoked":row["token_hash"] == token_hash})
            if row["token_hash"] == token_hash:
                resp.delete_cookie("session_token", path="/", samesite=SESSION_COOKIE_SAMESITE, secure=SESSION_COOKIE_SECURE)
                resp.delete_cookie("csrf_token", path="/", samesite=SESSION_COOKIE_SAMESITE, secure=SESSION_COOKIE_SECURE)
            return resp
        finally:
            conn.close()

    @app.route("/api/account/sessions/logout-all", methods=["POST"])
    @require_csrf
    def account_sessions_logout_all():
        actor = get_current_user_ctx()
        if not actor:
            return json_resp({"ok":False,"msg":"未登入"}), 401
        if not is_feature_enabled("feature_account_security_enabled"):
            return json_resp({"ok":False,"msg":"帳號安全功能目前已關閉"}), 503

        token_hash = current_session_hash()
        keep_current = bool(request.get_json(silent=True) or {}) and bool((request.get_json(silent=True) or {}).get("keep_current"))
        sql = "UPDATE sessions SET is_revoked=1, revoked_at=? WHERE user_id=? AND is_revoked=0"
        params = [datetime.now().isoformat(), actor["id"]]
        if keep_current and token_hash:
            sql += " AND token_hash<>?"
            params.append(token_hash)
        conn = get_db()
        try:
            cur = conn.execute(sql, tuple(params))
            conn.commit()
            audit("ACCOUNT_SESSIONS_REVOKED", get_client_ip(), user=actor["username"], success=True, ua=get_ua(),
                  detail=f"count={cur.rowcount},keep_current={keep_current}")
            resp = json_resp({"ok":True,"msg":"已登出指定裝置","revoked_count":cur.rowcount,"current_revoked":not keep_current})
            if not keep_current:
                resp.delete_cookie("session_token", path="/", samesite=SESSION_COOKIE_SAMESITE, secure=SESSION_COOKIE_SECURE)
                resp.delete_cookie("csrf_token", path="/", samesite=SESSION_COOKIE_SAMESITE, secure=SESSION_COOKIE_SECURE)
            return resp
        finally:
            conn.close()

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
                ensure_member_level_user_columns(conn)
                ensure_avatar_user_columns(conn)
                rows = conn.execute(
                    "SELECT id, username, email, nickname, real_name, birthdate, id_number, phone, status, role, "
                    "member_level, base_level, effective_level, trust_score, points, reputation, violation_score, "
                    "sanction_status, sanction_until, level_updated_at, level_updated_by, level_update_reason, "
                    "password_strength_score, avatar_file_id, avatar_crop_json, blocked_until, violation_count "
                    "FROM users ORDER BY id ASC"
                ).fetchall()
                data = [user_public_payload(r, include_sensitive=False) for r in rows]
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
        identity_governance_enabled = is_feature_enabled("feature_identity_governance_enabled")
        member_level = normalize_text(data.get("member_level")) or "normal"

        if role not in ROLE_RANK:
            return json_resp({"ok":False,"msg":"不支援的角色"}), 400
        if status not in ACCOUNT_STATUSES:
            return json_resp({"ok":False,"msg":"帳號狀態錯誤"}), 400
        if not identity_governance_enabled and "member_level" in data:
            return json_resp({"ok":False,"msg":"身份治理功能目前已關閉"}), 503
        if member_level not in MEMBER_LEVELS:
            return json_resp({"ok":False,"msg":"會員等級錯誤"}), 400
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
                if is_feature_enabled("feature_account_security_enabled"):
                    ok, msg, strength = enforce_password_strength(password, min_score=3)
                    if not ok:
                        return json_resp({"ok":False,"msg":msg,"password_strength":strength}), 400
        else:
            return json_resp({"ok":False,"msg":"新建帳號必須指定密碼"}), 400
        strength = score_password_strength(password)

        conn = get_db()
        try:
            existing = conn.execute("SELECT 1 FROM users WHERE username=?", (username,)).fetchone()
            if existing:
                return json_resp({"ok":False,"msg":"帳號已存在"}), 409
            now = datetime.now().isoformat()
            cur = conn.execute(
                "INSERT INTO users (username, nickname, real_name, birthdate, id_number, phone, role, status, member_level, base_level, effective_level, password_strength_score, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (username, encrypt_field(nickname), encrypt_field(real_name), encrypt_field(birthdate), encrypt_field(id_number), encrypt_field(phone), role, status, member_level, member_level, member_level, strength["score"], now, now)
            )
            conn.execute(
                "INSERT INTO user_passwords (user_id, password_hash, created_at) VALUES (?, ?, ?)",
                (cur.lastrowid, hash_password(password), now)
            )
            new_user_id = cur.lastrowid
            trim_password_history(conn, cur.lastrowid)
            conn.commit()
            if points_service and role in {"manager", "super_admin"} and username != "root":
                try:
                    points_service.award_admin_initial_grant(
                        user_id=new_user_id,
                        actor={"id": actor["id"], "username": actor["username"], "role": actor_role},
                    )
                except Exception as exc:
                    audit("POINTS_ADMIN_INITIAL_GRANT_FAILED", get_client_ip(), user=actor["username"], success=False, ua=get_ua(),
                          detail=f"target={username}, error={exc}")
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
        include_sensitive = is_self or actor["username"] == "root"

        conn = get_db()
        try:
            ensure_member_level_user_columns(conn)
            ensure_avatar_user_columns(conn)
            target = conn.execute(
                "SELECT id, username, nickname, real_name, birthdate, id_number, phone, role, status, "
                "member_level, base_level, effective_level, trust_score, points, reputation, violation_score, "
                "sanction_status, sanction_until, level_updated_at, level_updated_by, level_update_reason, "
                "password_strength_score, avatar_file_id, avatar_crop_json, blocked_until, violation_count FROM users WHERE id=?",
                (user_id,)
            ).fetchone()
            if not target:
                return json_resp({"ok":False,"msg":"找不到帳號"}), 404
            return json_resp({
                "ok": True,
                "user": user_public_payload(target, include_sensitive=include_sensitive)
            })
        finally:
            conn.close()

    def _parse_avatar_crop(raw):
        if not raw:
            return {}
        if isinstance(raw, str):
            try:
                raw = json.loads(raw)
            except Exception:
                return {}
        if not isinstance(raw, dict):
            return {}
        crop = {}
        for key in ("x", "y", "width", "height"):
            try:
                value = int(raw.get(key))
            except Exception:
                continue
            if value < 0:
                continue
            crop[key] = min(value, 10000)
        return crop if {"x", "y", "width", "height"} <= set(crop) else {}

    @app.route("/api/admin/users/<int:user_id>/avatar", methods=["POST"])
    @require_csrf
    def user_avatar_upload(user_id):
        actor = get_current_user_ctx()
        if not actor:
            return json_resp({"ok": False, "msg": "未登入"}), 401
        actor_role = "super_admin" if actor["username"] == "root" else actor["role"]
        is_self = int(actor["id"]) == int(user_id)
        if not is_self and role_rank(actor_role) < role_rank("super_admin"):
            return json_resp({"ok": False, "msg": "只有 root 可修改他人頭像"}), 403
        if "file" not in request.files:
            return json_resp({"ok": False, "msg": "缺少 file"}), 400
        file_storage = request.files["file"]
        mimetype = (getattr(file_storage, "mimetype", "") or "").lower()
        if mimetype not in {"image/jpeg", "image/png", "image/gif"}:
            return json_resp({"ok": False, "msg": "頭像僅支援 JPEG / PNG / GIF"}), 400
        # Enforce extension allowlist (L-1: path traversal + extension validation)
        filename = (getattr(file_storage, "filename", "") or "").lower()
        allowed_exts = {".jpg", ".jpeg", ".png", ".gif"}
        if not any(filename.endswith(ext) for ext in allowed_exts):
            return json_resp({"ok": False, "msg": "頭像僅支援 JPEG / PNG / GIF 副檔名"}), 400
        conn = get_db()
        try:
            ensure_member_level_user_columns(conn)
            ensure_avatar_user_columns(conn)
            ensure_cloud_drive_attachment_schema(conn)
            target = conn.execute("SELECT id, username, role, member_level, effective_level, sanction_status FROM users WHERE id=?", (user_id,)).fetchone()
            if not target:
                return json_resp({"ok": False, "msg": "找不到帳號"}), 404
            rule = get_member_level_rule(conn, target["effective_level"] or target["member_level"]) if get_member_level_rule else None
            result, msg = store_cloud_upload(
                conn,
                actor=dict(target),
                member_rule=rule,
                storage_root=storage_root,
                file_storage=file_storage,
                privacy_mode="public_attachment",
                scan_now=True,
            )
            if msg:
                conn.rollback()
                return json_resp({"ok": False, "msg": msg}), 400
            if result.get("scan_status") not in {"clean", "not_required"}:
                conn.rollback()
                return json_resp({"ok": False, "msg": "頭像未通過安全掃描"}), 400
            crop = _parse_avatar_crop(request.form.get("crop_json"))
            conn.execute(
                "UPDATE users SET avatar_file_id=?, avatar_crop_json=?, updated_at=? WHERE id=?",
                (result["file_id"], json.dumps(crop, ensure_ascii=False), datetime.now().isoformat(), user_id),
            )
            conn.execute(
                """
                INSERT OR IGNORE INTO cloud_file_refs (
                    id, file_id, owner_user_id, context_type, context_id, attached_by, created_at, permission_snapshot_json
                ) VALUES (?, ?, ?, 'avatar', ?, ?, ?, ?)
                """,
                (
                    f"avatar_{user_id}_{result['file_id']}",
                    result["file_id"],
                    user_id,
                    str(user_id),
                    actor["id"],
                    datetime.now().isoformat(),
                    json.dumps({"public_avatar": True, "crop": crop}, ensure_ascii=False),
                ),
            )
            conn.commit()
            audit("USER_AVATAR_UPLOAD", get_client_ip(), user=actor["username"], success=True, ua=get_ua(), detail=f"target_id={user_id},file_id={result['file_id']}")
            return json_resp({"ok": True, "avatar_file_id": result["file_id"], "avatar_crop": crop, "file": result})
        finally:
            conn.close()

    @app.route("/api/admin/users/<int:user_id>/avatar", methods=["GET"])
    @require_csrf_safe
    def user_avatar_get(user_id):
        actor = get_current_user_ctx()
        if not actor:
            return json_resp({"ok": False, "msg": "未登入"}), 401
        # Authorization: only self, admin, or super_admin can view this avatar (L-5)
        actor_role = "super_admin" if actor["username"] == "root" else actor["role"]
        if actor["id"] != user_id and actor_role not in {"admin", "super_admin"}:
            return json_resp({"ok": False, "msg": "權限不足"}), 403
        conn = get_db()
        try:
            ensure_member_level_user_columns(conn)
            ensure_avatar_user_columns(conn)
            ensure_cloud_drive_attachment_schema(conn)
            row = conn.execute(
                """
                SELECT f.storage_path, f.mime_type_plain_for_public, f.scan_status, f.privacy_mode, f.deleted_at
                FROM users u
                JOIN uploaded_files f ON f.id=u.avatar_file_id
                WHERE u.id=?
                """,
                (user_id,),
            ).fetchone()
            if not row or row["deleted_at"]:
                return json_resp({"ok": False, "msg": "尚未設定頭像"}), 404
            if not row["privacy_mode"].startswith("e2ee") and row["scan_status"] not in {"clean", "not_required"}:
                return json_resp({"ok": False, "msg": "頭像尚未通過安全掃描"}), 403
            path = resolve_file_storage_path(storage_root, row["storage_path"])
            if not path.exists() or not path.is_file():
                return json_resp({"ok": False, "msg": "頭像檔案不存在"}), 404
            return send_file(path, mimetype=row["mime_type_plain_for_public"] or "application/octet-stream")
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
        if request.method == "PUT" and not is_self and role_rank(actor_role) < role_rank("manager"):
            return json_resp({"ok":False,"msg":"只有管理者以上可修改他人帳號"}), 403

        conn = get_db()
        try:
            ensure_member_level_user_columns(conn)
            ensure_avatar_user_columns(conn)
            target = conn.execute(
                "SELECT id, username, nickname, real_name, birthdate, id_number, phone, role, status, "
                "member_level, base_level, effective_level, trust_score, points, reputation, violation_score, "
                "sanction_status, sanction_until, level_updated_at, level_updated_by, level_update_reason, "
                "password_strength_score, avatar_file_id, avatar_crop_json, blocked_until, violation_count FROM users WHERE id=?",
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
            if request.method == "PUT" and not is_self and role_rank(actor_role) < role_rank("super_admin"):
                allowed_manager_keys = {"member_level", "base_level", "level_update_reason", "reason"}
                if set(data.keys()) - allowed_manager_keys:
                    return json_resp({"ok":False,"msg":"管理員只能調整一般用戶會員等級；角色、狀態與個資需 root"}), 403

            revoke_sessions_needed = False
            level_changed = False
            previous_target = _row_snapshot(target)
            sanction_notice_needed = False
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
                if val not in ACCOUNT_STATUSES:
                    return json_resp({"ok":False,"msg":"帳號狀態錯誤"}), 400
                if _is_punitive_member_update({"status": val}, target):
                    sanction_notice_needed = True
                updates.append("status=?")
                params.append(val)
                if val != "active":
                    revoke_sessions_needed = True
            if "member_level" in data or "base_level" in data or "sanction_status" in data or "sanction_until" in data:
                if not is_feature_enabled("feature_identity_governance_enabled"):
                    return json_resp({"ok":False,"msg":"身份治理功能目前已關閉"}), 503
                if is_self:
                    return json_resp({"ok":False,"msg":"不可自行變更會員等級"}), 403
                requested_sanction_change = "sanction_status" in data or "sanction_until" in data
                val = normalize_text(data.get("base_level") or data.get("member_level") or target["base_level"] or target["member_level"])
                manager_level_change = (
                    role_rank(actor_role) >= role_rank("manager")
                    and target["role"] == "user"
                    and not requested_sanction_change
                    and val in {"newbie", "normal", "trusted", "vip"}
                )
                if role_rank(actor_role) < role_rank("super_admin") and not manager_level_change:
                    return json_resp({"ok":False,"msg":"管理員只能調整一般用戶的 newbie/normal/trusted/vip 會員等級；處分與角色需 root"}), 403
                level_user, err = apply_member_level_change(
                    conn,
                    user_id,
                    actor=actor["username"],
                    source="root" if actor["username"] == "root" else "admin",
                    base_level=val,
                    sanction_status=normalize_text(data.get("sanction_status")) if "sanction_status" in data else None,
                    sanction_until=normalize_text(data.get("sanction_until")) if data.get("sanction_until") else None,
                    reason=normalize_text(data.get("level_update_reason") or data.get("reason") or "admin user update"),
                )
                if err:
                    return json_resp({"ok":False,"msg":err}), 400
                level_changed = True
                if _is_punitive_member_update(data, target):
                    sanction_notice_needed = True
            if "role" in data:
                if is_self:
                    return json_resp({"ok":False,"msg":"不可自行變更角色"}), 403
                if actor["username"] != "root":
                    return json_resp({"ok":False,"msg":"只有 root 可變更角色"}), 403
                val = normalize_text(data["role"])
                if val not in ROLE_RANK:
                    return json_resp({"ok":False,"msg":"不支援的角色"}), 400
                if target["username"] == "root" and val != "super_admin":
                    return json_resp({"ok":False,"msg":"最高管理者角色不可變更"}), 403
                if val == "manager" and target["role"] != "manager" and count_role("manager") >= MAX_MANAGERS:
                    return json_resp({"ok":False,"msg":f"管理者已達上限（{MAX_MANAGERS} 人）"}), 409
                if val == "super_admin" and target["role"] != "super_admin" and count_role("super_admin") >= MAX_EXTRA_SUPER_ADMINS:
                    return json_resp({"ok":False,"msg":f"非 root 最高管理者已達上限（{MAX_EXTRA_SUPER_ADMINS} 人）"}), 409
                updates.append("role=?")
                params.append(val)
            if "password" in data and isinstance(data["password"], str) and data["password"]:
                action_name = "password_change" if is_self else "admin_password_reset"
                limit = 5 if is_self else 20
                blocked, info = check_user_rate_limit(actor["id"], action_name, max_req=limit, window_sec=3600)
                if blocked:
                    return json_resp({"ok":False,"msg":f"密碼操作過於頻繁（每小時最多 {info['limit']} 次）"}), 429
                pw = data["password"][:128]
                pw_confirm = data.get("password_confirm","") if isinstance(data.get("password_confirm"), str) else ""
                if not pw_confirm:
                    return json_resp({"ok":False,"msg":"請再次輸入新密碼"}), 400
                if pw_confirm != pw:
                    return json_resp({"ok":False,"msg":"兩次密碼輸入不一致"}), 400
                current_row = conn.execute(
                    "SELECT password_hash FROM user_passwords WHERE user_id=? ORDER BY created_at DESC, id DESC LIMIT 1",
                    (user_id,)
                ).fetchone()
                if is_self:
                    current_pw = data.get("current_password","") if isinstance(data.get("current_password"), str) else ""
                    if not current_pw:
                        return json_resp({"ok":False,"msg":"請輸入目前密碼"}), 400
                    if not current_row or not verify_password(current_row["password_hash"], current_pw):
                        return json_resp({"ok":False,"msg":"目前密碼錯誤"}), 403
                if current_row and verify_password(current_row["password_hash"], pw):
                    return json_resp({"ok":False,"msg":"新密碼不可與目前密碼相同"}), 400
                must_follow_password_policy = actor_role != "super_admin" or is_self
                if must_follow_password_policy:
                    ok, msg = validate_password(pw)
                    if not ok:
                        return json_resp({"ok":False,"msg":msg}), 400
                    if is_feature_enabled("feature_account_security_enabled"):
                        ok, msg, strength = enforce_password_strength(pw, min_score=3)
                        if not ok:
                            return json_resp({"ok":False,"msg":msg,"password_strength":strength}), 400
                strength = score_password_strength(pw)
                conn.execute(
                    "INSERT INTO user_passwords (user_id, password_hash, created_at) VALUES (?, ?, ?)",
                    (user_id, hash_password(pw), datetime.now().isoformat())
                )
                updates.append("password_strength_score=?")
                params.append(strength["score"])
                updates.append("password_changed_at=?")
                params.append(datetime.now().isoformat())
                updates.append("must_change_password=0")
                updates.append("is_default_password=0")
                trim_password_history(conn, user_id)
                revoke_sessions_needed = True
            if "username" in data:
                return json_resp({"ok":False,"msg":"不允許變更帳號名稱"}), 400

            pw_payload = "password" in data and isinstance(data["password"], str) and data["password"]
            if not updates and not pw_payload and not level_changed:
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
            elif level_changed:
                conn.commit()
            if sanction_notice_needed and target["username"] != "root" and not is_self:
                _send_admin_sanction_notice(
                    conn,
                    actor=actor,
                    actor_role=actor_role,
                    target=target,
                    previous=previous_target,
                    data=data,
                )
                conn.commit()
            if revoke_sessions_needed:
                revoke_user_sessions(user_id)
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

        action = (normalize_text(data.get("action")) or "").lower() or "block"
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
            if actor["username"] != "root" and role_rank(actor_role) <= role_rank(target["role"]):
                return json_resp({"ok":False,"msg":"無法封鎖同級或更高階帳號"}), 403

            if action == "unblock":
                conn.execute("UPDATE users SET status='active', blocked_until=NULL WHERE id=?", (user_id,))
                conn.commit()
                audit("ADMIN_UNBLOCK_USER", get_client_ip(), user=actor["username"], success=True, ua=get_ua(),
                      detail=f"target_id={user_id}")
                return json_resp({"ok":True,"msg":"帳號已解除封鎖"})

            blocked_until = (datetime.now() + timedelta(minutes=minutes)).isoformat()
            conn.execute("UPDATE users SET status='inactive', blocked_until=? WHERE id=?", (blocked_until, user_id))
            conn.commit()
            revoke_user_sessions(user_id)
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
        if actor["username"] != "root":
            return json_resp({"ok":False,"msg":"只有 root 可晉升帳號"}), 403

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
            if to_role == "super_admin" and count_role("super_admin") >= MAX_EXTRA_SUPER_ADMINS:
                return json_resp({"ok":False,"msg":f"非 root 最高管理者已達上限（{MAX_EXTRA_SUPER_ADMINS} 人）"}), 409

            conn.execute("UPDATE users SET role=?, violation_count=0, updated_at=? WHERE id=?",
                         (to_role, datetime.now().isoformat(), user_id))
            conn.commit()
            if points_service and to_role in {"manager", "super_admin"} and target["username"] != "root":
                try:
                    points_service.award_admin_initial_grant(
                        user_id=user_id,
                        actor={"id": actor["id"], "username": actor["username"], "role": actor_role},
                    )
                except Exception as exc:
                    audit("POINTS_ADMIN_INITIAL_GRANT_FAILED", get_client_ip(), user=actor["username"], success=False, ua=get_ua(),
                          detail=f"target_id={user_id}, error={exc}")
            audit("USER_PROMOTED", get_client_ip(), user=actor["username"],
                  success=True, detail=f"user_id={user_id} {from_role}→{to_role}")
            return json_resp({"ok":True,"msg":f"已升為 {ROLE_LABEL[to_role]}"})
        finally:
            conn.close()

    @app.route("/api/admin/users/<int:user_id>/demote", methods=["POST"])
    @require_csrf
    def admin_user_demote(user_id):
        """超級管理者可將管理者降為一般用戶；可選目標狀態：restricted / suspended / inactive"""
        actor = get_current_user_ctx()
        if not actor:
            return json_resp({"ok":False,"msg":"未登入"}), 401
        actor_role = "super_admin" if actor["username"] == "root" else actor["role"]
        if actor["username"] != "root":
            return json_resp({"ok":False,"msg":"只有 root 可降級帳號"}), 403

        try:
            data = request.get_json(force=True) or {}
        except:
            return json_resp({"ok":False,"msg":"Invalid JSON"}), 400
        target_status = str(data.get("target_status", "inactive")).strip()
        valid_statuses = {"restricted", "suspended", "inactive"}
        if target_status not in valid_statuses:
            return json_resp({"ok":False,"msg":f"無效的目標狀態，支援：{', '.join(valid_statuses)}"}), 400

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
                # Demote user to selected restricted/suspended/inactive state (Bug: demote)
                conn.execute(
                    f"UPDATE users SET status=?, blocked_until=NULL, updated_at=? WHERE id=?",
                    (target_status, datetime.now().isoformat(), user_id)
                )
                conn.commit()
                revoke_user_sessions(user_id)
                audit("USER_DEACTIVATED_BY_ADMIN", get_client_ip(), user=actor["username"],
                      detail=f"user_id={user_id} demoted to {target_status}")
                return json_resp({"ok":True,"msg":f"帳號已降級為 {target_status}"})
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
