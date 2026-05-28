#!/usr/bin/env python3
"""Standalone regular ComfyUI txt2img probe.

This script talks directly to a ComfyUI HTTP API.  It does not import
hackme_web, so it can live on the ComfyUI server machine for offline retests.
"""

from __future__ import annotations

import argparse
import http.client
import json
import os
import re
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


DEFAULT_MODEL = "SDXL\\illustrious(IL)\\janxd系列\\JANKUTrainedChenkinNoobai_v777.safetensors"
DEFAULT_PROMPT = (
    "adult women, fully clothed, by ogipote, 2girls, girls love, kiss, "
    "saliva, maid uniform, cat ears, cat tail"
)
DEFAULT_NEGATIVE = (
    "child, minor, underage, loli, teen, nude, naked, explicit, low quality, "
    "blurry, watermark, distorted, bad anatomy"
)
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


def apply_config(args, parser: argparse.ArgumentParser, *, section_names=("regular_comfyui",), argv=None):
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
    for name in ("out_dir", "out_json"):
        if hasattr(args, name):
            setattr(args, name, windows_equivalent_path(getattr(args, name)))
    return args


class ResourceMonitor:
    def __init__(self, interval: float = 1.0):
        self.interval = max(0.2, float(interval or 1.0))
        self.samples = []
        self._stop = threading.Event()
        self._thread = None
        self._psutil = None
        self._pynvml = None
        self._nvml_handle = None
        try:
            import psutil  # type: ignore

            self._psutil = psutil
        except Exception:
            self._psutil = None
        try:
            import pynvml  # type: ignore

            pynvml.nvmlInit()
            self._pynvml = pynvml
            self._nvml_handle = pynvml.nvmlDeviceGetHandleByIndex(0)
        except Exception:
            self._pynvml = None
            self._nvml_handle = None

    def __enter__(self):
        self._thread = threading.Thread(target=self._loop, name="regular-comfyui-resource-monitor", daemon=True)
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
        if self._psutil:
            try:
                virt = self._psutil.virtual_memory()
                payload.update({
                    "cpu_percent": self._psutil.cpu_percent(interval=None),
                    "ram_used_percent": round(float(virt.percent), 1),
                    "ram_available_mb": round(int(virt.available) / 1024 / 1024, 1),
                })
            except Exception as exc:
                payload["psutil_error"] = str(exc)
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
        for key in ("cpu_percent", "ram_used_percent", "vram_used_mb", "gpu_util_percent"):
            values = [float(item[key]) for item in normalized if isinstance(item.get(key), (int, float))]
            if values:
                peak[f"peak_{key}"] = round(max(values), 2)
        return {"samples": normalized, "peaks": peak}


class ComfyClient:
    def __init__(self, base_url: str, *, insecure: bool = False, timeout: int = 60):
        self.base_url = str(base_url or "").rstrip("/")
        self.timeout = int(timeout or 60)
        handlers = []
        if self.base_url.startswith("https://"):
            context = ssl._create_unverified_context() if insecure else ssl.create_default_context()
            handlers.append(urllib.request.HTTPSHandler(context=context))
        self.opener = urllib.request.build_opener(*handlers)
        self.opener.addheaders = [("User-Agent", "hackme-standalone-regular-comfyui-probe/1.0")]

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


def node_options(object_info: dict, node_class: str, input_name: str) -> set[str] | None:
    node = object_info.get(node_class) if isinstance(object_info, dict) else None
    required = ((node or {}).get("input") or {}).get("required") or {}
    raw = required.get(input_name)
    if isinstance(raw, list) and raw:
        if isinstance(raw[0], list):
            return {str(item) for item in raw[0] if str(item).strip()}
        if len(raw) > 1 and isinstance(raw[1], dict) and isinstance(raw[1].get("options"), list):
            return {str(item) for item in raw[1]["options"] if str(item).strip()}
    return None


def resolve_model(requested: str, options: set[str] | None) -> str:
    requested = str(requested or "").strip()
    if not requested:
        raise ProbeError("--model is required")
    if options is None or requested in options:
        return requested
    requested_name = Path(requested.replace("\\", "/")).name
    matches = [item for item in options if Path(str(item).replace("\\", "/")).name == requested_name]
    if matches:
        return matches[0]
    preview = ", ".join(sorted(options)[:10])
    raise ProbeError(f"checkpoint is not available in ComfyUI: {requested}. Available examples: {preview}")


def build_workflow(args, *, model_name: str) -> dict:
    return {
        "1": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": model_name}},
        "2": {"class_type": "CLIPTextEncode", "inputs": {"text": args.prompt, "clip": ["1", 1]}},
        "3": {"class_type": "CLIPTextEncode", "inputs": {"text": args.negative_prompt, "clip": ["1", 1]}},
        "4": {
            "class_type": "EmptyLatentImage",
            "inputs": {"width": int(args.width), "height": int(args.height), "batch_size": 1},
        },
        "5": {
            "class_type": "KSampler",
            "inputs": {
                "model": ["1", 0],
                "positive": ["2", 0],
                "negative": ["3", 0],
                "latent_image": ["4", 0],
                "seed": int(args.seed),
                "steps": int(args.steps),
                "cfg": float(args.cfg),
                "sampler_name": args.sampler,
                "scheduler": args.scheduler,
                "denoise": 1,
            },
        },
        "6": {"class_type": "VAEDecode", "inputs": {"samples": ["5", 0], "vae": ["1", 2]}},
        "7": {
            "class_type": "SaveImage",
            "inputs": {"images": ["6", 0], "filename_prefix": args.filename_prefix},
        },
    }


