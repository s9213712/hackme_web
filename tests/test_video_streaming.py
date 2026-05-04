import sqlite3
from pathlib import Path

from cryptography.fernet import Fernet
from flask import Flask, jsonify, make_response

import routes.videos as video_routes
import services.media_streaming as media_streaming
from routes.videos import register_video_routes
from services.cloud_drive import ensure_cloud_drive_attachment_schema
from services.member_levels import ensure_member_level_rules_schema
from services.storage_albums import ensure_storage_album_schema
from services.upload_security import ensure_upload_security_schema, update_cloud_drive_security_policy
from services.videos import publish_video


def _json_resp(payload, status=200):
    return make_response(jsonify(payload), status)


def _passthrough(fn):
    return fn


def _init_db(db_path):
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
        INSERT INTO users (id, username, nickname, role) VALUES
            (1, 'alice', 'Alice', 'user'),
            (2, 'viewer', 'Viewer', 'user'),
            (3, 'manager', 'Manager', 'manager');
        """
    )
    ensure_member_level_rules_schema(conn)
    ensure_upload_security_schema(conn)
    ensure_cloud_drive_attachment_schema(conn)
    ensure_storage_album_schema(conn)
    update_cloud_drive_security_policy(conn, {"scanner_enabled": False})
    conn.commit()
    conn.close()


def _build_app(db_path, storage_root, fernet, current_user):
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
        "get_current_user_ctx": lambda: current_user,
        "get_db": get_db,
        "get_system_settings": lambda: {},
        "get_member_level_rule": lambda conn, level: {
            "can_upload_attachment": True,
            "attachment_quota_mb": 100,
            "max_attachment_size_mb": 100,
            "upload_rate_limit_per_day": 50,
        },
        "get_ua": lambda: "pytest-video-streaming",
        "json_resp": _json_resp,
        "points_service": None,
        "require_csrf": _passthrough,
        "require_csrf_safe": _passthrough,
        "server_file_fernet": fernet,
    })
    return app


def _seed_uploaded_file(conn, storage_root, *, file_id, owner_user_id, filename, mime, privacy_mode="standard_plain", payload=b"demo-media"):
    rel = f"users/{owner_user_id}/{file_id}/{filename}"
    target = storage_root / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(payload)
    conn.execute(
        """
        INSERT INTO uploaded_files (
            id, owner_user_id, storage_path, privacy_mode, risk_level, scan_status,
            original_filename_plain_for_public, mime_type_plain_for_public, size_bytes, created_at
        ) VALUES (?, ?, ?, ?, 'low', 'clean', ?, ?, ?, '2026-01-01T00:00:00')
        """,
        (file_id, owner_user_id, rel, privacy_mode, filename, mime, len(payload)),
    )
    return target


def _fake_probe_payload(media_type="video"):
    streams = [{"codec_type": "audio", "codec_name": "aac", "bit_rate": "128000"}]
    if media_type == "video":
        streams.insert(0, {"codec_type": "video", "codec_name": "h264", "width": 1280, "height": 720, "bit_rate": "900000"})
    return {
        "format": {
            "duration": "12.5",
            "bit_rate": "1024000",
        },
        "streams": streams,
    }


def _fake_hls_package(source_path, *, derivative_dir, media_type, ffmpeg_bin="ffmpeg", segment_seconds=4):
    variant_name = "audio" if media_type == "audio" else "source"
    variant_dir = Path(derivative_dir) / variant_name
    variant_dir.mkdir(parents=True, exist_ok=True)
    (variant_dir / "init.mp4").write_bytes(b"init-segment")
    (variant_dir / "seg_00001.m4s").write_bytes(b"segment-1")
    (variant_dir / "seg_00002.m4s").write_bytes(b"segment-2")
    (variant_dir / "playlist.m3u8").write_text(
        "#EXTM3U\n"
        "#EXT-X-VERSION:7\n"
        "#EXT-X-MAP:URI=\"init.mp4\"\n"
        "#EXTINF:4.0,\n"
        "seg_00001.m4s\n"
        "#EXTINF:3.5,\n"
        "seg_00002.m4s\n"
        "#EXT-X-ENDLIST\n",
        encoding="utf-8",
    )
    return variant_name, variant_dir / "playlist.m3u8", variant_dir / "init.mp4"


def test_prepare_stream_asset_builds_hls_derivatives_for_plain_video(tmp_path, monkeypatch):
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE uploaded_files (
            id TEXT PRIMARY KEY,
            owner_user_id INTEGER NOT NULL,
            storage_path TEXT NOT NULL,
            privacy_mode TEXT NOT NULL,
            risk_level TEXT NOT NULL,
            scan_status TEXT NOT NULL,
            original_filename_plain_for_public TEXT,
            mime_type_plain_for_public TEXT,
            size_bytes INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT,
            deleted_at TEXT
        )
        """
    )
    storage_root = tmp_path / "storage"
    storage_root.mkdir()
    _seed_uploaded_file(conn, storage_root, file_id="plain-video", owner_user_id=1, filename="clip.mp4", mime="video/mp4")
    row = conn.execute("SELECT * FROM uploaded_files WHERE id='plain-video'").fetchone()

    monkeypatch.setattr(media_streaming, "_run_probe", lambda *args, **kwargs: _fake_probe_payload("video"))
    monkeypatch.setattr(media_streaming, "_run_ffmpeg_hls", _fake_hls_package)

    asset = media_streaming.prepare_stream_asset(
        conn,
        file_row=row,
        storage_root=storage_root,
        server_file_fernet=None,
    )

    assert asset["status"] == "ready"
    assert asset["media_type"] == "video"
    assert asset["master_manifest_path"] == "media_derivatives/plain-video/master.m3u8"
    assert len(asset["variants"]) == 1
    assert asset["variants"][0]["name"] == "source"
    assert [seg["filename"] for seg in asset["variants"][0]["segments"]] == ["seg_00001.m4s", "seg_00002.m4s"]
    assert (storage_root / "media_derivatives" / "plain-video" / "master.m3u8").exists()


