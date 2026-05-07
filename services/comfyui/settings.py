"""ComfyUI-specific settings defaults and validation helpers.

這一層只放 ComfyUI 專屬設定：
- 預設值
- key 清單
- admin/settings 會共用的驗證 helper

全站的 system settings 儲存、feature flag 與跨模組依賴規則，仍留在
``services.platform.settings``。
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from urllib.parse import urlparse

DEFAULT_COMFYUI_PORT = 8192
DEFAULT_COMFYUI_MAX_BATCH_SIZE = 1
DEFAULT_COMFYUI_WIDTH = 1024
DEFAULT_COMFYUI_HEIGHT = 1024

COMFYUI_DEFAULT_SETTINGS = {
    "comfyui_connection_mode": os.environ.get("COMFYUI_CONNECTION_MODE", "remote"),
    "comfyui_remote_api_url": os.environ.get("COMFYUI_API_URL", ""),
    "comfyui_base_dir": os.environ.get("COMFYUI_BASE_DIR", ""),
    "comfyui_local_start_script": os.environ.get("COMFYUI_START_SCRIPT", ""),
    "comfyui_api_host": os.environ.get("COMFYUI_API_HOST", "localhost"),
    "comfyui_api_port": DEFAULT_COMFYUI_PORT,
    "comfyui_civitai_api_key": os.environ.get("CIVITAI_API_KEY", ""),
    "comfyui_max_batch_size": DEFAULT_COMFYUI_MAX_BATCH_SIZE,
    "comfyui_default_width": DEFAULT_COMFYUI_WIDTH,
    "comfyui_default_height": DEFAULT_COMFYUI_HEIGHT,
}

COMFYUI_SETTING_KEYS = tuple(COMFYUI_DEFAULT_SETTINGS)
COMFYUI_HOST_RE = re.compile(r"^[A-Za-z0-9_.:-]+$")


def normalize_comfyui_connection_mode(value):
    mode = str(value or "").strip().lower()
    if mode in {"local", "remote"}:
        return mode
    return None


def validate_comfyui_api_host(value):
    host = str(value or "").strip().strip("[]")
    if not host:
        return None
    if len(host) > 253:
        return None
    forbidden = ("://", "/", "\\", "@", "?", "#", "%", " ")
    if any(part in host for part in forbidden):
        return None
    if not COMFYUI_HOST_RE.match(host):
        return None
    return host


def validate_comfyui_api_url(value, *, allow_blank=False):
    raw = str(value or "").strip().rstrip("/")
    if not raw:
        return "" if allow_blank else None
    parsed = urlparse(raw)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return None
    if parsed.username or parsed.password:
        return None
    if parsed.port is None:
        return None
    if parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
        return None
    return raw


def validate_comfyui_relative_script(value, *, base_dir=None):
    raw = str(value or "").strip()
    if not raw:
        return ""
    if len(raw) > 240:
        return None
    try:
        if raw.startswith("/") or raw.startswith("\\"):
            if not base_dir:
                return None
            base = Path(str(base_dir)).expanduser().resolve()
            target = Path(raw).expanduser().resolve()
            rel = target.relative_to(base)
            parts = rel.as_posix().split("/")
            if not parts or any(part in {"", ".", ".."} for part in parts):
                return None
            return rel.as_posix()
        parts = raw.replace("\\", "/").split("/")
        if not parts or any(part in {"", ".", ".."} for part in parts):
            return None
        return "/".join(parts)
    except Exception:
        return None


def validate_comfyui_api_port(value):
    try:
        port = int(value)
    except Exception:
        return None
    if port < 1 or port > 65535:
        return None
    return port


def validate_comfyui_batch_size(value):
    try:
        batch_size = int(value)
    except Exception:
        return None
    if batch_size < 1 or batch_size > 8:
        return None
    return batch_size


def validate_comfyui_dimension(value):
    try:
        size = int(value)
    except Exception:
        return None
    if size < 64 or size > 2048 or size % 8 != 0:
        return None
    return size
