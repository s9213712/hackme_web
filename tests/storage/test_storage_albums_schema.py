import sqlite3

from services.storage.storage_albums import ensure_storage_album_schema


def test_storage_album_schema_creates_core_tables_and_indexes():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("CREATE TABLE users (id INTEGER PRIMARY KEY)")
    conn.execute("CREATE TABLE uploaded_files (id TEXT PRIMARY KEY)")

    ensure_storage_album_schema(conn)

    tables = {
        row["name"]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    }
    storage_cols = {row["name"] for row in conn.execute("PRAGMA table_info(storage_files)").fetchall()}
    quota_cols = {row["name"] for row in conn.execute("PRAGMA table_info(storage_quota_log)").fetchall()}
    share_cols = {row["name"] for row in conn.execute("PRAGMA table_info(storage_share_links)").fetchall()}
    album_share_cols = {row["name"] for row in conn.execute("PRAGMA table_info(album_share_links)").fetchall()}
    album_cols = {row["name"] for row in conn.execute("PRAGMA table_info(albums)").fetchall()}
    album_file_cols = {row["name"] for row in conn.execute("PRAGMA table_info(album_files)").fetchall()}
    indexes = {
        row["name"]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type='index'").fetchall()
    }

    assert {"user_storage", "storage_files", "storage_quota_log", "albums", "album_files", "storage_share_links", "album_share_links"} <= tables
    assert {"file_id", "owner_user_id", "virtual_path", "is_trashed", "trashed_at", "deleted_at"} <= storage_cols
    assert {"delta_bytes", "before_used_bytes", "after_used_bytes", "source", "actor_user_id"} <= quota_cols
    assert {
        "storage_file_id",
        "token",
        "token_hash",
        "access_scope",
        "required_user_id",
        "max_views",
        "wrapped_file_key_envelope",
        "expires_at",
        "revoked_at",
        "access_count",
    } <= share_cols
    assert {"album_id", "owner_user_id", "token_hash", "revoked_at", "access_count", "password_required", "password_hash"} <= album_share_cols
    assert {"owner_user_id", "title", "visibility", "cover_file_id"} <= album_cols
    assert {"album_id", "storage_file_id", "file_id", "sort_order", "added_by"} <= album_file_cols
    assert {"idx_storage_files_owner_path", "idx_album_files_album", "idx_album_share_links_album"} <= indexes
