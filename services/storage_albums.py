import hashlib
import secrets
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
            trash_source TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            deleted_at TEXT,
            UNIQUE(owner_user_id, virtual_path)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS storage_folders (
            id TEXT PRIMARY KEY,
            owner_user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            display_name TEXT NOT NULL,
            virtual_path TEXT NOT NULL,
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
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS storage_share_links (
            id TEXT PRIMARY KEY,
            storage_file_id TEXT NOT NULL REFERENCES storage_files(id) ON DELETE CASCADE,
            file_id TEXT NOT NULL REFERENCES uploaded_files(id) ON DELETE CASCADE,
            owner_user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            token_hash TEXT NOT NULL UNIQUE,
            can_download INTEGER NOT NULL DEFAULT 1,
            can_preview INTEGER NOT NULL DEFAULT 0,
            expires_at TEXT,
            revoked_at TEXT,
            access_count INTEGER NOT NULL DEFAULT 0,
            last_accessed_at TEXT,
            created_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
            created_at TEXT NOT NULL
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_storage_files_owner_path ON storage_files(owner_user_id, virtual_path)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_storage_files_file ON storage_files(file_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_storage_folders_owner_path ON storage_folders(owner_user_id, virtual_path)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_storage_quota_log_user ON storage_quota_log(user_id, created_at)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_albums_owner ON albums(owner_user_id, created_at)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_album_files_album ON album_files(album_id, sort_order, created_at)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_storage_share_links_owner ON storage_share_links(owner_user_id, created_at)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_storage_share_links_file ON storage_share_links(storage_file_id, revoked_at)")
    storage_file_cols = {row["name"] for row in conn.execute("PRAGMA table_info(storage_files)").fetchall()}
    if "trash_source" not in storage_file_cols:
        conn.execute("ALTER TABLE storage_files ADD COLUMN trash_source TEXT")


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


def _display_name_from_path(path):
    return str(path or "").rstrip("/").split("/")[-1] or "untitled"


def _folder_prefix(path):
    normalized = normalize_virtual_path(path, "folder")
    return normalized.rstrip("/")


def _is_path_inside(path, folder_path):
    return path == folder_path or path.startswith(folder_path.rstrip("/") + "/")


def _parent_folders_for_file(path):
    parts = [part for part in str(path or "").split("/") if part]
    folders = []
    for idx in range(1, len(parts)):
        folders.append("/" + "/".join(parts[:idx]))
    return folders


def _storage_path_exists(conn, owner_user_id, path):
    if conn.execute(
        "SELECT 1 FROM storage_files WHERE owner_user_id=? AND virtual_path=? LIMIT 1",
        (int(owner_user_id), path),
    ).fetchone():
        return True
    return bool(conn.execute(
        "SELECT 1 FROM storage_folders WHERE owner_user_id=? AND virtual_path=? LIMIT 1",
        (int(owner_user_id), path),
    ).fetchone())


def _unique_storage_path(conn, owner_user_id, desired_path, display_name):
    base_path = normalize_virtual_path(desired_path, display_name)
    if not _storage_path_exists(conn, owner_user_id, base_path):
        return base_path
    parent = "/" + "/".join(base_path.strip("/").split("/")[:-1])
    if parent == "/":
        parent = ""
    name = _display_name_from_path(base_path)
    stem, dot, ext = name.rpartition(".")
    if not stem:
        stem, dot, ext = name, "", ""
    for index in range(2, 1000):
        candidate_name = f"{stem} ({index}){dot}{ext}"
        candidate = f"{parent}/{candidate_name}" if parent else f"/{candidate_name}"
        if not _storage_path_exists(conn, owner_user_id, candidate):
            return candidate
    raise ValueError("storage path conflict")


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


def list_storage_folders(conn, *, actor):
    ensure_storage_album_schema(conn)
    owner_user_id = int(actor["id"])
    folders = {}
    explicit_rows = conn.execute(
        """
        SELECT * FROM storage_folders
        WHERE owner_user_id=? AND deleted_at IS NULL
        ORDER BY virtual_path ASC
        """,
        (owner_user_id,),
    ).fetchall()
    for row in explicit_rows:
        path = row["virtual_path"]
        folders[path] = {
            "id": row["id"],
            "display_name": row["display_name"],
            "virtual_path": path,
            "is_explicit": True,
            "file_count": 0,
            "recursive_file_count": 0,
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }
    file_rows = conn.execute(
        """
        SELECT virtual_path
        FROM storage_files
        WHERE owner_user_id=? AND deleted_at IS NULL AND is_trashed=0
        """,
        (owner_user_id,),
    ).fetchall()
    for row in file_rows:
        file_path = row["virtual_path"]
        parent_parts = _parent_folders_for_file(file_path)
        direct_parent = parent_parts[-1] if parent_parts else ""
        for folder_path in parent_parts:
            folders.setdefault(folder_path, {
                "id": None,
                "display_name": _display_name_from_path(folder_path),
                "virtual_path": folder_path,
                "is_explicit": False,
                "file_count": 0,
                "recursive_file_count": 0,
                "created_at": None,
                "updated_at": None,
            })
            folders[folder_path]["recursive_file_count"] += 1
        if direct_parent:
            folders[direct_parent]["file_count"] += 1
    return [folders[path] for path in sorted(folders)]


def create_storage_folder(conn, *, actor, path):
    ensure_storage_album_schema(conn)
    owner_user_id = int(actor["id"])
    try:
        folder_path = _folder_prefix(path)
    except ValueError:
        return None, "資料夾路徑不安全或格式錯誤"
    if conn.execute(
        "SELECT id FROM storage_files WHERE owner_user_id=? AND virtual_path=? AND deleted_at IS NULL",
        (owner_user_id, folder_path),
    ).fetchone():
        return None, "同路徑已有檔案"
    existing = conn.execute(
        "SELECT * FROM storage_folders WHERE owner_user_id=? AND virtual_path=? AND deleted_at IS NULL",
        (owner_user_id, folder_path),
    ).fetchone()
    if existing:
        return dict(existing), None
    now = _now()
    folder_id = uuid.uuid4().hex
    conn.execute(
        """
        INSERT INTO storage_folders (id, owner_user_id, display_name, virtual_path, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (folder_id, owner_user_id, _display_name_from_path(folder_path), folder_path, now, now),
    )
    return dict(conn.execute("SELECT * FROM storage_folders WHERE id=?", (folder_id,)).fetchone()), None


def move_storage_file(conn, *, actor, storage_file_id, new_virtual_path):
    ensure_storage_album_schema(conn)
    row = get_storage_file(conn, actor=actor, storage_file_id=storage_file_id)
    if not row or row.get("deleted_at") or int(row.get("is_trashed") or 0):
        return None, "找不到檔案或檔案已刪除"
    try:
        normalized_path = normalize_virtual_path(new_virtual_path, row.get("display_name"))
    except ValueError:
        return None, "storage path 不安全或格式錯誤"
    owner_user_id = int(actor["id"])
    conflict = conn.execute(
        """
        SELECT id FROM storage_files
        WHERE owner_user_id=? AND virtual_path=? AND deleted_at IS NULL AND id<>?
        """,
        (owner_user_id, normalized_path, storage_file_id),
    ).fetchone()
    if conflict:
        return None, "目標路徑已有檔案"
    now = _now()
    conn.execute(
        """
        UPDATE storage_files
        SET virtual_path=?, display_name=?, updated_at=?
        WHERE id=? AND owner_user_id=?
        """,
        (normalized_path, _display_name_from_path(normalized_path), now, storage_file_id, owner_user_id),
    )
    return get_storage_file(conn, actor=actor, storage_file_id=storage_file_id), None


def move_storage_folder(conn, *, actor, old_path, new_path):
    ensure_storage_album_schema(conn)
    owner_user_id = int(actor["id"])
    try:
        old_folder = _folder_prefix(old_path)
        new_folder = _folder_prefix(new_path)
    except ValueError:
        return None, "資料夾路徑不安全或格式錯誤"
    if old_folder == new_folder:
        return {"old_path": old_folder, "new_path": new_folder, "moved_files": 0, "moved_folders": 0}, None
    if _is_path_inside(new_folder, old_folder):
        return None, "不能把資料夾移到自己的子資料夾"

    files = conn.execute(
        """
        SELECT id, virtual_path FROM storage_files
        WHERE owner_user_id=? AND deleted_at IS NULL AND is_trashed=0 AND virtual_path LIKE ?
        ORDER BY virtual_path ASC
        """,
        (owner_user_id, old_folder.rstrip("/") + "/%"),
    ).fetchall()
    folders = conn.execute(
        """
        SELECT id, virtual_path FROM storage_folders
        WHERE owner_user_id=? AND deleted_at IS NULL AND (virtual_path=? OR virtual_path LIKE ?)
        ORDER BY virtual_path ASC
        """,
        (owner_user_id, old_folder, old_folder.rstrip("/") + "/%"),
    ).fetchall()
    if not files and not folders:
        return None, "找不到資料夾或資料夾是空的"

    file_updates = []
    moving_file_ids = {row["id"] for row in files}
    for row in files:
        suffix = row["virtual_path"][len(old_folder):]
        target_path = new_folder + suffix
        conflict = conn.execute(
            """
            SELECT id FROM storage_files
            WHERE owner_user_id=? AND virtual_path=? AND deleted_at IS NULL
            """,
            (owner_user_id, target_path),
        ).fetchone()
        if conflict and conflict["id"] not in moving_file_ids:
            return None, f"目標路徑已有檔案：{target_path}"
        file_updates.append((target_path, _display_name_from_path(target_path), row["id"]))

    folder_updates = []
    moving_folder_ids = {row["id"] for row in folders}
    for row in folders:
        suffix = row["virtual_path"][len(old_folder):]
        target_path = new_folder + suffix
        conflict = conn.execute(
            """
            SELECT id FROM storage_folders
            WHERE owner_user_id=? AND virtual_path=? AND deleted_at IS NULL
            """,
            (owner_user_id, target_path),
        ).fetchone()
        if conflict and conflict["id"] not in moving_folder_ids:
            return None, f"目標路徑已有資料夾：{target_path}"
        folder_updates.append((target_path, _display_name_from_path(target_path), row["id"]))

    now = _now()
    for target_path, display_name, row_id in file_updates:
        conn.execute(
            "UPDATE storage_files SET virtual_path=?, display_name=?, updated_at=? WHERE id=? AND owner_user_id=?",
            (target_path, display_name, now, row_id, owner_user_id),
        )
    if not folders:
        folder, msg = create_storage_folder(conn, actor=actor, path=new_folder)
        if msg:
            return None, msg
        folder_updates.append((new_folder, _display_name_from_path(new_folder), folder["id"]))
    for target_path, display_name, row_id in folder_updates:
        conn.execute(
            "UPDATE storage_folders SET virtual_path=?, display_name=?, updated_at=? WHERE id=? AND owner_user_id=?",
            (target_path, display_name, now, row_id, owner_user_id),
        )
    return {
        "old_path": old_folder,
        "new_path": new_folder,
        "moved_files": len(file_updates),
        "moved_folders": len(folder_updates),
    }, None


def trash_storage_folder(conn, *, actor, path):
    ensure_storage_album_schema(conn)
    owner_user_id = int(actor["id"])
    try:
        folder_path = _folder_prefix(path)
    except ValueError:
        return None, "資料夾路徑不安全或格式錯誤"
    if folder_path == "/":
        return None, "不能回收根目錄"
    file_rows = conn.execute(
        """
        SELECT id FROM storage_files
        WHERE owner_user_id=? AND deleted_at IS NULL AND is_trashed=0
              AND virtual_path LIKE ?
        ORDER BY virtual_path ASC
        """,
        (owner_user_id, folder_path.rstrip("/") + "/%"),
    ).fetchall()
    folder_rows = conn.execute(
        """
        SELECT id FROM storage_folders
        WHERE owner_user_id=? AND deleted_at IS NULL
              AND (virtual_path=? OR virtual_path LIKE ?)
        ORDER BY virtual_path ASC
        """,
        (owner_user_id, folder_path, folder_path.rstrip("/") + "/%"),
    ).fetchall()
    if not file_rows and not folder_rows:
        return None, "找不到資料夾或資料夾是空的"
    now = _now()
    conn.executemany(
        """
        UPDATE storage_files
        SET is_trashed=1, trashed_at=?, trash_source=NULL, updated_at=?
        WHERE id=? AND owner_user_id=?
        """,
        [(now, now, row["id"], owner_user_id) for row in file_rows],
    )
    conn.executemany(
        "UPDATE storage_folders SET deleted_at=?, updated_at=? WHERE id=? AND owner_user_id=?",
        [(now, now, row["id"], owner_user_id) for row in folder_rows],
    )
    return {
        "path": folder_path,
        "trashed_files": len(file_rows),
        "deleted_folders": len(folder_rows),
    }, None


def trash_cloud_file_to_storage(conn, *, actor, file_id):
    ensure_storage_album_schema(conn)
    owner_user_id = int(actor["id"])
    file_row = conn.execute(
        "SELECT * FROM uploaded_files WHERE id=? AND owner_user_id=? AND deleted_at IS NULL",
        (str(file_id or ""), owner_user_id),
    ).fetchone()
    if not file_row:
        return None, "找不到檔案或檔案已刪除"
    now = _now()
    storage_rows = conn.execute(
        """
        SELECT id FROM storage_files
        WHERE owner_user_id=? AND file_id=? AND deleted_at IS NULL
        """,
        (owner_user_id, file_row["id"]),
    ).fetchall()
    if storage_rows:
        conn.executemany(
            """
            UPDATE storage_files
            SET is_trashed=1, trashed_at=?, trash_source='cloud_drive_delete', updated_at=?
            WHERE id=? AND owner_user_id=?
            """,
            [(now, now, row["id"], owner_user_id) for row in storage_rows],
        )
        return {"file_id": file_row["id"], "storage_file_ids": [row["id"] for row in storage_rows]}, None

    display_name = str(file_row["original_filename_plain_for_public"] or "download.bin").strip()[:160]
    try:
        virtual_path = _unique_storage_path(conn, owner_user_id, display_name, display_name)
    except ValueError:
        return None, "storage path 不安全或格式錯誤"
    storage_id = uuid.uuid4().hex
    conn.execute(
        """
        INSERT INTO storage_files (
            id, file_id, owner_user_id, parent_id, display_name, virtual_path,
            is_trashed, trashed_at, trash_source, created_at, updated_at
        ) VALUES (?, ?, ?, NULL, ?, ?, 1, ?, 'cloud_drive_delete', ?, ?)
        """,
        (storage_id, file_row["id"], owner_user_id, display_name, virtual_path, now, now, now),
    )
    sync_user_storage_summary(
        conn,
        owner_user_id,
        actor_user_id=owner_user_id,
        source="cloud_drive_delete",
        reason="cloud_file_moved_to_trash",
    )
    return {"file_id": file_row["id"], "storage_file_ids": [storage_id]}, None


def list_storage_trash(conn, *, actor, limit=100, offset=0):
    ensure_storage_album_schema(conn)
    rows = conn.execute(
        """
        SELECT sf.*, f.size_bytes, f.privacy_mode, f.risk_level, f.scan_status,
               f.original_filename_plain_for_public
        FROM storage_files sf
        JOIN uploaded_files f ON f.id=sf.file_id
        WHERE sf.owner_user_id=? AND sf.deleted_at IS NULL AND f.deleted_at IS NULL
              AND sf.is_trashed=1
        ORDER BY sf.trashed_at DESC, sf.updated_at DESC
        LIMIT ? OFFSET ?
        """,
        (int(actor["id"]), int(limit), int(offset)),
    ).fetchall()
    return [dict(row) for row in rows]


def trash_storage_file(conn, *, actor, storage_file_id):
    ensure_storage_album_schema(conn)
    row = get_storage_file(conn, actor=actor, storage_file_id=storage_file_id)
    if not row or row.get("deleted_at") or row.get("file_deleted_at"):
        return None, "找不到檔案或檔案已刪除"
    if int(row.get("is_trashed") or 0):
        return row, None
    now = _now()
    conn.execute(
        """
        UPDATE storage_files
        SET is_trashed=1, trashed_at=?, trash_source=NULL, updated_at=?
        WHERE id=? AND owner_user_id=?
        """,
        (now, now, storage_file_id, int(actor["id"])),
    )
    return get_storage_file(conn, actor=actor, storage_file_id=storage_file_id), None


def restore_storage_file(conn, *, actor, storage_file_id):
    ensure_storage_album_schema(conn)
    row = get_storage_file(conn, actor=actor, storage_file_id=storage_file_id)
    if not row or row.get("deleted_at") or row.get("file_deleted_at"):
        return None, "找不到檔案或檔案已刪除"
    if not int(row.get("is_trashed") or 0):
        return row, None
    now = _now()
    conn.execute(
        """
        UPDATE storage_files
        SET is_trashed=0, restored_at=?, trash_source=NULL, updated_at=?
        WHERE id=? AND owner_user_id=?
        """,
        (now, now, storage_file_id, int(actor["id"])),
    )
    if row.get("trash_source") == "cloud_drive_delete":
        conn.execute(
            """
            UPDATE storage_files
            SET trash_source=NULL, updated_at=?
            WHERE owner_user_id=? AND file_id=? AND deleted_at IS NULL
                  AND trash_source='cloud_drive_delete'
            """,
            (now, int(actor["id"]), row["file_id"]),
        )
    return get_storage_file(conn, actor=actor, storage_file_id=storage_file_id), None


def purge_storage_file(conn, *, actor, storage_file_id):
    ensure_storage_album_schema(conn)
    row = get_storage_file(conn, actor=actor, storage_file_id=storage_file_id)
    if not row or row.get("deleted_at") or row.get("file_deleted_at"):
        return None, "找不到檔案或檔案已刪除"
    now = _now()
    conn.execute(
        """
        UPDATE storage_files
        SET deleted_at=?, updated_at=?
        WHERE id=? AND owner_user_id=?
        """,
        (now, now, storage_file_id, int(actor["id"])),
    )
    if row.get("trash_source") == "cloud_drive_delete":
        conn.execute(
            """
            UPDATE uploaded_files
            SET deleted_at=?
            WHERE id=? AND owner_user_id=? AND deleted_at IS NULL
            """,
            (now, row["file_id"], int(actor["id"])),
        )
    summary = sync_user_storage_summary(
        conn,
        actor["id"],
        actor_user_id=actor["id"],
        source="trash",
        reason="storage_file_purged",
    )
    return {"id": storage_file_id, "storage": summary}, None


def restore_storage_trash(conn, *, actor):
    ensure_storage_album_schema(conn)
    now = _now()
    rows = conn.execute(
        """
        SELECT id FROM storage_files
        WHERE owner_user_id=? AND deleted_at IS NULL AND is_trashed=1
        """,
        (int(actor["id"]),),
    ).fetchall()
    if rows:
        conn.executemany(
            """
            UPDATE storage_files
            SET is_trashed=0, restored_at=?, trash_source=NULL, updated_at=?
            WHERE id=? AND owner_user_id=?
            """,
            [(now, now, row["id"], int(actor["id"])) for row in rows],
        )
    return {"restored": len(rows)}, None


def purge_storage_trash(conn, *, actor):
    ensure_storage_album_schema(conn)
    now = _now()
    rows = conn.execute(
        """
        SELECT id, file_id, trash_source FROM storage_files
        WHERE owner_user_id=? AND deleted_at IS NULL AND is_trashed=1
        """,
        (int(actor["id"]),),
    ).fetchall()
    if rows:
        conn.executemany(
            """
            UPDATE storage_files
            SET deleted_at=?, updated_at=?
            WHERE id=? AND owner_user_id=?
            """,
            [(now, now, row["id"], int(actor["id"])) for row in rows],
        )
        cloud_file_ids = [row["file_id"] for row in rows if row["trash_source"] == "cloud_drive_delete"]
        if cloud_file_ids:
            conn.executemany(
                """
                UPDATE uploaded_files
                SET deleted_at=?
                WHERE id=? AND owner_user_id=? AND deleted_at IS NULL
                """,
                [(now, file_id, int(actor["id"])) for file_id in cloud_file_ids],
            )
    summary = sync_user_storage_summary(
        conn,
        actor["id"],
        actor_user_id=actor["id"],
        source="trash",
        reason="storage_trash_purged",
    )
    return {"purged": len(rows), "storage": summary}, None


def _normalize_album_visibility(value):
    visibility = str(value or "private").strip().lower()
    return visibility if visibility in {"private", "unlisted", "public"} else "private"


def _album_row(conn, album_id):
    return conn.execute("SELECT * FROM albums WHERE id=?", (album_id,)).fetchone()


def create_album(conn, *, actor, title, description="", visibility="private"):
    ensure_storage_album_schema(conn)
    title = str(title or "").strip()
    if not title:
        return None, "相簿名稱不可為空"
    now = _now()
    album_id = uuid.uuid4().hex
    conn.execute(
        """
        INSERT INTO albums (
            id, owner_user_id, title, description, visibility, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            album_id,
            int(actor["id"]),
            title[:120],
            str(description or "")[:1000],
            _normalize_album_visibility(visibility),
            now,
            now,
        ),
    )
    return get_album(conn, actor=actor, album_id=album_id, include_files=True), None


def list_albums(conn, *, actor, include_deleted=False, limit=100, offset=0):
    ensure_storage_album_schema(conn)
    where = "owner_user_id=?"
    params = [int(actor["id"])]
    if not include_deleted:
        where += " AND a.deleted_at IS NULL"
    rows = conn.execute(
        f"""
        SELECT a.*, COUNT(af.id) AS file_count
        FROM albums a
        LEFT JOIN album_files af ON af.album_id=a.id AND af.deleted_at IS NULL
        WHERE {where}
        GROUP BY a.id
        ORDER BY a.created_at DESC
        LIMIT ? OFFSET ?
        """,
        (*params, int(limit), int(offset)),
    ).fetchall()
    return [dict(row) for row in rows]


def get_album(conn, *, actor, album_id, include_files=False):
    ensure_storage_album_schema(conn)
    row = _album_row(conn, album_id)
    if not row or row["deleted_at"] or int(row["owner_user_id"]) != int(actor["id"]):
        return None
    data = dict(row)
    if include_files:
        files = conn.execute(
            """
            SELECT af.*, sf.display_name, sf.virtual_path,
                   f.original_filename_plain_for_public, f.mime_type_plain_for_public,
                   f.size_bytes, f.scan_status, f.risk_level
            FROM album_files af
            JOIN uploaded_files f ON f.id=af.file_id
            LEFT JOIN storage_files sf ON sf.id=af.storage_file_id
            WHERE af.album_id=? AND af.deleted_at IS NULL AND f.deleted_at IS NULL
            ORDER BY af.sort_order ASC, af.created_at ASC
            """,
            (album_id,),
        ).fetchall()
        data["files"] = [dict(file_row) for file_row in files]
    return data


def update_album(conn, *, actor, album_id, title=None, description=None, visibility=None):
    album = get_album(conn, actor=actor, album_id=album_id)
    if not album:
        return None, "找不到相簿"
    fields = []
    params = []
    if title is not None:
        title = str(title or "").strip()
        if not title:
            return None, "相簿名稱不可為空"
        fields.append("title=?")
        params.append(title[:120])
    if description is not None:
        fields.append("description=?")
        params.append(str(description or "")[:1000])
    if visibility is not None:
        fields.append("visibility=?")
        params.append(_normalize_album_visibility(visibility))
    if not fields:
        return get_album(conn, actor=actor, album_id=album_id, include_files=True), None
    fields.append("updated_at=?")
    params.append(_now())
    params.append(album_id)
    conn.execute(f"UPDATE albums SET {', '.join(fields)} WHERE id=?", tuple(params))
    return get_album(conn, actor=actor, album_id=album_id, include_files=True), None


def delete_album(conn, *, actor, album_id):
    album = get_album(conn, actor=actor, album_id=album_id)
    if not album:
        return None, "找不到相簿"
    now = _now()
    conn.execute("UPDATE albums SET deleted_at=?, updated_at=? WHERE id=?", (now, now, album_id))
    return {"id": album_id}, None


def add_album_file(conn, *, actor, album_id, storage_file_id=None, file_id=None, caption="", sort_order=0):
    album = get_album(conn, actor=actor, album_id=album_id)
    if not album:
        return None, "找不到相簿"
    storage_file = None
    if storage_file_id:
        storage_file = get_storage_file(conn, actor=actor, storage_file_id=storage_file_id)
        if not storage_file or storage_file.get("deleted_at") or int(storage_file.get("is_trashed") or 0):
            return None, "找不到 storage 檔案或檔案已刪除"
        file_id = storage_file["file_id"]
    if not file_id:
        return None, "缺少 file_id"
    file_row = conn.execute("SELECT * FROM uploaded_files WHERE id=? AND deleted_at IS NULL", (str(file_id),)).fetchone()
    if not file_row or int(file_row["owner_user_id"]) != int(actor["id"]):
        return None, "只能加入自己的檔案"
    existing = conn.execute(
        "SELECT id FROM album_files WHERE album_id=? AND file_id=? AND deleted_at IS NULL",
        (album_id, file_row["id"]),
    ).fetchone()
    if existing:
        return None, "檔案已在相簿內"
    now = _now()
    album_file_id = uuid.uuid4().hex
    try:
        sort_order = int(sort_order)
    except Exception:
        sort_order = 0
    conn.execute(
        """
        INSERT INTO album_files (
            id, album_id, storage_file_id, file_id, sort_order, caption, added_by, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            album_file_id,
            album_id,
            storage_file_id,
            file_row["id"],
            sort_order,
            str(caption or "")[:500],
            int(actor["id"]),
            now,
        ),
    )
    conn.execute("UPDATE albums SET updated_at=? WHERE id=?", (now, album_id))
    return get_album(conn, actor=actor, album_id=album_id, include_files=True), None


def remove_album_file(conn, *, actor, album_id, album_file_id):
    album = get_album(conn, actor=actor, album_id=album_id)
    if not album:
        return None, "找不到相簿"
    row = conn.execute(
        "SELECT id FROM album_files WHERE id=? AND album_id=? AND deleted_at IS NULL",
        (album_file_id, album_id),
    ).fetchone()
    if not row:
        return None, "找不到相簿檔案"
    now = _now()
    conn.execute("UPDATE album_files SET deleted_at=? WHERE id=?", (now, album_file_id))
    conn.execute("UPDATE albums SET updated_at=? WHERE id=?", (now, album_id))
    return get_album(conn, actor=actor, album_id=album_id, include_files=True), None


def _hash_share_token(token):
    return hashlib.sha256(str(token or "").encode("utf-8")).hexdigest()


def create_share_link(conn, *, actor, storage_file_id, expires_at=None, can_preview=False):
    ensure_storage_album_schema(conn)
    storage_file = get_storage_file(conn, actor=actor, storage_file_id=storage_file_id)
    if not storage_file or storage_file.get("deleted_at") or storage_file.get("file_deleted_at") or int(storage_file.get("is_trashed") or 0):
        return None, "找不到 storage 檔案或檔案已刪除"
    token = secrets.token_urlsafe(32)
    now = _now()
    link_id = uuid.uuid4().hex
    conn.execute(
        """
        INSERT INTO storage_share_links (
            id, storage_file_id, file_id, owner_user_id, token_hash, can_download,
            can_preview, expires_at, created_by, created_at
        ) VALUES (?, ?, ?, ?, ?, 1, ?, ?, ?, ?)
        """,
        (
            link_id,
            storage_file_id,
            storage_file["file_id"],
            int(actor["id"]),
            _hash_share_token(token),
            1 if can_preview else 0,
            str(expires_at or "").strip() or None,
            int(actor["id"]),
            now,
        ),
    )
    link = get_share_link(conn, actor=actor, link_id=link_id)
    link["token"] = token
    return link, None


def list_share_links(conn, *, actor, storage_file_id=None):
    ensure_storage_album_schema(conn)
    where = "owner_user_id=?"
    params = [int(actor["id"])]
    if storage_file_id:
        where += " AND storage_file_id=?"
        params.append(str(storage_file_id))
    rows = conn.execute(
        f"""
        SELECT id, storage_file_id, file_id, owner_user_id, can_download, can_preview,
               expires_at, revoked_at, access_count, last_accessed_at, created_by, created_at
        FROM storage_share_links
        WHERE {where}
        ORDER BY created_at DESC
        """,
        tuple(params),
    ).fetchall()
    return [dict(row) for row in rows]


def get_share_link(conn, *, actor, link_id):
    row = conn.execute(
        """
        SELECT id, storage_file_id, file_id, owner_user_id, can_download, can_preview,
               expires_at, revoked_at, access_count, last_accessed_at, created_by, created_at
        FROM storage_share_links
        WHERE id=? AND owner_user_id=?
        """,
        (link_id, int(actor["id"])),
    ).fetchone()
    return dict(row) if row else None


def revoke_share_link(conn, *, actor, link_id):
    ensure_storage_album_schema(conn)
    link = get_share_link(conn, actor=actor, link_id=link_id)
    if not link:
        return None, "找不到分享連結"
    if link.get("revoked_at"):
        return link, None
    conn.execute("UPDATE storage_share_links SET revoked_at=? WHERE id=?", (_now(), link_id))
    return get_share_link(conn, actor=actor, link_id=link_id), None


def resolve_share_token(conn, token):
    ensure_storage_album_schema(conn)
    row = conn.execute(
        """
        SELECT sl.*, sf.display_name, sf.deleted_at AS storage_deleted_at, sf.is_trashed,
               f.storage_path, f.original_filename_plain_for_public, f.scan_status, f.risk_level,
               f.privacy_mode, f.deleted_at AS file_deleted_at
        FROM storage_share_links sl
        JOIN storage_files sf ON sf.id=sl.storage_file_id
        JOIN uploaded_files f ON f.id=sl.file_id
        WHERE sl.token_hash=?
        """,
        (_hash_share_token(token),),
    ).fetchone()
    if not row:
        return None, "not_found"
    data = dict(row)
    if data.get("revoked_at"):
        return None, "revoked"
    if data.get("expires_at") and data["expires_at"] <= _now():
        return None, "expired"
    if data.get("storage_deleted_at") or data.get("file_deleted_at") or int(data.get("is_trashed") or 0):
        return None, "deleted"
    if not int(data.get("can_download") or 0):
        return None, "download_disabled"
    return data, ""


def mark_share_link_accessed(conn, link_id):
    conn.execute(
        """
        UPDATE storage_share_links
        SET access_count=access_count + 1, last_accessed_at=?
        WHERE id=?
        """,
        (_now(), link_id),
    )
