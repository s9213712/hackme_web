from io import BytesIO

from flask import request, send_file

from services.cloud_drive import (
    decrypt_server_encrypted_bytes,
    is_server_encrypted_file,
    resolve_file_storage_path,
)
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
        if "insufficient balance" in message:
            return json_resp({"ok": False, "msg": "積分不足，無法投幣", "error": "insufficient_balance"}), 409
        return json_resp({"ok": False, "msg": message, "error": exc.__class__.__name__}), 400

    def _settings_float(key, default):
        try:
            return float((get_system_settings() or {}).get(key, default))
        except Exception:
            return float(default)

    @app.route("/api/videos/publish", methods=["POST"])
    @require_csrf
    def video_publish():
        actor, err = _actor_or_401()
        if err:
            return err
        data, err, status = _parse_json_body()
        if err:
            return err, status
        conn = get_db()
        try:
            video = publish_video(
                conn,
                actor=actor,
                cloud_file_id=data.get("cloud_file_id"),
                title=data.get("title"),
                description=data.get("description") or "",
                visibility=data.get("visibility") or "public",
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
            return json_resp({"ok": True, "video": video})
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
                return send_file(BytesIO(raw), as_attachment=False, download_name=filename, mimetype=mimetype, conditional=False)
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
