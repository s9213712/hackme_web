from __future__ import annotations

import json
import os
import threading
import time
import uuid
from datetime import datetime

from services.core.progress_backend import (
    DEFAULT_PROGRESS_TTL_SECONDS,
    get_progress_backend,
    progress_backend_status,
)


JOB_STATUSES = {
    "queued",
    "running",
    "waiting_external",
    "paused",
    "succeeded",
    "failed",
    "cancelled",
    "retry_wait",
    "expired",
}

TERMINAL_JOB_STATUSES = {"succeeded", "failed", "cancelled", "expired"}
_JOB_PROGRESS_NAMESPACE = "job_center:jobs"
_JOB_PROGRESS_EVENT_NAMESPACE = "job_center:events"
_JOB_PROGRESS_FLUSH_STATE = {}
_JOB_PROGRESS_EVENT_FLUSH_STATE = {}
_JOB_PROGRESS_LOCK = threading.RLock()
_JOB_CENTER_SCHEMA_READY = set()
_JOB_CENTER_SCHEMA_LOCK = threading.RLock()


def _env_bool(name, default=False):
    raw = os.environ.get(name)
    if raw is None:
        return bool(default)
    return str(raw).strip().lower() in {"1", "true", "yes", "on", "y", "t"}


def _env_float(name, default, *, minimum=0.0, maximum=3600.0):
    try:
        value = float(str(os.environ.get(name, default)).strip())
    except Exception:
        value = float(default)
    return max(float(minimum), min(float(maximum), value))


def _progress_buffer_enabled():
    return _env_bool("HACKME_JOB_PROGRESS_BUFFER_ENABLED", True)


def _progress_flush_interval_seconds():
    return _env_float("HACKME_JOB_PROGRESS_FLUSH_INTERVAL_SECONDS", 1.5, minimum=0.0, maximum=60.0)


def _progress_event_flush_interval_seconds():
    return _env_float("HACKME_JOB_PROGRESS_EVENT_FLUSH_INTERVAL_SECONDS", 5.0, minimum=0.0, maximum=300.0)


def job_progress_buffer_status():
    payload = progress_backend_status()
    payload.update(
        {
            "enabled": _progress_buffer_enabled(),
            "flush_interval_seconds": _progress_flush_interval_seconds(),
            "event_flush_interval_seconds": _progress_event_flush_interval_seconds(),
        }
    )
    return payload


def reset_job_progress_buffer_for_tests():
    with _JOB_PROGRESS_LOCK:
        _JOB_PROGRESS_FLUSH_STATE.clear()
        _JOB_PROGRESS_EVENT_FLUSH_STATE.clear()
    with _JOB_CENTER_SCHEMA_LOCK:
        _JOB_CENTER_SCHEMA_READY.clear()


def _job_notification_payload(job):
    status = str((job or {}).get("status") or "")
    title = str((job or {}).get("title") or "平台任務")
    if status == "succeeded":
        return {
            "type": "job_succeeded",
            "title": "任務已完成",
            "body": f"{title} 已完成。",
            "severity": "success",
        }
    if status == "failed":
        error = str((job or {}).get("error_message") or "").strip()
        return {
            "type": "job_failed",
            "title": "任務失敗",
            "body": f"{title} 失敗" + (f"：{error}" if error else "。"),
            "severity": "error",
        }
    if status == "cancelled":
        return {
            "type": "job_cancelled",
            "title": "任務已取消",
            "body": f"{title} 已取消。",
            "severity": "warning",
        }
    if status == "expired":
        return {
            "type": "job_expired",
            "title": "任務已逾時",
            "body": f"{title} 已逾時。",
            "severity": "warning",
        }
    return None


