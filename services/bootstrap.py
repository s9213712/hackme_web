import json
import os
from datetime import datetime

CURRENT_SCHEMA_VERSION = 4
SCHEMA_MIGRATIONS = (
    (1, "bootstrap schema_migrations metadata table"),
    (2, "ensure legacy-compatible users columns"),
    (3, "ensure violation_appeals columns"),
    (4, "ensure system_settings baseline rows"),
)

_STATE = {
    "get_db": None,
    "db_path": None,
    "schema_path": None,
    "legacy_fail_log": None,
    "legacy_blocked_ips": None,
    "legacy_rate_limit": None,
    "legacy_audit_log": None,
    "chain_seed": None,
    "chain_hash": None,
    "load_json": None,
    "normalize_text": None,
    "hash_password": None,
    "audit": None,
    "refresh_system_settings": None,
    "init_system_settings_table": None,
    "seed_missing_settings": None,
    "import_legacy_settings_files": None,
    "default_settings": None,
}


def configure_bootstrap_service(**kwargs):
    _STATE.update(kwargs)


def _safe_iso(value, fallback=None):
    if not value:
        return fallback
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(value).isoformat()
        except Exception:
            return fallback
    if isinstance(value, str):
        v = value.strip()
        if not v:
            return fallback
        try:
            return datetime.fromisoformat(v).isoformat()
        except Exception:
            return v
    return fallback


def _coerce_count(v, default=0):
    try:
        n = int(v)
        return n if n > 0 else default
    except Exception:
        return default


def _migrate_legacy_fail_log_rows():
    payload = _STATE["load_json"](_STATE["legacy_fail_log"])
    now = datetime.now().isoformat()
    rows = []
    if isinstance(payload, list):
        candidates = payload
    elif isinstance(payload, dict):
        candidates = []
        for ip, item in payload.items():
            if not isinstance(ip, str):
                continue
            if isinstance(item, dict):
                count = _coerce_count(item.get("count", 1), 1)
                created_at = _safe_iso(item.get("created_at") or item.get("ts") or item.get("time"), now)
                username = _STATE["normalize_text"](item.get("username") or item.get("user") or item.get("target_user"))
                detail = _STATE["normalize_text"](item.get("detail") or item.get("reason"))
            else:
                count = _coerce_count(item, 1)
                created_at = now
                username = ""
                detail = "legacy fail_log"
            for _ in range(min(max(1, count), 1000)):
                rows.append({"event_type": "login_fail", "ip_address": ip, "target_user": username or None, "detail": detail or "legacy fail_log", "created_at": created_at})
    else:
        candidates = []
    if isinstance(payload, list):
        for item in candidates:
            if not isinstance(item, dict):
                continue
            ip = _STATE["normalize_text"](item.get("ip") or item.get("ip_address"))
            if not ip:
                continue
            count = _coerce_count(item.get("count", 1), 1)
            username = _STATE["normalize_text"](item.get("username") or item.get("target_user") or item.get("user"))
            detail = _STATE["normalize_text"](item.get("detail") or item.get("reason"))
            created_at = _safe_iso(item.get("created_at") or item.get("ts") or item.get("time"), now)
            for _ in range(min(max(1, count), 1000)):
                rows.append({"event_type": "login_fail", "ip_address": ip, "target_user": username or None, "detail": detail or "legacy fail_log", "created_at": created_at})
    return rows


