import io
import sqlite3
from pathlib import Path

import pytest
from cryptography.fernet import Fernet
from flask import Flask, jsonify, make_response

from routes.videos import register_video_routes
from services.storage.cloud_drive import ensure_cloud_drive_attachment_schema
from services.users.member_levels import ensure_member_level_rules_schema
from services.storage.storage_albums import ensure_storage_album_schema
from services.security.upload_security import ensure_upload_security_schema, update_cloud_drive_security_policy
from services.media.videos import (
    create_video_social_share,
    get_video,
    list_videos,
    publish_video,
    resolve_video_share_token,
    shared_video_payload,
)
from tests.video.helpers.video_test_helpers import actor, seed_cloud_file, video_test_db


def test_video_share_password_hash_uses_configured_argon2_cost(monkeypatch):
    import services.media.videos as videos_module

    captured = {}

    def fake_argon2_hash_secret_raw(secret, salt, *, time_cost, memory_cost, parallelism, hash_len, type):
        captured.update({
            "time_cost": time_cost,
            "memory_cost": memory_cost,
            "parallelism": parallelism,
            "hash_len": hash_len,
            "type": type,
        })
        return b"x" * hash_len

    monkeypatch.setenv("HTML_LEARNING_ARGON2_TIME_COST", "1")
    monkeypatch.setenv("HTML_LEARNING_ARGON2_MEMORY_COST", "8192")
    monkeypatch.setenv("HTML_LEARNING_ARGON2_PARALLELISM", "1")
    monkeypatch.setattr(videos_module, "argon2_hash_secret_raw", fake_argon2_hash_secret_raw)
    monkeypatch.setattr(videos_module, "Argon2Type", type("Argon2TypeStub", (), {"ID": "id"}))

    stored = videos_module._hash_video_share_password("ViewerPass123")

    assert stored.startswith("argon2id$1$8192$1$")
    assert captured == {
        "time_cost": 1,
        "memory_cost": 8192,
        "parallelism": 1,
        "hash_len": 32,
        "type": "id",
    }


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


def test_publish_requires_share_envelope_for_e2ee_unlisted_and_blocks_public_direct_playback():
    conn = video_test_db()
    seed_cloud_file(conn, file_id="e2ee-video", owner_user_id=1, mime="video/mp4", privacy_mode="e2ee")
    with pytest.raises(ValueError, match="瀏覽器端分享授權"):
        publish_video(conn, actor=actor(1, "owner"), cloud_file_id="e2ee-video", title="secret", visibility="unlisted")

    with pytest.raises(ValueError, match="公開列表直連播放"):
        publish_video(conn, actor=actor(1, "owner"), cloud_file_id="e2ee-video", title="secret", visibility="public")

    video = publish_video(
        conn,
        actor=actor(1, "owner"),
        cloud_file_id="e2ee-video",
        title="secret",
        visibility="unlisted",
        share_wrapped_file_key_envelope='{"alg":"AES-GCM","v":1,"nonce":"AAAAAAAAAAAAAAAA","ciphertext":"AQIDBA=="}',
    )

    assert video["visibility"] == "unlisted"
    assert video["share_url"].startswith("/shared/videos/")
    assert video["share_requires_fragment_key"] is True


def test_existing_public_e2ee_video_is_owner_only_until_shared_by_link():
    conn = video_test_db()
    seed_cloud_file(conn, file_id="legacy-e2ee-video", owner_user_id=1, mime="video/mp4", privacy_mode="e2ee")
    conn.execute(
        """
        INSERT INTO videos (
            video_uuid, owner_user_id, cloud_file_id, title, description,
            visibility, status, created_at, updated_at
        ) VALUES ('legacy-public-e2ee', 1, 'legacy-e2ee-video', 'Legacy E2EE', '', 'public', 'ready', '2026-01-01T00:00:00', '2026-01-01T00:00:00')
        """
    )

    owner_rows = list_videos(conn, actor=actor(1, "owner"))
    viewer_rows = list_videos(conn, actor=actor(2, "viewer"))

    assert any(row["cloud_file_id"] == "legacy-e2ee-video" for row in owner_rows)
    assert all(row["cloud_file_id"] != "legacy-e2ee-video" for row in viewer_rows)
    with pytest.raises(PermissionError):
        get_video(conn, 1, actor=actor(2, "viewer"))


