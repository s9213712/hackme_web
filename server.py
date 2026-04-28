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
    repair_audit_chain,
    verify_audit_integrity,
)
from services.access_controls import (
    client_ip_allowed,
    is_browser_user_agent,
    maintenance_bypass_required_payload,
    verify_maintenance_bypass_token,
)
from services.auth import (
    CSRF_TOKEN_TTL,
    SESSION_TTL,
    SESSION_IDLE_TIMEOUT,
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
    revoke_user_sessions,
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
    get_feature_settings,
    get_system_settings,
    init_system_settings_table,
    is_feature_enabled,
    load_settings,
    refresh_system_settings,
    save_settings,
    save_feature_settings,
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
    repair_violation_chains,
    secure_add_violation,
    verify_violation_integrity,
)
from services.security_events import (
    block_ip,
    check_user_rate_limit,
    clear_failed_logins,
    configure_security_events_service,
    is_ip_blocked,
    is_rate_limited,
    record_403_access,
    record_login_failure,
    record_security_event,
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
from services.identity import (
    ACCOUNT_STATUSES,
    MEMBER_LEVELS,
    ROLE_LABEL,
    ROLE_RANK,
    ensure_user_identity_columns,
    role_rank,
)
from services.governance_records import ensure_governance_records_schema
from services.integrity_guard import IntegrityGuard, ensure_integrity_schema
from services.member_levels import ensure_member_level_rules_schema, get_member_level_rule
from services.moderation_proposals import ensure_moderation_proposals_schema
from services.password_strength import enforce_password_strength, score_password_strength
from services.release_info import APP_NAME, APP_RELEASE_ID
from services.server_bind import effective_server_bind
from services.snapshots import SnapshotService, ServerModeService, ensure_snapshot_schema
from services.storage_maintenance import run_storage_maintenance_if_due
from services.storage_paths import validate_storage_root
from services.upload_security import ensure_upload_security_schema

# ── Paths ───────────────────────────────────────────────────────────────────
BASE_DIR   = os.path.dirname(os.path.abspath(__file__))
STARTUP_BIND = effective_server_bind()
STARTUP_HOST = STARTUP_BIND["host"]
STARTUP_PORT = STARTUP_BIND["port"]
SERVER_BIND_STATE = {"host": STARTUP_HOST, "port": STARTUP_PORT}
SERVER_STARTED_AT = datetime.now().isoformat()
SERVER_RELEASE_ID = APP_RELEASE_ID
SERVER_VERSION = APP_RELEASE_ID

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
STORAGE_DIR = _env_path("HTML_LEARNING_STORAGE_DIR", os.path.join(BASE_DIR, "storage"))
REPORTS_DIR = _env_path("HTML_LEARNING_REPORTS_DIR", os.path.join(BASE_DIR, "reports"))
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
os.makedirs(REPORTS_DIR, exist_ok=True)


def _load_db_setting_value(db_path, key):
    if not os.path.exists(db_path):
        return ""
    try:
        conn = sqlite3.connect(db_path)
        try:
            row = conn.execute("SELECT value FROM system_settings WHERE key=?", (key,)).fetchone()
            return str(row[0] or "").strip() if row else ""
        finally:
            conn.close()
    except Exception:
        return ""


_configured_storage_root = _load_db_setting_value(DB_PATH, "cloud_drive_storage_root")
if _configured_storage_root:
    STORAGE_DIR = _configured_storage_root
STORAGE_DIR = str(validate_storage_root(STORAGE_DIR, base_dir=BASE_DIR, create=True))


def _load_or_create_text_secret(env_name, path, *, generator):
    env_value = os.environ.get(env_name, "").strip()
    if env_value:
        return env_value
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                value = f.read().strip()
            if value:
                return value
        except Exception:
            pass
    value = generator()
    with open(path, "w", encoding="utf-8") as f:
        f.write(value)
    os.chmod(path, 0o600)
    return value


def _load_or_create_binary_secret(env_name, path, *, generator):
    env_value = os.environ.get(env_name)
    if env_value:
        return env_value.encode("utf-8")
    if os.path.exists(path):
        try:
            with open(path, "rb") as f:
                value = f.read()
            if value:
                return value
        except Exception:
            pass
    value = generator()
    with open(path, "wb") as f:
        f.write(value)
    os.chmod(path, 0o600)
    return value


# ── Hash-chain seed (server-side only, not exposed to client) ─────────────────
def _get_chain_seed():
    seed_file = os.path.join(BASE_DIR, ".chain_seed")
    if os.path.exists(seed_file):
        try:
            with open(seed_file) as f:
                return f.read().strip()
        except Exception:
            pass
    seed = secrets.token_hex(24)
    with open(seed_file, "w") as f:
        f.write(seed)
    os.chmod(seed_file, 0o600)
    return seed

CHAIN_SEED = _get_chain_seed()

# ── Secrets ─────────────────────────────────────────────────────────────────
SECRET_KEY = _load_or_create_text_secret(
    "SESSION_SECRET",
    os.path.join(BASE_DIR, ".fkey"),
    generator=lambda: secrets.token_hex(32),
)

_INTEGRITY_KEY = _load_or_create_binary_secret(
    "INTEGRITY_SECRET_KEY",
    os.path.join(BASE_DIR, ".integrity_key"),
    generator=lambda: secrets.token_bytes(32),
)


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


def _env_int(name, default, minimum=None):
    raw = os.environ.get(name)
    try:
        value = int(str(raw).strip()) if raw is not None else int(default)
    except Exception:
        value = int(default)
    if minimum is not None and value < minimum:
        value = minimum
    return value


def _env_session_samesite():
    s = os.environ.get("SESSION_COOKIE_SAMESITE", "Strict").strip().lower()
    return "Strict" if s in {"", "strict"} else ("Lax" if s == "lax" else "None")

TRUSTED_PROXY_IPS = parse_ip_set(os.environ.get("TRUSTED_PROXY_IPS", ""))
USE_XFF = os.environ.get("USE_XFF", "false").strip().lower() in {"1", "true", "on", "yes"}
UNTRUSTED_XFF_MSG = "X-Forwarded-For from untrusted proxy rejected"
IP_BLOCKING_ENABLED = _env_bool("IP_BLOCKING_ENABLED", default=True)
FORCE_HTTPS = _env_bool("FORCE_HTTPS", default=False)
SESSION_COOKIE_SECURE = _env_bool("SESSION_COOKIE_SECURE", default=False)
SESSION_COOKIE_HTTPONLY = _env_bool("SESSION_COOKIE_HTTPONLY", default=True)
SESSION_COOKIE_SAMESITE = _env_session_samesite()

# ── CSRF double-submit secret ─────────────────────────────────────────────────
CSRF_SECRET_KEY = _load_or_create_text_secret(
    "CSRF_SECRET_KEY",
    os.path.join(BASE_DIR, ".csrfkey"),
    generator=lambda: secrets.token_hex(32),
)


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


def get_request_maintenance_bypass_token():
    return (
        request.headers.get("X-Maintenance-Bypass-Token", "")
        or request.args.get("maintenance_bypass_token", "")
        or ""
    )


def has_valid_maintenance_bypass(settings=None):
    settings = settings or get_system_settings()
    return verify_maintenance_bypass_token(
        get_request_maintenance_bypass_token(),
        settings.get("maintenance_bypass_token_hash", ""),
        settings.get("maintenance_bypass_token_expires_at", ""),
    )


def root_ip_is_allowed(settings=None):
    settings = settings or get_system_settings()
    if not settings.get("root_ip_whitelist_enabled", False):
        return True
    return client_ip_allowed(get_client_ip(), settings.get("root_ip_whitelist", ""))


FEATURE_ROUTE_GATES = (
    ("feature_chat_enabled", ("/api/chat/", "/api/chat/rooms", "/api/chat/messages")),
    ("feature_community_enabled", ("/api/community/", "/api/community")),
    ("feature_appeals_enabled", ("/api/appeals", "/api/admin/appeals")),
    ("feature_reports_enabled", ("/api/reports", "/api/admin/reports", "/api/admin/message-reports", "/api/admin/community-post-reports")),
    ("feature_reports_notifications_enabled", ("/api/notifications",)),
    ("feature_dm_enabled", ("/api/dm",)),
    ("feature_audit_log_enabled", ("/api/admin/audit", "/api/audit")),
    ("feature_violation_center_enabled", ("/api/admin/violations", "/api/admin/users/")),
    ("feature_accounts_enabled", ("/api/admin/users",)),
    ("feature_system_health_enabled", ("/api/admin/health",)),
    ("feature_privacy_uploads_enabled", ("/api/files/", "/api/files", "/api/cloud-drive/", "/api/cloud-drive", "/api/root/announcement-attachment-requests", "/api/crypto/")),
    ("feature_storage_albums_enabled", ("/api/storage/", "/api/storage", "/api/admin/storage/", "/api/admin/storage")),
)


def feature_gate_for_path(path):
    if path.startswith("/api/admin/users/") and (
        path.endswith("/violation") or path.endswith("/reset-violations")
    ):
        return "feature_violation_center_enabled"
    if path.startswith("/api/admin/users"):
        return "feature_accounts_enabled"
    for key, prefixes in FEATURE_ROUTE_GATES:
        if any(path == prefix or path.startswith(prefix) for prefix in prefixes):
            return key
    return None

# ── Domain constants / validation helpers ─────────────────────────────────────
MAX_MANAGERS = 5
MAX_EXTRA_SUPER_ADMINS = _env_int("HTML_LEARNING_MAX_EXTRA_SUPER_ADMINS", 2, minimum=0)
PASSWORD_HISTORY_LIMIT = _env_int("HTML_LEARNING_PASSWORD_HISTORY_LIMIT", 5, minimum=1)
VIOLATION_APPEAL_WINDOW_HOURS = 24
CHAT_MESSAGE_MAX_LEN = 500
SESSION_IDLE_TIMEOUT_SECONDS = _env_int("HTML_LEARNING_SESSION_IDLE_SECONDS", SESSION_IDLE_TIMEOUT, minimum=30)
OFFICIAL_CHAT_ROOM_NAME = "官方聊天室"

PW_RE = re.compile(r"^(?=.*[a-z])(?=.*[A-Z])(?=.*\d)(?=.*[!@#$%^&*()_+\-=\[\]{};':\"\\|,.<>\/?]).{8,128}$")


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
            "SELECT id, username, email, nickname, real_name, birthdate, id_number, phone, status, role, "
            "member_level, base_level, effective_level, trust_score, points, reputation, violation_score, "
            "sanction_status, sanction_until, level_updated_at, level_updated_by, level_update_reason, "
        "password_strength_score, must_change_password, is_default_password, avatar_file_id, avatar_crop_json, blocked_until, violation_count, chat_violation_warned "
            "FROM users WHERE username=?",
            (username,)
        ).fetchone()
    finally:
        conn.close()


