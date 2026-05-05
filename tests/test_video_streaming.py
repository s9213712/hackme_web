import base64
import hashlib
import io
import json
import os
import sqlite3
from pathlib import Path

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
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
    app.secret_key = "video-streaming-test-secret"

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


def _mark_file_as_e2ee(conn, file_id):
    conn.execute(
        """
        UPDATE uploaded_files
        SET privacy_mode='e2ee',
            original_filename_encrypted='sealed:metadata',
            encryption_algorithm='AES-GCM',
            encryption_version='browser_passphrase_pbkdf2_v2',
            nonce='nonce-123',
            ciphertext_sha256=?
        WHERE id=?
        """,
        ("a" * 64, file_id),
    )


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _b64url_decode(data: str) -> bytes:
    padded = data + ("=" * (-len(data) % 4))
    return base64.urlsafe_b64decode(padded.encode("ascii"))


def _seed_real_e2ee_file(conn, storage_root, *, file_id, owner_user_id, filename, mime, plaintext):
    file_key = AESGCM.generate_key(bit_length=256)
    file_aead = AESGCM(file_key)
    file_nonce = os.urandom(12)
    ciphertext = file_aead.encrypt(file_nonce, plaintext, None)
    metadata_nonce = os.urandom(12)
    encrypted_metadata = json.dumps(
        {
            "alg": "AES-GCM",
            "v": 1,
            "nonce": _b64(metadata_nonce),
            "ciphertext": _b64(
                file_aead.encrypt(
                    metadata_nonce,
                    json.dumps(
                        {
                            "filename": filename,
                            "mime_type": mime,
                            "size_bytes": len(plaintext),
                        }
                    ).encode("utf-8"),
                    None,
                )
            ),
        }
    )
    _seed_uploaded_file(
        conn,
        storage_root,
        file_id=file_id,
        owner_user_id=owner_user_id,
        filename=filename,
        mime=mime,
        privacy_mode="e2ee",
        payload=ciphertext,
    )
    conn.execute(
        """
        UPDATE uploaded_files
        SET privacy_mode='e2ee',
            original_filename_encrypted=?,
            encryption_algorithm='AES-GCM',
            encryption_version='browser-passphrase-v2',
            nonce=?,
            ciphertext_sha256=?,
            size_bytes=?
        WHERE id=?
        """,
        (
            encrypted_metadata,
            _b64(file_nonce),
            hashlib.sha256(ciphertext).hexdigest(),
            len(ciphertext),
            file_id,
        ),
    )

    share_key = AESGCM.generate_key(bit_length=256)
    share_nonce = os.urandom(12)
    share_envelope = json.dumps(
        {
            "alg": "AES-GCM",
            "v": 1,
            "nonce": _b64(share_nonce),
            "ciphertext": _b64(AESGCM(share_key).encrypt(share_nonce, file_key, None)),
        }
    )
    return {
        "plaintext": plaintext,
        "file_key": file_key,
        "file_nonce_b64": _b64(file_nonce),
        "encrypted_metadata": encrypted_metadata,
        "share_key": share_key,
        "share_fragment_key": _b64url(share_key),
        "share_wrapped_file_key_envelope": share_envelope,
    }


def _unwrap_shared_file_key_from_fragment(envelope_text, fragment_key):
    envelope = json.loads(envelope_text)
    share_key = _b64url_decode(fragment_key)
    return AESGCM(share_key).decrypt(base64.b64decode(envelope["nonce"]), base64.b64decode(envelope["ciphertext"]), None)


def _decrypt_shared_metadata(file_key, encrypted_metadata):
    envelope = json.loads(encrypted_metadata)
    plaintext = AESGCM(file_key).decrypt(
        base64.b64decode(envelope["nonce"]),
        base64.b64decode(envelope["ciphertext"]),
        None,
    )
    return json.loads(plaintext.decode("utf-8"))


