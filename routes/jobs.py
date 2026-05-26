from flask import request

from services.job_center import (
    ensure_job_center_schema,
    dismiss_job,
    expire_stale_cloud_remote_download_jobs,
    expire_stale_resumable_upload_jobs,
    get_job,
    list_job_events,
    list_jobs,
    purge_terminal_jobs,
    request_cancel,
    request_retry,
)


def register_job_routes(app, deps):
    get_current_user_ctx = deps["get_current_user_ctx"]
    get_db = deps["get_db"]
    json_resp = deps["json_resp"]
    require_csrf = deps["require_csrf"]
    require_csrf_safe = deps["require_csrf_safe"]
    parse_positive_int = deps["parse_positive_int"]
    role_rank = deps.get("role_rank", lambda role: {"user": 0, "manager": 1, "super_admin": 2}.get(role or "user", 0))
    audit = deps.get("audit", lambda *args, **kwargs: None)
    get_client_ip = deps.get("get_client_ip", lambda: "")
    get_ua = deps.get("get_ua", lambda: "")

    def actor_value(actor, key, default=None):
        if not actor:
            return default
        try:
            return actor[key]
        except Exception:
            return actor.get(key, default) if hasattr(actor, "get") else default

    def actor_or_401():
        actor = get_current_user_ctx()
        if not actor:
            return None, json_resp({"ok": False, "msg": "未登入"}), 401
        return actor, None, None

    def is_root(actor):
        role = "super_admin" if actor_value(actor, "username") == "root" else actor_value(actor, "role", "user")
        return actor_value(actor, "username") == "root" or role_rank(role) >= role_rank("super_admin")

    def can_access_job(actor, job):
        if not job:
            return False
        if is_root(actor):
            return True
        return int(job.get("owner_user_id") or -1) == int(actor_value(actor, "id", -2))

    def job_retry_handler(source_module):
        handlers = app.extensions.get("hackme_job_retry_handlers") or {}
        handler = handlers.get(str(source_module or ""))
        return handler if callable(handler) else None

    @app.route("/api/jobs", methods=["GET"])
    @require_csrf_safe
    def jobs_list():
        actor, err, status_code = actor_or_401()
        if err:
            return err, status_code
        status = str(request.args.get("status") or "").strip() or None
        limit = parse_positive_int(request.args.get("limit"), default=50, min_value=1, max_value=200)
        conn = get_db()
        try:
            expire_stale_cloud_remote_download_jobs(conn)
            expire_stale_resumable_upload_jobs(conn)
            purge_terminal_jobs(conn)
            conn.commit()
            jobs = list_jobs(conn, user_id=actor["id"], include_all=False, status=status, limit=limit)
            return json_resp({"ok": True, "jobs": jobs})
        finally:
            conn.close()

    @app.route("/api/admin/jobs", methods=["GET"])
    @require_csrf_safe
    def admin_jobs_list():
        actor, err, status_code = actor_or_401()
        if err:
            return err, status_code
        if not is_root(actor):
            return json_resp({"ok": False, "msg": "只有 root 可查看全站任務"}), 403
        status = str(request.args.get("status") or "").strip() or None
        limit = parse_positive_int(request.args.get("limit"), default=80, min_value=1, max_value=200)
        conn = get_db()
        try:
            expire_stale_cloud_remote_download_jobs(conn)
            expire_stale_resumable_upload_jobs(conn)
            purge_terminal_jobs(conn)
            conn.commit()
            jobs = list_jobs(conn, include_all=True, status=status, limit=limit)
            return json_resp({"ok": True, "jobs": jobs})
        finally:
            conn.close()

    @app.route("/api/jobs/<job_uuid>", methods=["GET"])
    @require_csrf_safe
    def job_detail(job_uuid):
        actor, err, status_code = actor_or_401()
        if err:
            return err, status_code
        conn = get_db()
        try:
            job = get_job(conn, job_uuid)
            if not can_access_job(actor, job):
                return json_resp({"ok": False, "msg": "找不到任務"}), 404
            return json_resp({"ok": True, "job": job})
        finally:
            conn.close()

    @app.route("/api/jobs/<job_uuid>/events", methods=["GET"])
    @require_csrf_safe
    def job_events(job_uuid):
        actor, err, status_code = actor_or_401()
        if err:
            return err, status_code
        conn = get_db()
        try:
            job = get_job(conn, job_uuid)
            if not can_access_job(actor, job):
                return json_resp({"ok": False, "msg": "找不到任務"}), 404
            return json_resp({"ok": True, "events": list_job_events(conn, job_uuid)})
        finally:
            conn.close()

    @app.route("/api/jobs/<job_uuid>/cancel", methods=["POST"])
    @require_csrf
    def job_cancel(job_uuid):
        actor, err, status_code = actor_or_401()
        if err:
            return err, status_code
        conn = get_db()
        try:
            ensure_job_center_schema(conn)
            job = get_job(conn, job_uuid)
            if not can_access_job(actor, job):
                return json_resp({"ok": False, "msg": "找不到任務"}), 404
            if not job.get("cancellable") and not is_root(actor):
                return json_resp({"ok": False, "msg": "此任務不可取消"}), 400
            updated = request_cancel(conn, job_uuid)
            conn.commit()
            audit("JOB_CANCEL_REQUESTED", get_client_ip(), user=actor_value(actor, "username"), success=True, ua=get_ua(), detail=f"job_uuid={job_uuid}")
            return json_resp({"ok": True, "job": updated, "msg": "已取消任務"})
        finally:
            conn.close()

    @app.route("/api/jobs/<job_uuid>/retry", methods=["POST"])
    @require_csrf
    def job_retry(job_uuid):
        actor, err, status_code = actor_or_401()
        if err:
            return err, status_code
        conn = get_db()
        try:
            ensure_job_center_schema(conn)
            job = get_job(conn, job_uuid)
            if not can_access_job(actor, job):
                return json_resp({"ok": False, "msg": "找不到任務"}), 404
            if job.get("status") not in {"failed", "retry_wait", "expired", "cancelled"} and not is_root(actor):
                return json_resp({"ok": False, "msg": "此任務目前不能重試"}), 400
            handler = job_retry_handler(job.get("source_module"))
            updated = request_retry(conn, job_uuid)
            conn.commit()
            if handler:
                try:
                    payload = handler(conn=conn, actor=actor, job=updated) or {}
                    conn.commit()
                except Exception as exc:
                    conn.rollback()
                    message = str(exc) or exc.__class__.__name__
                    audit("JOB_RETRY_REQUESTED", get_client_ip(), user=actor_value(actor, "username"), success=False, ua=get_ua(), detail=f"job_uuid={job_uuid},error={message[:240]}")
                    return json_resp({"ok": False, "msg": f"任務重試失敗：{message}", "error": "job_retry_handler_failed"}), 400
                status_code = int(payload.pop("status_code", 200) or 200)
                audit("JOB_RETRY_REQUESTED", get_client_ip(), user=actor_value(actor, "username"), success=status_code < 400, ua=get_ua(), detail=f"job_uuid={job_uuid},source_module={job.get('source_module')}")
                return json_resp(payload, status_code)
            audit("JOB_RETRY_REQUESTED", get_client_ip(), user=actor_value(actor, "username"), success=True, ua=get_ua(), detail=f"job_uuid={job_uuid}")
            return json_resp({"ok": True, "job": updated, "msg": "已排入重試"})
        finally:
            conn.close()

    @app.route("/api/jobs/<job_uuid>", methods=["DELETE"])
    @require_csrf
    def job_dismiss(job_uuid):
        actor, err, status_code = actor_or_401()
        if err:
            return err, status_code
        conn = get_db()
        try:
            ensure_job_center_schema(conn)
            job = get_job(conn, job_uuid)
            if not can_access_job(actor, job):
                return json_resp({"ok": False, "msg": "找不到任務"}), 404
            if job.get("status") not in {"succeeded", "failed", "cancelled", "expired"}:
                return json_resp({"ok": False, "msg": "任務仍在進行中，請先取消或等待完成。"}), 409
            updated = dismiss_job(conn, job_uuid, actor_user_id=actor_value(actor, "id"))
            conn.commit()
            audit("JOB_DISMISSED", get_client_ip(), user=actor_value(actor, "username"), success=True, ua=get_ua(), detail=f"job_uuid={job_uuid}")
            return json_resp({"ok": True, "job": updated, "msg": "任務已從列表移除"})
        finally:
            conn.close()
