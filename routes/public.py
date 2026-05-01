import base64
import hashlib
import re
from datetime import datetime, timedelta

import argon2
from flask import make_response, request, send_from_directory

from services.access_controls import verify_internal_test_token
from services.account_recovery import (
    create_password_reset_review_request,
    create_recovery_token,
    ensure_account_recovery_schema,
    lookup_valid_token,
    mark_token_used,
    normalize_email,
    queue_mail,
)
from services.captcha import create_captcha_challenge, normalize_captcha_mode, verify_captcha_response


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
    delete_csrf_token = deps.get("delete_csrf_token", lambda token: None)
    delete_csrf_tokens_for_username = deps.get("delete_csrf_tokens_for_username", lambda username: None)
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
    points_service = deps.get("points_service")
    record_login_failure = deps["record_login_failure"]
    record_security_event = deps["record_security_event"]
    require_csrf = deps["require_csrf"]
    revoke_user_sessions = deps.get("revoke_user_sessions", lambda user_id: 0)
    score_password_strength = deps["score_password_strength"]
    store_csrf_token = deps["store_csrf_token"]
    timing_delay = deps["timing_delay"]
    validate_id_number = deps["validate_id_number"]
    validate_password = deps["validate_password"]
    enforce_password_strength = deps["enforce_password_strength"]
    validate_phone = deps["validate_phone"]
    verify_csrf_double_submit = deps["verify_csrf_double_submit"]
    verify_csrf_token = deps.get("verify_csrf_token", lambda token, username: False)
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

    def generic_recovery_response():
        return json_resp({"ok": True, "msg": "如果資料符合，系統會寄出後續操作通知"})

    def password_reset_mode():
        mode = str(get_system_settings().get("password_reset_mode") or "admin_review").strip().lower()
        return mode if mode in {"admin_review", "email_token"} else "admin_review"

    def current_server_mode(conn):
        try:
            row = conn.execute("SELECT current_mode FROM server_modes WHERE id=1").fetchone()
            return str(row["current_mode"] or "test") if row else "test"
        except Exception:
            return "test"

    def internal_test_login_allowed(settings, data):
        token = (
            str(data.get("internal_test_token") or "").strip()
            or str(data.get("login_token") or "").strip()
            or request.headers.get("X-Internal-Test-Token", "").strip()
        )
        return verify_internal_test_token(
            token,
            settings.get("internal_test_login_token_hash", ""),
            settings.get("internal_test_login_token_expires_at", ""),
        )

    def production_login_conflict(conn, user_id, ip, now_iso):
        if current_server_mode(conn) != "production":
            return None
        try:
            ip_conflict = conn.execute(
                """
                SELECT s.user_id, u.username
                FROM sessions s
                LEFT JOIN users u ON u.id=s.user_id
                WHERE COALESCE(s.is_revoked, 0)=0
                  AND s.expires_at>?
                  AND s.ip_address=?
                  AND s.user_id<>?
                LIMIT 1
                """,
                (now_iso, ip, user_id),
            ).fetchone()
            if ip_conflict:
                return {
                    "kind": "ip_reused_by_other_account",
                    "msg": "正式上線模式禁止同一 IP 同時登入多個帳號，請先登出原帳號",
                    "detail": f"active_user_id={ip_conflict['user_id']},active_username={ip_conflict['username'] or '-'}",
                }
            account_conflict = conn.execute(
                """
                SELECT ip_address
                FROM sessions
                WHERE user_id=?
                  AND COALESCE(is_revoked, 0)=0
                  AND expires_at>?
                  AND ip_address IS NOT NULL
                  AND ip_address<>?
                LIMIT 1
                """,
                (user_id, now_iso, ip),
            ).fetchone()
            if account_conflict:
                return {
                    "kind": "account_active_from_other_ip",
                    "msg": "正式上線模式禁止同一帳號同時從不同 IP 登入，請先登出其他裝置",
                    "detail": f"active_ip={account_conflict['ip_address']}",
                }
        except Exception as exc:
            return {
                "kind": "session_policy_check_failed",
                "msg": "正式上線模式登入安全檢查失敗，請稍後再試",
                "detail": f"error={exc}",
            }
        return None

    def find_recovery_user(conn, identifier):
        ident = str(identifier or "").strip()
        if not ident:
            return None
        email = normalize_email(ident)
        if email:
            return conn.execute(
                "SELECT id, username, email, status, email_verified FROM users WHERE lower(email)=lower(?) LIMIT 1",
                (email,),
            ).fetchone()
        username = normalize_text(ident)
        if not username:
            return None
        return conn.execute(
            "SELECT id, username, email, status, email_verified FROM users WHERE username=? LIMIT 1",
            (username,),
        ).fetchone()

    def trim_password_history(conn, user_id, limit=5):
        conn.execute(
            "DELETE FROM user_passwords WHERE user_id=? AND id NOT IN ("
            "SELECT id FROM user_passwords WHERE user_id=? ORDER BY created_at DESC, id DESC LIMIT ?"
            ")",
            (user_id, user_id, int(limit)),
        )

    def ensure_public_account_columns(conn):
        cols = {row["name"] for row in conn.execute("PRAGMA table_info(users)").fetchall()}
        additions = (
            ("email", "TEXT"),
            ("email_verified", "INTEGER NOT NULL DEFAULT 0"),
            ("failed_login_count", "INTEGER NOT NULL DEFAULT 0"),
            ("locked_until", "TEXT"),
            ("last_login_at", "TEXT"),
            ("password_strength_score", "INTEGER NOT NULL DEFAULT 0"),
            ("password_changed_at", "TEXT"),
            ("must_change_password", "INTEGER NOT NULL DEFAULT 0"),
            ("is_default_password", "INTEGER NOT NULL DEFAULT 0"),
            ("updated_at", "TEXT"),
        )
        for name, ddl in additions:
            if name not in cols:
                conn.execute(f"ALTER TABLE users ADD COLUMN {name} {ddl}")

    @app.route("/")
    def index():
        resp = make_response(send_from_directory(PUBLIC_DIR, "index.html"))
        tok = request.cookies.get("session_token")
        user = db_get_user_from_token(tok) if tok else None
        csrf_owner = user or "__public__"
        csrf_cookie = request.cookies.get("csrf_token", "")
        if not csrf_cookie or not verify_csrf_token(csrf_cookie, csrf_owner):
            csrf_cookie = make_csrf_token()
            store_csrf_token(csrf_cookie, csrf_owner)
            resp.set_cookie("csrf_token", csrf_cookie, max_age=CSRF_TOKEN_TTL,
                            httponly=False, samesite=SESSION_COOKIE_SAMESITE,
                            secure=SESSION_COOKIE_SECURE)
        return resp

    # ── GET CSRF token ─────────────────────────────────────────────────────────────
    @app.route("/api/csrf-token", methods=["GET"])
    def get_csrf_token():
        tok = request.cookies.get("session_token")
        username = db_get_user_from_token(tok) if tok else None
        owner = username or "__public__"
        token = request.cookies.get("csrf_token", "")
        if not token or not verify_csrf_token(token, owner):
            token = make_csrf_token()
            store_csrf_token(token, owner)
        resp = json_resp({"ok":True,"csrf_token":token})
        resp.set_cookie("csrf_token", token, max_age=CSRF_TOKEN_TTL,
                        httponly=False, samesite=SESSION_COOKIE_SAMESITE,
                        secure=SESSION_COOKIE_SECURE)
        return resp

    @app.route("/api/site-config", methods=["GET"])
    def get_site_config():
        settings = get_system_settings()
        features = get_feature_settings()
        conn = get_db()
        try:
            server_mode = current_server_mode(conn)
        finally:
            conn.close()
        return json_resp({
            "ok": True,
            "site_config": {
                "server_mode": server_mode,
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
                "password_reset_mode": settings.get("password_reset_mode", "admin_review"),
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

    @app.route("/api/captcha/challenge", methods=["GET"])
    def captcha_challenge():
        ip = get_client_ip()
        settings = get_system_settings()
        mode = normalize_captcha_mode(settings.get("captcha_mode"))
        if mode == "turnstile":
            return json_resp({
                "ok": True,
                "captcha": {
                    "required": True,
                    "mode": "turnstile",
                    "site_key": settings.get("captcha_turnstile_site_key", ""),
                },
            })
        conn = get_db()
        try:
            challenge = create_captcha_challenge(
                conn,
                mode=mode,
                ttl_seconds=settings.get("captcha_ttl_seconds", 300),
                ip=ip,
            )
            conn.commit()
            return json_resp({"ok": True, "captcha": challenge})
        finally:
            conn.close()

    @app.route("/api/register", methods=["POST"])
    @require_csrf
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

        conn = get_db()
        try:
            captcha_ok, captcha_msg = verify_captcha_response(conn, settings, data, ip=ip)
            if captcha_ok:
                conn.commit()
            else:
                audit("REGISTER_CAPTCHA_FAIL", ip, ua=ua, success=False, detail=captcha_msg)
                return json_resp({"ok":False,"msg":captcha_msg}), 400
        finally:
            conn.close()

        username = normalize_text(data.get("username"))
        password = data.get("password","") if isinstance(data.get("password"), str) else ""
        password_confirm = data.get("password_confirm","") if isinstance(data.get("password_confirm"), str) else ""
        nickname = normalize_text(data.get("nickname"))
        real_name = normalize_text(data.get("real_name"))
        id_number = normalize_text(data.get("id_number"))
        birthdate = parse_birthdate(data.get("birthdate"))
        phone = normalize_text(data.get("phone"))
        email = normalize_email(data.get("email"))

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
                timing_delay()
                audit("REGISTER_DUP", ip, username, ua=ua, success=False)
                # Return generic — don't reveal account exists
                return json_resp({"ok":False,"msg":"註冊失敗，請稍後再試"}), 409

            # Always do timing-delay to normalize response time (Timing Oracle mitigation)
            timing_delay()

            now = datetime.now().isoformat()
            cur = conn.execute(
                "INSERT INTO users (username, email, nickname, real_name, birthdate, id_number, phone, status, role, member_level, base_level, effective_level, password_strength_score, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', 'user', 'newbie', 'newbie', 'newbie', ?, ?, ?)",
                (username, email or None, encrypt_field(nickname), encrypt_field(real_name), encrypt_field(birthdate), encrypt_field(id_number), encrypt_field(phone), strength["score"], now, now)
            )
            conn.execute(
                "INSERT INTO user_passwords (user_id, password_hash, created_at) VALUES (?, ?, ?)",
                (cur.lastrowid, hash_password(password), now)
            )
            conn.commit()
            new_user_id = cur.lastrowid
            if points_service:
                try:
                    points_service.award_signup_bonus(
                        user_id=new_user_id,
                        actor={"id": new_user_id, "username": username, "role": "user"},
                    )
                except Exception as exc:
                    audit("POINTS_SIGNUP_BONUS_FAILED", ip, username, ua=ua, success=False, detail=str(exc))
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
            ensure_public_account_columns(conn)
            user_row = conn.execute(
                "SELECT id, username, status, blocked_until, locked_until, failed_login_count, role, "
                "email, email_verified, must_change_password, is_default_password FROM users WHERE username=?",
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
                if settings.get("require_email_verification") and not bool(user_row["email_verified"] or 0):
                    audit("LOGIN_EMAIL_UNVERIFIED", ip, username, ua=ua, success=False)
                    return json_resp({"ok":False,"msg":"登入失敗（帳號或密碼錯誤）"}), 401
                if current_server_mode(conn) == "internal_test" and user_row["username"] != "root":
                    if not internal_test_login_allowed(settings, data):
                        conn.execute(
                            "INSERT INTO login_attempts (user_id, ip_address, user_agent, success, attempted_at) VALUES (?, ?, ?, 0, ?)",
                            (user_row["id"], ip, ua, now),
                        )
                        conn.commit()
                        audit("LOGIN_INTERNAL_TEST_TOKEN_REQUIRED", ip, username, ua=ua, success=False)
                        return json_resp({"ok":False,"msg":"目前是內測模式，請輸入 root 提供的內測 token"}), 403

                conflict = production_login_conflict(conn, user_row["id"], ip, now)
                if conflict:
                    conn.execute(
                        "INSERT INTO login_attempts (user_id, ip_address, user_agent, success, attempted_at) VALUES (?, ?, ?, 0, ?)",
                        (user_row["id"], ip, ua, now),
                    )
                    conn.commit()
                    audit(
                        "LOGIN_PRODUCTION_SESSION_CONFLICT",
                        ip,
                        username,
                        ua=ua,
                        success=False,
                        detail=f"{conflict['kind']};{conflict['detail']}",
                    )
                    return json_resp({"ok":False,"msg":conflict["msg"]}), 403

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

                if points_service and user_row["username"] != "root" and user_row["role"] in {"manager", "super_admin"}:
                    try:
                        points_service.award_admin_weekly_salary(
                            user_id=user_row["id"],
                            actor={"id": user_row["id"], "username": user_row["username"], "role": user_row["role"]},
                        )
                    except Exception as exc:
                        audit("POINTS_ADMIN_SALARY_FAILED", ip, username, ua=ua, success=False, detail=str(exc))

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

    @app.route("/api/password-reset/request", methods=["POST"])
    @require_csrf
    def password_reset_request():
        ip, ua = get_client_ip(), get_ua()
        blocked, info = is_rate_limited(f"password-reset:{ip}", max_req=5, window_sec=3600)
        if blocked:
            return json_resp({"ok": False, "msg": f"請求太頻繁（每小時最多 {info['limit']} 次）"}), 429
        try:
            data = request.get_json(force=True)
        except Exception:
            return json_resp({"ok": False, "msg": "Invalid JSON"}), 400
        identifier = data.get("username_or_email") or data.get("username") or data.get("email") if isinstance(data, dict) else ""
        conn = get_db()
        try:
            ensure_public_account_columns(conn)
            ensure_account_recovery_schema(conn)
            row = find_recovery_user(conn, identifier)
            mode = password_reset_mode()
            if mode == "email_token" and row and row["status"] == "active" and row["email"]:
                token = create_recovery_token(conn, user_id=row["id"], purpose="password_reset", ip=ip, user_agent=ua, ttl_minutes=60)
                queue_mail(
                    conn,
                    recipient=row["email"],
                    subject=f"{SERVER_APP_NAME} password reset",
                    body=f"Password reset token for {row['username']}:\n{token}\nThis token expires in 60 minutes.",
                    kind="password_reset",
                )
                audit("PASSWORD_RESET_REQUESTED", ip, user=row["username"], ua=ua, success=True)
            elif mode == "admin_review" and row and row["status"] == "active":
                request_id, created = create_password_reset_review_request(
                    conn,
                    user_id=row["id"],
                    identifier=identifier,
                    ip=ip,
                    user_agent=ua,
                )
                audit(
                    "PASSWORD_RESET_REVIEW_REQUESTED",
                    ip,
                    user=row["username"],
                    ua=ua,
                    success=True,
                    detail=f"review_request_id={request_id},created={created}",
                )
            else:
                audit("PASSWORD_RESET_REQUESTED", ip, user="-", ua=ua, success=True, detail="generic_no_delivery")
            conn.commit()
            timing_delay()
            if mode == "admin_review":
                return json_resp({"ok": True, "msg": "如果資料符合，系統會建立密碼重設審核申請"})
            return generic_recovery_response()
        finally:
            conn.close()

    @app.route("/api/password-reset/confirm", methods=["POST"])
    @require_csrf
    def password_reset_confirm():
        ip, ua = get_client_ip(), get_ua()
        try:
            data = request.get_json(force=True)
        except Exception:
            return json_resp({"ok": False, "msg": "Invalid JSON"}), 400
        if not isinstance(data, dict):
            return json_resp({"ok": False, "msg": "Invalid request"}), 400
        token = str(data.get("token") or "").strip()
        password = data.get("password", "") if isinstance(data.get("password"), str) else ""
        password_confirm = data.get("password_confirm", "") if isinstance(data.get("password_confirm"), str) else ""
        if not token:
            return json_resp({"ok": False, "msg": "驗證碼不可為空"}), 400
        if password != password_confirm:
            return json_resp({"ok": False, "msg": "兩次密碼輸入不一致"}), 400
        conn = get_db()
        try:
            ensure_public_account_columns(conn)
            token_row = lookup_valid_token(conn, token=token, purpose="password_reset")
            if not token_row:
                audit("PASSWORD_RESET_TOKEN_INVALID", ip, ua=ua, success=False)
                return json_resp({"ok": False, "msg": "驗證碼無效或已過期"}), 400
            target_is_root = str(token_row["username"] or "").strip().lower() == "root"
            if not target_is_root:
                ok, msg = validate_password(password)
                if not ok:
                    return json_resp({"ok": False, "msg": msg}), 400
                if is_feature_enabled("feature_account_security_enabled"):
                    ok, msg, strength = enforce_password_strength(password, min_score=3)
                    if not ok:
                        return json_resp({"ok": False, "msg": msg, "password_strength": strength}), 400
                else:
                    strength = score_password_strength(password)
            else:
                strength = score_password_strength(password)
            current_row = conn.execute(
                "SELECT password_hash FROM user_passwords WHERE user_id=? ORDER BY created_at DESC, id DESC LIMIT 1",
                (token_row["user_id"],),
            ).fetchone()
            if current_row and verify_password(current_row["password_hash"], password):
                return json_resp({"ok": False, "msg": "新密碼不可與目前密碼相同"}), 400
            now = datetime.now().isoformat()
            conn.execute(
                "INSERT INTO user_passwords (user_id, password_hash, created_at) VALUES (?, ?, ?)",
                (token_row["user_id"], hash_password(password), now),
            )
            conn.execute(
                "UPDATE users SET password_strength_score=?, password_changed_at=?, must_change_password=0, is_default_password=0, failed_login_count=0, locked_until=NULL, updated_at=? WHERE id=?",
                (strength["score"], now, now, token_row["user_id"]),
            )
            mark_token_used(conn, token_row["id"])
            trim_password_history(conn, token_row["user_id"])
            conn.commit()
            revoke_user_sessions(token_row["user_id"])
            audit("PASSWORD_RESET_CONFIRMED", ip, user=token_row["username"], ua=ua, success=True)
            return json_resp({"ok": True, "msg": "密碼已重設，請重新登入"})
        finally:
            conn.close()

    @app.route("/api/email-verification/request", methods=["POST"])
    @require_csrf
    def email_verification_request():
        ip, ua = get_client_ip(), get_ua()
        blocked, info = is_rate_limited(f"email-verify:{ip}", max_req=5, window_sec=3600)
        if blocked:
            return json_resp({"ok": False, "msg": f"請求太頻繁（每小時最多 {info['limit']} 次）"}), 429
        try:
            data = request.get_json(force=True)
        except Exception:
            return json_resp({"ok": False, "msg": "Invalid JSON"}), 400
        identifier = data.get("username_or_email") or data.get("username") or data.get("email") if isinstance(data, dict) else ""
        conn = get_db()
        try:
            ensure_public_account_columns(conn)
            ensure_account_recovery_schema(conn)
            row = find_recovery_user(conn, identifier)
            if row and row["email"] and not bool(row["email_verified"] or 0):
                token = create_recovery_token(conn, user_id=row["id"], purpose="email_verify", ip=ip, user_agent=ua, ttl_minutes=1440)
                queue_mail(
                    conn,
                    recipient=row["email"],
                    subject=f"{SERVER_APP_NAME} email verification",
                    body=f"Email verification token for {row['username']}:\n{token}\nThis token expires in 24 hours.",
                    kind="email_verify",
                )
                audit("EMAIL_VERIFICATION_REQUESTED", ip, user=row["username"], ua=ua, success=True)
            else:
                audit("EMAIL_VERIFICATION_REQUESTED", ip, user="-", ua=ua, success=True, detail="generic_no_delivery")
            conn.commit()
            timing_delay()
            return generic_recovery_response()
        finally:
            conn.close()

    @app.route("/api/email-verification/confirm", methods=["POST"])
    @require_csrf
    def email_verification_confirm():
        ip, ua = get_client_ip(), get_ua()
        try:
            data = request.get_json(force=True)
        except Exception:
            return json_resp({"ok": False, "msg": "Invalid JSON"}), 400
        token = str(data.get("token") or "").strip() if isinstance(data, dict) else ""
        if not token:
            return json_resp({"ok": False, "msg": "驗證碼不可為空"}), 400
        conn = get_db()
        try:
            ensure_public_account_columns(conn)
            token_row = lookup_valid_token(conn, token=token, purpose="email_verify")
            if not token_row:
                audit("EMAIL_VERIFICATION_TOKEN_INVALID", ip, ua=ua, success=False)
                return json_resp({"ok": False, "msg": "驗證碼無效或已過期"}), 400
            now = datetime.now().isoformat()
            conn.execute("UPDATE users SET email_verified=1, updated_at=? WHERE id=?", (now, token_row["user_id"]))
            mark_token_used(conn, token_row["id"])
            conn.commit()
            audit("EMAIL_VERIFIED", ip, user=token_row["username"], ua=ua, success=True)
            return json_resp({"ok": True, "msg": "Email 已完成驗證"})
        finally:
            conn.close()

    @app.route("/api/logout", methods=["POST"])
    @require_csrf
    def logout():
        ip, ua, tok = get_client_ip(), get_ua(), request.cookies.get("session_token")
        user = db_get_user_from_token(tok) if tok else None
        if tok:
            db_delete_session(tok)
        if user:
            delete_csrf_tokens_for_username(user)
        else:
            delete_csrf_token(request.cookies.get("csrf_token", ""))
        audit("LOGOUT", ip, user=user or "-", ua=ua, success=bool(user))
        resp = json_resp({"ok":True,"msg":"已登出"})
        resp.delete_cookie("session_token", path="/", samesite=SESSION_COOKIE_SAMESITE, secure=SESSION_COOKIE_SECURE)
        resp.delete_cookie("csrf_token", path="/", samesite=SESSION_COOKIE_SAMESITE, secure=SESSION_COOKIE_SECURE)
        return resp

    @app.route("/api/session/idle-timeout", methods=["POST"])
    @require_csrf
    def idle_timeout_logout():
        if request.headers.get("X-Idle-Timeout-Logout") != "1":
            return json_resp({"ok": False, "msg": "缺少閒置登出確認"}), 400
        ip, ua, tok = get_client_ip(), get_ua(), request.cookies.get("session_token")
        user = db_get_user_from_token(tok) if tok else None
        if tok:
            db_delete_session(tok)
        if user:
            delete_csrf_tokens_for_username(user)
        else:
            delete_csrf_token(request.cookies.get("csrf_token", ""))
        audit("IDLE_TIMEOUT_LOGOUT", ip, user=user or "-", ua=ua, success=bool(tok))
        resp = json_resp({"ok": True, "msg": "閒置逾時，已登出"})
        resp.delete_cookie("session_token", path="/", samesite=SESSION_COOKIE_SAMESITE, secure=SESSION_COOKIE_SECURE)
        resp.delete_cookie("csrf_token", path="/", samesite=SESSION_COOKIE_SAMESITE, secure=SESSION_COOKIE_SECURE)
        return resp

    @app.route("/api/me", methods=["GET"])
    def me():
        ctx = get_current_user_ctx()
        if not ctx:
            return json_resp({"ok":False,"msg":"未登入"}), 401
        role = "super_admin" if ctx["username"] == "root" else ctx["role"]
        is_special_account = ctx["username"] == "root" or role in {"super_admin", "manager"}
        effective_level = None if is_special_account else (dict(ctx).get("effective_level") or dict(ctx).get("member_level") or "normal")
        # 全局覆寫（system_settings）> member_level 規則 > 預設 10
        settings = get_system_settings()
        override = settings.get("session_idle_timeout_minutes")
        if override is not None:
            session_idle_timeout_minutes = max(1, int(override))
        elif get_member_level_rule and effective_level:
            conn = get_db()
            try:
                rule = get_member_level_rule(conn, effective_level) or {}
                session_idle_timeout_minutes = max(1, int(rule.get("session_idle_timeout_minutes") or 10))
            finally:
                conn.close()
        else:
            session_idle_timeout_minutes = 10
        return json_resp({
            "ok": True,
            "id": ctx["id"],
            "username": ctx["username"],
            "role": role,
            "role_label": ROLE_LABEL.get(role, role),
            "status": ctx["status"],
            "member_level": None if is_special_account else (dict(ctx).get("member_level") or "normal"),
            "base_level": None if is_special_account else (dict(ctx).get("base_level") or dict(ctx).get("member_level") or "normal"),
            "effective_level": effective_level,
            "member_level_label": "特殊階級" if is_special_account else effective_level,
            "special_account": is_special_account,
            "session_idle_timeout_minutes": session_idle_timeout_minutes,
            "trust_score": dict(ctx).get("trust_score") or 0,
            "reputation": dict(ctx).get("reputation") or 0,
            "violation_score": dict(ctx).get("violation_score") or dict(ctx).get("violation_count") or 0,
            "sanction_status": dict(ctx).get("sanction_status") or "none",
            "sanction_until": dict(ctx).get("sanction_until"),
            "preferred_landing_module": dict(ctx).get("preferred_landing_module") or "chat",
            "must_change_password": bool(dict(ctx).get("must_change_password") or 0),
            "is_default_password": bool(dict(ctx).get("is_default_password") or 0),
            "nickname": decrypt_field(ctx["nickname"]),
            "birthdate": decrypt_field(ctx["birthdate"]),
            "chat_violation_warned": dict(ctx).get("chat_violation_warned") or 0,
        })
