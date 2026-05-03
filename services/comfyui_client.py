import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass
from pathlib import Path

try:
    import websocket
except Exception:  # pragma: no cover - optional import fallback
    websocket = None


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

    def _ws_url(self):
        parsed = urllib.parse.urlparse(self.base_url)
        scheme = "wss" if parsed.scheme == "https" else "ws"
        netloc = parsed.netloc or parsed.path
        path = parsed.path.rstrip("/")
        return urllib.parse.urlunparse((scheme, netloc, path, "", "", ""))

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

    def _open_progress_socket(self, client_id, *, timeout=5):
        if websocket is None:
            raise ComfyUIError("缺少 websocket-client 套件，無法讀取 ComfyUI 即時進度")
        query = urllib.parse.urlencode({"clientId": str(client_id)})
        try:
            ws = websocket.create_connection(f"{self._ws_url()}/ws?{query}", timeout=timeout)
            ws.settimeout(0.25)
            return ws
        except Exception as exc:
            raise ComfyUIError(f"ComfyUI websocket 連線失敗：{exc}") from exc

    def _list_node_input_options(self, node_class, input_name):
        info = self._json_request(f"/object_info/{node_class}")
        node = info.get(node_class) if isinstance(info, dict) else None
        required = ((node or {}).get("input") or {}).get("required") or {}
        raw_values = required.get(input_name) or []
        values = raw_values[0] if isinstance(raw_values, list) and raw_values else []
        if not isinstance(values, list):
            values = []
        return [str(item) for item in values if str(item).strip()]

    def get_models(self):
        return self._list_node_input_options("CheckpointLoaderSimple", "ckpt_name")

    def get_loras(self):
        return self._list_node_input_options("LoraLoader", "lora_name")

    def get_vaes(self):
        return self._list_node_input_options("VAELoader", "vae_name")

    def get_embeddings(self):
        data = self._json_request("/embeddings")
        if isinstance(data, list):
            values = data
        elif isinstance(data, dict):
            values = data.get("embeddings") or data.get("items") or []
        else:
            values = []
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
        workflow = {
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
        final_model = ["4", 0]
        final_clip = ["4", 1]
        next_node_id = 10
        for item in params.get("loras") or []:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "").strip()
            if not name:
                continue
            node_id = str(next_node_id)
            next_node_id += 1
            workflow[node_id] = {
                "class_type": "LoraLoader",
                "inputs": {
                    "model": final_model,
                    "clip": final_clip,
                    "lora_name": name,
                    "strength_model": float(item.get("strength_model", 1.0)),
                    "strength_clip": float(item.get("strength_clip", 1.0)),
                },
            }
            final_model = [node_id, 0]
            final_clip = [node_id, 1]
        vae_name = str(params.get("vae") or "").strip()
        if vae_name:
            vae_node_id = str(next_node_id)
            workflow[vae_node_id] = {
                "class_type": "VAELoader",
                "inputs": {"vae_name": vae_name},
            }
            workflow["8"]["inputs"]["vae"] = [vae_node_id, 0]
        workflow["3"]["inputs"]["model"] = final_model
        workflow["6"]["inputs"]["clip"] = final_clip
        workflow["7"]["inputs"]["clip"] = final_clip
        return workflow

    def queue_prompt_with_client_id(self, workflow, *, client_id=None):
        client_id = str(client_id or uuid.uuid4().hex)
        data = self._json_request("/prompt", method="POST", payload={"prompt": workflow, "client_id": client_id})
        prompt_id = data.get("prompt_id") if isinstance(data, dict) else None
        if not prompt_id:
            raise ComfyUIError("ComfyUI 未回傳 prompt_id")
        return {"prompt_id": str(prompt_id), "client_id": client_id}

    def queue_prompt(self, workflow):
        return self.queue_prompt_with_client_id(workflow)["prompt_id"]

    def interrupt(self):
        return self._json_request("/interrupt", method="POST", payload={}, allow_non_json=True)

    def _emit_progress(self, progress_callback, snapshot):
        if not progress_callback:
            return
        progress_callback(dict(snapshot))

    def _apply_ws_message_to_progress(self, snapshot, message, prompt_id):
        if not isinstance(message, dict):
            return False
        msg_type = str(message.get("type") or "")
        data = message.get("data") if isinstance(message.get("data"), dict) else {}
        if data.get("prompt_id") and str(data.get("prompt_id")) != str(prompt_id):
            return False
        updated = False
        snapshot["last_event"] = msg_type
        snapshot["updated_at"] = time.time()
        if msg_type == "status":
            exec_info = data.get("status") if isinstance(data.get("status"), dict) else data.get("exec_info")
            if isinstance(exec_info, dict):
                queue_remaining = exec_info.get("queue_remaining")
                if queue_remaining is not None:
                    snapshot["queue_remaining"] = int(queue_remaining)
                    updated = True
        elif msg_type == "executing":
            snapshot["phase"] = "running"
            snapshot["current_node"] = data.get("node")
            updated = True
        elif msg_type == "execution_cached":
            snapshot["phase"] = "running"
            nodes = data.get("nodes") if isinstance(data.get("nodes"), list) else []
            snapshot["detail"] = f"使用快取節點 {len(nodes)} 個"
            updated = True
        elif msg_type == "progress":
            value = data.get("value")
            maximum = data.get("max")
            if isinstance(value, (int, float)) and isinstance(maximum, (int, float)) and maximum:
                snapshot["phase"] = "running"
                snapshot["current"] = float(value)
                snapshot["max"] = float(maximum)
                snapshot["percent"] = max(0, min(99, round((float(value) / float(maximum)) * 100)))
                node_id = data.get("node") or data.get("display_node_id")
                snapshot["current_node"] = node_id
                snapshot["detail"] = f"節點 {node_id or '-'}：{int(value)}/{int(maximum)}"
                updated = True
        elif msg_type == "progress_state":
            nodes = data.get("nodes") if isinstance(data.get("nodes"), dict) else {}
            total_value = 0.0
            total_max = 0.0
            active_node = None
            for node_id, node in nodes.items():
                if not isinstance(node, dict):
                    continue
                if node.get("prompt_id") and str(node.get("prompt_id")) != str(prompt_id):
                    continue
                node_max = node.get("max")
                node_value = node.get("value")
                if isinstance(node_max, (int, float)) and float(node_max) > 0:
                    total_max += float(node_max)
                    total_value += min(float(node_value or 0), float(node_max))
                    if active_node is None and float(node_value or 0) < float(node_max):
                        active_node = node
                        active_node["node_id"] = node.get("display_node_id") or node.get("node_id") or node_id
            if total_max > 0:
                snapshot["phase"] = "running"
                snapshot["current"] = total_value
                snapshot["max"] = total_max
                snapshot["percent"] = max(0, min(99, round((total_value / total_max) * 100)))
                if active_node:
                    node_label = active_node.get("node_id") or "-"
                    snapshot["current_node"] = node_label
                    snapshot["detail"] = f"節點 {node_label}：{int(active_node.get('value') or 0)}/{int(active_node.get('max') or 0)}"
                updated = True
        return updated

    def wait_for_images(self, prompt_id, *, timeout_seconds=600, poll_interval=1.0, expected_count=1, websocket_conn=None, progress_callback=None):
        deadline = time.time() + int(timeout_seconds)
        last_status = None
        expected = max(1, int(expected_count or 1))
        snapshot = {
            "prompt_id": str(prompt_id),
            "phase": "queued",
            "percent": 0,
            "current": 0,
            "max": 0,
            "current_node": None,
            "queue_remaining": None,
            "detail": "已送出至 ComfyUI 佇列",
            "completed": False,
            "updated_at": time.time(),
        }
        next_history_poll = 0.0
        while time.time() < deadline:
            if websocket_conn is not None and websocket is not None:
                for _ in range(20):
                    try:
                        raw = websocket_conn.recv()
                    except websocket.WebSocketTimeoutException:
                        break
                    except websocket.WebSocketConnectionClosedException:
                        websocket_conn = None
                        break
                    except Exception:
                        websocket_conn = None
                        break
                    if not isinstance(raw, str):
                        continue
                    try:
                        message = json.loads(raw)
                    except json.JSONDecodeError:
                        continue
                    if self._apply_ws_message_to_progress(snapshot, message, prompt_id):
                        self._emit_progress(progress_callback, snapshot)
            now = time.time()
            if now >= next_history_poll:
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
                        snapshot["phase"] = "completed"
                        snapshot["percent"] = 100
                        snapshot["completed"] = True
                        snapshot["detail"] = f"已完成，共 {len(found[:expected])} 張"
                        self._emit_progress(progress_callback, snapshot)
                        return found[:expected]
                    if found and status.get("completed") is True:
                        snapshot["phase"] = "completed"
                        snapshot["percent"] = 100
                        snapshot["completed"] = True
                        snapshot["detail"] = f"已完成，共 {len(found)} 張"
                        self._emit_progress(progress_callback, snapshot)
                        return found
                next_history_poll = now + float(poll_interval)
            time.sleep(0.15)
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

    def _local_dir_for_type(self, image_type, *, local_base_dir=None):
        normalized = str(image_type or "output").strip().lower() or "output"
        if normalized not in {"output", "input", "temp"}:
            raise ComfyUIError("ComfyUI 圖片類型不支援刪除")
        explicit = os.environ.get(f"COMFYUI_{normalized.upper()}_DIR")
        if explicit:
            return Path(explicit).expanduser()
        base_dir = local_base_dir or os.environ.get("COMFYUI_BASE_DIR")
        if base_dir:
            return Path(base_dir).expanduser() / normalized
        return None

    def _safe_local_image_path(self, image_ref, *, local_base_dir=None):
        filename = str((image_ref or {}).get("filename") or "").strip()
        subfolder = str((image_ref or {}).get("subfolder") or "").strip()
        image_type = str((image_ref or {}).get("type") or "output").strip() or "output"
        if not filename:
            raise ComfyUIError("缺少 ComfyUI 圖片檔名")
        if Path(filename).name != filename or filename in {".", ".."}:
            raise ComfyUIError("ComfyUI 圖片檔名不合法")
        base_dir = self._local_dir_for_type(image_type, local_base_dir=local_base_dir)
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

    def discard_image(self, image_ref, *, prompt_id=None, local_base_dir=None, allow_api_delete=True):
        result = {
            "file_deleted": False,
            "file_missing": False,
            "file_delete_supported": False,
            "history_deleted": False,
        }
        target = self._safe_local_image_path(image_ref, local_base_dir=local_base_dir)
        if target:
            result["file_delete_supported"] = True
            if target.exists():
                if not target.is_file():
                    raise ComfyUIError("ComfyUI 目標路徑不是檔案")
                target.unlink()
                result["file_deleted"] = True
            else:
                result["file_missing"] = True
        elif allow_api_delete:
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

    def generate_image(self, params, *, timeout_seconds=600, progress_callback=None):
        workflow = self.build_text_to_image_workflow(params)
        websocket_conn = None
        client_id = uuid.uuid4().hex
        try:
            if progress_callback:
                try:
                    websocket_conn = self._open_progress_socket(client_id, timeout=min(5, self.timeout))
                except ComfyUIError:
                    websocket_conn = None
            queued = self.queue_prompt_with_client_id(workflow, client_id=client_id)
            prompt_id = queued["prompt_id"]
            self._emit_progress(progress_callback, {
                "prompt_id": prompt_id,
                "phase": "queued",
                "percent": 0,
                "current": 0,
                "max": 0,
                "current_node": None,
                "queue_remaining": None,
                "detail": "已送出至 ComfyUI 佇列",
                "completed": False,
                "updated_at": time.time(),
            })
            image_refs = self.wait_for_images(
                prompt_id,
                timeout_seconds=timeout_seconds,
                expected_count=int(params.get("batch_size") or 1),
                websocket_conn=websocket_conn,
                progress_callback=progress_callback,
            )
        finally:
            try:
                if websocket_conn is not None:
                    websocket_conn.close()
            except Exception:
                pass
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
