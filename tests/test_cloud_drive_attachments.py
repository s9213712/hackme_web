import gzip
import io
import sqlite3
import time
import zipfile

import pytest
from cryptography.fernet import Fernet
from flask import Flask, jsonify, make_response

import routes.files as files_routes
from routes.files import register_file_routes
from services.cloud_drive import ensure_cloud_drive_attachment_schema
from services.member_levels import ensure_member_level_rules_schema
from services.storage_albums import ensure_storage_album_schema
from services.upload_security import ensure_upload_security_schema, update_cloud_drive_security_policy


@pytest.fixture(autouse=True)
def _clear_remote_download_globals():
    """Reset module-level remote-download state before every test so tests don't bleed into each other."""
    with files_routes._REMOTE_DOWNLOAD_TASKS_LOCK:
        files_routes._REMOTE_DOWNLOAD_TASKS.clear()
        files_routes._REMOTE_DOWNLOAD_ACTIVE_USERS.clear()
    yield
    # Also clear after the test so lingering background threads don't affect later tests.
    with files_routes._REMOTE_DOWNLOAD_TASKS_LOCK:
        files_routes._REMOTE_DOWNLOAD_TASKS.clear()
        files_routes._REMOTE_DOWNLOAD_ACTIVE_USERS.clear()


def _json_resp(payload, status=200):
    return make_response(jsonify(payload), status)


def _passthrough(fn):
    return fn


def _build_app(db_path, storage_root, actor_box, points_service=None):
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
        "get_system_settings": lambda: {"storage_trash_retention_days": 30},
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
        "points_service": points_service,
        "server_file_fernet": Fernet(Fernet.generate_key()),
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


def test_privacy_modes_explain_server_readability_and_e2ee_tradeoffs(tmp_path):
    db_path = tmp_path / "drive.db"
    storage_root = tmp_path / "storage"
    storage_root.mkdir()
    _init_db(db_path)
    actor_box = {"actor": _actor(1, "alice")}
    client = _build_app(db_path, storage_root, actor_box).test_client()

    res = client.get("/api/files/privacy-modes")

    assert res.status_code == 200
    body = res.get_json()
    modes = body["modes"]
    assert modes["standard_plain"]["server_can_read"] is True
    assert modes["standard_plain"]["stored_at_rest"] == "plaintext"
    assert modes["server_encrypted"]["server_can_read"] == "decryptable"
    assert modes["server_encrypted"]["stored_at_rest"] == "encrypted"
    assert "不是端到端加密" in modes["server_encrypted"]["warning"]
    assert modes["e2ee"]["server_can_read"] is False
    assert modes["e2ee"]["stored_at_rest"] == "encrypted"
    assert "E2EE 密碼" in modes["e2ee"]["warning"]


def test_storage_upgrade_catalog_falls_back_when_points_schema_is_locked(tmp_path):
    class LockedPointsService:
        def ensure_schema(self, conn):
            raise sqlite3.OperationalError("database is locked")

        def list_catalog(self):
            raise AssertionError("storage upgrade catalog should not open a second connection")

    db_path = tmp_path / "drive.db"
    storage_root = tmp_path / "storage"
    storage_root.mkdir()
    _init_db(db_path)
    actor_box = {"actor": _actor(1, "alice")}
    client = _build_app(db_path, storage_root, actor_box, points_service=LockedPointsService()).test_client()

    res = client.get("/api/cloud-drive/storage-upgrades")
    body = res.get_json()

    assert res.status_code == 200
    assert body["ok"] is True
    assert [item["item_key"] for item in body["catalog"]] == ["cloud_storage_1gb_30d"]


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


def test_cloud_drive_upload_failure_returns_specific_reason(tmp_path):
    db_path = tmp_path / "drive.db"
    storage_root = tmp_path / "storage"
    storage_root.mkdir()
    _init_db(db_path)
    actor_box = {"actor": _actor(1, "alice")}
    client = _build_app(db_path, storage_root, actor_box).test_client()

    res = client.post(
        "/api/cloud-drive/upload",
        data={"file": (io.BytesIO(b"cipher"), "vault.bin"), "privacy_mode": "e2ee"},
        content_type="multipart/form-data",
    )

    assert res.status_code == 400
    body = res.get_json()
    assert body["ok"] is False
    assert "encrypted_file_key is required" in body["msg"]
    assert body["error_code"] == "ValueError"


def test_server_encrypted_upload_stores_ciphertext_but_downloads_plaintext(tmp_path):
    db_path = tmp_path / "drive.db"
    storage_root = tmp_path / "storage"
    storage_root.mkdir()
    _init_db(db_path)
    actor_box = {"actor": _actor(1, "alice")}
    client = _build_app(db_path, storage_root, actor_box).test_client()

    res = client.post(
        "/api/cloud-drive/upload",
        data={"file": (io.BytesIO(b"secret note"), "note.txt"), "privacy_mode": "server_encrypted"},
        content_type="multipart/form-data",
    )

    assert res.status_code == 200
    file_id = res.get_json()["file"]["file_id"]
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM uploaded_files WHERE id=?", (file_id,)).fetchone()
    conn.close()
    assert row["privacy_mode"] == "server_encrypted"
    stored = storage_root / row["storage_path"]
    assert stored.read_bytes() != b"secret note"

    preview = client.get(f"/api/cloud-drive/files/{file_id}/preview")
    assert preview.status_code == 200
    assert preview.get_json()["preview"]["text"] == "secret note"

    download = client.get(f"/api/cloud-drive/files/{file_id}/download")
    assert download.status_code == 200
    assert download.data == b"secret note"


