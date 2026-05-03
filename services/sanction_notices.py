from datetime import datetime

from services.notifications import create_notification, ensure_notifications_schema


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


def _next_governance_notice_violation_id(conn):
    row = conn.execute(
        "SELECT MIN(violation_id) AS min_id FROM admin_sanction_appeal_contexts WHERE violation_id < 0"
    ).fetchone()
    current = row["min_id"] if row and row["min_id"] is not None else 0
    current = int(current or 0)
    return current - 1 if current < 0 else -1


def _member_notice_body(*, action_label, reason, appealable):
    body = (
        f"你收到一筆會員權益變更通知。\n\n"
        f"變更內容：{action_label}\n"
        f"原因：{reason or '未填寫'}\n"
    )
    if appealable:
        body += (
            "\n你可以到「申覆」分頁提出申覆。申覆時請補充理由、證據或相關脈絡；"
            "root 會依申覆紀錄審核是否撤銷或調整。"
        )
    return body


def record_admin_sanction_notice(conn, *, actor, target, previous, violation_id=None, action_label, reason, notice_title="會員權益變更通知", notification_type="member_governance", points_ledger_uuid=None, appealable=True):
    ensure_admin_sanction_appeal_schema(conn)
    ensure_notifications_schema(conn)
    actor_username = _value(actor, "username", "admin")
    resolved_violation_id = None
    if appealable:
        resolved_violation_id = int(violation_id) if violation_id is not None else _next_governance_notice_violation_id(conn)
    body = _member_notice_body(action_label=action_label, reason=reason, appealable=appealable)
    create_notification(
        conn,
        user_id=int(_value(target, "id")),
        type=notification_type,
        title=notice_title,
        body=body,
        link="/appeals" if appealable else None,
    )
    if not appealable:
        return {"notification": True, "violation_id": None}
    conn.execute(
        """
        INSERT OR REPLACE INTO admin_sanction_appeal_contexts (
            violation_id, user_id, pre_status, pre_role, pre_base_level, pre_member_level,
            pre_effective_level, pre_sanction_status, pre_sanction_until, action_label,
            reason, actor_username, points_ledger_uuid, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            resolved_violation_id,
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
    return {"notification": True, "violation_id": resolved_violation_id}


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
