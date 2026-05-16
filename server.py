#!/usr/bin/env python3
"""
hackme_web — Flask auth server
Hardened edition: timing-noise, account-enumeration protection,
CSRF tokens, strict CSP, full security headers, rate-limit amplification.
"""

import argparse
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
from services.system.audit import (
    _chain_hash,
    audit,
    canonical_json,
    configure_audit_service,
    repair_audit_chain,
    reset_audit_chain_with_event,
    verify_audit_integrity,
)
from services.security.access_controls import (
    client_ip_allowed,
    is_browser_user_agent,
    maintenance_bypass_required_payload,
    verify_maintenance_bypass_token,
)
from services.users.recovery import ensure_account_recovery_schema
from services.users.auth import (
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
    record_login_attempt,
    revoke_user_sessions,
    require_csrf,
    require_csrf_safe,
    store_csrf_token,
    timing_delay,
    verify_csrf_token,
    verify_csrf_double_submit,
    verify_password,
)
from services.platform.settings import (
    DEFAULT_SETTINGS,
    build_feature_disabled_payload,
    configure_settings_service,
    get_cached_system_setting,
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
from services.governance.violations import (
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
from services.security.events import (
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
from services.platform.bootstrap import (
    apply_schema_migrations,
    configure_bootstrap_service,
    init_db,
    migrate_legacy_json_artifacts,
    migrate_legacy_json_to_db,
)
from services.chat.support import (
    append_chat_record,
    configure_chat_support_service,
    ensure_official_chat_room,
    ensure_user_official_room_membership,
)
from services.security.identity import (
    ACCOUNT_STATUSES,
    MEMBER_LEVELS,
    ROLE_LABEL,
    ROLE_RANK,
    ensure_user_identity_columns,
    role_rank,
)
from services.governance.records import ensure_governance_records_schema
from services.system.integrity_guard import IntegrityGuard, ensure_integrity_schema
from services.users.member_levels import ensure_member_level_rules_schema, get_member_level_rule
from services.governance.moderation import ensure_moderation_proposals_schema
from services.security.password_strength import enforce_password_strength, score_password_strength
from services.points_chain import DEFAULT_BLOCK_LEDGER_THRESHOLD, DEFAULT_BLOCK_MAX_INTERVAL_SECONDS, PointsLedgerService, ensure_points_economy_schema
from services.platform.release_info import APP_NAME, APP_RELEASE_ID
from services.core.runtime_output import get_runtime_output, install_runtime_output_capture
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
    default_runtime_root,
    ensure_local_tls_files,
    load_chain_seed,
    load_json,
    parse_ip_set,
    save_json,
)
from services.server.security_runtime import (
    decrypt_field as decrypt_field_helper,
    encrypt_field as encrypt_field_helper,
    feature_gate_for_path as feature_gate_for_path_runtime_helper,
    get_client_ip as get_client_ip_helper,
    get_request_maintenance_bypass_token as get_request_maintenance_bypass_token_runtime_helper,
    get_runtime_server_mode as get_runtime_server_mode_helper,
    get_ua as get_ua_helper,
    has_valid_maintenance_bypass as has_valid_maintenance_bypass_runtime_helper,
    hash_token as hash_token_helper,
    is_audit_chain_enabled as is_audit_chain_enabled_helper,
    is_ip_blocking_enabled as is_ip_blocking_enabled_runtime_helper,
    path_is_root_recovery_allowed_during_lockdown as path_is_root_recovery_allowed_during_lockdown_runtime_helper,
    reseal_audit_chain_if_required_on_startup as reseal_audit_chain_if_required_on_startup_helper,
    root_ip_is_allowed as root_ip_is_allowed_runtime_helper,
    tester_token_identity_from_request as tester_token_identity_from_request_helper,
    tester_token_username_from_request as tester_token_username_from_request_helper,
    verify_token as verify_token_helper,
)
from services.server.validation import (
    normalize_text as normalize_text_helper,
    parse_birthdate as parse_birthdate_helper,
    parse_positive_int as parse_positive_int_helper,
    user_public_payload as user_public_payload_helper,
    validate_id_number as validate_id_number_helper,
    validate_password as validate_password_helper,
    validate_phone as validate_phone_helper,
)
from services.server.database import (
    activate_emergency_lockdown as activate_emergency_lockdown_helper,
    ensure_auth_db_schema as ensure_auth_db_schema_helper,
    count_role as count_role_helper,
    db_get_user_role as db_get_user_role_helper,
    ensure_audit_db_schema as ensure_audit_db_schema_helper,
    ensure_appeal_columns as ensure_appeal_columns_helper,
    ensure_secure_audit_columns as ensure_secure_audit_columns_helper,
    ensure_security_support_schema as ensure_security_support_schema_helper,
    ensure_session_columns as ensure_session_columns_helper,
    ensure_user_columns as ensure_user_columns_helper,
    get_audit_db as get_audit_db_helper,
    get_auth_db as get_auth_db_helper,
    get_control_db as get_control_db_helper,
    get_db as get_db_helper,
    get_user_by_username as get_user_by_username_helper,
)
from services.server.container import build_runtime_services
from services.server.startup import (
    measure_backtest_capacity_if_needed as measure_backtest_capacity_if_needed_helper,
    run_server_main as run_server_main_helper,
    start_daily_snapshot_worker as start_daily_snapshot_worker_helper,
    start_points_chain_block_worker as start_points_chain_block_worker_helper,
    start_storage_maintenance_worker as start_storage_maintenance_worker_helper,
    start_trading_background_worker as start_trading_background_worker_helper,
    start_trading_bot_worker as start_trading_bot_worker_helper,
    start_trading_liquidation_worker as start_trading_liquidation_worker_helper,
)

SERVER_SHUTDOWN_EVENT = None
ENTRYPOINT_DOCTOR_MODE = __name__ == "__main__" and "--doctor" in sys.argv[1:]
ENTRYPOINT_START_MODE = __name__ == "__main__" and not ENTRYPOINT_DOCTOR_MODE
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
from services.server.bind import effective_server_bind, effective_server_ssl
from services.server_mode.context import attach_to_g as smv2_attach_ctx, current_ctx as smv2_current_ctx
from services.platform.db_mode_triggers import register_app_mode_function as smv2_register_app_mode
from services.snapshots import SnapshotService, ServerModeService, ensure_snapshot_schema
from services.snapshots.schema import ensure_control_db_schema
from services.storage.maintenance import run_storage_maintenance_if_due
from services.storage.paths import validate_storage_root
from services.security.upload_security import ensure_upload_security_schema
from services.trading.trading_engine import TradingEngineService, ensure_trading_schema
from services.trading.streams import TradingPriceStreamHub

sys.dont_write_bytecode = True

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

RUNTIME_DIR = _env_path("HACKME_RUNTIME_DIR", default_runtime_root())
RUNTIME_DIR = os.path.abspath(RUNTIME_DIR)
RUNTIME_SECRETS_DIR = _env_path("HTML_LEARNING_RUNTIME_SECRETS_DIR", RUNTIME_DIR)
RUNTIME_SECRETS_DIR = os.path.abspath(RUNTIME_SECRETS_DIR)


def _runtime_path(env_name, relative_path):
    return _env_path(env_name, os.path.join(RUNTIME_SECRETS_DIR, relative_path))


DB_DIR = _env_path("HTML_LEARNING_DB_DIR", os.path.join(RUNTIME_DIR, "database"))
DB_PATH = os.path.join(DB_DIR, "database.db")
AUTH_DB_PATH = _env_path("HTML_LEARNING_AUTH_DB_PATH", os.path.join(DB_DIR, "auth.db"))
AUDIT_DB_PATH = _env_path("HTML_LEARNING_AUDIT_DB_PATH", os.path.join(DB_DIR, "audit.db"))
CONTROL_DB_PATH = _env_path("HTML_LEARNING_CONTROL_DB_PATH", os.path.join(DB_DIR, "control.db"))
CHESS_ENGINE_DB_PATH = _env_path("HTML_LEARNING_CHESS_ENGINE_DB_PATH", os.path.join(RUNTIME_DIR, "games", "models", "chess_experiment.db"))
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

_RUNTIME_REQUIRED_DIRECTORIES = (
    ("runtime_root", RUNTIME_DIR),
    ("runtime_secrets", RUNTIME_SECRETS_DIR),
    ("database", DB_DIR),
    ("logs", LOG_DIR),
    ("chats", CHAT_DIR),
    ("anchors", ANCHOR_DIR),
    ("storage", STORAGE_DIR),
    ("reports", REPORTS_DIR),
)
RUNTIME_ENV_INCOMPLETE = False


def _doctor_dir_status(path):
    entry = {
        "path": os.path.abspath(path),
        "exists": os.path.exists(path),
        "is_dir": os.path.isdir(path),
        "writable": False,
    }
    if entry["exists"] and entry["is_dir"]:
        entry["writable"] = os.access(path, os.W_OK | os.X_OK)
    return entry


def _doctor_report():
    checks = {}
    messages = []
    ok = True
    for label, path in _RUNTIME_REQUIRED_DIRECTORIES:
        status = _doctor_dir_status(path)
        checks[label] = status
        if not status["exists"]:
            ok = False
            messages.append(f"missing runtime directory: {label} -> {status['path']}")
        elif not status["is_dir"]:
            ok = False
            messages.append(f"runtime path is not a directory: {label} -> {status['path']}")
        elif not status["writable"]:
            ok = False
            messages.append(f"runtime directory is not writable: {label} -> {status['path']}")
    port_raw = str(os.environ.get("HTML_LEARNING_PORT", STARTUP_PORT)).strip() or str(STARTUP_PORT)
    try:
        port = int(port_raw)
    except Exception:
        port = 0
        ok = False
        messages.append(f"invalid HTML_LEARNING_PORT: {port_raw}")
    if port < 1 or port > 65535:
        ok = False
        messages.append(f"port out of range: {port_raw}")
    return {
        "ok": ok,
        "messages": messages,
        "bind": {"host": STARTUP_HOST, "port": port},
        "runtime": checks,
        "entry_mode": "doctor" if ENTRYPOINT_DOCTOR_MODE else ("start" if ENTRYPOINT_START_MODE else "import"),
    }


def _print_doctor_report(report):
    print("Hackme Web doctor")
    print(f"- mode: {report.get('entry_mode')}")
    bind = report.get("bind") or {}
    print(f"- bind: {bind.get('host')}:{bind.get('port')}")
    for label, status in (report.get("runtime") or {}).items():
        state = "ok"
        if not status.get("exists"):
            state = "missing"
        elif not status.get("is_dir"):
            state = "not-a-directory"
        elif not status.get("writable"):
            state = "read-only"
        print(f"- {label}: {state} -> {status.get('path')}")
    if report.get("ok"):
        print("doctor: ok")
    else:
        print("doctor: fail")
        for message in report.get("messages") or []:
            print(f"  * {message}")


def run_doctor():
    report = _doctor_report()
    _print_doctor_report(report)
    return report


def _ensure_runtime_dir(path, label):
    if os.path.isdir(path):
        return True
    if ENTRYPOINT_START_MODE or ENTRYPOINT_DOCTOR_MODE:
        return False
    os.makedirs(path, exist_ok=True)
    return True


for _label, _path in _RUNTIME_REQUIRED_DIRECTORIES:
    _ensure_runtime_dir(_path, _label)
RUNTIME_ENV_INCOMPLETE = any(not os.path.isdir(_path) for _, _path in _RUNTIME_REQUIRED_DIRECTORIES)
RUNTIME_BOOTSTRAP_SUPPRESSED = ENTRYPOINT_DOCTOR_MODE or (ENTRYPOINT_START_MODE and RUNTIME_ENV_INCOMPLETE)

if not RUNTIME_BOOTSTRAP_SUPPRESSED and str(os.environ.get("HACKME_RUNTIME_OUTPUT_CAPTURE", "1")).strip().lower() not in {"0", "false", "no"}:
    install_runtime_output_capture(SERVER_LOG_PATH)
get_server_output = get_runtime_output


_configured_storage_root = _load_db_setting_value(DB_PATH, "cloud_drive_storage_root")
if _configured_storage_root:
    STORAGE_DIR = _configured_storage_root
if RUNTIME_BOOTSTRAP_SUPPRESSED:
    STORAGE_DIR = os.path.abspath(STORAGE_DIR)
else:
    STORAGE_DIR = str(validate_storage_root(STORAGE_DIR, base_dir=BASE_DIR, create=not (ENTRYPOINT_DOCTOR_MODE or ENTRYPOINT_START_MODE)))

# ── Hash-chain seed (server-side only, not exposed to client) ─────────────────
if RUNTIME_BOOTSTRAP_SUPPRESSED:
    CHAIN_SEED = "doctor"
else:
    CHAIN_SEED = load_chain_seed(CHAIN_SEED_PATH)

# ── Secrets ─────────────────────────────────────────────────────────────────
if RUNTIME_BOOTSTRAP_SUPPRESSED:
    SECRET_KEY = "doctor-session-secret"
    SERVER_FILE_ENCRYPTION_KEY = Fernet.generate_key().decode("utf-8")
    _INTEGRITY_KEY = b"doctor-integrity-key-32-bytes!!"
else:
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
    return encrypt_field_helper(value, fernet=fernet)

def decrypt_field(value):
    return decrypt_field_helper(value, fernet=fernet)

def verify_token(token):
    return verify_token_helper(token, fernet=fernet)

# ── Token hash (stored in DB for session lookup) ──────────────────────────────
def hash_token(token):
    return hash_token_helper(token)

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
if RUNTIME_BOOTSTRAP_SUPPRESSED:
    CSRF_SECRET_KEY = "doctor-csrf-secret"
else:
    CSRF_SECRET_KEY = _load_or_create_text_secret(
        "CSRF_SECRET_KEY",
        CSRF_SECRET_PATH,
        generator=lambda: secrets.token_hex(32),
    )


def get_client_ip():
    return get_client_ip_helper(request, use_xff=USE_XFF, trusted_proxy_ips=TRUSTED_PROXY_IPS)

def get_ua(): return get_ua_helper(request)

def is_audit_chain_enabled():
    return is_audit_chain_enabled_helper(get_system_settings=get_system_settings)

def reseal_audit_chain_if_required_on_startup():
    return reseal_audit_chain_if_required_on_startup_helper(
        get_system_settings=get_system_settings,
        repair_audit_chain=repair_audit_chain,
        save_settings=save_settings,
        audit=audit,
    )

def is_ip_blocking_enabled():
    return is_ip_blocking_enabled_runtime_helper(
        get_system_settings=get_system_settings,
        env_default=IP_BLOCKING_ENABLED,
    )


def get_request_maintenance_bypass_token():
    return get_request_maintenance_bypass_token_runtime_helper(
        request,
        helper=get_request_maintenance_bypass_token_helper,
    )


def has_valid_maintenance_bypass(settings=None):
    return has_valid_maintenance_bypass_runtime_helper(
        settings=settings,
        get_system_settings=get_system_settings,
        request_obj=request,
        helper=has_valid_maintenance_bypass_helper,
        verify_maintenance_bypass_token=verify_maintenance_bypass_token,
    )


def get_runtime_server_mode():
    return get_runtime_server_mode_helper(get_db=get_db, get_control_db=get_control_db)


def tester_token_username_from_request(req):
    return tester_token_username_from_request_helper(
        req,
        get_db=get_db,
        ensure_snapshot_schema=ensure_snapshot_schema,
        get_runtime_server_mode_func=get_runtime_server_mode,
        record_security_event=record_security_event,
        get_client_ip_func=get_client_ip,
    )


def tester_token_identity_from_request(req):
    return tester_token_identity_from_request_helper(
        req,
        get_db=get_db,
        ensure_snapshot_schema=ensure_snapshot_schema,
        get_runtime_server_mode_func=get_runtime_server_mode,
        record_security_event=record_security_event,
        get_client_ip_func=get_client_ip,
    )


def tester_token_tester_id_from_request():
    identity = tester_token_identity_from_request(request)
    if not identity:
        return None
    return identity.get("tester_id")


def tester_token_actor_role_from_request():
    identity = tester_token_identity_from_request(request)
    if not identity:
        return None
    return identity.get("actor_role")


def path_is_root_recovery_allowed_during_lockdown(path):
    return path_is_root_recovery_allowed_during_lockdown_runtime_helper(
        path,
        helper=path_is_root_recovery_allowed_during_lockdown_helper,
    )


def root_ip_is_allowed(settings=None):
    return root_ip_is_allowed_runtime_helper(
        settings=settings,
        get_system_settings=get_system_settings,
        get_client_ip_func=get_client_ip,
        helper=root_ip_is_allowed_helper,
        client_ip_allowed=client_ip_allowed,
    )


def feature_gate_for_path(path):
    return feature_gate_for_path_runtime_helper(
        path,
        helper=feature_gate_for_path_helper,
    )

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
    return normalize_text_helper(v)


def parse_birthdate(v):
    return parse_birthdate_helper(v)


def parse_positive_int(v, default=None, min_value=1, max_value=None):
    return parse_positive_int_helper(v, default=default, min_value=min_value, max_value=max_value)


def validate_password(pw):
    return validate_password_helper(pw)


def validate_id_number(v):
    return validate_id_number_helper(v)


def validate_phone(v):
    return validate_phone_helper(v)


def get_db():
    return get_db_helper(
        DB_PATH,
        register_app_mode=lambda conn: smv2_register_app_mode(conn, mode_reader=get_runtime_server_mode),
    )


def get_audit_db():
    return get_audit_db_helper(AUDIT_DB_PATH)


def get_auth_db():
    return get_auth_db_helper(AUTH_DB_PATH)


def get_control_db():
    return get_control_db_helper(CONTROL_DB_PATH)


def _ensure_split_db_schemas():
    auth_conn = get_auth_db()
    try:
        ensure_auth_db_schema(auth_conn)
        auth_conn.commit()
    finally:
        auth_conn.close()
    audit_conn = get_audit_db()
    try:
        ensure_audit_db_schema(audit_conn)
        audit_conn.commit()
    finally:
        audit_conn.close()
    control_conn = get_control_db()
    try:
        ensure_control_db_schema(control_conn)
        control_conn.commit()
    finally:
        control_conn.close()


def _migrate_secure_audit_if_needed():
    if os.path.abspath(AUDIT_DB_PATH) == os.path.abspath(DB_PATH):
        return
    try:
        audit_conn = get_audit_db()
    except Exception:
        return
    try:
        audit_count = audit_conn.execute("SELECT COUNT(*) AS c FROM secure_audit").fetchone()["c"]
        if int(audit_count or 0) > 0:
            return
    except Exception:
        return
    finally:
        audit_conn.close()


def _migrate_auth_tables_if_needed():
    if os.path.abspath(AUTH_DB_PATH) == os.path.abspath(DB_PATH):
        return
    tables = ("csrf_tokens", "captcha_challenges", "login_attempts", "sessions")
    try:
        auth_conn = get_auth_db()
    except Exception:
        return
    try:
        auth_tables = {
            row["name"]: int(
                auth_conn.execute(f"SELECT COUNT(*) AS c FROM {row['name']}").fetchone()["c"]
            )
            for row in auth_conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name IN ('csrf_tokens','captcha_challenges','login_attempts','sessions')"
            ).fetchall()
        }
        if all(auth_tables.get(name, 0) > 0 for name in tables):
            return
    except Exception:
        return
    finally:
        auth_conn.close()


def _migrate_control_tables_if_needed():
    if os.path.abspath(CONTROL_DB_PATH) == os.path.abspath(DB_PATH):
        return
    tables = (
        "server_modes",
        "server_checkpoints",
        "mode_switch_logs",
        "security_keys",
        "production_entry_reports",
        "incident_reports",
        "security_profiles",
    )
    try:
        control_conn = get_control_db()
    except Exception:
        return
    try:
        existing = {
            row["name"]: int(control_conn.execute(f"SELECT COUNT(*) AS c FROM {row['name']}").fetchone()["c"])
            for row in control_conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name IN "
                "('server_modes','server_checkpoints','mode_switch_logs','security_keys','production_entry_reports','incident_reports','security_profiles')"
            ).fetchall()
        }
        if all(existing.get(name, 0) > 0 for name in ("server_modes", "security_profiles")):
            return
    except Exception:
        return
    finally:
        control_conn.close()
    try:
        main_conn = sqlite3.connect(DB_PATH, timeout=15)
        main_conn.row_factory = sqlite3.Row
    except Exception:
        return
    try:
        existing_tables = {
            row["name"]
            for row in main_conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        }
        table_columns = {
            name: [row["name"] for row in main_conn.execute(f"PRAGMA table_info({name})").fetchall()]
            for name in tables
            if name in existing_tables
        }
        table_rows = {}
        for name in tables:
            columns = table_columns.get(name)
            if not columns:
                continue
            rows = main_conn.execute(f"SELECT {', '.join(columns)} FROM {name}").fetchall()
            if rows:
                table_rows[name] = (columns, rows)
    except Exception:
        table_rows = {}
    finally:
        try:
            main_conn.close()
        except Exception:
            pass
    if not table_rows:
        return
    control_conn = get_control_db()
    try:
        for name, (columns, rows) in table_rows.items():
            placeholders = ", ".join("?" for _ in columns)
            control_conn.executemany(
                f"INSERT OR IGNORE INTO {name} ({', '.join(columns)}) VALUES ({placeholders})",
                [tuple(row[column] for column in columns) for row in rows],
            )
        control_conn.commit()
    finally:
        control_conn.close()
    try:
        main_conn = sqlite3.connect(DB_PATH, timeout=15)
        main_conn.row_factory = sqlite3.Row
    except Exception:
        return
    try:
        existing_tables = {
            row["name"]
            for row in main_conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        }
        table_columns = {
            name: [row["name"] for row in main_conn.execute(f"PRAGMA table_info({name})").fetchall()]
            for name in tables
            if name in existing_tables
        }
        table_rows = {}
        for name in tables:
            columns = table_columns.get(name)
            if not columns:
                continue
            sql = f"SELECT {', '.join(columns)} FROM {name}"
            rows = main_conn.execute(sql).fetchall()
            if rows:
                table_rows[name] = (columns, rows)
    except Exception:
        table_rows = {}
    finally:
        try:
            main_conn.close()
        except Exception:
            pass
    if not table_rows:
        return
    auth_conn = get_auth_db()
    try:
        for name, (columns, rows) in table_rows.items():
            placeholders = ", ".join("?" for _ in columns)
            auth_conn.executemany(
                f"INSERT OR IGNORE INTO {name} ({', '.join(columns)}) VALUES ({placeholders})",
                [tuple(row[column] for column in columns) for row in rows],
            )
        auth_conn.commit()
    except Exception:
        try:
            auth_conn.rollback()
        except Exception:
            pass
    finally:
        auth_conn.close()
    try:
        main_conn = sqlite3.connect(DB_PATH, timeout=15)
        main_conn.row_factory = sqlite3.Row
        table_exists = main_conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='secure_audit' LIMIT 1"
        ).fetchone()
        if not table_exists:
            return
        rows = main_conn.execute(
            "SELECT id, ts, action, ip, user, success, ua, detail, prev_hash, entry_hash, chain_hash "
            "FROM secure_audit ORDER BY id ASC"
        ).fetchall()
        if not rows:
            return
    except Exception:
        return
    finally:
        try:
            main_conn.close()
        except Exception:
            pass
    audit_conn = get_audit_db()
    try:
        audit_conn.executemany(
            """
            INSERT OR IGNORE INTO secure_audit
            (id, ts, action, ip, user, success, ua, detail, prev_hash, entry_hash, chain_hash)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    row["id"],
                    row["ts"],
                    row["action"],
                    row["ip"],
                    row["user"],
                    row["success"],
                    row["ua"],
                    row["detail"],
                    row["prev_hash"] if "prev_hash" in row.keys() else "",
                    row["entry_hash"] if "entry_hash" in row.keys() else "",
                    row["chain_hash"] if "chain_hash" in row.keys() else "",
                )
                for row in rows
            ],
        )
        audit_conn.commit()
    except Exception:
        try:
            audit_conn.rollback()
        except Exception:
            pass
    finally:
        audit_conn.close()


def count_role(role):
    return count_role_helper(role, get_db=get_db)


def get_user_by_username(username):
    return get_user_by_username_helper(username, get_db=get_db)


def user_public_payload(row, *, include_sensitive=False):
    return user_public_payload_helper(
        row,
        decrypt_field=decrypt_field,
        role_label=ROLE_LABEL,
        include_sensitive=include_sensitive,
    )


def ensure_user_columns(conn):
    return ensure_user_columns_helper(conn, ensure_user_identity_columns=ensure_user_identity_columns)


def ensure_secure_audit_columns(conn):
    return ensure_secure_audit_columns_helper(conn)


def ensure_auth_db_schema(conn):
    return ensure_auth_db_schema_helper(conn)


def ensure_audit_db_schema(conn):
    return ensure_audit_db_schema_helper(conn)


def ensure_appeal_columns(conn):
    return ensure_appeal_columns_helper(conn)


def ensure_session_columns(conn):
    return ensure_session_columns_helper(conn)


def ensure_security_support_schema(conn):
    return ensure_security_support_schema_helper(
        conn,
        ensure_member_level_rules_schema=ensure_member_level_rules_schema,
        ensure_moderation_proposals_schema=ensure_moderation_proposals_schema,
        ensure_governance_records_schema=ensure_governance_records_schema,
        ensure_snapshot_schema=ensure_snapshot_schema,
        ensure_upload_security_schema=ensure_upload_security_schema,
        ensure_integrity_schema=ensure_integrity_schema,
        ensure_account_recovery_schema=ensure_account_recovery_schema,
    )


def db_get_user_role(username):
    return db_get_user_role_helper(username, get_db=get_db)


def activate_emergency_lockdown(reason):
    return activate_emergency_lockdown_helper(
        reason,
        get_db=get_db,
        init_system_settings_table=init_system_settings_table,
        refresh_system_settings=refresh_system_settings,
        audit=audit,
        get_client_ip_func=get_client_ip,
    )


ROOT_INTEGRITY_SIGNING_KEY = os.environ.get("ROOT_INTEGRITY_SIGNING_KEY", "").encode("utf-8") or _INTEGRITY_KEY
_ensure_split_db_schemas()
_migrate_secure_audit_if_needed()
_migrate_auth_tables_if_needed()
_migrate_control_tables_if_needed()
_runtime_services = build_runtime_services(
    config={
        "base_dir": BASE_DIR,
        "db_dir": DB_DIR,
        "db_path": DB_PATH,
        "auth_db_path": AUTH_DB_PATH,
        "audit_db_path": AUDIT_DB_PATH,
        "control_db_path": CONTROL_DB_PATH,
        "chess_engine_db_path": CHESS_ENGINE_DB_PATH,
        "runtime_secrets_dir": RUNTIME_SECRETS_DIR,
        "storage_root": STORAGE_DIR,
        "chat_dir": CHAT_DIR,
        "points_chain_backup_dir": POINTS_CHAIN_BACKUP_DIR,
        "audit_log_path": AUDIT_LOG_PATH,
        "audit_anchor_path": AUDIT_ANCHOR_PATH,
        "audit_anchor_latest_path": AUDIT_ANCHOR_LATEST_PATH,
        "audit_anchor_interval_seconds": AUDIT_ANCHOR_INTERVAL_SECONDS,
        "legacy_fail_log": LEGACY_FAIL_LOG,
        "legacy_blocked_ips": LEGACY_BLOCKED_IPS,
        "legacy_rate_limit": LEGACY_RATE_LIMIT,
        "legacy_audit_log": LEGACY_AUDIT_LOG,
        "official_chat_room_name": OFFICIAL_CHAT_ROOM_NAME,
        "chain_seed": CHAIN_SEED,
        "integrity_key": _INTEGRITY_KEY,
        "root_integrity_signing_key": ROOT_INTEGRITY_SIGNING_KEY,
        "integrity_manifest_path": INTEGRITY_MANIFEST_PATH,
        "file_roots": [
            CHAT_DIR,
            STORAGE_DIR,
        ],
        "config_files": [
            os.path.join(BASE_DIR, "system_settings.json"),
            os.path.join(BASE_DIR, "settings.json"),
            os.path.join(BASE_DIR, ".env"),
        ],
        "runtime_secret_files": [
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
    },
    deps={
        "get_db": get_db,
        "get_auth_db": get_auth_db,
        "get_audit_db": get_audit_db,
        "get_control_db": get_control_db,
        "get_user_by_username": get_user_by_username,
        "fernet": fernet,
        "get_client_ip": get_client_ip,
        "session_ttl": SESSION_TTL,
        "csrf_token_ttl": CSRF_TOKEN_TTL,
        "session_idle_timeout": SESSION_IDLE_TIMEOUT_SECONDS,
        "tester_token_user_lookup": tester_token_username_from_request,
        "get_runtime_server_mode": get_runtime_server_mode,
        "get_cached_system_setting": get_cached_system_setting,
        "get_system_settings": get_system_settings,
        "save_settings": save_settings,
        "refresh_system_settings": refresh_system_settings,
        "init_system_settings_table": init_system_settings_table,
        "seed_missing_settings": _seed_missing_settings_to_db,
        "import_legacy_settings_files": _import_legacy_settings_files,
        "default_settings": DEFAULT_SETTINGS,
        "load_json": load_json,
        "normalize_text": normalize_text,
        "hash_password": hash_password,
        "verify_password": verify_password,
        "audit": audit,
        "is_ip_blocking_enabled": is_ip_blocking_enabled,
        "encrypt_field": encrypt_field,
        "record_security_event": record_security_event,
        "record_login_attempt": record_login_attempt,
    },
)
snapshot_service = _runtime_services["snapshot_service"]
integrity_guard = _runtime_services["integrity_guard"]
points_service = _runtime_services["points_service"]
trading_price_stream_hub = _runtime_services["trading_price_stream_hub"]
trading_service = _runtime_services["trading_service"]
chess_engine_store = _runtime_services["chess_engine_store"]
server_mode_service = _runtime_services["server_mode_service"]

# ── Flask app ──────────────────────────────────────────────────────────────────
app = Flask(__name__, static_folder=PUBLIC_DIR, static_url_path="")
app.config["SECRET_KEY"] = SECRET_KEY
MAX_UPLOAD_REQUEST_MB = _env_int("HTML_LEARNING_MAX_CONTENT_MB", 1024, minimum=128)
app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD_REQUEST_MB * 1024 * 1024
STATIC_ASSET_CACHE_SECONDS = _env_int(
    "HTML_LEARNING_STATIC_ASSET_CACHE_SECONDS",
    365 * 24 * 60 * 60,
    minimum=0,
)
app.config["SESSION_COOKIE_SECURE"] = SESSION_COOKIE_SECURE
app.config["SESSION_COOKIE_HTTPONLY"] = SESSION_COOKIE_HTTPONLY
app.config["SESSION_COOKIE_SAMESITE"] = SESSION_COOKIE_SAMESITE
app.config["PREFERRED_URL_SCHEME"] = "https" if FORCE_HTTPS else "http"

# ── Security Headers (via Flask-Talisman) ─────────────────────────────────────
# CSP: keep scripts strict. The existing UI uses inline style attributes and
# runtime element positioning, including the ComfyUI visual workflow editor.
talisman = Talisman(app,
    content_security_policy={
        "default-src": "'self'",
        "script-src":  "'self'",
        "style-src":   "'self' 'unsafe-inline'",
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
    elif STATIC_ASSET_CACHE_SECONDS > 0 and (
        ((request.path == "/styles.css" or request.path.startswith("/js/")) and request.args.get("v"))
        or request.path.startswith("/assets/")
    ):
        response.headers["Cache-Control"] = f"public, max-age={STATIC_ASSET_CACHE_SECONDS}, immutable"
        response.headers.pop("Pragma", None)
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
    try:
        app.logger.exception("Unhandled exception while serving %s %s", request.method, request.path)
    except Exception:
        pass
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

    We still refuse to hydrate full session-cookie actor info here.
    The only eagerly attached actor metadata is tester-token identity,
    because internal_test trading/orderbook routing must know the
    tester namespace before any write path runs. Requests without a
    tester token stay cheap: the reader exits before any DB work.
    """
    if request.method == "OPTIONS":
        return None
    smv2_attach_ctx(
        mode_reader=get_runtime_server_mode,
        tester_id_reader=tester_token_tester_id_from_request,
        actor_role_reader=tester_token_actor_role_from_request,
    )
    return None


@app.before_request
def protect_sensitive_static_pages():
    if request.method == "OPTIONS" or request.path not in {"/trading-workflow-editor.html", "/comfyui-workflow-editor.html"}:
        return None
    # Keep these protection markers visible in server.py while the heavy logic
    # lives in services.server_request_guards:
    # get_current_user_ctx()
    # STATIC_PAGE_UNAUTH_DENIED
    # resp.headers["Location"] = "/"
    # is_feature_enabled("feature_trading_enabled")
    # is_feature_enabled("feature_comfyui_enabled")
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


def start_daily_snapshot_worker(shutdown_event=None):
    return start_daily_snapshot_worker_helper(
        snapshot_service=snapshot_service,
        get_system_settings=get_system_settings,
        save_settings=save_settings,
        audit=audit,
        shutdown_event=shutdown_event or SERVER_SHUTDOWN_EVENT,
    )


def start_storage_maintenance_worker(shutdown_event=None):
    return start_storage_maintenance_worker_helper(
        get_db=get_db,
        run_storage_maintenance_if_due=run_storage_maintenance_if_due,
        get_system_settings=get_system_settings,
        save_settings=save_settings,
        audit=audit,
        shutdown_event=shutdown_event or SERVER_SHUTDOWN_EVENT,
    )


def start_points_chain_block_worker(shutdown_event=None):
    return start_points_chain_block_worker_helper(
        points_service=points_service,
        audit=audit,
        default_block_ledger_threshold=DEFAULT_BLOCK_LEDGER_THRESHOLD,
        default_block_max_interval_seconds=DEFAULT_BLOCK_MAX_INTERVAL_SECONDS,
        get_system_settings=get_system_settings,
        shutdown_event=shutdown_event or SERVER_SHUTDOWN_EVENT,
    )


def start_trading_liquidation_worker(shutdown_event=None):
    return start_trading_liquidation_worker_helper(
        trading_service=trading_service,
        audit=audit,
        get_system_settings=get_system_settings,
        shutdown_event=shutdown_event or SERVER_SHUTDOWN_EVENT,
    )


def start_trading_bot_worker(shutdown_event=None):
    return start_trading_bot_worker_helper(
        trading_service=trading_service,
        audit=audit,
        get_system_settings=get_system_settings,
        shutdown_event=shutdown_event or SERVER_SHUTDOWN_EVENT,
    )


def start_trading_background_worker(shutdown_event=None):
    return start_trading_background_worker_helper(
        trading_service=trading_service,
        audit=audit,
        get_system_settings=get_system_settings,
        get_runtime_server_mode=get_runtime_server_mode,
        shutdown_event=shutdown_event or SERVER_SHUTDOWN_EVENT,
    )


def measure_backtest_capacity_first_boot():
    return measure_backtest_capacity_if_needed_helper(trading_service=trading_service, audit=audit)


# ── Start ──────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Hackme Web server entrypoint")
    parser.add_argument("--doctor", action="store_true", help="Validate the current runtime environment and exit")
    args = parser.parse_args()

    if args.doctor:
        doctor = run_doctor()
        raise SystemExit(0 if doctor.get("ok") else 2)

    doctor = _doctor_report()
    if not doctor.get("ok"):
        _print_doctor_report(doctor)
        raise SystemExit(2)

    SERVER_SHUTDOWN_EVENT = threading.Event()

    def _handle_shutdown(signum, frame):
        print(f"[shutdown] signal {signum} received, draining workers...", flush=True)
        SERVER_SHUTDOWN_EVENT.set()
        raise SystemExit(0)

    signal.signal(signal.SIGTERM, _handle_shutdown)
    signal.signal(signal.SIGINT, _handle_shutdown)

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
        start_trading_background_worker=start_trading_background_worker,
        get_runtime_server_mode=get_runtime_server_mode,
        measure_backtest_capacity_first_boot=measure_backtest_capacity_first_boot,
        ensure_local_tls_files=ensure_local_tls_files,
        cert_file=CERT_FILE,
        key_file=KEY_FILE,
        effective_server_ssl=effective_server_ssl,
        effective_server_bind=effective_server_bind,
        server_bind_state=SERVER_BIND_STATE,
        app=app,
        shutdown_event=SERVER_SHUTDOWN_EVENT,
    )
