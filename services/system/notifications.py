from datetime import datetime


def notifications_enabled(default=True):
    try:
        from services.platform.settings import DEFAULT_SETTINGS, get_system_settings
        settings = get_system_settings()
        return bool(settings.get(
            "feature_reports_notifications_enabled",
            DEFAULT_SETTINGS.get("feature_reports_notifications_enabled", default),
        ))
    except Exception:
        return bool(default)


def parse_muted_notification_types(raw):
    if isinstance(raw, (list, tuple, set)):
        values = list(raw)
    else:
        text = str(raw or "")
        values = text.replace(";", "\n").replace(",", "\n").splitlines()
    muted = set()
    for value in values:
        item = str(value or "").strip().lower()
        if item:
            muted.add(item[:60])
    return muted


def notification_type_is_muted(notification_type, settings=None):
    note_type = str(notification_type or "").strip().lower()
    if not note_type:
        return False
    try:
        from services.platform.settings import DEFAULT_SETTINGS, get_system_settings

        active_settings = settings if isinstance(settings, dict) else get_system_settings()
        raw = (active_settings or {}).get(
            "notification_muted_types",
            DEFAULT_SETTINGS.get("notification_muted_types", ""),
        )
        return note_type in parse_muted_notification_types(raw)
    except Exception:
        return False


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
    if notification_type_is_muted(type):
        return False
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
    return True


def create_notification_if_enabled(conn, *, user_id, type, title, body, link=None):
    if not notifications_enabled(default=True):
        return False
    return create_notification(conn, user_id=user_id, type=type, title=title, body=body, link=link)


def create_notification_once_if_enabled(conn, *, user_id, type, title, body, link=None):
    if not notifications_enabled(default=True):
        return False
    if notification_type_is_muted(type):
        return False
    ensure_notifications_schema(conn)
    existing = conn.execute(
        """
        SELECT id FROM notifications
        WHERE user_id=? AND type=? AND title=? AND body=? AND is_read=0
        LIMIT 1
        """,
        (int(user_id), str(type or "system")[:60], str(title or "")[:120], str(body or "")[:1000]),
    ).fetchone()
    if existing:
        return False
    return create_notification(conn, user_id=user_id, type=type, title=title, body=body, link=link)


def root_user_ids(conn):
    try:
        rows = conn.execute("SELECT id FROM users WHERE username='root'").fetchall()
    except Exception:
        return []
    return [int(row["id"] if hasattr(row, "keys") else row[0]) for row in rows]


def create_root_notification_if_enabled(conn, *, type, title, body, link=None, once=False):
    created = 0
    create_fn = create_notification_once_if_enabled if once else create_notification_if_enabled
    for user_id in root_user_ids(conn):
        if create_fn(conn, user_id=user_id, type=type, title=title, body=body, link=link):
            created += 1
    return created


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
