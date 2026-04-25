#!/usr/bin/env python3
"""
hackme_web — Flask auth server
Hardened edition: timing-noise, account-enumeration protection,
CSRF tokens, strict CSP, full security headers, rate-limit amplification.
"""

import os, sqlite3, re, json, time, hashlib, secrets, hmac, threading, random, base64, fcntl
from datetime import datetime, timedelta
from functools import wraps
from flask import Flask, request, jsonify, send_from_directory, make_response
from cryptography.fernet import Fernet
import argon2
from flask_talisman import Talisman

# ── Paths ───────────────────────────────────────────────────────────────────
BASE_DIR   = os.path.dirname(os.path.abspath(__file__))
DB_PATH    = os.path.join(BASE_DIR, "database.db")
PUBLIC_DIR = os.path.join(BASE_DIR, "public")
BLOCK_FILE = os.path.join(BASE_DIR, "blocked_ips.json")
FAIL_FILE  = os.path.join(BASE_DIR, "fail_log.json")
RATE_FILE  = os.path.join(BASE_DIR, "rate_limit.json")
AUDIT_FILE = os.path.join(BASE_DIR, "audit.log")

# ── Secrets ─────────────────────────────────────────────────────────────────
SECRET_KEY = os.environ.get("SESSION_SECRET",
    open(os.path.join(BASE_DIR, ".fkey")).read() if os.path.exists(os.path.join(BASE_DIR, ".fkey")) else secrets.token_hex(32)
)

# ── Logging ───────────────────────────────────────────────────────────────────
_audit_lock = threading.Lock()