def _maybe_create_terminal_notification(conn, job, *, previous_status=None):
    if not job:
        return False
    status = str(job.get("status") or "")
    if status not in TERMINAL_JOB_STATUSES or previous_status == status:
        return False
    user_id = job.get("owner_user_id")
    if not user_id:
        return False
    payload = _job_notification_payload(job)
    if not payload:
        return False
    try:
        from services.system.notifications import (
            create_notification,
            ensure_notifications_schema,
            notification_type_is_muted,
            notifications_enabled,
        )

        if not notifications_enabled(default=True) or notification_type_is_muted(payload["type"]):
            return False
        ensure_notifications_schema(conn)
        exists = conn.execute(
            """
            SELECT id FROM notifications
            WHERE user_id=? AND type=? AND source_module='job_center' AND source_ref=?
            LIMIT 1
            """,
            (int(user_id), payload["type"], str(job.get("job_uuid") or "")),
        ).fetchone()
        if exists:
            return False
        create_notification(
            conn,
            user_id=int(user_id),
            type=payload["type"],
            title=payload["title"],
            body=payload["body"],
            link="#jobs",
            severity=payload["severity"],
            audience="user",
            source_module="job_center",
            source_ref=str(job.get("job_uuid") or ""),
            metadata_json=_json({
                "job_uuid": job.get("job_uuid"),
                "job_type": job.get("job_type"),
                "source_module": job.get("source_module"),
                "source_ref": job.get("source_ref"),
                "status": status,
            }),
        )
        return True
    except Exception:
        # Job Center is auxiliary. Notification failure must not break the job
        # lifecycle or background workers.
        return False


def utc_now():
    return datetime.utcnow().replace(microsecond=0).isoformat()


def _json(data):
    return json.dumps(data or {}, ensure_ascii=False, sort_keys=True)


def _json_load(raw):
    try:
        value = json.loads(raw) if raw else {}
    except Exception:
        value = {}
    return value if isinstance(value, dict) else {}


def _safe_int(value, default=0):
    try:
        return int(value)
    except Exception:
        return default


def _progress_ttl_seconds():
    return max(
        60,
        _safe_int(os.environ.get("HACKME_JOB_PROGRESS_CACHE_TTL_SECONDS"), DEFAULT_PROGRESS_TTL_SECONDS),
    )


def _normalize_progress(value):
    return max(0, min(100, _safe_int(value, 0)))


def _event_is_terminal(event_type, progress_percent=None):
    event_type = str(event_type or "").strip().lower()
    if event_type in {"created", "completed", "succeeded", "failed", "cancelled", "expired", "retry_requested"}:
        return True
    return progress_percent is not None and _normalize_progress(progress_percent) >= 100


def _cache_put(namespace, key, payload):
    if not _progress_buffer_enabled():
        return False
    try:
        return get_progress_backend().put(namespace, str(key), payload or {}, ttl_seconds=_progress_ttl_seconds())
    except Exception:
        return False


def _cache_get(namespace, key):
    if not _progress_buffer_enabled():
        return None
    try:
        return get_progress_backend().get(namespace, str(key))
    except Exception:
        return None


def _cache_delete(namespace, key):
    try:
        return get_progress_backend().delete(namespace, str(key))
    except Exception:
        return False


def _deserialize_cached_job_payload(payload):
    if not isinstance(payload, dict):
        return None
    job_uuid = str(payload.get("job_uuid") or "").strip()
    if not job_uuid:
        return None
    data = dict(payload)
    data["progress_percent"] = _normalize_progress(data.get("progress_percent", 0))
    data["retry_count"] = _safe_int(data.get("retry_count"), 0)
    data["max_retries"] = _safe_int(data.get("max_retries"), 0)
    data["cancellable"] = bool(data.get("cancellable"))
    data.setdefault("result", {})
    data.setdefault("metadata", {})
    return data


def _cached_job(job_uuid):
    return _deserialize_cached_job_payload(_cache_get(_JOB_PROGRESS_NAMESPACE, str(job_uuid)))


def _merge_cached_job(job):
    if not job:
        return job
    if str(job.get("status") or "") in TERMINAL_JOB_STATUSES:
        return job
    cached = _cached_job(job.get("job_uuid"))
    if not cached:
        return job
    merged = dict(job)
    merged.update(cached)
    return merged


