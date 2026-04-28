import base64
import mimetypes
import os
import re
import secrets
from io import BytesIO

from flask import request

from services.cloud_drive import ensure_cloud_drive_attachment_schema, store_cloud_upload
from services.comfyui_client import ComfyUIClient, ComfyUIError
from services.storage_albums import create_storage_file_entry, ensure_storage_album_schema


DEFAULT_COMFYUI_URL = os.environ.get("COMFYUI_API_URL", "http://127.0.0.1:8192")
DEFAULT_COMFYUI_PORT = 8192
SAFE_SAMPLER_FALLBACK = "euler"
SAFE_SCHEDULER_FALLBACK = "normal"


class _MemoryFile:
    def __init__(self, data, filename, mimetype):
        self.stream = BytesIO(data)
        self.filename = filename
        self.mimetype = mimetype


def register_comfyui_routes(app, deps):
    get_current_user_ctx = deps["get_current_user_ctx"]
    get_db = deps["get_db"]
    get_member_level_rule = deps["get_member_level_rule"]
    get_client_ip = deps.get("get_client_ip", lambda: "")
    get_ua = deps.get("get_ua", lambda: "")
    audit = deps.get("audit", lambda *args, **kwargs: None)
    json_resp = deps["json_resp"]
    require_csrf = deps.get("require_csrf", deps["require_csrf_safe"])
    require_csrf_safe = deps["require_csrf_safe"]
    storage_root = deps.get("STORAGE_DIR", ".")
    get_system_settings = deps.get("get_system_settings", lambda: {})
    injected_client = deps.get("comfyui_client")

    def _actor_or_401():
        actor = get_current_user_ctx()
        if not actor:
            return None, json_resp({"ok": False, "msg": "請先登入"}, 401)
        settings = get_system_settings() or {}
        if settings.get("feature_comfyui_enabled") is False:
            return None, json_resp({"ok": False, "msg": "ComfyUI 產圖功能目前未啟用"}, 403)
        return actor, None

    def _actor_value(actor, key, default=None):
        if not actor:
            return default
        try:
            return actor[key]
        except Exception:
            return actor.get(key, default) if hasattr(actor, "get") else default

    def _configured_comfyui_url():
        settings = get_system_settings() or {}
        try:
            port = int(settings.get("comfyui_api_port") or DEFAULT_COMFYUI_PORT)
        except Exception:
            port = DEFAULT_COMFYUI_PORT
        port = min(65535, max(1, port))
        return f"http://127.0.0.1:{port}"

    def _client():
        return injected_client or ComfyUIClient(_configured_comfyui_url())

    def _json_error_from_comfy(exc, active_client=None):
        active_client = active_client or _client()
        return json_resp({"ok": False, "msg": str(exc), "comfyui_url": getattr(active_client, "base_url", _configured_comfyui_url())}), 503

    def _int_range(value, default, minimum, maximum, *, multiple_of=None):
        try:
            number = int(value)
        except Exception:
            number = default
        number = max(minimum, min(maximum, number))
        if multiple_of:
            number = max(minimum, (number // multiple_of) * multiple_of)
        return number

    def _float_range(value, default, minimum, maximum):
        try:
            number = float(value)
        except Exception:
            number = default
        return max(minimum, min(maximum, number))

    def _clean_filename(name, fallback="comfyui.png"):
        text = str(name or "").strip()
        text = text.split("/")[-1].split("\\")[-1]
        text = re.sub(r"[^A-Za-z0-9_.-]+", "_", text)
        if not text:
            text = fallback
        if "." not in text:
            text += ".png"
        return text[:120]

    def _normalize_generation_payload(data):
        prompt = str(data.get("prompt") or "").strip()
        if not prompt:
            return None, "請輸入提示詞"
        if len(prompt) > 3000:
            return None, "提示詞最多 3000 字"
        negative = str(data.get("negative_prompt") or "").strip()
        if len(negative) > 3000:
            return None, "負面提示詞最多 3000 字"
        model = str(data.get("model") or "").strip()
        if not model:
            return None, "請選擇模型"
        seed = _int_range(data.get("seed"), secrets.randbits(32), 0, 2**63 - 1)
        params = {
            "model": model,
            "prompt": prompt,
            "negative_prompt": negative,
            "width": _int_range(data.get("width"), 512, 64, 2048, multiple_of=8),
            "height": _int_range(data.get("height"), 512, 64, 2048, multiple_of=8),
            "steps": _int_range(data.get("steps"), 20, 1, 80),
            "cfg": _float_range(data.get("cfg"), 7.0, 1.0, 30.0),
            "sampler_name": str(data.get("sampler_name") or SAFE_SAMPLER_FALLBACK).strip() or SAFE_SAMPLER_FALLBACK,
            "scheduler": str(data.get("scheduler") or SAFE_SCHEDULER_FALLBACK).strip() or SAFE_SCHEDULER_FALLBACK,
            "seed": seed,
            "filename_prefix": _clean_filename(data.get("filename_prefix") or "hackme_web", fallback="hackme_web").rsplit(".", 1)[0],
        }
        return params, None

    @app.route("/api/comfyui/models", methods=["GET"])
    @require_csrf_safe
    def comfyui_models():
        actor, err = _actor_or_401()
        if err:
            return err
        active_client = _client()
        try:
            models = active_client.get_models()
            options = active_client.get_sampler_options()
        except ComfyUIError as exc:
            return _json_error_from_comfy(exc, active_client)
        return json_resp({
            "ok": True,
            "models": models,
            "samplers": options.get("samplers") or [SAFE_SAMPLER_FALLBACK],
            "schedulers": options.get("schedulers") or [SAFE_SCHEDULER_FALLBACK],
            "comfyui_url": getattr(active_client, "base_url", _configured_comfyui_url()),
        })

    @app.route("/api/comfyui/generate", methods=["POST"])
    @require_csrf
    def comfyui_generate():
        actor, err = _actor_or_401()
        if err:
            return err
        try:
            data = request.get_json(force=True)
        except Exception:
            return json_resp({"ok": False, "msg": "Invalid JSON"}), 400
        params, msg = _normalize_generation_payload(data if isinstance(data, dict) else {})
        if msg:
            return json_resp({"ok": False, "msg": msg}), 400
        active_client = _client()
        try:
            result = active_client.generate_image(params, timeout_seconds=_int_range(data.get("timeout_seconds"), 180, 30, 300))
        except ComfyUIError as exc:
            audit("COMFYUI_GENERATE_ERROR", get_client_ip(), user=actor["username"], success=False, ua=get_ua(), detail=str(exc)[:180])
            return _json_error_from_comfy(exc, active_client)
        data_url = f"data:{result['mime_type']};base64,{base64.b64encode(result['data']).decode('ascii')}"
        image_ref = result["image_ref"]
        audit("COMFYUI_GENERATE", get_client_ip(), user=actor["username"], success=True, ua=get_ua(), detail=f"prompt_id={result['prompt_id']}, file={image_ref.get('filename')}")
        return json_resp({
            "ok": True,
            "image": {
                "prompt_id": result["prompt_id"],
                "image_ref": image_ref,
                "mime_type": result["mime_type"],
                "size_bytes": len(result["data"]),
                "data_url": data_url,
                "seed": params["seed"],
                "model": params["model"],
            },
        })

    @app.route("/api/comfyui/save", methods=["POST"])
    @require_csrf
    def comfyui_save():
        actor, err = _actor_or_401()
        if err:
            return err
        try:
            data = request.get_json(force=True)
        except Exception:
            return json_resp({"ok": False, "msg": "Invalid JSON"}), 400
        data = data if isinstance(data, dict) else {}
        image_ref = data.get("image_ref")
        if not isinstance(image_ref, dict):
            return json_resp({"ok": False, "msg": "缺少 image_ref"}), 400
        active_client = _client()
        try:
            image = active_client.fetch_image(image_ref)
        except ComfyUIError as exc:
            return _json_error_from_comfy(exc, active_client)
        filename = _clean_filename(data.get("display_name") or image.filename)
        guessed_mime = mimetypes.guess_type(filename)[0] or image.mime_type or "image/png"
        memory_file = _MemoryFile(image.data, filename, guessed_mime)
        conn = get_db()
        try:
            ensure_cloud_drive_attachment_schema(conn)
            ensure_storage_album_schema(conn)
            rule = get_member_level_rule(conn, _actor_value(actor, "effective_level") or _actor_value(actor, "member_level"))
            upload_result, msg = store_cloud_upload(
                conn,
                actor=actor,
                member_rule=rule,
                storage_root=storage_root,
                file_storage=memory_file,
                privacy_mode="private_scannable",
                scan_now=True,
            )
            if msg:
                conn.rollback()
                return json_resp({"ok": False, "msg": msg}), 400
            file_row = conn.execute("SELECT * FROM uploaded_files WHERE id=?", (upload_result["file_id"],)).fetchone()
            virtual_path = str(data.get("virtual_path") or "").strip()
            if not virtual_path:
                virtual_path = f"/ComfyUI/{filename}"
            storage_file, msg = create_storage_file_entry(
                conn,
                actor=actor,
                file_row=file_row,
                virtual_path=virtual_path,
                display_name=filename,
                source="comfyui",
            )
            if msg:
                conn.rollback()
                return json_resp({"ok": False, "msg": msg}), 400
            conn.commit()
            audit("COMFYUI_SAVE_TO_DRIVE", get_client_ip(), user=actor["username"], success=True, ua=get_ua(), detail=f"file_id={upload_result['file_id']}, storage_file_id={storage_file['id']}")
            return json_resp({"ok": True, "file": upload_result, "storage_file": storage_file})
        finally:
            conn.close()