def test_prepare_stream_asset_decrypts_server_encrypted_media_before_packaging(tmp_path, monkeypatch):
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE uploaded_files (
            id TEXT PRIMARY KEY,
            owner_user_id INTEGER NOT NULL,
            storage_path TEXT NOT NULL,
            privacy_mode TEXT NOT NULL,
            risk_level TEXT NOT NULL,
            scan_status TEXT NOT NULL,
            original_filename_plain_for_public TEXT,
            mime_type_plain_for_public TEXT,
            size_bytes INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT,
            deleted_at TEXT
        )
        """
    )
    storage_root = tmp_path / "storage"
    storage_root.mkdir()
    plaintext = b"server-encrypted-video-payload"
    fernet = Fernet(Fernet.generate_key())
    target = _seed_uploaded_file(
        conn,
        storage_root,
        file_id="encrypted-video",
        owner_user_id=1,
        filename="secret.mp4",
        mime="video/mp4",
        privacy_mode="server_encrypted",
        payload=fernet.encrypt(plaintext),
    )
    conn.execute("UPDATE uploaded_files SET size_bytes=? WHERE id='encrypted-video'", (target.stat().st_size,))
    row = conn.execute("SELECT * FROM uploaded_files WHERE id='encrypted-video'").fetchone()

    def fake_probe(source_path, **kwargs):
        assert Path(source_path).read_bytes() == plaintext
        return _fake_probe_payload("video")

    monkeypatch.setattr(media_streaming, "_run_probe", fake_probe)
    monkeypatch.setattr(media_streaming, "_run_ffmpeg_hls", _fake_hls_package)

    asset = media_streaming.prepare_stream_asset(
        conn,
        file_row=row,
        storage_root=storage_root,
        server_file_fernet=fernet,
    )

    assert asset["status"] == "ready"
    assert asset["source_mode"] == "server_encrypted"


def test_get_stream_status_marks_e2ee_media_unavailable(tmp_path):
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE uploaded_files (
            id TEXT PRIMARY KEY,
            owner_user_id INTEGER NOT NULL,
            storage_path TEXT NOT NULL,
            privacy_mode TEXT NOT NULL,
            risk_level TEXT NOT NULL,
            scan_status TEXT NOT NULL,
            original_filename_plain_for_public TEXT,
            mime_type_plain_for_public TEXT,
            size_bytes INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT,
            deleted_at TEXT
        )
        """
    )
    storage_root = tmp_path / "storage"
    storage_root.mkdir()
    _seed_uploaded_file(conn, storage_root, file_id="e2ee-video", owner_user_id=1, filename="secret.mp4", mime="video/mp4", privacy_mode="e2ee")
    row = conn.execute("SELECT * FROM uploaded_files WHERE id='e2ee-video'").fetchone()

    status = media_streaming.get_stream_status(conn, file_row=row)

    assert status["status"] == "unavailable"
    assert "E2EE" in status["error_message"]


