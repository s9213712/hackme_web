#!/usr/bin/env python3
"""Standalone GGUF txt2img probe.

This script does not require hackme_web.  It downloads a Hugging Face GGUF,
inspects whether it is a Diffusers-compatible component or a native
ComfyUI-GGUF UNet, then either runs Diffusers directly or submits a ComfyUI
GGUF workflow.
"""

from __future__ import annotations

import argparse
import http.client
import json
import os
import platform
import re
import shutil
import ssl
import sys
import threading
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path


DEFAULT_MODEL = "kekusprod/WAI-NSFW-illustrious-SDXL-v110-GGUF"
DEFAULT_BASE_REPO = "stabilityai/stable-diffusion-xl-base-1.0"
DEFAULT_AUX_REPO = "calcuis/illustrious"
DEFAULT_AUX_CLIP_L = "illustrious_clip_l_fp8_e4m3fn.safetensors"
DEFAULT_AUX_CLIP_G = "illustrious_clip_g_fp8_e4m3fn.safetensors"
DEFAULT_AUX_VAE = "illustrious_v110_vae_fp8_e4m3fn.safetensors"
DEFAULT_PROMPT = (
    "adult women, fully clothed, by ogipote, 2girls, girls love, kiss, "
    "saliva, maid uniform, cat ears, cat tail"
)
DEFAULT_NEGATIVE = (
    "child, minor, underage, loli, teen, nude, naked, explicit, low quality, "
    "blurry, watermark, distorted, bad anatomy"
)
GGUF_PREFERENCE = ("q8_0", "q6_k", "q5_k_m", "q4_k_m", "q3_k_m", "f16")
SENSITIVE_RE = re.compile(r"hf_[A-Za-z0-9]{8,}|(Bearer\s+)[A-Za-z0-9._-]+", re.IGNORECASE)


class ProbeError(RuntimeError):
    pass


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def sanitize_text(value) -> str:
    text = str(value or "")
    return SENSITIVE_RE.sub(lambda match: (match.group(1) or "") + "***" if match.group(1) else "hf_***", text)


def _explicit_cli_dests(parser: argparse.ArgumentParser, argv: list[str]) -> set[str]:
    explicit = set()
    for action in parser._actions:
        if not action.option_strings:
            continue
        for option in action.option_strings:
            if any(raw == option or raw.startswith(option + "=") for raw in argv):
                explicit.add(action.dest)
                break
    return explicit


def _profile_from_config(config: dict, profile_id: str) -> dict:
    profiles = config.get("gguf_profiles")
    if isinstance(profiles, dict):
        profile = profiles.get(profile_id)
        return dict(profile) if isinstance(profile, dict) else {}
    if isinstance(profiles, list):
        for profile in profiles:
            if isinstance(profile, dict) and str(profile.get("id") or "").strip() == profile_id:
                return dict(profile)
    return {}


def _config_sections(config: dict, section_names: tuple[str, ...], *, profile_id: str = "") -> dict:
    reserved = {"common", *section_names, "regular_comfyui", "hf_diffusers", "gguf", "gguf_profiles"}
    merged = {key: value for key, value in config.items() if key not in reserved and not isinstance(value, dict)}
    common = config.get("common")
    if isinstance(common, dict):
        merged.update(common)
    for section_name in section_names:
        section = config.get(section_name)
        if isinstance(section, dict):
            merged.update(section)
    selected_profile = str(profile_id or merged.get("gguf_profile") or config.get("gguf_profile") or "").strip()
    profile = _profile_from_config(config, selected_profile) if selected_profile else {}
    if profile:
        merged = {**profile, **merged, "gguf_profile": selected_profile}
    return merged


def apply_config(args, parser: argparse.ArgumentParser, *, section_names=("gguf",), argv=None):
    config_path = str(getattr(args, "config", "") or "").strip()
    args.config_loaded = ""
    if not config_path:
        return args
    path = Path(config_path).expanduser().resolve()
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ProbeError("--config must point to a JSON object")
    config = _config_sections(raw, tuple(section_names), profile_id=str(getattr(args, "gguf_profile", "") or ""))
    explicit = _explicit_cli_dests(parser, list(argv or sys.argv[1:]))
    aliases = {
        "negative_prompt": ("negative",),
        "hf_cache_root": ("cache_root", "huggingface_cache_root"),
        "sample_interval": ("resource_sample_interval",),
        "base_repo": ("gguf_base_repo",),
        "install_to_comfyui_unet_dir": ("comfyui_unet_dir",),
        "install_to_comfyui_text_encoder_dir": ("comfyui_text_encoder_dir", "comfyui_clip_dir"),
        "install_to_comfyui_vae_dir": ("comfyui_vae_dir",),
        "comfyui_model_name": ("comfyui_unet_name",),
        "aux_repo": ("gguf_aux_repo",),
        "aux_clip_l": ("gguf_aux_clip_l",),
        "aux_clip_g": ("gguf_aux_clip_g",),
        "aux_vae": ("gguf_aux_vae",),
        "clip_loader_class": ("gguf_clip_loader_class",),
    }
    for action in parser._actions:
        dest = action.dest
        if dest in {"help", "config"} or dest in explicit:
            continue
        keys = (dest, dest.replace("_", "-"), *aliases.get(dest, ()))
        for key in keys:
            if key in config:
                setattr(args, dest, config[key])
                break
    args.config_loaded = str(path)
    return args


