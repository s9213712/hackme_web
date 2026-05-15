import hashlib
import hmac
import json
import random
import secrets
import sqlite3
import time
from datetime import datetime, timedelta
from functools import wraps

import argon2
from flask import current_app, has_request_context, jsonify, make_response, request

from services.security.events import record_security_event

SESSION_TTL = 3600 * 4
CSRF_TOKEN_TTL = SESSION_TTL
SESSION_IDLE_TIMEOUT = 10 * 60
SESSION_LAST_SEEN_REFRESH_INTERVAL = 20
MIN_DELAY = 0.25
MAX_DELAY = 0.90
CSRF_PROTECTED_METHODS = {"POST", "PUT", "PATCH", "DELETE"}

_STATE = {
    "get_db": None,
    "get_auth_db": None,
    "get_user_by_username": None,
    "fernet": None,
    "get_client_ip": None,
    "session_ttl": SESSION_TTL,
    "csrf_token_ttl": CSRF_TOKEN_TTL,
    "session_idle_timeout": SESSION_IDLE_TIMEOUT,
    "tester_token_user_lookup": None,
    "get_runtime_server_mode": None,
}

_hasher = argon2.PasswordHasher(time_cost=3, memory_cost=65536,
                                parallelism=4, hash_len=32, salt_len=16)


def _is_sqlite_locked_error(exc):
    return isinstance(exc, sqlite3.OperationalError) and "locked" in str(exc).lower()


def configure_auth_service(
    *,
    get_db,
    get_auth_db=None,
    get_user_by_username,
    fernet,
    get_client_ip=None,
    session_ttl=SESSION_TTL,
    csrf_token_ttl=CSRF_TOKEN_TTL,
    session_idle_timeout=SESSION_IDLE_TIMEOUT,
    tester_token_user_lookup=None,
    get_runtime_server_mode=None,
):
    _STATE.update({
        "get_db": get_db,
        "get_auth_db": get_auth_db or get_db,
        "get_user_by_username": get_user_by_username,
        "fernet": fernet,
        "get_client_ip": get_client_ip,
        "session_ttl": session_ttl,
        "csrf_token_ttl": csrf_token_ttl,
        "session_idle_timeout": session_idle_timeout,
        "tester_token_user_lookup": tester_token_user_lookup,
        "get_runtime_server_mode": get_runtime_server_mode,
    })


def _is_superweak_csrf_bypass():
    """SERVER_MODE_V2_PROFILE_MATRIX.md §Mode Behavior Matrix footnote 1.

    CSRF is on in every mode EXCEPT `superweak` (the deliberate weakest
    web mode used for red-team / fuzz / pentest, alongside disabled
    rate limit / login lock / account lock / password strength).

    Returns True only when the runtime mode is exactly 'superweak';
    every other mode (including unknown / unconfigured) keeps CSRF on.
    Reads mode every call — no cache — so a switch *out of* superweak
    re-arms CSRF immediately and a switch *into* superweak only
    bypasses for requests that actually start in that mode.
    """
    reader = _STATE.get("get_runtime_server_mode")
    if not callable(reader):
        return False
    try:
        return reader() == "superweak"
    except Exception:
        return False


def json_resp(data, status=200):
    r = make_response(jsonify(data), status)
    r.headers["X-Content-Type-Options"] = "nosniff"
    r.headers["Cache-Control"] = "no-store"
    return r


def _request_ip():
    if not has_request_context():
        return "-"
    get_client_ip = _STATE.get("get_client_ip")
    if callable(get_client_ip):
        try:
            return get_client_ip() or "-"
        except Exception:
            pass
    return request.remote_addr or "-"


def _request_user_agent():
    if not has_request_context():
        return ""
    try:
        return str(request.headers.get("User-Agent") or "")
    except Exception:
        return ""


def _read_bool_setting(conn, key, default=False):
    try:
        row = conn.execute("SELECT value FROM system_settings WHERE key=?", (key,)).fetchone()
    except Exception:
        return default
    value = row["value"] if row and "value" in row.keys() else (row[0] if row else default)
    if isinstance(value, bool):
        return value
    normalized = str(value or "").strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    return default


def _main_db():
    return _STATE["get_db"]()


def _auth_db():
    getter = _STATE.get("get_auth_db") or _STATE.get("get_db")
    return getter()