def _migrate_legacy_blocked_ip_rows():
    payload = _STATE["load_json"](_STATE["legacy_blocked_ips"])
    now = datetime.now().isoformat()
    rows = []
    if not isinstance(payload, dict):
        return rows
    for ip, value in payload.items():
        if not isinstance(ip, str):
            continue
        detail = ""
        blocked_until = None
        if isinstance(value, dict):
            blocked_until = _safe_iso(value.get("blocked_until") or value.get("until") or value.get("expires_at"), None)
            detail = _STATE["normalize_text"](value.get("detail") or value.get("reason"))
        elif isinstance(value, str):
            blocked_until = _safe_iso(value, None)
            detail = "legacy blocked_ips.json"
        elif isinstance(value, (int, float)):
            blocked_until = _safe_iso(value, None)
            detail = "legacy blocked_ips.json"
        else:
            detail = "legacy blocked_ips.json"
        if not blocked_until:
            blocked_until = now
        rows.append({"event_type": "ip_block", "ip_address": ip, "target_user": None, "detail": f"blocked_until={blocked_until}" + (f" ({detail})" if detail else ""), "created_at": now})
    return rows


def _migrate_legacy_rate_limit_rows():
    payload = _STATE["load_json"](_STATE["legacy_rate_limit"])
    now = datetime.now().isoformat()
    rows = []
    if isinstance(payload, list):
        for item in payload:
            if not isinstance(item, dict):
                continue
            ip = _STATE["normalize_text"](item.get("ip") or item.get("ip_address"))
            if not ip:
                continue
            rows.append({"event_type": "rate_limit", "ip_address": ip, "target_user": _STATE["normalize_text"](item.get("target_user") or item.get("user")), "detail": _STATE["normalize_text"](item.get("detail") or item.get("reason")) or "legacy rate_limit", "created_at": _safe_iso(item.get("created_at") or item.get("ts") or item.get("time"), now)})
    elif isinstance(payload, dict):
        for ip, entry in payload.items():
            if not isinstance(ip, str):
                continue
            if isinstance(entry, dict):
                detail = _STATE["normalize_text"](entry.get("detail") or entry.get("reason") or "legacy rate_limit")
                created_at = _safe_iso(entry.get("created_at") or entry.get("ts") or entry.get("time"), now)
            else:
                detail = "legacy rate_limit"
                created_at = now
            rows.append({"event_type": "rate_limit", "ip_address": ip, "target_user": "", "detail": detail, "created_at": created_at})
    return rows


