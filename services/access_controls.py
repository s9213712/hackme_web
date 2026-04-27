import hashlib
import ipaddress
import secrets
from datetime import datetime, timedelta, timezone


BROWSER_UA_MARKERS = (
    "Mozilla/",
    "Chrome/",
    "Safari/",
    "Firefox/",
    "Edg/",
    "OPR/",
)


def parse_ip_whitelist(raw):
    entries = []
    for item in str(raw or "").replace("\n", ",").split(","):
        value = item.strip()
        if value:
            entries.append(value)
    return entries


def client_ip_allowed(ip, whitelist_raw):
    entries = parse_ip_whitelist(whitelist_raw)
    if not entries:
        return False
    try:
        client = ipaddress.ip_address(str(ip or "").strip())
    except ValueError:
        return False
    for entry in entries:
        try:
            if "/" in entry:
                if client in ipaddress.ip_network(entry, strict=False):
                    return True
            elif client == ipaddress.ip_address(entry):
                return True
        except ValueError:
            continue
    return False


def is_browser_user_agent(user_agent):
    ua = str(user_agent or "")
    if not ua or len(ua) > 512:
        return False
    return any(marker in ua for marker in BROWSER_UA_MARKERS)


def generate_maintenance_bypass_token():
    return secrets.token_urlsafe(32)


def maintenance_bypass_expires_at(ttl_minutes=30, now=None):
    try:
        ttl = int(ttl_minutes)
    except Exception:
        ttl = 30
    ttl = max(1, min(ttl, 24 * 60))
    base = now or datetime.now(timezone.utc)
    if base.tzinfo is None:
        base = base.replace(tzinfo=timezone.utc)
    return (base + timedelta(minutes=ttl)).isoformat()


def hash_maintenance_bypass_token(token):
    token = str(token or "").strip()
    if not token:
        return ""
    return hashlib.sha256(f"maintenance-bypass-v1:{token}".encode("utf-8")).hexdigest()


def _parse_datetime(value):
    if not value:
        return None
    try:
        text = str(value).strip()
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        parsed = datetime.fromisoformat(text)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed
    except Exception:
        return None


def maintenance_bypass_token_is_expired(expires_at, now=None):
    expires = _parse_datetime(expires_at)
    if not expires:
        return True
    base = now or datetime.now(timezone.utc)
    if base.tzinfo is None:
        base = base.replace(tzinfo=timezone.utc)
    return base >= expires


def verify_maintenance_bypass_token(token, stored_hash, expires_at=None, now=None):
    expected = str(stored_hash or "").strip()
    if not expected:
        return False
    if expires_at is not None and maintenance_bypass_token_is_expired(expires_at, now=now):
        return False
    provided = hash_maintenance_bypass_token(token)
    return bool(provided and secrets.compare_digest(provided, expected))


def maintenance_bypass_required_payload(message):
    return {
        "ok": False,
        "msg": message,
        "requires": "maintenance_bypass_token",
        "header": "X-Maintenance-Bypass-Token",
    }


def access_control_settings_payload(settings):
    settings = dict(settings or {})
    return {
        "root_ip_whitelist_enabled": bool(settings.get("root_ip_whitelist_enabled", False)),
        "root_ip_whitelist": settings.get("root_ip_whitelist", ""),
        "browser_only_mode_enabled": bool(settings.get("browser_only_mode_enabled", False)),
        "maintenance_bypass_token_configured": bool(settings.get("maintenance_bypass_token_hash")),
        "maintenance_bypass_token_expires_at": settings.get("maintenance_bypass_token_expires_at") or "",
        "maintenance_bypass_token_expired": maintenance_bypass_token_is_expired(settings.get("maintenance_bypass_token_expires_at")) if settings.get("maintenance_bypass_token_hash") else False,
    }