def _build_real_stream_v2_manifest_and_bundle(file_key, plaintext, *, content_type):
    aead = AESGCM(file_key)
    chunk_plaintext_size = 7
    chunks = []
    bundle_parts = []
    cipher_offset = 0
    plain_offset = 0
    chunk_index = 0
    while plain_offset < len(plaintext):
        chunk_plain = plaintext[plain_offset:plain_offset + chunk_plaintext_size]
        nonce = os.urandom(12)
        cipher = aead.encrypt(nonce, chunk_plain, None)
        chunks.append(
            {
                "chunk_index": chunk_index,
                "nonce": _b64(nonce),
                "ciphertext_offset": cipher_offset,
                "ciphertext_size": len(cipher),
                "plaintext_offset": plain_offset,
                "plaintext_size": len(chunk_plain),
                "ciphertext_sha256": hashlib.sha256(cipher).hexdigest(),
            }
        )
        bundle_parts.append(cipher)
        cipher_offset += len(cipher)
        plain_offset += len(chunk_plain)
        chunk_index += 1
    manifest = {
        "e2ee_stream_version": 2,
        "chunk_size": chunk_plaintext_size,
        "chunk_count": len(chunks),
        "content_type": content_type,
        "duration_hint": 3.5,
        "byte_range_hint": {"total_plaintext_bytes": len(plaintext)},
        "chunks": chunks,
    }
    return manifest, b"".join(bundle_parts)


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
    assert payload["player_strategy"] == "native_hls_or_hlsjs"
    assert payload["stream_warning"] == ""
    assert payload["hls_js_url"].endswith("hls.light.min.js?v=20260505-hlsjs")
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


def test_video_upload_server_encrypted_auto_prepares_stream_asset(tmp_path, monkeypatch):
    db_path = tmp_path / "upload-route.db"
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

    called = {}

    def fake_prepare(conn, *, file_row, storage_root, server_file_fernet=None, ffprobe_bin="ffprobe", ffmpeg_bin="ffmpeg"):
        called["file_id"] = file_row["id"]
        called["privacy_mode"] = file_row["privacy_mode"]
        return {"status": "ready", "master_manifest_path": f"media_derivatives/{file_row['id']}/master.m3u8"}

    monkeypatch.setattr(video_routes, "prepare_stream_asset", fake_prepare)
    response = owner_client.post(
        "/api/videos/upload",
        data={
            "video": (io.BytesIO(b"server-encrypted-video"), "clip.mp4", "video/mp4"),
            "title": "Encrypted upload",
            "visibility": "public",
            "privacy_mode": "server_encrypted",
        },
        content_type="multipart/form-data",
    )
    body = response.get_json()

    assert response.status_code == 200
    assert called["file_id"] == body["file"]["file_id"]
    assert called["privacy_mode"] == "server_encrypted"
    assert body["stream_asset"]["status"] == "ready"
    assert body["stream_warning"] == ""


def test_prepare_stream_auto_policy_distinguishes_plain_server_encrypted_and_e2ee(tmp_path):
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
    _seed_uploaded_file(conn, storage_root, file_id="plain-video", owner_user_id=1, filename="plain.mp4", mime="video/mp4", privacy_mode="standard_plain")
    _seed_uploaded_file(conn, storage_root, file_id="encrypted-video", owner_user_id=1, filename="enc.mp4", mime="video/mp4", privacy_mode="server_encrypted")
    _seed_uploaded_file(conn, storage_root, file_id="e2ee-video", owner_user_id=1, filename="secret.mp4", mime="video/mp4", privacy_mode="e2ee")

    plain = conn.execute("SELECT * FROM uploaded_files WHERE id='plain-video'").fetchone()
    encrypted = conn.execute("SELECT * FROM uploaded_files WHERE id='encrypted-video'").fetchone()
    e2ee = conn.execute("SELECT * FROM uploaded_files WHERE id='e2ee-video'").fetchone()

    assert media_streaming.should_auto_prepare_stream(plain, visibility="public")["enabled"] is True
    assert media_streaming.should_auto_prepare_stream(plain, visibility="private")["enabled"] is False
    assert media_streaming.should_auto_prepare_stream(encrypted, visibility="private")["enabled"] is True
    assert media_streaming.should_auto_prepare_stream(e2ee, visibility="public")["enabled"] is False