def user_public_payload(row, *, include_sensitive=False):
    if not row:
        return None
    data = dict(row)
    try:
        avatar_crop = json.loads(data.get("avatar_crop_json") or "{}") if data.get("avatar_crop_json") else {}
    except Exception:
        avatar_crop = {}
    payload = {
        "id": data.get("id"),
        "username": data.get("username"),
        "nickname": decrypt_field(data.get("nickname")),
        "email": data.get("email"),
        "status": data.get("status"),
        "role": data.get("role"),
        "member_level": data.get("member_level") or "normal",
        "base_level": data.get("base_level") or data.get("member_level") or "normal",
        "effective_level": data.get("effective_level") or data.get("member_level") or "normal",
        "trust_score": data.get("trust_score") or 0,
        "points": data.get("points") or 0,
        "reputation": data.get("reputation") or 0,
        "violation_score": data.get("violation_score") or data.get("violation_count") or 0,
        "sanction_status": data.get("sanction_status") or "none",
        "sanction_until": data.get("sanction_until"),
        "level_updated_at": data.get("level_updated_at"),
        "level_updated_by": data.get("level_updated_by"),
        "level_update_reason": data.get("level_update_reason"),
        "password_strength_score": data.get("password_strength_score") or 0,
        "must_change_password": bool(data.get("must_change_password") or 0),
        "is_default_password": bool(data.get("is_default_password") or 0),
        "avatar_file_id": data.get("avatar_file_id"),
        "avatar_crop": avatar_crop if isinstance(avatar_crop, dict) else {},
        "role_label": ROLE_LABEL.get(data.get("role"), data.get("role")),
        "blocked_until": data.get("blocked_until"),
        "violation_count": data.get("violation_count") or 0,
    }
    if include_sensitive:
        payload.update({
            "real_name": decrypt_field(data.get("real_name")),
            "birthdate": decrypt_field(data.get("birthdate")),
            "id_number": decrypt_field(data.get("id_number")),
            "phone": decrypt_field(data.get("phone")),
        })
    else:
        payload.update({
            "real_name": "",
            "birthdate": "",
            "id_number": "",
            "phone": "",
        })
    return payload


