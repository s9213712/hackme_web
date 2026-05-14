"""Hugging Face Diffusers backend for the ComfyUI module.

The public routes still speak the existing ComfyUI-shaped contract. This
client only replaces the execution backend when root selects diffusers mode.
"""

from __future__ import annotations

import hashlib
import importlib.util
import io
import mimetypes
import os
import re
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote, unquote, urlparse

from services.comfyui.client import ComfyUIError, ComfyUIImage
from services.comfyui.constants import GENERATION_MODE_DEFINITIONS, detect_model_families
from services.comfyui.huggingface import (
    infer_gguf_base_repo,
    inspect_huggingface_diffusers_repo,
    normalize_diffusers_variant,
    normalize_huggingface_repo_file,
)
from services.comfyui.settings import normalize_huggingface_repo_id


DIFFUSERS_BACKEND_SCHEME = "diffusers"
DIFFUSERS_BACKEND_NETLOC = "local"
_SAFE_FILENAME_RE = re.compile(r"[^A-Za-z0-9._-]+")


def _format_bytes(value):
    size = max(0, int(value or 0))
    units = ("B", "KB", "MB", "GB", "TB")
    amount = float(size)
    unit = units[0]
    for unit in units:
        if amount < 1024 or unit == units[-1]:
            break
        amount /= 1024
    if unit == "B":
        return f"{int(amount)} {unit}"
    return f"{amount:.1f} {unit}"


def _format_speed(value):
    speed = max(0, float(value or 0))
    if speed <= 0:
        return ""
    return f"{_format_bytes(speed)}/s"


def diffusers_backend_url(repo_id=""):
    repo_id = str(repo_id or "").strip()
    suffix = f"/{quote(repo_id, safe='')}" if repo_id else ""
    return f"{DIFFUSERS_BACKEND_SCHEME}://{DIFFUSERS_BACKEND_NETLOC}{suffix}"


def repo_id_from_diffusers_url(value):
    parsed = urlparse(str(value or "").strip())
    if parsed.scheme != DIFFUSERS_BACKEND_SCHEME or parsed.netloc != DIFFUSERS_BACKEND_NETLOC:
        return ""
    return unquote(parsed.path.lstrip("/")).strip()


@dataclass(frozen=True)
class _PipelineCacheKey:
    model_repo: str
    variant: str
    gguf_file: str
    gguf_base_repo: str
    mode: str
    device: str
    dtype: str
    token_fingerprint: str


