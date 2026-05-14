import sqlite3

from services.job_center import create_job, ensure_job_center_schema, list_job_events, list_jobs, request_cancel, request_retry, update_job


def connection():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    return conn


def test_job_center_lifecycle():
    conn = connection()
    conn.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, username TEXT)")
    conn.execute("INSERT INTO users (id, username) VALUES (1, 'alice')")
    ensure_job_center_schema(conn)
    job = create_job(
        conn,
        owner_user_id=1,
        created_by_user_id=1,
        job_type="comfyui.generate",
        title="產圖",
        source_module="comfyui",
        progress_percent=25,
        cancellable=True,
    )
    conn.commit()

    assert job["job_uuid"]
    assert job["status"] == "queued"
    assert list_jobs(conn, user_id=1)[0]["title"] == "產圖"
    assert list_jobs(conn, user_id=2) == []
    assert list_job_events(conn, job["job_uuid"])[0]["event_type"] == "created"

    cancelled = request_cancel(conn, job["job_uuid"])
    assert cancelled["status"] == "cancelled"
    notice = conn.execute("SELECT * FROM notifications WHERE source_module='job_center' AND source_ref=?", (job["job_uuid"],)).fetchone()
    assert notice["type"] == "job_cancelled"

    retried = request_retry(conn, job["job_uuid"])
    assert retried["status"] == "queued"
    assert retried["retry_count"] == 1
    failed = update_job(conn, job["job_uuid"], status="failed", error_message="boom", stage="execute", finished_at="2026-05-10T00:00:00")
    assert failed["status"] == "failed"
    rows = conn.execute("SELECT type FROM notifications WHERE source_module='job_center' AND source_ref=? ORDER BY id", (job["job_uuid"],)).fetchall()
    assert [row["type"] for row in rows] == ["job_cancelled", "job_failed"]
