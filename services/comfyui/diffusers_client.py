"""Hugging Face Diffusers backend for the ComfyUI module.

The public routes still speak the existing ComfyUI-shaped contract. This
client only replaces the execution backend when root selects diffusers mode.
"""

from __future__ import annotations

import hashlib
import importlib.util
import io
import mimetypes
import re
import threading
import uuid
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote, unquote, urlparse

from services.comfyui.client import ComfyUIError, ComfyUIImage
from services.comfyui.constants import GENERATION_MODE_DEFINITIONS, detect_model_families


DIFFUSERS_BACKEND_SCHEME = "diffusers"
DIFFUSERS_BACKEND_NETLOC = "local"
_SAFE_FILENAME_RE = re.compile(r"[^A-Za-z0-9._-]+")


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
        model_repo = repo_from_url or str(settings.get("comfyui_diffusers_model_repo") or "").strip()
        return cls(
            model_repo=model_repo,
            token=settings.get("comfyui_huggingface_api_token") or "",
            storage_root=storage_root,
            device=settings.get("comfyui_diffusers_device") or "auto",
            dtype=settings.get("comfyui_diffusers_dtype") or "auto",
            base_url=backend_url or diffusers_backend_url(model_repo),
        )

    def _ensure_configured(self):
        if not self.model_repo:
            raise ComfyUIError("Diffusers 模式尚未設定 Hugging Face model repo，例如 dhead/waiIllustriousSDXL_v150")

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

    def health_check(self, *, timeout=3):
        self._ensure_configured()
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

    def _load_pipeline(self, mode, progress_callback=None):
        self._ensure_configured()
        self._ensure_dependencies()
        import torch

        device = self._resolve_device(torch)
        dtype = self._resolve_dtype(torch, device)
        cache_key = _PipelineCacheKey(
            model_repo=self.model_repo,
            mode=mode,
            device=device,
            dtype=str(dtype),
            token_fingerprint=self._token_fingerprint(),
        )
        with self._pipeline_cache_lock:
            cached = self._pipeline_cache.get(cache_key)
            if cached is not None:
                return cached, torch, device
            if progress_callback:
                progress_callback({"phase": "loading", "percent": 5, "detail": f"正在載入 Hugging Face 模型 {self.model_repo}"})
            pipeline_cls = self._pipeline_class(mode)
            kwargs = {
                "torch_dtype": dtype,
                "use_safetensors": True,
            }
            if self.token:
                kwargs["token"] = self.token
            try:
                pipe = pipeline_cls.from_pretrained(self.model_repo, **kwargs)
            except TypeError:
                if self.token:
                    kwargs["use_auth_token"] = kwargs.pop("token")
                pipe = pipeline_cls.from_pretrained(self.model_repo, **kwargs)
            except Exception:
                fallback_kwargs = dict(kwargs)
                fallback_kwargs.pop("use_safetensors", None)
                try:
                    pipe = pipeline_cls.from_pretrained(self.model_repo, **fallback_kwargs)
                except Exception as exc:
                    raise ComfyUIError(f"Diffusers 模型載入失敗：{exc}") from exc
            try:
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
        pipe, torch, device = self._load_pipeline(mode, progress_callback=progress_callback)
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
            progress_callback({"phase": "running", "percent": 25, "detail": "Diffusers 推論中"})
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
