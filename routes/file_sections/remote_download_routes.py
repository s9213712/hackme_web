import os
import shutil
import tempfile
import threading
import uuid
from datetime import datetime

from flask import request

from services.storage.cloud_drive import ensure_cloud_drive_attachment_schema, store_cloud_upload
from services.storage.storage_albums import create_storage_file_entry, ensure_storage_album_schema
from services.system.notifications import create_notification_if_enabled
from services.security.upload_security import get_user_cloud_drive_usage, safe_public_filename


def register_file_remote_download_routes(app, ctx):
    get_db = ctx["get_db"]
    get_member_level_rule = ctx["get_member_level_rule"]
    get_client_ip = ctx["get_client_ip"]
    get_ua = ctx["get_ua"]
    audit = ctx["audit"]
    json_resp = ctx["json_resp"]
    require_csrf = ctx["require_csrf"]
    require_csrf_safe = ctx["require_csrf_safe"]
    storage_root = ctx["storage_root"]
    server_file_fernet = ctx["server_file_fernet"]

    actor_or_401 = ctx["actor_or_401"]
    actor_value = ctx["actor_value"]
    is_manager = ctx["is_manager"]
    actor_transfer_policy = ctx["actor_transfer_policy"]

    DownloadedFileStorage = ctx["DownloadedFileStorage"]
    task_snapshot = ctx["task_snapshot"]
    get_remote_download_task = ctx["get_remote_download_task"]
    list_remote_download_tasks_for_actor = ctx["list_remote_download_tasks_for_actor"]
    cleanup_stale_remote_download_tasks_locked = ctx["cleanup_stale_remote_download_tasks_locked"]
    run_remote_download_task = ctx["run_remote_download_task"]
    remote_download_storage_path = ctx["remote_download_storage_path"]

    remote_download_tasks = ctx["remote_download_tasks"]
    remote_download_tasks_lock = ctx["remote_download_tasks_lock"]

    download_remote_url = ctx["download_remote_url"]
    download_torrent_file_with_aria2 = ctx["download_torrent_file_with_aria2"]
    download_torrent_url_with_aria2 = ctx["download_torrent_url_with_aria2"]
    remote_download_capabilities = ctx["remote_download_capabilities"]
    validate_remote_url = ctx["validate_remote_url"]
    validate_torrent_file_trackers = ctx.get("validate_torrent_file_trackers")
    RemoteDownloadError = ctx["RemoteDownloadError"]

    def _actor_snapshot(actor):
        try:
            return dict(actor)
        except Exception:
            return {
                "id": actor_value(actor, "id"),
                "username": actor_value(actor, "username"),
                "role": actor_value(actor, "role"),
                "member_level": actor_value(actor, "member_level"),
                "effective_level": actor_value(actor, "effective_level"),
            }

    @app.route("/api/cloud-drive/remote-download/capabilities", methods=["GET"])
    @require_csrf_safe
    def cloud_drive_remote_download_capabilities():
        actor, err = actor_or_401()
        if err:
            return err
        return json_resp({"ok": True, "capabilities": remote_download_capabilities()})

    @app.route("/api/cloud-drive/remote-download/tasks", methods=["POST"])
    @require_csrf
    def cloud_drive_remote_download_task_create():
        actor, err = actor_or_401()
        if err:
            return err
        try:
            data = request.get_json(force=True)
        except Exception:
            return json_resp({"ok": False, "msg": "請求 JSON 格式錯誤"}), 400
        data = data if isinstance(data, dict) else {}
        url = str(data.get("url") or "").strip()
        if not url:
            return json_resp({"ok": False, "msg": "請輸入下載網址"}), 400
        try:
            parsed_remote = validate_remote_url(url)
        except RemoteDownloadError as exc:
            return json_resp({"ok": False, "msg": str(exc)}), 400
        download_mode = str(data.get("download_mode") or "direct").strip().lower()
        if download_mode not in {"direct", "bt"}:
            return json_resp({"ok": False, "msg": "下載模式不正確"}), 400
        if download_mode == "bt":
            if parsed_remote["kind"] == "magnet":
                source_type = "magnet"
            elif parsed_remote["kind"] == "torrent_url":
                source_type = "torrent_url"
            else:
                return json_resp({"ok": False, "msg": "BT/torrent 按鈕只接受 magnet link 或 .torrent URL"}), 400
        else:
            if parsed_remote["kind"] == "magnet":
                return json_resp({"ok": False, "msg": "Direct link 不接受 magnet link，請使用 BT/torrent 按鈕"}), 400
            source_type = "direct"
        privacy_mode = str(data.get("privacy_mode") or "standard_plain").strip() or "standard_plain"
        virtual_path = str(data.get("virtual_path") or "").strip()
        task_id = uuid.uuid4().hex
        now = datetime.now().isoformat()
        task = {
            "id": task_id,
            "kind": "remote_download",
            "source_type": source_type,
            "status": "queued",
            "phase": "queued",
            "filename": "",
            "url": url,
            "torrent_filename": "",
            "torrent_path": "",
            "torrent_cleanup_dir": "",
            "owner_user_id": int(actor_value(actor, "id")),
            "actor": _actor_snapshot(actor),
            "privacy_mode": privacy_mode,
            "virtual_path": virtual_path,
            "timeout_seconds": 1800 if source_type in {"magnet", "torrent_url"} else 120,
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
        with remote_download_tasks_lock:
            remote_download_tasks[task_id] = task
        worker = threading.Thread(target=run_remote_download_task, args=(task_id,), daemon=True)
        worker.start()
        return json_resp({"ok": True, "task": task_snapshot(task)}, 202)

    @app.route("/api/cloud-drive/remote-download/tasks", methods=["GET"])
    @require_csrf_safe
    def cloud_drive_remote_download_task_list():
        actor, err = actor_or_401()
        if err:
            return err
        return json_resp({"ok": True, "tasks": list_remote_download_tasks_for_actor(actor)})

    @app.route("/api/cloud-drive/remote-download/torrent-tasks", methods=["POST"])
    @require_csrf
    def cloud_drive_remote_download_torrent_task_create():
        actor, err = actor_or_401()
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
            if validate_torrent_file_trackers:
                try:
                    validate_torrent_file_trackers(torrent_path)
                except RemoteDownloadError as exc:
                    shutil.rmtree(tmpdir, ignore_errors=True)
                    return json_resp({"ok": False, "msg": str(exc)}), 400
            privacy_mode = str(request.form.get("privacy_mode") or "standard_plain").strip() or "standard_plain"
            virtual_path = str(request.form.get("virtual_path") or "").strip()
            task_id = uuid.uuid4().hex
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
                "owner_user_id": int(actor_value(actor, "id")),
                "actor": _actor_snapshot(actor),
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
            with remote_download_tasks_lock:
                remote_download_tasks[task_id] = task
            worker = threading.Thread(target=run_remote_download_task, args=(task_id,), daemon=True)
            worker.start()
            return json_resp({"ok": True, "task": task_snapshot(task)}, 202)
        except Exception:
            shutil.rmtree(tmpdir, ignore_errors=True)
            raise

    @app.route("/api/cloud-drive/remote-download/tasks/<task_id>", methods=["GET"])
    @require_csrf_safe
    def cloud_drive_remote_download_task_status(task_id):
        actor, err = actor_or_401()
        if err:
            return err
        task = get_remote_download_task(str(task_id))
        if not task:
            return json_resp({"ok": False, "msg": "找不到下載任務"}), 404
        if int(task.get("owner_user_id") or 0) != int(actor_value(actor, "id")):
            return json_resp({"ok": False, "msg": "沒有下載任務權限"}), 403
        return json_resp({"ok": True, "task": task_snapshot(task)})

    @app.route("/api/cloud-drive/remote-download/tasks/<task_id>", methods=["DELETE"])
    @require_csrf
    def cloud_drive_remote_download_task_dismiss(task_id):
        actor, err = actor_or_401()
        if err:
            return err
        task_id = str(task_id)
        with remote_download_tasks_lock:
            cleanup_stale_remote_download_tasks_locked()
            task = remote_download_tasks.get(task_id)
            if not task:
                return json_resp({"ok": True, "removed": False})
            if int(task.get("owner_user_id") or 0) != int(actor_value(actor, "id")):
                return json_resp({"ok": False, "msg": "沒有下載任務權限"}), 403
            if task.get("status") in {"queued", "running"}:
                return json_resp({"ok": False, "msg": "下載任務仍在進行，不能移除紀錄"}), 409
            cleanup_dir = task.get("torrent_cleanup_dir")
            remote_download_tasks.pop(task_id, None)
        if cleanup_dir:
            shutil.rmtree(cleanup_dir, ignore_errors=True)
        return json_resp({"ok": True, "removed": True})

    @app.route("/api/cloud-drive/remote-download", methods=["POST"])
    @require_csrf
    def cloud_drive_remote_download():
        actor, err = actor_or_401()
        if err:
            return err
        try:
            data = request.get_json(force=True)
        except Exception:
            return json_resp({"ok": False, "msg": "請求 JSON 格式錯誤"}), 400
        data = data if isinstance(data, dict) else {}
        url = str(data.get("url") or "").strip()
        privacy_mode = str(data.get("privacy_mode") or "standard_plain").strip() or "standard_plain"
        virtual_path = str(data.get("virtual_path") or "").strip()
        timeout_seconds = 120

        conn = None
        downloaded = None
        file_storage = None
        try:
            conn = get_db()
            ensure_cloud_drive_attachment_schema(conn)
            ensure_storage_album_schema(conn)
            rule = get_member_level_rule(conn, actor_value(actor, "effective_level") or actor_value(actor, "member_level"))
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

            remote_rate_kb_per_sec = int(actor_transfer_policy(actor).get("download_kb_per_sec") or 0)
            downloaded = download_remote_url(
                url,
                timeout_seconds=timeout_seconds,
                max_bytes=max_bytes,
                rate_limit_kb_per_sec=remote_rate_kb_per_sec or None,
                treat_torrent_as_bt=False,
            )
            file_storage = DownloadedFileStorage(downloaded)
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
                server_file_fernet=server_file_fernet,
            )
            if msg:
                conn.rollback()
                return json_resp({"ok": False, "msg": msg}), 400

            file_row = conn.execute("SELECT * FROM uploaded_files WHERE id=?", (upload_result["file_id"],)).fetchone()
            storage_path = remote_download_storage_path(downloaded.filename, virtual_path)
            storage_file, msg = create_storage_file_entry(
                conn,
                actor=actor,
                file_row=file_row,
                virtual_path=storage_path,
                display_name=downloaded.filename,
                source="remote_download",
            )
            if msg:
                conn.rollback()
                return json_resp({"ok": False, "msg": msg}), 400
            source_label = "BT 下載" if url.startswith("magnet:?") or url.lower().split("?", 1)[0].endswith(".torrent") else "遠端下載"
            create_notification_if_enabled(
                conn,
                user_id=actor_value(actor, "id"),
                type="cloud_drive_remote_download_completed",
                title=f"{source_label}已完成",
                body=f"{source_label}「{downloaded.filename}」已保存到你的雲端硬碟。",
                link="/drive",
            )
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
