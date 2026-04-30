from datetime import datetime


def _value(row, key, default=None):
    if not row:
        return default
    try:
        return row[key]
    except Exception:
        return row.get(key, default) if hasattr(row, "get") else default


def ensure_admin_sanction_appeal_schema(conn):
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS admin_sanction_appeal_contexts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            violation_id INTEGER NOT NULL UNIQUE,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            pre_status TEXT,
            pre_role TEXT,
            pre_base_level TEXT,
            pre_member_level TEXT,
            pre_effective_level TEXT,
            pre_sanction_status TEXT,
            pre_sanction_until TEXT,
            action_label TEXT NOT NULL,
            reason TEXT NOT NULL,
            actor_username TEXT NOT NULL,
            points_ledger_uuid TEXT,
            created_at TEXT NOT NULL
        )
        """
    )
    cols = {row["name"] for row in conn.execute("PRAGMA table_info(admin_sanction_appeal_contexts)").fetchall()}
    if "points_ledger_uuid" not in cols:
        conn.execute("ALTER TABLE admin_sanction_appeal_contexts ADD COLUMN points_ledger_uuid TEXT")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_admin_sanction_context_user ON admin_sanction_appeal_contexts(user_id, created_at)")


def ensure_dm_notification_schema(conn):
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS dm_threads (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            participant_a_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            participant_b_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            created_by_user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(participant_a_id, participant_b_id)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS direct_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            thread_id INTEGER NOT NULL REFERENCES dm_threads(id) ON DELETE CASCADE,
            sender_user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            recipient_user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            body TEXT NOT NULL,
            is_read INTEGER NOT NULL DEFAULT 0,
            read_at TEXT,
            sender_deleted_at TEXT,
            recipient_deleted_at TEXT,
            created_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS notifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            type TEXT NOT NULL,
            title TEXT NOT NULL,
            body TEXT NOT NULL,
            link TEXT,
            is_read INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            read_at TEXT
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_direct_messages_unread ON direct_messages(recipient_user_id, is_read)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_notifications_user_read ON notifications(user_id, is_read, created_at)")


def _dm_pair(a, b):
    a_id = int(a)
    b_id = int(b)
    return (a_id, b_id) if a_id < b_id else (b_id, a_id)


def _create_dm(conn, *, sender_id, recipient_id, body):
    ensure_dm_notification_schema(conn)
    now = datetime.now().isoformat()
    a_id, b_id = _dm_pair(sender_id, recipient_id)
    conn.execute(
        """
        INSERT OR IGNORE INTO dm_threads (
            participant_a_id, participant_b_id, created_by_user_id, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?)
        """,
        (a_id, b_id, sender_id, now, now),
    )
    thread = conn.execute(
        "SELECT * FROM dm_threads WHERE participant_a_id=? AND participant_b_id=?",
        (a_id, b_id),
    ).fetchone()
    conn.execute(
        """
        INSERT INTO direct_messages (
            thread_id, sender_user_id, recipient_user_id, body, is_read, created_at
        ) VALUES (?, ?, ?, ?, 0, ?)
        """,
        (thread["id"], sender_id, recipient_id, body, now),
    )
    conn.execute("UPDATE dm_threads SET updated_at=? WHERE id=?", (now, thread["id"]))
    return thread["id"]


def _create_notification(conn, *, user_id, title, body, link=None, type="admin_sanction"):
    ensure_dm_notification_schema(conn)
    conn.execute(
        """
        INSERT INTO notifications (user_id, type, title, body, link, is_read, created_at)
        VALUES (?, ?, ?, ?, ?, 0, ?)
        """,
        (int(user_id), str(type or "admin_sanction")[:60], title[:120], body[:1000], link, datetime.now().isoformat()),
    )


def record_admin_sanction_notice(conn, *, actor, target, previous, violation_id, action_label, reason, notice_title="會員權益變更通知", notification_type="member_governance", points_ledger_uuid=None):
    ensure_admin_sanction_appeal_schema(conn)
    actor_username = _value(actor, "username", "admin")
    body = (
        f"你收到一筆會員權益變更通知。\n\n"
        f"變更內容：{action_label}\n"
        f"原因：{reason or '未填寫'}\n\n"
        "你可以到「申覆」分頁提出申覆。申覆時請補充理由、證據或相關脈絡；root 會依申覆紀錄審核是否撤銷或調整。"
    )
    thread_id = _create_dm(
        conn,
        sender_id=int(_value(actor, "id")),
        recipient_id=int(_value(target, "id")),
        body=body,
    )
    _create_notification(
        conn,
        user_id=int(_value(target, "id")),
        title=notice_title,
        body="你收到一筆會員權益變更通知，可於申覆分頁提出申覆。",
        link="/appeals",
        type=notification_type,
    )
    conn.execute(
        """
        INSERT OR REPLACE INTO admin_sanction_appeal_contexts (
            violation_id, user_id, pre_status, pre_role, pre_base_level, pre_member_level,
            pre_effective_level, pre_sanction_status, pre_sanction_until, action_label,
            reason, actor_username, points_ledger_uuid, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            int(violation_id),
            int(_value(target, "id")),
            _value(previous, "status"),
            _value(previous, "role"),
            _value(previous, "base_level"),
            _value(previous, "member_level"),
            _value(previous, "effective_level"),
            _value(previous, "sanction_status"),
            _value(previous, "sanction_until"),
            str(action_label or "會員管理處分")[:120],
            str(reason or "")[:1000],
            actor_username[:80],
            str(points_ledger_uuid or "")[:120] or None,
            datetime.now().isoformat(),
        ),
    )
    return {"thread_id": thread_id, "notification": True}


def restore_admin_sanction_context(conn, *, user_id, violation_id):
    ensure_admin_sanction_appeal_schema(conn)
    row = conn.execute(
        "SELECT * FROM admin_sanction_appeal_contexts WHERE violation_id=? AND user_id=?",
        (int(violation_id), int(user_id)),
    ).fetchone()
    if not row:
        return False
    now = datetime.now().isoformat()
    conn.execute(
        """
        UPDATE users
        SET status=?,
            role=?,
            base_level=?,
            member_level=?,
            effective_level=?,
            sanction_status=?,
            sanction_until=?,
            level_update_reason=?,
            updated_at=?
        WHERE id=?
        """,
        (
            row["pre_status"] or "active",
            row["pre_role"] or "user",
            row["pre_base_level"] or row["pre_member_level"] or "normal",
            row["pre_member_level"] or row["pre_base_level"] or "normal",
            row["pre_effective_level"] or row["pre_member_level"] or row["pre_base_level"] or "normal",
            row["pre_sanction_status"] or "none",
            row["pre_sanction_until"],
            f"appeal approved: rollback {row['action_label']}",
            now,
            int(user_id),
        ),
    )
    return True