def audit(action, ip, user="-", success=False, ua="-", detail="-"):
    entry = {
        "ts":      datetime.now().isoformat(timespec="milliseconds"),
        "action":  action,
        "ip":      ip,
        "user":    user,
        "success": success,
        "ua":      ua[:200],
        "detail":  detail,
    }
    line = json.dumps(entry, ensure_ascii=False)
    _audit_lock.acquire()
    try:
        with open(AUDIT_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    finally:
        _audit_lock.release()

# ── JSON helpers ──────────────────────────────────────────────────────────────
def load_json(path):
    if not os.path.exists(path): return {}
    try:
        with open(path) as f: return json.load(f)
    except Exception:
        return {}

def save_json(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    os.replace(tmp, path)

# ── Atomic JSON ops (thread/process safe via fcntl) ─────────────────────────────
_json_locks = {}   # path → threading.Lock (held within a single process)
def _get_json_lock(path):
    if path not in _json_locks:
        _json_locks[path] = threading.Lock()
    return _json_locks[path]

def load_json_with_lock(path):
    with _get_json_lock(path):
        if not os.path.exists(path): return {}
        try:
            with open(path) as f: return json.load(f)
        except Exception:
            return {}

def save_json_with_lock(path, data):
    with _get_json_lock(path):
        tmp = path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        os.replace(tmp, path)

# ── CSRF double-submit helpers ─────────────────────────────────────────────────
def generate_csrf_dummy():
    """Dummy value for double-submit verification (matches cookie token)."""
    tok = request.cookies.get("csrf_token", "")
    return tok

def verify_csrf_double_submit(body_token):
    """
    Double-submit: body token must match cookie csrf_token.
    No session required — safe for /register.
    """
    cookie_tok = request.cookies.get("csrf_token", "")
    if not cookie_tok or not body_token:
        return False
    if cookie_tok != body_token:
        return False
    # Also verify it exists in DB and is not expired
    tok_hash = hashlib.sha256(cookie_tok.encode()).hexdigest()
    conn = get_db()
    row = conn.execute(
        "SELECT 1 FROM csrf_tokens WHERE token_hash=? AND expires_at>?",
        (tok_hash, datetime.now().isoformat())
    ).fetchone()
    conn.close()
    if not row:
        return False
    # Consume token (delete immediately — prevents replay)
    conn = get_db()
    conn.execute("DELETE FROM csrf_tokens WHERE token_hash=?", (tok_hash,))
    conn.commit()
    conn.close()
    return True

# ── Argon2 hasher ─────────────────────────────────────────────────────────────
_hasher = argon2.PasswordHasher(time_cost=3, memory_cost=65536,
                                parallelism=4, hash_len=32, salt_len=16)

def hash_password(pw):    return _hasher.hash(pw)
def verify_password(h, p):
    try:    return _hasher.verify(h, p)
    except argon2.exceptions.VerifyMismatchError: return False
    except argon2.exceptions.VerificationError: return False
    except argon2.exceptions.InvalidHash: return False
    except (argon2.exceptions.DecodeError, ValueError, TypeError): return False
    except Exception: return False

# ── Fernet (session tokens) ───────────────────────────────────────────────────
def _get_fernet_key():
    key_file = os.path.join(BASE_DIR, ".fkey")
    if os.path.exists(key_file):
        key = open(key_file, "rb").read()
        if len(key) >= 32:
            return key
    k = Fernet.generate_key()
    open(key_file, "wb").write(k)
    return k

fernet = Fernet(_get_fernet_key())
SESSION_TTL = 3600 * 4

def make_token(username):
    payload = json.dumps({
        "user":  username,
        "exp":   (datetime.now() + timedelta(seconds=SESSION_TTL)).isoformat(),
        "nonce": secrets.token_hex(8)
    }, ensure_ascii=False)
    return fernet.encrypt(payload.encode()).decode()

# ── Sensitive field encryption helpers (PII) ─────────────────────────────
def encrypt_field(value):
    if value is None:
        return None
    if not isinstance(value, str):
        value = str(value)
    if value == "":
        return ""
    return fernet.encrypt(value.encode("utf-8")).decode("utf-8")

def decrypt_field(value):
    if value is None or value == "":
        return ""
    if not isinstance(value, str):
        return str(value)
    try:
        return fernet.decrypt(value.encode("utf-8")).decode("utf-8")
    except Exception:
        # Backward compatibility with pre-encryption rows
        return value

def verify_token(token):
    try:
        data = json.loads(fernet.decrypt(token.encode()).decode())
        if datetime.now() > datetime.fromisoformat(data["exp"]): return None
        return data["user"]
    except Exception: return None

# ── Token hash (stored in DB for session lookup) ──────────────────────────────
def hash_token(token):
    return hashlib.sha256(token.encode()).hexdigest()

# ── Security helpers ────────────────────────────────────────────────────────────
# ── Trusted proxies (prevent X-Forwarded-For spoofing) ───────────────────────
TRUSTED_PROXY_IPS = {"127.0.0.1", "::1", "192.168.18.18"}
UNTRUSTED_XFF_MSG = "X-Forwarded-For from untrusted proxy rejected"
IP_BLOCKING_ENABLED = os.environ.get("IP_BLOCKING_ENABLED", "false").strip().lower() in {"1", "true", "on", "yes"}

# ── CSRF double-submit secret ─────────────────────────────────────────────────
CSRF_SECRET_KEY = os.environ.get("CSRF_SECRET_KEY",
    open(os.path.join(BASE_DIR, ".csrfkey")).read().strip()
    if os.path.exists(os.path.join(BASE_DIR, ".csrfkey")) else None
) or (lambda: (open(os.path.join(BASE_DIR, ".csrfkey"), "w").write(secrets.token_hex(32)),
               secrets.token_hex(32)))()


def get_client_ip():
    # Only trust X-Forwarded-For when the direct connection is from a trusted proxy
    xff = request.headers.get("X-Forwarded-For", "")
    if xff:
        # Check that the immediate upstream is a trusted proxy
        # In practice, your reverse proxy/Nginx sets X-Forwarded-For from the real client
        # We only use X-FF when the direct requestor is in our trusted list
        if request.remote_addr in TRUSTED_PROXY_IPS:
            return xff.split(",")[0].strip()
        # Direct connection from untrusted IP — ignore X-FF and use real remote_addr
    return request.remote_addr or "0.0.0.0"

def get_ua(): return request.headers.get("User-Agent","-")[:200]

def is_ip_blocked(ip):
    if not IP_BLOCKING_ENABLED:
        return False
    data = load_json_with_lock(BLOCK_FILE)
    entry = data.get(ip)
    if not entry: return False
    if datetime.now() < datetime.fromisoformat(entry["until"]): return True
    del data[ip]; save_json_with_lock(BLOCK_FILE, data); return False

def block_ip(ip, minutes=10):
    if not IP_BLOCKING_ENABLED:
        return
    data = load_json_with_lock(BLOCK_FILE)
    data[ip] = {"until": (datetime.now() + timedelta(minutes=minutes)).isoformat()}
    save_json_with_lock(BLOCK_FILE, data)

def record_failed_login(ip):
    now = datetime.now()
    data = load_json_with_lock(FAIL_FILE)
    data = {k:v for k,v in data.items() if now < datetime.fromisoformat(v["until"])}
    rec = data.get(ip, {"count":0})
    count = rec["count"] + 1
    data[ip] = {"count": count, "until": (now + timedelta(minutes=10)).isoformat()}
    save_json_with_lock(FAIL_FILE, data)
    return count

def clear_failed_logins(ip):
    data = load_json_with_lock(FAIL_FILE); data.pop(ip, None); save_json_with_lock(FAIL_FILE, data)

def is_rate_limited(ip, max_req=30, window_sec=60):
    now = datetime.now()
    data = load_json_with_lock(RATE_FILE)
    data = {k:v for k,v in data.items()
            if now - datetime.fromisoformat(v["window_start"]) < timedelta(seconds=window_sec)}
    entry = data.get(ip)
    if not entry:
        data[ip] = {"count":1, "window_start": now.isoformat()}
        save_json_with_lock(RATE_FILE, data); return False, {"count":1,"limit":max_req}
    count = entry["count"] + 1
    entry["count"] = count
    data[ip] = entry
    save_json_with_lock(RATE_FILE, data)
    if count > max_req: return True, {"count":count,"limit":max_req}
    return False, {"count":count,"limit":max_req}

# ── Constant-time delay (anti-timing-attack) ─────────────────────────────────
MIN_DELAY = 0.25   # seconds — minimum to obscure real verify time
MAX_DELAY = 0.90   # seconds — random extra delay

def timing_delay():
    """Add random jitter to obscure Argon2 timing."""
    time.sleep(MIN_DELAY + random.uniform(0, MAX_DELAY - MIN_DELAY))

# ── Account enumeration protection ─────────────────────────────────────────
# Real error messages — used in AUDIT only, never returned to client
REAL_MSGS = {
    "blank":    "請填寫帳號與密碼",
    "blocked":  "IP 已被鎖定，請稍後再試",
    "ratelimit":"請求太頻繁，請稍後再試",
    "no_user":  "登入失敗（帳號或密碼錯誤）",
    "bad_pw":   "登入失敗（帳號或密碼錯誤）",
    "inactive": "帳號已被停用",
    "locked":   "帳號已被鎖定",
}
# Generic message returned to client — identical for all failures
GENERIC_MSG = "登入失敗（帳號或密碼錯誤）"
GENERIC_MSG_REG = "註冊失敗，請稍後再試"

# ── CSRF token ────────────────────────────────────────────────────────────────
CSRF_TOKEN_TTL = 3600  # 1 hour

def make_csrf_token():
    return secrets.token_hex(16)

def store_csrf_token(token, username):
    conn = get_db()
    expires = (datetime.now() + timedelta(seconds=CSRF_TOKEN_TTL)).isoformat()
    conn.execute(
        "INSERT OR REPLACE INTO csrf_tokens (token_hash, username, expires_at) VALUES (?, ?, ?)",
        (hashlib.sha256(token.encode()).hexdigest(), username, expires)
    )
    conn.commit()
    conn.close()

def verify_csrf_token(token, username):
    if not token: return False
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT 1 FROM csrf_tokens WHERE token_hash=? AND username=? AND expires_at>?",
            (hashlib.sha256(token.encode()).hexdigest(), username, datetime.now().isoformat())
        ).fetchone()
        return row is not None
    finally:
        conn.close()

def delete_csrf_token(token):
    """Remove a used CSRF token from DB to prevent replay."""
    if not token: return
    h = hashlib.sha256(token.encode()).hexdigest()
    conn = get_db()
    conn.execute("DELETE FROM csrf_tokens WHERE token_hash=?", (h,))
    conn.commit()
    conn.close()

# ── CSRF require decorator ─────────────────────────────────────────────────────
def require_csrf(f):
    """Decorator: verify CSRF token, then DELETE it to prevent replay.
    Checks __public__ for unauthenticated routes (login), username for authenticated ones.
    Login: token MUST come from header or body (NOT cookie) to prevent browser-auto-submit bypass.
    """
    @wraps(f)
    def decorated(*args, **kwargs):
        # Extract CSRF token — try header first, then JSON body (never from cookie)
        csrf_tok = request.headers.get("X-CSRF-Token", "")
        body_username = None
        if request.is_json:
            body = request.get_json(silent=True) or {}
            body_username = body.get("username", "").strip()
            if not csrf_tok:
                csrf_tok = body.get("csrf_token", "")

        # Determine if user is authenticated
        tok = request.cookies.get("session_token")
        user = db_get_user_from_token(tok) if tok else None

        if user:
            # Authenticated routes — verify against real username only
            if not verify_csrf_token(csrf_tok, user):
                return json_resp({"ok": False, "msg": "CSRF token 無效或已過期"}), 403
        else:
            # Unauthenticated login — token must be in body or header (NOT cookie)
            if not csrf_tok:
                return json_resp({"ok": False, "msg": "CSRF token 缺失"}), 403
            # Valid if token matches __public__ OR target username
            if not verify_csrf_token(csrf_tok, "__public__") and \
               not (body_username and verify_csrf_token(csrf_tok, body_username)):
                return json_resp({"ok": False, "msg": "CSRF token 無效或已過期"}), 403

        # Delete immediately — token can only be used once (replay prevention)
        delete_csrf_token(csrf_tok)

        return f(*args, **kwargs)
    return decorated

# ── Password validation ────────────────────────────────────────────────────────
PW_RE = re.compile(r"^(?=.*[a-z])(?=.*[A-Z])(?=.*\d)(?=.*[!@#$%^&*()_+\-=\[\]{};':\"\\|,.<>\/?]).{8,128}$")

def validate_password(pw):
    if not isinstance(pw, str): return False, "密碼格式錯誤"
    if len(pw) < 8:   return False, "密碼至少需要 8 個字元"
    if len(pw) > 128: return False, "密碼太長（最多 128 字元）"
    if not re.search(r"[A-Z]", pw):  return False, "密碼必須包含大寫字母"
    if not re.search(r"[a-z]", pw):  return False, "密碼必須包含小寫字母"
    if not re.search(r"[!@#$%^&*()_+\-=\[\]{};':\"\\|,.<>\/?]", pw):
        return False, "密碼必須包含符號"
    return True, "OK"

# ── Database ───────────────────────────────────────────────────────────────────
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA foreign_keys = ON")
    except Exception:
        pass
    return conn

# RBAC / account status helpers
ROLE_RANK = {"user": 0, "manager": 1, "super_admin": 2}
ROLE_LABEL = {
    "super_admin": "最高管理者",
    "manager": "管理者",
    "user": "一般用戶",
}

def role_rank(role):
    return ROLE_RANK.get(role or "user", 0)

def normalize_text(v):
    return (v or "").strip() if isinstance(v, str) else ""

def parse_birthdate(v):
    if not v:
        return None
    v = str(v).strip()
    try:
        datetime.strptime(v, "%Y-%m-%d")
        return v
    except Exception:
        return None

def validate_id_number(v):
    if not isinstance(v, str):
        return False
    v = v.strip()
    if not v:
        return False
    return bool(re.fullmatch(r"^[A-Za-z0-9]{5,24}$", v))

def validate_phone(v):
    if not isinstance(v, str):
        return False
    v = v.strip()
    if not v:
        return False
    return bool(re.fullmatch(r"^\+?[0-9][0-9\-]{5,30}$", v))

def get_user_by_username(username):
    conn = get_db()
    try:
        return conn.execute(
            "SELECT id, username, email, nickname, real_name, birthdate, id_number, phone, status, role, blocked_until "
            "FROM users WHERE username=?",
            (username,)
        ).fetchone()
    finally:
        conn.close()

def get_current_user_ctx():
    tok = request.cookies.get("session_token")
    if not tok:
        return None
    username = db_get_user_from_token(tok)
    if not username:
        return None
    return get_user_by_username(username)

def user_public_payload(row):
    if not row:
        return None
    return {
        "id": row["id"],
        "username": row["username"],
        "email": row["email"],
        "nickname": decrypt_field(row["nickname"]),
        "real_name": decrypt_field(row["real_name"]),
        "birthdate": decrypt_field(row["birthdate"]),
        "id_number": decrypt_field(row["id_number"]),
        "phone": decrypt_field(row["phone"]),
        "status": row["status"],
        "role": row["role"],
        "role_label": ROLE_LABEL.get(row["role"], row["role"]),
        "blocked_until": row["blocked_until"],
    }

def ensure_user_columns(conn):
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(users)").fetchall()}
    for col, ddl in (
        ("nickname", "ALTER TABLE users ADD COLUMN nickname TEXT"),
        ("blocked_until", "ALTER TABLE users ADD COLUMN blocked_until TEXT"),
    ):
        if col not in cols:
            conn.execute(ddl)

def init_db():
    conn = get_db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            username   TEXT    NOT NULL UNIQUE,
            email      TEXT,
            nickname   TEXT,
            real_name  TEXT,
            birthdate  TEXT,
            id_number  TEXT,
            phone      TEXT,
            blocked_until TEXT,
            status     TEXT    NOT NULL DEFAULT 'active',
            role       TEXT    NOT NULL DEFAULT 'user',
            created_at TEXT    NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT    NOT NULL DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS user_passwords (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id         INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            password_hash   TEXT    NOT NULL,
            created_at      TEXT    NOT NULL DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS login_attempts (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id      INTEGER REFERENCES users(id) ON DELETE SET NULL,
            ip_address   TEXT,
            user_agent   TEXT,
            success      INTEGER NOT NULL DEFAULT 0,
            attempted_at TEXT    NOT NULL DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS sessions (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id      INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            token_hash   TEXT    NOT NULL UNIQUE,
            ip_address   TEXT,
            user_agent   TEXT,
            expires_at   TEXT    NOT NULL,
            created_at   TEXT    NOT NULL DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS csrf_tokens (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            token_hash   TEXT    NOT NULL UNIQUE,
            username     TEXT    NOT NULL,
            expires_at   TEXT    NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_sessions_token_hash ON sessions(token_hash);
        CREATE INDEX IF NOT EXISTS idx_sessions_user_id     ON sessions(user_id);
        CREATE INDEX IF NOT EXISTS idx_login_attempts_user  ON login_attempts(user_id);
        CREATE INDEX IF NOT EXISTS idx_login_attempts_ip    ON login_attempts(ip_address);
        CREATE INDEX IF NOT EXISTS idx_login_attempts_time  ON login_attempts(attempted_at);
        CREATE INDEX IF NOT EXISTS idx_csrf_token_hash      ON csrf_tokens(token_hash);
    """)

    ensure_user_columns(conn)

    # Keep role value consistent when coming from older schema
    try:
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(users)").fetchall()}
        if "role" not in cols:
            conn.execute("ALTER TABLE users ADD COLUMN role TEXT NOT NULL DEFAULT 'user'")
    except Exception:
        pass
    conn.execute("UPDATE users SET role='user' WHERE role IS NULL OR role=''")

    # Rebuild root account to the requested highest-privilege credential: root/root
    now = datetime.now().isoformat()
    conn.execute("DELETE FROM user_passwords WHERE user_id IN (SELECT id FROM users WHERE username='root')")
    conn.execute("DELETE FROM sessions WHERE user_id IN (SELECT id FROM users WHERE username='root')")
    conn.execute("DELETE FROM users WHERE username='root'")
    root_cur = conn.execute(
        "INSERT INTO users (username, status, role, created_at, updated_at) VALUES (?, 'active', 'super_admin', ?, ?)",
        ("root", now, now)
    )
    conn.execute(
        "INSERT INTO user_passwords (user_id, password_hash, created_at) VALUES (?, ?, ?)",
        (root_cur.lastrowid, hash_password("root"), now)
    )

    # Manager account: s92137 (keep password if already existed)
    row = conn.execute("SELECT id FROM users WHERE username='s92137'").fetchone()
    if row:
        conn.execute(
            "UPDATE users SET role='manager', status='active', updated_at=? WHERE username='s92137'",
            (now,)
        )
    else:
        mgr_cur = conn.execute(
            "INSERT INTO users (username, status, role, created_at, updated_at) VALUES (?, 'active', 'manager', ?, ?)",
            ("s92137", now, now)
        )
        conn.execute(
            "INSERT INTO user_passwords (user_id, password_hash, created_at) VALUES (?, ?, ?)",
            (mgr_cur.lastrowid, hash_password("Manager@1234"), now)
        )

    conn.commit()
    conn.close()

# ── Session helpers ─────────────────────────────────────────────────────────────
def db_save_session(user_id, token, ip, ua):
    conn = get_db()
    expires = (datetime.now() + timedelta(seconds=SESSION_TTL)).isoformat()
    conn.execute(
        "INSERT INTO sessions (user_id, token_hash, ip_address, user_agent, expires_at) VALUES (?, ?, ?, ?, ?)",
        (user_id, hash_token(token), ip, ua, expires)
    )
    conn.commit()
    conn.close()

def db_delete_session(token):
    conn = get_db()
    conn.execute("DELETE FROM sessions WHERE token_hash=?", (hash_token(token),))
    conn.commit()
    conn.close()

def db_clean_expired_sessions():
    conn = get_db()
    conn.execute("DELETE FROM sessions WHERE expires_at < ?", (datetime.now().isoformat(),))
    conn.commit()
    conn.close()

def db_get_user_from_token(token):
    conn = get_db()
    row = conn.execute(
        "SELECT u.username FROM sessions s JOIN users u ON u.id=s.user_id WHERE s.token_hash=? AND s.expires_at>?",
        (hash_token(token), datetime.now().isoformat())
    ).fetchone()
    conn.close()
    return row["username"] if row else None

def db_get_user_role(username):
    conn = get_db()
    row = conn.execute(
        "SELECT role FROM users WHERE username=?", (username,)
    ).fetchone()
    conn.close()
    return row["role"] if row else None

# ── Flask app ──────────────────────────────────────────────────────────────────
app = Flask(__name__, static_folder=PUBLIC_DIR, static_url_path="")
app.config["MAX_CONTENT_LENGTH"] = 64 * 1024

# ── Security Headers (via Flask-Talisman) ─────────────────────────────────────
# CSP: allow inline scripts for current single-page UI (testing mode)
talisman = Talisman(app,
    content_security_policy={
        "default-src": "'self'",
        "script-src":  "'self' 'unsafe-inline'",
        "style-src":   "'self' 'unsafe-inline'",   # allow inline styles (needed by the SPA)
        "img-src":     "'self' data:",
        "font-src":    "'self'",
        "connect-src": "'self'",
        "frame-ancestors": "'none'",
        "form-action":  "'self'",
        "base-uri":    "'self'",
        "object-src":  "'none'",
    },
    referrer_policy="no-referrer",
    feature_policy={},
    force_https=False,        # SSL termination at proxy level
)

# ── Legacy security headers (supplement Talisman) ─────────────────────────────
@app.after_request
def extra_security_headers(response):
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Permitted-Cross-Domain-Policies"] = "none"
    # Talisman sets Server header; override to avoid fingerprinting
    response.headers["Server"] = "WebServer"
    response.headers.pop("X-Powered-By", None)
    if request.path.startswith("/api"):
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, private"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response

# ── CORS (tightly scoped — no wildcard) ────────────────────────────────────────
@app.before_request
def restrict_cors():
    if request.method == "OPTIONS":
        origin = request.headers.get("Origin", "")
        # Only allow same-origin
        if origin and origin != request.host_url.rstrip("/"):
            return ("", 204)

# ── JSON response helper ───────────────────────────────────────────────────────
def json_resp(data, status=200):
    r = make_response(jsonify(data), status)
    r.headers["X-Content-Type-Options"] = "nosniff"
    r.headers["Cache-Control"] = "no-store"
    return r

# ── Routes ─────────────────────────────────────────────────────────────────────
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
                        samesite="Strict", secure=request.is_secure)
    # Logged-in users keep their per-user csrf_token cookie (set at login)
    return resp

# ── GET CSRF token ─────────────────────────────────────────────────────────────
@app.route("/api/csrf-token", methods=["GET"])
def get_csrf_token():
    tok = request.cookies.get("session_token")
    user = db_get_user_from_token(tok) if tok else None
    if not user:
        return json_resp({"ok":False,"msg":"未登入"}), 401
    token = make_csrf_token()
    store_csrf_token(token, user)
    return json_resp({"ok":True,"csrf_token":token})

@app.route("/api/register", methods=["POST"])
def register():
    ip, ua = get_client_ip(), get_ua()
    audit("REGISTER_ATTEMPT", ip, ua=ua)
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

    ok, msg = validate_password(password)
    if not ok:
        audit("REGISTER_BAD_PW", ip, username, ua=ua, detail=msg)
        return json_resp({"ok":False,"msg":msg}), 400

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
            "INSERT INTO users (username, nickname, real_name, birthdate, id_number, phone, status, role, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, 'active', 'user', ?, ?)",
            (username, encrypt_field(nickname), encrypt_field(real_name), encrypt_field(birthdate), encrypt_field(id_number), encrypt_field(phone), now, now)
        )
        user_id = cur.lastrowid
        conn.execute(
            "INSERT INTO user_passwords (user_id, password_hash, created_at) VALUES (?, ?, ?)",
            (user_id, hash_password(password), now)
        )
        conn.commit()
        audit("REGISTER_OK", ip, username, ua=ua, success=True)
        return json_resp({"ok":True,"msg":"註冊成功"})
    finally:
        conn.close()

@app.route("/api/login", methods=["POST"])
@require_csrf
def login():
    ip, ua = get_client_ip(), get_ua()

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

    try:    data = request.get_json(force=True)
    except: return json_resp({"ok":False,"msg":"Invalid JSON"}), 400
    if not isinstance(data, dict): return json_resp({"ok":False,"msg":"Invalid request"}), 400

    username = (data.get("username","") if isinstance(data.get("username"), str) else "").strip()
    password = data.get("password","") if isinstance(data.get("password"), str) else ""

    # Generic blank check — same message regardless of which field
    if not username or not password:
        audit("LOGIN_BLANK", ip, username, ua=ua, detail="blank field")
        timing_delay()
        return json_resp({"ok":False,"msg":"請填寫帳號與密碼"}), 400

    conn = get_db()
    try:
        user_row = conn.execute(
            "SELECT id, username, status, blocked_until, role FROM users WHERE username=?", (username,)
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
        if verified:
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
            conn.commit()

            # Create token + save session to DB
            token = make_token(username)
            db_save_session(user_row["id"], token, ip, ua)

            audit("LOGIN_OK", ip, username, ua=ua, success=True)
            resp = json_resp({"ok":True,"msg":"恭喜登入成功","token":token})
            resp.set_cookie("session_token", token, max_age=SESSION_TTL,
                            httponly=True, samesite="Strict",
                            secure=request.is_secure)
            # Invalidate the public CSRF token and issue a fresh per-user token
            new_csrf = make_csrf_token()
            store_csrf_token(new_csrf, username)
            resp.set_cookie("csrf_token", new_csrf, max_age=CSRF_TOKEN_TTL,
                            httponly=False, samesite="Strict",
                            secure=request.is_secure)
            return resp
        else:
            # Log failed attempt
            user_id_for_log = user_row["id"] if user_row else None
            conn.execute(
                "INSERT INTO login_attempts (user_id, ip_address, user_agent, success, attempted_at) VALUES (?, ?, ?, 0, ?)",
                (user_id_for_log, ip, ua, now)
            )
            conn.commit()

            failures = record_failed_login(ip)
            audit("LOGIN_FAIL", ip, username, ua=ua, detail=f"failures={failures}")

            # Generic message — never distinguish "no user" from "bad pw"
            if failures >= 3 and IP_BLOCKING_ENABLED:
                block_ip(ip, 10)
                audit("LOGIN_IP_BLOCKED", ip, username, ua=ua, detail="3 failures → 10 min block")
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
    resp.delete_cookie("session_token")
    return resp

@app.route("/api/me", methods=["GET"])
def me():
    ctx = get_current_user_ctx()
    if not ctx:
        return json_resp({"ok":False,"msg":"未登入"}), 401
    return json_resp({
        "ok": True,
        "username": ctx["username"],
        "role": ctx["role"],
        "role_label": ROLE_LABEL.get(ctx["role"], ctx["role"]),
        "status": ctx["status"],
        "nickname": decrypt_field(ctx["nickname"]),
    })

@app.route("/api/audit", methods=["GET"])
def api_audit():
    tok = request.cookies.get("session_token")
    user = db_get_user_from_token(tok) if tok else None
    if not user: return json_resp({"ok":False,"msg":"未授權"}), 401
    if role_rank(db_get_user_role(user) or "user") < role_rank("super_admin"):
        audit("AUDIT_FORBIDDEN", get_client_ip(), user, detail="non-admin attempted audit access")
        return json_resp({"ok":False,"msg":"需要最高管理者權限"}), 403

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

@app.route("/api/admin/users", methods=["GET","POST"])
@require_csrf
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
            now = datetime.now()
            if actor_role == "super_admin":
                rows = conn.execute(
                    "SELECT id, username, email, nickname, real_name, birthdate, id_number, phone, status, role, blocked_until "
                    "FROM users ORDER BY id ASC"
                ).fetchall()
                data = [user_public_payload(r) for r in rows]
            else:
                rows = conn.execute(
                    "SELECT id, username, status, role, blocked_until FROM users ORDER BY id ASC"
                ).fetchall()
                data = []
                for r in rows:
                    blocked_until = r["blocked_until"]
                    blocked = False
                    if blocked_until:
                        try:
                            blocked = datetime.fromisoformat(blocked_until) > now
                        except Exception:
                            blocked = False
                    data.append({
                        "id": r["id"],
                        "username": r["username"],
                        "nickname": "",
                        "real_name": "",
                        "status": r["status"],
                        "role": r["role"],
                        "blocked_until": r["blocked_until"],
                        "blocked": blocked,
                    })
        finally:
            conn.close()
        return json_resp({
            "ok": True,
            "users": data,
            "can_manage": role_rank(actor_role) >= role_rank("super_admin")
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

    ok, msg = validate_password(password)
    if not ok:
        return json_resp({"ok":False,"msg":msg}), 400

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

@app.route("/api/admin/users/<int:user_id>", methods=["PUT","DELETE"])
@require_csrf
def admin_user_item(user_id):
    actor = get_current_user_ctx()
    if not actor:
        return json_resp({"ok":False,"msg":"未登入"}), 401
    actor_role = "super_admin" if actor["username"] == "root" else actor["role"]
    if role_rank(actor_role) < role_rank("super_admin"):
        return json_resp({"ok":False,"msg":"只有最高權限可管理帳號"}), 403

    conn = get_db()
    try:
        target = conn.execute("SELECT id, username, role FROM users WHERE id=?", (user_id,)).fetchone()
        if not target:
            return json_resp({"ok":False,"msg":"找不到帳號"}), 404

        if request.method == "DELETE":
            if target["username"] == "root":
                return json_resp({"ok":False,"msg":"不可刪除最高管理者帳號"}), 403
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
            val = normalize_text(data["status"])
            if val not in ("active","inactive"):
                return json_resp({"ok":False,"msg":"帳號狀態錯誤"}), 400
            updates.append("status=?")
            params.append(val)
        if "role" in data:
            val = normalize_text(data["role"])
            if val not in ROLE_RANK:
                return json_resp({"ok":False,"msg":"不支援的角色"}), 400
            if target["username"] == "root" and val != "super_admin":
                return json_resp({"ok":False,"msg":"最高管理者角色不可變更"}), 403
            updates.append("role=?")
            params.append(val)
        if "password" in data and isinstance(data["password"], str) and data["password"]:
            ok, msg = validate_password(data["password"])
            if not ok:
                return json_resp({"ok":False,"msg":msg}), 400
            conn.execute(
                "INSERT INTO user_passwords (user_id, password_hash, created_at) VALUES (?, ?, ?)",
                (user_id, hash_password(data["password"]), datetime.now().isoformat())
            )
        if "username" in data:
            return json_resp({"ok":False,"msg":"不允許變更帳號名稱"}), 400

        if updates:
            updates.append("updated_at=?")
            params.append(datetime.now().isoformat())
            params.append(user_id)
            sql = "UPDATE users SET " + ", ".join(updates) + " WHERE id=?"
            conn.execute(sql, params)
            conn.commit()
        audit("ADMIN_UPDATE_USER", get_client_ip(), user=actor["username"], success=True, ua=get_ua(),
              detail=f"target_id={user_id}")
        return json_resp({"ok":True,"msg":"帳號已更新"})
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

@app.route("/<path:invalid>", methods=["GET","POST","PUT","DELETE","PATCH","OPTIONS"])
def catch_all(invalid):
    ip, ua = get_client_ip(), get_ua()
    audit("404_CATCHALL", ip, ua=ua, detail=f"path={invalid}")
    return json_resp({"ok":False,"msg":"Not found"}), 404

# ── Start ──────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    init_db()
    audit("SERVER_START", "0.0.0.0", detail="hackme_web server started — hardened edition")
    print(f"\n🌐  hackme_web server running at http://localhost:5000")
    print(f"    Default credentials: root / root")
    print(f"    Audit log: {AUDIT_FILE}")
    print(f"    Security: Argon2id + timing-noise + account-enum-protection + CSRF + strict-headers\n")
    app.run(host="0.0.0.0", port=5000, debug=False)