def run_generation(client: ComfyClient, args, out_png: Path, timings: dict) -> dict:
    t0 = time.perf_counter()
    object_info = client.json("/object_info", timeout=args.request_timeout)
    timings["object_info_seconds"] = round(time.perf_counter() - t0, 3)
    if "CheckpointLoaderSimple" not in object_info:
        raise ProbeError("ComfyUI does not expose CheckpointLoaderSimple")
    options = node_options(object_info, "CheckpointLoaderSimple", "ckpt_name")
    model_name = resolve_model(args.model, options)
    preflight = {
        "checkpoint_loader_available": True,
        "model_requested": args.model,
        "model_resolved": model_name,
        "checkpoint_option_count": len(options or []),
    }
    if args.preflight_only:
        return {"preflight": preflight, "skipped_generation": True}
    workflow = build_workflow(args, model_name=model_name)
    client_id = uuid.uuid4().hex
    t1 = time.perf_counter()
    prompt = client.json("/prompt", method="POST", payload={"prompt": workflow, "client_id": client_id}, timeout=args.request_timeout)
    timings["prompt_submit_seconds"] = round(time.perf_counter() - t1, 3)
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
                    "preflight": preflight,
                    "prompt_id": prompt_id,
                    "path": str(out_png),
                    "size_bytes": out_png.stat().st_size,
                    "image_ref": image,
                }
        time.sleep(max(0.5, float(args.poll_seconds)))
    raise ProbeError(f"timeout waiting for ComfyUI prompt {prompt_id}; last_history={str(last_history)[:500]}")


def parse_args():
    parser = argparse.ArgumentParser(description="Run a standalone regular ComfyUI SDXL txt2img workflow.")
    parser.add_argument("--config", default="", help="Shared JSON config for regular/HF/GGUF probes.")
    parser.add_argument("--comfyui-url", default="http://127.0.0.1:8188")
    parser.add_argument("--insecure", action="store_true")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--prompt", default=DEFAULT_PROMPT)
    parser.add_argument("--negative-prompt", default=DEFAULT_NEGATIVE)
    parser.add_argument("--width", type=int, default=1920)
    parser.add_argument("--height", type=int, default=1080)
    parser.add_argument("--steps", type=int, default=24)
    parser.add_argument("--cfg", type=float, default=5.0)
    parser.add_argument("--seed", type=int, default=20260528)
    parser.add_argument("--sampler", default="euler")
    parser.add_argument("--scheduler", default="normal")
    parser.add_argument("--filename-prefix", default="hackme_standalone_regular")
    parser.add_argument("--request-timeout", type=int, default=60)
    parser.add_argument("--max-seconds", type=int, default=1200)
    parser.add_argument("--poll-seconds", type=float, default=3)
    parser.add_argument("--sample-interval", type=float, default=1.0)
    parser.add_argument("--out-dir", default="/tmp/hackme_regular_comfyui_standalone")
    parser.add_argument("--out-json", default="")
    parser.add_argument("--preflight-only", action="store_true")
    args = parser.parse_args()
    return normalize_runtime_paths(apply_config(args, parser))


def main() -> int:
    args = parse_args()
    out_dir = Path(args.out_dir).expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    out_json = Path(args.out_json or (out_dir / "regular_comfyui_standalone_report.json")).expanduser().resolve()
    out_png = out_dir / "regular_comfyui.png"
    started = time.time()
    timings = {}
    report = {
        "ok": False,
        "label": "standalone_regular_comfyui_txt2img",
        "started_at": now_iso(),
        "config": getattr(args, "config_loaded", ""),
        "comfyui_url": args.comfyui_url,
        "dimensions": {"width": args.width, "height": args.height, "steps": args.steps, "cfg": args.cfg},
        "artifacts": {"out_dir": str(out_dir), "report": str(out_json), "image": str(out_png)},
    }
    try:
        client = ComfyClient(args.comfyui_url, insecure=args.insecure, timeout=args.request_timeout)
        with ResourceMonitor(args.sample_interval) as monitor:
            report["output"] = run_generation(client, args, out_png, timings)
            report["resources"] = monitor.summary(started)
        report["ok"] = bool(args.preflight_only or Path(str(report["output"].get("path", ""))).is_file())
        return_code = 0 if report["ok"] else 1
    except Exception as exc:
        report["ok"] = False
        report["error"] = sanitize_text(exc)
        report["traceback"] = sanitize_text(traceback.format_exc(limit=8))
        return_code = 1
    finally:
        report["timings"] = timings
        report["finished_at"] = now_iso()
        out_json.parent.mkdir(parents=True, exist_ok=True)
        out_json.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
        print(json.dumps({
            "ok": report.get("ok"),
            "image": report.get("output", {}).get("path"),
            "out_json": str(out_json),
            "error": report.get("error"),
            "timings": report.get("timings"),
            "resources": report.get("resources", {}).get("peaks"),
        }, ensure_ascii=False, indent=2))
    return return_code


if __name__ == "__main__":
    raise SystemExit(main())