def parse_bool(value) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "on", "enabled"}


def default_cache_root() -> str:
    explicit = os.environ.get("HF_PROBE_CACHE_ROOT") or os.environ.get("HF_HOME")
    if explicit:
        return explicit
    if os.name == "nt":
        for candidate in ("D:/", str(Path.home() / ".cache" / "huggingface")):
            try:
                if Path(candidate).exists():
                    return candidate
            except OSError:
                continue
        return str(Path.home() / ".cache" / "huggingface")
    return str(Path.home() / ".cache" / "huggingface")


def windows_equivalent_path(value: str) -> str:
    raw = str(value or "").strip()
    if os.name == "nt" and raw.startswith("/mnt/") and len(raw) >= 6 and raw[5].isalpha():
        drive = raw[5].upper()
        rest = raw[6:].lstrip("/").replace("/", "\\")
        return f"{drive}:\\{rest}" if rest else f"{drive}:\\"
    return raw


def normalize_runtime_paths(args):
    if os.name != "nt":
        return args
    for name in (
        "hf_cache_root",
        "out_dir",
        "out_json",
        "hf_token_file",
        "install_to_comfyui_unet_dir",
        "install_to_comfyui_text_encoder_dir",
        "install_to_comfyui_vae_dir",
    ):
        if hasattr(args, name):
            setattr(args, name, windows_equivalent_path(getattr(args, name)))
    return args


def configure_hf_env(cache_root: str, *, disable_xet: bool = True) -> dict:
    root = Path(os.path.expandvars(str(cache_root or default_cache_root()))).expanduser().resolve()
    hub = root / "hub"
    root.mkdir(parents=True, exist_ok=True)
    hub.mkdir(parents=True, exist_ok=True)
    os.environ["HF_HOME"] = str(root)
    os.environ["HF_HUB_CACHE"] = str(hub)
    os.environ["HUGGINGFACE_HUB_CACHE"] = str(hub)
    if disable_xet:
        os.environ["HF_HUB_DISABLE_XET"] = "1"
    return {
        "hf_home": str(root),
        "hf_hub_cache": str(hub),
        "xet_disabled": os.environ.get("HF_HUB_DISABLE_XET") == "1",
    }


def repo_cache_dir(cache_root: str, repo_id: str) -> Path:
    return Path(cache_root).expanduser().resolve() / "hub" / ("models--" + repo_id.replace("/", "--"))


def dir_size_bytes(path: Path) -> int:
    if not path.exists():
        return 0
    total = 0
    for item in path.rglob("*"):
        try:
            if item.is_file():
                total += int(item.stat().st_size)
        except OSError:
            continue
    return total


def cache_report(cache_root: str, repo_id: str) -> dict:
    path = repo_cache_dir(cache_root, repo_id)
    return {
        "path": str(path),
        "exists": path.exists(),
        "size_bytes": dir_size_bytes(path) if path.exists() else 0,
    }


def read_token(args) -> str:
    token = ""
    if args.hf_token_env:
        token = str(os.environ.get(args.hf_token_env) or "").strip()
    if not token and args.hf_token_file:
        token = Path(args.hf_token_file).expanduser().read_text(encoding="utf-8").strip()
    if not token and args.hf_token_stdin:
        token = sys.stdin.readline().strip()
    return token


def module_versions() -> dict:
    versions = {"python": sys.version.split()[0], "platform": platform.platform()}
    for module_name in ("torch", "diffusers", "huggingface_hub", "gguf", "PIL"):
        try:
            module = __import__(module_name)
            versions[module_name] = str(getattr(module, "__version__", "unknown"))
        except Exception as exc:
            versions[module_name] = f"missing: {exc}"
    return versions


