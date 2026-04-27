import hashlib
import json
import random
import secrets
import sqlite3
import time
from datetime import datetime, timedelta
from functools import wraps

import argon2
from flask import has_request_context, jsonify, make_response, request

from services.security_events import record_security_event

SESSION_TTL = 3600 * 4
CSRF_TOKEN_TTL = SESSION_TTL
SESSION_IDLE_TIMEOUT = 3 * 60
MIN_DELAY = 0.25
MAX_DELAY = 0.90

_STATE = {
    "get_db": None,
    "get_user_by_username": None,
    "fernet": None,
    "session_ttl": SESSION_TTL,
    "csrf_token_ttl": CSRF_TOKEN_TTL,
    "session_idle_timeout": SESSION_IDLE_TIMEOUT,
}

_hasher = argon2.PasswordHasher(time_cost=3, memory_cost=65536,
                                parallelism=4, hash_len=32, salt_len=16)


def configure_auth_service(
    *,
    get_db,
    get_user_by_username,
    fernet,
    session_ttl=SESSION_TTL,
    csrf_token_ttl=CSRF_TOKEN_TTL,
    session_idle_timeout=SESSION_IDLE_TIMEOUT,
):
    _STATE.update({
        "get_db": get_db,
        "get_user_by_username": get_user_by_username,
        "fernet": fernet,
        "session_ttl": session_ttl,
        "csrf_token_ttl": csrf_token_ttl,
        "session_idle_timeout": session_idle_timeout,
    })


def json_resp(data, status=200):
    r = make_response(jsonify(data), status)
    r.headers["X-Content-Type-Options"] = "nosniff"
    r.headers["Cache-Control"] = "no-store"
    return r


def _request_ip():
    if not has_request_context():
        return "-"
    return (request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
            or request.remote_addr
            or "-")


def _record_csrf_failure(reason, username="-"):
    record_security_event(
        "csrf_fail",
        _request_ip(),
        target_user=username or "-",
        detail=f"path={request.path},reason={reason}",
    )


def generate_csrf_dummy():
    tok = request.cookies.get("csrf_token", "")
    return tok


def verify_csrf_double_submit(body_token):
    if not isinstance(body_token, str):
        return False
    cookie_tok = request.cookies.get("csrf_token", "")
    if not isinstance(cookie_tok, str) or not cookie_tok or not body_token:
        return False
    if cookie_tok != body_token:
        return False
    tok_hash = hashlib.sha256(cookie_tok.encode()).hexdigest()
    conn = _STATE["get_db"]()
    try:
        now = datetime.now().isoformat()
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT 1 FROM csrf_tokens WHERE token_hash=? AND expires_at>?",
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


def timing_delay():
    time.sleep(MIN_DELAY + random.uniform(0, MAX_DELAY - MIN_DELAY))


def make_csrf_token():
    return secrets.token_hex(16)


def store_csrf_token(token, username):
    conn = _STATE["get_db"]()
    expires = (datetime.now() + timedelta(seconds=_STATE["csrf_token_ttl"])).isoformat()
    now = datetime.now().isoformat()
    try:
        conn.execute("DELETE FROM csrf_tokens WHERE expires_at<=?", (now,))
        conn.execute(
            "INSERT OR REPLACE INTO csrf_tokens (token_hash, username, expires_at) VALUES (?, ?, ?)",
            (hashlib.sha256(token.encode()).hexdigest(), username, expires)
        )
        conn.commit()
    finally:
        conn.close()


def verify_csrf_token(token, username):
    if not isinstance(token, str) or not token:
        return False
    if not isinstance(username, str) or not username:
        return False
    conn = _STATE["get_db"]()
    try:
        row = conn.execute(
            "SELECT 1 FROM csrf_tokens WHERE token_hash=? AND username=? AND expires_at>?",
            (hashlib.sha256(token.encode()).hexdigest(), username, datetime.now().isoformat())
        ).fetchone()
        return row is not None
    finally:
        conn.close()


def delete_csrf_token(token):
    if not token:
        return
    h = hashlib.sha256(token.encode()).hexdigest()
    conn = _STATE["get_db"]()
    conn.execute("DELETE FROM csrf_tokens WHERE token_hash=?", (h,))
    conn.commit()
    conn.close()


