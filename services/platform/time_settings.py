import re
import time
from datetime import datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


DEFAULT_SERVER_TIMEZONE = "UTC"

COMMON_SERVER_TIMEZONES = (
    "UTC",
    "Asia/Taipei",
    "Asia/Tokyo",
    "Asia/Seoul",
    "Asia/Shanghai",
    "Asia/Hong_Kong",
    "Asia/Singapore",
    "America/Los_Angeles",
    "America/Denver",
    "America/Chicago",
    "America/New_York",
    "Europe/London",
    "Europe/Paris",
    "Europe/Berlin",
    "Australia/Sydney",
)


def normalize_server_timezone(value, *, default=DEFAULT_SERVER_TIMEZONE):
    name = str(value or "").strip() or default
    if name.lower() in {"z", "utc"}:
        name = "UTC"
    if len(name) > 80 or not re.fullmatch(r"[A-Za-z0-9_./+-]+", name):
        return None
    try:
        ZoneInfo(name)
    except ZoneInfoNotFoundError:
        return None
    return name


def _offset_label(offset_minutes):
    sign = "+" if offset_minutes >= 0 else "-"
    minutes = abs(int(offset_minutes))
    hours, mins = divmod(minutes, 60)
    return f"UTC{sign}{hours:02d}:{mins:02d}"


def utc_iso(dt):
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def server_time_payload(settings=None, *, now=None):
    settings = settings or {}
    timezone_name = normalize_server_timezone(settings.get("server_timezone"))
    if not timezone_name:
        timezone_name = DEFAULT_SERVER_TIMEZONE
    zone = ZoneInfo(timezone_name)
    now_utc = now or datetime.now(timezone.utc)
    if now_utc.tzinfo is None:
        now_utc = now_utc.replace(tzinfo=timezone.utc)
    now_utc = now_utc.astimezone(timezone.utc)
    local_time = now_utc.astimezone(zone)
    offset = local_time.utcoffset()
    offset_minutes = int((offset.total_seconds() if offset else 0) // 60)
    system_local_time = datetime.now().astimezone()
    system_tz = system_local_time.tzname() or (time.tzname[0] if time.tzname else "")
    return {
        "timezone": timezone_name,
        "timezone_valid": True,
        "server_time_utc": utc_iso(now_utc),
        "server_time_local": local_time.isoformat(timespec="seconds"),
        "server_time_unix_ms": int(now_utc.timestamp() * 1000),
        "utc_offset_minutes": offset_minutes,
        "utc_offset_label": _offset_label(offset_minutes),
        "time_source": "system_clock",
        "system_timezone": system_tz,
        "system_time_local": system_local_time.isoformat(timespec="seconds"),
    }
