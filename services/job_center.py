from __future__ import annotations

import json
import uuid
from datetime import datetime


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


def _safe_int(value, default=0):
    try:
        return int(value)
    except Exception:
        return default


def ensure_job_center_schema(conn):
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


def serialize_job(row):
    data = dict(row)
    data["progress_percent"] = max(0, min(100, _safe_int(data.get("progress_percent"), 0)))
    data["retry_count"] = _safe_int(data.get("retry_count"), 0)
    data["max_retries"] = _safe_int(data.get("max_retries"), 0)
    data["cancellable"] = bool(data.get("cancellable"))
    for key in ("result_json", "metadata_json"):
        raw = data.get(key)
        try:
            data[key.replace("_json", "")] = json.loads(raw) if raw else {}
        except Exception:
            data[key.replace("_json", "")] = {}
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
    return get_job(conn, job_uuid)


def add_job_event(conn, job_uuid, *, event_type, stage=None, message="", progress_percent=None, payload=None):
    ensure_job_center_schema(conn)
    conn.execute(
        """
        INSERT INTO job_center_events (job_uuid, event_type, stage, message, progress_percent, payload_json, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            str(job_uuid),
            str(event_type or "event")[:80],
            str(stage or "")[:80] or None,
            str(message or "")[:1000],
            None if progress_percent is None else max(0, min(100, _safe_int(progress_percent, 0))),
            _json(payload),
            utc_now(),
        ),
    )


def update_job(conn, job_uuid, **updates):
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
    for key, value in updates.items():
        if key not in allowed:
            continue
        if key == "status" and value not in JOB_STATUSES:
            continue
        if key == "progress_percent":
            value = max(0, min(100, _safe_int(value, 0)))
        if key in {"result_json", "metadata_json"} and not isinstance(value, str):
            value = _json(value)
        fields.append(f"{key}=?")
        values.append(value)
    if not fields:
        return previous
    fields.append("updated_at=?")
    values.append(utc_now())
    values.append(str(job_uuid))
    conn.execute(f"UPDATE job_center_jobs SET {', '.join(fields)} WHERE job_uuid=?", tuple(values))
    updated = get_job(conn, job_uuid)
    _maybe_create_terminal_notification(
        conn,
        updated,
        previous_status=previous.get("status") if previous else None,
    )
    return updated


def get_job(conn, job_uuid):
    ensure_job_center_schema(conn)
    row = conn.execute("SELECT * FROM job_center_jobs WHERE job_uuid=?", (str(job_uuid),)).fetchone()
    return serialize_job(row) if row else None


def get_job_by_source(conn, source_module, source_ref):
    ensure_job_center_schema(conn)
    row = conn.execute(
        "SELECT * FROM job_center_jobs WHERE source_module=? AND source_ref=? ORDER BY id DESC LIMIT 1",
        (str(source_module), str(source_ref)),
    ).fetchone()
    return serialize_job(row) if row else None


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
    return [serialize_job(row) for row in rows]


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
    return [serialize_event(row) for row in rows]


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
