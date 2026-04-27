import hashlib
import ipaddress
import secrets


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


def hash_maintenance_bypass_token(token):
    token = str(token or "").strip()
    if not token:
        return ""
    return hashlib.sha256(f"maintenance-bypass-v1:{token}".encode("utf-8")).hexdigest()


def verify_maintenance_bypass_token(token, stored_hash):
    expected = str(stored_hash or "").strip()
    if not expected:
        return False
    provided = hash_maintenance_bypass_token(token)
    return bool(provided and secrets.compare_digest(provided, expected))


def access_control_settings_payload(settings):
    settings = dict(settings or {})
    return {
        "root_ip_whitelist_enabled": bool(settings.get("root_ip_whitelist_enabled", False)),
        "root_ip_whitelist": settings.get("root_ip_whitelist", ""),
        "browser_only_mode_enabled": bool(settings.get("browser_only_mode_enabled", False)),
        "maintenance_bypass_token_configured": bool(settings.get("maintenance_bypass_token_hash")),
    }
