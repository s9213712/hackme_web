#!/usr/bin/env python3
"""Run Hugging Face Diffusers jobs while sampling system resources."""

from __future__ import annotations

import argparse
import http.client
import http.cookiejar
import json
import os
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


class ProbeError(RuntimeError):
    pass


class WebClient:
    def __init__(self, base_url: str, *, insecure: bool = False):
        self.base_url = str(base_url).rstrip("/")
        self.jar = http.cookiejar.CookieJar()
        handlers = [urllib.request.HTTPCookieProcessor(self.jar)]
        if self.base_url.startswith("https://"):
            ctx = ssl._create_unverified_context() if insecure else ssl.create_default_context()
            handlers.append(urllib.request.HTTPSHandler(context=ctx))
        self.opener = urllib.request.build_opener(*handlers)
        self.opener.addheaders = [("User-Agent", "hackme_web-hf-diffusers-resource-probe/1.0")]
        self.csrf_token = ""

    def _url(self, path: str) -> str:
        return f"{self.base_url}{path if str(path).startswith('/') else '/' + str(path)}"

    def _request(self, path: str, *, method="GET", payload=None, allow_http_error=False, timeout=30):
        body = None
        headers = {}
        if payload is not None:
            headers["Content-Type"] = "application/json"
            if self.csrf_token:
                headers["X-CSRF-Token"] = self.csrf_token
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(self._url(path), data=body, headers=headers, method=method)
        try:
            with self.opener.open(req, timeout=timeout) as resp:
                raw = self._read_body(resp)
                return int(resp.status), raw
        except urllib.error.HTTPError as exc:
            raw = self._read_body(exc)
            if not allow_http_error:
                raise
            return int(exc.code), raw

    @staticmethod
    def _read_body(resp) -> bytes:
        try:
            return resp.read()
        except http.client.IncompleteRead as exc:
            return exc.partial or b""

    def json_request(self, path: str, *, method="GET", payload=None, allow_http_error=False, timeout=30):
        status, raw = self._request(
            path,
            method=method,
            payload=payload,
            allow_http_error=allow_http_error,
            timeout=timeout,
        )
        try:
            data = json.loads(raw.decode("utf-8", errors="replace"))
        except Exception as exc:
            raise ProbeError(f"{method} {path} returned non-JSON HTTP {status}") from exc
        if not isinstance(data, dict):
            data = {"ok": False, "raw": data}
        data["_http_status"] = status
        return data

    def fetch_csrf(self):
        payload = self.json_request("/api/csrf-token")
        token = str(payload.get("csrf_token") or "").strip()
        if not token:
            raise ProbeError("server did not return csrf_token")
        self.csrf_token = token
        return token

    def login(self, username: str, password: str):
        self.fetch_csrf()
        payload = self.json_request(
            "/api/login",
            method="POST",
            payload={"username": username, "password": password},
            allow_http_error=True,
        )
        if payload.get("_http_status") != 200 or payload.get("ok") is not True:
            raise ProbeError(f"login failed: {payload.get('msg') or payload}")
        self.fetch_csrf()
        return payload


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _read_cpu_times():
    with open("/proc/stat", "r", encoding="utf-8") as handle:
        parts = handle.readline().split()
    values = [int(value) for value in parts[1:]]
    idle = values[3] + (values[4] if len(values) > 4 else 0)
    total = sum(values)
    return total, idle


def _cpu_percent(previous, current):
    if not previous or not current:
        return None
    total_delta = current[0] - previous[0]
    idle_delta = current[1] - previous[1]
    if total_delta <= 0:
        return None
    return round(100.0 * (1.0 - idle_delta / total_delta), 1)


def _read_meminfo():
    values = {}
    with open("/proc/meminfo", "r", encoding="utf-8") as handle:
        for line in handle:
            key, raw = line.split(":", 1)
            values[key] = int(raw.strip().split()[0]) * 1024
    total = int(values.get("MemTotal") or 0)
    available = int(values.get("MemAvailable") or 0)
    return {
        "ram_total_mb": round(total / 1024 / 1024, 1),
        "ram_available_mb": round(available / 1024 / 1024, 1),
        "ram_used_mb": round((total - available) / 1024 / 1024, 1),
        "ram_used_percent": round(100.0 * (total - available) / total, 1) if total else None,
    }