def test_cloud_drive_upload_repairs_legacy_uploaded_files_schema(tmp_path):
    db_path = tmp_path / "legacy-drive.db"
    storage_root = tmp_path / "storage"
    storage_root.mkdir()
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE users (
            id INTEGER PRIMARY KEY,
            username TEXT NOT NULL,
            role TEXT NOT NULL
        );
        INSERT INTO users (id, username, role) VALUES (1, 'alice', 'user');
        CREATE TABLE uploaded_files (
            id TEXT PRIMARY KEY
        );
        """
    )
    ensure_member_level_rules_schema(conn)
    ensure_upload_security_schema(conn)
    update_cloud_drive_security_policy(conn, {"scanner_enabled": False})
    ensure_cloud_drive_attachment_schema(conn)
    conn.commit()
    conn.close()

    actor_box = {"actor": _actor(1, "alice")}
    client = _build_app(db_path, storage_root, actor_box).test_client()
    uploaded = client.post(
        "/api/cloud-drive/upload",
        data={"file": (io.BytesIO(b"legacy schema upload"), "legacy.txt")},
        content_type="multipart/form-data",
    )

    assert uploaded.status_code == 200
    body = uploaded.get_json()
    assert body["ok"] is True

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        cols = {row["name"] for row in conn.execute("PRAGMA table_info(uploaded_files)").fetchall()}
        saved = conn.execute("SELECT storage_path, size_bytes, deleted_at FROM uploaded_files").fetchone()
    finally:
        conn.close()
    assert {"owner_user_id", "storage_path", "privacy_mode", "scan_status", "size_bytes", "deleted_at"} <= cols
    assert saved["storage_path"].endswith("/legacy.txt")
    assert saved["size_bytes"] == len(b"legacy schema upload")
    assert saved["deleted_at"] is None


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

    restored_all = client.post("/api/storage/trash/restore")
    assert restored_all.status_code == 200
    assert restored_all.get_json()["trash"]["restored"] == 1
    assert client.get(f"/api/storage/files/{storage_file_id}/download").status_code == 200

    assert client.delete(f"/api/storage/files/{storage_file_id}").status_code == 200
    restored = client.post(f"/api/storage/files/{storage_file_id}/restore")
    assert restored.status_code == 200
    assert restored.get_json()["storage_file"]["is_trashed"] == 0
    assert client.get(f"/api/storage/files/{storage_file_id}/download").status_code == 200

    assert client.delete(f"/api/storage/files/{storage_file_id}").status_code == 200
    purged_all = client.delete("/api/storage/trash/purge")
    assert purged_all.status_code == 200
    assert purged_all.get_json()["trash"]["purged"] == 1
    assert client.get(f"/api/storage/files/{storage_file_id}/download").status_code == 404

    uploaded_again = client.post(
        "/api/storage/files",
        data={
            "file": (io.BytesIO(b"purge me"), "purge.txt"),
            "virtual_path": "purge.txt",
        },
        content_type="multipart/form-data",
    )
    assert uploaded_again.status_code == 200
    storage_file_id = uploaded_again.get_json()["storage_file"]["id"]
    purged = client.delete(f"/api/storage/files/{storage_file_id}/purge")
    assert purged.status_code == 200
    assert purged.get_json()["purged"]["storage"]["used_bytes"] == 0
    assert client.get(f"/api/storage/files/{storage_file_id}/download").status_code == 404


def test_storage_folders_and_file_organize_flow(tmp_path):
    db_path = tmp_path / "drive.db"
    storage_root = tmp_path / "storage"
    storage_root.mkdir()
    _init_db(db_path)
    actor_box = {"actor": _actor(1, "alice")}
    client = _build_app(db_path, storage_root, actor_box).test_client()

    created_folder = client.post("/api/storage/folders", json={"path": "/photos/raw"})
    assert created_folder.status_code == 200
    assert created_folder.get_json()["folder"]["virtual_path"] == "/photos/raw"

    uploaded = client.post(
        "/api/storage/files",
        data={
            "file": (io.BytesIO(b"folder move"), "image.txt"),
            "virtual_path": "/photos/raw/image.txt",
        },
        content_type="multipart/form-data",
    )
    assert uploaded.status_code == 200
    storage_file_id = uploaded.get_json()["storage_file"]["id"]

    folders = client.get("/api/storage/folders")
    assert folders.status_code == 200
    folder_paths = {folder["virtual_path"] for folder in folders.get_json()["folders"]}
    assert {"/photos", "/photos/raw"} <= folder_paths

    moved_file = client.put(f"/api/storage/files/{storage_file_id}/organize", json={"virtual_path": "/photos/final/image.txt"})
    assert moved_file.status_code == 200
    assert moved_file.get_json()["storage_file"]["virtual_path"] == "/photos/final/image.txt"

    moved_folder = client.put("/api/storage/folders/move", json={"old_path": "/photos/final", "new_path": "/archive/final"})
    assert moved_folder.status_code == 200
    assert moved_folder.get_json()["folder_move"]["moved_files"] == 1

    listing = client.get("/api/storage/files").get_json()["files"]
    assert listing[0]["virtual_path"] == "/archive/final/image.txt"

    deleted_folder = client.post("/api/storage/folders/trash", json={"path": "/archive"})
    assert deleted_folder.status_code == 200
    assert deleted_folder.get_json()["folder_trash"]["trashed_files"] == 1
    assert client.get("/api/storage/files").get_json()["files"] == []
    trash = client.get("/api/storage/trash").get_json()["files"]
    assert trash[0]["virtual_path"] == "/archive/final/image.txt"


def test_storage_folder_trash_endpoint_handles_empty_explicit_folder(tmp_path):
    db_path = tmp_path / "drive.db"
    storage_root = tmp_path / "storage"
    storage_root.mkdir()
    _init_db(db_path)
    actor_box = {"actor": _actor(1, "alice")}
    client = _build_app(db_path, storage_root, actor_box).test_client()

    created_folder = client.post("/api/storage/folders", json={"path": "/empty"})
    assert created_folder.status_code == 200

    deleted_folder = client.post("/api/storage/folders/trash", json={"path": "/empty"})

    assert deleted_folder.status_code == 200
    body = deleted_folder.get_json()
    assert body["folder_trash"]["path"] == "/empty"
    assert body["folder_trash"]["trashed_files"] == 0
    assert body["folder_trash"]["deleted_folders"] == 1


def test_storage_folder_can_be_converted_to_album_when_all_files_are_media(tmp_path):
    db_path = tmp_path / "drive.db"
    storage_root = tmp_path / "storage"
    storage_root.mkdir()
    _init_db(db_path)
    actor_box = {"actor": _actor(1, "alice")}
    client = _build_app(db_path, storage_root, actor_box).test_client()

    for filename, payload, virtual_path in (
        ("cover.png", b"\x89PNG\r\n\x1a\n", "/gallery/cover.png"),
        ("clip.mp4", b"\x00\x00\x00\x18ftypmp42", "/gallery/nested/clip.mp4"),
    ):
        uploaded = client.post(
            "/api/storage/files",
            data={"file": (io.BytesIO(payload), filename), "virtual_path": virtual_path},
            content_type="multipart/form-data",
        )
        assert uploaded.status_code == 200

    created = client.post("/api/storage/folders/album", json={"path": "/gallery", "title": "Gallery"})

    assert created.status_code == 200
    album = created.get_json()["album"]
    assert album["title"] == "Gallery"
    assert album["source_folder"] == "/gallery"
    assert album["added_count"] == 2
    assert [item["display_name"] for item in album["files"]] == ["cover.png", "clip.mp4"]


def test_storage_folder_album_rejects_non_media_files(tmp_path):
    db_path = tmp_path / "drive.db"
    storage_root = tmp_path / "storage"
    storage_root.mkdir()
    _init_db(db_path)
    actor_box = {"actor": _actor(1, "alice")}
    client = _build_app(db_path, storage_root, actor_box).test_client()

    for filename, virtual_path in (
        ("cover.png", "/mixed/cover.png"),
        ("note.txt", "/mixed/note.txt"),
    ):
        uploaded = client.post(
            "/api/storage/files",
            data={"file": (io.BytesIO(b"file body"), filename), "virtual_path": virtual_path},
            content_type="multipart/form-data",
        )
        assert uploaded.status_code == 200

    created = client.post("/api/storage/folders/album", json={"path": "/mixed", "title": "Mixed"})

    assert created.status_code == 400
    assert "非圖片/影片" in created.get_json()["msg"]
    assert all(album["title"] != "Mixed" for album in client.get("/api/storage/albums").get_json()["albums"])


def test_storage_album_crud_and_file_membership(tmp_path):
    db_path = tmp_path / "drive.db"
    storage_root = tmp_path / "storage"
    storage_root.mkdir()
    _init_db(db_path)
    actor_box = {"actor": _actor(1, "alice")}
    client = _build_app(db_path, storage_root, actor_box).test_client()

    uploaded = client.post(
        "/api/storage/files",
        data={
            "file": (io.BytesIO(b"album image"), "image.txt"),
            "virtual_path": "photos/image.txt",
        },
        content_type="multipart/form-data",
    )
    assert uploaded.status_code == 200
    storage_file_id = uploaded.get_json()["storage_file"]["id"]

    created = client.post("/api/storage/albums", json={"title": "Trip", "visibility": "unlisted"})
    assert created.status_code == 200
    album = created.get_json()["album"]
    assert album["title"] == "Trip"
    assert album["visibility"] == "unlisted"
    assert album["share_url"].startswith("/shared/albums/")
    assert album["share_link"]["url"] == album["share_url"]

    added = client.post(
        f"/api/storage/albums/{album['id']}/files",
        json={"storage_file_id": storage_file_id, "caption": "cover", "sort_order": 2},
    )
    assert added.status_code == 200
    files = added.get_json()["album"]["files"]
    assert len(files) == 1
    assert files[0]["caption"] == "cover"
    assert files[0]["original_filename_plain_for_public"] == "image.txt"
    assert "mime_type_plain_for_public" in files[0]

    public_album = client.get(f"/api/storage/shared/albums/{album['share_url'].rsplit('/', 1)[-1]}")
    assert public_album.status_code == 200
    assert public_album.get_json()["album"]["files"][0]["display_name"] == "image.txt"

    public_file = client.get(public_album.get_json()["album"]["files"][0]["download_url"])
    assert public_file.status_code == 200
    assert public_file.data == b"album image"

    protected = client.post(
        "/api/storage/albums",
        json={"title": "Protected Trip", "visibility": "unlisted", "share_password": "AlbumPass123"},
    )
    assert protected.status_code == 200
    protected_album = protected.get_json()["album"]
    assert protected_album["share_link"]["password_required"] is True
    protected_token = protected_album["share_url"].rsplit("/", 1)[-1]
    protected_added = client.post(
        f"/api/storage/albums/{protected_album['id']}/files",
        json={"storage_file_id": storage_file_id},
    )
    assert protected_added.status_code == 200
    assert client.get(f"/api/storage/shared/albums/{protected_token}").status_code == 401
    assert client.get(
        f"/api/storage/shared/albums/{protected_token}",
        headers={"X-Album-Share-Password": "wrong"},
    ).status_code == 403
    protected_public = client.get(
        f"/api/storage/shared/albums/{protected_token}",
        headers={"X-Album-Share-Password": "AlbumPass123"},
    )
    assert protected_public.status_code == 200
    protected_download = protected_public.get_json()["album"]["files"][0]["download_url"]
    assert client.get(protected_download).status_code == 401
    assert client.get(f"{protected_download}?password=AlbumPass123").status_code == 200

    updated = client.put(f"/api/storage/albums/{album['id']}", json={"title": "Trip 2", "visibility": "public"})
    assert updated.status_code == 200
    assert updated.get_json()["album"]["title"] == "Trip 2"
    assert "share_url" not in updated.get_json()["album"]
    assert client.get(f"/api/storage/shared/albums/{album['share_url'].rsplit('/', 1)[-1]}").status_code == 404

    listed = client.get("/api/storage/albums")
    assert listed.status_code == 200
    listed_album = next(row for row in listed.get_json()["albums"] if row["id"] == album["id"])
    assert listed_album["file_count"] == 1

    album_file_id = files[0]["id"]
    removed = client.delete(f"/api/storage/albums/{album['id']}/files/{album_file_id}")
    assert removed.status_code == 200
    assert removed.get_json()["album"]["files"] == []

    deleted = client.delete(f"/api/storage/albums/{album['id']}")
    assert deleted.status_code == 200
    assert client.get(f"/api/storage/albums/{album['id']}").status_code == 404


def test_album_preview_uses_storage_display_name_when_uploaded_metadata_missing(tmp_path):
    db_path = tmp_path / "drive.db"
    storage_root = tmp_path / "storage"
    storage_root.mkdir()
    _init_db(db_path)
    actor_box = {"actor": _actor(1, "alice")}
    client = _build_app(db_path, storage_root, actor_box).test_client()

    uploaded = client.post(
        "/api/storage/files",
        data={
            "file": (io.BytesIO(b"fake png bytes"), "opaque.bin"),
            "virtual_path": "photos/real-photo.png",
            "display_name": "real-photo.png",
        },
        content_type="multipart/form-data",
    )
    assert uploaded.status_code == 200
    file_id = uploaded.get_json()["file"]["file_id"]

    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "UPDATE uploaded_files SET original_filename_plain_for_public=NULL, mime_type_plain_for_public=NULL WHERE id=?",
            (file_id,),
        )
        conn.commit()
    finally:
        conn.close()

    created = client.post("/api/storage/albums", json={"title": "Recovered Preview"})
    assert created.status_code == 200
    album_id = created.get_json()["album"]["id"]

    added = client.post(f"/api/storage/albums/{album_id}/files", json={"file_id": file_id})
    assert added.status_code == 200
    album_file = added.get_json()["album"]["files"][0]
    assert album_file["display_name"] == "real-photo.png"
    assert album_file["original_filename_plain_for_public"] is None
    assert album_file["storage_path"]

    preview = client.get(f"/api/cloud-drive/files/{file_id}/preview")
    assert preview.status_code == 200
    preview_body = preview.get_json()["preview"]
    assert preview_body["filename"] == "real-photo.png"
    assert preview_body["category"] == "image"
    assert preview_body["render_mode"] == "media"
    assert preview_body["mime_type"] == "image/png"

    content = client.get(f"/api/cloud-drive/files/{file_id}/preview/content")
    assert content.status_code == 200
    assert content.content_type.startswith("image/png")


def test_storage_album_rejects_other_users_file(tmp_path):
    db_path = tmp_path / "drive.db"
    storage_root = tmp_path / "storage"
    storage_root.mkdir()
    _init_db(db_path)
    actor_box = {"actor": _actor(1, "alice")}
    client = _build_app(db_path, storage_root, actor_box).test_client()

    uploaded = client.post(
        "/api/storage/files",
        data={
            "file": (io.BytesIO(b"private"), "private.txt"),
            "virtual_path": "private.txt",
        },
        content_type="multipart/form-data",
    )
    assert uploaded.status_code == 200
    storage_file_id = uploaded.get_json()["storage_file"]["id"]

    actor_box["actor"] = _actor(2, "bob")
    created = client.post("/api/storage/albums", json={"title": "Bob"})
    album_id = created.get_json()["album"]["id"]
    denied = client.post(f"/api/storage/albums/{album_id}/files", json={"storage_file_id": storage_file_id})
    assert denied.status_code == 400


def test_storage_share_link_download_and_revoke(tmp_path):
    db_path = tmp_path / "drive.db"
    storage_root = tmp_path / "storage"
    storage_root.mkdir()
    _init_db(db_path)
    actor_box = {"actor": _actor(1, "alice")}
    client = _build_app(db_path, storage_root, actor_box).test_client()

    uploaded = client.post(
        "/api/storage/files",
        data={
            "file": (io.BytesIO(b"shared data"), "shared.txt"),
            "virtual_path": "shared.txt",
        },
        content_type="multipart/form-data",
    )
    assert uploaded.status_code == 200
    storage_file_id = uploaded.get_json()["storage_file"]["id"]

    created = client.post("/api/storage/share-links", json={"storage_file_id": storage_file_id})
    assert created.status_code == 200
    share_link = created.get_json()["share_link"]
    assert share_link["token"]

    listed = client.get("/api/storage/share-links").get_json()["share_links"]
    assert listed[0]["id"] == share_link["id"]
    assert "token" not in listed[0]

    actor_box["actor"] = _actor(3, "mallory")
    downloaded = client.get(f"/api/storage/shared/{share_link['token']}/download")
    assert downloaded.status_code == 200
    assert downloaded.data == b"shared data"

    actor_box["actor"] = _actor(1, "alice")
    revoked = client.post(f"/api/storage/share-links/{share_link['id']}/revoke")
    assert revoked.status_code == 200
    assert revoked.get_json()["share_link"]["revoked_at"]
    denied = client.get(f"/api/storage/shared/{share_link['token']}/download")
    assert denied.status_code == 404


def test_cloud_drive_text_and_archive_preview(tmp_path):
    db_path = tmp_path / "drive.db"
    storage_root = tmp_path / "storage"
    storage_root.mkdir()
    _init_db(db_path)
    actor_box = {"actor": _actor(1, "alice")}
    client = _build_app(db_path, storage_root, actor_box).test_client()

    text_upload = client.post(
        "/api/cloud-drive/upload",
        data={"file": (io.BytesIO(b"hello preview"), "note.txt")},
        content_type="multipart/form-data",
    )
    assert text_upload.status_code == 200
    text_file_id = text_upload.get_json()["file"]["file_id"]
    text_preview = client.get(f"/api/cloud-drive/files/{text_file_id}/preview")
    assert text_preview.status_code == 200
    text_body = text_preview.get_json()["preview"]
    assert text_body["render_mode"] == "text"
    assert "hello preview" in text_body["text"]

    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w") as archive:
        archive.writestr("docs/readme.txt", "archive preview")
    zip_buffer.seek(0)
    archive_upload = client.post(
        "/api/cloud-drive/upload",
        data={
            "file": (zip_buffer, "bundle.zip"),
            "privacy_mode": "standard_plain",
        },
        content_type="multipart/form-data",
    )
    assert archive_upload.status_code == 200
    archive_file_id = archive_upload.get_json()["file"]["file_id"]
    archive_preview = client.get(f"/api/cloud-drive/files/{archive_file_id}/preview")
    assert archive_preview.status_code == 200
    archive_body = archive_preview.get_json()["preview"]
    assert archive_body["render_mode"] == "archive"
    assert archive_body["entries"][0]["name"] == "docs/readme.txt"

    gz_upload = client.post(
        "/api/cloud-drive/upload",
        data={
            "file": (io.BytesIO(gzip.compress(b"compressed preview")), "single.txt.gz"),
            "privacy_mode": "standard_plain",
        },
        content_type="multipart/form-data",
    )
    assert gz_upload.status_code == 200
    gz_file_id = gz_upload.get_json()["file"]["file_id"]
    gz_preview = client.get(f"/api/cloud-drive/files/{gz_file_id}/preview")
    assert gz_preview.status_code == 200
    gz_body = gz_preview.get_json()["preview"]
    assert gz_body["render_mode"] == "archive"
    assert gz_body["entries"][0]["name"] == "single.txt"


def test_cloud_drive_pdf_preview_content_and_e2ee_denied(tmp_path):
    db_path = tmp_path / "drive.db"
    storage_root = tmp_path / "storage"
    storage_root.mkdir()
    _init_db(db_path)
    actor_box = {"actor": _actor(1, "alice")}
    client = _build_app(db_path, storage_root, actor_box).test_client()

    pdf_bytes = b"%PDF-1.4\n% minimal preview fixture\n"
    uploaded = client.post(
        "/api/cloud-drive/upload",
        data={
            "file": (io.BytesIO(pdf_bytes), "manual.pdf"),
            "privacy_mode": "standard_plain",
        },
        content_type="multipart/form-data",
    )
    assert uploaded.status_code == 200
    file_id = uploaded.get_json()["file"]["file_id"]

    metadata = client.get(f"/api/cloud-drive/files/{file_id}/preview")
    assert metadata.status_code == 200
    preview = metadata.get_json()["preview"]
    assert preview["category"] == "pdf"
    assert preview["render_mode"] == "media"

    content = client.get(f"/api/cloud-drive/files/{file_id}/preview/content")
    assert content.status_code == 200
    assert content.data == pdf_bytes
    assert content.mimetype == "application/pdf"

    encrypted = client.post(
        "/api/cloud-drive/upload",
        data={
            "file": (io.BytesIO(pdf_bytes), "sealed.pdf"),
            "privacy_mode": "e2ee",
            "encrypted_metadata": "sealed:metadata",
            "encrypted_file_key": "sealed:owner-key",
            "wrapped_by": "browser_passphrase_pbkdf2_v2",
            "ciphertext_sha256": "a" * 64,
            "encryption_algorithm": "AES-GCM",
            "encryption_version": "browser-passphrase-v2",
            "nonce": "nonce",
        },
        content_type="multipart/form-data",
    )
    assert encrypted.status_code == 200
    encrypted_file_id = encrypted.get_json()["file"]["file_id"]
    denied = client.get(f"/api/cloud-drive/files/{encrypted_file_id}/preview")
    assert denied.status_code == 403
    assert "E2EE" in denied.get_json()["msg"]
    encrypted_content = client.get(f"/api/cloud-drive/files/{encrypted_file_id}/preview/content")
    assert encrypted_content.status_code == 200
    assert encrypted_content.data == pdf_bytes
    assert encrypted_content.mimetype == "application/octet-stream"


def test_cloud_drive_text_file_can_be_edited_online(tmp_path):
    db_path = tmp_path / "drive.db"
    storage_root = tmp_path / "storage"
    storage_root.mkdir()
    _init_db(db_path)
    actor_box = {"actor": _actor(1, "alice")}
    client = _build_app(db_path, storage_root, actor_box).test_client()

    uploaded = client.post(
        "/api/cloud-drive/upload",
        data={"file": (io.BytesIO(b"old text"), "note.txt")},
        content_type="multipart/form-data",
    )
    assert uploaded.status_code == 200
    file_id = uploaded.get_json()["file"]["file_id"]

    edited = client.put(f"/api/cloud-drive/files/{file_id}/text", json={"content": "new text"})
    assert edited.status_code == 200
    assert edited.get_json()["size_bytes"] == len("new text")
    preview = client.get(f"/api/cloud-drive/files/{file_id}/preview")
    assert preview.status_code == 200
    assert preview.get_json()["preview"]["text"] == "new text"

    actor_box["actor"] = _actor(2, "bob")
    denied = client.put(f"/api/cloud-drive/files/{file_id}/text", json={"content": "take over"})
    assert denied.status_code == 403


def test_cloud_drive_can_create_text_document_and_preview_extensionless_file(tmp_path):
    db_path = tmp_path / "drive.db"
    storage_root = tmp_path / "storage"
    storage_root.mkdir()
    _init_db(db_path)
    actor_box = {"actor": _actor(1, "alice")}
    client = _build_app(db_path, storage_root, actor_box).test_client()

    created = client.post(
        "/api/cloud-drive/files/text",
        json={"filename": "notes", "content": "# hello\nbody", "privacy_mode": "standard_plain"},
    )
    assert created.status_code == 200
    file_id = created.get_json()["file"]["file_id"]
    preview = client.get(f"/api/cloud-drive/files/{file_id}/preview")
    assert preview.status_code == 200
    body = preview.get_json()["preview"]
    assert body["filename"] == "notes"
    assert body["render_mode"] == "text"
    assert body["mime_type"] == "text/plain"
    assert "# hello" in body["text"]


def test_cloud_drive_delete_file_from_ui_api_invalidates_download(tmp_path):
    db_path = tmp_path / "drive.db"
    storage_root = tmp_path / "storage"
    storage_root.mkdir()
    _init_db(db_path)
    actor_box = {"actor": _actor(1, "alice")}
    client = _build_app(db_path, storage_root, actor_box).test_client()

    uploaded = client.post(
        "/api/cloud-drive/upload",
        data={"file": (io.BytesIO(b"delete me"), "delete.txt")},
        content_type="multipart/form-data",
    )
    assert uploaded.status_code == 200
    file_id = uploaded.get_json()["file"]["file_id"]
    deleted = client.delete(f"/api/cloud-drive/files/{file_id}")
    assert deleted.status_code == 200
    assert deleted.get_json()["msg"] == "檔案已移到垃圾桶"
    assert client.get("/api/cloud-drive/files").get_json()["files"] == []
    trash = client.get("/api/storage/trash")
    assert trash.status_code == 200
    assert trash.get_json()["files"][0]["file_id"] == file_id
    assert client.get(f"/api/cloud-drive/files/{file_id}/download").status_code == 404


def test_cloud_drive_audio_preview_content(tmp_path):
    db_path = tmp_path / "drive.db"
    storage_root = tmp_path / "storage"
    storage_root.mkdir()
    _init_db(db_path)
    actor_box = {"actor": _actor(1, "alice")}
    client = _build_app(db_path, storage_root, actor_box).test_client()

    uploaded = client.post(
        "/api/cloud-drive/upload",
        data={"file": (io.BytesIO(b"not real mp3 but preview route returns bytes"), "sound.mp3")},
        content_type="multipart/form-data",
    )
    assert uploaded.status_code == 200
    file_id = uploaded.get_json()["file"]["file_id"]

    metadata = client.get(f"/api/cloud-drive/files/{file_id}/preview")
    assert metadata.status_code == 200
    assert metadata.get_json()["preview"]["category"] == "audio"
    content = client.get(f"/api/cloud-drive/files/{file_id}/preview/content")
    assert content.status_code == 200
    assert content.data == b"not real mp3 but preview route returns bytes"
    assert content.mimetype.startswith("audio/")


def test_cloud_drive_image_preview_content(tmp_path):
    db_path = tmp_path / "drive.db"
    storage_root = tmp_path / "storage"
    storage_root.mkdir()
    _init_db(db_path)
    actor_box = {"actor": _actor(1, "alice")}
    client = _build_app(db_path, storage_root, actor_box).test_client()

    image_bytes = b"\x89PNG\r\n\x1a\nnot a full image but enough for route bytes"
    uploaded = client.post(
        "/api/cloud-drive/upload",
        data={"file": (io.BytesIO(image_bytes), "preview.png")},
        content_type="multipart/form-data",
    )
    assert uploaded.status_code == 200
    file_id = uploaded.get_json()["file"]["file_id"]

    metadata = client.get(f"/api/cloud-drive/files/{file_id}/preview")
    assert metadata.status_code == 200
    preview = metadata.get_json()["preview"]
    assert preview["category"] == "image"
    assert preview["render_mode"] == "media"
    content = client.get(f"/api/cloud-drive/files/{file_id}/preview/content")
    assert content.status_code == 200
    assert content.data == image_bytes
    assert content.mimetype.startswith("image/")


def test_storage_admin_summary_sync_and_root_purge(tmp_path):
    db_path = tmp_path / "drive.db"
    storage_root = tmp_path / "storage"
    storage_root.mkdir()
    _init_db(db_path)
    actor_box = {"actor": _actor(1, "alice")}
    client = _build_app(db_path, storage_root, actor_box).test_client()

    uploaded = client.post(
        "/api/storage/files",
        data={
            "file": (io.BytesIO(b"admin visible"), "admin.txt"),
            "virtual_path": "admin.txt",
        },
        content_type="multipart/form-data",
    )
    assert uploaded.status_code == 200
    storage_file_id = uploaded.get_json()["storage_file"]["id"]
    assert client.delete(f"/api/storage/files/{storage_file_id}").status_code == 200

    actor_box["actor"] = _actor(4, "admin", "manager")
    summary = client.get("/api/admin/storage/summary")
    assert summary.status_code == 200
    assert summary.get_json()["summary"]["trashed_files"] == 1

    users = client.get("/api/admin/storage/users")
    assert users.status_code == 200
    assert any(row["username"] == "alice" for row in users.get_json()["users"])

    files = client.get("/api/admin/storage/files?include_trashed=1")
    assert files.status_code == 200
    assert files.get_json()["files"][0]["owner_username"] == "alice"

    synced = client.post("/api/admin/storage/sync-quota")
    assert synced.status_code == 200
    assert len(synced.get_json()["synced"]) >= 1

    denied = client.post("/api/admin/storage/trash/purge", json={"confirm": "PURGE STORAGE TRASH"})
    assert denied.status_code == 403

    actor_box["actor"] = _actor(5, "root", "super_admin")
    bad_confirm = client.post("/api/admin/storage/trash/purge", json={"confirm": "wrong"})
    assert bad_confirm.status_code == 400
    purged = client.post("/api/admin/storage/trash/purge", json={"confirm": "PURGE STORAGE TRASH"})
    assert purged.status_code == 200
    assert purged.get_json()["purged"] == 1

    maintenance = client.get("/api/admin/storage/maintenance")
    assert maintenance.status_code == 200
    assert "maintenance" in maintenance.get_json()
    run = client.post("/api/admin/storage/maintenance")
    assert run.status_code == 200
    assert "synced_users" in run.get_json()["maintenance"]


def test_root_storage_user_quota_override_api(tmp_path):
    db_path = tmp_path / "drive.db"
    storage_root = tmp_path / "storage"
    storage_root.mkdir()
    _init_db(db_path)
    actor_box = {"actor": _actor(4, "admin", "manager")}
    client = _build_app(db_path, storage_root, actor_box).test_client()

    denied = client.put(
        "/api/root/storage/users/1/quota-override",
        json={"quota_mb": 2, "reason": "manager should not set root override"},
    )
    assert denied.status_code == 403

    actor_box["actor"] = _actor(5, "root", "super_admin")
    listed = client.get("/api/root/storage/users")
    assert listed.status_code == 200
    assert any(row["username"] == "alice" for row in listed.get_json()["users"])

    saved = client.put(
        "/api/root/storage/users/1/quota-override",
        json={
            "quota_mb": 2,
            "max_file_size_mb": 1,
            "upload_rate_limit_per_day": 3,
            "can_upload": False,
            "reason": "root direct account setting",
        },
    )
    assert saved.status_code == 200
    payload = saved.get_json()
    assert payload["override"]["enabled"] is True
    assert payload["user"]["quota_source"] == "root_user_override"
    assert payload["user"]["total_bytes"] == 2 * 1024 * 1024
    assert payload["user"]["can_upload"] is False

    detail = client.get("/api/root/storage/users/1")
    assert detail.status_code == 200
    assert detail.get_json()["user"]["override"]["reason"] == "root direct account setting"

    cleared = client.delete("/api/root/storage/users/1/quota-override")
    assert cleared.status_code == 200
    assert cleared.get_json()["user"]["quota_source"] == "member_level_rules.attachment_quota_mb"


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
    ref_id = attached.get_json()["attachment"]["ref_id"]

    conn = sqlite3.connect(db_path)
    file_count = conn.execute("SELECT COUNT(*) FROM uploaded_files").fetchone()[0]
    ref_count = conn.execute("SELECT COUNT(*) FROM cloud_file_refs WHERE file_id=?", (file_id,)).fetchone()[0]
    conn.close()
    assert file_count == 1
    assert ref_count == 1

    actor_box["actor"] = _actor(2, "bob")
    assert client.get(f"/api/cloud-drive/files/{file_id}/download").status_code == 200

    actor_box["actor"] = _actor(1, "alice")
    removed_ref = client.delete(f"/api/cloud-drive/refs/{ref_id}")
    assert removed_ref.status_code == 200
    assert removed_ref.get_json()["msg"] == "附件已移除"
    refs_after_remove = client.get("/api/cloud-drive/refs?context_type=forum_post&context_id=101")
    assert refs_after_remove.status_code == 200
    assert refs_after_remove.get_json()["refs"] == []
    actor_box["actor"] = _actor(2, "bob")
    assert client.get(f"/api/cloud-drive/files/{file_id}/download").status_code == 403

    actor_box["actor"] = _actor(1, "alice")
    attached_again = client.post(
        "/api/cloud-drive/attach-existing",
        json={"file_id": file_id, "context_type": "forum_post", "context_id": "101", "grant_role": "user"},
    )
    assert attached_again.status_code == 200
    ref_id = attached_again.get_json()["attachment"]["ref_id"]
    removed_ref_compat = client.delete("/api/cloud-drive/refs/", json={"ref_id": ref_id})
    assert removed_ref_compat.status_code == 200

    attached_post_delete = client.post(
        "/api/cloud-drive/attach-existing",
        json={"file_id": file_id, "context_type": "forum_post", "context_id": "101", "grant_role": "user"},
    )
    assert attached_post_delete.status_code == 200
    ref_id = attached_post_delete.get_json()["attachment"]["ref_id"]
    removed_ref_post = client.post(f"/api/cloud-drive/refs/{ref_id}/delete", json={})
    assert removed_ref_post.status_code == 200

    deleted = client.delete(f"/api/cloud-drive/files/{file_id}")
    assert deleted.status_code == 200
    actor_box["actor"] = _actor(2, "bob")
    download = client.get(f"/api/cloud-drive/files/{file_id}/download")
    assert download.status_code == 404


def test_cloud_drive_refs_requires_private_context_membership(tmp_path):
    db_path = tmp_path / "drive.db"
    storage_root = tmp_path / "storage"
    storage_root.mkdir()
    _init_db(db_path)
    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        CREATE TABLE dm_threads (
            id INTEGER PRIMARY KEY,
            participant_a_id INTEGER NOT NULL,
            participant_b_id INTEGER NOT NULL,
            created_at TEXT,
            updated_at TEXT
        )
        """
    )
    conn.execute(
        "INSERT INTO dm_threads (id, participant_a_id, participant_b_id, created_at, updated_at) VALUES (1, 1, 2, '2026-01-01', '2026-01-01')"
    )
    conn.commit()
    conn.close()
    actor_box = {"actor": _actor(1, "alice")}
    client = _build_app(db_path, storage_root, actor_box).test_client()

    uploaded = client.post(
        "/api/cloud-drive/upload",
        data={"file": (io.BytesIO(b"dm private"), "private.txt")},
        content_type="multipart/form-data",
    )
    file_id = uploaded.get_json()["file"]["file_id"]
    attached = client.post(
        "/api/cloud-drive/attach-existing",
        json={"file_id": file_id, "context_type": "dm", "context_id": "1", "grant_user_ids": [2]},
    )
    assert attached.status_code == 200

    actor_box["actor"] = _actor(3, "mallory")
    denied = client.get("/api/cloud-drive/refs?context_type=dm&context_id=1")
    assert denied.status_code == 403

    actor_box["actor"] = _actor(2, "bob")
    allowed = client.get("/api/cloud-drive/refs?context_type=dm&context_id=1")
    assert allowed.status_code == 200
    assert allowed.get_json()["refs"][0]["file_id"] == file_id


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
    assert payload["privacy_mode"] == "standard_plain"

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
            "privacy_mode": "e2ee",
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


