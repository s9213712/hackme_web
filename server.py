#!/usr/bin/env python3
"""
hackme_web — Flask auth server
Hardened edition: timing-noise, account-enumeration protection,
CSRF tokens, strict CSP, full security headers, rate-limit amplification.
"""

import os, sqlite3, re, json, time, hashlib, secrets, hmac, threading, random, base64, fcntl, subprocess, signal, sys, platform, smtplib, ssl
from ipaddress import ip_address
from datetime import datetime, timedelta
from email.message import EmailMessage
from functools import wraps
from flask import Flask, request, jsonify, send_from_directory, make_response
from cryptography.fernet import Fernet
import argon2
from flask_talisman import Talisman
from routes.chat import register_chat_routes
from routes.public import register_public_routes
from routes.users import register_user_routes
from routes.operations import register_operation_routes
from services.audit import (
    _chain_hash,
    audit,
    canonical_json,
    configure_audit_service,
    verify_audit_integrity,
)
from services.auth import (
    CSRF_TOKEN_TTL,
    SESSION_TTL,
    configure_auth_service,
    db_delete_session,
    db_get_user_from_token,
    db_save_session,
    delete_csrf_token,
    get_current_user_ctx,
    get_request_csrf_token,
    hash_password,
    json_resp,
    make_csrf_token,
    make_token,
    require_csrf,
    require_csrf_safe,
    store_csrf_token,
    timing_delay,
    verify_csrf_token,
    verify_csrf_double_submit,
    verify_password,
)
from services.settings import (
    DEFAULT_SETTINGS,
    configure_settings_service,
    get_system_settings,
    init_system_settings_table,
    load_settings,
    refresh_system_settings,
    save_settings,
    _import_legacy_settings_files,
    _seed_missing_settings_to_db,
)
from services.violations import (
    add_violation,
    check_and_apply_auto_violations,
    configure_violations_service,
    detect_chat_violation,
    get_latest_violation,
    parse_iso_to_datetime,
    verify_violation_integrity,
)
from services.security_events import (
    block_ip,
    clear_failed_logins,
    configure_security_events_service,
    is_ip_blocked,
    is_rate_limited,
    record_403_access,
    record_login_failure,
)
from services.bootstrap import (
    apply_schema_migrations,
    configure_bootstrap_service,
    init_db,
    migrate_legacy_json_artifacts,
    migrate_legacy_json_to_db,
)
from services.chat_support import (
    append_chat_record,
    configure_chat_support_service,
    ensure_official_chat_room,
    ensure_user_official_room_membership,
)

# ── Paths ───────────────────────────────────────────────────────────────────
BASE_DIR   = os.path.dirname(os.path.abspath(__file__))
SERVER_STARTED_AT = datetime.now().isoformat()
SERVER_VERSION = os.environ.get("HTML_LEARNING_SERVER_VERSION", f"boot-{SERVER_STARTED_AT}")

def _env_path(name, default_path):
    value = os.environ.get(name, "").strip()
    if not value:
        return default_path
    return value if os.path.isabs(value) else os.path.abspath(value)

DB_DIR = _env_path("HTML_LEARNING_DB_DIR", os.path.join(BASE_DIR, "database"))
DB_PATH = os.path.join(DB_DIR, "database.db")
LOG_DIR = _env_path("HTML_LEARNING_LOG_DIR", os.path.join(BASE_DIR, "logs"))
CHAT_DIR = _env_path("HTML_LEARNING_CHAT_DIR", os.path.join(BASE_DIR, "chats"))
ANCHOR_DIR = _env_path("HTML_LEARNING_ANCHOR_DIR", os.path.join(BASE_DIR, "anchors"))
PUBLIC_DIR = os.path.join(BASE_DIR, "public")
AUDIT_LOG_PATH = os.path.join(LOG_DIR, "audit.log")
SERVER_LOG_PATH = os.path.join(LOG_DIR, "server.log")
AUDIT_ANCHOR_PATH = os.path.join(ANCHOR_DIR, "audit_head.jsonl")
AUDIT_ANCHOR_LATEST_PATH = os.path.join(ANCHOR_DIR, "audit_head_latest.json")
AUDIT_ANCHOR_INTERVAL_SECONDS = 60