def _read_net_bytes():
    rx = 0
    tx = 0
    with open("/proc/net/dev", "r", encoding="utf-8") as handle:
        for line in handle.readlines()[2:]:
            if ":" not in line:
                continue
            iface, raw = line.split(":", 1)
            if iface.strip() == "lo":
                continue
            fields = raw.split()
            if len(fields) < 16:
                continue
            rx += int(fields[0])
            tx += int(fields[8])
    return rx, tx


def _net_rate(previous, current, elapsed):
    if not previous or not current or elapsed <= 0:
        return {"net_rx_kb_s": None, "net_tx_kb_s": None, "net_rx_total_mb": 0, "net_tx_total_mb": 0}
    rx_delta = max(0, current[0] - previous[0])
    tx_delta = max(0, current[1] - previous[1])
    return {
        "net_rx_kb_s": round(rx_delta / 1024 / elapsed, 1),
        "net_tx_kb_s": round(tx_delta / 1024 / elapsed, 1),
        "net_rx_total_mb": round(rx_delta / 1024 / 1024, 3),
        "net_tx_total_mb": round(tx_delta / 1024 / 1024, 3),
    }


class GpuSampler:
    def __init__(self):
        self.available = False
        self.handle = None
        self.error = ""
        try:
            import pynvml  # type: ignore

            self.pynvml = pynvml
            pynvml.nvmlInit()
            self.handle = pynvml.nvmlDeviceGetHandleByIndex(0)
            self.available = True
        except Exception as exc:
            self.pynvml = None
            self.error = str(exc)

    def sample(self):
        if not self.available:
            return {"gpu_available": False, "gpu_error": self.error}
        try:
            mem = self.pynvml.nvmlDeviceGetMemoryInfo(self.handle)
            util = self.pynvml.nvmlDeviceGetUtilizationRates(self.handle)
            name = self.pynvml.nvmlDeviceGetName(self.handle)
            if isinstance(name, bytes):
                name = name.decode("utf-8", errors="replace")
            return {
                "gpu_available": True,
                "gpu_name": str(name),
                "gpu_util_percent": int(util.gpu),
                "gpu_mem_util_percent": int(util.memory),
                "vram_total_mb": round(int(mem.total) / 1024 / 1024, 1),
                "vram_used_mb": round(int(mem.used) / 1024 / 1024, 1),
                "vram_free_mb": round(int(mem.free) / 1024 / 1024, 1),
            }
        except Exception as exc:
            return {"gpu_available": False, "gpu_error": str(exc)}


class ResourceSampler:
    def __init__(self):
        self.gpu = GpuSampler()
        self.previous_cpu = None
        self.previous_net = None
        self.previous_at = None

    def sample(self):
        now = time.time()
        cpu_now = _read_cpu_times()
        net_now = _read_net_bytes()
        elapsed = now - self.previous_at if self.previous_at else 0
        sample = {
            "sampled_at": _now_iso(),
            "cpu_percent": _cpu_percent(self.previous_cpu, cpu_now),
            **_read_meminfo(),
            **_net_rate(self.previous_net, net_now, elapsed),
            **self.gpu.sample(),
        }
        self.previous_cpu = cpu_now
        self.previous_net = net_now
        self.previous_at = now
        return sample


def _compact_progress(progress):
    progress = progress if isinstance(progress, dict) else {}
    keys = (
        "phase",
        "percent",
        "step",
        "detail",
        "current_file",
        "bytes_written",
        "total_bytes",
        "cache_hit",
        "cache_check",
        "cuda_device_name",
        "cuda_free_bytes",
        "cuda_total_bytes",
        "backend_unresponsive",
        "stale_seconds",
    )
    compact = {key: progress.get(key) for key in keys if key in progress}
    tail = progress.get("python_log_tail") if isinstance(progress.get("python_log_tail"), list) else []
    compact["python_log_tail"] = tail[-12:]
    return compact


def _job_output_count(result):
    result = result if isinstance(result, dict) else {}
    images = result.get("images") if isinstance(result.get("images"), list) else []
    media = result.get("media") if isinstance(result.get("media"), list) else []
    return len(images), len(media)


