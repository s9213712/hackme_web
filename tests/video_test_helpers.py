import sqlite3

from services.videos import ensure_video_schema


def video_test_db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE users (
            id INTEGER PRIMARY KEY,
            username TEXT NOT NULL,
            nickname TEXT,
            role TEXT NOT NULL DEFAULT 'user',
            status TEXT NOT NULL DEFAULT 'active'
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE uploaded_files (
            id TEXT PRIMARY KEY,
            owner_user_id INTEGER NOT NULL,
            storage_path TEXT NOT NULL,
            privacy_mode TEXT NOT NULL DEFAULT 'standard_plain',
            risk_level TEXT NOT NULL DEFAULT 'low',
            scan_status TEXT NOT NULL DEFAULT 'clean',
            original_filename_plain_for_public TEXT,
            mime_type_plain_for_public TEXT,
            size_bytes INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT '2026-01-01T00:00:00',
            updated_at TEXT,
            deleted_at TEXT
        )
        """
    )
    conn.executemany(
        "INSERT INTO users (id, username, nickname, role, status) VALUES (?, ?, ?, ?, 'active')",
        [
            (1, "owner", "Owner", "user"),
            (2, "viewer", "Viewer", "user"),
            (3, "manager", "Manager", "manager"),
            (9, "root", "Root", "super_admin"),
        ],
    )
    ensure_video_schema(conn)
    return conn


def actor(user_id, username, role="user"):
    return {"id": user_id, "username": username, "role": role, "status": "active"}


def seed_cloud_file(conn, *, file_id="file-video", owner_user_id=1, mime="video/mp4", privacy_mode="standard_plain"):
    conn.execute(
        """
        INSERT INTO uploaded_files (
            id, owner_user_id, storage_path, privacy_mode, risk_level, scan_status,
            original_filename_plain_for_public, mime_type_plain_for_public, size_bytes
        ) VALUES (?, ?, ?, ?, 'low', 'clean', ?, ?, 128)
        """,
        (file_id, owner_user_id, f"users/{owner_user_id}/{file_id}/clip.mp4", privacy_mode, "clip.mp4", mime),
    )
    return file_id