def test_video_playback_and_hls_routes_use_ready_stream_asset(tmp_path, monkeypatch):
    db_path = tmp_path / "video-stream.db"
    storage_root = tmp_path / "storage"
    storage_root.mkdir()
    _init_db(db_path)
    fernet = Fernet(Fernet.generate_key())
    client = _build_app(
        db_path,
        storage_root,
        fernet,
        current_user={"id": 2, "username": "viewer", "role": "user", "member_level": "trusted", "effective_level": "trusted"},
    ).test_client()
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        _seed_uploaded_file(conn, storage_root, file_id="video-1", owner_user_id=1, filename="movie.mp4", mime="video/mp4")
        video = publish_video(conn, actor={"id": 1, "username": "alice", "role": "user"}, cloud_file_id="video-1", title="Movie")
        row = conn.execute("SELECT * FROM uploaded_files WHERE id='video-1'").fetchone()
        monkeypatch.setattr(media_streaming, "_run_probe", lambda *args, **kwargs: _fake_probe_payload("video"))
        monkeypatch.setattr(media_streaming, "_run_ffmpeg_hls", _fake_hls_package)
        media_streaming.prepare_stream_asset(conn, file_row=row, storage_root=storage_root, server_file_fernet=fernet)
        conn.commit()
        video_id = video["id"]
    finally:
        conn.close()

    playback = client.get(f"/api/videos/{video_id}/playback")
    payload = playback.get_json()
    assert playback.status_code == 200
    assert payload["ok"] is True
    assert payload["mode"] == "hls"
    assert payload["streaming_ready"] is True
    assert payload["can_prepare_stream"] is False
    assert payload["master_url"].endswith(f"/api/videos/{video_id}/hls/master.m3u8")
    assert payload["fallback_url"].endswith(f"/api/videos/{video_id}/stream")

    master = client.get(f"/api/videos/{video_id}/hls/master.m3u8")
    assert master.status_code == 200
    assert master.mimetype == "application/vnd.apple.mpegurl"

    playlist = client.get(f"/api/videos/{video_id}/hls/source/playlist.m3u8")
    assert playlist.status_code == 200
    assert playlist.mimetype == "application/vnd.apple.mpegurl"

    init_seg = client.get(f"/api/videos/{video_id}/hls/source/init.mp4")
    assert init_seg.status_code == 200
    assert init_seg.mimetype == "video/mp4"

    segment = client.get(f"/api/videos/{video_id}/hls/source/seg_00001.m4s")
    assert segment.status_code == 200
    assert segment.mimetype == "video/mp4"


def test_media_prepare_stream_route_requires_owner_or_manager(tmp_path, monkeypatch):
    db_path = tmp_path / "prepare-route.db"
    storage_root = tmp_path / "storage"
    storage_root.mkdir()
    _init_db(db_path)
    fernet = Fernet(Fernet.generate_key())
    viewer_client = _build_app(
        db_path,
        storage_root,
        fernet,
        current_user={"id": 2, "username": "viewer", "role": "user", "member_level": "trusted", "effective_level": "trusted"},
    ).test_client()
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        _seed_uploaded_file(conn, storage_root, file_id="private-video", owner_user_id=1, filename="private.mp4", mime="video/mp4")
        conn.commit()
    finally:
        conn.close()

    monkeypatch.setattr(video_routes, "prepare_stream_asset", lambda *args, **kwargs: {"status": "ready"})
    response = viewer_client.post("/api/media/private-video/prepare-stream")

    assert response.status_code == 403


def test_video_publish_auto_prepares_stream_asset_without_blocking_publish(tmp_path, monkeypatch):
    db_path = tmp_path / "publish-route.db"
    storage_root = tmp_path / "storage"
    storage_root.mkdir()
    _init_db(db_path)
    fernet = Fernet(Fernet.generate_key())
    owner_client = _build_app(
        db_path,
        storage_root,
        fernet,
        current_user={"id": 1, "username": "alice", "role": "user", "member_level": "trusted", "effective_level": "trusted"},
    ).test_client()
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        _seed_uploaded_file(conn, storage_root, file_id="video-1", owner_user_id=1, filename="movie.mp4", mime="video/mp4")
        conn.commit()
    finally:
        conn.close()

    called = {}

    def fake_prepare(conn, *, file_row, storage_root, server_file_fernet=None, ffprobe_bin="ffprobe", ffmpeg_bin="ffmpeg"):
        called["file_id"] = file_row["id"]
        return {"status": "ready", "master_manifest_path": "media_derivatives/video-1/master.m3u8"}

    monkeypatch.setattr(video_routes, "prepare_stream_asset", fake_prepare)
    response = owner_client.post(
        "/api/videos/publish",
        json={
            "cloud_file_id": "video-1",
            "title": "Movie",
            "visibility": "public",
        },
    )
    body = response.get_json()

    assert response.status_code == 200
    assert called["file_id"] == "video-1"
    assert body["video"]["title"] == "Movie"
    assert body["stream_asset"]["status"] == "ready"
    assert body["stream_warning"] == ""


def test_video_publish_keeps_success_when_auto_prepare_fails(tmp_path, monkeypatch):
    db_path = tmp_path / "publish-route-fail.db"
    storage_root = tmp_path / "storage"
    storage_root.mkdir()
    _init_db(db_path)
    fernet = Fernet(Fernet.generate_key())
    owner_client = _build_app(
        db_path,
        storage_root,
        fernet,
        current_user={"id": 1, "username": "alice", "role": "user", "member_level": "trusted", "effective_level": "trusted"},
    ).test_client()
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        _seed_uploaded_file(conn, storage_root, file_id="video-2", owner_user_id=1, filename="movie.mp4", mime="video/mp4")
        conn.commit()
    finally:
        conn.close()

    monkeypatch.setattr(video_routes, "prepare_stream_asset", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("ffmpeg missing")))
    response = owner_client.post(
        "/api/videos/publish",
        json={
            "cloud_file_id": "video-2",
            "title": "Movie 2",
            "visibility": "public",
        },
    )
    body = response.get_json()

    assert response.status_code == 200
    assert body["video"]["title"] == "Movie 2"
    assert body["stream_asset"] is None
    assert "HLS 串流準備失敗" in body["stream_warning"]