def test_e2ee_key_endpoint_returns_only_recipient_key(tmp_path):
    db_path = tmp_path / "drive.db"
    storage_root = tmp_path / "storage"
    storage_root.mkdir()
    _init_db(db_path)
    actor_box = {"actor": _actor(1, "alice")}
    client = _build_app(db_path, storage_root, actor_box).test_client()

    uploaded = client.post(
        "/api/cloud-drive/upload",
        data={
            "file": (io.BytesIO(b"cipher"), "vault.bin"),
            "privacy_mode": "e2ee",
            "encrypted_metadata": "sealed:metadata",
            "encrypted_file_key": "sealed:owner-key",
            "wrapped_by": "browser_passphrase_pbkdf2_v2",
            "ciphertext_sha256": "a" * 64,
            "encryption_algorithm": "AES-GCM",
            "encryption_version": "browser-passphrase-v2",
            "nonce": "nonce",
        },
        content_type="multipart/form-data",
    )
    assert uploaded.status_code == 200
    file_id = uploaded.get_json()["file"]["file_id"]

    owner_key = client.get(f"/api/cloud-drive/files/{file_id}/e2ee-key")
    assert owner_key.status_code == 200
    body = owner_key.get_json()
    assert body["ok"] is True
    assert body["e2ee"]["encrypted_file_key"] == "sealed:owner-key"
    assert body["e2ee"]["encrypted_metadata"] == "sealed:metadata"
    assert body["e2ee"]["wrapped_by"] == "browser_passphrase_pbkdf2_v2"

    actor_box["actor"] = _actor(3, "mallory")
    denied = client.get(f"/api/cloud-drive/files/{file_id}/e2ee-key")
    assert denied.status_code == 403
    assert "沒有可用的解密金鑰" in denied.get_json()["msg"]


