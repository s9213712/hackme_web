"""Security/runtime helpers extracted from ``server.py``."""

from __future__ import annotations

import hashlib
import json
import urllib.parse
from datetime import datetime, timedelta
from ipaddress import ip_address


def encrypt_field(value, *, fernet):
    if value is None:
        return None
    if not isinstance(value, str):
        value = str(value)
    if value == "":
        return ""
    return fernet.encrypt(value.encode("utf-8")).decode("utf-8")


def decrypt_field(value, *, fernet):
    if value is None or value == "":
        return ""
    if not isinstance(value, str):
        return str(value)
    try:
        return fernet.decrypt(value.encode("utf-8")).decode("utf-8")
    except Exception:
        if value.startswith("gAAAAA"):
            return ""
        return value


def verify_token(token, *, fernet, now_func=datetime.now):
    try:
        data = json.loads(fernet.decrypt(token.encode()).decode())
        if now_func() > datetime.fromisoformat(data["exp"]):
            return None
        return data["user"]
    except Exception:
        return None


def hash_token(token):
    return hashlib.sha256(token.encode()).hexdigest()


def get_client_ip(request_obj, *, use_xff, trusted_proxy_ips):
    remote = request_obj.remote_addr or ""
    try:
        remote = str(ip_address(remote))
    except Exception:
        remote = "0.0.0.0"

    if not use_xff or not trusted_proxy_ips:
        return remote

    xff = request_obj.headers.get("X-Forwarded-For", "")
    if xff and remote in trusted_proxy_ips:
        parts = [p.strip() for p in xff.split(",") if p.strip()]
        if parts:
            try:
                return str(ip_address(parts[0]))
            except Exception:
                return remote
    return remote


def get_ua(request_obj):
    return request_obj.headers.get("User-Agent", "-")[:200]


def is_audit_chain_enabled(*, get_system_settings):
    return bool(get_system_settings().get("audit_chain_enabled", False))


def reseal_audit_chain_if_required_on_startup(*, get_system_settings, repair_audit_chain, save_settings, audit):
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


def is_ip_blocking_enabled(*, get_system_settings, env_default):
    settings = get_system_settings()
    if "ip_blocking_enabled" in settings:
        return bool(settings.get("ip_blocking_enabled", False))
    return bool(env_default)


def get_request_maintenance_bypass_token(request_obj, *, helper):
    return helper(request_obj)


def has_valid_maintenance_bypass(
    *,
    settings=None,
    get_system_settings,
    request_obj,
    helper,
    verify_maintenance_bypass_token,
):
    settings = settings or get_system_settings()
    return helper(
        settings,
        request_obj=request_obj,
        verify_maintenance_bypass_token=verify_maintenance_bypass_token,
    )


def get_runtime_server_mode(*, get_db):
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


def tester_token_identity_from_request(
    req,
    *,
    get_db,
    ensure_snapshot_schema,
    get_runtime_server_mode_func,
    record_security_event,
    get_client_ip_func,
):
    cache_key = "hackme_web.tester_token_identity"
    if cache_key in req.environ:
        return req.environ[cache_key]
    token = (
        req.headers.get("X-Tester-Token", "")
        or req.headers.get("X-Internal-Test-Token", "")
        or ""
    ).strip()
    auth_header = req.headers.get("Authorization", "")
    if not token and auth_header.lower().startswith("bearer "):
        token = auth_header[7:].strip()
    if not token:
        req.environ[cache_key] = None
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
        record_security_event(
            "permission_denied",
            get_client_ip_func(),
            target_user="-",
            detail=f"tester_token_suspicious_path:path={raw_uri}",
        )
        req.environ[cache_key] = None
        return None
    conn = None
    try:
        conn = get_db()
        ensure_snapshot_schema(conn)
        mode = get_runtime_server_mode_func()
        if mode not in {"test", "internal_test"}:
            req.environ[cache_key] = None
            return None
        token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
        row = conn.execute(
            """
            SELECT t.*, u.username, u.role, u.status
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
            record_security_event(
                "permission_denied",
                get_client_ip_func(),
                target_user=row["username"],
                detail=f"tester_token_root_api:path={path}",
            )
            req.environ[cache_key] = None
            return None
        forbidden_prefixes = (
            "/api/admin/server-mode",
            "/api/admin/snapshots",
            "/api/admin/integrity",
            "/api/admin/settings",
            "/api/admin/features",
        )
        if any(path == prefix or path.startswith(prefix) for prefix in forbidden_prefixes):
            record_security_event(
                "permission_denied",
                get_client_ip_func(),
                target_user=row["username"],
                detail=f"tester_token_forbidden_admin_api:path={path}",
            )
            req.environ[cache_key] = None
            return None
        try:
            allowed_routes = json.loads(row["allowed_routes_json"] or "[]")
        except Exception:
            allowed_routes = []
        if allowed_routes and not any(path == route or path.startswith(str(route).rstrip("/") + "/") for route in allowed_routes):
            record_security_event(
                "permission_denied",
                get_client_ip_func(),
                target_user=row["username"],
                detail=f"tester_token_route_not_allowed:path={path}",
            )
            req.environ[cache_key] = None
            return None
        window_start = (datetime.now() - timedelta(seconds=60)).isoformat()
        recent = conn.execute(
            "SELECT COUNT(*) AS c FROM tester_token_request_log WHERE token_id=? AND created_at>?",
            (row["id"], window_start),
        ).fetchone()
        max_rpm = max(1, int(row["max_requests_per_minute"] or 60))
        if int(recent["c"] or 0) >= max_rpm:
            record_security_event(
                "rate_limited",
                get_client_ip_func(),
                target_user=row["username"],
                detail=f"tester_token_rate_limit:token_id={row['id']}",
            )
            req.environ[cache_key] = None
            return None
        conn.execute(
            "INSERT INTO tester_token_request_log (token_id, route, ip_address, created_at) VALUES (?, ?, ?, ?)",
            (row["id"], path, get_client_ip_func(), datetime.now().isoformat()),
        )
        conn.commit()
        identity = {
            "username": row["username"],
            "tester_id": int(row["tester_user_id"]),
            "actor_role": str(row["role"] or "user").strip() or "user",
        }
        req.environ[cache_key] = identity
        return identity
    except Exception:
        try:
            if conn:
                conn.rollback()
        except Exception:
            pass
        req.environ[cache_key] = None
        return None
    finally:
        if conn:
            conn.close()


def tester_token_username_from_request(
    req,
    *,
    get_db,
    ensure_snapshot_schema,
    get_runtime_server_mode_func,
    record_security_event,
    get_client_ip_func,
):
    identity = tester_token_identity_from_request(
        req,
        get_db=get_db,
        ensure_snapshot_schema=ensure_snapshot_schema,
        get_runtime_server_mode_func=get_runtime_server_mode_func,
        record_security_event=record_security_event,
        get_client_ip_func=get_client_ip_func,
    )
    if not identity:
        return None
    return identity.get("username")


def path_is_root_recovery_allowed_during_lockdown(path, *, helper):
    return helper(path)


def root_ip_is_allowed(*, settings=None, get_system_settings, get_client_ip_func, helper, client_ip_allowed):
    settings = settings or get_system_settings()
    return helper(settings, get_client_ip=get_client_ip_func, client_ip_allowed=client_ip_allowed)


def feature_gate_for_path(path, *, helper):
    return helper(path)
