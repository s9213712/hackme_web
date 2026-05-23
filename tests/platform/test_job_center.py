import sqlite3

from flask import Flask, jsonify, make_response

from routes.jobs import register_job_routes
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