def test_shared_e2ee_video_requires_password_fragment_and_exposes_browser_side_payload(tmp_path):
    db_path = tmp_path / "shared-e2ee.db"
    storage_root = tmp_path / "storage"
    storage_root.mkdir()
    _init_db(db_path)
    owner_conn = sqlite3.connect(db_path)
    owner_conn.row_factory = sqlite3.Row
    try:
        _seed_uploaded_file(owner_conn, storage_root, file_id="e2ee-video", owner_user_id=1, filename="secret.mp4", mime="video/mp4", privacy_mode="e2ee", payload=b"ciphertext-video")
        _mark_file_as_e2ee(owner_conn, "e2ee-video")
        video = publish_video(
            owner_conn,
            actor={"id": 1, "username": "alice", "role": "user"},
            cloud_file_id="e2ee-video",
            title="Secret",
            visibility="unlisted",
            share_password="SharePass123",
            share_wrapped_file_key_envelope='{"alg":"AES-GCM","v":1,"nonce":"AAAAAAAAAAAAAAAA","ciphertext":"AQIDBA=="}',
            share_max_views=5,
        )
        owner_conn.commit()
        token = video["share_url"].rsplit("/", 1)[-1]
    finally:
        owner_conn.close()

    client = _build_app(db_path, storage_root, Fernet(Fernet.generate_key()), current_user=None).test_client()

    locked = client.get(f"/api/videos/shared/{token}")
    assert locked.status_code == 401
    assert locked.get_json()["reason"] == "password_required"

    forbidden = client.get(f"/api/videos/shared/{token}?vk=should-not-arrive")
    assert forbidden.status_code == 400
    assert forbidden.get_json()["reason"] == "forbidden_fragment_transport"

    secret_field = client.post(
        f"/api/videos/shared/{token}/unlock",
        json={"password": "SharePass123", "raw_file_key": "forbidden"},
    )
    assert secret_field.status_code == 400
    assert secret_field.get_json()["error"] == "forbidden_share_secret_field"

    bad_password = client.post(
        f"/api/videos/shared/{token}/unlock",
        json={"password": "wrong-pass"},
    )
    assert bad_password.status_code == 403
    assert bad_password.get_json()["reason"] == "password_invalid"

    unlocked = client.post(
        f"/api/videos/shared/{token}/unlock",
        json={"password": "SharePass123"},
    )
    assert unlocked.status_code == 200
    assert unlocked.get_json()["ok"] is True

    detail = client.get(f"/api/videos/shared/{token}")
    assert detail.status_code == 200
    video_payload = detail.get_json()["video"]
    assert video_payload["share_password_required"] is True
    assert video_payload["share_requires_fragment_key"] is True
    assert video_payload["share_max_views"] == 5

    playback = client.get(f"/api/videos/shared/{token}/playback")
    assert playback.status_code == 200
    playback_json = playback.get_json()
    assert playback_json["mode"] == "e2ee_direct"
    assert playback_json["requires_fragment_key"] is True
    assert playback_json["player_strategy"] == "browser_e2ee_full_fallback"
    assert playback_json["stream_warning"]
    assert playback_json["hls_js_url"] == ""
    assert playback_json["stream_v2_available"] is False

    e2ee_key = client.get(f"/api/videos/shared/{token}/e2ee-key")
    assert e2ee_key.status_code == 200
    key_payload = e2ee_key.get_json()["e2ee_share"]
    assert key_payload["wrapped_file_key_envelope"]
    assert "encrypted_file_key" not in key_payload
    assert key_payload["ciphertext_sha256"] == "a" * 64

    ciphertext = client.get(f"/api/videos/shared/{token}/ciphertext")
    assert ciphertext.status_code == 200
    assert ciphertext.data == b"ciphertext-video"


def test_shared_e2ee_video_simulation_can_decrypt_original_plaintext(tmp_path):
    db_path = tmp_path / "shared-e2ee-sim.db"
    storage_root = tmp_path / "storage"
    storage_root.mkdir()
    _init_db(db_path)
    owner_conn = sqlite3.connect(db_path)
    owner_conn.row_factory = sqlite3.Row
    try:
        sealed = _seed_real_e2ee_file(
            owner_conn,
            storage_root,
            file_id="e2ee-video",
            owner_user_id=1,
            filename="secret.mp4",
            mime="video/mp4",
            plaintext=b"simulated-shared-e2ee-video-payload",
        )
        video = publish_video(
            owner_conn,
            actor={"id": 1, "username": "alice", "role": "user"},
            cloud_file_id="e2ee-video",
            title="Secret",
            visibility="unlisted",
            share_password="SharePass123",
            share_wrapped_file_key_envelope=sealed["share_wrapped_file_key_envelope"],
            share_max_views=5,
        )
        owner_conn.commit()
        token = video["share_url"].rsplit("/", 1)[-1]
    finally:
        owner_conn.close()

    viewer = _build_app(db_path, storage_root, Fernet(Fernet.generate_key()), current_user=None).test_client()
    assert viewer.post(f"/api/videos/shared/{token}/unlock", json={"password": "SharePass123"}).status_code == 200

    playback = viewer.get(f"/api/videos/shared/{token}/playback")
    assert playback.status_code == 200
    playback_json = playback.get_json()
    assert playback_json["player_strategy"] == "browser_e2ee_full_fallback"
    assert playback_json["mode"] == "e2ee_direct"

    key_payload = viewer.get(playback_json["e2ee_key_url"]).get_json()["e2ee_share"]
    unwrapped_file_key = _unwrap_shared_file_key_from_fragment(
        key_payload["wrapped_file_key_envelope"],
        sealed["share_fragment_key"],
    )
    assert unwrapped_file_key == sealed["file_key"]

    decrypted_metadata = _decrypt_shared_metadata(unwrapped_file_key, key_payload["encrypted_metadata"])
    assert decrypted_metadata["filename"] == "secret.mp4"
    assert decrypted_metadata["mime_type"] == "video/mp4"

    ciphertext = viewer.get(playback_json["ciphertext_url"])
    assert ciphertext.status_code == 200
    plaintext = AESGCM(unwrapped_file_key).decrypt(
        base64.b64decode(key_payload["nonce"]),
        ciphertext.data,
        None,
    )
    assert plaintext == sealed["plaintext"]


