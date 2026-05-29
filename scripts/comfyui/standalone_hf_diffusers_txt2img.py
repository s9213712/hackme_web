#!/usr/bin/env python3
"""Standalone Hugging Face Diffusers txt2img probe.

This script intentionally does not call hackme_web.  It is meant to be copied
to another machine to verify whether a model can load and generate there using
plain Diffusers, while recording cache placement and resource usage.
"""

from __future__ import annotations

import argparse
import html
import json
import os
import platform
import re
import sys
import threading
import time
import traceback
from pathlib import Path, PurePosixPath
from urllib import request as urllib_request


DEFAULT_MODEL = "dhead/wai-nsfw-illustrious-sdxl-v140-sdxl"
DEFAULT_PROMPT = (
    "adult women, fully clothed, by ogipote, 2girls, girls love, kiss, "
    "saliva, maid uniform, cat ears, cat tail"
)
DEFAULT_NEGATIVE = (
    "child, minor, underage, loli, teen, nude, naked, explicit, low quality, "
    "blurry, watermark, distorted, bad anatomy"
)
SENSITIVE_RE = re.compile(r"hf_[A-Za-z0-9]{8,}|(Bearer\s+)[A-Za-z0-9._-]+", re.IGNORECASE)
FROM_PRETRAINED_RE = re.compile(
    r"(?P<class>[A-Za-z_][A-Za-z0-9_]*Pipeline)\.from_pretrained\(\s*"
    r"(?P<quote>['\"])(?P<repo>[^'\"]+)(?P=quote)(?P<args>.*?)\)",
    re.DOTALL,
)


class ProbeError(RuntimeError):
    pass


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def sanitize_text(value) -> str:
    text = str(value or "")
    return SENSITIVE_RE.sub(lambda match: (match.group(1) or "") + "***" if match.group(1) else "hf_***", text)


def _ask_text(label: str, current):
    shown = str(current or "")
    value = input(f"{label} [{shown}]: ").strip()
    return value or current


def _ask_choice(label: str, current: str, choices: tuple[str, ...]) -> str:
    allowed = ", ".join(choices)
    while True:
        value = input(f"{label} ({allowed}) [{current}]: ").strip()
        if not value:
            return current
        if value in choices:
            return value
        print(f"Enter one of: {allowed}", file=sys.stderr)


def _ask_int(label: str, current: int) -> int:
    while True:
        value = input(f"{label} [{current}]: ").strip()
        if not value:
            return int(current)
        try:
            return int(value)
        except ValueError:
            print("Enter an integer.", file=sys.stderr)


def _ask_float(label: str, current: float) -> float:
    while True:
        value = input(f"{label} [{current}]: ").strip()
        if not value:
            return float(current)
        try:
            return float(value)
        except ValueError:
            print("Enter a number.", file=sys.stderr)


def apply_interactive_prompts(args):
    if not getattr(args, "interactive", False):
        return args
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        raise ProbeError("--interactive requires a TTY; omit it for non-interactive CLI runs.")
    print("Interactive HF Diffusers txt2img probe. Press Enter to keep the shown value.")
    args.model = _ask_text("HF Diffusers repo id", args.model)
    args.variant = _ask_text("Variant", args.variant)
    args.prompt = _ask_text("Positive prompt", args.prompt)
    args.negative_prompt = _ask_text("Negative prompt", args.negative_prompt)
    args.width = _ask_int("Width", args.width)
    args.height = _ask_int("Height", args.height)
    args.steps = _ask_int("Steps", args.steps)
    args.cfg = _ask_float("CFG", args.cfg)
    args.seed = _ask_int("Seed", args.seed)
    args.device = _ask_text("Device", args.device)
    args.dtype = _ask_text("Dtype", args.dtype)
    args.device_map = _ask_text("Device map", args.device_map)
    args.pipeline_loader = _ask_choice("Pipeline loader", args.pipeline_loader, ("auto", "diffusion"))
    args.model_card_hints = _ask_choice("Model-card hints", args.model_card_hints, ("auto", "off", "force"))
    args.hf_cache_root = _ask_text("HF cache root", args.hf_cache_root)
    args.hf_token_env = _ask_text("HF token environment variable", args.hf_token_env)
    args.hf_token_file = _ask_text("HF token file path (blank for env/stdin)", args.hf_token_file)
    args.out_dir = _ask_text("Output directory", args.out_dir)
    explicit = set(getattr(args, "_explicit_cli_dests", []) or [])
    explicit.update({
        "model",
        "variant",
        "prompt",
        "negative_prompt",
        "width",
        "height",
        "steps",
        "cfg",
        "seed",
        "device",
        "dtype",
        "device_map",
        "pipeline_loader",
        "model_card_hints",
        "hf_cache_root",
        "hf_token_env",
        "hf_token_file",
        "out_dir",
    })
    args._explicit_cli_dests = sorted(explicit)
    return args


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


