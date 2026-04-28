import json
import os
import uuid
from datetime import datetime
from pathlib import Path

from services.storage_paths import resolve_storage_path
from services.upload_security import (
    create_uploaded_file_record,
    get_cloud_drive_security_policy,
    get_user_cloud_drive_usage,
    safe_public_filename,
    scan_uploaded_file,
)


CONTEXT_TYPES = {"dm", "group_chat", "forum_post", "forum_comment", "announcement"}
ANNOUNCEMENT_REQUEST_STATUSES = {"pending", "approved", "rejected"}


def ensure_cloud_drive_attachment_schema(conn):
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS cloud_file_refs (
            id TEXT PRIMARY KEY,
            file_id TEXT NOT NULL REFERENCES uploaded_files(id) ON DELETE CASCADE,
            owner_user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            context_type TEXT NOT NULL,
            context_id TEXT NOT NULL,
            attached_by INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            created_at TEXT NOT NULL,
            permission_snapshot_json TEXT
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS file_access_grants (
            id TEXT PRIMARY KEY,
            file_id TEXT NOT NULL REFERENCES uploaded_files(id) ON DELETE CASCADE,
            granted_to_user_id INTEGER,
            granted_to_role TEXT,
            granted_to_group_id TEXT,
            context_type TEXT NOT NULL,
            context_id TEXT NOT NULL,
            can_download INTEGER NOT NULL DEFAULT 1,
            can_preview INTEGER NOT NULL DEFAULT 0,
            expires_at TEXT,
            revoked_at TEXT,
            created_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS announcement_attachment_requests (
            id TEXT PRIMARY KEY,
            file_id TEXT NOT NULL REFERENCES uploaded_files(id) ON DELETE CASCADE,
            requested_by INTEGER NOT NULL REFERENCES users(id),
            announcement_id INTEGER REFERENCES announcements(id),
            status TEXT NOT NULL DEFAULT 'pending',
            reviewed_by INTEGER REFERENCES users(id),
            reviewed_at TEXT,
            reason TEXT,
            created_at TEXT NOT NULL
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_cloud_file_refs_file ON cloud_file_refs(file_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_cloud_file_refs_context ON cloud_file_refs(context_type, context_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_cloud_file_refs_owner ON cloud_file_refs(owner_user_id, created_at)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_file_access_grants_file ON file_access_grants(file_id, revoked_at)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_file_access_grants_user_context ON file_access_grants(granted_to_user_id, context_type, context_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_announcement_attachment_requests_status ON announcement_attachment_requests(status, created_at)")


def _now():
    return datetime.now().isoformat()


def _actor_value(actor, key, default=None):
    if not actor:
        return default
    try:
        return actor[key]
    except Exception:
        return actor.get(key, default) if hasattr(actor, "get") else default


def _actor_role(actor):
    return "super_admin" if actor and _actor_value(actor, "username") == "root" else _actor_value(actor, "role", "user")


def _role_rank_value(role):
    return {"user": 0, "manager": 1, "admin": 1, "super_admin": 2}.get(role or "user", 0)


def is_manager_or_root(actor):
    return _role_rank_value(_actor_role(actor)) >= _role_rank_value("manager")


def validate_context_type(context_type):
    value = str(context_type or "").strip()
    if value not in CONTEXT_TYPES:
        raise ValueError("unsupported attachment context_type")
    return value


def _context_id(value):
    text = str(value or "").strip()
    if not text:
        raise ValueError("context_id is required")
    return text[:80]


def _active_grant_where(actor, action):
    field = "can_preview" if action == "preview" else "can_download"
    role = _actor_role(actor)
    return (
        f"revoked_at IS NULL AND {field}=1 AND "
        "(expires_at IS NULL OR expires_at > ?) AND "
        "((granted_to_user_id IS NOT NULL AND granted_to_user_id=?) OR "
        "(granted_to_role IS NOT NULL AND granted_to_role IN (?, ?)))"
    ), (_now(), int(actor["id"]), role, "user")


def _create_file_access_log(conn, *, file_id, actor_user_id, action, result, reason=None, ip=None, user_agent=None):
    conn.execute(
        """
        INSERT INTO file_access_logs (
            id, file_id, actor_user_id, action, ip, user_agent, result, reason, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            uuid.uuid4().hex,
            file_id,
            actor_user_id,
            action,
            ip,
            (user_agent or "")[:200] if user_agent else None,
            result,
            reason,
            _now(),
        ),
    )


def list_cloud_files(conn, actor, *, limit=50, offset=0):
    ensure_cloud_drive_attachment_schema(conn)
    rows = conn.execute(
        """
        SELECT f.*, COUNT(r.id) AS ref_count
        FROM uploaded_files f
        LEFT JOIN cloud_file_refs r ON r.file_id=f.id
        WHERE f.owner_user_id=? AND f.deleted_at IS NULL
        GROUP BY f.id
        ORDER BY f.created_at DESC
        LIMIT ? OFFSET ?
        """,
        (int(actor["id"]), int(limit), int(offset)),
    ).fetchall()
    return [serialize_file_row(row) for row in rows]


def serialize_file_row(row):
    data = dict(row)
    for key in ("size_bytes", "owner_user_id"):
        if key in data and data[key] is not None:
            data[key] = int(data[key])
    data["ref_count"] = int(data.get("ref_count") or 0)
    return data


def _check_quota(conn, actor, member_rule, size_bytes, storage_root=None):
    usage = get_user_cloud_drive_usage(conn, actor, member_rule=member_rule, storage_root=storage_root)
    if not usage["can_upload"]:
        return False, "目前會員等級或處分狀態不可上傳"
    max_file = usage.get("max_file_size_bytes")
    if max_file is not None and int(size_bytes) > int(max_file):
        return False, "檔案超過單檔大小限制"
    remaining = usage.get("remaining_bytes")
    if remaining is not None and int(size_bytes) > int(remaining):
        return False, "雲端硬碟容量不足"
    daily_limit = usage.get("upload_rate_limit_per_day")
    if daily_limit is not None and int(daily_limit) >= 0:
        today = datetime.now().date().isoformat()
        row = conn.execute(
            "SELECT COUNT(*) AS c FROM uploaded_files WHERE owner_user_id=? AND created_at>=? AND deleted_at IS NULL",
            (int(actor["id"]), f"{today}T00:00:00"),
        ).fetchone()
        if int(row["c"] or 0) >= int(daily_limit):
            return False, "已達每日上傳限制"
    return True, ""


def store_cloud_upload(
    conn,
    *,
    actor,
    member_rule,
    storage_root,
    file_storage,
    privacy_mode="public_attachment",
    encrypted_metadata=None,
    encrypted_file_key=None,
    wrapped_by="user_public_key",
    ciphertext_sha256=None,
    encryption_algorithm=None,
    encryption_version=None,
    nonce=None,
    client_scan_report=None,
    scan_now=True,
):
    ensure_cloud_drive_attachment_schema(conn)
    filename = safe_public_filename(getattr(file_storage, "filename", "") or "upload.bin")
    stream = getattr(file_storage, "stream", file_storage)
    position = stream.tell() if hasattr(stream, "tell") else None
    if hasattr(stream, "seek"):
        stream.seek(0, os.SEEK_END)
        size_bytes = stream.tell()
        stream.seek(0)
    else:
        data = stream.read()
        size_bytes = len(data)
        from io import BytesIO
        stream = BytesIO(data)
    ok, msg = _check_quota(conn, actor, member_rule, size_bytes, storage_root=storage_root)
    if not ok:
        if position is not None and hasattr(stream, "seek"):
            stream.seek(position)
        return None, msg
    file_id_hint = uuid.uuid4().hex
    rel_path = f"users/{int(actor['id'])}/{file_id_hint}/{filename}"
    target = resolve_storage_path(storage_root, rel_path, create_parent=True)
    with open(target, "wb") as out:
        while True:
            chunk = stream.read(1024 * 1024)
            if not chunk:
                break
            out.write(chunk)
    result = create_uploaded_file_record(
        conn,
        owner_user_id=actor["id"],
        storage_path=rel_path,
        privacy_mode=privacy_mode,
        size_bytes=size_bytes,
        original_filename=filename,
        encrypted_metadata=encrypted_metadata,
        encrypted_file_key=encrypted_file_key,
        wrapped_by=wrapped_by,
        mime_type=getattr(file_storage, "mimetype", None),
        ciphertext_sha256=ciphertext_sha256,
        plaintext_sha256=None,
        encryption_algorithm=encryption_algorithm,
        encryption_version=encryption_version,
        nonce=nonce,
        client_scan_report=client_scan_report,
        user=actor,
        scan_now=False,
    )
    if scan_now and result.get("scan_status") == "pending":
        scan_result = scan_uploaded_file(
            conn,
            file_id=result["file_id"],
            file_path=target,
            filename=filename,
            declared_mime=getattr(file_storage, "mimetype", None),
        )
        result["scan_status"] = scan_result["scan_status"]
        result["risk_level"] = scan_result["risk_level"]
        result["scan_result"] = scan_result
    return result, None


def get_file_status(conn, *, actor, file_id):
    ensure_cloud_drive_attachment_schema(conn)
    row = _file_row(conn, file_id)
    if not row or row["deleted_at"]:
        return None, "找不到檔案或檔案已刪除"
    if int(row["owner_user_id"]) != int(actor["id"]) and not is_manager_or_root(actor):
        allowed, _, _ = can_download_file(conn, actor=actor, file_id=file_id)
        if not allowed:
            return None, "沒有檔案權限"
    scans = conn.execute(
        """
        SELECT scanner_name, result, malware_name, scan_completed_at, created_at
        FROM file_scan_results
        WHERE file_id=?
        ORDER BY created_at DESC
        LIMIT 20
        """,
        (file_id,),
    ).fetchall()
    grants = conn.execute(
        """
        SELECT id, granted_to_user_id, granted_to_role, granted_to_group_id,
               context_type, context_id, can_download, can_preview, expires_at,
               revoked_at, created_at
        FROM file_access_grants
        WHERE file_id=?
        ORDER BY created_at DESC
        """,
        (file_id,),
    ).fetchall()
    keys = []
    if row["privacy_mode"].startswith("e2ee") and (
        int(row["owner_user_id"]) == int(actor["id"]) or is_manager_or_root(actor)
    ):
        keys = conn.execute(
            """
            SELECT id, recipient_user_id, wrapped_by, key_version, created_at, revoked_at
            FROM encrypted_file_keys
            WHERE file_id=?
            ORDER BY created_at DESC
            """,
            (file_id,),
        ).fetchall()
    data = serialize_file_row(row)
    data["scan_results"] = [dict(scan) for scan in scans]
    data["access_grants"] = [dict(grant) for grant in grants]
    data["encrypted_key_recipients"] = [dict(key) for key in keys]
    return data, None


def share_e2ee_file(
    conn,
    *,
    actor,
    file_id,
    recipient_user_id,
    encrypted_file_key,
    wrapped_by="recipient_public_key",
    context_type="dm",
    context_id=None,
):
    ensure_cloud_drive_attachment_schema(conn)
    row = _file_row(conn, file_id)
    if not row or row["deleted_at"]:
        return None, "找不到檔案或檔案已刪除"
    if int(row["owner_user_id"]) != int(actor["id"]):
        return None, "只能分享自己的 E2EE 檔案"
    if not row["privacy_mode"].startswith("e2ee"):
        return None, "只有 E2EE 檔案需要加密金鑰分享"
    try:
        recipient_user_id = int(recipient_user_id)
    except Exception:
        return None, "recipient_user_id 錯誤"
    if recipient_user_id == int(actor["id"]):
        return None, "不需要分享給自己"
    if not str(encrypted_file_key or "").strip():
        return None, "缺少 encrypted_file_key"
    recipient = conn.execute("SELECT id FROM users WHERE id=?", (recipient_user_id,)).fetchone()
    if not recipient:
        return None, "找不到分享對象"
    context_type = validate_context_type(context_type)
    context_id = _context_id(context_id or f"file-share:{file_id}")
    now = _now()
    key_id = uuid.uuid4().hex
    conn.execute(
        """
        INSERT INTO encrypted_file_keys (
            id, file_id, recipient_user_id, encrypted_file_key, wrapped_by, key_version, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (key_id, file_id, recipient_user_id, str(encrypted_file_key), str(wrapped_by or "recipient_public_key"), 1, now),
    )
    grant_id = _insert_grant(
        conn,
        file_id=file_id,
        user_id=recipient_user_id,
        role=None,
        group_id=None,
        context_type=context_type,
        context_id=context_id,
        can_preview=True,
    )
    _create_file_access_log(
        conn,
        file_id=file_id,
        actor_user_id=actor["id"],
        action="share",
        result="allowed",
        reason=f"recipient_user_id={recipient_user_id}",
    )
    return {"key_id": key_id, "grant_id": grant_id, "recipient_user_id": recipient_user_id}, None


def revoke_e2ee_file_share(conn, *, actor, file_id, recipient_user_id):
    ensure_cloud_drive_attachment_schema(conn)
    row = _file_row(conn, file_id)
    if not row or row["deleted_at"]:
        return None, "找不到檔案或檔案已刪除"
    if int(row["owner_user_id"]) != int(actor["id"]) and not is_manager_or_root(actor):
        return None, "只能撤銷自己的檔案分享"
    try:
        recipient_user_id = int(recipient_user_id)
    except Exception:
        return None, "recipient_user_id 錯誤"
    now = _now()
    key_cur = conn.execute(
        """
        UPDATE encrypted_file_keys
        SET revoked_at=?
        WHERE file_id=? AND recipient_user_id=? AND revoked_at IS NULL
        """,
        (now, file_id, recipient_user_id),
    )
    grant_cur = conn.execute(
        """
        UPDATE file_access_grants
        SET revoked_at=?
        WHERE file_id=? AND granted_to_user_id=? AND revoked_at IS NULL
        """,
        (now, file_id, recipient_user_id),
    )
    _create_file_access_log(
        conn,
        file_id=file_id,
        actor_user_id=actor["id"],
        action="revoke_share",
        result="allowed",
        reason=f"recipient_user_id={recipient_user_id}",
    )
    return {"revoked_keys": key_cur.rowcount, "revoked_grants": grant_cur.rowcount}, None


def _file_row(conn, file_id):
    return conn.execute("SELECT * FROM uploaded_files WHERE id=?", (file_id,)).fetchone()


def attach_existing_file(conn, *, actor, file_id, context_type, context_id, grant_user_ids=None, grant_role=None, grant_group_id=None, can_preview=False, allow_announcement=False):
    ensure_cloud_drive_attachment_schema(conn)
    context_type = validate_context_type(context_type)
    context_id = _context_id(context_id)
    row = _file_row(conn, file_id)
    if not row or row["deleted_at"]:
        return None, "找不到檔案或檔案已刪除"
    if int(row["owner_user_id"]) != int(actor["id"]) and not is_manager_or_root(actor):
        return None, "只能附加自己的雲端硬碟檔案"
    if context_type == "announcement" and not allow_announcement:
        return None, "公告附件必須走 root 審核流程"
    now = _now()
    ref_id = uuid.uuid4().hex
    snapshot = {
        "scan_status": row["scan_status"],
        "risk_level": row["risk_level"],
        "privacy_mode": row["privacy_mode"],
    }
    conn.execute(
        """
        INSERT INTO cloud_file_refs (
            id, file_id, owner_user_id, context_type, context_id, attached_by,
            created_at, permission_snapshot_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (ref_id, file_id, row["owner_user_id"], context_type, context_id, actor["id"], now, json.dumps(snapshot, ensure_ascii=False)),
    )
    created_grants = []
    for uid in sorted({int(x) for x in (grant_user_ids or []) if str(x).strip()}):
        created_grants.append(_insert_grant(conn, file_id=file_id, user_id=uid, role=None, group_id=None, context_type=context_type, context_id=context_id, can_preview=can_preview))
    if grant_role:
        created_grants.append(_insert_grant(conn, file_id=file_id, user_id=None, role=str(grant_role), group_id=None, context_type=context_type, context_id=context_id, can_preview=can_preview))
    if grant_group_id:
        created_grants.append(_insert_grant(conn, file_id=file_id, user_id=None, role=None, group_id=str(grant_group_id), context_type=context_type, context_id=context_id, can_preview=can_preview))
    return {"ref_id": ref_id, "grants": created_grants}, None


def _insert_grant(conn, *, file_id, user_id=None, role=None, group_id=None, context_type, context_id, can_preview=False):
    grant_id = uuid.uuid4().hex
    conn.execute(
        """
        INSERT INTO file_access_grants (
            id, file_id, granted_to_user_id, granted_to_role, granted_to_group_id,
            context_type, context_id, can_download, can_preview, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, ?)
        """,
        (grant_id, file_id, user_id, role, group_id, context_type, context_id, 1 if can_preview else 0, _now()),
    )
    return grant_id


def can_download_file(conn, *, actor, file_id, action="download"):
    ensure_cloud_drive_attachment_schema(conn)
    row = _file_row(conn, file_id)
    if not row:
        return False, "not_found", None
    if row["deleted_at"]:
        return False, "deleted", row
    if int(row["owner_user_id"]) == int(actor["id"]) or is_manager_or_root(actor):
        return _scan_allows_download(conn, row), "owner_or_admin", row
    where, params = _active_grant_where(actor, action)
    grant = conn.execute(
        f"SELECT id FROM file_access_grants WHERE file_id=? AND {where} LIMIT 1",
        (file_id, *params),
    ).fetchone()
    if not grant:
        return False, "no_grant", row
    allowed = _scan_allows_download(conn, row)
    return allowed, "grant" if allowed else "blocked_by_scan_policy", row


def _scan_allows_download(conn, row):
    policy = get_cloud_drive_security_policy(conn)
    if not policy["block_unclean_downloads"]:
        return True
    if row["privacy_mode"].startswith("e2ee"):
        return True
    return row["scan_status"] in {"clean", "not_required"}


def soft_delete_cloud_file(conn, *, actor, file_id):
    row = _file_row(conn, file_id)
    if not row or row["deleted_at"]:
        return False, "找不到檔案或檔案已刪除"
    if int(row["owner_user_id"]) != int(actor["id"]) and not is_manager_or_root(actor):
        return False, "只能刪除自己的檔案"
    conn.execute("UPDATE uploaded_files SET deleted_at=?, updated_at=? WHERE id=?", (_now(), _now(), file_id))
    return True, ""


def create_announcement_attachment_request(conn, *, actor, file_id, announcement_id=None, reason=""):
    ensure_cloud_drive_attachment_schema(conn)
    if not is_manager_or_root(actor):
        return None, "只有管理員以上可提出公告附件請求"
    row = _file_row(conn, file_id)
    if not row or row["deleted_at"]:
        return None, "找不到檔案或檔案已刪除"
    if row["privacy_mode"].startswith("e2ee"):
        return None, "E2EE 檔案不可作為公告附件"
    req_id = uuid.uuid4().hex
    conn.execute(
        """
        INSERT INTO announcement_attachment_requests (
            id, file_id, requested_by, announcement_id, status, reason, created_at
        ) VALUES (?, ?, ?, ?, 'pending', ?, ?)
        """,
        (req_id, file_id, actor["id"], announcement_id, str(reason or "")[:500], _now()),
    )
    return {"id": req_id}, None


def review_announcement_attachment_request(conn, *, actor, request_id, action, reason=""):
    ensure_cloud_drive_attachment_schema(conn)
    if _actor_role(actor) != "super_admin":
        return None, "只有 root 可審核公告附件"
    if action not in {"approve", "reject"}:
        return None, "審核動作錯誤"
    req = conn.execute("SELECT * FROM announcement_attachment_requests WHERE id=?", (request_id,)).fetchone()
    if not req:
        return None, "找不到公告附件請求"
    if req["status"] != "pending":
        return None, "此請求已審核"
    status = "approved" if action == "approve" else "rejected"
    now = _now()
    conn.execute(
        "UPDATE announcement_attachment_requests SET status=?, reviewed_by=?, reviewed_at=?, reason=? WHERE id=?",
        (status, actor["id"], now, str(reason or req["reason"] or "")[:500], request_id),
    )
    if status == "approved":
        # Approved announcement attachments become root-owned management files so
        # future quota/accounting follows the announcement ownership rule.
        conn.execute(
            "UPDATE uploaded_files SET owner_user_id=?, updated_at=? WHERE id=?",
            (actor["id"], now, req["file_id"]),
        )
        attach_existing_file(
            conn,
            actor=actor,
            file_id=req["file_id"],
            context_type="announcement",
            context_id=str(req["announcement_id"] or request_id),
            grant_role="user",
            can_preview=True,
            allow_announcement=True,
        )
    return {"id": request_id, "status": status}, None


def resolve_file_storage_path(storage_root, row):
    return resolve_storage_path(storage_root, row["storage_path"], create_parent=False)