def _cache_job_snapshot(snapshot):
    snapshot = _deserialize_cached_job_payload(snapshot)
    if not snapshot:
        return False
    return _cache_put(_JOB_PROGRESS_NAMESPACE, snapshot["job_uuid"], snapshot)


def _delete_cached_job(job_uuid):
    _cache_delete(_JOB_PROGRESS_NAMESPACE, str(job_uuid))
    _cache_delete(_JOB_PROGRESS_EVENT_NAMESPACE, str(job_uuid))


def _cached_event(job_uuid):
    payload = _cache_get(_JOB_PROGRESS_EVENT_NAMESPACE, str(job_uuid))
    return dict(payload) if isinstance(payload, dict) else None


def _cache_event(job_uuid, event):
    if not isinstance(event, dict):
        return False
    return _cache_put(_JOB_PROGRESS_EVENT_NAMESPACE, str(job_uuid), event)


def _mark_job_progress_flushed(job_uuid):
    with _JOB_PROGRESS_LOCK:
        _JOB_PROGRESS_FLUSH_STATE[str(job_uuid)] = time.monotonic()


def _mark_job_event_flushed(job_uuid):
    with _JOB_PROGRESS_LOCK:
        _JOB_PROGRESS_EVENT_FLUSH_STATE[str(job_uuid)] = time.monotonic()


def _job_progress_flush_due(job_uuid):
    interval = _progress_flush_interval_seconds()
    if interval <= 0:
        return True
    with _JOB_PROGRESS_LOCK:
        last = _JOB_PROGRESS_FLUSH_STATE.get(str(job_uuid))
    return last is None or (time.monotonic() - float(last)) >= interval


def _job_event_flush_due(job_uuid):
    interval = _progress_event_flush_interval_seconds()
    if interval <= 0:
        return True
    with _JOB_PROGRESS_LOCK:
        last = _JOB_PROGRESS_EVENT_FLUSH_STATE.get(str(job_uuid))
    return last is None or (time.monotonic() - float(last)) >= interval


def _snapshot_from_update(previous, normalized_updates):
    if not previous:
        return None
    snapshot = dict(previous)
    for key, value in normalized_updates.items():
        if key == "metadata_json":
            snapshot["metadata"] = _json_load(value)
            continue
        if key == "result_json":
            snapshot["result"] = _json_load(value)
            continue
        if key == "progress_percent":
            snapshot[key] = _normalize_progress(value)
            continue
        if key == "cancellable":
            snapshot[key] = bool(value)
            continue
        snapshot[key] = value
    snapshot["updated_at"] = utc_now()
    return snapshot


def _update_should_write_db(job_uuid, previous, normalized_updates, *, defer_progress=False, flush=False):
    if flush or not defer_progress or not _progress_buffer_enabled():
        return True
    if not normalized_updates:
        return True
    next_status = normalized_updates.get("status")
    if next_status in TERMINAL_JOB_STATUSES:
        return True
    if normalized_updates.get("finished_at") or normalized_updates.get("cancel_requested_at"):
        return True
    if normalized_updates.get("error_code") or normalized_updates.get("error_message") or normalized_updates.get("error_stage"):
        return True
    if normalized_updates.get("result_json") not in (None, "", "{}"):
        return True
    previous_status = str((previous or {}).get("status") or "")
    if next_status and previous_status and str(next_status) != previous_status:
        return True
    if not any(key in normalized_updates for key in ("status", "progress_percent", "stage", "stage_detail", "metadata_json", "started_at", "cancellable")):
        return True
    return _job_progress_flush_due(job_uuid)


def _schema_cache_key(conn):
    try:
        rows = conn.execute("PRAGMA database_list").fetchall()
        for row in rows:
            try:
                name = row["name"]
                file_path = row["file"]
            except Exception:
                name = row[1]
                file_path = row[2]
            if name == "main" and file_path:
                return f"path:{file_path}"
    except Exception:
        pass
    return f"conn:{id(conn)}"


