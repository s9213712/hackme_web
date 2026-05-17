from pathlib import Path
import html
import mimetypes
import json
import os
import re
import secrets
import subprocess
import sys
import threading
from datetime import datetime, timedelta

from flask import Response, request, send_file, session

from services.storage.cloud_drive import (
    decrypt_server_encrypted_bytes,
    ensure_cloud_drive_attachment_schema,
    is_e2ee_file,
    is_server_encrypted_file,
    resolve_file_storage_path,
    store_cloud_upload,
)
from services.core.http_headers import build_content_disposition
from services.media.streaming import (
    ensure_media_stream_schema,
    get_stream_status,
    mark_stream_asset_processing,
    repair_hls_master_manifest_text,
    should_auto_prepare_stream,
    stream_playback_payload,
)
from services.media.e2ee_streaming import (
    ensure_e2ee_stream_v2_schema,
    get_e2ee_stream_v2_status,
    resolve_e2ee_chunk_response,
    serialize_manifest_for_client,
    upsert_e2ee_stream_v2_asset,
)
from services.job_center import (
    add_job_event as add_platform_job_event,
    create_job as create_platform_job,
    get_job_by_source as get_platform_job_by_source,
    update_job as update_platform_job,
)
from services.storage.storage_albums import create_storage_file_entry, ensure_storage_album_schema
from services.security.upload_security import safe_public_filename
from services.share_access_events import log_share_access_event
from services.media.videos import (
    add_video_comment,
    boost_owner_video,
    delete_owner_video,
    ensure_video_schema,
    ensure_video_share_link,
    get_video,
    list_owner_videos,
    list_video_comments,
    list_videos,
    mark_video_share_link_accessed,
    publish_video,
    revoke_video_share_link,
    record_video_view,
    resolve_video_share_token,
    set_video_like,
    shared_video_payload,
    tip_video,
    update_owner_video,
)


