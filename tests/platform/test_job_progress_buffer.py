import sqlite3

from services.core.progress_backend import get_progress_backend, reset_progress_backend_for_tests
from services.job_center import (
    add_job_event,
    create_job,
    ensure_job_center_schema,
    get_job,
    list_job_events,
    reset_job_progress_buffer_for_tests,
    update_job,
)


def connection():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    return conn


def reset_progress_state(monkeypatch, *, backend="memory", cache_dir=None):
    monkeypatch.setenv("HACKME_JOB_PROGRESS_BACKEND", backend)
    monkeypatch.setenv("HACKME_JOB_PROGRESS_BUFFER_ENABLED", "1")
    monkeypatch.setenv("HACKME_JOB_PROGRESS_FLUSH_INTERVAL_SECONDS", "60")
    monkeypatch.setenv("HACKME_JOB_PROGRESS_EVENT_FLUSH_INTERVAL_SECONDS", "60")
    if cache_dir is not None:
        monkeypatch.setenv("HACKME_PROGRESS_CACHE_DIR", str(cache_dir))
    reset_progress_backend_for_tests()
    reset_job_progress_buffer_for_tests()


def test_buffered_job_progress_keeps_latest_snapshot_without_db_churn(monkeypatch):
    reset_progress_state(monkeypatch)
    conn = connection()
    ensure_job_center_schema(conn)
    job = create_job(
        conn,
        owner_user_id=1,
        created_by_user_id=1,
        job_type="cloud_drive.remote_download.direct",
        title="download",
        source_module="cloud_drive_remote_download",
        source_ref="remote_download:1",
    )

    update_job(
        conn,
        job["job_uuid"],
        status="running",
        progress_percent=10,
        stage="downloading",
        stage_detail="started",
        defer_progress=True,
    )
    update_job(
        conn,
        job["job_uuid"],
        status="running",
        progress_percent=35,
        stage="downloading",
        stage_detail="chunk 35",
        defer_progress=True,
    )

    stored = conn.execute(
        "SELECT status, progress_percent, stage_detail FROM job_center_jobs WHERE job_uuid=?",
        (job["job_uuid"],),
    ).fetchone()
    assert stored["status"] == "running"
    assert stored["progress_percent"] == 10
    assert stored["stage_detail"] == "started"

    latest = get_job(conn, job["job_uuid"])
    assert latest["progress_percent"] == 35
    assert latest["stage_detail"] == "chunk 35"


def test_buffered_progress_events_are_coalesced_until_flush(monkeypatch):
    reset_progress_state(monkeypatch)
    conn = connection()
    ensure_job_center_schema(conn)
    job = create_job(
        conn,
        owner_user_id=1,
        created_by_user_id=1,
        job_type="cloud_drive.resumable_upload",
        title="upload",
        source_module="cloud_drive_resumable_upload",
        source_ref="upload_session:1",
    )

    wrote = add_job_event(
        conn,
        job["job_uuid"],
        event_type="progress",
        stage="uploading",
        message="35%",
        progress_percent=35,
        payload={"received_bytes": 35},
        defer_progress=True,
    )

    assert wrote is False
    stored_events = conn.execute("SELECT event_type FROM job_center_events WHERE job_uuid=?", (job["job_uuid"],)).fetchall()
    assert [row["event_type"] for row in stored_events] == ["created"]
    events = list_job_events(conn, job["job_uuid"])
    assert events[-1]["event_type"] == "progress"
    assert events[-1]["progress_percent"] == 35


def test_file_progress_backend_is_available_for_cross_process_cache(monkeypatch, tmp_path):
    reset_progress_state(monkeypatch, backend="file", cache_dir=tmp_path)
    backend = get_progress_backend()

    assert backend.status()["backend"] == "file"
    assert backend.put("job_center:jobs", "abc", {"job_uuid": "abc", "progress_percent": 42})
    assert backend.get("job_center:jobs", "abc")["progress_percent"] == 42
    assert backend.delete("job_center:jobs", "abc")
    assert backend.get("job_center:jobs", "abc") is None