def ensure_job_center_schema(conn):
    cache_key = _schema_cache_key(conn)
    if cache_key in _JOB_CENTER_SCHEMA_READY:
        return
    with _JOB_CENTER_SCHEMA_LOCK:
        if cache_key in _JOB_CENTER_SCHEMA_READY:
            return
        _ensure_job_center_schema_uncached(conn)
        _JOB_CENTER_SCHEMA_READY.add(cache_key)


def _ensure_job_center_schema_uncached(conn):
    was_in_transaction = bool(getattr(conn, "in_transaction", False))
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS job_center_jobs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_uuid TEXT NOT NULL UNIQUE,
            owner_user_id INTEGER,
            created_by_user_id INTEGER,
            job_type TEXT NOT NULL,
            title TEXT NOT NULL,
            description TEXT,
            source_module TEXT NOT NULL,
            source_ref TEXT,
            status TEXT NOT NULL DEFAULT 'queued',
            progress_percent INTEGER NOT NULL DEFAULT 0,
            stage TEXT NOT NULL DEFAULT 'queued',
            stage_detail TEXT,
            error_code TEXT,
            error_message TEXT,
            error_stage TEXT,
            retry_count INTEGER NOT NULL DEFAULT 0,
            max_retries INTEGER NOT NULL DEFAULT 0,
            cancellable INTEGER NOT NULL DEFAULT 0,
            cancel_requested_at TEXT,
            result_json TEXT,
            metadata_json TEXT,
            created_at TEXT NOT NULL,
            started_at TEXT,
            updated_at TEXT NOT NULL,
            finished_at TEXT,
            expires_at TEXT
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS job_center_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_uuid TEXT NOT NULL,
            event_type TEXT NOT NULL,
            stage TEXT,
            message TEXT,
            progress_percent INTEGER,
            payload_json TEXT,
            created_at TEXT NOT NULL
        )
        """
    )
    cols = {row["name"] for row in conn.execute("PRAGMA table_info(job_center_jobs)").fetchall()}
    additions = {
        "owner_user_id": "INTEGER",
        "created_by_user_id": "INTEGER",
        "description": "TEXT",
        "source_ref": "TEXT",
        "stage_detail": "TEXT",
        "error_code": "TEXT",
        "error_message": "TEXT",
        "error_stage": "TEXT",
        "retry_count": "INTEGER NOT NULL DEFAULT 0",
        "max_retries": "INTEGER NOT NULL DEFAULT 0",
        "cancellable": "INTEGER NOT NULL DEFAULT 0",
        "cancel_requested_at": "TEXT",
        "result_json": "TEXT",
        "metadata_json": "TEXT",
        "started_at": "TEXT",
        "finished_at": "TEXT",
        "expires_at": "TEXT",
    }
    for name, ddl in additions.items():
        if name not in cols:
            conn.execute(f"ALTER TABLE job_center_jobs ADD COLUMN {name} {ddl}")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_job_center_owner_status ON job_center_jobs(owner_user_id, status, updated_at)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_job_center_status_updated ON job_center_jobs(status, updated_at)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_job_center_source ON job_center_jobs(source_module, source_ref)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_job_center_events_job ON job_center_events(job_uuid, created_at)")
    if not was_in_transaction:
        try:
            conn.commit()
        except Exception:
            pass


def serialize_job(row):
    data = dict(row)
    data["progress_percent"] = max(0, min(100, _safe_int(data.get("progress_percent"), 0)))
    data["retry_count"] = _safe_int(data.get("retry_count"), 0)
    data["max_retries"] = _safe_int(data.get("max_retries"), 0)
    data["cancellable"] = bool(data.get("cancellable"))
    for key in ("result_json", "metadata_json"):
        raw = data.get(key)
        data[key.replace("_json", "")] = _json_load(raw)
        data.pop(key, None)
    return data


def serialize_event(row):
    data = dict(row)
    try:
        data["payload"] = json.loads(data.get("payload_json") or "{}")
    except Exception:
        data["payload"] = {}
    data.pop("payload_json", None)
    return data


def create_job(
    conn,
    *,
    owner_user_id=None,
    created_by_user_id=None,
    job_type,
    title,
    description="",
    source_module,
    source_ref=None,
    status="queued",
    progress_percent=0,
    stage="queued",
    stage_detail="",
    max_retries=0,
    cancellable=False,
    metadata=None,
    expires_at=None,
):
    ensure_job_center_schema(conn)
    status = str(status or "queued").strip() or "queued"
    if status not in JOB_STATUSES:
        status = "queued"
    now = utc_now()
    job_uuid = uuid.uuid4().hex
    conn.execute(
        """
        INSERT INTO job_center_jobs (
            job_uuid, owner_user_id, created_by_user_id, job_type, title,
            description, source_module, source_ref, status, progress_percent,
            stage, stage_detail, max_retries, cancellable, metadata_json,
            created_at, updated_at, expires_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            job_uuid,
            owner_user_id,
            created_by_user_id,
            str(job_type or "generic")[:80],
            str(title or "未命名任務")[:160],
            str(description or "")[:1000],
            str(source_module or "system")[:80],
            str(source_ref or "")[:160] or None,
            status,
            max(0, min(100, _safe_int(progress_percent, 0))),
            str(stage or status)[:80],
            str(stage_detail or "")[:1000],
            max(0, _safe_int(max_retries, 0)),
            1 if cancellable else 0,
            _json(metadata),
            now,
            now,
            expires_at,
        ),
    )
    add_job_event(conn, job_uuid, event_type="created", stage=stage or status, message="任務已建立", progress_percent=progress_percent)
    _mark_job_progress_flushed(job_uuid)
    _delete_cached_job(job_uuid)
    return get_job(conn, job_uuid)