def _preview_first_image(client: WebClient, result):
    result = result if isinstance(result, dict) else {}
    images = result.get("images") if isinstance(result.get("images"), list) else []
    image = images[0] if images else result.get("image")
    image_ref = image.get("image_ref") if isinstance(image, dict) else None
    if not isinstance(image_ref, dict):
        return {"ok": False, "detail": "no image_ref"}
    payload = client.json_request(
        "/api/comfyui/image-preview",
        method="POST",
        payload={"image_ref": image_ref},
        allow_http_error=True,
        timeout=60,
    )
    image_payload = payload.get("image") if isinstance(payload.get("image"), dict) else {}
    return {
        "ok": payload.get("_http_status") == 200 and payload.get("ok") is True and bool(image_payload.get("data_url")),
        "http_status": payload.get("_http_status"),
        "size_bytes": image_payload.get("size_bytes"),
        "mime_type": image_payload.get("mime_type"),
    }


def run_generation(client: WebClient, sampler: ResourceSampler, *, label: str, payload: dict, max_seconds: int, poll_seconds: float):
    started_at = time.time()
    run = {
        "label": label,
        "payload": {key: value for key, value in payload.items() if key not in {"negative_prompt"}},
        "started_at": _now_iso(),
        "samples": [],
        "progress_events": [],
    }
    start_payload = client.json_request(
        "/api/comfyui/generate",
        method="POST",
        payload=payload,
        allow_http_error=True,
        timeout=120,
    )
    run["start_response"] = start_payload
    job_id = ((start_payload.get("job") or {}) if isinstance(start_payload.get("job"), dict) else {}).get("job_id")
    run["job_id"] = job_id
    if start_payload.get("_http_status") != 200 or start_payload.get("ok") is not True or not job_id:
        run["ok"] = False
        run["error"] = start_payload.get("msg") or "job did not start"
        return run

    last_status = None
    while time.time() - started_at <= max_seconds:
        resource = sampler.sample()
        job_payload = client.json_request(
            f"/api/comfyui/jobs/{urllib.parse.quote(str(job_id))}",
            allow_http_error=True,
            timeout=60,
        )
        job = job_payload.get("job") if isinstance(job_payload.get("job"), dict) else {}
        status = str(job.get("status") or "").strip().lower()
        progress = _compact_progress(job.get("progress") or {})
        run["samples"].append({"elapsed_seconds": round(time.time() - started_at, 1), **resource})
        run["progress_events"].append({"elapsed_seconds": round(time.time() - started_at, 1), "status": status, **progress})
        last_status = status
        if status in {"completed", "failed", "error", "cancelled"}:
            run["final_job"] = job_payload
            break
        time.sleep(max(0.5, float(poll_seconds)))

    run["duration_seconds"] = round(time.time() - started_at, 1)
    if "final_job" not in run:
        run["ok"] = False
        run["error"] = f"timeout waiting for job; last_status={last_status}"
        return run
    final_job = (run["final_job"].get("job") or {}) if isinstance(run["final_job"], dict) else {}
    result = final_job.get("result") if isinstance(final_job.get("result"), dict) else {}
    image_count, media_count = _job_output_count(result)
    run["output"] = {"image_count": image_count, "media_count": media_count}
    run["preview"] = _preview_first_image(client, result) if image_count else {"ok": False, "detail": "no image output"}
    run["ok"] = final_job.get("status") == "completed" and image_count > 0 and run["preview"].get("ok") is True
    if not run["ok"]:
        run["error"] = final_job.get("error") or run["final_job"].get("msg") or "job completed without previewable image"
    return run


