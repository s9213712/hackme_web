from pathlib import Path
import mimetypes

from flask import Response, request, send_file

from services.cloud_drive import (
    decrypt_server_encrypted_bytes,
    ensure_cloud_drive_attachment_schema,
    is_server_encrypted_file,
    resolve_file_storage_path,
    store_cloud_upload,
)
from services.storage_albums import create_storage_file_entry, ensure_storage_album_schema
from services.upload_security import safe_public_filename
from services.videos import (
    add_video_comment,
    ensure_video_schema,
    get_video,
    list_video_comments,
    list_videos,
    publish_video,
    record_video_view,
    set_video_like,
    tip_video,
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
    get_system_settings = deps.get("get_system_settings", lambda: {})
    get_member_level_rule = deps["get_member_level_rule"]

    def _parse_json_body():
        try:
            data = request.get_json(force=True)
        except Exception:
            return None, json_resp({"ok": False, "msg": "Invalid JSON", "error": "invalid_json"}), 400
        if not isinstance(data, dict):
            return None, json_resp({"ok": False, "msg": "Invalid request", "error": "invalid_request"}), 400
        return data, None, None

    def _actor_or_401():
        actor = get_current_user_ctx()
        if not actor:
            return None, json_resp({"ok": False, "msg": "請先登入", "error": "login_required"}), 401
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
            }
            return data, request.files.get("cover"), None, None
        data, err, status = _parse_json_body()
        return data, None, err, status

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
        response.headers.set("Content-Disposition", "inline", filename=download_name)
        return response

    @app.route("/api/videos/publish", methods=["POST"])
    @require_csrf
    def video_publish():
        actor, err = _actor_or_401()
        if err:
            return err
        data, cover_upload, err, status = _parse_publish_request()
        if err:
            return err, status
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
        privacy_mode = str(request.form.get("privacy_mode") or "standard_plain").strip() or "standard_plain"
        if privacy_mode == "e2ee":
            return json_resp({"ok": False, "msg": "影音串流不支援 E2EE 檔案，請改用一般檔案或伺服器端加密", "error": "e2ee_not_streamable"}), 400
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
                "cover_file": ({**cover_result, "filename": safe_public_filename(cover_upload.filename)} if cover_result else None),
                "cover_storage_file": cover_storage_file,
            })
        except Exception as exc:
            conn.rollback()
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
            )
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
            if is_server_encrypted_file(row):
                raw = decrypt_server_encrypted_bytes(path, server_file_fernet)
                return _send_bytes_with_range(raw, download_name=filename, mimetype=mimetype, range_header=request.headers.get("Range"))
            return send_file(path, as_attachment=False, download_name=filename, mimetype=mimetype, conditional=True)
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