os.makedirs(DB_DIR, exist_ok=True)
os.makedirs(LOG_DIR, exist_ok=True)
os.makedirs(CHAT_DIR, exist_ok=True)
os.makedirs(ANCHOR_DIR, exist_ok=True)
# ── Hash-chain integrity key (server-side only, not exposed to client) ───────
# Seed derived from SECRET_KEY so it survives restarts (prevents chain-break on reboot)
def _get_chain_seed():
    # Try to read persisted seed
    seed_file = os.path.join(BASE_DIR, ".chain_seed")
    if os.path.exists(seed_file):
        try:
            with open(seed_file) as f:
                return f.read().strip()
        except Exception:
            pass
    # First run — generate and persist
    import secrets as _s
    seed = _s.token_hex(24)
    with open(seed_file, "w") as f:
        f.write(seed)
    os.chmod(seed_file, 0o600)  # readable only by owner
    return seed

CHAIN_SEED = _get_chain_seed()

# ── Secrets ─────────────────────────────────────────────────────────────────
SECRET_KEY = os.environ.get("SESSION_SECRET",
    open(os.path.join(BASE_DIR, ".fkey")).read() if os.path.exists(os.path.join(BASE_DIR, ".fkey")) else secrets.token_hex(32)
)

_INTEGRITY_KEY = SECRET_KEY.encode()  # HMAC 金鑰（在 SECRET_KEY 之後定義）


def _build_fernet(secret):
    if isinstance(secret, bytes):
        secret = secret.decode("utf-8", errors="ignore")
    secret = str(secret).strip()
    try:
        return Fernet(secret.encode("utf-8"))
    except Exception:
        derived = base64.urlsafe_b64encode(hashlib.sha256(secret.encode("utf-8")).digest())
        return Fernet(derived)


fernet = _build_fernet(SECRET_KEY)

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

LEGACY_FAIL_LOG = os.path.join(BASE_DIR, "fail_log.json")
LEGACY_BLOCKED_IPS = os.path.join(BASE_DIR, "blocked_ips.json")
LEGACY_RATE_LIMIT = os.path.join(BASE_DIR, "rate_limit.json")
LEGACY_AUDIT_LOG = AUDIT_LOG_PATH

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
def parse_ip_set(raw_value):
    if not raw_value:
        return set()
    values = set()
    for token in str(raw_value).split(","):
        token = token.strip()
        if not token:
            continue
        try:
            values.add(str(ip_address(token)))
        except Exception:
            continue
    return values

def _env_bool(name, default=False):
    value = os.environ.get(name)
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "on", "yes"}

def _env_session_samesite():
    s = os.environ.get("SESSION_COOKIE_SAMESITE", "Strict").strip().lower()
    return "Strict" if s in {"", "strict"} else ("Lax" if s == "lax" else "None")

TRUSTED_PROXY_IPS = parse_ip_set(os.environ.get("TRUSTED_PROXY_IPS", ""))
USE_XFF = os.environ.get("USE_XFF", "false").strip().lower() in {"1", "true", "on", "yes"}
UNTRUSTED_XFF_MSG = "X-Forwarded-For from untrusted proxy rejected"
IP_BLOCKING_ENABLED = _env_bool("IP_BLOCKING_ENABLED", default=False)
FORCE_HTTPS = _env_bool("FORCE_HTTPS", default=False)
SESSION_COOKIE_SECURE = _env_bool("SESSION_COOKIE_SECURE", default=False)
SESSION_COOKIE_HTTPONLY = _env_bool("SESSION_COOKIE_HTTPONLY", default=True)
SESSION_COOKIE_SAMESITE = _env_session_samesite()

# ── CSRF double-submit secret ─────────────────────────────────────────────────
CSRF_SECRET_KEY = os.environ.get("CSRF_SECRET_KEY",
    open(os.path.join(BASE_DIR, ".csrfkey")).read().strip()
    if os.path.exists(os.path.join(BASE_DIR, ".csrfkey")) else None
) or (lambda: (open(os.path.join(BASE_DIR, ".csrfkey"), "w").write(secrets.token_hex(32)),
               secrets.token_hex(32)))()


def get_client_ip():
    remote = request.remote_addr or ""
    try:
        remote = str(ip_address(remote))
    except Exception:
        remote = "0.0.0.0"

    # By default, do not trust X-Forwarded-For unless explicitly enabled.
    # This avoids spoofing when app is accessed directly (local tests / direct TLS).
    if not USE_XFF or not TRUSTED_PROXY_IPS:
        return remote

    # Only trust XFF when request source is a trusted proxy in allow-list.
    xff = request.headers.get("X-Forwarded-For", "")
    if xff:
        if remote in TRUSTED_PROXY_IPS:
            parts = [p.strip() for p in xff.split(",") if p.strip()]
            if parts:
                try:
                    return str(ip_address(parts[0]))
                except Exception:
                    return remote
    return remote

