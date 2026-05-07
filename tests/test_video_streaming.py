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
from services.media import streaming as media_streaming
from routes.videos import register_video_routes
from services.storage.cloud_drive import ensure_cloud_drive_attachment_schema
from services.system.audit import audit as runtime_audit
from services.system.audit import configure_audit_service
from services.users.member_levels import ensure_member_level_rules_schema
from services.storage_albums import ensure_storage_album_schema
from services.upload_security import ensure_upload_security_schema, update_cloud_drive_security_policy
from services.media.videos import publish_video


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


def _build_app(db_path, storage_root, fernet, current_user, *, audit_func=None):
    public_dir = str(Path(__file__).resolve().parents[1] / "public")
    app = Flask(__name__, static_folder=public_dir, static_url_path="")
    app.testing = True
    app.secret_key = "video-streaming-test-secret"

    def get_db():
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        return conn

    register_video_routes(app, {
        "STORAGE_DIR": str(storage_root),
        "audit": audit_func or (lambda *args, **kwargs: None),
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


def _configure_real_audit_for_test(db_path, runtime_root):
    runtime_root.mkdir(parents=True, exist_ok=True)
    log_dir = runtime_root / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    anchor_dir = runtime_root / "anchors"
    anchor_dir.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS secure_audit (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT NOT NULL,
            action TEXT NOT NULL,
            ip TEXT,
            user TEXT,
            success INTEGER NOT NULL DEFAULT 0,
            ua TEXT,
            detail TEXT,
            prev_hash TEXT,
            entry_hash TEXT,
            chain_hash TEXT
        )
        """
    )
    conn.commit()
    conn.close()

    def get_db():
        audit_conn = sqlite3.connect(db_path)
        audit_conn.row_factory = sqlite3.Row
        return audit_conn

    configure_audit_service(
        get_db=get_db,
        chain_seed="pytest-video-audit-seed",
        integrity_key=b"pytest-video-audit-key-32-bytes!",
        audit_log_path=str(log_dir / "audit.log"),
        audit_anchor_path=str(anchor_dir / "audit_anchors.log"),
        audit_anchor_latest_path=str(anchor_dir / "audit_latest_anchor.json"),
        audit_anchor_interval_seconds=0,
    )
    return runtime_audit


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
    # Issue #182 fix: the runtime JS lives in public/js/shared-video.js so
    # CSP `script-src: 'self'` doesn't block it. The HTML now only carries
    # the JSON token island + external script tag; the assertions below
    # scan the standalone JS file.
    from pathlib import Path as _P
    js = (_P(__file__).resolve().parents[1] / "public" / "js" / "shared-video.js").read_text(encoding="utf-8")

    assert page.status_code == 200
    assert '<script src="/js/shared-video.js' in html
    assert '<script id="share-token" type="application/json">' in html
    assert 'id="player-action"' in html
    assert "loadSharedHlsLibrary" in js
    assert "/js/vendor/hls.light.min.js?v=20260505-hlsjs" in js
    assert "Chrome / Firefox / Edge" in js
    assert "完整連結" in js
    assert "無法復原" in js
    assert "分享授權無效或已被竄改" in js
    assert "正在讀取 E2EE 分享授權" in js
    assert "正在下載加密影音檔" in js
    assert "正在瀏覽器端解密影音" in js
    assert "不會把密碼或金鑰送到伺服器" in js
    assert "AbortController" in js
    assert "setTimeout(() => controller.abort(), 10000);" in js
    assert "分享影音載入失敗" in js
    assert "isSharePasswordResponse" in js
    assert "showSharePasswordPrompt" in js
    assert "此分享影音需要先解鎖" in js
    assert "showSharedPlaybackAction" in js
    assert "開始 E2EE 播放" in js
    assert "未按下播放前，不會主動要求密碼或開始解密。" in js


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


def test_share_link_update_and_revoke_succeed_with_real_audit_service(tmp_path):
    db_path = tmp_path / "shared-real-audit.db"
    storage_root = tmp_path / "storage-real-audit"
    storage_root.mkdir()
    _init_db(db_path)
    audit_func = _configure_real_audit_for_test(db_path, tmp_path / "runtime-real-audit")
    owner_conn = sqlite3.connect(db_path)
    owner_conn.row_factory = sqlite3.Row
    try:
        _seed_uploaded_file(
            owner_conn,
            storage_root,
            file_id="plain-video",
            owner_user_id=1,
            filename="movie.mp4",
            mime="video/mp4",
            privacy_mode="standard_plain",
            payload=b"plain-video",
        )
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

    owner_client = _build_app(
        db_path,
        storage_root,
        Fernet(Fernet.generate_key()),
        current_user={"id": 1, "username": "alice", "role": "user", "member_level": "trusted", "effective_level": "trusted"},
        audit_func=audit_func,
    ).test_client()

    regenerated = owner_client.put(f"/api/videos/{video_id}/share-link", json={"regenerate": True})
    assert regenerated.status_code == 200
    token = regenerated.get_json()["share_link"]["url"].rsplit("/", 1)[-1]

    revoked = owner_client.delete(f"/api/videos/{video_id}/share-link")
    assert revoked.status_code == 200

    anonymous = _build_app(db_path, storage_root, Fernet(Fernet.generate_key()), current_user=None).test_client()
    revoked_view = anonymous.get(f"/api/videos/shared/{token}")
    assert revoked_view.status_code == 404


def test_shared_video_three_privacy_modes_complete_unlock_flow(tmp_path):
    """User-reported regression: share page stuck after password input, no
    response to submit. Reproduces full unlock flow for all 3 privacy modes
    so any future regression in this user-facing flow fails CI:

      1) standard_plain   — server stores plaintext on disk
      2) server_encrypted — Fernet-encrypted on disk, decrypted server-side
      3) e2ee             — browser-side decryption only

    For each mode the test exercises:
      - GET /shared/videos/<token>            → returns the inline HTML (200)
      - GET /api/videos/shared/<token>        → 401 password_required (locked)
      - POST /api/videos/shared/<token>/unlock with wrong password → 403
      - POST .../unlock with right password → 200 ok
      - GET /api/videos/shared/<token>        → 200 with video metadata
      - GET /api/videos/shared/<token>/playback → 200 playback descriptor
    """
    import sqlite3
    from cryptography.fernet import Fernet

    cases = [
        ("standard_plain", False),   # plaintext on disk
        ("server_encrypted", False), # Fernet on disk
        ("e2ee", True),              # browser-side only
    ]

    for privacy_mode, is_e2ee in cases:
        db_path = tmp_path / f"share-{privacy_mode}.db"
        storage_root = tmp_path / f"storage-{privacy_mode}"
        storage_root.mkdir()
        _init_db(db_path)
        owner_conn = sqlite3.connect(db_path)
        owner_conn.row_factory = sqlite3.Row
        try:
            file_id = f"video-{privacy_mode}"
            if is_e2ee:
                _seed_uploaded_file(
                    owner_conn, storage_root,
                    file_id=file_id, owner_user_id=1,
                    filename="secret.mp4", mime="video/mp4",
                )
                _mark_file_as_e2ee(owner_conn, file_id)
            else:
                _seed_uploaded_file(
                    owner_conn, storage_root,
                    file_id=file_id, owner_user_id=1,
                    filename="clip.mp4", mime="video/mp4",
                    privacy_mode=privacy_mode,
                )

            kwargs = {
                "actor": {"id": 1, "username": "alice", "role": "user"},
                "cloud_file_id": file_id,
                "title": f"Test {privacy_mode}",
                "visibility": "unlisted",
                "share_password": "P@ssw0rd!",
                "share_max_views": 10,
            }
            if is_e2ee:
                kwargs["share_wrapped_file_key_envelope"] = (
                    '{"alg":"AES-GCM","v":1,"nonce":"AAAAAAAAAAAAAAAA","ciphertext":"AQIDBA=="}'
                )
            video = publish_video(owner_conn, **kwargs)
            owner_conn.commit()
            token = video["share_url"].rsplit("/", 1)[-1]
        finally:
            owner_conn.close()

        client = _build_app(
            db_path, storage_root,
            Fernet(Fernet.generate_key()),
            current_user=None,
        ).test_client()

        # 1) Inline HTML page renders (no 5xx, no f-string crash). Per
        # issue #182 fix, the runtime JS now lives in
        # public/js/shared-video.js (loaded via <script src>), and the
        # token is delivered through a JSON island so CSP allows it.
        page = client.get(f"/shared/videos/{token}")
        assert page.status_code == 200, f"{privacy_mode}: share page HTML status {page.status_code}"
        page_html = page.data.decode("utf-8")
        assert "share-password-form" in page_html, f"{privacy_mode}: form missing from rendered HTML"
        assert '<script src="/js/shared-video.js' in page_html, (
            f"{privacy_mode}: external shared-video.js not loaded — fix #182 may have regressed"
        )
        assert '<script id="share-token" type="application/json">' in page_html, (
            f"{privacy_mode}: token JSON island missing"
        )

        # 2) Metadata while locked → 401 password_required
        locked = client.get(f"/api/videos/shared/{token}")
        assert locked.status_code == 401, (
            f"{privacy_mode}: locked metadata expected 401, got {locked.status_code} "
            f"body={locked.get_json()}"
        )
        body = locked.get_json()
        assert body.get("password_required") is True, f"{privacy_mode}: missing password_required flag"

        # 3) Wrong password → 403
        bad = client.post(
            f"/api/videos/shared/{token}/unlock",
            json={"password": "wrong-attempt-1"},
        )
        assert bad.status_code == 403, (
            f"{privacy_mode}: wrong password expected 403, got {bad.status_code}"
        )

        # 4) Correct password → 200 OK + session granted
        unlock = client.post(
            f"/api/videos/shared/{token}/unlock",
            json={"password": "P@ssw0rd!"},
        )
        assert unlock.status_code == 200, (
            f"{privacy_mode}: correct password expected 200, got {unlock.status_code} "
            f"body={unlock.get_json()}"
        )
        assert unlock.get_json()["ok"] is True

        # 5) Metadata after unlock → 200 with video payload
        detail = client.get(f"/api/videos/shared/{token}")
        assert detail.status_code == 200, (
            f"{privacy_mode}: post-unlock detail expected 200, got {detail.status_code} "
            f"body={detail.get_json()}"
        )
        assert detail.get_json()["video"]["share_password_required"] is True

        # 6) Playback descriptor available
        playback = client.get(f"/api/videos/shared/{token}/playback")
        assert playback.status_code == 200, (
            f"{privacy_mode}: playback expected 200, got {playback.status_code} "
            f"body={playback.get_json()}"
        )
        playback_json = playback.get_json()
        if is_e2ee:
            assert playback_json["mode"].startswith("e2ee"), (
                f"e2ee: expected e2ee_* playback mode, got {playback_json['mode']}"
            )
        else:
            assert playback_json["mode"] in {"hls", "direct", "high_performance", "server_encrypted"}, (
                f"{privacy_mode}: expected non-e2ee playback mode, got {playback_json['mode']}"
            )


def test_shared_video_page_csp_does_not_block_inline_script(tmp_path):
    """Issue #182 regression guard.

    Talisman is configured with strict CSP `script-src: 'self'` (no
    'unsafe-inline', no nonce). Inline `<script>` blocks are blocked by
    every modern browser. The shared video page must not rely on inline
    JS to function.

    This test fires when:
      A) the response has an inline <script>...</script> body AND
      B) the CSP forbids both 'unsafe-inline' and nonce-X for script-src

    The fix is either (A) move the JS to /static or (B) emit a nonce
    matching the script tag.
    """
    import sqlite3, re
    from cryptography.fernet import Fernet

    db_path = tmp_path / "csp-share.db"
    storage_root = tmp_path / "storage"
    storage_root.mkdir()
    _init_db(db_path)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        _seed_uploaded_file(
            conn, storage_root,
            file_id="video-csp", owner_user_id=1,
            filename="x.mp4", mime="video/mp4",
        )
        video = publish_video(
            conn,
            actor={"id": 1, "username": "alice", "role": "user"},
            cloud_file_id="video-csp",
            title="csp",
            visibility="unlisted",
            share_password="P",
        )
        conn.commit()
        token = video["share_url"].rsplit("/", 1)[-1]
    finally:
        conn.close()

    client = _build_app(
        db_path, storage_root,
        Fernet(Fernet.generate_key()),
        current_user=None,
    ).test_client()

    resp = client.get(f"/shared/videos/{token}")
    assert resp.status_code == 200
    body = resp.data.decode("utf-8")

    # The test fixture doesn't go through Talisman, so we can't rely on
    # the test response's CSP header. Read the *production* CSP config
    # directly from server.py to know what real browsers will see.
    from pathlib import Path as _Path
    server_py = (_Path(__file__).resolve().parents[1] / "server.py").read_text(encoding="utf-8")
    script_src_match = re.search(r'"script-src":\s*"([^"]+)"', server_py)
    production_script_src = script_src_match.group(1) if script_src_match else ""
    production_allows_inline = (
        "'unsafe-inline'" in production_script_src
        or "'nonce-" in production_script_src
    )

    inline_script = re.search(r"<script>(.{50,})</script>", body, re.DOTALL)
    has_external_script = (
        '<script src="' in body or '<script type="application/json"' in body
    )

    if inline_script and not has_external_script and not production_allows_inline:
        raise AssertionError(
            f"Shared video page emits a non-trivial inline <script> body "
            f"({len(inline_script.group(1))} chars) but the production CSP "
            f"in server.py is `script-src: {production_script_src}` which "
            "forbids inline scripts. Browsers will silently block the JS, "
            "leaving the password form inert and the page stuck at "
            "'讀取中...'.\n"
            "\n"
            "Fix options:\n"
            "  A) Move the inline JS to public/js/shared-video.js and load "
            "via <script src='/js/shared-video.js'>. Pass TOKEN via a JSON "
            "island (<script type='application/json'>...</script>).\n"
            "  B) Configure Talisman with content_security_policy_nonce_in="
            "['script-src'] and emit <script nonce='...'> on this page.\n"
            "\n"
            "See issue #182."
        )


def test_shared_video_page_browser_realistic_full_flow_for_three_modes(tmp_path):
    """Issue #182 deeper guard — go beyond "the file exists" string-grep:

      A) /js/shared-video.js is reachable via the same Flask static handler
         that real browsers will hit (so a misnamed/misplaced file fails CI).
      B) The token JSON island parses with json.loads (catches future
         regressions where someone uses repr() / format() and emits
         single-quoted Python literals — invalid JSON the browser drops).
      C) The external JS file references the exact API URL templates that
         the server actually serves, with a `${TOKEN}` interpolation slot
         (catches drift between route paths and JS fetch calls).
      D) The full 3-mode unlock + metadata + playback flow still works
         when invoked using the parsed-from-island token.
    """
    import re
    import sqlite3
    from cryptography.fernet import Fernet

    cases = [
        ("standard_plain", False),
        ("server_encrypted", False),
        ("e2ee", True),
    ]

    for privacy_mode, is_e2ee in cases:
        db_path = tmp_path / f"realbr-{privacy_mode}.db"
        storage_root = tmp_path / f"realbr-{privacy_mode}-st"
        storage_root.mkdir()
        _init_db(db_path)
        owner_conn = sqlite3.connect(db_path)
        owner_conn.row_factory = sqlite3.Row
        try:
            file_id = f"realbr-{privacy_mode}"
            if is_e2ee:
                _seed_uploaded_file(
                    owner_conn, storage_root,
                    file_id=file_id, owner_user_id=1,
                    filename="x.mp4", mime="video/mp4",
                )
                _mark_file_as_e2ee(owner_conn, file_id)
            else:
                _seed_uploaded_file(
                    owner_conn, storage_root,
                    file_id=file_id, owner_user_id=1,
                    filename="x.mp4", mime="video/mp4",
                    privacy_mode=privacy_mode,
                )
            kwargs = {
                "actor": {"id": 1, "username": "alice", "role": "user"},
                "cloud_file_id": file_id,
                "title": f"realbr-{privacy_mode}",
                "visibility": "unlisted",
                "share_password": "P@ssw0rd!",
                "share_max_views": 10,
            }
            if is_e2ee:
                kwargs["share_wrapped_file_key_envelope"] = (
                    '{"alg":"AES-GCM","v":1,"nonce":"AAAAAAAAAAAAAAAA","ciphertext":"AQIDBA=="}'
                )
            video = publish_video(owner_conn, **kwargs)
            owner_conn.commit()
            html_token = video["share_url"].rsplit("/", 1)[-1]
        finally:
            owner_conn.close()

        client = _build_app(
            db_path, storage_root,
            Fernet(Fernet.generate_key()),
            current_user=None,
        ).test_client()

        # A) external JS reachable via Flask static handler
        js_resp = client.get("/js/shared-video.js")
        assert js_resp.status_code == 200, (
            f"{privacy_mode}: /js/shared-video.js not reachable via static "
            f"handler (status {js_resp.status_code}); check public/ static "
            "mount in server.py"
        )
        js_body = js_resp.data.decode("utf-8")

        # B) token JSON island must parse as strict JSON
        page = client.get(f"/shared/videos/{html_token}").data.decode("utf-8")
        m = re.search(
            r'<script id="share-token" type="application/json">([^<]*)</script>',
            page,
        )
        assert m, f"{privacy_mode}: JSON island missing"
        try:
            parsed_token = json.loads(m.group(1))
        except json.JSONDecodeError as exc:
            raise AssertionError(
                f"{privacy_mode}: JSON island body {m.group(1)!r} is not "
                f"valid JSON ({exc}). If this trips, someone likely changed "
                "the serializer to repr() — use json.dumps."
            )
        assert parsed_token == html_token, (
            f"{privacy_mode}: token round-trip mismatch "
            f"(island={parsed_token!r}, url={html_token!r})"
        )

        # C) JS fetches the URLs the route actually exposes
        for needle in (
            "/api/videos/shared/${encodeURIComponent(TOKEN)}",
            "/api/videos/shared/${encodeURIComponent(TOKEN)}/unlock",
            "/api/videos/shared/${encodeURIComponent(TOKEN)}/playback",
        ):
            assert needle in js_body, (
                f"{privacy_mode}: shared-video.js missing fetch URL `{needle}` "
                "— route path and JS fetch path are out of sync"
            )

        # D) full unlock flow with the parsed token
        unlock = client.post(
            f"/api/videos/shared/{parsed_token}/unlock",
            json={"password": "P@ssw0rd!"},
        )
        assert unlock.status_code == 200, (
            f"{privacy_mode}: unlock with island-parsed token failed "
            f"(status={unlock.status_code}, body={unlock.get_json()})"
        )
        detail = client.get(f"/api/videos/shared/{parsed_token}")
        assert detail.status_code == 200, (
            f"{privacy_mode}: post-unlock metadata expected 200, "
            f"got {detail.status_code}"
        )
        playback = client.get(f"/api/videos/shared/{parsed_token}/playback")
        assert playback.status_code == 200, (
            f"{privacy_mode}: playback descriptor expected 200, "
            f"got {playback.status_code}"
        )


def test_shared_video_token_json_island_resists_script_tag_close_injection():
    """Issue #182 hardening guard.

    The route writes the share token into a JSON island via
    json.dumps + .replace("</", "<\\/"). That defense exists so a token
    that *looked* like </script> can never close the host <script> tag
    and inject markup. This test simulates the exact serialization the
    route does for a malicious-looking token and confirms a) the JSON
    island never closes prematurely, b) it round-trips back to the
    same string under json.loads.

    The serializer lives at routes/videos.py:_shared_video_html (a
    closure inside register_video_routes, so we mirror the two-line
    transformation here).
    """
    import json as _json

    malicious = 'abc</script><script>alert(1)</script>def'
    # Mirror routes/videos.py: share_token_json = json.dumps(...).replace("</", "<\\/")
    serialized = _json.dumps(malicious).replace("</", "<\\/")
    html = (
        '<script id="share-token" type="application/json">'
        + serialized
        + '</script>'
        + '<script src="/js/shared-video.js"></script>'
    )
    opener = '<script id="share-token" type="application/json">'
    start = html.find(opener)
    body_start = start + len(opener)
    body_end = html.find("</script>", body_start)
    assert body_end > body_start, (
        "JSON island never closes — token serializer let </script> through"
    )
    island_body = html[body_start:body_end]
    # In the JSON-string form, "<\/" is the legal way to embed a slash;
    # json.loads turns it back into "</" so the parsed token equals the
    # input.
    parsed = _json.loads(island_body)
    assert parsed == malicious, (
        f"JSON island body did not round-trip the token. "
        f"island_body={island_body!r}, parsed={parsed!r}"
    )
