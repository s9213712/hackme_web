import sqlite3
from datetime import datetime, timezone

from flask import Flask, jsonify, make_response

from routes.jobs import register_job_routes
from services.job_center import (
    create_job,
    dismiss_job,
    ensure_job_center_schema,
    expire_stale_cloud_remote_download_jobs,
    expire_stale_resumable_upload_jobs,
    list_job_events,
    list_jobs,
    purge_terminal_jobs,
    request_cancel,
    request_retry,
    update_job,
)


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

    dismissed = dismiss_job(conn, job["job_uuid"], actor_user_id=1)
    assert dismissed["dismissed_at"]
    assert dismissed["dismissed_by_user_id"] == 1
    assert list_jobs(conn, user_id=1) == []
    events = conn.execute(
        "SELECT event_type FROM job_center_events WHERE job_uuid=? ORDER BY id",
        (job["job_uuid"],),
    ).fetchall()
    assert [row["event_type"] for row in events][-1] == "dismissed"


def test_stale_cloud_remote_download_jobs_are_marked_failed():
    conn = connection()
    conn.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, username TEXT)")
    conn.execute("INSERT INTO users (id, username) VALUES (1, 'alice')")
    ensure_job_center_schema(conn)
    stale = create_job(
        conn,
        owner_user_id=1,
        created_by_user_id=1,
        job_type="cloud_drive.remote_download.bt.magnet",
        title="BT 下載",
        source_module="cloud_drive_remote_download",
        source_ref="remote_download:stale",
        status="running",
        stage="downloading",
        metadata={"task_id": "stale", "source_type": "magnet", "timeout_seconds": 1800},
        cancellable=True,
    )
    paused = create_job(
        conn,
        owner_user_id=1,
        created_by_user_id=1,
        job_type="cloud_drive.remote_download.bt.magnet",
        title="BT 暫停",
        source_module="cloud_drive_remote_download",
        source_ref="remote_download:paused",
        status="paused",
        stage="paused",
        metadata={"task_id": "paused", "source_type": "magnet", "timeout_seconds": 1800},
        cancellable=True,
    )
    conn.execute(
        "UPDATE job_center_jobs SET created_at='2026-05-01T00:00:00', updated_at='2026-05-01T00:00:00' WHERE job_uuid IN (?, ?)",
        (stale["job_uuid"], paused["job_uuid"]),
    )
    conn.commit()

    expired = expire_stale_cloud_remote_download_jobs(conn)
    conn.commit()

    assert [job["job_uuid"] for job in expired] == [stale["job_uuid"]]
    stale_row = conn.execute("SELECT status, error_code, finished_at FROM job_center_jobs WHERE job_uuid=?", (stale["job_uuid"],)).fetchone()
    paused_row = conn.execute("SELECT status, finished_at FROM job_center_jobs WHERE job_uuid=?", (paused["job_uuid"],)).fetchone()
    assert stale_row["status"] == "failed"
    assert stale_row["error_code"] == "remote_download_task_stale"
    assert stale_row["finished_at"]
    assert paused_row["status"] == "paused"
    assert paused_row["finished_at"] is None