class ResourceMonitor:
    def __init__(self, interval: float = 1.0):
        self.interval = max(0.2, float(interval or 1.0))
        self.samples = []
        self._stop = threading.Event()
        self._thread = None
        self._psutil = None
        self._process = None
        self._pynvml = None
        self._nvml_handle = None
        self._init_optional_backends()

    def _init_optional_backends(self):
        try:
            import psutil  # type: ignore

            self._psutil = psutil
            self._process = psutil.Process(os.getpid())
        except Exception:
            self._psutil = None
            self._process = None
        try:
            import pynvml  # type: ignore

            pynvml.nvmlInit()
            self._pynvml = pynvml
            self._nvml_handle = pynvml.nvmlDeviceGetHandleByIndex(0)
        except Exception:
            self._pynvml = None
            self._nvml_handle = None

    def __enter__(self):
        self._thread = threading.Thread(target=self._loop, name="gguf-resource-monitor", daemon=True)
        self._thread.start()
        return self

    def __exit__(self, exc_type, exc, tb):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)
        self.sample()
        return False

    def _loop(self):
        while not self._stop.is_set():
            self.sample()
            self._stop.wait(self.interval)

    def sample(self):
        payload = {"elapsed_at": time.time()}
        if self._psutil and self._process:
            try:
                mem = self._process.memory_info()
                virt = self._psutil.virtual_memory()
                payload.update({
                    "process_rss_mb": round(mem.rss / 1024 / 1024, 1),
                    "process_vms_mb": round(mem.vms / 1024 / 1024, 1),
                    "cpu_percent": self._process.cpu_percent(interval=None),
                    "ram_used_percent": round(float(virt.percent), 1),
                    "ram_available_mb": round(int(virt.available) / 1024 / 1024, 1),
                })
            except Exception as exc:
                payload["psutil_error"] = str(exc)
        else:
            try:
                import resource

                rss_kb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
                rss_mb = rss_kb / 1024 / 1024 if sys.platform == "darwin" else rss_kb / 1024
                payload["process_rss_mb"] = round(rss_mb, 1)
            except Exception:
                pass
        if self._pynvml and self._nvml_handle:
            try:
                mem = self._pynvml.nvmlDeviceGetMemoryInfo(self._nvml_handle)
                util = self._pynvml.nvmlDeviceGetUtilizationRates(self._nvml_handle)
                name = self._pynvml.nvmlDeviceGetName(self._nvml_handle)
                if isinstance(name, bytes):
                    name = name.decode("utf-8", errors="replace")
                payload.update({
                    "gpu_name": str(name),
                    "gpu_util_percent": int(util.gpu),
                    "gpu_mem_util_percent": int(util.memory),
                    "vram_total_mb": round(int(mem.total) / 1024 / 1024, 1),
                    "vram_used_mb": round(int(mem.used) / 1024 / 1024, 1),
                    "vram_free_mb": round(int(mem.free) / 1024 / 1024, 1),
                })
            except Exception as exc:
                payload["gpu_error"] = str(exc)
        self.samples.append(payload)

    def summary(self, started_at: float) -> dict:
        normalized = []
        for sample in self.samples:
            item = dict(sample)
            item["elapsed_seconds"] = round(float(item.pop("elapsed_at", started_at)) - started_at, 2)
            normalized.append(item)
        peak = {}
        for key in ("process_rss_mb", "process_vms_mb", "cpu_percent", "ram_used_percent", "vram_used_mb", "gpu_util_percent"):
            values = [float(item[key]) for item in normalized if isinstance(item.get(key), (int, float))]
            if values:
                peak[f"peak_{key}"] = round(max(values), 2)
        return {"samples": normalized, "peaks": peak}


def list_gguf_files(repo_id: str, token: str) -> list[dict]:
    from huggingface_hub import HfApi

    info = HfApi().model_info(repo_id, token=token or None, files_metadata=True)
    files = []
    for sibling in getattr(info, "siblings", []) or []:
        name = str(getattr(sibling, "rfilename", "") or "")
        if not name.lower().endswith(".gguf"):
            continue
        size = getattr(sibling, "size", None)
        files.append({"filename": name, "size_bytes": int(size or 0)})
    return sorted(files, key=lambda item: item["filename"].lower())


def select_gguf_file(files: list[dict], requested: str = "") -> str:
    requested = str(requested or "").strip()
    if requested:
        return requested
    if not files:
        raise ProbeError("repo has no .gguf files; pass --gguf-file if the file list is private or unusual")

    def rank(item):
        name = str(item.get("filename") or "").lower()
        for index, marker in enumerate(GGUF_PREFERENCE):
            if marker in name:
                return (index, name)
        return (len(GGUF_PREFERENCE), name)

    return str(sorted(files, key=rank)[0]["filename"])


def download_gguf(repo_id: str, filename: str, token: str, *, local_files_only: bool = False) -> Path:
    return download_hf_file(repo_id, filename, token, local_files_only=local_files_only)


def download_hf_file(repo_id: str, filename: str, token: str, *, local_files_only: bool = False) -> Path:
    from huggingface_hub import hf_hub_download

    path = hf_hub_download(
        repo_id=repo_id,
        filename=filename,
        token=token or None,
        cache_dir=os.environ.get("HF_HUB_CACHE") or None,
        local_files_only=bool(local_files_only),
    )
    return Path(path).expanduser().resolve()