def add_job_event(conn, job_uuid, *, event_type, stage=None, message="", progress_percent=None, payload=None, defer_progress=False, flush=False):
    ensure_job_center_schema(conn)
    event_type_value = str(event_type or "event")[:80]
    progress_value = None if progress_percent is None else _normalize_progress(progress_percent)
    event_payload = {
        "job_uuid": str(job_uuid),
        "event_type": event_type_value,
        "stage": str(stage or "")[:80] or None,
        "message": str(message or "")[:1000],
        "progress_percent": progress_value,
        "payload": payload or {},
        "created_at": utc_now(),
    }
    if (
        defer_progress
        and _progress_buffer_enabled()
        and not flush
        and not _event_is_terminal(event_type_value, progress_value)
        and not _job_event_flush_due(job_uuid)
    ):
        _cache_event(job_uuid, event_payload)
        return False
    conn.execute(
        """
        INSERT INTO job_center_events (job_uuid, event_type, stage, message, progress_percent, payload_json, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            event_payload["job_uuid"],
            event_payload["event_type"],
            event_payload["stage"],
            event_payload["message"],
            event_payload["progress_percent"],
            _json(event_payload["payload"]),
            event_payload["created_at"],
        ),
    )
    _mark_job_event_flushed(job_uuid)
    _cache_delete(_JOB_PROGRESS_EVENT_NAMESPACE, str(job_uuid))
    return True


def update_job(conn, job_uuid, *, defer_progress=False, flush=False, **updates):
    ensure_job_center_schema(conn)
    previous = get_job(conn, job_uuid)
    allowed = {
        "status",
        "progress_percent",
        "stage",
        "stage_detail",
        "error_code",
        "error_message",
        "error_stage",
        "retry_count",
        "result_json",
        "metadata_json",
        "started_at",
        "finished_at",
        "expires_at",
        "cancel_requested_at",
        "cancellable",
    }
    fields = []
    values = []
    normalized_updates = {}
    for key, value in updates.items():
        if key not in allowed:
            continue
        if key == "status" and value not in JOB_STATUSES:
            continue
        if key == "progress_percent":
            value = _normalize_progress(value)
        if key in {"result_json", "metadata_json"} and not isinstance(value, str):
            value = _json(value)
        normalized_updates[key] = value
        fields.append(f"{key}=?")
        values.append(value)
    if not fields:
        return previous
    if not _update_should_write_db(
        job_uuid,
        previous,
        normalized_updates,
        defer_progress=defer_progress,
        flush=flush,
    ):
        snapshot = _snapshot_from_update(previous, normalized_updates)
        if snapshot:
            _cache_job_snapshot(snapshot)
            return snapshot
        return previous
    fields.append("updated_at=?")
    values.append(utc_now())
    values.append(str(job_uuid))
    conn.execute(f"UPDATE job_center_jobs SET {', '.join(fields)} WHERE job_uuid=?", tuple(values))
    updated = _get_job_from_db(conn, job_uuid)
    _maybe_create_terminal_notification(
        conn,
        updated,
        previous_status=previous.get("status") if previous else None,
    )
    _mark_job_progress_flushed(job_uuid)
    if updated and updated.get("status") in TERMINAL_JOB_STATUSES:
        _delete_cached_job(job_uuid)
    elif updated:
        _cache_job_snapshot(updated)
    return updated


def get_job(conn, job_uuid):
    return _merge_cached_job(_get_job_from_db(conn, job_uuid))


def _get_job_from_db(conn, job_uuid):
    ensure_job_center_schema(conn)
    row = conn.execute("SELECT * FROM job_center_jobs WHERE job_uuid=?", (str(job_uuid),)).fetchone()
    return serialize_job(row) if row else None


def get_job_by_source(conn, source_module, source_ref):
    ensure_job_center_schema(conn)
    row = conn.execute(
        "SELECT * FROM job_center_jobs WHERE source_module=? AND source_ref=? ORDER BY id DESC LIMIT 1",
        (str(source_module), str(source_ref)),
    ).fetchone()
    return _merge_cached_job(serialize_job(row)) if row else None


def list_jobs(conn, *, user_id=None, include_all=False, status=None, limit=50):
    ensure_job_center_schema(conn)
    where = []
    params = []
    if not include_all:
        where.append("owner_user_id=?")
        params.append(int(user_id))
    if status:
        where.append("status=?")
        params.append(str(status))
    sql_where = "WHERE " + " AND ".join(where) if where else ""
    rows = conn.execute(
        f"SELECT * FROM job_center_jobs {sql_where} ORDER BY updated_at DESC, id DESC LIMIT ?",
        tuple(params + [max(1, min(200, _safe_int(limit, 50)))]),
    ).fetchall()
    return [_merge_cached_job(serialize_job(row)) for row in rows]


def list_job_events(conn, job_uuid, *, limit=100):
    ensure_job_center_schema(conn)
    rows = conn.execute(
        """
        SELECT * FROM job_center_events
        WHERE job_uuid=?
        ORDER BY created_at ASC, id ASC
        LIMIT ?
        """,
        (str(job_uuid), max(1, min(500, _safe_int(limit, 100)))),
    ).fetchall()
    events = [serialize_event(row) for row in rows]
    cached = _cached_event(job_uuid)
    if cached:
        events.append(cached)
    return events


def request_cancel(conn, job_uuid):
    job = update_job(
        conn,
        job_uuid,
        status="cancelled",
        cancel_requested_at=utc_now(),
        stage="cancelled",
        stage_detail="使用者要求取消",
        finished_at=utc_now(),
    )
    if job:
        add_job_event(conn, job_uuid, event_type="cancelled", stage="cancelled", message="任務已取消", progress_percent=job.get("progress_percent", 0))
    return job


def request_retry(conn, job_uuid):
    job = get_job(conn, job_uuid)
    if not job:
        return None
    retry_count = _safe_int(job.get("retry_count"), 0) + 1
    updated = update_job(
        conn,
        job_uuid,
        status="queued",
        retry_count=retry_count,
        stage="queued",
        stage_detail="等待重試",
        error_code=None,
        error_message=None,
        error_stage=None,
        finished_at=None,
    )
    add_job_event(conn, job_uuid, event_type="retry_requested", stage="queued", message="任務已排入重試", progress_percent=updated.get("progress_percent", 0))
    return updated
