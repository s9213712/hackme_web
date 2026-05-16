import hashlib
import ipaddress
import json
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


def generate_internal_test_token():
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


def hash_internal_test_token(token):
    token = str(token or "").strip()
    if not token:
        return ""
    return hashlib.sha256(f"internal-test-login-v1:{token}".encode("utf-8")).hexdigest()


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


def verify_internal_test_token(token, stored_hash, expires_at=None, now=None):
    expected = str(stored_hash or "").strip()
    if not expected:
        return False
    if expires_at is not None and maintenance_bypass_token_is_expired(expires_at, now=now):
        return False
    provided = hash_internal_test_token(token)
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
    bound_user_id = 0
    allowed_features = []
    try:
        bound_user_id = int(settings.get("internal_test_login_token_user_id") or 0)
    except Exception:
        bound_user_id = 0
    try:
        parsed_features = json.loads(str(settings.get("internal_test_login_token_allowed_features_json") or "[]"))
        if isinstance(parsed_features, list):
            allowed_features = [str(item).strip() for item in parsed_features if str(item).strip()]
    except Exception:
        allowed_features = []
    return {
        "root_ip_whitelist_enabled": bool(settings.get("root_ip_whitelist_enabled", False)),
        "root_ip_whitelist": settings.get("root_ip_whitelist", ""),
        "browser_only_mode_enabled": bool(settings.get("browser_only_mode_enabled", False)),
        "maintenance_bypass_token_configured": bool(settings.get("maintenance_bypass_token_hash")),
        "maintenance_bypass_token_expires_at": settings.get("maintenance_bypass_token_expires_at") or "",
        "maintenance_bypass_token_expired": maintenance_bypass_token_is_expired(settings.get("maintenance_bypass_token_expires_at")) if settings.get("maintenance_bypass_token_hash") else False,
        "internal_test_token_configured": bool(settings.get("internal_test_login_token_hash")),
        "internal_test_token_expires_at": settings.get("internal_test_login_token_expires_at") or "",
        "internal_test_token_expired": maintenance_bypass_token_is_expired(settings.get("internal_test_login_token_expires_at")) if settings.get("internal_test_login_token_hash") else False,
        "internal_test_token_user_id": bound_user_id,
        "internal_test_token_username": str(settings.get("internal_test_login_token_username") or "").strip(),
        "internal_test_token_allowed_features": allowed_features,
        "internal_test_token_feature_scope_enabled": bool(allowed_features),
    }
