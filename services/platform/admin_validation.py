from __future__ import annotations

import ipaddress
import os
import re
from pathlib import Path


COMFYUI_HOST_RE = re.compile(r"^[A-Za-z0-9_.:-]+$")
GIT_BRANCH_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,119}$")


def parse_strict_bool(value):
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and value in (0, 1):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on", "y", "t"}:
            return True
        if normalized in {"0", "false", "no", "off", "n", "f"}:
            return False
    return None


def parse_int_in_range(value, minimum, maximum):
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        parsed = value
    elif isinstance(value, float):
        if not value.is_integer():
            return None
        parsed = int(value)
    elif isinstance(value, str) and re.fullmatch(r"-?\d+", value.strip()):
        parsed = int(value.strip())
    else:
        return None
    if parsed < minimum or parsed > maximum:
        return None
    return parsed


def is_hhmm(value):
    text = str(value or "").strip()
    return bool(re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", text))


def normalize_ip_whitelist_or_none(raw):
    entries = []
    bad = []
    for item in str(raw or "").replace("\n", ",").split(","):
        value = item.strip()
        if not value:
            continue
        try:
            if "/" in value:
                ipaddress.ip_network(value, strict=False)
            else:
                ipaddress.ip_address(value)
            entries.append(value)
        except ValueError:
            bad.append(value)
    if bad:
        return None, bad
    return ",".join(entries), []


def feature_dependency_error_payload(violations):
    first = violations[0]
    missing_labels = "、".join(item["required_label"] for item in violations)
    return {
        "ok": False,
        "msg": f"{first['feature_label']} 需要先啟用：{missing_labels}",
        "violations": violations,
    }


def public_relative_path(path, base_dir):
    if not path:
        return "-"
    try:
        base = os.path.abspath(base_dir)
        target = os.path.abspath(path)
        rel = os.path.relpath(target, base)
        if rel == ".":
            return "."
        if rel.startswith(".."):
            return f"<outside>/{os.path.basename(target) or 'path'}"
        return rel.replace("\\", "/")
    except Exception:
        return os.path.basename(str(path)) or "-"


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


def validate_comfyui_api_url(value, *, allow_blank=True, return_error=False):
    from urllib.parse import urlparse

    # 這個 helper 同時服務兩種舊契約：
    # 1. system_admin 設定頁允許把 remote API URL 清空，表示改回 local host/port 模式。
    # 2. routes/comfyui.py 需要保留原本可讀的錯誤訊息分支，而不是把所有 invalid URL
    #    都壓成同一個 generic message。
    raw = str(value or "").strip().rstrip("/")
    if not raw:
        if return_error:
            return ("" if allow_blank else None), ("blank" if not allow_blank else None)
        return "" if allow_blank else None
    parsed = urlparse(raw)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return (None, "shape") if return_error else None
    if parsed.username or parsed.password:
        return (None, "credentials") if return_error else None
    if parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
        return (None, "path") if return_error else None
    return (raw, None) if return_error else raw


def validate_comfyui_relative_script(value, *, base_dir=None):
    raw = str(value or "").strip()
    if not raw:
        return ""
    if len(raw) > 240:
        return None
    try:
        # 允許 root 從本機檔案選擇器帶絕對路徑，但儲存時一定要轉成 base dir
        # 內的相對路徑，避免把維運者工作站路徑寫進設定。
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


def validate_git_branch_name(value):
    branch = str(value or "").strip()
    if not branch or branch in {"HEAD", ".", ".."}:
        return None
    if branch.startswith("/") or branch.endswith("/") or ".." in branch or branch.endswith(".lock"):
        return None
    if not GIT_BRANCH_RE.match(branch):
        return None
    return branch