def test_publish_accepts_server_encrypted_video_for_server_streaming():
    conn = video_test_db()
    seed_cloud_file(conn, file_id="server-encrypted-video", owner_user_id=1, mime="video/mp4", privacy_mode="server_encrypted")

    video = publish_video(conn, actor=actor(1, "owner"), cloud_file_id="server-encrypted-video", title="encrypted stream")

    assert video["cloud_file_id"] == "server-encrypted-video"


def test_public_video_social_share_link_resolves_for_shared_page():
    conn = video_test_db()
    seed_cloud_file(conn, file_id="public-video", owner_user_id=1, mime="video/mp4", privacy_mode="server_encrypted")
    video = publish_video(conn, actor=actor(1, "owner"), cloud_file_id="public-video", title="shareable stream")

    share, msg = create_video_social_share(conn, actor=actor(2, "viewer"), video_id=video["id"])
    assert msg is None

    token = share["url"].rsplit("/", 1)[-1]
    payload, reason = shared_video_payload(conn, token)

    assert reason is None
    assert payload["id"] == video["id"]
    assert payload["share_url"] == share["url"]


def test_processing_unlisted_share_can_show_status_without_serving_as_ready():
    conn = video_test_db()
    seed_cloud_file(conn, file_id="processing-video", owner_user_id=1, mime="video/mp4", privacy_mode="server_encrypted")
    video = publish_video(
        conn,
        actor=actor(1, "owner"),
        cloud_file_id="processing-video",
        title="processing stream",
        visibility="unlisted",
    )
    token = video["share_url"].rsplit("/", 1)[-1]
    conn.execute("UPDATE videos SET status='processing' WHERE id=?", (video["id"],))

    assert resolve_video_share_token(conn, token)[1] == "not_ready"
    payload, reason = shared_video_payload(conn, token, allow_processing=True)

    assert reason is None
    assert payload["id"] == video["id"]
    assert payload["status"] == "processing"
    assert payload["share_url"] == video["share_url"]


def test_publish_share_link_hash_uses_kdf_and_revoke_regenerate_controls():
    conn = video_test_db()
    seed_cloud_file(conn, file_id="e2ee-video", owner_user_id=1, mime="video/mp4", privacy_mode="e2ee")
    first = publish_video(
        conn,
        actor=actor(1, "owner"),
        cloud_file_id="e2ee-video",
        title="secret",
        visibility="unlisted",
        share_password="ViewerPass123",
        share_wrapped_file_key_envelope='{"alg":"AES-GCM","v":1,"nonce":"AAAAAAAAAAAAAAAA","ciphertext":"AQIDBA=="}',
        share_expires_at="2026-12-31T23:59:59",
        share_max_views=12,
    )
    share_row = conn.execute("SELECT * FROM video_share_links WHERE video_id=?", (first["id"],)).fetchone()
    assert share_row["password_required"] == 1
    assert str(share_row["password_hash"]).startswith(("argon2id$", "pbkdf2_sha256$"))
    assert share_row["wrapped_file_key_envelope"]

    from services.media.videos import ensure_video_share_link, revoke_video_share_link

    updated, msg = ensure_video_share_link(
        conn,
        actor=actor(1, "owner"),
        video_id=first["id"],
        regenerate=True,
        wrapped_file_key_envelope='{"alg":"AES-GCM","v":1,"nonce":"BBBBBBBBBBBBBBBB","ciphertext":"BQYHCA=="}',
    )
    assert msg is None
    assert updated["url"] != first["share_url"]
    assert updated["password_required"] is True

    revoke_video_share_link(conn, actor=actor(1, "owner"), video_id=first["id"])
    active = conn.execute(
        "SELECT COUNT(*) AS total FROM video_share_links WHERE video_id=? AND revoked_at IS NULL",
        (first["id"],),
    ).fetchone()
    assert int(active["total"]) == 0


