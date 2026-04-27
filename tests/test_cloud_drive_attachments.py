import io
import sqlite3

from flask import Flask, jsonify, make_response

from routes.files import register_file_routes
from services.cloud_drive import ensure_cloud_drive_attachment_schema
from services.member_levels import ensure_member_level_rules_schema
from services.storage_albums import ensure_storage_album_schema
from services.upload_security import ensure_upload_security_schema, update_cloud_drive_security_policy


def _json_resp(payload, status=200):
    return make_response(jsonify(payload), status)


def _passthrough(fn):
    return fn


def _build_app(db_path, storage_root, actor_box):
    app = Flask(__name__)
    app.testing = True

    def get_db():
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        return conn

    register_file_routes(app, {
        "STORAGE_DIR": str(storage_root),
        "audit": lambda *args, **kwargs: None,
        "get_client_ip": lambda: "127.0.0.1",
        "get_current_user_ctx": lambda: actor_box["actor"],
        "get_db": get_db,
        "get_member_level_rule": lambda conn, level: {
            "can_upload_attachment": True,
            "attachment_quota_mb": 1,
            "max_attachment_size_mb": 1,
            "upload_rate_limit_per_day": 10,
        },
        "get_ua": lambda: "test-agent",
        "json_resp": _json_resp,
        "require_csrf": _passthrough,
        "require_csrf_safe": _passthrough,
        "role_rank": lambda role: {"user": 0, "manager": 1, "super_admin": 2}.get(role or "user", 0),
    })
    return app