def test_remote_download_capabilities_and_rejects_local_paths(tmp_path):
    db_path = tmp_path / "drive.db"
    storage_root = tmp_path / "storage"
    storage_root.mkdir()
    _init_db(db_path)
    actor_box = {"actor": _actor(1, "alice")}
    client = _build_app(db_path, storage_root, actor_box).test_client()

    caps = client.get("/api/cloud-drive/remote-download/capabilities")
    assert caps.status_code == 200
    assert caps.get_json()["capabilities"]["direct_link"] is True

    blocked = client.post(
        "/api/cloud-drive/remote-download",
        json={"url": "file:///etc/passwd", "privacy_mode": "standard_plain"},
    )
    assert blocked.status_code == 400
    assert "http" in blocked.get_json()["msg"]

    blocked_task = client.post(
        "/api/cloud-drive/remote-download/tasks",
        json={"url": "file:///etc/passwd", "privacy_mode": "standard_plain"},
    )
    assert blocked_task.status_code == 400
    assert "http" in blocked_task.get_json()["msg"]


def test_remote_download_saves_to_cloud_drive_and_storage(tmp_path, monkeypatch):
    db_path = tmp_path / "drive.db"
    storage_root = tmp_path / "storage"
    storage_root.mkdir()
    _init_db(db_path)
    actor_box = {"actor": _actor(1, "alice")}
    client = _build_app(db_path, storage_root, actor_box).test_client()

    source = tmp_path / "remote.txt"
    source.write_text("remote content", encoding="utf-8")

    class FakeDownloaded:
        path = str(source)
        filename = "remote.txt"
        mimetype = "text/plain"
        cleanup_dir = None

    def fake_download(url, **kwargs):
        assert url == "https://example.test/remote.txt"
        assert kwargs["max_bytes"] > 0
        return FakeDownloaded()

    monkeypatch.setattr("routes.files.download_remote_url", fake_download)
    res = client.post(
        "/api/cloud-drive/remote-download",
        json={
            "url": "https://example.test/remote.txt",
            "privacy_mode": "standard_plain",
            "virtual_path": "/Downloads/remote.txt",
        },
    )
    body = res.get_json()

    assert res.status_code == 200
    assert body["file"]["filename"] == "remote.txt"
    assert body["storage_file"]["virtual_path"] == "/Downloads/remote.txt"