def _auth_write(operation, *, attempts=5, delay_seconds=0.1):
    last_exc = None
    for attempt in range(max(1, int(attempts))):
        conn = _auth_db()
        try:
            result = operation(conn)
            conn.commit()
            return result
        except Exception as exc:
            last_exc = exc
            try:
                conn.rollback()
            except Exception:
                pass
            if _is_sqlite_locked_error(exc) and attempt + 1 < max(1, int(attempts)):
                time.sleep(delay_seconds * (attempt + 1))
                continue
            raise
        finally:
            conn.close()
    if last_exc is not None:
        raise last_exc
    return None


def record_login_attempt(*, user_id, ip_address, user_agent, success, attempted_at):
    def _write(conn):
        conn.execute(
            "INSERT INTO login_attempts (user_id, ip_address, user_agent, success, attempted_at) VALUES (?, ?, ?, ?, ?)",
            (user_id, ip_address, user_agent, 1 if success else 0, attempted_at),
        )
    _auth_write(_write)


def _record_csrf_failure(reason, username="-"):
    record_security_event(
        "csrf_fail",
        _request_ip(),
        target_user=username or "-",
        detail=f"path={request.path},reason={reason}",
    )


def csrf_invalid_response(reason="invalid", username="-"):
    _record_csrf_failure(reason, username)
    return json_resp({
        "ok": False,
        "error": "csrf_invalid",
        "message": "CSRF token expired or invalid",
    }), 403


def generate_csrf_dummy():
    tok = request.cookies.get("csrf_token", "")
    return tok


def verify_csrf_double_submit(body_token):
    if not isinstance(body_token, str):
        return False
    cookie_tok = request.cookies.get("csrf_token", "")
    if not isinstance(cookie_tok, str) or not cookie_tok or not body_token:
        return False
    # Constant-time compare to deny a timing oracle on the CSRF token.
    # `==` short-circuits on the first mismatching byte, leaking position
    # information. hmac.compare_digest takes the same time for any pair
    # of equal-length strings.  See issue #180.
    if not hmac.compare_digest(cookie_tok, body_token):
        return False
    tok_hash = hashlib.sha256(cookie_tok.encode()).hexdigest()
    conn = _auth_db()
    try:
        now = datetime.now().isoformat()
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT username FROM csrf_tokens WHERE token_hash=? AND expires_at>?",
            (tok_hash, now)
        ).fetchone()
        if not row:
            conn.rollback()
            return False
        conn.execute("DELETE FROM csrf_tokens WHERE token_hash=?", (tok_hash,))
        conn.commit()
        return True
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        return False
    finally:
        conn.close()


def hash_password(pw):
    return _hasher.hash(pw)


def verify_password(h, p):
    try:
        return _hasher.verify(h, p)
    except argon2.exceptions.VerifyMismatchError:
        return False
    except argon2.exceptions.VerificationError:
        return False
    except argon2.exceptions.InvalidHash:
        return False
    except (argon2.exceptions.DecodeError, ValueError, TypeError):
        return False
    except Exception:
        return False


def make_token(username):
    payload = json.dumps({
        "user": username,
        "exp": (datetime.now() + timedelta(seconds=_STATE["session_ttl"])).isoformat(),
        "nonce": secrets.token_hex(8),
    }, ensure_ascii=False)
    return _STATE["fernet"].encrypt(payload.encode()).decode()


def _hash_token(token):
    return hashlib.sha256(token.encode()).hexdigest()


def _device_info_from_user_agent(ua):
    ua = ua or "-"
    lowered = ua.lower()
    browser = "Other"
    if "edg/" in lowered:
        browser = "Edge"
    elif "chrome/" in lowered and "chromium" not in lowered:
        browser = "Chrome"
    elif "firefox/" in lowered:
        browser = "Firefox"
    elif "safari/" in lowered and "chrome/" not in lowered:
        browser = "Safari"
    os_name = "Other"
    if "windows" in lowered:
        os_name = "Windows"
    elif "android" in lowered:
        os_name = "Android"
    elif "iphone" in lowered or "ipad" in lowered:
        os_name = "iOS"
    elif "mac os" in lowered or "macintosh" in lowered:
        os_name = "macOS"
    elif "linux" in lowered:
        os_name = "Linux"
    device = "Mobile" if any(token in lowered for token in ("mobile", "android", "iphone")) else "Desktop"
    return json.dumps({"browser": browser, "os": os_name, "device": device}, ensure_ascii=False)


def _current_security_epoch(conn):
    try:
        row = conn.execute("SELECT value FROM system_settings WHERE key='server_security_epoch'").fetchone()
        return int((row["value"] if row else 0) or 0)
    except Exception:
        return 0


def timing_delay():
    time.sleep(MIN_DELAY + random.uniform(0, MAX_DELAY - MIN_DELAY))