def test_cancel_requested_remote_download_jobs_are_resolved_cancelled():
    conn = connection()
    conn.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, username TEXT)")
    conn.execute("INSERT INTO users (id, username) VALUES (1, 'alice')")
    ensure_job_center_schema(conn)
    job = create_job(
        conn,
        owner_user_id=1,
        created_by_user_id=1,
        job_type="cloud_drive.remote_download.bt.magnet",
        title="BT 取消中",
        source_module="cloud_drive_remote_download",
        source_ref="remote_download:cancel-me",
        status="running",
        stage="cancel_requested",
        metadata={
            "task_id": "cancel-me",
            "source_type": "magnet",
            "timeout_seconds": 1800,
            "control_action": "cancel",
        },
        cancellable=True,
    )
    conn.execute(
        """
        UPDATE job_center_jobs
        SET updated_at='2026-05-01T00:00:00',
            cancel_requested_at='2026-05-01T00:00:00'
        WHERE job_uuid=?
        """,
        (job["job_uuid"],),
    )
    conn.commit()

    expired = expire_stale_cloud_remote_download_jobs(conn)
    conn.commit()

    assert [item["job_uuid"] for item in expired] == [job["job_uuid"]]
    row = conn.execute(
        "SELECT status, stage, finished_at, error_code FROM job_center_jobs WHERE job_uuid=?",
        (job["job_uuid"],),
    ).fetchone()
    events = conn.execute(
        "SELECT event_type FROM job_center_events WHERE job_uuid=? ORDER BY id",
        (job["job_uuid"],),
    ).fetchall()
    assert row["status"] == "cancelled"
    assert row["stage"] == "cancelled"
    assert row["finished_at"]
    assert row["error_code"] is None
    assert [event["event_type"] for event in events][-1] == "cancelled"


def test_stale_empty_resumable_upload_jobs_are_expired(monkeypatch):
    conn = connection()
    conn.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, username TEXT)")
    conn.execute("INSERT INTO users (id, username) VALUES (1, 'alice')")
    conn.execute(
        """
        CREATE TABLE cloud_resumable_upload_sessions (
            session_id TEXT PRIMARY KEY,
            status TEXT NOT NULL,
            error_message TEXT,
            updated_at TEXT
        )
        """
    )
    ensure_job_center_schema(conn)
    monkeypatch.setenv("HACKME_RESUMABLE_UPLOAD_EMPTY_STALE_SECONDS", "60")
    monkeypatch.setenv("HACKME_RESUMABLE_UPLOAD_STALE_SECONDS", str(31 * 24 * 60 * 60))
    stale = create_job(
        conn,
        owner_user_id=1,
        created_by_user_id=1,
        job_type="cloud_drive.resumable_upload",
        title="分段上傳：stale.bin",
        source_module="cloud_drive_resumable_upload",
        source_ref="upload_session:stale-session",
        status="running",
        stage="created",
        metadata={"session_id": "stale-session", "filename": "stale.bin", "received_bytes": 0, "total_bytes": 1024},
    )
    active = create_job(
        conn,
        owner_user_id=1,
        created_by_user_id=1,
        job_type="cloud_drive.resumable_upload",
        title="分段上傳：active.bin",
        source_module="cloud_drive_resumable_upload",
        source_ref="upload_session:active-session",
        status="running",
        stage="uploading",
        metadata={"session_id": "active-session", "filename": "active.bin", "received_bytes": 512, "total_bytes": 1024},
    )
    conn.execute(
        "INSERT INTO cloud_resumable_upload_sessions (session_id, status, updated_at) VALUES ('stale-session', 'created', '2026-05-01T00:00:00')"
    )
    conn.execute(
        "INSERT INTO cloud_resumable_upload_sessions (session_id, status, updated_at) VALUES ('active-session', 'uploading', '2026-05-01T00:00:00')"
    )
    conn.execute(
        "UPDATE job_center_jobs SET created_at='2026-05-01T00:00:00', updated_at='2026-05-01T00:00:00' WHERE job_uuid IN (?, ?)",
        (stale["job_uuid"], active["job_uuid"]),
    )
    conn.commit()

    expired = expire_stale_resumable_upload_jobs(conn)
    conn.commit()

    assert [item["job_uuid"] for item in expired] == [stale["job_uuid"]]
    stale_job = conn.execute("SELECT status, error_code, finished_at FROM job_center_jobs WHERE job_uuid=?", (stale["job_uuid"],)).fetchone()
    active_job = conn.execute("SELECT status, finished_at FROM job_center_jobs WHERE job_uuid=?", (active["job_uuid"],)).fetchone()
    stale_session = conn.execute("SELECT status, error_message FROM cloud_resumable_upload_sessions WHERE session_id='stale-session'").fetchone()
    active_session = conn.execute("SELECT status FROM cloud_resumable_upload_sessions WHERE session_id='active-session'").fetchone()
    events = conn.execute("SELECT event_type FROM job_center_events WHERE job_uuid=? ORDER BY id", (stale["job_uuid"],)).fetchall()
    assert stale_job["status"] == "expired"
    assert stale_job["error_code"] == "resumable_upload_stale"
    assert stale_job["finished_at"]
    assert stale_session["status"] == "expired"
    assert stale_session["error_message"]
    assert active_job["status"] == "running"
    assert active_job["finished_at"] is None
    assert active_session["status"] == "uploading"
    assert [event["event_type"] for event in events][-1] == "expired"


