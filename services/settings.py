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
}

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
