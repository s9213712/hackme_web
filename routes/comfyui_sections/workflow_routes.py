import json
from datetime import datetime

from services.comfyui.template import errors as template_errors
from services.comfyui.template.run_gate import (
    RunGateFailure,
    run_workflow_through_gates,
)
from services.platform.settings import is_feature_enabled


def _default_upload_callback(active_client):
    """Return an UploadCallback that pushes bytes into ComfyUI input/<run_id>/.

    Falls back to a no-op (returns the synthetic filename) when no
    ComfyUI client is available; the run gate will then surface the
    capability blocker rather than silently swallowing the upload.
    """
    def _cb(*, file_row, target_filename, run_id):
        if active_client is None:
            return {"filename": target_filename, "subfolder": run_id, "type": "input"}
        try:
            from services.comfyui.files import upload_image_bytes
            from services.comfyui.client import ComfyUIError
        except Exception:  # pragma: no cover - defensive import guard
            return {"filename": target_filename, "subfolder": run_id, "type": "input"}
        storage_path = file_row.get("storage_path") if hasattr(file_row, "get") else file_row["storage_path"]
        try:
            with open(storage_path, "rb") as fh:
                data = fh.read()
        except Exception:
            data = b""
        try:
            return upload_image_bytes(
                active_client,
                data,
                target_filename,
                image_type="input",
                overwrite=False,
                subfolder=run_id,
                error_cls=ComfyUIError,
            )
        except Exception:
            return {"filename": target_filename, "subfolder": run_id, "type": "input"}
    return _cb