def test_shared_video_password_lock_max_views_and_revoke_routes(tmp_path):
    db_path = tmp_path / "shared-guardrails.db"
    storage_root = tmp_path / "storage"
    storage_root.mkdir()
    _init_db(db_path)
    owner_conn = sqlite3.connect(db_path)
    owner_conn.row_factory = sqlite3.Row
    try:
        _seed_uploaded_file(owner_conn, storage_root, file_id="plain-video", owner_user_id=1, filename="movie.mp4", mime="video/mp4", privacy_mode="standard_plain", payload=b"plain-video")
        video = publish_video(
            owner_conn,
            actor={"id": 1, "username": "alice", "role": "user"},
            cloud_file_id="plain-video",
            title="Plain",
            visibility="unlisted",
            share_password="SharePass123",
            share_max_views=1,
        )
        owner_conn.commit()
        video_id = video["id"]
        token = video["share_url"].rsplit("/", 1)[-1]
    finally:
        owner_conn.close()

    anonymous = _build_app(db_path, storage_root, Fernet(Fernet.generate_key()), current_user=None).test_client()
    for _ in range(5):
        denied = anonymous.post(f"/api/videos/shared/{token}/unlock", json={"password": "wrong-pass"})
        assert denied.status_code == 403
    locked = anonymous.post(f"/api/videos/shared/{token}/unlock", json={"password": "wrong-pass"})
    assert locked.status_code == 429
    assert locked.get_json()["reason"] == "password_locked"

    owner_client = _build_app(
        db_path,
        storage_root,
        Fernet(Fernet.generate_key()),
        current_user={"id": 1, "username": "alice", "role": "user", "member_level": "trusted", "effective_level": "trusted"},
    ).test_client()
    regenerated = owner_client.put(f"/api/videos/{video_id}/share-link", json={"regenerate": True})
    assert regenerated.status_code == 200
    new_share_url = regenerated.get_json()["share_link"]["url"]
    new_token = new_share_url.rsplit("/", 1)[-1]
    assert new_token != token
    assert regenerated.get_json()["share_link"]["password_required"] is True

    first_viewer = _build_app(db_path, storage_root, Fernet(Fernet.generate_key()), current_user=None).test_client()
    unlock = first_viewer.post(f"/api/videos/shared/{new_token}/unlock", json={"password": "SharePass123"})
    assert unlock.status_code == 200
    ok = first_viewer.get(f"/api/videos/shared/{new_token}/playback")
    assert ok.status_code == 200

    second_viewer = _build_app(db_path, storage_root, Fernet(Fernet.generate_key()), current_user=None).test_client()
    second_unlock = second_viewer.post(f"/api/videos/shared/{new_token}/unlock", json={"password": "SharePass123"})
    assert second_unlock.status_code == 410
    exhausted = second_unlock
    assert exhausted.status_code == 410
    assert exhausted.get_json()["reason"] == "view_limit_reached"

    revoked = owner_client.delete(f"/api/videos/{video_id}/share-link")
    assert revoked.status_code == 200
    revoked_view = _build_app(db_path, storage_root, Fernet(Fernet.generate_key()), current_user=None).test_client().get(f"/api/videos/shared/{new_token}")
    assert revoked_view.status_code == 404


def test_manager_can_update_unlisted_share_link_and_receives_state_payload(tmp_path):
    db_path = tmp_path / "shared-manager.db"
    storage_root = tmp_path / "storage"
    storage_root.mkdir()
    _init_db(db_path)
    owner_conn = sqlite3.connect(db_path)
    owner_conn.row_factory = sqlite3.Row
    try:
        _seed_uploaded_file(owner_conn, storage_root, file_id="plain-video", owner_user_id=1, filename="movie.mp4", mime="video/mp4", privacy_mode="standard_plain", payload=b"plain-video")
        video = publish_video(
            owner_conn,
            actor={"id": 1, "username": "alice", "role": "user"},
            cloud_file_id="plain-video",
            title="Plain",
            visibility="unlisted",
        )
        owner_conn.commit()
        video_id = video["id"]
    finally:
        owner_conn.close()

    manager_client = _build_app(
        db_path,
        storage_root,
        Fernet(Fernet.generate_key()),
        current_user={"id": 3, "username": "manager", "role": "manager", "member_level": "trusted", "effective_level": "trusted"},
    ).test_client()
    updated = manager_client.put(
        f"/api/videos/{video_id}/share-link",
        json={"share_password": "ManagerShare123", "share_max_views": 7},
    )
    assert updated.status_code == 200
    body = updated.get_json()
    assert body["share_link"]["state"] == "active"
    assert body["share_link"]["remaining_views"] == 7
    assert body["share_link"]["password_required"] is True
    assert body["video"]["share_link"]["state_message"] == "分享連結有效"


