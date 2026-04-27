import uuid
from datetime import datetime


def _now():
    return datetime.now().isoformat()


def ensure_storage_album_schema(conn):
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS user_storage (
            user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
            quota_bytes INTEGER NOT NULL DEFAULT 0,
            used_bytes INTEGER NOT NULL DEFAULT 0,
            reserved_bytes INTEGER NOT NULL DEFAULT 0,
            file_count INTEGER NOT NULL DEFAULT 0,
            updated_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS storage_files (
            id TEXT PRIMARY KEY,
            file_id TEXT NOT NULL REFERENCES uploaded_files(id) ON DELETE CASCADE,
            owner_user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            parent_id TEXT REFERENCES storage_files(id) ON DELETE SET NULL,
            display_name TEXT NOT NULL,
            virtual_path TEXT NOT NULL,
            is_trashed INTEGER NOT NULL DEFAULT 0,
            trashed_at TEXT,
            restored_at TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            deleted_at TEXT,
            UNIQUE(owner_user_id, virtual_path)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS storage_quota_log (
            id TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            file_id TEXT REFERENCES uploaded_files(id) ON DELETE SET NULL,
            delta_bytes INTEGER NOT NULL,
            before_used_bytes INTEGER NOT NULL,
            after_used_bytes INTEGER NOT NULL,
            source TEXT NOT NULL,
            reason TEXT,
            actor_user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
            created_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS albums (
            id TEXT PRIMARY KEY,
            owner_user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            title TEXT NOT NULL,
            description TEXT,
            visibility TEXT NOT NULL DEFAULT 'private',
            cover_file_id TEXT REFERENCES uploaded_files(id) ON DELETE SET NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            deleted_at TEXT
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS album_files (
            id TEXT PRIMARY KEY,
            album_id TEXT NOT NULL REFERENCES albums(id) ON DELETE CASCADE,
            storage_file_id TEXT REFERENCES storage_files(id) ON DELETE SET NULL,
            file_id TEXT NOT NULL REFERENCES uploaded_files(id) ON DELETE CASCADE,
            sort_order INTEGER NOT NULL DEFAULT 0,
            caption TEXT,
            added_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
            created_at TEXT NOT NULL,
            deleted_at TEXT,
            UNIQUE(album_id, file_id)
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_storage_files_owner_path ON storage_files(owner_user_id, virtual_path)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_storage_files_file ON storage_files(file_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_storage_quota_log_user ON storage_quota_log(user_id, created_at)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_albums_owner ON albums(owner_user_id, created_at)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_album_files_album ON album_files(album_id, sort_order, created_at)")


def normalize_virtual_path(path, display_name=None):
    raw = str(path or "").replace("\\", "/").strip()
    if not raw:
        raw = str(display_name or "").strip()
    if not raw:
        raw = "untitled"
    parts = []
    for part in raw.split("/"):
        cleaned = part.strip()
        if not cleaned:
            continue
        if cleaned in {".", ".."} or "\x00" in cleaned:
            raise ValueError("invalid storage path")
        parts.append(cleaned[:120])
    if not parts:
        raise ValueError("invalid storage path")
    return "/" + "/".join(parts)


def get_user_storage_summary(conn, user_id):
    ensure_storage_album_schema(conn)
    row = conn.execute("SELECT * FROM user_storage WHERE user_id=?", (int(user_id),)).fetchone()
    if row:
        return dict(row)
    now = _now()
    conn.execute(
        "INSERT INTO user_storage (user_id, quota_bytes, used_bytes, reserved_bytes, file_count, updated_at) VALUES (?, 0, 0, 0, 0, ?)",
        (int(user_id), now),
    )
    return {
        "user_id": int(user_id),
        "quota_bytes": 0,
        "used_bytes": 0,
        "reserved_bytes": 0,
        "file_count": 0,
        "updated_at": now,
    }


def _recalculate_storage_usage(conn, user_id):
    row = conn.execute(
        """
        SELECT COALESCE(SUM(f.size_bytes), 0) AS used_bytes, COUNT(sf.id) AS file_count
        FROM storage_files sf
        JOIN uploaded_files f ON f.id=sf.file_id
        WHERE sf.owner_user_id=? AND sf.deleted_at IS NULL AND f.deleted_at IS NULL
        """,
        (int(user_id),),
    ).fetchone()
    return int(row["used_bytes"] or 0), int(row["file_count"] or 0)


def sync_user_storage_summary(conn, user_id, *, actor_user_id=None, source="system", reason="sync"):
    ensure_storage_album_schema(conn)
    before = get_user_storage_summary(conn, user_id)
    used_bytes, file_count = _recalculate_storage_usage(conn, user_id)
    now = _now()
    conn.execute(
        """
        UPDATE user_storage
        SET used_bytes=?, file_count=?, updated_at=?
        WHERE user_id=?
        """,
        (used_bytes, file_count, now, int(user_id)),
    )
    delta = used_bytes - int(before.get("used_bytes") or 0)
    if delta:
        conn.execute(
            """
            INSERT INTO storage_quota_log (
                id, user_id, file_id, delta_bytes, before_used_bytes, after_used_bytes,
                source, reason, actor_user_id, created_at
            ) VALUES (?, ?, NULL, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                uuid.uuid4().hex,
                int(user_id),
                delta,
                int(before.get("used_bytes") or 0),
                used_bytes,
                str(source or "system")[:50],
                str(reason or "")[:200],
                actor_user_id,
                now,
            ),
        )
    return get_user_storage_summary(conn, user_id)


def create_storage_file_entry(conn, *, actor, file_row, virtual_path=None, display_name=None, source="upload"):
    ensure_storage_album_schema(conn)
    owner_user_id = int(file_row["owner_user_id"])
    if owner_user_id != int(actor["id"]):
        return None, "只能加入自己的檔案到 storage"
    display_name = str(display_name or file_row["original_filename_plain_for_public"] or "download.bin").strip()[:160]
    try:
        normalized_path = normalize_virtual_path(virtual_path, display_name)
    except ValueError:
        return None, "storage path 不安全或格式錯誤"
    existing = conn.execute(
        "SELECT id FROM storage_files WHERE owner_user_id=? AND virtual_path=? AND deleted_at IS NULL",
        (owner_user_id, normalized_path),
    ).fetchone()
    if existing:
        return None, "storage path 已存在"
    now = _now()
    storage_id = uuid.uuid4().hex
    before = get_user_storage_summary(conn, owner_user_id)
    after_used = int(before.get("used_bytes") or 0) + int(file_row["size_bytes"] or 0)
    conn.execute(
        """
        INSERT INTO storage_files (
            id, file_id, owner_user_id, parent_id, display_name, virtual_path,
            is_trashed, created_at, updated_at
        ) VALUES (?, ?, ?, NULL, ?, ?, 0, ?, ?)
        """,
        (storage_id, file_row["id"], owner_user_id, display_name, normalized_path, now, now),
    )
    conn.execute(
        """
        INSERT INTO storage_quota_log (
            id, user_id, file_id, delta_bytes, before_used_bytes, after_used_bytes,
            source, reason, actor_user_id, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            uuid.uuid4().hex,
            owner_user_id,
            file_row["id"],
            int(file_row["size_bytes"] or 0),
            int(before.get("used_bytes") or 0),
            after_used,
            str(source or "upload")[:50],
            "storage_file_created",
            int(actor["id"]),
            now,
        ),
    )
    conn.execute(
        """
        INSERT INTO user_storage (user_id, quota_bytes, used_bytes, reserved_bytes, file_count, updated_at)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET used_bytes=excluded.used_bytes, file_count=user_storage.file_count + 1, updated_at=excluded.updated_at
        """,
        (
            owner_user_id,
            int(before.get("quota_bytes") or 0),
            after_used,
            int(before.get("reserved_bytes") or 0),
            int(before.get("file_count") or 0) + 1,
            now,
        ),
    )
    return get_storage_file(conn, actor=actor, storage_file_id=storage_id), None


def get_storage_file(conn, *, actor, storage_file_id):
    ensure_storage_album_schema(conn)
    row = conn.execute(
        """
        SELECT sf.*, f.size_bytes, f.privacy_mode, f.risk_level, f.scan_status,
               f.original_filename_plain_for_public, f.deleted_at AS file_deleted_at
        FROM storage_files sf
        JOIN uploaded_files f ON f.id=sf.file_id
        WHERE sf.id=?
        """,
        (storage_file_id,),
    ).fetchone()
    if not row:
        return None
    if int(row["owner_user_id"]) != int(actor["id"]):
        return None
    return dict(row)


def list_storage_files(conn, *, actor, include_trashed=False, limit=100, offset=0):
    ensure_storage_album_schema(conn)
    where = "sf.owner_user_id=? AND sf.deleted_at IS NULL AND f.deleted_at IS NULL"
    params = [int(actor["id"])]
    if not include_trashed:
        where += " AND sf.is_trashed=0"
    rows = conn.execute(
        f"""
        SELECT sf.*, f.size_bytes, f.privacy_mode, f.risk_level, f.scan_status,
               f.original_filename_plain_for_public
        FROM storage_files sf
        JOIN uploaded_files f ON f.id=sf.file_id
        WHERE {where}
        ORDER BY sf.virtual_path ASC
        LIMIT ? OFFSET ?
        """,
        (*params, int(limit), int(offset)),
    ).fetchall()
    return [dict(row) for row in rows]