class DiffusersClient:
    backend_kind = "diffusers"
    _pipeline_cache = {}
    _pipeline_cache_lock = threading.RLock()

    def __init__(
        self,
        *,
        model_repo="",
        token="",
        storage_root=".",
        device="auto",
        dtype="auto",
        base_url="",
    ):
        self.model_repo = str(model_repo or "").strip()
        self.token = str(token or "").strip()
        self.storage_root = Path(storage_root or ".").expanduser()
        self.runtime_root = self.storage_root / "_runtime" / "comfyui_diffusers"
        self.device_setting = str(device or "auto").strip().lower()
        self.dtype_setting = str(dtype or "auto").strip().lower()
        self.base_url = str(base_url or diffusers_backend_url(self.model_repo))
        self.timeout = 30

    @classmethod
    def from_settings(cls, settings=None, *, storage_root=".", backend_url=""):
        settings = settings or {}
        repo_from_url = repo_id_from_diffusers_url(backend_url)
        model_repo = normalize_huggingface_repo_id(
            repo_from_url or settings.get("comfyui_diffusers_model_repo"),
            allow_blank=True,
        ) or ""
        return cls(
            model_repo=model_repo,
            token=settings.get("comfyui_huggingface_api_token") or "",
            storage_root=storage_root,
            device=settings.get("comfyui_diffusers_device") or "auto",
            dtype=settings.get("comfyui_diffusers_dtype") or "auto",
            base_url=backend_url or diffusers_backend_url(model_repo),
        )

    def _effective_model_repo(self, params=None):
        params = params or {}
        return normalize_huggingface_repo_id(
            params.get("diffusers_model_repo")
            or params.get("huggingface_model_repo")
            or params.get("hf_model_repo")
            or params.get("model")
            or self.model_repo,
            allow_blank=True,
        ) or ""

    def _ensure_configured(self, model_repo=None):
        if not str(model_repo or self.model_repo or "").strip():
            raise ComfyUIError("Diffusers 模式尚未設定 Hugging Face model repo，例如 dhead/waiIllustriousSDXL_v150")

    def _effective_model_variant(self, params=None):
        params = params or {}
        raw = str(params.get("diffusers_model_variant") or "").strip()
        if raw.startswith("gguf::"):
            return ""
        variant = normalize_diffusers_variant(raw, allow_blank=True)
        if variant is None:
            raise ComfyUIError("Diffusers 模型精度版本名稱不合法")
        return variant

    def _effective_gguf_file(self, params=None):
        params = params or {}
        selected = str(params.get("diffusers_model_variant") or "").strip()
        raw = params.get("diffusers_gguf_file") or ""
        if selected.startswith("gguf::"):
            raw = selected.split("::", 1)[1]
        gguf_file = normalize_huggingface_repo_file(raw, allow_blank=True)
        if gguf_file is None or (gguf_file and not gguf_file.lower().endswith(".gguf")):
            raise ComfyUIError("GGUF 檔案路徑不合法")
        return gguf_file

    def _effective_gguf_base_repo(self, params=None, *, model_repo=""):
        params = params or {}
        base_repo = normalize_huggingface_repo_id(params.get("diffusers_gguf_base_repo"), allow_blank=True)
        if base_repo is None:
            raise ComfyUIError("GGUF base Diffusers repo 格式不合法")
        if base_repo:
            return base_repo
        if not model_repo:
            model_repo = self._effective_model_repo(params)
        inspection = inspect_huggingface_diffusers_repo(model_repo, token=self.token, mode=params.get("generation_mode") or "txt2img")
        if inspection.get("suggested_base_repo"):
            return inspection["suggested_base_repo"]
        inferred = infer_gguf_base_repo(model_repo)
        if inferred:
            return inferred
        raise ComfyUIError("GGUF 需要設定 base Diffusers repo，例如 stabilityai/stable-diffusion-xl-base-1.0")

    def _missing_dependency_names(self):
        required = {
            "diffusers": "diffusers",
            "torch": "torch",
            "PIL": "Pillow",
        }
        missing = []
        for module_name, package_name in required.items():
            if importlib.util.find_spec(module_name) is None:
                missing.append(package_name)
        return missing

    def _ensure_dependencies(self):
        missing = self._missing_dependency_names()
        if missing:
            raise ComfyUIError(
                "Diffusers 模式需要先安裝 Python 套件："
                + ", ".join(missing)
                + "。建議同時安裝 transformers、accelerate、safetensors。"
            )

    def _ensure_gguf_dependencies(self):
        self._ensure_dependencies()
        missing = []
        for module_name, package_name in {"huggingface_hub": "huggingface-hub", "gguf": "gguf"}.items():
            if importlib.util.find_spec(module_name) is None:
                missing.append(package_name)
        if missing:
            raise ComfyUIError("GGUF 模式需要先安裝 Python 套件：" + ", ".join(missing))

    def _enable_hf_transfer_if_available(self):
        if importlib.util.find_spec("hf_transfer") is None:
            return False
        os.environ.setdefault("HF_HUB_ENABLE_HF_TRANSFER", "1")
        return True

    def health_check(self, *, timeout=3):
        self._ensure_dependencies()
        return {
            "ok": True,
            "backend": "diffusers",
            "base_url": self.base_url,
            "model_repo": self.model_repo,
            "token_configured": bool(self.token),
            "system": {
                "backend": "diffusers",
                "model_repo": self.model_repo,
                "device": self.device_setting,
                "dtype": self.dtype_setting,
            },
        }

    def get_models(self):
        return [self.model_repo] if self.model_repo else []

    def get_loras(self):
        return []

    def get_vaes(self):
        return []

    def get_embeddings(self):
        return []

    def get_sampler_options(self):
        return {"samplers": ["diffusers-auto"], "schedulers": ["default"]}

    def get_object_info(self, node_class=None):
        return {}

    def list_node_classes(self):
        return []

    def get_capabilities(self):
        model_families = detect_model_families([self.model_repo] if self.model_repo else [])
        supported_modes = {"txt2img", "img2img", "inpaint"}
        generation_modes = []
        for key, value in GENERATION_MODE_DEFINITIONS.items():
            available = key in supported_modes
            generation_modes.append({
                "key": key,
                "label": value.get("label") or key,
                "available": available,
                "workflow_only": bool(value.get("workflow_only")) if available else bool(value.get("workflow_only")),
                "output_kind": value.get("output_kind") or "image",
                "source_kind": value.get("source_kind") or "",
                "recommended_model_families": list(value.get("recommended_model_families") or []),
                "unavailable_reason": "" if available else "Diffusers 後端目前只支援文字生圖、圖生圖與局部重繪。",
            })
        return {
            "backend_kind": "diffusers",
            "available_nodes": [],
            "controlnet_models": [],
            "upscale_models": [],
            "controlnet_types": {},
            "generation_modes": generation_modes,
            "model_families": model_families,
            "model_repo": self.model_repo,
            "token_configured": bool(self.token),
        }

    def inspect_model_repo(self, repo_value, *, mode="txt2img"):
        return inspect_huggingface_diffusers_repo(repo_value, token=self.token, mode=mode)

    def _dir_for_type(self, file_type):
        normalized = str(file_type or "output").strip().lower()
        if normalized not in {"input", "output", "temp"}:
            normalized = "output"
        path = self.runtime_root / normalized
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _safe_filename(self, filename, *, fallback="image.png"):
        name = Path(str(filename or "")).name.strip()
        if not name:
            name = fallback
        name = _SAFE_FILENAME_RE.sub("_", name)[:160].strip("._")
        if not name:
            name = fallback
        return name

    def upload_image_bytes(self, data, filename, *, image_type="input", overwrite=False, subfolder=""):
        target_dir = self._safe_ref_dir({"type": image_type, "subfolder": subfolder})
        safe_name = self._safe_filename(filename)
        if not overwrite:
            safe_name = f"{uuid.uuid4().hex}_{safe_name}"
        path = target_dir / safe_name
        path.write_bytes(data or b"")
        return {"filename": safe_name, "subfolder": str(subfolder or "").strip(), "type": str(image_type or "input")}

    def _safe_ref_dir(self, file_ref):
        file_type = str((file_ref or {}).get("type") or "output").strip().lower()
        root = self._dir_for_type(file_type)
        subfolder = str((file_ref or {}).get("subfolder") or "").strip().replace("\\", "/")
        if not subfolder:
            return root
        parts = [part for part in subfolder.split("/") if part]
        if any(part in {".", ".."} for part in parts):
            raise ComfyUIError("Diffusers 檔案路徑不安全")
        target = (root / Path(*parts)).resolve()
        try:
            target.relative_to(root.resolve())
        except Exception as exc:
            raise ComfyUIError("Diffusers 檔案路徑超出允許範圍") from exc
        target.mkdir(parents=True, exist_ok=True)
        return target

    def _safe_ref_path(self, file_ref):
        if not isinstance(file_ref, dict):
            raise ComfyUIError("Diffusers 檔案參照格式錯誤")
        filename = self._safe_filename(file_ref.get("filename"), fallback="")
        if not filename:
            raise ComfyUIError("Diffusers 檔案參照缺少檔名")
        path = (self._safe_ref_dir(file_ref) / filename).resolve()
        try:
            path.relative_to(self.runtime_root.resolve())
        except Exception as exc:
            raise ComfyUIError("Diffusers 檔案路徑超出允許範圍") from exc
        return path

    def fetch_file(self, file_ref):
        path = self._safe_ref_path(file_ref)
        if not path.is_file():
            raise ComfyUIError("Diffusers 檔案不存在")
        mime_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        return ComfyUIImage(
            filename=path.name,
            subfolder=str((file_ref or {}).get("subfolder") or ""),
            type=str((file_ref or {}).get("type") or "output"),
            mime_type=mime_type,
            data=path.read_bytes(),
        )

    def fetch_image(self, image_ref):
        return self.fetch_file(image_ref)

    def discard_image(self, image_ref, *, prompt_id=None, local_base_dir=None, allow_api_delete=True):
        try:
            path = self._safe_ref_path(image_ref)
        except ComfyUIError:
            return {"file_deleted": False, "file_missing": True, "file_delete_supported": True, "history_deleted": False}
        if not path.exists():
            return {"file_deleted": False, "file_missing": True, "file_delete_supported": True, "history_deleted": False}
        try:
            path.unlink()
        except Exception as exc:
            raise ComfyUIError(f"Diffusers 預覽檔案刪除失敗：{exc}") from exc
        return {"file_deleted": True, "file_missing": False, "file_delete_supported": True, "history_deleted": bool(prompt_id)}

    def interrupt(self):
        return {"interrupted": False, "message": "Diffusers 後端目前不支援中斷已進入推論中的工作"}

    def _token_fingerprint(self):
        if not self.token:
            return ""
        return hashlib.sha256(self.token.encode("utf-8")).hexdigest()[:16]

    def _resolve_device(self, torch):
        requested = self.device_setting
        if requested in {"cpu", "cuda", "mps"}:
            return requested
        if torch.cuda.is_available():
            return "cuda"
        mps_backend = getattr(getattr(torch, "backends", None), "mps", None)
        if mps_backend is not None and mps_backend.is_available():
            return "mps"
        return "cpu"

    def _resolve_dtype(self, torch, device):
        requested = self.dtype_setting
        if requested == "float16":
            return torch.float16
        if requested == "bfloat16":
            return torch.bfloat16
        if requested == "float32":
            return torch.float32
        return torch.float16 if device == "cuda" else torch.float32

    def _huggingface_progress_tqdm_class(self, progress_callback, *, label="", base_percent=5, span_percent=20):
        if not progress_callback:
            return None
        try:
            from huggingface_hub.utils import tqdm as hf_tqdm
        except Exception:
            return None

        lock = threading.Lock()
        state = {"last_emit": 0.0}
        outer_label = str(label or "Hugging Face 模型")

        def emit(bar, *, force=False):
            now = time.monotonic()
            if not force and now - state["last_emit"] < 0.35:
                return
            with lock:
                state["last_emit"] = now
            current = max(0, int(getattr(bar, "_hackme_progress_n", 0) or 0))
            total = max(0, int(getattr(bar, "_hackme_progress_total", 0) or 0))
            last_current = max(0, int(getattr(bar, "_hackme_progress_last_n", 0) or 0))
            last_at = float(getattr(bar, "_hackme_progress_last_at", 0.0) or 0.0)
            previous_speed = float(getattr(bar, "_hackme_progress_speed_bps", 0.0) or 0.0)
            delta_t = now - last_at if last_at else 0.0
            instant_speed = ((current - last_current) / delta_t) if delta_t > 0 and current >= last_current else 0.0
            speed = (previous_speed * 0.65 + instant_speed * 0.35) if previous_speed and instant_speed else (instant_speed or previous_speed)
            bar._hackme_progress_last_n = current
            bar._hackme_progress_last_at = now
            bar._hackme_progress_speed_bps = speed
            ratio = (current / total) if total > 0 else 0
            percent = min(99, round(float(base_percent) + float(span_percent) * ratio, 1))
            unit = str(getattr(bar, "_hackme_progress_unit", "") or "")
            desc = str(getattr(bar, "_hackme_progress_desc", "") or "").strip() or outer_label
            current_file = desc
            if unit.upper() == "B" or total > 1024 * 1024:
                size_text = f"{_format_bytes(current)} / {_format_bytes(total)}" if total else _format_bytes(current)
                speed_text = _format_speed(speed)
                detail = f"下載 {desc}：{size_text}{f'，{speed_text}' if speed_text else ''}"
                payload = {
                    "phase": "downloading",
                    "percent": percent,
                    "step": "Hugging Face 檔案下載",
                    "current_file": current_file,
                    "detail": detail,
                    "bytes_written": current,
                    "total_bytes": total,
                    "speed_bytes_per_sec": int(speed) if speed > 0 else 0,
                }
            else:
                total_text = f"/{total}" if total else ""
                detail = f"下載 {desc}：{current}{total_text} {unit or 'items'}"
                payload = {
                    "phase": "downloading",
                    "percent": percent,
                    "step": "Hugging Face 檔案清單",
                    "current_file": current_file,
                    "detail": detail,
                    "current": current,
                    "max": total,
                }
            progress_callback(payload)

        class HuggingFaceProgressTqdm(hf_tqdm):
            def __init__(self, *args, **kwargs):
                initial = int(kwargs.get("initial") or 0)
                total = int(kwargs.get("total") or 0)
                desc = str(kwargs.get("desc") or outer_label)
                unit = str(kwargs.get("unit") or "")
                kwargs["disable"] = True
                super().__init__(*args, **kwargs)
                self._hackme_progress_n = initial
                self._hackme_progress_total = total
                self._hackme_progress_desc = desc
                self._hackme_progress_unit = unit
                self._hackme_progress_last_n = initial
                self._hackme_progress_last_at = time.monotonic()
                self._hackme_progress_speed_bps = 0.0
                emit(self, force=True)

            def update(self, n=1):
                try:
                    self._hackme_progress_n = max(0, int(getattr(self, "_hackme_progress_n", 0) or 0) + int(n or 0))
                except Exception:
                    pass
                result = super().update(n)
                emit(self)
                return result

            def __iter__(self):
                iterable = getattr(self, "iterable", None)
                if iterable is None:
                    return
                for item in iterable:
                    yield item
                    self.update(1)

            def close(self):
                emit(self, force=True)
                return super().close()

        return HuggingFaceProgressTqdm

    def _diffusers_snapshot_patterns(self, variant=""):
        base_patterns = [
            "*.json",
            "**/*.json",
            "*.txt",
            "**/*.txt",
            "*.model",
            "**/*.model",
            "*.spm",
            "**/*.spm",
            "*.py",
            "**/*.py",
        ]
        weight_extensions = ("safetensors", "bin")
        if variant:
            weights = []
            for ext in weight_extensions:
                weights.extend([f"*.{variant}.{ext}", f"**/*.{variant}.{ext}"])
            return base_patterns + weights, None
        weights = []
        for ext in weight_extensions:
            weights.extend([f"*.{ext}", f"**/*.{ext}"])
        ignore = []
        for precision in ("fp16", "float16", "half", "bf16", "bfloat16", "fp32", "float32"):
            ignore.extend([f"*.{precision}.*", f"**/*.{precision}.*"])
        return base_patterns + weights, ignore

    def _prefetch_diffusers_snapshot(self, model_repo, *, variant="", progress_callback=None, base_percent=5, span_percent=20):
        if not progress_callback:
            return ""
        try:
            from huggingface_hub import snapshot_download
        except Exception:
            return ""
        allow_patterns, ignore_patterns = self._diffusers_snapshot_patterns(variant)
        variant_text = f"（{variant}）" if variant else ""
        accelerated = self._enable_hf_transfer_if_available()
        progress_callback({
            "phase": "downloading",
            "percent": base_percent,
            "step": "Hugging Face metadata / cache 檢查",
            "current_file": "",
            "detail": (
                f"準備下載 Hugging Face 模型 {model_repo}{variant_text}"
                + ("；已啟用 hf_transfer 加速" if accelerated else "；使用 huggingface_hub 下載")
            ),
            "token_used": bool(self.token),
            "hf_transfer_enabled": accelerated,
        })
        tqdm_class = self._huggingface_progress_tqdm_class(
            progress_callback,
            label=f"{model_repo}{variant_text}",
            base_percent=base_percent,
            span_percent=span_percent,
        )
        kwargs = {
            "repo_id": model_repo,
            "token": (self.token or None),
            "allow_patterns": allow_patterns,
            "tqdm_class": tqdm_class,
        }
        if ignore_patterns:
            kwargs["ignore_patterns"] = ignore_patterns
        try:
            snapshot_path = snapshot_download(**kwargs)
        except TypeError:
            kwargs.pop("tqdm_class", None)
            snapshot_path = snapshot_download(**kwargs)
        except Exception as exc:
            raise ComfyUIError(f"Hugging Face 模型下載失敗：{exc}") from exc
        progress_callback({
            "phase": "loading",
            "percent": min(99, base_percent + span_percent),
            "step": "載入 Diffusers pipeline",
            "current_file": "",
            "detail": f"Hugging Face 模型已下載到本機快取，正在載入 {model_repo}{variant_text}",
        })
        return str(snapshot_path or "")

    def _pipeline_class(self, mode):
        if mode == "txt2img":
            from diffusers import AutoPipelineForText2Image

            return AutoPipelineForText2Image
        if mode == "img2img":
            from diffusers import AutoPipelineForImage2Image

            return AutoPipelineForImage2Image
        if mode == "inpaint":
            from diffusers import AutoPipelineForInpainting

            return AutoPipelineForInpainting
        raise ComfyUIError("Diffusers 後端目前只支援文字生圖、圖生圖與局部重繪")

    def _load_pipeline(self, mode, progress_callback=None, model_repo=None, variant="", gguf_file="", gguf_base_repo=""):
        model_repo = self._effective_model_repo({"model": model_repo})
        variant = self._effective_model_variant({"diffusers_model_variant": variant})
        gguf_file = self._effective_gguf_file({"diffusers_gguf_file": gguf_file})
        if gguf_file:
            gguf_base_repo = self._effective_gguf_base_repo(
                {"diffusers_gguf_base_repo": gguf_base_repo, "generation_mode": mode},
                model_repo=model_repo,
            )
        self._ensure_configured(model_repo)
        if gguf_file:
            self._ensure_gguf_dependencies()
        else:
            self._ensure_dependencies()
        import torch

        device = self._resolve_device(torch)
        dtype = self._resolve_dtype(torch, device)
        cache_key = _PipelineCacheKey(
            model_repo=model_repo,
            variant=variant,
            gguf_file=gguf_file,
            gguf_base_repo=gguf_base_repo,
            mode=mode,
            device=device,
            dtype=str(dtype),
            token_fingerprint=self._token_fingerprint(),
        )
        with self._pipeline_cache_lock:
            cached = self._pipeline_cache.get(cache_key)
            if cached is not None:
                if progress_callback:
                    progress_callback({
                        "phase": "loading",
                        "percent": 24,
                        "step": "使用已載入模型快取",
                        "detail": f"已使用記憶體中的 Diffusers pipeline：{model_repo}",
                        "current_file": "",
                    })
                return cached, torch, device
            if gguf_file:
                pipe = self._load_gguf_pipeline(
                    mode,
                    model_repo=model_repo,
                    gguf_file=gguf_file,
                    gguf_base_repo=gguf_base_repo,
                    dtype=dtype,
                    device=device,
                    progress_callback=progress_callback,
                )
                self._pipeline_cache[cache_key] = pipe
                return pipe, torch, device
            if progress_callback:
                variant_text = f"（{variant}）" if variant else ""
                progress_callback({
                    "phase": "loading",
                    "percent": 5,
                    "step": "解析模型設定",
                    "detail": f"正在載入 Hugging Face 模型 {model_repo}{variant_text}",
                    "current_file": "",
                    "token_used": bool(self.token),
                })
            pipeline_cls = self._pipeline_class(mode)
            kwargs = {
                "torch_dtype": dtype,
                "use_safetensors": True,
            }
            if variant:
                kwargs["variant"] = variant
            if self.token:
                kwargs["token"] = self.token
            snapshot_path = self._prefetch_diffusers_snapshot(
                model_repo,
                variant=variant,
                progress_callback=progress_callback,
                base_percent=6,
                span_percent=18,
            )
            load_target = snapshot_path or model_repo
            if snapshot_path:
                kwargs["local_files_only"] = True
            try:
                pipe = pipeline_cls.from_pretrained(load_target, **kwargs)
            except TypeError:
                if self.token:
                    kwargs["use_auth_token"] = kwargs.pop("token")
                pipe = pipeline_cls.from_pretrained(load_target, **kwargs)
            except Exception:
                fallback_kwargs = dict(kwargs)
                fallback_kwargs.pop("use_safetensors", None)
                try:
                    pipe = pipeline_cls.from_pretrained(load_target, **fallback_kwargs)
                except Exception as exc:
                    if not snapshot_path:
                        raise ComfyUIError(f"Diffusers 模型載入失敗：{exc}") from exc
                    if progress_callback:
                        progress_callback({
                            "phase": "downloading",
                            "percent": 24,
                            "step": "補齊 Diffusers 缺漏檔案",
                            "current_file": "",
                            "detail": "本機快取缺少部分檔案，改由 Diffusers 補齊 Hugging Face 檔案。",
                            "token_used": bool(self.token),
                        })
                    remote_kwargs = dict(kwargs)
                    remote_kwargs.pop("local_files_only", None)
                    try:
                        pipe = pipeline_cls.from_pretrained(model_repo, **remote_kwargs)
                    except TypeError:
                        if self.token and "token" in remote_kwargs:
                            remote_kwargs["use_auth_token"] = remote_kwargs.pop("token")
                        pipe = pipeline_cls.from_pretrained(model_repo, **remote_kwargs)
                    except Exception:
                        remote_fallback_kwargs = dict(remote_kwargs)
                        remote_fallback_kwargs.pop("use_safetensors", None)
                        try:
                            pipe = pipeline_cls.from_pretrained(model_repo, **remote_fallback_kwargs)
                        except Exception as remote_exc:
                            raise ComfyUIError(f"Diffusers 模型載入失敗：{remote_exc}") from remote_exc
            try:
                if progress_callback:
                    progress_callback({
                        "phase": "loading",
                        "percent": 24,
                        "step": f"移動模型到 {device}",
                        "current_file": "",
                        "detail": f"Diffusers pipeline 已載入，正在移至 {device}",
                    })
                pipe.to(device)
            except Exception as exc:
                raise ComfyUIError(f"Diffusers 模型移至裝置 {device} 失敗：{exc}") from exc
            if hasattr(pipe, "set_progress_bar_config"):
                try:
                    pipe.set_progress_bar_config(disable=True)
                except Exception:
                    pass
            if hasattr(pipe, "enable_attention_slicing"):
                try:
                    pipe.enable_attention_slicing()
                except Exception:
                    pass
            self._pipeline_cache[cache_key] = pipe
            return pipe, torch, device

    def _load_gguf_pipeline(self, mode, *, model_repo, gguf_file, gguf_base_repo, dtype, device, progress_callback=None):
        if mode != "txt2img":
            raise ComfyUIError("GGUF Diffusers 模式目前只支援文字生圖；圖生圖與局部重繪請改用一般 Diffusers repo 或 ComfyUI workflow。")
        if progress_callback:
            progress_callback({
                "phase": "loading",
                "percent": 5,
                "step": "準備 GGUF component",
                "current_file": gguf_file,
                "detail": f"正在下載/載入 GGUF 檔案 {gguf_file}",
                "token_used": bool(self.token),
            })
        try:
            from huggingface_hub import hf_hub_download
            from diffusers import GGUFQuantizationConfig
        except Exception as exc:
            raise ComfyUIError(f"GGUF 依賴載入失敗：{exc}") from exc
        try:
            tqdm_class = self._huggingface_progress_tqdm_class(
                progress_callback,
                label=gguf_file,
                base_percent=6,
                span_percent=16,
            )
            accelerated = self._enable_hf_transfer_if_available()
            if progress_callback:
                progress_callback({
                    "phase": "downloading",
                    "percent": 6,
                    "step": "下載 GGUF component",
                    "current_file": gguf_file,
                    "detail": (
                        f"準備下載 {gguf_file}"
                        + ("；已啟用 hf_transfer 加速" if accelerated else "；使用 huggingface_hub 下載")
                    ),
                    "token_used": bool(self.token),
                    "hf_transfer_enabled": accelerated,
                })
            kwargs = {"repo_id": model_repo, "filename": gguf_file, "token": (self.token or None)}
            if tqdm_class:
                kwargs["tqdm_class"] = tqdm_class
            try:
                gguf_path = hf_hub_download(**kwargs)
            except TypeError:
                kwargs.pop("tqdm_class", None)
                gguf_path = hf_hub_download(**kwargs)
        except Exception as exc:
            raise ComfyUIError(f"GGUF 檔案下載失敗，尚未載入模型：{exc}") from exc

        text = f"{model_repo}/{gguf_file}/{gguf_base_repo}".lower()
        quantization_config = GGUFQuantizationConfig(compute_dtype=dtype)
        common_kwargs = {"torch_dtype": dtype}
        if self.token:
            common_kwargs["token"] = self.token
        try:
            if "flux" in text:
                from diffusers import FluxPipeline, FluxTransformer2DModel

                transformer = FluxTransformer2DModel.from_single_file(
                    gguf_path,
                    quantization_config=quantization_config,
                    config=gguf_base_repo,
                    subfolder="transformer",
                    torch_dtype=dtype,
                )
                pipe = FluxPipeline.from_pretrained(gguf_base_repo, transformer=transformer, **common_kwargs)
            else:
                from diffusers import StableDiffusionXLPipeline, UNet2DConditionModel

                unet = UNet2DConditionModel.from_single_file(
                    gguf_path,
                    quantization_config=quantization_config,
                    config=gguf_base_repo,
                    subfolder="unet",
                    torch_dtype=dtype,
                )
                pipe = StableDiffusionXLPipeline.from_pretrained(gguf_base_repo, unet=unet, **common_kwargs)
        except Exception as exc:
            raise ComfyUIError(
                "GGUF 模型載入失敗：Diffusers GGUF 需要可用的 base Diffusers repo 與相容的 GGUF component。"
                f"目前 base={gguf_base_repo}，檔案={gguf_file}。原始錯誤：{exc}"
            ) from exc
        try:
            pipe.to(device)
        except Exception as exc:
            raise ComfyUIError(f"GGUF pipeline 移至裝置 {device} 失敗：{exc}") from exc
        if hasattr(pipe, "set_progress_bar_config"):
            try:
                pipe.set_progress_bar_config(disable=True)
            except Exception:
                pass
        return pipe

    def _load_ref_image(self, image_ref, *, mode="RGB", size=None):
        from PIL import Image, ImageOps

        image = self.fetch_image(image_ref)
        try:
            loaded = Image.open(io.BytesIO(image.data))
            loaded = ImageOps.exif_transpose(loaded).convert(mode)
        except Exception as exc:
            raise ComfyUIError(f"Diffusers 圖片讀取失敗：{exc}") from exc
        if size:
            resampling = getattr(getattr(Image, "Resampling", Image), "LANCZOS")
            loaded = loaded.resize(size, resampling)
        return loaded

    def _save_output_image(self, image, *, index=0):
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        data = buffer.getvalue()
        filename = f"hackme_web_diffusers_{uuid.uuid4().hex}_{index + 1:02d}.png"
        path = self._dir_for_type("output") / filename
        path.write_bytes(data)
        return {
            "image_ref": {"filename": filename, "subfolder": "", "type": "output"},
            "mime_type": "image/png",
            "data": data,
        }

    def generate_image(self, params, *, timeout_seconds=1800, progress_callback=None, extra_data=None):
        params = params or {}
        mode = str(params.get("generation_mode") or "txt2img").strip().lower()
        if mode not in {"txt2img", "img2img", "inpaint"}:
            raise ComfyUIError("Diffusers 後端目前只支援文字生圖、圖生圖與局部重繪")
        if params.get("loras"):
            raise ComfyUIError("Diffusers 後端目前不支援本站 ComfyUI LoRA 選擇，請改用 ComfyUI 本地/遠端模式")
        if params.get("controlnet"):
            raise ComfyUIError("Diffusers 後端目前不支援本站 ControlNet 快捷模式，請改用 ComfyUI 本地/遠端模式")
        model_repo = self._effective_model_repo(params)
        variant = self._effective_model_variant(params)
        gguf_file = self._effective_gguf_file(params)
        gguf_base_repo = ""
        if gguf_file:
            gguf_base_repo = self._effective_gguf_base_repo(params, model_repo=model_repo)
            variant = ""
        params["diffusers_model_repo"] = model_repo
        params["model"] = model_repo
        params["diffusers_model_variant"] = variant
        params["diffusers_gguf_file"] = gguf_file
        params["diffusers_gguf_base_repo"] = gguf_base_repo
        pipe, torch, device = self._load_pipeline(
            mode,
            progress_callback=progress_callback,
            model_repo=model_repo,
            variant=variant,
            gguf_file=gguf_file,
            gguf_base_repo=gguf_base_repo,
        )
        width = max(64, int(params.get("width") or 1024))
        height = max(64, int(params.get("height") or 1024))
        size = (width, height)
        prompt = str(params.get("prompt") or "").strip()
        negative_prompt = str(params.get("negative_prompt") or "").strip()
        batch_size = max(1, int(params.get("batch_size") or 1))
        seed = int(params.get("seed") or 0)
        generator_device = "cuda" if device == "cuda" else "cpu"
        generator = torch.Generator(device=generator_device)
        generator.manual_seed(seed)
        call_kwargs = {
            "prompt": prompt,
            "num_inference_steps": max(1, int(params.get("steps") or 20)),
            "guidance_scale": float(params.get("cfg") or 7.0),
            "num_images_per_prompt": batch_size,
            "generator": generator,
        }
        if negative_prompt:
            call_kwargs["negative_prompt"] = negative_prompt
        if mode == "txt2img":
            call_kwargs.update({"width": width, "height": height})
        elif mode == "img2img":
            source_ref = params.get("source_image_ref")
            if not source_ref:
                raise ComfyUIError("Diffusers 圖生圖需要來源圖片")
            call_kwargs["image"] = self._load_ref_image(source_ref, size=size)
            call_kwargs["strength"] = float(params.get("denoise_strength") or 0.65)
        elif mode == "inpaint":
            source_ref = params.get("source_image_ref")
            mask_ref = params.get("mask_image_ref")
            if not source_ref or not mask_ref:
                raise ComfyUIError("Diffusers 局部重繪需要來源圖片與遮罩圖片")
            call_kwargs["image"] = self._load_ref_image(source_ref, size=size)
            call_kwargs["mask_image"] = self._load_ref_image(mask_ref, mode="L", size=size)
            call_kwargs["strength"] = float(params.get("denoise_strength") or 0.65)
        if progress_callback:
            progress_callback({
                "phase": "running",
                "percent": 25,
                "step": f"Diffusers {mode} 推論",
                "current_file": "",
                "detail": f"Diffusers 推論中：steps={call_kwargs['num_inference_steps']}，device={device}",
            })
        try:
            with torch.inference_mode():
                output = pipe(**call_kwargs)
        except TypeError as exc:
            raise ComfyUIError(f"Diffusers pipeline 參數不相容：{exc}") from exc
        except Exception as exc:
            raise ComfyUIError(f"Diffusers 產圖失敗：{exc}") from exc
        generated_images = list(getattr(output, "images", []) or [])
        if not generated_images:
            raise ComfyUIError("Diffusers 產圖完成但沒有輸出圖片")
        if progress_callback:
            progress_callback({
                "phase": "running",
                "percent": 92,
                "step": "保存輸出圖片",
                "current_file": "",
                "detail": f"Diffusers 推論完成，正在保存 {len(generated_images)} 張圖片",
            })
        images = [self._save_output_image(image, index=index) for index, image in enumerate(generated_images)]
        prompt_id = f"diffusers-{uuid.uuid4().hex}"
        if progress_callback:
            progress_callback({"phase": "completed", "percent": 100, "completed": True, "detail": f"Diffusers 已完成，共 {len(images)} 張"})
        return {
            "prompt_id": prompt_id,
            "image_ref": images[0]["image_ref"],
            "mime_type": images[0]["mime_type"],
            "data": images[0]["data"],
            "images": images,
        }
