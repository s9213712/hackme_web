from services.upload_security import (
    get_cloud_drive_safety_summary,
    get_cloud_drive_security_policy,
    get_user_cloud_drive_usage,
    log_file_access,
)
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
    soft_delete_cloud_file,
    store_cloud_upload,
)
from services.storage_albums import (
    create_storage_file_entry,
    ensure_storage_album_schema,
    get_storage_file,
    list_storage_files,
    list_storage_trash,
    purge_storage_file,
    restore_storage_file,
    sync_user_storage_summary,
    trash_storage_file,
)
from flask import request, send_file


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

    def _actor_or_401():
        actor = get_current_user_ctx()
        if not actor:
            return None, json_resp({"ok": False, "msg": "請先登入"}, 401)
        return actor, None

    def _is_root(actor):
        return actor and actor.get("username") == "root"

    def _is_manager(actor):
        role = "super_admin" if actor and actor.get("username") == "root" else (actor or {}).get("role", "user")
        return role_rank(role) >= role_rank("manager")

    def _requires_download_warning(policy, row):
        if not policy.get("warn_high_risk_downloads"):
            return False
        return row["risk_level"] in {"high", "blocked", "unknown_encrypted"} or row["scan_status"] in {"infected", "quarantined", "failed", "unknown_encrypted"}

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

    @app.route("/api/files/quota", methods=["GET"])
    @require_csrf_safe
    def file_quota():
        actor, err = _actor_or_401()
        if err:
            return err
        conn = get_db()
        try:
            rule = get_member_level_rule(conn, actor["effective_level"] or actor["member_level"])
            usage = get_user_cloud_drive_usage(conn, actor, member_rule=rule)
            return json_resp({"ok": True, "quota": usage})
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
            rule = get_member_level_rule(conn, actor.get("effective_level") or actor.get("member_level"))
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
            rule = get_member_level_rule(conn, actor.get("effective_level") or actor.get("member_level"))
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
            if not allowed:
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
            ok, msg = soft_delete_cloud_file(conn, actor=actor, file_id=file_id)
            if not ok:
                conn.rollback()
                return json_resp({"ok": False, "msg": msg}), 404
            conn.commit()
            audit("CLOUD_DRIVE_FILE_DELETE", get_client_ip(), user=actor["username"], success=True, ua=get_ua(), detail=f"file_id={file_id}")
            return json_resp({"ok": True, "msg": "檔案已刪除"})
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
            summary = get_cloud_drive_safety_summary(conn, actor, member_rule=rule)
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
