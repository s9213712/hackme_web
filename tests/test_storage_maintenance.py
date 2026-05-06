import sqlite3
from datetime import datetime, timedelta

from services.storage_albums import ensure_storage_album_schema
from services.storage.maintenance import (
    run_storage_maintenance,
    run_storage_maintenance_if_due,
    storage_maintenance_status,
)
from services.storage.quota_enforcement import ensure_storage_quota_enforcement_schema


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


def test_storage_maintenance_syncs_quota_and_purges_old_trash():
    conn = _conn()
    now = datetime(2026, 4, 27, 12, 0, 0)
    old = (now - timedelta(days=31)).isoformat()
    conn.execute("INSERT INTO users (id, username) VALUES (1, 'alice')")
    conn.execute("INSERT INTO uploaded_files (id, owner_user_id, storage_path, size_bytes, deleted_at) VALUES ('f1', 1, 'users/1/f1/a.txt', 10, NULL)")
    conn.execute(
        """
        INSERT INTO storage_files (
            id, file_id, owner_user_id, display_name, virtual_path, is_trashed,
            trashed_at, created_at, updated_at
        ) VALUES ('sf1', 'f1', 1, 'a.txt', '/a.txt', 1, ?, ?, ?)
        """,
        (old, old, old),
    )

    result = run_storage_maintenance(conn, actor_user_id=0, retention_days=30, now=now)
    row = conn.execute("SELECT deleted_at FROM storage_files WHERE id='sf1'").fetchone()
    summary = conn.execute("SELECT used_bytes, file_count FROM user_storage WHERE user_id=1").fetchone()

    assert result["purged_trash_entries"] == 1
    assert row["deleted_at"] is not None
    assert summary["used_bytes"] == 0
    assert summary["file_count"] == 0


def test_storage_maintenance_due_logic_updates_last_date():
    conn = _conn()
    conn.execute("INSERT INTO users (id, username) VALUES (1, 'alice')")
    saved = {}
    now = datetime(2026, 4, 27, 5, 0, 0)
    settings = {
        "storage_maintenance_auto_enabled": True,
        "storage_maintenance_daily_time": "04:00",
        "storage_maintenance_last_date": "",
        "storage_trash_retention_days": 30,
    }

    status = storage_maintenance_status(settings, now=now)
    result = run_storage_maintenance_if_due(conn, settings=settings, save_settings=saved.update, now=now)

    assert status["due"] is True
    assert result["ran"] is True
    assert saved["storage_maintenance_last_date"] == "2026-04-27"


def test_storage_maintenance_purges_expired_quota_reduction_overage():
    conn = _conn()
    now = datetime(2026, 4, 27, 12, 0, 0)
    old = (now - timedelta(days=2)).isoformat()
    conn.execute("INSERT INTO users (id, username) VALUES (1, 'alice')")
    conn.execute(
        """
        INSERT INTO uploaded_files (id, owner_user_id, storage_path, size_bytes, deleted_at, created_at)
        VALUES
          ('old', 1, 'users/1/old.bin', ?, NULL, ?),
          ('new', 1, 'users/1/new.bin', ?, NULL, ?)
        """,
        (
            70 * 1024 * 1024,
            (now - timedelta(days=3)).isoformat(),
            50 * 1024 * 1024,
            (now - timedelta(days=1)).isoformat(),
        ),
    )
    conn.execute(
        """
        INSERT INTO storage_files (
            id, file_id, owner_user_id, display_name, virtual_path, is_trashed,
            created_at, updated_at
        ) VALUES
          ('sf_old', 'old', 1, 'old.bin', '/old.bin', 0, ?, ?),
          ('sf_new', 'new', 1, 'new.bin', '/new.bin', 0, ?, ?)
        """,
        (old, old, old, old),
    )
    ensure_storage_quota_enforcement_schema(conn)
    conn.execute(
        """
        INSERT INTO storage_quota_reduction_notices (
            id, user_id, old_level, new_level, old_quota_bytes, new_quota_bytes,
            used_bytes_at_notice, deadline_at, status, notice_message, created_at
        ) VALUES ('n1', 1, 'vip', 'normal', ?, ?, ?, ?, 'pending', 'backup warning', ?)
        """,
        (2048 * 1024 * 1024, 100 * 1024 * 1024, 120 * 1024 * 1024, old, old),
    )

    result = run_storage_maintenance(conn, actor_user_id=0, retention_days=30, now=now)
    notice = conn.execute("SELECT status, deleted_file_count, deleted_bytes FROM storage_quota_reduction_notices WHERE id='n1'").fetchone()
    old_file = conn.execute("SELECT deleted_at FROM uploaded_files WHERE id='old'").fetchone()
    new_file = conn.execute("SELECT deleted_at FROM uploaded_files WHERE id='new'").fetchone()
    summary = conn.execute("SELECT used_bytes, file_count FROM user_storage WHERE user_id=1").fetchone()

    assert result["quota_enforcement"]["processed"] == 1
    assert notice["status"] == "purged"
    assert notice["deleted_file_count"] == 1
    assert notice["deleted_bytes"] == 50 * 1024 * 1024
    assert old_file["deleted_at"] is None
    assert new_file["deleted_at"] is not None
    assert summary["used_bytes"] == 70 * 1024 * 1024
    assert summary["file_count"] == 1
