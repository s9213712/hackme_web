import os
from ipaddress import ip_address


DEFAULT_LISTEN_HOST = "0.0.0.0"
DEFAULT_LISTEN_PORT = 5000
LOCALHOST_NAMES = {"localhost"}


def _env_get(env, key, default=""):
    source = env if env is not None else os.environ
    try:
        return source.get(key, default)
    except AttributeError:
        return default


def validate_listen_host(value, *, allow_empty=True):
    text = str(value or "").strip()
    if not text:
        if allow_empty:
            return ""
        return None
    if any(ch in text for ch in ("/", ",", " ", "\t", "\n", "\r")):
        return None
    if text.lower() in LOCALHOST_NAMES:
        return "localhost"
    try:
        return str(ip_address(text))
    except ValueError:
        return None


def validate_listen_port(value, *, allow_empty=True):
    if value in (None, ""):
        if allow_empty:
            return 0
        return None
    try:
        port = int(value)
    except Exception:
        return None
    if port == 0 and allow_empty:
        return 0
    if 1 <= port <= 65535:
        return port
    return None


def effective_server_bind(settings=None, env=None):
    settings = dict(settings or {})
    configured_host = validate_listen_host(settings.get("server_listen_host", ""), allow_empty=True)
    configured_port = validate_listen_port(settings.get("server_listen_port", 0), allow_empty=True)

    env_host = validate_listen_host(_env_get(env, "HTML_LEARNING_HOST", DEFAULT_LISTEN_HOST), allow_empty=False) or DEFAULT_LISTEN_HOST
    env_port = validate_listen_port(_env_get(env, "HTML_LEARNING_PORT", DEFAULT_LISTEN_PORT), allow_empty=False) or DEFAULT_LISTEN_PORT

    return {
        "host": configured_host or env_host,
        "port": configured_port or env_port,
        "configured_host": configured_host or "",
        "configured_port": configured_port or 0,
        "host_source": "settings" if configured_host else "env",
        "port_source": "settings" if configured_port else "env",
        "env_host": env_host,
        "env_port": env_port,
    }


def server_bind_settings_payload(settings=None, *, current_host=None, current_port=None, env=None):
    bind = effective_server_bind(settings=settings, env=env)
    current = {
        "host": current_host or bind["host"],
        "port": int(current_port or bind["port"]),
    }
    return {
        **bind,
        "current_host": current["host"],
        "current_port": current["port"],
        "restart_required": current["host"] != bind["host"] or current["port"] != bind["port"],
    }