def test_remote_download_task_reports_progress_and_completion(tmp_path, monkeypatch):
    db_path = tmp_path / "drive.db"
    storage_root = tmp_path / "storage"
    storage_root.mkdir()
    _init_db(db_path)
    actor_box = {"actor": _actor(1, "alice")}
    client = _build_app(db_path, storage_root, actor_box).test_client()

    source = tmp_path / "remote-task.txt"
    source.write_text("remote task content", encoding="utf-8")

    class FakeDownloaded:
        path = str(source)
        filename = "remote-task.txt"
        mimetype = "text/plain"
        cleanup_dir = None

    def fake_download(url, **kwargs):
        progress = kwargs.get("progress_callback")
        assert progress
        progress({"phase": "downloading", "filename": "remote-task.txt", "loaded_bytes": 5, "total_bytes": 20})
        progress({"phase": "downloaded", "filename": "remote-task.txt", "loaded_bytes": 20, "total_bytes": 20})
        return FakeDownloaded()

    monkeypatch.setattr("routes.files.download_remote_url", fake_download)
    created = client.post(
        "/api/cloud-drive/remote-download/tasks",
        json={
            "url": "https://93.184.216.34/remote-task.txt",
            "privacy_mode": "standard_plain",
            "virtual_path": "/Downloads/remote-task.txt",
        },
    )
    assert created.status_code == 202
    task_id = created.get_json()["task"]["id"]

    body = {}
    for _ in range(30):
        status = client.get(f"/api/cloud-drive/remote-download/tasks/{task_id}")
        assert status.status_code == 200
        body = status.get_json()["task"]
        if body["status"] == "completed":
            break
        time.sleep(0.02)

    assert body["status"] == "completed"
    assert body["progress_percent"] == 100
    assert body["file"]["filename"] == "remote-task.txt"
    assert body["file"]["size_bytes"] == len(source.read_bytes())
    assert body["loaded_bytes"] == len(source.read_bytes())
    assert body["total_bytes"] == len(source.read_bytes())
    assert body["storage_file"]["virtual_path"] == "/Downloads/remote-task.txt"


