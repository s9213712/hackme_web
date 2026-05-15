import sqlite3
import sys
from pathlib import Path

from flask import Flask, jsonify, make_response

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from routes.share_management import register_share_management_routes
from services.media.videos import ensure_video_schema
from services.share_access_events import log_share_access_event
from services.storage.catalog import ensure_storage_album_schema


def _json_resp(payload, status=200):
    return make_response(jsonify(payload), status)


def _passthrough(fn):
    return fn


def test_share_management_access_events_include_opened_time_and_ip(tmp_path):
    db_path = tmp_path / "shares.db"

    def get_db():
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        return conn

    app = Flask(__name__)
    app.testing = True
    register_share_management_routes(app, {
        "audit": lambda *args, **kwargs: None,
        "get_client_ip": lambda: "127.0.0.1",
        "get_current_user_ctx": lambda: {"id": 1, "username": "alice", "role": "user"},
        "get_db": get_db,
        "get_ua": lambda: "test-agent",
        "json_resp": _json_resp,
        "parse_positive_int": lambda value, default=100, min_value=1, max_value=200: default,
        "require_csrf": _passthrough,
        "require_csrf_safe": _passthrough,
        "role_rank": lambda role: {"user": 0, "manager": 1, "super_admin": 2}.get(role or "user", 0),
    })

    conn = get_db()
    try:
        ensure_storage_album_schema(conn)
        ensure_video_schema(conn)
        conn.execute(
            """
            INSERT INTO storage_share_links (
                id, storage_file_id, file_id, owner_user_id, token_hash, created_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            ("share-1", "storage-file-1", "upload-1", 1, "token-hash-1", "2026-05-11T01:00:00"),
        )
        event = log_share_access_event(
            conn,
            share_type="file",
            share_id="share-1",
            ip="203.0.113.20",
            user_agent="share-test-agent",
        )
        conn.commit()
    finally:
        conn.close()

    response = app.test_client().get("/api/shares/file/share-1/access-events")

    assert response.status_code == 200
    events = response.get_json()["events"]
    opened = next(item for item in events if item["event_type"] == "opened")
    assert opened["opened_at"] == event["created_at"]
    assert opened["created_at"] == event["created_at"]
    assert opened["ip"] == "203.0.113.20"
    assert opened["source_ip"] == "203.0.113.20"
    assert opened["user_agent"] == "share-test-agent"


def test_share_management_is_owner_scoped_even_for_manager(tmp_path):
    db_path = tmp_path / "shares-manager.db"
    actor_box = {"actor": {"id": 4, "username": "admin", "role": "manager"}}

    def get_db():
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        return conn

    app = Flask(__name__)
    app.testing = True
    register_share_management_routes(app, {
        "audit": lambda *args, **kwargs: None,
        "get_client_ip": lambda: "127.0.0.1",
        "get_current_user_ctx": lambda: actor_box["actor"],
        "get_db": get_db,
        "get_ua": lambda: "test-agent",
        "json_resp": _json_resp,
        "parse_positive_int": lambda value, default=100, min_value=1, max_value=200: default,
        "require_csrf": _passthrough,
        "require_csrf_safe": _passthrough,
        "role_rank": lambda role: {"user": 0, "manager": 1, "super_admin": 2}.get(role or "user", 0),
    })

    conn = get_db()
    try:
        ensure_storage_album_schema(conn)
        ensure_video_schema(conn)
        conn.execute(
            """
            INSERT INTO storage_share_links (
                id, storage_file_id, file_id, owner_user_id, token_hash, created_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            ("share-1", "storage-file-1", "upload-1", 1, "token-hash-1", "2026-05-11T01:00:00"),
        )
        conn.execute(
            """
            INSERT INTO video_share_links (
                id, video_id, owner_user_id, token, token_hash, created_by, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            ("video-share-1", 1, 1, "video-token", "video-token-hash", 1, "2026-05-11T02:00:00"),
        )
        conn.commit()
    finally:
        conn.close()

    client = app.test_client()
    listed = client.get("/api/shares?limit=120&all=1")
    assert listed.status_code == 200
    assert listed.get_json()["shares"] == []

    revoked = client.post("/api/shares/file/share-1/revoke")
    assert revoked.status_code == 403

    revoked_video = client.post("/api/shares/video/video-share-1/revoke")
    assert revoked_video.status_code == 403

    conn = get_db()
    try:
        storage_row = conn.execute("SELECT revoked_at FROM storage_share_links WHERE id='share-1'").fetchone()
        video_row = conn.execute("SELECT revoked_at FROM video_share_links WHERE id='video-share-1'").fetchone()
        assert storage_row["revoked_at"] is None
        assert video_row["revoked_at"] is None
    finally:
        conn.close()
