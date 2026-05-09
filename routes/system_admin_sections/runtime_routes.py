import os

from flask import request, send_file


def register_system_admin_runtime_routes(app, ctx):
    BASE_DIR = ctx["BASE_DIR"]
    require_csrf = ctx["require_csrf"]
    require_csrf_safe = ctx["require_csrf_safe"]
    json_resp = ctx["json_resp"]
    get_current_user_ctx = ctx["get_current_user_ctx"]
    get_client_ip = ctx["get_client_ip"]
    get_auth_db = ctx.get("get_auth_db", ctx["get_db"])
    get_db = ctx["get_db"]
    audit = ctx["audit"]
    require_root_actor = ctx["require_root_actor"]
    force_points_block = ctx["force_points_block"]
    server_mode_service = ctx["server_mode_service"]
    snapshot_service = ctx["snapshot_service"]
    schedule_server_restart = ctx["schedule_server_restart"]
    public_relative_path = ctx["public_relative_path"]
    points_service = ctx["points_service"]
    verify_audit_integrity = ctx["verify_audit_integrity"]
    is_audit_chain_enabled = ctx["is_audit_chain_enabled"]
    repair_audit_chain = ctx["repair_audit_chain"]
    repair_violation_chains = ctx["repair_violation_chains"]
    save_settings = ctx["save_settings"]
    get_system_settings = ctx["get_system_settings"]
    notify_root = ctx["notify_root"]
    role_rank = ctx["role_rank"]

    def _tester_token_from_request():
        header_value = request.headers.get("X-Tester-Token", "") or request.headers.get("Authorization", "")
        if header_value.lower().startswith("bearer "):
            header_value = header_value[7:]
        return str(header_value or "").strip()

    def _require_tester_actor():
        actor = get_current_user_ctx()
        if not actor:
            return None, (json_resp({"ok":False,"msg":"未登入或 tester token 無效"}), 401)
        if actor["username"] == "root":
            return None, (json_resp({"ok":False,"msg":"root 不使用 tester shadow layer"}), 403)
        return actor, None

    @app.route("/api/admin/snapshots", methods=["GET", "POST"])
    @require_csrf_safe
    def admin_snapshots():
        if not snapshot_service:
            return json_resp({"ok":False,"msg": "Snapshot 服務目前無法使用"}), 503
        actor, error = require_root_actor()
        if error:
            return error
        if request.method == "GET":
            return json_resp({"ok":True,"snapshots":snapshot_service.list_snapshots(actor=actor)})
        try:
            data = request.get_json(force=True) if request.is_json else {}
        except Exception:
            return json_resp({"ok":False,"msg": "請求 JSON 格式錯誤"}), 400
        if not isinstance(data, dict):
            return json_resp({"ok":False,"msg": "請求內容格式錯誤"}), 400
        snapshot_type = data.get("type") or "manual"
        if snapshot_type == "before_superweak" and actor["username"] != "root":
            return json_resp({"ok":False,"msg":"before_superweak snapshot 必須由 root 建立"}), 403
        result = snapshot_service.create_snapshot(snapshot_type=snapshot_type, actor=actor, notes=data.get("notes") or "")
        if not result.ok:
            return json_resp({"ok":False,"msg":"snapshot 建立失敗","error":result.error,"snapshot_id":result.snapshot_id}), 500
        block_result = force_points_block("snapshot_create", actor)
        payload = {"ok":True,"snapshot_id":result.snapshot_id,"status":result.status}
        if block_result:
            payload["points_block"] = block_result
        return json_resp(payload)

    @app.route("/api/admin/snapshots/daily", methods=["GET", "POST"])
    @require_csrf_safe
    def admin_daily_snapshots():
        if not snapshot_service:
            return json_resp({"ok":False,"msg": "Snapshot 服務目前無法使用"}), 503
        actor, error = require_root_actor()
        if error:
            return error
        settings = get_system_settings()
        if request.method == "GET":
            return json_resp({"ok":True,"daily":snapshot_service.daily_snapshot_status(settings=settings)})
        try:
            data = request.get_json(force=True) if request.is_json else {}
        except Exception:
            return json_resp({"ok":False,"msg": "請求 JSON 格式錯誤"}), 400
        if not isinstance(data, dict):
            return json_resp({"ok":False,"msg": "請求內容格式錯誤"}), 400
        if data.get("confirm") != "RUN_DAILY_SNAPSHOT":
            return json_resp({"ok":False,"msg":"confirm 必須等於 RUN_DAILY_SNAPSHOT"}), 400
        result = snapshot_service.create_daily_snapshot_if_due(
            actor=actor,
            settings=settings,
            save_settings=save_settings,
            force=bool(data.get("force")),
            notes=data.get("notes") or "",
        )
        if result.get("ok") and result.get("created"):
            result["points_block"] = force_points_block("daily_snapshot", actor)
        return json_resp(result), (200 if result.get("ok") else 500)

    @app.route("/api/admin/system-reset", methods=["POST"])
    @require_csrf
    def admin_system_reset():
        if not snapshot_service:
            return json_resp({"ok":False,"msg": "Snapshot 服務目前無法使用"}), 503
        actor, error = require_root_actor()
        if error:
            return error
        try:
            data = request.get_json(force=True)
        except Exception:
            return json_resp({"ok":False,"msg": "請求 JSON 格式錯誤"}), 400
        if not isinstance(data, dict):
            return json_resp({"ok":False,"msg": "請求內容格式錯誤"}), 400
        result = snapshot_service.reset_runtime_state(
            actor=actor,
            confirm=data.get("confirm"),
            reason=data.get("reason") or "",
        )
        if result.get("ok"):
            try:
                restart = schedule_server_restart(reason="system-reset", delay_seconds=1.25)
            except Exception as exc:
                result["restart_scheduled"] = False
                result["restart_error"] = str(exc)
                result["msg"] = "runtime state reset，但重啟排程失敗"
                return json_resp(result), 500
            result["restart_scheduled"] = True
            result["restart"] = restart
            result["msg"] = "runtime state reset，服務器正在重啟"
        return json_resp(result), (200 if result.get("ok") else 400)

    @app.route("/api/admin/snapshots/<snapshot_id>", methods=["GET", "DELETE"])
    @require_csrf_safe
    def admin_snapshot_detail(snapshot_id):
        if not snapshot_service:
            return json_resp({"ok":False,"msg": "Snapshot 服務目前無法使用"}), 503
        actor, error = require_root_actor()
        if error:
            return error
        try:
            if request.method == "GET":
                snapshot = snapshot_service.get_snapshot(snapshot_id=snapshot_id, actor=actor)
                if not snapshot:
                    return json_resp({"ok":False,"msg":"找不到 snapshot"}), 404
                return json_resp({"ok":True,"snapshot":snapshot})
            result = snapshot_service.delete_snapshot(snapshot_id=snapshot_id, actor=actor, reason=request.args.get("reason") or "root delete")
            return json_resp(result)
        except ValueError as exc:
            return json_resp({"ok":False,"msg":str(exc)}), 400

    @app.route("/api/admin/snapshots/<snapshot_id>/download", methods=["GET"])
    @require_csrf_safe
    def admin_snapshot_download(snapshot_id):
        if not snapshot_service:
            return json_resp({"ok":False,"msg": "Snapshot 服務目前無法使用"}), 503
        actor, error = require_root_actor()
        if error:
            return error
        try:
            result = snapshot_service.export_snapshot_archive(snapshot_id=snapshot_id, actor=actor)
        except ValueError as exc:
            return json_resp({"ok":False,"msg":str(exc)}), 400
        if not result.get("ok"):
            return json_resp(result), 400
        return send_file(
            result["path"],
            as_attachment=True,
            download_name=result["filename"],
            mimetype="application/gzip",
        )

    @app.route("/api/admin/snapshots/upload-restore", methods=["POST"])
    @require_csrf
    def admin_snapshot_upload_restore():
        if not snapshot_service:
            return json_resp({"ok":False,"msg": "Snapshot 服務目前無法使用"}), 503
        actor, error = require_root_actor()
        if error:
            return error
        if "file" not in request.files:
            return json_resp({"ok":False,"msg":"缺少 snapshot 檔案"}), 400
        dry_run = str(request.form.get("dry_run") or "").strip().lower() in {"1", "true", "yes", "on"}
        confirm = request.form.get("confirm") or ""
        if dry_run:
            if confirm != "DRY_RUN":
                return json_resp({"ok":False,"msg":"dry_run confirm 必須等於 DRY_RUN"}), 400
        elif confirm != "RESTORE":
            return json_resp({"ok":False,"msg":"confirm 必須等於 RESTORE"}), 400
        result = snapshot_service.restore_snapshot_archive(
            actor=actor,
            file_storage=request.files["file"],
            reason=request.form.get("reason") or "",
            dry_run=dry_run,
        )
        if result.get("ok") and not dry_run:
            result["points_block"] = force_points_block("snapshot_restore_upload", actor)
        return json_resp(result), (200 if result.get("ok") else 400)

    @app.route("/api/admin/snapshots/<snapshot_id>/restore", methods=["POST"])
    @require_csrf
    def admin_snapshot_restore(snapshot_id):
        if not snapshot_service:
            return json_resp({"ok":False,"msg": "Snapshot 服務目前無法使用"}), 503
        actor, error = require_root_actor()
        if error:
            return error
        try:
            data = request.get_json(force=True)
        except Exception:
            return json_resp({"ok":False,"msg": "請求 JSON 格式錯誤"}), 400
        if not isinstance(data, dict):
            return json_resp({"ok":False,"msg": "請求內容格式錯誤"}), 400
        dry_run = bool(data.get("dry_run"))
        confirm = data.get("confirm")
        if dry_run:
            if confirm != "DRY_RUN":
                return json_resp({"ok":False,"msg":"dry_run confirm 必須等於 DRY_RUN"}), 400
        elif confirm != "RESTORE":
            return json_resp({"ok":False,"msg":"confirm 必須等於 RESTORE"}), 400
        try:
            result = snapshot_service.restore_snapshot(
                snapshot_id=snapshot_id,
                actor=actor,
                reason=data.get("reason") or "",
                dry_run=dry_run,
            )
        except ValueError as exc:
            return json_resp({"ok":False,"msg":str(exc)}), 400
        if result.get("ok") and not dry_run:
            result["points_block"] = force_points_block("snapshot_restore", actor)
        return json_resp(result), (200 if result.get("ok") else 400)

    @app.route("/api/admin/server-mode", methods=["GET", "POST"])
    @require_csrf_safe
    def admin_server_mode():
        if not server_mode_service:
            return json_resp({"ok":False,"msg": "Server Mode 服務目前無法使用"}), 503
        actor, error = require_root_actor()
        if error:
            return error
        if request.method == "GET":
            return json_resp({"ok":True,"mode":server_mode_service.get_current_mode(),"profiles":server_mode_service.list_profiles()})
        try:
            data = request.get_json(force=True)
        except Exception:
            return json_resp({"ok":False,"msg": "請求 JSON 格式錯誤"}), 400
        if not isinstance(data, dict):
            return json_resp({"ok":False,"msg": "請求內容格式錯誤"}), 400
        result = server_mode_service.switch_mode(
            target_mode=data.get("mode"),
            actor=actor,
            confirm=data.get("confirm"),
            notes=data.get("notes") or "",
        )
        if result.get("ok"):
            result["points_block"] = force_points_block("server_mode_change", actor)
            mode = (result.get("mode") or {}).get("current_mode") or data.get("mode") or "-"
            notify_root(
                "root_server_mode_changed",
                "伺服器模式已變更",
                f"{actor['username']} 已將伺服器模式切換為 {mode}。",
                link="/security",
            )
        return json_resp(result), (200 if result.get("ok") else 400)

    @app.route("/api/root/server-mode", methods=["GET"])
    @require_csrf_safe
    def root_server_mode_status():
        if not server_mode_service:
            return json_resp({"ok":False,"msg": "Server Mode 服務目前無法使用"}), 503
        actor, error = require_root_actor()
        if error:
            return error
        payload = {
            "ok": True,
            "mode": server_mode_service.get_current_mode(),
            "profiles": server_mode_service.list_profiles(),
        }
        if hasattr(server_mode_service, "production_requirements"):
            payload["production_requirements"] = server_mode_service.production_requirements()
        if hasattr(server_mode_service, "incident_status"):
            payload["incident"] = server_mode_service.incident_status().get("incident")
        return json_resp(payload)

    @app.route("/api/root/server-mode/checkpoint", methods=["POST"])
    @require_csrf
    def root_server_mode_checkpoint():
        if not server_mode_service:
            return json_resp({"ok":False,"msg": "Server Mode 服務目前無法使用"}), 503
        actor, error = require_root_actor()
        if error:
            return error
        try:
            data = request.get_json(force=True)
        except Exception:
            return json_resp({"ok":False,"msg": "請求 JSON 格式錯誤"}), 400
        if not isinstance(data, dict):
            return json_resp({"ok":False,"msg": "請求內容格式錯誤"}), 400
        result = server_mode_service.create_mode_checkpoint(
            actor=actor,
            target_mode=data.get("target_mode") or data.get("mode"),
            reason=data.get("reason") or data.get("notes") or "",
        )
        return json_resp(result), (200 if result.get("ok") else 400)

    @app.route("/api/root/server-mode/restore-check", methods=["POST"])
    @require_csrf
    def root_server_mode_restore_check():
        if not server_mode_service or not hasattr(server_mode_service, "validate_checkpoint_restore"):
            return json_resp({"ok":False,"msg": "Server Mode 服務目前無法使用"}), 503
        actor, error = require_root_actor()
        if error:
            return error
        try:
            data = request.get_json(force=True)
        except Exception:
            return json_resp({"ok":False,"msg": "請求 JSON 格式錯誤"}), 400
        if not isinstance(data, dict):
            return json_resp({"ok":False,"msg": "請求內容格式錯誤"}), 400
        result = server_mode_service.validate_checkpoint_restore(checkpoint_id=data.get("checkpoint_id"))
        return json_resp(result), (200 if result.get("ok") else 400)

    @app.route("/api/root/server-mode/switch", methods=["POST"])
    @require_csrf
    def root_server_mode_switch():
        if not server_mode_service:
            return json_resp({"ok":False,"msg": "Server Mode 服務目前無法使用"}), 503
        actor, error = require_root_actor()
        if error:
            return error
        try:
            data = request.get_json(force=True)
        except Exception:
            return json_resp({"ok":False,"msg": "請求 JSON 格式錯誤"}), 400
        if not isinstance(data, dict):
            return json_resp({"ok":False,"msg": "請求內容格式錯誤"}), 400
        result = server_mode_service.switch_mode(
            target_mode=data.get("mode") or data.get("target_mode"),
            actor=actor,
            confirm=data.get("confirm"),
            notes=data.get("reason") or data.get("notes") or "",
        )
        if result.get("ok"):
            result["points_block"] = force_points_block("server_mode_change", actor)
        return json_resp(result), (200 if result.get("ok") else 400)

    @app.route("/api/root/server-mode/requirements", methods=["GET"])
    @require_csrf_safe
    def root_server_mode_requirements():
        if not server_mode_service or not hasattr(server_mode_service, "production_requirements"):
            return json_resp({"ok":False,"msg": "Server Mode 服務目前無法使用"}), 503
        actor, error = require_root_actor()
        if error:
            return error
        return json_resp(server_mode_service.production_requirements())

    @app.route("/api/root/server-mode/logs", methods=["GET"])
    @require_csrf_safe
    def root_server_mode_logs():
        if not server_mode_service or not hasattr(server_mode_service, "mode_switch_logs"):
            return json_resp({"ok":False,"msg": "Server Mode 服務目前無法使用"}), 503
        actor, error = require_root_actor()
        if error:
            return error
        try:
            limit = int(request.args.get("limit") or 50)
        except Exception:
            limit = 50
        return json_resp({"ok": True, "logs": server_mode_service.mode_switch_logs(limit=limit)})

    @app.route("/api/server-mode/logs/verify", methods=["GET"])
    @app.route("/api/root/server-mode/logs/verify", methods=["GET"])
    @require_csrf_safe
    def root_server_mode_logs_verify():
        if not server_mode_service or not hasattr(server_mode_service, "verify_mode_switch_logs"):
            return json_resp({"ok":False,"msg": "Server Mode 服務目前無法使用"}), 503
        actor, error = require_root_actor()
        if error:
            return error
        result = server_mode_service.verify_mode_switch_logs()
        return json_resp({
            "ok": bool(result.get("ok")),
            "chain_length": result.get("chain_length", result.get("count", 0)),
            "broken_links": result.get("broken_links", len(result.get("mismatches") or [])),
            "invalid_signatures": result.get("invalid_signatures", []),
            "first_hash": result.get("first_hash", ""),
            "last_hash": result.get("last_hash", result.get("latest_hash", "")),
            "result": result.get("result", "PASS" if result.get("ok") else "FAIL"),
            "details": result,
        }), (200 if result.get("ok") else 409)

    @app.route("/api/root/launch-check/doc", methods=["GET"])
    @require_csrf_safe
    def root_launch_check_doc():
        actor, error = require_root_actor()
        if error:
            return error
        rel_path = str(request.args.get("path") or "").strip()
        if not rel_path:
            return json_resp({"ok": False, "msg": "缺少文件路徑"}), 400
        docs_root = os.path.realpath(os.path.join(BASE_DIR, "docs"))
        target = os.path.realpath(os.path.join(BASE_DIR, rel_path))
        if not target.startswith(docs_root + os.sep):
            return json_resp({"ok": False, "msg": "只允許讀取 docs/ 內的文件"}), 400
        if not os.path.isfile(target):
            return json_resp({"ok": False, "msg": "找不到指定文件"}), 404
        if os.path.splitext(target)[1].lower() not in {".md", ".txt", ".json"}:
            return json_resp({"ok": False, "msg": "文件格式不支援"}), 400
        try:
            with open(target, "r", encoding="utf-8") as fh:
                content = fh.read()
        except OSError as exc:
            return json_resp({"ok": False, "msg": f"文件讀取失敗：{exc}"}), 500
        return json_resp({
            "ok": True,
            "path": public_relative_path(target, BASE_DIR),
            "label": os.path.basename(target),
            "content": content[:120000],
            "truncated": len(content) > 120000,
        })

    @app.route("/api/root/production-report/upload", methods=["POST"])
    @require_csrf
    def root_production_report_upload():
        if not server_mode_service or not hasattr(server_mode_service, "upload_production_report"):
            return json_resp({"ok":False,"msg": "Server Mode 服務目前無法使用"}), 503
        actor, error = require_root_actor()
        if error:
            return error
        try:
            data = request.get_json(force=True)
        except Exception:
            return json_resp({"ok":False,"msg": "請求 JSON 格式錯誤"}), 400
        if not isinstance(data, dict):
            return json_resp({"ok":False,"msg": "請求內容格式錯誤"}), 400
        result = server_mode_service.upload_production_report(
            actor=actor,
            report_type=data.get("report_type"),
            report_hash=data.get("report_hash"),
            target_commit=data.get("target_commit") or "",
            target_branch=data.get("target_branch") or "",
            server_mode=data.get("server_mode") or "",
            test_result=data.get("test_result") or "",
            passed=bool(data.get("pass") if "pass" in data else data.get("passed")),
            critical_findings_count=data.get("critical_findings_count") or 0,
            high_findings_count=data.get("high_findings_count") or 0,
            unresolved_findings=data.get("unresolved_findings") or [],
            tester=data.get("tester") or actor["username"],
            signature=data.get("signature") or "",
            raw_report=data.get("raw_report"),
            key_version=data.get("key_version") or "",
            report_source=data.get("report_source") or "manual_signed_upload",
        )
        return json_resp(result), (200 if result.get("ok") else 400)

    @app.route("/api/root/production-report/status", methods=["GET"])
    @require_csrf_safe
    def root_production_report_status():
        if not server_mode_service or not hasattr(server_mode_service, "production_requirements"):
            return json_resp({"ok":False,"msg": "Server Mode 服務目前無法使用"}), 503
        actor, error = require_root_actor()
        if error:
            return error
        return json_resp(server_mode_service.production_requirements())

    @app.route("/api/root/production/enter", methods=["POST"])
    @require_csrf
    def root_production_enter():
        if not server_mode_service:
            return json_resp({"ok":False,"msg": "Server Mode 服務目前無法使用"}), 503
        actor, error = require_root_actor()
        if error:
            return error
        try:
            data = request.get_json(force=True)
        except Exception:
            return json_resp({"ok":False,"msg": "請求 JSON 格式錯誤"}), 400
        if not isinstance(data, dict):
            return json_resp({"ok":False,"msg": "請求內容格式錯誤"}), 400
        result = server_mode_service.switch_mode(
            target_mode="production",
            actor=actor,
            confirm=data.get("confirm"),
            notes=data.get("reason") or data.get("notes") or "",
        )
        if result.get("ok"):
            result["points_block"] = force_points_block("server_mode_change", actor)
        return json_resp(result), (200 if result.get("ok") else 400)

    @app.route("/api/root/tester-token/create", methods=["POST"])
    @require_csrf
    def root_tester_token_create():
        if not server_mode_service or not hasattr(server_mode_service, "create_tester_token"):
            return json_resp({"ok":False,"msg": "Server Mode 服務目前無法使用"}), 503
        actor, error = require_root_actor()
        if error:
            return error
        try:
            data = request.get_json(force=True)
        except Exception:
            return json_resp({"ok":False,"msg": "請求 JSON 格式錯誤"}), 400
        if not isinstance(data, dict):
            return json_resp({"ok":False,"msg": "請求內容格式錯誤"}), 400
        result = server_mode_service.create_tester_token(
            actor=actor,
            tester_user_id=data.get("tester_user_id"),
            allowed_features=data.get("allowed_features") or [],
            allowed_routes=data.get("allowed_routes") or [],
            expires_at=data.get("expires_at"),
            max_requests_per_minute=data.get("max_requests_per_minute") or 60,
            can_modify_own_role=bool(data.get("can_modify_own_role")),
            can_modify_own_points=bool(data.get("can_modify_own_points")),
            can_run_security_tests=bool(data.get("can_run_security_tests")),
        )
        return json_resp(result), (200 if result.get("ok") else 400)

    @app.route("/api/root/tester-token/revoke", methods=["POST"])
    @require_csrf
    def root_tester_token_revoke():
        if not server_mode_service or not hasattr(server_mode_service, "revoke_tester_token"):
            return json_resp({"ok":False,"msg": "Server Mode 服務目前無法使用"}), 503
        actor, error = require_root_actor()
        if error:
            return error
        try:
            data = request.get_json(force=True)
        except Exception:
            return json_resp({"ok":False,"msg": "請求 JSON 格式錯誤"}), 400
        if not isinstance(data, dict):
            return json_resp({"ok":False,"msg": "請求內容格式錯誤"}), 400
        result = server_mode_service.revoke_tester_token(
            actor=actor,
            token_id=data.get("token_id"),
            reason=data.get("reason") or "",
        )
        return json_resp(result), (200 if result.get("ok") else 400)

    @app.route("/api/root/tester-token/list", methods=["GET"])
    @require_csrf_safe
    def root_tester_token_list():
        if not server_mode_service or not hasattr(server_mode_service, "list_tester_tokens"):
            return json_resp({"ok":False,"msg": "Server Mode 服務目前無法使用"}), 503
        actor, error = require_root_actor()
        if error:
            return error
        return json_resp({"ok": True, "tokens": server_mode_service.list_tester_tokens()})

    @app.route("/api/tester/shadow-state", methods=["GET"])
    def tester_shadow_state():
        if not server_mode_service or not hasattr(server_mode_service, "tester_shadow_state"):
            return json_resp({"ok":False,"msg": "Server Mode 服務目前無法使用"}), 503
        actor, error = _require_tester_actor()
        if error:
            return error
        tester_header_value = _tester_token_from_request()
        result = server_mode_service.tester_shadow_state(
            actor=actor,
            **{"token": tester_header_value},
            route=request.path,
            ip_address=get_client_ip(),
        )
        return json_resp(result), (200 if result.get("ok") else 403)

    @app.route("/api/tester/shadow-role", methods=["GET"])
    def tester_shadow_role_get():
        if not server_mode_service or not hasattr(server_mode_service, "tester_shadow_state"):
            return json_resp({"ok":False,"msg": "Server Mode 服務目前無法使用"}), 503
        actor, error = _require_tester_actor()
        if error:
            return error
        tester_header_value = _tester_token_from_request()
        state = server_mode_service.tester_shadow_state(
            actor=actor,
            **{"token": tester_header_value},
            route=request.path,
            ip_address=get_client_ip(),
        )
        if not state.get("ok"):
            return json_resp(state), 403
        return json_resp({
            "ok": True,
            "mode": state.get("mode"),
            "token": state.get("token"),
            "shadow_role": state.get("shadow_role"),
        })

    @app.route("/api/tester/shadow-role", methods=["POST"])
    @require_csrf
    def tester_shadow_role():
        if not server_mode_service or not hasattr(server_mode_service, "set_tester_shadow_role"):
            return json_resp({"ok":False,"msg": "Server Mode 服務目前無法使用"}), 503
        actor, error = _require_tester_actor()
        if error:
            return error
        try:
            data = request.get_json(force=True)
        except Exception:
            return json_resp({"ok":False,"msg": "請求 JSON 格式錯誤"}), 400
        if not isinstance(data, dict):
            return json_resp({"ok":False,"msg": "請求內容格式錯誤"}), 400
        tester_header_value = _tester_token_from_request()
        result = server_mode_service.set_tester_shadow_role(
            actor=actor,
            **{"token": tester_header_value},
            shadow_role=data.get("shadow_role") or data.get("role"),
            route=request.path,
            ip_address=get_client_ip(),
        )
        return json_resp(result), (200 if result.get("ok") else 403)

    @app.route("/api/tester/shadow-wallet", methods=["GET"])
    def tester_shadow_wallet_get():
        if not server_mode_service or not hasattr(server_mode_service, "tester_shadow_state"):
            return json_resp({"ok":False,"msg": "Server Mode 服務目前無法使用"}), 503
        actor, error = _require_tester_actor()
        if error:
            return error
        tester_header_value = _tester_token_from_request()
        state = server_mode_service.tester_shadow_state(
            actor=actor,
            **{"token": tester_header_value},
            route=request.path,
            ip_address=get_client_ip(),
        )
        if not state.get("ok"):
            return json_resp(state), 403
        return json_resp({
            "ok": True,
            "mode": state.get("mode"),
            "token": state.get("token"),
            "shadow_wallet": state.get("shadow_wallet"),
        })

    @app.route("/api/tester/shadow-wallet", methods=["POST"])
    @require_csrf
    def tester_shadow_wallet():
        if not server_mode_service or not hasattr(server_mode_service, "adjust_tester_shadow_wallet"):
            return json_resp({"ok":False,"msg": "Server Mode 服務目前無法使用"}), 503
        actor, error = _require_tester_actor()
        if error:
            return error
        try:
            data = request.get_json(force=True)
        except Exception:
            return json_resp({"ok":False,"msg": "請求 JSON 格式錯誤"}), 400
        if not isinstance(data, dict):
            return json_resp({"ok":False,"msg": "請求內容格式錯誤"}), 400
        tester_header_value = _tester_token_from_request()
        result = server_mode_service.adjust_tester_shadow_wallet(
            actor=actor,
            **{"token": tester_header_value},
            delta_points=data.get("delta_points") or data.get("delta"),
            reason=data.get("reason") or "",
            route=request.path,
            ip_address=get_client_ip(),
        )
        return json_resp(result), (200 if result.get("ok") else 403)

    @app.route("/api/root/incident/enter", methods=["POST"])
    @require_csrf
    def root_incident_enter():
        if not server_mode_service or not hasattr(server_mode_service, "enter_incident_lockdown"):
            return json_resp({"ok":False,"msg": "Server Mode 服務目前無法使用"}), 503
        actor, error = require_root_actor()
        if error:
            return error
        try:
            data = request.get_json(force=True)
        except Exception:
            return json_resp({"ok":False,"msg": "請求 JSON 格式錯誤"}), 400
        if not isinstance(data, dict):
            return json_resp({"ok":False,"msg": "請求內容格式錯誤"}), 400
        if data.get("confirm") != "ENTER_INCIDENT_LOCKDOWN":
            return json_resp({"ok":False,"msg":"confirm 必須等於 ENTER_INCIDENT_LOCKDOWN"}), 400
        result = server_mode_service.enter_incident_lockdown(
            actor=actor,
            trigger_type=data.get("trigger_type") or "manual",
            reason=data.get("reason") or "",
            verification=data.get("verification") or {},
        )
        return json_resp(result), (200 if result.get("ok") else 400)

    @app.route("/api/root/incident/status", methods=["GET"])
    @require_csrf_safe
    def root_incident_status():
        if not server_mode_service or not hasattr(server_mode_service, "incident_status"):
            return json_resp({"ok":False,"msg": "Server Mode 服務目前無法使用"}), 503
        actor, error = require_root_actor()
        if error:
            return error
        return json_resp(server_mode_service.incident_status())

    @app.route("/api/root/incident/resolve", methods=["POST"])
    @require_csrf
    def root_incident_resolve():
        if not server_mode_service or not hasattr(server_mode_service, "resolve_incident"):
            return json_resp({"ok":False,"msg": "Server Mode 服務目前無法使用"}), 503
        actor, error = require_root_actor()
        if error:
            return error
        try:
            data = request.get_json(force=True)
        except Exception:
            return json_resp({"ok":False,"msg": "請求 JSON 格式錯誤"}), 400
        if not isinstance(data, dict):
            return json_resp({"ok":False,"msg": "請求內容格式錯誤"}), 400
        result = server_mode_service.resolve_incident(
            actor=actor,
            confirm=data.get("confirm"),
            notes=data.get("notes") or "",
            verification=data.get("verification") or {},
        )
        return json_resp(result), (200 if result.get("ok") else 400)

    @app.route("/api/admin/server-mode/exit-superweak", methods=["POST"])
    @require_csrf
    def admin_exit_superweak():
        if not server_mode_service:
            return json_resp({"ok":False,"msg": "Server Mode 服務目前無法使用"}), 503
        actor, error = require_root_actor()
        if error:
            return error
        try:
            data = request.get_json(force=True)
        except Exception:
            return json_resp({"ok":False,"msg": "請求 JSON 格式錯誤"}), 400
        if not isinstance(data, dict):
            return json_resp({"ok":False,"msg": "請求內容格式錯誤"}), 400
        result = server_mode_service.exit_superweak(
            actor=actor,
            action=data.get("action"),
            confirm=data.get("confirm"),
            reason=data.get("reason") or "",
        )
        if result.get("ok"):
            result["points_block"] = force_points_block("superweak_exit", actor)
            mode = (result.get("mode") or {}).get("current_mode") or "-"
            notify_root(
                "root_server_mode_changed",
                "伺服器模式已變更",
                f"{actor['username']} 已離開 superweak 模式，目前模式為 {mode}。",
                link="/security",
            )
        return json_resp(result), (200 if result.get("ok") else 400)

    @app.route("/api/admin/restart", methods=["POST"])
    @require_csrf
    def admin_restart():
        actor = get_current_user_ctx()
        if not actor:
            return json_resp({"ok":False,"msg":"未登入"}), 401
        if actor["username"] != "root":
            return json_resp({"ok":False,"msg":"只有最高管理者可重啟服務器"}), 403

        audit("SERVER_RESTART", get_client_ip(), user=actor["username"], detail="initiated by admin")
        try:
            restart = schedule_server_restart(reason="manual-restart", delay_seconds=1.25)
        except Exception as exc:
            return json_resp({"ok":False,"msg":"重啟排程失敗","error":str(exc)}), 500
        return json_resp({"ok":True,"msg":"服務器正在重啟，請稍後重新整理頁面","restart_scheduled":True,"restart":restart})

    @app.route("/api/admin/platform-stats", methods=["GET"])
    @require_csrf_safe
    def admin_platform_stats():
        actor = get_current_user_ctx()
        if not actor:
            return json_resp({"ok":False,"msg":"未登入"}), 401
        role = "super_admin" if actor["username"] == "root" else actor.get("role", "user")
        if role_rank(role) < role_rank("super_admin"):
            return json_resp({"ok":False,"msg":"只有最高管理者可查看健康中心"}), 403

        conn = get_db()
        auth_conn = get_auth_db()
        try:
            from datetime import datetime
            now = datetime.utcnow()
            month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0).strftime("%Y-%m-%d %H:%M:%S")
            today_start = now.strftime("%Y-%m-%d 00:00:00")

            total_users = conn.execute("SELECT COUNT(*) AS c FROM users").fetchone()["c"]

            new_users_month = conn.execute(
                "SELECT COUNT(*) AS c FROM users WHERE created_at >= ?", (month_start,)
            ).fetchone()["c"]

            try:
                active_sessions = auth_conn.execute(
                    "SELECT COUNT(*) AS c FROM sessions WHERE COALESCE(last_seen, created_at) >= datetime('now', '-15 minutes') AND COALESCE(is_revoked, 0)=0"
                ).fetchone()["c"]
            except Exception:
                active_sessions = 0

            try:
                pv_today = conn.execute(
                    "SELECT COUNT(*) AS c FROM page_views WHERE viewed_at >= ?", (today_start,)
                ).fetchone()["c"]
            except Exception:
                pv_today = 0

            try:
                total_points = conn.execute("SELECT COALESCE(SUM(points), 0) AS c FROM users").fetchone()["c"]
            except Exception:
                total_points = 0

            try:
                points_earned_month = conn.execute(
                    "SELECT COALESCE(SUM(delta), 0) AS c FROM point_transactions WHERE delta > 0 AND created_at >= ?",
                    (month_start,)
                ).fetchone()["c"]
            except Exception:
                points_earned_month = 0

            try:
                points_spent_month = abs(int(conn.execute(
                    "SELECT COALESCE(SUM(delta), 0) AS c FROM point_transactions WHERE delta < 0 AND created_at >= ?",
                    (month_start,)
                ).fetchone()["c"] or 0))
            except Exception:
                points_spent_month = 0

            return json_resp({
                "ok": True,
                "stats": {
                    "total_users": total_users,
                    "new_users_month": new_users_month,
                    "active_sessions": active_sessions,
                    "page_views_today": pv_today,
                    "total_points": total_points,
                    "points_earned_month": points_earned_month,
                    "points_spent_month": points_spent_month,
                    "points_net_month": points_earned_month - points_spent_month,
                }
            })
        finally:
            auth_conn.close()
            conn.close()

    @app.route("/<path:invalid>", methods=["GET", "POST", "OPTIONS"], provide_automatic_options=False)
    def catch_all(invalid):
        ip, ua = get_client_ip(), ctx["get_ua"]()
        audit("404_CATCHALL", ip, ua=ua, detail=f"path={invalid}")
        resp = json_resp({"ok":False,"msg": "找不到資源"})
        if request.method == "OPTIONS":
            resp.headers["Allow"] = "GET, POST, HEAD, OPTIONS"
        return resp, 404
