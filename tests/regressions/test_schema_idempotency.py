import sqlite3

import routes.chat as chat_routes
from services.governance import sanction_notices


def _connect(path):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def test_chat_schema_duplicate_column_race_is_idempotent(tmp_path, monkeypatch):
    conn = _connect(tmp_path / "chat.db")
    try:
        conn.executescript(
            """
            CREATE TABLE users (id INTEGER PRIMARY KEY, username TEXT, status TEXT DEFAULT 'active');
            CREATE TABLE chat_rooms (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                owner_user_id INTEGER,
                is_private INTEGER NOT NULL DEFAULT 0,
                is_active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT
            );
            CREATE TABLE chat_room_members (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                room_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                joined_at TEXT
            );
            CREATE TABLE chat_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                room_id INTEGER NOT NULL,
                sender_id INTEGER NOT NULL,
                content TEXT NOT NULL,
                is_blocked INTEGER NOT NULL DEFAULT 0,
                created_at TEXT
            );
            """
        )
        chat_routes.ensure_chat_feature_schema(conn)
        conn.commit()

        real_table_columns = chat_routes._table_columns
        db_path = chat_routes._connection_path(conn)
        chat_routes._CHAT_SCHEMA_READY_PATHS.discard(db_path)

        def stale_table_columns(target_conn, table_name):
            cols = set(real_table_columns(target_conn, table_name))
            if table_name == "chat_messages":
                cols.discard("message_type")
            return cols

        monkeypatch.setattr(chat_routes, "_table_columns", stale_table_columns)
        chat_routes.ensure_chat_feature_schema(conn)
        conn.commit()
        assert "message_type" in real_table_columns(conn, "chat_messages")
    finally:
        conn.close()


def test_admin_sanction_appeal_schema_duplicate_column_race_is_idempotent(tmp_path, monkeypatch):
    conn = _connect(tmp_path / "appeals.db")
    try:
        conn.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, username TEXT)")
        sanction_notices.ensure_admin_sanction_appeal_schema(conn)
        conn.commit()

        real_table_columns = sanction_notices._table_columns
        db_path = sanction_notices._connection_path(conn)
        sanction_notices._APPEAL_SCHEMA_READY_PATHS.discard(db_path)

        def stale_table_columns(target_conn, table_name):
            cols = set(real_table_columns(target_conn, table_name))
            if table_name == "admin_sanction_appeal_contexts":
                cols.discard("points_ledger_uuid")
            return cols

        monkeypatch.setattr(sanction_notices, "_table_columns", stale_table_columns)
        sanction_notices.ensure_admin_sanction_appeal_schema(conn)
        conn.commit()
        assert "points_ledger_uuid" in real_table_columns(conn, "admin_sanction_appeal_contexts")
    finally:
        conn.close()