def register_video_routes(app, deps):
    get_current_user_ctx = deps["get_current_user_ctx"]
    get_db = deps["get_db"]
    get_client_ip = deps.get("get_client_ip", lambda: "")
    get_ua = deps.get("get_ua", lambda: "")
    json_resp = deps["json_resp"]
    require_csrf = deps["require_csrf"]
    require_csrf_safe = deps["require_csrf_safe"]
    audit = deps.get("audit", lambda *args, **kwargs: None)
    points_service = deps.get("points_service")
    storage_root = deps["STORAGE_DIR"]
    server_file_fernet = deps.get("server_file_fernet")
    db_path = deps.get("DB_PATH")
    log_dir = deps.get("LOG_DIR")
    server_file_key_path = deps.get("SERVER_FILE_KEY_PATH")
    get_system_settings = deps.get("get_system_settings", lambda: {})
    get_member_level_rule = deps["get_member_level_rule"]
    ffmpeg_bin = deps.get("FFMPEG_BIN", "ffmpeg")
    ffprobe_bin = deps.get("FFPROBE_BIN", "ffprobe")
    forbidden_share_fields = {"raw_file_key", "e2ee_password", "vk", "share_key", "share_key_bytes"}
    stream_prepare_lock = threading.Lock()
    stream_prepare_jobs = set()

    def _now_iso():
        return datetime.utcnow().replace(microsecond=0).isoformat()

    def _parse_json_body():
        try:
            data = request.get_json(force=True)
        except Exception:
            return None, json_resp({"ok": False, "msg": "請求 JSON 格式錯誤", "error": "invalid_json"}), 400
        if not isinstance(data, dict):
            return None, json_resp({"ok": False, "msg": "請求內容格式錯誤", "error": "invalid_request"}), 400
        return data, None, None

    def _actor_or_401():
        actor = get_current_user_ctx()
        if not actor:
            return None, json_resp({"ok": False, "msg": "請先登入", "error": "login_required"}, 401)
        return actor, None

    def _error_response(exc):
        message = str(exc) or exc.__class__.__name__
        if isinstance(exc, PermissionError):
            return json_resp({"ok": False, "msg": message, "error": "forbidden"}), 403
        if "無法以目前伺服器金鑰解密" in message:
            return json_resp({"ok": False, "msg": message, "error": "decrypt_unavailable"}), 409
        if "insufficient balance" in message:
            return json_resp({"ok": False, "msg": "積分不足，無法投幣", "error": "insufficient_balance"}), 409
        return json_resp({"ok": False, "msg": message, "error": exc.__class__.__name__}), 400

    def _svg_placeholder_response(message, *, label="封面不可顯示"):
        safe_label = (label or "封面不可顯示").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        safe_message = (message or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="960" height="540" viewBox="0 0 960 540">
<rect width="960" height="540" fill="#151823"/>
<rect x="32" y="32" width="896" height="476" rx="20" fill="#202533" stroke="#39405a"/>
<text x="480" y="220" text-anchor="middle" fill="#f4f6ff" font-size="34" font-family="Arial, sans-serif">{safe_label}</text>
<text x="480" y="280" text-anchor="middle" fill="#b8bfd8" font-size="20" font-family="Arial, sans-serif">{safe_message}</text>
</svg>"""
        return Response(svg, status=200, mimetype="image/svg+xml")

    def _settings_float(key, default):
        try:
            return float((get_system_settings() or {}).get(key, default))
        except Exception:
            return float(default)

    def _settings_bool(key, default):
        raw = (get_system_settings() or {}).get(key, default)
        if isinstance(raw, bool):
            return raw
        return str(raw).strip().lower() in {"1", "true", "yes", "on", "y", "t"}

    def _load_stream_file(conn, *, file_id):
        row = conn.execute(
            "SELECT * FROM uploaded_files WHERE id=? AND deleted_at IS NULL",
            (str(file_id or ""),),
        ).fetchone()
        if not row:
            raise ValueError("找不到影音檔案")
        return row

    def _video_e2ee_owner_key(conn, file_row):
        return conn.execute(
            """
            SELECT encrypted_file_key, wrapped_by, key_version
            FROM encrypted_file_keys
            WHERE file_id=? AND recipient_user_id=? AND revoked_at IS NULL
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (file_row["id"], int(file_row["owner_user_id"])),
        ).fetchone()

    def _assert_stream_prepare_allowed(actor, row):
        if not actor:
            raise PermissionError("login required")
        if int(row["owner_user_id"]) == int(actor["id"]):
            return
        raise PermissionError("只有檔案擁有者可以準備串流衍生檔")

    def _append_share_session_to_hls_manifest(text, share_session_id=""):
        share_session_id = str(share_session_id or "").strip()
        if not share_session_id:
            return text
        uri_attr_pattern = re.compile(r"URI=([\"'])([^\"']+)\1")

        def with_share_session(url):
            raw = str(url or "")
            if not raw or "share_session=" in raw or raw.startswith("data:"):
                return raw
            separator = "&" if "?" in raw else "?"
            return f"{raw}{separator}share_session={share_session_id}"

        def replace_uri_attr(match):
            quote = match.group(1)
            url = match.group(2)
            return f"URI={quote}{with_share_session(url)}{quote}"

        lines = []
        for line in str(text or "").splitlines():
            stripped = line.strip()
            if not stripped:
                lines.append(line)
                continue
            if stripped.startswith("#"):
                lines.append(uri_attr_pattern.sub(replace_uri_attr, line))
                continue
            lines.append(with_share_session(line))
        return "\n".join(lines) + ("\n" if str(text or "").endswith("\n") else "")

    def _send_hls_master_manifest(path, *, share_session_id=""):
        text = repair_hls_master_manifest_text(Path(path).read_text(encoding="utf-8"))
        text = _append_share_session_to_hls_manifest(text, share_session_id)
        return Response(text, status=200, mimetype="application/vnd.apple.mpegurl")

    def _video_stream_worker_key(file_id):
        return str(file_id or "").strip()

    def _stream_worker_is_active(file_id):
        key = _video_stream_worker_key(file_id)
        with stream_prepare_lock:
            return key in stream_prepare_jobs

    def _mark_video_stream_processing(conn, *, file_id, video_id=None):
        now = _now_iso()
        if video_id:
            conn.execute(
                """
                UPDATE videos
                SET status='processing', updated_at=?
                WHERE id=? AND cloud_file_id=? AND deleted_at IS NULL
                """,
                (now, int(video_id), str(file_id)),
            )
            return
        conn.execute(
            """
            UPDATE videos
            SET status='processing', updated_at=?
            WHERE cloud_file_id=? AND status<>'ready' AND deleted_at IS NULL
            """,
            (now, str(file_id)),
        )

    def _hls_job_source_ref(file_id):
        return f"media_stream:{str(file_id or '').strip()}"

    def _platform_job_title(prefix, title="", fallback="影音"):
        clean = str(title or fallback or "影音").strip() or "影音"
        return f"{prefix}：{clean[:96]}"

    def _sync_hls_platform_job(
        conn,
        *,
        file_row,
        video_id=None,
        owner_user_id=None,
        title="",
        status="running",
        progress_percent=0,
        stage="queued",
        stage_detail="",
        error_message="",
        result=None,
    ):
        try:
            file_id = str(file_row["id"])
            owner = owner_user_id if owner_user_id is not None else file_row["owner_user_id"]
            source_ref = _hls_job_source_ref(file_id)
            existing = get_platform_job_by_source(conn, "media_hls_prepare", source_ref)
            metadata = {
                "file_id": file_id,
                "video_id": int(video_id or 0),
                "privacy_mode": str(file_row["privacy_mode"] or ""),
                "media_type": "audio" if str(file_row["mime_type_plain_for_public"] or "").lower().startswith("audio/") else "video",
            }
            if existing:
                updates = {
                    "status": status,
                    "progress_percent": progress_percent,
                    "stage": stage,
                    "stage_detail": stage_detail,
                    "metadata_json": metadata,
                }
                if status == "running" and not existing.get("started_at"):
                    updates["started_at"] = _now_iso()
                if status in {"succeeded", "failed", "cancelled", "expired"}:
                    updates["finished_at"] = _now_iso()
                if result is not None:
                    updates["result_json"] = result
                if error_message:
                    updates["error_message"] = error_message
                    updates["error_stage"] = stage
                job = update_platform_job(conn, existing["job_uuid"], defer_progress=False, flush=True, **updates)
                add_platform_job_event(
                    conn,
                    job["job_uuid"],
                    event_type="failed" if status == "failed" else "progress",
                    stage=stage,
                    message=stage_detail or error_message or "HLS 任務狀態更新",
                    progress_percent=progress_percent,
                    payload=metadata,
                    defer_progress=False,
                    flush=True,
                )
                return job
            return create_platform_job(
                conn,
                owner_user_id=int(owner or 0) or None,
                created_by_user_id=int(owner or 0) or None,
                job_type="video.hls.prepare",
                title=_platform_job_title("HLS 處理", title, file_row["original_filename_plain_for_public"]),
                description="影音 HLS 衍生檔建立、轉封裝與可播放狀態追蹤",
                source_module="media_hls_prepare",
                source_ref=source_ref,
                status=status,
                progress_percent=progress_percent,
                stage=stage,
                stage_detail=stage_detail,
                metadata=metadata,
            )
        except Exception:
            return None

    def _sync_e2ee_stream_v2_platform_job(conn, *, file_row, owner_user_id=None, title="", asset=None, status="succeeded", error_message=""):
        try:
            file_id = str(file_row["id"])
            owner = owner_user_id if owner_user_id is not None else file_row["owner_user_id"]
            source_ref = f"e2ee_stream_v2:{file_id}"
            stage = "ready" if status == "succeeded" else "failed"
            detail = "E2EE Streaming v2 manifest 與密文分段已建立" if status == "succeeded" else (error_message or "E2EE Streaming v2 建立失敗")
            existing = get_platform_job_by_source(conn, "media_e2ee_stream_v2", source_ref)
            metadata = {
                "file_id": file_id,
                "chunk_count": int((asset or {}).get("chunk_count") or 0),
                "bundle_size_bytes": int((asset or {}).get("bundle_size_bytes") or 0),
            }
            if existing:
                job = update_platform_job(
                    conn,
                    existing["job_uuid"],
                    status=status,
                    progress_percent=100,
                    stage=stage,
                    stage_detail=detail,
                    error_message=error_message if status == "failed" else "",
                    error_stage=stage if status == "failed" else "",
                    finished_at=_now_iso(),
                    result_json=asset or {},
                    metadata_json=metadata,
                )
                add_platform_job_event(
                    conn,
                    job["job_uuid"],
                    event_type="failed" if status == "failed" else "progress",
                    stage=stage,
                    message=detail,
                    progress_percent=100,
                    payload=metadata,
                )
                return job
            job = create_platform_job(
                conn,
                owner_user_id=int(owner or 0) or None,
                created_by_user_id=int(owner or 0) or None,
                job_type="video.e2ee_stream_v2.prepare",
                title=_platform_job_title("E2EE Streaming v2", title, file_row["original_filename_plain_for_public"]),
                description="端到端加密影音的瀏覽器端分段密文串流準備紀錄",
                source_module="media_e2ee_stream_v2",
                source_ref=source_ref,
                status="running",
                progress_percent=90,
                stage="server_processing",
                stage_detail="E2EE Streaming v2 manifest 與密文分段正在儲存。",
                metadata=metadata,
            )
            job = update_platform_job(
                conn,
                job["job_uuid"],
                status=status,
                progress_percent=100,
                stage=stage,
                stage_detail=detail,
                error_message=error_message if status == "failed" else "",
                error_stage=stage if status == "failed" else "",
                finished_at=_now_iso(),
                result_json=asset or {},
                metadata_json=metadata,
            )
            add_platform_job_event(
                conn,
                job["job_uuid"],
                event_type="failed" if status == "failed" else "progress",
                stage=stage,
                message=detail,
                progress_percent=100,
                payload=metadata,
            )
            return job
        except Exception:
            return None

    def _start_stream_prepare_worker(file_id, *, video_id=None, owner_user_id=None, title=""):
        key = _video_stream_worker_key(file_id)
        if not key:
            return False
        with stream_prepare_lock:
            if key in stream_prepare_jobs:
                return False
            stream_prepare_jobs.add(key)
        if db_path:
            try:
                worker_path = Path(__file__).resolve().parents[1] / "scripts" / "media" / "hls_prepare_worker.py"
                if not worker_path.exists():
                    raise FileNotFoundError(str(worker_path))
                worker_log_dir = Path(log_dir or (Path(storage_root).parent / "logs"))
                worker_log_dir.mkdir(parents=True, exist_ok=True)
                log_path = worker_log_dir / "media_hls_worker.log"
                cmd = [
                    sys.executable,
                    str(worker_path),
                    "--db-path",
                    str(db_path),
                    "--storage-root",
                    str(storage_root),
                    "--file-id",
                    key,
                    "--video-id",
                    str(int(video_id or 0)),
                    "--owner-user-id",
                    str(int(owner_user_id or 0)),
                    "--title",
                    str(title or ""),
                    "--ffmpeg-bin",
                    str(ffmpeg_bin),
                    "--ffprobe-bin",
                    str(ffprobe_bin),
                ]
                if server_file_key_path:
                    cmd.extend(["--server-file-key-path", str(server_file_key_path)])
                with log_path.open("ab") as log_file:
                    subprocess.Popen(
                        cmd,
                        stdout=log_file,
                        stderr=log_file,
                        stdin=subprocess.DEVNULL,
                        close_fds=True,
                        start_new_session=True,
                    )
                return True
            except Exception as exc:
                try:
                    audit(
                        "MEDIA_STREAM_PREPARE_BACKGROUND_LAUNCH",
                        get_client_ip(),
                        user=f"user_id:{owner_user_id or ''}",
                        success=False,
                        ua=get_ua(),
                        detail=f"file_id={key},video_id={video_id or ''},error={str(exc)[:300]}",
                    )
                except Exception:
                    pass
                return False
            finally:
                with stream_prepare_lock:
                    stream_prepare_jobs.discard(key)
        with stream_prepare_lock:
            stream_prepare_jobs.discard(key)
        return False

    def _queue_stream_prepare(conn, *, file_row, video_id=None, title="", visibility="public", force=False):
        ensure_media_stream_schema(conn)
        current = get_stream_status(conn, file_row=file_row, include_segments=False)
        if not force and current and current.get("status") == "ready":
            return current, None, False
        if current and current.get("status") == "processing" and (not force or _stream_worker_is_active(file_row["id"])):
            return current, None, False
        asset = mark_stream_asset_processing(conn, file_row=file_row)
        if video_id:
            _mark_video_stream_processing(conn, file_id=file_row["id"], video_id=video_id)
        _sync_hls_platform_job(
            conn,
            file_row=file_row,
            video_id=video_id,
            owner_user_id=file_row["owner_user_id"],
            title=title,
            status="running",
            progress_percent=5,
            stage="queued",
            stage_detail="HLS 背景處理已排程；你可以先做別的事，進度會顯示在任務中心，完成後會通知。",
        )
        return asset, None, True

    def _maybe_prepare_stream_asset(conn, *, file_row, visibility, video_id=None, title=""):
        if not _settings_bool("video_stream_auto_prepare_enabled", True):
            return None, None, False
        decision = should_auto_prepare_stream(file_row, visibility=visibility)
        if not decision.get("enabled"):
            return None, None, False
        try:
            return _queue_stream_prepare(
                conn,
                file_row=file_row,
                video_id=video_id,
                title=title,
                visibility=visibility,
            )
        except Exception as exc:
            return None, f"HLS 串流排程失敗：{exc}", False

    def _video_ready_for_browse(conn, video):
        if not _settings_bool("video_stream_auto_prepare_enabled", True):
            return True
        try:
            file_row = _load_stream_file(conn, file_id=video["cloud_file_id"])
            decision = should_auto_prepare_stream(file_row, visibility=video.get("visibility") or "public")
            if not decision.get("enabled"):
                return True
            asset = get_stream_status(conn, file_row=file_row, include_segments=False)
            return bool(asset and asset.get("status") == "ready")
        except Exception:
            return False

    def _uploaded_file_is_media(file_storage):
        filename = getattr(file_storage, "filename", "") or ""
        declared = str(getattr(file_storage, "mimetype", "") or "").split(";", 1)[0].strip().lower()
        guessed = str(mimetypes.guess_type(filename)[0] or "").lower()
        return (
            declared.startswith("video/")
            or declared.startswith("audio/")
            or guessed.startswith("video/")
            or guessed.startswith("audio/")
        )

    def _uploaded_file_is_image(file_storage):
        filename = getattr(file_storage, "filename", "") or ""
        declared = str(getattr(file_storage, "mimetype", "") or "").split(";", 1)[0].strip().lower()
        guessed = str(mimetypes.guess_type(filename)[0] or "").lower()
        return declared.startswith("image/") or guessed.startswith("image/")

    def _file_storage_size(file_storage):
        stream = getattr(file_storage, "stream", file_storage)
        if hasattr(stream, "tell") and hasattr(stream, "seek"):
            try:
                position = stream.tell()
                stream.seek(0, os.SEEK_END)
                size = stream.tell()
                stream.seek(position)
                return int(size or 0)
            except Exception:
                return 0
        return 0

    def _env_size_bytes(bytes_key, mb_key, default_bytes):
        raw_bytes = os.environ.get(bytes_key)
        raw_mb = os.environ.get(mb_key)
        try:
            value = int(raw_bytes) if raw_bytes is not None else int(raw_mb) * 1024 * 1024 if raw_mb is not None else int(default_bytes)
        except Exception:
            value = int(default_bytes)
        return max(0, int(value))

    def _e2ee_stream_bundle_max_bytes():
        return _env_size_bytes(
            "HACKME_E2EE_STREAM_BUNDLE_MAX_BYTES",
            "HACKME_E2EE_STREAM_BUNDLE_MAX_MB",
            128 * 1024 * 1024,
        )

    def _default_media_title(file_storage):
        filename = safe_public_filename(getattr(file_storage, "filename", "") or "media")
        stem = Path(filename).stem.strip()
        return stem or "未命名影音"

    def _parse_publish_request():
        if request.files or request.form:
            data = {
                "cloud_file_id": (request.form.get("cloud_file_id") or "").strip(),
                "title": (request.form.get("title") or "").strip(),
                "description": request.form.get("description") or "",
                "visibility": (request.form.get("visibility") or "public").strip() or "public",
                "cover_file_id": (request.form.get("cover_file_id") or "").strip() or None,
                "share_password": request.form.get("share_password") or "",
                "share_wrapped_file_key_envelope": request.form.get("share_wrapped_file_key_envelope") or "",
                "share_expires_at": request.form.get("share_expires_at") or "",
                "share_max_views": request.form.get("share_max_views") or "",
            }
            return data, request.files.get("cover"), None, None
        data, err, status = _parse_json_body()
        if isinstance(data, dict):
            data["share_password"] = data.get("share_password") or ""
            data["share_wrapped_file_key_envelope"] = data.get("share_wrapped_file_key_envelope") or ""
            data["share_expires_at"] = data.get("share_expires_at") or ""
            data["share_max_views"] = data.get("share_max_views") or ""
        return data, None, err, status

    def _reject_sensitive_share_fields(payload):
        payload = payload or {}
        for field in forbidden_share_fields:
            value = payload.get(field)
            if value not in (None, "", [], {}):
                return json_resp({"ok": False, "msg": f"禁止提交敏感分享欄位：{field}", "error": "forbidden_share_secret_field"}), 400
        return None

    def _store_video_cover_upload(conn, *, actor, member_rule, cover_upload, privacy_mode):
        if not cover_upload or not cover_upload.filename:
            return None, None, None, None
        if not _uploaded_file_is_image(cover_upload):
            return None, None, "封面圖只接受圖片檔", "cover_not_image"
        cover_result, cover_msg = store_cloud_upload(
            conn,
            actor=actor,
            member_rule=member_rule,
            storage_root=storage_root,
            file_storage=cover_upload,
            privacy_mode=privacy_mode,
            scan_now=True,
            server_file_fernet=server_file_fernet,
        )
        if cover_msg:
            return None, None, cover_msg, "cover_upload_rejected"
        cover_row = conn.execute("SELECT * FROM uploaded_files WHERE id=?", (cover_result["file_id"],)).fetchone()
        cover_storage_file, cover_storage_msg = create_storage_file_entry(
            conn,
            actor=actor,
            file_row=cover_row,
            virtual_path=f"/Media/Covers/{cover_result['file_id']}-{safe_public_filename(cover_upload.filename)}",
            display_name=safe_public_filename(cover_upload.filename),
            source="video_cover_upload",
        )
        if cover_storage_msg:
            return None, None, cover_storage_msg, "cover_storage_entry_failed"
        return cover_result, cover_storage_file, None, None

    def _parse_http_byte_range(range_header, total_size):
        if not range_header:
            return None, None
        value = str(range_header or "").strip()
        if not value.startswith("bytes="):
            return None, "invalid"
        spec = value[6:].split(",", 1)[0].strip()
        if "-" not in spec:
            return None, "invalid"
        start_raw, end_raw = spec.split("-", 1)
        try:
            if start_raw == "":
                suffix_len = int(end_raw)
                if suffix_len <= 0:
                    return None, "invalid"
                start = max(0, total_size - suffix_len)
                end = total_size - 1
            else:
                start = int(start_raw)
                end = int(end_raw) if end_raw else total_size - 1
        except Exception:
            return None, "invalid"
        if total_size <= 0 or start < 0 or end < start or start >= total_size:
            return None, "invalid"
        return (start, min(end, total_size - 1)), None

    def _send_bytes_with_range(raw, *, download_name, mimetype, range_header=None):
        total_size = len(raw)
        byte_range, error = _parse_http_byte_range(range_header, total_size)
        if error:
            response = Response(status=416)
            response.headers["Content-Range"] = f"bytes */{total_size}"
            response.headers["Accept-Ranges"] = "bytes"
            return response
        if byte_range:
            start, end = byte_range
            response = Response(raw[start:end + 1], status=206, mimetype=mimetype or "application/octet-stream")
            response.headers["Content-Range"] = f"bytes {start}-{end}/{total_size}"
            response.headers["Content-Length"] = str(end - start + 1)
        else:
            response = Response(raw, status=200, mimetype=mimetype or "application/octet-stream")
            response.headers["Content-Length"] = str(total_size)
        response.headers["Accept-Ranges"] = "bytes"
        response.headers["Content-Disposition"] = build_content_disposition("inline", download_name)
        return response

    def _shared_video_password_from_request():
        return request.headers.get("X-Video-Share-Password") or request.args.get("password") or ""

    def _shared_video_session_state():
        raw = session.get("video_share_sessions")
        return raw if isinstance(raw, dict) else {}

    def _store_shared_video_session_state(state):
        now = datetime.utcnow().replace(microsecond=0).isoformat()
        cleaned = {}
        for key, value in (state or {}).items():
            if not isinstance(value, dict):
                continue
            expires_at = str(value.get("expires_at") or "").strip()
            if expires_at and expires_at <= now:
                continue
            cleaned[str(key)] = value
        session["video_share_sessions"] = cleaned
        session.modified = True
        return cleaned

    def _shared_video_request_session_id():
        return str(request.headers.get("X-Video-Share-Session") or request.args.get("share_session") or "").strip()

    def _shared_video_session_for_request(token):
        share_session_id = _shared_video_request_session_id()
        if not share_session_id:
            return "", None
        state = _store_shared_video_session_state(_shared_video_session_state())
        item = state.get(share_session_id)
        if not isinstance(item, dict):
            return "", None
        if str(item.get("token") or "") != str(token or ""):
            return "", None
        return share_session_id, item

    def _create_shared_video_session(token, *, password_verified=False, hours=8):
        state = _store_shared_video_session_state(_shared_video_session_state())
        share_session_id = secrets.token_urlsafe(24)
        state[share_session_id] = {
            "token": str(token or ""),
            "password_verified": bool(password_verified),
            "counted": False,
            "expires_at": (datetime.utcnow() + timedelta(hours=max(1, int(hours)))).replace(microsecond=0).isoformat(),
        }
        session["video_share_sessions"] = state
        session.modified = True
        return share_session_id

    def _mark_shared_video_session_counted(share_session_id):
        if not share_session_id:
            return
        state = _store_shared_video_session_state(_shared_video_session_state())
        item = state.get(share_session_id)
        if not isinstance(item, dict):
            return
        item["counted"] = True
        state[share_session_id] = item
        session["video_share_sessions"] = state
        session.modified = True

    def _count_shared_video_access(conn, row, share_session_id, counted_in_session):
        if counted_in_session:
            return True
        share_id = row["share_id"] if "share_id" in row.keys() else row["id"]
        mark_video_share_link_accessed(conn, share_id)
        log_share_access_event(conn, share_type="video", share_id=share_id, ip=get_client_ip(), user_agent=get_ua())
        _mark_shared_video_session_counted(share_session_id)
        return True

    def _ensure_shared_video_session_counted(conn, row, token, *, password_verified, share_session_id, counted_in_session):
        if not share_session_id:
            share_session_id = _create_shared_video_session(token, password_verified=password_verified)
        _count_shared_video_access(conn, row, share_session_id, counted_in_session)
        return share_session_id

    def _url_with_share_session(url, share_session_id):
        url = str(url or "")
        share_session_id = str(share_session_id or "").strip()
        if not url or not share_session_id:
            return url
        separator = "&" if "?" in url else "?"
        return f"{url}{separator}share_session={share_session_id}"

    def _attach_share_session_to_playback_payload(payload, share_session_id):
        if not isinstance(payload, dict) or not share_session_id:
            return payload
        for key in (
            "fallback_url",
            "stream_url",
            "ciphertext_url",
            "e2ee_key_url",
            "manifest_url",
            "chunk_url_template",
            "master_url",
        ):
            if payload.get(key):
                payload[key] = _url_with_share_session(payload[key], share_session_id)
        for variant in payload.get("variants") or []:
            if isinstance(variant, dict) and variant.get("playlist_url"):
                variant["playlist_url"] = _url_with_share_session(variant["playlist_url"], share_session_id)
        return payload

    def _shared_video_error_response(reason):
        if reason == "password_required":
            return json_resp({
                "ok": False,
                "msg": "這部影音需要分享密碼",
                "reason": reason,
                "password_required": True,
            }), 401
        if reason == "password_invalid":
            return json_resp({
                "ok": False,
                "msg": "分享密碼不正確",
                "reason": reason,
                "password_required": True,
            }), 403
        if reason == "password_locked":
            return json_resp({"ok": False, "msg": "分享密碼嘗試次數過多，請稍後再試", "reason": reason, "password_required": True}), 429
        if reason == "expired":
            return json_resp({"ok": False, "msg": "此分享連結已到期", "reason": reason}), 410
        if reason == "view_limit_reached":
            return json_resp({"ok": False, "msg": "此分享連結已達最大觀看次數", "reason": reason}), 410
        if reason == "forbidden_fragment_transport":
            return json_resp({"ok": False, "msg": "分享金鑰必須保留在 URL fragment，不可送到伺服器", "reason": reason}), 400
        return json_resp({"ok": False, "msg": "分享影音不存在或已失效", "reason": reason}), 404

    def _shared_video_ended_html(reason):
        reason = str(reason or "").strip()
        detail_by_reason = {
            "expired": "此分享連結已到期，請向分享者索取新的連結。",
            "view_limit_reached": "此分享連結已達最大觀看次數，無法再開啟。",
            "forbidden_fragment_transport": "分享金鑰格式不正確，請確認使用完整的分享網址。",
        }
        detail = detail_by_reason.get(reason, "此分享連結不存在、已撤銷，或分享者已結束分享。")
        safe_detail = html.escape(detail, quote=True)
        return f"""<!doctype html>
<html lang="zh-Hant">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>分享已結束</title>
  <style>
    html {{ min-height:100%; }}
    body {{ min-height:100dvh; margin:0; display:grid; place-items:center; background:radial-gradient(circle at 18% 8%, rgba(61,120,255,.16), transparent 28rem), radial-gradient(circle at 82% 2%, rgba(54,211,153,.08), transparent 26rem), #111521; color:#eef2ff; font-family:system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; }}
    body::before {{ content:""; position:fixed; inset:0; pointer-events:none; background-image:linear-gradient(rgba(255,255,255,.035) 1px, transparent 1px), linear-gradient(90deg, rgba(255,255,255,.035) 1px, transparent 1px); background-size:42px 42px; mask-image:linear-gradient(to bottom, rgba(0,0,0,.72), transparent 72%); }}
    .card {{ position:relative; width:min(92vw, 520px); box-sizing:border-box; padding:1.35rem; border-radius:8px; background:rgba(23,28,43,.88); border:1px solid #2a3150; box-shadow:0 18px 48px rgba(0,0,0,.22); backdrop-filter:blur(12px); }}
    h1 {{ margin:0 0 .55rem; font-size:clamp(1.35rem, 4vw, 1.9rem); line-height:1.2; }}
    p {{ margin:0; color:#b9c2f0; line-height:1.6; }}
    a {{ display:inline-flex; margin-top:1rem; color:#fff; background:#3d78ff; text-decoration:none; border-radius:12px; padding:.7rem 1rem; }}
  </style>
</head>
<body>
  <main class="card">
    <h1>分享已結束</h1>
    <p>{safe_detail}</p>
    <a href="/">回到首頁</a>
  </main>
</body>
</html>"""

    def _resolve_shared_video(conn, token, *, allow_counted_session_limit=False):
        if request.args.get("vk"):
            share_session_id, session_state = _shared_video_session_for_request(token)
            return None, "forbidden_fragment_transport", False, bool(session_state and session_state.get("counted")), share_session_id
        share_session_id, session_state = _shared_video_session_for_request(token)
        password_verified = bool(session_state and session_state.get("password_verified"))
        counted_in_session = bool(session_state and session_state.get("counted"))
        row, reason = resolve_video_share_token(
            conn,
            token,
            password=_shared_video_password_from_request(),
            password_verified=password_verified,
            counted_in_session=bool(allow_counted_session_limit and counted_in_session),
        )
        return row, reason, password_verified, counted_in_session, share_session_id

    def _e2ee_direct_status(row):
        return {
            "uploaded_file_id": row["id"],
            "source_mode": "e2ee",
            "media_type": "audio" if str(row["original_filename_plain_for_public"] or "").lower().endswith((".mp3", ".m4a", ".aac", ".flac", ".wav", ".weba", ".opus", ".oga", ".ogg")) else "video",
            "status": "direct_only",
            "storage_mode": "browser_e2ee",
            "master_manifest_path": "",
            "duration_seconds": 0.0,
            "source_mime_type": str(row["mime_type_plain_for_public"] or mimetypes.guess_type(str(row["original_filename_plain_for_public"] or ""))[0] or ""),
            "source_size_bytes": int(row["size_bytes"] or 0),
            "error_message": "端到端加密影音只支援瀏覽器端解密播放，會較慢且不支援 HLS 加速。",
            "variants": [],
        }

    def _playback_payload_for_file(conn, *, row, video_id, shared_token=None):
        media_type = "audio" if str(row["original_filename_plain_for_public"] or "").lower().endswith((".mp3", ".m4a", ".aac", ".flac", ".wav", ".weba", ".opus", ".oga", ".ogg")) else "video"
        if is_e2ee_file(row):
            ensure_e2ee_stream_v2_schema(conn)
            if shared_token:
                ciphertext_url = f"/api/videos/shared/{shared_token}/ciphertext"
                e2ee_key_url = f"/api/videos/shared/{shared_token}/e2ee-key"
                manifest_url = f"/api/videos/shared/{shared_token}/e2ee-stream-v2/manifest"
                chunk_url_template = f"/api/videos/shared/{shared_token}/e2ee-stream-v2/chunks/__INDEX__"
            else:
                ciphertext_url = f"/api/videos/{video_id}/ciphertext"
                e2ee_key_url = f"/api/videos/{video_id}/e2ee-key"
                manifest_url = f"/api/videos/{video_id}/e2ee-stream-v2/manifest"
                chunk_url_template = f"/api/videos/{video_id}/e2ee-stream-v2/chunks/__INDEX__"
            stream_v2 = get_e2ee_stream_v2_status(conn, file_row=row, storage_root=storage_root)
            available = bool(stream_v2 and stream_v2.get("available"))
            payload = {
                "mode": "e2ee_stream_v2" if available else "e2ee_direct",
                "media_type": media_type,
                "source_mode": "e2ee",
                "fallback_url": ciphertext_url,
                "stream_url": ciphertext_url,
                "ciphertext_url": ciphertext_url,
                "e2ee_key_url": e2ee_key_url,
                "requires_fragment_key": bool(shared_token),
                "master_url": "",
                "hls_js_url": "",
                "player_strategy": "browser_e2ee_stream_v2" if available else "browser_e2ee_full_fallback",
                "stream_warning": (
                    "正在使用 E2EE Streaming v2：密文分段下載、瀏覽器端解密；伺服器無法看到明文，因此不會在伺服器產生 480/720/1080 明文轉檔。"
                    if available
                    else "此 strict E2EE 影音尚未建立 Streaming v2 manifest，將退回舊版完整解密播放。"
                ),
                "streaming_ready": available,
                "high_performance_streaming": False,
                "status": stream_v2 if stream_v2 else _e2ee_direct_status(row),
                "manifest_url": manifest_url,
                "chunk_url_template": chunk_url_template,
                "stream_v2_available": available,
                "default_quality": "original",
                "fallback_quality": "",
                "quality_policy": {
                    "default_quality": "original",
                    "fallback_quality": "",
                    "derivatives_quota_exempt": True,
                    "larger_derivatives_hidden": True,
                    "e2ee_original_only": True,
                    "note": "strict E2EE 不允許伺服器解密轉檔；若要達到多畫質又維持 E2EE，需由發布端瀏覽器本機產生較低畫質後再上傳加密衍生包。這些 E2EE Streaming v2 服務分段不計入用戶雲端硬碟容量。",
                },
            }
            return payload
        payload = stream_playback_payload(conn, file_row=row, video_id=video_id)
        if shared_token:
            shared_base = f"/api/videos/shared/{shared_token}"
            if payload.get("fallback_url"):
                payload["fallback_url"] = f"{shared_base}/stream"
            if payload.get("stream_url"):
                payload["stream_url"] = f"{shared_base}/stream"
            if payload.get("master_url"):
                payload["master_url"] = f"{shared_base}/hls/master.m3u8"
            for variant in payload.get("variants") or []:
                if isinstance(variant, dict) and variant.get("name"):
                    variant["playlist_url"] = f"{shared_base}/hls/{variant['name']}/playlist.m3u8"
        payload["high_performance_streaming"] = payload.get("mode") == "hls"
        return payload

    def _shared_video_html(token):
        token = str(token or "")
        # JSON-encode token so the JSON island parses cleanly (repr() emits
        # single quotes which aren't valid JSON). The "</" sequence in any
        # token would close the <script> tag early — defend by escaping
        # the slash even though our tokens are URL-safe.
        share_token_json = json.dumps(token).replace("</", "<\\/")
        return f"""<!doctype html>
<html lang="zh-Hant">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>分享影音</title>
  <style>
    html {{ min-height:100%; }}
    body {{ min-height:100dvh; margin:0; overflow-x:hidden; background:radial-gradient(circle at 18% 8%, rgba(61,120,255,.16), transparent 28rem), radial-gradient(circle at 82% 2%, rgba(54,211,153,.08), transparent 26rem), #111521; color:#eef2ff; font-family:system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; }}
    body::before {{ content:""; position:fixed; inset:0; pointer-events:none; background-image:linear-gradient(rgba(255,255,255,.035) 1px, transparent 1px), linear-gradient(90deg, rgba(255,255,255,.035) 1px, transparent 1px); background-size:42px 42px; mask-image:linear-gradient(to bottom, rgba(0,0,0,.72), transparent 72%); }}
    .wrap {{ width:min(100%, 1120px); min-height:100dvh; margin:0 auto; padding:clamp(.75rem, 2vw, 1.25rem); box-sizing:border-box; display:flex; align-items:center; }}
    .card {{ position:relative; width:100%; max-height:calc(100dvh - 2rem); background:rgba(23,28,43,.88); border:1px solid #2a3150; border-radius:8px; padding:clamp(.85rem, 2vw, 1.1rem); box-shadow:0 18px 48px rgba(0,0,0,.22); overflow:auto; box-sizing:border-box; backdrop-filter:blur(12px); }}
    h1 {{ margin:.1rem 0 .35rem; font-size:clamp(1.25rem, 3vw, 1.85rem); line-height:1.2; overflow-wrap:anywhere; }}
    .msg {{ min-height:1.4rem; color:#b9c2f0; margin:.75rem 0; white-space:pre-wrap; }}
    .field {{ display:grid; gap:.35rem; margin:.75rem 0; }}
    input, button, textarea {{ font:inherit; }}
    input[type=password] {{ width:100%; box-sizing:border-box; padding:.7rem .9rem; border-radius:12px; border:1px solid #39405c; background:#0f1422; color:#eef2ff; }}
    button {{ padding:.7rem 1rem; border-radius:12px; border:0; background:#3d78ff; color:#fff; cursor:pointer; }}
    button.secondary {{ background:#2b3148; }}
    .quality-control {{ margin:.7rem 0 0; display:flex; flex-wrap:wrap; align-items:center; gap:.5rem; color:#b8bfd8; }}
    .quality-control select {{ min-height:2.35rem; border-radius:10px; border:1px solid #39405c; background:#0f1422; color:#eef2ff; padding:.45rem .7rem; }}
    .quality-control small {{ flex:1 1 16rem; line-height:1.45; }}
    #player-host {{ width:100%; min-height:0; margin-top:.8rem; display:grid; place-items:center; }}
    #player-host video, #player-host audio {{ display:block; width:100%; max-width:100%; border-radius:14px; background:#070b15; }}
    #player-host video {{ inline-size:min(100%, calc((100dvh - 240px) * 16 / 9)); height:auto; max-height:min(64dvh, 560px); aspect-ratio:16 / 9; object-fit:contain; }}
    #player-host audio {{ min-height:44px; }}
    .meta {{ color:#b8bfd8; font-size:.95rem; }}
    .hidden {{ display:none !important; }}
    @media (max-width: 640px) {{
      .wrap {{ width:100%; min-height:100dvh; padding:0; align-items:stretch; }}
      .card {{ min-height:100dvh; max-height:none; border:0; border-radius:0; padding:.85rem; box-shadow:none; background:rgba(23,28,43,.92); }}
      h1 {{ font-size:1.35rem; }}
      #player-host {{ margin-top:.55rem; }}
      #player-host video, #player-host audio {{ border-radius:10px; }}
      #player-host video {{ inline-size:100%; max-height:min(48dvh, calc(100dvh - 210px)); }}
      button {{ width:100%; }}
    }}
    @media (max-height: 520px) and (orientation: landscape) {{
      .wrap {{ align-items:flex-start; }}
      .card {{ max-height:none; }}
      #player-host video {{ inline-size:min(100%, calc(72dvh * 16 / 9)); max-height:72dvh; }}
    }}
  </style>
</head>
<body>
  <div class="wrap">
    <div class="card">
      <h1 id="title">分享影音</h1>
      <div class="meta" id="meta">讀取中...</div>
      <div class="msg" id="msg"></div>
      <form id="share-password-form" class="hidden">
        <div class="field">
          <label for="share-password">分享密碼</label>
          <input id="share-password" type="password" autocomplete="current-password" />
        </div>
        <button type="submit">解鎖影音</button>
      </form>
      <div id="player-host" class="hidden"></div>
      <div id="quality-host" class="quality-control hidden"></div>
      <div id="player-action" class="hidden"></div>
      <div id="e2ee-note" class="meta hidden">此影音採端到端加密，只支援瀏覽器端解密播放，首次載入與快轉會較慢。</div>
    </div>
  </div>
  <script id="share-token" type="application/json">{share_token_json}</script>
  <script src="/js/shared-video.js?v=20260518-hls-quality-defaults"></script>
</body>
</html>"""

    @app.route("/api/videos/publish", methods=["POST"])
    @require_csrf
    def video_publish():
        actor, err = _actor_or_401()
        if err:
            return err
        data, cover_upload, err, status = _parse_publish_request()
        if err:
            return err, status
        sensitive = _reject_sensitive_share_fields(data)
        if sensitive:
            return sensitive
        conn = get_db()
        try:
            cover_result = None
            cover_storage_file = None
            if cover_upload and cover_upload.filename:
                rule = get_member_level_rule(conn, actor["effective_level"] or actor["member_level"])
                cover_result, cover_storage_file, cover_msg, cover_error = _store_video_cover_upload(
                    conn,
                    actor=actor,
                    member_rule=rule,
                    cover_upload=cover_upload,
                    privacy_mode="standard_plain",
                )
                if cover_msg:
                    conn.rollback()
                    return json_resp({"ok": False, "msg": cover_msg, "error": cover_error}), 400
            video = publish_video(
                conn,
                actor=actor,
                cloud_file_id=data.get("cloud_file_id"),
                title=data.get("title"),
                description=data.get("description") or "",
                visibility=data.get("visibility") or "public",
                cover_file_id=cover_result["file_id"] if cover_result else (data.get("cover_file_id") or None),
                share_password=data.get("share_password") or "",
                share_wrapped_file_key_envelope=data.get("share_wrapped_file_key_envelope") or "",
                share_expires_at=data.get("share_expires_at") or "",
                share_max_views=data.get("share_max_views") or 0,
            )
            file_row = conn.execute("SELECT * FROM uploaded_files WHERE id=?", (video["cloud_file_id"],)).fetchone()
            stream_asset, stream_warning, stream_queued = _maybe_prepare_stream_asset(
                conn,
                file_row=file_row,
                visibility=video["visibility"],
                video_id=video["id"],
                title=video["title"],
            )
            if stream_asset and stream_asset.get("status") == "processing":
                video["status"] = "processing"
            conn.commit()
            if stream_queued:
                worker_started = _start_stream_prepare_worker(
                    file_row["id"],
                    video_id=video["id"],
                    owner_user_id=video["owner_user_id"],
                    title=video["title"],
                )
                if not worker_started:
                    stream_warning = "HLS 背景處理程序啟動失敗，請稍後重新排程。"
                    _sync_hls_platform_job(
                        conn,
                        file_row=file_row,
                        video_id=video["id"],
                        owner_user_id=video["owner_user_id"],
                        title=video["title"],
                        status="failed",
                        progress_percent=100,
                        stage="launch_failed",
                        stage_detail=stream_warning,
                        error_message=stream_warning,
                    )
                else:
                    _sync_hls_platform_job(
                        conn,
                        file_row=file_row,
                        video_id=video["id"],
                        owner_user_id=video["owner_user_id"],
                        title=video["title"],
                        status="running",
                        progress_percent=10,
                        stage="worker_started",
                        stage_detail="HLS 外部轉檔程序已啟動；你可以先做別的事，進度會顯示在任務中心。",
                    )
                conn.commit()
            audit(
                "VIDEO_PUBLISH",
                get_client_ip(),
                user=actor["username"],
                success=True,
                ua=get_ua(),
                detail=f"video_id={video['id']},cloud_file_id={video['cloud_file_id']},visibility={video['visibility']}",
            )
            return json_resp({
                "ok": True,
                "video": video,
                "stream_asset": stream_asset,
                "stream_warning": stream_warning or "",
                "cover_file": ({**cover_result, "filename": safe_public_filename(cover_upload.filename)} if cover_result else None),
                "cover_storage_file": cover_storage_file,
            })
        except Exception as exc:
            conn.rollback()
            return _error_response(exc)
        finally:
            conn.close()

    @app.route("/api/videos/upload", methods=["POST"])
    @require_csrf
    def video_upload_and_publish():
        actor, err = _actor_or_401()
        if err:
            return err
        uploaded = request.files.get("video") or request.files.get("file")
        if not uploaded or not uploaded.filename:
            return json_resp({"ok": False, "msg": "請選擇要上傳的影音檔", "error": "missing_file"}), 400
        if not _uploaded_file_is_media(uploaded):
            return json_resp({"ok": False, "msg": "只接受影片或音樂檔", "error": "not_media"}), 400
        sensitive = _reject_sensitive_share_fields(request.form)
        if sensitive:
            return sensitive
        privacy_mode = str(request.form.get("privacy_mode") or "standard_plain").strip() or "standard_plain"
        if privacy_mode not in {"standard_plain", "server_encrypted"}:
            return json_resp({"ok": False, "msg": "影音隱私模式不支援", "error": "unsupported_privacy_mode"}), 400
        cover_upload = request.files.get("cover")
        conn = get_db()
        try:
            ensure_cloud_drive_attachment_schema(conn)
            ensure_storage_album_schema(conn)
            rule = get_member_level_rule(conn, actor["effective_level"] or actor["member_level"])
            upload_result, msg = store_cloud_upload(
                conn,
                actor=actor,
                member_rule=rule,
                storage_root=storage_root,
                file_storage=uploaded,
                privacy_mode=privacy_mode,
                scan_now=True,
                server_file_fernet=server_file_fernet,
            )
            if msg:
                conn.rollback()
                return json_resp({"ok": False, "msg": msg, "error": "upload_rejected"}), 400
            file_row = conn.execute("SELECT * FROM uploaded_files WHERE id=?", (upload_result["file_id"],)).fetchone()
            storage_file, storage_msg = create_storage_file_entry(
                conn,
                actor=actor,
                file_row=file_row,
                virtual_path=f"/Media/{upload_result['file_id']}-{safe_public_filename(uploaded.filename)}",
                display_name=safe_public_filename(uploaded.filename),
                source="video_upload",
            )
            if storage_msg:
                conn.rollback()
                return json_resp({"ok": False, "msg": storage_msg, "error": "storage_entry_failed"}), 400
            cover_result = None
            cover_storage_file = None
            if cover_upload and cover_upload.filename:
                cover_result, cover_storage_file, cover_msg, cover_error = _store_video_cover_upload(
                    conn,
                    actor=actor,
                    member_rule=rule,
                    privacy_mode="server_encrypted" if privacy_mode == "server_encrypted" else "standard_plain",
                    cover_upload=cover_upload,
                )
                if cover_msg:
                    conn.rollback()
                    return json_resp({"ok": False, "msg": cover_msg, "error": cover_error}), 400
            video = publish_video(
                conn,
                actor=actor,
                cloud_file_id=upload_result["file_id"],
                title=request.form.get("title") or _default_media_title(uploaded),
                description=request.form.get("description") or "",
                visibility=request.form.get("visibility") or "public",
                cover_file_id=cover_result["file_id"] if cover_result else None,
                share_password=request.form.get("share_password") or "",
                share_wrapped_file_key_envelope=request.form.get("share_wrapped_file_key_envelope") or "",
                share_expires_at=request.form.get("share_expires_at") or "",
                share_max_views=request.form.get("share_max_views") or 0,
            )
            stream_asset, stream_warning, stream_queued = _maybe_prepare_stream_asset(
                conn,
                file_row=file_row,
                visibility=video["visibility"],
                video_id=video["id"],
                title=video["title"],
            )
            if stream_asset and stream_asset.get("status") == "processing":
                video["status"] = "processing"
            conn.commit()
            if stream_queued:
                worker_started = _start_stream_prepare_worker(
                    file_row["id"],
                    video_id=video["id"],
                    owner_user_id=video["owner_user_id"],
                    title=video["title"],
                )
                if not worker_started:
                    stream_warning = "HLS 背景處理程序啟動失敗，請稍後重新排程。"
                    _sync_hls_platform_job(
                        conn,
                        file_row=file_row,
                        video_id=video["id"],
                        owner_user_id=video["owner_user_id"],
                        title=video["title"],
                        status="failed",
                        progress_percent=100,
                        stage="launch_failed",
                        stage_detail=stream_warning,
                        error_message=stream_warning,
                    )
                else:
                    _sync_hls_platform_job(
                        conn,
                        file_row=file_row,
                        video_id=video["id"],
                        owner_user_id=video["owner_user_id"],
                        title=video["title"],
                        status="running",
                        progress_percent=10,
                        stage="worker_started",
                        stage_detail="HLS 外部轉檔程序已啟動；你可以先做別的事，進度會顯示在任務中心。",
                    )
                conn.commit()
            audit(
                "VIDEO_UPLOAD_PUBLISH",
                get_client_ip(),
                user=actor["username"],
                success=True,
                ua=get_ua(),
                detail=f"video_id={video['id']},cloud_file_id={video['cloud_file_id']},privacy_mode={privacy_mode},visibility={video['visibility']}",
            )
            return json_resp({
                "ok": True,
                "video": video,
                "file": {**upload_result, "filename": safe_public_filename(uploaded.filename)},
                "storage_file": storage_file,
                "stream_asset": stream_asset,
                "stream_warning": stream_warning or "",
                "cover_file": ({**cover_result, "filename": safe_public_filename(cover_upload.filename)} if cover_result else None),
                "cover_storage_file": cover_storage_file,
            })
        except Exception as exc:
            conn.rollback()
            return _error_response(exc)
        finally:
            conn.close()

    @app.route("/shared/videos/<token>", methods=["GET"])
    def shared_video_page(token):
        conn = get_db()
        try:
            row, reason = resolve_video_share_token(conn, token, password="", password_verified=False, counted_in_session=False)
            if not row and reason != "password_required":
                status = 400 if reason == "forbidden_fragment_transport" else 410
                return Response(_shared_video_ended_html(reason), status=status, mimetype="text/html")
        finally:
            conn.close()
        return Response(_shared_video_html(token), status=200, mimetype="text/html")

    @app.route("/api/videos/shared/<token>/unlock", methods=["POST"])
    @require_csrf
    def shared_video_unlock(token):
        conn = get_db()
        try:
            data = request.get_json(silent=True) or {}
            sensitive = _reject_sensitive_share_fields(data)
            if sensitive:
                return sensitive
            password = str(data.get("password") or "")
            row, reason = resolve_video_share_token(conn, token, password=password, password_verified=False)
            if not row:
                if reason in {"password_invalid", "password_locked"}:
                    conn.commit()
                return _shared_video_error_response(reason)
            share_session_id = _create_shared_video_session(token, password_verified=True)
            _count_shared_video_access(conn, row, share_session_id, False)
            conn.commit()
            return json_resp({
                "ok": True,
                "share_url": f"/shared/videos/{token}",
                "share_session_id": share_session_id,
                "password_required": bool((row["share_password_required"] if "share_password_required" in row.keys() else row["password_required"]) or 0),
            })
        finally:
            conn.close()

    @app.route("/api/videos/shared/<token>", methods=["GET"])
    def shared_video_detail(token):
        conn = get_db()
        try:
            row, reason, password_verified, counted_in_session, share_session_id = _resolve_shared_video(conn, token, allow_counted_session_limit=True)
            if not row:
                if reason in {"password_invalid", "password_locked"}:
                    conn.commit()
                return _shared_video_error_response(reason)
            share_session_id = _ensure_shared_video_session_counted(
                conn,
                row,
                token,
                password_verified=password_verified,
                share_session_id=share_session_id,
                counted_in_session=counted_in_session,
            )
            video, _ = shared_video_payload(conn, token, password_verified=password_verified, counted_in_session=True)
            conn.commit()
            return json_resp({"ok": True, "video": video, "share_session_id": share_session_id})
        finally:
            conn.close()

    @app.route("/api/videos/shared/<token>/playback", methods=["GET"])
    def shared_video_playback(token):
        conn = get_db()
        try:
            row, reason, password_verified, counted_in_session, share_session_id = _resolve_shared_video(conn, token, allow_counted_session_limit=True)
            if not row:
                if reason in {"password_invalid", "password_locked"}:
                    conn.commit()
                return _shared_video_error_response(reason)
            share_session_id = _ensure_shared_video_session_counted(conn, row, token, password_verified=password_verified, share_session_id=share_session_id, counted_in_session=counted_in_session)
            file_row = _load_stream_file(conn, file_id=row["cloud_file_id"])
            payload = _playback_payload_for_file(conn, row=file_row, video_id=row["id"], shared_token=token)
            payload = _attach_share_session_to_playback_payload(payload, share_session_id)
            payload["video_id"] = int(row["id"])
            payload["share_session_id"] = share_session_id
            payload["can_prepare_stream"] = False
            payload["prepare_stream_url"] = ""
            conn.commit()
            return json_resp({"ok": True, **payload})
        finally:
            conn.close()

    @app.route("/api/videos/shared/<token>/stream", methods=["GET"])
    def shared_video_stream(token):
        conn = get_db()
        try:
            row, reason, password_verified, counted_in_session, share_session_id = _resolve_shared_video(conn, token, allow_counted_session_limit=True)
            if not row:
                if reason in {"password_invalid", "password_locked"}:
                    conn.commit()
                return _shared_video_error_response(reason)
            _ensure_shared_video_session_counted(conn, row, token, password_verified=password_verified, share_session_id=share_session_id, counted_in_session=counted_in_session)
            file_row = _load_stream_file(conn, file_id=row["cloud_file_id"])
            path = resolve_file_storage_path(storage_root, file_row)
            if not path.exists():
                return json_resp({"ok": False, "msg": "實體檔案不存在", "error": "file_missing"}), 404
            filename = file_row["original_filename_plain_for_public"] or row["title"] or "video"
            mimetype = file_row["mime_type_plain_for_public"] or "video/mp4"
            if is_e2ee_file(file_row):
                conn.commit()
                return send_file(path, as_attachment=False, download_name=filename, mimetype="application/octet-stream", conditional=True)
            if is_server_encrypted_file(file_row):
                conn.commit()
                return json_resp({
                    "ok": False,
                    "msg": "伺服端加密影音不提供主程序直接解密串流，請使用已準備完成的 HLS 播放。",
                    "error": "server_encrypted_hls_required",
                }), 409
            conn.commit()
            return send_file(path, as_attachment=False, download_name=filename, mimetype=mimetype, conditional=True)
        finally:
            conn.close()

    @app.route("/api/videos/shared/<token>/cover", methods=["GET"])
    def shared_video_cover(token):
        conn = get_db()
        try:
            row, reason, password_verified, counted_in_session, share_session_id = _resolve_shared_video(conn, token, allow_counted_session_limit=True)
            if not row:
                if reason in {"password_invalid", "password_locked"}:
                    conn.commit()
                return _shared_video_error_response(reason)
            _ensure_shared_video_session_counted(conn, row, token, password_verified=password_verified, share_session_id=share_session_id, counted_in_session=counted_in_session)
            cover_file_id = row["cover_file_id"]
            if not cover_file_id:
                return json_resp({"ok": False, "msg": "此影音沒有封面", "error": "cover_not_found"}), 404
            cover_row = conn.execute(
                "SELECT * FROM uploaded_files WHERE id=? AND deleted_at IS NULL",
                (cover_file_id,),
            ).fetchone()
            if not cover_row:
                return json_resp({"ok": False, "msg": "封面檔案不存在", "error": "cover_file_not_found"}), 404
            path = resolve_file_storage_path(storage_root, cover_row)
            if not path.exists():
                return json_resp({"ok": False, "msg": "封面實體檔案不存在", "error": "cover_file_missing"}), 404
            filename = cover_row["original_filename_plain_for_public"] or "cover"
            mimetype = cover_row["mime_type_plain_for_public"] or mimetypes.guess_type(filename)[0] or "image/jpeg"
            if is_server_encrypted_file(cover_row):
                raw = decrypt_server_encrypted_bytes(path, server_file_fernet)
                conn.commit()
                return _send_bytes_with_range(raw, download_name=filename, mimetype=mimetype, range_header=request.headers.get("Range"))
            conn.commit()
            return send_file(path, as_attachment=False, download_name=filename, mimetype=mimetype, conditional=True)
        finally:
            conn.close()

    @app.route("/api/videos/shared/<token>/e2ee-key", methods=["GET"])
    def shared_video_e2ee_key(token):
        conn = get_db()
        try:
            row, reason, password_verified, counted_in_session, share_session_id = _resolve_shared_video(conn, token, allow_counted_session_limit=True)
            if not row:
                if reason in {"password_invalid", "password_locked"}:
                    conn.commit()
                return _shared_video_error_response(reason)
            _ensure_shared_video_session_counted(conn, row, token, password_verified=password_verified, share_session_id=share_session_id, counted_in_session=counted_in_session)
            file_row = _load_stream_file(conn, file_id=row["cloud_file_id"])
            if not is_e2ee_file(file_row):
                return json_resp({"ok": False, "msg": "此影音不是端到端加密檔案"}), 400
            if not str((row["share_wrapped_file_key_envelope"] if "share_wrapped_file_key_envelope" in row.keys() else row["wrapped_file_key_envelope"]) or "").strip():
                return json_resp({"ok": False, "msg": "此 E2EE 影音尚未建立可分享的瀏覽器端解密授權", "error": "missing_share_key_wrap"}), 409
            conn.commit()
            return json_resp({
                "ok": True,
                "e2ee_share": {
                    "file_id": file_row["id"],
                    "privacy_mode": file_row["privacy_mode"],
                    "encrypted_metadata": file_row["original_filename_encrypted"],
                    "wrapped_file_key_envelope": row["share_wrapped_file_key_envelope"] if "share_wrapped_file_key_envelope" in row.keys() else row["wrapped_file_key_envelope"],
                    "encryption_algorithm": file_row["encryption_algorithm"],
                    "encryption_version": file_row["encryption_version"],
                    "nonce": file_row["nonce"],
                    "ciphertext_sha256": file_row["ciphertext_sha256"],
                },
            })
        finally:
            conn.close()

    @app.route("/api/videos/shared/<token>/e2ee-stream-v2/manifest", methods=["GET"])
    def shared_video_e2ee_stream_v2_manifest(token):
        conn = get_db()
        try:
            row, reason, password_verified, counted_in_session, share_session_id = _resolve_shared_video(conn, token, allow_counted_session_limit=True)
            if not row:
                if reason in {"password_invalid", "password_locked"}:
                    conn.commit()
                return _shared_video_error_response(reason)
            _ensure_shared_video_session_counted(conn, row, token, password_verified=password_verified, share_session_id=share_session_id, counted_in_session=counted_in_session)
            file_row = _load_stream_file(conn, file_id=row["cloud_file_id"])
            if not is_e2ee_file(file_row):
                return json_resp({"ok": False, "msg": "此影音不是端到端加密檔案", "error": "not_e2ee"}), 400
            payload = serialize_manifest_for_client(conn, file_row=file_row, storage_root=storage_root)
            conn.commit()
            return json_resp(payload)
        finally:
            conn.close()

    @app.route("/api/videos/shared/<token>/e2ee-stream-v2/chunks/<int:chunk_index>", methods=["GET"])
    def shared_video_e2ee_stream_v2_chunk(token, chunk_index):
        conn = get_db()
        try:
            row, reason, password_verified, counted_in_session, share_session_id = _resolve_shared_video(conn, token, allow_counted_session_limit=True)
            if not row:
                if reason in {"password_invalid", "password_locked"}:
                    conn.commit()
                return _shared_video_error_response(reason)
            _ensure_shared_video_session_counted(conn, row, token, password_verified=password_verified, share_session_id=share_session_id, counted_in_session=counted_in_session)
            file_row = _load_stream_file(conn, file_id=row["cloud_file_id"])
            if not is_e2ee_file(file_row):
                return json_resp({"ok": False, "msg": "此影音不是端到端加密檔案", "error": "not_e2ee"}), 400
            resolved, error = resolve_e2ee_chunk_response(conn, file_row=file_row, storage_root=storage_root, chunk_index=chunk_index)
            if error:
                status = 404 if error.get("error") == "chunk_not_found" else 409
                return json_resp(error), status
            conn.commit()
            response = Response(resolved["payload"], status=200, mimetype=resolved.get("content_type") or "application/octet-stream")
            response.headers["Content-Length"] = str(len(resolved["payload"]))
            response.headers["Cache-Control"] = "private, max-age=0, no-store"
            return response
        finally:
            conn.close()

    @app.route("/api/videos/shared/<token>/ciphertext", methods=["GET"])
    def shared_video_ciphertext(token):
        conn = get_db()
        try:
            row, reason, password_verified, counted_in_session, share_session_id = _resolve_shared_video(conn, token, allow_counted_session_limit=True)
            if not row:
                if reason in {"password_invalid", "password_locked"}:
                    conn.commit()
                return _shared_video_error_response(reason)
            _ensure_shared_video_session_counted(conn, row, token, password_verified=password_verified, share_session_id=share_session_id, counted_in_session=counted_in_session)
            file_row = _load_stream_file(conn, file_id=row["cloud_file_id"])
            if not is_e2ee_file(file_row):
                return json_resp({"ok": False, "msg": "此影音不是端到端加密檔案"}), 400
            path = resolve_file_storage_path(storage_root, file_row)
            if not path.exists():
                return json_resp({"ok": False, "msg": "實體檔案不存在"}), 404
            conn.commit()
            return send_file(
                path,
                as_attachment=False,
                download_name=file_row["original_filename_plain_for_public"] or "e2ee.bin",
                mimetype="application/octet-stream",
                conditional=True,
            )
        finally:
            conn.close()

    @app.route("/api/videos/shared/<token>/hls/master.m3u8", methods=["GET"])
    def shared_video_hls_master(token):
        conn = get_db()
        try:
            row, reason, password_verified, counted_in_session, share_session_id = _resolve_shared_video(conn, token, allow_counted_session_limit=True)
            if not row:
                if reason in {"password_invalid", "password_locked"}:
                    conn.commit()
                return _shared_video_error_response(reason)
            share_session_id = _ensure_shared_video_session_counted(conn, row, token, password_verified=password_verified, share_session_id=share_session_id, counted_in_session=counted_in_session)
            file_row = _load_stream_file(conn, file_id=row["cloud_file_id"])
            asset = get_stream_status(conn, file_row=file_row, include_segments=False)
            if not asset or asset.get("status") != "ready" or not asset.get("master_manifest_path"):
                return json_resp({"ok": False, "msg": "影音串流尚未準備完成", "error": "stream_not_ready"}), 409
            path = resolve_file_storage_path(storage_root, {"storage_path": asset["master_manifest_path"]})
            conn.commit()
            return _send_hls_master_manifest(path, share_session_id=share_session_id)
        finally:
            conn.close()

    @app.route("/api/videos/shared/<token>/hls/<variant>/playlist.m3u8", methods=["GET"])
    def shared_video_hls_variant_playlist(token, variant):
        conn = get_db()
        try:
            row, reason, password_verified, counted_in_session, share_session_id = _resolve_shared_video(conn, token, allow_counted_session_limit=True)
            if not row:
                if reason in {"password_invalid", "password_locked"}:
                    conn.commit()
                return _shared_video_error_response(reason)
            share_session_id = _ensure_shared_video_session_counted(conn, row, token, password_verified=password_verified, share_session_id=share_session_id, counted_in_session=counted_in_session)
            file_row = _load_stream_file(conn, file_id=row["cloud_file_id"])
            asset = get_stream_status(conn, file_row=file_row, include_segments=False)
            if not asset or asset.get("status") != "ready":
                return json_resp({"ok": False, "msg": "影音串流尚未準備完成", "error": "stream_not_ready"}), 409
            match = next((item for item in (asset.get("variants") or []) if item.get("name") == variant), None)
            if not match:
                return json_resp({"ok": False, "msg": "找不到串流變體", "error": "variant_not_found"}), 404
            path = resolve_file_storage_path(storage_root, {"storage_path": match["playlist_path"]})
            conn.commit()
            text = _append_share_session_to_hls_manifest(Path(path).read_text(encoding="utf-8"), share_session_id)
            return Response(text, status=200, mimetype="application/vnd.apple.mpegurl")
        finally:
            conn.close()

    @app.route("/api/videos/shared/<token>/hls/<variant>/<segment>", methods=["GET"])
    def shared_video_hls_segment(token, variant, segment):
        conn = get_db()
        try:
            row, reason, password_verified, counted_in_session, share_session_id = _resolve_shared_video(conn, token, allow_counted_session_limit=True)
            if not row:
                if reason in {"password_invalid", "password_locked"}:
                    conn.commit()
                return _shared_video_error_response(reason)
            _ensure_shared_video_session_counted(conn, row, token, password_verified=password_verified, share_session_id=share_session_id, counted_in_session=counted_in_session)
            file_row = _load_stream_file(conn, file_id=row["cloud_file_id"])
            asset = get_stream_status(conn, file_row=file_row)
            if not asset or asset.get("status") != "ready":
                return json_resp({"ok": False, "msg": "影音串流尚未準備完成", "error": "stream_not_ready"}), 409
            match = next((item for item in (asset.get("variants") or []) if item.get("name") == variant), None)
            if not match:
                return json_resp({"ok": False, "msg": "找不到串流變體", "error": "variant_not_found"}), 404
            if "/" in segment or ".." in segment:
                return json_resp({"ok": False, "msg": "無效的串流片段", "error": "invalid_segment"}), 400
            rel = next((item["path"] for item in (match.get("segments") or []) if item.get("filename") == segment), "")
            if not rel:
                if segment == "init.mp4" and match.get("init_segment_path"):
                    rel = match["init_segment_path"]
                else:
                    return json_resp({"ok": False, "msg": "找不到串流片段", "error": "segment_not_found"}), 404
            path = resolve_file_storage_path(storage_root, {"storage_path": rel})
            mimetype = "video/mp4" if segment.endswith(".mp4") or segment.endswith(".m4s") else "application/octet-stream"
            conn.commit()
            return send_file(path, as_attachment=False, download_name=segment, mimetype=mimetype, conditional=True)
        finally:
            conn.close()

    @app.route("/api/videos/<int:video_id>/share-link", methods=["PUT", "DELETE"])
    @require_csrf
    def video_share_link_manage(video_id):
        actor, err = _actor_or_401()
        if err:
            return err
        conn = get_db()
        try:
            try:
                video = get_video(conn, video_id, actor=actor)
            except PermissionError:
                return json_resp({"ok": False, "msg": "找不到影音", "error": "not_found"}), 404
            if not video or not video.get("can_edit"):
                return json_resp({"ok": False, "msg": "找不到影音", "error": "not_found"}), 404
            if request.method == "DELETE":
                revoke_video_share_link(conn, actor=actor, video_id=video_id)
                # 先提交分享連結撤銷，再寫 secure_audit。
                # 否則同一請求中的未提交寫入會和 audit() 另開的 SQLite 連線互鎖，
                # 在真實 server wiring 下把正常撤銷操作打成 500。
                conn.commit()
                audit(
                    "VIDEO_SHARE_LINK_REVOKE",
                    get_client_ip(),
                    user=actor["username"],
                    success=True,
                    ua=get_ua(),
                    detail=f"video_id={int(video_id)}",
                )
                return json_resp({"ok": True, "share_link": None, "video_id": int(video_id)})
            data = request.get_json(silent=True) or {}
            sensitive = _reject_sensitive_share_fields(data)
            if sensitive:
                return sensitive
            share_link, msg = ensure_video_share_link(
                conn,
                actor=actor,
                video_id=video_id,
                password=data["share_password"] if "share_password" in data else None,
                wrapped_file_key_envelope=data["share_wrapped_file_key_envelope"] if "share_wrapped_file_key_envelope" in data else None,
                expires_at=data["share_expires_at"] if "share_expires_at" in data else None,
                max_views=data["share_max_views"] if "share_max_views" in data else None,
                regenerate=bool(data.get("regenerate")),
            )
            if msg:
                return json_resp({"ok": False, "msg": msg, "error": "share_link_update_failed"}), 400
            updated = get_video(conn, video_id, actor=actor)
            # 同 DELETE 分支，先提交 share-link 寫入，避免 audit 另開連線時踩到 SQLite 寫鎖。
            conn.commit()
            audit(
                "VIDEO_SHARE_LINK_UPDATE",
                get_client_ip(),
                user=actor["username"],
                success=True,
                ua=get_ua(),
                detail=(
                    f"video_id={int(video_id)},"
                    f"regenerate={1 if data.get('regenerate') else 0},"
                    f"password_required={1 if share_link and share_link.get('password_required') else 0},"
                    f"state={share_link.get('state') if share_link else 'unknown'}"
                ),
            )
            return json_resp({"ok": True, "share_link": share_link, "video": updated})
        except PermissionError as exc:
            conn.rollback()
            return _error_response(exc)
        except ValueError as exc:
            conn.rollback()
            return _error_response(exc)
        finally:
            conn.close()

    @app.route("/api/videos/manage", methods=["GET"])
    @require_csrf
    def video_manage_list():
        actor, err = _actor_or_401()
        if err:
            return err
        conn = get_db()
        try:
            videos = list_owner_videos(
                conn,
                actor=actor,
                limit=request.args.get("limit") or 120,
            )
            for video in videos:
                try:
                    detail = get_video(conn, video["id"], actor=actor)
                    if detail:
                        for key in (
                            "share_link",
                            "share_url",
                            "share_password_required",
                            "share_requires_fragment_key",
                            "share_expires_at",
                            "share_max_views",
                        ):
                            if key in detail:
                                video[key] = detail[key]
                    file_row = _load_stream_file(conn, file_id=video["cloud_file_id"])
                    video["stream_asset"] = get_stream_status(conn, file_row=file_row, include_segments=False)
                except Exception:
                    video["stream_asset"] = None
            summary = {
                "total_videos": len(videos),
                "total_views": sum(int(video.get("view_count") or 0) for video in videos),
                "total_likes": sum(int(video.get("like_count") or 0) for video in videos),
                "total_gross_points": sum(int(video.get("gross_points") or 0) for video in videos),
                "total_revenue_points": sum(int(video.get("revenue_points") or 0) for video in videos),
                "total_platform_fee_points": sum(int(video.get("platform_fee_points") or 0) for video in videos),
                "total_boost_points": sum(int(video.get("boost_points_total") or 0) for video in videos),
            }
            return json_resp({"ok": True, "videos": videos, "summary": summary})
        except PermissionError as exc:
            return _error_response(exc)
        finally:
            conn.close()

    @app.route("/api/videos/<int:video_id>/manage", methods=["PUT", "DELETE"])
    @require_csrf
    def video_manage_item(video_id):
        actor, err = _actor_or_401()
        if err:
            return err
        conn = get_db()
        try:
            if request.method == "DELETE":
                result = delete_owner_video(conn, actor=actor, video_id=video_id)
                conn.commit()
                audit(
                    "VIDEO_MANAGE_DELETE",
                    get_client_ip(),
                    user=actor["username"],
                    success=True,
                    ua=get_ua(),
                    detail=f"video_id={int(video_id)}",
                )
                return json_resp(result)
            data, bad_resp, status = _parse_json_body()
            if bad_resp:
                return bad_resp, status
            kwargs = {}
            if "cover_file_id" in data:
                kwargs["cover_file_id"] = data.get("cover_file_id")
            video = update_owner_video(
                conn,
                actor=actor,
                video_id=video_id,
                title=data.get("title"),
                description=data.get("description"),
                visibility=data.get("visibility"),
                **kwargs,
            )
            conn.commit()
            audit(
                "VIDEO_MANAGE_UPDATE",
                get_client_ip(),
                user=actor["username"],
                success=True,
                ua=get_ua(),
                detail=f"video_id={int(video_id)},visibility={video.get('visibility') if video else ''}",
            )
            return json_resp({"ok": True, "video": video})
        except Exception as exc:
            conn.rollback()
            return _error_response(exc)
        finally:
            conn.close()

    @app.route("/api/videos/<int:video_id>/boost", methods=["POST"])
    @require_csrf
    def video_manage_boost(video_id):
        actor, err = _actor_or_401()
        if err:
            return err
        data, bad_resp, status = _parse_json_body()
        if bad_resp:
            return bad_resp, status
        conn = get_db()
        try:
            result = boost_owner_video(
                conn,
                points_service=points_service,
                actor=actor,
                video_id=video_id,
                amount=data.get("amount"),
                idempotency_key=request.headers.get("Idempotency-Key") or data.get("idempotency_key"),
            )
            conn.commit()
            audit(
                "VIDEO_MANAGE_BOOST",
                get_client_ip(),
                user=actor["username"],
                success=True,
                ua=get_ua(),
                detail=f"video_id={int(video_id)},amount={int(result.get('amount') or 0)}",
            )
            return json_resp(result)
        except Exception as exc:
            conn.rollback()
            if "insufficient balance" in str(exc):
                return json_resp({"ok": False, "msg": "積分不足，無法增加曝光", "error": "insufficient_balance"}), 409
            return _error_response(exc)
        finally:
            conn.close()

    @app.route("/api/videos", methods=["GET"])
    @require_csrf
    def video_list():
        actor = get_current_user_ctx()
        conn = get_db()
        try:
            videos = list_videos(
                conn,
                actor=actor,
                sort=request.args.get("sort") or "new",
                page=request.args.get("page") or 1,
                query=request.args.get("q") or "",
            )
            videos = [video for video in videos if _video_ready_for_browse(conn, video)]
            return json_resp({"ok": True, "videos": videos})
        finally:
            conn.close()

    @app.route("/api/videos/<int:video_id>", methods=["GET"])
    @require_csrf
    def video_detail(video_id):
        actor = get_current_user_ctx()
        conn = get_db()
        try:
            video = get_video(conn, video_id, actor=actor)
            if not video:
                return json_resp({"ok": False, "msg": "找不到影片", "error": "not_found"}), 404
            comments = list_video_comments(conn, actor=actor, video_id=video_id, limit=100)
            return json_resp({"ok": True, "video": video, "comments": comments})
        except PermissionError as exc:
            return _error_response(exc)
        finally:
            conn.close()

    @app.route("/api/media/<file_id>/prepare-stream", methods=["POST"])
    @require_csrf
    def media_prepare_stream(file_id):
        actor, err = _actor_or_401()
        if err:
            return err
        conn = get_db()
        try:
            ensure_media_stream_schema(conn)
            row = _load_stream_file(conn, file_id=file_id)
            _assert_stream_prepare_allowed(actor, row)
            if is_e2ee_file(row):
                return json_resp({"ok": False, "msg": "E2EE 影音只支援瀏覽器端解密播放，不建立伺服器端串流衍生檔", "error": "e2ee_direct_only"}), 409
            video_row = conn.execute(
                "SELECT id, title, owner_user_id, visibility FROM videos WHERE cloud_file_id=? AND deleted_at IS NULL LIMIT 1",
                (row["id"],),
            ).fetchone()
            asset, stream_warning, stream_queued = _queue_stream_prepare(
                conn,
                file_row=row,
                video_id=video_row["id"] if video_row else None,
                title=video_row["title"] if video_row else row["original_filename_plain_for_public"],
                visibility=video_row["visibility"] if video_row else "private",
                force=True,
            )
            conn.commit()
            if stream_queued:
                worker_started = _start_stream_prepare_worker(
                    row["id"],
                    video_id=video_row["id"] if video_row else None,
                    owner_user_id=video_row["owner_user_id"] if video_row else row["owner_user_id"],
                    title=video_row["title"] if video_row else row["original_filename_plain_for_public"],
                )
                if not worker_started:
                    stream_warning = "HLS 背景處理程序啟動失敗，請稍後重新排程。"
                    _sync_hls_platform_job(
                        conn,
                        file_row=row,
                        video_id=video_row["id"] if video_row else None,
                        owner_user_id=video_row["owner_user_id"] if video_row else row["owner_user_id"],
                        title=video_row["title"] if video_row else row["original_filename_plain_for_public"],
                        status="failed",
                        progress_percent=100,
                        stage="launch_failed",
                        stage_detail=stream_warning,
                        error_message=stream_warning,
                    )
                else:
                    _sync_hls_platform_job(
                        conn,
                        file_row=row,
                        video_id=video_row["id"] if video_row else None,
                        owner_user_id=video_row["owner_user_id"] if video_row else row["owner_user_id"],
                        title=video_row["title"] if video_row else row["original_filename_plain_for_public"],
                        status="running",
                        progress_percent=10,
                        stage="worker_started",
                        stage_detail="HLS 外部轉檔程序已啟動。",
                    )
                conn.commit()
            audit(
                "MEDIA_STREAM_PREPARE",
                get_client_ip(),
                user=actor["username"],
                success=True,
                ua=get_ua(),
                detail=f"file_id={file_id},status={asset.get('status')}",
            )
            return json_resp({
                "ok": True,
                "asset": asset,
                "queued": bool(stream_queued),
                "stream_warning": stream_warning or "",
                "msg": "HLS 串流已排入背景處理；你可以先做別的事，進度會顯示在任務中心，完成後會通知上傳者。",
            })
        except Exception as exc:
            conn.rollback()
            return _error_response(exc)
        finally:
            conn.close()

    @app.route("/api/media/<file_id>/e2ee-stream-v2", methods=["POST"])
    @require_csrf
    def media_prepare_e2ee_stream_v2(file_id):
        actor, err = _actor_or_401()
        if err:
            return err
        conn = get_db()
        try:
            ensure_e2ee_stream_v2_schema(conn)
            row = _load_stream_file(conn, file_id=file_id)
            _assert_stream_prepare_allowed(actor, row)
            if not is_e2ee_file(row):
                return json_resp({"ok": False, "msg": "只有 strict E2EE 影音可建立 Streaming v2", "error": "not_e2ee"}), 400
            if request.is_json:
                return json_resp({"ok": False, "msg": "E2EE Streaming v2 準備需要 multipart bundle 上傳", "error": "multipart_required"}), 400
            bundle = request.files.get("bundle")
            manifest_json = request.form.get("manifest_json") or ""
            if not bundle or not getattr(bundle, "filename", ""):
                return json_resp({"ok": False, "msg": "缺少 E2EE Streaming v2 bundle", "error": "missing_bundle"}), 400
            bundle_size = _file_storage_size(bundle)
            bundle_limit = _e2ee_stream_bundle_max_bytes()
            if bundle_limit > 0 and bundle_size > bundle_limit:
                return json_resp({
                    "ok": False,
                    "msg": f"E2EE Streaming v2 bundle 超過伺服器即時處理上限（{max(1, bundle_limit // (1024 * 1024))} MB），請改用較小分段或背景處理流程。",
                    "error": "e2ee_stream_bundle_too_large",
                    "max_bytes": bundle_limit,
                }), 413
            if not manifest_json.strip():
                return json_resp({"ok": False, "msg": "缺少 E2EE Streaming v2 manifest", "error": "missing_manifest"}), 400
            try:
                manifest_payload = json.loads(manifest_json)
            except Exception:
                return json_resp({"ok": False, "msg": "E2EE Streaming v2 manifest JSON 不正確", "error": "invalid_manifest_json"}), 400
            sensitive = _reject_sensitive_share_fields(manifest_payload)
            if sensitive:
                return sensitive
            asset = upsert_e2ee_stream_v2_asset(
                conn,
                file_row=row,
                storage_root=storage_root,
                manifest_payload=manifest_payload,
                bundle_bytes=bundle.read(),
            )
            _sync_e2ee_stream_v2_platform_job(
                conn,
                file_row=row,
                owner_user_id=row["owner_user_id"],
                title=row["original_filename_plain_for_public"],
                asset=asset,
                status="succeeded",
            )
            conn.commit()
            audit(
                "MEDIA_E2EE_STREAM_V2_PREPARE",
                get_client_ip(),
                user=actor["username"],
                success=True,
                ua=get_ua(),
                detail=f"file_id={file_id},chunks={asset.get('chunk_count', 0)}",
            )
            return json_resp({"ok": True, "asset": asset})
        except Exception as exc:
            conn.rollback()
            return _error_response(exc)
        finally:
            conn.close()

    @app.route("/api/videos/<int:video_id>/e2ee-stream-v2/manifest", methods=["GET"])
    @require_csrf
    def video_e2ee_stream_v2_manifest(video_id):
        actor = get_current_user_ctx()
        conn = get_db()
        try:
            ensure_e2ee_stream_v2_schema(conn)
            video = get_video(conn, video_id, actor=actor, for_stream=True)
            if not video:
                return json_resp({"ok": False, "msg": "找不到影片", "error": "not_found"}), 404
            row = _load_stream_file(conn, file_id=video["cloud_file_id"])
            if not is_e2ee_file(row):
                return json_resp({"ok": False, "msg": "此影音不是端到端加密檔案", "error": "not_e2ee"}), 400
            return json_resp(serialize_manifest_for_client(conn, file_row=row, storage_root=storage_root))
        except PermissionError as exc:
            return _error_response(exc)
        except ValueError as exc:
            return _error_response(exc)
        finally:
            conn.close()

    @app.route("/api/videos/<int:video_id>/e2ee-stream-v2/chunks/<int:chunk_index>", methods=["GET"])
    @require_csrf
    def video_e2ee_stream_v2_chunk(video_id, chunk_index):
        actor = get_current_user_ctx()
        conn = get_db()
        try:
            ensure_e2ee_stream_v2_schema(conn)
            video = get_video(conn, video_id, actor=actor, for_stream=True)
            if not video:
                return json_resp({"ok": False, "msg": "找不到影片", "error": "not_found"}), 404
            row = _load_stream_file(conn, file_id=video["cloud_file_id"])
            if not is_e2ee_file(row):
                return json_resp({"ok": False, "msg": "此影音不是端到端加密檔案", "error": "not_e2ee"}), 400
            resolved, error = resolve_e2ee_chunk_response(conn, file_row=row, storage_root=storage_root, chunk_index=chunk_index)
            if error:
                status = 404 if error.get("error") == "chunk_not_found" else 409
                return json_resp(error), status
            response = Response(resolved["payload"], status=200, mimetype=resolved.get("content_type") or "application/octet-stream")
            response.headers["Content-Length"] = str(len(resolved["payload"]))
            response.headers["Cache-Control"] = "private, max-age=0, no-store"
            return response
        except PermissionError as exc:
            return _error_response(exc)
        except ValueError as exc:
            return _error_response(exc)
        finally:
            conn.close()

    @app.route("/api/videos/<int:video_id>/e2ee-key", methods=["GET"])
    @require_csrf
    def video_e2ee_key(video_id):
        actor = get_current_user_ctx()
        conn = get_db()
        try:
            ensure_cloud_drive_attachment_schema(conn)
            video = get_video(conn, video_id, actor=actor, for_stream=True)
            if not video:
                return json_resp({"ok": False, "msg": "找不到影片", "error": "not_found"}), 404
            file_row = _load_stream_file(conn, file_id=video["cloud_file_id"])
            if not is_e2ee_file(file_row):
                return json_resp({"ok": False, "msg": "此影音不是端到端加密檔案", "error": "not_e2ee"}), 400
            key = _video_e2ee_owner_key(conn, file_row)
            if not key:
                return json_resp({"ok": False, "msg": "此 E2EE 影音缺少擁有者解密金鑰包裝", "error": "missing_owner_e2ee_key"}), 409
            return json_resp({
                "ok": True,
                "e2ee": {
                    "file_id": file_row["id"],
                    "privacy_mode": file_row["privacy_mode"],
                    "encrypted_metadata": file_row["original_filename_encrypted"],
                    "encrypted_file_key": key["encrypted_file_key"],
                    "wrapped_by": key["wrapped_by"],
                    "key_version": key["key_version"],
                    "encryption_algorithm": file_row["encryption_algorithm"],
                    "encryption_version": file_row["encryption_version"],
                    "nonce": file_row["nonce"],
                    "ciphertext_sha256": file_row["ciphertext_sha256"],
                },
            })
        except PermissionError as exc:
            return _error_response(exc)
        except ValueError as exc:
            return _error_response(exc)
        finally:
            conn.close()

    @app.route("/api/videos/<int:video_id>/ciphertext", methods=["GET"])
    @require_csrf
    def video_e2ee_ciphertext(video_id):
        actor = get_current_user_ctx()
        conn = get_db()
        try:
            video = get_video(conn, video_id, actor=actor, for_stream=True)
            if not video:
                return json_resp({"ok": False, "msg": "找不到影片", "error": "not_found"}), 404
            file_row = _load_stream_file(conn, file_id=video["cloud_file_id"])
            if not is_e2ee_file(file_row):
                return json_resp({"ok": False, "msg": "此影音不是端到端加密檔案", "error": "not_e2ee"}), 400
            path = resolve_file_storage_path(storage_root, file_row)
            if not path.exists():
                return json_resp({"ok": False, "msg": "實體檔案不存在", "error": "file_missing"}), 404
            return send_file(
                path,
                as_attachment=False,
                download_name=file_row["original_filename_plain_for_public"] or "e2ee.bin",
                mimetype="application/octet-stream",
                conditional=True,
            )
        except PermissionError as exc:
            return _error_response(exc)
        except ValueError as exc:
            return _error_response(exc)
        finally:
            conn.close()

    @app.route("/api/media/<file_id>/stream-status", methods=["GET"])
    @require_csrf
    def media_stream_status(file_id):
        actor, err = _actor_or_401()
        if err:
            return err
        conn = get_db()
        try:
            ensure_media_stream_schema(conn)
            row = _load_stream_file(conn, file_id=file_id)
            _assert_stream_prepare_allowed(actor, row)
            return json_resp({"ok": True, "asset": get_stream_status(conn, file_row=row, include_segments=False)})
        except Exception as exc:
            return _error_response(exc)
        finally:
            conn.close()

    @app.route("/api/videos/<int:video_id>/playback", methods=["GET"])
    @require_csrf
    def video_playback(video_id):
        actor = get_current_user_ctx()
        conn = get_db()
        try:
            ensure_media_stream_schema(conn)
            video = get_video(conn, video_id, actor=actor, for_stream=True)
            if not video:
                return json_resp({"ok": False, "msg": "找不到影片", "error": "not_found"}), 404
            row = _load_stream_file(conn, file_id=video["cloud_file_id"])
            payload = _playback_payload_for_file(conn, row=row, video_id=video_id)
            payload["video_id"] = int(video_id)
            payload["can_prepare_stream"] = bool(video.get("can_edit")) and not is_e2ee_file(row)
            payload["prepare_stream_url"] = video.get("prepare_stream_url") or ""
            return json_resp({"ok": True, **payload})
        except PermissionError as exc:
            return _error_response(exc)
        except ValueError as exc:
            return _error_response(exc)
        finally:
            conn.close()

    @app.route("/api/videos/<int:video_id>/stream", methods=["GET"])
    @require_csrf
    def video_stream(video_id):
        actor = get_current_user_ctx()
        conn = get_db()
        try:
            video = get_video(conn, video_id, actor=actor, for_stream=True)
            if not video:
                return json_resp({"ok": False, "msg": "找不到影片", "error": "not_found"}), 404
            row = conn.execute(
                "SELECT * FROM uploaded_files WHERE id=? AND deleted_at IS NULL",
                (video["cloud_file_id"],),
            ).fetchone()
            if not row:
                return json_resp({"ok": False, "msg": "找不到影片檔案", "error": "file_not_found"}), 404
            path = resolve_file_storage_path(storage_root, row)
            if not path.exists():
                return json_resp({"ok": False, "msg": "實體檔案不存在", "error": "file_missing"}), 404
            filename = row["original_filename_plain_for_public"] or video["title"] or "video"
            mimetype = row["mime_type_plain_for_public"] or "video/mp4"
            if is_e2ee_file(row):
                return send_file(
                    path,
                    as_attachment=False,
                    download_name=filename,
                    mimetype="application/octet-stream",
                    conditional=True,
                )
            if is_server_encrypted_file(row):
                return json_resp({
                    "ok": False,
                    "msg": "伺服端加密影音不提供主程序直接解密串流，請使用已準備完成的 HLS 播放。",
                    "error": "server_encrypted_hls_required",
                }), 409
            return send_file(path, as_attachment=False, download_name=filename, mimetype=mimetype, conditional=True)
        except PermissionError as exc:
            return _error_response(exc)
        except ValueError as exc:
            return _error_response(exc)
        finally:
            conn.close()

    @app.route("/api/videos/<int:video_id>/hls/master.m3u8", methods=["GET"])
    @require_csrf
    def video_hls_master(video_id):
        actor = get_current_user_ctx()
        conn = get_db()
        try:
            ensure_media_stream_schema(conn)
            video = get_video(conn, video_id, actor=actor, for_stream=True)
            if not video:
                return json_resp({"ok": False, "msg": "找不到影片", "error": "not_found"}), 404
            row = _load_stream_file(conn, file_id=video["cloud_file_id"])
            asset = get_stream_status(conn, file_row=row, include_segments=False)
            if not asset or asset.get("status") != "ready" or not asset.get("master_manifest_path"):
                return json_resp({"ok": False, "msg": "影音串流尚未準備完成", "error": "stream_not_ready"}), 409
            path = resolve_file_storage_path(storage_root, {"storage_path": asset["master_manifest_path"]})
            return _send_hls_master_manifest(path)
        except PermissionError as exc:
            return _error_response(exc)
        except ValueError as exc:
            return _error_response(exc)
        finally:
            conn.close()

    @app.route("/api/videos/<int:video_id>/hls/<variant>/playlist.m3u8", methods=["GET"])
    @require_csrf
    def video_hls_variant_playlist(video_id, variant):
        actor = get_current_user_ctx()
        conn = get_db()
        try:
            ensure_media_stream_schema(conn)
            video = get_video(conn, video_id, actor=actor, for_stream=True)
            if not video:
                return json_resp({"ok": False, "msg": "找不到影片", "error": "not_found"}), 404
            row = _load_stream_file(conn, file_id=video["cloud_file_id"])
            asset = get_stream_status(conn, file_row=row, include_segments=False)
            if not asset or asset.get("status") != "ready":
                return json_resp({"ok": False, "msg": "影音串流尚未準備完成", "error": "stream_not_ready"}), 409
            match = next((item for item in (asset.get("variants") or []) if item.get("name") == variant), None)
            if not match:
                return json_resp({"ok": False, "msg": "找不到串流變體", "error": "variant_not_found"}), 404
            path = resolve_file_storage_path(storage_root, {"storage_path": match["playlist_path"]})
            return send_file(path, as_attachment=False, download_name="playlist.m3u8", mimetype="application/vnd.apple.mpegurl", conditional=True)
        except PermissionError as exc:
            return _error_response(exc)
        except ValueError as exc:
            return _error_response(exc)
        finally:
            conn.close()

    @app.route("/api/videos/<int:video_id>/hls/<variant>/<segment>", methods=["GET"])
    @require_csrf
    def video_hls_segment(video_id, variant, segment):
        actor = get_current_user_ctx()
        conn = get_db()
        try:
            ensure_media_stream_schema(conn)
            video = get_video(conn, video_id, actor=actor, for_stream=True)
            if not video:
                return json_resp({"ok": False, "msg": "找不到影片", "error": "not_found"}), 404
            row = _load_stream_file(conn, file_id=video["cloud_file_id"])
            asset = get_stream_status(conn, file_row=row)
            if not asset or asset.get("status") != "ready":
                return json_resp({"ok": False, "msg": "影音串流尚未準備完成", "error": "stream_not_ready"}), 409
            match = next((item for item in (asset.get("variants") or []) if item.get("name") == variant), None)
            if not match:
                return json_resp({"ok": False, "msg": "找不到串流變體", "error": "variant_not_found"}), 404
            if "/" in segment or ".." in segment:
                return json_resp({"ok": False, "msg": "無效的串流片段", "error": "invalid_segment"}), 400
            rel = next((item["path"] for item in (match.get("segments") or []) if item.get("filename") == segment), "")
            if not rel:
                if segment == "init.mp4" and match.get("init_segment_path"):
                    rel = match["init_segment_path"]
                else:
                    return json_resp({"ok": False, "msg": "找不到串流片段", "error": "segment_not_found"}), 404
            path = resolve_file_storage_path(storage_root, {"storage_path": rel})
            mimetype = "video/mp4" if segment.endswith(".mp4") or segment.endswith(".m4s") else "application/octet-stream"
            return send_file(path, as_attachment=False, download_name=segment, mimetype=mimetype, conditional=True)
        except PermissionError as exc:
            return _error_response(exc)
        except ValueError as exc:
            return _error_response(exc)
        finally:
            conn.close()

    @app.route("/api/videos/<int:video_id>/cover", methods=["GET"])
    @require_csrf
    def video_cover(video_id):
        actor = get_current_user_ctx()
        conn = get_db()
        try:
            video = get_video(conn, video_id, actor=actor)
            if not video:
                return json_resp({"ok": False, "msg": "找不到影音", "error": "not_found"}), 404
            cover_file_id = video.get("cover_file_id")
            if not cover_file_id:
                return json_resp({"ok": False, "msg": "此影音沒有封面", "error": "cover_not_found"}), 404
            row = conn.execute(
                "SELECT * FROM uploaded_files WHERE id=? AND deleted_at IS NULL",
                (cover_file_id,),
            ).fetchone()
            if not row:
                return json_resp({"ok": False, "msg": "封面檔案不存在", "error": "cover_file_not_found"}), 404
            path = resolve_file_storage_path(storage_root, row)
            if not path.exists():
                return json_resp({"ok": False, "msg": "封面實體檔案不存在", "error": "cover_file_missing"}), 404
            filename = row["original_filename_plain_for_public"] or "cover"
            mimetype = row["mime_type_plain_for_public"] or mimetypes.guess_type(filename)[0] or "image/jpeg"
            if is_server_encrypted_file(row):
                try:
                    raw = decrypt_server_encrypted_bytes(path, server_file_fernet)
                except ValueError as exc:
                    return _svg_placeholder_response(str(exc))
                return _send_bytes_with_range(raw, download_name=filename, mimetype=mimetype, range_header=request.headers.get("Range"))
            return send_file(path, as_attachment=False, download_name=filename, mimetype=mimetype, conditional=True)
        except PermissionError as exc:
            return _error_response(exc)
        except ValueError as exc:
            return _error_response(exc)
        finally:
            conn.close()

    @app.route("/api/videos/<int:video_id>/view", methods=["POST"])
    @require_csrf
    def video_view(video_id):
        actor, err = _actor_or_401()
        if err:
            return err
        data, err, status = _parse_json_body()
        if err:
            return err, status
        conn = get_db()
        try:
            result = record_video_view(
                conn,
                actor=actor,
                video_id=video_id,
                ip=get_client_ip(),
                watch_seconds=data.get("watch_seconds") or 0,
                completed=bool(data.get("completed")),
            )
            conn.commit()
            return json_resp({"ok": True, **result})
        except Exception as exc:
            conn.rollback()
            return _error_response(exc)
        finally:
            conn.close()

    @app.route("/api/videos/<int:video_id>/like", methods=["POST", "DELETE"])
    @require_csrf
    def video_like(video_id):
        actor, err = _actor_or_401()
        if err:
            return err
        conn = get_db()
        try:
            video = set_video_like(conn, actor=actor, video_id=video_id, liked=request.method == "POST")
            conn.commit()
            return json_resp({"ok": True, "video": video})
        except Exception as exc:
            conn.rollback()
            return _error_response(exc)
        finally:
            conn.close()

    @app.route("/api/videos/<int:video_id>/comments", methods=["GET", "POST"])
    @require_csrf
    def video_comments(video_id):
        actor = get_current_user_ctx()
        if request.method == "POST":
            actor, err = _actor_or_401()
            if err:
                return err
            data, err, status = _parse_json_body()
            if err:
                return err, status
        conn = get_db()
        try:
            if request.method == "GET":
                comments = list_video_comments(conn, actor=actor, video_id=video_id, limit=100)
                return json_resp({"ok": True, "comments": comments})
            comment = add_video_comment(
                conn,
                actor=actor,
                video_id=video_id,
                content=data.get("content"),
                parent_id=data.get("parent_id"),
            )
            conn.commit()
            audit(
                "VIDEO_COMMENT",
                get_client_ip(),
                user=actor["username"],
                success=True,
                ua=get_ua(),
                detail=f"video_id={video_id},comment_id={comment['id']}",
            )
            return json_resp({"ok": True, "comment": comment})
        except Exception as exc:
            conn.rollback()
            return _error_response(exc)
        finally:
            conn.close()

    @app.route("/api/videos/<int:video_id>/comment", methods=["POST"])
    @require_csrf
    def video_comment_alias(video_id):
        return video_comments(video_id)

    @app.route("/api/videos/<int:video_id>/tip", methods=["POST"])
    @require_csrf
    def video_tip(video_id):
        actor, err = _actor_or_401()
        if err:
            return err
        data, err, status = _parse_json_body()
        if err:
            return err, status
        conn = get_db()
        try:
            amount = int(data.get("amount") or 0)
            min_points = max(1, int(_settings_float("video_tip_min_points", 1)))
            if amount < min_points:
                return json_resp({"ok": False, "msg": f"投幣至少需要 {min_points} 點", "error": "tip_amount_too_small"}), 400
            ensure_video_schema(conn)
            conn.commit()
            conn.execute("BEGIN IMMEDIATE")
            result = tip_video(
                conn,
                points_service=points_service,
                actor=actor,
                video_id=video_id,
                amount=amount,
                fee_percent=_settings_float("video_tip_fee_percent", 5),
                idempotency_key=request.headers.get("Idempotency-Key") or data.get("idempotency_key"),
            )
            conn.commit()
            audit(
                "VIDEO_TIP",
                get_client_ip(),
                user=actor["username"],
                success=True,
                ua=get_ua(),
                detail=f"video_id={video_id},amount={result['tip']['amount_points']},fee={result['tip']['fee_points']}",
            )
            return json_resp(result)
        except Exception as exc:
            conn.rollback()
            return _error_response(exc)
        finally:
            conn.close()
