import base64
import hashlib
import re
import time
from datetime import datetime, timedelta

import argon2
from flask import make_response, request, send_from_directory


def register_public_routes(app, deps):
    CSRF_TOKEN_TTL = deps["CSRF_TOKEN_TTL"]
    PUBLIC_DIR = deps["PUBLIC_DIR"]
    ROLE_LABEL = deps["ROLE_LABEL"]
    SERVER_APP_NAME = deps.get("SERVER_APP_NAME", "hackme_web")
    SERVER_RELEASE_ID = deps.get("SERVER_RELEASE_ID", deps.get("SERVER_VERSION", "unknown"))
    SERVER_STARTED_AT = deps["SERVER_STARTED_AT"]
    SERVER_VERSION = deps["SERVER_VERSION"]
    SESSION_COOKIE_SAMESITE = deps["SESSION_COOKIE_SAMESITE"]
    SESSION_COOKIE_SECURE = deps["SESSION_COOKIE_SECURE"]
    SESSION_TTL = deps["SESSION_TTL"]
    audit = deps["audit"]
    db_delete_session = deps["db_delete_session"]
    db_get_user_from_token = deps["db_get_user_from_token"]
    db_save_session = deps["db_save_session"]
    decrypt_field = deps["decrypt_field"]
    encrypt_field = deps["encrypt_field"]
    ensure_user_official_room_membership = deps["ensure_user_official_room_membership"]
    get_client_ip = deps["get_client_ip"]
    get_current_user_ctx = deps["get_current_user_ctx"]
    get_db = deps["get_db"]
    get_feature_settings = deps["get_feature_settings"]
    get_member_level_rule = deps.get("get_member_level_rule")
    get_system_settings = deps["get_system_settings"]
    get_ua = deps["get_ua"]
    hash_password = deps["hash_password"]
    is_feature_enabled = deps["is_feature_enabled"]
    is_ip_blocked = deps["is_ip_blocked"]
    is_rate_limited = deps["is_rate_limited"]
    json_resp = deps["json_resp"]
    make_csrf_token = deps["make_csrf_token"]
    make_token = deps["make_token"]
    normalize_text = deps["normalize_text"]
    parse_birthdate = deps["parse_birthdate"]
    record_login_failure = deps["record_login_failure"]
    record_security_event = deps["record_security_event"]
    require_csrf = deps["require_csrf"]
    score_password_strength = deps["score_password_strength"]
    store_csrf_token = deps["store_csrf_token"]
    timing_delay = deps["timing_delay"]
    validate_id_number = deps["validate_id_number"]
    validate_password = deps["validate_password"]
    enforce_password_strength = deps["enforce_password_strength"]
    validate_phone = deps["validate_phone"]
    verify_csrf_double_submit = deps["verify_csrf_double_submit"]
    verify_password = deps["verify_password"]

    def record_login_location(conn, user_id, username, ip, ua):
        ip_hash = hashlib.sha256((ip or "-").encode("utf-8")).hexdigest()
        previous = conn.execute(
            "SELECT 1 FROM login_locations WHERE user_id=? AND ip_hash<>? LIMIT 1",
            (user_id, ip_hash)
        ).fetchone()
        is_suspicious = 1 if previous else 0
        conn.execute(
            "INSERT INTO login_locations (user_id, ip_hash, country, city, login_at, is_suspicious) "
            "VALUES (?, ?, NULL, NULL, ?, ?)",
            (user_id, ip_hash, datetime.now().isoformat(), is_suspicious)
        )
        if is_suspicious:
            record_security_event(
                "login_location_suspicious",
                ip,
                target_user=username,
                detail=f"new_ip_hash={ip_hash[:12]},ua={ua[:80]}",
            )

    @app.route("/")
    def index():
        resp = make_response(send_from_directory(PUBLIC_DIR, "index.html"))
        tok = request.cookies.get("session_token")
        user = db_get_user_from_token(tok) if tok else None
        if not user:
            # Ship a CSRF token for login form — no session needed
            tok = make_csrf_token()
            store_csrf_token(tok, "__public__")
            resp.set_cookie("csrf_token", tok, max_age=3600, httponly=False,
                            samesite=SESSION_COOKIE_SAMESITE, secure=SESSION_COOKIE_SECURE)
        # Logged-in users keep their per-user csrf_token cookie (set at login)
        return resp

    # ── GET CSRF token ─────────────────────────────────────────────────────────────
    @app.route("/api/csrf-token", methods=["GET"])
    def get_csrf_token():
        tok = request.cookies.get("session_token")
        username = db_get_user_from_token(tok) if tok else None
        token = make_csrf_token()
        if not username:
            store_csrf_token(token, "__public__")
            resp = json_resp({"ok":True,"csrf_token":token})
            resp.set_cookie("csrf_token", token, max_age=CSRF_TOKEN_TTL,
                            httponly=False, samesite=SESSION_COOKIE_SAMESITE,
                            secure=SESSION_COOKIE_SECURE)
            return resp
        store_csrf_token(token, username)
        resp = json_resp({"ok":True,"csrf_token":token})
        resp.set_cookie("csrf_token", token, max_age=CSRF_TOKEN_TTL,
                        httponly=False, samesite=SESSION_COOKIE_SAMESITE,
                        secure=SESSION_COOKIE_SECURE)
        return resp

    @app.route("/api/site-config", methods=["GET"])
    def get_site_config():
        settings = get_system_settings()
        features = get_feature_settings()
        return json_resp({
            "ok": True,
            "site_config": {
                "site_bg": settings.get("site_bg"),
                "site_surface": settings.get("site_surface"),
                "site_accent": settings.get("site_accent"),
                "site_accent2": settings.get("site_accent2"),
                "site_text": settings.get("site_text"),
                "site_muted": settings.get("site_muted"),
                "site_layout_mode": settings.get("site_layout_mode"),
                "site_density": settings.get("site_density"),
                "module_chat_min_role": settings.get("module_chat_min_role"),
                "module_community_min_role": settings.get("module_community_min_role"),
                "module_appeals_min_role": settings.get("module_appeals_min_role"),
                "module_accounts_min_role": settings.get("module_accounts_min_role"),
                "maintenance_mode": bool(settings.get("maintenance_mode", False)),
                **features,
            },
            "server_meta": {
                "app": SERVER_APP_NAME,
                "release_id": SERVER_RELEASE_ID,
                "version": SERVER_VERSION,
                "started_at": SERVER_STARTED_AT,
            },
        })

    @app.route("/api/version", methods=["GET"])
    def get_version():
        return json_resp({
            "ok": True,
            "app": SERVER_APP_NAME,
            "release_id": SERVER_RELEASE_ID,
            "version": SERVER_VERSION,
            "started_at": SERVER_STARTED_AT,
            "maintenance_mode": bool(get_system_settings().get("maintenance_mode", False)),
        })

    @app.route("/api/password-strength", methods=["POST"])
    def password_strength():
        ip = get_client_ip()
        blocked, info = is_rate_limited(ip, max_req=30, window_sec=60)
        if blocked:
            return json_resp({"ok": False, "msg": f"請求太頻繁（{info['limit']}次/分鐘）"}), 429
        try:
            data = request.get_json(force=True)
        except Exception:
            return json_resp({"ok": False, "msg": "Invalid JSON"}), 400
        password = data.get("password", "") if isinstance(data, dict) and isinstance(data.get("password"), str) else ""
        result = score_password_strength(password)
        return json_resp({"ok": True, **result})

    @app.route("/api/register", methods=["POST"])
    def register():
        ip, ua = get_client_ip(), get_ua()
        audit("REGISTER_ATTEMPT", ip, ua=ua)
        settings = get_system_settings()
        if not settings.get("allow_register", True):
            audit("REGISTER_DISABLED", ip, ua=ua, detail="allow_register=false")
            return json_resp({"ok":False,"msg":"目前暫停開放註冊"}), 403
        if is_ip_blocked(ip):
            audit("REGISTER_BLOCKED", ip, ua=ua, detail="IP locked")
            return json_resp({"ok":False,"msg":"IP 已被鎖定，請稍後再試"}), 429

        blocked, info = is_rate_limited(ip, max_req=10, window_sec=60)
        if blocked:
            audit("REGISTER_RATELIMIT", ip, ua=ua)
            return json_resp({"ok":False,"msg":f"請求太頻繁（{info['limit']}次/分鐘）"}), 429

        try:    data = request.get_json(force=True)
        except: return json_resp({"ok":False,"msg":"Invalid JSON"}), 400
        if not isinstance(data, dict):
            audit("REGISTER_EMPTY", ip, ua=ua)
            return json_resp({"ok":False,"msg":"Invalid request"}), 400

        # CSRF double-submit check (no session required — safe for register)
        if not verify_csrf_double_submit(data.get("csrf_token", "")):
            audit("REGISTER_CSRF", ip, ua=ua)
            return json_resp({"ok":False,"msg":"Invalid request"}), 403

        username = normalize_text(data.get("username"))
        password = data.get("password","") if isinstance(data.get("password"), str) else ""
        password_confirm = data.get("password_confirm","") if isinstance(data.get("password_confirm"), str) else ""
        nickname = normalize_text(data.get("nickname"))
        real_name = normalize_text(data.get("real_name"))
        id_number = normalize_text(data.get("id_number"))
        birthdate = parse_birthdate(data.get("birthdate"))
        phone = normalize_text(data.get("phone"))

        # Username validation
        if not username:        return json_resp({"ok":False,"msg":"帳號不可為空"}), 400
        if len(username) < 3:  return json_resp({"ok":False,"msg":"帳號至少需要 3 個字元"}), 400
        if len(username) > 32: return json_resp({"ok":False,"msg":"帳號最長 32 字元"}), 400
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

        ok, msg = validate_password(password)
        if not ok:
            audit("REGISTER_BAD_PW", ip, username, ua=ua, detail=msg)
            return json_resp({"ok":False,"msg":msg}), 400
        strength = score_password_strength(password)
        if is_feature_enabled("feature_account_security_enabled"):
            strong_enough, msg, strength = enforce_password_strength(password, min_score=3)
            if not strong_enough:
                audit("REGISTER_WEAK_PW", ip, username, ua=ua, detail=msg)
                return json_resp({"ok": False, "msg": msg, "password_strength": strength}), 400

        conn = get_db()
        try:
            existing = conn.execute("SELECT 1 FROM users WHERE username=?",(username,)).fetchone()
            if existing:
                time.sleep(0.3)
                audit("REGISTER_DUP", ip, username, ua=ua, success=False)
                # Return generic — don't reveal account exists
                return json_resp({"ok":False,"msg":"註冊失敗，請稍後再試"}), 409

            now = datetime.now().isoformat()
            cur = conn.execute(
                "INSERT INTO users (username, nickname, real_name, birthdate, id_number, phone, status, role, member_level, base_level, effective_level, password_strength_score, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, 'pending', 'user', 'newbie', 'newbie', 'newbie', ?, ?, ?)",
                (username, encrypt_field(nickname), encrypt_field(real_name), encrypt_field(birthdate), encrypt_field(id_number), encrypt_field(phone), strength["score"], now, now)
            )
            conn.execute(
                "INSERT INTO user_passwords (user_id, password_hash, created_at) VALUES (?, ?, ?)",
                (cur.lastrowid, hash_password(password), now)
            )
            conn.commit()
            audit("REGISTER_PENDING", ip, username, ua=ua, success=True, detail="awaiting manager approval")
            return json_resp({"ok":True,"msg":"註冊申請已送出，需經管理員或最高管理者審核後才能登入"})
        finally:
            conn.close()

    @app.route("/api/login", methods=["POST"])
    @require_csrf
    def login():
        ip, ua = get_client_ip(), get_ua()
        settings = get_system_settings()

        # Check blocked BEFORE anything else
        if is_ip_blocked(ip):
            audit("LOGIN_BLOCKED", ip, ua=ua, detail="IP locked")
            timing_delay()  # still do delay so blocked vs not-blocked timing looks same
            return json_resp({"ok":False,"msg":"登入失敗（帳號或密碼錯誤）"}), 429

        blocked, info = is_rate_limited(ip, max_req=30, window_sec=60)
        if blocked:
            audit("LOGIN_RATELIMIT", ip, ua=ua)
            timing_delay()
            return json_resp({"ok":False,"msg":"請求太頻繁，請稍後再試"}), 429

        try:
            data = request.get_json(force=True)
        except Exception:
            record_login_failure(ip, ua=ua, detail="invalid_json")
            timing_delay()
            return json_resp({"ok":False,"msg":"Invalid JSON"}), 400
        if not isinstance(data, dict):
            record_login_failure(ip, ua=ua, detail="json_not_object")
            timing_delay()
            return json_resp({"ok":False,"msg":"Invalid request"}), 400

        username = (data.get("username","") if isinstance(data.get("username"), str) else "").strip()
        password = data.get("password","") if isinstance(data.get("password"), str) else ""

        # Generic blank check — same message regardless of which field
        if not username or not password:
            record_login_failure(ip, username, ua=ua, detail="blank_field")
            timing_delay()
            return json_resp({"ok":False,"msg":"請填寫帳號與密碼"}), 400

        conn = get_db()
        try:
            user_row = conn.execute(
                "SELECT id, username, status, blocked_until, locked_until, failed_login_count, role, "
                "must_change_password, is_default_password FROM users WHERE username=?",
                (username,)
            ).fetchone()

            # Always do timing-consuming verify to prevent timing oracles
            pw_hash = None
            if user_row:
                pw_row = conn.execute(
                    "SELECT password_hash FROM user_passwords WHERE user_id=? ORDER BY created_at DESC LIMIT 1",
                    (user_row["id"],)
                ).fetchone()
                if pw_row:
                    pw_hash = pw_row["password_hash"]

            # Perform verify with constant-ish delay regardless of user existence
            if pw_hash:
                verified = verify_password(pw_hash, password)
            else:
                # Fake hash work — user doesn't exist, still burn same CPU time
                # Properly formatted: 16-byte salt → 22 b64 chars, 32-byte hash → 43 b64 chars
                fake_salt = base64.urlsafe_b64encode(b"fakesaltPASSSalt0").decode()[:22]
                fake_hsh  = base64.urlsafe_b64encode(b"f" * 32).decode()[:43]
                try:
                    verify_password(f"$argon2id$v=19$m=65536,t=3,p=4${fake_salt}${fake_hsh}", password)
                except argon2.exceptions.VerifyMismatchError:
                    pass  # expected — always fails
                verified = False

            # ALWAYS add jitter delay to obscure timing differences
            timing_delay()

            now = datetime.now().isoformat()
            account_security_enabled = is_feature_enabled("feature_account_security_enabled")
            if verified:
                if account_security_enabled and user_row["locked_until"]:
                    try:
                        locked_until = datetime.fromisoformat(user_row["locked_until"])
                        if datetime.now() < locked_until:
                            audit("LOGIN_ACCOUNT_LOCKED", ip, username, ua=ua, detail=f"locked_until={user_row['locked_until']}")
                            return json_resp({"ok":False,"msg":"登入失敗（帳號或密碼錯誤）"}), 401
                    except Exception:
                        pass
                if user_row["blocked_until"]:
                    try:
                        blocked_until = datetime.fromisoformat(user_row["blocked_until"])
                        if datetime.now() < blocked_until:
                            audit("LOGIN_BLOCKED_TEMP", ip, username, ua=ua, detail=f"blocked_until={user_row['blocked_until']}")
                            return json_resp({"ok":False,"msg":"登入失敗（帳號或密碼錯誤）"}), 401
                    except Exception:
                        pass
                if user_row["status"] != "active":
                    audit("LOGIN_INACTIVE", ip, username, ua=ua, success=False)
                    return json_resp({"ok":False,"msg":"登入失敗（帳號或密碼錯誤）"}), 401

                # Log successful attempt
                conn.execute(
                    "INSERT INTO login_attempts (user_id, ip_address, user_agent, success, attempted_at) VALUES (?, ?, ?, 1, ?)",
                    (user_row["id"], ip, ua, now)
                )
                if account_security_enabled:
                    conn.execute(
                        "UPDATE users SET failed_login_count=0, locked_until=NULL, last_login_at=?, updated_at=? WHERE id=?",
                        (now, now, user_row["id"])
                    )
                    record_login_location(conn, user_row["id"], username, ip, ua)
                conn.commit()

                # Create token + save session to DB
                token = make_token(username)
                db_save_session(user_row["id"], token, ip, ua)
                ensure_user_official_room_membership(conn, user_row["id"])
                conn.commit()

                audit("LOGIN_OK", ip, username, ua=ua, success=True)
                resp = json_resp({
                    "ok": True,
                    "msg": "恭喜登入成功",
                    "must_change_password": bool(user_row["must_change_password"] or 0),
                    "is_default_password": bool(user_row["is_default_password"] or 0),
                })
                resp.set_cookie("session_token", token, max_age=SESSION_TTL,
                                httponly=True, samesite=SESSION_COOKIE_SAMESITE,
                                secure=SESSION_COOKIE_SECURE)
                # Invalidate the public CSRF token and issue a fresh per-user token
                new_csrf = make_csrf_token()
                store_csrf_token(new_csrf, username)
                resp.set_cookie("csrf_token", new_csrf, max_age=CSRF_TOKEN_TTL,
                                httponly=False, samesite=SESSION_COOKIE_SAMESITE,
                                secure=SESSION_COOKIE_SECURE)
                return resp
            else:
                # Log failed attempt
                user_id_for_log = user_row["id"] if user_row else None
                conn.execute(
                    "INSERT INTO login_attempts (user_id, ip_address, user_agent, success, attempted_at) VALUES (?, ?, ?, 0, ?)",
                    (user_id_for_log, ip, ua, now)
                )
                conn.commit()
                if account_security_enabled and user_row:
                    fail_count = int(user_row["failed_login_count"] or 0) + 1
                    lock_limit = max(1, int(settings.get("max_login_failures", 5)))
                    updates = ["failed_login_count=?", "updated_at=?"]
                    params = [fail_count, now]
                    if fail_count >= lock_limit:
                        locked_until = (datetime.now() + timedelta(minutes=max(1, int(settings.get("block_duration_minutes", 10))))).isoformat()
                        updates.append("locked_until=?")
                        params.append(locked_until)
                        audit("LOGIN_ACCOUNT_LOCKED", ip, username, ua=ua, detail=f"failed_login_count={fail_count},locked_until={locked_until}")
                    params.append(user_row["id"])
                    conn.execute("UPDATE users SET " + ", ".join(updates) + " WHERE id=?", params)
                    conn.commit()
                record_login_failure(ip, username=username, ua=ua, detail="bad_credentials")

                # Generic message — never distinguish "no user" from "bad pw"
                return json_resp({"ok":False,"msg":"登入失敗（帳號或密碼錯誤）"}), 401
        finally:
            conn.close()

    @app.route("/api/logout", methods=["POST"])
    @require_csrf
    def logout():
        ip, ua, tok = get_client_ip(), get_ua(), request.cookies.get("session_token")
        user = db_get_user_from_token(tok) if tok else None
        if tok:
            db_delete_session(tok)
        audit("LOGOUT", ip, user=user or "-", ua=ua, success=bool(user))
        resp = json_resp({"ok":True,"msg":"已登出"})
        resp.delete_cookie("session_token", path="/", samesite=SESSION_COOKIE_SAMESITE, secure=SESSION_COOKIE_SECURE)
        resp.delete_cookie("csrf_token", path="/", samesite=SESSION_COOKIE_SAMESITE, secure=SESSION_COOKIE_SECURE)
        return resp

    @app.route("/api/me", methods=["GET"])
    def me():
        ctx = get_current_user_ctx()
        if not ctx:
            return json_resp({"ok":False,"msg":"未登入"}), 401
        role = "super_admin" if ctx["username"] == "root" else ctx["role"]
        effective_level = dict(ctx).get("effective_level") or dict(ctx).get("member_level") or "normal"
        session_idle_timeout_minutes = 3
        if get_member_level_rule:
            conn = get_db()
            try:
                rule = get_member_level_rule(conn, effective_level) or {}
                session_idle_timeout_minutes = max(1, int(rule.get("session_idle_timeout_minutes") or 3))
            finally:
                conn.close()
        return json_resp({
            "ok": True,
            "id": ctx["id"],
            "username": ctx["username"],
            "role": role,
            "role_label": ROLE_LABEL.get(role, role),
            "status": ctx["status"],
            "base_level": dict(ctx).get("base_level") or dict(ctx).get("member_level") or "normal",
            "effective_level": effective_level,
            "session_idle_timeout_minutes": session_idle_timeout_minutes,
            "trust_score": dict(ctx).get("trust_score") or 0,
            "reputation": dict(ctx).get("reputation") or 0,
            "violation_score": dict(ctx).get("violation_score") or dict(ctx).get("violation_count") or 0,
            "sanction_status": dict(ctx).get("sanction_status") or "none",
            "sanction_until": dict(ctx).get("sanction_until"),
            "must_change_password": bool(dict(ctx).get("must_change_password") or 0),
            "is_default_password": bool(dict(ctx).get("is_default_password") or 0),
            "nickname": decrypt_field(ctx["nickname"]),
            "birthdate": decrypt_field(ctx["birthdate"]),
            "chat_violation_warned": dict(ctx).get("chat_violation_warned") or 0,
        })