def test_remote_download_task_direct_mode_keeps_torrent_file(tmp_path, monkeypatch):
    db_path = tmp_path / "drive.db"
    storage_root = tmp_path / "storage"
    storage_root.mkdir()
    _init_db(db_path)
    actor_box = {"actor": _actor(1, "alice")}
    client = _build_app(db_path, storage_root, actor_box).test_client()

    source = tmp_path / "sample.torrent"
    source.write_bytes(b"d8:announce0:e")
    captured = {}

    class FakeDownloaded:
        path = str(source)
        filename = "sample.torrent"
        mimetype = "application/x-bittorrent"
        cleanup_dir = None

    def fake_download(url, **kwargs):
        captured["url"] = url
        captured["treat_torrent_as_bt"] = kwargs.get("treat_torrent_as_bt")
        return FakeDownloaded()

    monkeypatch.setattr("routes.files.download_remote_url", fake_download)
    created = client.post(
        "/api/cloud-drive/remote-download/tasks",
        json={
            "url": "https://93.184.216.34/sample.torrent",
            "download_mode": "direct",
            "privacy_mode": "standard_plain",
            "virtual_path": "/Downloads/sample.torrent",
        },
    )
    assert created.status_code == 202
    task = created.get_json()["task"]
    assert task["source_type"] == "direct"
    task_id = task["id"]

    body = {}
    for _ in range(30):
        status = client.get(f"/api/cloud-drive/remote-download/tasks/{task_id}")
        assert status.status_code == 200
        body = status.get_json()["task"]
        if body["status"] == "completed":
            break
        time.sleep(0.02)

    assert captured["url"] == "https://93.184.216.34/sample.torrent"
    assert captured["treat_torrent_as_bt"] is False
    assert body["status"] == "completed"
    assert body["file"]["filename"] == "sample.torrent"


