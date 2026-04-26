from datetime import datetime, timedelta

_STATE = {
    "get_db": None,
    "get_system_settings": None,
    "audit": None,
    "is_ip_blocking_enabled": None,
}


def configure_security_events_service(*, get_db, get_system_settings, audit, is_ip_blocking_enabled):
    _STATE.update({
        "get_db": get_db,
        "get_system_settings": get_system_settings,
        "audit": audit,
        "is_ip_blocking_enabled": is_ip_blocking_enabled,
    })


def is_ip_blocked(ip):
    if not _STATE["is_ip_blocking_enabled"]():
        return False
    if ip == "127.0.0.1" or ip == "::1":
        return False
    conn = _STATE["get_db"]()
    try:
        row = conn.execute(
            "SELECT detail FROM security_events WHERE event_type='ip_block' AND ip_address=? ORDER BY created_at DESC LIMIT 1",
            (ip,)
        ).fetchone()
        if not row:
            return False
        try:
            until = datetime.fromisoformat(row["detail"].replace("blocked_until=", ""))
            return datetime.now() < until
        except Exception:
            return False
    finally:
        conn.close()


def block_ip(ip, minutes=10, reason="multiple failures"):
    if ip == "127.0.0.1" or ip == "::1":
        return
    blocked_until = (datetime.now() + timedelta(minutes=minutes)).isoformat()
    conn = _STATE["get_db"]()
    try:
        conn.execute(
            "INSERT INTO security_events (event_type, ip_address, detail, created_at) VALUES ('ip_block', ?, ?, ?)",
            (ip, f"blocked_until={blocked_until}", datetime.now().isoformat())
        )
        conn.commit()
    finally:
        conn.close()


def record_login_failure(ip, username="", ua="-", detail="-", lock_on=3):
    settings = _STATE["get_system_settings"]()
    lock_limit = max(1, int(settings.get("max_login_failures", lock_on or 3)))
    block_minutes = max(1, int(settings.get("block_duration_minutes", 10)))
    conn = _STATE["get_db"]()
    try:
        conn.execute(
            "INSERT INTO security_events (event_type, ip_address, target_user, detail, created_at) VALUES ('login_fail', ?, ?, ?, ?)",
            (ip, username, detail, datetime.now().isoformat())
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
    conn = _STATE["get_db"]()
    try:
        since = (datetime.now() - timedelta(seconds=window_sec)).isoformat()
        conn.execute(
            "INSERT INTO security_events (event_type, ip_address, detail, created_at) VALUES ('rate_limit', ?, ?, ?)",
            (ip, f"window={window_sec}s", datetime.now().isoformat())
        )
        count = conn.execute(
            "SELECT COUNT(*) as c FROM security_events WHERE event_type='rate_limit' AND ip_address=? AND created_at>=?",
            (ip, since)
        ).fetchone()["c"]
        conn.commit()
        if count > max_req:
            return True, {"count": count, "limit": max_req}
        return False, {"count": count, "limit": max_req}
    finally:
        conn.close()


def record_403_access(ip, path, username="-"):
    conn = _STATE["get_db"]()
    try:
        conn.execute(
            "INSERT INTO security_events (event_type, ip_address, target_user, detail, created_at) VALUES ('403_access', ?, ?, ?, ?)",
            (ip, username, f"path={path}", datetime.now().isoformat())
        )
        conn.commit()
    finally:
        conn.close()