def register_comfyui_workflow_routes(app, ctx):
    actor_or_401 = ctx["actor_or_401"]
    root_or_403 = ctx["root_or_403"]
    actor_value = ctx["actor_value"]
    json_resp = ctx["json_resp"]
    require_csrf = ctx["require_csrf"]
    require_csrf_safe = ctx["require_csrf_safe"]
    get_db = ctx["get_db"]
    get_client_ip = ctx["get_client_ip"]
    get_ua = ctx["get_ua"]
    audit = ctx["audit"]
    comfyui_binding = ctx["comfyui_binding"]
    client_for_url = ctx["client_for_url"]
    load_workflow_preset = ctx["load_workflow_preset"]
    workflow_preset_summary = ctx["workflow_preset_summary"]
    parse_json_field = ctx["parse_json_field"]
    extract_workflow_payload = ctx["extract_workflow_payload"]
    normalize_workflow_default_params = ctx["normalize_workflow_default_params"]
    upsert_workflow_preset = ctx["upsert_workflow_preset"]
    load_workflow_preset_row = ctx["load_workflow_preset_row"]
    WorkflowValidationError = ctx["WorkflowValidationError"]
    list_workflow_presets = ctx["list_workflow_presets"]
    workflow_dependency_status = ctx["workflow_dependency_status"]
    list_workflow_runs = ctx["list_workflow_runs"]
    normalize_generation_payload = ctx["normalize_generation_payload"]
    validate_generation_capabilities = ctx["validate_generation_capabilities"]
    sanitize_workflow_json = ctx["sanitize_workflow_json"]
    workflow_json_to_pretty_text = ctx["workflow_json_to_pretty_text"]
    assert_workflow_dependencies_or_error = ctx["assert_workflow_dependencies_or_error"]
    create_workflow_run = ctx["create_workflow_run"]
    create_generation_job = ctx["create_generation_job"]
    capture_request_audit_meta = ctx["capture_request_audit_meta"]
    run_comfyui_workflow_preset_job = ctx["run_comfyui_workflow_preset_job"]
    DEFAULT_GENERATION_TIMEOUT_SECONDS = ctx["DEFAULT_GENERATION_TIMEOUT_SECONDS"]
    safe_text = ctx["safe_text"]
    threading = ctx["threading"]

    @app.route("/api/comfyui/workflows", methods=["GET"])
    @require_csrf_safe
    def comfyui_workflow_presets():
        actor, err = actor_or_401()
        if err:
            return err
        binding = comfyui_binding(actor)
        active_client = None
        dependency_warning = ""
        try:
            active_client = client_for_url(binding["url"])
            if hasattr(active_client, "health_check"):
                active_client.health_check(timeout=3)
        except Exception as exc:
            dependency_warning = str(exc)
            active_client = None
        conn = get_db()
        try:
            presets = list_workflow_presets(conn, actor=actor, active_client=active_client)
        finally:
            conn.close()
        return json_resp({
            "ok": True,
            "presets": presets,
            "official_presets": [item for item in presets if item.get("is_official")],
            "my_presets": [item for item in presets if int(item.get("owner_user_id") or 0) == int(actor_value(actor, "id")) and not item.get("is_official")],
            "shared_presets": [item for item in presets if int(item.get("owner_user_id") or 0) != int(actor_value(actor, "id")) and not item.get("is_official")],
            "can_publish_official": actor_value(actor, "username") == "root",
            "dependency_warning": dependency_warning,
        })

    @app.route("/api/comfyui/workflows/import", methods=["POST"])
    @require_csrf
    def comfyui_workflow_import():
        actor, err = actor_or_401()
        if err:
            return err
        try:
            data = ctx["request"].get_json(force=True)
        except Exception:
            return json_resp({"ok": False, "msg": "Invalid JSON"}), 400
        data = data if isinstance(data, dict) else {}
        workflow_candidate = data.get("workflow_json") if "workflow_json" in data else data.get("workflow")
        if workflow_candidate in (None, ""):
            return json_resp({"ok": False, "msg": "請提供 workflow JSON"}), 400
        try:
            workflow_payload, extracted_defaults = extract_workflow_payload(workflow_candidate)
            default_params = (
                normalize_workflow_default_params(data.get("default_params_json") if "default_params_json" in data else data.get("default_params"))
                if ("default_params_json" in data or "default_params" in data)
                else extracted_defaults
            )
        except WorkflowValidationError as exc:
            return json_resp({"ok": False, "msg": str(exc)}), 400
        title = safe_text(data.get("title") or data.get("name") or f"Workflow {datetime.now().strftime('%Y-%m-%d %H:%M')}", 120)
        conn = get_db()
        try:
            preset_id = upsert_workflow_preset(
                conn,
                actor=actor,
                title=title,
                description=data.get("description") or "",
                visibility=data.get("visibility") or "private",
                workflow_payload=workflow_payload,
                default_params=default_params,
            )
            row = load_workflow_preset_row(conn, preset_id=preset_id)
            conn.commit()
        finally:
            conn.close()
        audit("COMFYUI_WORKFLOW_IMPORT", get_client_ip(), user=actor_value(actor, "username"), success=True, ua=get_ua(), detail=f"preset_id={preset_id}, title={title}")
        return json_resp({"ok": True, "preset": workflow_preset_summary(row, actor=actor), "msg": "已匯入 workflow preset"})

    @app.route("/api/comfyui/workflows/export-current", methods=["POST"])
    @require_csrf
    def comfyui_workflow_export_current():
        actor, err = actor_or_401()
        if err:
            return err
        try:
            data = ctx["request"].get_json(force=True)
        except Exception:
            return json_resp({"ok": False, "msg": "Invalid JSON"}), 400
        data = data if isinstance(data, dict) else {}
        params, msg = normalize_generation_payload(data)
        if msg:
            return json_resp({"ok": False, "msg": msg}), 400
        active_client = client_for_url(comfyui_binding(actor)["url"])
        try:
            capabilities, capability_msg = validate_generation_capabilities(active_client, params)
            if capability_msg:
                return json_resp({"ok": False, "msg": capability_msg, "capabilities": capabilities or {}}), 409
            workflow = active_client.build_generation_workflow(params)
            workflow_payload = sanitize_workflow_json(workflow)
        except (ctx["ComfyUIError"], WorkflowValidationError) as exc:
            return json_resp({"ok": False, "msg": str(exc)}), 400
        return json_resp({
            "ok": True,
            "workflow_json": workflow_payload["workflow_json"],
            "workflow_text": workflow_json_to_pretty_text(workflow_payload["workflow_json"]),
            "workflow_hash": workflow_payload["workflow_hash"],
            "required_models": workflow_payload["required_models"],
            "required_loras": workflow_payload["required_loras"],
            "required_controlnets": workflow_payload["required_controlnets"],
            "default_params": params,
        })

    @app.route("/api/comfyui/workflows/<int:preset_id>", methods=["GET"])
    @require_csrf_safe
    def comfyui_workflow_detail(preset_id):
        actor, err = actor_or_401()
        if err:
            return err
        conn = get_db()
        try:
            row, err_resp = load_workflow_preset(conn, preset_id=preset_id, actor=actor)
            if err_resp:
                return err_resp
            active_client = None
            try:
                active_client = client_for_url(comfyui_binding(actor)["url"])
                if hasattr(active_client, "health_check"):
                    active_client.health_check(timeout=3)
            except Exception:
                active_client = None
            dependency_status = workflow_dependency_status(active_client, row) if active_client is not None else None
            recent_runs = list_workflow_runs(conn, preset_id=preset_id, limit=ctx["COMFYUI_WORKFLOW_RUN_LIMIT"])
            payload = workflow_preset_summary(row, dependency_status=dependency_status, recent_runs=recent_runs, actor=actor)
            payload["workflow_json"] = parse_json_field(row["workflow_json"], {}) or {}
        finally:
            conn.close()
        return json_resp({"ok": True, "preset": payload})

    @app.route("/api/comfyui/workflows/<int:preset_id>", methods=["PUT"])
    @require_csrf
    def comfyui_workflow_update(preset_id):
        actor, err = actor_or_401()
        if err:
            return err
        try:
            data = ctx["request"].get_json(force=True)
        except Exception:
            return json_resp({"ok": False, "msg": "Invalid JSON"}), 400
        data = data if isinstance(data, dict) else {}
        conn = get_db()
        try:
            row, err_resp = load_workflow_preset(conn, preset_id=preset_id, actor=actor, require_write=True)
            if err_resp:
                return err_resp
            before = workflow_preset_summary(row, actor=actor)
            workflow_candidate = data.get("workflow_json") if "workflow_json" in data else parse_json_field(row["workflow_json"], {})
            workflow_payload, extracted_defaults = extract_workflow_payload(workflow_candidate)
            if "default_params_json" in data or "default_params" in data:
                default_params = normalize_workflow_default_params(data.get("default_params_json") if "default_params_json" in data else data.get("default_params"))
            elif "workflow_json" in data:
                default_params = extracted_defaults
            else:
                default_params = parse_json_field(row["default_params_json"], {}) or {}
            updated_id = upsert_workflow_preset(
                conn,
                preset_id=preset_id,
                actor=actor,
                title=data.get("title") or row["title"],
                description=data.get("description") if "description" in data else row["description"],
                visibility=data.get("visibility") if "visibility" in data else row["visibility"],
                workflow_payload=workflow_payload,
                default_params=default_params,
                is_official=bool(row["is_official"]),
                published_by_user_id=row["published_by_user_id"],
            )
            row = load_workflow_preset_row(conn, preset_id=updated_id)
            conn.commit()
        except WorkflowValidationError as exc:
            conn.rollback()
            return json_resp({"ok": False, "msg": str(exc)}), 400
        finally:
            conn.close()
        after = workflow_preset_summary(row, actor=actor)
        audit(
            "COMFYUI_WORKFLOW_UPDATE",
            get_client_ip(),
            user=actor_value(actor, "username"),
            success=True,
            ua=get_ua(),
            detail=f"preset_id={preset_id}, before={json.dumps(before, ensure_ascii=False)[:180]}, after={json.dumps(after, ensure_ascii=False)[:180]}",
        )
        return json_resp({"ok": True, "preset": after, "msg": "已更新 workflow preset"})

    @app.route("/api/comfyui/workflows/<int:preset_id>", methods=["DELETE"])
    @require_csrf
    def comfyui_workflow_delete(preset_id):
        actor, err = actor_or_401()
        if err:
            return err
        conn = get_db()
        try:
            row, err_resp = load_workflow_preset(conn, preset_id=preset_id, actor=actor, require_write=True)
            if err_resp:
                return err_resp
            conn.execute("DELETE FROM comfyui_workflow_runs WHERE preset_id=?", (int(preset_id),))
            conn.execute("DELETE FROM comfyui_workflow_presets WHERE id=? AND owner_user_id=?", (int(preset_id), int(actor_value(actor, "id"))))
            conn.commit()
        finally:
            conn.close()
        audit("COMFYUI_WORKFLOW_DELETE", get_client_ip(), user=actor_value(actor, "username"), success=True, ua=get_ua(), detail=f"preset_id={preset_id}")
        return json_resp({"ok": True, "msg": "已刪除 workflow preset"})

    @app.route("/api/comfyui/workflows/<int:preset_id>/run", methods=["POST"])
    @require_csrf
    def comfyui_workflow_run(preset_id):
        actor, err = actor_or_401()
        if err:
            return err
        # Strict mode (§15.7 / Phase 6): when feature_comfyui_template_importer_strict
        # is on, every /run goes through the §10 5-gate. Body may carry
        # user_inputs (per-node patch dict) and image_field_assignments
        # (LoadImage node_id → cloud_file_id) so the gate can validate +
        # remap. Legacy callers without these fields are still subject to
        # gate validation against the preset's stored workflow.
        strict_mode = is_feature_enabled("feature_comfyui_template_importer_strict")
        try:
            body = ctx["request"].get_json(force=True, silent=True) if strict_mode else {}
        except Exception:
            body = {}
        body = body if isinstance(body, dict) else {}
        user_inputs = body.get("user_inputs") if isinstance(body.get("user_inputs"), dict) else {}
        image_field_assignments = (
            body.get("image_field_assignments")
            if isinstance(body.get("image_field_assignments"), dict)
            else {}
        )
        conn = get_db()
        try:
            row, err_resp = load_workflow_preset(conn, preset_id=preset_id, actor=actor)
            if err_resp:
                return err_resp
            comfyui_url = (comfyui_binding(actor) or {}).get("url")
            active_client = client_for_url(comfyui_url) if comfyui_url else None
            dependency_status, dependency_msg = assert_workflow_dependencies_or_error(active_client, row)
            if dependency_msg:
                return json_resp({"ok": False, "msg": dependency_msg, "dependency_status": dependency_status}), 409
            default_params = parse_json_field(row["default_params_json"], {}) or {}
            workflow_json = parse_json_field(row["workflow_json"], {}) or {}

            # 5-gate enforcement before any job is created — failed gates
            # never produce a job_id so the user gets immediate feedback
            # instead of polling status.
            if strict_mode:
                import uuid as _uuid
                gate_run_id = _uuid.uuid4().hex
                try:
                    gate_result = run_workflow_through_gates(
                        raw_workflow=workflow_json,
                        user_inputs=user_inputs,
                        image_field_assignments=image_field_assignments,
                        actor=dict(actor),
                        user_id=int(actor_value(actor, "id")),
                        run_id=gate_run_id,
                        conn=conn,
                        comfyui_client=active_client,
                        upload_callback=_default_upload_callback(active_client),
                    )
                except RunGateFailure as exc:
                    audit(
                        "COMFYUI_TEMPLATE_RUN_GATE_FAIL",
                        get_client_ip(),
                        user=actor_value(actor, "username") or "-",
                        success=False,
                        ua=get_ua(),
                        detail=(
                            f"preset_id={preset_id} run_id={gate_run_id} "
                            f"gate={exc.gate} stage={exc.stage} reason={exc.msg}"
                        ),
                    )
                    return json_resp({
                        "ok": False,
                        "msg": exc.msg,
                        "stage": exc.stage,
                        "gate": exc.gate,
                        "audit_detail": exc.audit_detail,
                    }), exc.http_status
                workflow_json = gate_result.workflow
                audit(
                    "COMFYUI_TEMPLATE_RUN_GATE_PASS",
                    get_client_ip(),
                    user=actor_value(actor, "username") or "-",
                    success=True,
                    ua=get_ua(),
                    detail=(
                        f"preset_id={preset_id} run_id={gate_run_id} "
                        f"node_count={gate_result.audit_metadata.get('node_count')} "
                        f"image_remapped={gate_result.audit_metadata.get('image_remapped')}"
                    ),
                )

            run_id = create_workflow_run(
                conn,
                preset_id=preset_id,
                actor=actor,
                prompt=default_params.get("prompt") or "",
                negative_prompt=default_params.get("negative_prompt") or "",
                params_json=default_params,
                workflow_json=workflow_json,
            )
            conn.commit()
        finally:
            conn.close()
        job_id = create_generation_job(actor)
        request_meta = capture_request_audit_meta()
        worker = threading.Thread(
            target=run_comfyui_workflow_preset_job,
            args=(job_id, dict(actor), dict(row), run_id, DEFAULT_GENERATION_TIMEOUT_SECONDS, request_meta),
            daemon=True,
        )
        worker.start()
        return json_resp({
            "ok": True,
            "async": True,
            "workflow_run_id": run_id,
            "dependency_status": dependency_status,
            "strict_mode": bool(strict_mode),
            "job": {
                "job_id": job_id,
                "status": "queued",
                "progress": {"phase": "queued", "percent": 0, "detail": "已建立 workflow 執行工作"},
            },
        })

    @app.route("/api/comfyui/workflows/<int:preset_id>/export", methods=["POST"])
    @require_csrf
    def comfyui_workflow_export(preset_id):
        actor, err = actor_or_401()
        if err:
            return err
        conn = get_db()
        try:
            row, err_resp = load_workflow_preset(conn, preset_id=preset_id, actor=actor)
            if err_resp:
                return err_resp
            workflow_json = parse_json_field(row["workflow_json"], {}) or {}
        finally:
            conn.close()
        return json_resp({
            "ok": True,
            "filename": f"comfyui-workflow-{preset_id}.json",
            "workflow_hash": row["workflow_hash"] or "",
            "workflow_json": workflow_json,
            "workflow_text": workflow_json_to_pretty_text(workflow_json),
        })

    @app.route("/api/admin/comfyui/workflows/<int:preset_id>/publish-official", methods=["POST"])
    @require_csrf
    def comfyui_workflow_publish_official(preset_id):
        actor, err = root_or_403()
        if err:
            return err
        conn = get_db()
        try:
            row, err_resp = load_workflow_preset(conn, preset_id=preset_id, actor=actor, require_write=True)
            if err_resp:
                return err_resp
            updated_id = upsert_workflow_preset(
                conn,
                preset_id=preset_id,
                actor=actor,
                title=row["title"],
                description=row["description"],
                visibility="public",
                workflow_payload={
                    "workflow_json": parse_json_field(row["workflow_json"], {}) or {},
                    "workflow_hash": row["workflow_hash"] or "",
                    "required_models": parse_json_field(row["required_models_json"], []) or [],
                    "required_loras": parse_json_field(row["required_loras_json"], []) or [],
                    "required_controlnets": parse_json_field(row["required_controlnets_json"], []) or [],
                    "default_params": parse_json_field(row["default_params_json"], {}) or {},
                },
                default_params=parse_json_field(row["default_params_json"], {}) or {},
                is_official=True,
                published_by_user_id=actor_value(actor, "id"),
            )
            row = load_workflow_preset_row(conn, preset_id=updated_id)
            conn.commit()
        finally:
            conn.close()
        audit("COMFYUI_WORKFLOW_PUBLISH_OFFICIAL", get_client_ip(), user=actor_value(actor, "username"), success=True, ua=get_ua(), detail=f"preset_id={preset_id}")
        return json_resp({"ok": True, "preset": workflow_preset_summary(row, actor=actor), "msg": "已發布為官方 preset"})