def test_remote_download_task_bt_mode_torrent_url_downloads_payload(tmp_path, monkeypatch):
    db_path = tmp_path / "drive.db"
    storage_root = tmp_path / "storage"
    storage_root.mkdir()
    _init_db(db_path)
    actor_box = {"actor": _actor(1, "alice")}
    client = _build_app(db_path, storage_root, actor_box).test_client()

    source = tmp_path / "bt-payload.txt"
    source.write_text("bt payload", encoding="utf-8")
    captured = {}

    class FakeDownloaded:
        path = str(source)
        filename = "bt-payload.txt"
        mimetype = "text/plain"
        cleanup_dir = None

    def fake_download(url, **kwargs):
        captured["url"] = url
        progress = kwargs.get("progress_callback")
        assert progress
        progress({"phase": "downloading", "filename": "sample.torrent", "loaded_bytes": 1, "total_bytes": None})
        return FakeDownloaded()

    monkeypatch.setattr("routes.files.download_torrent_url_with_aria2", fake_download)
    created = client.post(
        "/api/cloud-drive/remote-download/tasks",
        json={
            "url": "https://93.184.216.34/sample.torrent",
            "download_mode": "bt",
            "privacy_mode": "standard_plain",
            "virtual_path": "/Downloads/bt-payload.txt",
        },
    )
    assert created.status_code == 202
    task = created.get_json()["task"]
    assert task["source_type"] == "torrent_url"
    task_id = task["id"]

    body = {}
    for _ in range(30):
        status = client.get(f"/api/cloud-drive/remote-download/tasks/{task_id}")
        assert status.status_code == 200
        body = status.get_json()["task"]
        if body["status"] == "completed":
            break
        time.sleep(0.02)

    assert captured["url"] == "https://93.184.216.34/sample.torrent"
    assert body["status"] == "completed"
    assert body["file"]["filename"] == "bt-payload.txt"