def _init_db(db_path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE users (
            id INTEGER PRIMARY KEY,
            username TEXT NOT NULL,
            role TEXT NOT NULL
        );
        INSERT INTO users (id, username, role) VALUES
          (1, 'alice', 'user'),
          (2, 'bob', 'user'),
          (3, 'mallory', 'user'),
          (4, 'admin', 'manager'),
          (5, 'root', 'super_admin');
        CREATE TABLE announcements (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            content TEXT NOT NULL,
            author_user_id INTEGER NOT NULL,
            author_username TEXT NOT NULL,
            is_pinned INTEGER NOT NULL DEFAULT 0,
            is_active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        INSERT INTO announcements (id, title, content, author_user_id, author_username, created_at, updated_at)
        VALUES (1, '公告', '內容', 4, 'admin', '2026-01-01T00:00:00', '2026-01-01T00:00:00');
        """
    )
    ensure_member_level_rules_schema(conn)
    ensure_upload_security_schema(conn)
    ensure_cloud_drive_attachment_schema(conn)
    ensure_storage_album_schema(conn)
    update_cloud_drive_security_policy(conn, {"scanner_enabled": False})
    conn.commit()
    conn.close()


def _actor(user_id, username, role="user"):
    return {
        "id": user_id,
        "username": username,
        "role": role,
        "member_level": "trusted",
        "effective_level": "trusted",
        "sanction_status": "none",
    }


def test_dm_upload_enters_owner_drive_and_grants_counterparty_download(tmp_path):
    db_path = tmp_path / "drive.db"
    storage_root = tmp_path / "storage"
    storage_root.mkdir()
    _init_db(db_path)
    actor_box = {"actor": _actor(1, "alice")}
    client = _build_app(db_path, storage_root, actor_box).test_client()

    uploaded = client.post(
        "/api/cloud-drive/upload",
        data={
            "file": (io.BytesIO(b"hello bob"), "hello.txt"),
            "context_type": "dm",
            "context_id": "room-1",
            "grant_user_ids": "2",
        },
        content_type="multipart/form-data",
    )
    assert uploaded.status_code == 200
    file_id = uploaded.get_json()["file"]["file_id"]

    files = client.get("/api/cloud-drive/files")
    assert files.status_code == 200
    assert files.get_json()["files"][0]["id"] == file_id

    quota = client.get("/api/files/quota").get_json()["quota"]
    assert quota["used_bytes"] == len(b"hello bob")

    actor_box["actor"] = _actor(2, "bob")
    download = client.get(f"/api/cloud-drive/files/{file_id}/download")
    assert download.status_code == 200
    assert download.data == b"hello bob"

    actor_box["actor"] = _actor(3, "mallory")
    denied = client.get(f"/api/cloud-drive/files/{file_id}/download")
    assert denied.status_code == 403


def test_storage_upload_creates_logical_file_and_downloads_through_original_record(tmp_path):
    db_path = tmp_path / "drive.db"
    storage_root = tmp_path / "storage"
    storage_root.mkdir()
    _init_db(db_path)
    actor_box = {"actor": _actor(1, "alice")}
    client = _build_app(db_path, storage_root, actor_box).test_client()

    uploaded = client.post(
        "/api/storage/files",
        data={
            "file": (io.BytesIO(b"storage data"), "note.txt"),
            "virtual_path": "docs/note.txt",
            "display_name": "note.txt",
        },
        content_type="multipart/form-data",
    )
    assert uploaded.status_code == 200
    storage_file = uploaded.get_json()["storage_file"]
    assert storage_file["virtual_path"] == "/docs/note.txt"

    listing = client.get("/api/storage/files")
    assert listing.status_code == 200
    body = listing.get_json()
    assert body["files"][0]["id"] == storage_file["id"]
    assert body["storage"]["used_bytes"] == len(b"storage data")

    download = client.get(f"/api/storage/files/{storage_file['id']}/download")
    assert download.status_code == 200
    assert download.data == b"storage data"


def test_storage_upload_rejects_path_traversal(tmp_path):
    db_path = tmp_path / "drive.db"
    storage_root = tmp_path / "storage"
    storage_root.mkdir()
    _init_db(db_path)
    actor_box = {"actor": _actor(1, "alice")}
    client = _build_app(db_path, storage_root, actor_box).test_client()

    uploaded = client.post(
        "/api/storage/files",
        data={
            "file": (io.BytesIO(b"bad path"), "bad.txt"),
            "virtual_path": "../bad.txt",
        },
        content_type="multipart/form-data",
    )
    assert uploaded.status_code == 400
    assert "path" in uploaded.get_json()["msg"]


def test_storage_trash_restore_and_purge_updates_listing_and_quota(tmp_path):
    db_path = tmp_path / "drive.db"
    storage_root = tmp_path / "storage"
    storage_root.mkdir()
    _init_db(db_path)
    actor_box = {"actor": _actor(1, "alice")}
    client = _build_app(db_path, storage_root, actor_box).test_client()

    uploaded = client.post(
        "/api/storage/files",
        data={
            "file": (io.BytesIO(b"trash me"), "trash.txt"),
            "virtual_path": "trash.txt",
        },
        content_type="multipart/form-data",
    )
    assert uploaded.status_code == 200
    storage_file_id = uploaded.get_json()["storage_file"]["id"]

    trashed = client.delete(f"/api/storage/files/{storage_file_id}")
    assert trashed.status_code == 200
    assert trashed.get_json()["storage_file"]["is_trashed"] == 1

    assert client.get(f"/api/storage/files/{storage_file_id}/download").status_code == 404
    listing = client.get("/api/storage/files").get_json()
    assert listing["files"] == []
    trash = client.get("/api/storage/trash").get_json()
    assert trash["files"][0]["id"] == storage_file_id
    assert trash["storage"]["used_bytes"] == len(b"trash me")

    restored = client.post(f"/api/storage/files/{storage_file_id}/restore")
    assert restored.status_code == 200
    assert restored.get_json()["storage_file"]["is_trashed"] == 0
    assert client.get(f"/api/storage/files/{storage_file_id}/download").status_code == 200

    purged = client.delete(f"/api/storage/files/{storage_file_id}/purge")
    assert purged.status_code == 200
    assert purged.get_json()["purged"]["storage"]["used_bytes"] == 0
    assert client.get(f"/api/storage/files/{storage_file_id}/download").status_code == 404


def test_attach_existing_does_not_duplicate_file_and_delete_invalidates_reference(tmp_path):
    db_path = tmp_path / "drive.db"
    storage_root = tmp_path / "storage"
    storage_root.mkdir()
    _init_db(db_path)
    actor_box = {"actor": _actor(1, "alice")}
    client = _build_app(db_path, storage_root, actor_box).test_client()

    uploaded = client.post(
        "/api/cloud-drive/upload",
        data={"file": (io.BytesIO(b"one copy"), "one.txt")},
        content_type="multipart/form-data",
    )
    file_id = uploaded.get_json()["file"]["file_id"]
    attached = client.post(
        "/api/cloud-drive/attach-existing",
        json={"file_id": file_id, "context_type": "forum_post", "context_id": "101", "grant_role": "user"},
    )
    assert attached.status_code == 200

    conn = sqlite3.connect(db_path)
    file_count = conn.execute("SELECT COUNT(*) FROM uploaded_files").fetchone()[0]
    ref_count = conn.execute("SELECT COUNT(*) FROM cloud_file_refs WHERE file_id=?", (file_id,)).fetchone()[0]
    conn.close()
    assert file_count == 1
    assert ref_count == 1

    deleted = client.delete(f"/api/cloud-drive/files/{file_id}")
    assert deleted.status_code == 200
    actor_box["actor"] = _actor(2, "bob")
    download = client.get(f"/api/cloud-drive/files/{file_id}/download")
    assert download.status_code == 403


def test_announcement_attachment_requires_root_approval_before_visible(tmp_path):
    db_path = tmp_path / "drive.db"
    storage_root = tmp_path / "storage"
    storage_root.mkdir()
    _init_db(db_path)
    actor_box = {"actor": _actor(4, "admin", "manager")}
    client = _build_app(db_path, storage_root, actor_box).test_client()

    uploaded = client.post(
        "/api/cloud-drive/upload",
        data={"file": (io.BytesIO(b"policy"), "policy.txt")},
        content_type="multipart/form-data",
    )
    file_id = uploaded.get_json()["file"]["file_id"]
    requested = client.post(
        "/api/cloud-drive/announcement-attachment-requests",
        json={"file_id": file_id, "announcement_id": 1, "reason": "公告附件"},
    )
    assert requested.status_code == 200
    request_id = requested.get_json()["request"]["id"]

    refs_before = client.get("/api/cloud-drive/refs?context_type=announcement&context_id=1")
    assert refs_before.status_code == 200
    assert refs_before.get_json()["refs"] == []

    actor_box["actor"] = _actor(5, "root", "super_admin")
    approved = client.post(
        f"/api/root/announcement-attachment-requests/{request_id}/review",
        json={"action": "approve", "reason": "合法公告文件"},
    )
    assert approved.status_code == 200
    conn = sqlite3.connect(db_path)
    owner_user_id = conn.execute("SELECT owner_user_id FROM uploaded_files WHERE id=?", (file_id,)).fetchone()[0]
    conn.close()
    assert owner_user_id == 5

    actor_box["actor"] = _actor(2, "bob")
    refs_after = client.get("/api/cloud-drive/refs?context_type=announcement&context_id=1")
    assert refs_after.status_code == 200
    assert refs_after.get_json()["refs"][0]["file_id"] == file_id


def test_legacy_files_api_upload_status_and_download_alias(tmp_path):
    db_path = tmp_path / "drive.db"
    storage_root = tmp_path / "storage"
    storage_root.mkdir()
    _init_db(db_path)
    actor_box = {"actor": _actor(1, "alice")}
    client = _build_app(db_path, storage_root, actor_box).test_client()

    uploaded = client.post(
        "/api/files/upload",
        data={"file": (io.BytesIO(b"legacy alias"), "legacy.txt")},
        content_type="multipart/form-data",
    )
    assert uploaded.status_code == 200
    file_id = uploaded.get_json()["file"]["file_id"]

    status = client.get(f"/api/files/{file_id}/status")
    assert status.status_code == 200
    payload = status.get_json()["file"]
    assert payload["id"] == file_id
    assert payload["privacy_mode"] == "public_attachment"

    download = client.get(f"/api/files/{file_id}/download")
    assert download.status_code == 200
    assert download.data == b"legacy alias"


def test_e2ee_share_and_revoke_controls_download_grant(tmp_path):
    db_path = tmp_path / "drive.db"
    storage_root = tmp_path / "storage"
    storage_root.mkdir()
    _init_db(db_path)
    actor_box = {"actor": _actor(1, "alice")}
    client = _build_app(db_path, storage_root, actor_box).test_client()

    uploaded = client.post(
        "/api/files/upload",
        data={
            "file": (io.BytesIO(b"ciphertext"), "vault.bin"),
            "privacy_mode": "e2ee_vault",
            "encrypted_metadata": "sealed:filename",
            "encrypted_file_key": "sealed:owner-key",
            "ciphertext_sha256": "a" * 64,
            "encryption_algorithm": "XChaCha20-Poly1305",
            "encryption_version": "1",
            "nonce": "nonce",
        },
        content_type="multipart/form-data",
    )
    assert uploaded.status_code == 200
    file_id = uploaded.get_json()["file"]["file_id"]

    shared = client.post(
        f"/api/files/{file_id}/share",
        json={
            "recipient_user_id": 2,
            "encrypted_file_key": "sealed:bob-key",
            "context_type": "dm",
            "context_id": "room-1",
        },
    )
    assert shared.status_code == 200

    actor_box["actor"] = _actor(2, "bob")
    download = client.get(f"/api/files/{file_id}/download")
    assert download.status_code == 409
    assert download.get_json()["requires_confirmation"] is True

    download = client.get(f"/api/files/{file_id}/download?confirm_high_risk=1")
    assert download.status_code == 200
    assert download.data == b"ciphertext"

    actor_box["actor"] = _actor(1, "alice")
    revoked = client.post(f"/api/files/{file_id}/share/revoke", json={"recipient_user_id": 2})
    assert revoked.status_code == 200
    assert revoked.get_json()["revoked"]["revoked_keys"] == 1

    actor_box["actor"] = _actor(2, "bob")
    denied = client.get(f"/api/files/{file_id}/download")
    assert denied.status_code == 403
