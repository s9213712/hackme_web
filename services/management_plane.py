from __future__ import annotations

import json
import logging
import os
import threading
import time
from datetime import datetime, timezone
from typing import Any, Callable

try:
    import fcntl
except Exception:  # pragma: no cover - non-Unix fallback
    fcntl = None

from services.job_center import (
    add_job_event,
    create_job,
    get_job,
    get_job_by_source,
    update_job,
    utc_now,
)


MANAGEMENT_PLANE_SOURCE_MODULE = "management_plane"
_LOGGER = logging.getLogger(__name__)


def _json_dumps(payload: Any) -> str:
    return json.dumps(payload if payload is not None else {}, ensure_ascii=False, sort_keys=True)


def _json_loads(raw: str | None) -> dict[str, Any]:
    try:
        value = json.loads(raw or "{}")
    except Exception:
        value = {}
    return value if isinstance(value, dict) else {}


def _safe_json_size(payload: Any) -> int:
    try:
        return len(_json_dumps(payload).encode("utf-8"))
    except Exception:
        return 0


def _compact_result_summary(payload: Any, *, snapshot_key: str) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {
            "ok": True,
            "snapshot_key": snapshot_key,
            "result_type": type(payload).__name__,
            "result_size_bytes": _safe_json_size(payload),
        }
    summary: dict[str, Any] = {
        "ok": bool(payload.get("ok", True)),
        "snapshot_key": snapshot_key,
        "result_size_bytes": _safe_json_size(payload),
    }
    for key in (
        "generated_at",
        "sealed",
        "block",
        "verification",
        "management_timing",
        "refresh",
        "snapshot",
    ):
        value = payload.get(key)
        if key == "verification" and isinstance(value, dict):
            summary[key] = {
                "ok": bool(value.get("ok")),
                "error_count": len(value.get("errors") or []),
                "counts": value.get("counts") or {},
                "verification_mode": value.get("verification_mode"),
                "financial_ok": value.get("financial_ok"),
            }
        elif key == "management_timing" and isinstance(value, dict):
            summary[key] = {
                "total_ms": value.get("total_ms"),
                "phases": value.get("phases") or [],
            }
        elif key in payload:
            summary[key] = value
    return summary


