import hashlib
import os
import shutil
import sqlite3
import tempfile
import threading
import uuid

from services.upload_security import (
    get_cloud_drive_safety_summary,
    get_cloud_drive_security_policy,
    get_user_cloud_drive_usage,
    log_file_access,
    safe_public_filename,
    scan_uploaded_file,
)
from datetime import datetime
from services.cloud_drive import (
    attach_existing_file,
    can_download_file,
    create_announcement_attachment_request,
    ensure_cloud_drive_attachment_schema,
    get_file_status,
    list_cloud_files,
    resolve_file_storage_path,
    review_announcement_attachment_request,
    revoke_e2ee_file_share,
    share_e2ee_file,
    store_cloud_upload,
)
from services.file_previews import build_preview_metadata, preview_category
from services.remote_downloads import RemoteDownloadError, download_remote_url, download_torrent_file_with_aria2, remote_download_capabilities, validate_remote_url
from services.storage_albums import (
    add_album_file,
    create_album,
    create_album_from_storage_folder,
    create_share_link,
    create_storage_folder,
    create_storage_file_entry,
    delete_album,
    ensure_storage_album_schema,
    get_album,
    get_storage_file,
    list_albums,
    list_share_links,
    list_storage_folders,
    list_storage_files,
    list_storage_trash,
    move_storage_file,
    move_storage_folder,
    purge_storage_trash,
    purge_storage_file,
    remove_album_file,
    resolve_share_token,
    restore_storage_trash,
    restore_storage_file,
    revoke_share_link,
    mark_share_link_accessed,
    sync_user_storage_summary,
    trash_cloud_file_to_storage,
    trash_storage_folder,
    trash_storage_file,
    update_album,
)
from services.storage_maintenance import run_storage_maintenance, storage_maintenance_status
from services.storage_quota_overrides import (
    clear_storage_quota_override,
    get_storage_quota_override,
    set_storage_quota_override,
)
from services.storage_quota_purchases import (
    active_storage_quota_purchases,
    default_storage_upgrade_catalog,
    ensure_storage_upgrade_price_catalog,
    list_storage_upgrade_price_catalog,
    record_storage_quota_purchase,
)
from services.storage_capacity_audit import audit_storage_capacity, can_allocate_storage_bytes
from flask import request, send_file


_REMOTE_DOWNLOAD_TASKS = {}
_REMOTE_DOWNLOAD_TASKS_LOCK = threading.Lock()
_REMOTE_DOWNLOAD_ACTIVE_USERS = set()


