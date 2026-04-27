import os
import sqlite3
import threading
from datetime import datetime

SYSTEM_SETTINGS_TABLE = "system_settings"
DEFAULT_SETTINGS = {
    "audit_chain_enabled": False,
    "ip_blocking_enabled": True,
    "max_login_fails_for_violation": 5,
    "login_violation_enabled": True,
    "rate_limit_violation_enabled": True,
    "maintenance_mode": False,
    "root_ip_whitelist_enabled": False,
    "root_ip_whitelist": "",
    "browser_only_mode_enabled": False,
    "maintenance_bypass_token_hash": "",
    "maintenance_bypass_token_expires_at": "",
    "server_listen_host": "",
    "server_listen_port": 0,
    "cloud_drive_storage_root": "",
    "allow_register": True,
    "require_email_verification": False,
    "max_login_failures": 3,
    "block_duration_minutes": 10,
    "session_ttl_hours": 4,
    "site_bg": "#0f0f1a",
    "site_surface": "#1a1a2e",
    "site_accent": "#6c63ff",
    "site_accent2": "#00d4aa",
    "site_text": "#e0e0f0",
    "site_muted": "#8888aa",
    "site_layout_mode": "centered",
    "site_density": "comfortable",
    "module_chat_min_role": "user",
    "module_community_min_role": "user",
    "module_appeals_min_role": "user",
    "module_accounts_min_role": "manager",
    "chat_filter_rules_json": "",
    "feature_chat_enabled": True,
    "feature_community_enabled": True,
    "feature_accounts_enabled": True,
    "feature_appeals_enabled": True,
    "feature_audit_log_enabled": True,
    "feature_violation_center_enabled": True,
    "feature_reports_enabled": True,
    "feature_system_health_enabled": True,
    "feature_identity_governance_enabled": True,
    "feature_account_security_enabled": False,
    "feature_member_governance_enabled": False,
    "feature_server_modes_enabled": False,
    "feature_snapshot_restore_enabled": False,
    "snapshot_daily_auto_enabled": False,
    "snapshot_daily_time": "03:00",
    "snapshot_daily_last_date": "",
    "feature_health_center_enabled": True,
    "feature_forum_core_enabled": True,
    "feature_ui_rebuild_enabled": False,
    "feature_reports_notifications_enabled": True,
    "feature_dm_enabled": False,
    "feature_attachments_enabled": False,
    "feature_storage_albums_enabled": False,
    "feature_personalization_enabled": False,
    "feature_social_search_enabled": False,
    "feature_advanced_security_enabled": False,
    "feature_privacy_uploads_enabled": False,
}

FEATURE_FLAG_KEYS = tuple(key for key in DEFAULT_SETTINGS if key.startswith("feature_"))

_SETTINGS_LOCK = threading.Lock()
_SYSTEM_SETTINGS = None
_STATE = {
    "get_db": None,
    "load_json": None,
    "settings_files": (),
}


def configure_settings_service(*, get_db, load_json, base_dir):
    _STATE.update({
        "get_db": get_db,
        "load_json": load_json,
        "settings_files": (
            os.path.join(base_dir, "system_settings.json"),
            os.path.join(base_dir, "settings.json"),
        ),
    })


def _coerce_setting_value(key, value):
    default = DEFAULT_SETTINGS.get(key)
    if isinstance(default, bool):
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "on", "y", "t"}
        if isinstance(value, int):
            return value != 0
        return bool(value)
    if isinstance(default, int):
        try:
            return int(value)
        except Exception:
            return default
    if default is None:
        return value
    return str(value)


def init_system_settings_table(conn):
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS system_settings (
            key         TEXT PRIMARY KEY,
            value       TEXT NOT NULL,
            updated_at  TEXT NOT NULL,
            updated_by  TEXT
        )
        """
    )


def _load_settings_from_db(conn=None):
    close_conn = False
    if conn is None:
        conn = _STATE["get_db"]()
        close_conn = True
    try:
        try:
            rows = conn.execute(
                f"SELECT key, value FROM {SYSTEM_SETTINGS_TABLE}"
            ).fetchall()
        except sqlite3.OperationalError:
            rows = []
        values = {r["key"]: _coerce_setting_value(r["key"], r["value"]) for r in rows}
        return {**DEFAULT_SETTINGS, **values}
    finally:
        if close_conn:
            conn.close()


def _seed_missing_settings_to_db(conn):
    now = datetime.now().isoformat()
    existing = {r["key"] for r in conn.execute("SELECT key FROM system_settings").fetchall()}
    for key, default in DEFAULT_SETTINGS.items():
        if key not in existing:
            conn.execute(
                "INSERT INTO system_settings (key, value, updated_at, updated_by) VALUES (?, ?, ?, ?)",
                (key, str(default), now, "system")
            )


def _import_legacy_settings_files(conn):
    for path in _STATE["settings_files"]:
        data = _STATE["load_json"](path)
        if not isinstance(data, dict):
            continue
        for key in DEFAULT_SETTINGS:
            if key in data:
                conn.execute(
                    "INSERT OR REPLACE INTO system_settings (key, value, updated_at, updated_by) VALUES (?, ?, ?, ?)",
                    (key, str(_coerce_setting_value(key, data[key])), datetime.now().isoformat(), "migration")
                )


def get_system_settings():
    with _SETTINGS_LOCK:
        return (_SYSTEM_SETTINGS.copy() if isinstance(_SYSTEM_SETTINGS, dict) else _load_settings_from_db())


def load_settings():
    return get_system_settings()


def refresh_system_settings():
    global _SYSTEM_SETTINGS
    with _SETTINGS_LOCK:
        _SYSTEM_SETTINGS = _load_settings_from_db()
        return _SYSTEM_SETTINGS


def save_settings(data):
    updates = {}
    if not isinstance(data, dict):
        return {}
    for key, value in data.items():
        if key not in DEFAULT_SETTINGS:
            continue
        updates[key] = _coerce_setting_value(key, value)
    if not updates:
        return {}

    conn = _STATE["get_db"]()
    try:
        init_system_settings_table(conn)
        now = datetime.now().isoformat()
        for key, value in updates.items():
            conn.execute(
                "INSERT OR REPLACE INTO system_settings (key, value, updated_at, updated_by) VALUES (?, ?, ?, ?)",
                (key, str(value), now, "admin")
            )
        conn.commit()
        _seed_missing_settings_to_db(conn)
    finally:
        conn.close()
    refresh_system_settings()
    return updates


def is_feature_enabled(feature_key):
    key = str(feature_key or "")
    if not key.startswith("feature_"):
        key = f"feature_{key}_enabled"
    settings = get_system_settings()
    default = DEFAULT_SETTINGS.get(key, False)
    return bool(settings.get(key, default))


def get_feature_settings():
    settings = get_system_settings()
    return {key: bool(settings.get(key, DEFAULT_SETTINGS[key])) for key in FEATURE_FLAG_KEYS}


def save_feature_settings(data):
    if not isinstance(data, dict):
        return {}
    updates = {key: value for key, value in data.items() if key in FEATURE_FLAG_KEYS}
    return save_settings(updates)