def ensure_management_plane_schema(conn) -> None:
    was_in_transaction = bool(getattr(conn, "in_transaction", False))
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS management_plane_snapshots (
            snapshot_key TEXT PRIMARY KEY,
            payload_json TEXT NOT NULL DEFAULT '{}',
            summary_json TEXT NOT NULL DEFAULT '{}',
            source_job_uuid TEXT,
            generated_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            error TEXT NOT NULL DEFAULT ''
        )
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_management_plane_snapshots_updated
        ON management_plane_snapshots(updated_at)
        """
    )
    if not was_in_transaction:
        try:
            conn.commit()
        except Exception:
            pass


def _main_db_path(conn) -> str:
    try:
        for row in conn.execute("PRAGMA database_list").fetchall():
            try:
                name = row["name"]
                file_path = row["file"]
            except Exception:
                name = row[1]
                file_path = row[2]
            if name == "main" and file_path:
                return str(file_path)
    except Exception:
        pass
    return ""


def _acquire_management_worker_lock(conn):
    if fcntl is None:
        return None
    db_path = _main_db_path(conn)
    lock_dir = os.path.dirname(db_path) if db_path else "/tmp"
    os.makedirs(lock_dir, exist_ok=True)
    lock_path = os.path.join(lock_dir, "management_plane_worker.lock")
    fh = open(lock_path, "a+", encoding="utf-8")
    fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
    return fh


def _release_management_worker_lock(lock_fh) -> None:
    if not lock_fh:
        return
    try:
        if fcntl is not None:
            fcntl.flock(lock_fh.fileno(), fcntl.LOCK_UN)
    finally:
        try:
            lock_fh.close()
        except Exception:
            pass


def write_management_snapshot(
    conn,
    *,
    snapshot_key: str,
    payload: dict[str, Any],
    source_job_uuid: str,
    summary: dict[str, Any] | None = None,
    error: str = "",
) -> dict[str, Any]:
    ensure_management_plane_schema(conn)
    now = utc_now()
    summary_payload = summary if isinstance(summary, dict) else _compact_result_summary(payload, snapshot_key=snapshot_key)
    conn.execute(
        """
        INSERT INTO management_plane_snapshots (
            snapshot_key, payload_json, summary_json, source_job_uuid,
            generated_at, updated_at, error
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(snapshot_key) DO UPDATE SET
            payload_json=excluded.payload_json,
            summary_json=excluded.summary_json,
            source_job_uuid=excluded.source_job_uuid,
            generated_at=excluded.generated_at,
            updated_at=excluded.updated_at,
            error=excluded.error
        """,
        (
            str(snapshot_key),
            _json_dumps(payload),
            _json_dumps(summary_payload),
            str(source_job_uuid or ""),
            now,
            now,
            str(error or "")[:2000],
        ),
    )
    return {
        "snapshot_key": str(snapshot_key),
        "generated_at": now,
        "source_job_uuid": str(source_job_uuid or ""),
        "summary": summary_payload,
        "error": str(error or ""),
    }


def get_management_snapshot(conn, *, snapshot_key: str, include_payload: bool = True) -> dict[str, Any]:
    ensure_management_plane_schema(conn)
    row = conn.execute(
        "SELECT * FROM management_plane_snapshots WHERE snapshot_key=?",
        (str(snapshot_key),),
    ).fetchone()
    if not row:
        return {
            "ok": False,
            "missing": True,
            "snapshot_key": str(snapshot_key),
            "payload": {},
            "summary": {},
            "msg": "management-plane snapshot has not been generated yet",
        }
    payload = _json_loads(row["payload_json"]) if include_payload else {}
    summary = _json_loads(row["summary_json"])
    return {
        "ok": True,
        "missing": False,
        "snapshot_key": row["snapshot_key"],
        "payload": payload,
        "summary": summary,
        "generated_at": row["generated_at"],
        "updated_at": row["updated_at"],
        "source_job_uuid": row["source_job_uuid"],
        "error": row["error"],
    }


def _active_existing_job(conn, *, snapshot_key: str) -> dict[str, Any] | None:
    job = get_job_by_source(conn, MANAGEMENT_PLANE_SOURCE_MODULE, snapshot_key)
    if job and str(job.get("status") or "") in {"queued", "running", "waiting_external", "retry_wait"}:
        metadata = job.get("metadata") if isinstance(job.get("metadata"), dict) else {}
        pid = 0
        try:
            pid = int(metadata.get("worker_pid") or metadata.get("starter_pid") or 0)
        except Exception:
            pid = 0
        if pid > 0 and os.path.exists(f"/proc/{pid}"):
            return job
        try:
            updated = datetime.fromisoformat(str(job.get("updated_at") or ""))
            if updated.tzinfo is not None:
                updated = updated.astimezone(timezone.utc).replace(tzinfo=None)
            if (datetime.utcnow() - updated).total_seconds() <= 10:
                return job
        except Exception:
            pass
    return None


def start_management_plane_job(
    *,
    get_db: Callable[[], Any],
    actor: dict[str, Any] | None,
    job_type: str,
    title: str,
    snapshot_key: str,
    request_payload: dict[str, Any] | None,
    worker: Callable[[Callable[..., None]], dict[str, Any]],
    summary_builder: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
    reuse_running: bool = True,
) -> dict[str, Any]:
    conn = get_db()
    try:
        ensure_management_plane_schema(conn)
        if reuse_running:
            existing = _active_existing_job(conn, snapshot_key=snapshot_key)
            if existing:
                return {"created": False, "job": existing}
        job = create_job(
            conn,
            owner_user_id=(actor or {}).get("id"),
            created_by_user_id=(actor or {}).get("id"),
            job_type=job_type,
            title=title,
            description="Management-plane async job; heavy work runs outside the request path.",
            source_module=MANAGEMENT_PLANE_SOURCE_MODULE,
            source_ref=snapshot_key,
            status="queued",
            progress_percent=0,
            stage="queued",
            max_retries=0,
            cancellable=False,
            metadata={"snapshot_key": snapshot_key, "request": request_payload or {}, "starter_pid": os.getpid()},
        )
        conn.commit()
    finally:
        conn.close()

    thread = threading.Thread(
        target=_run_management_plane_job,
        kwargs={
            "get_db": get_db,
            "job_uuid": job["job_uuid"],
            "snapshot_key": snapshot_key,
            "worker": worker,
            "summary_builder": summary_builder,
        },
        name=f"management-plane-{job['job_uuid'][:8]}",
        daemon=True,
    )
    thread.start()
    return {"created": True, "job": job}


def _run_management_plane_job(
    *,
    get_db: Callable[[], Any],
    job_uuid: str,
    snapshot_key: str,
    worker: Callable[[Callable[..., None]], dict[str, Any]],
    summary_builder: Callable[[dict[str, Any]], dict[str, Any]] | None,
) -> None:
    conn = get_db()
    started = time.perf_counter()
    try:
        update_job(
            conn,
            job_uuid,
            status="running",
            progress_percent=5,
            stage="running",
            stage_detail="management-plane job started",
            started_at=utc_now(),
            metadata_json={"snapshot_key": snapshot_key, "worker_pid": os.getpid()},
        )
        add_job_event(
            conn,
            job_uuid,
            event_type="started",
            stage="running",
            message="management-plane job started",
            progress_percent=5,
        )
        conn.commit()

        def progress(*, stage: str, progress_percent: int, detail: str = "", payload: dict[str, Any] | None = None) -> None:
            update_job(
                conn,
                job_uuid,
                status="running",
                progress_percent=max(1, min(99, int(progress_percent or 1))),
                stage=str(stage or "running")[:80],
                stage_detail=str(detail or "")[:1000],
                metadata_json={
                    "snapshot_key": snapshot_key,
                    "worker_pid": os.getpid(),
                    "last_progress_payload": payload or {},
                },
                defer_progress=True,
            )
            add_job_event(
                conn,
                job_uuid,
                event_type="progress",
                stage=str(stage or "running")[:80],
                message=str(detail or "")[:1000],
                progress_percent=max(1, min(99, int(progress_percent or 1))),
                payload=payload or {},
                defer_progress=True,
            )
            conn.commit()

        progress(stage="waiting_worker_lock", progress_percent=8, detail="waiting for management-plane worker slot")
        lock_fh = None
        try:
            lock_fh = _acquire_management_worker_lock(conn)
            progress(stage="worker_lock_acquired", progress_percent=10, detail="management-plane worker slot acquired")
            result = worker(progress)
        finally:
            _release_management_worker_lock(lock_fh)
        if not isinstance(result, dict):
            result = {"ok": True, "result": result}
        result.setdefault("ok", True)
        result.setdefault("generated_at", utc_now())
        result.setdefault("management_async", True)
        summary = summary_builder(result) if callable(summary_builder) else _compact_result_summary(result, snapshot_key=snapshot_key)
        summary.setdefault("elapsed_ms", round((time.perf_counter() - started) * 1000, 3))
        snapshot = write_management_snapshot(
            conn,
            snapshot_key=snapshot_key,
            payload=result,
            source_job_uuid=job_uuid,
            summary=summary,
        )
        update_job(
            conn,
            job_uuid,
            status="succeeded",
            progress_percent=100,
            stage="succeeded",
            stage_detail="snapshot generated",
            result_json=snapshot["summary"],
            finished_at=utc_now(),
            flush=True,
        )
        add_job_event(
            conn,
            job_uuid,
            event_type="succeeded",
            stage="succeeded",
            message="management-plane snapshot generated",
            progress_percent=100,
            payload=snapshot["summary"],
            flush=True,
        )
        conn.commit()
    except Exception as exc:
        try:
            conn.rollback()
        except Exception:
            pass
        message = str(exc) or exc.__class__.__name__
        try:
            update_job(
                conn,
                job_uuid,
                status="failed",
                progress_percent=100,
                stage="failed",
                stage_detail=message[:1000],
                error_code=exc.__class__.__name__,
                error_message=message[:1000],
                error_stage="management_plane_worker",
                result_json={"ok": False, "snapshot_key": snapshot_key, "error": message[:1000]},
                finished_at=utc_now(),
                flush=True,
            )
            add_job_event(
                conn,
                job_uuid,
                event_type="failed",
                stage="failed",
                message=message[:1000],
                progress_percent=100,
                payload={"snapshot_key": snapshot_key},
                flush=True,
            )
            conn.commit()
        except Exception:
            _LOGGER.exception("failed to mark management-plane job failed: %s", job_uuid)
        _LOGGER.exception("management-plane job failed: %s", job_uuid)
    finally:
        conn.close()


def management_job_start_payload(job: dict[str, Any], *, snapshot_key: str, created: bool) -> dict[str, Any]:
    job_uuid = str(job.get("job_uuid") or "")
    return {
        "ok": True,
        "async": True,
        "accepted": True,
        "created": bool(created),
        "job_id": job_uuid,
        "job_uuid": job_uuid,
        "job": job,
        "snapshot_key": snapshot_key,
        "status_url": f"/api/root/management/jobs/{job_uuid}",
        "latest_snapshot_url": f"/api/root/management/snapshots/{snapshot_key}",
    }
