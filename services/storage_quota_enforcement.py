import uuid
from datetime import datetime, timedelta

from services.notifications import create_notification
from services.storage_albums import ensure_storage_album_schema, sync_user_storage_summary
from services.upload_security import (
    ensure_upload_security_schema,
    get_user_cloud_drive_usage,
)


QUOTA_BACKUP_GRACE_HOURS = 24


def _now():
    return datetime.now().isoformat()


def _value(row, key, default=None):
    if not row:
        return default
    try:
        return row[key]
    except Exception:
        return row.get(key, default) if hasattr(row, "get") else default


def _table_cols(conn, table):
    return {row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def ensure_storage_quota_enforcement_schema(conn):
    ensure_upload_security_schema(conn)
    ensure_storage_album_schema(conn)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS storage_quota_reduction_notices (
            id TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            old_level TEXT,
            new_level TEXT NOT NULL,
            old_quota_bytes INTEGER,
            new_quota_bytes INTEGER NOT NULL,
            used_bytes_at_notice INTEGER NOT NULL,
            deadline_at TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            notice_message TEXT NOT NULL,
            created_by TEXT,
            created_at TEXT NOT NULL,
            resolved_at TEXT,
            purged_at TEXT,
            deleted_file_count INTEGER NOT NULL DEFAULT 0,
            deleted_bytes INTEGER NOT NULL DEFAULT 0,
            CHECK (status IN ('pending', 'resolved', 'purged'))
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_storage_quota_notices_due ON storage_quota_reduction_notices(status, deadline_at)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_storage_quota_notices_user ON storage_quota_reduction_notices(user_id, created_at)")


def _quota_for_user(conn, user, member_rule):
    usage = get_user_cloud_drive_usage(conn, user, member_rule=member_rule)
    return usage.get("total_bytes"), usage


def _format_bytes(value):
    try:
        size = int(value)
    except Exception:
        return "-"
    units = ("B", "KB", "MB", "GB", "TB")
    amount = float(size)
    for unit in units:
        if amount < 1024 or unit == units[-1]:
            if unit == "B":
                return f"{int(amount)} {unit}"
            return f"{amount:.1f} {unit}"
        amount /= 1024
    return f"{size} B"


def _ensure_dm_schema(conn):
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
    conn.execute("CREATE INDEX IF NOT EXISTS idx_direct_messages_unread ON direct_messages(recipient_user_id, is_read)")


def _dm_pair(a, b):
    a_id = int(a)
    b_id = int(b)
    return (a_id, b_id) if a_id < b_id else (b_id, a_id)


def _send_system_dm(conn, *, sender_id, recipient_id, body):
    if not sender_id or int(sender_id) == int(recipient_id):
        return None
    _ensure_dm_schema(conn)
    now = _now()
    a_id, b_id = _dm_pair(sender_id, recipient_id)
    conn.execute(
        """
        INSERT OR IGNORE INTO dm_threads (
            participant_a_id, participant_b_id, created_by_user_id, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?)
        """,
        (a_id, b_id, int(sender_id), now, now),
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
        (thread["id"], int(sender_id), int(recipient_id), body, now),
    )
    conn.execute("UPDATE dm_threads SET updated_at=? WHERE id=?", (now, thread["id"]))
    return thread["id"]


def maybe_create_quota_reduction_notice(
    conn,
    *,
    user_before,
    user_after,
    old_member_rule,
    new_member_rule,
    actor=None,
    reason="member level changed",
    now=None,
):
    ensure_storage_quota_enforcement_schema(conn)
    now_dt = now or datetime.now()
    user_id = int(_value(user_after, "id") or _value(user_before, "id") or 0)
    if not user_id:
        return {"created": False, "reason": "missing_user"}

    old_quota, _old_usage = _quota_for_user(conn, user_before, old_member_rule)
    new_quota, new_usage = _quota_for_user(conn, user_after, new_member_rule)
    if old_quota is None or new_quota is None:
        return {"created": False, "reason": "unlimited_quota"}
    if int(new_quota) >= int(old_quota):
        return {"created": False, "reason": "quota_not_reduced"}
    used_bytes = int(new_usage.get("used_bytes") or 0)
    if used_bytes <= int(new_quota):
        conn.execute(
            "UPDATE storage_quota_reduction_notices SET status='resolved', resolved_at=? WHERE user_id=? AND status='pending'",
            (now_dt.isoformat(), user_id),
        )
        return {"created": False, "reason": "usage_within_new_quota"}

    conn.execute(
        "UPDATE storage_quota_reduction_notices SET status='resolved', resolved_at=? WHERE user_id=? AND status='pending'",
        (now_dt.isoformat(), user_id),
    )
    deadline = now_dt + timedelta(hours=QUOTA_BACKUP_GRACE_HOURS)
    message = (
        "你的帳號等級已變更，雲端硬碟容量上限同步降低。\n\n"
        f"目前使用量：{_format_bytes(used_bytes)}\n"
        f"新容量上限：{_format_bytes(new_quota)}\n"
        f"寬限期限：{deadline.isoformat()}\n\n"
        "請在 24 小時內完成備份或自行刪除超額檔案。期限後系統會直接刪除最新上傳的超額檔案，直到使用量低於新上限。"
    )
    notice_id = uuid.uuid4().hex
    conn.execute(
        """
        INSERT INTO storage_quota_reduction_notices (
            id, user_id, old_level, new_level, old_quota_bytes, new_quota_bytes,
            used_bytes_at_notice, deadline_at, status, notice_message, created_by, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?, ?)
        """,
        (
            notice_id,
            user_id,
            _value(user_before, "effective_level") or _value(user_before, "member_level"),
            _value(user_after, "effective_level") or _value(user_after, "member_level") or "normal",
            int(old_quota),
            int(new_quota),
            used_bytes,
            deadline.isoformat(),
            message,
            _value(actor, "username") if actor else None,
            now_dt.isoformat(),
        ),
    )
    create_notification(
        conn,
        user_id=user_id,
        type="storage_quota_reduced",
        title="雲端硬碟容量降低，請於 24 小時內備份",
        body=f"你的雲端硬碟目前使用 {_format_bytes(used_bytes)}，新上限為 {_format_bytes(new_quota)}。請在 24 小時內完成備份。",
        link="/drive",
    )
    sender_id = _value(actor, "id")
    _send_system_dm(conn, sender_id=sender_id, recipient_id=user_id, body=message)
    return {
        "created": True,
        "notice_id": notice_id,
        "deadline_at": deadline.isoformat(),
        "used_bytes": used_bytes,
        "new_quota_bytes": int(new_quota),
    }


def purge_expired_quota_reduction_files(conn, *, actor_user_id=None, now=None):
    ensure_storage_quota_enforcement_schema(conn)
    now_dt = now or datetime.now()
    user_cols = _table_cols(conn, "users")
    role_expr = "u.role" if "role" in user_cols else "'user'"
    member_expr = "u.member_level" if "member_level" in user_cols else "'normal'"
    base_expr = "u.base_level" if "base_level" in user_cols else member_expr
    effective_expr = "u.effective_level" if "effective_level" in user_cols else base_expr
    sanction_expr = "u.sanction_status" if "sanction_status" in user_cols else "'none'"
    due_rows = conn.execute(
        """
        SELECT n.*, u.id AS uid, u.username,
               {role_expr} AS role,
               {member_expr} AS member_level,
               {base_expr} AS base_level,
               {effective_expr} AS effective_level,
               {sanction_expr} AS sanction_status
        FROM storage_quota_reduction_notices n
        JOIN users u ON u.id=n.user_id
        WHERE n.status='pending' AND n.deadline_at<=?
        ORDER BY n.deadline_at ASC
        """.format(
            role_expr=role_expr,
            member_expr=member_expr,
            base_expr=base_expr,
            effective_expr=effective_expr,
            sanction_expr=sanction_expr,
        ),
        (now_dt.isoformat(),),
    ).fetchall()
    results = []
    for notice in due_rows:
        user = {
            "id": notice["uid"],
            "username": notice["username"],
            "role": notice["role"],
            "member_level": notice["member_level"],
            "base_level": notice["base_level"],
            "effective_level": notice["effective_level"],
            "sanction_status": notice["sanction_status"],
        }
        from services.member_levels import get_member_level_rule

        current_rule = get_member_level_rule(conn, user.get("effective_level") or user.get("member_level") or "normal")
        usage = get_user_cloud_drive_usage(conn, user, member_rule=current_rule)
        quota_value = usage.get("total_bytes")
        if quota_value is None:
            conn.execute(
                "UPDATE storage_quota_reduction_notices SET status='resolved', resolved_at=? WHERE id=?",
                (now_dt.isoformat(), notice["id"]),
            )
            results.append({"notice_id": notice["id"], "user_id": notice["user_id"], "status": "resolved", "deleted_file_count": 0, "deleted_bytes": 0})
            continue
        quota = int(quota_value)
        used = int(usage.get("used_bytes") or 0)
        if used <= quota:
            conn.execute(
                "UPDATE storage_quota_reduction_notices SET status='resolved', resolved_at=? WHERE id=?",
                (now_dt.isoformat(), notice["id"]),
            )
            results.append({"notice_id": notice["id"], "user_id": notice["user_id"], "status": "resolved", "deleted_file_count": 0, "deleted_bytes": 0})
            continue

        remaining_overage = used - quota
        files = conn.execute(
            """
            SELECT id, storage_path, size_bytes, created_at
            FROM uploaded_files
            WHERE owner_user_id=? AND deleted_at IS NULL
            ORDER BY created_at DESC, id DESC
            """,
            (int(notice["user_id"]),),
        ).fetchall()
        delete_ids = []
        deleted_bytes = 0
        for file_row in files:
            delete_ids.append(file_row["id"])
            deleted_bytes += int(file_row["size_bytes"] or 0)
            if deleted_bytes >= remaining_overage:
                break
        timestamp = now_dt.isoformat()
        for file_id in delete_ids:
            conn.execute(
                "UPDATE storage_files SET deleted_at=?, updated_at=? WHERE owner_user_id=? AND file_id=? AND deleted_at IS NULL",
                (timestamp, timestamp, int(notice["user_id"]), file_id),
            )
            conn.execute(
                "UPDATE uploaded_files SET deleted_at=?, updated_at=? WHERE owner_user_id=? AND id=? AND deleted_at IS NULL",
                (timestamp, timestamp, int(notice["user_id"]), file_id),
            )
        summary = sync_user_storage_summary(
            conn,
            notice["user_id"],
            actor_user_id=actor_user_id,
            source="quota_enforcement",
            reason="quota_reduction_deadline_expired",
        )
        conn.execute(
            """
            UPDATE storage_quota_reduction_notices
            SET status='purged', purged_at=?, deleted_file_count=?, deleted_bytes=?
            WHERE id=?
            """,
            (timestamp, len(delete_ids), deleted_bytes, notice["id"]),
        )
        create_notification(
            conn,
            user_id=int(notice["user_id"]),
            type="storage_quota_purged",
            title="雲端硬碟超額檔案已刪除",
            body=f"備份寬限期已到，系統已刪除 {len(delete_ids)} 個超額檔案，共 {_format_bytes(deleted_bytes)}。",
            link="/drive",
        )
        results.append({
            "notice_id": notice["id"],
            "user_id": notice["user_id"],
            "status": "purged",
            "deleted_file_count": len(delete_ids),
            "deleted_bytes": deleted_bytes,
            "storage": summary,
        })
    return {"processed": len(results), "results": results}