def get_ua(): return request.headers.get("User-Agent","-")[:200]

def is_audit_chain_enabled():
    return bool(get_system_settings().get("audit_chain_enabled", False))

def is_ip_blocking_enabled():
    settings = get_system_settings()
    if "ip_blocking_enabled" in settings:
        return bool(settings.get("ip_blocking_enabled", False))
    return bool(IP_BLOCKING_ENABLED)

# ── Domain constants / validation helpers ─────────────────────────────────────
ROLE_RANK = {"user": 0, "manager": 1, "super_admin": 2}
ROLE_LABEL = {
    "super_admin": "最高管理者",
    "manager": "管理者",
    "user": "一般用戶",
}
MAX_MANAGERS = 5
VIOLATION_APPEAL_WINDOW_HOURS = 24
CHAT_MESSAGE_MAX_LEN = 500
OFFICIAL_CHAT_ROOM_NAME = "官方聊天室"

PW_RE = re.compile(r"^(?=.*[a-z])(?=.*[A-Z])(?=.*\d)(?=.*[!@#$%^&*()_+\-=\[\]{};':\"\\|,.<>\/?]).{8,128}$")


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


def parse_positive_int(v, default=None, min_value=1, max_value=None):
    if v is None:
        return default
    if isinstance(v, bool):
        return None
    if isinstance(v, float) and not v.is_integer():
        return None
    if isinstance(v, str):
        v = v.strip()
    try:
        value = int(v)
    except (TypeError, ValueError):
        return None
    if value < min_value:
        return None
    if max_value is not None and value > max_value:
        return None
    return value


def validate_password(pw):
    if not isinstance(pw, str):
        return False, "密碼格式錯誤"
    if len(pw) < 8:
        return False, "密碼至少需要 8 個字元"
    if len(pw) > 128:
        return False, "密碼太長（最多 128 字元）"
    if not re.search(r"[A-Z]", pw):
        return False, "密碼必須包含大寫字母"
    if not re.search(r"[a-z]", pw):
        return False, "密碼必須包含小寫字母"
    if not re.search(r"[!@#$%^&*()_+\-=\[\]{};':\"\\|,.<>\/?]", pw):
        return False, "密碼必須包含符號"
    return True, "OK"


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


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA foreign_keys = ON")
    except Exception:
        pass
    return conn


def count_role(role):
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT COUNT(*) as c FROM users WHERE role=? AND username<>'root'",
            (role,)
        ).fetchone()
        return row["c"] if row else 0
    finally:
        conn.close()


def get_user_by_username(username):
    conn = get_db()
    try:
        return conn.execute(
            "SELECT id, username, email, nickname, real_name, birthdate, id_number, phone, status, role, blocked_until, violation_count, chat_violation_warned "
            "FROM users WHERE username=?",
            (username,)
        ).fetchone()
    finally:
        conn.close()


def user_public_payload(row):
    if not row:
        return None
    data = dict(row)
    return {
        "id": data.get("id"),
        "username": data.get("username"),
        "nickname": decrypt_field(data.get("nickname")),
        "real_name": decrypt_field(data.get("real_name")),
        "birthdate": decrypt_field(data.get("birthdate")),
        "id_number": decrypt_field(data.get("id_number")),
        "phone": decrypt_field(data.get("phone")),
        "email": data.get("email"),
        "status": data.get("status"),
        "role": data.get("role"),
        "role_label": ROLE_LABEL.get(data.get("role"), data.get("role")),
        "blocked_until": data.get("blocked_until"),
        "violation_count": data.get("violation_count") or 0,
    }


def ensure_user_columns(conn):
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(users)").fetchall()}
    additions = [
        ("role", "TEXT NOT NULL DEFAULT 'user'"),
        ("nickname", "TEXT"),
        ("real_name", "TEXT"),
        ("birthdate", "TEXT"),
        ("id_number", "TEXT"),
        ("phone", "TEXT"),
        ("blocked_until", "TEXT"),
        ("violation_count", "INTEGER NOT NULL DEFAULT 0"),
        ("chat_violation_warned", "INTEGER NOT NULL DEFAULT 0"),
        ("updated_at", "TEXT"),
    ]
    for name, ddl in additions:
        if name not in cols:
            conn.execute(f"ALTER TABLE users ADD COLUMN {name} {ddl}")