def _migrate_legacy_audit_rows():
    if not os.path.exists(_STATE["legacy_audit_log"]):
        return []
    rows = []
    with open(_STATE["legacy_audit_log"], "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except Exception:
                continue
            if not isinstance(obj, dict):
                continue
            rows.append({
                "action": _STATE["normalize_text"](obj.get("action", "legacy_audit")),
                "ip": _STATE["normalize_text"](obj.get("ip")),
                "user": _STATE["normalize_text"](obj.get("user")),
                "success": 1 if bool(obj.get("success")) else 0,
                "ua": _STATE["normalize_text"](obj.get("ua")),
                "detail": _STATE["normalize_text"](obj.get("detail")),
                "ts": _safe_iso(obj.get("ts"), datetime.now().isoformat()),
            })
    return rows


def migrate_legacy_json_artifacts(conn):
    summary = {"security_events_imported": 0, "secure_audit_imported": 0, "settings_imported": 0}

    _STATE["init_system_settings_table"](conn)
    existing_settings = {r["key"] for r in conn.execute("SELECT key FROM system_settings").fetchall()}
    before_settings = len(existing_settings)
    if len(existing_settings) < len(_STATE["default_settings"]):
        _STATE["import_legacy_settings_files"](conn)
        _STATE["seed_missing_settings"](conn)
        conn.commit()
        after_settings = {r["key"] for r in conn.execute("SELECT key FROM system_settings").fetchall()}
        summary["settings_imported"] = max(0, len(after_settings) - before_settings)

    has_security_rows = conn.execute("SELECT 1 FROM security_events LIMIT 1").fetchone()
    if not has_security_rows:
        security_rows = []
        security_rows.extend(_migrate_legacy_fail_log_rows())
        security_rows.extend(_migrate_legacy_blocked_ip_rows())
        security_rows.extend(_migrate_legacy_rate_limit_rows())
        security_rows.sort(key=lambda item: item.get("created_at", ""))
        for row in security_rows:
            conn.execute(
                "INSERT INTO security_events (event_type, ip_address, target_user, detail, created_at) VALUES (?, ?, ?, ?, ?)",
                (row["event_type"], row["ip_address"], row["target_user"], row["detail"], row["created_at"])
            )
        summary["security_events_imported"] = len(security_rows)

    has_audit_rows = conn.execute("SELECT 1 FROM secure_audit LIMIT 1").fetchone()
    if not has_audit_rows:
        prev_hash = _STATE["chain_seed"]
        for row in _migrate_legacy_audit_rows():
            entry = {
                "ts": row["ts"], "action": row["action"], "ip": row["ip"],
                "user": row["user"], "success": bool(row["success"]), "ua": row["ua"], "detail": row["detail"],
            }
            entry_json = json.dumps(entry, ensure_ascii=False)
            chain_hash = _STATE["chain_hash"](prev_hash, entry_json)
            conn.execute(
                "INSERT INTO secure_audit (ts, action, ip, user, success, ua, detail, chain_hash) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (row["ts"], row["action"], row["ip"] or "-", row["user"] or "-", 1 if bool(row["success"]) else 0, row["ua"] or "-", row["detail"] or "-", chain_hash)
            )
            prev_hash = chain_hash
            summary["secure_audit_imported"] += 1

    _STATE["seed_missing_settings"](conn)
    conn.commit()
    return summary


def migrate_legacy_json_to_db():
    conn = _STATE["get_db"]()
    try:
        _STATE["init_system_settings_table"](conn)
        summary = migrate_legacy_json_artifacts(conn)
        _STATE["refresh_system_settings"]()
        return summary
    finally:
        conn.close()


def ensure_schema_migrations_table(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version     INTEGER PRIMARY KEY,
            name        TEXT NOT NULL,
            applied_at  TEXT NOT NULL
        )
    """)


def get_schema_version(conn):
    ensure_schema_migrations_table(conn)
    try:
        row = conn.execute("SELECT MAX(version) as v FROM schema_migrations").fetchone()
        return int(row["v"]) if row and row["v"] is not None else 0
    except Exception:
        return 0


def apply_schema_migrations(conn, ensure_secure_audit_columns, ensure_user_columns, ensure_appeal_columns):
    current = get_schema_version(conn)
    if current >= CURRENT_SCHEMA_VERSION:
        return {"previous": current, "applied": [], "current": current}

    applied = []
    for version, name in SCHEMA_MIGRATIONS:
        if version <= current:
            continue
        if version == 1:
            pass
        elif version == 2:
            ensure_secure_audit_columns(conn)
            ensure_user_columns(conn)
        elif version == 3:
            ensure_appeal_columns(conn)
        elif version == 4:
            _STATE["init_system_settings_table"](conn)
            _STATE["seed_missing_settings"](conn)

        conn.execute(
            "INSERT OR REPLACE INTO schema_migrations (version, name, applied_at) VALUES (?, ?, ?)",
            (version, name, datetime.now().isoformat())
        )
        applied.append(version)

    return {"previous": current, "applied": applied, "current": max(current, applied[-1] if applied else current)}


def init_db(*, ensure_secure_audit_columns, ensure_user_columns, ensure_appeal_columns, ensure_official_chat_room, hash_password):
    conn = _STATE["get_db"]()
    schema_path = _STATE.get("schema_path") or (_STATE["db_path"] + '.schema.sql')
    conn.executescript(open(schema_path, 'r', encoding='utf-8').read())
    ensure_secure_audit_columns(conn)
    ensure_user_columns(conn)
    ensure_appeal_columns(conn)
    _STATE["init_system_settings_table"](conn)
    _STATE["seed_missing_settings"](conn)
    migration_plan = apply_schema_migrations(conn, ensure_secure_audit_columns, ensure_user_columns, ensure_appeal_columns)
    conn.commit()
    if migration_plan["applied"]:
        _STATE["audit"]("DB_SCHEMA_MIGRATION", "127.0.0.1", user="system", detail=f"schema migrated from v{migration_plan['previous']} to v{migration_plan['current']}")

    migration_summary = migrate_legacy_json_artifacts(conn)
    if migration_summary["settings_imported"] or migration_summary["security_events_imported"] or migration_summary["secure_audit_imported"]:
        _STATE["audit"]("DB_MIGRATION_APPLIED", "127.0.0.1", user="system", detail=str(migration_summary))

    try:
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(users)").fetchall()}
        if "role" not in cols:
            conn.execute("ALTER TABLE users ADD COLUMN role TEXT NOT NULL DEFAULT 'user'")
    except Exception:
        pass
    conn.execute("UPDATE users SET role='user' WHERE role IS NULL OR role=''")

    now = datetime.now().isoformat()
    root_row = conn.execute("SELECT id FROM users WHERE username='root'").fetchone()
    if root_row:
        root_id = root_row["id"]
        conn.execute("UPDATE users SET role='super_admin', status='active', updated_at=? WHERE id=?", (now, root_id))
    else:
        root_cur = conn.execute("INSERT INTO users (username, status, role, created_at, updated_at) VALUES (?, 'active', 'super_admin', ?, ?)", ("root", now, now))
        root_id = root_cur.lastrowid
        conn.execute("INSERT INTO user_passwords (user_id, password_hash, created_at) VALUES (?, ?, ?)", (root_id, hash_password("root"), now))
    has_root_pw = conn.execute("SELECT 1 FROM user_passwords WHERE user_id=? LIMIT 1", (root_id,)).fetchone()
    if not has_root_pw:
        conn.execute("INSERT INTO user_passwords (user_id, password_hash, created_at) VALUES (?, ?, ?)", (root_id, hash_password("root"), now))

    row = conn.execute("SELECT id FROM users WHERE username='admin'").fetchone()
    if row:
        admin_id = row["id"]
        conn.execute("UPDATE users SET role='manager', status='active', updated_at=? WHERE username='admin'", (now,))
    else:
        mgr_cur = conn.execute("INSERT INTO users (username, status, role, created_at, updated_at) VALUES (?, 'active', 'manager', ?, ?)", ("admin", now, now))
        admin_id = mgr_cur.lastrowid
        conn.execute("INSERT INTO user_passwords (user_id, password_hash, created_at) VALUES (?, ?, ?)", (admin_id, hash_password("admin"), now))
    has_admin_pw = conn.execute("SELECT 1 FROM user_passwords WHERE user_id=? LIMIT 1", (admin_id,)).fetchone()
    if not has_admin_pw:
        conn.execute("INSERT INTO user_passwords (user_id, password_hash, created_at) VALUES (?, ?, ?)", (admin_id, hash_password("admin"), now))

    row = conn.execute("SELECT id FROM users WHERE username='test'").fetchone()
    if row:
        test_id = row["id"]
        conn.execute("UPDATE users SET role='user', status='active', updated_at=? WHERE username='test'", (now,))
    else:
        test_cur = conn.execute("INSERT INTO users (username, status, role, created_at, updated_at) VALUES (?, 'active', 'user', ?, ?)", ("test", now, now))
        test_id = test_cur.lastrowid
        conn.execute("INSERT INTO user_passwords (user_id, password_hash, created_at) VALUES (?, ?, ?)", (test_id, hash_password("test"), now))
    has_test_pw = conn.execute("SELECT 1 FROM user_passwords WHERE user_id=? LIMIT 1", (test_id,)).fetchone()
    if not has_test_pw:
        conn.execute("INSERT INTO user_passwords (user_id, password_hash, created_at) VALUES (?, ?, ?)", (test_id, hash_password("test"), now))

    ensure_official_chat_room(conn)
    _STATE["refresh_system_settings"]()
    conn.commit()
    conn.close()
