import io
import sqlite3
from pathlib import Path

import pytest
from cryptography.fernet import Fernet
from flask import Flask, jsonify, make_response

from routes.videos import register_video_routes
from services.cloud_drive import ensure_cloud_drive_attachment_schema
from services.member_levels import ensure_member_level_rules_schema
from services.storage_albums import ensure_storage_album_schema
from services.upload_security import ensure_upload_security_schema, update_cloud_drive_security_policy
from services.videos import publish_video
from tests.video_test_helpers import actor, seed_cloud_file, video_test_db


def test_publish_media_requires_owner_and_video_or_audio_mime():
    conn = video_test_db()
    seed_cloud_file(conn, file_id="video-1", owner_user_id=1, mime="video/mp4")
    video = publish_video(
        conn,
        actor=actor(1, "owner"),
        cloud_file_id="video-1",
        title="Demo video",
        description="Cloud Drive backed",
        visibility="public",
    )
    assert video["id"] == 1
    assert video["cloud_file_id"] == "video-1"
    assert video["visibility"] == "public"
    assert video["media_type"] == "video"

    seed_cloud_file(conn, file_id="audio-1", owner_user_id=1, mime="audio/mpeg", filename="song.mp3")
    audio = publish_video(
        conn,
        actor=actor(1, "owner"),
        cloud_file_id="audio-1",
        title="Demo song",
        description="Cloud Drive backed audio",
        visibility="public",
    )
    assert audio["id"] == 2
    assert audio["cloud_file_id"] == "audio-1"
    assert audio["media_type"] == "audio"

    with pytest.raises(PermissionError):
        publish_video(conn, actor=actor(2, "viewer"), cloud_file_id="video-1", title="steal")

    seed_cloud_file(conn, file_id="text-1", owner_user_id=1, mime="text/plain", filename="note.txt")
    with pytest.raises(ValueError, match="video or audio"):
        publish_video(conn, actor=actor(1, "owner"), cloud_file_id="text-1", title="not video")


def test_publish_rejects_e2ee_video_for_server_streaming():
    conn = video_test_db()
    seed_cloud_file(conn, file_id="e2ee-video", owner_user_id=1, mime="video/mp4", privacy_mode="e2ee")
    with pytest.raises(ValueError, match="E2EE"):
        publish_video(conn, actor=actor(1, "owner"), cloud_file_id="e2ee-video", title="secret")


def test_publish_accepts_server_encrypted_video_for_server_streaming():
    conn = video_test_db()
    seed_cloud_file(conn, file_id="server-encrypted-video", owner_user_id=1, mime="video/mp4", privacy_mode="server_encrypted")

    video = publish_video(conn, actor=actor(1, "owner"), cloud_file_id="server-encrypted-video", title="encrypted stream")

    assert video["cloud_file_id"] == "server-encrypted-video"


def _json_resp(payload, status=200):
    return make_response(jsonify(payload), status)


def _passthrough(fn):
    return fn