def test_shared_video_page_mentions_hls_js_fallback_and_fragment_loss(tmp_path):
    db_path = tmp_path / "shared-page.db"
    storage_root = tmp_path / "storage"
    storage_root.mkdir()
    _init_db(db_path)
    owner_conn = sqlite3.connect(db_path)
    owner_conn.row_factory = sqlite3.Row
    try:
        _seed_uploaded_file(owner_conn, storage_root, file_id="plain-video", owner_user_id=1, filename="movie.mp4", mime="video/mp4", privacy_mode="standard_plain", payload=b"plain-video")
        video = publish_video(
            owner_conn,
            actor={"id": 1, "username": "alice", "role": "user"},
            cloud_file_id="plain-video",
            title="Plain",
            visibility="unlisted",
        )
        owner_conn.commit()
        token = video["share_url"].rsplit("/", 1)[-1]
    finally:
        owner_conn.close()

    page = _build_app(db_path, storage_root, Fernet(Fernet.generate_key()), current_user=None).test_client().get(f"/shared/videos/{token}")
    html = page.get_data(as_text=True)

    assert page.status_code == 200
    assert "loadSharedHlsLibrary" in html
    assert "/js/vendor/hls.light.min.js?v=20260505-hlsjs" in html
    assert "Chrome / Firefox / Edge" in html
    assert "完整連結" in html
    assert "無法復原" in html
    assert "分享授權無效或已被竄改" in html
    assert "正在讀取 E2EE 分享授權" in html
    assert "正在下載加密影音檔" in html
    assert "正在瀏覽器端解密影音" in html
    assert "不會把密碼或金鑰送到伺服器" in html
    assert "isSharePasswordResponse" in html
    assert "showSharePasswordPrompt" in html
    assert "此分享影音需要先解鎖" in html
    assert 'id="player-action"' in html
    assert "showSharedPlaybackAction" in html
    assert "開始 E2EE 播放" in html
    assert "未按下播放前，不會主動要求密碼或開始解密。" in html


