import base64
import hashlib
import json
import mimetypes
import os
import ipaddress
import re
import secrets
import signal
import socket
import subprocess
import tempfile
import threading
import time
from datetime import datetime
from io import BytesIO
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlencode, urlparse, urlunparse
import urllib.error
import urllib.request

from routes.comfyui_sections.admin_helpers import build_comfyui_admin_helpers
from routes.comfyui_sections.billing_helpers import build_comfyui_billing_helpers
from routes.comfyui_sections import (
    register_comfyui_admin_routes,
    register_comfyui_image_routes,
    register_comfyui_runtime_routes,
    register_comfyui_template_routes,
    register_comfyui_workflow_routes,
)

from flask import request, send_file

from services.comfyui.settings import (
    DEFAULT_COMFYUI_PORT,
    normalize_comfyui_connection_mode,
    validate_comfyui_api_host,
    validate_comfyui_api_port,
    validate_comfyui_api_url,
)
from services.comfyui.api_nodes import build_comfyui_account_extra_data, detect_paid_api_nodes
from services.comfyui.node_catalog import build_node_catalog
from services.storage.cloud_drive import (
    attach_existing_file,
    can_download_file,
    ensure_cloud_drive_attachment_schema,
    resolve_file_storage_path,
    store_cloud_upload,
)
from services.platform.admin_validation import (
    validate_comfyui_api_host as shared_validate_comfyui_api_host,
    validate_comfyui_api_url as shared_validate_comfyui_api_url,
)
from services.comfyui.client import (
    CONTROLNET_TYPE_DEFINITIONS,
    GENERATION_MODE_DEFINITIONS,
    ComfyUIClient,
    ComfyUIError,
)
from services.comfyui.workflows import (
    WorkflowValidationError,
    extract_workflow_summary,
    sanitize_workflow_json,
    workflow_json_to_pretty_text,
)
from services.comfyui.template import (
    analyze_workflow_json,
    build_ui_schema,
    check_workflow_capability,
    runtime_comfyui_dir,
)
from services.comfyui.template.seeding import SYSTEM_WORKFLOW_IDS
from services.comfyui.validation.rules import (
    WORKFLOW_ABSOLUTE_PATH_RE,
    WORKFLOW_BLOCKED_COMMAND_RE,
    WORKFLOW_URL_RE,
)
from services.platform.release_info import APP_RELEASE_ID
from services.system.notifications import create_notification_if_enabled
from services.storage.storage_albums import (
    add_album_file,
    create_storage_file_entry,
    ensure_output_album,
    ensure_storage_album_schema,
)


DEFAULT_COMFYUI_URL = os.environ.get("COMFYUI_API_URL", "http://localhost:8192")
COMFYUI_LOCAL_START_TEMPLATE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "comfyui" / "comfyui_run_in_linux.template.sh"
SAFE_SAMPLER_FALLBACK = "euler"
SAFE_SCHEDULER_FALLBACK = "normal"
DEFAULT_GENERATION_TIMEOUT_SECONDS = 1800
MAX_GENERATION_TIMEOUT_SECONDS = 1800
COMFYUI_BASIC_PRICE_ITEM_KEY = "comfyui_txt2img_basic"
MAX_COMFYUI_FETCH_IMAGE_BYTES = 50 * 1024 * 1024
MAX_COMFYUI_LORAS_PER_PROMPT = 8
COMFYUI_LORA_EXTRA_PRICE_POINTS = 1
COMFYUI_VAE_BUILTIN = "__checkpoint_builtin__"
COMFYUI_MODEL_DOWNLOAD_EXTENSIONS = {".safetensors", ".ckpt", ".pt", ".pth", ".bin", ".gguf"}
COMFYUI_MODEL_DOWNLOAD_TYPES = {
    "checkpoint": ("checkpoints", "Checkpoint"),
    "diffusion_model": ("diffusion_models", "Diffusion Model / UNet"),
    "unet": ("diffusion_models", "Diffusion Model / UNet"),
    "text_encoder": ("text_encoders", "Text Encoder / CLIP / T5 / Qwen"),
    "clip": ("clip", "CLIP / Text Encoder (legacy)"),
    "clip_vision": ("clip_vision", "CLIP Vision"),
    "lora": ("loras", "LoRA"),
    "embedding": ("embeddings", "Embedding / Textual Inversion"),
    "vae": ("vae", "VAE"),
    "audio": ("audio", "Audio / TTS"),
    "video": ("video", "Video / Motion"),
    "controlnet": ("controlnet", "ControlNet"),
    "upscale": ("upscale_models", "放大模型"),
}
COMFYUI_SUPPORTED_LORA_BASE_MODEL_FAMILIES = {"sdxl", "pony", "illustrious", "noob"}
MAX_COMFYUI_MODEL_DOWNLOAD_BYTES = int(os.environ.get("COMFYUI_MODEL_DOWNLOAD_MAX_BYTES", str(20 * 1024 * 1024 * 1024)))
CIVITAI_ALLOWED_HOSTS = {
    "civitai.com",
    "www.civitai.com",
    "civitai.red",
    "www.civitai.red",
    "civitai.green",
    "www.civitai.green",
}
CIVITAI_API_BASE = os.environ.get("CIVITAI_API_BASE", "https://civitai.com/api/v1").rstrip("/")
def _configured_civitai_api_bases():
    raw = os.environ.get("CIVITAI_API_BASES", "")
    if raw.strip():
        candidates = [item.strip().rstrip("/") for item in raw.split(",")]
    else:
        candidates = [CIVITAI_API_BASE, "https://civitai.red/api/v1"]
    bases = []
    seen = set()
    for item in candidates:
        if not item or item in seen:
            continue
        parsed = urlparse(item)
        host = (parsed.hostname or "").lower()
        if parsed.scheme != "https" or host not in CIVITAI_ALLOWED_HOSTS:
            continue
        bases.append(item)
        seen.add(item)
    return bases or [CIVITAI_API_BASE]

