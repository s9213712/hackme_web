"""§8 ComfyUI Template Importer — preview / import / consume endpoints.

Wired into routes/comfyui.py via ``register_comfyui_template_routes(app, ctx)``,
following the same dependency-injection pattern as the rest of
routes/comfyui_sections/.

Spec reference: docs/comfyui/COMFYUI_TEMPLATE_IMPORTER_PLAN.md §8.
"""

from __future__ import annotations

import json

from services.comfyui.template import (
    PREVIEW_TOKEN_TTL_SECONDS,
    analyze_workflow_json,
    build_ui_schema,
    check_workflow_capability,
    get_default_preview_store,
)
from services.comfyui.validation.rules import (
    WORKFLOW_MAX_JSON_BYTES,
    WorkflowValidationError,
)
from services.comfyui.validation.sanitize import sanitize_workflow_json


def register_comfyui_template_routes(app, ctx):
    """Register §8 preview endpoint on `app`.

    `ctx` mirrors the convention used by workflow_routes.py / admin_routes.py:
    every route-layer dependency is passed in by name so this module stays
    side-effect-free at import time and easy to unit test.

    Required ctx keys:
      - actor_or_401, json_resp, require_csrf, get_client_ip, get_ua, audit,
        comfyui_binding, client_for_url, request
    Optional ctx keys (override for tests):
      - preview_store: PreviewStore instance (defaults to module singleton)
    """
    actor_or_401 = ctx["actor_or_401"]
    json_resp = ctx["json_resp"]
    require_csrf = ctx["require_csrf"]
    get_client_ip = ctx["get_client_ip"]
    get_ua = ctx["get_ua"]
    audit = ctx["audit"]
    comfyui_binding = ctx["comfyui_binding"]
    client_for_url = ctx["client_for_url"]
    request = ctx["request"]
    # Use `is None` check, not `or` — InMemoryPreviewStore has __len__ so an
    # empty store evaluates falsy and would silently fall through to the
    # module singleton.
    preview_store = ctx.get("preview_store")
    if preview_store is None:
        preview_store = get_default_preview_store()

    def _err(msg, *, status=400, stage="", **extra):
        payload = {"ok": False, "msg": msg}
        if stage:
            payload["stage"] = stage
        payload.update(extra)
        return json_resp(payload), status

    def _audit_preview(actor, *, success, stage="", **detail):
        audit(
            "COMFYUI_TEMPLATE_PREVIEW_FAIL" if not success else "COMFYUI_TEMPLATE_PREVIEW_PASS",
            get_client_ip(),
            user=(actor or {}).get("username") or "-",
            success=success,
            ua=get_ua(),
            detail=" ".join(f"{k}={v}" for k, v in {"stage": stage, **detail}.items() if v),
        )

    @app.route("/api/comfyui/templates/preview", methods=["POST"])
    @require_csrf
    def comfyui_templates_preview():
        actor, err = actor_or_401()
        if err:
            return err

        # ----- Parse the body --------------------------------------------------
        # Two shapes accepted:
        #   1. Content-Type: application/json with body { "workflow": {...} }
        #      OR { "workflow_text": "..." } (raw API-format JSON string).
        #   2. multipart/form-data with a single ``workflow`` file part.
        raw_text: str | None = None
        if request.content_type and "multipart/form-data" in request.content_type:
            uploaded = request.files.get("workflow")
            if uploaded is None:
                _audit_preview(actor, success=False, stage="parse")
                return _err("缺少 workflow 檔案", stage="parse")
            try:
                blob = uploaded.read()
            except Exception:
                blob = b""
            if not blob:
                _audit_preview(actor, success=False, stage="parse")
                return _err("workflow 檔案為空", stage="parse")
            if len(blob) > WORKFLOW_MAX_JSON_BYTES:
                _audit_preview(actor, success=False, stage="parse")
                return _err(
                    f"workflow 大小超過 {WORKFLOW_MAX_JSON_BYTES // 1024}KB 上限",
                    stage="parse",
                )
            try:
                raw_text = blob.decode("utf-8")
            except UnicodeDecodeError:
                _audit_preview(actor, success=False, stage="parse")
                return _err("workflow 必須是 UTF-8 編碼的 JSON 文字", stage="parse")
        else:
            try:
                body = request.get_json(force=True, silent=False)
            except Exception:
                _audit_preview(actor, success=False, stage="parse")
                return _err("workflow 必須是 JSON", stage="parse")
            if not isinstance(body, dict):
                _audit_preview(actor, success=False, stage="parse")
                return _err("workflow 必須是 JSON 物件", stage="parse")
            workflow_inline = body.get("workflow")
            workflow_text = body.get("workflow_text")
            if isinstance(workflow_inline, dict):
                raw_text = json.dumps(workflow_inline, ensure_ascii=False)
            elif isinstance(workflow_text, str) and workflow_text.strip():
                raw_text = workflow_text
            else:
                _audit_preview(actor, success=False, stage="parse")
                return _err(
                    "請提供 workflow（dict）或 workflow_text（API-format JSON 字串）",
                    stage="parse",
                )

        if raw_text is None or not raw_text.strip():
            _audit_preview(actor, success=False, stage="parse")
            return _err("workflow 內容為空", stage="parse")

        # ----- Decode JSON -----------------------------------------------------
        try:
            workflow = json.loads(raw_text)
        except json.JSONDecodeError as exc:
            _audit_preview(actor, success=False, stage="parse")
            return _err(
                f"workflow JSON 格式錯誤：{exc.msg}（行 {exc.lineno}）。"
                f"請確認上傳的是 ComfyUI API format（不是 UI graph）。",
                stage="parse",
            )

        # ----- Sanitize (§3 + §7) ---------------------------------------------
        # sanitize_workflow_json wraps the cleaned graph in a dict like
        # ``{"workflow_json": ..., "workflow_hash": ..., **summary}`` (see
        # services/comfyui/validation/sanitize.py); we keep the wrapper around
        # for the import flow but pass the inner dict to the analyzer.
        try:
            sanitized_wrapper = sanitize_workflow_json(workflow)
        except WorkflowValidationError as exc:
            _audit_preview(actor, success=False, stage="sanitize")
            return _err(str(exc), stage="sanitize")
        workflow = sanitized_wrapper.get("workflow_json") or {}

        # ----- Analyze (§5) ----------------------------------------------------
        try:
            analysis = analyze_workflow_json(workflow)
        except WorkflowValidationError as exc:
            _audit_preview(actor, success=False, stage="analyze")
            return _err(str(exc), stage="analyze")

        # ----- Block on explicit denylist (§4.3) ------------------------------
        if analysis.has_blocking_classes():
            _audit_preview(
                actor,
                success=False,
                stage="allowlist",
                denied=",".join(sorted(analysis.denied_classes)),
            )
            return _err(
                f"workflow 含明確拒絕的節點類型：{sorted(analysis.denied_classes)}。"
                f"第一版不支援這些類別（見 §4.3）。",
                stage="allowlist",
                denied_classes=sorted(analysis.denied_classes),
            )

        # ----- Capability check (§6) ------------------------------------------
        binding = comfyui_binding(actor)
        client = None
        try:
            client = client_for_url(binding) if binding else None
        except Exception:
            client = None
        capability = check_workflow_capability(analysis, client=client)

        # ----- Build the UI schema (§9) ---------------------------------------
        schema = build_ui_schema(analysis=analysis, capability=capability, raw_workflow=workflow)

        # ----- Persist preview token (§8.2) -----------------------------------
        token = preview_store.put(
            user_id=int(actor["id"]),
            payload={
                "workflow": workflow,
                "analysis_class_types": sorted(analysis.class_types),
                "capability": capability.to_dict(),
                "ui_schema": schema.to_dict(),
            },
        )
        _audit_preview(
            actor,
            success=True,
            stage="ok",
            classes=len(analysis.class_types),
            unsupported=len(capability.unsupported),
            overall=capability.overall,
        )
        return json_resp(
            {
                "ok": True,
                "preview_token": token,
                "preview_token_ttl_seconds": int(PREVIEW_TOKEN_TTL_SECONDS),
                "ui_schema": schema.to_dict(),
                "capability": capability.to_dict(),
            }
        )


__all__ = ["register_comfyui_template_routes"]
