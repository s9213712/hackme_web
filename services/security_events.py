import sqlite3
import threading
import time
from datetime import datetime, timedelta

_STATE = {
    "get_db": None,
    "get_system_settings": None,
    "audit": None,
    "is_ip_blocking_enabled": None,
}

_RATE_LIMIT_LOCK = threading.Lock()
_RATE_LIMIT_BUCKETS = {}
_USER_RATE_LIMIT_BUCKETS = {}
_CLEANUP_LOCK = threading.Lock()
_LAST_EVENT_CLEANUP_AT = 0.0
_EVENT_RETENTION_DAYS = 7
_EVENT_CLEANUP_INTERVAL_SECONDS = 300
SECURITY_EVENT_TYPES = {
    "login_fail",
    "ip_block",
    "rate_limit",
    "403_access",
    "feature_disabled",
    "csrf_fail",
    "permission_denied",
    "session_revoked",
    "login_location_suspicious",
}


def configure_security_events_service(*, get_db, get_system_settings, audit, is_ip_blocking_enabled):
    _STATE.update({
        "get_db": get_db,
        "get_system_settings": get_system_settings,
        "audit": audit,
        "is_ip_blocking_enabled": is_ip_blocking_enabled,
    })


def _parse_blocked_until(detail):
    if not detail:
        return None
    prefix = "blocked_until="
    if prefix not in detail:
        return None
    raw = detail.split(prefix, 1)[1].strip()
    if " " in raw:
        raw = raw.split(" ", 1)[0]
    try:
        return datetime.fromisoformat(raw)
    except Exception:
        return None


def _maybe_cleanup_old_events():
    global _LAST_EVENT_CLEANUP_AT
    now_monotonic = time.monotonic()
    if now_monotonic - _LAST_EVENT_CLEANUP_AT < _EVENT_CLEANUP_INTERVAL_SECONDS:
        return
    with _CLEANUP_LOCK:
        if now_monotonic - _LAST_EVENT_CLEANUP_AT < _EVENT_CLEANUP_INTERVAL_SECONDS:
            return
        conn = _STATE["get_db"]()
        try:
            cutoff = (datetime.now() - timedelta(days=_EVENT_RETENTION_DAYS)).isoformat()
            now_iso = datetime.now().isoformat()
            try:
                conn.execute("DELETE FROM security_events WHERE created_at<?", (cutoff,))
            except sqlite3.OperationalError:
                return
            try:
                conn.execute("DELETE FROM ip_blocks WHERE blocked_until<?", (now_iso,))
            except Exception:
                pass
            conn.commit()
        finally:
            conn.close()
        _LAST_EVENT_CLEANUP_AT = now_monotonic


def _check_window_limit(bucket, key, *, max_req, window_sec):
    now = time.time()
    cutoff = now - window_sec
    with _RATE_LIMIT_LOCK:
        recent = [ts for ts in bucket.get(key, []) if ts >= cutoff]
        blocked = len(recent) >= max_req
        if not blocked:
            recent.append(now)
        if recent:
            bucket[key] = recent
        else:
            bucket.pop(key, None)
    return blocked, {"count": len(recent), "limit": max_req}


def normalize_security_event_type(event_type):
    event_type = str(event_type or "").strip().lower()
    return event_type if event_type in SECURITY_EVENT_TYPES else "permission_denied"


def record_security_event(event_type, ip, target_user=None, detail="", created_at=None):
    if not callable(_STATE.get("get_db")):
        return
    _maybe_cleanup_old_events()
    conn = _STATE["get_db"]()
    try:
        conn.execute(
            "INSERT INTO security_events (event_type, ip_address, target_user, detail, created_at) VALUES (?, ?, ?, ?, ?)",
            (
                normalize_security_event_type(event_type),
                ip or "-",
                target_user,
                detail or "",
                created_at or datetime.now().isoformat(),
            ),
        )
        conn.commit()
    except sqlite3.OperationalError:
        pass
    finally:
        conn.close()