CIVITAI_API_BASES = _configured_civitai_api_bases()
CIVITAI_MODEL_TYPE_TO_DOWNLOAD_TYPE = {
    "checkpoint": "checkpoint",
    "model": "checkpoint",
    "diffusionmodel": "diffusion_model",
    "diffusion_model": "diffusion_model",
    "unet": "diffusion_model",
    "textencoder": "text_encoder",
    "text_encoder": "text_encoder",
    "clip": "clip",
    "clipvision": "clip_vision",
    "clip_vision": "clip_vision",
    "lora": "lora",
    "textualinversion": "embedding",
    "embedding": "embedding",
    "vae": "vae",
    "audio": "audio",
    "video": "video",
    "controlnet": "controlnet",
    "upscaler": "upscale",
    "upscale": "upscale",
}
CIVITAI_SEARCH_TYPE_TO_API = {
    "checkpoint": "Checkpoint",
    "lora": "LORA",
    "embedding": "TextualInversion",
    "controlnet": "Controlnet",
    "upscale": "Upscaler",
}
COMFYUI_EMBEDDING_TOKEN_RE = re.compile(r"<\s*embeddings\s*:\s*([^<>]+?)\s*>", re.IGNORECASE)
COMFYUI_ALLOWED_IMAGE_MIME_TYPES = {
    "image/png",
    "image/jpeg",
    "image/webp",
}
COMFYUI_ALLOWED_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}
COMFYUI_HISTORY_LIMIT = 20
COMFYUI_WORKFLOW_PRESET_LIMIT = 50
COMFYUI_WORKFLOW_RUN_LIMIT = 8
COMFYUI_WORKFLOW_VISIBILITY_VALUES = {"private", "public"}
COMFYUI_WORKFLOW_PURPOSE_VALUES = {
    "txt2img",
    "img2img",
    "inpaint",
    "outpaint",
    "upscale",
    "t2v",
    "i2v",
    "v2v",
    "t2s",
    "t2sv",
    "controlnet",
    "custom",
}
COMFYUI_WORKFLOW_SCHEMA_VERSION = "1"
COMFYUI_WORKFLOW_LAYOUT_MAX_JSON_BYTES = 64_000
COMFYUI_CORE_WORKFLOW_NODE_CLASSES = {
    "CheckpointLoaderSimple",
    "CLIPTextEncode",
    "CLIPSetLastLayer",
    "ConditioningConcat",
    "ConditioningAverage",
    "ConditioningCombine",
    "ConditioningZeroOut",
    "VAELoader",
    "VAEEncode",
    "VAEEncodeForInpaint",
    "VAEDecode",
    "KSampler",
    "KSamplerAdvanced",
    "EmptyLatentImage",
    "LatentUpscale",
    "LatentUpscaleBy",
    "LoadImage",
    "LoadImageMask",
    "SaveImage",
    "PreviewImage",
    "LoraLoader",
    "ControlNetLoader",
    "ControlNetApply",
    "ControlNetApplyAdvanced",
    "ImagePadForOutpaint",
    "UpscaleModelLoader",
    "ImageUpscaleWithModel",
}


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
    points_service = deps.get("points_service")
    active_generations = deps.get("comfyui_active_generations") or {}
    active_generations_lock = deps.get("comfyui_active_generations_lock") or threading.Lock()
    generation_jobs = deps.get("comfyui_generation_jobs") or {}
    generation_jobs_lock = deps.get("comfyui_generation_jobs_lock") or threading.Lock()
    model_download_jobs = deps.get("comfyui_model_download_jobs") or {}
    model_download_jobs_lock = deps.get("comfyui_model_download_jobs_lock") or threading.Lock()

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

    def _image_ref_payload(image_ref):
        if not isinstance(image_ref, dict):
            return None
        filename = str(image_ref.get("filename") or "").strip()
        image_type = str(image_ref.get("type") or "output").strip() or "output"
        subfolder = str(image_ref.get("subfolder") or "").strip()
        if not filename or "/" in filename or "\\" in filename or ".." in filename:
            return None
        if image_type not in {"input", "output", "temp"}:
            return None
        if subfolder.startswith("/") or subfolder.startswith("\\") or ".." in subfolder.replace("\\", "/").split("/"):
            return None
        return {"filename": filename, "subfolder": subfolder, "type": image_type}

    def _image_ref_key(image_ref):
        payload = _image_ref_payload(image_ref)
        if payload is None:
            return None
        raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(raw).hexdigest()

    def _ensure_comfyui_image_ref_schema(conn):
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS comfyui_image_refs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ref_key TEXT NOT NULL UNIQUE,
                owner_user_id INTEGER NOT NULL,
                prompt_id TEXT,
                backend_url TEXT NOT NULL DEFAULT '',
                image_ref_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                last_used_at TEXT
            )
            """
        )
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(comfyui_image_refs)").fetchall()}
        if "backend_url" not in columns:
            conn.execute("ALTER TABLE comfyui_image_refs ADD COLUMN backend_url TEXT NOT NULL DEFAULT ''")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_comfyui_image_refs_owner ON comfyui_image_refs(owner_user_id, created_at)")

    def _register_comfyui_image_refs(conn, *, actor, images, backend_url=""):
        _ensure_comfyui_image_ref_schema(conn)
        now = datetime.now().isoformat()
        normalized_backend_url = _normalize_comfyui_backend_url(backend_url)
        for item in images:
            image_ref = item.get("image_ref") if isinstance(item, dict) else None
            payload = _image_ref_payload(image_ref)
            ref_key = _image_ref_key(payload)
            if not payload or not ref_key:
                continue
            conn.execute(
                """
                INSERT INTO comfyui_image_refs (ref_key, owner_user_id, prompt_id, backend_url, image_ref_json, created_at, last_used_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(ref_key) DO UPDATE SET
                    owner_user_id=excluded.owner_user_id,
                    prompt_id=excluded.prompt_id,
                    backend_url=excluded.backend_url,
                    image_ref_json=excluded.image_ref_json,
                    last_used_at=excluded.last_used_at
                """,
                (
                    ref_key,
                    int(_actor_value(actor, "id")),
                    str(item.get("prompt_id") or ""),
                    normalized_backend_url,
                    json.dumps(payload, ensure_ascii=False, sort_keys=True),
                    now,
                    now,
                ),
            )

    def _load_comfyui_image_ref_record(conn, *, actor, image_ref, prompt_id=None):
        _ensure_comfyui_image_ref_schema(conn)
        ref_key = _image_ref_key(image_ref)
        if not ref_key:
            return None
        row = conn.execute(
            "SELECT owner_user_id, prompt_id, backend_url FROM comfyui_image_refs WHERE ref_key=?",
            (ref_key,),
        ).fetchone()
        if not row or int(row["owner_user_id"]) != int(_actor_value(actor, "id")):
            return None
        if prompt_id and row["prompt_id"] and str(row["prompt_id"]) != str(prompt_id):
            return None
        conn.execute("UPDATE comfyui_image_refs SET last_used_at=? WHERE ref_key=?", (datetime.now().isoformat(), ref_key))
        return dict(row)

    def _verify_comfyui_image_ref_owner(conn, *, actor, image_ref, prompt_id=None):
        return bool(_load_comfyui_image_ref_record(conn, actor=actor, image_ref=image_ref, prompt_id=prompt_id))

    def _ensure_comfyui_generation_history_schema(conn):
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS comfyui_generation_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                owner_user_id INTEGER NOT NULL,
                backend_url TEXT NOT NULL DEFAULT '',
                generation_mode TEXT NOT NULL DEFAULT 'txt2img',
                payload_json TEXT NOT NULL,
                input_assets_json TEXT NOT NULL DEFAULT '{}',
                controlnet_json TEXT NOT NULL DEFAULT '{}',
                result_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_comfyui_generation_history_owner ON comfyui_generation_history(owner_user_id, created_at DESC)"
        )

    def _record_generation_history(conn, *, actor, params, backend_url="", result_payload=None):
        _ensure_comfyui_generation_history_schema(conn)
        now = datetime.now().isoformat()
        payload = {
            "generation_mode": params.get("generation_mode") or "txt2img",
            "model": params.get("model") or "",
            "prompt": params.get("prompt") or "",
            "negative_prompt": params.get("negative_prompt") or "",
            "width": int(params.get("width") or 0),
            "height": int(params.get("height") or 0),
            "steps": int(params.get("steps") or 0),
            "cfg": float(params.get("cfg") or 0),
            "sampler_name": params.get("sampler_name") or "",
            "scheduler": params.get("scheduler") or "",
            "seed": int(params.get("seed") or 0),
            "batch_size": int(params.get("batch_size") or 1),
            "filename_prefix": params.get("filename_prefix") or "hackme_web",
            "loras": list(params.get("loras") or []),
            "vae": params.get("vae") or "",
            "denoise_strength": float(params.get("denoise_strength") or 0),
            "upscale_model": params.get("upscale_model") or "",
            "outpaint": dict(params.get("outpaint") or {}),
        }
        input_assets = {
            "source_image_ref": params.get("source_image_ref"),
            "mask_image_ref": params.get("mask_image_ref"),
            "control_image_ref": ((params.get("controlnet") or {}).get("image_ref") if isinstance(params.get("controlnet"), dict) else None),
        }
        cur = conn.execute(
            """
            INSERT INTO comfyui_generation_history (
                owner_user_id, backend_url, generation_mode, payload_json,
                input_assets_json, controlnet_json, result_json, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                int(_actor_value(actor, "id")),
                _normalize_comfyui_backend_url(backend_url),
                str(payload["generation_mode"] or "txt2img"),
                json.dumps(payload, ensure_ascii=False, sort_keys=True),
                json.dumps(input_assets, ensure_ascii=False, sort_keys=True),
                json.dumps(params.get("controlnet") or {}, ensure_ascii=False, sort_keys=True),
                json.dumps(result_payload or {}, ensure_ascii=False, sort_keys=True),
                now,
                now,
            ),
        )
        return cur.lastrowid

    def _list_generation_history(conn, *, actor, limit=COMFYUI_HISTORY_LIMIT):
        _ensure_comfyui_generation_history_schema(conn)
        rows = conn.execute(
            """
            SELECT * FROM comfyui_generation_history
            WHERE owner_user_id=?
            ORDER BY created_at DESC, id DESC
            LIMIT ?
            """,
            (int(_actor_value(actor, "id")), int(limit)),
        ).fetchall()
        items = []
        for row in rows:
            payload = _parse_json_field(row["payload_json"], {})
            input_assets = _parse_json_field(row["input_assets_json"], {})
            controlnet = _parse_json_field(row["controlnet_json"], {})
            result_json = _parse_json_field(row["result_json"], {})
            items.append({
                "id": int(row["id"]),
                "generation_mode": row["generation_mode"],
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
                "payload": payload,
                "input_assets": input_assets,
                "controlnet": controlnet,
                "result": result_json,
            })
        return items

    def _load_generation_history(conn, *, actor, history_id):
        _ensure_comfyui_generation_history_schema(conn)
        row = conn.execute(
            "SELECT * FROM comfyui_generation_history WHERE id=? AND owner_user_id=?",
            (int(history_id), int(_actor_value(actor, "id"))),
        ).fetchone()
        if not row:
            return None
        return {
            "id": int(row["id"]),
            "backend_url": row["backend_url"] or "",
            "generation_mode": row["generation_mode"] or "txt2img",
            "payload": _parse_json_field(row["payload_json"], {}),
            "input_assets": _parse_json_field(row["input_assets_json"], {}),
            "controlnet": _parse_json_field(row["controlnet_json"], {}),
            "result": _parse_json_field(row["result_json"], {}),
        }

    def _ensure_comfyui_workflow_schema(conn):
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS comfyui_workflow_presets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                owner_user_id INTEGER NOT NULL,
                title TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                visibility TEXT NOT NULL DEFAULT 'private',
                is_official INTEGER NOT NULL DEFAULT 0,
                system_bundle_id TEXT,
                purpose TEXT NOT NULL DEFAULT 'custom',
                comfyui_version TEXT NOT NULL DEFAULT '',
                project_version TEXT NOT NULL DEFAULT '',
                workflow_schema_version TEXT NOT NULL DEFAULT '1',
                workflow_json TEXT NOT NULL,
                workflow_hash TEXT NOT NULL DEFAULT '',
                layout_json TEXT NOT NULL DEFAULT '{}',
                required_models_json TEXT NOT NULL DEFAULT '[]',
                required_loras_json TEXT NOT NULL DEFAULT '[]',
                required_controlnets_json TEXT NOT NULL DEFAULT '[]',
                required_custom_nodes_json TEXT NOT NULL DEFAULT '[]',
                default_params_json TEXT NOT NULL DEFAULT '{}',
                is_default INTEGER NOT NULL DEFAULT 0,
                published_by_user_id INTEGER,
                published_at TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS comfyui_workflow_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                preset_id INTEGER NOT NULL,
                actor_user_id INTEGER NOT NULL,
                prompt TEXT NOT NULL DEFAULT '',
                negative_prompt TEXT NOT NULL DEFAULT '',
                params_json TEXT NOT NULL DEFAULT '{}',
                workflow_json TEXT NOT NULL,
                output_refs_json TEXT NOT NULL DEFAULT '{}',
                status TEXT NOT NULL DEFAULT 'queued',
                error TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS comfyui_workflow_layout_versions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                preset_id INTEGER NOT NULL,
                version_no INTEGER NOT NULL,
                created_by_user_id INTEGER NOT NULL,
                title TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                purpose TEXT NOT NULL DEFAULT 'custom',
                comfyui_version TEXT NOT NULL DEFAULT '',
                project_version TEXT NOT NULL DEFAULT '',
                workflow_schema_version TEXT NOT NULL DEFAULT '1',
                workflow_json TEXT NOT NULL,
                workflow_hash TEXT NOT NULL DEFAULT '',
                layout_json TEXT NOT NULL DEFAULT '{}',
                required_models_json TEXT NOT NULL DEFAULT '[]',
                required_loras_json TEXT NOT NULL DEFAULT '[]',
                required_controlnets_json TEXT NOT NULL DEFAULT '[]',
                required_custom_nodes_json TEXT NOT NULL DEFAULT '[]',
                default_params_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL,
                UNIQUE(preset_id, version_no)
            )
            """
        )
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(comfyui_workflow_presets)").fetchall()}
        if "published_by_user_id" not in columns:
            conn.execute("ALTER TABLE comfyui_workflow_presets ADD COLUMN published_by_user_id INTEGER")
        if "published_at" not in columns:
            conn.execute("ALTER TABLE comfyui_workflow_presets ADD COLUMN published_at TEXT")
        if "system_bundle_id" not in columns:
            conn.execute("ALTER TABLE comfyui_workflow_presets ADD COLUMN system_bundle_id TEXT")
        for column_name, ddl in {
            "purpose": "ALTER TABLE comfyui_workflow_presets ADD COLUMN purpose TEXT NOT NULL DEFAULT 'custom'",
            "comfyui_version": "ALTER TABLE comfyui_workflow_presets ADD COLUMN comfyui_version TEXT NOT NULL DEFAULT ''",
            "project_version": "ALTER TABLE comfyui_workflow_presets ADD COLUMN project_version TEXT NOT NULL DEFAULT ''",
            "workflow_schema_version": "ALTER TABLE comfyui_workflow_presets ADD COLUMN workflow_schema_version TEXT NOT NULL DEFAULT '1'",
            "layout_json": "ALTER TABLE comfyui_workflow_presets ADD COLUMN layout_json TEXT NOT NULL DEFAULT '{}'",
            "required_custom_nodes_json": "ALTER TABLE comfyui_workflow_presets ADD COLUMN required_custom_nodes_json TEXT NOT NULL DEFAULT '[]'",
            "is_default": "ALTER TABLE comfyui_workflow_presets ADD COLUMN is_default INTEGER NOT NULL DEFAULT 0",
        }.items():
            if column_name not in columns:
                conn.execute(ddl)
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_comfyui_workflow_presets_owner ON comfyui_workflow_presets(owner_user_id, updated_at DESC)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_comfyui_workflow_presets_official ON comfyui_workflow_presets(is_official, updated_at DESC)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_comfyui_workflow_presets_system_bundle ON comfyui_workflow_presets(system_bundle_id)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_comfyui_workflow_runs_preset ON comfyui_workflow_runs(preset_id, created_at DESC)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_comfyui_workflow_layout_versions_preset ON comfyui_workflow_layout_versions(preset_id, version_no DESC)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_comfyui_workflow_presets_default ON comfyui_workflow_presets(owner_user_id, is_default, updated_at DESC)"
        )

    def _normalize_workflow_visibility(value):
        text = str(value or "private").strip().lower() or "private"
        return text if text in COMFYUI_WORKFLOW_VISIBILITY_VALUES else "private"

    def _normalize_workflow_purpose(value, default_params=None):
        text = str(value or "").strip().lower()
        if text in COMFYUI_WORKFLOW_PURPOSE_VALUES:
            return text
        mode = str((default_params or {}).get("generation_mode") or "").strip().lower()
        if mode in COMFYUI_WORKFLOW_PURPOSE_VALUES:
            return mode
        return "custom"

    def _normalize_workflow_version(value, fallback=""):
        return _safe_text(value if value not in (None, "") else fallback, 80)

    def _sanitize_workflow_layout_json(value, workflow_json=None):
        if value in (None, ""):
            return {
                "layout_schema_version": "1",
                "node_order": list((workflow_json or {}).keys()) if isinstance(workflow_json, dict) else [],
                "node_positions": {},
                "field_overrides": {},
            }
        candidate = value
        if isinstance(candidate, str):
            if len(candidate.encode("utf-8")) > COMFYUI_WORKFLOW_LAYOUT_MAX_JSON_BYTES:
                raise WorkflowValidationError("layout JSON 過大")
            try:
                candidate = json.loads(candidate)
            except json.JSONDecodeError as exc:
                raise WorkflowValidationError("layout JSON 格式不正確") from exc
        if not isinstance(candidate, dict):
            raise WorkflowValidationError("layout JSON 必須是物件")

        def sanitize_value(item, *, path="layout", depth=0):
            if depth > 8:
                raise WorkflowValidationError(f"{path} 巢狀層級過深")
            if isinstance(item, dict):
                result = {}
                for key, child in item.items():
                    key_text = str(key or "").strip()
                    if not key_text:
                        raise WorkflowValidationError(f"{path} 含有空白欄位名稱")
                    result[key_text[:80]] = sanitize_value(child, path=f"{path}.{key_text[:80]}", depth=depth + 1)
                return result
            if isinstance(item, list):
                return [sanitize_value(child, path=f"{path}[{index}]", depth=depth + 1) for index, child in enumerate(item[:500])]
            if isinstance(item, str):
                text = item.strip()
                if WORKFLOW_BLOCKED_COMMAND_RE.search(text):
                    raise WorkflowValidationError(f"{path} 含有不允許的命令片段")
                if WORKFLOW_URL_RE.match(text):
                    raise WorkflowValidationError(f"{path} 不可包含外部 URL")
                if WORKFLOW_ABSOLUTE_PATH_RE.match(text):
                    raise WorkflowValidationError(f"{path} 不可包含絕對路徑")
                return item[:2000]
            if isinstance(item, (int, float, bool)) or item is None:
                return item
            raise WorkflowValidationError(f"{path} 類型不支援")

        sanitized = sanitize_value(candidate)
        if len(json.dumps(sanitized, ensure_ascii=False, sort_keys=True).encode("utf-8")) > COMFYUI_WORKFLOW_LAYOUT_MAX_JSON_BYTES:
            raise WorkflowValidationError("layout JSON 過大")
        return sanitized

    def _infer_required_custom_nodes(workflow_json):
        nodes = []
        if not isinstance(workflow_json, dict):
            return nodes
        for node in workflow_json.values():
            class_type = str((node or {}).get("class_type") or "").strip()
            if class_type and class_type not in COMFYUI_CORE_WORKFLOW_NODE_CLASSES and class_type not in nodes:
                nodes.append(class_type)
        return sorted(nodes)

    def _workflow_version_warnings(row):
        warnings = []
        schema_version = str(row["workflow_schema_version"] or COMFYUI_WORKFLOW_SCHEMA_VERSION)
        if schema_version != COMFYUI_WORKFLOW_SCHEMA_VERSION:
            warnings.append(f"workflow schema 版本 {schema_version} 與目前支援版本 {COMFYUI_WORKFLOW_SCHEMA_VERSION} 不一致")
        return warnings

    def _workflow_manifest_for_row(row):
        bundle_id = str(row["system_bundle_id"] or "").strip()
        if not bundle_id or not re.match(r"^[a-z][a-z0-9_]{0,63}$", bundle_id):
            return None
        manifest_path = runtime_comfyui_dir() / bundle_id / "manifest.json"
        if not manifest_path.is_file():
            return None
        try:
            if manifest_path.stat().st_size > 64 * 1024:
                return None
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception:
            return None
        if not isinstance(manifest, dict):
            return None
        if str(manifest.get("id") or "").strip() != bundle_id:
            return None
        return manifest

    def _workflow_manifest_summary(row):
        manifest = _workflow_manifest_for_row(row)
        if not manifest:
            return {"available": False}
        panels = ((manifest.get("ui") or {}).get("panels") or [])
        return {
            "available": True,
            "id": str(manifest.get("id") or ""),
            "schema_version": int(manifest.get("schema_version") or 1),
            "name": str(manifest.get("name") or ""),
            "description": str(manifest.get("description") or ""),
            "workflow_file": str(manifest.get("workflow_file") or "workflow.json"),
            "panel_count": len(panels) if isinstance(panels, list) else 0,
            "source": str(manifest.get("source") or "system"),
        }

    def _workflow_preset_summary(row, *, dependency_status=None, recent_runs=None, actor=None):
        default_params = _parse_json_field(row["default_params_json"], {}) or {}
        workflow_json = _parse_json_field(row["workflow_json"], {}) or {}
        paid_api_nodes = detect_paid_api_nodes(workflow_json)
        result = {
            "id": int(row["id"]),
            "owner_user_id": int(row["owner_user_id"]),
            "title": row["title"] or f"Workflow #{row['id']}",
            "description": row["description"] or "",
            "visibility": row["visibility"] or "private",
            "is_official": bool(row["is_official"]),
            "system_bundle_id": row["system_bundle_id"] or "",
            "purpose": row["purpose"] or "custom",
            "comfyui_version": row["comfyui_version"] or "",
            "project_version": row["project_version"] or "",
            "workflow_schema_version": row["workflow_schema_version"] or COMFYUI_WORKFLOW_SCHEMA_VERSION,
            "workflow_hash": row["workflow_hash"] or "",
            "layout_json": _parse_json_field(row["layout_json"], {}) or {},
            "required_models": _parse_json_field(row["required_models_json"], []) or [],
            "required_loras": _parse_json_field(row["required_loras_json"], []) or [],
            "required_controlnets": _parse_json_field(row["required_controlnets_json"], []) or [],
            "required_custom_nodes": _parse_json_field(row["required_custom_nodes_json"], []) or [],
            "default_params": default_params,
            "is_default": bool(row["is_default"]),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "published_at": row["published_at"],
            "published_by_user_id": row["published_by_user_id"],
            "can_edit": actor is not None and int(row["owner_user_id"]) == int(_actor_value(actor, "id")),
            "can_publish_official": bool(
                actor is not None
                and _actor_value(actor, "username") == "root"
                and int(row["owner_user_id"]) == int(_actor_value(actor, "id"))
            ),
            "version_warnings": _workflow_version_warnings(row),
            "paid_api_nodes": paid_api_nodes,
            "requires_paid_api_confirmation": bool(paid_api_nodes.get("required")),
            "manifest_summary": _workflow_manifest_summary(row),
        }
        if dependency_status is not None:
            result["dependency_status"] = dependency_status
        if recent_runs is not None:
            result["recent_runs"] = recent_runs
        return result

    def _load_workflow_preset_row(conn, *, preset_id):
        _ensure_comfyui_workflow_schema(conn)
        return conn.execute("SELECT * FROM comfyui_workflow_presets WHERE id=?", (int(preset_id),)).fetchone()

    def _can_read_workflow_preset(row, actor):
        if not row or not actor:
            return False
        actor_id = int(_actor_value(actor, "id"))
        return (
            int(row["owner_user_id"]) == actor_id
            or bool(row["is_official"])
            or str(row["visibility"] or "private").strip().lower() == "public"
        )

    def _can_write_workflow_preset(row, actor):
        return bool(row and actor and int(row["owner_user_id"]) == int(_actor_value(actor, "id")))

    def _load_workflow_preset(conn, *, preset_id, actor, require_write=False):
        row = _load_workflow_preset_row(conn, preset_id=preset_id)
        if not row:
            return None, json_resp({"ok": False, "msg": "找不到這個 workflow preset"}, 404)
        if require_write:
            if not _can_write_workflow_preset(row, actor):
                return None, json_resp({"ok": False, "msg": "你沒有權限修改這個 workflow preset"}, 403)
        elif not _can_read_workflow_preset(row, actor):
            return None, json_resp({"ok": False, "msg": "你沒有權限查看這個 workflow preset"}, 403)
        return row, None

    def _list_workflow_runs(conn, *, preset_id, limit=COMFYUI_WORKFLOW_RUN_LIMIT):
        _ensure_comfyui_workflow_schema(conn)
        rows = conn.execute(
            """
            SELECT id, prompt, negative_prompt, params_json, output_refs_json, status, error, created_at, updated_at
            FROM comfyui_workflow_runs
            WHERE preset_id=?
            ORDER BY created_at DESC, id DESC
            LIMIT ?
            """,
            (int(preset_id), int(limit)),
        ).fetchall()
        return [{
            "id": int(row["id"]),
            "prompt": row["prompt"] or "",
            "negative_prompt": row["negative_prompt"] or "",
            "params": _parse_json_field(row["params_json"], {}) or {},
            "output_refs": _parse_json_field(row["output_refs_json"], {}) or {},
            "status": row["status"] or "queued",
            "error": row["error"] or "",
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        } for row in rows]

    def _list_workflow_presets(conn, *, actor, active_client=None):
        _ensure_comfyui_workflow_schema(conn)
        if _sync_runtime_official_workflow_presets(conn):
            conn.commit()
        rows = conn.execute(
            """
            SELECT *
            FROM comfyui_workflow_presets
            WHERE owner_user_id=? OR is_official=1 OR visibility='public'
            ORDER BY is_official DESC, updated_at DESC, id DESC
            LIMIT ?
            """,
            (int(_actor_value(actor, "id")), COMFYUI_WORKFLOW_PRESET_LIMIT),
        ).fetchall()
        dependency_cache = {}
        items = []
        for row in rows:
            dependency_status = None
            if active_client is not None:
                dependency_status = _workflow_dependency_status(active_client, row)
            recent_runs = _list_workflow_runs(conn, preset_id=row["id"], limit=3)
            items.append(_workflow_preset_summary(row, dependency_status=dependency_status, recent_runs=recent_runs, actor=actor))
        return items

    def _official_workflow_owner_user_id(conn):
        row = conn.execute(
            "SELECT id FROM users WHERE username='root' ORDER BY id ASC LIMIT 1"
        ).fetchone()
        if row:
            return int(row["id"])
        row = conn.execute("SELECT id FROM users ORDER BY id ASC LIMIT 1").fetchone()
        if row:
            return int(row["id"])
        return 1

    def _sync_runtime_official_workflow_presets(conn):
        _ensure_comfyui_workflow_schema(conn)
        runtime_dir = runtime_comfyui_dir()
        if not runtime_dir.is_dir():
            return []

        owner_user_id = _official_workflow_owner_user_id(conn)
        bundle_rows = conn.execute(
            """
            SELECT *
            FROM comfyui_workflow_presets
            WHERE is_official=1
            ORDER BY updated_at DESC, id DESC
            """
        ).fetchall()
        by_bundle_id = {}
        by_title = {}
        by_hash = {}
        for row in bundle_rows:
            bundle_id = str(row["system_bundle_id"] or "").strip()
            if bundle_id and bundle_id not in by_bundle_id:
                by_bundle_id[bundle_id] = row
            title = str(row["title"] or "").strip()
            if title and title not in by_title:
                by_title[title] = row
            workflow_hash = str(row["workflow_hash"] or "").strip()
            if workflow_hash and workflow_hash not in by_hash:
                by_hash[workflow_hash] = row

        synced = []
        for bundle_id in SYSTEM_WORKFLOW_IDS:
            bundle_dir = runtime_dir / bundle_id
            workflow_path = bundle_dir / "workflow.json"
            manifest_path = bundle_dir / "manifest.json"
            if not workflow_path.is_file() or not manifest_path.is_file():
                continue
            try:
                workflow_candidate = json.loads(workflow_path.read_text(encoding="utf-8"))
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            except Exception:
                continue
            try:
                workflow_payload = sanitize_workflow_json(workflow_candidate)
            except WorkflowValidationError:
                continue
            manifest_bundle_id = str(manifest.get("id") or bundle_dir.name or "").strip()
            if manifest_bundle_id != bundle_id:
                continue
            title = _safe_text(manifest.get("name") or bundle_id, 120)
            description = _safe_text(manifest.get("description") or "", 1200)
            default_params = manifest.get("default_params")
            if not isinstance(default_params, dict):
                default_params = workflow_payload.get("default_params") or {}
            existing = (
                by_bundle_id.get(bundle_id)
                or by_hash.get(str(workflow_payload.get("workflow_hash") or "").strip())
                or by_title.get(title)
            )
            update_actor_id = int(existing["owner_user_id"]) if existing else owner_user_id
            preset_id = _upsert_workflow_preset(
                conn,
                preset_id=int(existing["id"]) if existing else None,
                actor={"id": update_actor_id},
                title=title,
                description=description,
                visibility="public",
                workflow_payload=workflow_payload,
                default_params=default_params,
                is_official=True,
                published_by_user_id=owner_user_id,
                system_bundle_id=bundle_id,
            )
            synced.append({"bundle_id": bundle_id, "preset_id": int(preset_id)})
        return synced

    def _normalize_workflow_default_params(data):
        candidate = data
        if candidate in (None, ""):
            return {}
        if isinstance(candidate, str):
            candidate = _parse_json_field(candidate, None)
        if not isinstance(candidate, dict):
            raise WorkflowValidationError("default params 必須是物件")
        normalized_candidate = dict(candidate)
        normalized_candidate["skip_asset_validation"] = True
        params, msg = _normalize_generation_payload(normalized_candidate)
        if msg:
            raise WorkflowValidationError(msg)
        return params

    def _extract_workflow_payload(data):
        try:
            parsed = sanitize_workflow_json(data)
        except WorkflowValidationError:
            raise
        default_params = parsed.get("default_params") or {}
        return parsed, default_params

    def _record_workflow_layout_version(conn, row, *, actor, now=None):
        if not row:
            return
        now = now or datetime.now().isoformat()
        preset_id = int(row["id"])
        existing = conn.execute(
            "SELECT COALESCE(MAX(version_no), 0) AS max_version FROM comfyui_workflow_layout_versions WHERE preset_id=?",
            (preset_id,),
        ).fetchone()
        version_no = int(existing["max_version"] if existing and existing["max_version"] is not None else 0) + 1
        conn.execute(
            """
            INSERT INTO comfyui_workflow_layout_versions (
                preset_id, version_no, created_by_user_id, title, description, purpose,
                comfyui_version, project_version, workflow_schema_version, workflow_json,
                workflow_hash, layout_json, required_models_json, required_loras_json,
                required_controlnets_json, required_custom_nodes_json, default_params_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                preset_id,
                version_no,
                int(_actor_value(actor, "id")),
                row["title"] or "",
                row["description"] or "",
                row["purpose"] or "custom",
                row["comfyui_version"] or "",
                row["project_version"] or "",
                row["workflow_schema_version"] or COMFYUI_WORKFLOW_SCHEMA_VERSION,
                row["workflow_json"] or "{}",
                row["workflow_hash"] or "",
                row["layout_json"] or "{}",
                row["required_models_json"] or "[]",
                row["required_loras_json"] or "[]",
                row["required_controlnets_json"] or "[]",
                row["required_custom_nodes_json"] or "[]",
                row["default_params_json"] or "{}",
                now,
            ),
        )

    def _workflow_preset_revision_changed(before, after):
        if before is None:
            return True
        keys = (
            "title",
            "description",
            "visibility",
            "is_official",
            "system_bundle_id",
            "purpose",
            "comfyui_version",
            "project_version",
            "workflow_schema_version",
            "workflow_json",
            "workflow_hash",
            "layout_json",
            "required_models_json",
            "required_loras_json",
            "required_controlnets_json",
            "required_custom_nodes_json",
            "default_params_json",
            "is_default",
        )
        return any(str(before[key] if before[key] is not None else "") != str(after[key] if after[key] is not None else "") for key in keys)

    def _upsert_workflow_preset(
        conn,
        *,
        preset_id=None,
        actor,
        title,
        description,
        visibility,
        workflow_payload,
        default_params,
        purpose=None,
        comfyui_version=None,
        project_version=None,
        workflow_schema_version=None,
        layout_json=None,
        required_custom_nodes=None,
        is_default=False,
        is_official=False,
        published_by_user_id=None,
        system_bundle_id=None,
    ):
        _ensure_comfyui_workflow_schema(conn)
        now = datetime.now().isoformat()
        workflow_json = workflow_payload["workflow_json"]
        workflow_hash = workflow_payload["workflow_hash"]
        required_models = workflow_payload["required_models"]
        required_loras = workflow_payload["required_loras"]
        required_controlnets = workflow_payload["required_controlnets"]
        default_payload = default_params or workflow_payload["default_params"] or {}
        safe_layout = _sanitize_workflow_layout_json(layout_json, workflow_json=workflow_json)
        safe_custom_nodes = (
            [str(item).strip()[:160] for item in required_custom_nodes if str(item or "").strip()]
            if isinstance(required_custom_nodes, list)
            else _infer_required_custom_nodes(workflow_json)
        )
        safe_purpose = _normalize_workflow_purpose(purpose, default_payload)
        safe_project_version = _normalize_workflow_version(project_version, APP_RELEASE_ID)
        safe_comfyui_version = _normalize_workflow_version(comfyui_version, "")
        safe_schema_version = _normalize_workflow_version(workflow_schema_version, COMFYUI_WORKFLOW_SCHEMA_VERSION)
        safe_is_default = 1 if is_default else 0
        args = (
            title.strip()[:120],
            _safe_text(description, 1200),
            _normalize_workflow_visibility(visibility),
            1 if is_official else 0,
            safe_purpose,
            safe_comfyui_version,
            safe_project_version,
            safe_schema_version,
            json.dumps(workflow_json, ensure_ascii=False, sort_keys=True),
            workflow_hash,
            json.dumps(safe_layout, ensure_ascii=False, sort_keys=True),
            json.dumps(required_models, ensure_ascii=False, sort_keys=True),
            json.dumps(required_loras, ensure_ascii=False, sort_keys=True),
            json.dumps(required_controlnets, ensure_ascii=False, sort_keys=True),
            json.dumps(safe_custom_nodes, ensure_ascii=False, sort_keys=True),
            json.dumps(default_payload, ensure_ascii=False, sort_keys=True),
            safe_is_default,
            int(published_by_user_id) if published_by_user_id else None,
            now if is_official else None,
            str(system_bundle_id or "").strip() or None,
            now,
        )
        if preset_id is None:
            cur = conn.execute(
                """
                INSERT INTO comfyui_workflow_presets (
                    owner_user_id, title, description, visibility, is_official,
                    purpose, comfyui_version, project_version, workflow_schema_version,
                    workflow_json, workflow_hash, layout_json, required_models_json, required_loras_json,
                    required_controlnets_json, required_custom_nodes_json, default_params_json, is_default,
                    published_by_user_id, published_at, system_bundle_id, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    int(_actor_value(actor, "id")),
                    *args,
                    now,
                ),
            )
            preset_id = int(cur.lastrowid)
            if safe_is_default:
                conn.execute(
                    "UPDATE comfyui_workflow_presets SET is_default=0 WHERE owner_user_id=? AND id<>?",
                    (int(_actor_value(actor, "id")), preset_id),
                )
            row = _load_workflow_preset_row(conn, preset_id=preset_id)
            _record_workflow_layout_version(conn, row, actor=actor, now=now)
            return preset_id
        before_row = _load_workflow_preset_row(conn, preset_id=preset_id)
        conn.execute(
                """
                UPDATE comfyui_workflow_presets
                SET title=?, description=?, visibility=?, is_official=?, purpose=?, comfyui_version=?,
                    project_version=?, workflow_schema_version=?, workflow_json=?, workflow_hash=?,
                    layout_json=?, required_models_json=?, required_loras_json=?, required_controlnets_json=?,
                    required_custom_nodes_json=?, default_params_json=?, is_default=?, published_by_user_id=?,
                    published_at=?, system_bundle_id=?, updated_at=?
                WHERE id=? AND owner_user_id=?
                """,
                (
                *args,
                int(preset_id),
                int(_actor_value(actor, "id")),
            ),
        )
        if safe_is_default:
            conn.execute(
                "UPDATE comfyui_workflow_presets SET is_default=0 WHERE owner_user_id=? AND id<>?",
                (int(_actor_value(actor, "id")), int(preset_id)),
            )
        after_row = _load_workflow_preset_row(conn, preset_id=preset_id)
        if _workflow_preset_revision_changed(before_row, after_row):
            _record_workflow_layout_version(conn, after_row, actor=actor, now=now)
        return int(preset_id)

    def _create_workflow_run(conn, *, preset_id, actor, prompt, negative_prompt, params_json, workflow_json):
        _ensure_comfyui_workflow_schema(conn)
        now = datetime.now().isoformat()
        cur = conn.execute(
            """
            INSERT INTO comfyui_workflow_runs (
                preset_id, actor_user_id, prompt, negative_prompt, params_json,
                workflow_json, output_refs_json, status, error, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, '{}', 'queued', '', ?, ?)
            """,
            (
                int(preset_id),
                int(_actor_value(actor, "id")),
                _safe_text(prompt, 3000),
                _safe_text(negative_prompt, 3000),
                json.dumps(params_json or {}, ensure_ascii=False, sort_keys=True),
                json.dumps(workflow_json or {}, ensure_ascii=False, sort_keys=True),
                now,
                now,
            ),
        )
        return cur.lastrowid

    def _update_workflow_run(conn, *, run_id, status, output_refs=None, error=""):
        _ensure_comfyui_workflow_schema(conn)
        conn.execute(
            """
            UPDATE comfyui_workflow_runs
            SET status=?, output_refs_json=?, error=?, updated_at=?
            WHERE id=?
            """,
            (
                str(status or "queued"),
                json.dumps(output_refs or {}, ensure_ascii=False, sort_keys=True),
                _safe_text(error, 500),
                datetime.now().isoformat(),
                int(run_id),
            ),
        )

    def _active_client_dependency_sets(active_client):
        capabilities = active_client.get_capabilities() if hasattr(active_client, "get_capabilities") else {}
        try:
            models = set(active_client.get_models() if hasattr(active_client, "get_models") else [])
        except Exception:
            models = set()
        try:
            vaes = set(active_client.get_vaes() if hasattr(active_client, "get_vaes") else [])
        except Exception:
            vaes = set()
        try:
            loras = set(active_client.get_loras() if hasattr(active_client, "get_loras") else [])
        except Exception:
            loras = set()
        return {
            "models": models,
            "vaes": vaes,
            "loras": loras,
            "controlnets": set((capabilities or {}).get("controlnet_models") or []),
            "upscale_models": set((capabilities or {}).get("upscale_models") or []),
            "available_nodes": set((capabilities or {}).get("available_nodes") or []),
            "controlnet_types": (capabilities or {}).get("controlnet_types") or {},
        }

    def _workflow_dependency_status(active_client, row):
        payload = _parse_json_field(row["workflow_json"], {}) or {}
        required_models = _parse_json_field(row["required_models_json"], []) or []
        required_loras = _parse_json_field(row["required_loras_json"], []) or []
        required_controlnets = _parse_json_field(row["required_controlnets_json"], []) or []
        sets = _active_client_dependency_sets(active_client)
        missing_models = []
        missing_loras = []
        missing_controlnets = []
        missing_nodes = []
        for node in payload.values():
            class_type = str((node or {}).get("class_type") or "").strip()
            if class_type and sets["available_nodes"] and class_type not in sets["available_nodes"]:
                missing_nodes.append(class_type)
        for item in required_models:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "").strip()
            kind = str(item.get("kind") or "checkpoint").strip().lower()
            if not name:
                continue
            if kind == "vae":
                if name not in sets["vaes"]:
                    missing_models.append({"kind": kind, "name": name})
            elif kind == "upscale":
                if name not in sets["upscale_models"]:
                    missing_models.append({"kind": kind, "name": name})
            elif name not in sets["models"]:
                missing_models.append({"kind": kind, "name": name})
        for item in required_loras:
            name = str((item or {}).get("name") or "").strip() if isinstance(item, dict) else str(item or "").strip()
            if name and name not in sets["loras"]:
                missing_loras.append({"name": name})
        for item in required_controlnets:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "").strip()
            control_type = str(item.get("type") or "").strip().lower()
            if name and name not in sets["controlnets"]:
                missing_controlnets.append({"name": name, "type": control_type})
            elif control_type and not ((sets["controlnet_types"].get(control_type) or {}).get("available")):
                missing_controlnets.append({"name": name, "type": control_type})
        available = not (missing_models or missing_loras or missing_controlnets or missing_nodes)
        issues = []
        if missing_nodes:
            issues.append(f"缺少 workflow node：{', '.join(sorted(set(missing_nodes)))}")
        if missing_models:
            issues.append("缺少模型：" + ", ".join(sorted({item['name'] for item in missing_models})))
        if missing_loras:
            issues.append("缺少 LoRA：" + ", ".join(sorted({item['name'] for item in missing_loras})))
        if missing_controlnets:
            issues.append("缺少 ControlNet：" + ", ".join(sorted({item['name'] for item in missing_controlnets})))
        return {
            "available": available,
            "missing_nodes": sorted(set(missing_nodes)),
            "missing_models": missing_models,
            "missing_loras": missing_loras,
            "missing_controlnets": missing_controlnets,
            "issues": issues,
        }

    def _assert_workflow_dependencies_or_error(active_client, row):
        status = _workflow_dependency_status(active_client, row)
        if status["available"]:
            return status, None
        message = "；".join(status["issues"]) if status["issues"] else "workflow 依賴檢查失敗"
        return status, message

    def _parse_generation_request():
        uploaded_assets = {}
        if request.content_type and "multipart/form-data" in request.content_type.lower():
            data = request.form.to_dict(flat=True)
            files = request.files or {}
            for field_name, label in (
                ("source_image", "來源圖片"),
                ("mask_image", "遮罩圖片"),
                ("control_image", "控制圖"),
            ):
                payload, msg = _validate_image_upload(files.get(field_name), label=label)
                if msg:
                    return None, None, msg
                if payload:
                    uploaded_assets[field_name] = payload
            return data, uploaded_assets, None
        try:
            data = request.get_json(force=True)
        except Exception:
            return None, None, "請求 JSON 格式錯誤"
        if not isinstance(data, dict):
            return None, None, "請求內容格式錯誤"
        return data, uploaded_assets, None

    def _hydrate_generation_assets(actor, active_client, params, uploaded_assets):
        params = dict(params or {})
        uploaded_assets = dict(uploaded_assets or {})
        image_ref_records = []
        for field_name, params_key in (
            ("source_image", "source_image_ref"),
            ("mask_image", "mask_image_ref"),
            ("control_image", "control_image_ref"),
        ):
            asset = uploaded_assets.get(field_name)
            if not asset:
                continue
            image_ref = active_client.upload_image_bytes(
                asset["data"],
                asset["filename"],
                image_type="input",
                overwrite=False,
            )
            image_ref_records.append({"image_ref": image_ref, "prompt_id": ""})
            if params_key == "control_image_ref":
                control = dict(params.get("controlnet") or {})
                control["image_ref"] = image_ref
                params["controlnet"] = control
            else:
                params[params_key] = image_ref
        if image_ref_records:
            conn = get_db()
            try:
                _register_comfyui_image_refs(conn, actor=actor, images=image_ref_records, backend_url=getattr(active_client, "base_url", ""))
                conn.commit()
            finally:
                conn.close()
        return params

    def _validate_generation_capabilities(active_client, params):
        if not hasattr(active_client, "get_capabilities"):
            return {}, None
        capabilities = active_client.get_capabilities() if hasattr(active_client, "get_capabilities") else {}
        available_nodes = set((capabilities or {}).get("available_nodes") or [])
        mode = str((params or {}).get("generation_mode") or "txt2img").strip().lower()
        mode_definition = GENERATION_MODE_DEFINITIONS.get(mode) or {}
        backend_kind = str(getattr(active_client, "backend_kind", "") or (capabilities or {}).get("backend_kind") or "").strip().lower()
        if backend_kind == "diffusers":
            supported_modes = {
                str(item.get("key") or "").strip().lower()
                for item in (capabilities or {}).get("generation_modes") or []
                if item.get("available")
            }
            if mode_definition.get("workflow_only") or mode not in supported_modes:
                return capabilities, "Diffusers 後端目前只支援文字生圖、圖生圖與局部重繪；影片、語音、放大與 workflow 模板仍請使用 ComfyUI 後端。"
            model_repo = str((capabilities or {}).get("model_repo") or getattr(active_client, "model_repo", "") or "").strip()
            selected_model = str((params or {}).get("model") or "").strip()
            if model_repo and selected_model and selected_model != model_repo:
                return capabilities, f"Diffusers 模式目前使用 root 設定的 Hugging Face repo：{model_repo}"
            if model_repo:
                params["model"] = model_repo
            if params.get("loras"):
                return capabilities, "Diffusers 後端目前不支援本站 ComfyUI LoRA 選擇；請改用本地或遠端 ComfyUI 模式。"
            control = (params or {}).get("controlnet") if isinstance((params or {}).get("controlnet"), dict) else None
            if control:
                return capabilities, "Diffusers 後端目前不支援本站 ControlNet 快捷模式；請改用本地或遠端 ComfyUI 模式。"
            return capabilities, None
        if mode_definition.get("workflow_only"):
            return capabilities, "這個模式需要透過支援的大模型 workflow 模板執行，請先匯入或選擇對應 workflow。"
        required_nodes = {"CheckpointLoaderSimple", "CLIPTextEncode", "KSampler", "VAEDecode", "SaveImage"}
        if mode == "img2img":
            required_nodes.update({"LoadImage", "VAEEncode"})
        elif mode == "inpaint":
            required_nodes.update({"LoadImage", "LoadImageMask", "VAEEncodeForInpaint"})
        elif mode == "outpaint":
            required_nodes.update({"LoadImage", "ImagePadForOutpaint", "VAEEncodeForInpaint"})
        elif mode == "upscale":
            required_nodes = {"LoadImage", "UpscaleModelLoader", "ImageUpscaleWithModel", "SaveImage"}
            upscale_models = set((capabilities or {}).get("upscale_models") or [])
            if str((params or {}).get("upscale_model") or "").strip() not in upscale_models:
                return None, "缺少對應的放大模型，請先安裝 scale model"
        missing_nodes = sorted(node for node in required_nodes if node not in available_nodes)
        if missing_nodes:
            return None, f"ComfyUI 缺少必要 workflow node：{', '.join(missing_nodes)}"
        control = (params or {}).get("controlnet") if isinstance((params or {}).get("controlnet"), dict) else None
        if control:
            control_type = str(control.get("type") or "").strip().lower()
            type_info = ((capabilities or {}).get("controlnet_types") or {}).get(control_type) or {}
            if not type_info.get("available"):
                return None, f"ControlNet {CONTROLNET_TYPE_DEFINITIONS.get(control_type, {}).get('label', control_type)} 缺少對應 nodes 或 models"
            chosen_preprocessor = str(control.get("preprocessor") or type_info.get("default_preprocessor") or "").strip()
            if not chosen_preprocessor:
                return None, "找不到可用的 ControlNet preprocessor"
            if chosen_preprocessor not in set(type_info.get("available_preprocessors") or []):
                return None, f"ControlNet preprocessor 不可用：{chosen_preprocessor}"
            chosen_model = str(control.get("model_name") or "").strip()
            if not chosen_model:
                matching_models = list(type_info.get("matching_models") or [])
                if not matching_models:
                    return None, "缺少對應的 ControlNet 模型"
                control["model_name"] = matching_models[0]
            elif chosen_model not in set(type_info.get("matching_models") or []):
                return None, f"ControlNet 模型不可用：{chosen_model}"
            control["preprocessor"] = chosen_preprocessor
            params["controlnet"] = control
        return capabilities, None

    def _assert_reasonable_image_size(image):
        size = len(getattr(image, "data", b"") or b"")
        if size > MAX_COMFYUI_FETCH_IMAGE_BYTES:
            raise ComfyUIError(f"ComfyUI image too large: {size} bytes")

    def _root_or_403():
        actor, err = _actor_or_401()
        if err:
            return None, err
        if _actor_value(actor, "username") != "root":
            return None, json_resp({"ok": False, "msg": "只有 root 可執行此操作"}, 403)
        return actor, None

    def _can_interrupt(actor):
        return (
            _actor_value(actor, "username") == "root"
            or _actor_value(actor, "role") in {"manager", "super_admin"}
        )

    def _generation_owner_id(actor):
        try:
            return int(_actor_value(actor, "id"))
        except Exception:
            return None

    def _coerce_bool(value):
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return value != 0
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "on", "y", "t"}
        return False

    def _register_active_generation(actor, *, backend_url="", backend_scope="primary"):
        generation_key = secrets.token_hex(12)
        with active_generations_lock:
            active_generations[generation_key] = {
                "user_id": _generation_owner_id(actor),
                "username": _actor_value(actor, "username", ""),
                "role": _actor_value(actor, "role", ""),
                "backend_url": _normalize_comfyui_backend_url(backend_url),
                "backend_scope": str(backend_scope or "primary"),
                "started_at": time.time(),
            }
        return generation_key

    def _unregister_active_generation(token):
        with active_generations_lock:
            active_generations.pop(token, None)

    def _create_generation_job(actor):
        job_id = secrets.token_hex(12)
        job = {
            "job_id": job_id,
            "owner_user_id": _generation_owner_id(actor),
            "owner_username": _actor_value(actor, "username", ""),
            "status": "queued",
            "error": "",
            "progress": {
                "phase": "queued",
                "percent": 0,
                "current": 0,
                "max": 0,
                "current_node": None,
                "queue_remaining": None,
                "detail": "已建立產圖工作",
                "completed": False,
                "updated_at": time.time(),
            },
            "result": None,
            "created_at": time.time(),
            "updated_at": time.time(),
        }
        with generation_jobs_lock:
            generation_jobs[job_id] = job
        try:
            from services.job_center import create_job as create_platform_job

            conn = get_db()
            try:
                create_platform_job(
                    conn,
                    owner_user_id=_generation_owner_id(actor),
                    created_by_user_id=_generation_owner_id(actor),
                    job_type="comfyui.generate",
                    title="ComfyUI 產圖",
                    description="ComfyUI 產圖 / workflow 執行工作",
                    source_module="comfyui",
                    source_ref=job_id,
                    status="queued",
                    progress_percent=0,
                    stage="queued",
                    stage_detail="已建立產圖工作",
                    cancellable=False,
                    metadata={"comfyui_job_id": job_id},
                )
                conn.commit()
            finally:
                conn.close()
        except Exception:
            pass
        return job_id

    def _capture_request_audit_meta():
        try:
            client_ip = get_client_ip() or "-"
        except Exception:
            client_ip = "-"
        try:
            user_agent = get_ua() or "-"
        except Exception:
            user_agent = "-"
        return {
            "client_ip": client_ip,
            "user_agent": user_agent,
        }

    def _update_generation_job(job_id, **changes):
        with generation_jobs_lock:
            job = generation_jobs.get(job_id)
            if not job:
                return None
            for key, value in changes.items():
                job[key] = value
            job["updated_at"] = time.time()
            updated = dict(job)
        try:
            from services.job_center import add_job_event, get_job_by_source, update_job as update_platform_job

            conn = get_db()
            try:
                platform_job = get_job_by_source(conn, "comfyui", job_id)
                if platform_job:
                    status_map = {"completed": "succeeded", "error": "failed", "running": "running", "queued": "queued"}
                    next_status = status_map.get(str(updated.get("status") or ""), None)
                    payload = {}
                    if next_status:
                        payload["status"] = next_status
                        payload["stage"] = next_status
                    if next_status in {"succeeded", "failed", "cancelled", "expired"}:
                        payload["finished_at"] = __import__("datetime").datetime.utcnow().replace(microsecond=0).isoformat()
                    if updated.get("error"):
                        payload["error_message"] = str(updated.get("error") or "")[:1000]
                        payload["error_stage"] = "comfyui"
                    update_platform_job(conn, platform_job["job_uuid"], **payload)
                    add_job_event(conn, platform_job["job_uuid"], event_type="updated", stage=payload.get("stage"), message=payload.get("error_message") or "ComfyUI 任務狀態更新")
                    conn.commit()
            finally:
                conn.close()
        except Exception:
            pass
        return updated

    def _update_generation_job_progress(job_id, progress):
        with generation_jobs_lock:
            job = generation_jobs.get(job_id)
            if not job:
                return None
            job["progress"] = {
                **(job.get("progress") or {}),
                **(progress or {}),
                "updated_at": time.time(),
            }
            if job["status"] in {"queued", "running"}:
                job["status"] = "running"
            job["updated_at"] = time.time()
            updated = dict(job)
        try:
            from services.job_center import add_job_event, get_job_by_source, update_job as update_platform_job

            conn = get_db()
            try:
                platform_job = get_job_by_source(conn, "comfyui", job_id)
                if platform_job:
                    progress_data = updated.get("progress") or {}
                    percent = int(float(progress_data.get("percent") or 0))
                    stage = str(progress_data.get("phase") or "running")[:80]
                    detail = str(progress_data.get("detail") or "")[:1000]
                    update_platform_job(conn, platform_job["job_uuid"], status="running", progress_percent=percent, stage=stage, stage_detail=detail)
                    add_job_event(conn, platform_job["job_uuid"], event_type="progress", stage=stage, message=detail, progress_percent=percent, payload=progress_data)
                    conn.commit()
            finally:
                conn.close()
        except Exception:
            pass
        return updated

    def _get_generation_job(job_id):
        with generation_jobs_lock:
            job = generation_jobs.get(str(job_id))
            return dict(job) if job else None

    def _assert_generation_job_owner(job_id, actor):
        job = _get_generation_job(job_id)
        if not job:
            return None, json_resp({"ok": False, "msg": "找不到 ComfyUI 產圖工作"}, 404)
        if int(job.get("owner_user_id") or 0) != int(_generation_owner_id(actor) or 0):
            return None, json_resp({"ok": False, "msg": "無權查看此 ComfyUI 工作"}, 403)
        return job, None

    def _active_generation_snapshot():
        with active_generations_lock:
            return list(active_generations.values())

    def _interrupt_policy(actor):
        if _actor_value(actor, "username") == "root":
            return True, "root_force", {}
        actor_id = _generation_owner_id(actor)
        binding = _comfyui_binding(actor)
        target_backend_url = _normalize_comfyui_backend_url(binding.get("url"))
        active = _active_generation_snapshot()
        own = [item for item in active if item.get("user_id") == actor_id]
        others = [
            item for item in active
            if item.get("user_id") != actor_id
            and _normalize_comfyui_backend_url(item.get("backend_url")) == target_backend_url
        ]
        summary = {
            "own_active": len(own),
            "other_active_same_backend": len(others),
            "total_active": len(active),
        }
        if not own:
            return False, "no_owned_generation", summary
        if others:
            return False, "shared_backend_busy", summary
        return True, "owned_generation_only", summary

    _admin_helpers = build_comfyui_admin_helpers({
        "DEFAULT_COMFYUI_URL": DEFAULT_COMFYUI_URL,
        "SAFE_SAMPLER_FALLBACK": SAFE_SAMPLER_FALLBACK,
        "SAFE_SCHEDULER_FALLBACK": SAFE_SCHEDULER_FALLBACK,
        "COMFYUI_LOCAL_START_TEMPLATE_PATH": COMFYUI_LOCAL_START_TEMPLATE_PATH,
        "COMFYUI_MODEL_DOWNLOAD_EXTENSIONS": COMFYUI_MODEL_DOWNLOAD_EXTENSIONS,
        "COMFYUI_MODEL_DOWNLOAD_TYPES": COMFYUI_MODEL_DOWNLOAD_TYPES,
        "COMFYUI_SUPPORTED_LORA_BASE_MODEL_FAMILIES": COMFYUI_SUPPORTED_LORA_BASE_MODEL_FAMILIES,
        "MAX_COMFYUI_MODEL_DOWNLOAD_BYTES": MAX_COMFYUI_MODEL_DOWNLOAD_BYTES,
        "CIVITAI_ALLOWED_HOSTS": CIVITAI_ALLOWED_HOSTS,
        "CIVITAI_API_BASE": CIVITAI_API_BASE,
        "CIVITAI_API_BASES": CIVITAI_API_BASES,
        "CIVITAI_MODEL_TYPE_TO_DOWNLOAD_TYPE": CIVITAI_MODEL_TYPE_TO_DOWNLOAD_TYPE,
        "CIVITAI_SEARCH_TYPE_TO_API": CIVITAI_SEARCH_TYPE_TO_API,
        "MemoryFile": _MemoryFile,
        "actor_value": _actor_value,
        "audit": audit,
        "deps": deps,
        "get_client_ip": get_client_ip,
        "generation_owner_id": _generation_owner_id,
        "get_system_settings": get_system_settings,
        "get_ua": get_ua,
        "injected_client": injected_client,
        "json_resp": json_resp,
        "model_download_jobs": model_download_jobs,
        "model_download_jobs_lock": model_download_jobs_lock,
    })
    _validate_comfyui_host = _admin_helpers["_validate_comfyui_host"]
    _parse_comfyui_endpoint = _admin_helpers["_parse_comfyui_endpoint"]
    _validate_comfyui_api_url = _admin_helpers["_validate_comfyui_api_url"]
    _normalize_comfyui_backend_url = _admin_helpers["_normalize_comfyui_backend_url"]
    _configured_connection_mode = _admin_helpers["_configured_connection_mode"]
    _configured_comfyui_url = _admin_helpers["_configured_comfyui_url"]
    _comfyui_binding = _admin_helpers["_comfyui_binding"]
    _configured_local_start_script = _admin_helpers["_configured_local_start_script"]
    _configured_comfyui_port = _admin_helpers["_configured_comfyui_port"]
    _local_comfyui_state_path = _admin_helpers["_local_comfyui_state_path"]
    _write_local_comfyui_state = _admin_helpers["_write_local_comfyui_state"]
    _read_local_comfyui_state = _admin_helpers["_read_local_comfyui_state"]
    _clear_local_comfyui_state = _admin_helpers["_clear_local_comfyui_state"]
    _tail_text_lines = _admin_helpers["_tail_text_lines"]
    _local_comfyui_runtime_status = _admin_helpers["_local_comfyui_runtime_status"]
    _pid_exists = _admin_helpers["_pid_exists"]
    _pid_cmdline = _admin_helpers["_pid_cmdline"]
    _listener_pids_for_port = _admin_helpers["_listener_pids_for_port"]
    _proc_scan_comfyui_pids = _admin_helpers["_proc_scan_comfyui_pids"]
    _looks_like_comfyui_process = _admin_helpers["_looks_like_comfyui_process"]
    _terminate_local_comfyui_targets = _admin_helpers["_terminate_local_comfyui_targets"]
    _stop_local_comfyui = _admin_helpers["_stop_local_comfyui"]
    _local_start_script_status = _admin_helpers["_local_start_script_status"]
    _start_local_comfyui = _admin_helpers["_start_local_comfyui"]
    _configured_max_batch_size = _admin_helpers["_configured_max_batch_size"]
    _configured_default_dimensions = _admin_helpers["_configured_default_dimensions"]
    _configured_comfyui_base_dir = _admin_helpers["_configured_comfyui_base_dir"]
    _configured_comfyui_project_dir = _admin_helpers["_configured_comfyui_project_dir"]
    _configured_civitai_api_key = _admin_helpers["_configured_civitai_api_key"]
    _public_download_host = _admin_helpers["_public_download_host"]
    _safe_model_filename = _admin_helpers["_safe_model_filename"]
    _normalize_download_model_type = _admin_helpers["_normalize_download_model_type"]
    _filename_from_content_disposition = _admin_helpers["_filename_from_content_disposition"]
    _append_civitai_token = _admin_helpers["_append_civitai_token"]
    _civitai_headers = _admin_helpers["_civitai_headers"]
    _comfyui_model_sidecar_path = _admin_helpers["_comfyui_model_sidecar_path"]
    _normalize_model_relative_dir = _admin_helpers["_normalize_model_relative_dir"]
    _split_model_relative_name = _admin_helpers["_split_model_relative_name"]
    _resolve_model_destination_dir = _admin_helpers["_resolve_model_destination_dir"]
    _comfyui_model_sidecar_path_with_relative = _admin_helpers["_comfyui_model_sidecar_path_with_relative"]
    _write_comfyui_model_sidecar = _admin_helpers["_write_comfyui_model_sidecar"]
    _read_comfyui_model_sidecar = _admin_helpers["_read_comfyui_model_sidecar"]
    _normalize_lora_base_model_family = _admin_helpers["_normalize_lora_base_model_family"]
    _lora_support_payload = _admin_helpers["_lora_support_payload"]
    _build_lora_details = _admin_helpers["_build_lora_details"]
    _public_or_civitai_host = _admin_helpers["_public_or_civitai_host"]
    _parse_civitai_reference = _admin_helpers["_parse_civitai_reference"]
    _fetch_json = _admin_helpers["_fetch_json"]
    _civitai_api_get = _admin_helpers["_civitai_api_get"]
    _normalize_civitai_search_type = _admin_helpers["_normalize_civitai_search_type"]
    _normalize_civitai_nsfw_mode = _admin_helpers["_normalize_civitai_nsfw_mode"]
    _serialize_civitai_file = _admin_helpers["_serialize_civitai_file"]
    _serialize_civitai_versions = _admin_helpers["_serialize_civitai_versions"]
    _build_civitai_page_url = _admin_helpers["_build_civitai_page_url"]
    _safe_civitai_media_url = _admin_helpers["_safe_civitai_media_url"]
    _fetch_civitai_media = _admin_helpers["_fetch_civitai_media"]
    _serialize_civitai_search_results = _admin_helpers["_serialize_civitai_search_results"]
    _search_civitai_models = _admin_helpers["_search_civitai_models"]
    _inspect_civitai_model = _admin_helpers["_inspect_civitai_model"]
    _create_model_download_job = _admin_helpers["_create_model_download_job"]
    _update_model_download_job = _admin_helpers["_update_model_download_job"]
    _update_model_download_progress = _admin_helpers["_update_model_download_progress"]
    _get_model_download_job = _admin_helpers["_get_model_download_job"]
    _assert_model_download_job_owner = _admin_helpers["_assert_model_download_job_owner"]
    _parse_civitai_download_request = _admin_helpers["_parse_civitai_download_request"]
    _download_comfyui_model_file = _admin_helpers["_download_comfyui_model_file"]
    _download_civitai_model_selection = _admin_helpers["_download_civitai_model_selection"]
    _upload_comfyui_model_file = _admin_helpers["_upload_comfyui_model_file"]
    _client = _admin_helpers["_client"]
    _client_for_url = _admin_helpers["_client_for_url"]
    del _admin_helpers

    _billing_helpers = build_comfyui_billing_helpers({
        "COMFYUI_BASIC_PRICE_ITEM_KEY": COMFYUI_BASIC_PRICE_ITEM_KEY,
        "COMFYUI_LORA_EXTRA_PRICE_POINTS": COMFYUI_LORA_EXTRA_PRICE_POINTS,
        "COMFYUI_VAE_BUILTIN": COMFYUI_VAE_BUILTIN,
        "actor_value": _actor_value,
        "get_member_level_rule": get_member_level_rule,
        "points_service": points_service,
    })
    _is_root = _billing_helpers["_is_root"]
    _comfyui_charge_required = _billing_helpers["_comfyui_charge_required"]
    _comfyui_wallet_payload = _billing_helpers["_comfyui_wallet_payload"]
    _comfyui_lora_count = _billing_helpers["_comfyui_lora_count"]
    _comfyui_price_quote = _billing_helpers["_comfyui_price_quote"]
    _comfyui_total_quantity = _billing_helpers["_comfyui_total_quantity"]
    _ensure_comfyui_balance = _billing_helpers["_ensure_comfyui_balance"]
    _charge_comfyui_generation = _billing_helpers["_charge_comfyui_generation"]
    del _billing_helpers

    def _json_error_from_comfy(exc, active_client=None):
        active_client = active_client or _client()
        return json_resp({
            "ok": False,
            "msg": str(exc),
            "connection_mode": _configured_connection_mode(),
            "comfyui_url": getattr(active_client, "base_url", _configured_comfyui_url()),
        }), 503

    def _serialize_generation_result(actor, params, result, billing):
        result_images = result.get("images") if isinstance(result.get("images"), list) else []
        if not result_images:
            result_images = [{
                "image_ref": result["image_ref"],
                "mime_type": result["mime_type"],
                "data": result["data"],
            }]
        images = []
        for index, item in enumerate(result_images):
            raw_data = item.get("data") or b""
            mime_type = item.get("mime_type") or result.get("mime_type") or "image/png"
            image_ref_item = item.get("image_ref") if isinstance(item.get("image_ref"), dict) else result["image_ref"]
            images.append({
                "prompt_id": result["prompt_id"],
                "image_ref": image_ref_item,
                "mime_type": mime_type,
                "size_bytes": len(raw_data),
                "data_url": f"data:{mime_type};base64,{base64.b64encode(raw_data).decode('ascii')}",
                "seed": params["seed"],
                "model": params["model"],
                "batch_size": params["batch_size"],
                "batch_index": index,
            })
        image = images[0]
        return {
            "image": image,
            "images": images,
            "billing": billing,
        }

    def _finalize_generation_records(actor, params, result, *, backend_url=""):
        result_images = result.get("images") if isinstance(result.get("images"), list) else []
        if not result_images:
            result_images = [{
                "image_ref": result["image_ref"],
                "mime_type": result["mime_type"],
                "data": result["data"],
            }]
        images = []
        for index, item in enumerate(result_images):
            raw_data = item.get("data") or b""
            mime_type = item.get("mime_type") or result.get("mime_type") or "image/png"
            image_ref_item = item.get("image_ref") if isinstance(item.get("image_ref"), dict) else result["image_ref"]
            images.append({
                "prompt_id": result["prompt_id"],
                "image_ref": image_ref_item,
                "mime_type": mime_type,
                "size_bytes": len(raw_data),
                "data_url": f"data:{mime_type};base64,{base64.b64encode(raw_data).decode('ascii')}",
                "seed": params["seed"],
                "model": params["model"],
                "batch_size": params["batch_size"],
                "batch_index": index,
            })
        conn = get_db()
        try:
            _register_comfyui_image_refs(conn, actor=actor, images=images, backend_url=backend_url)
            create_notification_if_enabled(
                conn,
                user_id=_actor_value(actor, "id"),
                type="comfyui_generation_completed",
                title="ComfyUI 產圖完成",
                body=f"你的 ComfyUI 產圖已完成，共產生 {len(images)} 張圖片。",
                link="/comfyui",
            )
            conn.commit()
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass
        finally:
            conn.close()
        return images

    def _serialize_comfyui_media_records(result):
        media = result.get("media") if isinstance(result.get("media"), dict) else {}
        items = []
        for media_kind, records in media.items():
            if media_kind not in {"videos", "audio", "other"} or not isinstance(records, list):
                continue
            for index, item in enumerate(records):
                raw_data = item.get("data") or b""
                file_ref = item.get("file_ref") if isinstance(item.get("file_ref"), dict) else item.get("image_ref")
                if not file_ref:
                    continue
                mime_type = item.get("mime_type") or "application/octet-stream"
                items.append({
                    "prompt_id": result.get("prompt_id") or "",
                    "media_kind": "video" if media_kind == "videos" else ("audio" if media_kind == "audio" else "file"),
                    "file_ref": file_ref,
                    "mime_type": mime_type,
                    "size_bytes": len(raw_data),
                    "data_url": f"data:{mime_type};base64,{base64.b64encode(raw_data).decode('ascii')}" if raw_data else "",
                    "batch_index": index,
                })
        return items

    def _run_comfyui_generation_job(job_id, actor, params, quote, timeout_seconds, request_meta=None, backend_binding=None):
        backend_binding = backend_binding if isinstance(backend_binding, dict) else _comfyui_binding(actor)
        active_client = _client_for_url(backend_binding["url"])
        generation_token = _register_active_generation(
            actor,
            backend_url=backend_binding.get("url"),
            backend_scope=backend_binding.get("backend_scope"),
        )
        request_meta = request_meta if isinstance(request_meta, dict) else {}
        audit_ip = request_meta.get("client_ip") or "-"
        audit_ua = request_meta.get("user_agent") or "-"
        _update_generation_job(job_id, status="running")
        try:
            result = active_client.generate_image(
                params,
                timeout_seconds=timeout_seconds,
                progress_callback=lambda progress: _update_generation_job_progress(job_id, progress),
            )
            billing = {"charged": False, "exempt": "root"} if not quote else None
            if quote:
                billing = _charge_comfyui_generation(actor, quote, prompt_id=result.get("prompt_id"))
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
            payload = {
                "image": images[0],
                "images": images,
                "billing": billing,
                "history_id": history_id,
                "wallet": (billing or {}).get("wallet") or _comfyui_wallet_payload(actor),
            }
            audit(
                "COMFYUI_GENERATE",
                audit_ip,
                user=_actor_value(actor, "username"),
                success=True,
                ua=audit_ua,
                detail=f"job_id={job_id}, prompt_id={result['prompt_id']}, file={result['image_ref'].get('filename')}, batch={len(images)}",
            )
            _update_generation_job_progress(job_id, {
                "phase": "completed",
                "percent": 100,
                "completed": True,
                "detail": f"已完成，共 {len(images)} 張",
            })
            _update_generation_job(
                job_id,
                status="completed",
                result=payload,
                error="",
            )
        except ComfyUIError as exc:
            _update_generation_job(job_id, status="error", error=str(exc), result=None)
            _update_generation_job_progress(job_id, {
                "phase": "error",
                "detail": str(exc),
                "completed": False,
            })
            audit("COMFYUI_GENERATE_ERROR", audit_ip, user=_actor_value(actor, "username"), success=False, ua=audit_ua, detail=str(exc)[:180])
        except Exception as exc:
            _update_generation_job(job_id, status="error", error=str(exc), result=None)
            _update_generation_job_progress(job_id, {
                "phase": "error",
                "detail": str(exc),
                "completed": False,
            })
            audit("COMFYUI_GENERATE_ERROR", audit_ip, user=_actor_value(actor, "username"), success=False, ua=audit_ua, detail=str(exc)[:180])
        finally:
            _unregister_active_generation(generation_token)

    def _comfyui_account_api_key():
        return str((get_system_settings() or {}).get("comfyui_account_api_key") or os.environ.get("COMFYUI_ACCOUNT_API_KEY") or "").strip()

    def _comfyui_paid_api_status_payload():
        settings = get_system_settings() or {}
        return {
            "enabled": bool(settings.get("comfyui_paid_api_nodes_enabled")),
            "key_configured": bool(_comfyui_account_api_key()),
            "credit_balance_available": False,
            "credit_balance": None,
            "credits_msg": "ComfyUI credits 目前沒有穩定官方 REST endpoint；請在 ComfyUI UI 的 Settings / Credits 查看餘額。",
        }

    def _comfyui_paid_api_policy(workflow_json, *, confirm=False, object_info=None):
        paid_api = detect_paid_api_nodes(workflow_json, object_info=object_info)
        if not paid_api.get("required"):
            return {}, None
        settings = get_system_settings() or {}
        if not bool(settings.get("comfyui_paid_api_nodes_enabled")):
            return None, (
                json_resp({
                    "ok": False,
                    "msg": "這個 workflow 含有可能需要付費的 ComfyUI API node，但伺服器尚未允許付費/API nodes。",
                    "stage": "paid_api_nodes_disabled",
                    "paid_api_nodes": paid_api,
                }),
                409,
            )
        api_key = _comfyui_account_api_key()
        if not api_key:
            return None, (
                json_resp({
                    "ok": False,
                    "msg": "這個 workflow 需要 ComfyUI Account API Key；請先由 root 在伺服器設定中保存 key。",
                    "stage": "paid_api_key_missing",
                    "paid_api_nodes": paid_api,
                }),
                409,
            )
        if not confirm:
            return None, (
                json_resp({
                    "ok": False,
                    "msg": "這個 workflow 可能消耗 ComfyUI API credits，請先確認後再執行。",
                    "stage": "paid_api_confirmation_required",
                    "paid_api_nodes": paid_api,
                    "confirmation_required": True,
                }),
                409,
            )
        return build_comfyui_account_extra_data(api_key), None

    def _run_comfyui_workflow_preset_job(job_id, actor, row, run_id, timeout_seconds, request_meta=None, prompt_extra_data=None, workflow_override=None):
        backend_binding = _comfyui_binding(actor)
        active_client = _client_for_url(backend_binding["url"])
        request_meta = request_meta if isinstance(request_meta, dict) else {}
        audit_ip = request_meta.get("client_ip") or "-"
        audit_ua = request_meta.get("user_agent") or "-"
        _update_generation_job(job_id, status="running")
        workflow_json = workflow_override if isinstance(workflow_override, dict) else (_parse_json_field(row["workflow_json"], {}) or {})
        default_params = _parse_json_field(row["default_params_json"], {}) or {}
        prompt = str(default_params.get("prompt") or "")
        negative_prompt = str(default_params.get("negative_prompt") or "")
        expected_count = max(1, int(default_params.get("batch_size") or 1))
        try:
            run_kwargs = {
                "timeout_seconds": timeout_seconds,
                "expected_count": expected_count,
                "progress_callback": lambda progress: _update_generation_job_progress(job_id, progress),
            }
            if prompt_extra_data:
                run_kwargs["extra_data"] = prompt_extra_data
            result = active_client.generate_from_workflow(workflow_json, **run_kwargs)
            images = (
                _finalize_generation_records(actor, default_params, result, backend_url=backend_binding.get("url"))
                if isinstance(result.get("images"), list) and result.get("images")
                else []
            )
            media = _serialize_comfyui_media_records(result)
            output_refs = {
                "prompt_id": result.get("prompt_id") or "",
                "images": [
                    {
                        "image_ref": item.get("image_ref"),
                        "mime_type": item.get("mime_type"),
                        "size_bytes": item.get("size_bytes"),
                    }
                    for item in images
                ],
                "media": [
                    {
                        "media_kind": item.get("media_kind"),
                        "file_ref": item.get("file_ref"),
                        "mime_type": item.get("mime_type"),
                        "size_bytes": item.get("size_bytes"),
                    }
                    for item in media
                ],
            }
            conn = get_db()
            try:
                _update_workflow_run(conn, run_id=run_id, status="completed", output_refs=output_refs, error="")
                conn.commit()
            finally:
                conn.close()
            payload = {
                "image": images[0] if images else None,
                "images": images,
                "media": media,
                "workflow_run_id": run_id,
                "preset_id": int(row["id"]),
            }
            _update_generation_job(job_id, status="completed", result=payload, error="")
            _update_generation_job_progress(job_id, {
                "phase": "completed",
                "percent": 100,
                "completed": True,
                "detail": f"已完成，共 {len(images)} 張圖片、{len(media)} 個媒體輸出",
            })
            audit(
                "COMFYUI_WORKFLOW_RUN",
                audit_ip,
                user=_actor_value(actor, "username"),
                success=True,
                ua=audit_ua,
                detail=f"job_id={job_id}, preset_id={row['id']}, run_id={run_id}, prompt_id={result.get('prompt_id') or ''}",
            )
        except ComfyUIError as exc:
            conn = get_db()
            try:
                _update_workflow_run(conn, run_id=run_id, status="error", output_refs={}, error=str(exc))
                conn.commit()
            finally:
                conn.close()
            _update_generation_job(job_id, status="error", error=str(exc), result=None)
            _update_generation_job_progress(job_id, {"phase": "error", "detail": str(exc), "completed": False})
            audit("COMFYUI_WORKFLOW_RUN_ERROR", audit_ip, user=_actor_value(actor, "username"), success=False, ua=audit_ua, detail=str(exc)[:180])
        except Exception as exc:
            conn = get_db()
            try:
                _update_workflow_run(conn, run_id=run_id, status="error", output_refs={}, error=str(exc))
                conn.commit()
            finally:
                conn.close()
            _update_generation_job(job_id, status="error", error=str(exc), result=None)
            _update_generation_job_progress(job_id, {"phase": "error", "detail": str(exc), "completed": False})
            audit("COMFYUI_WORKFLOW_RUN_ERROR", audit_ip, user=_actor_value(actor, "username"), success=False, ua=audit_ua, detail=str(exc)[:180])

    def _run_comfyui_model_download_job(job_id, actor, request_data, request_meta=None):
        request_data = dict(request_data or {})
        request_meta = request_meta if isinstance(request_meta, dict) else {}
        audit_ip = request_meta.get("client_ip") or "-"
        audit_ua = request_meta.get("user_agent") or "-"
        _update_model_download_job(job_id, status="running")
        parsed_request, msg = _parse_civitai_download_request(request_data)
        if msg:
            _update_model_download_job(job_id, status="error", error=msg, result=None)
            _update_model_download_progress(job_id, {
                "phase": "error",
                "detail": msg,
                "completed": False,
            })
            return
        try:
            result, msg = _download_civitai_model_selection(
                page_url=parsed_request["page_url"],
                version_id=parsed_request["version_id"],
                file_id=parsed_request["file_id"],
                model_type=parsed_request["model_type"],
                base_dir=parsed_request["base_dir"],
                relative_dir=parsed_request["relative_dir"],
                progress_callback=lambda progress: _update_model_download_progress(job_id, progress),
            )
            if msg:
                raise ValueError(msg)
            _update_model_download_job(job_id, status="completed", error="", result=result)
            _update_model_download_progress(job_id, {
                "phase": "completed",
                "percent": 100,
                "bytes_written": int((result or {}).get("size_bytes") or 0),
                "total_bytes": int((result or {}).get("size_bytes") or 0),
                "detail": f"已下載 {(result or {}).get('filename') or ''}",
                "completed": True,
            })
            audit(
                "COMFYUI_CIVITAI_DOWNLOAD",
                audit_ip,
                user=_actor_value(actor, "username"),
                success=True,
                ua=audit_ua,
                detail=f"async_job={job_id}, type={(result or {}).get('type') or ''}, filename={(result or {}).get('filename') or ''}",
            )
        except Exception as exc:
            _update_model_download_job(job_id, status="error", error=str(exc), result=None)
            _update_model_download_progress(job_id, {
                "phase": "error",
                "detail": str(exc),
                "completed": False,
            })
            audit("COMFYUI_CIVITAI_DOWNLOAD", audit_ip, user=_actor_value(actor, "username"), success=False, ua=audit_ua, detail=f"async_job={job_id}, error={str(exc)[:220]}")

    def _comfyui_unavailable_payload(exc, active_client=None):
        active_client = active_client or _client()
        return {
            "ok": True,
            "available": False,
            "msg": str(exc),
            "connection_mode": _configured_connection_mode(),
            "comfyui_url": getattr(active_client, "base_url", _configured_comfyui_url()),
        }

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

    def _normalize_loras(data):
        raw_loras = data.get("loras") if isinstance(data, dict) else []
        if raw_loras in (None, ""):
            return [], None
        if not isinstance(raw_loras, list):
            return None, "LoRA 參數格式不正確"
        normalized = []
        seen = set()
        for item in raw_loras[:MAX_COMFYUI_LORAS_PER_PROMPT]:
            if isinstance(item, str):
                item = {"name": item}
            if not isinstance(item, dict):
                return None, "LoRA 參數格式不正確"
            name = str(item.get("name") or item.get("lora_name") or "").strip()
            if not name:
                continue
            if "/" in name or "\\" in name or ".." in name:
                return None, "LoRA 名稱不合法"
            if name in seen:
                continue
            seen.add(name)
            detail = _build_lora_details([name]).get(name) or {}
            if detail.get("supported") is not True:
                return None, detail.get("support_message") or (
                    "這個 LoRA 目前不支援；只允許 SDXL、Pony、Illustrious、Noob 系列 LoRA。"
                )
            normalized.append({
                "name": name[:180],
                "strength_model": _float_range(item.get("strength_model"), 1.0, -2.0, 2.0),
                "strength_clip": _float_range(item.get("strength_clip"), 1.0, -2.0, 2.0),
            })
        return normalized, None

    def _normalize_comfyui_prompt_text(value):
        text = str(value or "").strip()
        if not text:
            return ""
        text = COMFYUI_EMBEDDING_TOKEN_RE.sub(
            lambda match: f"embedding:{match.group(1).strip()}",
            text,
        )
        return text

    def _normalize_comfyui_vae_name(value):
        text = str(value or "").strip()
        if not text or text == COMFYUI_VAE_BUILTIN:
            return ""
        if "/" in text or "\\" in text or ".." in text:
            return None
        return text[:180]

    def _clean_filename(name, fallback="comfyui.png"):
        text = str(name or "").strip()
        text = text.split("/")[-1].split("\\")[-1]
        text = re.sub(r"[^A-Za-z0-9_.-]+", "_", text)
        if not text:
            text = fallback
        if "." not in text:
            text += ".png"
        return text[:120]

    def _parse_json_field(value, fallback):
        if value in (None, ""):
            return fallback
        if isinstance(value, (dict, list)):
            return value
        try:
            return json.loads(str(value))
        except Exception:
            return fallback

    def _number_from_text(value, *, label, numeric_type=float):
        if value in (None, ""):
            return None, None
        try:
            return numeric_type(value), None
        except Exception:
            return None, f"{label} 格式不正確"

    def _normalized_generation_mode(value):
        mode = str(value or "txt2img").strip().lower()
        return mode if mode in GENERATION_MODE_DEFINITIONS else None

    def _validate_image_upload(file_storage, *, label):
        if not file_storage:
            return None, None
        filename = str(getattr(file_storage, "filename", "") or "").strip()
        mime_type = str(getattr(file_storage, "mimetype", "") or "").strip().lower()
        ext = Path(filename).suffix.lower()
        if ext not in COMFYUI_ALLOWED_IMAGE_EXTENSIONS or mime_type not in COMFYUI_ALLOWED_IMAGE_MIME_TYPES:
            return None, f"{label} 只支援 PNG / JPG / WEBP"
        data = file_storage.read()
        try:
            file_storage.stream.seek(0)
        except Exception:
            pass
        if not data:
            return None, f"{label} 內容不可為空"
        return {
            "filename": _clean_filename(filename, fallback="image.png"),
            "mime_type": mime_type,
            "data": data,
        }, None

    def _normalize_image_ref_field(value):
        payload = _parse_json_field(value, None)
        if not isinstance(payload, dict):
            return None
        return _image_ref_payload(payload)

    def _normalize_controlnet_payload(data):
        enabled = _coerce_bool(data.get("controlnet_enabled"))
        if not enabled and isinstance(data.get("controlnet"), dict):
            enabled = True
        if not enabled:
            return None, None
        control_type = str(
            data.get("controlnet_type")
            or ((data.get("controlnet") or {}).get("type") if isinstance(data.get("controlnet"), dict) else "")
            or ""
        ).strip().lower()
        if control_type not in CONTROLNET_TYPE_DEFINITIONS:
            return None, "請選擇有效的 ControlNet 類型"
        strength, err = _number_from_text(
            data.get("control_strength")
            if "control_strength" in data
            else ((data.get("controlnet") or {}).get("strength") if isinstance(data.get("controlnet"), dict) else None),
            label="Control strength",
            numeric_type=float,
        )
        if err:
            return None, err
        start_percent, err = _number_from_text(
            data.get("control_start")
            if "control_start" in data
            else ((data.get("controlnet") or {}).get("start_percent") if isinstance(data.get("controlnet"), dict) else None),
            label="Control start",
            numeric_type=float,
        )
        if err:
            return None, err
        end_percent, err = _number_from_text(
            data.get("control_end")
            if "control_end" in data
            else ((data.get("controlnet") or {}).get("end_percent") if isinstance(data.get("controlnet"), dict) else None),
            label="Control end",
            numeric_type=float,
        )
        if err:
            return None, err
        strength = 1.0 if strength is None else strength
        start_percent = 0.0 if start_percent is None else start_percent
        end_percent = 1.0 if end_percent is None else end_percent
        if strength < 0 or strength > 2:
            return None, "Control strength 必須介於 0 到 2"
        if start_percent < 0 or start_percent > 1 or end_percent < 0 or end_percent > 1 or start_percent > end_percent:
            return None, "Control start / end 必須介於 0 到 1，且 start 不可大於 end"
        preprocessor = str(
            data.get("controlnet_preprocessor")
            or ((data.get("controlnet") or {}).get("preprocessor") if isinstance(data.get("controlnet"), dict) else "")
            or ""
        ).strip()
        model_name = str(
            data.get("controlnet_model")
            or ((data.get("controlnet") or {}).get("model_name") if isinstance(data.get("controlnet"), dict) else "")
            or ""
        ).strip()
        return {
            "enabled": True,
            "type": control_type,
            "strength": round(float(strength), 4),
            "start_percent": round(float(start_percent), 4),
            "end_percent": round(float(end_percent), 4),
            "preprocessor": preprocessor,
            "model_name": model_name,
        }, None

    def _normalize_outpaint_payload(data):
        return {
            "left": _int_range(data.get("outpaint_left"), 0, 0, 2048),
            "top": _int_range(data.get("outpaint_top"), 0, 0, 2048),
            "right": _int_range(data.get("outpaint_right"), 0, 0, 2048),
            "bottom": _int_range(data.get("outpaint_bottom"), 0, 0, 2048),
            "feathering": _int_range(data.get("outpaint_feathering"), 24, 0, 256),
        }

    def _normalize_generation_payload(data):
        mode = _normalized_generation_mode(data.get("generation_mode"))
        if not mode:
            return None, "ComfyUI 產圖模式不支援"
        mode_definition = GENERATION_MODE_DEFINITIONS.get(mode) or {}
        workflow_only = bool(mode_definition.get("workflow_only"))
        prompt = _normalize_comfyui_prompt_text(data.get("prompt"))
        if mode != "upscale" and mode != "v2v" and not prompt:
            return None, "請輸入提示詞"
        if len(prompt) > 3000:
            return None, "提示詞最多 3000 字"
        negative = _normalize_comfyui_prompt_text(data.get("negative_prompt"))
        if len(negative) > 3000:
            return None, "負面提示詞最多 3000 字"
        model = str(data.get("model") or "").strip()
        if mode != "upscale" and not workflow_only and not model:
            return None, "請選擇模型"
        vae = _normalize_comfyui_vae_name(data.get("vae"))
        if vae is None:
            return None, "VAE 名稱不合法"
        loras_source = dict(data)
        if loras_source.get("loras") in (None, "") and loras_source.get("loras_json") not in (None, ""):
            loras_source["loras"] = _parse_json_field(loras_source.get("loras_json"), [])
        loras, lora_msg = _normalize_loras(loras_source)
        if lora_msg:
            return None, lora_msg
        seed = _int_range(data.get("seed"), secrets.randbits(32), 0, 2**63 - 1)
        default_dimensions = _configured_default_dimensions()
        controlnet, controlnet_msg = _normalize_controlnet_payload(data)
        if controlnet_msg:
            return None, controlnet_msg
        denoise_strength, denoise_err = _number_from_text(data.get("denoise_strength"), label="Denoise strength", numeric_type=float)
        if denoise_err:
            return None, denoise_err
        if denoise_strength is not None and (denoise_strength < 0 or denoise_strength > 1):
            return None, "Denoise strength 必須介於 0 到 1"
        params = {
            "generation_mode": mode,
            "model": model,
            "prompt": prompt,
            "negative_prompt": negative,
            "width": _int_range(data.get("width"), default_dimensions["width"], 64, 2048, multiple_of=8),
            "height": _int_range(data.get("height"), default_dimensions["height"], 64, 2048, multiple_of=8),
            "steps": _int_range(data.get("steps"), 20, 1, 80),
            "cfg": _float_range(data.get("cfg"), 7.0, 1.0, 30.0),
            "sampler_name": str(data.get("sampler_name") or SAFE_SAMPLER_FALLBACK).strip() or SAFE_SAMPLER_FALLBACK,
            "scheduler": str(data.get("scheduler") or SAFE_SCHEDULER_FALLBACK).strip() or SAFE_SCHEDULER_FALLBACK,
            "seed": seed,
            "batch_size": _int_range(data.get("batch_size"), 1, 1, _configured_max_batch_size()),
            "filename_prefix": _clean_filename(data.get("filename_prefix") or "hackme_web", fallback="hackme_web").rsplit(".", 1)[0],
            "loras": loras,
            "vae": vae,
            "denoise_strength": 0.65 if denoise_strength is None else round(float(denoise_strength), 4),
            "controlnet": controlnet,
            "source_image_ref": _normalize_image_ref_field(data.get("source_image_ref") or data.get("source_image_ref_json")),
            "mask_image_ref": _normalize_image_ref_field(data.get("mask_image_ref") or data.get("mask_image_ref_json")),
            "upscale_model": str(data.get("upscale_model") or "").strip(),
            "outpaint": _normalize_outpaint_payload(data),
        }
        skip_asset_validation = _coerce_bool(data.get("skip_asset_validation"))
        if not skip_asset_validation and mode == "img2img" and not params["source_image_ref"]:
            return None, "圖生圖需要來源圖片"
        if not skip_asset_validation and mode == "inpaint":
            if not params["source_image_ref"]:
                return None, "局部重繪需要來源圖片"
            if not params["mask_image_ref"]:
                return None, "局部重繪需要遮罩圖片"
        if not skip_asset_validation and mode == "outpaint" and not params["source_image_ref"]:
            return None, "向外延展需要來源圖片"
        if not skip_asset_validation and mode == "upscale":
            if not params["source_image_ref"]:
                return None, "放大修復需要來源圖片"
            if not params["upscale_model"]:
                return None, "請選擇放大模型"
        if not skip_asset_validation and mode == "i2v" and not params["source_image_ref"]:
            return None, "圖生影片需要來源圖片"
        return params, None

    def _safe_text(value, limit):
        text = str(value or "").strip()
        text = re.sub(r"\r\n?", "\n", text)
        return text[:limit]

    def _ensure_comfyui_share_schema(conn):
        now = None
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS forum_categories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                description TEXT,
                sort_order INTEGER NOT NULL DEFAULT 100,
                is_active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS forum_boards (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                category_id INTEGER REFERENCES forum_categories(id) ON DELETE SET NULL,
                slug TEXT UNIQUE,
                title TEXT NOT NULL,
                description TEXT NOT NULL,
                rules TEXT,
                visibility TEXT NOT NULL DEFAULT 'public',
                sort_order INTEGER NOT NULL DEFAULT 100,
                is_active INTEGER NOT NULL DEFAULT 1,
                last_activity_at TEXT,
                owner_user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                owner_username TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'approved',
                review_note TEXT,
                reviewed_by TEXT,
                reviewed_at TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS forum_threads (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                board_id INTEGER NOT NULL REFERENCES forum_boards(id) ON DELETE CASCADE,
                title TEXT NOT NULL,
                content TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'approved',
                review_note TEXT,
                reviewed_by TEXT,
                reviewed_at TEXT,
                post_type TEXT NOT NULL DEFAULT 'normal',
                is_sticky INTEGER NOT NULL DEFAULT 0,
                is_locked INTEGER NOT NULL DEFAULT 0,
                is_curated INTEGER NOT NULL DEFAULT 0,
                view_count INTEGER NOT NULL DEFAULT 0,
                edited_at TEXT,
                edited_by TEXT,
                is_deleted INTEGER NOT NULL DEFAULT 0,
                deleted_at TEXT,
                deleted_by TEXT,
                delete_reason TEXT,
                author_user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                author_username TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            """
        )
        return now

    def _find_or_create_comfyui_board(conn, actor):
        _ensure_comfyui_share_schema(conn)
        row = conn.execute(
            """
            SELECT id, title FROM forum_boards
            WHERE is_active=1 AND status='approved' AND (title='ComfyUI專區' OR title LIKE '%ComfyUI%')
            ORDER BY CASE WHEN title='ComfyUI專區' THEN 0 ELSE 1 END, sort_order ASC, id ASC
            LIMIT 1
            """
        ).fetchone()
        if row:
            return dict(row)
        now = datetime.now().isoformat()
        conn.execute(
            "INSERT OR IGNORE INTO forum_categories (name, description, sort_order, is_active, created_at, updated_at) VALUES (?, ?, ?, 1, ?, ?)",
            ("交流討論", "預設討論分類", 10, now, now),
        )
        category = conn.execute("SELECT id FROM forum_categories WHERE name=?", ("交流討論",)).fetchone()
        cur = conn.execute(
            """
            INSERT INTO forum_boards (
                category_id, slug, title, description, rules, visibility, sort_order, is_active,
                last_activity_at, owner_user_id, owner_username, status, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, 'public', 30, 1, ?, ?, ?, 'approved', ?, ?)
            """,
            (
                category["id"] if category else None,
                "comfyui",
                "ComfyUI專區",
                "ComfyUI 工作流、模型、節點與生成參數交流。",
                "分享工作流時請標註來源與使用限制。",
                now,
                int(_actor_value(actor, "id")),
                _actor_value(actor, "username", "system"),
                now,
                now,
            ),
        )
        return {"id": cur.lastrowid, "title": "ComfyUI專區"}

    def _maybe_add_to_album(conn, *, actor, album_id, storage_file_id, file_id, caption=""):
        normalized_album_id = str(album_id or "").strip()
        if not normalized_album_id:
            return None, None
        album, msg = add_album_file(
            conn,
            actor=actor,
            album_id=normalized_album_id,
            storage_file_id=storage_file_id,
            file_id=file_id,
            caption=caption,
        )
        if msg and msg != "檔案已在相簿內":
            return None, msg
        if album is None:
            album = {"id": normalized_album_id, "already_exists": True}
        return album, None

    def _find_or_create_output_album(conn, *, actor):
        return ensure_output_album(conn, actor=actor)

    def _save_fetched_image(conn, *, actor, data, image):
        filename = _clean_filename(data.get("display_name") or image.filename)
        guessed_mime = mimetypes.guess_type(filename)[0] or image.mime_type or "image/png"
        memory_file = _MemoryFile(image.data, filename, guessed_mime)
        ensure_cloud_drive_attachment_schema(conn)
        ensure_storage_album_schema(conn)
        rule = get_member_level_rule(conn, _actor_value(actor, "effective_level") or _actor_value(actor, "member_level"))
        upload_result, msg = store_cloud_upload(
            conn,
            actor=actor,
            member_rule=rule,
            storage_root=storage_root,
            file_storage=memory_file,
            privacy_mode="standard_plain",
            scan_now=True,
        )
        if msg:
            return None, None, None, msg
        file_row = conn.execute("SELECT * FROM uploaded_files WHERE id=?", (upload_result["file_id"],)).fetchone()
        virtual_path = str(data.get("virtual_path") or "").strip()
        if not virtual_path:
            virtual_path = f"/output/{filename}"
        default_output_album = None
        if virtual_path.replace("\\", "/").strip().lower().startswith("/output/"):
            default_output_album, msg = _find_or_create_output_album(conn, actor=actor)
            if msg:
                return None, None, None, msg
        storage_file, msg = create_storage_file_entry(
            conn,
            actor=actor,
            file_row=file_row,
            virtual_path=virtual_path,
            display_name=filename,
            source="comfyui",
        )
        if msg:
            return None, None, None, msg
        selected_album_id = str(data.get("album_id") or "").strip()
        output_album_id = str((default_output_album or {}).get("id") or "").strip()
        album = None
        if output_album_id:
            album, msg = _maybe_add_to_album(
                conn,
                actor=actor,
                album_id=output_album_id,
                storage_file_id=storage_file["id"],
                file_id=upload_result["file_id"],
                caption="ComfyUI 產圖",
            )
            if msg:
                return None, None, None, msg
        if selected_album_id and selected_album_id != output_album_id:
            album, msg = _maybe_add_to_album(
                conn,
                actor=actor,
                album_id=selected_album_id,
                storage_file_id=storage_file["id"],
                file_id=upload_result["file_id"],
                caption="ComfyUI 產圖",
            )
            if msg:
                return None, None, None, msg
        return upload_result, storage_file, album, None

    def _existing_saved_image(conn, *, actor, data):
        file_id = str(data.get("file_id") or data.get("saved_file_id") or "").strip()
        if not file_id:
            return None
        ensure_cloud_drive_attachment_schema(conn)
        ensure_storage_album_schema(conn)
        file_row = conn.execute("SELECT * FROM uploaded_files WHERE id=? AND deleted_at IS NULL", (file_id,)).fetchone()
        if not file_row or int(file_row["owner_user_id"]) != int(_actor_value(actor, "id")):
            return None
        storage_file_id = str(data.get("storage_file_id") or "").strip()
        params = [file_id, int(_actor_value(actor, "id"))]
        where = "file_id=? AND owner_user_id=? AND deleted_at IS NULL AND COALESCE(is_trashed, 0)=0"
        if storage_file_id:
            where += " AND id=?"
            params.append(storage_file_id)
        storage_row = conn.execute(
            f"SELECT * FROM storage_files WHERE {where} ORDER BY updated_at DESC, created_at DESC LIMIT 1",
            tuple(params),
        ).fetchone()
        upload_result = {"file_id": file_id}
        storage_file = dict(storage_row) if storage_row else None
        album, msg = _maybe_add_to_album(
            conn,
            actor=actor,
            album_id=data.get("album_id"),
            storage_file_id=storage_file["id"] if storage_file else None,
            file_id=file_id,
            caption="ComfyUI 產圖",
        )
        if msg:
            return upload_result, storage_file, album, msg
        return upload_result, storage_file, album, None

    def _compose_comfyui_share_content(data, *, file_id, storage_file):
        params = data.get("generation") if isinstance(data.get("generation"), dict) else {}
        note = _safe_text(data.get("note"), 900)
        prompt = _safe_text(params.get("prompt") or data.get("prompt"), 1400)
        negative = _safe_text(params.get("negative_prompt") or data.get("negative_prompt"), 700)
        model = _safe_text(params.get("model"), 180)
        sampler = _safe_text(params.get("sampler_name"), 80)
        scheduler = _safe_text(params.get("scheduler"), 80)
        vae = _safe_text(params.get("vae"), 180)
        size = f"{params.get('width') or '-'} x {params.get('height') or '-'}"
        loras = params.get("loras") if isinstance(params.get("loras"), list) else []
        lora_text = ", ".join(
            _safe_text((item or {}).get("name"), 120)
            for item in loras
            if isinstance(item, dict) and str(item.get("name") or "").strip()
        )
        lines = []
        if note:
            lines.extend(["心得", note, ""])
        lines.extend([
            f"[[comfyui-image:{file_id}]]",
            f"圖片檔案：{_safe_text((storage_file or {}).get('display_name') or (storage_file or {}).get('virtual_path') or file_id, 160)}",
            "",
            "提示詞",
            prompt or "-",
            "",
            "負面提示詞",
            negative or "-",
            "",
            "產圖參數",
            f"模型：{model or '-'}",
            f"尺寸：{size}",
            f"步數：{params.get('steps') or '-'}",
            f"CFG：{params.get('cfg') or '-'}",
            f"張數：{params.get('batch_size') or 1}",
            f"Seed：{params.get('seed') if params.get('seed') is not None else '-'}",
            f"Sampler：{sampler or '-'}",
            f"Scheduler：{scheduler or '-'}",
            f"VAE：{vae or '使用 checkpoint 內建 VAE'}",
            f"LoRA：{lora_text or '-'}",
        ])
        return "\n".join(lines)[:3900]

    register_comfyui_runtime_routes(app, {
        "request": request,
        "json_resp": json_resp,
        "require_csrf": require_csrf,
        "require_csrf_safe": require_csrf_safe,
        "get_db": get_db,
        "get_client_ip": get_client_ip,
        "get_ua": get_ua,
        "audit": audit,
        "threading": threading,
        "ComfyUIError": ComfyUIError,
        "SAFE_SAMPLER_FALLBACK": SAFE_SAMPLER_FALLBACK,
        "SAFE_SCHEDULER_FALLBACK": SAFE_SCHEDULER_FALLBACK,
        "COMFYUI_LORA_EXTRA_PRICE_POINTS": COMFYUI_LORA_EXTRA_PRICE_POINTS,
        "COMFYUI_HISTORY_LIMIT": COMFYUI_HISTORY_LIMIT,
        "DEFAULT_GENERATION_TIMEOUT_SECONDS": DEFAULT_GENERATION_TIMEOUT_SECONDS,
        "MAX_GENERATION_TIMEOUT_SECONDS": MAX_GENERATION_TIMEOUT_SECONDS,
        "actor_or_401": _actor_or_401,
        "root_or_403": _root_or_403,
        "actor_value": _actor_value,
        "assert_generation_job_owner": _assert_generation_job_owner,
        "build_lora_details": _build_lora_details,
        "capture_request_audit_meta": _capture_request_audit_meta,
        "charge_comfyui_generation": _charge_comfyui_generation,
        "client_for_url": _client_for_url,
        "coerce_bool": _coerce_bool,
        "comfyui_binding": _comfyui_binding,
        "comfyui_charge_required": _comfyui_charge_required,
        "comfyui_lora_count": _comfyui_lora_count,
        "comfyui_price_quote": _comfyui_price_quote,
        "comfyui_total_quantity": _comfyui_total_quantity,
        "comfyui_unavailable_payload": _comfyui_unavailable_payload,
        "comfyui_wallet_payload": _comfyui_wallet_payload,
        "configured_comfyui_port": _configured_comfyui_port,
        "configured_comfyui_url": _configured_comfyui_url,
        "configured_connection_mode": _configured_connection_mode,
        "configured_default_dimensions": _configured_default_dimensions,
        "configured_max_batch_size": _configured_max_batch_size,
        "create_generation_job": _create_generation_job,
        "ensure_comfyui_balance": _ensure_comfyui_balance,
        "finalize_generation_records": _finalize_generation_records,
        "hydrate_generation_assets": _hydrate_generation_assets,
        "int_range": _int_range,
        "json_error_from_comfy": _json_error_from_comfy,
        "list_generation_history": _list_generation_history,
        "load_generation_history": _load_generation_history,
        "local_comfyui_runtime_status": _local_comfyui_runtime_status,
        "comfyui_paid_api_status_payload": _comfyui_paid_api_status_payload,
        "build_node_catalog": build_node_catalog,
        "normalize_generation_payload": _normalize_generation_payload,
        "parse_generation_request": _parse_generation_request,
        "record_generation_history": _record_generation_history,
        "register_active_generation": _register_active_generation,
        "run_comfyui_generation_job": _run_comfyui_generation_job,
        "start_local_comfyui": _start_local_comfyui,
        "stop_local_comfyui": _stop_local_comfyui,
        "unregister_active_generation": _unregister_active_generation,
        "validate_generation_capabilities": _validate_generation_capabilities,
    })

    register_comfyui_admin_routes(app, {
        "request": request,
        "root_or_403": _root_or_403,
        "actor_value": _actor_value,
        "json_resp": json_resp,
        "require_csrf": require_csrf,
        "require_csrf_safe": require_csrf_safe,
        "get_client_ip": get_client_ip,
        "get_ua": get_ua,
        "audit": audit,
        "parse_comfyui_endpoint": _parse_comfyui_endpoint,
        "local_start_script_status": _local_start_script_status,
        "client_for_url": _client_for_url,
        "ComfyUIError": ComfyUIError,
        "configured_connection_mode": _configured_connection_mode,
        "start_local_comfyui": _start_local_comfyui,
        "local_comfyui_runtime_status": _local_comfyui_runtime_status,
        "normalize_civitai_nsfw_mode": _normalize_civitai_nsfw_mode,
        "normalize_civitai_search_type": _normalize_civitai_search_type,
        "inspect_civitai_model": _inspect_civitai_model,
        "search_civitai_models": _search_civitai_models,
        "fetch_civitai_media": _fetch_civitai_media,
        "parse_civitai_download_request": _parse_civitai_download_request,
        "coerce_bool": _coerce_bool,
        "create_model_download_job": _create_model_download_job,
        "capture_request_audit_meta": _capture_request_audit_meta,
        "run_comfyui_model_download_job": _run_comfyui_model_download_job,
        "download_civitai_model_selection": _download_civitai_model_selection,
        "upload_comfyui_model_file": _upload_comfyui_model_file,
        "assert_model_download_job_owner": _assert_model_download_job_owner,
        "local_start_template_path": COMFYUI_LOCAL_START_TEMPLATE_PATH,
        "send_file": send_file,
        "threading": threading,
    })

    register_comfyui_template_routes(app, {
        "request": request,
        "actor_or_401": _actor_or_401,
        "actor_value": _actor_value,
        "json_resp": json_resp,
        "require_csrf": require_csrf,
        "get_client_ip": get_client_ip,
        "get_ua": get_ua,
        "audit": audit,
        "comfyui_binding": _comfyui_binding,
        "client_for_url": _client_for_url,
        "get_db": get_db,
        "upsert_workflow_preset": _upsert_workflow_preset,
        "load_workflow_preset_row": _load_workflow_preset_row,
        "workflow_preset_summary": _workflow_preset_summary,
    })

    register_comfyui_workflow_routes(app, {
        "request": request,
        "actor_or_401": _actor_or_401,
        "root_or_403": _root_or_403,
        "actor_value": _actor_value,
        "json_resp": json_resp,
        "require_csrf": require_csrf,
        "require_csrf_safe": require_csrf_safe,
        "get_db": get_db,
        "get_client_ip": get_client_ip,
        "get_ua": get_ua,
        "audit": audit,
        "comfyui_binding": _comfyui_binding,
        "client_for_url": _client_for_url,
        "load_workflow_preset": _load_workflow_preset,
        "workflow_preset_summary": _workflow_preset_summary,
        "workflow_manifest_for_row": _workflow_manifest_for_row,
        "parse_json_field": _parse_json_field,
        "extract_workflow_payload": _extract_workflow_payload,
        "normalize_workflow_default_params": _normalize_workflow_default_params,
        "upsert_workflow_preset": _upsert_workflow_preset,
        "load_workflow_preset_row": _load_workflow_preset_row,
        "WorkflowValidationError": WorkflowValidationError,
        "ComfyUIError": ComfyUIError,
        "list_workflow_presets": _list_workflow_presets,
        "workflow_dependency_status": _workflow_dependency_status,
        "list_workflow_runs": _list_workflow_runs,
        "normalize_generation_payload": _normalize_generation_payload,
        "validate_generation_capabilities": _validate_generation_capabilities,
        "sanitize_workflow_json": sanitize_workflow_json,
        "workflow_json_to_pretty_text": workflow_json_to_pretty_text,
        "analyze_workflow_json": analyze_workflow_json,
        "build_ui_schema": build_ui_schema,
        "check_workflow_capability": check_workflow_capability,
        "assert_workflow_dependencies_or_error": _assert_workflow_dependencies_or_error,
        "create_workflow_run": _create_workflow_run,
        "create_generation_job": _create_generation_job,
        "capture_request_audit_meta": _capture_request_audit_meta,
        "run_comfyui_workflow_preset_job": _run_comfyui_workflow_preset_job,
        "comfyui_paid_api_policy": _comfyui_paid_api_policy,
        "DEFAULT_GENERATION_TIMEOUT_SECONDS": DEFAULT_GENERATION_TIMEOUT_SECONDS,
        "COMFYUI_WORKFLOW_RUN_LIMIT": COMFYUI_WORKFLOW_RUN_LIMIT,
        "COMFYUI_WORKFLOW_SCHEMA_VERSION": COMFYUI_WORKFLOW_SCHEMA_VERSION,
        "APP_RELEASE_ID": APP_RELEASE_ID,
        "safe_text": _safe_text,
        "threading": threading,
    })

    register_comfyui_image_routes(app, {
        "base64": base64,
        "request": request,
        "json_resp": json_resp,
        "require_csrf": require_csrf,
        "get_db": get_db,
        "get_client_ip": get_client_ip,
        "get_ua": get_ua,
        "audit": audit,
        "attach_existing_file": attach_existing_file,
        "can_download_file": can_download_file,
        "datetime": datetime,
        "ComfyUIError": ComfyUIError,
        "active_generation_snapshot": _active_generation_snapshot,
        "actor_or_401": _actor_or_401,
        "actor_value": _actor_value,
        "assert_reasonable_image_size": _assert_reasonable_image_size,
        "client": _client,
        "client_for_url": _client_for_url,
        "comfyui_binding": _comfyui_binding,
        "compose_comfyui_share_content": _compose_comfyui_share_content,
        "configured_comfyui_base_dir": _configured_comfyui_base_dir,
        "configured_comfyui_project_dir": _configured_comfyui_project_dir,
        "existing_saved_image": _existing_saved_image,
        "find_or_create_comfyui_board": _find_or_create_comfyui_board,
        "generation_owner_id": _generation_owner_id,
        "image_ref_payload": _image_ref_payload,
        "interrupt_policy": _interrupt_policy,
        "is_root": _is_root,
        "json_error_from_comfy": _json_error_from_comfy,
        "load_comfyui_image_ref_record": _load_comfyui_image_ref_record,
        "list_generation_history": _list_generation_history,
        "normalize_comfyui_backend_url": _normalize_comfyui_backend_url,
        "register_comfyui_image_refs": _register_comfyui_image_refs,
        "resolve_file_storage_path": resolve_file_storage_path,
        "safe_text": _safe_text,
        "save_fetched_image": _save_fetched_image,
        "storage_root": storage_root,
        "COMFYUI_ALLOWED_IMAGE_EXTENSIONS": COMFYUI_ALLOWED_IMAGE_EXTENSIONS,
        "COMFYUI_ALLOWED_IMAGE_MIME_TYPES": COMFYUI_ALLOWED_IMAGE_MIME_TYPES,
        "MAX_COMFYUI_FETCH_IMAGE_BYTES": MAX_COMFYUI_FETCH_IMAGE_BYTES,
    })
