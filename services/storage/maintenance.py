from datetime import datetime, time, timedelta

from services.storage_albums import ensure_storage_album_schema, sync_user_storage_summary
from services.storage_quota_enforcement import purge_expired_quota_reduction_files


def _parse_daily_time(value):
    try:
        hour, minute = str(value or "04:00").split(":", 1)
        hour = max(0, min(23, int(hour)))
        minute = max(0, min(59, int(minute)))
        return time(hour, minute), f"{hour:02d}:{minute:02d}"
    except Exception:
        return time(4, 0), "04:00"


def storage_maintenance_status(settings, now=None):
    now = now or datetime.now()
    enabled = bool(settings.get("storage_maintenance_auto_enabled", False))
    run_time, normalized = _parse_daily_time(settings.get("storage_maintenance_daily_time"))
    due_at = datetime.combine(now.date(), run_time)
    today = now.date().isoformat()
    last_date = str(settings.get("storage_maintenance_last_date") or "")
    due = enabled and now >= due_at and last_date != today
    return {
        "enabled": enabled,
        "time": normalized,
        "today": today,
        "last_date": last_date,
        "due": due,
        "reason": "due" if due else ("disabled" if not enabled else ("already_ran" if last_date == today else "before_scheduled_time")),
    }


def run_storage_maintenance(conn, *, actor_user_id=None, retention_days=30, now=None):
    now = now or datetime.now()
    ensure_storage_album_schema(conn)
    try:
        retention_days = int(retention_days)
    except Exception:
        retention_days = 30
    retention_days = max(0, min(retention_days, 3650))
    cutoff = (now - timedelta(days=retention_days)).isoformat()
    update_now = now.isoformat()
    purged = conn.execute(
        """
        UPDATE storage_files
        SET deleted_at=?, updated_at=?
        WHERE is_trashed=1 AND deleted_at IS NULL AND trashed_at IS NOT NULL AND trashed_at<=?
        """,
        (update_now, update_now, cutoff),
    ).rowcount
    users = conn.execute("SELECT id FROM users ORDER BY id ASC").fetchall()
    synced = [
        sync_user_storage_summary(
            conn,
            row["id"],
            actor_user_id=actor_user_id,
            source="maintenance",
            reason="storage_maintenance",
        )
        for row in users
    ]
    quota_enforcement = purge_expired_quota_reduction_files(
        conn,
        actor_user_id=actor_user_id,
        now=now,
    )
    return {
        "purged_trash_entries": int(purged or 0),
        "quota_enforcement": quota_enforcement,
        "synced_users": len(synced),
        "retention_days": retention_days,
        "cutoff": cutoff,
    }


def run_storage_maintenance_if_due(conn, *, settings, save_settings=None, actor_user_id=None, now=None, force=False):
    now = now or datetime.now()
    status = storage_maintenance_status(settings, now=now)
    if not force and not status["due"]:
        return {"ok": True, "ran": False, "status": status}
    result = run_storage_maintenance(
        conn,
        actor_user_id=actor_user_id,
        retention_days=settings.get("storage_trash_retention_days", 30),
        now=now,
    )
    if save_settings:
        save_settings({"storage_maintenance_last_date": status["today"]})
    return {"ok": True, "ran": True, "status": status, "result": result}