def inspect_gguf(path: Path) -> dict:
    from gguf import GGUFReader

    reader = GGUFReader(str(path))
    fields = set(getattr(reader, "fields", {}) or {})
    tensors = list(getattr(reader, "tensors", []) or [])
    tensor_names = [str(getattr(tensor, "name", "") or "") for tensor in tensors[:100]]
    has_comfy_metadata = any(name.startswith("comfy.gguf.") for name in fields)
    has_original_unet_names = any(
        name.startswith(("input_blocks.", "middle_block.", "output_blocks.", "out."))
        for name in tensor_names
    )
    suggested_backend = "comfyui_gguf" if has_comfy_metadata and has_original_unet_names else "diffusers"
    return {
        "field_count": len(fields),
        "tensor_count": len(tensors),
        "has_comfy_metadata": has_comfy_metadata,
        "has_original_unet_names": has_original_unet_names,
        "suggested_backend": suggested_backend,
        "sample_tensors": tensor_names[:12],
    }


def resolve_device_and_dtype(torch, args):
    requested_device = str(args.device or "auto").strip().lower()
    if requested_device == "auto":
        device = "cuda" if torch.cuda.is_available() else "cpu"
    else:
        device = requested_device
    requested_dtype = str(args.dtype or "auto").strip().lower()
    if requested_dtype == "auto":
        dtype = torch.float16 if device == "cuda" else torch.float32
    elif requested_dtype in {"float16", "fp16", "half"}:
        dtype = torch.float16
    elif requested_dtype in {"bfloat16", "bf16"}:
        dtype = torch.bfloat16
    elif requested_dtype in {"float32", "fp32"}:
        dtype = torch.float32
    else:
        raise ProbeError(f"unsupported dtype: {args.dtype}")
    return device, dtype


def run_diffusers_gguf(args, token: str, gguf_path: Path, metadata: dict, out_png: Path, timings: dict) -> dict:
    if metadata.get("suggested_backend") == "comfyui_gguf" and not args.allow_comfy_native_diffusers:
        raise ProbeError(
            "GGUF metadata says this is a native ComfyUI-GGUF UNet. "
            "Auto mode should use --comfyui-url, not Diffusers direct load. "
            "Pass --allow-comfy-native-diffusers only if you intentionally want to prove direct Diffusers fails."
        )
    t0 = time.perf_counter()
    import torch
    from diffusers import GGUFQuantizationConfig, StableDiffusionXLPipeline, UNet2DConditionModel

    timings["import_seconds"] = round(time.perf_counter() - t0, 3)
    device, dtype = resolve_device_and_dtype(torch, args)
    quantization_config = GGUFQuantizationConfig(compute_dtype=dtype)
    t1 = time.perf_counter()
    unet = UNet2DConditionModel.from_single_file(
        str(gguf_path),
        quantization_config=quantization_config,
        config=args.base_repo,
        subfolder="unet",
        torch_dtype=dtype,
    )
    timings["gguf_unet_load_seconds"] = round(time.perf_counter() - t1, 3)
    pipe_kwargs = {"torch_dtype": dtype, "unet": unet}
    if token:
        pipe_kwargs["token"] = token
    if args.local_files_only:
        pipe_kwargs["local_files_only"] = True
    t2 = time.perf_counter()
    try:
        pipe = StableDiffusionXLPipeline.from_pretrained(args.base_repo, **pipe_kwargs)
    except TypeError:
        if token and "token" in pipe_kwargs:
            pipe_kwargs["use_auth_token"] = pipe_kwargs.pop("token")
        pipe = StableDiffusionXLPipeline.from_pretrained(args.base_repo, **pipe_kwargs)
    timings["base_pipeline_load_seconds"] = round(time.perf_counter() - t2, 3)
    t3 = time.perf_counter()
    pipe.to(device)
    timings["move_to_device_seconds"] = round(time.perf_counter() - t3, 3)
    if hasattr(pipe, "set_progress_bar_config"):
        pipe.set_progress_bar_config(disable=False)
    generator_device = "cuda" if device == "cuda" and torch.cuda.is_available() else "cpu"
    generator = torch.Generator(device=generator_device)
    generator.manual_seed(int(args.seed))
    if torch.cuda.is_available():
        torch.cuda.reset_peak_memory_stats()
    t4 = time.perf_counter()
    result = pipe(
        prompt=args.prompt,
        negative_prompt=args.negative_prompt,
        width=int(args.width),
        height=int(args.height),
        num_inference_steps=int(args.steps),
        guidance_scale=float(args.cfg),
        generator=generator,
    )
    timings["generate_seconds"] = round(time.perf_counter() - t4, 3)
    images = list(getattr(result, "images", []) or [])
    if not images:
        raise ProbeError("Diffusers GGUF returned no images")
    images[0].save(out_png)
    output = {
        "path": str(out_png),
        "size_bytes": out_png.stat().st_size,
        "width": getattr(images[0], "width", None),
        "height": getattr(images[0], "height", None),
        "device": device,
        "dtype": str(dtype).replace("torch.", ""),
        "cuda_available": bool(torch.cuda.is_available()),
        "cuda_device_name": torch.cuda.get_device_name(0) if torch.cuda.is_available() else "",
    }
    if torch.cuda.is_available():
        output.update({
            "cuda_peak_allocated_mb": round(torch.cuda.max_memory_allocated() / 1024 / 1024, 1),
            "cuda_peak_reserved_mb": round(torch.cuda.max_memory_reserved() / 1024 / 1024, 1),
        })
    return output