def test_shared_e2ee_stream_v2_manifest_and_chunk_routes_work_and_stay_off_hls(tmp_path):
    db_path = tmp_path / "shared-e2ee-stream-v2.db"
    storage_root = tmp_path / "storage"
    storage_root.mkdir()
    _init_db(db_path)
    owner_conn = sqlite3.connect(db_path)
    owner_conn.row_factory = sqlite3.Row
    try:
        _seed_uploaded_file(
            owner_conn,
            storage_root,
            file_id="e2ee-video",
            owner_user_id=1,
            filename="secret.mp4",
            mime="video/mp4",
            privacy_mode="e2ee",
            payload=b"ciphertext-video",
        )
        _mark_file_as_e2ee(owner_conn, "e2ee-video")
        video = publish_video(
            owner_conn,
            actor={"id": 1, "username": "alice", "role": "user"},
            cloud_file_id="e2ee-video",
            title="Secret",
            visibility="unlisted",
            share_password="SharePass123",
            share_wrapped_file_key_envelope='{"alg":"AES-GCM","v":1,"nonce":"AAAAAAAAAAAAAAAA","ciphertext":"AQIDBA=="}',
            share_max_views=8,
        )
        owner_conn.commit()
        video_id = video["id"]
        token = video["share_url"].rsplit("/", 1)[-1]
    finally:
        owner_conn.close()

    owner_client = _build_app(
        db_path,
        storage_root,
        Fernet(Fernet.generate_key()),
        current_user={"id": 1, "username": "alice", "role": "user", "member_level": "trusted", "effective_level": "trusted"},
    ).test_client()

    manifest = {
        "e2ee_stream_version": 2,
        "chunk_size": 8,
        "chunk_count": 2,
        "content_type": "video/mp4",
        "duration_hint": 3.5,
        "byte_range_hint": {"total_plaintext_bytes": 9},
        "chunks": [
            {
                "chunk_index": 0,
                "nonce": "AAAAAAAAAAAAAAAA",
                "ciphertext_offset": 0,
                "ciphertext_size": 5,
                "plaintext_offset": 0,
                "plaintext_size": 4,
                "ciphertext_sha256": "11" * 32,
            },
            {
                "chunk_index": 1,
                "nonce": "BBBBBBBBBBBBBBBB",
                "ciphertext_offset": 5,
                "ciphertext_size": 4,
                "plaintext_offset": 4,
                "plaintext_size": 5,
                "ciphertext_sha256": "22" * 32,
            },
        ],
    }
    prepared = owner_client.post(
        "/api/media/e2ee-video/e2ee-stream-v2",
        data={
            "manifest_json": json.dumps(manifest),
            "bundle": (io.BytesIO(b"abcdeWXYZ"), "bundle.bin"),
        },
        content_type="multipart/form-data",
    )
    assert prepared.status_code == 200
    assert prepared.get_json()["asset"]["available"] is True

    viewer = _build_app(db_path, storage_root, Fernet(Fernet.generate_key()), current_user=None).test_client()
    unlocked = viewer.post(f"/api/videos/shared/{token}/unlock", json={"password": "SharePass123"})
    assert unlocked.status_code == 200

    playback = viewer.get(f"/api/videos/shared/{token}/playback")
    assert playback.status_code == 200
    playback_json = playback.get_json()
    assert playback_json["mode"] == "e2ee_stream_v2"
    assert playback_json["player_strategy"] == "browser_e2ee_stream_v2"
    assert playback_json["stream_v2_available"] is True
    assert playback_json["high_performance_streaming"] is False
    assert playback_json["master_url"] == ""
    assert playback_json["hls_js_url"] == ""
    assert "manifest_url" in playback_json
    assert "chunk_url_template" in playback_json

    shared_manifest = viewer.get(f"/api/videos/shared/{token}/e2ee-stream-v2/manifest")
    assert shared_manifest.status_code == 200
    shared_manifest_json = shared_manifest.get_json()
    assert shared_manifest_json["available"] is True
    assert shared_manifest_json["player_strategy"] == "browser_e2ee_stream_v2"
    assert shared_manifest_json["chunk_count"] == 2
    assert shared_manifest_json["chunks"][0]["ciphertext_size"] == 5
    assert "ciphertext_offset" not in shared_manifest_json["chunks"][0]

    chunk0 = viewer.get(f"/api/videos/shared/{token}/e2ee-stream-v2/chunks/0")
    assert chunk0.status_code == 200
    assert chunk0.data == b"abcde"
    assert chunk0.headers["Cache-Control"] == "private, max-age=0, no-store"

    missing_chunk = viewer.get(f"/api/videos/shared/{token}/e2ee-stream-v2/chunks/9")
    assert missing_chunk.status_code == 404
    assert missing_chunk.get_json()["error"] == "chunk_not_found"

    direct_manifest = owner_client.get(f"/api/videos/{video_id}/e2ee-stream-v2/manifest")
    assert direct_manifest.status_code == 200
    assert direct_manifest.get_json()["available"] is True


