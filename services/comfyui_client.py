import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass
from pathlib import Path


class ComfyUIError(RuntimeError):
    pass


@dataclass
class ComfyUIImage:
    filename: str
    subfolder: str
    type: str
    mime_type: str
    data: bytes


class ComfyUIClient:
    def __init__(self, base_url="http://localhost:8192", timeout=30):
        self.base_url = str(base_url or "http://localhost:8192").rstrip("/")
        self.timeout = int(timeout or 30)

    def _url(self, path):
        return f"{self.base_url}{path}"

    def _json_request(self, path, *, method="GET", payload=None, timeout=None, allow_non_json=False):
        headers = {"Accept": "application/json"}
        body = None
        if payload is not None:
            body = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(self._url(path), data=body, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=timeout or self.timeout) as resp:
                raw = resp.read().decode("utf-8")
                if not raw.strip():
                    return {}
                try:
                    return json.loads(raw)
                except json.JSONDecodeError as exc:
                    if allow_non_json:
                        return {"raw": raw}
                    raise ComfyUIError("ComfyUI 回應不是 JSON") from exc
        except urllib.error.URLError as exc:
            raise ComfyUIError(f"ComfyUI 連線失敗：{getattr(exc, 'reason', exc)}") from exc

    def get_models(self):
        info = self._json_request("/object_info/CheckpointLoaderSimple")
        node = info.get("CheckpointLoaderSimple") if isinstance(info, dict) else None
        required = ((node or {}).get("input") or {}).get("required") or {}
        ckpt = required.get("ckpt_name") or []
        values = ckpt[0] if isinstance(ckpt, list) and ckpt else []
        if not isinstance(values, list):
            values = []
        return [str(item) for item in values if str(item).strip()]

    def health_check(self, *, timeout=3):
        stats = self._json_request("/system_stats", timeout=timeout)
        if not isinstance(stats, dict):
            raise ComfyUIError("ComfyUI 狀態回應格式不正確")
        return {
            "ok": True,
            "base_url": self.base_url,
            "system": stats.get("system") or {},
        }

    def get_sampler_options(self):
        info = self._json_request("/object_info/KSampler")
        node = info.get("KSampler") if isinstance(info, dict) else None
        required = ((node or {}).get("input") or {}).get("required") or {}
        sampler = required.get("sampler_name") or []
        scheduler = required.get("scheduler") or []
        sampler_values = sampler[0] if isinstance(sampler, list) and sampler else []
        scheduler_values = scheduler[0] if isinstance(scheduler, list) and scheduler else []
        return {
            "samplers": [str(item) for item in sampler_values] if isinstance(sampler_values, list) else [],
            "schedulers": [str(item) for item in scheduler_values] if isinstance(scheduler_values, list) else [],
        }

    def build_text_to_image_workflow(self, params):
        return {
            "3": {
                "class_type": "KSampler",
                "inputs": {
                    "seed": int(params["seed"]),
                    "steps": int(params["steps"]),
                    "cfg": float(params["cfg"]),
                    "sampler_name": params["sampler_name"],
                    "scheduler": params["scheduler"],
                    "denoise": 1,
                    "model": ["4", 0],
                    "positive": ["6", 0],
                    "negative": ["7", 0],
                    "latent_image": ["5", 0],
                },
            },
            "4": {
                "class_type": "CheckpointLoaderSimple",
                "inputs": {"ckpt_name": params["model"]},
            },
            "5": {
                "class_type": "EmptyLatentImage",
                "inputs": {
                    "width": int(params["width"]),
                    "height": int(params["height"]),
                    "batch_size": int(params.get("batch_size") or 1),
                },
            },
            "6": {
                "class_type": "CLIPTextEncode",
                "inputs": {"text": params["prompt"], "clip": ["4", 1]},
            },
            "7": {
                "class_type": "CLIPTextEncode",
                "inputs": {"text": params.get("negative_prompt") or "", "clip": ["4", 1]},
            },
            "8": {
                "class_type": "VAEDecode",
                "inputs": {"samples": ["3", 0], "vae": ["4", 2]},
            },
            "9": {
                "class_type": "SaveImage",
                "inputs": {
                    "filename_prefix": params.get("filename_prefix") or "hackme_web",
                    "images": ["8", 0],
                },
            },
        }

    def queue_prompt(self, workflow):
        client_id = uuid.uuid4().hex
        data = self._json_request("/prompt", method="POST", payload={"prompt": workflow, "client_id": client_id})
        prompt_id = data.get("prompt_id") if isinstance(data, dict) else None
        if not prompt_id:
            raise ComfyUIError("ComfyUI 未回傳 prompt_id")
        return str(prompt_id)

    def interrupt(self):
        return self._json_request("/interrupt", method="POST", payload={}, allow_non_json=True)

    def wait_for_images(self, prompt_id, *, timeout_seconds=600, poll_interval=1.0, expected_count=1):
        deadline = time.time() + int(timeout_seconds)
        last_status = None
        expected = max(1, int(expected_count or 1))
        while time.time() < deadline:
            history = self._json_request(f"/history/{urllib.parse.quote(prompt_id)}", timeout=self.timeout)
            record = history.get(prompt_id) if isinstance(history, dict) else None
            if record:
                status = record.get("status") or {}
                last_status = status
                if status.get("status_str") == "error" or status.get("completed") is False and status.get("status_str") == "error":
                    raise ComfyUIError("ComfyUI 產圖失敗")
                found = []
                outputs = record.get("outputs") or {}
                for output in outputs.values():
                    images = output.get("images") if isinstance(output, dict) else None
                    if images:
                        found.extend(images)
                if len(found) >= expected:
                    return found[:expected]
                if found and status.get("completed") is True:
                    return found
            time.sleep(float(poll_interval))
        detail = f"；最後狀態：{last_status}" if last_status else ""
        raise ComfyUIError(f"ComfyUI 產圖逾時{detail}")

    def wait_for_first_image(self, prompt_id, *, timeout_seconds=600, poll_interval=1.0):
        return self.wait_for_images(prompt_id, timeout_seconds=timeout_seconds, poll_interval=poll_interval, expected_count=1)[0]

    def fetch_image(self, image_ref):
        filename = str((image_ref or {}).get("filename") or "").strip()
        subfolder = str((image_ref or {}).get("subfolder") or "").strip()
        image_type = str((image_ref or {}).get("type") or "output").strip() or "output"
        if not filename:
            raise ComfyUIError("缺少 ComfyUI 圖片檔名")
        query = urllib.parse.urlencode({"filename": filename, "subfolder": subfolder, "type": image_type})
        req = urllib.request.Request(self._url(f"/view?{query}"), headers={"Accept": "image/*"})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                content_type = resp.headers.get("Content-Type") or "image/png"
                data = resp.read()
        except urllib.error.URLError as exc:
            raise ComfyUIError(f"ComfyUI 圖片讀取失敗：{getattr(exc, 'reason', exc)}") from exc
        if not data:
            raise ComfyUIError("ComfyUI 圖片內容為空")
        return ComfyUIImage(filename=filename, subfolder=subfolder, type=image_type, mime_type=content_type, data=data)

    def _local_dir_for_type(self, image_type):
        normalized = str(image_type or "output").strip().lower() or "output"
        if normalized not in {"output", "input", "temp"}:
            raise ComfyUIError("ComfyUI 圖片類型不支援刪除")
        explicit = os.environ.get(f"COMFYUI_{normalized.upper()}_DIR")
        if explicit:
            return Path(explicit).expanduser()
        base_dir = os.environ.get("COMFYUI_BASE_DIR")
        if base_dir:
            return Path(base_dir).expanduser() / normalized
        return None

    def _safe_local_image_path(self, image_ref):
        filename = str((image_ref or {}).get("filename") or "").strip()
        subfolder = str((image_ref or {}).get("subfolder") or "").strip()
        image_type = str((image_ref or {}).get("type") or "output").strip() or "output"
        if not filename:
            raise ComfyUIError("缺少 ComfyUI 圖片檔名")
        if Path(filename).name != filename or filename in {".", ".."}:
            raise ComfyUIError("ComfyUI 圖片檔名不合法")
        base_dir = self._local_dir_for_type(image_type)
        if not base_dir:
            return None
        relative = Path(subfolder) / filename if subfolder else Path(filename)
        if relative.is_absolute() or any(part in {"..", ""} for part in relative.parts):
            raise ComfyUIError("ComfyUI 圖片路徑不合法")
        base = base_dir.resolve()
        target = (base / relative).resolve()
        try:
            target.relative_to(base)
        except ValueError as exc:
            raise ComfyUIError("ComfyUI 圖片路徑超出允許目錄") from exc
        return target

    def discard_image(self, image_ref, *, prompt_id=None):
        result = {
            "file_deleted": False,
            "file_missing": False,
            "file_delete_supported": False,
            "history_deleted": False,
        }
        target = self._safe_local_image_path(image_ref)
        if target:
            result["file_delete_supported"] = True
            if target.exists():
                if not target.is_file():
                    raise ComfyUIError("ComfyUI 目標路徑不是檔案")
                target.unlink()
                result["file_deleted"] = True
            else:
                result["file_missing"] = True
        else:
            filename = str((image_ref or {}).get("filename") or "").strip()
            subfolder = str((image_ref or {}).get("subfolder") or "").strip()
            image_type = str((image_ref or {}).get("type") or "output").strip() or "output"
            query = urllib.parse.urlencode({"filename": filename, "subfolder": subfolder, "type": image_type})
            req = urllib.request.Request(self._url(f"/view?{query}"), method="DELETE", headers={"Accept": "application/json"})
            try:
                with urllib.request.urlopen(req, timeout=self.timeout):
                    result["file_delete_supported"] = True
                    result["file_deleted"] = True
            except urllib.error.HTTPError as exc:
                if exc.code == 404:
                    result["file_delete_supported"] = True
                    result["file_missing"] = True
                elif exc.code not in {405, 501}:
                    raise ComfyUIError(f"ComfyUI 原始檔刪除失敗：HTTP {exc.code}") from exc
            except urllib.error.URLError as exc:
                raise ComfyUIError(f"ComfyUI 原始檔刪除失敗：{getattr(exc, 'reason', exc)}") from exc
        if prompt_id:
            self._json_request("/history", method="POST", payload={"delete": [str(prompt_id)]}, allow_non_json=True)
            result["history_deleted"] = True
        return result

    def generate_image(self, params, *, timeout_seconds=600):
        workflow = self.build_text_to_image_workflow(params)
        prompt_id = self.queue_prompt(workflow)
        image_refs = self.wait_for_images(
            prompt_id,
            timeout_seconds=timeout_seconds,
            expected_count=int(params.get("batch_size") or 1),
        )
        images = [self.fetch_image(image_ref) for image_ref in image_refs]
        image = images[0]
        serialized_images = [{
            "image_ref": {
                "filename": item.filename,
                "subfolder": item.subfolder,
                "type": item.type,
            },
            "mime_type": item.mime_type,
            "data": item.data,
        } for item in images]
        return {
            "prompt_id": prompt_id,
            "image_ref": {
                "filename": image.filename,
                "subfolder": image.subfolder,
                "type": image.type,
            },
            "mime_type": image.mime_type,
            "data": image.data,
            "images": serialized_images,
        }