def _arg_value(call_args: str, name: str) -> str:
    match = re.search(rf"\b{re.escape(name)}\s*=\s*(?P<value>\"[^\"]*\"|'[^']*'|[^,\n)]+)", call_args or "")
    return match.group("value").strip() if match else ""


def _string_literal_value(value: str) -> str:
    raw = str(value or "").strip()
    if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in {"'", '"'}:
        return raw[1:-1]
    return ""


def _bool_literal_value(value: str):
    raw = str(value or "").strip().lower()
    if raw == "true":
        return True
    if raw == "false":
        return False
    return None


def _dtype_hint(value: str) -> str:
    lowered = str(value or "").lower()
    if "bfloat16" in lowered or "bf16" in lowered:
        return "bfloat16"
    if "float16" in lowered or "fp16" in lowered or "torch.half" in lowered:
        return "float16"
    if "float32" in lowered or "fp32" in lowered:
        return "float32"
    return ""


def parse_model_card_diffusers_hints(card_text: str, repo_id: str) -> dict:
    hints = {}
    for match in FROM_PRETRAINED_RE.finditer(card_text or ""):
        if match.group("repo") != repo_id:
            continue
        class_name = match.group("class")
        call_args = match.group("args") or ""
        if class_name == "DiffusionPipeline":
            hints["pipeline_loader"] = "diffusion"
        elif class_name == "AutoPipelineForText2Image":
            hints["pipeline_loader"] = "auto"
        for dtype_kwarg in ("dtype", "torch_dtype"):
            dtype = _dtype_hint(_arg_value(call_args, dtype_kwarg))
            if dtype:
                hints["dtype"] = dtype
                hints["dtype_kwarg"] = dtype_kwarg
                break
        for name in ("device_map", "variant", "revision", "subfolder", "custom_pipeline"):
            value = _string_literal_value(_arg_value(call_args, name))
            if value:
                hints[name] = value
        trust_remote_code = _bool_literal_value(_arg_value(call_args, "trust_remote_code"))
        if trust_remote_code is not None:
            hints["trust_remote_code"] = trust_remote_code
        if hints:
            hints["source"] = "model_card"
            hints["class_name"] = class_name
            break
    return hints