def require_csrf(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        csrf_tok = request.headers.get("X-CSRF-Token", "") or ""
        if not isinstance(csrf_tok, str):
            csrf_tok = ""
        body_username = None
        if request.is_json:
            body = request.get_json(silent=True) or {}
            if isinstance(body, dict):
                body_username = body.get("username", "")
                if isinstance(body_username, str):
                    body_username = body_username.strip()
                else:
                    body_username = ""
            if not csrf_tok and isinstance(body, dict):
                csrf_body = body.get("csrf_token", "")
                if isinstance(csrf_body, str):
                    csrf_tok = csrf_body

        tok = request.cookies.get("session_token")
        user = db_get_user_from_token(tok) if tok else None

        if user:
            if not verify_csrf_token(csrf_tok, user):
                _record_csrf_failure("invalid_authenticated", user)
                return json_resp({"ok": False, "msg": "CSRF token 無效或已過期"}), 403
        else:
            if not csrf_tok:
                _record_csrf_failure("missing_public", body_username or "-")
                return json_resp({"ok": False, "msg": "CSRF token 缺失"}), 403
            if not verify_csrf_token(csrf_tok, "__public__") and not (body_username and verify_csrf_token(csrf_tok, body_username)):
                _record_csrf_failure("invalid_public", body_username or "-")
                return json_resp({"ok": False, "msg": "CSRF token 無效或已過期"}), 403

        delete_csrf_token(csrf_tok)
        return f(*args, **kwargs)
    return decorated


def require_csrf_safe(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        csrf_tok = request.headers.get("X-CSRF-Token", "") or ""
        if not isinstance(csrf_tok, str):
            csrf_tok = ""
        tok = request.cookies.get("session_token")
        user = db_get_user_from_token(tok) if tok else None
        if not user:
            return json_resp({"ok": False, "msg": "未登入"}), 401
        if not verify_csrf_token(csrf_tok, user):
            _record_csrf_failure("invalid_safe", user)
            return json_resp({"ok": False, "msg": "CSRF token 無效或已過期"}), 403
        return f(*args, **kwargs)
    return decorated


def get_request_csrf_token():
    token = request.headers.get("X-CSRF-Token", "") or ""
    if not isinstance(token, str):
        token = ""
    if token:
        return token
    if request.is_json:
        body = request.get_json(silent=True) or {}
        if isinstance(body, dict):
            req_token = body.get("csrf_token", "")
            if isinstance(req_token, str):
                return req_token
    return ""


def db_save_session(user_id, token, ip, ua):
    conn = _STATE["get_db"]()
    now = datetime.now().isoformat()
    expires = (datetime.now() + timedelta(seconds=_STATE["session_ttl"])).isoformat()
    cols = {row["name"] for row in conn.execute("PRAGMA table_info(sessions)").fetchall()}
    if "device_info" in cols:
        conn.execute(
            "INSERT INTO sessions (user_id, token_hash, ip_address, user_agent, device_info, expires_at, last_seen) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (user_id, _hash_token(token), ip, ua, _device_info_from_user_agent(ua), expires, now)
        )
    else:
        conn.execute(
            "INSERT INTO sessions (user_id, token_hash, ip_address, user_agent, expires_at, last_seen) VALUES (?, ?, ?, ?, ?, ?)",
            (user_id, _hash_token(token), ip, ua, expires, now)
        )
    conn.commit()
    conn.close()


def db_delete_session(token):
    conn = _STATE["get_db"]()
    try:
        conn.execute(
            "UPDATE sessions SET is_revoked=1, revoked_at=? WHERE token_hash=?",
            (datetime.now().isoformat(), _hash_token(token))
        )
        conn.commit()
        record_security_event("session_revoked", _request_ip(), detail="single_session_logout")
    finally:
        conn.close()


def revoke_user_sessions(user_id):
    conn = _STATE["get_db"]()
    try:
        conn.execute(
            "UPDATE sessions SET is_revoked=1, revoked_at=? WHERE user_id=? AND is_revoked=0",
            (datetime.now().isoformat(), user_id)
        )
        conn.commit()
        record_security_event("session_revoked", "-", target_user=str(user_id), detail="user_sessions_revoked")
    finally:
        conn.close()


def db_clean_expired_sessions():
    conn = _STATE["get_db"]()
    try:
        conn.execute(
            "DELETE FROM sessions WHERE expires_at < ? OR is_revoked=1",
            (datetime.now().isoformat(),)
        )
        conn.commit()
    finally:
        conn.close()


def db_get_user_from_token(token):
    conn = _STATE["get_db"]()
    try:
        now = datetime.now()
        now_iso = now.isoformat()
        row = conn.execute(
            "SELECT s.id, s.last_seen, u.username FROM sessions s "
            "JOIN users u ON u.id=s.user_id "
            "WHERE s.token_hash=? AND s.expires_at>? AND COALESCE(s.is_revoked, 0)=0 "
            "AND u.status='active'",
            (_hash_token(token), now_iso)
        ).fetchone()
        if not row:
            return None

        last_seen = row["last_seen"]
        if last_seen:
            try:
                idle_seconds = (now - datetime.fromisoformat(last_seen)).total_seconds()
            except Exception:
                idle_seconds = 0
            if idle_seconds > int(_STATE["session_idle_timeout"]):
                conn.execute(
                    "UPDATE sessions SET is_revoked=1, revoked_at=? WHERE id=?",
                    (now_iso, row["id"])
                )
                conn.commit()
                record_security_event("session_revoked", "-", target_user=row["username"], detail="idle_timeout")
                return None

        conn.execute("UPDATE sessions SET last_seen=? WHERE id=?", (now_iso, row["id"]))
        conn.commit()
        return row["username"]
    finally:
        conn.close()


def get_current_user_ctx():
    tok = request.cookies.get("session_token")
    if not tok:
        return None
    username = db_get_user_from_token(tok)
    if not username:
        return None
    return _STATE["get_user_by_username"](username)