def make_csrf_token():
    return secrets.token_urlsafe(32)


def store_csrf_token(token, username):
    expires = (datetime.now() + timedelta(seconds=_STATE["csrf_token_ttl"])).isoformat()
    now = datetime.now().isoformat()
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    def _write(conn):
        conn.execute("DELETE FROM csrf_tokens WHERE expires_at<=?", (now,))
        conn.execute(
            "INSERT OR REPLACE INTO csrf_tokens (token_hash, username, expires_at) VALUES (?, ?, ?)",
            (token_hash, username, expires)
        )
    _auth_write(_write)


def verify_csrf_token(token, username):
    if not isinstance(token, str) or not token:
        return False
    if not isinstance(username, str) or not username:
        return False
    conn = _auth_db()
    try:
        row = conn.execute(
            "SELECT 1 FROM csrf_tokens WHERE token_hash=? AND username=? AND expires_at>?",
            (hashlib.sha256(token.encode()).hexdigest(), username, datetime.now().isoformat())
        ).fetchone()
        return row is not None
    finally:
        conn.close()


def consume_csrf_token(token, username):
    if not isinstance(token, str) or not token:
        return False
    if not isinstance(username, str) or not username:
        return False
    conn = _auth_db()
    try:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT 1 FROM csrf_tokens WHERE token_hash=? AND username=? AND expires_at>?",
            (hashlib.sha256(token.encode()).hexdigest(), username, datetime.now().isoformat())
        ).fetchone()
        if not row:
            conn.rollback()
            return False
        conn.execute(
            "DELETE FROM csrf_tokens WHERE token_hash=? AND username=?",
            (hashlib.sha256(token.encode()).hexdigest(), username),
        )
        conn.commit()
        return True
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        return False
    finally:
        conn.close()


def delete_csrf_token(token):
    if not token:
        return
    h = hashlib.sha256(token.encode()).hexdigest()
    conn = _auth_db()
    conn.execute("DELETE FROM csrf_tokens WHERE token_hash=?", (h,))
    conn.commit()
    conn.close()


def delete_csrf_tokens_for_username(username):
    if not username:
        return
    conn = _auth_db()
    try:
        conn.execute("DELETE FROM csrf_tokens WHERE username=?", (username,))
        conn.commit()
    finally:
        conn.close()


def _rotate_authenticated_csrf(response, csrf_tok, username):
    resp = make_response(response)
    if resp.status_code >= 400 or not csrf_tok or not username:
        return resp
    consume_csrf_token(csrf_tok, username)
    new_csrf = make_csrf_token()
    store_csrf_token(new_csrf, username)
    resp.set_cookie(
        "csrf_token",
        new_csrf,
        max_age=int(_STATE.get("csrf_token_ttl") or CSRF_TOKEN_TTL),
        httponly=False,
        samesite=current_app.config.get("SESSION_COOKIE_SAMESITE", "Lax"),
        secure=bool(current_app.config.get("SESSION_COOKIE_SECURE", False)),
        path="/",
    )
    return resp