class ComfyClient:
    def __init__(self, base_url: str, *, insecure: bool = False, timeout: int = 60):
        self.base_url = str(base_url or "").rstrip("/")
        self.timeout = int(timeout or 60)
        handlers = []
        if self.base_url.startswith("https://"):
            context = ssl._create_unverified_context() if insecure else ssl.create_default_context()
            handlers.append(urllib.request.HTTPSHandler(context=context))
        self.opener = urllib.request.build_opener(*handlers)
        self.opener.addheaders = [("User-Agent", "hackme-standalone-gguf-probe/1.0")]

    def _url(self, path: str) -> str:
        return f"{self.base_url}{path if path.startswith('/') else '/' + path}"

    @staticmethod
    def _read_body(resp) -> bytes:
        try:
            return resp.read()
        except http.client.IncompleteRead as exc:
            return exc.partial or b""

    def json(self, path: str, *, method="GET", payload=None, timeout=None) -> dict:
        body = None
        headers = {}
        if payload is not None:
            headers["Content-Type"] = "application/json"
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(self._url(path), data=body, headers=headers, method=method)
        try:
            with self.opener.open(req, timeout=timeout or self.timeout) as resp:
                raw = self._read_body(resp)
        except urllib.error.HTTPError as exc:
            raw = self._read_body(exc)
            raise ProbeError(f"{method} {path} HTTP {exc.code}: {raw[:500]!r}") from exc
        try:
            data = json.loads(raw.decode("utf-8", errors="replace"))
        except Exception as exc:
            raise ProbeError(f"{method} {path} returned non-JSON") from exc
        return data if isinstance(data, dict) else {"raw": data}

    def bytes(self, path: str, *, timeout=None) -> bytes:
        req = urllib.request.Request(self._url(path), method="GET")
        with self.opener.open(req, timeout=timeout or self.timeout) as resp:
            return self._read_body(resp)


def comfy_options(object_info: dict, node_class: str, input_name: str) -> set[str] | None:
    node = object_info.get(node_class) if isinstance(object_info, dict) else None
    required = ((node or {}).get("input") or {}).get("required") or {}
    raw = required.get(input_name)
    if isinstance(raw, list) and raw:
        if isinstance(raw[0], list):
            return {str(item) for item in raw[0] if str(item).strip()}
        if len(raw) > 1 and isinstance(raw[1], dict) and isinstance(raw[1].get("options"), list):
            return {str(item) for item in raw[1]["options"] if str(item).strip()}
    return None


def resolve_comfy_option(value: str, options: set[str] | None, *, label: str) -> str:
    requested = str(value or "").strip()
    if not requested:
        raise ProbeError(f"{label} is required")
    if options is None or requested in options:
        return requested
    requested_name = Path(requested.replace("\\", "/")).name
    matches = [item for item in options if Path(str(item).replace("\\", "/")).name == requested_name]
    if matches:
        return matches[0]
    preview = ", ".join(sorted(options)[:8])
    raise ProbeError(f"{label} not available in ComfyUI: {requested}. Available examples: {preview}")


def maybe_install_gguf_to_comfyui(gguf_path: Path, target_dir: str, model_name: str) -> dict:
    return maybe_install_file_to_dir(gguf_path, target_dir, model_name)


def maybe_install_file_to_dir(source_path: Path, target_dir: str, model_name: str) -> dict:
    if not target_dir:
        return {"installed": False, "reason": "no install dir provided"}
    target_root = Path(target_dir).expanduser().resolve()
    target_root.mkdir(parents=True, exist_ok=True)
    destination = target_root / Path(model_name.replace("\\", "/")).name
    if destination.exists() and destination.stat().st_size == source_path.stat().st_size:
        return {"installed": False, "cache_hit": True, "path": str(destination), "size_bytes": destination.stat().st_size}
    shutil.copy2(source_path, destination)
    return {"installed": True, "path": str(destination), "size_bytes": destination.stat().st_size}