def test_remote_download_task_list_restores_refresh_state(tmp_path, monkeypatch):
    db_path = tmp_path / "drive.db"
    storage_root = tmp_path / "storage"
    storage_root.mkdir()
    _init_db(db_path)
    actor_box = {"actor": _actor(1, "alice")}
    client = _build_app(db_path, storage_root, actor_box).test_client()

    source = tmp_path / "refresh-task.txt"
    source.write_text("refresh task content", encoding="utf-8")

    class FakeDownloaded:
        path = str(source)
        filename = "refresh-task.txt"
        mimetype = "text/plain"
        cleanup_dir = None

    def fake_download(url, **kwargs):
        progress = kwargs.get("progress_callback")
        assert progress
        progress({"phase": "downloading", "filename": "refresh-task.txt", "loaded_bytes": 3, "total_bytes": 30})
        time.sleep(0.05)
        progress({"phase": "downloaded", "filename": "refresh-task.txt", "loaded_bytes": 30, "total_bytes": 30})
        return FakeDownloaded()

    monkeypatch.setattr("routes.files.download_remote_url", fake_download)
    created = client.post(
        "/api/cloud-drive/remote-download/tasks",
        json={
            "url": "https://93.184.216.34/refresh-task.txt",
            "privacy_mode": "standard_plain",
            "virtual_path": "/Downloads/refresh-task.txt",
        },
    )
    assert created.status_code == 202
    task_id = created.get_json()["task"]["id"]

    listed = client.get("/api/cloud-drive/remote-download/tasks")
    assert listed.status_code == 200
    tasks = listed.get_json()["tasks"]
    assert any(task["id"] == task_id for task in tasks)

    # Wait for background thread to finish so user slot is released before next test.
    for _ in range(50):
        status = client.get(f"/api/cloud-drive/remote-download/tasks/{task_id}")
        if status.get_json()["task"]["status"] != "running":
            break
        time.sleep(0.02)


def test_remote_download_stale_running_task_does_not_block_new_task(tmp_path, monkeypatch):
    db_path = tmp_path / "drive.db"
    storage_root = tmp_path / "storage"
    storage_root.mkdir()
    _init_db(db_path)
    actor_box = {"actor": _actor(1, "alice")}
    client = _build_app(db_path, storage_root, actor_box).test_client()

    with files_routes._REMOTE_DOWNLOAD_TASKS_LOCK:
        files_routes._REMOTE_DOWNLOAD_TASKS.clear()
        files_routes._REMOTE_DOWNLOAD_ACTIVE_USERS.clear()
        files_routes._REMOTE_DOWNLOAD_TASKS["stale-task"] = {
            "id": "stale-task",
            "kind": "remote_download",
            "source_type": "url",
            "status": "running",
            "phase": "downloading",
            "filename": "",
            "url": "https://93.184.216.34/stale.txt",
            "owner_user_id": 1,
            "actor": dict(actor_box["actor"]),
            "privacy_mode": "standard_plain",
            "virtual_path": "",
            "timeout_seconds": 1,
            "loaded_bytes": 0,
            "total_bytes": None,
            "progress_percent": 0,
            "msg": "舊任務",
            "error": "",
            "file": None,
            "storage_file": None,
            "created_at": "2000-01-01T00:00:00",
            "updated_at": "2000-01-01T00:00:00",
        }
        files_routes._REMOTE_DOWNLOAD_ACTIVE_USERS.add(1)

    source = tmp_path / "fresh-task.txt"
    source.write_text("fresh task content", encoding="utf-8")

    class FakeDownloaded:
        path = str(source)
        filename = "fresh-task.txt"
        mimetype = "text/plain"
        cleanup_dir = None

    monkeypatch.setattr("routes.files.download_remote_url", lambda url, **kwargs: FakeDownloaded())
    created = client.post(
        "/api/cloud-drive/remote-download/tasks",
        json={
            "url": "https://93.184.216.34/fresh-task.txt",
            "privacy_mode": "standard_plain",
            "virtual_path": "/Downloads/fresh-task.txt",
        },
    )
    assert created.status_code == 202
    fresh_task_id = created.get_json()["task"]["id"]

    listed = client.get("/api/cloud-drive/remote-download/tasks")
    assert listed.status_code == 200
    stale = next(task for task in listed.get_json()["tasks"] if task["id"] == "stale-task")
    assert stale["status"] == "failed"
    assert "逾時" in stale["msg"]

    removed = client.delete("/api/cloud-drive/remote-download/tasks/stale-task")
    assert removed.status_code == 200
    assert removed.get_json()["removed"] is True
    listed_after_remove = client.get("/api/cloud-drive/remote-download/tasks")
    assert all(task["id"] != "stale-task" for task in listed_after_remove.get_json()["tasks"])

    # Wait for the fresh task's background thread to finish so it releases
    # the user slot in _REMOTE_DOWNLOAD_ACTIVE_USERS before the next test runs.
    for _ in range(50):
        status = client.get(f"/api/cloud-drive/remote-download/tasks/{fresh_task_id}")
        if status.get_json()["task"]["status"] != "running":
            break
        time.sleep(0.02)


def test_remote_download_task_accepts_uploaded_torrent_file(tmp_path, monkeypatch):
    db_path = tmp_path / "drive.db"
    storage_root = tmp_path / "storage"
    storage_root.mkdir()
    _init_db(db_path)
    actor_box = {"actor": _actor(1, "alice")}
    client = _build_app(db_path, storage_root, actor_box).test_client()

    source = tmp_path / "torrent-result.txt"
    source.write_text("torrent task content", encoding="utf-8")
    captured = {}

    class FakeDownloaded:
        path = str(source)
        filename = "torrent-result.txt"
        mimetype = "text/plain"
        cleanup_dir = None

    def fake_download(torrent_path, **kwargs):
        captured["torrent_path"] = torrent_path
        captured["display_name"] = kwargs.get("display_name")
        progress = kwargs.get("progress_callback")
        assert torrent_path.endswith("sample.torrent")
        assert progress
        progress({"phase": "downloading", "filename": "sample.torrent", "loaded_bytes": 0, "total_bytes": None})
        return FakeDownloaded()

    monkeypatch.setattr("routes.files.download_torrent_file_with_aria2", fake_download)
    created = client.post(
        "/api/cloud-drive/remote-download/torrent-tasks",
        data={
            "torrent_file": (io.BytesIO(b"d8:announce0:e"), "sample.torrent"),
            "privacy_mode": "standard_plain",
            "virtual_path": "/Downloads/torrent-result.txt",
        },
    )
    assert created.status_code == 202
    task = created.get_json()["task"]
    assert task["source_type"] == "torrent_file"
    assert task["torrent_filename"] == "sample.torrent"
    task_id = task["id"]

    body = {}
    for _ in range(30):
        status = client.get(f"/api/cloud-drive/remote-download/tasks/{task_id}")
        assert status.status_code == 200
        body = status.get_json()["task"]
        if body["status"] == "completed":
            break
        time.sleep(0.02)

    assert captured["display_name"] == "sample.torrent"
    assert body["status"] == "completed"
    assert body["file"]["filename"] == "torrent-result.txt"
    assert body["storage_file"]["virtual_path"] == "/Downloads/torrent-result.txt"


def test_remote_download_torrent_upload_rejects_non_torrent(tmp_path):
    db_path = tmp_path / "drive.db"
    storage_root = tmp_path / "storage"
    storage_root.mkdir()
    _init_db(db_path)
    actor_box = {"actor": _actor(1, "alice")}
    client = _build_app(db_path, storage_root, actor_box).test_client()

    res = client.post(
        "/api/cloud-drive/remote-download/torrent-tasks",
        data={"torrent_file": (io.BytesIO(b"not torrent"), "note.txt")},
    )

    assert res.status_code == 400
    assert ".torrent" in res.get_json()["msg"]
