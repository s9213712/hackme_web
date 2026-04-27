from datetime import datetime


def ensure_notifications_schema(conn):
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS notifications (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id         INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            type            TEXT NOT NULL,
            title           TEXT NOT NULL,
            body            TEXT NOT NULL,
            link            TEXT,
            is_read         INTEGER NOT NULL DEFAULT 0,
            created_at      TEXT NOT NULL,
            read_at         TEXT
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_notifications_user_read ON notifications(user_id, is_read, created_at)")


def create_notification(conn, *, user_id, type, title, body, link=None):
    ensure_notifications_schema(conn)
    conn.execute(
        """
        INSERT INTO notifications (user_id, type, title, body, link, is_read, created_at)
        VALUES (?, ?, ?, ?, ?, 0, ?)
        """,
        (
            int(user_id),
            str(type or "system")[:60],
            str(title or "")[:120],
            str(body or "")[:1000],
            str(link or "")[:300] if link else None,
            datetime.now().isoformat(),
        ),
    )


def serialize_notification(row):
    return {
        "id": row["id"],
        "user_id": row["user_id"],
        "type": row["type"],
        "title": row["title"],
        "body": row["body"],
        "link": row["link"],
        "is_read": bool(row["is_read"]),
        "created_at": row["created_at"],
        "read_at": row["read_at"],
    }