def maybe_install_aux_models(args, token: str, timings: dict) -> dict:
    aux_repo = str(args.aux_repo or "").strip()
    files = {
        "clip_l": str(args.aux_clip_l or "").strip(),
        "clip_g": str(args.aux_clip_g or "").strip(),
        "vae": str(args.aux_vae or "").strip(),
    }
    if not aux_repo or not any(files.values()):
        return {"enabled": False, "reason": "no aux repo/files configured"}

    installed = {"enabled": True, "repo": aux_repo, "files": {}}
    started = time.perf_counter()
    for key, filename in files.items():
        if not filename:
            continue
        path = download_hf_file(aux_repo, filename, token, local_files_only=args.local_files_only)
        target_dir = (
            args.install_to_comfyui_vae_dir
            if key == "vae"
            else args.install_to_comfyui_text_encoder_dir
        )
        install = maybe_install_file_to_dir(path, target_dir, filename)
        installed["files"][key] = {
            "filename": filename,
            "cache_path": str(path),
            "size_bytes": path.stat().st_size,
            "install": install,
        }
    timings["aux_download_or_cache_seconds"] = round(time.perf_counter() - started, 3)
    return installed


def build_comfyui_gguf_workflow(args, *, unet_name: str, clip_l: str, clip_g: str, vae_name: str, clip_loader_class: str) -> dict:
    return {
        "3": {
            "class_type": "KSampler",
            "inputs": {
                "cfg": float(args.cfg),
                "denoise": 1,
                "latent_image": ["5", 0],
                "model": ["4", 0],
                "negative": ["7", 0],
                "positive": ["6", 0],
                "sampler_name": args.sampler,
                "scheduler": args.scheduler,
                "seed": int(args.seed),
                "steps": int(args.steps),
            },
        },
        "4": {"class_type": "UnetLoaderGGUF", "inputs": {"unet_name": unet_name}},
        "5": {
            "class_type": "EmptyLatentImage",
            "inputs": {"batch_size": 1, "height": int(args.height), "width": int(args.width)},
        },
        "6": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["10", 0], "text": args.prompt}},
        "7": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["10", 0], "text": args.negative_prompt}},
        "8": {"class_type": "VAEDecode", "inputs": {"samples": ["3", 0], "vae": ["11", 0]}},
        "9": {"class_type": "SaveImage", "inputs": {"filename_prefix": args.filename_prefix, "images": ["8", 0]}},
        "10": {"class_type": clip_loader_class, "inputs": {"clip_name1": clip_l, "clip_name2": clip_g, "type": "sdxl"}},
        "11": {"class_type": "VAELoader", "inputs": {"vae_name": vae_name}},
    }
    if clip_loader_class == "DualCLIPLoader":
        workflow["10"]["inputs"]["device"] = "default"
    return workflow


def run_comfyui_gguf(args, token: str, gguf_path: Path, out_png: Path, timings: dict) -> dict:
    if not args.comfyui_url:
        raise ProbeError("ComfyUI-GGUF backend requires --comfyui-url")
    client = ComfyClient(args.comfyui_url, insecure=args.insecure, timeout=args.request_timeout)
    model_name = args.comfyui_model_name or Path(args.gguf_file or gguf_path.name).name
    install = maybe_install_gguf_to_comfyui(gguf_path, args.install_to_comfyui_unet_dir, model_name)
    aux_install = maybe_install_aux_models(args, token, timings)
    t0 = time.perf_counter()
    object_info = client.json("/object_info", timeout=args.request_timeout)
    timings["comfyui_object_info_seconds"] = round(time.perf_counter() - t0, 3)
    if "UnetLoaderGGUF" not in object_info:
        raise ProbeError("ComfyUI does not expose UnetLoaderGGUF; install/enable ComfyUI-GGUF on that machine")
    clip_loader_class = str(args.clip_loader_class or "DualCLIPLoader").strip()
    if clip_loader_class not in object_info:
        raise ProbeError(f"ComfyUI does not expose {clip_loader_class}; install/enable the expected CLIP loader")
    unet_name = resolve_comfy_option(
        model_name,
        comfy_options(object_info, "UnetLoaderGGUF", "unet_name"),
        label="GGUF UNet",
    )
    clip_l = resolve_comfy_option(args.clip_l, comfy_options(object_info, clip_loader_class, "clip_name1"), label="CLIP-L")
    clip_g = resolve_comfy_option(args.clip_g, comfy_options(object_info, clip_loader_class, "clip_name2"), label="CLIP-G")
    vae_name = resolve_comfy_option(args.vae, comfy_options(object_info, "VAELoader", "vae_name"), label="VAE")
    workflow = build_comfyui_gguf_workflow(
        args,
        unet_name=unet_name,
        clip_l=clip_l,
        clip_g=clip_g,
        vae_name=vae_name,
        clip_loader_class=clip_loader_class,
    )
    client_id = uuid.uuid4().hex
    t1 = time.perf_counter()
    prompt = client.json("/prompt", method="POST", payload={"prompt": workflow, "client_id": client_id}, timeout=args.request_timeout)
    timings["comfyui_prompt_submit_seconds"] = round(time.perf_counter() - t1, 3)
    prompt_id = str(prompt.get("prompt_id") or "").strip()
    if not prompt_id:
        raise ProbeError(f"ComfyUI did not return prompt_id: {prompt}")
    started = time.perf_counter()
    last_history = {}
    while time.perf_counter() - started <= int(args.max_seconds):
        history = client.json(f"/history/{urllib.parse.quote(prompt_id)}", timeout=args.request_timeout)
        last_history = history
        item = history.get(prompt_id) if isinstance(history.get(prompt_id), dict) else None
        if item:
            outputs = item.get("outputs") if isinstance(item.get("outputs"), dict) else {}
            for output in outputs.values():
                images = output.get("images") if isinstance(output, dict) and isinstance(output.get("images"), list) else []
                if not images:
                    continue
                image = images[0]
                query = urllib.parse.urlencode({
                    "filename": image.get("filename") or "",
                    "subfolder": image.get("subfolder") or "",
                    "type": image.get("type") or "output",
                })
                data = client.bytes(f"/view?{query}", timeout=args.request_timeout)
                out_png.write_bytes(data)
                timings["comfyui_total_seconds"] = round(time.perf_counter() - started, 3)
                return {
                    "path": str(out_png),
                    "size_bytes": out_png.stat().st_size,
                    "prompt_id": prompt_id,
                    "comfyui_url": args.comfyui_url,
                    "selected_models": {
                        "unet_name": unet_name,
                        "clip_loader_class": clip_loader_class,
                        "clip_l": clip_l,
                        "clip_g": clip_g,
                        "vae": vae_name,
                    },
                    "install": install,
                    "aux_install": aux_install,
                }
        time.sleep(max(0.5, float(args.poll_seconds)))
    raise ProbeError(f"timeout waiting for ComfyUI prompt {prompt_id}; last_history={str(last_history)[:500]}")