def ensure_user_columns(conn):
    ensure_user_identity_columns(conn)


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


def ensure_session_columns(conn):
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(sessions)").fetchall()}
    additions = [
        ("is_revoked", "INTEGER NOT NULL DEFAULT 0"),
        ("revoked_at", "TEXT"),
        ("last_seen", "TEXT"),
        ("device_info", "TEXT"),
        ("ip_country", "TEXT"),
    ]
    for name, ddl in additions:
        if name not in cols:
            conn.execute(f"ALTER TABLE sessions ADD COLUMN {name} {ddl}")
    conn.execute("UPDATE sessions SET is_revoked=0 WHERE is_revoked IS NULL")
    conn.execute("UPDATE sessions SET last_seen=created_at WHERE last_seen IS NULL")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_sessions_expires_at ON sessions(expires_at)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_sessions_last_seen ON sessions(last_seen)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_sessions_revoked ON sessions(is_revoked)")


def ensure_security_support_schema(conn):
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS ip_blocks (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            ip_address     TEXT NOT NULL UNIQUE,
            blocked_until  TEXT NOT NULL,
            reason         TEXT,
            created_at     TEXT NOT NULL DEFAULT (datetime('now'))
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS login_locations (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id       INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            ip_hash       TEXT NOT NULL,
            country       TEXT,
            city          TEXT,
            login_at      TEXT NOT NULL,
            is_suspicious INTEGER NOT NULL DEFAULT 0
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_ip_blocks_ip ON ip_blocks(ip_address)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_ip_blocks_until ON ip_blocks(blocked_until)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_login_locations_user ON login_locations(user_id, login_at)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_login_locations_ip ON login_locations(ip_hash)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_csrf_expires_at ON csrf_tokens(expires_at)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_sec_event_type_ip_time ON security_events(event_type, ip_address, created_at)")
    ensure_member_level_rules_schema(conn)
    ensure_moderation_proposals_schema(conn)
    ensure_governance_records_schema(conn)
    ensure_snapshot_schema(conn)
    ensure_upload_security_schema(conn)
    ensure_integrity_schema(conn)

    legacy_rows = conn.execute(
        "SELECT ip_address, detail, created_at FROM security_events "
        "WHERE event_type='ip_block' ORDER BY id DESC"
    ).fetchall()
    seen = set()
    for row in legacy_rows:
        ip = row["ip_address"]
        if not ip or ip in seen:
            continue
        seen.add(ip)
        detail = row["detail"] or ""
        match = re.search(r"blocked_until=([0-9T:\-\.]+)", detail)
        if not match:
            continue
        blocked_until = match.group(1)
        conn.execute(
            "INSERT OR IGNORE INTO ip_blocks (ip_address, blocked_until, reason, created_at) VALUES (?, ?, ?, ?)",
            (ip, blocked_until, detail, row["created_at"] or datetime.now().isoformat())
        )


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
    session_idle_timeout=SESSION_IDLE_TIMEOUT_SECONDS,
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
    verify_password=verify_password,
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
snapshot_service = SnapshotService(
    get_db=get_db,
    db_path=DB_PATH,
    base_dir=BASE_DIR,
    storage_root=STORAGE_DIR,
    audit=audit,
    file_roots=[
        CHAT_DIR,
        os.path.join(BASE_DIR, "uploads"),
        os.path.join(BASE_DIR, "avatars"),
        os.path.join(BASE_DIR, "attachments"),
        os.path.join(BASE_DIR, "media"),
    ],
    config_files=[
        os.path.join(BASE_DIR, "system_settings.json"),
        os.path.join(BASE_DIR, "settings.json"),
        os.path.join(BASE_DIR, ".env"),
    ],
)
ROOT_INTEGRITY_SIGNING_KEY = os.environ.get("ROOT_INTEGRITY_SIGNING_KEY", "").encode("utf-8") or _INTEGRITY_KEY
integrity_guard = IntegrityGuard(
    base_dir=BASE_DIR,
    manifest_path=os.path.join(BASE_DIR, "integrity_manifest.json"),
    signing_key=ROOT_INTEGRITY_SIGNING_KEY,
    get_db=get_db,
    audit=audit,
)
server_mode_service = ServerModeService(snapshot_service=snapshot_service, get_db=get_db, audit=audit, integrity_guard=integrity_guard)

# ── Flask app ──────────────────────────────────────────────────────────────────
app = Flask(__name__, static_folder=PUBLIC_DIR, static_url_path="")
app.config["SECRET_KEY"] = SECRET_KEY
app.config["MAX_CONTENT_LENGTH"] = 50 * 1024 * 1024  # 50MB, per-level quota enforced in upload_security.py
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
def enforce_root_ip_whitelist():
    if request.method == "OPTIONS" or not request.path.startswith("/api"):
        return None
    settings = get_system_settings()
    if not settings.get("root_ip_whitelist_enabled", False):
        return None
    if request.path == "/api/login":
        data = request.get_json(silent=True) if request.is_json else {}
        username = normalize_text(data.get("username")) if isinstance(data, dict) else ""
        if username == "root" and not root_ip_is_allowed(settings):
            record_security_event("permission_denied", get_client_ip(), target_user="root", detail="root_ip_whitelist_login")
            return json_resp({"ok":False,"msg":"root IP 不在允許清單內"}), 403
        return None
    actor = get_current_user_ctx()
    if actor and actor["username"] == "root" and not root_ip_is_allowed(settings):
        record_security_event("permission_denied", get_client_ip(), target_user="root", detail=f"root_ip_whitelist:path={request.path}")
        return json_resp({"ok":False,"msg":"root IP 不在允許清單內"}), 403
    return None


@app.before_request
def enforce_browser_only_mode():
    if request.method == "OPTIONS" or not request.path.startswith("/api"):
        return None
    settings = get_system_settings()
    if not settings.get("browser_only_mode_enabled", False):
        return None
    if has_valid_maintenance_bypass(settings):
        return None
    if request.path in ("/api/version", "/api/site-config", "/api/captcha/challenge"):
        return None
    if is_browser_user_agent(request.headers.get("User-Agent", "")):
        return None
    actor = get_current_user_ctx()
    record_security_event(
        "permission_denied",
        get_client_ip(),
        target_user=(actor["username"] if actor else "-"),
        detail=f"browser_only_mode:path={request.path}",
    )
    return json_resp(maintenance_bypass_required_payload(
        "browser-only mode 已啟用，請使用瀏覽器存取；維護腳本可由 root 提供維護旁路 token。"
    )), 403


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
    if has_valid_maintenance_bypass(settings):
        return None
    if not request.path.startswith("/api"):
        return None
    if request.path in ("/api/csrf-token", "/api/logout", "/api/me", "/api/captcha/challenge"):
        return None
    if request.path == "/api/login":
        data = request.get_json(silent=True) if request.is_json else {}
        username = normalize_text(data.get("username")) if isinstance(data, dict) else ""
        if username == "root":
            return None
        return json_resp(maintenance_bypass_required_payload(
            "系統進入緊急維護模式，僅允許最高管理者登入；維護腳本可由 root 提供維護旁路 token。"
        )), 503

    actor = get_current_user_ctx()
    if actor and actor["username"] == "root":
        return None
    if actor:
        try:
            revoke_user_sessions(actor["id"])
            audit("MAINTENANCE_FORCED_LOGOUT", get_client_ip(), user=actor["username"], success=True, detail=f"path={request.path}")
        except Exception:
            pass
        resp = json_resp(maintenance_bypass_required_payload(
            "系統進入緊急維護模式，非 root 帳號已強制登出。"
        ), 503)
        resp.delete_cookie("session_token", path="/", samesite=SESSION_COOKIE_SAMESITE, secure=SESSION_COOKIE_SECURE)
        resp.delete_cookie("csrf_token", path="/", samesite=SESSION_COOKIE_SAMESITE, secure=SESSION_COOKIE_SECURE)
        return resp
    return json_resp(maintenance_bypass_required_payload(
        "系統進入緊急維護模式，請等待最高管理者處理，或由 root 提供維護旁路 token。"
    )), 503


@app.before_request
def enforce_feature_flags():
    if request.method == "OPTIONS" or not request.path.startswith("/api"):
        return None
    # The settings endpoints must stay reachable, otherwise root can lock the
    # site into a disabled state with no way back through the UI/API.
    if request.path in ("/api/admin/settings", "/api/admin/features", "/api/site-config", "/api/csrf-token", "/api/captcha/challenge", "/api/me", "/api/login", "/api/logout"):
        return None
    feature_key = feature_gate_for_path(request.path)
    if not feature_key or is_feature_enabled(feature_key):
        return None
    actor = get_current_user_ctx()
    record_security_event(
        "feature_disabled",
        get_client_ip(),
        target_user=(actor["username"] if actor else "-"),
        detail=f"path={request.path},feature={feature_key}",
    )
    return json_resp({
        "ok": False,
        "msg": "此功能目前已由 root 關閉",
        "feature": feature_key,
    }, 503)


@app.before_request
def enforce_required_password_change():
    if request.method == "OPTIONS" or not request.path.startswith("/api"):
        return None
    allowed = {"/api/csrf-token", "/api/logout", "/api/me", "/api/version", "/api/site-config", "/api/password-strength", "/api/captcha/challenge"}
    if request.path in allowed:
        return None
    actor = get_current_user_ctx()
    if not actor or not dict(actor).get("must_change_password"):
        return None
    match = re.fullmatch(r"/api/admin/users/(\d+)", request.path or "")
    if request.method in {"GET", "PUT"} and match and int(match.group(1)) == int(actor["id"]):
        return None
    return json_resp({
        "ok": False,
        "msg": "此預設帳號初次登入必須先變更密碼",
        "must_change_password": True,
    }), 403

# ── Routes ─────────────────────────────────────────────────────────────────────
register_public_routes(app, {
    "CSRF_TOKEN_TTL": CSRF_TOKEN_TTL,
    "PUBLIC_DIR": PUBLIC_DIR,
    "ROLE_LABEL": ROLE_LABEL,
    "SERVER_APP_NAME": APP_NAME,
    "SERVER_RELEASE_ID": SERVER_RELEASE_ID,
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
    "get_feature_settings": get_feature_settings,
    "get_member_level_rule": get_member_level_rule,
    "get_system_settings": get_system_settings,
    "get_ua": get_ua,
    "hash_password": hash_password,
    "hash_token": hash_token,
    "is_feature_enabled": is_feature_enabled,
    "is_ip_blocked": is_ip_blocked,
    "is_rate_limited": is_rate_limited,
    "json_resp": json_resp,
    "make_csrf_token": make_csrf_token,
    "make_token": make_token,
    "normalize_text": normalize_text,
    "parse_birthdate": parse_birthdate,
    "record_login_failure": record_login_failure,
    "record_security_event": record_security_event,
    "require_csrf": require_csrf,
    "score_password_strength": score_password_strength,
    "store_csrf_token": store_csrf_token,
    "timing_delay": timing_delay,
    "validate_id_number": validate_id_number,
    "validate_password": validate_password,
    "enforce_password_strength": enforce_password_strength,
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
    "check_user_rate_limit": check_user_rate_limit,
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
    "get_member_level_rule": get_member_level_rule,
    "is_feature_enabled": is_feature_enabled,
    "json_resp": json_resp,
    "normalize_text": normalize_text,
    "parse_positive_int": parse_positive_int,
    "require_csrf": require_csrf,
    "require_csrf_safe": require_csrf_safe,
    "role_rank": role_rank,
    "verify_csrf_token": verify_csrf_token,
})

register_user_routes(app, {
    "ACCOUNT_STATUSES": ACCOUNT_STATUSES,
    "MAX_MANAGERS": MAX_MANAGERS,
    "MAX_EXTRA_SUPER_ADMINS": MAX_EXTRA_SUPER_ADMINS,
    "MEMBER_LEVELS": MEMBER_LEVELS,
    "PASSWORD_HISTORY_LIMIT": PASSWORD_HISTORY_LIMIT,
    "ROLE_LABEL": ROLE_LABEL,
    "ROLE_RANK": ROLE_RANK,
    "add_violation": add_violation,
    "audit": audit,
    "check_user_rate_limit": check_user_rate_limit,
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
    "hash_token": hash_token,
    "is_feature_enabled": is_feature_enabled,
    "json_resp": json_resp,
    "normalize_text": normalize_text,
    "parse_birthdate": parse_birthdate,
    "parse_positive_int": parse_positive_int,
    "revoke_user_sessions": revoke_user_sessions,
    "require_csrf": require_csrf,
    "require_csrf_safe": require_csrf_safe,
    "SESSION_COOKIE_SAMESITE": SESSION_COOKIE_SAMESITE,
    "SESSION_COOKIE_SECURE": SESSION_COOKIE_SECURE,
    "enforce_password_strength": enforce_password_strength,
    "score_password_strength": score_password_strength,
    "role_rank": role_rank,
    "get_member_level_rule": get_member_level_rule,
    "STORAGE_DIR": STORAGE_DIR,
    "user_public_payload": user_public_payload,
    "validate_id_number": validate_id_number,
    "validate_password": validate_password,
    "validate_phone": validate_phone,
    "verify_password": verify_password,
})

register_operation_routes(app, {
    "ANCHOR_DIR": ANCHOR_DIR,
    "AUDIT_LOG_PATH": AUDIT_LOG_PATH,
    "BASE_DIR": BASE_DIR,
    "CHAT_DIR": CHAT_DIR,
    "CURRENT_SERVER_BIND_STATE": SERVER_BIND_STATE,
    "DB_PATH": DB_PATH,
    "LOG_DIR": LOG_DIR,
    "REPORTS_DIR": REPORTS_DIR,
    "SERVER_LOG_PATH": SERVER_LOG_PATH,
    "STORAGE_DIR": STORAGE_DIR,
    "SESSION_COOKIE_SAMESITE": SESSION_COOKIE_SAMESITE,
    "SESSION_COOKIE_SECURE": SESSION_COOKIE_SECURE,
    "VIOLATION_APPEAL_WINDOW_HOURS": VIOLATION_APPEAL_WINDOW_HOURS,
    "activate_emergency_lockdown": activate_emergency_lockdown,
    "add_violation": add_violation,
    "audit": audit,
    "check_user_rate_limit": check_user_rate_limit,
    "get_client_ip": get_client_ip,
    "get_current_user_ctx": get_current_user_ctx,
    "get_db": get_db,
    "get_latest_violation": get_latest_violation,
    "get_feature_settings": get_feature_settings,
    "get_member_level_rule": get_member_level_rule,
    "get_system_settings": get_system_settings,
    "get_ua": get_ua,
    "is_audit_chain_enabled": is_audit_chain_enabled,
    "is_feature_enabled": is_feature_enabled,
    "json_resp": json_resp,
    "normalize_text": normalize_text,
    "parse_iso_to_datetime": parse_iso_to_datetime,
    "parse_positive_int": parse_positive_int,
    "repair_audit_chain": repair_audit_chain,
    "repair_violation_chains": repair_violation_chains,
    "require_csrf": require_csrf,
    "require_csrf_safe": require_csrf_safe,
    "revoke_user_sessions": revoke_user_sessions,
    "role_rank": role_rank,
    "save_feature_settings": save_feature_settings,
    "save_settings": save_settings,
    "secure_add_violation": secure_add_violation,
    "server_mode_service": server_mode_service,
    "snapshot_service": snapshot_service,
    "integrity_guard": integrity_guard,
    "verify_audit_integrity": verify_audit_integrity,
    "verify_violation_integrity": verify_violation_integrity,
})


def start_daily_snapshot_worker():
    try:
        interval = int(os.environ.get("HTML_LEARNING_SNAPSHOT_CHECK_INTERVAL_SECONDS", "3600"))
    except ValueError:
        interval = 3600
    interval = max(60, interval)

    def loop():
        while True:
            try:
                result = snapshot_service.create_daily_snapshot_if_due(
                    actor={"id": 0, "username": "system"},
                    settings=get_system_settings(),
                    save_settings=save_settings,
                )
                if result.get("created"):
                    audit("DAILY_SNAPSHOT_CREATED", "0.0.0.0", user="system", success=True, detail=f"snapshot_id={result.get('snapshot_id')}")
            except Exception as exc:
                audit("DAILY_SNAPSHOT_FAILED", "0.0.0.0", user="system", success=False, detail=str(exc))
            time.sleep(interval)

    worker = threading.Thread(target=loop, name="daily-snapshot-worker", daemon=True)
    worker.start()
    return worker


def start_storage_maintenance_worker():
    try:
        interval = int(os.environ.get("HTML_LEARNING_STORAGE_MAINTENANCE_CHECK_INTERVAL_SECONDS", "3600"))
    except ValueError:
        interval = 3600
    interval = max(60, interval)

    def loop():
        while True:
            conn = None
            try:
                conn = get_db()
                result = run_storage_maintenance_if_due(
                    conn,
                    settings=get_system_settings(),
                    save_settings=save_settings,
                    actor_user_id=0,
                )
                if result.get("ran"):
                    conn.commit()
                    audit("STORAGE_MAINTENANCE_AUTO_RUN", "0.0.0.0", user="system", success=True, detail=str(result.get("result") or {}))
                else:
                    conn.rollback()
            except Exception as exc:
                if conn:
                    conn.rollback()
                audit("STORAGE_MAINTENANCE_FAILED", "0.0.0.0", user="system", success=False, detail=str(exc))
            finally:
                if conn:
                    conn.close()
            time.sleep(interval)

    worker = threading.Thread(target=loop, name="storage-maintenance-worker", daemon=True)
    worker.start()
    return worker


# ── Start ──────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    init_db(
        ensure_secure_audit_columns=ensure_secure_audit_columns,
        ensure_user_columns=ensure_user_columns,
        ensure_appeal_columns=ensure_appeal_columns,
        ensure_security_support_schema=ensure_security_support_schema,
        ensure_session_columns=ensure_session_columns,
        ensure_official_chat_room=ensure_official_chat_room,
        hash_password=hash_password,
    )
    if get_system_settings().get("integrity_guard_enabled", True):
        integrity_status = integrity_guard.scan(actor="system-startup", create_initial_manifest=True)
        if get_system_settings().get("integrity_guard_strict_mode", False):
            high_risk = (integrity_status.get("summary") or {}).get("high_risk_pending", 0)
            if high_risk:
                raise SystemExit("Integrity Guard strict mode blocked startup due to high risk findings")
    start_daily_snapshot_worker()
    start_storage_maintenance_worker()
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    CERT_FILE = os.path.join(BASE_DIR, "cert.pem")
    KEY_FILE  = os.path.join(BASE_DIR, "key.pem")
    has_ssl = os.path.exists(CERT_FILE) and os.path.exists(KEY_FILE)

    audit("SERVER_START", "0.0.0.0", detail="hackme_web server started — hardened edition")
    scheme = "https" if has_ssl else "http"
    bind = effective_server_bind(get_system_settings())
    host = bind["host"]
    port = bind["port"]
    SERVER_BIND_STATE.update({"host": host, "port": port})
    print(f"\n🌐  hackme_web server running at {scheme}://{host}:{port}")
    print(f"    SSL: {'enabled' if has_ssl else 'disabled (add cert.pem + key.pem to enable)'}")
    print(f"    Audit log: database (secure_audit table + hash-chain)")
    print(f"    Security: Argon2id + timing-noise + account-enum-protection + CSRF + strict-headers\n")

    kwargs = {"host": host, "port": port, "debug": False}
    if has_ssl:
        kwargs["ssl_context"] = (CERT_FILE, KEY_FILE)
    app.run(**kwargs)
