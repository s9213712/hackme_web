import sqlite3

from services.storage.catalog import (
    ensure_storage_album_schema,
    purge_storage_trash,
    sync_user_storage_summary,
)


def _conn():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, username TEXT)")
    conn.execute(
        """
        CREATE TABLE uploaded_files (
            id TEXT PRIMARY KEY,
            owner_user_id INTEGER,
            storage_path TEXT,
            size_bytes INTEGER,
            deleted_at TEXT,
            created_at TEXT,
            updated_at TEXT
        )
        """
    )
    ensure_storage_album_schema(conn)
    return conn


def test_storage_trash_purge_deletes_uploaded_file_and_physical_blob(tmp_path):
    conn = _conn()
    storage_root = tmp_path / "storage"
    blob = storage_root / "users" / "1" / "f1" / "a.txt"
    blob.parent.mkdir(parents=True)
    blob.write_bytes(b"abc")
    conn.execute("INSERT INTO users (id, username) VALUES (1, 'alice')")
    conn.execute(
        """
        INSERT INTO uploaded_files (
            id, owner_user_id, storage_path, size_bytes, deleted_at, created_at, updated_at
        ) VALUES ('f1', 1, 'users/1/f1/a.txt', 3, NULL, '2026-05-31T00:00:00', '2026-05-31T00:00:00')
        """
    )
    conn.execute(
        """
        INSERT INTO storage_files (
            id, file_id, owner_user_id, display_name, virtual_path, is_trashed,
            trashed_at, created_at, updated_at
        ) VALUES ('sf1', 'f1', 1, 'a.txt', '/a.txt', 1, '2026-05-31T00:00:00', '2026-05-31T00:00:00', '2026-05-31T00:00:00')
        """
    )
    sync_user_storage_summary(conn, 1)

    result, msg = purge_storage_trash(
        conn,
        actor={"id": 1},
        storage_root=storage_root,
    )

    uploaded = conn.execute("SELECT deleted_at FROM uploaded_files WHERE id='f1'").fetchone()
    summary = conn.execute("SELECT used_bytes, file_count FROM user_storage WHERE user_id=1").fetchone()
    assert msg is None
    assert result["purged"] == 1
    assert result["purged_file_ids"] == ["f1"]
    assert result["removed_physical_files"] == 1
    assert uploaded["deleted_at"] is not None
    assert summary["used_bytes"] == 0
    assert summary["file_count"] == 0
    assert not blob.exists()