def load_model_card_hints(args, token: str) -> dict:
    if str(getattr(args, "model_card_hints", "auto") or "auto").strip().lower() == "off":
        return {}
    errors = []
    try:
        from huggingface_hub import hf_hub_download

        path = hf_hub_download(
            repo_id=args.model,
            filename="README.md",
            repo_type="model",
            token=(token or None),
            local_files_only=bool(args.local_files_only),
        )
        card_text = Path(path).read_text(encoding="utf-8", errors="replace")
        hints = parse_model_card_diffusers_hints(card_text, args.model)
        if hints:
            return hints
    except Exception as exc:
        errors.append(sanitize_text(exc))
    try:
        url = f"https://huggingface.co/{args.model}"
        headers = {"User-Agent": "hackme-hf-diffusers-probe/1.0"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        req = urllib_request.Request(url, headers=headers)
        with urllib_request.urlopen(req, timeout=20) as response:
            page_text = response.read().decode("utf-8", errors="replace")
        hints = parse_model_card_diffusers_hints(html.unescape(page_text), args.model)
        if hints:
            hints["source"] = "model_page"
            return hints
    except Exception as exc:
        errors.append(sanitize_text(exc))
    payload = {"source": "model_card", "found": False}
    if errors:
        payload["errors"] = errors[-3:]
    return payload


def apply_model_card_hints(args, hints: dict):
    if not isinstance(hints, dict) or hints.get("error") or hints.get("found") is False:
        return args
    mode = str(getattr(args, "model_card_hints", "auto") or "auto").strip().lower()
    explicit = set(getattr(args, "_explicit_cli_dests", []) or [])
    force = mode == "force"

    def maybe_set(dest: str, value):
        if value in (None, ""):
            return
        if force or dest not in explicit:
            setattr(args, dest, value)

    maybe_set("dtype", hints.get("dtype"))
    maybe_set("dtype_kwarg", hints.get("dtype_kwarg"))
    maybe_set("device_map", hints.get("device_map"))
    maybe_set("pipeline_loader", hints.get("pipeline_loader"))
    maybe_set("variant", hints.get("variant"))
    maybe_set("revision", hints.get("revision"))
    maybe_set("subfolder", hints.get("subfolder"))
    maybe_set("custom_pipeline", hints.get("custom_pipeline"))
    if "trust_remote_code" in hints and (force or "trust_remote_code" not in explicit):
        args.trust_remote_code = bool(hints.get("trust_remote_code"))
    return args


def inspect_diffusers_repo_layout(args, token: str) -> dict:
    try:
        from huggingface_hub import HfApi, hf_hub_download

        info = HfApi().model_info(args.model, token=(token or None), files_metadata=False)
        sibling_names = [str(getattr(item, "rfilename", "") or getattr(item, "filename", "") or "") for item in (getattr(info, "siblings", []) or [])]
    except Exception as exc:
        return {"ok": False, "error": sanitize_text(exc)}
    has_model_index = any(PurePosixPath(name).name == "model_index.json" for name in sibling_names)
    has_modular_model_index = any(PurePosixPath(name).name == "modular_model_index.json" for name in sibling_names)
    layout = {
        "ok": True,
        "has_model_index": has_model_index,
        "has_modular_model_index": has_modular_model_index,
        "requires_modular_pipeline": bool(has_modular_model_index and not has_model_index),
    }
    if not layout["requires_modular_pipeline"]:
        return layout
    try:
        path = hf_hub_download(
            repo_id=args.model,
            filename="modular_model_index.json",
            repo_type="model",
            token=(token or None),
            local_files_only=bool(args.local_files_only),
        )
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        layout["required_diffusers_version"] = str(data.get("_diffusers_version") or "")
        layout["modular_class_name"] = str(data.get("_class_name") or "")
        missing = []
        for name, value in data.items():
            if not isinstance(value, list) or len(value) < 2:
                continue
            library_name, class_name = str(value[0] or ""), str(value[1] or "")
            if library_name not in {"diffusers", "transformers"} or not class_name:
                continue
            try:
                module = __import__(library_name)
                if not hasattr(module, class_name):
                    missing.append(f"{library_name}.{class_name}")
            except Exception:
                missing.append(f"{library_name}.{class_name}")
        layout["missing_runtime_classes"] = missing
    except Exception as exc:
        layout["modular_inspect_error"] = sanitize_text(exc)
    return layout


def _config_sections(config: dict, section_names: tuple[str, ...]) -> dict:
    reserved = {"common", *section_names, "regular_comfyui", "hf_diffusers", "gguf"}
    merged = {key: value for key, value in config.items() if key not in reserved and not isinstance(value, dict)}
    common = config.get("common")
    if isinstance(common, dict):
        merged.update(common)
    for section_name in section_names:
        section = config.get(section_name)
        if isinstance(section, dict):
            merged.update(section)
    return merged


def apply_config(args, parser: argparse.ArgumentParser, *, section_names=("hf_diffusers",), argv=None):
    config_path = str(getattr(args, "config", "") or "").strip()
    args.config_loaded = ""
    if not config_path:
        return args
    path = Path(config_path).expanduser().resolve()
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ProbeError("--config must point to a JSON object")
    config = _config_sections(raw, tuple(section_names))
    explicit = _explicit_cli_dests(parser, list(argv or sys.argv[1:]))
    aliases = {
        "negative_prompt": ("negative",),
        "hf_cache_root": ("cache_root", "huggingface_cache_root"),
        "sample_interval": ("resource_sample_interval",),
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
        for candidate in ("D:/tmp/hackme_hf_cache", str(Path.home() / ".cache" / "huggingface")):
            try:
                if Path(candidate).parent.exists():
                    return candidate
            except OSError:
                continue
        return str(Path.home() / ".cache" / "huggingface")
    return str(Path.home() / ".cache" / "huggingface")


def resolve_existing_path(value: str) -> Path | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        path = Path(raw).expanduser()
        if path.exists():
            return path.resolve()
    except OSError:
        return None
    return None


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
    for name in ("hf_cache_root", "out_dir", "out_json", "hf_token_file"):
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
    for module_name in ("torch", "diffusers", "transformers", "accelerate", "huggingface_hub"):
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
        self._thread = threading.Thread(target=self._loop, name="hf-resource-monitor", daemon=True)
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
                if sys.platform == "darwin":
                    rss_mb = rss_kb / 1024 / 1024
                else:
                    rss_mb = rss_kb / 1024
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


def load_pipeline(args, token: str, timings: dict):
    t0 = time.perf_counter()
    import torch
    from diffusers import AutoPipelineForText2Image, DiffusionPipeline

    timings["import_seconds"] = round(time.perf_counter() - t0, 3)
    device, dtype = resolve_device_and_dtype(torch, args)
    device_map = str(args.device_map or "disabled").strip().lower()
    if device_map in {"none", "off", "false"}:
        device_map = "disabled"
    pipeline_loader = str(getattr(args, "pipeline_loader", "") or "auto").strip().lower()
    if pipeline_loader not in {"auto", "diffusion"}:
        raise ProbeError(f"unsupported pipeline loader: {args.pipeline_loader}")
    pipeline_cls = DiffusionPipeline if pipeline_loader == "diffusion" else AutoPipelineForText2Image
    dtype_kwarg = str(getattr(args, "dtype_kwarg", "") or "torch_dtype").strip()
    if dtype_kwarg not in {"torch_dtype", "dtype"}:
        raise ProbeError(f"unsupported dtype kwarg: {args.dtype_kwarg}")
    kwargs = {"use_safetensors": True, dtype_kwarg: dtype}
    if args.variant:
        kwargs["variant"] = args.variant
    if getattr(args, "revision", ""):
        kwargs["revision"] = args.revision
    if getattr(args, "subfolder", ""):
        kwargs["subfolder"] = args.subfolder
    if getattr(args, "custom_pipeline", ""):
        kwargs["custom_pipeline"] = args.custom_pipeline
    if bool(getattr(args, "trust_remote_code", False)):
        kwargs["trust_remote_code"] = True
    if token:
        kwargs["token"] = token
    if args.local_files_only:
        kwargs["local_files_only"] = True
    if device_map != "disabled":
        kwargs["device_map"] = device_map
    if parse_bool(args.low_cpu_mem_usage):
        kwargs["low_cpu_mem_usage"] = True

    t1 = time.perf_counter()
    try:
        pipe = pipeline_cls.from_pretrained(args.model, **kwargs)
    except TypeError:
        if token and "token" in kwargs:
            kwargs["use_auth_token"] = kwargs.pop("token")
        pipe = pipeline_cls.from_pretrained(args.model, **kwargs)
    timings["pipeline_load_seconds"] = round(time.perf_counter() - t1, 3)

    moved = False
    if device_map == "disabled" and not getattr(pipe, "hf_device_map", None):
        t2 = time.perf_counter()
        pipe.to(device)
        timings["move_to_device_seconds"] = round(time.perf_counter() - t2, 3)
        moved = True
    if hasattr(pipe, "set_progress_bar_config"):
        pipe.set_progress_bar_config(disable=False)
    if hasattr(pipe, "enable_attention_slicing"):
        try:
            pipe.enable_attention_slicing()
        except Exception:
            pass
    return pipe, torch, {
        "device": device,
        "dtype": str(dtype).replace("torch.", ""),
        "dtype_kwarg": dtype_kwarg,
        "device_map": device_map,
        "pipeline_loader": pipeline_loader,
        "revision": getattr(args, "revision", ""),
        "subfolder": getattr(args, "subfolder", ""),
        "custom_pipeline": getattr(args, "custom_pipeline", ""),
        "trust_remote_code": bool(getattr(args, "trust_remote_code", False)),
        "pipeline_class": f"{pipe.__class__.__module__}.{pipe.__class__.__name__}",
        "manual_to_device": moved,
        "cuda_available": bool(torch.cuda.is_available()),
        "cuda_device_name": torch.cuda.get_device_name(0) if torch.cuda.is_available() else "",
    }


def generate_image(pipe, torch, args, runtime: dict, timings: dict):
    generator_device = "cuda" if runtime["device"] == "cuda" and torch.cuda.is_available() else "cpu"
    generator = torch.Generator(device=generator_device)
    generator.manual_seed(int(args.seed))
    call_kwargs = {
        "prompt": args.prompt,
        "negative_prompt": args.negative_prompt,
        "width": int(args.width),
        "height": int(args.height),
        "num_inference_steps": int(args.steps),
        "guidance_scale": float(args.cfg),
        "num_images_per_prompt": 1,
        "generator": generator,
    }
    if torch.cuda.is_available():
        torch.cuda.reset_peak_memory_stats()
    t0 = time.perf_counter()
    result = pipe(**call_kwargs)
    timings["generate_seconds"] = round(time.perf_counter() - t0, 3)
    cuda_peak = {}
    if torch.cuda.is_available():
        cuda_peak = {
            "cuda_peak_allocated_mb": round(torch.cuda.max_memory_allocated() / 1024 / 1024, 1),
            "cuda_peak_reserved_mb": round(torch.cuda.max_memory_reserved() / 1024 / 1024, 1),
        }
    images = list(getattr(result, "images", []) or [])
    if not images:
        raise ProbeError("Diffusers returned no images")
    return images[0], cuda_peak


def parse_args():
    parser = argparse.ArgumentParser(
        description=(
            "Run a standalone HF Diffusers txt2img generation without hackme_web. "
            "Install deps with: pip install torch diffusers transformers accelerate safetensors "
            "huggingface-hub pillow psutil pynvml"
        )
    )
    parser.add_argument("--interactive", action="store_true", help="Prompt for common options while keeping CLI defaults.")
    parser.add_argument("--config", default="", help="Shared JSON config for regular/HF/GGUF probes.")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--variant", default="fp16")
    parser.add_argument("--prompt", default=DEFAULT_PROMPT)
    parser.add_argument("--negative-prompt", default=DEFAULT_NEGATIVE)
    parser.add_argument("--width", type=int, default=1920)
    parser.add_argument("--height", type=int, default=1080)
    parser.add_argument("--steps", type=int, default=24)
    parser.add_argument("--cfg", type=float, default=5.0)
    parser.add_argument("--seed", type=int, default=20260528)
    parser.add_argument("--device", default="auto", help="auto, cuda, cpu, cuda:0, etc.")
    parser.add_argument("--dtype", default="auto", help="auto, float16, bfloat16, float32")
    parser.add_argument("--dtype-kwarg", choices=("torch_dtype", "dtype"), default="torch_dtype")
    parser.add_argument("--device-map", default="disabled", help="disabled, auto, balanced, sequential")
    parser.add_argument("--pipeline-loader", choices=("auto", "diffusion"), default="diffusion", help="diffusion uses DiffusionPipeline like HF snippets; auto uses AutoPipelineForText2Image.")
    parser.add_argument("--model-card-hints", choices=("auto", "off", "force"), default="auto", help="Read README Diffusers snippet and apply loader hints.")
    parser.add_argument("--revision", default="")
    parser.add_argument("--subfolder", default="")
    parser.add_argument("--custom-pipeline", default="")
    parser.add_argument("--trust-remote-code", action="store_true")
    parser.add_argument("--low-cpu-mem-usage", default="true")
    parser.add_argument("--local-files-only", action="store_true")
    parser.add_argument("--hf-cache-root", default=default_cache_root())
    parser.add_argument("--hf-token-env", default="HF_TOKEN")
    parser.add_argument("--hf-token-file", default="")
    parser.add_argument("--hf-token-stdin", action="store_true")
    parser.add_argument("--disable-xet", type=parse_bool, default=True)
    parser.add_argument("--sample-interval", type=float, default=1.0)
    parser.add_argument("--out-dir", default="/tmp/hackme_hf_diffusers_standalone")
    parser.add_argument("--out-json", default="")
    parser.add_argument("--preflight-only", action="store_true", help="Check imports/cache/token/env but do not load or generate.")
    argv = sys.argv[1:]
    args = parser.parse_args(argv)
    args._explicit_cli_dests = sorted(_explicit_cli_dests(parser, argv))
    args = apply_config(args, parser, argv=argv)
    args = apply_interactive_prompts(args)
    return normalize_runtime_paths(args)


def main() -> int:
    args = parse_args()
    out_dir = Path(args.out_dir).expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    output_json = Path(args.out_json or (out_dir / "hf_diffusers_standalone_report.json")).expanduser().resolve()
    output_png = out_dir / "hf_diffusers.png"
    token = read_token(args)
    hf_env = configure_hf_env(args.hf_cache_root, disable_xet=bool(args.disable_xet))
    model_card_hints = load_model_card_hints(args, token)
    args = apply_model_card_hints(args, model_card_hints)
    repo_layout = inspect_diffusers_repo_layout(args, token)
    started = time.time()
    timings = {}
    report = {
        "ok": False,
        "label": "standalone_hf_diffusers_txt2img",
        "started_at": now_iso(),
        "config": getattr(args, "config_loaded", ""),
        "model": args.model,
        "variant": args.variant,
        "dimensions": {"width": args.width, "height": args.height, "steps": args.steps, "cfg": args.cfg},
        "pipeline_loader": args.pipeline_loader,
        "model_card_hints": model_card_hints,
        "repo_layout": repo_layout,
        "dtype": args.dtype,
        "dtype_kwarg": args.dtype_kwarg,
        "device_map": args.device_map,
        "revision": args.revision,
        "subfolder": args.subfolder,
        "custom_pipeline": args.custom_pipeline,
        "trust_remote_code": bool(args.trust_remote_code),
        "prompt": args.prompt,
        "negative_prompt": args.negative_prompt,
        "hf_env": hf_env,
        "hf_token_supplied": bool(token),
        "cache_before": cache_report(args.hf_cache_root, args.model),
        "versions": module_versions(),
        "artifacts": {"out_dir": str(out_dir), "report": str(output_json), "image": str(output_png)},
    }
    try:
        if args.preflight_only:
            report["ok"] = True
            report["preflight_only"] = True
            return_code = 0
        else:
            if repo_layout.get("requires_modular_pipeline"):
                missing = ", ".join(repo_layout.get("missing_runtime_classes") or []) or "none reported"
                version = repo_layout.get("required_diffusers_version") or "unknown"
                raise ProbeError(
                    "Repo has modular_model_index.json but no model_index.json; "
                    "DiffusionPipeline.from_pretrained requires model_index.json. "
                    f"Use ModularPipeline support instead. Required diffusers={version}; missing_runtime_classes={missing}"
                )
            with ResourceMonitor(args.sample_interval) as monitor:
                pipe, torch, runtime = load_pipeline(args, token, timings)
                report["runtime"] = runtime
                image, cuda_peak = generate_image(pipe, torch, args, runtime, timings)
                t0 = time.perf_counter()
                image.save(output_png)
                timings["save_seconds"] = round(time.perf_counter() - t0, 3)
                report["output"] = {
                    "path": str(output_png),
                    "size_bytes": output_png.stat().st_size,
                    "mode": getattr(image, "mode", ""),
                    "width": getattr(image, "width", None),
                    "height": getattr(image, "height", None),
                    **cuda_peak,
                }
            report["resources"] = monitor.summary(started)
            report["ok"] = True
            return_code = 0
    except Exception as exc:
        report["ok"] = False
        report["error"] = sanitize_text(exc)
        report["traceback"] = sanitize_text(traceback.format_exc(limit=8))
        return_code = 1
    finally:
        report["timings"] = timings
        report["cache_after"] = cache_report(args.hf_cache_root, args.model)
        report["finished_at"] = now_iso()
        output_json.parent.mkdir(parents=True, exist_ok=True)
        output_json.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
        print(json.dumps({
            "ok": report.get("ok"),
            "image": report.get("output", {}).get("path"),
            "out_json": str(output_json),
            "error": report.get("error"),
            "timings": report.get("timings"),
            "resources": report.get("resources", {}).get("peaks"),
            "cache_after": report.get("cache_after"),
        }, ensure_ascii=False, indent=2))
    return return_code


if __name__ == "__main__":
    raise SystemExit(main())
