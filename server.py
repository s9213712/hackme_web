#!/usr/bin/env python3
"""
hackme_web — Flask auth server
Hardened edition: timing-noise, account-enumeration protection,
CSRF tokens, strict CSP, full security headers, rate-limit amplification.
"""

import os, sqlite3, re, json, time, hashlib, secrets, hmac, threading, random, base64, fcntl, subprocess, signal, sys, platform, smtplib, ssl, urllib.parse
from ipaddress import ip_address
from datetime import datetime, timedelta
from email.message import EmailMessage
from functools import wraps
from flask import Flask, request, jsonify, send_from_directory, make_response
from werkzeug.exceptions import HTTPException, RequestEntityTooLarge
from cryptography import x509
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
import argon2
from flask_talisman import Talisman
from services.audit import (
    _chain_hash,
    audit,
    canonical_json,
    configure_audit_service,
    repair_audit_chain,
    reset_audit_chain_with_event,
    verify_audit_integrity,
)
from services.access_controls import (
    client_ip_allowed,
    is_browser_user_agent,
    maintenance_bypass_required_payload,
    verify_maintenance_bypass_token,
)
from services.account_recovery import ensure_account_recovery_schema
from services.auth import (
    CSRF_TOKEN_TTL,
    SESSION_TTL,
    SESSION_IDLE_TIMEOUT,
    configure_auth_service,
    db_delete_session,
    db_get_user_from_token,
    db_save_session,
    delete_csrf_token,
    delete_csrf_tokens_for_username,
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
    build_feature_disabled_payload,
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
from services.points_chain import DEFAULT_BLOCK_LEDGER_THRESHOLD, DEFAULT_BLOCK_MAX_INTERVAL_SECONDS, PointsLedgerService, ensure_points_economy_schema
from services.release_info import APP_NAME, APP_RELEASE_ID
from services.runtime_output import get_runtime_output, install_runtime_output_capture
from services.server.routes import register_server_routes
from services.server.runtime import (
    _build_fernet,
    _env_bool,
    _env_int,
    _env_path,
    _env_session_samesite,
    _load_db_setting_value,
    _load_or_create_binary_secret,
    _load_or_create_text_secret,
    ensure_local_tls_files,
    load_chain_seed,
    load_json,
    parse_ip_set,
    save_json,
)
from services.server.startup import (
    run_server_main as run_server_main_helper,
    start_daily_snapshot_worker as start_daily_snapshot_worker_helper,
    start_points_chain_block_worker as start_points_chain_block_worker_helper,
    start_storage_maintenance_worker as start_storage_maintenance_worker_helper,
    start_trading_bot_worker as start_trading_bot_worker_helper,
    start_trading_liquidation_worker as start_trading_liquidation_worker_helper,
)
from services.server.request_guards import (
    enforce_browser_only_mode as enforce_browser_only_mode_helper,
    enforce_feature_flags as enforce_feature_flags_helper,
    enforce_mode_restrictions as enforce_mode_restrictions_helper,
    enforce_required_password_change as enforce_required_password_change_helper,
    enforce_root_ip_whitelist as enforce_root_ip_whitelist_helper,
    feature_gate_for_path as feature_gate_for_path_helper,
    get_request_maintenance_bypass_token as get_request_maintenance_bypass_token_helper,
    has_valid_maintenance_bypass as has_valid_maintenance_bypass_helper,
    path_is_root_recovery_allowed_during_lockdown as path_is_root_recovery_allowed_during_lockdown_helper,
    protect_sensitive_static_page as protect_sensitive_static_page_helper,
    root_ip_is_allowed as root_ip_is_allowed_helper,
)
from services.server_bind import effective_server_bind, effective_server_ssl
from services.server_mode_context import attach_to_g as smv2_attach_ctx, current_ctx as smv2_current_ctx
from services.db_mode_triggers import register_app_mode_function as smv2_register_app_mode
from services.snapshots import SnapshotService, ServerModeService, ensure_snapshot_schema
from services.storage_maintenance import run_storage_maintenance_if_due
from services.storage_paths import validate_storage_root
from services.upload_security import ensure_upload_security_schema
from services.trading_engine import TradingEngineService, ensure_trading_schema
from services.trading_price_streams import TradingPriceStreamHub

# ── Paths ───────────────────────────────────────────────────────────────────
BASE_DIR   = os.path.dirname(os.path.abspath(__file__))
_git_repo_dir_env = os.environ.get("HTML_LEARNING_GIT_REPO_DIR", "").strip()
if _git_repo_dir_env:
    GIT_REPO_DIR = _git_repo_dir_env if os.path.isabs(_git_repo_dir_env) else os.path.abspath(_git_repo_dir_env)
else:
    GIT_REPO_DIR = BASE_DIR
STARTUP_BIND = effective_server_bind()
STARTUP_HOST = STARTUP_BIND["host"]
STARTUP_PORT = STARTUP_BIND["port"]
SERVER_BIND_STATE = {"host": STARTUP_HOST, "port": STARTUP_PORT}
SERVER_STARTED_AT = datetime.now().isoformat()
SERVER_RELEASE_ID = APP_RELEASE_ID
SERVER_VERSION = APP_RELEASE_ID

RUNTIME_DIR = _env_path("HACKME_RUNTIME_DIR", os.path.join(BASE_DIR, "runtime"))
RUNTIME_DIR = os.path.abspath(RUNTIME_DIR)
RUNTIME_SECRETS_DIR = _env_path("HTML_LEARNING_RUNTIME_SECRETS_DIR", RUNTIME_DIR)
RUNTIME_SECRETS_DIR = os.path.abspath(RUNTIME_SECRETS_DIR)


def _runtime_path(env_name, relative_path):
    return _env_path(env_name, os.path.join(RUNTIME_SECRETS_DIR, relative_path))


DB_DIR = _env_path("HTML_LEARNING_DB_DIR", os.path.join(RUNTIME_DIR, "database"))
DB_PATH = os.path.join(DB_DIR, "database.db")
LOG_DIR = _env_path("HTML_LEARNING_LOG_DIR", os.path.join(RUNTIME_DIR, "logs"))
CHAT_DIR = _env_path("HTML_LEARNING_CHAT_DIR", os.path.join(RUNTIME_DIR, "chats"))
ANCHOR_DIR = _env_path("HTML_LEARNING_ANCHOR_DIR", os.path.join(RUNTIME_DIR, "anchors"))
STORAGE_DIR = _env_path("HTML_LEARNING_STORAGE_DIR", os.path.join(RUNTIME_DIR, "storage"))
REPORTS_DIR = _env_path("HTML_LEARNING_REPORTS_DIR", os.path.join(RUNTIME_DIR, "reports"))
POINTS_CHAIN_BACKUP_DIR = _env_path("POINTS_CHAIN_BACKUP_DIR", os.path.join(DB_DIR, "points_chain_backups"))
PUBLIC_DIR = os.path.join(BASE_DIR, "public")
AUDIT_LOG_PATH = os.path.join(LOG_DIR, "audit.log")
SERVER_LOG_PATH = os.path.join(LOG_DIR, "server.log")
AUDIT_ANCHOR_PATH = os.path.join(ANCHOR_DIR, "audit_head.jsonl")
AUDIT_ANCHOR_LATEST_PATH = os.path.join(ANCHOR_DIR, "audit_head_latest.json")
AUDIT_ANCHOR_INTERVAL_SECONDS = 60
CHAIN_SEED_PATH = _runtime_path("HTML_LEARNING_CHAIN_SEED_PATH", ".chain_seed")
SESSION_SECRET_PATH = _runtime_path("HTML_LEARNING_SESSION_SECRET_FILE", ".fkey")
SERVER_FILE_KEY_PATH = _runtime_path("HTML_LEARNING_SERVER_FILE_KEY_FILE", ".filekey")
INTEGRITY_KEY_PATH = _runtime_path("HTML_LEARNING_INTEGRITY_KEY_PATH", ".integrity_key")
CSRF_SECRET_PATH = _runtime_path("HTML_LEARNING_CSRF_KEY_PATH", ".csrfkey")
SERVER_MODE_LOG_HMAC_KEY_PATH = _runtime_path("HTML_LEARNING_SERVER_MODE_LOG_HMAC_KEY_FILE", ".server_mode_log_hmac_key")
INTEGRITY_MANIFEST_PATH = _runtime_path("HTML_LEARNING_INTEGRITY_MANIFEST_PATH", "integrity_manifest.json")
CERT_FILE = _runtime_path("HTML_LEARNING_CERT_FILE", "cert.pem")
KEY_FILE = _runtime_path("HTML_LEARNING_KEY_FILE", "key.pem")

os.makedirs(RUNTIME_DIR, exist_ok=True)
os.makedirs(RUNTIME_SECRETS_DIR, exist_ok=True)
os.makedirs(DB_DIR, exist_ok=True)
os.makedirs(LOG_DIR, exist_ok=True)
os.makedirs(CHAT_DIR, exist_ok=True)
os.makedirs(ANCHOR_DIR, exist_ok=True)
os.makedirs(REPORTS_DIR, exist_ok=True)


_configured_storage_root = _load_db_setting_value(DB_PATH, "cloud_drive_storage_root")
if _configured_storage_root:
    STORAGE_DIR = _configured_storage_root
STORAGE_DIR = str(validate_storage_root(STORAGE_DIR, base_dir=BASE_DIR, create=True))

# ── Hash-chain seed (server-side only, not exposed to client) ─────────────────
CHAIN_SEED = load_chain_seed(CHAIN_SEED_PATH)

# ── Secrets ─────────────────────────────────────────────────────────────────
SECRET_KEY = _load_or_create_text_secret(
    "SESSION_SECRET",
    SESSION_SECRET_PATH,
    generator=lambda: secrets.token_hex(32),
)

SERVER_FILE_ENCRYPTION_KEY = _load_or_create_text_secret(
    "SERVER_FILE_ENCRYPTION_KEY",
    SERVER_FILE_KEY_PATH,
    generator=lambda: Fernet.generate_key().decode("utf-8"),
)

_INTEGRITY_KEY = _load_or_create_binary_secret(
    "INTEGRITY_SECRET_KEY",
    INTEGRITY_KEY_PATH,
    generator=lambda: secrets.token_bytes(32),
)


fernet = _build_fernet(SECRET_KEY)
server_file_fernet = _build_fernet(SERVER_FILE_ENCRYPTION_KEY)

LEGACY_FAIL_LOG = _runtime_path("HTML_LEARNING_FAIL_LOG_PATH", "fail_log.json")
LEGACY_BLOCKED_IPS = _runtime_path("HTML_LEARNING_BLOCKED_IPS_PATH", "blocked_ips.json")
LEGACY_RATE_LIMIT = _runtime_path("HTML_LEARNING_RATE_LIMIT_PATH", "rate_limit.json")
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
        # Backward compatibility with pre-encryption rows. If the value looks
        # like Fernet ciphertext but can no longer be decrypted (for example,
        # a runtime key was reset), do not leak the raw ciphertext into UI.
        if value.startswith("gAAAAA"):
            return ""
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
TRUSTED_PROXY_IPS = parse_ip_set(os.environ.get("TRUSTED_PROXY_IPS", ""))
USE_XFF = os.environ.get("USE_XFF", "false").strip().lower() in {"1", "true", "on", "yes"}
UNTRUSTED_XFF_MSG = "X-Forwarded-For from untrusted proxy rejected"
IP_BLOCKING_ENABLED = _env_bool("IP_BLOCKING_ENABLED", default=True)
FORCE_HTTPS = _env_bool("FORCE_HTTPS", default=True)
SESSION_COOKIE_SECURE = _env_bool("SESSION_COOKIE_SECURE", default=True)
SESSION_COOKIE_HTTPONLY = _env_bool("SESSION_COOKIE_HTTPONLY", default=True)
SESSION_COOKIE_SAMESITE = _env_session_samesite()

# ── CSRF double-submit secret ─────────────────────────────────────────────────
CSRF_SECRET_KEY = _load_or_create_text_secret(
    "CSRF_SECRET_KEY",
    CSRF_SECRET_PATH,
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

def reseal_audit_chain_if_required_on_startup():
    settings = get_system_settings()
    if not bool(settings.get("audit_chain_enabled", False)):
        return {"ok": True, "skipped": True, "reason": "audit_chain_disabled"}
    if not bool(settings.get("audit_chain_reseal_required", False)):
        return {"ok": True, "skipped": True, "reason": "not_required"}
    result = repair_audit_chain(reason="startup_after_audit_chain_reenabled")
    save_settings({"audit_chain_reseal_required": False})
    audit(
        "AUDIT_CHAIN_STARTUP_RESEALED",
        "0.0.0.0",
        user="system",
        success=True,
        detail=f"entries_resealed={result.get('entries_resealed')},head_id={result.get('head_id')}",
    )
    return {"ok": True, "skipped": False, "result": result}

def is_ip_blocking_enabled():
    settings = get_system_settings()
    if "ip_blocking_enabled" in settings:
        return bool(settings.get("ip_blocking_enabled", False))
    return bool(IP_BLOCKING_ENABLED)


def get_request_maintenance_bypass_token():
    return get_request_maintenance_bypass_token_helper(request)


def has_valid_maintenance_bypass(settings=None):
    settings = settings or get_system_settings()
    return has_valid_maintenance_bypass_helper(
        settings,
        request_obj=request,
        verify_maintenance_bypass_token=verify_maintenance_bypass_token,
    )


def get_runtime_server_mode():
    conn = None
    try:
        conn = get_db()
        row = conn.execute("SELECT current_mode FROM server_modes WHERE id=1").fetchone()
        mode = str(row["current_mode"] or "test").strip().lower() if row else "test"
        return "dev_ready" if mode == "preprod" else mode
    except Exception:
        return "test"
    finally:
        if conn:
            conn.close()


def tester_token_username_from_request(req):
    token = (  # allowlist: tester token header parsing, not a hardcoded secret
        req.headers.get("X-Tester-Token", "")
        or req.headers.get("X-Internal-Test-Token", "")
        or ""
    ).strip()
    auth_header = req.headers.get("Authorization", "")
    if not token and auth_header.lower().startswith("bearer "):
        token = auth_header[7:].strip()  # allowlist: parse bearer token from request header
    if not token:
        return None
    raw_uri = (
        req.environ.get("RAW_URI")
        or req.environ.get("REQUEST_URI")
        or req.full_path
        or req.path
        or ""
    )
    decoded_uri = urllib.parse.unquote(raw_uri)
    suspicious_path = any(marker in raw_uri.lower() for marker in ("%2f", "%5c", "%2e")) or "\\" in decoded_uri or ".." in decoded_uri
    if suspicious_path:
        record_security_event("permission_denied", get_client_ip(), target_user="-", detail=f"tester_token_suspicious_path:path={raw_uri}")
        return None
    conn = None
    try:
        conn = get_db()
        ensure_snapshot_schema(conn)
        mode = get_runtime_server_mode()
        if mode not in {"test", "internal_test"}:
            return None
        token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
        row = conn.execute(
            """
            SELECT t.*, u.username, u.status
            FROM tester_tokens t
            JOIN users u ON u.id=t.tester_user_id
            WHERE t.token_hash=?
              AND t.revoked_at IS NULL
              AND t.expires_at>?
              AND u.status='active'
            LIMIT 1
            """,
            (token_hash, datetime.now().isoformat()),
        ).fetchone()
        if not row:
            return None
        path = req.path or ""
        if path.startswith("/api/root/") or path in {"/api/root"}:
            record_security_event("permission_denied", get_client_ip(), target_user=row["username"], detail=f"tester_token_root_api:path={path}")
            return None
        forbidden_prefixes = (
            "/api/admin/server-mode",
            "/api/admin/snapshots",
            "/api/admin/integrity",
            "/api/admin/settings",
            "/api/admin/features",
        )
        if any(path == prefix or path.startswith(prefix) for prefix in forbidden_prefixes):
            record_security_event("permission_denied", get_client_ip(), target_user=row["username"], detail=f"tester_token_forbidden_admin_api:path={path}")
            return None
        try:
            allowed_routes = json.loads(row["allowed_routes_json"] or "[]")
        except Exception:
            allowed_routes = []
        if allowed_routes and not any(path == route or path.startswith(str(route).rstrip("/") + "/") for route in allowed_routes):
            record_security_event("permission_denied", get_client_ip(), target_user=row["username"], detail=f"tester_token_route_not_allowed:path={path}")
            return None
        window_start = (datetime.now() - timedelta(seconds=60)).isoformat()
        recent = conn.execute(
            "SELECT COUNT(*) AS c FROM tester_token_request_log WHERE token_id=? AND created_at>?",
            (row["id"], window_start),
        ).fetchone()
        max_rpm = max(1, int(row["max_requests_per_minute"] or 60))
        if int(recent["c"] or 0) >= max_rpm:
            record_security_event("rate_limited", get_client_ip(), target_user=row["username"], detail=f"tester_token_rate_limit:token_id={row['id']}")
            return None
        conn.execute(
            "INSERT INTO tester_token_request_log (token_id, route, ip_address, created_at) VALUES (?, ?, ?, ?)",
            (row["id"], path, get_client_ip(), datetime.now().isoformat()),
        )
        conn.commit()
        return row["username"]
    except Exception:
        try:
            if conn:
                conn.rollback()
        except Exception:
            pass
        return None
    finally:
        if conn:
            conn.close()


def path_is_root_recovery_allowed_during_lockdown(path):
    return path_is_root_recovery_allowed_during_lockdown_helper(path)


def root_ip_is_allowed(settings=None):
    settings = settings or get_system_settings()
    return root_ip_is_allowed_helper(settings, get_client_ip=get_client_ip, client_ip_allowed=client_ip_allowed)


def feature_gate_for_path(path):
    return feature_gate_for_path_helper(path)

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
    conn = sqlite3.connect(DB_PATH, timeout=15)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA busy_timeout = 15000")
    except Exception:
        pass
    # Phase 3: register app_mode() user function on every connection so
    # the BEFORE INSERT trigger on points_chain_blocks has something to
    # evaluate. Failure to register is silently safe — the trigger
    # would just fail with "no such function" on the next chain insert,
    # which is loud-fail behavior we want anyway.
    try:
        smv2_register_app_mode(conn, mode_reader=get_runtime_server_mode)
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
        row = conn.execute(
            "SELECT id, username, email, nickname, real_name, birthdate, id_number, phone, status, role, "
            "member_level, base_level, effective_level, trust_score, points, reputation, violation_score, "
            "sanction_status, sanction_until, level_updated_at, level_updated_by, level_update_reason, "
        "password_strength_score, must_change_password, is_default_password, avatar_file_id, avatar_crop_json, blocked_until, violation_count, chat_violation_warned "
            "FROM users WHERE username=?",
            (username,)
        ).fetchone()
        if not row:
            return None
        return row
    finally:
        conn.close()


def user_public_payload(row, *, include_sensitive=False):
    if not row:
        return None
    data = dict(row)
    is_special_account = data.get("username") == "root" or data.get("role") in {"super_admin", "manager"}
    is_deleted = str(data.get("status") or "").strip().lower() == "deleted"
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
        "member_level": None if (is_special_account or is_deleted) else (data.get("member_level") or "normal"),
        "base_level": None if (is_special_account or is_deleted) else (data.get("base_level") or data.get("member_level") or "normal"),
        "effective_level": None if (is_special_account or is_deleted) else (data.get("effective_level") or data.get("member_level") or "normal"),
        "member_level_label": "已刪除" if is_deleted else ("特殊階級" if is_special_account else (data.get("effective_level") or data.get("member_level") or "normal")),
        "special_account": is_special_account,
        "is_deleted": is_deleted,
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
        ("session_epoch", "INTEGER NOT NULL DEFAULT 0"),
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
    ensure_account_recovery_schema(conn)

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
    get_client_ip=get_client_ip,
    session_ttl=SESSION_TTL,
    csrf_token_ttl=CSRF_TOKEN_TTL,
    session_idle_timeout=SESSION_IDLE_TIMEOUT_SECONDS,
    tester_token_user_lookup=tester_token_username_from_request,
    get_runtime_server_mode=get_runtime_server_mode,
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
    schema_path=os.path.join(BASE_DIR, "bootstrap.schema.sql"),
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
    runtime_base_dir=RUNTIME_SECRETS_DIR,
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
    runtime_secret_files=[
        CHAIN_SEED_PATH,
        CSRF_SECRET_PATH,
        SERVER_FILE_KEY_PATH,
        SESSION_SECRET_PATH,
        os.path.join(RUNTIME_SECRETS_DIR, ".fley"),
        INTEGRITY_KEY_PATH,
        INTEGRITY_MANIFEST_PATH,
        CERT_FILE,
        KEY_FILE,
        SERVER_MODE_LOG_HMAC_KEY_PATH,
    ],
    reset_points_chain=lambda **kwargs: points_service.reset_runtime_chain(**kwargs),
    reset_audit_chain=reset_audit_chain_with_event,
)
ROOT_INTEGRITY_SIGNING_KEY = os.environ.get("ROOT_INTEGRITY_SIGNING_KEY", "").encode("utf-8") or _INTEGRITY_KEY
integrity_guard = IntegrityGuard(
    base_dir=BASE_DIR,
    manifest_path=INTEGRITY_MANIFEST_PATH,
    signing_key=ROOT_INTEGRITY_SIGNING_KEY,
    get_db=get_db,
    audit=audit,
)
points_service = PointsLedgerService(
    get_db=get_db,
    chain_secret=CHAIN_SEED,
    audit=audit,
    backup_dir=POINTS_CHAIN_BACKUP_DIR,
    # Phase 7: chain writes require mode == 'production'.
    mode_reader=get_runtime_server_mode,
    security_event_recorder=lambda event_type, **kwargs: record_security_event(event_type, get_client_ip(), **kwargs),
)
trading_price_stream_hub = TradingPriceStreamHub(audit=audit)
trading_service = TradingEngineService(
    get_db=get_db,
    points_service=points_service,
    audit=audit,
    stream_hub=trading_price_stream_hub,
)
snapshot_service.set_post_restore_validators([
    ("points_chain", lambda: points_service.verify_chain()),
    ("trading_state", lambda: trading_service.verify_state()),
])
server_mode_service = ServerModeService(
    snapshot_service=snapshot_service,
    get_db=get_db,
    audit=audit,
    integrity_guard=integrity_guard,
    save_settings=save_settings,
)

# ── Flask app ──────────────────────────────────────────────────────────────────
app = Flask(__name__, static_folder=PUBLIC_DIR, static_url_path="")
app.config["SECRET_KEY"] = SECRET_KEY
MAX_UPLOAD_REQUEST_MB = _env_int("HTML_LEARNING_MAX_CONTENT_MB", 1024, minimum=128)
app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD_REQUEST_MB * 1024 * 1024
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
        "img-src":     "'self' data: blob:",
        "media-src":   "'self' blob:",
        "frame-src":   "'self' blob:",
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


@app.errorhandler(404)
def api_not_found(error):
    if request.path.startswith("/api"):
        return json_resp({"ok": False, "msg": "Not found"}), 404
    return error


@app.errorhandler(RequestEntityTooLarge)
def api_request_too_large(error):
    if request.path.startswith("/api"):
        limit_bytes = int(app.config.get("MAX_CONTENT_LENGTH") or 0)
        limit_mb = max(1, limit_bytes // (1024 * 1024)) if limit_bytes > 0 else 0
        return json_resp({
            "ok": False,
            "msg": f"上傳內容超過伺服器單次請求上限（{limit_mb} MB）",
            "error": "request_too_large",
            "max_request_mb": limit_mb,
        }), 413
    return error


@app.errorhandler(Exception)
def api_unhandled_exception(error):
    if isinstance(error, HTTPException):
        if request.path.startswith("/api"):
            return json_resp({
                "ok": False,
                "msg": str(error.description or "Request failed"),
                "error": str(error.name or "http_error").strip().lower().replace(" ", "_"),
            }), int(error.code or 500)
        return error
    if request.path.startswith("/api"):
        return json_resp({
            "ok": False,
            "msg": "Internal server error",
            "error": "internal_server_error",
        }), 500
    return "Internal Server Error", 500


@app.before_request
def attach_smv2_ctx():
    """SERVER_MODE_V2_IMPLEMENTATION_PLAN.md Phase 1.

    MUST stay registered as the FIRST before_request hook so every
    later hook + route can read flask.g.smv2_ctx via current_ctx().

    Phase 1 deliberately attaches only `mode` + `request_id` eagerly.
    Computing `tester_id` / `actor_role` here would require running
    `get_current_user_ctx()` for every request — which itself runs
    `tester_token_username_from_request()` (timing-noisy DB query +
    audit event recording). Doing that on top of the per-route auth
    lookups would double the work and push some hot endpoints past
    request-timeout budgets.

    Later phases that genuinely need actor info (Phase 2 routing,
    Phase 5 trading) will populate those fields where needed; see
    `SmV2Context.tester_id` / `.actor_role` defaulting to None.
    """
    if request.method == "OPTIONS":
        return None
    smv2_attach_ctx(mode_reader=get_runtime_server_mode)
    return None


@app.before_request
def protect_sensitive_static_pages():
    if request.method == "OPTIONS" or request.path != "/trading-workflow-editor.html":
        return None
    # Keep these protection markers visible in server.py while the heavy logic
    # lives in services.server_request_guards:
    # get_current_user_ctx()
    # STATIC_PAGE_UNAUTH_DENIED
    # resp.headers["Location"] = "/"
    # is_feature_enabled("feature_trading_enabled")
    return protect_sensitive_static_page_helper(
        request,
        get_current_user_ctx=get_current_user_ctx,
        audit=audit,
        get_client_ip=get_client_ip,
        get_ua=get_ua,
        is_feature_enabled=is_feature_enabled,
        record_security_event=record_security_event,
        make_response=make_response,
    )

# ── CORS (tightly scoped — no wildcard) ────────────────────────────────────────
@app.before_request
def enforce_root_ip_whitelist():
    return enforce_root_ip_whitelist_helper(
        request,
        get_system_settings=get_system_settings,
        normalize_text=normalize_text,
        get_current_user_ctx=get_current_user_ctx,
        root_ip_is_allowed_func=root_ip_is_allowed,
        record_security_event=record_security_event,
        get_client_ip=get_client_ip,
        json_resp=json_resp,
    )


@app.before_request
def enforce_browser_only_mode():
    return enforce_browser_only_mode_helper(
        request,
        get_system_settings=get_system_settings,
        has_valid_maintenance_bypass_func=has_valid_maintenance_bypass,
        is_browser_user_agent=is_browser_user_agent,
        get_current_user_ctx=get_current_user_ctx,
        record_security_event=record_security_event,
        get_client_ip=get_client_ip,
        maintenance_bypass_required_payload=maintenance_bypass_required_payload,
        json_resp=json_resp,
    )


@app.before_request
def restrict_cors():
    if request.method == "OPTIONS":
        origin = request.headers.get("Origin", "")
        # Only allow same-origin
        if origin and origin != request.host_url.rstrip("/"):
            return ("", 204)
    return enforce_mode_restrictions_helper(
        request,
        get_system_settings=get_system_settings,
        smv2_current_ctx=smv2_current_ctx,
        has_valid_maintenance_bypass_func=has_valid_maintenance_bypass,
        get_current_user_ctx=get_current_user_ctx,
        path_is_root_recovery_allowed_during_lockdown_func=path_is_root_recovery_allowed_during_lockdown,
        revoke_user_sessions=revoke_user_sessions,
        audit=audit,
        get_client_ip=get_client_ip,
        maintenance_bypass_required_payload=maintenance_bypass_required_payload,
        json_resp=json_resp,
        session_cookie_samesite=SESSION_COOKIE_SAMESITE,
        session_cookie_secure=SESSION_COOKIE_SECURE,
    )


@app.before_request
def enforce_feature_flags():
    return enforce_feature_flags_helper(
        request,
        feature_gate_for_path_func=feature_gate_for_path,
        is_feature_enabled=is_feature_enabled,
        get_current_user_ctx=get_current_user_ctx,
        record_security_event=record_security_event,
        get_client_ip=get_client_ip,
        build_feature_disabled_payload=build_feature_disabled_payload,
        json_resp=json_resp,
    )


@app.before_request
def enforce_required_password_change():
    return enforce_required_password_change_helper(
        request,
        get_current_user_ctx=get_current_user_ctx,
        json_resp=json_resp,
    )

# ── Routes ─────────────────────────────────────────────────────────────────────
# Source-based compatibility markers kept in ``server.py`` while the actual
# dependency bundle selection lives in ``services.server.routes``:
# "GIT_REPO_DIR": GIT_REPO_DIR
# "require_csrf_safe": require_csrf_safe,
register_server_routes(app, globals())


def start_daily_snapshot_worker():
    return start_daily_snapshot_worker_helper(
        snapshot_service=snapshot_service,
        get_system_settings=get_system_settings,
        save_settings=save_settings,
        audit=audit,
    )


def start_storage_maintenance_worker():
    return start_storage_maintenance_worker_helper(
        get_db=get_db,
        run_storage_maintenance_if_due=run_storage_maintenance_if_due,
        get_system_settings=get_system_settings,
        save_settings=save_settings,
        audit=audit,
    )


def start_points_chain_block_worker():
    return start_points_chain_block_worker_helper(
        points_service=points_service,
        audit=audit,
        default_block_ledger_threshold=DEFAULT_BLOCK_LEDGER_THRESHOLD,
        default_block_max_interval_seconds=DEFAULT_BLOCK_MAX_INTERVAL_SECONDS,
    )


def start_trading_liquidation_worker():
    return start_trading_liquidation_worker_helper(trading_service=trading_service, audit=audit)


def start_trading_bot_worker():
    return start_trading_bot_worker_helper(trading_service=trading_service, audit=audit)


# ── Start ──────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    run_server_main_helper(
        server_log_path=SERVER_LOG_PATH,
        install_runtime_output_capture=install_runtime_output_capture,
        init_db=init_db,
        init_db_kwargs={
            "ensure_secure_audit_columns": ensure_secure_audit_columns,
            "ensure_user_columns": ensure_user_columns,
            "ensure_appeal_columns": ensure_appeal_columns,
            "ensure_security_support_schema": ensure_security_support_schema,
            "ensure_points_economy_schema": ensure_points_economy_schema,
            "ensure_session_columns": ensure_session_columns,
            "ensure_official_chat_room": ensure_official_chat_room,
            "hash_password": hash_password,
        },
        get_db=get_db,
        ensure_trading_schema=ensure_trading_schema,
        reseal_audit_chain_if_required_on_startup=reseal_audit_chain_if_required_on_startup,
        audit=audit,
        server_mode_service=server_mode_service,
        points_service=points_service,
        get_system_settings=get_system_settings,
        integrity_guard=integrity_guard,
        start_daily_snapshot_worker=start_daily_snapshot_worker,
        start_storage_maintenance_worker=start_storage_maintenance_worker,
        start_points_chain_block_worker=start_points_chain_block_worker,
        start_trading_liquidation_worker=start_trading_liquidation_worker,
        start_trading_bot_worker=start_trading_bot_worker,
        ensure_local_tls_files=ensure_local_tls_files,
        cert_file=CERT_FILE,
        key_file=KEY_FILE,
        effective_server_ssl=effective_server_ssl,
        effective_server_bind=effective_server_bind,
        server_bind_state=SERVER_BIND_STATE,
        app=app,
    )