def ensure_secure_audit_columns(conn):
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(secure_audit)").fetchall()}
    for name in ("prev_hash", "entry_hash"):
        if name not in cols:
            conn.execute(f"ALTER TABLE secure_audit ADD COLUMN {name} TEXT")


def ensure_appeal_columns(conn):
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(violation_appeals)").fetchall()}
    additions = [
        ("latest_violation_id", "INTEGER"),
        ("violation_count_snapshot", "INTEGER NOT NULL DEFAULT 0"),
        ("penalty_points", "INTEGER NOT NULL DEFAULT 0"),
        ("pre_status", "TEXT NOT NULL DEFAULT 'active'"),
        ("pre_role", "TEXT NOT NULL DEFAULT 'user'"),
        ("review_note", "TEXT"),
    ]
    for name, ddl in additions:
        if name not in cols:
            conn.execute(f"ALTER TABLE violation_appeals ADD COLUMN {name} {ddl}")

def db_get_user_role(username):
    conn = get_db()
    row = conn.execute(
        "SELECT role FROM users WHERE username=?", (username,)
    ).fetchone()
    conn.close()
    return row["role"] if row else None


def activate_emergency_lockdown(reason):
    conn = get_db()
    try:
        init_system_settings_table(conn)
        conn.execute(
            "INSERT OR REPLACE INTO system_settings (key, value, updated_at, updated_by) VALUES (?, ?, ?, ?)",
            ("maintenance_mode", "True", datetime.now().isoformat(), "audit_guard")
        )
        conn.commit()
        refresh_system_settings()
    finally:
        conn.close()
    try:
        audit("EMERGENCY_LOCKDOWN_ENABLED", get_client_ip(), user="audit_guard", success=True, detail=reason)
    except Exception:
        pass


configure_settings_service(
    get_db=get_db,
    load_json=load_json,
    base_dir=BASE_DIR,
)
configure_auth_service(
    get_db=get_db,
    get_user_by_username=get_user_by_username,
    fernet=fernet,
    session_ttl=SESSION_TTL,
    csrf_token_ttl=CSRF_TOKEN_TTL,
)
configure_audit_service(
    get_db=get_db,
    chain_seed=CHAIN_SEED,
    integrity_key=_INTEGRITY_KEY,
    audit_log_path=AUDIT_LOG_PATH,
    audit_anchor_path=AUDIT_ANCHOR_PATH,
    audit_anchor_latest_path=AUDIT_ANCHOR_LATEST_PATH,
    audit_anchor_interval_seconds=AUDIT_ANCHOR_INTERVAL_SECONDS,
)
configure_violations_service(
    get_db=get_db,
    get_system_settings=get_system_settings,
    audit=audit,
    get_client_ip=get_client_ip,
    chain_seed=CHAIN_SEED,
    integrity_key=_INTEGRITY_KEY,
)
configure_security_events_service(
    get_db=get_db,
    get_system_settings=get_system_settings,
    audit=audit,
    is_ip_blocking_enabled=is_ip_blocking_enabled,
)
configure_bootstrap_service(
    get_db=get_db,
    db_path=os.path.join(DB_DIR, "bootstrap"),
    schema_path=os.path.join(BASE_DIR, "database", "bootstrap.schema.sql"),
    legacy_fail_log=LEGACY_FAIL_LOG,
    legacy_blocked_ips=LEGACY_BLOCKED_IPS,
    legacy_rate_limit=LEGACY_RATE_LIMIT,
    legacy_audit_log=LEGACY_AUDIT_LOG,
    chain_seed=CHAIN_SEED,
    chain_hash=_chain_hash,
    load_json=load_json,
    normalize_text=normalize_text,
    hash_password=hash_password,
    audit=audit,
    refresh_system_settings=refresh_system_settings,
    init_system_settings_table=init_system_settings_table,
    seed_missing_settings=_seed_missing_settings_to_db,
    import_legacy_settings_files=_import_legacy_settings_files,
    default_settings=DEFAULT_SETTINGS,
)
configure_chat_support_service(
    chat_dir=CHAT_DIR,
    official_chat_room_name=OFFICIAL_CHAT_ROOM_NAME,
    encrypt_field=encrypt_field,
)