def parse_args():
    parser = argparse.ArgumentParser(
        description=(
            "Download/inspect a HF GGUF and run txt2img through Diffusers or ComfyUI-GGUF. "
            "Install deps with: pip install torch diffusers transformers accelerate safetensors "
            "huggingface-hub gguf pillow psutil pynvml"
        )
    )
    parser.add_argument("--config", default="", help="Shared JSON config for regular/HF/GGUF probes.")
    parser.add_argument("--gguf-profile", default="", help="Official GGUF profile id from the shared config gguf_profiles map.")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--gguf-file", default="")
    parser.add_argument("--base-repo", default=DEFAULT_BASE_REPO)
    parser.add_argument("--backend", choices=["auto", "inspect", "diffusers", "comfyui"], default="auto")
    parser.add_argument("--allow-comfy-native-diffusers", action="store_true")
    parser.add_argument("--prompt", default=DEFAULT_PROMPT)
    parser.add_argument("--negative-prompt", default=DEFAULT_NEGATIVE)
    parser.add_argument("--width", type=int, default=1920)
    parser.add_argument("--height", type=int, default=1080)
    parser.add_argument("--steps", type=int, default=24)
    parser.add_argument("--cfg", type=float, default=5.0)
    parser.add_argument("--seed", type=int, default=20260529)
    parser.add_argument("--device", default="auto", help="Diffusers direct mode only.")
    parser.add_argument("--dtype", default="auto", help="Diffusers direct mode only.")
    parser.add_argument("--local-files-only", action="store_true")
    parser.add_argument("--hf-cache-root", default=default_cache_root())
    parser.add_argument("--hf-token-env", default="HF_TOKEN")
    parser.add_argument("--hf-token-file", default="")
    parser.add_argument("--hf-token-stdin", action="store_true")
    parser.add_argument("--disable-xet", type=parse_bool, default=True)
    parser.add_argument("--comfyui-url", default="")
    parser.add_argument("--insecure", action="store_true")
    parser.add_argument("--install-to-comfyui-unet-dir", default="", help="Local ComfyUI models/unet or diffusion_models dir.")
    parser.add_argument("--install-to-comfyui-text-encoder-dir", default="", help="Local ComfyUI models/text_encoders or models/clip dir.")
    parser.add_argument("--install-to-comfyui-vae-dir", default="", help="Local ComfyUI models/vae dir.")
    parser.add_argument("--comfyui-model-name", default="", help="Name ComfyUI should list for the GGUF. Defaults to the file basename.")
    parser.add_argument("--aux-repo", default="", help="HF repo for model-card-required CLIP/VAE companion files.")
    parser.add_argument("--aux-clip-l", default="", help="Companion CLIP-L filename to download/install before ComfyUI generation.")
    parser.add_argument("--aux-clip-g", default="", help="Companion CLIP-G filename to download/install before ComfyUI generation.")
    parser.add_argument("--aux-vae", default="", help="Companion VAE filename to download/install before ComfyUI generation.")
    parser.add_argument("--clip-loader-class", default="DualCLIPLoader", help="ComfyUI CLIP loader class, e.g. DualCLIPLoader or DualCLIPLoaderGGUF.")
    parser.add_argument("--clip-l", default="clip_l.safetensors")
    parser.add_argument("--clip-g", default="clip_g.safetensors")
    parser.add_argument("--vae", default="sdxl_vae.safetensors")
    parser.add_argument("--sampler", default="euler")
    parser.add_argument("--scheduler", default="normal")
    parser.add_argument("--filename-prefix", default="hackme_standalone_gguf")
    parser.add_argument("--request-timeout", type=int, default=60)
    parser.add_argument("--max-seconds", type=int, default=1800)
    parser.add_argument("--poll-seconds", type=float, default=3)
    parser.add_argument("--sample-interval", type=float, default=1.0)
    parser.add_argument("--out-dir", default="/tmp/hackme_gguf_standalone")
    parser.add_argument("--out-json", default="")
    parser.add_argument("--preflight-only", action="store_true", help="Download and inspect only; do not generate.")
    args = parser.parse_args()
    return normalize_runtime_paths(apply_config(args, parser))