def test_terminal_jobs_are_purged_after_retention(monkeypatch):
    conn = connection()
    conn.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, username TEXT)")
    conn.execute("INSERT INTO users (id, username) VALUES (1, 'alice')")
    ensure_job_center_schema(conn)
    monkeypatch.setenv("HACKME_JOB_CENTER_SUCCEEDED_RETENTION_SECONDS", "60")
    monkeypatch.setenv("HACKME_JOB_CENTER_FAILED_RETENTION_SECONDS", "3600")
    done = create_job(
        conn,
        owner_user_id=1,
        created_by_user_id=1,
        job_type="storage.upload",
        title="done",
        source_module="cloud_drive_upload",
        status="succeeded",
    )
    failed = create_job(
        conn,
        owner_user_id=1,
        created_by_user_id=1,
        job_type="storage.upload",
        title="failed",
        source_module="cloud_drive_upload",
        status="failed",
    )
    running = create_job(
        conn,
        owner_user_id=1,
        created_by_user_id=1,
        job_type="storage.upload",
        title="running",
        source_module="cloud_drive_upload",
        status="running",
    )
    conn.execute(
        """
        UPDATE job_center_jobs
        SET finished_at='2026-05-01T00:00:00', updated_at='2026-05-01T00:00:00'
        WHERE job_uuid IN (?, ?)
        """,
        (done["job_uuid"], failed["job_uuid"]),
    )
    conn.execute(
        "UPDATE job_center_jobs SET updated_at='2026-05-01T00:00:00' WHERE job_uuid=?",
        (running["job_uuid"],),
    )
    conn.commit()

    purged = purge_terminal_jobs(conn, now=datetime(2026, 5, 1, 0, 2, 0, tzinfo=timezone.utc))
    conn.commit()

    assert [item["job_uuid"] for item in purged] == [done["job_uuid"]]
    assert conn.execute("SELECT 1 FROM job_center_jobs WHERE job_uuid=?", (done["job_uuid"],)).fetchone() is None
    assert conn.execute("SELECT 1 FROM job_center_events WHERE job_uuid=?", (done["job_uuid"],)).fetchone() is None
    assert conn.execute("SELECT status FROM job_center_jobs WHERE job_uuid=?", (failed["job_uuid"],)).fetchone()["status"] == "failed"
    assert conn.execute("SELECT status FROM job_center_jobs WHERE job_uuid=?", (running["job_uuid"],)).fetchone()["status"] == "running"


def test_terminal_job_purge_handles_legacy_local_naive_finished_at():
    conn = connection()
    conn.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, username TEXT)")
    conn.execute("INSERT INTO users (id, username) VALUES (1, 'alice')")
    ensure_job_center_schema(conn)
    job = create_job(
        conn,
        owner_user_id=1,
        created_by_user_id=1,
        job_type="video.upload",
        title="legacy local finished job",
        source_module="video_upload_publish",
        status="succeeded",
    )
    conn.execute(
        """
        UPDATE job_center_jobs
        SET finished_at='2026-05-26T16:29:06', updated_at='2026-05-26T08:29:06'
        WHERE job_uuid=?
        """,
        (job["job_uuid"],),
    )
    conn.commit()

    purged = purge_terminal_jobs(conn, now=datetime(2026, 5, 26, 9, 31, 0, tzinfo=timezone.utc))
    conn.commit()

    assert [item["job_uuid"] for item in purged] == [job["job_uuid"]]
    assert conn.execute("SELECT 1 FROM job_center_jobs WHERE job_uuid=?", (job["job_uuid"],)).fetchone() is None


