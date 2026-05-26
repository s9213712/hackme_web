import sqlite3
import sys
from pathlib import Path
from datetime import datetime, timedelta

from flask import Flask, jsonify, make_response

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from routes.share_management import register_share_management_routes, share_expiry_is_elapsed
from services.media.videos import ensure_video_schema
from services.share_access_events import ensure_share_access_event_schema, log_share_access_event
from services.storage.catalog import ensure_storage_album_schema


def _json_resp(payload, status=200):
    return make_response(jsonify(payload), status)


def _passthrough(fn):
    return fn


def test_share_expiry_elapsed_treats_datetime_local_as_local_time():
    local_now = datetime(2026, 5, 25, 0, 10, 0)

    assert share_expiry_is_elapsed("2026-05-25T00:00", now=local_now) is True
    assert share_expiry_is_elapsed("2026-05-25T00:20", now=local_now) is False


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


def test_video_share_management_timestamps_are_marked_as_utc_for_client(tmp_path):
    db_path = tmp_path / "video-share-timezone.db"

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
        ensure_video_schema(conn)
        ensure_share_access_event_schema(conn)
        conn.execute(
            """
            INSERT INTO videos (
                id, video_uuid, owner_user_id, cloud_file_id, title, description,
                visibility, status, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (1, "video-timezone", 1, "cloud-video-1", "Movie", "", "unlisted", "ready", "2026-05-17T23:17:00", "2026-05-17T23:17:00"),
        )
        conn.execute(
            """
            INSERT INTO video_share_links (
                id, video_id, owner_user_id, token, token_hash, created_by,
                created_at, access_count, last_accessed_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("video-share-timezone", 1, 1, "token-timezone", "hash-timezone", 1, "2026-05-17T23:17:00", 1, "2026-05-17T23:18:00"),
        )
        conn.execute(
            """
            INSERT INTO share_access_events (
                id, share_type, share_id, event_type, ip, user_agent, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            ("event-timezone", "video", "video-share-timezone", "opened", "127.0.0.1", "agent", "2026-05-17T23:18:00"),
        )
        conn.commit()
    finally:
        conn.close()

    listed = app.test_client().get("/api/shares?limit=120")
    assert listed.status_code == 200
    share = listed.get_json()["shares"][0]
    assert share["created_at"] == "2026-05-17T23:17:00Z"
    assert share["last_accessed_at"] == "2026-05-17T23:18:00Z"

    events_response = app.test_client().get("/api/shares/video/video-share-timezone/access-events")
    assert events_response.status_code == 200
    events = events_response.get_json()["events"]
    opened = next(item for item in events if item["event_type"] == "opened")
    accessed = next(item for item in events if item["event_type"] == "accessed")
    created = next(item for item in events if item["event_type"] == "created")
    assert opened["created_at"] == "2026-05-17T23:18:00Z"
    assert accessed["created_at"] == "2026-05-17T23:18:00Z"
    assert created["created_at"] == "2026-05-17T23:17:00Z"


def test_share_management_lists_elapsed_file_share_as_expired(tmp_path):
    db_path = tmp_path / "shares-elapsed-expiry.db"

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

    expired_at = (datetime.now() - timedelta(minutes=1)).replace(microsecond=0).isoformat()
    conn = get_db()
    try:
        ensure_storage_album_schema(conn)
        ensure_video_schema(conn)
        conn.execute(
            """
            INSERT INTO storage_share_links (
                id, storage_file_id, file_id, owner_user_id, token, token_hash,
                can_download, can_preview, access_scope, expires_at, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("share-expired-now", "storage-file-1", "upload-1", 1, "token-expired-now", "token-hash-expired-now", 1, 1, "link", expired_at, "2026-05-11T01:00:00"),
        )
        conn.commit()
    finally:
        conn.close()

    listed = app.test_client().get("/api/shares?limit=120")

    assert listed.status_code == 200
    share = listed.get_json()["shares"][0]
    assert share["status"] == "expired"


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


def test_share_management_can_update_file_share_options(tmp_path):
    db_path = tmp_path / "shares-update.db"

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
            INSERT INTO storage_files (
                id, file_id, owner_user_id, display_name, virtual_path, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            ("storage-file-1", "upload-1", 1, "share-title.txt", "share-title.txt", "2026-05-11T01:00:00", "2026-05-11T01:00:00"),
        )
        conn.execute(
            """
            INSERT INTO storage_share_links (
                id, storage_file_id, file_id, owner_user_id, token, token_hash,
                can_download, can_preview, access_scope, max_views, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("share-1", "storage-file-1", "upload-1", 1, "token-1", "token-hash-1", 1, 1, "link", 0, "2026-05-11T01:00:00"),
        )
        conn.commit()
    finally:
        conn.close()

    response = app.test_client().put(
        "/api/shares/file/share-1",
        json={
            "can_preview": False,
            "can_download": True,
            "access_scope": "link",
            "expires_at": "2026-06-01T12:00",
            "max_views": 7,
        },
    )

    assert response.status_code == 200
    body = response.get_json()
    assert body["ok"] is True
    assert body["share"]["can_preview"] is False
    assert body["share"]["can_download"] is True
    assert body["share"]["expires_at"] == "2026-06-01T12:00"
    assert body["share"]["max_views"] == 7
    assert body["share"]["resource_title"] == "share-title.txt"

    conn = get_db()
    try:
        row = conn.execute("SELECT * FROM storage_share_links WHERE id='share-1'").fetchone()
        assert row["can_preview"] == 0
        assert row["can_download"] == 1
        assert row["max_views"] == 7
    finally:
        conn.close()


def test_share_management_can_update_album_share_options(tmp_path):
    db_path = tmp_path / "album-share-update.db"

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
            INSERT INTO albums (
                id, owner_user_id, title, description, visibility, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            ("album-1", 1, "Trip", "", "unlisted", "2026-05-11T01:00:00", "2026-05-11T01:00:00"),
        )
        conn.execute(
            """
            INSERT INTO album_share_links (
                id, album_id, owner_user_id, token, token_hash, created_by,
                created_at, max_views, access_count, last_accessed_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("album-share-1", "album-1", 1, "album-token", "album-token-hash", 1, "2026-05-11T02:00:00", 2, 2, "2026-05-18T07:18:00"),
        )
        conn.commit()
    finally:
        conn.close()

    response = app.test_client().put(
        "/api/shares/album/album-share-1",
        json={
            "expires_at": "2026-06-01T12:00",
            "max_views": 9,
            "reset_access_count": True,
            "share_password": "AlbumPass123",
        },
    )

    assert response.status_code == 200
    body = response.get_json()
    assert body["ok"] is True
    assert body["share"]["share_type"] == "album"
    assert body["share"]["expires_at"] == "2026-06-01T12:00"
    assert body["share"]["max_views"] == 9
    assert body["share"]["access_count"] == 0
    assert body["share"]["password_required"] is True

    listed = app.test_client().get("/api/shares?limit=120")
    assert listed.status_code == 200
    listed_album = next(item for item in listed.get_json()["shares"] if item["id"] == "album-share-1")
    assert listed_album["resource_title"] == "Trip"
    assert listed_album["expires_at"] == "2026-06-01T12:00"
    assert listed_album["max_views"] == 9

    conn = get_db()
    try:
        row = conn.execute("SELECT * FROM album_share_links WHERE id='album-share-1'").fetchone()
        assert row["access_count"] == 0
        assert row["last_accessed_at"] is None
        assert row["password_required"] == 1
        assert row["expires_at"] == "2026-06-01T12:00"
        assert row["max_views"] == 9
    finally:
        conn.close()


def test_share_management_can_reactivate_expired_file_share(tmp_path):
    db_path = tmp_path / "shares-reactivate-expired.db"

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
                id, storage_file_id, file_id, owner_user_id, token, token_hash,
                can_download, can_preview, access_scope, expires_at, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("share-expired", "storage-file-1", "upload-1", 1, "token-expired", "token-hash-expired", 1, 1, "link", "2000-01-01T00:00:00", "2026-05-11T01:00:00"),
        )
        conn.commit()
    finally:
        conn.close()

    response = app.test_client().put(
        "/api/shares/file/share-expired",
        json={
            "can_preview": True,
            "can_download": True,
            "access_scope": "link",
            "expires_at": "",
            "max_views": 0,
        },
    )

    assert response.status_code == 200
    body = response.get_json()
    assert body["ok"] is True
    assert body["msg"] == "分享設定已更新，分享連結已重新啟用"
    assert body["share"]["status"] == "active"
    assert body["share"]["expires_at"] is None


def test_share_management_can_reactivate_view_limit_file_share(tmp_path):
    db_path = tmp_path / "shares-reactivate-limit.db"

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
                id, storage_file_id, file_id, owner_user_id, token, token_hash,
                can_download, can_preview, access_scope, max_views, access_count, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("share-limit", "storage-file-1", "upload-1", 1, "token-limit", "token-hash-limit", 1, 1, "link", 2, 2, "2026-05-11T01:00:00"),
        )
        conn.commit()
    finally:
        conn.close()

    response = app.test_client().put(
        "/api/shares/file/share-limit",
        json={
            "can_preview": True,
            "can_download": True,
            "access_scope": "link",
            "expires_at": "",
            "max_views": 3,
        },
    )

    assert response.status_code == 200
    body = response.get_json()
    assert body["ok"] is True
    assert body["msg"] == "分享設定已更新，分享連結已重新啟用"
    assert body["share"]["status"] == "active"
    assert body["share"]["access_count"] == 2
    assert body["share"]["max_views"] == 3


def test_share_management_can_reset_file_share_access_count(tmp_path):
    db_path = tmp_path / "shares-reset-count.db"

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
                id, storage_file_id, file_id, owner_user_id, token, token_hash,
                can_download, can_preview, access_scope, max_views, access_count,
                last_accessed_at, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("share-reset", "storage-file-1", "upload-1", 1, "token-reset", "token-hash-reset", 1, 1, "link", 10, 10, "2026-05-18T07:18:00", "2026-05-11T01:00:00"),
        )
        conn.commit()
    finally:
        conn.close()

    response = app.test_client().put(
        "/api/shares/file/share-reset",
        json={
            "can_preview": True,
            "can_download": True,
            "access_scope": "link",
            "max_views": 10,
            "reset_access_count": True,
        },
    )

    assert response.status_code == 200
    body = response.get_json()
    assert body["ok"] is True
    assert body["share"]["status"] == "active"
    assert body["share"]["access_count"] == 0
    conn = get_db()
    try:
        row = conn.execute("SELECT access_count, last_accessed_at FROM storage_share_links WHERE id='share-reset'").fetchone()
        assert row["access_count"] == 0
        assert row["last_accessed_at"] is None
    finally:
        conn.close()