def is_ip_blocked(ip):
    if not _STATE["is_ip_blocking_enabled"]():
        return False
    if ip == "127.0.0.1" or ip == "::1":
        return False
    _maybe_cleanup_old_events()
    conn = _STATE["get_db"]()
    try:
        row = conn.execute(
            "SELECT blocked_until FROM ip_blocks WHERE ip_address=? LIMIT 1",
            (ip,)
        ).fetchone()
        if row:
            try:
                until = datetime.fromisoformat(row["blocked_until"])
                if datetime.now() < until:
                    return True
                conn.execute("DELETE FROM ip_blocks WHERE ip_address=?", (ip,))
                conn.commit()
                return False
            except Exception:
                conn.execute("DELETE FROM ip_blocks WHERE ip_address=?", (ip,))
                conn.commit()
                return False
        legacy_row = conn.execute(
            "SELECT detail FROM security_events WHERE event_type='ip_block' AND ip_address=? ORDER BY created_at DESC LIMIT 1",
            (ip,)
        ).fetchone()
        if not legacy_row:
            return False
        until = _parse_blocked_until(legacy_row["detail"])
        return bool(until and datetime.now() < until)
    finally:
        conn.close()


def block_ip(ip, minutes=10, reason="multiple failures"):
    if ip == "127.0.0.1" or ip == "::1":
        return
    blocked_until = (datetime.now() + timedelta(minutes=minutes)).isoformat()
    conn = _STATE["get_db"]()
    try:
        conn.execute(
            "INSERT INTO ip_blocks (ip_address, blocked_until, reason, created_at) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(ip_address) DO UPDATE SET blocked_until=excluded.blocked_until, reason=excluded.reason, created_at=excluded.created_at",
            (ip, blocked_until, reason, datetime.now().isoformat())
        )
        conn.commit()
    finally:
        conn.close()
    record_security_event("ip_block", ip, detail=f"blocked_until={blocked_until}")
    _maybe_cleanup_old_events()


def record_login_failure(ip, username="", ua="-", detail="-", lock_on=3):
    settings = _STATE["get_system_settings"]()
    lock_limit = max(1, int(settings.get("max_login_failures", lock_on or 3)))
    block_minutes = max(1, int(settings.get("block_duration_minutes", 10)))
    _maybe_cleanup_old_events()
    conn = _STATE["get_db"]()
    try:
        conn.execute(
            "INSERT INTO security_events (event_type, ip_address, target_user, detail, created_at) VALUES (?, ?, ?, ?, ?)",
            (normalize_security_event_type("login_fail"), ip, username, detail, datetime.now().isoformat())
        )
        since = (datetime.now() - timedelta(minutes=10)).isoformat()
        count = conn.execute(
            "SELECT COUNT(*) as c FROM security_events WHERE event_type='login_fail' AND ip_address=? AND created_at>=?",
            (ip, since)
        ).fetchone()["c"]
        conn.commit()
    finally:
        conn.close()

    _STATE["audit"]("LOGIN_FAIL", ip, username, ua=ua, detail=detail)

    if count >= lock_limit and _STATE["is_ip_blocking_enabled"]():
        block_ip(ip, block_minutes, f"{count} failures → {block_minutes} min block")
        _STATE["audit"]("LOGIN_IP_BLOCKED", ip, username, ua=ua, detail=f"{count} failures → {block_minutes} min block")
    return count


def clear_failed_logins(ip):
    conn = _STATE["get_db"]()
    try:
        conn.execute("DELETE FROM security_events WHERE event_type='login_fail' AND ip_address=?", (ip,))
        conn.commit()
    finally:
        conn.close()


def is_rate_limited(ip, max_req=30, window_sec=60):
    blocked, info = _check_window_limit(_RATE_LIMIT_BUCKETS, str(ip), max_req=max_req, window_sec=window_sec)
    if blocked:
        record_security_event("rate_limit", ip, detail=f"limit={max_req},window={window_sec}")
    return blocked, info


def check_user_rate_limit(user_id, action, max_req=10, window_sec=3600):
    key = (int(user_id), str(action))
    blocked, info = _check_window_limit(_USER_RATE_LIMIT_BUCKETS, key, max_req=max_req, window_sec=window_sec)
    if blocked:
        record_security_event(
            "rate_limit",
            "-",
            target_user=str(user_id),
            detail=f"action={action},limit={max_req},window={window_sec}",
        )
    return blocked, info


def record_403_access(ip, path, username="-"):
    record_security_event("403_access", ip, target_user=username, detail=f"path={path}")