def test_job_routes_are_owner_scoped_for_manager(tmp_path):
    db_path = tmp_path / "jobs.db"
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, username TEXT, role TEXT)")
    conn.executemany(
        "INSERT INTO users (id, username, role) VALUES (?, ?, ?)",
        [(1, "alice", "user"), (2, "admin", "manager"), (3, "root", "super_admin")],
    )
    ensure_job_center_schema(conn)
    job = create_job(
        conn,
        owner_user_id=1,
        created_by_user_id=1,
        job_type="comfyui.generate",
        title="Alice private job",
        source_module="comfyui",
        cancellable=True,
    )
    conn.commit()
    conn.close()

    actor_box = {"actor": {"id": 2, "username": "admin", "role": "manager"}}

    def get_db():
        db = sqlite3.connect(db_path)
        db.row_factory = sqlite3.Row
        return db

    def json_resp(payload, status=200):
        return make_response(jsonify(payload), status)

    app = Flask(__name__)
    app.testing = True
    register_job_routes(app, {
        "audit": lambda *args, **kwargs: None,
        "get_client_ip": lambda: "127.0.0.1",
        "get_current_user_ctx": lambda: actor_box["actor"],
        "get_db": get_db,
        "get_ua": lambda: "test-agent",
        "json_resp": json_resp,
        "parse_positive_int": lambda value, default=50, min_value=1, max_value=200: default,
        "require_csrf": lambda fn: fn,
        "require_csrf_safe": lambda fn: fn,
        "role_rank": lambda role: {"user": 0, "manager": 1, "super_admin": 2}.get(role or "user", 0),
    })
    client = app.test_client()

    admin_list = client.get("/api/admin/jobs")
    assert admin_list.status_code == 403

    detail = client.get(f"/api/jobs/{job['job_uuid']}")
    assert detail.status_code == 404

    cancel = client.post(f"/api/jobs/{job['job_uuid']}/cancel")
    assert cancel.status_code == 404

    actor_box["actor"] = {"id": 1, "username": "alice", "role": "user"}
    owner_detail = client.get(f"/api/jobs/{job['job_uuid']}")
    assert owner_detail.status_code == 200