def require_csrf(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if request.method not in CSRF_PROTECTED_METHODS:
            return f(*args, **kwargs)
        # SERVER_MODE_V2_PROFILE_MATRIX.md §Mode Behavior Matrix footnote 1:
        # CSRF on in every mode EXCEPT `superweak`.
        if _is_superweak_csrf_bypass():
            record_security_event(
                "csrf_skipped_superweak",
                _request_ip(),
                target_user="-",
                detail=f"path={request.path},decorator=require_csrf",
            )
            return f(*args, **kwargs)
        csrf_tok = get_request_csrf_token()
        body_username = None
        if request.is_json:
            body = request.get_json(silent=True) or {}
            if isinstance(body, dict):
                body_username = body.get("username", "")
                if isinstance(body_username, str):
                    body_username = body_username.strip()
                else:
                    body_username = ""

        tok = request.cookies.get("session_token")
        user = db_get_user_from_token(tok) if tok else None

        if request.path == "/api/login":
            csrf_owner = ""
            if user and verify_csrf_token(csrf_tok, user):
                csrf_owner = user
            elif verify_csrf_token(csrf_tok, "__public__"):
                csrf_owner = "__public__"
            elif body_username and verify_csrf_token(csrf_tok, body_username):
                csrf_owner = body_username
            if not csrf_owner:
                return csrf_invalid_response("invalid_login", body_username or user or "-")
            response = f(*args, **kwargs)
            if csrf_tok:
                consume_csrf_token(csrf_tok, csrf_owner)
            return response

        if user:
            # Authenticated: token stored under username
            if not verify_csrf_token(csrf_tok, user):
                return csrf_invalid_response("invalid_authenticated", user)
        else:
            # Unauthenticated: token stored under "__public__" OR under body_username
            if not csrf_tok:
                return csrf_invalid_response("missing_public", body_username or "-")
            csrf_owner = "__public__"
            if not verify_csrf_token(csrf_tok, csrf_owner):
                # Also accept token stored under body_username (e.g. login request)
                if not body_username or not verify_csrf_token(csrf_tok, body_username):
                    return csrf_invalid_response("invalid_public", body_username or "-")
                csrf_owner = body_username

        response = f(*args, **kwargs)
        if user:
            response = _rotate_authenticated_csrf(response, csrf_tok, user)
        elif csrf_tok:
            consume_csrf_token(csrf_tok, csrf_owner)
        return response
    return decorated


def require_csrf_safe(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        tok = request.cookies.get("session_token")
        user = db_get_user_from_token(tok) if tok else None
        if not user:
            return json_resp({"ok": False, "msg": "未登入"}), 401
        if request.method not in CSRF_PROTECTED_METHODS:
            return f(*args, **kwargs)
        # CSRF policy: see comment in require_csrf above. superweak bypass
        # also applies here so that CSRF posture is uniform across both
        # decorators — otherwise red-team / pentest tooling would be blocked
        # on authenticated endpoints in superweak only.
        if _is_superweak_csrf_bypass():
            record_security_event(
                "csrf_skipped_superweak",
                _request_ip(),
                target_user=user,
                detail=f"path={request.path},decorator=require_csrf_safe",
            )
            return f(*args, **kwargs)
        csrf_tok = get_request_csrf_token()
        if not verify_csrf_token(csrf_tok, user):
            return csrf_invalid_response("invalid_safe", user)
        response = f(*args, **kwargs)
        response = _rotate_authenticated_csrf(response, csrf_tok, user)
        return response
    return decorated


def get_request_csrf_token():
    token = request.headers.get("X-CSRF-Token", "") or ""
    if not isinstance(token, str):
        token = ""
    if token:
        return token
    if request.form:
        req_token = request.form.get("csrf_token", "")
        if isinstance(req_token, str):
            return req_token
    if request.is_json:
        body = request.get_json(silent=True) or {}
        if isinstance(body, dict):
            req_token = body.get("csrf_token", "")
            if isinstance(req_token, str):
                return req_token
    return ""


def db_save_session(user_id, token, ip, ua):
    now = datetime.now().isoformat()
    expires = (datetime.now() + timedelta(seconds=_STATE["session_ttl"])).isoformat()
    def _write(conn):
        cols = {row["name"] for row in conn.execute("PRAGMA table_info(sessions)").fetchall()}
        session_epoch = _current_security_epoch(conn)
        if "device_info" in cols:
            if "session_epoch" in cols:
                conn.execute(
                    "INSERT INTO sessions (user_id, token_hash, ip_address, user_agent, device_info, expires_at, last_seen, session_epoch) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (user_id, _hash_token(token), ip, ua, _device_info_from_user_agent(ua), expires, now, session_epoch)
                )
            else:
                conn.execute(
                    "INSERT INTO sessions (user_id, token_hash, ip_address, user_agent, device_info, expires_at, last_seen) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (user_id, _hash_token(token), ip, ua, _device_info_from_user_agent(ua), expires, now)
                )
        else:
            conn.execute(
                "INSERT INTO sessions (user_id, token_hash, ip_address, user_agent, expires_at, last_seen) VALUES (?, ?, ?, ?, ?, ?)",
                (user_id, _hash_token(token), ip, ua, expires, now)
            )
    _auth_write(_write)


def db_delete_session(token, *, notify_security_event=False, detail="single_session_logout"):
    conn = _auth_db()
    try:
        conn.execute(
            "UPDATE sessions SET is_revoked=1, revoked_at=? WHERE token_hash=?",
            (datetime.now().isoformat(), _hash_token(token))
        )
        conn.commit()
        if notify_security_event:
            record_security_event("session_revoked", _request_ip(), detail=detail)
    finally:
        conn.close()


def revoke_user_sessions(user_id, *, notify_security_event=True, detail="user_sessions_revoked"):
    conn = _auth_db()
    try:
        conn.execute(
            "UPDATE sessions SET is_revoked=1, revoked_at=? WHERE user_id=? AND is_revoked=0",
            (datetime.now().isoformat(), user_id)
        )
        conn.commit()
        if notify_security_event:
            record_security_event("session_revoked", "-", target_user=str(user_id), detail=detail)
    finally:
        conn.close()


def db_clean_expired_sessions():
    conn = _auth_db()
    try:
        conn.execute(
            "DELETE FROM sessions WHERE expires_at < ? OR is_revoked=1",
            (datetime.now().isoformat(),)
        )
        conn.commit()
    finally:
        conn.close()


def db_get_user_from_token(token):
    auth_conn = _auth_db()
    try:
        now = datetime.now()
        now_iso = now.isoformat()
        try:
            session_cols = {item["name"] for item in auth_conn.execute("PRAGMA table_info(sessions)").fetchall()}
        except Exception:
            session_cols = set()
        session_epoch_expr = "s.session_epoch" if "session_epoch" in session_cols else "0"
        row = auth_conn.execute(
            f"SELECT s.id, s.user_id, s.last_seen, s.ip_address, s.user_agent, COALESCE({session_epoch_expr}, 0) AS session_epoch "
            "FROM sessions s "
            "WHERE s.token_hash=? AND s.expires_at>? AND COALESCE(s.is_revoked, 0)=0",
            (_hash_token(token), now_iso)
        ).fetchone()
        if not row:
            return None
        main_conn = _main_db()
        try:
            user_row = main_conn.execute(
                "SELECT username, status FROM users WHERE id=?",
                (row["user_id"],),
            ).fetchone()
            if not user_row or str(user_row["status"] or "") != "active":
                return None
            username = user_row["username"]
            current_epoch = _current_security_epoch(main_conn)
            strict_ip_binding = _read_bool_setting(main_conn, "session_strict_ip_binding", default=False)
        finally:
            main_conn.close()
        if int(row["session_epoch"] or 0) < current_epoch:
            try:
                auth_conn.execute(
                    "UPDATE sessions SET is_revoked=1, revoked_at=? WHERE id=?",
                    (now_iso, row["id"])
                )
                auth_conn.commit()
            except sqlite3.OperationalError:
                auth_conn.rollback()
            record_security_event("session_revoked", "-", target_user=username, detail="security_epoch_rotated")
            return None

        stored_ip = str(row["ip_address"] or "").strip()
        current_ip = _request_ip()
        if stored_ip and current_ip and stored_ip != current_ip:
            record_security_event(
                "session_ip_mismatch",
                current_ip,
                target_user=username,
                detail=f"stored={stored_ip}",
            )
            if strict_ip_binding:
                try:
                    auth_conn.execute(
                        "UPDATE sessions SET is_revoked=1, revoked_at=? WHERE id=?",
                        (now_iso, row["id"])
                    )
                    auth_conn.commit()
                except sqlite3.OperationalError:
                    auth_conn.rollback()
                record_security_event("session_revoked", current_ip, target_user=username, detail=f"strict_ip_binding stored={stored_ip}")
                return None

        stored_ua = str(row["user_agent"] or "").strip()
        current_ua = _request_user_agent().strip()
        if stored_ua and current_ua and stored_ua != current_ua:
            record_security_event(
                "session_user_agent_mismatch",
                current_ip or "-",
                target_user=username,
                detail=f"stored={stored_ua[:120]},current={current_ua[:120]}",
            )

        last_seen = row["last_seen"]
        idle_seconds = 0
        if last_seen:
            try:
                idle_seconds = (now - datetime.fromisoformat(last_seen)).total_seconds()
            except Exception:
                idle_seconds = 0
            if idle_seconds > int(_STATE["session_idle_timeout"]):
                try:
                    auth_conn.execute(
                        "UPDATE sessions SET is_revoked=1, revoked_at=? WHERE id=?",
                        (now_iso, row["id"])
                    )
                    auth_conn.commit()
                except sqlite3.OperationalError:
                    auth_conn.rollback()
                record_security_event("session_revoked", "-", target_user=username, detail="idle_timeout")
                return None

        if idle_seconds >= SESSION_LAST_SEEN_REFRESH_INTERVAL:
            try:
                auth_conn.execute("UPDATE sessions SET last_seen=? WHERE id=?", (now_iso, row["id"]))
                auth_conn.commit()
            except sqlite3.OperationalError:
                auth_conn.rollback()
        return username
    finally:
        auth_conn.close()


def get_current_user_ctx():
    tok = request.cookies.get("session_token")
    username = db_get_user_from_token(tok) if tok else None
    if not username:
        lookup = _STATE.get("tester_token_user_lookup")
        if callable(lookup):
            try:
                username = lookup(request)
            except Exception:
                username = None
    if not username:
        return None
    return _STATE["get_user_by_username"](username)
