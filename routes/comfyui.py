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

from flask import request

from services.cloud_drive import attach_existing_file, ensure_cloud_drive_attachment_schema, store_cloud_upload
from services.comfyui_client import (
    CONTROLNET_TYPE_DEFINITIONS,
    GENERATION_MODE_DEFINITIONS,
    ComfyUIClient,
    ComfyUIError,
)
from services.comfyui_workflows import (
    WorkflowValidationError,
    extract_workflow_summary,
    sanitize_workflow_json,
    workflow_json_to_pretty_text,
)
from services.notifications import create_notification_if_enabled
from services.storage_albums import (
    add_album_file,
    create_storage_file_entry,
    ensure_output_album,
    ensure_storage_album_schema,
)


DEFAULT_COMFYUI_URL = os.environ.get("COMFYUI_API_URL", "http://localhost:8192")
DEFAULT_COMFYUI_PORT = 8192
SAFE_SAMPLER_FALLBACK = "euler"
SAFE_SCHEDULER_FALLBACK = "normal"
DEFAULT_GENERATION_TIMEOUT_SECONDS = 1800
MAX_GENERATION_TIMEOUT_SECONDS = 1800
COMFYUI_BASIC_PRICE_ITEM_KEY = "comfyui_txt2img_basic"
COMFYUI_HOST_RE = re.compile(r"^[A-Za-z0-9_.:-]+$")
MAX_COMFYUI_FETCH_IMAGE_BYTES = 50 * 1024 * 1024
MAX_COMFYUI_LORAS_PER_PROMPT = 8
COMFYUI_LORA_EXTRA_PRICE_POINTS = 1
COMFYUI_VAE_BUILTIN = "__checkpoint_builtin__"
COMFYUI_MODEL_DOWNLOAD_EXTENSIONS = {".safetensors", ".ckpt", ".pt", ".pth", ".bin"}
COMFYUI_MODEL_DOWNLOAD_TYPES = {
    "checkpoint": ("checkpoints", "Checkpoint"),
    "lora": ("loras", "LoRA"),
    "embedding": ("embeddings", "Embedding / Textual Inversion"),
    "vae": ("vae", "VAE"),
    "controlnet": ("controlnet", "ControlNet"),
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
CIVITAI_MODEL_TYPE_TO_DOWNLOAD_TYPE = {
    "checkpoint": "checkpoint",
    "lora": "lora",
    "textualinversion": "embedding",
    "embedding": "embedding",
    "vae": "vae",
    "controlnet": "controlnet",
}
CIVITAI_SEARCH_TYPE_TO_API = {
    "checkpoint": "Checkpoint",
    "lora": "LORA",
    "embedding": "TextualInversion",
    "controlnet": "Controlnet",
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
                workflow_json TEXT NOT NULL,
                workflow_hash TEXT NOT NULL DEFAULT '',
                required_models_json TEXT NOT NULL DEFAULT '[]',
                required_loras_json TEXT NOT NULL DEFAULT '[]',
                required_controlnets_json TEXT NOT NULL DEFAULT '[]',
                default_params_json TEXT NOT NULL DEFAULT '{}',
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
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(comfyui_workflow_presets)").fetchall()}
        if "published_by_user_id" not in columns:
            conn.execute("ALTER TABLE comfyui_workflow_presets ADD COLUMN published_by_user_id INTEGER")
        if "published_at" not in columns:
            conn.execute("ALTER TABLE comfyui_workflow_presets ADD COLUMN published_at TEXT")
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_comfyui_workflow_presets_owner ON comfyui_workflow_presets(owner_user_id, updated_at DESC)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_comfyui_workflow_presets_official ON comfyui_workflow_presets(is_official, updated_at DESC)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_comfyui_workflow_runs_preset ON comfyui_workflow_runs(preset_id, created_at DESC)"
        )

    def _normalize_workflow_visibility(value):
        text = str(value or "private").strip().lower() or "private"
        return text if text in COMFYUI_WORKFLOW_VISIBILITY_VALUES else "private"

    def _workflow_preset_summary(row, *, dependency_status=None, recent_runs=None, actor=None):
        default_params = _parse_json_field(row["default_params_json"], {}) or {}
        result = {
            "id": int(row["id"]),
            "owner_user_id": int(row["owner_user_id"]),
            "title": row["title"] or f"Workflow #{row['id']}",
            "description": row["description"] or "",
            "visibility": row["visibility"] or "private",
            "is_official": bool(row["is_official"]),
            "workflow_hash": row["workflow_hash"] or "",
            "required_models": _parse_json_field(row["required_models_json"], []) or [],
            "required_loras": _parse_json_field(row["required_loras_json"], []) or [],
            "required_controlnets": _parse_json_field(row["required_controlnets_json"], []) or [],
            "default_params": default_params,
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

    def _upsert_workflow_preset(conn, *, preset_id=None, actor, title, description, visibility, workflow_payload, default_params, is_official=False, published_by_user_id=None):
        _ensure_comfyui_workflow_schema(conn)
        now = datetime.now().isoformat()
        workflow_json = workflow_payload["workflow_json"]
        workflow_hash = workflow_payload["workflow_hash"]
        required_models = workflow_payload["required_models"]
        required_loras = workflow_payload["required_loras"]
        required_controlnets = workflow_payload["required_controlnets"]
        default_payload = default_params or workflow_payload["default_params"] or {}
        args = (
            title.strip()[:120],
            _safe_text(description, 1200),
            _normalize_workflow_visibility(visibility),
            1 if is_official else 0,
            json.dumps(workflow_json, ensure_ascii=False, sort_keys=True),
            workflow_hash,
            json.dumps(required_models, ensure_ascii=False, sort_keys=True),
            json.dumps(required_loras, ensure_ascii=False, sort_keys=True),
            json.dumps(required_controlnets, ensure_ascii=False, sort_keys=True),
            json.dumps(default_payload, ensure_ascii=False, sort_keys=True),
            int(published_by_user_id) if published_by_user_id else None,
            now if is_official else None,
            now,
        )
        if preset_id is None:
            cur = conn.execute(
                """
                INSERT INTO comfyui_workflow_presets (
                    owner_user_id, title, description, visibility, is_official,
                    workflow_json, workflow_hash, required_models_json, required_loras_json,
                    required_controlnets_json, default_params_json, published_by_user_id,
                    published_at, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    int(_actor_value(actor, "id")),
                    *args,
                    now,
                ),
            )
            return cur.lastrowid
        conn.execute(
            """
            UPDATE comfyui_workflow_presets
            SET title=?, description=?, visibility=?, is_official=?, workflow_json=?, workflow_hash=?,
                required_models_json=?, required_loras_json=?, required_controlnets_json=?,
                default_params_json=?, published_by_user_id=?, published_at=?, updated_at=?
            WHERE id=? AND owner_user_id=?
            """,
            (
                *args,
                int(preset_id),
                int(_actor_value(actor, "id")),
            ),
        )
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
            return None, None, "Invalid JSON"
        if not isinstance(data, dict):
            return None, None, "Invalid request"
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
            return dict(job)

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
            return dict(job)

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

    def _validate_comfyui_host(value):
        host = str(value or "").strip().strip("[]")
        if not host:
            return None
        if len(host) > 253:
            return None
        forbidden = ("://", "/", "\\", "@", "?", "#", "%", " ")
        if any(part in host for part in forbidden):
            return None
        if not COMFYUI_HOST_RE.match(host):
            return None
        return host

    def _parse_comfyui_endpoint(data):
        mode = str((data or {}).get("mode") or (data or {}).get("comfyui_connection_mode") or _configured_connection_mode()).strip().lower()
        if mode == "remote":
            raw_url = str((data or {}).get("api_url") or (data or {}).get("comfyui_remote_api_url") or "").strip()
            if raw_url:
                url, msg = _validate_comfyui_api_url(raw_url)
                if msg:
                    return None, None, msg
                parsed = urlparse(url)
                return url, {"mode": "remote", "api_url": url, "host": parsed.hostname, "port": parsed.port or (443 if parsed.scheme == "https" else 80)}, None
        default_url = urlparse(DEFAULT_COMFYUI_URL)
        host = _validate_comfyui_host(data.get("host") or data.get("comfyui_api_host") or default_url.hostname or "localhost")
        if host is None:
            return None, None, "ComfyUI Host / IP 必須是主機名稱或 IP，不可包含 http://、路徑、帳密或特殊字元"
        try:
            port = int(data.get("port") or data.get("comfyui_api_port") or default_url.port or DEFAULT_COMFYUI_PORT)
        except Exception:
            return None, None, "ComfyUI Port 必須是 1-65535"
        if port < 1 or port > 65535:
            return None, None, "ComfyUI Port 必須是 1-65535"
        display_host = f"[{host}]" if ":" in host and not host.startswith("[") else host
        return f"http://{display_host}:{port}", {"mode": mode if mode in {"local", "remote"} else "remote", "host": host, "port": port}, None

    def _validate_comfyui_api_url(value):
        raw = str(value or "").strip().rstrip("/")
        if not raw:
            return None, "ComfyUI API 位址不可空白"
        parsed = urlparse(raw)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            return None, "ComfyUI API 位址必須是 http://host:port 或 https://host:port"
        if parsed.username or parsed.password:
            return None, "ComfyUI API 位址不可包含帳密"
        if parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
            return None, "ComfyUI API 位址只需填主機與 port，不要包含路徑或參數"
        return raw, None

    def _normalize_comfyui_backend_url(value):
        raw = str(value or "").strip()
        if not raw:
            return ""
        url, msg = _validate_comfyui_api_url(raw)
        return "" if msg else url

    def _configured_connection_mode():
        settings = get_system_settings() or {}
        mode = str(settings.get("comfyui_connection_mode") or "remote").strip().lower()
        return mode if mode in {"local", "remote"} else "remote"

    def _configured_comfyui_url():
        settings = get_system_settings() or {}
        if _configured_connection_mode() == "remote":
            configured_url = str(settings.get("comfyui_remote_api_url") or "").strip()
            if configured_url:
                url, msg = _validate_comfyui_api_url(configured_url)
                if not msg:
                    return url
        default_url = urlparse(DEFAULT_COMFYUI_URL)
        host = str(settings.get("comfyui_api_host") or default_url.hostname or os.environ.get("COMFYUI_API_HOST") or "localhost").strip()
        host = host.strip("[]")
        if not host:
            host = "localhost"
        try:
            port = int(settings.get("comfyui_api_port") or default_url.port or DEFAULT_COMFYUI_PORT)
        except Exception:
            port = DEFAULT_COMFYUI_PORT
        port = min(65535, max(1, port))
        display_host = f"[{host}]" if ":" in host and not host.startswith("[") else host
        return f"http://{display_host}:{port}"

    def _comfyui_binding(actor=None, *, backend_url=None):
        primary_mode = _configured_connection_mode()
        primary_url = _configured_comfyui_url()
        explicit_url = _normalize_comfyui_backend_url(backend_url)
        if explicit_url:
            if explicit_url == _normalize_comfyui_backend_url(primary_url):
                return {
                    "url": primary_url,
                    "connection_mode": primary_mode,
                    "backend_scope": "primary",
                }
            return {
                "url": explicit_url,
                "connection_mode": "remote",
                "backend_scope": "custom",
            }
        return {
            "url": primary_url,
            "connection_mode": primary_mode,
            "backend_scope": "primary",
        }

    def _configured_local_start_script(value=None, *, base_dir=None):
        raw = str(value or (get_system_settings() or {}).get("comfyui_local_start_script") or "").strip()
        if not raw:
            return None, None
        base = _configured_comfyui_base_dir(base_dir)
        if not base:
            return None, "請先設定 ComfyUI 本地資料夾"
        try:
            if raw.startswith("/") or raw.startswith("\\"):
                script = Path(raw).expanduser().resolve()
            else:
                if ".." in raw.replace("\\", "/").split("/"):
                    return None, "ComfyUI 啟動腳本必須在本地資料夾內"
                script = (base / raw).resolve()
            script.relative_to(base)
        except Exception:
            return None, "ComfyUI 啟動腳本超出允許資料夾"
        if not script.exists() or not script.is_file():
            return None, f"找不到 ComfyUI 啟動腳本：{raw}"
        return script, None

    def _configured_comfyui_port(url=None):
        try:
            parsed = urlparse(url or _configured_comfyui_url())
            port = int(parsed.port or DEFAULT_COMFYUI_PORT)
        except Exception:
            port = DEFAULT_COMFYUI_PORT
        return min(65535, max(1, port))

    def _local_comfyui_state_path(port=None):
        safe_port = _configured_comfyui_port() if port is None else _configured_comfyui_port(f"http://localhost:{port}")
        return Path(tempfile.gettempdir()) / f"hackme_web_comfyui_local_{safe_port}.json"

    def _write_local_comfyui_state(payload):
        try:
            path = _local_comfyui_state_path(payload.get("port"))
            path.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True), encoding="utf-8")
        except Exception:
            return False
        return True

    def _read_local_comfyui_state(port=None):
        path = _local_comfyui_state_path(port)
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None

    def _clear_local_comfyui_state(port=None):
        try:
            _local_comfyui_state_path(port).unlink(missing_ok=True)
        except Exception:
            pass

    def _tail_text_lines(path, limit=8):
        if not path:
            return []
        try:
            text = Path(path).read_text(encoding="utf-8", errors="ignore")
        except Exception:
            return []
        return [line.strip() for line in text.splitlines() if line.strip()][-limit:]

    def _local_comfyui_runtime_status(port=None):
        state = _read_local_comfyui_state(port)
        if not state:
            return None
        pid = int(state.get("pid") or 0)
        if pid <= 0 or not _pid_exists(pid):
            return None
        log_lines = _tail_text_lines(state.get("log_path"))
        joined = "\n".join(log_lines)
        starting_markers = [
            "Starting server",
            "To see the GUI go to:",
            "FETCH ComfyRegistry Data:",
            "Checkpoint files will always be loaded safely.",
            "Using split optimization for attention",
        ]
        waiting_markers = [
            "FETCH ComfyRegistry Data:",
            "Import times for custom nodes:",
        ]
        starting = any(marker in joined for marker in starting_markers)
        waiting_on_registry = any(marker in joined for marker in waiting_markers)
        if waiting_on_registry:
            message = "ComfyUI 主程式已啟動，正在載入自訂節點 / Registry，API 尚未就緒"
        elif starting:
            message = "ComfyUI 主程式已啟動，正在初始化，API 尚未就緒"
        else:
            message = "ComfyUI 進程仍在執行，但 API 尚未回應"
        return {
            "pid": pid,
            "pgid": int(state.get("pgid") or 0),
            "port": int(state.get("port") or 0),
            "base_dir": state.get("base_dir") or "",
            "script": state.get("script") or "",
            "log_path": state.get("log_path") or "",
            "starting": starting,
            "waiting_on_registry": waiting_on_registry,
            "startup_log_tail": log_lines,
            "message": message,
        }

    def _pid_exists(pid):
        try:
            os.kill(int(pid), 0)
            return True
        except Exception:
            return False

    def _pid_cmdline(pid):
        try:
            raw = Path(f"/proc/{int(pid)}/cmdline").read_bytes()
        except Exception:
            return ""
        return raw.replace(b"\x00", b" ").decode("utf-8", errors="ignore").strip()

    def _listener_pids_for_port(port):
        candidates = set()
        commands = [
            ["ss", "-ltnp", f"sport = :{int(port)}"],
            ["lsof", "-tiTCP:%s" % int(port), "-sTCP:LISTEN"],
        ]
        for command in commands:
            try:
                result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=5)
            except Exception:
                continue
            if result.returncode not in (0, 1):
                continue
            output = (result.stdout or "") + "\n" + (result.stderr or "")
            for match in re.findall(r"pid=(\d+)", output):
                candidates.add(int(match))
            if command and command[0] == "lsof":
                for line in (result.stdout or "").splitlines():
                    line = line.strip()
                    if line.isdigit():
                        candidates.add(int(line))
        return sorted(candidates)

    def _proc_scan_comfyui_pids(*, port=None, base_dir=None, script=None):
        candidates = []
        port_token = str(int(port)) if port else ""
        for entry in Path("/proc").iterdir():
            if not entry.name.isdigit():
                continue
            pid = int(entry.name)
            cmdline = _pid_cmdline(pid)
            if not cmdline:
                continue
            lower = cmdline.lower()
            if "comfyui" not in lower and "main.py" not in lower:
                continue
            if port_token:
                if f"--port {port_token}" not in lower and f"--port={port_token}" not in lower and f":{port_token}" not in lower:
                    continue
            if not _looks_like_comfyui_process(pid, base_dir=base_dir, script=script):
                continue
            candidates.append(pid)
        return sorted(set(candidates))

    def _looks_like_comfyui_process(pid, *, base_dir=None, script=None):
        cmdline = _pid_cmdline(pid).lower()
        if not cmdline:
            return False
        if "comfyui" in cmdline:
            return True
        if "main.py" in cmdline and "python" in cmdline:
            return True
        if script and Path(str(script)).name.lower() in cmdline:
            return True
        if base_dir and str(base_dir).lower() in cmdline:
            return True
        return False

    def _terminate_local_comfyui_targets(targets):
        killed = []
        failed = []
        for target in targets:
            pid = int(target.get("pid") or 0)
            if pid <= 0:
                continue
            pgid = int(target.get("pgid") or 0)
            try:
                if pgid > 0:
                    os.killpg(pgid, signal.SIGTERM)
                else:
                    os.kill(pid, signal.SIGTERM)
                killed.append(pid)
            except ProcessLookupError:
                continue
            except Exception as exc:
                failed.append({"pid": pid, "error": str(exc)})
        deadline = time.time() + 8
        while time.time() < deadline:
            remaining = [pid for pid in killed if _pid_exists(pid)]
            if not remaining:
                break
            time.sleep(0.3)
        for pid in list(killed):
            if not _pid_exists(pid):
                continue
            try:
                pgid = os.getpgid(pid)
            except Exception:
                pgid = 0
            try:
                if pgid > 0:
                    os.killpg(pgid, signal.SIGKILL)
                else:
                    os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                continue
            except Exception as exc:
                failed.append({"pid": pid, "error": str(exc)})
        return {"killed_pids": sorted(set(killed)), "errors": failed}

    def _stop_local_comfyui(actor):
        url = _configured_comfyui_url()
        port = _configured_comfyui_port(url)
        active_client = _client_for_url(url)
        mode = _configured_connection_mode()
        if mode != "local":
            return None, "只有本地模式可以從網頁停止 ComfyUI"
        state = _read_local_comfyui_state(port) or {}
        base = _configured_comfyui_base_dir(state.get("base_dir"))
        script, _ = _configured_local_start_script(state.get("script"), base_dir=str(base) if base else None)
        targets = []
        tracked_pid = int(state.get("pid") or 0)
        if tracked_pid > 0 and _pid_exists(tracked_pid):
            targets.append({"pid": tracked_pid, "pgid": int(state.get("pgid") or 0)})
        if not targets:
            for pid in _listener_pids_for_port(port):
                if _looks_like_comfyui_process(pid, base_dir=base, script=script):
                    targets.append({"pid": pid})
        if not targets:
            for pid in _proc_scan_comfyui_pids(port=port, base_dir=base, script=script):
                targets.append({"pid": pid})
        if not targets:
            try:
                active_client.health_check(timeout=2)
            except Exception:
                _clear_local_comfyui_state(port)
                return {
                    "stopped": False,
                    "already_stopped": True,
                    "port": port,
                    "killed_pids": [],
                }, None
            return None, "找不到可停止的本地 ComfyUI 進程"
        result = _terminate_local_comfyui_targets(targets)
        time.sleep(0.5)
        try:
            active_client.health_check(timeout=2)
            audit(
                "COMFYUI_LOCAL_STOP_ERROR",
                get_client_ip(),
                user=_actor_value(actor, "username"),
                success=False,
                ua=get_ua(),
                detail=f"port={port}, pids={result['killed_pids']}, errors={result['errors']}",
            )
            return None, "ComfyUI 停止請求已送出，但服務仍在執行"
        except Exception:
            _clear_local_comfyui_state(port)
            audit(
                "COMFYUI_LOCAL_STOP",
                get_client_ip(),
                user=_actor_value(actor, "username"),
                success=True,
                ua=get_ua(),
                detail=f"port={port}, pids={result['killed_pids']}",
            )
            return {
                "stopped": True,
                "port": port,
                "killed_pids": result["killed_pids"],
                "errors": result["errors"],
            }, None

    def _local_start_script_status(data):
        raw_script = str((data or {}).get("local_start_script") or (data or {}).get("comfyui_local_start_script") or "").strip()
        raw_base = str((data or {}).get("base_dir") or (data or {}).get("comfyui_base_dir") or "").strip()
        if not raw_script:
            raw_script = str((get_system_settings() or {}).get("comfyui_local_start_script") or "").strip()
        script, msg = _configured_local_start_script(raw_script, base_dir=raw_base or None)
        status = {
            "configured": bool(raw_script),
            "exists": bool(script),
            "syntax_ok": None,
            "message": msg or "",
        }
        if script:
            status["filename"] = script.name
            status["relative_path"] = script.relative_to(_configured_comfyui_base_dir(raw_base or None)).as_posix()
            if script.suffix.lower() == ".sh":
                try:
                    check = subprocess.run(["bash", "-n", str(script)], cwd=str(script.parent), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=5)
                    status["syntax_ok"] = check.returncode == 0
                    if check.returncode != 0:
                        status["message"] = (check.stderr or check.stdout or "啟動腳本語法檢查失敗")[:400]
                except Exception as exc:
                    status["syntax_ok"] = False
                    status["message"] = str(exc)[:400]
        return status

    def _start_local_comfyui(actor, *, wait_seconds=2, data=None):
        url, endpoint, endpoint_msg = _parse_comfyui_endpoint(data or {})
        mode = endpoint.get("mode") if isinstance(endpoint, dict) else _configured_connection_mode()
        if mode != "local":
            return None, "只有本地模式可以從網頁啟動 ComfyUI"
        if injected_client is not None:
            return {"started": False, "already_running": True, "testing": True}, None
        if endpoint_msg:
            return None, endpoint_msg
        active_client = _client_for_url(url or _configured_comfyui_url())
        try:
            active_client.health_check(timeout=2)
            return {"started": False, "already_running": True, "comfyui_url": getattr(active_client, "base_url", url or _configured_comfyui_url())}, None
        except Exception:
            pass
        raw_base = (data or {}).get("base_dir") or (data or {}).get("comfyui_base_dir")
        raw_script = (data or {}).get("local_start_script") or (data or {}).get("comfyui_local_start_script")
        script, msg = _configured_local_start_script(raw_script, base_dir=raw_base or None)
        if msg or not script:
            audit("COMFYUI_LOCAL_AUTOSTART_SKIPPED", get_client_ip(), user=_actor_value(actor, "username"), success=False, ua=get_ua(), detail=msg or "no script configured")
            return None, msg or "尚未設定 ComfyUI 本地啟動腳本"
        base = _configured_comfyui_base_dir(raw_base or None)
        project_dir = _configured_comfyui_project_dir(raw_base or None)
        command = [str(script)]
        if script.suffix.lower() == ".sh":
            command = ["bash", str(script)]
        env = os.environ.copy()
        try:
            configured_port = urlparse(url or _configured_comfyui_url()).port or DEFAULT_COMFYUI_PORT
        except Exception:
            configured_port = DEFAULT_COMFYUI_PORT
        env.update({
            "PORT": str(configured_port),
            "AUTO_PORT_SCAN": "0",
            "COMFYUI_DIR": str(project_dir or base),
        })
        start_log = None
        try:
            log_fd, log_path = tempfile.mkstemp(prefix="comfyui_local_start_", suffix=".log")
            os.close(log_fd)
            start_log = Path(log_path)
            with open(start_log, "ab") as log_handle:
                proc = subprocess.Popen(
                    command,
                    cwd=str(base),
                    env=env,
                    stdout=log_handle,
                    stderr=subprocess.STDOUT,
                    start_new_session=True,
                )
            try:
                proc_pgid = int(os.getpgid(proc.pid))
            except Exception:
                proc_pgid = 0
            _write_local_comfyui_state({
                "pid": int(proc.pid),
                "pgid": proc_pgid,
                "port": int(configured_port),
                "base_dir": str(base),
                "script": str(script),
                "log_path": str(start_log) if start_log else "",
                "started_at": datetime.now().isoformat(),
            })
            time.sleep(1)
            return_code = proc.poll()
            if return_code not in (None, 0):
                _clear_local_comfyui_state(configured_port)
                detail = ""
                try:
                    lines = start_log.read_text(encoding="utf-8", errors="ignore").splitlines()
                    if lines:
                        detail = "；" + " / ".join(line.strip() for line in lines[-6:] if line.strip())[:500]
                except Exception:
                    pass
                msg = f"本地 ComfyUI 啟動腳本已結束（exit {return_code}）{detail}"
                audit("COMFYUI_LOCAL_AUTOSTART_ERROR", get_client_ip(), user=_actor_value(actor, "username"), success=False, ua=get_ua(), detail=msg[:180])
                return None, msg
            audit("COMFYUI_LOCAL_AUTOSTART", get_client_ip(), user=_actor_value(actor, "username"), success=True, ua=get_ua(), detail=f"script={script.name}")
            deadline = time.time() + max(0, int(wait_seconds or 0))
            while time.time() < deadline:
                try:
                    active_client.health_check(timeout=2)
                    return {"started": True, "available": True, "comfyui_url": getattr(active_client, "base_url", url or _configured_comfyui_url())}, None
                except Exception:
                    time.sleep(1)
            return {
                "started": True,
                "available": False,
                "comfyui_url": getattr(active_client, "base_url", url or _configured_comfyui_url()),
                "message": "已啟動背景流程；若是第一次安裝依賴，可能需要數分鐘，稍後請按重新整理模型。",
                "startup_log_tail": (
                    start_log.read_text(encoding="utf-8", errors="ignore").splitlines()[-8:]
                    if start_log and start_log.exists()
                    else []
                ),
            }, None
        except Exception as exc:
            audit("COMFYUI_LOCAL_AUTOSTART_ERROR", get_client_ip(), user=_actor_value(actor, "username"), success=False, ua=get_ua(), detail=str(exc)[:180])
            return None, str(exc)

    def _configured_max_batch_size():
        settings = get_system_settings() or {}
        return _int_range(settings.get("comfyui_max_batch_size"), 1, 1, 8)

    def _configured_default_dimensions():
        settings = get_system_settings() or {}
        return {
            "width": _int_range(settings.get("comfyui_default_width"), 1024, 64, 2048, multiple_of=8),
            "height": _int_range(settings.get("comfyui_default_height"), 1024, 64, 2048, multiple_of=8),
        }

    def _configured_comfyui_base_dir(value=None):
        raw = str(value or (get_system_settings() or {}).get("comfyui_base_dir") or os.environ.get("COMFYUI_BASE_DIR") or "").strip()
        if not raw:
            return None
        path = Path(raw).expanduser()
        try:
            return path.resolve()
        except Exception:
            return None

    def _configured_comfyui_project_dir(value=None):
        base = _configured_comfyui_base_dir(value)
        if not base:
            return None
        direct = (base / "main.py").resolve()
        nested = (base / "ComfyUI" / "main.py").resolve()
        if direct.exists():
            return base
        if nested.exists():
            return nested.parent
        return base

    def _configured_civitai_api_key():
        return str((get_system_settings() or {}).get("comfyui_civitai_api_key") or os.environ.get("CIVITAI_API_KEY") or "").strip()

    def _public_download_host(url):
        parsed = urlparse(str(url or "").strip())
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            return None, "下載網址只支援 http/https"
        if parsed.username or parsed.password:
            return None, "下載網址不可包含帳密"
        try:
            resolved = socket.getaddrinfo(parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80), type=socket.SOCK_STREAM)
        except socket.gaierror:
            return None, "下載網址無法解析主機"
        for item in resolved:
            ip_text = item[4][0]
            try:
                ip = ipaddress.ip_address(ip_text)
            except ValueError:
                return None, "下載網址解析到不合法 IP"
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved or ip.is_unspecified:
                return None, "下載網址不可指向 localhost、內網或保留位址"
        return parsed, None

    def _safe_model_filename(url, fallback):
        parsed = urlparse(str(url or ""))
        name = Path(parsed.path or "").name or fallback
        name = re.sub(r"[^A-Za-z0-9_.-]+", "_", name).strip("._")
        if not name:
            name = fallback
        suffix = Path(name).suffix.lower()
        if suffix not in COMFYUI_MODEL_DOWNLOAD_EXTENSIONS:
            raise ValueError(f"模型副檔名必須是 {', '.join(sorted(COMFYUI_MODEL_DOWNLOAD_EXTENSIONS))}")
        return name[:180]

    def _normalize_download_model_type(value):
        key = re.sub(r"[^a-z0-9]+", "", str(value or "").strip().lower())
        return CIVITAI_MODEL_TYPE_TO_DOWNLOAD_TYPE.get(key, key)

    def _filename_from_content_disposition(header_value):
        header = str(header_value or "").strip()
        if not header:
            return ""
        match = re.search(r'filename\*=UTF-8\'\'([^;]+)', header, re.IGNORECASE)
        if match:
            return unquote(match.group(1)).strip().strip('"')
        match = re.search(r'filename="?([^";]+)"?', header, re.IGNORECASE)
        return (match.group(1).strip() if match else "")

    def _append_civitai_token(url, auth_value):
        if not auth_value:
            return str(url or "")
        parsed = urlparse(str(url or "").strip())
        if not parsed.scheme or not parsed.netloc:
            return str(url or "")
        query = parse_qs(parsed.query, keep_blank_values=True)
        query["token"] = [auth_value]
        return urlunparse(parsed._replace(query=urlencode(query, doseq=True)))

    def _civitai_headers(auth_value):
        headers = {
            "User-Agent": "hackme_web-comfyui-model-downloader/1.0",
            "Accept": "application/json",
        }
        if auth_value:
            headers["Authorization"] = f"Bearer {auth_value}"
        return headers

    def _comfyui_model_sidecar_path(*, model_type, filename, base_dir=None):
        safe_name = str(filename or "").strip()
        if not safe_name or "/" in safe_name or "\\" in safe_name or ".." in safe_name:
            return None
        project_dir = _configured_comfyui_project_dir(base_dir)
        if not project_dir:
            return None
        mapping = COMFYUI_MODEL_DOWNLOAD_TYPES.get(_normalize_download_model_type(model_type))
        if not mapping:
            return None
        folder_name, _label = mapping
        model_dir = (project_dir / "models" / folder_name).resolve()
        sidecar = (model_dir / f"{safe_name}.civitai.json").resolve()
        try:
            sidecar.relative_to(model_dir)
        except ValueError:
            return None
        return sidecar

    def _write_comfyui_model_sidecar(*, model_type, filename, base_dir=None, payload=None):
        sidecar = _comfyui_model_sidecar_path(model_type=model_type, filename=filename, base_dir=base_dir)
        if not sidecar:
            return False
        data = payload if isinstance(payload, dict) else {}
        try:
            sidecar.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
        except Exception:
            return False
        return True

    def _read_comfyui_model_sidecar(*, model_type, filename, base_dir=None):
        sidecar = _comfyui_model_sidecar_path(model_type=model_type, filename=filename, base_dir=base_dir)
        if not sidecar or not sidecar.exists():
            return {}
        try:
            data = json.loads(sidecar.read_text(encoding="utf-8"))
        except Exception:
            return {}
        return data if isinstance(data, dict) else {}

    def _normalize_lora_base_model_family(value):
        raw = str(value or "").strip()
        normalized = re.sub(r"\s+", " ", raw).lower()
        if not normalized:
            return raw, "unknown"
        if "pony" in normalized:
            return raw, "pony"
        if "illustrious" in normalized:
            return raw, "illustrious"
        if "noob" in normalized:
            return raw, "noob"
        if "sdxl" in normalized or "sd xl" in normalized:
            return raw, "sdxl"
        if "flux" in normalized:
            return raw, "flux"
        if (
            "sd1.5" in normalized
            or "sd 1.5" in normalized
            or "sd15" in normalized
            or "stable diffusion 1.5" in normalized
            or "v1-5" in normalized
        ):
            return raw, "sd15"
        return raw, "other"

    def _lora_support_payload(base_model):
        raw_base_model, family = _normalize_lora_base_model_family(base_model)
        supported = family in COMFYUI_SUPPORTED_LORA_BASE_MODEL_FAMILIES
        if supported:
            support_message = "目前生圖介面支援這個 LoRA base model。"
        elif raw_base_model:
            support_message = (
                f"{raw_base_model} LoRA 目前不支援；"
                "目前只允許 SDXL、Pony、Illustrious、Noob 系列 LoRA。"
            )
        else:
            support_message = (
                "這個 LoRA 沒有可辨識的 base model metadata；"
                "目前只允許 SDXL、Pony、Illustrious、Noob 系列 LoRA。"
            )
        return {
            "base_model": raw_base_model,
            "base_model_family": family,
            "supported": supported,
            "support_message": support_message,
        }

    def _build_lora_details(lora_names, *, base_dir=None):
        details = {}
        for name in list(lora_names or []):
            clean_name = str(name or "").strip()
            if not clean_name:
                continue
            meta = _read_comfyui_model_sidecar(model_type="lora", filename=clean_name, base_dir=base_dir)
            support = _lora_support_payload(meta.get("base_model"))
            details[clean_name] = {
                "name": clean_name,
                "trained_words": [
                    str(item).strip()
                    for item in list(meta.get("trained_words") or [])
                    if str(item).strip()
                ],
                "source": str(meta.get("source") or "").strip(),
                "version_name": str(meta.get("version_name") or "").strip(),
                **support,
            }
        return details

    def _public_or_civitai_host(url, *, allow_civitai_only=False):
        parsed = urlparse(str(url or "").strip())
        host = (parsed.hostname or "").lower()
        if allow_civitai_only:
            if parsed.scheme != "https" or host not in CIVITAI_ALLOWED_HOSTS:
                return None, "只接受 Civitai 模型頁網址"
            return parsed, None
        return _public_download_host(url)

    def _parse_civitai_reference(page_url):
        parsed, msg = _public_or_civitai_host(page_url, allow_civitai_only=True)
        if msg:
            return None, msg
        path_match = re.search(r"/models/(\d+)", parsed.path or "", re.IGNORECASE)
        if not path_match:
            return None, "無法從網址解析 Civitai modelId"
        query = parse_qs(parsed.query or "")
        version_id = None
        if query.get("modelVersionId"):
            raw = str(query.get("modelVersionId")[0] or "").strip()
            if raw.isdigit():
                version_id = int(raw)
        return {
            "page_url": urlunparse(parsed._replace(fragment="")),
            "model_id": int(path_match.group(1)),
            "version_id": version_id,
        }, None

    def _fetch_json(url, *, headers=None, timeout=20):
        request_obj = urllib.request.Request(str(url), headers=headers or {"User-Agent": "hackme_web/1.0"})
        with urllib.request.urlopen(request_obj, timeout=timeout) as resp:
            charset = resp.headers.get_content_charset() or "utf-8"
            return json.loads(resp.read().decode(charset, errors="replace"))

    def _civitai_api_get(path, *, auth_value):
        if not auth_value:
            return None, "請先在 root 設定填入 Civitai API Key"
        url = f"{CIVITAI_API_BASE}/{path.lstrip('/')}"
        try:
            return _fetch_json(url, headers=_civitai_headers(auth_value), timeout=20), None
        except urllib.error.HTTPError as exc:
            detail = ""
            try:
                detail = exc.read().decode("utf-8", errors="replace")[:200]
            except Exception:
                detail = ""
            return None, f"Civitai API 失敗：HTTP {exc.code}{f' {detail}' if detail else ''}"
        except urllib.error.URLError as exc:
            return None, f"Civitai API 連線失敗：{getattr(exc, 'reason', exc)}"
        except Exception as exc:
            return None, str(exc)

    def _normalize_civitai_search_type(value):
        key = _normalize_download_model_type(value)
        return key if key in CIVITAI_SEARCH_TYPE_TO_API else ""

    def _normalize_civitai_nsfw_mode(value):
        raw = str(value or "safe").strip().lower()
        if raw in {"safe", "all", "nsfw"}:
            return raw
        return "safe"

    def _serialize_civitai_file(file_entry, fallback_download_url):
        if not isinstance(file_entry, dict):
            return None
        filename = str(file_entry.get("name") or "").strip()
        if not filename:
            return None
        suffix = Path(filename).suffix.lower()
        if suffix not in COMFYUI_MODEL_DOWNLOAD_EXTENSIONS:
            return None
        try:
            size_kb = float(file_entry.get("sizeKB")) if file_entry.get("sizeKB") is not None else None
        except Exception:
            size_kb = None
        return {
            "id": int(file_entry.get("id") or 0) or None,
            "name": filename,
            "size_kb": size_kb,
            "size_bytes": int(round(size_kb * 1024)) if size_kb is not None else None,
            "download_url": str(file_entry.get("downloadUrl") or fallback_download_url or "").strip(),
            "metadata": dict(file_entry.get("metadata") or {}),
            "hashes": {
                str(key).strip().lower(): str(value).strip()
                for key, value in dict(file_entry.get("hashes") or {}).items()
                if str(key).strip() and str(value).strip()
            },
            "pickle_scan_result": file_entry.get("pickleScanResult"),
            "virus_scan_result": file_entry.get("virusScanResult"),
            "type": str(file_entry.get("type") or "").strip(),
        }

    def _serialize_civitai_versions(model_data, preferred_version_id=None):
        versions = []
        for version in list((model_data or {}).get("modelVersions") or []):
            version_id = int(version.get("id") or 0) or None
            files = []
            for file_entry in list(version.get("files") or []):
                payload = _serialize_civitai_file(file_entry, version.get("downloadUrl"))
                if payload:
                    files.append(payload)
            if not files:
                continue
            versions.append({
                "id": version_id,
                "name": str(version.get("name") or f"Version {version_id or '?'}").strip(),
                "created_at": version.get("createdAt"),
                "base_model": version.get("baseModel"),
                "trained_words": list(version.get("trainedWords") or []),
                "download_url": str(version.get("downloadUrl") or "").strip(),
                "files": files,
            })
        selected_version_id = None
        if preferred_version_id:
            for item in versions:
                if item["id"] == int(preferred_version_id):
                    selected_version_id = item["id"]
                    break
        if selected_version_id is None and versions:
            selected_version_id = versions[0]["id"]
        return versions, selected_version_id

    def _build_civitai_page_url(model_id, version_id=None):
        base_url = f"https://civitai.com/models/{int(model_id)}"
        if version_id:
            return f"{base_url}?modelVersionId={int(version_id)}"
        return base_url

    def _serialize_civitai_search_results(search_data):
        results = []
        items = list((search_data or {}).get("items") or [])
        for item in items:
            if not isinstance(item, dict):
                continue
            model_id = int(item.get("id") or 0) or None
            if not model_id:
                continue
            versions, selected_version_id = _serialize_civitai_versions(item)
            if not versions:
                continue
            compatible_models = []
            for version in versions:
                base_model = str(version.get("base_model") or "").strip()
                if base_model and base_model not in compatible_models:
                    compatible_models.append(base_model)
            latest_version = versions[0]
            primary_file = dict((latest_version.get("files") or [None])[0] or {})
            suggested_model_type = _normalize_download_model_type(item.get("type"))
            if suggested_model_type not in COMFYUI_MODEL_DOWNLOAD_TYPES:
                suggested_model_type = "checkpoint"
            results.append({
                "model_id": model_id,
                "page_url": _build_civitai_page_url(model_id),
                "selected_page_url": _build_civitai_page_url(model_id, selected_version_id),
                "name": str(item.get("name") or f"Model {model_id}").strip(),
                "type": str(item.get("type") or "").strip(),
                "suggested_model_type": suggested_model_type,
                "creator": str(((item.get("creator") or {}).get("username") or "")).strip(),
                "nsfw": bool(item.get("nsfw")),
                "version_count": len(versions),
                "compatible_models": compatible_models,
                "selected_version_id": selected_version_id,
                "latest_version": {
                    "id": latest_version.get("id"),
                    "name": latest_version.get("name"),
                    "created_at": latest_version.get("created_at"),
                    "base_model": latest_version.get("base_model"),
                    "trained_words": list(latest_version.get("trained_words") or []),
                    "file_count": len(latest_version.get("files") or []),
                    "primary_file": primary_file or None,
                },
            })
        metadata = dict((search_data or {}).get("metadata") or {})
        return {
            "results": results,
            "total_items": int(metadata.get("totalItems") or 0) if str(metadata.get("totalItems") or "").isdigit() else len(results),
            "current_page": int(metadata.get("currentPage") or 1) if str(metadata.get("currentPage") or "").isdigit() else 1,
            "page_size": int(metadata.get("pageSize") or len(results) or 0) if str(metadata.get("pageSize") or "").isdigit() else len(results),
        }

    def _search_civitai_models(query="", *, base_model="", model_type="", nsfw_mode="safe", limit=12):
        safe_query = str(query or "").strip()[:120]
        safe_base_model = str(base_model or "").strip()[:80]
        safe_model_type = _normalize_civitai_search_type(model_type)
        safe_nsfw_mode = _normalize_civitai_nsfw_mode(nsfw_mode)
        try:
            safe_limit = max(1, min(24, int(limit or 12)))
        except Exception:
            safe_limit = 12
        params = [("limit", safe_limit)]
        if safe_query:
            params.append(("query", safe_query))
        if safe_model_type:
            params.append(("types", CIVITAI_SEARCH_TYPE_TO_API[safe_model_type]))
        if safe_base_model:
            params.append(("baseModels", safe_base_model))
        if safe_nsfw_mode == "safe":
            params.append(("nsfw", "false"))
        elif safe_nsfw_mode == "nsfw":
            params.append(("nsfw", "true"))
        search_data, err = _civitai_api_get(f"models?{urlencode(params, doseq=True)}", auth_value=_configured_civitai_api_key())
        if err:
            return None, err
        payload = _serialize_civitai_search_results(search_data)
        payload["filters"] = {
            "query": safe_query,
            "base_model": safe_base_model,
            "model_type": safe_model_type,
            "nsfw_mode": safe_nsfw_mode,
            "limit": safe_limit,
        }
        return payload, None

    def _inspect_civitai_model(page_url):
        ref, msg = _parse_civitai_reference(page_url)
        if msg:
            return None, msg
        model_data, err = _civitai_api_get(f"models/{ref['model_id']}", auth_value=_configured_civitai_api_key())
        if err:
            return None, err
        versions, selected_version_id = _serialize_civitai_versions(model_data, preferred_version_id=ref.get("version_id"))
        if not versions:
            return None, "這個模型目前沒有可下載的版本或檔案"
        model_type = _normalize_download_model_type((model_data or {}).get("type"))
        if model_type not in COMFYUI_MODEL_DOWNLOAD_TYPES:
            model_type = "checkpoint"
        return {
            "page_url": ref["page_url"],
            "model_id": ref["model_id"],
            "name": str((model_data or {}).get("name") or f"Model {ref['model_id']}").strip(),
            "type": str((model_data or {}).get("type") or "").strip(),
            "suggested_model_type": model_type,
            "creator": ((model_data or {}).get("creator") or {}).get("username") or "",
            "nsfw": bool((model_data or {}).get("nsfw")),
            "selected_version_id": selected_version_id,
            "versions": versions,
        }, None

    def _create_model_download_job(actor):
        job_id = secrets.token_hex(12)
        job = {
            "job_id": job_id,
            "owner_user_id": _generation_owner_id(actor),
            "owner_username": _actor_value(actor, "username", ""),
            "status": "queued",
            "error": "",
            "result": None,
            "progress": {
                "phase": "queued",
                "percent": 0,
                "bytes_written": 0,
                "total_bytes": 0,
                "detail": "已建立模型下載工作",
                "completed": False,
                "updated_at": time.time(),
            },
            "created_at": time.time(),
            "updated_at": time.time(),
        }
        with model_download_jobs_lock:
            model_download_jobs[job_id] = job
        return job_id

    def _update_model_download_job(job_id, **changes):
        with model_download_jobs_lock:
            job = model_download_jobs.get(job_id)
            if not job:
                return None
            for key, value in changes.items():
                job[key] = value
            job["updated_at"] = time.time()
            return dict(job)

    def _update_model_download_progress(job_id, progress):
        with model_download_jobs_lock:
            job = model_download_jobs.get(job_id)
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
            return dict(job["progress"])

    def _get_model_download_job(job_id):
        with model_download_jobs_lock:
            job = model_download_jobs.get(str(job_id))
            return dict(job) if job else None

    def _assert_model_download_job_owner(job_id, actor):
        job = _get_model_download_job(job_id)
        if not job:
            return None, json_resp({"ok": False, "msg": "找不到 ComfyUI 模型下載工作"}, 404)
        if int(job.get("owner_user_id") or 0) != int(_generation_owner_id(actor) or 0):
            return None, json_resp({"ok": False, "msg": "無權查看此 ComfyUI 模型下載工作"}, 403)
        return job, None

    def _parse_civitai_download_request(data):
        page_url = str(data.get("page_url") or data.get("url") or "").strip()
        try:
            version_id = int(data.get("version_id") or data.get("model_version_id") or 0)
        except Exception:
            version_id = 0
        try:
            file_id = int(data.get("file_id") or 0) or None
        except Exception:
            file_id = None
        model_type = str(data.get("type") or data.get("model_type") or "").strip().lower()
        if not page_url or version_id <= 0:
            return None, "請先輸入 Civitai 模型頁網址並選擇版本"
        return {
            "page_url": page_url,
            "version_id": version_id,
            "file_id": file_id,
            "model_type": model_type,
            "base_dir": data.get("base_dir"),
        }, None

    def _download_comfyui_model_file(*, url, model_type, base_dir, filename_hint=None, auth_value=None, progress_callback=None):
        parsed, msg = _public_or_civitai_host(url)
        if msg:
            return None, msg
        model_type = _normalize_download_model_type(model_type)
        if model_type not in COMFYUI_MODEL_DOWNLOAD_TYPES:
            return None, "模型類型不支援"
        base = _configured_comfyui_base_dir(base_dir)
        if not base:
            return None, "請先設定 COMFYUI_BASE_DIR 或在本面板輸入 ComfyUI 專案資料夾"
        project_dir = _configured_comfyui_project_dir(base_dir) or base
        folder_name, label = COMFYUI_MODEL_DOWNLOAD_TYPES[model_type]
        try:
            filename = _safe_model_filename(filename_hint or url, f"downloaded_{model_type}.safetensors")
        except ValueError as exc:
            return None, str(exc)
        destination_dir = (project_dir / "models" / folder_name).resolve()
        try:
            destination_dir.relative_to(base.resolve())
        except ValueError:
            return None, "模型儲存路徑不合法"
        destination_dir.mkdir(parents=True, exist_ok=True)
        destination = (destination_dir / filename).resolve()
        try:
            destination.relative_to(destination_dir)
        except ValueError:
            return None, "模型檔名不合法"
        if destination.exists():
            return None, f"{label} 檔案已存在：{filename}"
        request_obj = urllib.request.Request(
            _append_civitai_token(str(url), auth_value),
            headers=_civitai_headers(auth_value),
        )
        written = 0
        temp_path = None
        try:
            with urllib.request.urlopen(request_obj, timeout=30) as resp:
                try:
                    total_bytes = int(resp.headers.get("Content-Length") or 0)
                except Exception:
                    total_bytes = 0
                final_url = resp.geturl()
                _final_parsed, final_msg = _public_or_civitai_host(final_url)
                if final_msg:
                    return None, final_msg
                content_name = _filename_from_content_disposition(resp.headers.get("Content-Disposition"))
                if content_name:
                    filename = _safe_model_filename(content_name, filename)
                    destination = (destination_dir / filename).resolve()
                    if destination.exists():
                        return None, f"{label} 檔案已存在：{filename}"
                if progress_callback:
                    progress_callback({
                        "phase": "downloading",
                        "percent": 0,
                        "bytes_written": 0,
                        "total_bytes": total_bytes,
                        "detail": f"開始下載 {label}：{filename}",
                        "completed": False,
                    })
                with tempfile.NamedTemporaryFile(prefix=f".{filename}.", suffix=".part", dir=str(destination_dir), delete=False) as tmp:
                    temp_path = Path(tmp.name)
                    while True:
                        chunk = resp.read(1024 * 1024)
                        if not chunk:
                            break
                        written += len(chunk)
                        if written > MAX_COMFYUI_MODEL_DOWNLOAD_BYTES:
                            raise ValueError("模型檔案超過下載大小上限")
                        tmp.write(chunk)
                        if progress_callback:
                            percent = 0
                            if total_bytes > 0:
                                percent = max(0, min(99, round((written / total_bytes) * 100)))
                            progress_callback({
                                "phase": "downloading",
                                "percent": percent,
                                "bytes_written": written,
                                "total_bytes": total_bytes,
                                "detail": f"正在下載 {label}：{filename}",
                                "completed": False,
                            })
            if written <= 0:
                raise ValueError("下載內容為空")
            temp_path.replace(destination)
        except urllib.error.URLError as exc:
            if temp_path and temp_path.exists():
                temp_path.unlink(missing_ok=True)
            return None, f"模型下載中斷或連線失敗：{getattr(exc, 'reason', exc)}"
        except Exception as exc:
            if temp_path and temp_path.exists():
                temp_path.unlink(missing_ok=True)
            if isinstance(exc, TimeoutError):
                return None, "模型下載逾時，請稍後再試"
            if exc.__class__.__name__ == "IncompleteRead":
                return None, "模型下載中斷，請稍後再試"
            return None, str(exc)
        return {
            "type": model_type,
            "label": label,
            "filename": filename,
            "size_bytes": written,
            "saved_path": str(destination),
        }, None

    def _download_civitai_model_selection(*, page_url, version_id, file_id, model_type, base_dir, progress_callback=None):
        inspection, msg = _inspect_civitai_model(page_url)
        if msg:
            return None, msg
        chosen_version = None
        for version in inspection["versions"]:
            if version["id"] == int(version_id or 0):
                chosen_version = version
                break
        if not chosen_version:
            return None, "找不到指定版本"
        chosen_file = None
        if file_id:
            for file_payload in chosen_version["files"]:
                if file_payload.get("id") == int(file_id):
                    chosen_file = file_payload
                    break
            if not chosen_file:
                return None, "找不到指定檔案"
        else:
            chosen_file = chosen_version["files"][0]
        download_url = str(chosen_file.get("download_url") or chosen_version.get("download_url") or "").strip()
        if not download_url:
            download_url = f"https://civitai.com/api/download/models/{chosen_version['id']}"
        result, err = _download_comfyui_model_file(
            url=download_url,
            model_type=model_type or inspection.get("suggested_model_type"),
            base_dir=base_dir,
            filename_hint=chosen_file.get("name"),
            auth_value=_configured_civitai_api_key(),
            progress_callback=progress_callback,
        )
        if err:
            return None, err
        result["civitai"] = {
            "model_id": inspection["model_id"],
            "model_name": inspection["name"],
            "version_id": chosen_version["id"],
            "version_name": chosen_version["name"],
            "base_model": str(chosen_version.get("base_model") or "").strip(),
            "trained_words": list(chosen_version.get("trained_words") or []),
            "file_id": chosen_file.get("id"),
            "file_name": chosen_file.get("name"),
            "source_url": inspection["page_url"],
        }
        _write_comfyui_model_sidecar(
            model_type=result.get("type") or model_type or inspection.get("suggested_model_type"),
            filename=result.get("filename"),
            base_dir=base_dir,
            payload={
                "source": "civitai",
                "model_id": inspection["model_id"],
                "model_name": inspection["name"],
                "version_id": chosen_version["id"],
                "version_name": chosen_version["name"],
                "base_model": str(chosen_version.get("base_model") or "").strip(),
                "file_id": chosen_file.get("id"),
                "file_name": chosen_file.get("name"),
                "trained_words": list(chosen_version.get("trained_words") or []),
                "source_url": inspection["page_url"],
                "saved_filename": result.get("filename"),
            },
        )
        return result, None

    def _upload_comfyui_model_file(*, uploaded_file, model_type, base_dir, actor=None):
        model_type = _normalize_download_model_type(model_type)
        if model_type not in COMFYUI_MODEL_DOWNLOAD_TYPES:
            return None, "模型類型不支援"
        if _configured_connection_mode() != "local":
            return None, "目前是遠端模式，不提供本地 ComfyUI 模型匯入"
        if uploaded_file is None:
            return None, "請先選擇要上傳的模型檔案"
        original_name = str(getattr(uploaded_file, "filename", "") or "").strip()
        if not original_name:
            return None, "請先選擇要上傳的模型檔案"
        base = _configured_comfyui_base_dir(base_dir)
        if not base:
            return None, "請先設定 COMFYUI_BASE_DIR 或在本面板輸入 ComfyUI 專案資料夾"
        project_dir = _configured_comfyui_project_dir(base_dir) or base
        folder_name, label = COMFYUI_MODEL_DOWNLOAD_TYPES[model_type]
        try:
            filename = _safe_model_filename(original_name, f"uploaded_{model_type}.safetensors")
        except ValueError as exc:
            return None, str(exc)
        destination_dir = (project_dir / "models" / folder_name).resolve()
        try:
            destination_dir.relative_to(base.resolve())
        except ValueError:
            return None, "模型儲存路徑不合法"
        destination_dir.mkdir(parents=True, exist_ok=True)
        destination = (destination_dir / filename).resolve()
        try:
            destination.relative_to(destination_dir)
        except ValueError:
            return None, "模型檔名不合法"
        if destination.exists():
            return None, f"{label} 檔案已存在：{filename}"
        temp_path = None
        written = 0
        try:
            with tempfile.NamedTemporaryFile(prefix=f".{filename}.", suffix=".part", dir=str(destination_dir), delete=False) as tmp:
                temp_path = Path(tmp.name)
                stream = getattr(uploaded_file, "stream", uploaded_file)
                while True:
                    chunk = stream.read(1024 * 1024)
                    if not chunk:
                        break
                    written += len(chunk)
                    if written > MAX_COMFYUI_MODEL_DOWNLOAD_BYTES:
                        raise ValueError("模型檔案超過上傳大小上限")
                    tmp.write(chunk)
            if written <= 0:
                raise ValueError("上傳內容為空")
            temp_path.replace(destination)
        except Exception as exc:
            if temp_path and temp_path.exists():
                temp_path.unlink(missing_ok=True)
            return None, str(exc)
        _write_comfyui_model_sidecar(
            model_type=model_type,
            filename=filename,
            base_dir=base_dir,
            payload={
                "source": "manual_upload",
                "original_filename": original_name,
                "saved_filename": filename,
                "uploaded_at": datetime.now().isoformat(),
                "uploaded_by": _actor_value(actor, "username", "") if actor else "",
                "size_bytes": written,
            },
        )
        return {
            "type": model_type,
            "label": label,
            "filename": filename,
            "size_bytes": written,
            "saved_path": str(destination),
            "source": "manual_upload",
        }, None

    def _client(actor=None, *, backend_url=None):
        binding = _comfyui_binding(actor, backend_url=backend_url)
        return _client_for_url(binding["url"])

    def _client_for_url(url):
        if injected_client is not None:
            return injected_client
        factory = deps.get("comfyui_client_factory")
        if factory:
            return factory(url)
        return ComfyUIClient(url)

    def _is_root(actor):
        return _actor_value(actor, "username") == "root"

    def _comfyui_charge_required(actor):
        return not _is_root(actor)

    def _comfyui_wallet_payload(actor):
        if not points_service:
            return None
        try:
            wallet = points_service.get_wallet(_actor_value(actor, "id"))
        except Exception:
            return None
        if not isinstance(wallet, dict):
            return None
        return {
            "points_balance": int(wallet.get("points_balance") or 0),
            "charged": _comfyui_charge_required(actor),
        }

    def _comfyui_lora_count(params):
        loras = (params or {}).get("loras") or []
        return len(loras) if isinstance(loras, list) else 0

    def _comfyui_price_quote(quantity, *, lora_count=0):
        if not points_service:
            return None, "積分服務未啟用，無法使用 ComfyUI 產圖"
        catalog = points_service.list_catalog()
        item = next((row for row in catalog if row.get("item_key") == COMFYUI_BASIC_PRICE_ITEM_KEY), None)
        if not item:
            return None, "ComfyUI 產圖收費項目未啟用"
        quantity = max(1, int(quantity or 1))
        lora_count = max(0, int(lora_count or 0))
        unit_price = int(item.get("base_price") or 0)
        lora_extra_price = COMFYUI_LORA_EXTRA_PRICE_POINTS * lora_count * quantity
        return {
            "item_key": COMFYUI_BASIC_PRICE_ITEM_KEY,
            "item_name": item.get("item_name") or "ComfyUI 基礎生圖一次",
            "unit_price": unit_price,
            "lora_extra_unit_price": COMFYUI_LORA_EXTRA_PRICE_POINTS,
            "lora_count": lora_count,
            "lora_extra_price": lora_extra_price,
            "quantity": quantity,
            "base_price_total": unit_price * quantity,
            "total_price": unit_price * quantity + lora_extra_price,
            "currency_type": "points",
        }, None

    def _comfyui_total_quantity(data, params):
        batch_size = max(1, int((params or {}).get("batch_size") or 1))
        run_count = _int_range((data or {}).get("run_count"), 1, 1, 10)
        return batch_size * run_count, run_count

    def _ensure_comfyui_balance(actor, quote):
        if not quote or not points_service:
            return None
        wallet = points_service.get_wallet(_actor_value(actor, "id"))
        balance = int((wallet or {}).get("points_balance") or 0)
        if balance < int(quote.get("total_price") or 0):
            return f"積分不足：本次產圖需要 {quote['total_price']} 點，目前餘額 {balance} 點"
        return None

    def _charge_comfyui_generation(actor, quote, *, prompt_id):
        if not quote or not points_service:
            return None
        result = points_service.spend_points(
            user_id=_actor_value(actor, "id"),
            item_key=quote["item_key"],
            quantity=quote["quantity"],
            override_amount=quote["total_price"],
            reference_type="comfyui_generation",
            reference_id=str(prompt_id or ""),
            idempotency_key=f"comfyui_generation:{_actor_value(actor, 'id')}:{prompt_id or secrets.token_hex(8)}",
            metadata={
                "charged_after_success": True,
                "unit_price": quote["unit_price"],
                "quantity": quote["quantity"],
                "lora_count": quote.get("lora_count", 0),
                "lora_extra_unit_price": quote.get("lora_extra_unit_price", 0),
                "lora_extra_price": quote.get("lora_extra_price", 0),
                "total_price": quote["total_price"],
            },
            actor=actor,
        )
        return {
            "charged": True,
            "item_key": quote["item_key"],
            "unit_price": quote["unit_price"],
            "quantity": quote["quantity"],
            "lora_count": quote.get("lora_count", 0),
            "lora_extra_unit_price": quote.get("lora_extra_unit_price", 0),
            "lora_extra_price": quote.get("lora_extra_price", 0),
            "total_price": quote["total_price"],
            "ledger_uuid": (result.get("ledger") or {}).get("ledger_uuid"),
            "wallet": result.get("wallet"),
        }

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
            _update_generation_job(
                job_id,
                status="completed",
                result=payload,
                error="",
            )
            _update_generation_job_progress(job_id, {
                "phase": "completed",
                "percent": 100,
                "completed": True,
                "detail": f"已完成，共 {len(images)} 張",
            })
            audit(
                "COMFYUI_GENERATE",
                audit_ip,
                user=_actor_value(actor, "username"),
                success=True,
                ua=audit_ua,
                detail=f"job_id={job_id}, prompt_id={result['prompt_id']}, file={result['image_ref'].get('filename')}, batch={len(images)}",
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

    def _run_comfyui_workflow_preset_job(job_id, actor, row, run_id, timeout_seconds, request_meta=None):
        backend_binding = _comfyui_binding(actor)
        active_client = _client_for_url(backend_binding["url"])
        request_meta = request_meta if isinstance(request_meta, dict) else {}
        audit_ip = request_meta.get("client_ip") or "-"
        audit_ua = request_meta.get("user_agent") or "-"
        _update_generation_job(job_id, status="running")
        workflow_json = _parse_json_field(row["workflow_json"], {}) or {}
        default_params = _parse_json_field(row["default_params_json"], {}) or {}
        prompt = str(default_params.get("prompt") or "")
        negative_prompt = str(default_params.get("negative_prompt") or "")
        expected_count = max(1, int(default_params.get("batch_size") or 1))
        try:
            result = active_client.generate_from_workflow(
                workflow_json,
                timeout_seconds=timeout_seconds,
                expected_count=expected_count,
                progress_callback=lambda progress: _update_generation_job_progress(job_id, progress),
            )
            images = _finalize_generation_records(actor, default_params, result, backend_url=backend_binding.get("url"))
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
            }
            conn = get_db()
            try:
                _update_workflow_run(conn, run_id=run_id, status="completed", output_refs=output_refs, error="")
                conn.commit()
            finally:
                conn.close()
            payload = {
                "image": images[0],
                "images": images,
                "workflow_run_id": run_id,
                "preset_id": int(row["id"]),
            }
            _update_generation_job(job_id, status="completed", result=payload, error="")
            _update_generation_job_progress(job_id, {
                "phase": "completed",
                "percent": 100,
                "completed": True,
                "detail": f"已完成，共 {len(images)} 張",
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
        prompt = _normalize_comfyui_prompt_text(data.get("prompt"))
        if mode != "upscale" and not prompt:
            return None, "請輸入提示詞"
        if len(prompt) > 3000:
            return None, "提示詞最多 3000 字"
        negative = _normalize_comfyui_prompt_text(data.get("negative_prompt"))
        if len(negative) > 3000:
            return None, "負面提示詞最多 3000 字"
        model = str(data.get("model") or "").strip()
        if mode != "upscale" and not model:
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

    @app.route("/api/root/comfyui/test-connection", methods=["POST"])
    @require_csrf
    def root_comfyui_test_connection():
        actor, err = _root_or_403()
        if err:
            return err
        try:
            data = request.get_json(force=True)
        except Exception:
            return json_resp({"ok": False, "msg": "Invalid JSON"}), 400
        if not isinstance(data, dict):
            return json_resp({"ok": False, "msg": "Invalid request"}), 400
        url, endpoint, msg = _parse_comfyui_endpoint(data)
        if msg:
            return json_resp({"ok": False, "msg": msg}), 400
        local_script_status = _local_start_script_status(data) if isinstance(endpoint, dict) and endpoint.get("mode") == "local" else None
        active_client = _client_for_url(url)
        try:
            status = active_client.health_check(timeout=3) if hasattr(active_client, "health_check") else {"ok": True}
            audit(
                "COMFYUI_CONNECTION_TEST",
                get_client_ip(),
                user=_actor_value(actor, "username"),
                success=True,
                ua=get_ua(),
                detail=f"url={url}",
            )
            return json_resp({
                "ok": True,
                "available": True,
                "comfyui_url": getattr(active_client, "base_url", url),
                "endpoint": endpoint,
                "connection_mode": endpoint.get("mode") if isinstance(endpoint, dict) else _configured_connection_mode(),
                "local_script": local_script_status,
                "system": status.get("system") if isinstance(status, dict) else {},
            })
        except ComfyUIError as exc:
            autostart = {"attempted": False}
            if isinstance(endpoint, dict) and endpoint.get("mode") == "local":
                start_result, start_msg = _start_local_comfyui(actor, wait_seconds=6, data=data)
                autostart = {
                    "attempted": True,
                    "ok": bool(start_result and not start_msg),
                    "message": start_msg or (start_result or {}).get("message") or "",
                    "available": bool((start_result or {}).get("available")),
                    "start": start_result,
                }
                if start_result and (start_result.get("available") or start_result.get("already_running")):
                    try:
                        status = active_client.health_check(timeout=3) if hasattr(active_client, "health_check") else {"ok": True}
                        return json_resp({
                            "ok": True,
                            "available": True,
                            "comfyui_url": getattr(active_client, "base_url", url),
                            "endpoint": endpoint,
                            "connection_mode": endpoint.get("mode") if isinstance(endpoint, dict) else _configured_connection_mode(),
                            "local_script": local_script_status,
                            "autostart": autostart,
                            "system": status.get("system") if isinstance(status, dict) else {},
                        })
                    except ComfyUIError as exc2:
                        exc = exc2
            runtime = _local_comfyui_runtime_status((endpoint or {}).get("port") if isinstance(endpoint, dict) else None)
            audit(
                "COMFYUI_CONNECTION_TEST",
                get_client_ip(),
                user=_actor_value(actor, "username"),
                success=False,
                ua=get_ua(),
                detail=f"url={url}, error={exc}",
            )
            return json_resp({
                "ok": True,
                "available": False,
                "starting": bool(runtime),
                "msg": runtime["message"] if runtime else str(exc),
                "comfyui_url": getattr(active_client, "base_url", url),
                "endpoint": endpoint,
                "connection_mode": endpoint.get("mode") if isinstance(endpoint, dict) else _configured_connection_mode(),
                "local_script": local_script_status,
                "autostart": autostart,
                "local_runtime": runtime,
            })

    @app.route("/api/root/comfyui/civitai/inspect", methods=["POST"])
    @require_csrf
    def root_comfyui_civitai_inspect():
        actor, err = _root_or_403()
        if err:
            return err
        try:
            data = request.get_json(force=True)
        except Exception:
            return json_resp({"ok": False, "msg": "Invalid JSON"}), 400
        if not isinstance(data, dict):
            return json_resp({"ok": False, "msg": "Invalid request"}), 400
        page_url = str(data.get("page_url") or data.get("url") or "").strip()
        result, msg = _inspect_civitai_model(page_url)
        audit(
            "COMFYUI_CIVITAI_INSPECT",
            get_client_ip(),
            user=_actor_value(actor, "username"),
            success=not bool(msg),
            ua=get_ua(),
            detail=f"model_id={(result or {}).get('model_id') or ''}, url_host={urlparse(page_url).hostname if page_url else ''}, error={msg or ''}"[:300],
        )
        if msg:
            return json_resp({"ok": False, "msg": msg}), 400
        return json_resp({"ok": True, "model": result, "msg": f"已讀取 {result['name']}，請選擇版本與檔案"})

    @app.route("/api/root/comfyui/civitai/search", methods=["POST"])
    @require_csrf
    def root_comfyui_civitai_search():
        actor, err = _root_or_403()
        if err:
            return err
        try:
            data = request.get_json(force=True)
        except Exception:
            return json_resp({"ok": False, "msg": "Invalid JSON"}), 400
        if not isinstance(data, dict):
            return json_resp({"ok": False, "msg": "Invalid request"}), 400
        query = str(data.get("query") or "").strip()
        base_model = str(data.get("base_model") or "").strip()
        model_type = str(data.get("model_type") or data.get("type") or "").strip()
        nsfw_mode = _normalize_civitai_nsfw_mode(data.get("nsfw_mode") or data.get("safety") or "safe")
        try:
            limit = max(1, min(24, int(data.get("limit") or 12)))
        except Exception:
            limit = 12
        result, msg = _search_civitai_models(
            query,
            base_model=base_model,
            model_type=model_type,
            nsfw_mode=nsfw_mode,
            limit=limit,
        )
        audit(
            "COMFYUI_CIVITAI_SEARCH",
            get_client_ip(),
            user=_actor_value(actor, "username"),
            success=not bool(msg),
            ua=get_ua(),
            detail=(
                f"query={query[:80]}, type={_normalize_civitai_search_type(model_type) or '-'}, "
                f"base_model={base_model[:40] or '-'}, nsfw={nsfw_mode}, "
                f"count={len((result or {}).get('results') or [])}, error={msg or ''}"
            )[:300],
        )
        if msg:
            return json_resp({"ok": False, "msg": msg}), 400
        total = int(result.get("total_items") or 0)
        count = len(result.get("results") or [])
        message = "沒有符合條件的 Civitai 模型，請調整關鍵字或篩選器。" if count == 0 else f"已找到 {count} 個 Civitai 模型（總數約 {total}）。"
        return json_resp({
            "ok": True,
            "results": result.get("results") or [],
            "filters": result.get("filters") or {},
            "total_items": total,
            "current_page": result.get("current_page") or 1,
            "page_size": result.get("page_size") or count,
            "msg": message,
        })

    @app.route("/api/root/comfyui/civitai/download", methods=["POST"])
    @require_csrf
    def root_comfyui_download_civitai_model():
        actor, err = _root_or_403()
        if err:
            return err
        try:
            data = request.get_json(force=True)
        except Exception:
            return json_resp({"ok": False, "msg": "Invalid JSON"}), 400
        if not isinstance(data, dict):
            return json_resp({"ok": False, "msg": "Invalid request"}), 400
        request_data, msg = _parse_civitai_download_request(data)
        if msg:
            return json_resp({"ok": False, "msg": msg}), 400
        if _coerce_bool(data.get("async_progress")):
            job_id = _create_model_download_job(actor)
            request_meta = _capture_request_audit_meta()
            worker = threading.Thread(
                target=_run_comfyui_model_download_job,
                args=(job_id, dict(actor), request_data, request_meta),
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
                        "detail": "已建立模型下載工作",
                    },
                },
            })
        result, msg = _download_civitai_model_selection(
            page_url=request_data["page_url"],
            version_id=request_data["version_id"],
            file_id=request_data["file_id"],
            model_type=request_data["model_type"],
            base_dir=request_data["base_dir"],
        )
        audit(
            "COMFYUI_CIVITAI_DOWNLOAD",
            get_client_ip(),
            user=_actor_value(actor, "username"),
            success=not bool(msg),
            ua=get_ua(),
            detail=f"type={request_data['model_type']}, version_id={request_data['version_id']}, file_id={request_data['file_id'] or ''}, url_host={urlparse(request_data['page_url']).hostname if request_data['page_url'] else ''}, filename={(result or {}).get('filename') or ''}, error={msg or ''}"[:300],
        )
        if msg:
            return json_resp({"ok": False, "msg": msg}), 400
        return json_resp({"ok": True, "download": result, "msg": f"已下載 {result['label']}：{result['filename']}"})

    @app.route("/api/root/comfyui/model-upload", methods=["POST"])
    @require_csrf
    def root_comfyui_upload_model_file():
        actor, err = _root_or_403()
        if err:
            return err
        model_file = request.files.get("model_file")
        model_type = str(request.form.get("type") or request.form.get("model_type") or "").strip().lower()
        base_dir = request.form.get("base_dir")
        result, msg = _upload_comfyui_model_file(
            uploaded_file=model_file,
            model_type=model_type,
            base_dir=base_dir,
            actor=actor,
        )
        audit(
            "COMFYUI_MODEL_UPLOAD",
            get_client_ip(),
            user=_actor_value(actor, "username"),
            success=not bool(msg),
            ua=get_ua(),
            detail=f"type={model_type}, filename={getattr(model_file, 'filename', '') if model_file else ''}, saved={(result or {}).get('filename') or ''}, error={msg or ''}"[:300],
        )
        if msg:
            return json_resp({"ok": False, "msg": msg}), 400
        return json_resp({"ok": True, "upload": result, "msg": f"已匯入 {result['label']}：{result['filename']}"})

    @app.route("/api/root/comfyui/download-jobs/<job_id>", methods=["GET"])
    @require_csrf_safe
    def root_comfyui_download_job_status(job_id):
        actor, err = _root_or_403()
        if err:
            return err
        job, err = _assert_model_download_job_owner(job_id, actor)
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
            return json_resp({"ok": False, "msg": "Invalid JSON"}), 400
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

    @app.route("/api/comfyui/workflows", methods=["GET"])
    @require_csrf_safe
    def comfyui_workflow_presets():
        actor, err = _actor_or_401()
        if err:
            return err
        binding = _comfyui_binding(actor)
        active_client = None
        dependency_warning = ""
        try:
            active_client = _client_for_url(binding["url"])
            if hasattr(active_client, "health_check"):
                active_client.health_check(timeout=3)
        except Exception as exc:
            dependency_warning = str(exc)
            active_client = None
        conn = get_db()
        try:
            presets = _list_workflow_presets(conn, actor=actor, active_client=active_client)
        finally:
            conn.close()
        return json_resp({
            "ok": True,
            "presets": presets,
            "official_presets": [item for item in presets if item.get("is_official")],
            "my_presets": [item for item in presets if int(item.get("owner_user_id") or 0) == int(_actor_value(actor, "id")) and not item.get("is_official")],
            "shared_presets": [item for item in presets if int(item.get("owner_user_id") or 0) != int(_actor_value(actor, "id")) and not item.get("is_official")],
            "can_publish_official": _actor_value(actor, "username") == "root",
            "dependency_warning": dependency_warning,
        })

    @app.route("/api/comfyui/workflows/import", methods=["POST"])
    @require_csrf
    def comfyui_workflow_import():
        actor, err = _actor_or_401()
        if err:
            return err
        try:
            data = request.get_json(force=True)
        except Exception:
            return json_resp({"ok": False, "msg": "Invalid JSON"}), 400
        data = data if isinstance(data, dict) else {}
        workflow_candidate = data.get("workflow_json") if "workflow_json" in data else data.get("workflow")
        if workflow_candidate in (None, ""):
            return json_resp({"ok": False, "msg": "請提供 workflow JSON"}), 400
        try:
            workflow_payload, extracted_defaults = _extract_workflow_payload(workflow_candidate)
            default_params = (
                _normalize_workflow_default_params(data.get("default_params_json") if "default_params_json" in data else data.get("default_params"))
                if ("default_params_json" in data or "default_params" in data)
                else extracted_defaults
            )
        except WorkflowValidationError as exc:
            return json_resp({"ok": False, "msg": str(exc)}), 400
        title = _safe_text(data.get("title") or data.get("name") or f"Workflow {datetime.now().strftime('%Y-%m-%d %H:%M')}", 120)
        conn = get_db()
        try:
            preset_id = _upsert_workflow_preset(
                conn,
                actor=actor,
                title=title,
                description=data.get("description") or "",
                visibility=data.get("visibility") or "private",
                workflow_payload=workflow_payload,
                default_params=default_params,
            )
            row = _load_workflow_preset_row(conn, preset_id=preset_id)
            conn.commit()
        finally:
            conn.close()
        audit("COMFYUI_WORKFLOW_IMPORT", get_client_ip(), user=_actor_value(actor, "username"), success=True, ua=get_ua(), detail=f"preset_id={preset_id}, title={title}")
        return json_resp({"ok": True, "preset": _workflow_preset_summary(row, actor=actor), "msg": "已匯入 workflow preset"})

    @app.route("/api/comfyui/workflows/export-current", methods=["POST"])
    @require_csrf
    def comfyui_workflow_export_current():
        actor, err = _actor_or_401()
        if err:
            return err
        try:
            data = request.get_json(force=True)
        except Exception:
            return json_resp({"ok": False, "msg": "Invalid JSON"}), 400
        data = data if isinstance(data, dict) else {}
        params, msg = _normalize_generation_payload(data)
        if msg:
            return json_resp({"ok": False, "msg": msg}), 400
        active_client = _client_for_url(_comfyui_binding(actor)["url"])
        try:
            capabilities, capability_msg = _validate_generation_capabilities(active_client, params)
            if capability_msg:
                return json_resp({"ok": False, "msg": capability_msg, "capabilities": capabilities or {}}), 409
            workflow = active_client.build_generation_workflow(params)
            workflow_payload = sanitize_workflow_json(workflow)
        except (ComfyUIError, WorkflowValidationError) as exc:
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
        actor, err = _actor_or_401()
        if err:
            return err
        conn = get_db()
        try:
            row, err_resp = _load_workflow_preset(conn, preset_id=preset_id, actor=actor)
            if err_resp:
                return err_resp
            active_client = None
            try:
                active_client = _client_for_url(_comfyui_binding(actor)["url"])
                if hasattr(active_client, "health_check"):
                    active_client.health_check(timeout=3)
            except Exception:
                active_client = None
            dependency_status = _workflow_dependency_status(active_client, row) if active_client is not None else None
            recent_runs = _list_workflow_runs(conn, preset_id=preset_id, limit=COMFYUI_WORKFLOW_RUN_LIMIT)
            payload = _workflow_preset_summary(row, dependency_status=dependency_status, recent_runs=recent_runs, actor=actor)
            payload["workflow_json"] = _parse_json_field(row["workflow_json"], {}) or {}
        finally:
            conn.close()
        return json_resp({"ok": True, "preset": payload})

    @app.route("/api/comfyui/workflows/<int:preset_id>", methods=["PUT"])
    @require_csrf
    def comfyui_workflow_update(preset_id):
        actor, err = _actor_or_401()
        if err:
            return err
        try:
            data = request.get_json(force=True)
        except Exception:
            return json_resp({"ok": False, "msg": "Invalid JSON"}), 400
        data = data if isinstance(data, dict) else {}
        conn = get_db()
        try:
            row, err_resp = _load_workflow_preset(conn, preset_id=preset_id, actor=actor, require_write=True)
            if err_resp:
                return err_resp
            before = _workflow_preset_summary(row, actor=actor)
            workflow_candidate = data.get("workflow_json") if "workflow_json" in data else _parse_json_field(row["workflow_json"], {})
            workflow_payload, extracted_defaults = _extract_workflow_payload(workflow_candidate)
            if "default_params_json" in data or "default_params" in data:
                default_params = _normalize_workflow_default_params(data.get("default_params_json") if "default_params_json" in data else data.get("default_params"))
            elif "workflow_json" in data:
                default_params = extracted_defaults
            else:
                default_params = _parse_json_field(row["default_params_json"], {}) or {}
            updated_id = _upsert_workflow_preset(
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
            row = _load_workflow_preset_row(conn, preset_id=updated_id)
            conn.commit()
        except WorkflowValidationError as exc:
            conn.rollback()
            return json_resp({"ok": False, "msg": str(exc)}), 400
        finally:
            conn.close()
        after = _workflow_preset_summary(row, actor=actor)
        audit(
            "COMFYUI_WORKFLOW_UPDATE",
            get_client_ip(),
            user=_actor_value(actor, "username"),
            success=True,
            ua=get_ua(),
            detail=f"preset_id={preset_id}, before={json.dumps(before, ensure_ascii=False)[:180]}, after={json.dumps(after, ensure_ascii=False)[:180]}",
        )
        return json_resp({"ok": True, "preset": after, "msg": "已更新 workflow preset"})

    @app.route("/api/comfyui/workflows/<int:preset_id>", methods=["DELETE"])
    @require_csrf
    def comfyui_workflow_delete(preset_id):
        actor, err = _actor_or_401()
        if err:
            return err
        conn = get_db()
        try:
            row, err_resp = _load_workflow_preset(conn, preset_id=preset_id, actor=actor, require_write=True)
            if err_resp:
                return err_resp
            conn.execute("DELETE FROM comfyui_workflow_runs WHERE preset_id=?", (int(preset_id),))
            conn.execute("DELETE FROM comfyui_workflow_presets WHERE id=? AND owner_user_id=?", (int(preset_id), int(_actor_value(actor, "id"))))
            conn.commit()
        finally:
            conn.close()
        audit("COMFYUI_WORKFLOW_DELETE", get_client_ip(), user=_actor_value(actor, "username"), success=True, ua=get_ua(), detail=f"preset_id={preset_id}")
        return json_resp({"ok": True, "msg": "已刪除 workflow preset"})

    @app.route("/api/comfyui/workflows/<int:preset_id>/run", methods=["POST"])
    @require_csrf
    def comfyui_workflow_run(preset_id):
        actor, err = _actor_or_401()
        if err:
            return err
        conn = get_db()
        try:
            row, err_resp = _load_workflow_preset(conn, preset_id=preset_id, actor=actor)
            if err_resp:
                return err_resp
            active_client = _client_for_url(_comfyui_binding(actor)["url"])
            dependency_status, dependency_msg = _assert_workflow_dependencies_or_error(active_client, row)
            if dependency_msg:
                return json_resp({"ok": False, "msg": dependency_msg, "dependency_status": dependency_status}), 409
            default_params = _parse_json_field(row["default_params_json"], {}) or {}
            workflow_json = _parse_json_field(row["workflow_json"], {}) or {}
            run_id = _create_workflow_run(
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
        job_id = _create_generation_job(actor)
        request_meta = _capture_request_audit_meta()
        worker = threading.Thread(
            target=_run_comfyui_workflow_preset_job,
            args=(job_id, dict(actor), dict(row), run_id, DEFAULT_GENERATION_TIMEOUT_SECONDS, request_meta),
            daemon=True,
        )
        worker.start()
        return json_resp({
            "ok": True,
            "async": True,
            "workflow_run_id": run_id,
            "dependency_status": dependency_status,
            "job": {
                "job_id": job_id,
                "status": "queued",
                "progress": {"phase": "queued", "percent": 0, "detail": "已建立 workflow 執行工作"},
            },
        })

    @app.route("/api/comfyui/workflows/<int:preset_id>/export", methods=["POST"])
    @require_csrf
    def comfyui_workflow_export(preset_id):
        actor, err = _actor_or_401()
        if err:
            return err
        conn = get_db()
        try:
            row, err_resp = _load_workflow_preset(conn, preset_id=preset_id, actor=actor)
            if err_resp:
                return err_resp
            workflow_json = _parse_json_field(row["workflow_json"], {}) or {}
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
        actor, err = _root_or_403()
        if err:
            return err
        conn = get_db()
        try:
            row, err_resp = _load_workflow_preset(conn, preset_id=preset_id, actor=actor, require_write=True)
            if err_resp:
                return err_resp
            updated_id = _upsert_workflow_preset(
                conn,
                preset_id=preset_id,
                actor=actor,
                title=row["title"],
                description=row["description"],
                visibility="public",
                workflow_payload={
                    "workflow_json": _parse_json_field(row["workflow_json"], {}) or {},
                    "workflow_hash": row["workflow_hash"] or "",
                    "required_models": _parse_json_field(row["required_models_json"], []) or [],
                    "required_loras": _parse_json_field(row["required_loras_json"], []) or [],
                    "required_controlnets": _parse_json_field(row["required_controlnets_json"], []) or [],
                    "default_params": _parse_json_field(row["default_params_json"], {}) or {},
                },
                default_params=_parse_json_field(row["default_params_json"], {}) or {},
                is_official=True,
                published_by_user_id=_actor_value(actor, "id"),
            )
            row = _load_workflow_preset_row(conn, preset_id=updated_id)
            conn.commit()
        finally:
            conn.close()
        audit("COMFYUI_WORKFLOW_PUBLISH_OFFICIAL", get_client_ip(), user=_actor_value(actor, "username"), success=True, ua=get_ua(), detail=f"preset_id={preset_id}")
        return json_resp({"ok": True, "preset": _workflow_preset_summary(row, actor=actor), "msg": "已發布為官方 preset"})

    @app.route("/api/comfyui/image-preview", methods=["POST"])
    @require_csrf
    def comfyui_image_preview():
        actor, err = _actor_or_401()
        if err:
            return err
        try:
            data = request.get_json(force=True)
        except Exception:
            return json_resp({"ok": False, "msg": "Invalid JSON"}), 400
        if not isinstance(data, dict):
            return json_resp({"ok": False, "msg": "Invalid request"}), 400
        image_ref = _image_ref_payload(data.get("image_ref"))
        if not image_ref:
            return json_resp({"ok": False, "msg": "圖片引用不合法"}), 400
        conn = get_db()
        try:
            ref_row = _load_comfyui_image_ref_record(conn, actor=actor, image_ref=image_ref)
        finally:
            conn.close()
        if not ref_row:
            return json_resp({"ok": False, "msg": "無權讀取這張 ComfyUI 圖片"}), 403
        active_client = _client_for_url(_comfyui_binding(actor, backend_url=(ref_row or {}).get("backend_url")).get("url"))
        try:
            image = active_client.fetch_image(image_ref)
            _assert_reasonable_image_size(image)
        except ComfyUIError as exc:
            return _json_error_from_comfy(exc, active_client)
        return json_resp({
            "ok": True,
            "image": {
                "image_ref": image_ref,
                "mime_type": image.mime_type,
                "size_bytes": len(image.data),
                "data_url": f"data:{image.mime_type};base64,{base64.b64encode(image.data).decode('ascii')}",
            },
        })

    @app.route("/api/comfyui/interrupt", methods=["POST"])
    @require_csrf
    def comfyui_interrupt():
        actor, err = _actor_or_401()
        if err:
            return err
        try:
            data = request.get_json(force=True, silent=True)
        except TypeError:
            data = None
        data = data if isinstance(data, dict) else {}
        allowed, reason, summary = _interrupt_policy(actor)
        if not allowed:
            audit(
                "COMFYUI_INTERRUPT_SKIPPED",
                get_client_ip(),
                user=actor["username"],
                success=True,
                ua=get_ua(),
                detail=f"reason={reason}, summary={summary}",
            )
            msg = "已中斷本頁等待；未送出 ComfyUI 全域中斷，避免影響其他使用者的產圖。"
            if reason == "no_owned_generation":
                msg = "目前沒有偵測到你的後端產圖任務；已中斷本頁等待。"
            return json_resp({
                "ok": True,
                "msg": msg,
                "interrupt": {
                    "interrupted": False,
                    "backend_interrupted": False,
                    "reason": reason,
                    **summary,
                },
            })
        active_client = _client(actor)
        if _is_root(actor):
            own_active = [
                item for item in _active_generation_snapshot()
                if int(item.get("user_id") or 0) == int(_generation_owner_id(actor) or 0)
            ]
            own_backends = {
                _normalize_comfyui_backend_url(item.get("backend_url"))
                for item in own_active
                if _normalize_comfyui_backend_url(item.get("backend_url"))
            }
            if len(own_backends) == 1:
                active_client = _client_for_url(next(iter(own_backends)))
        try:
            if not hasattr(active_client, "interrupt"):
                return json_resp({"ok": False, "msg": "ComfyUI 中斷產圖不支援"}), 501
            result = active_client.interrupt()
        except ComfyUIError as exc:
            audit("COMFYUI_INTERRUPT_ERROR", get_client_ip(), user=actor["username"], success=False, ua=get_ua(), detail=str(exc)[:180])
            return _json_error_from_comfy(exc, active_client)
        payload = result if isinstance(result, dict) else {}
        payload.setdefault("interrupted", True)
        payload["backend_interrupted"] = True
        payload["reason"] = reason
        payload.update(summary)
        audit("COMFYUI_INTERRUPT", get_client_ip(), user=actor["username"], success=True, ua=get_ua(), detail=f"interrupt requested, reason={reason}, summary={summary}")
        return json_resp({"ok": True, "msg": "已送出中斷產圖請求", "interrupt": payload})

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
        conn = get_db()
        try:
            ref_row = _load_comfyui_image_ref_record(conn, actor=actor, image_ref=image_ref)
            if not ref_row:
                audit("COMFYUI_IMAGE_REF_DENIED", get_client_ip(), user=actor["username"], success=False, ua=get_ua(), detail=f"action=save,file={image_ref.get('filename', '-')}")
                return json_resp({"ok": False, "msg": "找不到可存取的產圖預覽"}), 404
            active_client = _client_for_url(_comfyui_binding(actor, backend_url=ref_row.get("backend_url")).get("url"))
            try:
                image = active_client.fetch_image(image_ref)
                _assert_reasonable_image_size(image)
            except ComfyUIError as exc:
                return _json_error_from_comfy(exc, active_client)
            upload_result, storage_file, album, msg = _save_fetched_image(conn, actor=actor, data=data, image=image)
            if msg:
                conn.rollback()
                return json_resp({"ok": False, "msg": msg}), 400
            conn.commit()
            audit("COMFYUI_SAVE_TO_DRIVE", get_client_ip(), user=actor["username"], success=True, ua=get_ua(), detail=f"file_id={upload_result['file_id']}, storage_file_id={storage_file['id']}")
            return json_resp({"ok": True, "file": upload_result, "storage_file": storage_file, "album": album})
        finally:
            conn.close()

    @app.route("/api/comfyui/discard", methods=["POST"])
    @require_csrf
    def comfyui_discard():
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
        conn = get_db()
        try:
            ref_row = _load_comfyui_image_ref_record(conn, actor=actor, image_ref=image_ref, prompt_id=data.get("prompt_id"))
            if not ref_row:
                audit("COMFYUI_IMAGE_REF_DENIED", get_client_ip(), user=actor["username"], success=False, ua=get_ua(), detail=f"action=discard,file={image_ref.get('filename', '-')}")
                return json_resp({"ok": False, "msg": "找不到可丟棄的產圖預覽"}), 404
            conn.commit()
        finally:
            conn.close()
        image_binding = _comfyui_binding(actor, backend_url=(ref_row or {}).get("backend_url"))
        if image_binding["connection_mode"] != "local":
            result = {
                "file_deleted": False,
                "file_missing": False,
                "file_delete_supported": False,
                "history_deleted": False,
                "remote_preview_only": True,
            }
            audit("COMFYUI_DISCARD_REMOTE_PREVIEW_ONLY", get_client_ip(), user=actor["username"], success=True, ua=get_ua(), detail=f"file={image_ref.get('filename')}")
            return json_resp({
                "ok": True,
                "msg": "已移除網頁上的預覽；遠端 ComfyUI API 不支援刪除 output 原始檔。",
                "discard": result,
                "warning": "source_file_not_deleted",
            })
        active_client = _client_for_url(image_binding["url"])
        try:
            if not hasattr(active_client, "discard_image"):
                return json_resp({"ok": False, "msg": "ComfyUI 原始檔刪除不支援"}), 501
            result = active_client.discard_image(
                image_ref,
                prompt_id=data.get("prompt_id"),
                local_base_dir=str(_configured_comfyui_project_dir() or _configured_comfyui_base_dir() or ""),
                allow_api_delete=False,
            )
        except ComfyUIError as exc:
            audit("COMFYUI_DISCARD_ERROR", get_client_ip(), user=actor["username"], success=False, ua=get_ua(), detail=str(exc)[:180])
            return _json_error_from_comfy(exc, active_client)
        if not (result.get("file_deleted") or result.get("file_missing")):
            msg = "已丟棄前端預覽；ComfyUI 未提供刪除 output 檔案端點，原始檔可能仍留在 ComfyUI output。若要同步刪原檔，請設定 COMFYUI_OUTPUT_DIR 或 COMFYUI_BASE_DIR。"
            audit("COMFYUI_DISCARD_UNSUPPORTED", get_client_ip(), user=actor["username"], success=True, ua=get_ua(), detail=str(result)[:180])
            return json_resp({"ok": True, "msg": msg, "discard": result, "warning": "source_file_not_deleted"})
        audit("COMFYUI_DISCARD", get_client_ip(), user=actor["username"], success=True, ua=get_ua(), detail=f"file={image_ref.get('filename')}, result={result}")
        return json_resp({"ok": True, "msg": "已丟棄預覽並刪除 ComfyUI 原始檔", "discard": result})

    @app.route("/api/comfyui/share", methods=["POST"])
    @require_csrf
    def comfyui_share():
        actor, err = _actor_or_401()
        if err:
            return err
        try:
            data = request.get_json(force=True)
        except Exception:
            return json_resp({"ok": False, "msg": "Invalid JSON"}), 400
        data = data if isinstance(data, dict) else {}
        image_ref = data.get("image_ref")
        conn = get_db()
        try:
            existing = _existing_saved_image(conn, actor=actor, data=data)
            if existing:
                upload_result, storage_file, album, msg = existing
                if msg:
                    conn.rollback()
                    return json_resp({"ok": False, "msg": msg}), 400
            else:
                if not isinstance(image_ref, dict):
                    return json_resp({"ok": False, "msg": "缺少 image_ref"}), 400
                ref_row = _load_comfyui_image_ref_record(conn, actor=actor, image_ref=image_ref)
                if not ref_row:
                    audit("COMFYUI_IMAGE_REF_DENIED", get_client_ip(), user=actor["username"], success=False, ua=get_ua(), detail=f"action=share,file={image_ref.get('filename', '-')}")
                    conn.rollback()
                    return json_resp({"ok": False, "msg": "找不到可分享的產圖預覽"}), 404
                active_client = _client_for_url(_comfyui_binding(actor, backend_url=ref_row.get("backend_url")).get("url"))
                try:
                    image = active_client.fetch_image(image_ref)
                    _assert_reasonable_image_size(image)
                except ComfyUIError as exc:
                    return _json_error_from_comfy(exc, active_client)
                upload_result, storage_file, album, msg = _save_fetched_image(conn, actor=actor, data=data, image=image)
                if msg:
                    conn.rollback()
                    return json_resp({"ok": False, "msg": msg}), 400
            board = _find_or_create_comfyui_board(conn, actor)
            title = _safe_text(data.get("title"), 120) or "ComfyUI 產圖分享"
            content = _compose_comfyui_share_content(
                data,
                file_id=upload_result["file_id"],
                storage_file=storage_file or {},
            )
            if not content.strip():
                conn.rollback()
                return json_resp({"ok": False, "msg": "分享內容不可為空"}), 400
            level = _actor_value(actor, "effective_level") or _actor_value(actor, "base_level") or _actor_value(actor, "member_level") or "normal"
            role = _actor_value(actor, "role", "user")
            status = "pending" if role == "user" and level == "newbie" else "approved"
            now = datetime.now().isoformat()
            cur = conn.execute(
                """
                INSERT INTO forum_threads (
                    board_id, title, content, status, post_type, author_user_id,
                    author_username, created_at, updated_at
                ) VALUES (?, ?, ?, ?, 'normal', ?, ?, ?, ?)
                """,
                (board["id"], title, content, status, int(_actor_value(actor, "id")), _actor_value(actor, "username"), now, now),
            )
            thread_id = cur.lastrowid
            conn.execute("UPDATE forum_boards SET last_activity_at=?, updated_at=? WHERE id=?", (now, now, board["id"]))
            attached, msg = attach_existing_file(
                conn,
                actor=actor,
                file_id=upload_result["file_id"],
                context_type="forum_thread",
                context_id=thread_id,
                grant_role="user",
                can_preview=True,
            )
            if msg:
                conn.rollback()
                return json_resp({"ok": False, "msg": msg}), 400
            conn.commit()
            audit(
                "COMFYUI_SHARE_TO_COMMUNITY",
                get_client_ip(),
                user=actor["username"],
                success=True,
                ua=get_ua(),
                detail=f"thread_id={thread_id}, file_id={upload_result['file_id']}, board_id={board['id']}",
            )
            return json_resp({
                "ok": True,
                "msg": "已分享到 ComfyUI 專區" if status == "approved" else "已送出分享，待審核後公開",
                "thread": {"id": thread_id, "board_id": board["id"], "title": title, "status": status},
                "file": upload_result,
                "storage_file": storage_file,
                "album": album,
                "attachment": attached,
            })
        finally:
            conn.close()
