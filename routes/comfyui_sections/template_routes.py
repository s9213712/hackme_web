"""§8 ComfyUI Template Importer — preview / import / consume endpoints.

Wired into routes/comfyui.py via ``register_comfyui_template_routes(app, ctx)``,
following the same dependency-injection pattern as the rest of
routes/comfyui_sections/.

Spec reference: docs/comfyui/COMFYUI_TEMPLATE_IMPORTER_PLAN.md §8.
"""

from __future__ import annotations

import json
import re
import shutil
from datetime import datetime
from pathlib import Path

from services.comfyui.template import (
    DatabasePreviewStore,
    PREVIEW_TOKEN_TTL_SECONDS,
    REPO_SOURCE_DIR,
    analyze_workflow_json,
    build_ui_schema,
    check_workflow_capability,
    get_default_preview_store,
    normalize_uploaded_workflow_json,
    runtime_comfyui_dir,
)
from services.comfyui.validation.rules import (
    WORKFLOW_MAX_JSON_BYTES,
    WorkflowValidationError,
)
from services.comfyui.validation.sanitize import sanitize_workflow_json


def register_comfyui_template_routes(app, ctx):
    """Register §8 preview + import endpoints on `app`.

    `ctx` mirrors the convention used by workflow_routes.py / admin_routes.py:
    every route-layer dependency is passed in by name so this module stays
    side-effect-free at import time and easy to unit test.

    Required ctx keys (preview):
      - actor_or_401, json_resp, require_csrf, get_client_ip, get_ua, audit,
        comfyui_binding, client_for_url, request
    Required ctx keys (import) — supplied by routes/comfyui.py from the
    existing preset helpers:
      - get_db, actor_value, upsert_workflow_preset, load_workflow_preset_row,
        workflow_preset_summary
    Optional ctx keys (override for tests):
      - preview_store: PreviewStore instance (defaults to DB-backed storage
        when get_db is available, otherwise the module singleton)
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
    # Optional integration with the existing preset upsert helpers; the import
    # endpoint short-circuits when these are missing so unit tests of the
    # preview endpoint can omit them.
    get_db = ctx.get("get_db")
    # Use `is None` check, not `or` — InMemoryPreviewStore has __len__ so an
    # empty store evaluates falsy and would silently fall through to another
    # store. In production, prefer DB-backed storage so preview/import requests
    # survive multi-worker routing and short server restarts.
    preview_store = ctx.get("preview_store")
    if preview_store is None:
        preview_store = DatabasePreviewStore(get_db) if get_db is not None else get_default_preview_store()
    actor_value = ctx.get("actor_value")
    upsert_workflow_preset = ctx.get("upsert_workflow_preset")
    load_workflow_preset_row = ctx.get("load_workflow_preset_row")
    workflow_preset_summary = ctx.get("workflow_preset_summary")

    def _template_output_kinds(workflow_json):
        classes = {
            str((node or {}).get("class_type") or "").strip()
            for node in (workflow_json or {}).values()
            if isinstance(node, dict)
        }
        output_kinds = []
        if any(name in classes for name in {"SaveImage", "PreviewImage", "VAEDecode"}):
            output_kinds.append("image")
        if any("video" in name.lower() for name in classes):
            output_kinds.append("video")
        if any(token in name.lower() for name in classes for token in ("audio", "music", "wave", "wav")):
            output_kinds.append("music")
        if not output_kinds:
            output_kinds.append("image")
        return output_kinds

    def _slugify_template_name(text):
        normalized = re.sub(r"[^a-z0-9]+", "_", str(text or "").strip().lower())
        normalized = re.sub(r"_+", "_", normalized).strip("_")
        return normalized or "workflow"

    def _bundle_id_for_import(*, preset_id, title):
        return f"imported_{int(preset_id)}_{_slugify_template_name(title)}"

    def _write_json_file(path: Path, payload):
        path.write_text(
            json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )

    def _materialize_template_bundle(
        *,
        preset_id,
        actor,
        title,
        description,
        visibility,
        workflow_json,
        default_params,
        schema,
        capability,
        workflow_hash="",
    ):
        # User-imported workflows are runtime artifacts only. They MUST NOT be
        # written into REPO_SOURCE_DIR (= workflows/comfyui/), which is the
        # canonical read-only ship location for the 6 system workflow templates.
        # Writing imports there pollutes dev source trees with imported_*/
        # folders even when .gitignore hides them; runtime is the right home.
        bundle_id = _bundle_id_for_import(preset_id=preset_id, title=title)
        runtime_dir = Path(runtime_comfyui_dir()) / bundle_id
        output_kinds = _template_output_kinds(workflow_json)
        manifest = {
            "schema_version": 1,
            "id": bundle_id,
            "name": title,
            "description": description or "",
            "workflow_file": "workflow.json",
            "output_kinds": output_kinds,
            "source": "imported",
            "preset_id": int(preset_id),
            "visibility": str(visibility or "private"),
            "owner_username": _actor_field(actor, "username") or "",
            "workflow_hash": str(workflow_hash or ""),
            "default_params": default_params if isinstance(default_params, dict) else {},
            "capability": capability.to_dict() if capability is not None else {},
            "ui": {
                "initial_collapsed": True,
                "panels": (schema.to_dict().get("panels") if schema is not None else []) or [],
            },
        }
        readme = (
            f"# {title}\n\n"
            f"{description or 'Imported from a ComfyUI API-format workflow JSON.'}\n\n"
            f"- Source: `/api/comfyui/templates/import`\n"
            f"- Preset ID: `{preset_id}`\n"
            f"- Owner: `{_actor_field(actor, 'username') or '-'}\n"
            f"- Visibility: `{visibility or 'private'}`\n"
            f"- Imported At: `{datetime.now().isoformat()}`\n"
            f"- Files: `workflow.json` for ComfyUI, `manifest.json` for hackme_web card rendering.\n"
        )

        if runtime_dir.exists():
            shutil.rmtree(runtime_dir)
        runtime_dir.mkdir(parents=True, exist_ok=True)
        _write_json_file(runtime_dir / "workflow.json", workflow_json)
        _write_json_file(runtime_dir / "manifest.json", manifest)
        (runtime_dir / "README.md").write_text(readme, encoding="utf-8")
        return {
            "bundle_id": bundle_id,
            "runtime_dir": str(runtime_dir),
            "manifest": manifest,
        }

    def _err(msg, *, status=400, stage="", **extra):
        payload = {"ok": False, "msg": msg}
        if stage:
            payload["stage"] = stage
        payload.update(extra)
        return json_resp(payload), status

    def _actor_field(actor, key):
        """Read a field from actor whether it's a sqlite3.Row, dict, or None.

        sqlite3.Row supports __getitem__ but not .get(); dict supports both.
        """
        if actor is None:
            return None
        if actor_value is not None:
            return actor_value(actor, key)
        try:
            return actor[key]
        except (KeyError, IndexError, TypeError):
            return getattr(actor, key, None)

    def _audit_preview(actor, *, success, stage="", **detail):
        audit(
            "COMFYUI_TEMPLATE_PREVIEW_FAIL" if not success else "COMFYUI_TEMPLATE_PREVIEW_PASS",
            get_client_ip(),
            user=_actor_field(actor, "username") or "-",
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
                f"請確認上傳的是合法的 ComfyUI workflow JSON。",
                stage="parse",
            )

        try:
            workflow = normalize_uploaded_workflow_json(workflow)
        except WorkflowValidationError as exc:
            _audit_preview(actor, success=False, stage="normalize")
            return _err(str(exc), stage="normalize")

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
        # comfyui_binding returns a dict like {"url": "...", ...}; client_for_url
        # expects a bare URL string (matching all other call sites in routes/comfyui.py).
        binding = comfyui_binding(actor)
        binding_url = (binding or {}).get("url") if isinstance(binding, dict) else binding
        client = None
        try:
            client = client_for_url(binding_url) if binding_url else None
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

    # The import endpoint requires the preset-upsert helpers from routes/comfyui.py;
    # skip registration when ctx is missing them (e.g., preview-only unit tests).
    if not all([get_db, actor_value, upsert_workflow_preset, load_workflow_preset_row, workflow_preset_summary]):
        return

    @app.route("/api/comfyui/templates/import", methods=["POST"])
    @require_csrf
    def comfyui_templates_import():
        actor, err = actor_or_401()
        if err:
            return err

        try:
            body = request.get_json(force=True, silent=False)
        except Exception:
            audit(
                "COMFYUI_TEMPLATE_IMPORT_FAIL",
                get_client_ip(),
                user=_actor_field(actor, "username") or "-",
                success=False,
                ua=get_ua(),
                detail="stage=parse",
            )
            return _err("請以 JSON 格式提交", stage="parse")
        if not isinstance(body, dict):
            return _err("請以 JSON 物件格式提交", stage="parse")

        token = str(body.get("preview_token") or "").strip()
        if not token or not token.startswith("tkn_"):
            audit(
                "COMFYUI_TEMPLATE_IMPORT_FAIL",
                get_client_ip(),
                user=actor_value(actor, "username") or "-",
                success=False,
                ua=get_ua(),
                detail="stage=token",
            )
            return _err("缺少 preview_token；請先呼叫 /api/comfyui/templates/preview", stage="token")

        title = str(body.get("title") or "").strip()
        if not title:
            return _err("title 不可為空", stage="title")
        description = str(body.get("description") or "")
        visibility = str(body.get("visibility") or "private")
        default_params = body.get("default_params") if isinstance(body.get("default_params"), dict) else {}

        # Single-use redemption (§8.2: tokens 30-min TTL, never reused)
        entry = preview_store.consume(token=token, user_id=int(actor_value(actor, "id")))
        if entry is None:
            audit(
                "COMFYUI_TEMPLATE_IMPORT_FAIL",
                get_client_ip(),
                user=actor_value(actor, "username") or "-",
                success=False,
                ua=get_ua(),
                detail="stage=token_invalid",
            )
            return _err("preview_token 無效或已過期，請重新預覽 workflow", stage="token_invalid")

        # Defense in depth: re-sanitize + re-analyze + re-capability before write.
        # Even though preview did all of these, the workflow's been sitting in
        # an in-process store; cheap to verify it's still safe before commit.
        stored_workflow = entry.payload.get("workflow") or {}
        try:
            sanitized_wrapper = sanitize_workflow_json(stored_workflow)
        except WorkflowValidationError as exc:
            audit(
                "COMFYUI_TEMPLATE_IMPORT_FAIL",
                get_client_ip(),
                user=actor_value(actor, "username") or "-",
                success=False,
                ua=get_ua(),
                detail="stage=sanitize",
            )
            return _err(str(exc), stage="sanitize")

        sanitized_inner = sanitized_wrapper.get("workflow_json") or {}
        try:
            analysis = analyze_workflow_json(sanitized_inner)
        except WorkflowValidationError as exc:
            audit(
                "COMFYUI_TEMPLATE_IMPORT_FAIL",
                get_client_ip(),
                user=actor_value(actor, "username") or "-",
                success=False,
                ua=get_ua(),
                detail="stage=analyze",
            )
            return _err(str(exc), stage="analyze")

        if analysis.has_blocking_classes():
            audit(
                "COMFYUI_TEMPLATE_IMPORT_FAIL",
                get_client_ip(),
                user=actor_value(actor, "username") or "-",
                success=False,
                ua=get_ua(),
                detail="stage=allowlist",
            )
            return _err(
                f"workflow 含明確拒絕的節點類型：{sorted(analysis.denied_classes)}",
                stage="allowlist",
                denied_classes=sorted(analysis.denied_classes),
            )

        # Per §4: import requires SUPPORTED or PARTIALLY_SUPPORTED. UNSUPPORTED
        # (custom nodes missing locally, or hackme_web allowlist rejects a class
        # that's *present* locally) blocks at import; PARTIALLY_SUPPORTED is
        # allowed so the user can download missing models and try /run later.
        binding = comfyui_binding(actor)
        binding_url = (binding or {}).get("url") if isinstance(binding, dict) else binding
        client = None
        try:
            client = client_for_url(binding_url) if binding_url else None
        except Exception:
            client = None
        capability = check_workflow_capability(analysis, client=client)
        if capability.overall == "UNSUPPORTED":
            audit(
                "COMFYUI_TEMPLATE_IMPORT_FAIL",
                get_client_ip(),
                user=actor_value(actor, "username") or "-",
                success=False,
                ua=get_ua(),
                detail=f"stage=capability unsupported={capability.unsupported}",
            )
            return _err(
                f"workflow 在本地 ComfyUI 上不支援：{capability.unsupported}",
                stage="capability",
                unsupported=capability.unsupported,
                blockers=capability.blockers,
            )
        schema = build_ui_schema(
            analysis=analysis,
            capability=capability,
            raw_workflow=sanitized_inner,
        )

        # Persist as preset.
        conn = get_db()
        try:
            preset_id = upsert_workflow_preset(
                conn,
                preset_id=None,
                actor=actor,
                title=title,
                description=description,
                visibility=visibility,
                workflow_payload=sanitized_wrapper,
                default_params=default_params,
                is_official=False,
            )
            row = load_workflow_preset_row(conn, preset_id=preset_id)
            bundle_info = _materialize_template_bundle(
                preset_id=preset_id,
                actor=actor,
                title=title,
                description=description,
                visibility=visibility,
                workflow_json=sanitized_inner,
                default_params=(default_params or sanitized_wrapper.get("default_params") or {}),
                schema=schema,
                capability=capability,
                workflow_hash=sanitized_wrapper.get("workflow_hash") or "",
            )
            conn.commit()
        except Exception as exc:
            conn.rollback()
            audit(
                "COMFYUI_TEMPLATE_IMPORT_FAIL",
                get_client_ip(),
                user=actor_value(actor, "username") or "-",
                success=False,
                ua=get_ua(),
                detail=f"stage=bundle_write error={exc}",
            )
            return _err(f"模板 bundle 寫入失敗：{exc}", stage="bundle_write", status=500)
        finally:
            conn.close()

        audit(
            "COMFYUI_TEMPLATE_IMPORT_PASS",
            get_client_ip(),
            user=actor_value(actor, "username") or "-",
            success=True,
            ua=get_ua(),
            detail=f"preset_id={preset_id} overall={capability.overall} bundle_id={bundle_info['bundle_id']}",
        )
        return json_resp(
            {
                "ok": True,
                "preset_id": preset_id,
                "preset": workflow_preset_summary(row, actor=actor),
                "capability": capability.to_dict(),
                "bundle": {
                    "id": bundle_info["bundle_id"],
                    "runtime_dir": bundle_info["runtime_dir"],
                    "manifest": bundle_info["manifest"],
                },
            }
        )


__all__ = ["register_comfyui_template_routes"]