def _init_video_upload_db(db_path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE users (
            id INTEGER PRIMARY KEY,
            username TEXT NOT NULL,
            nickname TEXT,
            role TEXT NOT NULL
        );
        INSERT INTO users (id, username, nickname, role) VALUES (1, 'alice', 'Alice', 'user');
        """
    )
    ensure_member_level_rules_schema(conn)
    ensure_upload_security_schema(conn)
    ensure_cloud_drive_attachment_schema(conn)
    ensure_storage_album_schema(conn)
    update_cloud_drive_security_policy(conn, {"scanner_enabled": False})
    conn.commit()
    conn.close()


def _build_video_upload_app(db_path, storage_root, fernet):
    app = Flask(__name__)
    app.testing = True

    def get_db():
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        return conn

    register_video_routes(app, {
        "STORAGE_DIR": str(storage_root),
        "audit": lambda *args, **kwargs: None,
        "get_client_ip": lambda: "127.0.0.1",
        "get_current_user_ctx": lambda: {
            "id": 1,
            "username": "alice",
            "role": "user",
            "member_level": "trusted",
            "effective_level": "trusted",
            "sanction_status": "none",
        },
        "get_db": get_db,
        "get_system_settings": lambda: {},
        "get_member_level_rule": lambda conn, level: {
            "can_upload_attachment": True,
            "attachment_quota_mb": 10,
            "max_attachment_size_mb": 10,
            "upload_rate_limit_per_day": 10,
        },
        "get_ua": lambda: "test-agent",
        "json_resp": _json_resp,
        "points_service": None,
        "require_csrf": _passthrough,
        "require_csrf_safe": _passthrough,
        "server_file_fernet": fernet,
    })
    return app


def test_video_upload_endpoint_stores_server_encrypted_video_and_streams_plaintext(tmp_path):
    db_path = tmp_path / "video.db"
    storage_root = tmp_path / "storage"
    storage_root.mkdir()
    _init_video_upload_db(db_path)
    fernet = Fernet(Fernet.generate_key())
    client = _build_video_upload_app(db_path, storage_root, fernet).test_client()

    response = client.post(
        "/api/videos/upload",
        data={
            "video": (io.BytesIO(b"not-a-real-mp4-but-route-test"), "clip.mp4", "video/mp4"),
            "cover": (io.BytesIO(b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x02fake-cover\xff\xd9"), "cover.jpg", "image/jpeg"),
            "title": "Direct upload",
            "description": "server encrypted",
            "visibility": "public",
            "privacy_mode": "server_encrypted",
        },
        content_type="multipart/form-data",
    )
    body = response.get_json()

    assert response.status_code == 200
    assert body["video"]["title"] == "Direct upload"
    assert body["file"]["privacy_mode"] == "server_encrypted"
    assert body["cover_file"]["privacy_mode"] == "server_encrypted"
    assert body["video"]["cover_file_id"] == body["cover_file"]["file_id"]
    assert body["video"]["cover_url"].endswith(f"/api/videos/{body['video']['id']}/cover")
    assert body["storage_file"]["virtual_path"].startswith("/Media/")
    assert body["cover_storage_file"]["virtual_path"].startswith("/Media/Covers/")

    stream = client.get(f"/api/videos/{body['video']['id']}/stream")
    assert stream.status_code == 200
    assert stream.data == b"not-a-real-mp4-but-route-test"
    assert stream.headers["Accept-Ranges"] == "bytes"

    ranged = client.get(f"/api/videos/{body['video']['id']}/stream", headers={"Range": "bytes=4-11"})
    assert ranged.status_code == 206
    assert ranged.headers["Content-Range"] == "bytes 4-11/29"
    assert ranged.headers["Accept-Ranges"] == "bytes"
    assert ranged.data == b"a-real-m"

    cover = client.get(f"/api/videos/{body['video']['id']}/cover")
    assert cover.status_code == 200
    assert cover.mimetype == "image/jpeg"
    assert cover.data == b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x02fake-cover\xff\xd9"


def test_video_upload_endpoint_accepts_audio_and_streams_it(tmp_path):
    db_path = tmp_path / "audio.db"
    storage_root = tmp_path / "storage"
    storage_root.mkdir()
    _init_video_upload_db(db_path)
    fernet = Fernet(Fernet.generate_key())
    client = _build_video_upload_app(db_path, storage_root, fernet).test_client()

    response = client.post(
        "/api/videos/upload",
        data={
            "video": (io.BytesIO(b"not-a-real-mp3-but-route-test"), "song.mp3", "audio/mpeg"),
            "title": "Direct audio",
            "description": "server encrypted audio",
            "visibility": "public",
            "privacy_mode": "server_encrypted",
        },
        content_type="multipart/form-data",
    )
    body = response.get_json()

    assert response.status_code == 200
    assert body["video"]["title"] == "Direct audio"
    assert body["video"]["media_type"] == "audio"
    assert body["file"]["privacy_mode"] == "server_encrypted"
    assert body["storage_file"]["virtual_path"].startswith("/Media/")

    stream = client.get(f"/api/videos/{body['video']['id']}/stream")
    assert stream.status_code == 200
    assert stream.mimetype == "audio/mpeg"
    assert stream.data == b"not-a-real-mp3-but-route-test"


def test_video_publish_endpoint_accepts_cover_upload_for_existing_cloud_media(tmp_path):
    db_path = tmp_path / "publish.db"
    storage_root = tmp_path / "storage"
    storage_root.mkdir()
    _init_video_upload_db(db_path)
    fernet = Fernet(Fernet.generate_key())
    client = _build_video_upload_app(db_path, storage_root, fernet).test_client()
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute(
            """
            INSERT INTO uploaded_files (
                id, owner_user_id, storage_path, privacy_mode, risk_level, scan_status,
                original_filename_plain_for_public, mime_type_plain_for_public, size_bytes, created_at
            ) VALUES (?, ?, ?, 'standard_plain', 'low', 'clean', ?, ?, 18, '2026-01-01T00:00:00')
            """,
            ("drive-video", 1, "users/1/drive-video/from-drive.mp4", "from-drive.mp4", "video/mp4"),
        )
        Path(storage_root / "users" / "1" / "drive-video").mkdir(parents=True, exist_ok=True)
        (storage_root / "users" / "1" / "drive-video" / "from-drive.mp4").write_bytes(b"cloud-backed-video")
        conn.commit()
    finally:
        conn.close()

    response = client.post(
        "/api/videos/publish",
        data={
            "cloud_file_id": "drive-video",
            "title": "Cloud file with cover",
            "description": "published from drive",
            "visibility": "public",
            "cover": (io.BytesIO(b"\xff\xd8\xff\xe0cover-from-drive\xff\xd9"), "cover.jpg", "image/jpeg"),
        },
        content_type="multipart/form-data",
    )
    body = response.get_json()

    assert response.status_code == 200
    assert body["ok"] is True
    assert body["video"]["cloud_file_id"] == "drive-video"
    assert body["video"]["cover_file_id"] == body["cover_file"]["file_id"]
    assert body["video"]["cover_url"].endswith(f"/api/videos/{body['video']['id']}/cover")
    assert body["cover_storage_file"]["virtual_path"].startswith("/Media/Covers/")

    cover = client.get(f"/api/videos/{body['video']['id']}/cover")
    assert cover.status_code == 200
    assert cover.mimetype == "image/jpeg"
    assert cover.data == b"\xff\xd8\xff\xe0cover-from-drive\xff\xd9"


def test_video_server_encrypted_cover_and_stream_handle_rotated_key_without_500(tmp_path):
    db_path = tmp_path / "video.db"
    storage_root = tmp_path / "storage"
    storage_root.mkdir()
    _init_video_upload_db(db_path)
    writer_fernet = Fernet(Fernet.generate_key())
    writer_client = _build_video_upload_app(db_path, storage_root, writer_fernet).test_client()

    response = writer_client.post(
        "/api/videos/upload",
        data={
            "video": (io.BytesIO(b"rotated-key-video"), "clip.mp4", "video/mp4"),
            "cover": (io.BytesIO(b"\xff\xd8\xff\xe0rotated-cover\xff\xd9"), "cover.jpg", "image/jpeg"),
            "title": "Rotated key",
            "visibility": "public",
            "privacy_mode": "server_encrypted",
        },
        content_type="multipart/form-data",
    )
    assert response.status_code == 200
    video_id = response.get_json()["video"]["id"]

    reader_fernet = Fernet(Fernet.generate_key())
    reader_client = _build_video_upload_app(db_path, storage_root, reader_fernet).test_client()

    cover = reader_client.get(f"/api/videos/{video_id}/cover")
    assert cover.status_code == 200
    assert cover.mimetype == "image/svg+xml"

    stream = reader_client.get(f"/api/videos/{video_id}/stream")
    assert stream.status_code == 409
    assert stream.get_json()["error"] == "decrypt_unavailable"


def test_video_upload_rejects_e2ee_and_non_video(tmp_path):
    db_path = tmp_path / "video.db"
    storage_root = tmp_path / "storage"
    storage_root.mkdir()
    _init_video_upload_db(db_path)
    client = _build_video_upload_app(db_path, storage_root, Fernet(Fernet.generate_key())).test_client()

    e2ee = client.post(
        "/api/videos/upload",
        data={
            "video": (io.BytesIO(b"video"), "clip.mp4", "video/mp4"),
            "title": "Secret",
            "privacy_mode": "e2ee",
        },
        content_type="multipart/form-data",
    )
    text = client.post(
        "/api/videos/upload",
        data={
            "video": (io.BytesIO(b"text"), "note.txt"),
            "title": "Not video",
            "privacy_mode": "standard_plain",
        },
        content_type="multipart/form-data",
    )
    bad_cover = client.post(
        "/api/videos/upload",
        data={
            "video": (io.BytesIO(b"video"), "clip.mp4", "video/mp4"),
            "cover": (io.BytesIO(b"not image"), "cover.txt", "text/plain"),
            "title": "Bad cover",
            "privacy_mode": "standard_plain",
        },
        content_type="multipart/form-data",
    )

    assert e2ee.status_code == 400
    assert e2ee.get_json()["error"] == "e2ee_not_streamable"
    assert text.status_code == 400
    assert text.get_json()["error"] == "not_media"
    assert bad_cover.status_code == 400
    assert bad_cover.get_json()["error"] == "cover_not_image"
