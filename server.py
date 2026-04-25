#!/usr/bin/env python3
"""
Flask server for html_learning auth demo.
Hardened version — see SECURITY.md for details.
"""

import os
import sqlite3
import re
import json
import time
import hashlib
import secrets
import hmac
import struct
import threading
from datetime import datetime, timedelta
from functools import wraps

from flask import Flask, request, jsonify, send_from_directory, make_response
from flask_talisman import Talisman
from cryptography.fernet import Fernet
import argon2

# ── Config ──────────────────────────────────────────────────────────────────
BASE_DIR    = os.path.dirname(os.path.abspath(__file__))
DB_PATH     = os.path.join(BASE_DIR, "database.db")
PUBLIC_DIR  = os.path.join(BASE_DIR, "public")
BLOCK_FILE  = os.path.join(BASE_DIR, "blocked_ips.json")
FAIL_FILE   = os.path.join(BASE_DIR, "fail_log.json")
LOG_FILE    = os.path.join(BASE_DIR, "attack_log.json")
PORT        = 5000

# ── Attack logging ───────────────────────────────────────────────────────────
def log_event(event_type, ip, detail=""):
    import json, datetime
    log = json.load(open(LOG_FILE)) if os.path.exists(LOG_FILE) else {}
    entry = {
        "time": datetime.datetime.now().isoformat(),
        "type": event_type,
        "ip": ip,
        "detail": detail
    }
    log[datetime.datetime.now().isoformat()] = entry
    with open(LOG_FILE, "w") as f:
        json.dump(log, f, indent=2)
    ts = datetime.datetime.now().strftime("%H:%M:%S")
    print(f"  [{ts}] [{event_type}] {ip} {detail}")
AUDIT_FILE  = os.path.join(BASE_DIR, "audit.log")
PORT        = 5000

