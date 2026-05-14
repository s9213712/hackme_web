GLOBAL_CAPACITY_SETTING_KEY = "cloud_drive_global_capacity_limit_mb"
DEFAULT_GLOBAL_CAPACITY_LIMIT_MB = -1
DEFAULT_DISK_TOTAL_RATIO = 0.95
MIB = 1024 * 1024


def parse_global_capacity_limit_mb(value):
    try:
        limit = int(value)
    except Exception as exc:
        raise ValueError("cloud_drive_global_capacity_limit_mb 必須是 -1 或非負整數 MB") from exc
    if limit < -1:
        raise ValueError("cloud_drive_global_capacity_limit_mb 必須是 -1 或非負整數 MB")
    return limit


def _system_settings():
    try:
        from services.platform.settings import get_system_settings

        return get_system_settings() or {}
    except Exception:
        return {}


def configured_global_capacity_limit_mb(settings=None):
    settings = _system_settings() if settings is None else (settings or {})
    return parse_global_capacity_limit_mb(settings.get(GLOBAL_CAPACITY_SETTING_KEY, DEFAULT_GLOBAL_CAPACITY_LIMIT_MB))


def resolve_global_capacity_limit(disk, settings=None):
    limit_mb = configured_global_capacity_limit_mb(settings)
    if limit_mb >= 0:
        limit_bytes = limit_mb * MIB
        source = "root_setting"
    else:
        total_bytes = int((disk or {}).get("total_bytes") or 0)
        limit_bytes = int(total_bytes * DEFAULT_DISK_TOTAL_RATIO) if total_bytes > 0 else None
        source = "disk_total_95_percent"
    return {
        "configured_limit_mb": limit_mb,
        "limit_bytes": limit_bytes,
        "limit_source": source,
        "default_disk_total_ratio": DEFAULT_DISK_TOTAL_RATIO,
    }