def test_job_route_can_dismiss_terminal_owner_job(tmp_path):
    db_path = tmp_path / "jobs.db"
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, username TEXT, role TEXT)")
    conn.execute("INSERT INTO users (id, username, role) VALUES (1, 'alice', 'user')")
    ensure_job_center_schema(conn)
    job = create_job(
        conn,
        owner_user_id=1,
        created_by_user_id=1,
        job_type="cloud_drive.upload",
        title="雲端硬碟上傳",
        source_module="cloud_drive_upload",
    )
    job = update_job(conn, job["job_uuid"], status="succeeded", progress_percent=100, stage="completed")
    active = create_job(
        conn,
        owner_user_id=1,
        created_by_user_id=1,
        job_type="cloud_drive.remote_download",
        title="下載中",
        source_module="cloud_drive_remote_download",
        status="running",
        cancellable=True,
    )
    conn.commit()
    conn.close()

    def get_db():
        db = sqlite3.connect(db_path)
        db.row_factory = sqlite3.Row
        return db

    def json_resp(payload, status=200):
        return make_response(jsonify(payload), status)

    app = Flask(__name__)
    app.testing = True
    register_job_routes(app, {
        "audit": lambda *args, **kwargs: None,
        "get_client_ip": lambda: "127.0.0.1",
        "get_current_user_ctx": lambda: {"id": 1, "username": "alice", "role": "user"},
        "get_db": get_db,
        "get_ua": lambda: "test-agent",
        "json_resp": json_resp,
        "parse_positive_int": lambda value, default=50, min_value=1, max_value=200: default,
        "require_csrf": lambda fn: fn,
        "require_csrf_safe": lambda fn: fn,
        "role_rank": lambda role: {"user": 0, "manager": 1, "super_admin": 2}.get(role or "user", 0),
    })
    client = app.test_client()

    denied = client.delete(f"/api/jobs/{active['job_uuid']}")
    assert denied.status_code == 409

    response = client.delete(f"/api/jobs/{job['job_uuid']}")
    assert response.status_code == 200
    assert response.get_json()["msg"] == "任務已從列表移除"

    listing = client.get("/api/jobs")
    assert [item["job_uuid"] for item in listing.get_json()["jobs"]] == [active["job_uuid"]]

    conn = get_db()
    row = conn.execute("SELECT dismissed_at, dismissed_by_user_id FROM job_center_jobs WHERE job_uuid=?", (job["job_uuid"],)).fetchone()
    conn.close()
    assert row["dismissed_at"]
    assert row["dismissed_by_user_id"] == 1


def test_job_retry_uses_registered_source_handler(tmp_path):
    db_path = tmp_path / "jobs.db"
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, username TEXT, role TEXT)")
    conn.execute("INSERT INTO users (id, username, role) VALUES (1, 'alice', 'user')")
    ensure_job_center_schema(conn)
    job = create_job(
        conn,
        owner_user_id=1,
        created_by_user_id=1,
        job_type="video.hls.prepare",
        title="HLS 處理",
        source_module="media_hls_prepare",
        source_ref="media_stream:file-a",
        metadata={"file_id": "file-a"},
    )
    job = update_job(conn, job["job_uuid"], status="failed", progress_percent=100, error_message="ffprobe failed", stage="failed")
    conn.commit()
    conn.close()

    def get_db():
        db = sqlite3.connect(db_path)
        db.row_factory = sqlite3.Row
        return db

    def json_resp(payload, status=200):
        return make_response(jsonify(payload), status)

    calls = []

    def retry_handler(*, conn, actor, job):
        calls.append({"status": job["status"], "retry_count": job["retry_count"], "actor": actor["username"]})
        return {"ok": True, "job": job, "msg": "source handler retried"}

    app = Flask(__name__)
    app.testing = True
    app.extensions.setdefault("hackme_job_retry_handlers", {})["media_hls_prepare"] = retry_handler
    register_job_routes(app, {
        "audit": lambda *args, **kwargs: None,
        "get_client_ip": lambda: "127.0.0.1",
        "get_current_user_ctx": lambda: {"id": 1, "username": "alice", "role": "user"},
        "get_db": get_db,
        "get_ua": lambda: "test-agent",
        "json_resp": json_resp,
        "parse_positive_int": lambda value, default=50, min_value=1, max_value=200: default,
        "require_csrf": lambda fn: fn,
        "require_csrf_safe": lambda fn: fn,
        "role_rank": lambda role: {"user": 0, "manager": 1, "super_admin": 2}.get(role or "user", 0),
    })
    client = app.test_client()

    response = client.post(f"/api/jobs/{job['job_uuid']}/retry")
    assert response.status_code == 200
    assert response.get_json()["msg"] == "source handler retried"
    assert calls == [{"status": "queued", "retry_count": 1, "actor": "alice"}]

    conn = get_db()
    stored = conn.execute("SELECT status, retry_count, error_message FROM job_center_jobs WHERE job_uuid=?", (job["job_uuid"],)).fetchone()
    conn.close()
    assert stored["status"] == "queued"
    assert stored["retry_count"] == 1
    assert stored["error_message"] is None