def test_publish_share_payload_exposes_state_remaining_views_and_fragment_requirement():
    conn = video_test_db()
    seed_cloud_file(conn, file_id="e2ee-video", owner_user_id=1, mime="video/mp4", privacy_mode="e2ee")
    video = publish_video(
        conn,
        actor=actor(1, "owner"),
        cloud_file_id="e2ee-video",
        title="secret",
        visibility="unlisted",
        share_password="ViewerPass123",
        share_wrapped_file_key_envelope='{"alg":"AES-GCM","v":1,"nonce":"AAAAAAAAAAAAAAAA","ciphertext":"AQIDBA=="}',
        share_max_views=12,
    )

    hydrated = get_video(conn, video["id"], actor=actor(1, "owner"))
    share = hydrated["share_link"]

    assert share["state"] == "active"
    assert share["state_message"] == "分享連結有效"
    assert share["remaining_views"] == 12
    assert share["password_required"] is True
    assert share["requires_fragment_key"] is True
    assert share["password_locked_until"] == ""


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


def test_video_upload_endpoint_stores_server_encrypted_video_and_requires_hls_for_stream(tmp_path):
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
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    job = conn.execute(
        """
        SELECT source_module, status, progress_percent, stage, stage_detail, metadata_json
        FROM job_center_jobs
        WHERE source_module='video_upload_publish'
        ORDER BY id DESC
        LIMIT 1
        """
    ).fetchone()
    conn.close()
    assert job is not None
    assert job["status"] == "succeeded"
    assert job["progress_percent"] == 100
    assert job["stage"] == "published"
    assert "影音已發布" in job["stage_detail"]
    assert '"privacy_mode": "server_encrypted"' in job["metadata_json"]

    stream = client.get(f"/api/videos/{body['video']['id']}/stream")
    assert stream.status_code == 403

    ranged = client.get(f"/api/videos/{body['video']['id']}/stream", headers={"Range": "bytes=4-11"})
    assert ranged.status_code == 403

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
    assert stream.status_code == 403


def test_video_stream_encodes_unicode_filename_safely_for_range_responses(tmp_path):
    db_path = tmp_path / "unicode-video.db"
    storage_root = tmp_path / "storage"
    storage_root.mkdir()
    _init_video_upload_db(db_path)
    fernet = Fernet(Fernet.generate_key())
    client = _build_video_upload_app(db_path, storage_root, fernet).test_client()

    response = client.post(
        "/api/videos/upload",
        data={
            "video": (io.BytesIO(b"unicode-video-stream"), "測試影片.mp4", "video/mp4"),
            "title": "Unicode video",
            "description": "standard unicode name",
            "visibility": "private",
            "privacy_mode": "standard_plain",
        },
        content_type="multipart/form-data",
    )
    body = response.get_json()

    assert response.status_code == 200

    stream = client.get(f"/api/videos/{body['video']['id']}/stream")
    assert stream.status_code == 200
    assert stream.data == b"unicode-video-stream"
    disposition = stream.headers["Content-Disposition"]
    assert "filename*=UTF-8''" in disposition
    assert "%E6%B8%AC%E8%A9%A6%E5%BD%B1%E7%89%87.mp4" in disposition

    ranged = client.get(f"/api/videos/{body['video']['id']}/stream", headers={"Range": "bytes=0-6"})
    assert ranged.status_code == 206
    assert ranged.data == b"unicode"
    assert "filename*=UTF-8''" in ranged.headers["Content-Disposition"]


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
    assert stream.status_code == 403


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
    assert e2ee.get_json()["error"] == "unsupported_privacy_mode"
    assert text.status_code == 400
    assert text.get_json()["error"] == "not_media"
    assert bad_cover.status_code == 400
    assert bad_cover.get_json()["error"] == "cover_not_image"


def test_video_publish_routes_reject_sensitive_share_secret_fields(tmp_path):
    db_path = tmp_path / "publish-secrets.db"
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
        json={
            "cloud_file_id": "drive-video",
            "title": "Cloud file with forbidden field",
            "visibility": "public",
            "raw_file_key": "never-allowed",
        },
    )
    assert response.status_code == 400
    assert response.get_json()["error"] == "forbidden_share_secret_field"