def test_shared_e2ee_stream_v2_simulation_can_decrypt_chunked_plaintext(tmp_path):
    db_path = tmp_path / "shared-e2ee-stream-v2-sim.db"
    storage_root = tmp_path / "storage"
    storage_root.mkdir()
    _init_db(db_path)
    owner_conn = sqlite3.connect(db_path)
    owner_conn.row_factory = sqlite3.Row
    try:
        sealed = _seed_real_e2ee_file(
            owner_conn,
            storage_root,
            file_id="e2ee-video",
            owner_user_id=1,
            filename="secret.mp4",
            mime="video/mp4",
            plaintext=b"simulated-shared-e2ee-stream-v2-payload",
        )
        video = publish_video(
            owner_conn,
            actor={"id": 1, "username": "alice", "role": "user"},
            cloud_file_id="e2ee-video",
            title="Secret",
            visibility="unlisted",
            share_password="SharePass123",
            share_wrapped_file_key_envelope=sealed["share_wrapped_file_key_envelope"],
            share_max_views=6,
        )
        owner_conn.commit()
        token = video["share_url"].rsplit("/", 1)[-1]
    finally:
        owner_conn.close()

    owner_client = _build_app(
        db_path,
        storage_root,
        Fernet(Fernet.generate_key()),
        current_user={"id": 1, "username": "alice", "role": "user", "member_level": "trusted", "effective_level": "trusted"},
    ).test_client()
    manifest, bundle = _build_real_stream_v2_manifest_and_bundle(
        sealed["file_key"],
        sealed["plaintext"],
        content_type="video/mp4",
    )
    prepared = owner_client.post(
        "/api/media/e2ee-video/e2ee-stream-v2",
        data={
            "manifest_json": json.dumps(manifest),
            "bundle": (io.BytesIO(bundle), "bundle.bin"),
        },
        content_type="multipart/form-data",
    )
    assert prepared.status_code == 200
    assert prepared.get_json()["asset"]["available"] is True

    viewer = _build_app(db_path, storage_root, Fernet(Fernet.generate_key()), current_user=None).test_client()
    assert viewer.post(f"/api/videos/shared/{token}/unlock", json={"password": "SharePass123"}).status_code == 200

    playback = viewer.get(f"/api/videos/shared/{token}/playback")
    assert playback.status_code == 200
    playback_json = playback.get_json()
    assert playback_json["player_strategy"] == "browser_e2ee_stream_v2"
    assert playback_json["mode"] == "e2ee_stream_v2"

    key_payload = viewer.get(playback_json["e2ee_key_url"]).get_json()["e2ee_share"]
    unwrapped_file_key = _unwrap_shared_file_key_from_fragment(
        key_payload["wrapped_file_key_envelope"],
        sealed["share_fragment_key"],
    )
    assert unwrapped_file_key == sealed["file_key"]

    shared_manifest = viewer.get(playback_json["manifest_url"])
    assert shared_manifest.status_code == 200
    manifest_json = shared_manifest.get_json()
    plaintext_parts = []
    for chunk_meta in manifest_json["chunks"]:
        chunk_res = viewer.get(
            playback_json["chunk_url_template"].replace("__INDEX__", str(chunk_meta["chunk_index"]))
        )
        assert chunk_res.status_code == 200
        chunk_plain = AESGCM(unwrapped_file_key).decrypt(
            base64.b64decode(chunk_meta["nonce"]),
            chunk_res.data,
            None,
        )
        plaintext_parts.append(chunk_plain)
    assert b"".join(plaintext_parts) == sealed["plaintext"]


def test_shared_e2ee_stream_v2_endpoints_respect_revoked_expired_and_view_limits(tmp_path):
    db_path = tmp_path / "shared-e2ee-stream-v2-guards.db"
    storage_root = tmp_path / "storage"
    storage_root.mkdir()
    _init_db(db_path)
    owner_conn = sqlite3.connect(db_path)
    owner_conn.row_factory = sqlite3.Row
    try:
        _seed_uploaded_file(
            owner_conn,
            storage_root,
            file_id="e2ee-video",
            owner_user_id=1,
            filename="secret.mp4",
            mime="video/mp4",
            privacy_mode="e2ee",
            payload=b"ciphertext-video",
        )
        _mark_file_as_e2ee(owner_conn, "e2ee-video")
        video = publish_video(
            owner_conn,
            actor={"id": 1, "username": "alice", "role": "user"},
            cloud_file_id="e2ee-video",
            title="Secret",
            visibility="unlisted",
            share_password="SharePass123",
            share_wrapped_file_key_envelope='{"alg":"AES-GCM","v":1,"nonce":"AAAAAAAAAAAAAAAA","ciphertext":"AQIDBA=="}',
            share_max_views=1,
        )
        owner_conn.commit()
        video_id = video["id"]
        token = video["share_url"].rsplit("/", 1)[-1]
    finally:
        owner_conn.close()

    owner_client = _build_app(
        db_path,
        storage_root,
        Fernet(Fernet.generate_key()),
        current_user={"id": 1, "username": "alice", "role": "user", "member_level": "trusted", "effective_level": "trusted"},
    ).test_client()
    manifest = {
        "e2ee_stream_version": 2,
        "chunk_size": 8,
        "chunk_count": 1,
        "content_type": "video/mp4",
        "duration_hint": 1.0,
        "byte_range_hint": {"total_plaintext_bytes": 4},
        "chunks": [
            {
                "chunk_index": 0,
                "nonce": "AAAAAAAAAAAAAAAA",
                "ciphertext_offset": 0,
                "ciphertext_size": 4,
                "plaintext_offset": 0,
                "plaintext_size": 4,
                "ciphertext_sha256": "11" * 32,
            }
        ],
    }
    prepared = owner_client.post(
        "/api/media/e2ee-video/e2ee-stream-v2",
        data={
            "manifest_json": json.dumps(manifest),
            "bundle": (io.BytesIO(b"ABCD"), "bundle.bin"),
        },
        content_type="multipart/form-data",
    )
    assert prepared.status_code == 200

    expired_conn = sqlite3.connect(db_path)
    expired_conn.row_factory = sqlite3.Row
    expired_conn.execute(
        "UPDATE video_share_links SET expires_at='2000-01-01T00:00:00' WHERE video_id=?",
        (video_id,),
    )
    expired_conn.commit()
    expired_conn.close()
    expired_client = _build_app(db_path, storage_root, Fernet(Fernet.generate_key()), current_user=None).test_client()
    expired_manifest = expired_client.get(f"/api/videos/shared/{token}/e2ee-stream-v2/manifest")
    assert expired_manifest.status_code == 410
    assert expired_manifest.get_json()["reason"] == "expired"

    reopen_conn = sqlite3.connect(db_path)
    reopen_conn.row_factory = sqlite3.Row
    reopen_conn.execute(
        "UPDATE video_share_links SET expires_at=NULL, access_count=0 WHERE video_id=?",
        (video_id,),
    )
    reopen_conn.commit()
    reopen_conn.close()
    first_viewer = _build_app(db_path, storage_root, Fernet(Fernet.generate_key()), current_user=None).test_client()
    assert first_viewer.post(f"/api/videos/shared/{token}/unlock", json={"password": "SharePass123"}).status_code == 200
    assert first_viewer.get(f"/api/videos/shared/{token}/e2ee-stream-v2/manifest").status_code == 200

    second_viewer = _build_app(db_path, storage_root, Fernet(Fernet.generate_key()), current_user=None).test_client()
    exhausted = second_viewer.post(f"/api/videos/shared/{token}/unlock", json={"password": "SharePass123"})
    assert exhausted.status_code == 410
    assert exhausted.get_json()["reason"] == "view_limit_reached"

    regenerated = owner_client.put(
        f"/api/videos/{video_id}/share-link",
        json={
            "regenerate": True,
            "share_wrapped_file_key_envelope": '{"alg":"AES-GCM","v":1,"nonce":"BBBBBBBBBBBBBBBB","ciphertext":"BQYHCA=="}',
        },
    )
    assert regenerated.status_code == 200
    new_token = regenerated.get_json()["share_link"]["url"].rsplit("/", 1)[-1]
    revoked = owner_client.delete(f"/api/videos/{video_id}/share-link")
    assert revoked.status_code == 200
    revoked_manifest = _build_app(db_path, storage_root, Fernet(Fernet.generate_key()), current_user=None).test_client().get(
        f"/api/videos/shared/{new_token}/e2ee-stream-v2/manifest"
    )
    assert revoked_manifest.status_code == 404