def main() -> int:
    args = parse_args()
    out_dir = Path(args.out_dir).expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    out_json = Path(args.out_json or (out_dir / "gguf_standalone_report.json")).expanduser().resolve()
    out_png = out_dir / "gguf.png"
    token = read_token(args)
    hf_env = configure_hf_env(args.hf_cache_root, disable_xet=bool(args.disable_xet))
    started = time.time()
    timings = {}
    report = {
        "ok": False,
        "label": "standalone_gguf_txt2img",
        "started_at": now_iso(),
        "config": getattr(args, "config_loaded", ""),
        "gguf_profile": str(getattr(args, "gguf_profile", "") or ""),
        "model": args.model,
        "requested_gguf_file": args.gguf_file,
        "backend_requested": args.backend,
        "base_repo": args.base_repo,
        "dimensions": {"width": args.width, "height": args.height, "steps": args.steps, "cfg": args.cfg},
        "hf_env": hf_env,
        "hf_token_supplied": bool(token),
        "cache_before": cache_report(args.hf_cache_root, args.model),
        "versions": module_versions(),
        "artifacts": {"out_dir": str(out_dir), "report": str(out_json), "image": str(out_png)},
    }
    try:
        with ResourceMonitor(args.sample_interval) as monitor:
            t0 = time.perf_counter()
            files = list_gguf_files(args.model, token)
            timings["hf_list_repo_seconds"] = round(time.perf_counter() - t0, 3)
            selected_file = select_gguf_file(files, args.gguf_file)
            args.gguf_file = selected_file
            report["gguf_files"] = files[:30]
            report["selected_gguf_file"] = selected_file
            t1 = time.perf_counter()
            gguf_path = download_gguf(args.model, selected_file, token, local_files_only=args.local_files_only)
            timings["gguf_download_or_cache_seconds"] = round(time.perf_counter() - t1, 3)
            report["gguf_path"] = str(gguf_path)
            report["gguf_size_bytes"] = gguf_path.stat().st_size
            t2 = time.perf_counter()
            metadata = inspect_gguf(gguf_path)
            timings["gguf_metadata_seconds"] = round(time.perf_counter() - t2, 3)
            report["metadata"] = metadata
            if args.preflight_only or args.backend == "inspect":
                report["ok"] = True
                report["preflight_only"] = True
            else:
                selected_backend = args.backend
                if selected_backend == "auto":
                    selected_backend = "comfyui" if metadata.get("suggested_backend") == "comfyui_gguf" else "diffusers"
                report["backend_selected"] = selected_backend
                if selected_backend == "comfyui":
                    report["output"] = run_comfyui_gguf(args, token, gguf_path, out_png, timings)
                elif selected_backend == "diffusers":
                    report["output"] = run_diffusers_gguf(args, token, gguf_path, metadata, out_png, timings)
                else:
                    raise ProbeError(f"unsupported selected backend: {selected_backend}")
                report["ok"] = True
            report["resources"] = monitor.summary(started)
        return_code = 0 if report.get("ok") else 1
    except Exception as exc:
        report["ok"] = False
        report["error"] = sanitize_text(exc)
        report["traceback"] = sanitize_text(traceback.format_exc(limit=8))
        return_code = 1
    finally:
        report["timings"] = timings
        report["cache_after"] = cache_report(args.hf_cache_root, args.model)
        report["finished_at"] = now_iso()
        out_json.parent.mkdir(parents=True, exist_ok=True)
        out_json.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
        print(json.dumps({
            "ok": report.get("ok"),
            "backend_selected": report.get("backend_selected"),
            "selected_gguf_file": report.get("selected_gguf_file"),
            "suggested_backend": (report.get("metadata") or {}).get("suggested_backend"),
            "image": report.get("output", {}).get("path"),
            "out_json": str(out_json),
            "error": report.get("error"),
            "timings": report.get("timings"),
            "resources": report.get("resources", {}).get("peaks"),
            "cache_after": report.get("cache_after"),
        }, ensure_ascii=False, indent=2))
    return return_code


if __name__ == "__main__":
    raise SystemExit(main())