def parse_args():
    parser = argparse.ArgumentParser(description="Probe HF Diffusers generation with resource metrics.")
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--username", default="root")
    parser.add_argument("--password", required=True)
    parser.add_argument("--insecure", action="store_true")
    parser.add_argument("--label", default="hf-diffusers-resource-probe")
    parser.add_argument("--max-seconds", type=int, default=900)
    parser.add_argument("--poll-seconds", type=float, default=5)
    parser.add_argument("--out-json", default="")
    parser.add_argument("--run", action="append", choices=["diffusers", "gguf"], help="Run subset; defaults to both.")
    parser.add_argument("--device", default="auto")
    parser.add_argument("--dtype", default="auto")
    parser.add_argument("--device-map", default="auto")
    parser.add_argument("--low-cpu-mem-usage", default="true")
    parser.add_argument("--cuda-fallback-to-cpu", default="true")
    parser.add_argument("--keep-downloaded-models", default="true")
    parser.add_argument("--width", type=int, default=512)
    parser.add_argument("--height", type=int, default=512)
    parser.add_argument("--steps", type=int, default=2)
    parser.add_argument("--cfg", type=float, default=5)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    client = WebClient(args.base_url, insecure=args.insecure)
    report = {
        "label": args.label,
        "base_url": args.base_url,
        "started_at": _now_iso(),
        "runtime_settings": {
            "device": args.device,
            "dtype": args.dtype,
            "device_map": args.device_map,
            "low_cpu_mem_usage": args.low_cpu_mem_usage,
            "cuda_fallback_to_cpu": args.cuda_fallback_to_cpu,
            "keep_downloaded_models": args.keep_downloaded_models,
        },
        "runs": [],
    }
    try:
        client.login(args.username, args.password)
        settings_payload = client.json_request(
            "/api/admin/settings",
            method="PUT",
            payload={
                "comfyui_connection_mode": "diffusers",
                "comfyui_allow_in_process_diffusers": True,
                "comfyui_diffusers_device": args.device,
                "comfyui_diffusers_dtype": args.dtype,
                "comfyui_diffusers_device_map": args.device_map,
                "comfyui_diffusers_low_cpu_mem_usage": str(args.low_cpu_mem_usage).strip().lower() in {"1", "true", "yes", "on"},
                "comfyui_diffusers_cuda_fallback_to_cpu": str(args.cuda_fallback_to_cpu).strip().lower() in {"1", "true", "yes", "on"},
                "comfyui_diffusers_keep_downloaded_models": str(args.keep_downloaded_models).strip().lower() in {"1", "true", "yes", "on"},
            },
            allow_http_error=True,
            timeout=60,
        )
        report["settings_response"] = {
            "ok": settings_payload.get("ok"),
            "http_status": settings_payload.get("_http_status"),
            "msg": settings_payload.get("msg"),
        }
        if settings_payload.get("_http_status") != 200 or settings_payload.get("ok") is not True:
            raise ProbeError(f"failed to update Diffusers root settings: {settings_payload.get('msg') or settings_payload}")
        client.fetch_csrf()
        sampler = ResourceSampler()
        selected = set(args.run or ["diffusers", "gguf"])
        common = {
            "generation_mode": "txt2img",
            "prompt": "a bright anime style landscape with a small cottage, blue sky, flowers, clean composition, high detail",
            "negative_prompt": "low quality, blurry, distorted",
            "width": int(args.width),
            "height": int(args.height),
            "steps": int(args.steps),
            "cfg": float(args.cfg),
            "seed": 12345,
            "batch_size": 1,
            "confirm_billing": True,
            "async_progress": True,
            "timeout_seconds": 0,
        }
        if "diffusers" in selected:
            report["runs"].append(run_generation(
                client,
                sampler,
                label="diffusers",
                payload={
                    **common,
                    "diffusers_model_repo": "dhead/wai-nsfw-illustrious-sdxl-v140-sdxl",
                    "diffusers_model_variant": "fp16",
                },
                max_seconds=args.max_seconds,
                poll_seconds=args.poll_seconds,
            ))
        if "gguf" in selected:
            report["runs"].append(run_generation(
                client,
                sampler,
                label="gguf",
                payload={
                    **common,
                    "diffusers_model_repo": "sothmik/Wai-NSFW-Illustrious-v140-Q8-GGUF",
                    "diffusers_model_variant": "gguf::waiNSFWIllustrious_v140-Q8_0.gguf",
                    "diffusers_gguf_file": "waiNSFWIllustrious_v140-Q8_0.gguf",
                    "diffusers_gguf_base_repo": "stabilityai/stable-diffusion-xl-base-1.0",
                },
                max_seconds=args.max_seconds,
                poll_seconds=args.poll_seconds,
            ))
        report["ok"] = all(run.get("ok") is True for run in report["runs"])
    except Exception as exc:
        report["ok"] = False
        report["error"] = str(exc)
    report["finished_at"] = _now_iso()
    output_path = Path(args.out_json or f"/tmp/{args.label}.json")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps({"ok": report.get("ok"), "out_json": str(output_path), "runs": [
        {
            "label": run.get("label"),
            "ok": run.get("ok"),
            "duration_seconds": run.get("duration_seconds"),
            "output": run.get("output"),
            "preview": run.get("preview"),
            "error": run.get("error"),
        }
        for run in report.get("runs", [])
    ]}, ensure_ascii=False, indent=2))
    return 0 if report.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