def test_shared_video_regeneration_for_e2ee_requires_new_browser_side_envelope(tmp_path):
    db_path = tmp_path / "shared-e2ee-regenerate.db"
    storage_root = tmp_path / "storage"
    storage_root.mkdir()
    _init_db(db_path)
    owner_conn = sqlite3.connect(db_path)
    owner_conn.row_factory = sqlite3.Row
    try:
        _seed_uploaded_file(owner_conn, storage_root, file_id="e2ee-video", owner_user_id=1, filename="secret.mp4", mime="video/mp4", privacy_mode="e2ee", payload=b"ciphertext-video")
        _mark_file_as_e2ee(owner_conn, "e2ee-video")
        video = publish_video(
            owner_conn,
            actor={"id": 1, "username": "alice", "role": "user"},
            cloud_file_id="e2ee-video",
            title="Secret",
            visibility="unlisted",
            share_wrapped_file_key_envelope='{"alg":"AES-GCM","v":1,"nonce":"AAAAAAAAAAAAAAAA","ciphertext":"AQIDBA=="}',
        )
        owner_conn.commit()
        video_id = video["id"]
    finally:
        owner_conn.close()

    owner_client = _build_app(
        db_path,
        storage_root,
        Fernet(Fernet.generate_key()),
        current_user={"id": 1, "username": "alice", "role": "user", "member_level": "trusted", "effective_level": "trusted"},
    ).test_client()

    missing = owner_client.put(f"/api/videos/{video_id}/share-link", json={"regenerate": True})
    assert missing.status_code == 400
    assert "瀏覽器端分享授權" in missing.get_json()["msg"]

    forbidden = owner_client.put(f"/api/videos/{video_id}/share-link", json={"regenerate": True, "e2ee_password": "nope"})
    assert forbidden.status_code == 400
    assert forbidden.get_json()["error"] == "forbidden_share_secret_field"

    regenerated = owner_client.put(
        f"/api/videos/{video_id}/share-link",
        json={
            "regenerate": True,
            "share_wrapped_file_key_envelope": '{"alg":"AES-GCM","v":1,"nonce":"BBBBBBBBBBBBBBBB","ciphertext":"BQYHCA=="}',
        },
    )
    assert regenerated.status_code == 200
    body = regenerated.get_json()
    assert body["share_link"]["requires_fragment_key"] is True
    assert body["video"]["share_requires_fragment_key"] is True