def test_share_management_reports_still_exhausted_when_limit_not_increased(tmp_path):
    db_path = tmp_path / "shares-still-limit.db"

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
                id, storage_file_id, file_id, owner_user_id, token, token_hash,
                can_download, can_preview, access_scope, max_views, access_count, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("share-still-limit", "storage-file-1", "upload-1", 1, "token-still-limit", "token-hash-still-limit", 1, 1, "link", 2, 2, "2026-05-11T01:00:00"),
        )
        conn.commit()
    finally:
        conn.close()

    response = app.test_client().put(
        "/api/shares/file/share-still-limit",
        json={
            "can_preview": True,
            "can_download": True,
            "access_scope": "link",
            "max_views": 2,
        },
    )

    assert response.status_code == 200
    body = response.get_json()
    assert body["ok"] is True
    assert body["share"]["status"] == "view_limit_reached"
    assert body["msg"].startswith("分享設定已更新，但分享仍次數已用完")


def test_share_management_can_reactivate_exhausted_video_share(tmp_path):
    db_path = tmp_path / "video-share-reactivate-limit.db"

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
        ensure_video_schema(conn)
        conn.execute(
            """
            CREATE TABLE uploaded_files (
                id TEXT PRIMARY KEY,
                owner_user_id INTEGER,
                privacy_mode TEXT,
                mime_type_plain_for_public TEXT,
                original_filename_plain_for_public TEXT,
                deleted_at TEXT
            )
            """
        )
        conn.execute(
            """
            INSERT INTO uploaded_files (
                id, owner_user_id, privacy_mode, mime_type_plain_for_public,
                original_filename_plain_for_public
            ) VALUES (?, ?, ?, ?, ?)
            """,
            ("cloud-video-1", 1, "standard_plain", "video/mp4", "movie.mp4"),
        )
        conn.execute(
            """
            INSERT INTO videos (
                id, video_uuid, owner_user_id, cloud_file_id, title, description,
                visibility, status, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (1, "video-uuid-1", 1, "cloud-video-1", "Movie", "", "unlisted", "ready", "2026-05-11T01:00:00", "2026-05-11T01:00:00"),
        )
        conn.execute(
            """
            INSERT INTO video_share_links (
                id, video_id, owner_user_id, token, token_hash, created_by,
                max_views, access_count, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("video-share-limit", 1, 1, "video-token-limit", "video-token-hash-limit", 1, 2, 2, "2026-05-11T02:00:00"),
        )
        conn.commit()
    finally:
        conn.close()

    response = app.test_client().put(
        "/api/shares/video/video-share-limit",
        json={
            "expires_at": "",
            "max_views": 3,
        },
    )

    assert response.status_code == 200
    body = response.get_json()
    assert body["ok"] is True
    assert body["msg"] == "分享設定已更新，分享連結已重新啟用"
    assert body["share"]["status"] == "active"
    assert body["share"]["access_count"] == 2
    assert body["share"]["max_views"] == 3


def test_share_management_can_reset_video_share_access_count(tmp_path):
    db_path = tmp_path / "video-share-reset-count.db"

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
        ensure_video_schema(conn)
        conn.execute(
            """
            CREATE TABLE uploaded_files (
                id TEXT PRIMARY KEY,
                owner_user_id INTEGER,
                privacy_mode TEXT,
                mime_type_plain_for_public TEXT,
                original_filename_plain_for_public TEXT,
                deleted_at TEXT
            )
            """
        )
        conn.execute(
            """
            INSERT INTO uploaded_files (
                id, owner_user_id, privacy_mode, mime_type_plain_for_public,
                original_filename_plain_for_public
            ) VALUES (?, ?, ?, ?, ?)
            """,
            ("cloud-video-reset", 1, "standard_plain", "video/mp4", "movie.mp4"),
        )
        conn.execute(
            """
            INSERT INTO videos (
                id, video_uuid, owner_user_id, cloud_file_id, title, description,
                visibility, status, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (1, "video-uuid-reset", 1, "cloud-video-reset", "Movie", "", "unlisted", "ready", "2026-05-11T01:00:00", "2026-05-11T01:00:00"),
        )
        conn.execute(
            """
            INSERT INTO video_share_links (
                id, video_id, owner_user_id, token, token_hash, created_by,
                max_views, access_count, last_accessed_at, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("video-share-reset", 1, 1, "video-token-reset", "video-token-hash-reset", 1, 10, 10, "2026-05-18T07:18:00", "2026-05-11T02:00:00"),
        )
        conn.commit()
    finally:
        conn.close()

    response = app.test_client().put(
        "/api/shares/video/video-share-reset",
        json={
            "max_views": 10,
            "reset_access_count": True,
        },
    )

    assert response.status_code == 200
    body = response.get_json()
    assert body["ok"] is True
    assert body["share"]["status"] == "active"
    assert body["share"]["access_count"] == 0