# ── Flask app ──────────────────────────────────────────────────────────────────
app = Flask(__name__, static_folder=PUBLIC_DIR, static_url_path="")
app.config["SECRET_KEY"] = SECRET_KEY
app.config["MAX_CONTENT_LENGTH"] = 64 * 1024
app.config["SESSION_COOKIE_SECURE"] = SESSION_COOKIE_SECURE
app.config["SESSION_COOKIE_HTTPONLY"] = SESSION_COOKIE_HTTPONLY
app.config["SESSION_COOKIE_SAMESITE"] = SESSION_COOKIE_SAMESITE
app.config["PREFERRED_URL_SCHEME"] = "https" if FORCE_HTTPS else "http"

# ── Security Headers (via Flask-Talisman) ─────────────────────────────────────
# CSP: strict mode (no inline scripts/styles)
talisman = Talisman(app,
    content_security_policy={
        "default-src": "'self'",
        "script-src":  "'self'",
        "style-src":   "'self'",
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
    force_https=FORCE_HTTPS,        # SSL termination at proxy level
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

    settings = get_system_settings()
    if not settings.get("maintenance_mode", False):
        return None
    if not request.path.startswith("/api"):
        return None
    if request.path in ("/api/csrf-token", "/api/logout", "/api/me"):
        return None
    if request.path == "/api/login":
        data = request.get_json(silent=True) if request.is_json else {}
        username = normalize_text(data.get("username")) if isinstance(data, dict) else ""
        if username == "root":
            return None
        return json_resp({"ok":False,"msg":"系統進入緊急維護模式，僅允許最高管理者登入"}, 503)

    actor = get_current_user_ctx()
    if actor and actor["username"] == "root":
        return None
    return json_resp({"ok":False,"msg":"系統進入緊急維護模式，請等待最高管理者處理"}, 503)

# ── Routes ─────────────────────────────────────────────────────────────────────
register_public_routes(app, {
    "CSRF_TOKEN_TTL": CSRF_TOKEN_TTL,
    "PUBLIC_DIR": PUBLIC_DIR,
    "ROLE_LABEL": ROLE_LABEL,
    "SERVER_STARTED_AT": SERVER_STARTED_AT,
    "SERVER_VERSION": SERVER_VERSION,
    "SESSION_COOKIE_SAMESITE": SESSION_COOKIE_SAMESITE,
    "SESSION_COOKIE_SECURE": SESSION_COOKIE_SECURE,
    "SESSION_TTL": SESSION_TTL,
    "audit": audit,
    "db_delete_session": db_delete_session,
    "db_get_user_from_token": db_get_user_from_token,
    "db_save_session": db_save_session,
    "decrypt_field": decrypt_field,
    "encrypt_field": encrypt_field,
    "ensure_user_official_room_membership": ensure_user_official_room_membership,
    "get_client_ip": get_client_ip,
    "get_current_user_ctx": get_current_user_ctx,
    "get_db": get_db,
    "get_system_settings": get_system_settings,
    "get_ua": get_ua,
    "hash_password": hash_password,
    "is_ip_blocked": is_ip_blocked,
    "is_rate_limited": is_rate_limited,
    "json_resp": json_resp,
    "make_csrf_token": make_csrf_token,
    "make_token": make_token,
    "normalize_text": normalize_text,
    "parse_birthdate": parse_birthdate,
    "record_login_failure": record_login_failure,
    "require_csrf": require_csrf,
    "role_rank": role_rank,
    "store_csrf_token": store_csrf_token,
    "timing_delay": timing_delay,
    "validate_id_number": validate_id_number,
    "validate_password": validate_password,
    "validate_phone": validate_phone,
    "verify_csrf_double_submit": verify_csrf_double_submit,
    "verify_password": verify_password,
})

register_chat_routes(app, {
    "CHAT_MESSAGE_MAX_LEN": CHAT_MESSAGE_MAX_LEN,
    "OFFICIAL_CHAT_ROOM_NAME": OFFICIAL_CHAT_ROOM_NAME,
    "add_violation": add_violation,
    "append_chat_record": append_chat_record,
    "audit": audit,
    "db_get_user_from_token": db_get_user_from_token,
    "db_get_user_role": db_get_user_role,
    "delete_csrf_token": delete_csrf_token,
    "detect_chat_violation": detect_chat_violation,
    "ensure_user_official_room_membership": ensure_user_official_room_membership,
    "get_client_ip": get_client_ip,
    "get_current_user_ctx": get_current_user_ctx,
    "get_db": get_db,
    "get_request_csrf_token": get_request_csrf_token,
    "get_ua": get_ua,
    "json_resp": json_resp,
    "normalize_text": normalize_text,
    "parse_positive_int": parse_positive_int,
    "require_csrf": require_csrf,
    "require_csrf_safe": require_csrf_safe,
    "role_rank": role_rank,
    "verify_csrf_token": verify_csrf_token,
})

register_user_routes(app, {
    "MAX_MANAGERS": MAX_MANAGERS,
    "ROLE_LABEL": ROLE_LABEL,
    "ROLE_RANK": ROLE_RANK,
    "add_violation": add_violation,
    "audit": audit,
    "count_role": count_role,
    "db_get_user_from_token": db_get_user_from_token,
    "db_get_user_role": db_get_user_role,
    "decrypt_field": decrypt_field,
    "encrypt_field": encrypt_field,
    "ensure_user_official_room_membership": ensure_user_official_room_membership,
    "get_client_ip": get_client_ip,
    "get_current_user_ctx": get_current_user_ctx,
    "get_db": get_db,
    "get_ua": get_ua,
    "hash_password": hash_password,
    "json_resp": json_resp,
    "normalize_text": normalize_text,
    "parse_birthdate": parse_birthdate,
    "parse_positive_int": parse_positive_int,
    "require_csrf": require_csrf,
    "require_csrf_safe": require_csrf_safe,
    "role_rank": role_rank,
    "user_public_payload": user_public_payload,
    "validate_id_number": validate_id_number,
    "validate_password": validate_password,
    "validate_phone": validate_phone,
})

register_operation_routes(app, {
    "ANCHOR_DIR": ANCHOR_DIR,
    "AUDIT_LOG_PATH": AUDIT_LOG_PATH,
    "BASE_DIR": BASE_DIR,
    "CHAT_DIR": CHAT_DIR,
    "DB_PATH": DB_PATH,
    "LOG_DIR": LOG_DIR,
    "SERVER_LOG_PATH": SERVER_LOG_PATH,
    "SESSION_COOKIE_SAMESITE": SESSION_COOKIE_SAMESITE,
    "SESSION_COOKIE_SECURE": SESSION_COOKIE_SECURE,
    "VIOLATION_APPEAL_WINDOW_HOURS": VIOLATION_APPEAL_WINDOW_HOURS,
    "activate_emergency_lockdown": activate_emergency_lockdown,
    "add_violation": add_violation,
    "audit": audit,
    "get_client_ip": get_client_ip,
    "get_current_user_ctx": get_current_user_ctx,
    "get_db": get_db,
    "get_latest_violation": get_latest_violation,
    "get_system_settings": get_system_settings,
    "get_ua": get_ua,
    "is_audit_chain_enabled": is_audit_chain_enabled,
    "json_resp": json_resp,
    "normalize_text": normalize_text,
    "parse_iso_to_datetime": parse_iso_to_datetime,
    "parse_positive_int": parse_positive_int,
    "require_csrf": require_csrf,
    "require_csrf_safe": require_csrf_safe,
    "role_rank": role_rank,
    "save_settings": save_settings,
    "verify_audit_integrity": verify_audit_integrity,
    "verify_violation_integrity": verify_violation_integrity,
})

# ── Start ──────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    init_db(
        ensure_secure_audit_columns=ensure_secure_audit_columns,
        ensure_user_columns=ensure_user_columns,
        ensure_appeal_columns=ensure_appeal_columns,
        ensure_official_chat_room=ensure_official_chat_room,
        hash_password=hash_password,
    )
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    CERT_FILE = os.path.join(BASE_DIR, "cert.pem")
    KEY_FILE  = os.path.join(BASE_DIR, "key.pem")
    has_ssl = os.path.exists(CERT_FILE) and os.path.exists(KEY_FILE)

    audit("SERVER_START", "0.0.0.0", detail="hackme_web server started — hardened edition")
    scheme = "https" if has_ssl else "http"
    print(f"\n🌐  hackme_web server running at {scheme}://localhost:5000")
    print(f"    Default credentials: root / root")
    print(f"    SSL: {'enabled' if has_ssl else 'disabled (add cert.pem + key.pem to enable)'}")
    print(f"    Audit log: database (secure_audit table + hash-chain)")
    print(f"    Security: Argon2id + timing-noise + account-enum-protection + CSRF + strict-headers\n")

    port = int(os.environ.get("HTML_LEARNING_PORT", "5000"))
    host = os.environ.get("HTML_LEARNING_HOST", "0.0.0.0").strip() or "0.0.0.0"
    kwargs = {"host": host, "port": port, "debug": False}
    if has_ssl:
        kwargs["ssl_context"] = (CERT_FILE, KEY_FILE)
    app.run(**kwargs)
