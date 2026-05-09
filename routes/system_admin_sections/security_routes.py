import json
import os
import platform
import re
import sys
import uuid

from flask import request


def register_system_admin_security_routes(app, ctx):
    BASE_DIR = ctx["BASE_DIR"]
    CHAT_DIR = ctx["CHAT_DIR"]
    DB_PATH = ctx["DB_PATH"]
    LOG_DIR = ctx["LOG_DIR"]
    ANCHOR_DIR = ctx["ANCHOR_DIR"]
    SERVER_LOG_PATH = ctx["SERVER_LOG_PATH"]
    STORAGE_DIR = ctx["STORAGE_DIR"]
    CURRENT_SCHEMA_VERSION = ctx["CURRENT_SCHEMA_VERSION"]
    CONFIRM_APPROVE = ctx["CONFIRM_APPROVE"]
    SECURITY_TEST_JOBS = ctx["SECURITY_TEST_JOBS"]
    SECURITY_TEST_JOBS_LOCK = ctx["SECURITY_TEST_JOBS_LOCK"]
    SECURITY_SETTING_KEYS = ctx["SECURITY_SETTING_KEYS"]
    SECURITY_THRESHOLD_KEYS = ctx["SECURITY_THRESHOLD_KEYS"]
    SERVER_UPDATE_WARNING = ctx["SERVER_UPDATE_WARNING"]
    GIT_REPO_DIR = ctx["GIT_REPO_DIR"]

    audit = ctx["audit"]
    get_client_ip = ctx["get_client_ip"]
    get_current_user_ctx = ctx["get_current_user_ctx"]
    get_db = ctx["get_db"]
    get_feature_settings = ctx["get_feature_settings"]
    get_server_output = ctx["get_server_output"]
    get_system_settings = ctx["get_system_settings"]
    get_ua = ctx["get_ua"]
    is_audit_chain_enabled = ctx["is_audit_chain_enabled"]
    json_resp = ctx["json_resp"]
    save_settings = ctx["save_settings"]
    server_mode_service = ctx["server_mode_service"]
    snapshot_service = ctx["snapshot_service"]
    integrity_guard = ctx["integrity_guard"]
    verify_audit_integrity = ctx["verify_audit_integrity"]

    require_csrf = ctx["require_csrf"]
    require_csrf_safe = ctx["require_csrf_safe"]
    require_root_actor = ctx["require_root_actor"]
    require_super_admin_actor = ctx["require_super_admin_actor"]

    dir_stats = ctx["dir_stats"]
    health_counts = ctx["health_counts"]
    db_integrity_summary = ctx["db_integrity_summary"]
    readiness_summary = ctx["readiness_summary"]
    anomaly_summary = ctx["anomaly_summary"]
    audit_integrity_summary = ctx["audit_integrity_summary"]
    security_center_payload = ctx["security_center_payload"]
    security_profile_payload = ctx["security_profile_payload"]
    public_relative_path = ctx["public_relative_path"]
    current_git_state = ctx["current_git_state"]
    git_short_text = ctx["git_short_text"]
    git_update_preview = ctx["git_update_preview"]
    rebuild_integrity_baseline_after_update = ctx["rebuild_integrity_baseline_after_update"]
    prepare_server_update_recovery_points = ctx["prepare_server_update_recovery_points"]
    run_git_command = ctx["run_git_command"]
    read_update_summary = ctx["read_update_summary"]
    schedule_server_restart = ctx["schedule_server_restart"]
    audit_settings_changed = ctx["audit_settings_changed"]
    notify_root = ctx["notify_root"]
    safe_security_test_int = ctx["safe_security_test_int"]
    security_test_job_payload = ctx["security_test_job_payload"]
    security_test_report_root = ctx["security_test_report_root"]
    start_security_test_job = ctx["start_security_test_job"]
    validate_git_branch_name = ctx["validate_git_branch_name"]
    repair_audit_chain = ctx["repair_audit_chain"]
    repair_violation_chains = ctx["repair_violation_chains"]
    audit_storage_capacity = ctx["audit_storage_capacity"]

    @app.route("/api/admin/health", methods=["GET"])
    @require_csrf_safe
    def admin_health():
        actor = get_current_user_ctx()
        if not actor:
            return json_resp({"ok":False,"msg":"未登入"}), 401
        actor_role = "super_admin" if actor["username"] == "root" else actor["role"]
        if ctx["role_rank"](actor_role) < ctx["role_rank"]("super_admin"):
            return json_resp({"ok":False,"msg":"只有最高管理者可查看伺服器健康度"}), 403

        settings = get_system_settings()
        audit_enabled = is_audit_chain_enabled()
        if audit_enabled:
            audit_ok, audit_broken, audit_details = verify_audit_integrity()
        else:
            audit_ok, audit_broken, audit_details = None, None, "audit chain disabled"

        counts, count_errors = health_counts()
        counts["pending_reports"] = counts.get("pending_chat_reports", 0)

        db_size = os.path.getsize(DB_PATH) if os.path.exists(DB_PATH) else 0
        chat_stats = dir_stats(CHAT_DIR, ".jsonl")
        log_stats = dir_stats(LOG_DIR)
        anchor_stats = dir_stats(ANCHOR_DIR)
        storage_stats = dir_stats(STORAGE_DIR)
        capacity_conn = get_db()
        try:
            storage_capacity = audit_storage_capacity(capacity_conn, STORAGE_DIR)
        finally:
            capacity_conn.close()
        readiness = readiness_summary()
        anomaly = anomaly_summary()
        status = "critical" if ((audit_enabled and audit_ok is False) or settings.get("maintenance_mode", False) or readiness["status"] == "critical") else "ok"
        if storage_capacity["status"] == "critical":
            status = "critical"
        if status == "ok" and (readiness["status"] == "degraded" or anomaly["status"] in {"warning", "critical"} or count_errors):
            status = "degraded"
        if status == "ok" and storage_capacity["status"] == "warning":
            status = "degraded"
        return json_resp({
            "ok": True,
            "status": status,
            "maintenance_mode": settings.get("maintenance_mode", False),
            "audit_integrity": {
                "enabled": audit_enabled,
                "ok": audit_ok,
                "broken_at": audit_broken,
                "details": audit_details,
                "operator_action_required": audit_ok is False,
                "auto_lockdown_applied": False,
            },
            "counts": counts,
            "count_errors": count_errors,
            "storage": {
                "database_bytes": db_size,
                "chat_files": chat_stats["files"],
                "chat_bytes": chat_stats["bytes"],
                "chat_dir": public_relative_path(CHAT_DIR, BASE_DIR),
                "log_files": log_stats["files"],
                "log_bytes": log_stats["bytes"],
                "anchor_files": anchor_stats["files"],
                "anchor_bytes": anchor_stats["bytes"],
                "storage_files": storage_stats["files"],
                "storage_bytes": storage_stats["bytes"],
                "capacity_audit": storage_capacity,
            },
            "readiness": readiness,
            "anomaly": anomaly,
        })

    @app.route("/api/admin/environment", methods=["GET"])
    @require_csrf_safe
    def admin_environment():
        actor = get_current_user_ctx()
        if not actor:
            return json_resp({"ok":False,"msg":"未登入"}), 401
        if actor["username"] != "root":
            return json_resp({"ok":False,"msg":"只有 root 可查看系統環境"}), 403

        db_size = os.path.getsize(DB_PATH) if os.path.exists(DB_PATH) else 0
        log_files = [name for name in os.listdir(LOG_DIR) if os.path.isfile(os.path.join(LOG_DIR, name))] if os.path.isdir(LOG_DIR) else []
        chat_files = [name for name in os.listdir(CHAT_DIR) if os.path.isfile(os.path.join(CHAT_DIR, name))] if os.path.isdir(CHAT_DIR) else []
        anchor_files = [name for name in os.listdir(ANCHOR_DIR) if os.path.isfile(os.path.join(ANCHOR_DIR, name))] if os.path.isdir(ANCHOR_DIR) else []
        return json_resp({
            "ok": True,
            "environment": {
                "platform": platform.platform(),
                "python_version": sys.version.split()[0],
                "pid": os.getpid(),
                "base_dir": ".",
                "database_path": public_relative_path(DB_PATH, BASE_DIR),
                "log_dir": public_relative_path(LOG_DIR, BASE_DIR),
                "chat_dir": public_relative_path(CHAT_DIR, BASE_DIR),
                "anchor_dir": public_relative_path(ANCHOR_DIR, BASE_DIR),
                "database_bytes": db_size,
                "log_files": len(log_files),
                "chat_files": len(chat_files),
                "anchor_files": len(anchor_files),
            }
        })

    @app.route("/api/admin/health/readiness", methods=["GET"])
    @require_csrf_safe
    def admin_health_readiness():
        _, error = require_super_admin_actor()
        if error:
            return error
        summary = readiness_summary()
        return json_resp({"ok": True, "readiness": summary})

    @app.route("/api/admin/health/anomaly", methods=["GET"])
    @require_csrf_safe
    def admin_health_anomaly():
        _, error = require_super_admin_actor()
        if error:
            return error
        return json_resp({"ok": True, "anomaly": anomaly_summary()})

    @app.route("/api/admin/health/audit-chain", methods=["GET"])
    @require_csrf_safe
    def admin_health_audit_chain():
        _, error = require_super_admin_actor()
        if error:
            return error
        return json_resp({"ok": True, "audit_integrity": audit_integrity_summary()})

    @app.route("/api/admin/health/db-integrity", methods=["GET"])
    @require_csrf_safe
    def admin_health_db_integrity():
        _, error = require_super_admin_actor()
        if error:
            return error
        return json_resp({"ok": True, "database": db_integrity_summary()})

    @app.route("/api/admin/security-center", methods=["GET"])
    @require_csrf_safe
    def admin_security_center():
        _, error = require_root_actor()
        if error:
            return error
        return json_resp({"ok": True, "security_center": security_center_payload()})

    @app.route("/api/admin/server-output", methods=["GET"])
    @require_csrf_safe
    def admin_server_output():
        _, error = require_root_actor()
        if error:
            return error
        limit = request.args.get("limit", 200)
        try:
            limit_int = max(1, int(limit))
        except (TypeError, ValueError):
            limit_int = 200
        result = get_server_output(limit=limit_int) or {"lines": [], "max_lines": 0}
        # When the in-process runtime buffer is empty (e.g. immediately after
        # gunicorn boot, or after a runtime reset) fall back to tailing the
        # gunicorn_error.log on disk so the operator can still see what
        # happened during boot.
        lines = result.get("lines") or []
        if not lines:
            log_path = os.path.join(LOG_DIR, "gunicorn_error.log")
            if os.path.isfile(log_path):
                try:
                    with open(log_path, "r", encoding="utf-8", errors="replace") as fh:
                        tail = fh.readlines()[-limit_int:]
                    parsed_lines = []
                    for raw in tail:
                        text = raw.rstrip("\n")
                        # gunicorn format: "[ts] [pid] [LEVEL] message"
                        stream = "info"
                        m = re.search(r"\[(DEBUG|INFO|WARNING|ERROR|CRITICAL)\]", text)
                        if m:
                            stream = m.group(1).lower()
                        elif " ERROR " in text or " Traceback" in text:
                            stream = "error"
                        parsed_lines.append({"stream": stream, "line": text})
                    result = {
                        "lines": parsed_lines,
                        "max_lines": result.get("max_lines") or 0,
                        "source": "gunicorn_error.log",
                    }
                except OSError:
                    pass
        return json_resp({"ok": True, "server_output": result})

    @app.route("/api/root/security-tests", methods=["GET"])
    @require_csrf_safe
    def root_security_tests():
        _, error = require_root_actor()
        if error:
            return error
        with SECURITY_TEST_JOBS_LOCK:
            jobs = [security_test_job_payload(job) for job in SECURITY_TEST_JOBS.values()]
        jobs.sort(key=lambda item: item.get("started_at") or "", reverse=True)
        return json_resp({"ok": True, "jobs": jobs[:20], "report_root": os.path.relpath(security_test_report_root(), BASE_DIR)})

    @app.route("/api/root/security-tests/<job_id>", methods=["GET"])
    @require_csrf_safe
    def root_security_test_detail(job_id):
        _, error = require_root_actor()
        if error:
            return error
        with SECURITY_TEST_JOBS_LOCK:
            job = SECURITY_TEST_JOBS.get(job_id)
            payload = security_test_job_payload(job) if job else None
        if not payload:
            return json_resp({"ok": False, "msg": "找不到測試任務"}), 404
        return json_resp({"ok": True, "job": payload})

    @app.route("/api/root/security-tests/pentest", methods=["POST"])
    @require_csrf
    def root_security_test_pentest():
        actor, error = require_root_actor()
        if error:
            return error
        try:
            data = request.get_json(force=True) if request.is_json else {}
        except Exception:
            return json_resp({"ok": False, "msg": "請求 JSON 格式錯誤"}), 400
        if not isinstance(data, dict):
            return json_resp({"ok": False, "msg": "請求內容格式錯誤"}), 400
        target = str(data.get("target") or request.host_url or "").strip().rstrip("/")
        if not re.fullmatch(r"https?://[A-Za-z0-9.\-_\[\]:]+(?::\d+)?(?:/.*)?", target):
            return json_resp({"ok": False, "msg": "target 必須是 http(s) URL"}), 400
        tool_timeout = safe_security_test_int(data.get("tool_timeout_seconds"), 180, 1, 3600)
        if tool_timeout is None:
            return json_resp({"ok": False, "msg": "tool_timeout_seconds 必須介於 1-3600"}), 400
        report_root = security_test_report_root()
        command = [
            os.path.join(BASE_DIR, "security", "run_pentest.sh"),
            "--target", target,
            "--out", report_root,
            "--tool-timeout", str(tool_timeout),
        ]
        only = str(data.get("only") or "").strip()
        skip = str(data.get("skip") or "").strip()
        # Default to a quick-scan set so the root operator can fire the
        # endpoint with just `{target}` and still get a useful smoke run
        # instead of accidentally launching the full pentest matrix.
        if not only:
            only = "curl-baseline,functional-permissions,session-security,header-security"
        command.extend(["--only", only])
        if skip:
            command.extend(["--skip", skip])
        if bool(data.get("i_own_this_target")):
            command.append("--i-own-this-target")
        env = {}
        for key in ("ROOT_PASSWORD", "MANAGER_PASSWORD", "TEST_PASSWORD"):
            value = str(data.get(key.lower()) or "").strip()
            if not value:
                value = str(os.environ.get(f"HTML_LEARNING_{key}") or "").strip()
            if value:
                env[key] = value
        # Defaults match the seed users created by test_for_develop.sh /
        # the bootstrap routine so a fresh dev site can run the privilege
        # scan without forcing every operator to pass usernames in JSON.
        username_defaults = {
            "root_username": "root",
            "manager_username": "admin",
            "user_username": "test",
        }
        username_env_keys = {
            "root_username": "PENTEST_ROOT_USERNAME",
            "manager_username": "PENTEST_MANAGER_USERNAME",
            "user_username": "PENTEST_USER_USERNAME",
        }
        for payload_key, env_key in username_env_keys.items():
            value = str(data.get(payload_key) or "").strip()
            if not value:
                value = username_defaults[payload_key]
            env[env_key] = value
        job = start_security_test_job(
            "pentest",
            command,
            command_label=["security/run_pentest.sh", "--target", target],
            report_root=report_root,
            report_prefix="20",
            actor=actor,
            env=env,
        )
        return json_resp({"ok": True, "msg": "滲透測試已啟動", "job": security_test_job_payload(job)}, 202)

    @app.route("/api/root/security-tests/functional", methods=["POST"])
    @require_csrf
    def root_security_test_functional():
        actor, error = require_root_actor()
        if error:
            return error
        try:
            data = request.get_json(force=True) if request.is_json else {}
        except Exception:
            return json_resp({"ok": False, "msg": "請求 JSON 格式錯誤"}), 400
        if not isinstance(data, dict):
            return json_resp({"ok": False, "msg": "請求內容格式錯誤"}), 400
        port = safe_security_test_int(data.get("port"), 50741, 1, 65535)
        if port is None:
            return json_resp({"ok": False, "msg": "port 必須介於 1-65535"}), 400
        report_root = security_test_report_root()
        command = [
            os.path.join(BASE_DIR, "security", "run_functional_smoke.sh"),
            "--port", str(port),
            "--out", report_root,
        ]
        if bool(data.get("keep_runtime")):
            command.append("--keep-runtime")
        env = {}
        for key in ("ROOT_PASSWORD", "ROOT_CHANGED_PASSWORD", "MANAGER_PASSWORD", "TEST_PASSWORD"):
            value = str(data.get(key.lower()) or "").strip()
            if not value:
                value = str(os.environ.get(f"HTML_LEARNING_{key}") or "").strip()
            if value:
                env[key] = value
        job = start_security_test_job(
            "functional",
            command,
            command_label=["security/run_functional_smoke.sh", "--port", str(port)],
            report_root=report_root,
            report_prefix="functional_",
            actor=actor,
            env=env,
        )
        return json_resp({"ok": True, "msg": "全功能測試已啟動", "job": security_test_job_payload(job)}, 202)

    @app.route("/api/root/security-tests/privilege", methods=["POST"])
    @require_csrf
    def root_security_test_privilege():
        actor, error = require_root_actor()
        if error:
            return error
        try:
            data = request.get_json(force=True) if request.is_json else {}
        except Exception:
            return json_resp({"ok": False, "msg": "請求 JSON 格式錯誤"}), 400
        if not isinstance(data, dict):
            return json_resp({"ok": False, "msg": "請求內容格式錯誤"}), 400
        target = str(data.get("target") or request.host_url or "").strip().rstrip("/")
        if not re.fullmatch(r"https?://[A-Za-z0-9.\-_\[\]:]+(?::\d+)?(?:/.*)?", target):
            return json_resp({"ok": False, "msg": "target 必須是 http(s) URL"}), 400
        report_root = security_test_report_root()
        artifact_prefix = f"privilege_{uuid.uuid4().hex[:10]}"
        out_json = os.path.join(report_root, f"{artifact_prefix}.json")
        out_md = os.path.join(report_root, f"{artifact_prefix}.md")
        command = [
            sys.executable,
            os.path.join(BASE_DIR, "security", "functional_permission_pentest.py"),
            "--base-url", target,
            "--out-json", out_json,
            "--out-md", out_md,
        ]
        if bool(data.get("destructive")):
            command.append("--destructive")
        env = {}
        for key in ("ROOT_PASSWORD", "MANAGER_PASSWORD", "TEST_PASSWORD"):
            value = str(data.get(key.lower()) or "").strip()
            if not value:
                value = str(os.environ.get(f"HTML_LEARNING_{key}") or "").strip()
            if value:
                env[key] = value
        # Defaults match the seed users created by test_for_develop.sh /
        # the bootstrap routine so a fresh dev site can run the privilege
        # scan without forcing every operator to pass usernames in JSON.
        username_defaults = {
            "root_username": "root",
            "manager_username": "admin",
            "user_username": "test",
        }
        username_env_keys = {
            "root_username": "PENTEST_ROOT_USERNAME",
            "manager_username": "PENTEST_MANAGER_USERNAME",
            "user_username": "PENTEST_USER_USERNAME",
        }
        for payload_key, env_key in username_env_keys.items():
            value = str(data.get(payload_key) or "").strip()
            if not value:
                value = username_defaults[payload_key]
            env[env_key] = value
        job = start_security_test_job(
            "privilege",
            command,
            command_label=[
                "python3",
                "security/functional_permission_pentest.py",
                "--base-url",
                target,
            ] + (["--destructive"] if bool(data.get("destructive")) else []),
            report_root=report_root,
            report_prefix=artifact_prefix,
            actor=actor,
            env=env,
        )
        return json_resp({"ok": True, "msg": "越權測試已啟動", "job": security_test_job_payload(job)}, 202)

    @app.route("/api/root/security-tests/stress", methods=["POST"])
    @require_csrf
    def root_security_test_stress():
        actor, error = require_root_actor()
        if error:
            return error
        try:
            data = request.get_json(force=True) if request.is_json else {}
        except Exception:
            return json_resp({"ok": False, "msg": "請求 JSON 格式錯誤"}), 400
        if not isinstance(data, dict):
            return json_resp({"ok": False, "msg": "請求內容格式錯誤"}), 400
        target = str(data.get("target") or request.host_url or "").strip().rstrip("/")
        if not re.fullmatch(r"https?://[A-Za-z0-9.\-_\[\]:]+(?::\d+)?(?:/.*)?", target):
            return json_resp({"ok": False, "msg": "target 必須是 http(s) URL"}), 400
        total_requests = safe_security_test_int(data.get("requests"), 200, 1, 5000)
        duration_seconds = safe_security_test_int(data.get("duration_seconds"), 30, 1, 600)
        max_requests = safe_security_test_int(data.get("max_requests"), 5000, 1, 20000)
        concurrency = safe_security_test_int(data.get("concurrency"), 20, 1, 100)
        burst_size = safe_security_test_int(data.get("burst_size"), 1, 1, 500)
        burst_interval_ms = safe_security_test_int(data.get("burst_interval_ms"), 0, 0, 60000)
        timeout_seconds = safe_security_test_int(data.get("timeout_seconds"), 8, 1, 120)
        mode = str(data.get("mode") or "count").strip().lower()
        if total_requests is None:
            return json_resp({"ok": False, "msg": "requests 必須介於 1-5000"}), 400
        if duration_seconds is None:
            return json_resp({"ok": False, "msg": "duration_seconds 必須介於 1-600"}), 400
        if max_requests is None:
            return json_resp({"ok": False, "msg": "max_requests 必須介於 1-20000"}), 400
        if concurrency is None:
            return json_resp({"ok": False, "msg": "concurrency 必須介於 1-100"}), 400
        if burst_size is None:
            return json_resp({"ok": False, "msg": "burst_size 必須介於 1-500"}), 400
        if burst_interval_ms is None:
            return json_resp({"ok": False, "msg": "burst_interval_ms 必須介於 0-60000"}), 400
        if timeout_seconds is None:
            return json_resp({"ok": False, "msg": "timeout_seconds 必須介於 1-120"}), 400
        if mode not in {"count", "duration"}:
            return json_resp({"ok": False, "msg": "mode 必須是 count 或 duration"}), 400
        paths = str(data.get("paths") or "").strip()
        report_root = security_test_report_root()
        command = [
            sys.executable,
            os.path.join(BASE_DIR, "security", "stress_test.py"),
            "--target", target,
            "--mode", mode,
            "--concurrency", str(concurrency),
            "--timeout", str(timeout_seconds),
            "--burst-size", str(burst_size),
            "--burst-interval-ms", str(burst_interval_ms),
            "--out", report_root,
        ]
        if mode == "duration":
            command.extend(["--duration-seconds", str(duration_seconds), "--max-requests", str(max_requests)])
        else:
            command.extend(["--requests", str(total_requests)])
        if paths:
            command.extend(["--paths", paths])
        job = start_security_test_job(
            "stress",
            command,
            command_label=[
                "python3",
                "security/stress_test.py",
                "--target",
                target,
                "--mode",
                mode,
                "--concurrency",
                str(concurrency),
            ],
            report_root=report_root,
            report_prefix="stress_",
            actor=actor,
        )
        return json_resp({"ok": True, "msg": "壓力測試已啟動", "job": security_test_job_payload(job)}, 202)

    @app.route("/api/admin/security-center/thresholds", methods=["PUT"])
    @require_csrf
    def admin_security_center_thresholds():
        actor, error = require_root_actor()
        if error:
            return error
        try:
            data = request.get_json(force=True)
        except Exception:
            return json_resp({"ok": False, "msg": "請求 JSON 格式錯誤"}), 400
        if not isinstance(data, dict):
            return json_resp({"ok": False, "msg": "請求內容格式錯誤"}), 400
        updates = {}
        for key in SECURITY_THRESHOLD_KEYS:
            if key not in data:
                continue
            try:
                value = int(data.get(key))
            except Exception:
                return json_resp({"ok": False, "msg": f"{key} 必須是整數"}), 400
            if value < 0 or value > 100000:
                return json_resp({"ok": False, "msg": f"{key} 必須介於 0-100000"}), 400
            updates[key] = value
        if not updates:
            return json_resp({"ok": False, "msg": "沒有可寫入的閾值"}), 400
        before_settings = get_system_settings()
        saved = save_settings(updates)
        audit_settings_changed("SECURITY_THRESHOLDS_CHANGED", actor, before_settings, saved, scope="security_thresholds")
        return json_resp({"ok": True, "msg": "安全閾值已更新", "thresholds": {key: get_system_settings().get(key) for key in SECURITY_THRESHOLD_KEYS}})

    @app.route("/api/admin/security-center/controls", methods=["PUT"])
    @require_csrf
    def admin_security_center_controls():
        actor, error = require_root_actor()
        if error:
            return error
        try:
            data = request.get_json(force=True)
        except Exception:
            return json_resp({"ok": False, "msg": "請求 JSON 格式錯誤"}), 400
        if not isinstance(data, dict):
            return json_resp({"ok": False, "msg": "請求內容格式錯誤"}), 400
        updates = {key: data[key] for key in SECURITY_SETTING_KEYS if key in data}
        if not updates:
            return json_resp({"ok": False, "msg": "沒有可寫入的安全機制開關"}), 400
        before_settings = get_system_settings()
        saved = save_settings(updates)
        audit_settings_changed("SECURITY_CONTROLS_CHANGED", actor, before_settings, saved, scope="security_controls")
        return json_resp({"ok": True, "msg": "安全機制設定已更新", "settings": {key: get_system_settings().get(key) for key in SECURITY_SETTING_KEYS}})

    @app.route("/api/root/server-update/status", methods=["GET"])
    @require_csrf_safe
    def root_server_update_status():
        actor, error = require_root_actor()
        if error:
            return error
        fetch = str(request.args.get("fetch") or "").lower() in {"1", "true", "yes"}
        state = current_git_state(fetch=fetch)
        return json_resp({"ok": bool(state.get("ok")), "update": state, "warning": SERVER_UPDATE_WARNING}), (200 if state.get("ok") else 500)

    @app.route("/api/root/server-update/preview", methods=["POST"])
    @require_csrf
    def root_server_update_preview():
        actor, error = require_root_actor()
        if error:
            return error
        try:
            data = request.get_json(force=True)
        except Exception:
            return json_resp({"ok": False, "msg": "請求 JSON 格式錯誤"}), 400
        branch = validate_git_branch_name((data or {}).get("branch"))
        if not branch:
            return json_resp({"ok": False, "msg": "請選擇合法的更新分支"}), 400
        preview = git_update_preview(branch, fetch=True)
        audit(
            "SERVER_UPDATE_PREVIEW",
            get_client_ip(),
            user=actor["username"],
            success=bool(preview.get("ok")),
            ua=get_ua(),
            detail=json.dumps({"branch": branch, "ok": bool(preview.get("ok")), "msg": preview.get("msg", "")}, ensure_ascii=False, sort_keys=True),
        )
        return json_resp({"ok": bool(preview.get("ok")), "preview": preview, "msg": preview.get("msg", "")}), (200 if preview.get("ok") else 400)

    @app.route("/api/root/server-update/apply", methods=["POST"])
    @require_csrf
    def root_server_update_apply():
        actor, error = require_root_actor()
        if error:
            return error
        try:
            data = request.get_json(force=True)
        except Exception:
            return json_resp({"ok": False, "msg": "請求 JSON 格式錯誤"}), 400
        branch = validate_git_branch_name((data or {}).get("branch"))
        confirm = str((data or {}).get("confirm") or "").strip()
        if not branch:
            return json_resp({"ok": False, "msg": "請選擇合法的更新分支"}), 400
        if confirm != "APPLY_UNVERIFIED_UPDATE":
            return json_resp({"ok": False, "msg": "請輸入 APPLY_UNVERIFIED_UPDATE 確認此次更新未經驗證"}), 400
        preview = git_update_preview(branch, fetch=True)
        if not preview.get("ok"):
            return json_resp({"ok": False, "msg": preview.get("msg") or "更新預覽失敗", "preview": preview}), 400
        state = preview.get("state") or {}
        stash_applied = False
        stash_result = None
        if state.get("dirty"):
            stash_result = run_git_command(
                ["stash", "push", "--include-untracked", "-m", "auto-stash before server update"],
                timeout=30,
            )
            if not stash_result["ok"]:
                return json_resp({
                    "ok": False,
                    "msg": "工作目錄有未提交變更，且自動暫存失敗，請先手動處理後再更新。",
                    "dirty_files": state.get("dirty_files") or [],
                    "stash_error": git_short_text(stash_result),
                    "preview": preview,
                }), 409
            stash_applied = True
        recovery_points = prepare_server_update_recovery_points(actor, branch)
        if not recovery_points.get("ok"):
            if stash_applied:
                restore = run_git_command(["stash", "pop"], timeout=30)
                if not restore.get("ok"):
                    run_git_command(["stash", "drop"], timeout=15)
            audit(
                "SERVER_UPDATE_PREPARE_FAILED",
                get_client_ip(),
                user=actor["username"],
                success=False,
                ua=get_ua(),
                detail=json.dumps({"branch": branch, "msg": recovery_points.get("msg"), "recovery": recovery_points}, ensure_ascii=False, sort_keys=True),
            )
            return json_resp({
                "ok": False,
                "msg": recovery_points.get("msg") or "更新前保護點建立失敗，已中止更新",
                "preview": preview,
                "recovery": recovery_points,
            }), 500
        before_commit = state.get("current_commit") or ""
        merge_result = run_git_command(["merge", "--ff-only", f"origin/{branch}"], timeout=120)
        stash_pop_result = None
        if stash_applied:
            stash_pop_result = run_git_command(["stash", "pop"], timeout=30)
            if not stash_pop_result.get("ok"):
                run_git_command(["stash", "drop"], timeout=15)
        after_state = current_git_state(fetch=False)
        integrity_result = None
        restart_result = None
        if merge_result["ok"]:
            integrity_result = rebuild_integrity_baseline_after_update(actor, branch, preview)
            restart_result = schedule_server_restart(reason=f"server update from origin/{branch}", delay_seconds=1.25)
            notify_root(
                "server_update_unverified",
                "伺服器已套用未驗證更新",
                f"已從 origin/{branch} 套用更新，更新前已建立 snapshot 與 PointsChain backup，Integrity Guard baseline 已依本次更新檔案重建，系統將自動重啟。此更新尚未經本機測試驗證，請執行 smoke test、權限測試並確認沒有其他 pending findings。",
                link="/server",
            )
        detail = {
            "branch": branch,
            "before_commit": before_commit,
            "after_commit": (after_state or {}).get("current_commit"),
            "success": bool(merge_result["ok"]),
            "merge_output": git_short_text(merge_result, limit=4000),
            "stash_applied": stash_applied,
            "stash_pop_ok": bool(stash_pop_result.get("ok")) if stash_pop_result else None,
            "recovery": recovery_points,
            "restart": restart_result,
            "warning": SERVER_UPDATE_WARNING,
        }
        audit(
            "SERVER_UPDATE_APPLIED",
            get_client_ip(),
            user=actor["username"],
            success=bool(merge_result["ok"]),
            ua=get_ua(),
            detail=json.dumps(detail, ensure_ascii=False, sort_keys=True),
        )
        if not merge_result["ok"]:
            return json_resp({
                "ok": False,
                "msg": "Git 更新套用失敗。通常是目標分支無法 fast-forward，請改用乾淨部署或手動合併。",
                "preview": preview,
                "merge": merge_result,
                "recovery": recovery_points,
                "warning": SERVER_UPDATE_WARNING,
            }), 409
        return json_resp({
            "ok": True,
            "msg": "伺服器更新已套用；已建立更新前 snapshot 與 PointsChain 備份，伺服器將自動重啟。重啟後請自行執行測試與 debug。",
            "preview": preview,
            "merge": merge_result,
            "state": after_state,
            "integrity": integrity_result,
            "recovery": recovery_points,
            "restart": restart_result,
            "release_summary": read_update_summary(),
            "warning": SERVER_UPDATE_WARNING,
            "restart_required": True,
        })

    @app.route("/api/admin/security-center/profiles", methods=["GET", "POST"])
    @require_csrf_safe
    def admin_security_profiles():
        if not server_mode_service:
            return json_resp({"ok": False, "msg": "Server Mode 服務目前無法使用"}), 503
        if request.method == "GET":
            _, error = require_super_admin_actor()
            if error:
                return error
            return json_resp({"ok": True, "profiles": server_mode_service.list_profiles()})
        actor, error = require_root_actor()
        if error:
            return error
        try:
            data = request.get_json(force=True)
        except Exception:
            return json_resp({"ok": False, "msg": "請求 JSON 格式錯誤"}), 400
        if not isinstance(data, dict):
            return json_resp({"ok": False, "msg": "請求內容格式錯誤"}), 400
        profile_payload, err = security_profile_payload(data)
        if err:
            return json_resp({"ok": False, "msg": err}), 400
        result = server_mode_service.save_profile(
            name=data.get("name"),
            label=data.get("label"),
            description=data.get("description") or "",
            settings=profile_payload["settings"],
            thresholds=profile_payload["thresholds"],
            actor=actor,
        )
        if result.get("ok"):
            audit("SECURITY_PROFILE_SAVED", get_client_ip(), user=actor["username"], success=True, detail=f"profile={result['profile']['name']}")
        return json_resp(result), (200 if result.get("ok") else 400)

    @app.route("/api/root/integrity/status", methods=["GET"])
    @require_csrf_safe
    def root_integrity_status():
        actor, error = require_root_actor()
        if error:
            return error
        if not integrity_guard:
            return json_resp({"ok":False,"msg": "Integrity Guard 服務目前無法使用"}), 503
        return json_resp({"ok":True,"integrity":integrity_guard.status()})

    @app.route("/api/root/integrity/rescan", methods=["POST"])
    @require_csrf
    def root_integrity_rescan():
        actor, error = require_root_actor()
        if error:
            return error
        if not integrity_guard:
            return json_resp({"ok":False,"msg": "Integrity Guard 服務目前無法使用"}), 503
        result = integrity_guard.scan(actor=actor["username"], create_initial_manifest=True)
        audit("INTEGRITY_RESCAN", get_client_ip(), user=actor["username"], success=bool(result.get("ok")), detail=f"status={result.get('status') or result.get('last_scan', {}).get('status')}")
        return json_resp({"ok":bool(result.get("ok", True)),"integrity":result}), (200 if result.get("ok", True) else 500)

    @app.route("/api/root/integrity/findings", methods=["GET"])
    @require_csrf_safe
    def root_integrity_findings():
        actor, error = require_root_actor()
        if error:
            return error
        if not integrity_guard:
            return json_resp({"ok":False,"msg": "Integrity Guard 服務目前無法使用"}), 503
        status = request.args.get("status") or None
        return json_resp({"ok":True,"findings":integrity_guard.list_findings(status=status)})

    @app.route("/api/root/integrity/findings/<int:finding_id>", methods=["GET"])
    @require_csrf_safe
    def root_integrity_finding(finding_id):
        actor, error = require_root_actor()
        if error:
            return error
        if not integrity_guard:
            return json_resp({"ok":False,"msg": "Integrity Guard 服務目前無法使用"}), 503
        finding = integrity_guard.get_finding(finding_id)
        if not finding:
            return json_resp({"ok":False,"msg":"找不到 integrity finding"}), 404
        return json_resp({"ok":True,"finding":finding})

    def handle_integrity_review(finding_id, action):
        actor, error = require_root_actor()
        if error:
            return error
        if not integrity_guard:
            return json_resp({"ok":False,"msg": "Integrity Guard 服務目前無法使用"}), 503
        try:
            data = request.get_json(force=True) if request.is_json else {}
        except Exception:
            return json_resp({"ok":False,"msg": "請求 JSON 格式錯誤"}), 400
        if not isinstance(data, dict):
            return json_resp({"ok":False,"msg": "請求內容格式錯誤"}), 400
        result = integrity_guard.review_finding(
            finding_id,
            action=action,
            actor=actor,
            note=data.get("note") or "",
            confirm=data.get("confirm") or "",
        )
        return json_resp(result), (200 if result.get("ok") else 400)

    @app.route("/api/root/integrity/findings/bulk-review", methods=["POST"])
    @require_csrf
    def root_integrity_bulk_review():
        actor, error = require_root_actor()
        if error:
            return error
        if not integrity_guard:
            return json_resp({"ok":False,"msg": "Integrity Guard 服務目前無法使用"}), 503
        try:
            data = request.get_json(force=True)
        except Exception:
            return json_resp({"ok":False,"msg": "請求 JSON 格式錯誤"}), 400
        if not isinstance(data, dict):
            return json_resp({"ok":False,"msg": "請求內容格式錯誤"}), 400
        action = str(data.get("action") or "").strip().lower()
        if action not in {"approve", "reject", "ignore"}:
            return json_resp({"ok":False,"msg": "不支援的 integrity 操作"}), 400
        raw_ids = data.get("finding_ids") or data.get("ids") or []
        if not isinstance(raw_ids, list) or not raw_ids:
            return json_resp({"ok":False,"msg":"finding_ids 不可為空"}), 400
        try:
            finding_ids = [int(item) for item in raw_ids]
        except Exception:
            return json_resp({"ok":False,"msg":"finding_ids 格式錯誤"}), 400
        confirm = str(data.get("confirm") or "")
        if action == "approve" and confirm != CONFIRM_APPROVE:
            return json_resp({"ok":False,"msg": "確認字串不正確"}), 400
        note = str(data.get("note") or "")[:1000]
        results = []
        ok_count = 0
        for finding_id in finding_ids:
            result = integrity_guard.review_finding(
                finding_id,
                action=action,
                actor=actor,
                note=note,
                confirm=confirm,
            )
            result["finding_id"] = finding_id
            results.append(result)
            if result.get("ok"):
                ok_count += 1
        audit(
            f"INTEGRITY_FINDING_BULK_{action.upper()}",
            get_client_ip(),
            user=actor["username"],
            success=ok_count == len(finding_ids),
            ua=get_ua(),
            detail=f"ids={finding_ids}, ok={ok_count}/{len(finding_ids)}, note={note}",
        )
        return json_resp({"ok": ok_count == len(finding_ids), "action": action, "reviewed": ok_count, "total": len(finding_ids), "results": results}), (200 if ok_count == len(finding_ids) else 400)

    @app.route("/api/root/integrity/findings/<int:finding_id>/approve", methods=["POST"])
    @require_csrf
    def root_integrity_approve(finding_id):
        return handle_integrity_review(finding_id, "approve")

    @app.route("/api/root/integrity/findings/<int:finding_id>/reject", methods=["POST"])
    @require_csrf
    def root_integrity_reject(finding_id):
        return handle_integrity_review(finding_id, "reject")

    @app.route("/api/root/integrity/findings/<int:finding_id>/ignore", methods=["POST"])
    @require_csrf
    def root_integrity_ignore(finding_id):
        return handle_integrity_review(finding_id, "ignore")

    @app.route("/api/root/integrity/report", methods=["GET"])
    @require_csrf_safe
    def root_integrity_report():
        actor, error = require_root_actor()
        if error:
            return error
        if not integrity_guard:
            return json_resp({"ok":False,"msg": "Integrity Guard 服務目前無法使用"}), 503
        return json_resp({"ok":True,"report":integrity_guard.export_report(),"approve_confirm":CONFIRM_APPROVE})

    @app.route("/api/admin/integrity/repair", methods=["POST"])
    @require_csrf
    def admin_repair_integrity_chains():
        actor = get_current_user_ctx()
        if not actor:
            return json_resp({"ok":False,"msg":"未登入"}), 401
        if actor["username"] != "root":
            return json_resp({"ok":False,"msg":"只有 root 可處理鏈異常"}), 403

        audit_before = verify_audit_integrity() if is_audit_chain_enabled() else (None, None, "audit chain disabled")
        audit_result = repair_audit_chain(reason=f"manual_repair_by={actor['username']}")
        violation_result = repair_violation_chains()
        before_settings = get_system_settings()
        saved = save_settings({"maintenance_mode": False})
        audit_settings_changed("SETTINGS_CHANGED", actor, before_settings, saved, scope="integrity_repair")
        audit_after = verify_audit_integrity() if is_audit_chain_enabled() else (None, None, "audit chain disabled")

        audit(
            "INTEGRITY_CHAINS_RESEALED",
            get_client_ip(),
            user=actor["username"],
            success=True,
            detail=(
                f"audit_before={audit_before[2]}; audit_resealed={audit_result['entries_resealed']}; "
                f"violations_resealed={violation_result['entries_resealed']}; maintenance_mode=False"
            ),
        )
        return json_resp({
            "ok": True,
            "msg": "鏈異常已重新封鏈，維護模式已關閉",
            "audit": {
                "before": {"ok": audit_before[0], "broken_at": audit_before[1], "details": audit_before[2]},
                "after": {"ok": audit_after[0], "broken_at": audit_after[1], "details": audit_after[2]},
                **audit_result,
            },
            "violations": violation_result,
            "maintenance_mode": False,
        })
