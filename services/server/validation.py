"""Validation and payload helpers extracted from ``server.py``."""

from __future__ import annotations

import json
import re
from datetime import datetime

from services.server.request_guards import should_require_password_change_flag


def normalize_text(value):
    return (value or "").strip() if isinstance(value, str) else ""


def parse_birthdate(value):
    if not value:
        return None
    value = str(value).strip()
    try:
        datetime.strptime(value, "%Y-%m-%d")
        return value
    except Exception:
        return None


def parse_positive_int(value, default=None, min_value=1, max_value=None):
    if value is None:
        return default
    if isinstance(value, bool):
        return None
    if isinstance(value, float) and not value.is_integer():
        return None
    if isinstance(value, str):
        value = value.strip()
    try:
        value = int(value)
    except (TypeError, ValueError):
        return None
    if value < min_value:
        return None
    if max_value is not None and value > max_value:
        return None
    return value


def validate_password(password):
    if not isinstance(password, str):
        return False, "密碼格式錯誤"
    if len(password) < 8:
        return False, "密碼至少需要 8 個字元"
    if len(password) > 128:
        return False, "密碼太長（最多 128 字元）"
    if not re.search(r"[A-Z]", password):
        return False, "密碼必須包含大寫字母"
    if not re.search(r"[a-z]", password):
        return False, "密碼必須包含小寫字母"
    if not re.search(r"[!@#$%^&*()_+\-=\[\]{};':\"\\|,.<>\/?]", password):
        return False, "密碼必須包含符號"
    return True, "OK"


def validate_id_number(value):
    if not isinstance(value, str):
        return False
    value = value.strip()
    if not value:
        return False
    return bool(re.fullmatch(r"^[A-Za-z0-9]{5,24}$", value))


def validate_phone(value):
    if not isinstance(value, str):
        return False
    value = value.strip()
    if not value:
        return False
    return bool(re.fullmatch(r"^\+?[0-9][0-9\-]{5,30}$", value))


def user_public_payload(row, *, decrypt_field, role_label, include_sensitive=False):
    if not row:
        return None
    data = dict(row)
    is_special_account = data.get("username") == "root" or data.get("role") in {"super_admin", "manager"}
    is_deleted = str(data.get("status") or "").strip().lower() == "deleted"
    try:
        avatar_crop = json.loads(data.get("avatar_crop_json") or "{}") if data.get("avatar_crop_json") else {}
    except Exception:
        avatar_crop = {}
    payload = {
        "id": data.get("id"),
        "username": data.get("username"),
        "nickname": decrypt_field(data.get("nickname")),
        "email": data.get("email"),
        "status": data.get("status"),
        "role": data.get("role"),
        "member_level": None if (is_special_account or is_deleted) else (data.get("member_level") or "normal"),
        "base_level": None if (is_special_account or is_deleted) else (data.get("base_level") or data.get("member_level") or "normal"),
        "effective_level": None if (is_special_account or is_deleted) else (data.get("effective_level") or data.get("member_level") or "normal"),
        "member_level_label": "已刪除" if is_deleted else ("特殊階級" if is_special_account else (data.get("effective_level") or data.get("member_level") or "normal")),
        "special_account": is_special_account,
        "is_deleted": is_deleted,
        "trust_score": data.get("trust_score") or 0,
        "points": data.get("points") or 0,
        "reputation": data.get("reputation") or 0,
        "violation_score": data.get("violation_score") or data.get("violation_count") or 0,
        "sanction_status": data.get("sanction_status") or "none",
        "sanction_until": data.get("sanction_until"),
        "level_updated_at": data.get("level_updated_at"),
        "level_updated_by": data.get("level_updated_by"),
        "level_update_reason": data.get("level_update_reason"),
        "password_strength_score": data.get("password_strength_score") or 0,
        "must_change_password": should_require_password_change_flag(data.get("must_change_password")),
        "is_default_password": bool(data.get("is_default_password") or 0),
        "avatar_file_id": data.get("avatar_file_id"),
        "avatar_crop": avatar_crop if isinstance(avatar_crop, dict) else {},
        "role_label": role_label.get(data.get("role"), data.get("role")),
        "blocked_until": data.get("blocked_until"),
        "violation_count": data.get("violation_count") or 0,
    }
    if include_sensitive:
        payload.update(
            {
                "real_name": decrypt_field(data.get("real_name")),
                "birthdate": decrypt_field(data.get("birthdate")),
                "id_number": decrypt_field(data.get("id_number")),
                "phone": decrypt_field(data.get("phone")),
            }
        )
    else:
        payload.update(
            {
                "real_name": "",
                "birthdate": "",
                "id_number": "",
                "phone": "",
            }
        )
    return payload
