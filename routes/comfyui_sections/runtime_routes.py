def register_comfyui_runtime_routes(app, ctx):
    request = ctx["request"]
    json_resp = ctx["json_resp"]
    require_csrf = ctx["require_csrf"]
    require_csrf_safe = ctx["require_csrf_safe"]
    get_db = ctx["get_db"]
    get_client_ip = ctx["get_client_ip"]
    get_ua = ctx["get_ua"]
    audit = ctx["audit"]
    threading = ctx["threading"]
    ComfyUIError = ctx["ComfyUIError"]
    SAFE_SAMPLER_FALLBACK = ctx["SAFE_SAMPLER_FALLBACK"]
    SAFE_SCHEDULER_FALLBACK = ctx["SAFE_SCHEDULER_FALLBACK"]
    COMFYUI_LORA_EXTRA_PRICE_POINTS = ctx["COMFYUI_LORA_EXTRA_PRICE_POINTS"]
    COMFYUI_HISTORY_LIMIT = ctx["COMFYUI_HISTORY_LIMIT"]
    DEFAULT_GENERATION_TIMEOUT_SECONDS = ctx["DEFAULT_GENERATION_TIMEOUT_SECONDS"]
    MAX_GENERATION_TIMEOUT_SECONDS = ctx["MAX_GENERATION_TIMEOUT_SECONDS"]
    _actor_or_401 = ctx["actor_or_401"]
    _actor_value = ctx["actor_value"]
    _assert_generation_job_owner = ctx["assert_generation_job_owner"]
    _build_lora_details = ctx["build_lora_details"]
    _capture_request_audit_meta = ctx["capture_request_audit_meta"]
    _charge_comfyui_generation = ctx["charge_comfyui_generation"]
    _client_for_url = ctx["client_for_url"]
    _coerce_bool = ctx["coerce_bool"]
    _comfyui_binding = ctx["comfyui_binding"]
    _comfyui_charge_required = ctx["comfyui_charge_required"]
    _comfyui_lora_count = ctx["comfyui_lora_count"]
    _comfyui_price_quote = ctx["comfyui_price_quote"]
    _comfyui_total_quantity = ctx["comfyui_total_quantity"]
    _comfyui_unavailable_payload = ctx["comfyui_unavailable_payload"]
    _comfyui_wallet_payload = ctx["comfyui_wallet_payload"]
    _configured_comfyui_port = ctx["configured_comfyui_port"]
    _configured_comfyui_url = ctx["configured_comfyui_url"]
    _configured_connection_mode = ctx["configured_connection_mode"]
    _configured_default_dimensions = ctx["configured_default_dimensions"]
    _configured_max_batch_size = ctx["configured_max_batch_size"]
    _create_generation_job = ctx["create_generation_job"]
    _ensure_comfyui_balance = ctx["ensure_comfyui_balance"]
    _finalize_generation_records = ctx["finalize_generation_records"]
    _hydrate_generation_assets = ctx["hydrate_generation_assets"]
    _int_range = ctx["int_range"]
    _json_error_from_comfy = ctx["json_error_from_comfy"]
    _list_generation_history = ctx["list_generation_history"]
    _load_generation_history = ctx["load_generation_history"]
    _local_comfyui_runtime_status = ctx["local_comfyui_runtime_status"]
    _normalize_generation_payload = ctx["normalize_generation_payload"]
    _parse_generation_request = ctx["parse_generation_request"]
    _record_generation_history = ctx["record_generation_history"]
    _register_active_generation = ctx["register_active_generation"]
    _run_comfyui_generation_job = ctx["run_comfyui_generation_job"]
    _start_local_comfyui = ctx["start_local_comfyui"]
    _stop_local_comfyui = ctx["stop_local_comfyui"]
    _unregister_active_generation = ctx["unregister_active_generation"]
    _validate_generation_capabilities = ctx["validate_generation_capabilities"]

    @app.route("/api/comfyui/status", methods=["GET"])
    @require_csrf_safe
    def comfyui_status():
        actor, err = _actor_or_401()
        if err:
            return err
        binding = _comfyui_binding(actor)
        active_client = _client_for_url(binding["url"])
        try:
            if hasattr(active_client, "health_check"):
                status = active_client.health_check(timeout=3)
            else:
                active_client.get_models()
                status = {"ok": True}
        except ComfyUIError as exc:
            runtime = _local_comfyui_runtime_status(_configured_comfyui_port())
            if binding["connection_mode"] == "local" and runtime:
                return json_resp({
                    "ok": True,
                    "available": False,
                    "starting": True,
                    "msg": runtime["message"],
                    "startup_log_tail": runtime["startup_log_tail"],
                    "connection_mode": binding["connection_mode"],
                    "backend_scope": binding["backend_scope"],
                    "comfyui_url": getattr(active_client, "base_url", binding["url"]),
                    "max_batch_size": _configured_max_batch_size(),
                    "default_width": _configured_default_dimensions()["width"],
                    "default_height": _configured_default_dimensions()["height"],
                    "billing": None if not _comfyui_charge_required(actor) else (_comfyui_price_quote(1)[0] or {}),
                    "wallet": _comfyui_wallet_payload(actor),
                    "lora_extra_unit_price": COMFYUI_LORA_EXTRA_PRICE_POINTS,
                    "local_runtime": runtime,
                })
            return json_resp(_comfyui_unavailable_payload(exc, active_client))
        return json_resp({
            "ok": True,
            "available": True,
            "connection_mode": binding["connection_mode"],
            "backend_scope": binding["backend_scope"],
            "comfyui_url": getattr(active_client, "base_url", binding["url"]),
            "max_batch_size": _configured_max_batch_size(),
            "default_width": _configured_default_dimensions()["width"],
            "default_height": _configured_default_dimensions()["height"],
            "billing": None if not _comfyui_charge_required(actor) else (_comfyui_price_quote(1)[0] or {}),
            "wallet": _comfyui_wallet_payload(actor),
            "lora_extra_unit_price": COMFYUI_LORA_EXTRA_PRICE_POINTS,
            "system": status.get("system") if isinstance(status, dict) else {},
        })

    @app.route("/api/comfyui/start", methods=["POST"])
    @require_csrf
    def comfyui_start_local():
        actor, err = _actor_or_401()
        if err:
            return err
        result, msg = _start_local_comfyui(actor, wait_seconds=2)
        if msg:
            return json_resp({"ok": False, "msg": msg, "connection_mode": _configured_connection_mode()}), 400
        return json_resp({
            "ok": True,
            "connection_mode": _configured_connection_mode(),
            "comfyui_url": _configured_comfyui_url(),
            "start": result,
            "msg": (result or {}).get("message") or ("ComfyUI 已在執行中" if (result or {}).get("already_running") else "已送出 ComfyUI 啟動請求"),
        })

    @app.route("/api/root/comfyui/stop", methods=["POST"])
    @require_csrf
    def root_comfyui_stop():
        actor, err = _root_or_403()
        if err:
            return err
        result, msg = _stop_local_comfyui(actor)
        if msg:
            return json_resp({"ok": False, "msg": msg, "connection_mode": _configured_connection_mode()}), 400
        return json_resp({
            "ok": True,
            "connection_mode": _configured_connection_mode(),
            "comfyui_url": _configured_comfyui_url(),
            "stop": result,
            "msg": "已停止本地 ComfyUI" if not (result or {}).get("already_stopped") else "ComfyUI 目前未在執行",
        })

    @app.route("/api/comfyui/models", methods=["GET"])
    @require_csrf_safe
    def comfyui_models():
        actor, err = _actor_or_401()
        if err:
            return err
        binding = _comfyui_binding(actor)
        active_client = _client_for_url(binding["url"])
        try:
            models = active_client.get_models()
            options = active_client.get_sampler_options()
            loras = active_client.get_loras() if hasattr(active_client, "get_loras") else []
            capabilities = active_client.get_capabilities() if hasattr(active_client, "get_capabilities") else {}
        except ComfyUIError as exc:
            return _json_error_from_comfy(exc, active_client)
        try:
            vaes = active_client.get_vaes() if hasattr(active_client, "get_vaes") else []
        except ComfyUIError:
            vaes = []
        try:
            embeddings = active_client.get_embeddings() if hasattr(active_client, "get_embeddings") else []
        except ComfyUIError:
            embeddings = []
        lora_details = _build_lora_details(loras)
        return json_resp({
            "ok": True,
            "models": models,
            "loras": loras,
            "lora_details": lora_details,
            "vaes": vaes,
            "embeddings": embeddings,
            "connection_mode": binding["connection_mode"],
            "backend_scope": binding["backend_scope"],
            "samplers": options.get("samplers") or [SAFE_SAMPLER_FALLBACK],
            "schedulers": options.get("schedulers") or [SAFE_SCHEDULER_FALLBACK],
            "comfyui_url": getattr(active_client, "base_url", binding["url"]),
            "max_batch_size": _configured_max_batch_size(),
            "default_width": _configured_default_dimensions()["width"],
            "default_height": _configured_default_dimensions()["height"],
            "controlnet_models": (capabilities or {}).get("controlnet_models") or [],
            "upscale_models": (capabilities or {}).get("upscale_models") or [],
            "controlnet_types": (capabilities or {}).get("controlnet_types") or {},
            "generation_modes": (capabilities or {}).get("generation_modes") or [],
            "billing": None if not _comfyui_charge_required(actor) else (_comfyui_price_quote(1)[0] or {}),
            "wallet": _comfyui_wallet_payload(actor),
            "lora_extra_unit_price": COMFYUI_LORA_EXTRA_PRICE_POINTS,
        })

    @app.route("/api/comfyui/billing-quote", methods=["POST"])
    @require_csrf
    def comfyui_billing_quote():
        actor, err = _actor_or_401()
        if err:
            return err
        try:
            data = request.get_json(force=True)
        except Exception:
            return json_resp({"ok": False, "msg": "請求 JSON 格式錯誤"}), 400
        data = data if isinstance(data, dict) else {}
        data = {**data, "skip_asset_validation": True}
        params, msg = _normalize_generation_payload(data)
        if msg:
            return json_resp({"ok": False, "msg": msg}), 400
        if not _comfyui_charge_required(actor):
            return json_resp({"ok": True, "billing": {"charged": False, "exempt": "root"}, "wallet": _comfyui_wallet_payload(actor)})
        total_quantity, run_count = _comfyui_total_quantity(data, params)
        quote, msg = _comfyui_price_quote(total_quantity, lora_count=_comfyui_lora_count(params))
        if msg:
            return json_resp({"ok": False, "msg": msg}), 503
        quote = {**quote, "batch_size": params["batch_size"], "run_count": run_count}
        msg = _ensure_comfyui_balance(actor, quote)
        if msg:
            return json_resp({"ok": False, "msg": msg, "billing": quote, "wallet": _comfyui_wallet_payload(actor)}), 409
        return json_resp({"ok": True, "billing": quote, "wallet": _comfyui_wallet_payload(actor)})

    @app.route("/api/comfyui/generate", methods=["POST"])
    @require_csrf
    def comfyui_generate():
        actor, err = _actor_or_401()
        if err:
            return err
        data, uploaded_assets, request_msg = _parse_generation_request()
        if request_msg:
            return json_resp({"ok": False, "msg": request_msg}), 400
        request_data = data if isinstance(data, dict) else {}
        if uploaded_assets:
            request_data = {**request_data, "skip_asset_validation": True}
        params, msg = _normalize_generation_payload(request_data)
        if msg:
            return json_resp({"ok": False, "msg": msg}), 400
        backend_binding = _comfyui_binding(actor)
        active_client = _client_for_url(backend_binding["url"])
        try:
            params = _hydrate_generation_assets(actor, active_client, params, uploaded_assets)
            capabilities, capability_msg = _validate_generation_capabilities(active_client, params)
            if capability_msg:
                return json_resp({"ok": False, "msg": capability_msg, "capabilities": capabilities or {}}), 409
        except ComfyUIError as exc:
            return _json_error_from_comfy(exc, active_client)
        quote = None
        timeout_seconds = _int_range(
            data.get("timeout_seconds"),
            DEFAULT_GENERATION_TIMEOUT_SECONDS,
            30,
            MAX_GENERATION_TIMEOUT_SECONDS,
        )
        if _comfyui_charge_required(actor):
            quote, msg = _comfyui_price_quote(params["batch_size"], lora_count=_comfyui_lora_count(params))
            if msg:
                return json_resp({"ok": False, "msg": msg}), 503
            msg = _ensure_comfyui_balance(actor, quote)
            if msg:
                return json_resp({"ok": False, "msg": msg}), 409
            if not _coerce_bool(data.get("confirm_billing")):
                return json_resp({
                    "ok": False,
                    "msg": (
                        f"請先確認扣點：本次成功產圖將扣 {quote['total_price']} 點；"
                        "產圖失敗不扣點，丟棄預覽不退款。"
                    ),
                    "billing": {**quote, "confirmation_required": True},
                }), 409
        if _coerce_bool(data.get("async_progress")):
            job_id = _create_generation_job(actor)
            request_meta = _capture_request_audit_meta()
            worker = threading.Thread(
                target=_run_comfyui_generation_job,
                args=(job_id, dict(actor), params, quote, timeout_seconds, request_meta, backend_binding),
                daemon=True,
            )
            worker.start()
            return json_resp({
                "ok": True,
                "async": True,
                "job": {
                    "job_id": job_id,
                    "status": "queued",
                    "progress": {
                        "phase": "queued",
                        "percent": 0,
                        "detail": "已建立產圖工作",
                    },
                },
            })
        generation_token = _register_active_generation(
            actor,
            backend_url=backend_binding.get("url"),
            backend_scope=backend_binding.get("backend_scope"),
        )
        try:
            result = active_client.generate_image(
                params,
                timeout_seconds=timeout_seconds,
            )
        except ComfyUIError as exc:
            audit("COMFYUI_GENERATE_ERROR", get_client_ip(), user=actor["username"], success=False, ua=get_ua(), detail=str(exc)[:180])
            return _json_error_from_comfy(exc, active_client)
        finally:
            _unregister_active_generation(generation_token)
        billing = {"charged": False, "exempt": "root"} if not quote else None
        if quote:
            try:
                billing = _charge_comfyui_generation(actor, quote, prompt_id=result.get("prompt_id"))
            except Exception as exc:
                audit("COMFYUI_BILLING_ERROR", get_client_ip(), user=actor["username"], success=False, ua=get_ua(), detail=str(exc)[:180])
                return json_resp({"ok": False, "msg": f"產圖成功，但扣款失敗：{exc}"}), 409
        images = _finalize_generation_records(actor, params, result, backend_url=backend_binding.get("url"))
        history_id = None
        conn = get_db()
        try:
            history_id = _record_generation_history(
                conn,
                actor=actor,
                params=params,
                backend_url=backend_binding.get("url"),
                result_payload={
                    "prompt_id": result.get("prompt_id") or "",
                    "images": [
                        {
                            "image_ref": item.get("image_ref"),
                            "mime_type": item.get("mime_type"),
                            "size_bytes": item.get("size_bytes"),
                        }
                        for item in images
                    ],
                },
            )
            conn.commit()
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass
        finally:
            conn.close()
        image = images[0]
        image_ref = result["image_ref"]
        audit("COMFYUI_GENERATE", get_client_ip(), user=actor["username"], success=True, ua=get_ua(), detail=f"prompt_id={result['prompt_id']}, file={image_ref.get('filename')}, batch={len(images)}")
        return json_resp({
            "ok": True,
            "image": image,
            "images": images,
            "billing": billing,
            "history_id": history_id,
            "wallet": (billing or {}).get("wallet") or _comfyui_wallet_payload(actor),
            "backend_scope": backend_binding["backend_scope"],
        })

    @app.route("/api/comfyui/jobs/<job_id>", methods=["GET"])
    @require_csrf_safe
    def comfyui_generation_job_status(job_id):
        actor, err = _actor_or_401()
        if err:
            return err
        job, err = _assert_generation_job_owner(job_id, actor)
        if err:
            return err
        return json_resp({
            "ok": True,
            "job": {
                "job_id": job["job_id"],
                "status": job["status"],
                "progress": job.get("progress") or {},
                "error": job.get("error") or "",
                "result": job.get("result"),
            },
        })

    @app.route("/api/comfyui/history", methods=["GET"])
    @require_csrf_safe
    def comfyui_generation_history():
        actor, err = _actor_or_401()
        if err:
            return err
        conn = get_db()
        try:
            items = _list_generation_history(conn, actor=actor, limit=COMFYUI_HISTORY_LIMIT)
        finally:
            conn.close()
        return json_resp({"ok": True, "history": items})

    @app.route("/api/comfyui/history/<int:history_id>/rerun", methods=["POST"])
    @require_csrf
    def comfyui_generation_history_rerun(history_id):
        actor, err = _actor_or_401()
        if err:
            return err
        conn = get_db()
        try:
            item = _load_generation_history(conn, actor=actor, history_id=history_id)
        finally:
            conn.close()
        if not item:
            return json_resp({"ok": False, "msg": "找不到這筆 ComfyUI 歷史紀錄"}), 404
        payload = dict(item.get("payload") or {})
        input_assets = dict(item.get("input_assets") or {})
        controlnet = dict(item.get("controlnet") or {})
        if controlnet:
            controlnet["image_ref"] = input_assets.get("control_image_ref")
            payload["controlnet"] = controlnet
        payload["source_image_ref"] = input_assets.get("source_image_ref")
        payload["mask_image_ref"] = input_assets.get("mask_image_ref")
        payload["async_progress"] = True
        payload["confirm_billing"] = True
        payload["timeout_seconds"] = DEFAULT_GENERATION_TIMEOUT_SECONDS
        active_client = _client_for_url(_comfyui_binding(actor, backend_url=item.get("backend_url")).get("url"))
        try:
            capabilities, capability_msg = _validate_generation_capabilities(active_client, payload)
            if capability_msg:
                return json_resp({"ok": False, "msg": capability_msg, "capabilities": capabilities or {}}), 409
        except ComfyUIError as exc:
            return _json_error_from_comfy(exc, active_client)
        quote = None
        if _comfyui_charge_required(actor):
            quote, msg = _comfyui_price_quote(payload.get("batch_size") or 1, lora_count=_comfyui_lora_count(payload))
            if msg:
                return json_resp({"ok": False, "msg": msg}), 503
            msg = _ensure_comfyui_balance(actor, quote)
            if msg:
                return json_resp({"ok": False, "msg": msg}), 409
        job_id = _create_generation_job(actor)
        request_meta = _capture_request_audit_meta()
        worker = threading.Thread(
            target=_run_comfyui_generation_job,
            args=(job_id, dict(actor), payload, quote, DEFAULT_GENERATION_TIMEOUT_SECONDS, request_meta, _comfyui_binding(actor, backend_url=item.get("backend_url"))),
            daemon=True,
        )
        worker.start()
        return json_resp({
            "ok": True,
            "async": True,
            "job": {
                "job_id": job_id,
                "status": "queued",
                "progress": {"phase": "queued", "percent": 0, "detail": "已建立重跑工作"},
            },
        })

