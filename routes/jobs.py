from flask import request

from services.job_center import (
    ensure_job_center_schema,
    get_job,
    list_job_events,
    list_jobs,
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

    def is_manager(actor):
        role = "super_admin" if actor_value(actor, "username") == "root" else actor_value(actor, "role", "user")
        return role_rank(role) >= role_rank("manager")

    def can_access_job(actor, job):
        if not job:
            return False
        if is_manager(actor):
            return True
        return int(job.get("owner_user_id") or -1) == int(actor_value(actor, "id", -2))

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
        if not is_manager(actor):
            return json_resp({"ok": False, "msg": "需要管理員權限"}), 403
        status = str(request.args.get("status") or "").strip() or None
        limit = parse_positive_int(request.args.get("limit"), default=80, min_value=1, max_value=200)
        conn = get_db()
        try:
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
            if not job.get("cancellable") and not is_manager(actor):
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
            if job.get("status") not in {"failed", "retry_wait", "expired", "cancelled"} and not is_manager(actor):
                return json_resp({"ok": False, "msg": "此任務目前不能重試"}), 400
            updated = request_retry(conn, job_uuid)
            conn.commit()
            audit("JOB_RETRY_REQUESTED", get_client_ip(), user=actor_value(actor, "username"), success=True, ua=get_ua(), detail=f"job_uuid={job_uuid}")
            return json_resp({"ok": True, "job": updated, "msg": "已排入重試"})
        finally:
            conn.close()