def register_file_routes(app, deps):
    get_current_user_ctx = deps["get_current_user_ctx"]
    get_db = deps["get_db"]
    get_member_level_rule = deps["get_member_level_rule"]
    get_client_ip = deps.get("get_client_ip", lambda: "")
    get_ua = deps.get("get_ua", lambda: "")
    audit = deps.get("audit", lambda *args, **kwargs: None)
    json_resp = deps["json_resp"]
    require_csrf = deps.get("require_csrf", deps["require_csrf_safe"])
    require_csrf_safe = deps["require_csrf_safe"]
    role_rank = deps.get("role_rank", lambda role: {"user": 0, "manager": 1, "super_admin": 2}.get(role or "user", 0))
    storage_root = deps.get("STORAGE_DIR", ".")
    points_service = deps.get("points_service")

    def _actor_or_401():
        actor = get_current_user_ctx()
        if not actor:
            return None, json_resp({"ok": False, "msg": "請先登入"}, 401)
        return actor, None

    def _actor_value(actor, key, default=None):
        if not actor:
            return default
        try:
            return actor[key]
        except Exception:
            return actor.get(key, default) if hasattr(actor, "get") else default

    def _is_root(actor):
        return actor and _actor_value(actor, "username") == "root"

    def _is_manager(actor):
        role = "super_admin" if actor and _actor_value(actor, "username") == "root" else _actor_value(actor, "role", "user")
        return role_rank(role) >= role_rank("manager")

    def _manager_or_403():
        actor, err = _actor_or_401()
        if err:
            return None, err
        if not _is_manager(actor):
            return None, json_resp({"ok": False, "msg": "需要管理員權限"}), 403
        return actor, None

    def _root_or_403():
        actor, err = _actor_or_401()
        if err:
            return None, err
        if not _is_root(actor):
            return None, json_resp({"ok": False, "msg": "只有 root 可操作"}, 403)
        return actor, None

    def _optional_mb_to_bytes(value, field):
        if value in (None, ""):
            return None
        try:
            mb = float(value)
        except Exception as exc:
            raise ValueError(f"{field} 必須是數字") from exc
        if mb < 0:
            raise ValueError(f"{field} 不可小於 0")
        return int(mb * 1024 * 1024)

    def _optional_nonnegative_int(value, field):
        if value in (None, ""):
            return None
        try:
            number = int(value)
        except Exception as exc:
            raise ValueError(f"{field} 必須是整數") from exc
        if number < 0:
            raise ValueError(f"{field} 不可小於 0")
        return number

    def _optional_bool(value):
        if value in ("", None, "inherit"):
            return None
        if isinstance(value, bool):
            return value
        text = str(value).strip().lower()
        if text in {"1", "true", "yes", "on", "allow", "allowed"}:
            return True
        if text in {"0", "false", "no", "off", "deny", "denied"}:
            return False
        raise ValueError("can_upload 必須是 true、false 或 inherit")

    def _parse_json_body():
        try:
            data = request.get_json(force=True)
        except Exception:
            return None, json_resp({"ok": False, "msg": "Invalid JSON"}), 400
        if not isinstance(data, dict):
            return None, json_resp({"ok": False, "msg": "Invalid request"}), 400
        return data, None, None

    def _points_error(exc):
        msg = str(exc) or exc.__class__.__name__
        status = 400
        if "insufficient balance" in msg:
            status = 409
        return json_resp({"ok": False, "msg": msg}), status

    def _refund_storage_upgrade_spend(spend, actor, *, reason):
        ledger = (spend or {}).get("ledger") or {}
        ledger_uuid = ledger.get("ledger_uuid")
        if not ledger_uuid or not points_service or not hasattr(points_service, "rollback_ledger"):
            return False
        try:
            points_service.rollback_ledger(
                actor=actor,
                ledger_uuid=ledger_uuid,
                reason=reason,
            )
            audit(
                "CLOUD_STORAGE_UPGRADE_REFUND",
                get_client_ip(),
                user=_actor_value(actor, "username"),
                success=True,
                ua=get_ua(),
                detail=f"ledger_uuid={ledger_uuid},reason={reason[:200]}",
            )
            return True
        except Exception as exc:
            audit(
                "CLOUD_STORAGE_UPGRADE_REFUND_FAILED",
                get_client_ip(),
                user=_actor_value(actor, "username"),
                success=False,
                ua=get_ua(),
                detail=f"ledger_uuid={ledger_uuid},error={exc}",
            )
            return False

    def _storage_upgrade_catalog(conn):
        try:
            if hasattr(points_service, "ensure_schema"):
                points_service.ensure_schema(conn)
            ensure_storage_upgrade_price_catalog(conn)
            conn.commit()
            catalog = list_storage_upgrade_price_catalog(conn)
            return catalog or default_storage_upgrade_catalog()
        except sqlite3.OperationalError as exc:
            try:
                conn.rollback()
            except Exception:
                pass
            if "locked" in str(exc).lower():
                return default_storage_upgrade_catalog()
            raise

    def _storage_usage_for_user_row(conn, row):
        data = dict(row)
        level = data.get("effective_level") or data.get("member_level") or "newbie"
        rule = get_member_level_rule(conn, level)
        usage = get_user_cloud_drive_usage(conn, data, member_rule=rule, storage_root=storage_root)
        usage["username"] = data.get("username")
        usage["role"] = data.get("role", "user")
        usage["member_level"] = data.get("member_level") or data.get("base_level") or data.get("effective_level")
        usage["effective_level"] = data.get("effective_level") or usage.get("effective_level")
        usage["override"] = get_storage_quota_override(conn, data.get("id"))
        return usage

    def _requires_download_warning(policy, row):
        if not policy.get("warn_high_risk_downloads"):
            return False
        return row["risk_level"] in {"high", "blocked", "unknown_encrypted"} or row["scan_status"] in {"infected", "quarantined", "failed", "unknown_encrypted"}

    def _preview_allowed_by_policy(policy, row):
        if row["privacy_mode"].startswith("e2ee"):
            return False, "E2EE 檔案無法由伺服器預覽"
        if policy.get("block_unclean_downloads") and row["scan_status"] not in {"clean", "not_required"}:
            return False, "檔案尚未通過安全檢查"
        if _requires_download_warning(policy, row) and not policy.get("allow_inline_preview_for_high_risk"):
            return False, "高風險檔案目前不允許 inline preview"
        return True, ""

    def _preview_row_with_storage_fallback(conn, actor, row):
        data = dict(row)
        if data.get("original_filename_plain_for_public"):
            return data
        try:
            storage_row = conn.execute(
                """
                SELECT display_name, virtual_path
                FROM storage_files
                WHERE file_id=? AND owner_user_id=? AND deleted_at IS NULL AND COALESCE(is_trashed, 0)=0
                ORDER BY updated_at DESC, created_at DESC
                LIMIT 1
                """,
                (row["id"], _actor_value(actor, "id")),
            ).fetchone()
        except Exception:
            storage_row = None
        if storage_row:
            fallback_name = storage_row["display_name"] or os.path.basename(str(storage_row["virtual_path"] or ""))
            if fallback_name:
                data["original_filename_plain_for_public"] = fallback_name
        return data

    def _grant_user_ids_from_payload(data):
        raw = data.get("grant_user_ids") if isinstance(data, dict) else []
        if raw is None:
            return []
        if not isinstance(raw, list):
            return []
        out = []
        for item in raw:
            try:
                out.append(int(item))
            except Exception:
                pass
        return out

    class _DownloadedFileStorage:
        def __init__(self, downloaded):
            self._downloaded = downloaded
            self.filename = downloaded.filename
            self.mimetype = downloaded.mimetype
            self.stream = open(downloaded.path, "rb")

        def close(self):
            try:
                self.stream.close()
            except Exception:
                pass

    def _task_update(task_id, **changes):
        with _REMOTE_DOWNLOAD_TASKS_LOCK:
            task = _REMOTE_DOWNLOAD_TASKS.get(task_id)
            if not task:
                return
            task.update(changes)
            task["updated_at"] = datetime.now().isoformat()

    def _task_snapshot(task):
        public = {
            "id": task.get("id"),
            "kind": task.get("kind"),
            "status": task.get("status"),
            "phase": task.get("phase"),
            "filename": task.get("filename"),
            "url": task.get("url"),
            "source_type": task.get("source_type"),
            "torrent_filename": task.get("torrent_filename"),
            "loaded_bytes": task.get("loaded_bytes"),
            "total_bytes": task.get("total_bytes"),
            "progress_percent": task.get("progress_percent"),
            "msg": task.get("msg"),
            "error": task.get("error"),
            "file": task.get("file"),
            "storage_file": task.get("storage_file"),
            "created_at": task.get("created_at"),
            "updated_at": task.get("updated_at"),
        }
        return public

    def _get_remote_download_task(task_id):
        with _REMOTE_DOWNLOAD_TASKS_LOCK:
            task = _REMOTE_DOWNLOAD_TASKS.get(task_id)
            return dict(task) if task else None

    def _user_has_active_remote_download(user_id):
        try:
            user_id = int(user_id)
        except Exception:
            return True
        with _REMOTE_DOWNLOAD_TASKS_LOCK:
            if user_id in _REMOTE_DOWNLOAD_ACTIVE_USERS:
                return True
            return any(
                int(task.get("owner_user_id") or 0) == user_id
                and task.get("status") in {"queued", "running"}
                for task in _REMOTE_DOWNLOAD_TASKS.values()
            )

    def _table_exists(conn, table_name):
        row = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
            (table_name,),
        ).fetchone()
        return row is not None

    def _context_refs_visible_to_actor(conn, actor, context_type, context_id):
        if _is_manager(actor):
            return True
        actor_id = int(_actor_value(actor, "id") or 0)
        context_type = str(context_type or "").strip()
        context_id = str(context_id or "").strip()
        if context_type == "dm":
            if not _table_exists(conn, "dm_threads"):
                return True
            try:
                row = conn.execute(
                    """
                    SELECT 1 FROM dm_threads
                    WHERE id=? AND (participant_a_id=? OR participant_b_id=?)
                    """,
                    (int(context_id), actor_id, actor_id),
                ).fetchone()
            except Exception:
                return False
            return row is not None
        if context_type == "group_chat":
            if not _table_exists(conn, "chat_room_members"):
                return True
            try:
                row = conn.execute(
                    "SELECT 1 FROM chat_room_members WHERE room_id=? AND user_id=?",
                    (int(context_id), actor_id),
                ).fetchone()
            except Exception:
                return False
            return row is not None
        if context_type == "chat_message":
            if not (_table_exists(conn, "chat_messages") and _table_exists(conn, "chat_room_members")):
                return True
            try:
                row = conn.execute(
                    """
                    SELECT 1
                    FROM chat_messages m
                    JOIN chat_room_members rm ON rm.room_id=m.room_id AND rm.user_id=?
                    WHERE m.id=?
                    """,
                    (actor_id, int(context_id)),
                ).fetchone()
            except Exception:
                return False
            return row is not None
        if context_type == "announcement":
            if not _table_exists(conn, "announcements"):
                return True
            row = conn.execute("SELECT 1 FROM announcements WHERE id=? AND is_active=1", (context_id,)).fetchone()
            return row is not None
        if context_type == "forum_thread":
            if not _table_exists(conn, "forum_threads"):
                return True
            row = conn.execute(
                """
                SELECT 1 FROM forum_threads
                WHERE id=? AND is_deleted=0 AND (status='approved' OR author_user_id=?)
                """,
                (context_id, actor_id),
            ).fetchone()
            return row is not None
        if context_type in {"forum_post", "forum_comment"}:
            if not (_table_exists(conn, "forum_posts") and _table_exists(conn, "forum_threads")):
                return True
            row = conn.execute(
                """
                SELECT 1
                FROM forum_posts p
                JOIN forum_threads t ON t.id=p.thread_id
                WHERE p.id=? AND p.is_deleted=0 AND t.is_deleted=0
                  AND (t.status='approved' OR p.author_user_id=? OR t.author_user_id=?)
                """,
                (context_id, actor_id, actor_id),
            ).fetchone()
            return row is not None
        return False

    def _remote_progress_updater(task_id):
        def _callback(event):
            loaded = event.get("loaded_bytes")
            total = event.get("total_bytes")
            percent = None
            try:
                if total:
                    percent = max(0, min(100, round((int(loaded or 0) / int(total)) * 100, 1)))
            except Exception:
                percent = None
            phase = event.get("phase") or "downloading"
            msg = "下載中" if phase == "downloading" else "下載完成，準備保存"
            _task_update(
                task_id,
                status="running",
                phase=phase,
                filename=event.get("filename"),
                loaded_bytes=loaded,
                total_bytes=total,
                progress_percent=percent,
                msg=msg,
            )
        return _callback

    def _run_remote_download_task(task_id):
        task = _get_remote_download_task(task_id)
        if not task:
            return
        actor = task["actor"]
        owner_user_id = int(task.get("owner_user_id") or _actor_value(actor, "id") or 0)
        downloaded = None
        file_storage = None
        conn = None
        try:
            with _REMOTE_DOWNLOAD_TASKS_LOCK:
                if owner_user_id in _REMOTE_DOWNLOAD_ACTIVE_USERS:
                    task_ref = _REMOTE_DOWNLOAD_TASKS.get(task_id)
                    if task_ref:
                        task_ref.update(status="failed", phase="failed", error="已有遠端下載正在進行，請等完成後再新增", msg="已有遠端下載正在進行")
                    return
                _REMOTE_DOWNLOAD_ACTIVE_USERS.add(owner_user_id)
            conn = get_db()
            ensure_cloud_drive_attachment_schema(conn)
            ensure_storage_album_schema(conn)
            rule = get_member_level_rule(conn, _actor_value(actor, "effective_level") or _actor_value(actor, "member_level"))
            usage = get_user_cloud_drive_usage(conn, actor, member_rule=rule, storage_root=storage_root)
            remaining = usage.get("remaining_bytes")
            max_file = usage.get("max_file_size_bytes")
            max_bytes = None
            if remaining is not None:
                max_bytes = int(remaining)
            if max_file is not None:
                max_bytes = min(max_bytes, int(max_file)) if max_bytes is not None else int(max_file)
            conn.close()
            conn = None

            source_type = task.get("source_type") or "url"
            _task_update(task_id, status="running", phase="starting", msg="連線到遠端來源")
            if source_type == "torrent_file":
                downloaded = download_torrent_file_with_aria2(
                    task["torrent_path"],
                    display_name=task.get("torrent_filename") or "BT 檔案",
                    timeout_seconds=task["timeout_seconds"],
                    max_bytes=max_bytes,
                    progress_callback=_remote_progress_updater(task_id),
                )
            else:
                downloaded = download_remote_url(
                    task["url"],
                    timeout_seconds=task["timeout_seconds"],
                    max_bytes=max_bytes,
                    progress_callback=_remote_progress_updater(task_id),
                )
            _task_update(task_id, status="running", phase="saving", filename=downloaded.filename, msg="保存到雲端硬碟")
            file_storage = _DownloadedFileStorage(downloaded)
            conn = get_db()
            ensure_cloud_drive_attachment_schema(conn)
            ensure_storage_album_schema(conn)
            upload_result, msg = store_cloud_upload(
                conn,
                actor=actor,
                member_rule=rule,
                storage_root=storage_root,
                file_storage=file_storage,
                privacy_mode=task["privacy_mode"],
                scan_now=True,
            )
            if msg:
                conn.rollback()
                _task_update(task_id, status="failed", phase="failed", error=msg, msg=msg)
                return

            storage_file = None
            if task.get("virtual_path"):
                file_row = conn.execute("SELECT * FROM uploaded_files WHERE id=?", (upload_result["file_id"],)).fetchone()
                storage_file, msg = create_storage_file_entry(
                    conn,
                    actor=actor,
                    file_row=file_row,
                    virtual_path=task["virtual_path"],
                    display_name=downloaded.filename,
                    source="remote_download",
                )
                if msg:
                    conn.rollback()
                    _task_update(task_id, status="failed", phase="failed", error=msg, msg=msg)
                    return
            conn.commit()
            audit("CLOUD_DRIVE_REMOTE_DOWNLOAD", task.get("ip") or "", user=actor["username"], success=True, ua=task.get("ua") or "", detail=f"file_id={upload_result['file_id']}")
            _task_update(
                task_id,
                status="completed",
                phase="completed",
                loaded_bytes=upload_result.get("size_bytes"),
                total_bytes=upload_result.get("size_bytes"),
                progress_percent=100,
                msg="遠端下載已保存到雲端硬碟",
                file={**upload_result, "filename": downloaded.filename},
                storage_file=storage_file,
            )
        except RemoteDownloadError as exc:
            if conn:
                conn.rollback()
            _task_update(task_id, status="failed", phase="failed", error=str(exc), msg=str(exc))
        except Exception as exc:
            if conn:
                conn.rollback()
            audit("CLOUD_DRIVE_REMOTE_DOWNLOAD_ERROR", task.get("ip") or "", user=actor.get("username"), success=False, ua=task.get("ua") or "", detail=exc.__class__.__name__)
            _task_update(task_id, status="failed", phase="failed", error=f"遠端下載失敗：{exc.__class__.__name__}", msg=f"遠端下載失敗：{exc.__class__.__name__}")
        finally:
            if file_storage:
                file_storage.close()
            if downloaded and downloaded.cleanup_dir:
                shutil.rmtree(downloaded.cleanup_dir, ignore_errors=True)
            if task.get("torrent_cleanup_dir"):
                shutil.rmtree(task["torrent_cleanup_dir"], ignore_errors=True)
            with _REMOTE_DOWNLOAD_TASKS_LOCK:
                _REMOTE_DOWNLOAD_ACTIVE_USERS.discard(owner_user_id)
            if conn:
                conn.close()

    @app.route("/api/admin/storage/summary", methods=["GET"])
    @require_csrf_safe
    def admin_storage_summary():
        actor, err = _manager_or_403()
        if err:
            return err
        conn = get_db()
        try:
            ensure_storage_album_schema(conn)
            file_stats = conn.execute(
                """
                SELECT COUNT(sf.id) AS storage_files,
                       COALESCE(SUM(f.size_bytes), 0) AS storage_bytes,
                       SUM(CASE WHEN sf.is_trashed=1 THEN 1 ELSE 0 END) AS trashed_files
                FROM storage_files sf
                JOIN uploaded_files f ON f.id=sf.file_id
                WHERE sf.deleted_at IS NULL AND f.deleted_at IS NULL
                """
            ).fetchone()
            album_count = conn.execute("SELECT COUNT(*) AS c FROM albums WHERE deleted_at IS NULL").fetchone()
            share_count = conn.execute("SELECT COUNT(*) AS c FROM storage_share_links WHERE revoked_at IS NULL").fetchone()
            users = conn.execute(
                """
                SELECT COUNT(*) AS users_with_storage,
                       COALESCE(SUM(used_bytes), 0) AS used_bytes,
                       COALESCE(SUM(file_count), 0) AS file_count
                FROM user_storage
                """
            ).fetchone()
            return json_resp({
                "ok": True,
                "summary": {
                    "storage_files": int(file_stats["storage_files"] or 0),
                    "storage_bytes": int(file_stats["storage_bytes"] or 0),
                    "trashed_files": int(file_stats["trashed_files"] or 0),
                    "albums": int(album_count["c"] or 0),
                    "active_share_links": int(share_count["c"] or 0),
                    "users_with_storage": int(users["users_with_storage"] or 0),
                    "tracked_used_bytes": int(users["used_bytes"] or 0),
                    "tracked_file_count": int(users["file_count"] or 0),
                },
            })
        finally:
            conn.close()

    @app.route("/api/admin/storage/users", methods=["GET"])
    @require_csrf_safe
    def admin_storage_users():
        actor, err = _manager_or_403()
        if err:
            return err
        conn = get_db()
        try:
            ensure_storage_album_schema(conn)
            rows = conn.execute(
                """
                SELECT u.id AS user_id, u.username, COALESCE(us.quota_bytes, 0) AS quota_bytes,
                       COALESCE(us.used_bytes, 0) AS used_bytes,
                       COALESCE(us.reserved_bytes, 0) AS reserved_bytes,
                       COALESCE(us.file_count, 0) AS file_count,
                       COALESCE(SUM(CASE WHEN sf.is_trashed=1 AND sf.deleted_at IS NULL THEN 1 ELSE 0 END), 0) AS trashed_files
                FROM users u
                LEFT JOIN user_storage us ON us.user_id=u.id
                LEFT JOIN storage_files sf ON sf.owner_user_id=u.id
                GROUP BY u.id, u.username, us.quota_bytes, us.used_bytes, us.reserved_bytes, us.file_count
                ORDER BY used_bytes DESC, file_count DESC, u.id ASC
                LIMIT 200
                """
            ).fetchall()
            return json_resp({"ok": True, "users": [dict(row) for row in rows]})
        finally:
            conn.close()

    @app.route("/api/root/storage/users", methods=["GET"])
    @require_csrf_safe
    def root_storage_users():
        actor, err = _root_or_403()
        if err:
            return err
        query = (request.args.get("q") or "").strip().lower()
        conn = get_db()
        try:
            ensure_storage_album_schema(conn)
            rows = conn.execute("SELECT * FROM users ORDER BY username ASC, id ASC LIMIT 300").fetchall()
            users = []
            for row in rows:
                usage = _storage_usage_for_user_row(conn, row)
                if query and query not in str(usage.get("username") or "").lower():
                    continue
                users.append(usage)
            return json_resp({"ok": True, "users": users})
        finally:
            conn.close()

    @app.route("/api/root/storage/users/<int:user_id>", methods=["GET"])
    @require_csrf_safe
    def root_storage_user_detail(user_id):
        actor, err = _root_or_403()
        if err:
            return err
        include_trashed = request.args.get("include_trashed") in {"1", "true", "yes"}
        conn = get_db()
        try:
            ensure_storage_album_schema(conn)
            row = conn.execute("SELECT * FROM users WHERE id=?", (int(user_id),)).fetchone()
            if not row:
                return json_resp({"ok": False, "msg": "找不到帳號"}, 404)
            where = "sf.owner_user_id=? AND sf.deleted_at IS NULL AND f.deleted_at IS NULL"
            params = [int(user_id)]
            if not include_trashed:
                where += " AND sf.is_trashed=0"
            files = conn.execute(
                f"""
                SELECT sf.*, f.size_bytes, f.scan_status, f.risk_level, f.privacy_mode
                FROM storage_files sf
                JOIN uploaded_files f ON f.id=sf.file_id
                WHERE {where}
                ORDER BY sf.updated_at DESC
                LIMIT 300
                """,
                tuple(params),
            ).fetchall()
            return json_resp({
                "ok": True,
                "user": _storage_usage_for_user_row(conn, row),
                "files": [dict(item) for item in files],
            })
        finally:
            conn.close()

    @app.route("/api/root/storage/users/<int:user_id>/quota-override", methods=["PUT"])
    @require_csrf
    def root_storage_set_quota_override(user_id):
        actor, err = _root_or_403()
        if err:
            return err
        try:
            data = request.get_json(force=True) or {}
        except Exception:
            return json_resp({"ok": False, "msg": "Invalid JSON"}, 400)
        try:
            quota_bytes = _optional_mb_to_bytes(data.get("quota_mb"), "quota_mb")
            max_file_size_bytes = _optional_mb_to_bytes(data.get("max_file_size_mb"), "max_file_size_mb")
            upload_rate_limit = _optional_nonnegative_int(data.get("upload_rate_limit_per_day"), "upload_rate_limit_per_day")
        except ValueError as exc:
            return json_resp({"ok": False, "msg": str(exc)}, 400)
        try:
            can_upload_override = _optional_bool(data.get("can_upload"))
        except ValueError as exc:
            return json_resp({"ok": False, "msg": str(exc)}, 400)
        reason = (data.get("reason") or "").strip()
        if not reason:
            return json_resp({"ok": False, "msg": "請填寫 root 覆寫原因"}, 400)
        conn = get_db()
        try:
            target = conn.execute("SELECT * FROM users WHERE id=?", (int(user_id),)).fetchone()
            if not target:
                return json_resp({"ok": False, "msg": "找不到帳號"}, 404)
            if quota_bytes is not None and target["username"] != "root":
                current_usage = _storage_usage_for_user_row(conn, target)
                current_total = int(current_usage.get("total_bytes") or 0)
                additional_bytes = max(0, int(quota_bytes) - current_total)
                if additional_bytes:
                    capacity_ok, capacity_msg, capacity_audit = can_allocate_storage_bytes(conn, storage_root, additional_bytes)
                    if not capacity_ok:
                        return json_resp({
                            "ok": False,
                            "msg": capacity_msg,
                            "storage_capacity": capacity_audit,
                        }), 409
            override = set_storage_quota_override(
                conn,
                user_id,
                enabled=bool(data.get("enabled", True)),
                quota_bytes=quota_bytes,
                max_file_size_bytes=max_file_size_bytes,
                upload_rate_limit_per_day=upload_rate_limit,
                can_upload_override=can_upload_override,
                reason=reason,
                actor_user_id=_actor_value(actor, "id"),
            )
            conn.commit()
            audit(
                "ROOT_STORAGE_QUOTA_OVERRIDE",
                get_client_ip(),
                user=actor["username"],
                success=True,
                ua=get_ua(),
                detail=f"user_id={user_id}, quota_bytes={quota_bytes}, max_file_size_bytes={max_file_size_bytes}, rate={upload_rate_limit}",
            )
            return json_resp({"ok": True, "override": override, "user": _storage_usage_for_user_row(conn, target)})
        finally:
            conn.close()

    @app.route("/api/root/storage/users/<int:user_id>/quota-override", methods=["DELETE"])
    @require_csrf
    def root_storage_clear_quota_override(user_id):
        actor, err = _root_or_403()
        if err:
            return err
        conn = get_db()
        try:
            target = conn.execute("SELECT * FROM users WHERE id=?", (int(user_id),)).fetchone()
            if not target:
                return json_resp({"ok": False, "msg": "找不到帳號"}, 404)
            clear_storage_quota_override(conn, user_id)
            conn.commit()
            audit("ROOT_STORAGE_QUOTA_OVERRIDE_CLEAR", get_client_ip(), user=actor["username"], success=True, ua=get_ua(), detail=f"user_id={user_id}")
            return json_resp({"ok": True, "user": _storage_usage_for_user_row(conn, target)})
        finally:
            conn.close()

    @app.route("/api/admin/storage/files", methods=["GET"])
    @require_csrf_safe
    def admin_storage_files():
        actor, err = _manager_or_403()
        if err:
            return err
        user_id = request.args.get("user_id")
        include_trashed = request.args.get("include_trashed") in {"1", "true", "yes"}
        conn = get_db()
        try:
            ensure_storage_album_schema(conn)
            where = "sf.deleted_at IS NULL AND f.deleted_at IS NULL"
            params = []
            if user_id:
                where += " AND sf.owner_user_id=?"
                params.append(int(user_id))
            if not include_trashed:
                where += " AND sf.is_trashed=0"
            rows = conn.execute(
                f"""
                SELECT sf.*, f.size_bytes, f.scan_status, f.risk_level, f.privacy_mode,
                       u.username AS owner_username
                FROM storage_files sf
                JOIN uploaded_files f ON f.id=sf.file_id
                JOIN users u ON u.id=sf.owner_user_id
                WHERE {where}
                ORDER BY sf.updated_at DESC
                LIMIT 200
                """,
                tuple(params),
            ).fetchall()
            return json_resp({"ok": True, "files": [dict(row) for row in rows]})
        finally:
            conn.close()

    @app.route("/api/admin/storage/sync-quota", methods=["POST"])
    @require_csrf
    def admin_storage_sync_quota():
        actor, err = _manager_or_403()
        if err:
            return err
        conn = get_db()
        try:
            ensure_storage_album_schema(conn)
            rows = conn.execute("SELECT id FROM users ORDER BY id ASC").fetchall()
            synced = []
            for row in rows:
                synced.append(sync_user_storage_summary(conn, row["id"], actor_user_id=actor["id"], source="admin", reason="admin_sync_quota"))
            conn.commit()
            audit("STORAGE_ADMIN_SYNC_QUOTA", get_client_ip(), user=actor["username"], success=True, ua=get_ua(), detail=f"users={len(synced)}")
            return json_resp({"ok": True, "synced": synced})
        finally:
            conn.close()

    @app.route("/api/admin/storage/trash/purge", methods=["POST"])
    @require_csrf
    def admin_storage_purge_trash():
        actor, err = _manager_or_403()
        if err:
            return err
        if not _is_root(actor):
            return json_resp({"ok": False, "msg": "只有 root 可清理 storage 回收筒"}), 403
        try:
            data = request.get_json(force=True)
        except Exception:
            return json_resp({"ok": False, "msg": "Invalid JSON"}), 400
        if data.get("confirm") != "PURGE STORAGE TRASH":
            return json_resp({"ok": False, "msg": "confirm 必須等於 PURGE STORAGE TRASH"}), 400
        conn = get_db()
        try:
            ensure_storage_album_schema(conn)
            user_id = data.get("user_id")
            where = "is_trashed=1 AND deleted_at IS NULL"
            params = []
            if user_id:
                where += " AND owner_user_id=?"
                params.append(int(user_id))
            now = datetime.now().isoformat()
            cur = conn.execute(f"UPDATE storage_files SET deleted_at=?, updated_at=? WHERE {where}", (now, now, *params))
            users = conn.execute("SELECT id FROM users ORDER BY id ASC").fetchall()
            for row in users:
                sync_user_storage_summary(conn, row["id"], actor_user_id=actor["id"], source="admin", reason="admin_purge_trash")
            conn.commit()
            audit("STORAGE_ADMIN_PURGE_TRASH", get_client_ip(), user=actor["username"], success=True, ua=get_ua(), detail=f"purged={cur.rowcount}, user_id={user_id or '*'}")
            return json_resp({"ok": True, "purged": cur.rowcount})
        finally:
            conn.close()

    @app.route("/api/admin/storage/maintenance", methods=["GET", "POST"])
    @require_csrf_safe
    def admin_storage_maintenance():
        actor, err = _manager_or_403()
        if err:
            return err
        get_system_settings = deps.get("get_system_settings")
        settings = get_system_settings() if get_system_settings else {}
        if request.method == "GET":
            return json_resp({"ok": True, "maintenance": storage_maintenance_status(settings)})
        conn = get_db()
        try:
            result = run_storage_maintenance(
                conn,
                actor_user_id=actor["id"],
                retention_days=settings.get("storage_trash_retention_days", 30),
            )
            conn.commit()
            audit("STORAGE_MAINTENANCE_RUN", get_client_ip(), user=actor["username"], success=True, ua=get_ua(), detail=str(result))
            return json_resp({"ok": True, "maintenance": result})
        finally:
            conn.close()

    @app.route("/api/files/quota", methods=["GET"])
    @require_csrf_safe
    def file_quota():
        actor, err = _actor_or_401()
        if err:
            return err
        conn = get_db()
        try:
            rule = get_member_level_rule(conn, actor["effective_level"] or actor["member_level"])
            usage = get_user_cloud_drive_usage(conn, actor, member_rule=rule, storage_root=storage_root)
            return json_resp({"ok": True, "quota": usage})
        finally:
            conn.close()

    @app.route("/api/cloud-drive/storage-upgrades", methods=["GET"])
    @require_csrf_safe
    def cloud_drive_storage_upgrades():
        actor, err = _actor_or_401()
        if err:
            return err
        if not points_service:
            return json_resp({"ok": False, "msg": "積分服務未啟用"}), 503
        conn = get_db()
        try:
            level = _actor_value(actor, "effective_level") or _actor_value(actor, "member_level") or "newbie"
            rule = get_member_level_rule(conn, level)
            usage = get_user_cloud_drive_usage(conn, actor, member_rule=rule, storage_root=storage_root)
            catalog = _storage_upgrade_catalog(conn)
            can_purchase = not _is_root(actor)
            message = "root 依實際磁碟容量控管，不需要用積分購買容量" if _is_root(actor) else ""
            capacity_audit = audit_storage_capacity(conn, storage_root)
            if can_purchase:
                headroom = min(
                    max(0, int(capacity_audit["allocatable_cloud_capacity_bytes"]) - int(capacity_audit["committed_total_bytes"])),
                    max(0, int(capacity_audit["disk"]["safe_free_bytes"]) - int(capacity_audit["committed_remaining_bytes"])),
                )
                catalog = [item for item in catalog if int(item.get("storage_bytes") or 0) <= headroom]
                if not catalog:
                    can_purchase = False
                    message = "Host 磁碟可承諾容量不足，目前不能購買更多雲端容量"
            return json_resp({
                "ok": True,
                "can_purchase": can_purchase,
                "message": message,
                "catalog": catalog,
                "active_purchases": active_storage_quota_purchases(conn, _actor_value(actor, "id")),
                "usage": usage,
                "storage_capacity": capacity_audit,
            })
        finally:
            conn.close()

    @app.route("/api/cloud-drive/storage-upgrades/purchase", methods=["POST"])
    @require_csrf
    def cloud_drive_purchase_storage_upgrade():
        actor, err = _actor_or_401()
        if err:
            return err
        if _is_root(actor):
            return json_resp({"ok": False, "msg": "root 不需要用積分購買容量"}), 403
        if not points_service:
            return json_resp({"ok": False, "msg": "積分服務未啟用"}), 503
        data, err, status = _parse_json_body()
        if err:
            return err, status
        item_key = str(data.get("item_key") or "").strip()
        try:
            quantity = int(data.get("quantity") or 1)
        except Exception:
            return json_resp({"ok": False, "msg": "購買數量必須是整數"}), 400
        if quantity < 1 or quantity > 20:
            return json_resp({"ok": False, "msg": "單次購買數量需介於 1 到 20"}), 400
        conn = get_db()
        try:
            catalog = _storage_upgrade_catalog(conn)
            product = next((item for item in catalog if item.get("item_key") == item_key), None)
            if not product:
                return json_resp({"ok": False, "msg": "容量商品未啟用"}), 400
            additional_bytes = int(product["storage_bytes"]) * quantity
            capacity_ok, capacity_msg, capacity_audit = can_allocate_storage_bytes(conn, storage_root, additional_bytes)
            if not capacity_ok:
                return json_resp({
                    "ok": False,
                    "msg": capacity_msg,
                    "storage_capacity": capacity_audit,
                }), 409
        finally:
            conn.close()
        try:
            spend = points_service.spend_points(
                user_id=_actor_value(actor, "id"),
                item_key=item_key,
                quantity=quantity,
                reference_type="cloud_storage_upgrade",
                reference_id=item_key,
                idempotency_key=f"cloud_storage_upgrade:{_actor_value(actor, 'id')}:{uuid.uuid4().hex}",
                metadata={
                    "storage_bytes": additional_bytes,
                    "duration_days": int(product["duration_days"]),
                },
                actor=actor,
            )
        except Exception as exc:
            return _points_error(exc)

        conn = get_db()
        purchase_committed = False
        try:
            conn.commit()
            conn.execute("BEGIN IMMEDIATE")
            capacity_ok, capacity_msg, capacity_audit = can_allocate_storage_bytes(conn, storage_root, additional_bytes)
            if not capacity_ok:
                conn.rollback()
                _refund_storage_upgrade_spend(
                    spend,
                    actor,
                    reason=f"storage allocation failed after debit: {capacity_msg}",
                )
                return json_resp({
                    "ok": False,
                    "msg": capacity_msg,
                    "storage_capacity": capacity_audit,
                }), 409
            ledger = spend.get("ledger") or {}
            purchase = record_storage_quota_purchase(
                conn,
                user_id=_actor_value(actor, "id"),
                item_key=item_key,
                quantity=quantity,
                points_spent=ledger.get("amount") or (spend.get("item") or {}).get("base_price", 0) * quantity,
                ledger_uuid=ledger.get("ledger_uuid"),
            )
            level = _actor_value(actor, "effective_level") or _actor_value(actor, "member_level") or "newbie"
            usage = get_user_cloud_drive_usage(conn, actor, member_rule=get_member_level_rule(conn, level), storage_root=storage_root)
            conn.commit()
            purchase_committed = True
            audit(
                "CLOUD_STORAGE_UPGRADE_PURCHASE",
                get_client_ip(),
                user=_actor_value(actor, "username"),
                success=True,
                ua=get_ua(),
                detail=f"item_key={item_key}, quantity={quantity}, bytes={purchase['purchased_bytes']}",
            )
            return json_resp({"ok": True, "purchase": purchase, "wallet": spend.get("wallet"), "usage": usage})
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass
            if not purchase_committed:
                _refund_storage_upgrade_spend(
                    spend,
                    actor,
                    reason="storage upgrade allocation exception after debit",
                )
            raise
        finally:
            conn.close()

    @app.route("/api/cloud-drive/files", methods=["GET"])
    @require_csrf_safe
    def cloud_drive_files():
        actor, err = _actor_or_401()
        if err:
            return err
        conn = get_db()
        try:
            ensure_cloud_drive_attachment_schema(conn)
            rows = list_cloud_files(conn, actor, limit=100, offset=0)
            return json_resp({"ok": True, "files": rows})
        finally:
            conn.close()

    def _form_json_value(name):
        raw = (request.form.get(name) or "").strip()
        if not raw:
            return None
        try:
            import json
            return json.loads(raw)
        except Exception:
            return None

    @app.route("/api/storage/files", methods=["GET", "POST"])
    @require_csrf_safe
    def storage_files():
        actor, err = _actor_or_401()
        if err:
            return err
        conn = get_db()
        try:
            ensure_cloud_drive_attachment_schema(conn)
            ensure_storage_album_schema(conn)
            if request.method == "GET":
                include_trashed = request.args.get("include_trashed") in {"1", "true", "yes"}
                files = list_storage_files(conn, actor=actor, include_trashed=include_trashed, limit=100, offset=0)
                summary = sync_user_storage_summary(conn, actor["id"], actor_user_id=actor["id"], source="list", reason="storage_files_list")
                conn.commit()
                return json_resp({"ok": True, "files": files, "storage": summary})
            if "file" not in request.files:
                return json_resp({"ok": False, "msg": "缺少 file"}), 400
            rule = get_member_level_rule(conn, _actor_value(actor, "effective_level") or _actor_value(actor, "member_level"))
            upload_result, msg = store_cloud_upload(
                conn,
                actor=actor,
                member_rule=rule,
                storage_root=storage_root,
                file_storage=request.files["file"],
                privacy_mode=(request.form.get("privacy_mode") or "private_scannable").strip(),
                encrypted_metadata=(request.form.get("encrypted_metadata") or "").strip() or None,
                encrypted_file_key=(request.form.get("encrypted_file_key") or "").strip() or None,
                wrapped_by=(request.form.get("wrapped_by") or "user_public_key").strip() or "user_public_key",
                ciphertext_sha256=(request.form.get("ciphertext_sha256") or "").strip() or None,
                encryption_algorithm=(request.form.get("encryption_algorithm") or "").strip() or None,
                encryption_version=(request.form.get("encryption_version") or "").strip() or None,
                nonce=(request.form.get("nonce") or "").strip() or None,
                client_scan_report=_form_json_value("client_scan_report"),
                scan_now=True,
            )
            if msg:
                conn.rollback()
                return json_resp({"ok": False, "msg": msg}), 400
            file_row = conn.execute("SELECT * FROM uploaded_files WHERE id=?", (upload_result["file_id"],)).fetchone()
            storage_file, msg = create_storage_file_entry(
                conn,
                actor=actor,
                file_row=file_row,
                virtual_path=(request.form.get("virtual_path") or "").strip(),
                display_name=(request.form.get("display_name") or "").strip() or None,
                source="upload",
            )
            if msg:
                conn.rollback()
                return json_resp({"ok": False, "msg": msg}), 400
            conn.commit()
            audit("STORAGE_FILE_UPLOAD", get_client_ip(), user=actor["username"], success=True, ua=get_ua(), detail=f"storage_file_id={storage_file['id']}")
            return json_resp({"ok": True, "file": upload_result, "storage_file": storage_file})
        finally:
            conn.close()

    @app.route("/api/storage/files/attach-existing", methods=["POST"])
    @require_csrf
    def storage_attach_existing():
        actor, err = _actor_or_401()
        if err:
            return err
        try:
            data = request.get_json(force=True)
        except Exception:
            return json_resp({"ok": False, "msg": "Invalid JSON"}), 400
        conn = get_db()
        try:
            ensure_storage_album_schema(conn)
            file_row = conn.execute("SELECT * FROM uploaded_files WHERE id=? AND deleted_at IS NULL", (str(data.get("file_id") or ""),)).fetchone()
            if not file_row:
                return json_resp({"ok": False, "msg": "找不到檔案或檔案已刪除"}), 404
            storage_file, msg = create_storage_file_entry(
                conn,
                actor=actor,
                file_row=file_row,
                virtual_path=data.get("virtual_path") or "",
                display_name=data.get("display_name") or None,
                source="attach_existing",
            )
            if msg:
                conn.rollback()
                return json_resp({"ok": False, "msg": msg}), 400
            conn.commit()
            audit("STORAGE_FILE_ATTACH_EXISTING", get_client_ip(), user=actor["username"], success=True, ua=get_ua(), detail=f"storage_file_id={storage_file['id']}")
            return json_resp({"ok": True, "storage_file": storage_file})
        finally:
            conn.close()

    @app.route("/api/storage/folders", methods=["GET", "POST", "DELETE"])
    @app.route("/api/storage/folders/trash", methods=["POST"])
    @require_csrf_safe
    def storage_folders():
        actor, err = _actor_or_401()
        if err:
            return err
        conn = get_db()
        try:
            ensure_storage_album_schema(conn)
            if request.method == "GET":
                return json_resp({"ok": True, "folders": list_storage_folders(conn, actor=actor)})
            try:
                data = request.get_json(force=True)
            except Exception:
                return json_resp({"ok": False, "msg": "Invalid JSON"}), 400
            data = data if isinstance(data, dict) else {}
            if request.method == "DELETE" or request.path.endswith("/trash"):
                result, msg = trash_storage_folder(conn, actor=actor, path=data.get("path") or "")
                if msg:
                    conn.rollback()
                    return json_resp({"ok": False, "msg": msg}), 400
                conn.commit()
                audit("STORAGE_FOLDER_TRASH", get_client_ip(), user=actor["username"], success=True, ua=get_ua(), detail=f"path={result['path']}")
                return json_resp({"ok": True, "folder_trash": result})
            folder, msg = create_storage_folder(conn, actor=actor, path=data.get("path") or "")
            if msg:
                conn.rollback()
                return json_resp({"ok": False, "msg": msg}), 400
            conn.commit()
            audit("STORAGE_FOLDER_CREATE", get_client_ip(), user=actor["username"], success=True, ua=get_ua(), detail=f"path={folder['virtual_path']}")
            return json_resp({"ok": True, "folder": folder})
        finally:
            conn.close()

    @app.route("/api/storage/folders/move", methods=["PUT"])
    @require_csrf
    def storage_folder_move():
        actor, err = _actor_or_401()
        if err:
            return err
        try:
            data = request.get_json(force=True)
        except Exception:
            return json_resp({"ok": False, "msg": "Invalid JSON"}), 400
        conn = get_db()
        try:
            result, msg = move_storage_folder(conn, actor=actor, old_path=data.get("old_path") or "", new_path=data.get("new_path") or "")
            if msg:
                conn.rollback()
                return json_resp({"ok": False, "msg": msg}), 400
            conn.commit()
            audit("STORAGE_FOLDER_MOVE", get_client_ip(), user=actor["username"], success=True, ua=get_ua(), detail=f"{result['old_path']} -> {result['new_path']}")
            return json_resp({"ok": True, "folder_move": result})
        finally:
            conn.close()

    @app.route("/api/storage/folders/album", methods=["POST"])
    @require_csrf
    def storage_folder_album():
        actor, err = _actor_or_401()
        if err:
            return err
        try:
            data = request.get_json(force=True)
        except Exception:
            return json_resp({"ok": False, "msg": "Invalid JSON"}), 400
        data = data if isinstance(data, dict) else {}
        conn = get_db()
        try:
            album, msg = create_album_from_storage_folder(
                conn,
                actor=actor,
                path=data.get("path") or "",
                title=data.get("title") or None,
                description=data.get("description") or "",
                visibility=data.get("visibility") or "private",
            )
            if msg:
                conn.rollback()
                return json_resp({"ok": False, "msg": msg}), 400
            conn.commit()
            audit(
                "STORAGE_FOLDER_TO_ALBUM",
                get_client_ip(),
                user=actor["username"],
                success=True,
                ua=get_ua(),
                detail=f"path={album.get('source_folder')}, album_id={album['id']}, files={album.get('added_count')}",
            )
            return json_resp({"ok": True, "album": album})
        finally:
            conn.close()

    @app.route("/api/storage/files/<storage_file_id>/organize", methods=["PUT"])
    @require_csrf
    def storage_file_organize(storage_file_id):
        actor, err = _actor_or_401()
        if err:
            return err
        try:
            data = request.get_json(force=True)
        except Exception:
            return json_resp({"ok": False, "msg": "Invalid JSON"}), 400
        conn = get_db()
        try:
            storage_file, msg = move_storage_file(conn, actor=actor, storage_file_id=storage_file_id, new_virtual_path=data.get("virtual_path") or "")
            if msg:
                conn.rollback()
                return json_resp({"ok": False, "msg": msg}), 400
            conn.commit()
            audit("STORAGE_FILE_ORGANIZE", get_client_ip(), user=actor["username"], success=True, ua=get_ua(), detail=f"storage_file_id={storage_file_id}, path={storage_file['virtual_path']}")
            return json_resp({"ok": True, "storage_file": storage_file})
        finally:
            conn.close()

    @app.route("/api/storage/files/<storage_file_id>/download", methods=["GET"])
    @require_csrf_safe
    def storage_file_download(storage_file_id):
        actor, err = _actor_or_401()
        if err:
            return err
        conn = get_db()
        try:
            ensure_storage_album_schema(conn)
            storage_file = get_storage_file(conn, actor=actor, storage_file_id=storage_file_id)
            if not storage_file or storage_file.get("deleted_at") or storage_file.get("file_deleted_at") or int(storage_file.get("is_trashed") or 0):
                return json_resp({"ok": False, "msg": "找不到檔案或檔案已刪除"}), 404
            allowed, reason, row = can_download_file(conn, actor=actor, file_id=storage_file["file_id"])
            if not row:
                return json_resp({"ok": False, "msg": "找不到檔案"}), 404
            if not allowed:
                if reason == "deleted":
                    return json_resp({"ok": False, "msg": "找不到檔案"}), 404
                conn.commit()
                return json_resp({"ok": False, "msg": "沒有下載權限或檔案尚未通過安全檢查", "reason": reason}), 403
            path = resolve_file_storage_path(storage_root, row)
            if not path.exists():
                return json_resp({"ok": False, "msg": "實體檔案不存在"}), 404
            log_file_access(conn, file_id=storage_file["file_id"], actor_user_id=actor["id"], action="storage_download", result="allowed", reason=reason, ip=get_client_ip(), user_agent=get_ua())
            conn.commit()
            return send_file(path, as_attachment=True, download_name=storage_file["display_name"] or row["original_filename_plain_for_public"] or "download.bin")
        finally:
            conn.close()

    @app.route("/api/storage/trash", methods=["GET"])
    @require_csrf_safe
    def storage_trash():
        actor, err = _actor_or_401()
        if err:
            return err
        conn = get_db()
        try:
            ensure_storage_album_schema(conn)
            files = list_storage_trash(conn, actor=actor, limit=100, offset=0)
            summary = sync_user_storage_summary(conn, actor["id"], actor_user_id=actor["id"], source="trash", reason="storage_trash_list")
            conn.commit()
            return json_resp({"ok": True, "files": files, "storage": summary})
        finally:
            conn.close()

    @app.route("/api/storage/trash/restore", methods=["POST"])
    @require_csrf
    def storage_trash_restore():
        actor, err = _actor_or_401()
        if err:
            return err
        conn = get_db()
        try:
            result, msg = restore_storage_trash(conn, actor=actor)
            if msg:
                conn.rollback()
                return json_resp({"ok": False, "msg": msg}), 400
            conn.commit()
            audit("STORAGE_TRASH_RESTORE_ALL", get_client_ip(), user=actor["username"], success=True, ua=get_ua(), detail=f"restored={result['restored']}")
            return json_resp({"ok": True, "trash": result})
        finally:
            conn.close()

    @app.route("/api/storage/trash/purge", methods=["DELETE"])
    @require_csrf
    def storage_trash_purge():
        actor, err = _actor_or_401()
        if err:
            return err
        conn = get_db()
        try:
            result, msg = purge_storage_trash(conn, actor=actor)
            if msg:
                conn.rollback()
                return json_resp({"ok": False, "msg": msg}), 400
            conn.commit()
            audit("STORAGE_TRASH_PURGE_ALL", get_client_ip(), user=actor["username"], success=True, ua=get_ua(), detail=f"purged={result['purged']}")
            return json_resp({"ok": True, "trash": result})
        finally:
            conn.close()

    @app.route("/api/storage/files/<storage_file_id>", methods=["DELETE"])
    @require_csrf
    def storage_file_trash(storage_file_id):
        actor, err = _actor_or_401()
        if err:
            return err
        conn = get_db()
        try:
            storage_file, msg = trash_storage_file(conn, actor=actor, storage_file_id=storage_file_id)
            if msg:
                conn.rollback()
                return json_resp({"ok": False, "msg": msg}), 404
            conn.commit()
            audit("STORAGE_FILE_TRASH", get_client_ip(), user=actor["username"], success=True, ua=get_ua(), detail=f"storage_file_id={storage_file_id}")
            return json_resp({"ok": True, "storage_file": storage_file})
        finally:
            conn.close()

    @app.route("/api/storage/files/<storage_file_id>/restore", methods=["POST"])
    @require_csrf
    def storage_file_restore(storage_file_id):
        actor, err = _actor_or_401()
        if err:
            return err
        conn = get_db()
        try:
            storage_file, msg = restore_storage_file(conn, actor=actor, storage_file_id=storage_file_id)
            if msg:
                conn.rollback()
                return json_resp({"ok": False, "msg": msg}), 404
            conn.commit()
            audit("STORAGE_FILE_RESTORE", get_client_ip(), user=actor["username"], success=True, ua=get_ua(), detail=f"storage_file_id={storage_file_id}")
            return json_resp({"ok": True, "storage_file": storage_file})
        finally:
            conn.close()

    @app.route("/api/storage/files/<storage_file_id>/purge", methods=["DELETE"])
    @require_csrf
    def storage_file_purge(storage_file_id):
        actor, err = _actor_or_401()
        if err:
            return err
        conn = get_db()
        try:
            result, msg = purge_storage_file(conn, actor=actor, storage_file_id=storage_file_id)
            if msg:
                conn.rollback()
                return json_resp({"ok": False, "msg": msg}), 404
            conn.commit()
            audit("STORAGE_FILE_PURGE", get_client_ip(), user=actor["username"], success=True, ua=get_ua(), detail=f"storage_file_id={storage_file_id}")
            return json_resp({"ok": True, "purged": result})
        finally:
            conn.close()

    @app.route("/api/storage/albums", methods=["GET", "POST"])
    @require_csrf_safe
    def storage_albums():
        actor, err = _actor_or_401()
        if err:
            return err
        conn = get_db()
        try:
            ensure_storage_album_schema(conn)
            if request.method == "GET":
                albums = list_albums(conn, actor=actor, limit=100, offset=0)
                return json_resp({"ok": True, "albums": albums})
            try:
                data = request.get_json(force=True)
            except Exception:
                return json_resp({"ok": False, "msg": "Invalid JSON"}), 400
            album, msg = create_album(
                conn,
                actor=actor,
                title=data.get("title"),
                description=data.get("description") or "",
                visibility=data.get("visibility") or "private",
            )
            if msg:
                conn.rollback()
                return json_resp({"ok": False, "msg": msg}), 400
            conn.commit()
            audit("STORAGE_ALBUM_CREATE", get_client_ip(), user=actor["username"], success=True, ua=get_ua(), detail=f"album_id={album['id']}")
            return json_resp({"ok": True, "album": album})
        finally:
            conn.close()

    @app.route("/api/storage/albums/<album_id>", methods=["GET", "PUT", "DELETE"])
    @require_csrf_safe
    def storage_album_detail(album_id):
        actor, err = _actor_or_401()
        if err:
            return err
        conn = get_db()
        try:
            ensure_storage_album_schema(conn)
            if request.method == "GET":
                album = get_album(conn, actor=actor, album_id=album_id, include_files=True)
                if not album:
                    return json_resp({"ok": False, "msg": "找不到相簿"}), 404
                return json_resp({"ok": True, "album": album})
            if request.method == "DELETE":
                result, msg = delete_album(conn, actor=actor, album_id=album_id)
                if msg:
                    conn.rollback()
                    return json_resp({"ok": False, "msg": msg}), 404
                conn.commit()
                audit("STORAGE_ALBUM_DELETE", get_client_ip(), user=actor["username"], success=True, ua=get_ua(), detail=f"album_id={album_id}")
                return json_resp({"ok": True, "deleted": result})
            try:
                data = request.get_json(force=True)
            except Exception:
                return json_resp({"ok": False, "msg": "Invalid JSON"}), 400
            album, msg = update_album(
                conn,
                actor=actor,
                album_id=album_id,
                title=data.get("title") if "title" in data else None,
                description=data.get("description") if "description" in data else None,
                visibility=data.get("visibility") if "visibility" in data else None,
            )
            if msg:
                conn.rollback()
                return json_resp({"ok": False, "msg": msg}), 400
            conn.commit()
            audit("STORAGE_ALBUM_UPDATE", get_client_ip(), user=actor["username"], success=True, ua=get_ua(), detail=f"album_id={album_id}")
            return json_resp({"ok": True, "album": album})
        finally:
            conn.close()

    @app.route("/api/storage/albums/<album_id>/files", methods=["POST"])
    @require_csrf
    def storage_album_add_file(album_id):
        actor, err = _actor_or_401()
        if err:
            return err
        try:
            data = request.get_json(force=True)
        except Exception:
            return json_resp({"ok": False, "msg": "Invalid JSON"}), 400
        conn = get_db()
        try:
            album, msg = add_album_file(
                conn,
                actor=actor,
                album_id=album_id,
                storage_file_id=data.get("storage_file_id"),
                file_id=data.get("file_id"),
                caption=data.get("caption") or "",
                sort_order=data.get("sort_order") or 0,
            )
            if msg:
                conn.rollback()
                return json_resp({"ok": False, "msg": msg}), 400
            conn.commit()
            audit("STORAGE_ALBUM_FILE_ADD", get_client_ip(), user=actor["username"], success=True, ua=get_ua(), detail=f"album_id={album_id}")
            return json_resp({"ok": True, "album": album})
        finally:
            conn.close()

    @app.route("/api/storage/albums/<album_id>/files/<album_file_id>", methods=["DELETE"])
    @require_csrf
    def storage_album_remove_file(album_id, album_file_id):
        actor, err = _actor_or_401()
        if err:
            return err
        conn = get_db()
        try:
            album, msg = remove_album_file(conn, actor=actor, album_id=album_id, album_file_id=album_file_id)
            if msg:
                conn.rollback()
                return json_resp({"ok": False, "msg": msg}), 404
            conn.commit()
            audit("STORAGE_ALBUM_FILE_REMOVE", get_client_ip(), user=actor["username"], success=True, ua=get_ua(), detail=f"album_id={album_id}, album_file_id={album_file_id}")
            return json_resp({"ok": True, "album": album})
        finally:
            conn.close()

    @app.route("/api/storage/share-links", methods=["GET", "POST"])
    @require_csrf_safe
    def storage_share_links():
        actor, err = _actor_or_401()
        if err:
            return err
        conn = get_db()
        try:
            ensure_storage_album_schema(conn)
            if request.method == "GET":
                links = list_share_links(conn, actor=actor, storage_file_id=request.args.get("storage_file_id"))
                return json_resp({"ok": True, "share_links": links})
            try:
                data = request.get_json(force=True)
            except Exception:
                return json_resp({"ok": False, "msg": "Invalid JSON"}), 400
            link, msg = create_share_link(
                conn,
                actor=actor,
                storage_file_id=data.get("storage_file_id"),
                expires_at=data.get("expires_at") or None,
                can_preview=bool(data.get("can_preview", False)),
            )
            if msg:
                conn.rollback()
                return json_resp({"ok": False, "msg": msg}), 400
            conn.commit()
            audit("STORAGE_SHARE_LINK_CREATE", get_client_ip(), user=actor["username"], success=True, ua=get_ua(), detail=f"share_link_id={link['id']}")
            return json_resp({"ok": True, "share_link": link})
        finally:
            conn.close()

    @app.route("/api/storage/share-links/<link_id>/revoke", methods=["POST"])
    @require_csrf
    def storage_share_link_revoke(link_id):
        actor, err = _actor_or_401()
        if err:
            return err
        conn = get_db()
        try:
            link, msg = revoke_share_link(conn, actor=actor, link_id=link_id)
            if msg:
                conn.rollback()
                return json_resp({"ok": False, "msg": msg}), 404
            conn.commit()
            audit("STORAGE_SHARE_LINK_REVOKE", get_client_ip(), user=actor["username"], success=True, ua=get_ua(), detail=f"share_link_id={link_id}")
            return json_resp({"ok": True, "share_link": link})
        finally:
            conn.close()

    @app.route("/api/storage/shared/<token>/download", methods=["GET"])
    def storage_share_link_download(token):
        conn = get_db()
        try:
            row, reason = resolve_share_token(conn, token)
            if not row:
                return json_resp({"ok": False, "msg": "分享連結不存在或已失效", "reason": reason}), 404
            policy = get_cloud_drive_security_policy(conn)
            if policy.get("block_unclean_downloads") and not str(row["privacy_mode"]).startswith("e2ee") and row["scan_status"] not in {"clean", "not_required"}:
                return json_resp({"ok": False, "msg": "檔案尚未通過安全檢查"}), 403
            if _requires_download_warning(policy, row):
                confirmed = (
                    request.args.get("confirm_high_risk") == "1"
                    or request.headers.get("X-Confirm-High-Risk-Download", "").lower() in {"1", "true", "yes"}
                )
                if not confirmed:
                    return json_resp({
                        "ok": False,
                        "requires_confirmation": True,
                        "msg": "此分享檔案為高風險或無法完整掃描，請確認信任來源後再下載。",
                        "risk_level": row["risk_level"],
                        "scan_status": row["scan_status"],
                    }), 409
            path = resolve_file_storage_path(storage_root, row)
            if not path.exists():
                return json_resp({"ok": False, "msg": "實體檔案不存在"}), 404
            mark_share_link_accessed(conn, row["id"])
            log_file_access(conn, file_id=row["file_id"], actor_user_id=None, action="storage_share_download", result="allowed", reason="share_link", ip=get_client_ip(), user_agent=get_ua())
            conn.commit()
            return send_file(path, as_attachment=True, download_name=row["display_name"] or row["original_filename_plain_for_public"] or "download.bin")
        finally:
            conn.close()

    @app.route("/api/files/upload", methods=["POST"])
    @app.route("/api/cloud-drive/upload", methods=["POST"])
    @require_csrf
    def cloud_drive_upload():
        actor, err = _actor_or_401()
        if err:
            return err
        if "file" not in request.files:
            return json_resp({"ok": False, "msg": "缺少 file"}), 400
        privacy_mode = (request.form.get("privacy_mode") or "public_attachment").strip()
        context_type = (request.form.get("context_type") or "").strip()
        context_id = (request.form.get("context_id") or "").strip()
        grant_user_ids = []
        for value in request.form.getlist("grant_user_ids"):
            try:
                grant_user_ids.append(int(value))
            except Exception:
                pass
        grant_role = (request.form.get("grant_role") or "").strip() or None
        conn = get_db()
        try:
            ensure_cloud_drive_attachment_schema(conn)
            rule = get_member_level_rule(conn, _actor_value(actor, "effective_level") or _actor_value(actor, "member_level"))
            try:
                result, msg = store_cloud_upload(
                    conn,
                    actor=actor,
                    member_rule=rule,
                    storage_root=storage_root,
                    file_storage=request.files["file"],
                    privacy_mode=privacy_mode,
                    encrypted_metadata=(request.form.get("encrypted_metadata") or "").strip() or None,
                    encrypted_file_key=(request.form.get("encrypted_file_key") or "").strip() or None,
                    wrapped_by=(request.form.get("wrapped_by") or "user_public_key").strip() or "user_public_key",
                    ciphertext_sha256=(request.form.get("ciphertext_sha256") or "").strip() or None,
                    encryption_algorithm=(request.form.get("encryption_algorithm") or "").strip() or None,
                    encryption_version=(request.form.get("encryption_version") or "").strip() or None,
                    nonce=(request.form.get("nonce") or "").strip() or None,
                    client_scan_report=_form_json_value("client_scan_report"),
                    scan_now=True,
                )
            except ValueError as exc:
                conn.rollback()
                return json_resp({"ok": False, "msg": f"雲端硬碟上傳失敗：{str(exc) or exc.__class__.__name__}", "error_code": exc.__class__.__name__}), 400
            except Exception as exc:
                conn.rollback()
                audit("CLOUD_DRIVE_UPLOAD_ERROR", get_client_ip(), user=actor["username"], success=False, ua=get_ua(), detail=exc.__class__.__name__)
                return json_resp({"ok": False, "msg": f"雲端硬碟上傳失敗：{exc.__class__.__name__}", "error_code": exc.__class__.__name__}), 500
            if msg:
                conn.rollback()
                return json_resp({"ok": False, "msg": msg}), 400
            attach_result = None
            if context_type and context_id:
                attach_result, msg = attach_existing_file(
                    conn,
                    actor=actor,
                    file_id=result["file_id"],
                    context_type=context_type,
                    context_id=context_id,
                    grant_user_ids=grant_user_ids,
                    grant_role=grant_role,
                    can_preview=True,
                )
                if msg:
                    conn.rollback()
                    return json_resp({"ok": False, "msg": msg}), 400
            conn.commit()
            audit("CLOUD_DRIVE_UPLOAD", get_client_ip(), user=actor["username"], success=True, ua=get_ua(), detail=f"file_id={result['file_id']}")
            return json_resp({"ok": True, "file": result, "attachment": attach_result})
        finally:
            conn.close()

    @app.route("/api/cloud-drive/remote-download/capabilities", methods=["GET"])
    @require_csrf_safe
    def cloud_drive_remote_download_capabilities():
        actor, err = _actor_or_401()
        if err:
            return err
        return json_resp({"ok": True, "capabilities": remote_download_capabilities()})

    @app.route("/api/cloud-drive/remote-download/tasks", methods=["POST"])
    @require_csrf
    def cloud_drive_remote_download_task_create():
        actor, err = _actor_or_401()
        if err:
            return err
        try:
            data = request.get_json(force=True)
        except Exception:
            return json_resp({"ok": False, "msg": "Invalid JSON"}), 400
        data = data if isinstance(data, dict) else {}
        url = str(data.get("url") or "").strip()
        if not url:
            return json_resp({"ok": False, "msg": "請輸入下載網址"}), 400
        try:
            validate_remote_url(url)
        except RemoteDownloadError as exc:
            return json_resp({"ok": False, "msg": str(exc)}), 400
        if _user_has_active_remote_download(_actor_value(actor, "id")):
            return json_resp({"ok": False, "msg": "已有遠端下載正在進行，請等完成後再新增"}), 409
        privacy_mode = str(data.get("privacy_mode") or "private_scannable").strip() or "private_scannable"
        virtual_path = str(data.get("virtual_path") or "").strip()
        task_id = uuid.uuid4().hex
        try:
            actor_snapshot = dict(actor)
        except Exception:
            actor_snapshot = {
                "id": _actor_value(actor, "id"),
                "username": _actor_value(actor, "username"),
                "role": _actor_value(actor, "role"),
                "member_level": _actor_value(actor, "member_level"),
                "effective_level": _actor_value(actor, "effective_level"),
            }
        now = datetime.now().isoformat()
        task = {
            "id": task_id,
            "kind": "remote_download",
            "source_type": "url",
            "status": "queued",
            "phase": "queued",
            "filename": "",
            "url": url,
            "torrent_filename": "",
            "torrent_path": "",
            "torrent_cleanup_dir": "",
            "owner_user_id": int(_actor_value(actor, "id")),
            "actor": actor_snapshot,
            "privacy_mode": privacy_mode,
            "virtual_path": virtual_path,
            "timeout_seconds": 1800 if url.startswith("magnet:?") else 120,
            "loaded_bytes": 0,
            "total_bytes": None,
            "progress_percent": 0,
            "msg": "已加入下載佇列",
            "error": "",
            "file": None,
            "storage_file": None,
            "ip": get_client_ip(),
            "ua": get_ua(),
            "created_at": now,
            "updated_at": now,
        }
        with _REMOTE_DOWNLOAD_TASKS_LOCK:
            _REMOTE_DOWNLOAD_TASKS[task_id] = task
        worker = threading.Thread(target=_run_remote_download_task, args=(task_id,), daemon=True)
        worker.start()
        return json_resp({"ok": True, "task": _task_snapshot(task)}, 202)

    @app.route("/api/cloud-drive/remote-download/torrent-tasks", methods=["POST"])
    @require_csrf
    def cloud_drive_remote_download_torrent_task_create():
        actor, err = _actor_or_401()
        if err:
            return err
        uploaded = request.files.get("torrent_file") or request.files.get("torrent")
        if not uploaded or not uploaded.filename:
            return json_resp({"ok": False, "msg": "請上傳 .torrent BT 種子檔"}), 400
        filename = safe_public_filename(uploaded.filename)
        if not filename.lower().endswith(".torrent"):
            return json_resp({"ok": False, "msg": "只接受 .torrent BT 種子檔"}), 400

        tmpdir = tempfile.mkdtemp(prefix="hackme_torrent_")
        torrent_path = os.path.join(tmpdir, filename)
        try:
            uploaded.save(torrent_path)
            try:
                torrent_size = os.path.getsize(torrent_path)
            except OSError:
                torrent_size = 0
            if torrent_size <= 0:
                shutil.rmtree(tmpdir, ignore_errors=True)
                return json_resp({"ok": False, "msg": "BT 種子檔是空的"}), 400
            if torrent_size > 2 * 1024 * 1024:
                shutil.rmtree(tmpdir, ignore_errors=True)
                return json_resp({"ok": False, "msg": "BT 種子檔太大，請上傳 2MB 以內的 .torrent"}), 400
            if _user_has_active_remote_download(_actor_value(actor, "id")):
                shutil.rmtree(tmpdir, ignore_errors=True)
                return json_resp({"ok": False, "msg": "已有遠端下載正在進行，請等完成後再新增"}), 409

            privacy_mode = str(request.form.get("privacy_mode") or "private_scannable").strip() or "private_scannable"
            virtual_path = str(request.form.get("virtual_path") or "").strip()
            task_id = uuid.uuid4().hex
            try:
                actor_snapshot = dict(actor)
            except Exception:
                actor_snapshot = {
                    "id": _actor_value(actor, "id"),
                    "username": _actor_value(actor, "username"),
                    "role": _actor_value(actor, "role"),
                    "member_level": _actor_value(actor, "member_level"),
                    "effective_level": _actor_value(actor, "effective_level"),
                }
            now = datetime.now().isoformat()
            task = {
                "id": task_id,
                "kind": "remote_download",
                "source_type": "torrent_file",
                "status": "queued",
                "phase": "queued",
                "filename": filename,
                "url": f"BT 檔案：{filename}",
                "torrent_filename": filename,
                "torrent_path": torrent_path,
                "torrent_cleanup_dir": tmpdir,
                "owner_user_id": int(_actor_value(actor, "id")),
                "actor": actor_snapshot,
                "privacy_mode": privacy_mode,
                "virtual_path": virtual_path,
                "timeout_seconds": 1800,
                "loaded_bytes": 0,
                "total_bytes": None,
                "progress_percent": 0,
                "msg": "BT 種子檔已加入下載佇列",
                "error": "",
                "file": None,
                "storage_file": None,
                "ip": get_client_ip(),
                "ua": get_ua(),
                "created_at": now,
                "updated_at": now,
            }
            with _REMOTE_DOWNLOAD_TASKS_LOCK:
                _REMOTE_DOWNLOAD_TASKS[task_id] = task
            worker = threading.Thread(target=_run_remote_download_task, args=(task_id,), daemon=True)
            worker.start()
            return json_resp({"ok": True, "task": _task_snapshot(task)}, 202)
        except Exception:
            shutil.rmtree(tmpdir, ignore_errors=True)
            raise

    @app.route("/api/cloud-drive/remote-download/tasks/<task_id>", methods=["GET"])
    @require_csrf_safe
    def cloud_drive_remote_download_task_status(task_id):
        actor, err = _actor_or_401()
        if err:
            return err
        task = _get_remote_download_task(str(task_id))
        if not task:
            return json_resp({"ok": False, "msg": "找不到下載任務"}), 404
        if int(task.get("owner_user_id") or 0) != int(_actor_value(actor, "id")) and not _is_manager(actor):
            return json_resp({"ok": False, "msg": "沒有下載任務權限"}), 403
        return json_resp({"ok": True, "task": _task_snapshot(task)})

    @app.route("/api/cloud-drive/remote-download", methods=["POST"])
    @require_csrf
    def cloud_drive_remote_download():
        actor, err = _actor_or_401()
        if err:
            return err
        try:
            data = request.get_json(force=True)
        except Exception:
            return json_resp({"ok": False, "msg": "Invalid JSON"}), 400
        data = data if isinstance(data, dict) else {}
        url = str(data.get("url") or "").strip()
        privacy_mode = str(data.get("privacy_mode") or "private_scannable").strip() or "private_scannable"
        virtual_path = str(data.get("virtual_path") or "").strip()
        timeout_seconds = 1800 if url.startswith("magnet:?") else 120

        conn = None
        downloaded = None
        file_storage = None
        try:
            conn = get_db()
            ensure_cloud_drive_attachment_schema(conn)
            ensure_storage_album_schema(conn)
            rule = get_member_level_rule(conn, _actor_value(actor, "effective_level") or _actor_value(actor, "member_level"))
            usage = get_user_cloud_drive_usage(conn, actor, member_rule=rule, storage_root=storage_root)
            remaining = usage.get("remaining_bytes")
            max_file = usage.get("max_file_size_bytes")
            max_bytes = None
            if remaining is not None:
                max_bytes = int(remaining)
            if max_file is not None:
                max_bytes = min(max_bytes, int(max_file)) if max_bytes is not None else int(max_file)
            conn.close()
            conn = None

            downloaded = download_remote_url(url, timeout_seconds=timeout_seconds, max_bytes=max_bytes)
            file_storage = _DownloadedFileStorage(downloaded)
            conn = get_db()
            ensure_cloud_drive_attachment_schema(conn)
            ensure_storage_album_schema(conn)
            upload_result, msg = store_cloud_upload(
                conn,
                actor=actor,
                member_rule=rule,
                storage_root=storage_root,
                file_storage=file_storage,
                privacy_mode=privacy_mode,
                scan_now=True,
            )
            if msg:
                conn.rollback()
                return json_resp({"ok": False, "msg": msg}), 400

            storage_file = None
            if virtual_path:
                file_row = conn.execute("SELECT * FROM uploaded_files WHERE id=?", (upload_result["file_id"],)).fetchone()
                storage_file, msg = create_storage_file_entry(
                    conn,
                    actor=actor,
                    file_row=file_row,
                    virtual_path=virtual_path,
                    display_name=downloaded.filename,
                    source="remote_download",
                )
                if msg:
                    conn.rollback()
                    return json_resp({"ok": False, "msg": msg}), 400
            conn.commit()
            audit("CLOUD_DRIVE_REMOTE_DOWNLOAD", get_client_ip(), user=actor["username"], success=True, ua=get_ua(), detail=f"file_id={upload_result['file_id']}")
            payload = {"ok": True, "msg": "遠端下載已保存到雲端硬碟", "file": {**upload_result, "filename": downloaded.filename}}
            if storage_file:
                payload["storage_file"] = storage_file
            return json_resp(payload)
        except RemoteDownloadError as exc:
            if conn:
                conn.rollback()
            return json_resp({"ok": False, "msg": str(exc)}), 400
        finally:
            if file_storage:
                file_storage.close()
            if downloaded and downloaded.cleanup_dir:
                shutil.rmtree(downloaded.cleanup_dir, ignore_errors=True)
            if conn:
                conn.close()

    @app.route("/api/cloud-drive/attach-existing", methods=["POST"])
    @require_csrf
    def cloud_drive_attach_existing():
        actor, err = _actor_or_401()
        if err:
            return err
        try:
            data = request.get_json(force=True)
        except Exception:
            return json_resp({"ok": False, "msg": "Invalid JSON"}), 400
        conn = get_db()
        try:
            ensure_cloud_drive_attachment_schema(conn)
            result, msg = attach_existing_file(
                conn,
                actor=actor,
                file_id=str(data.get("file_id") or ""),
                context_type=data.get("context_type"),
                context_id=data.get("context_id"),
                grant_user_ids=_grant_user_ids_from_payload(data),
                grant_role=data.get("grant_role") or None,
                grant_group_id=data.get("grant_group_id") or None,
                can_preview=bool(data.get("can_preview", True)),
            )
            if msg:
                conn.rollback()
                return json_resp({"ok": False, "msg": msg}), 400
            conn.commit()
            audit("CLOUD_DRIVE_ATTACH_EXISTING", get_client_ip(), user=actor["username"], success=True, ua=get_ua(), detail=f"file_id={data.get('file_id')}")
            return json_resp({"ok": True, "attachment": result})
        finally:
            conn.close()

    @app.route("/api/files/<file_id>/status", methods=["GET"])
    @require_csrf_safe
    def file_status(file_id):
        actor, err = _actor_or_401()
        if err:
            return err
        conn = get_db()
        try:
            ensure_cloud_drive_attachment_schema(conn)
            status, msg = get_file_status(conn, actor=actor, file_id=file_id)
            if msg:
                return json_resp({"ok": False, "msg": msg}), 403
            return json_resp({"ok": True, "file": status})
        finally:
            conn.close()

    @app.route("/api/cloud-drive/refs", methods=["GET"])
    @require_csrf_safe
    def cloud_drive_refs():
        actor, err = _actor_or_401()
        if err:
            return err
        context_type = (request.args.get("context_type") or "").strip()
        context_id = (request.args.get("context_id") or "").strip()
        if not context_type or not context_id:
            return json_resp({"ok": False, "msg": "context_type/context_id required"}), 400
        conn = get_db()
        try:
            ensure_cloud_drive_attachment_schema(conn)
            if not _context_refs_visible_to_actor(conn, actor, context_type, context_id):
                return json_resp({"ok": False, "msg": "權限不足"}), 403
            rows = conn.execute(
                """
                SELECT r.*, f.original_filename_plain_for_public, f.size_bytes, f.scan_status, f.risk_level,
                       f.privacy_mode, f.deleted_at
                FROM cloud_file_refs r JOIN uploaded_files f ON f.id=r.file_id
                WHERE r.context_type=? AND r.context_id=?
                ORDER BY r.created_at ASC
                """,
                (context_type, context_id),
            ).fetchall()
            refs = []
            for row in rows:
                allowed, reason, _ = can_download_file(conn, actor=actor, file_id=row["file_id"])
                if allowed or row["attached_by"] == actor["id"] or row["owner_user_id"] == actor["id"] or _is_manager(actor):
                    refs.append({**dict(row), "can_download": allowed, "download_reason": reason})
            return json_resp({"ok": True, "refs": refs})
        finally:
            conn.close()

    @app.route("/api/cloud-drive/refs", methods=["DELETE"])
    @app.route("/api/cloud-drive/refs/", methods=["DELETE"])
    @app.route("/api/cloud-drive/refs/<ref_id>", methods=["DELETE"])
    @app.route("/api/cloud-drive/refs/delete", methods=["POST"])
    @app.route("/api/cloud-drive/refs/<ref_id>/delete", methods=["POST"])
    @require_csrf
    def cloud_drive_delete_ref(ref_id=None):
        actor, err = _actor_or_401()
        if err:
            return err
        ref_id = (ref_id or "").strip()
        if not ref_id:
            try:
                data = request.get_json(silent=True) or {}
            except Exception:
                data = {}
            ref_id = (data.get("ref_id") or request.args.get("ref_id") or "").strip()
        if not ref_id:
            return json_resp({"ok": False, "msg": "attachment ref required"}), 400
        conn = get_db()
        try:
            ensure_cloud_drive_attachment_schema(conn)
            row = conn.execute("SELECT * FROM cloud_file_refs WHERE id=?", (ref_id,)).fetchone()
            if not row:
                return json_resp({"ok": False, "msg": "找不到附件"}), 404
            allowed = (
                int(row["attached_by"]) == int(_actor_value(actor, "id"))
                or int(row["owner_user_id"]) == int(_actor_value(actor, "id"))
                or _is_manager(actor)
            )
            if not allowed:
                return json_resp({"ok": False, "msg": "沒有移除此附件的權限"}), 403
            now = datetime.now().isoformat()
            conn.execute("DELETE FROM cloud_file_refs WHERE id=?", (ref_id,))
            conn.execute(
                """
                UPDATE file_access_grants
                SET revoked_at=?
                WHERE file_id=? AND context_type=? AND context_id=? AND revoked_at IS NULL
                """,
                (now, row["file_id"], row["context_type"], row["context_id"]),
            )
            conn.commit()
            audit(
                "CLOUD_DRIVE_ATTACHMENT_REMOVE",
                get_client_ip(),
                user=actor["username"],
                success=True,
                ua=get_ua(),
                detail=f"ref_id={ref_id},file_id={row['file_id']},context={row['context_type']}#{row['context_id']}",
            )
            return json_resp({"ok": True, "msg": "附件已移除", "ref_id": ref_id})
        finally:
            conn.close()

    @app.route("/api/cloud-drive/files/<file_id>/preview", methods=["GET"])
    @require_csrf_safe
    def cloud_drive_preview(file_id):
        actor, err = _actor_or_401()
        if err:
            return err
        conn = get_db()
        try:
            ensure_cloud_drive_attachment_schema(conn)
            allowed, reason, row = can_download_file(conn, actor=actor, file_id=file_id, action="preview")
            if not row:
                return json_resp({"ok": False, "msg": "找不到檔案"}), 404
            if row["deleted_at"]:
                return json_resp({"ok": False, "msg": "找不到檔案"}), 404
            if not allowed:
                if reason == "deleted":
                    return json_resp({"ok": False, "msg": "找不到檔案"}), 404
                return json_resp({"ok": False, "msg": "沒有預覽權限或檔案尚未通過安全檢查", "reason": reason}), 403
            policy = get_cloud_drive_security_policy(conn)
            ok, msg = _preview_allowed_by_policy(policy, row)
            if not ok:
                return json_resp({"ok": False, "msg": msg}), 403
            path = resolve_file_storage_path(storage_root, row)
            if not path.exists():
                return json_resp({"ok": False, "msg": "實體檔案不存在"}), 404
            preview_row = _preview_row_with_storage_fallback(conn, actor, row)
            preview = build_preview_metadata(preview_row, path)
            log_file_access(conn, file_id=file_id, actor_user_id=actor["id"], action="preview", result="allowed", reason=preview["category"], ip=get_client_ip(), user_agent=get_ua())
            conn.commit()
            return json_resp({"ok": True, "preview": preview})
        finally:
            conn.close()

    @app.route("/api/cloud-drive/files/<file_id>/preview/content", methods=["GET"])
    @require_csrf_safe
    def cloud_drive_preview_content(file_id):
        actor, err = _actor_or_401()
        if err:
            return err
        conn = get_db()
        try:
            ensure_cloud_drive_attachment_schema(conn)
            allowed, reason, row = can_download_file(conn, actor=actor, file_id=file_id, action="preview")
            if not row:
                return json_resp({"ok": False, "msg": "找不到檔案"}), 404
            if row["deleted_at"]:
                return json_resp({"ok": False, "msg": "找不到檔案"}), 404
            if not allowed:
                if reason == "deleted":
                    return json_resp({"ok": False, "msg": "找不到檔案"}), 404
                return json_resp({"ok": False, "msg": "沒有預覽權限或檔案尚未通過安全檢查", "reason": reason}), 403
            policy = get_cloud_drive_security_policy(conn)
            ok, msg = _preview_allowed_by_policy(policy, row)
            if not ok:
                return json_resp({"ok": False, "msg": msg}), 403
            path = resolve_file_storage_path(storage_root, row)
            if not path.exists():
                return json_resp({"ok": False, "msg": "實體檔案不存在"}), 404
            preview_row = _preview_row_with_storage_fallback(conn, actor, row)
            category, mime_type = preview_category(preview_row)
            if category not in {"audio", "video", "image", "pdf"}:
                return json_resp({"ok": False, "msg": "此檔案類型不支援 inline content preview"}), 415
            log_file_access(conn, file_id=file_id, actor_user_id=actor["id"], action="preview_content", result="allowed", reason=category, ip=get_client_ip(), user_agent=get_ua())
            conn.commit()
            return send_file(
                path,
                as_attachment=False,
                download_name=preview_row["original_filename_plain_for_public"] or "preview",
                mimetype=mime_type,
                conditional=True,
            )
        finally:
            conn.close()

    @app.route("/api/cloud-drive/files/<file_id>/text", methods=["PUT"])
    @require_csrf
    def cloud_drive_update_text(file_id):
        actor, err = _actor_or_401()
        if err:
            return err
        try:
            data = request.get_json(force=True)
        except Exception:
            return json_resp({"ok": False, "msg": "Invalid JSON"}), 400
        content = data.get("content") if isinstance(data, dict) else None
        if not isinstance(content, str):
            return json_resp({"ok": False, "msg": "content 必須是文字"}), 400
        raw = content.encode("utf-8")
        if len(raw) > 512 * 1024:
            return json_resp({"ok": False, "msg": "線上編輯目前限制 512KB 以內文字檔"}), 400
        conn = get_db()
        try:
            ensure_cloud_drive_attachment_schema(conn)
            row = conn.execute("SELECT * FROM uploaded_files WHERE id=?", (file_id,)).fetchone()
            if not row or row["deleted_at"]:
                return json_resp({"ok": False, "msg": "找不到檔案或檔案已刪除"}), 404
            if int(row["owner_user_id"]) != int(actor["id"]):
                return json_resp({"ok": False, "msg": "只能修改自己的雲端硬碟檔案"}), 403
            if str(row["privacy_mode"] or "").startswith("e2ee"):
                return json_resp({"ok": False, "msg": "E2EE 檔案不可由伺服器線上修改"}), 400
            category, _ = preview_category(row)
            if category != "text":
                return json_resp({"ok": False, "msg": "目前只支援文字類檔案線上修改"}), 415
            policy = get_cloud_drive_security_policy(conn)
            ok, msg = _preview_allowed_by_policy(policy, row)
            if not ok:
                return json_resp({"ok": False, "msg": msg}), 403
            path = resolve_file_storage_path(storage_root, row)
            if not path.exists():
                return json_resp({"ok": False, "msg": "實體檔案不存在"}), 404
            with open(path, "wb") as handle:
                handle.write(raw)
            now = datetime.now().isoformat()
            conn.execute(
                """
                UPDATE uploaded_files
                SET size_bytes=?, plaintext_sha256=?, updated_at=?
                WHERE id=?
                """,
                (len(raw), hashlib.sha256(raw).hexdigest(), now, file_id),
            )
            scan_result = scan_uploaded_file(
                conn,
                file_id=file_id,
                file_path=path,
                filename=row["original_filename_plain_for_public"],
                declared_mime=row["mime_type_plain_for_public"],
            )
            log_file_access(conn, file_id=file_id, actor_user_id=actor["id"], action="text_edit", result="allowed", reason=scan_result.get("scan_status"), ip=get_client_ip(), user_agent=get_ua())
            conn.commit()
            return json_resp({"ok": True, "file_id": file_id, "scan_result": scan_result, "size_bytes": len(raw)})
        finally:
            conn.close()

    @app.route("/api/files/<file_id>/download", methods=["GET"])
    @app.route("/api/cloud-drive/files/<file_id>/download", methods=["GET"])
    @require_csrf_safe
    def cloud_drive_download(file_id):
        actor, err = _actor_or_401()
        if err:
            return err
        conn = get_db()
        try:
            ensure_cloud_drive_attachment_schema(conn)
            allowed, reason, row = can_download_file(conn, actor=actor, file_id=file_id)
            if not row:
                return json_resp({"ok": False, "msg": "找不到檔案"}), 404
            if row["deleted_at"]:
                return json_resp({"ok": False, "msg": "找不到檔案"}), 404
            if not allowed:
                if reason == "deleted":
                    return json_resp({"ok": False, "msg": "找不到檔案"}), 404
                conn.commit()
                return json_resp({"ok": False, "msg": "沒有下載權限或檔案尚未通過安全檢查", "reason": reason}), 403
            policy = get_cloud_drive_security_policy(conn)
            confirmed = (
                request.args.get("confirm_high_risk") == "1"
                or request.headers.get("X-Confirm-High-Risk-Download", "").lower() in {"1", "true", "yes"}
            )
            if _requires_download_warning(policy, row) and not confirmed:
                return json_resp({
                    "ok": False,
                    "requires_confirmation": True,
                    "msg": "此檔案為高風險或無法完整掃描，請確認信任來源後再下載。",
                    "risk_level": row["risk_level"],
                    "scan_status": row["scan_status"],
                }), 409
            path = resolve_file_storage_path(storage_root, row)
            if not path.exists():
                return json_resp({"ok": False, "msg": "實體檔案不存在"}), 404
            log_file_access(conn, file_id=file_id, actor_user_id=actor["id"], action="download", result="allowed", reason=reason, ip=get_client_ip(), user_agent=get_ua())
            conn.commit()
            return send_file(path, as_attachment=True, download_name=row["original_filename_plain_for_public"] or "download.bin")
        finally:
            conn.close()

    @app.route("/api/cloud-drive/files/<file_id>/e2ee-key", methods=["GET"])
    @require_csrf_safe
    def cloud_drive_e2ee_key(file_id):
        actor, err = _actor_or_401()
        if err:
            return err
        conn = get_db()
        try:
            ensure_cloud_drive_attachment_schema(conn)
            row = conn.execute("SELECT * FROM uploaded_files WHERE id=?", (file_id,)).fetchone()
            if not row or row["deleted_at"]:
                return json_resp({"ok": False, "msg": "找不到檔案"}), 404
            if not str(row["privacy_mode"] or "").startswith("e2ee"):
                return json_resp({"ok": False, "msg": "此檔案不是端到端加密檔案"}), 400
            key = conn.execute(
                """
                SELECT encrypted_file_key, wrapped_by, key_version
                FROM encrypted_file_keys
                WHERE file_id=? AND recipient_user_id=? AND revoked_at IS NULL
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (file_id, int(actor["id"])),
            ).fetchone()
            if not key:
                return json_resp({"ok": False, "msg": "此帳號沒有可用的解密金鑰"}), 403
            log_file_access(conn, file_id=file_id, actor_user_id=actor["id"], action="e2ee_key", result="allowed", reason=key["wrapped_by"], ip=get_client_ip(), user_agent=get_ua())
            conn.commit()
            return json_resp({
                "ok": True,
                "e2ee": {
                    "file_id": row["id"],
                    "privacy_mode": row["privacy_mode"],
                    "encrypted_metadata": row["original_filename_encrypted"],
                    "encrypted_file_key": key["encrypted_file_key"],
                    "wrapped_by": key["wrapped_by"],
                    "key_version": key["key_version"],
                    "encryption_algorithm": row["encryption_algorithm"],
                    "encryption_version": row["encryption_version"],
                    "nonce": row["nonce"],
                    "ciphertext_sha256": row["ciphertext_sha256"],
                },
            })
        finally:
            conn.close()

    @app.route("/api/files/<file_id>/share", methods=["POST"])
    @require_csrf
    def file_share(file_id):
        actor, err = _actor_or_401()
        if err:
            return err
        try:
            data = request.get_json(force=True)
        except Exception:
            return json_resp({"ok": False, "msg": "Invalid JSON"}), 400
        conn = get_db()
        try:
            ensure_cloud_drive_attachment_schema(conn)
            result, msg = share_e2ee_file(
                conn,
                actor=actor,
                file_id=file_id,
                recipient_user_id=data.get("recipient_user_id"),
                encrypted_file_key=data.get("encrypted_file_key"),
                wrapped_by=data.get("wrapped_by") or "recipient_public_key",
                context_type=data.get("context_type") or "dm",
                context_id=data.get("context_id"),
            )
            if msg:
                conn.rollback()
                return json_resp({"ok": False, "msg": msg}), 400
            conn.commit()
            audit("FILE_E2EE_SHARE", get_client_ip(), user=actor["username"], success=True, ua=get_ua(), detail=f"file_id={file_id}, recipient_user_id={result['recipient_user_id']}")
            return json_resp({"ok": True, "share": result})
        finally:
            conn.close()

    @app.route("/api/files/<file_id>/share/revoke", methods=["POST"])
    @require_csrf
    def file_share_revoke(file_id):
        actor, err = _actor_or_401()
        if err:
            return err
        try:
            data = request.get_json(force=True)
        except Exception:
            return json_resp({"ok": False, "msg": "Invalid JSON"}), 400
        conn = get_db()
        try:
            ensure_cloud_drive_attachment_schema(conn)
            result, msg = revoke_e2ee_file_share(
                conn,
                actor=actor,
                file_id=file_id,
                recipient_user_id=data.get("recipient_user_id"),
            )
            if msg:
                conn.rollback()
                return json_resp({"ok": False, "msg": msg}), 400
            conn.commit()
            audit("FILE_E2EE_SHARE_REVOKE", get_client_ip(), user=actor["username"], success=True, ua=get_ua(), detail=f"file_id={file_id}, recipient_user_id={data.get('recipient_user_id')}")
            return json_resp({"ok": True, "revoked": result})
        finally:
            conn.close()

    @app.route("/api/cloud-drive/files/<file_id>", methods=["DELETE"])
    @require_csrf
    def cloud_drive_delete_file(file_id):
        actor, err = _actor_or_401()
        if err:
            return err
        conn = get_db()
        try:
            ensure_cloud_drive_attachment_schema(conn)
            result, msg = trash_cloud_file_to_storage(conn, actor=actor, file_id=file_id)
            if msg:
                conn.rollback()
                return json_resp({"ok": False, "msg": msg}), 404
            conn.commit()
            audit("CLOUD_DRIVE_FILE_TRASH", get_client_ip(), user=actor["username"], success=True, ua=get_ua(), detail=f"file_id={file_id}")
            return json_resp({"ok": True, "msg": "檔案已移到垃圾桶", "trash": result})
        finally:
            conn.close()

    @app.route("/api/cloud-drive/announcement-attachment-requests", methods=["GET", "POST"])
    @require_csrf_safe
    def announcement_attachment_requests():
        actor, err = _actor_or_401()
        if err:
            return err
        if not _is_manager(actor):
            return json_resp({"ok": False, "msg": "只有管理員以上可使用公告附件請求"}), 403
        conn = get_db()
        try:
            ensure_cloud_drive_attachment_schema(conn)
            if request.method == "GET":
                if not _is_root(actor):
                    return json_resp({"ok": False, "msg": "只有 root 可查看所有公告附件請求"}), 403
                rows = conn.execute("SELECT * FROM announcement_attachment_requests ORDER BY created_at DESC").fetchall()
                return json_resp({"ok": True, "requests": [dict(row) for row in rows]})
            try:
                data = request.get_json(force=True)
            except Exception:
                return json_resp({"ok": False, "msg": "Invalid JSON"}), 400
            result, msg = create_announcement_attachment_request(
                conn,
                actor=actor,
                file_id=str(data.get("file_id") or ""),
                announcement_id=data.get("announcement_id"),
                reason=data.get("reason") or "",
            )
            if msg:
                conn.rollback()
                return json_resp({"ok": False, "msg": msg}), 400
            conn.commit()
            audit("ANNOUNCEMENT_ATTACHMENT_REQUEST", get_client_ip(), user=actor["username"], success=True, ua=get_ua(), detail=f"request_id={result['id']}")
            return json_resp({"ok": True, "request": result})
        finally:
            conn.close()

    @app.route("/api/root/announcement-attachment-requests/<request_id>/review", methods=["POST"])
    @require_csrf
    def root_review_announcement_attachment_request(request_id):
        actor, err = _actor_or_401()
        if err:
            return err
        if not _is_root(actor):
            return json_resp({"ok": False, "msg": "只有 root 可審核公告附件"}), 403
        try:
            data = request.get_json(force=True)
        except Exception:
            return json_resp({"ok": False, "msg": "Invalid JSON"}), 400
        conn = get_db()
        try:
            ensure_cloud_drive_attachment_schema(conn)
            result, msg = review_announcement_attachment_request(
                conn,
                actor=actor,
                request_id=request_id,
                action=data.get("action"),
                reason=data.get("reason") or "",
            )
            if msg:
                conn.rollback()
                return json_resp({"ok": False, "msg": msg}), 400
            conn.commit()
            audit("ANNOUNCEMENT_ATTACHMENT_REVIEW", get_client_ip(), user=actor["username"], success=True, ua=get_ua(), detail=f"request_id={request_id}, status={result['status']}")
            return json_resp({"ok": True, "request": result})
        finally:
            conn.close()

    @app.route("/api/files/security-policy", methods=["GET"])
    @require_csrf_safe
    def file_security_policy():
        actor, err = _actor_or_401()
        if err:
            return err
        conn = get_db()
        try:
            rule = get_member_level_rule(conn, actor["effective_level"] or actor["member_level"])
            summary = get_cloud_drive_safety_summary(conn, actor, member_rule=rule, storage_root=storage_root)
            return json_resp({"ok": True, "security": summary})
        finally:
            conn.close()

    @app.route("/api/files/privacy-modes", methods=["GET"])
    @require_csrf_safe
    def file_privacy_modes():
        actor, err = _actor_or_401()
        if err:
            return err
        conn = get_db()
        try:
            policy = get_cloud_drive_security_policy(conn)
            return json_resp({
                "ok": True,
                "modes": {
                    "public_attachment": {
                        "label": "公開附件",
                        "server_can_read": True,
                        "server_scan": "required",
                        "e2ee": False,
                        "warning": "請勿上傳需要端到端保密的資料。",
                    },
                    "private_scannable": {
                        "label": "私密可掃描",
                        "server_can_read": "temporary_for_scan",
                        "server_scan": "required",
                        "e2ee": False,
                        "warning": "提供伺服器端掃毒與加密保存，但不是端到端加密。",
                    },
                    "e2ee_vault": {
                        "label": "端到端加密保險庫",
                        "server_can_read": False,
                        "server_scan": "metadata_only",
                        "e2ee": True,
                        "warning": "站方無法讀取內容，也無法完整掃毒；遺失金鑰可能無法救回。",
                    },
                    "e2ee_vault_with_client_scan": {
                        "label": "E2EE + 本機檢查",
                        "server_can_read": False,
                        "server_scan": "client_report_untrusted",
                        "e2ee": True,
                        "warning": "本機掃描回報不可完全信任，伺服器仍無法驗證全部內容。",
                    },
                },
                "policy": policy,
            })
        finally:
            conn.close()