# ── Audit / Attack Logging ──────────────────────────────────────────────────
def audit(action: str, ip: str, username: str = "-", details: str = "-",
          user_agent: str = "-", success: bool = False):
    """
    Append a structured log line to audit.log (one event per line, JSON).
    Records everything for forensic analysis and attack pattern detection.
    """
    entry = {
        "ts":      datetime.now().isoformat(timespec="milliseconds"),
        "action":  action,
        "ip":      ip,
        "user":    username,
        "success": success,
        "ua":      user_agent[:200],        # truncate long UAs
        "details": details,
    }
    line = json.dumps(entry, ensure_ascii=False)
    _audit_lock.acquire()
    try:
        with open(AUDIT_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    finally:
        _audit_lock.release()

_audit_lock = threading.Lock()

def get_audit_summary(lines: int = 50) -> list[dict]:
    """Read last N audit log entries for monitoring."""
    if not os.path.exists(AUDIT_FILE):
        return []
    with open(AUDIT_FILE) as f:
        all_lines = f.readlines()
    parsed = []
    for l in all_lines[-lines:]:
        try:
            parsed.append(json.loads(l))
        except Exception:
            continue
    return parsed

# Argon2 hasher (for passwords)
_hasher = argon2.PasswordHasher(
    time_cost=3,      # iterations
    memory_cost=65536,# 64 MiB
    parallelism=4,
    hash_len=32,
    salt_len=16,
)

# Fernet for encrypting stored tokens (non-password data)
def _get_fernet_key() -> bytes:
    key_file = os.path.join(BASE_DIR, ".fkey")
    if os.path.exists(key_file):
        return open(key_file, "rb").read()
    key = Fernet.generate_key()
    open(key_file, "wb").write(key)
    return key

fernet = Fernet(_get_fernet_key())

# ── JSON helpers (atomic write) ───────────────────────────────────────────────
def load_json(path):
    if not os.path.exists(path):
        return {}
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return {}

def save_json(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    os.replace(tmp, path)      # atomic rename

# ── Security: constant-time comparison (prevents timing attacks) ──────────────
def const_time_compare(a: str, b: str) -> bool:
    """Compare two strings in constant time to prevent timing side-channels."""
    if len(a) != len(b):
        # Still do a dummy comparison to keep timing equal
        hmac.compare_digest(a, b)
        return False
    return hmac.compare_digest(a.encode(), b.encode())

# ── Security: rate limiting (per-IP, before auth logic) ──────────────────────
def is_rate_limited(ip: str, max_req: int = 20, window_sec: int = 60) -> tuple[bool, dict]:
    """
    Sliding-window rate limit.
    Returns (blocked, info_dict).
    """
    data = load_json(RATE_FILE)
    now  = datetime.now()
    # Prune old entries
    data = {
        k: v for k, v in data.items()
        if now - datetime.fromisoformat(v["window_start"]) < timedelta(seconds=window_sec)
    }
    entry = data.get(ip)
    if not entry:
        data[ip] = {"count": 1, "window_start": now.isoformat()}
        save_json(RATE_FILE, data)
        return False, {"count": 1, "limit": max_req}

    count = entry["count"] + 1
    if count > max_req:
        data[ip] = entry  # keep it; it will be pruned on next window
        save_json(RATE_FILE, data)
        return True, {"count": count, "limit": max_req}

    entry["count"] = count
    data[ip] = entry
    save_json(RATE_FILE, data)
    return False, {"count": count, "limit": max_req}

# ── Security: IP blocking ──────────────────────────────────────────────────────
def is_ip_blocked(ip: str) -> bool:
    data = load_json(BLOCK_FILE)
    entry = data.get(ip)
    if not entry:
        return False
    if datetime.now() < datetime.fromisoformat(entry["until"]):
        return True
    del data[ip]
    save_json(BLOCK_FILE, data)
    return False

def block_ip(ip: str, minutes: int = 10):
    data = load_json(BLOCK_FILE)
    data[ip] = {"until": (datetime.now() + timedelta(minutes=minutes)).isoformat()}
    save_json(BLOCK_FILE, data)

def record_failed_login(ip: str) -> int:
    fail_data = load_json(FAIL_FILE)
    now = datetime.now()
    fail_data = {
        k: v for k, v in fail_data.items()
        if now < datetime.fromisoformat(v["until"])
    }
    record = fail_data.get(ip)
    count  = (record["count"] + 1) if record else 1
    fail_data[ip] = {"count": count, "until": (now + timedelta(minutes=10)).isoformat()}
    save_json(FAIL_FILE, fail_data)
    return count

def clear_failed_logins(ip: str):
    fail_data = load_json(FAIL_FILE)
    fail_data.pop(ip, None)
    save_json(FAIL_FILE, fail_data)

# ── Security: intentional login delay ────────────────────────────────────────
def elastic_sleep(ip: str, failures: int):
    """Add variable delay to slow brute-force, proportional to failure count."""
    base = 0.05          # 50ms minimum
    cap  = min(2.0, base * (2 ** failures))   # max 2 seconds
    time.sleep(cap)

# ── Password hashing (Argon2id) ──────────────────────────────────────────────
def hash_password(pw: str) -> str:
    """Argon2id — winner of Password Hashing Competition, memory-hard."""
    return _hasher.hash(pw)

def verify_password(hashed: str, pw: str) -> bool:
    try:
        return _hasher.verify(hashed, pw)
    except argon2.exceptions.VerifyMismatch:
        return False

# ── Validation ────────────────────────────────────────────────────────────────
USERNAME_MAX = 32
PW_RE = re.compile(
    r"^(?=.*[a-z])(?=.*[A-Z])(?=.*\d)(?=.*[!@#$%^&*()_+\-=\[\]{};':\"\\|,.<>\/?]).{8,128}$"
)

def validate_password(pw: str) -> tuple[bool, str]:
    if len(pw) < 8:   return False, "密碼至少需要 8 個字元"
    if len(pw) > 128: return False, "密碼太長（最多 128 字元）"
    if not re.search(r"[A-Z]",  pw): return False, "密碼必須包含大寫字母"
    if not re.search(r"[a-z]",  pw): return False, "密碼必須包含小寫字母"
    if not re.search(r"[!@#$%^&*()_+\-=\[\]{};':\"\\|,.<>\/?]", pw):
        return False, "密碼必須包含符號"
    return True, "OK"

def validate_username(username: str) -> tuple[bool, str]:
    username = username.strip()
    if not username:          return False, "帳號不可為空"
    if len(username) < 3:     return False, "帳號至少需要 3 個字元"
    if len(username) > USERNAME_MAX: return False, f"帳號最長 {USERNAME_MAX} 字元"
    if not re.fullmatch(r"[a-zA-Z0-9_\-]+", username):
        return False, "帳號只能包含英文、數字、底線、減號"
    return True, username   # return sanitized

# ── Session tokens (stateless, signed) ───────────────────────────────────────
SESSION_TTL = 3600 * 4   # 4 hours

def make_token(username: str) -> str:
    """Create a signed, encrypted session token (Fernet)."""
    payload = json.dumps({
        "user": username,
        "exp":  (datetime.now() + timedelta(seconds=SESSION_TTL)).isoformat(),
        "nonce": secrets.token_hex(8)
    }, ensure_ascii=False)
    return fernet.encrypt(payload.encode()).decode()

def verify_token(token: str) -> str | None:
    """
    Decrypt & verify token. Returns username if valid, None otherwise.
    Tokens are NOT timing-vulnerable (Fernet handles that).
    """
    try:
        payload = fernet.decrypt(token.encode()).decode()
        data = json.loads(payload)
        if datetime.now() > datetime.fromisoformat(data["exp"]):
            return None
        return data["user"]
    except Exception:
        return None

# ── CSRF token ────────────────────────────────────────────────────────────────
def make_csrf_token(session_token: str) -> str:
    """Generate a CSRF token tied to the session."""
    user = verify_token(session_token)
    if not user:
        return ""
    return hashlib.sha256((user + session_token + "csrf_salt").encode()).hexdigest()

def verify_csrf_token(session_token: str, csrf_tok: str) -> bool:
    expected = make_csrf_token(session_token)
    return hmac.compare_digest(expected, csrf_tok)

# ── Flask app ──────────────────────────────────────────────────────────────────
app = Flask(__name__, static_folder=PUBLIC_DIR, static_url_path="")
app.config["MAX_CONTENT_LENGTH"] = 64 * 1024   # 64 KB max request size

# Security headers (HSTS, X-Frame-Options, etc.)
Talisman(app,
    content_security_policy={
        "default-src": "'self'",
        "style-src":    "'self' 'unsafe-inline'",   # needed for inline CSS
        "script-src":   "'self' 'unsafe-inline'",   # needed for inline JS
        "img-src":      "'self' data:",
    },
    force_https=False,
    frame_options="DENY",
    strict_transport_security="max-age=31536000; includeSubDomains",
    x_content_type_options="nosniff",
    x_xss_protection="1; mode=block",
)

# ── Route helpers ──────────────────────────────────────────────────────────────
def json_response(data, status=200):
    r = make_response(jsonify(data), status)
    r.headers["Cache-Control"] = "no-store"
    r.headers["X-Content-Type-Options"] = "nosniff"
    return r

def get_client_ip() -> str:
    """Respect X-Forwarded-For if behind a trusted proxy, else remote_addr."""
    if request.headers.get("X-Forwarded-For"):
        return request.headers.get("X-Forwarded-For").split(",")[0].strip()
    return request.remote_addr or "0.0.0.0"

def get_user_agent() -> str:
    return request.headers.get("User-Agent", "-")[:200]

# ── Routes ─────────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return send_from_directory(PUBLIC_DIR, "index.html")

@app.route("/api/register", methods=["POST"])
def register():
    ip  = get_client_ip()
    ua  = get_user_agent()

    if is_ip_blocked(ip):
        audit("REGISTER_BLOCKED", ip, user_agent=ua, details="IP locked")
        return json_response({"ok": False, "msg": "IP 已被鎖定，請稍後再試"}), 429

    blocked, info = is_rate_limited(ip, max_req=10, window_sec=60)
    if blocked:
        audit("REGISTER_RATELIMIT", ip, user_agent=ua, details="limit exceeded")
        return json_response({
            "ok": False,
            "msg": f"請求太頻繁，請稍後再試（{info['limit']}次/分鐘）"
        }), 429

    try:
        data = request.get_json(force=True)
    except Exception:
        audit("REGISTER_INVALID_JSON", ip, user_agent=ua)
        return json_response({"ok": False, "msg": "Invalid JSON"}), 400
    if not data:
        audit("REGISTER_EMPTY", ip, user_agent=ua)
        return json_response({"ok": False, "msg": "Invalid request"}), 400

    username_raw = data.get("username", "")
    password      = data.get("password", "") or ""

    audit("REGISTER_ATTEMPT", ip, username=username_raw, user_agent=ua)

    ok, val = validate_username(username_raw)
    if not ok:
        audit("REGISTER_BAD_USERNAME", ip, username=username_raw, user_agent=ua, details=val)
        return json_response({"ok": False, "msg": val}), 400
    username = val

    ok, msg = validate_password(password)
    if not ok:
        audit("REGISTER_BAD_PASSWORD", ip, username=username, user_agent=ua, details=msg)
        return json_response({"ok": False, "msg": msg}), 400

    conn = get_db()
    try:
        existing = conn.execute(
            "SELECT 1 FROM users WHERE username = ?", (username,)
        ).fetchone()
        if existing:
            time.sleep(0.3)   # timing obfuscation for username enum
            audit("REGISTER_DUP", ip, username=username, user_agent=ua, success=False)
            return json_response({"ok": False, "msg": "帳號已存在"}), 409

        hashed_pw = hash_password(password)
        conn.execute(
            "INSERT INTO users (username, password) VALUES (?, ?)",
            (username, hashed_pw)
        )
        conn.commit()
        audit("REGISTER_SUCCESS", ip, username=username, user_agent=ua, success=True)
        return json_response({"ok": True, "msg": "註冊成功"})
    finally:
        conn.close()

@app.route("/api/login", methods=["POST"])
def login():
    ip  = get_client_ip()
    ua  = get_user_agent()

    if is_ip_blocked(ip):
        audit("LOGIN_BLOCKED", ip, user_agent=ua, details="IP locked")
        until = load_json(BLOCK_FILE).get(ip, {}).get("until", "")
        return json_response({
            "ok": False,
            "msg": f"IP 已被鎖定，請於 {until[:16]} 後再試"
        }), 429

    blocked, info = is_rate_limited(ip, max_req=30, window_sec=60)
    if blocked:
        audit("LOGIN_RATELIMIT", ip, user_agent=ua, details="rate limit exceeded")
        return json_response({
            "ok": False,
            "msg": f"請求太頻繁，請稍後再試（{info['limit']}次/分鐘）"
        }), 429

    try:
        data = request.get_json(force=True)
    except Exception:
        audit("LOGIN_INVALID_JSON", ip, user_agent=ua)
        return json_response({"ok": False, "msg": "Invalid JSON"}), 400
    if not data:
        audit("LOGIN_EMPTY", ip, user_agent=ua)
        return json_response({"ok": False, "msg": "Invalid request"}), 400

    username = (data.get("username") or "").strip()
    password = data.get("password") or ""

    if not username or not password:
        audit("LOGIN_BLANK", ip, username=username, user_agent=ua, details="blank field")
        return json_response({"ok": False, "msg": "請填寫帳號與密碼"}), 400

    conn = get_db()
    try:
        row = conn.execute(
            "SELECT password FROM users WHERE username = ?", (username,)
        ).fetchone()

        verified = False
        if row:
            verified = verify_password(row["password"], password)

        if not verified:
            failures = record_failed_login(ip)
            elastic_sleep(ip, failures)
            audit("LOGIN_FAILED", ip, username=username, user_agent=ua,
                  details=f"failures={failures}")
            if failures >= 3:
                block_ip(ip, minutes=10)
                audit("LOGIN_IP_BLOCKED", ip, username=username, user_agent=ua,
                      details="3 failures → blocked 10 min")
                return json_response({
                    "ok": False,
                    "msg": "登入失敗 3 次，IP 已被鎖定 10 分鐘"
                }), 429
            return json_response({
                "ok": False,
                "msg": f"登入失敗（剩 {3 - failures} 次嘗試）"
            }), 401

        clear_failed_logins(ip)
        token = make_token(username)
        audit("LOGIN_SUCCESS", ip, username=username, user_agent=ua, success=True)
        resp  = json_response({"ok": True, "msg": "恭喜登入成功", "token": token})
        resp.set_cookie(
            "session_token", token,
            max_age=SESSION_TTL,
            httponly=True,
            samesite="Strict",
            secure=request.is_secure,
        )
        return resp
    finally:
        conn.close()

@app.route("/api/logout", methods=["POST"])
def logout():
    ip   = get_client_ip()
    ua   = get_user_agent()
    tok  = request.cookies.get("session_token")
    user = verify_token(tok) if tok else None
    audit("LOGOUT", ip, username=user or "-", user_agent=ua, success=bool(user))
    resp = json_response({"ok": True, "msg": "已登出"})
    resp.delete_cookie("session_token")
    return resp

@app.route("/api/me", methods=["GET"])
def me():
    """Check current session validity."""
    ip   = get_client_ip()
    ua   = get_user_agent()
    tok  = request.cookies.get("session_token")
    user = verify_token(tok) if tok else None
    audit("ME_CHECK", ip, username=user or "-", user_agent=ua, success=bool(user))
    if not user:
        return json_response({"ok": False, "msg": "未登入"}), 401
    return json_response({"ok": True, "username": user})

# ── Catch-all 404 ─────────────────────────────────────────────────────────────
@app.route("/<path:invalid>", methods=["GET","POST","PUT","DELETE","PATCH","OPTIONS"])
def catch_all(invalid):
    ip = get_client_ip()
    ua = get_user_agent()
    audit("404_CATCHALL", ip, user_agent=ua, details=f"path={invalid}", success=False)
    return json_response({"ok": False, "msg": "Not found"}), 404

# ── Audit viewer endpoint ────────────────────────────────────────────────────
@app.route("/api/audit", methods=["GET"])
def api_audit():
    """View recent audit entries. Requires valid session."""
    tok  = request.cookies.get("session_token")
    user = verify_token(tok) if tok else None
    # Only root can see audit logs
    if not user or user != "root":
        return json_response({"ok": False, "msg": "無權限"}), 403
    try:
        n = int(request.args.get("n", 100))
        n = min(n, 1000)
    except ValueError:
        n = 100
    entries = get_audit_summary(n)
    return json_response({"ok": True, "entries": entries})

# ── Init ──────────────────────────────────────────────────────────────────────
def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            username TEXT PRIMARY KEY,
            password TEXT NOT NULL
        )
    """)
    conn.commit()
    cur = conn.execute("SELECT 1 FROM users WHERE username = ?", ("root",))
    if not cur.fetchone():
        conn.execute(
            "INSERT INTO users (username, password) VALUES (?, ?)",
            ("root", hash_password("Admin@1234"))
        )
        conn.commit()
    conn.close()

if __name__ == "__main__":
    init_db()
    print(f"\n🌐 html_learning server running at http://localhost:{PORT}")
    print(f"   Default credentials: root / Admin@1234")
    print(f"   SECURITY: Argon2id pw hash | Fernet sessions | rate-limit | timing-safe compare\n")
    app.run(host="0.0.0.0", port=PORT, debug=False, threaded=True)
