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
