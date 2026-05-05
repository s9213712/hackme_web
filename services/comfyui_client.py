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


CONTROLNET_TYPE_DEFINITIONS = {
    "canny": {
        "label": "Canny",
        "default_preprocessor": "CannyEdgePreprocessor",
        "preprocessor_candidates": ["CannyEdgePreprocessor"],
        "model_keywords": ["canny"],
    },
    "depth": {
        "label": "Depth",
        "default_preprocessor": "DepthAnythingPreprocessor",
        "preprocessor_candidates": ["DepthAnythingPreprocessor", "MiDaS-DepthMapPreprocessor"],
        "model_keywords": ["depth"],
    },
    "openpose": {
        "label": "OpenPose",
        "default_preprocessor": "OpenposePreprocessor",
        "preprocessor_candidates": ["OpenposePreprocessor", "DWPreprocessor"],
        "model_keywords": ["openpose", "pose"],
    },
    "lineart": {
        "label": "Lineart",
        "default_preprocessor": "LineArtPreprocessor",
        "preprocessor_candidates": ["LineArtPreprocessor", "LineartStandardPreprocessor"],
        "model_keywords": ["lineart", "line-art"],
    },
    "scribble": {
        "label": "Scribble",
        "default_preprocessor": "PiDiNetPreprocessor",
        "preprocessor_candidates": ["PiDiNetPreprocessor", "ScribblePreprocessor"],
        "model_keywords": ["scribble"],
    },
    "softedge": {
        "label": "SoftEdge",
        "default_preprocessor": "SoftEdgePreprocessor",
        "preprocessor_candidates": ["SoftEdgePreprocessor", "HEDPreprocessor", "PiDiNetPreprocessor"],
        "model_keywords": ["softedge", "soft-edge", "hed"],
    },
    "tile": {
        "label": "Tile",
        "default_preprocessor": "TilePreprocessor",
        "preprocessor_candidates": ["TilePreprocessor"],
        "model_keywords": ["tile"],
    },
}

GENERATION_MODE_DEFINITIONS = {
    "txt2img": {"label": "文字生圖"},
    "img2img": {"label": "圖生圖"},
    "inpaint": {"label": "局部重繪"},
    "outpaint": {"label": "向外延展"},
    "upscale": {"label": "放大修復"},
}


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

    def _multipart_request(self, path, *, fields=None, files=None, timeout=None):
        boundary = f"----HackmeWebComfyUI{uuid.uuid4().hex}"
        body = bytearray()
        for key, value in (fields or {}).items():
            body.extend(f"--{boundary}\r\n".encode("utf-8"))
            body.extend(f'Content-Disposition: form-data; name="{key}"\r\n\r\n'.encode("utf-8"))
            body.extend(str(value).encode("utf-8"))
            body.extend(b"\r\n")
        for item in files or []:
            if not isinstance(item, dict):
                continue
            field_name = str(item.get("field") or "image")
            filename = str(item.get("filename") or "upload.bin")
            content_type = str(item.get("content_type") or "application/octet-stream")
            data = item.get("data") or b""
            body.extend(f"--{boundary}\r\n".encode("utf-8"))
            body.extend(
                f'Content-Disposition: form-data; name="{field_name}"; filename="{filename}"\r\n'.encode("utf-8")
            )
            body.extend(f"Content-Type: {content_type}\r\n\r\n".encode("utf-8"))
            body.extend(data)
            body.extend(b"\r\n")
        body.extend(f"--{boundary}--\r\n".encode("utf-8"))
        headers = {
            "Accept": "application/json",
            "Content-Type": f"multipart/form-data; boundary={boundary}",
        }
        req = urllib.request.Request(self._url(path), data=bytes(body), method="POST", headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=timeout or self.timeout) as resp:
                raw = resp.read().decode("utf-8")
                if not raw.strip():
                    return {}
                try:
                    return json.loads(raw)
                except json.JSONDecodeError as exc:
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
        values = []
        if isinstance(raw_values, list) and raw_values:
            first = raw_values[0]
            if isinstance(first, list):
                values = first
            elif isinstance(first, str) and len(raw_values) > 1 and isinstance(raw_values[1], dict):
                options = raw_values[1].get("options") or []
                if isinstance(options, list):
                    values = options
        return [str(item) for item in values if str(item).strip()]

    def get_object_info(self, node_class=None):
        path = "/object_info"
        if node_class:
            path = f"/object_info/{urllib.parse.quote(str(node_class))}"
        info = self._json_request(path)
        if not isinstance(info, dict):
            raise ComfyUIError("ComfyUI object_info 回應格式不正確")
        return info

    def list_node_classes(self):
        return sorted(self.get_object_info().keys())

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

    def get_controlnet_models(self):
        return self._list_node_input_options("ControlNetLoader", "control_net_name")

    def get_upscale_models(self):
        return self._list_node_input_options("UpscaleModelLoader", "model_name")

    def get_capabilities(self):
        object_info = self.get_object_info()
        available_nodes = set(object_info.keys())
        controlnet_models = self.get_controlnet_models() if "ControlNetLoader" in available_nodes else []
        upscale_models = self.get_upscale_models() if "UpscaleModelLoader" in available_nodes else []
        controlnet_types = {}
        for key, definition in CONTROLNET_TYPE_DEFINITIONS.items():
            preprocessor_candidates = list(definition.get("preprocessor_candidates") or [])
            available_preprocessors = [
                name for name in preprocessor_candidates if name in available_nodes
            ]
            model_keywords = [keyword.lower() for keyword in definition.get("model_keywords") or []]
            matching_models = [
                model
                for model in controlnet_models
                if any(keyword in str(model).lower() for keyword in model_keywords)
            ]
            controlnet_types[key] = {
                "label": definition.get("label") or key,
                "available": bool(
                    {"ControlNetLoader", "ControlNetApplyAdvanced", "LoadImage"}.issubset(available_nodes)
                    and available_preprocessors
                    and matching_models
                ),
                "available_preprocessors": available_preprocessors,
                "default_preprocessor": next(
                    (name for name in [definition.get("default_preprocessor")] + preprocessor_candidates if name in available_preprocessors),
                    "",
                ),
                "matching_models": matching_models,
            }
        return {
            "available_nodes": sorted(available_nodes),
            "controlnet_models": controlnet_models,
            "upscale_models": upscale_models,
            "controlnet_types": controlnet_types,
            "generation_modes": [
                {
                    "key": key,
                    "label": value.get("label") or key,
                    "available": True,
                }
                for key, value in GENERATION_MODE_DEFINITIONS.items()
            ],
        }

    def upload_image_bytes(self, data, filename, *, image_type="input", overwrite=False, subfolder=""):
        filename = Path(str(filename or "upload.png")).name
        payload = self._multipart_request(
            "/upload/image",
            fields={
                "type": str(image_type or "input"),
                "overwrite": "true" if overwrite else "false",
                "subfolder": str(subfolder or ""),
            },
            files=[{
                "field": "image",
                "filename": filename,
                "content_type": "application/octet-stream",
                "data": data or b"",
            }],
        )
        name = str(payload.get("name") or filename).strip()
        if not name:
            raise ComfyUIError("ComfyUI 未回傳上傳檔名")
        return {
            "filename": name,
            "subfolder": str(payload.get("subfolder") or subfolder or "").strip(),
            "type": str(payload.get("type") or image_type or "input").strip() or "input",
        }

    def _build_text_to_image_base(self, params):
        workflow = {
            "4": {
                "class_type": "CheckpointLoaderSimple",
                "inputs": {"ckpt_name": params["model"]},
            },
            "6": {
                "class_type": "CLIPTextEncode",
                "inputs": {"text": params["prompt"], "clip": ["4", 1]},
            },
            "7": {
                "class_type": "CLIPTextEncode",
                "inputs": {"text": params.get("negative_prompt") or "", "clip": ["4", 1]},
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
        vae_ref = ["4", 2]
        vae_name = str(params.get("vae") or "").strip()
        if vae_name:
            vae_node_id = str(next_node_id)
            next_node_id += 1
            workflow[vae_node_id] = {
                "class_type": "VAELoader",
                "inputs": {"vae_name": vae_name},
            }
            vae_ref = [vae_node_id, 0]
        workflow["6"]["inputs"]["clip"] = final_clip
        workflow["7"]["inputs"]["clip"] = final_clip
        return workflow, final_model, final_clip, vae_ref, next_node_id

    def _attach_controlnet(self, workflow, params, *, positive_ref, negative_ref, next_node_id):
        control = params.get("controlnet") if isinstance(params.get("controlnet"), dict) else None
        if not control:
            return positive_ref, negative_ref, next_node_id
        control_image = control.get("image_ref") if isinstance(control.get("image_ref"), dict) else None
        if not control_image or not control_image.get("filename"):
            raise ComfyUIError("ControlNet 缺少控制圖")
        loader_id = str(next_node_id)
        next_node_id += 1
        workflow[loader_id] = {
            "class_type": "LoadImage",
            "inputs": {"image": control_image["filename"], "upload": "image"},
        }
        image_ref = [loader_id, 0]
        preprocessor = str(control.get("preprocessor") or "").strip()
        if preprocessor:
            preprocessor_id = str(next_node_id)
            next_node_id += 1
            workflow[preprocessor_id] = {
                "class_type": preprocessor,
                "inputs": {"image": image_ref},
            }
            image_ref = [preprocessor_id, 0]
        model_id = str(next_node_id)
        next_node_id += 1
        workflow[model_id] = {
            "class_type": "ControlNetLoader",
            "inputs": {"control_net_name": control["model_name"]},
        }
        apply_id = str(next_node_id)
        next_node_id += 1
        workflow[apply_id] = {
            "class_type": "ControlNetApplyAdvanced",
            "inputs": {
                "positive": positive_ref,
                "negative": negative_ref,
                "control_net": [model_id, 0],
                "image": image_ref,
                "strength": float(control.get("strength") or 1.0),
                "start_percent": float(control.get("start_percent") or 0.0),
                "end_percent": float(control.get("end_percent") or 1.0),
            },
        }
        return [apply_id, 0], [apply_id, 1], next_node_id

    def build_text_to_image_workflow(self, params):
        workflow, final_model, _final_clip, vae_ref, next_node_id = self._build_text_to_image_base(params)
        workflow["5"] = {
            "class_type": "EmptyLatentImage",
            "inputs": {
                "width": int(params["width"]),
                "height": int(params["height"]),
                "batch_size": int(params.get("batch_size") or 1),
            },
        }
        positive_ref = ["6", 0]
        negative_ref = ["7", 0]
        positive_ref, negative_ref, next_node_id = self._attach_controlnet(
            workflow,
            params,
            positive_ref=positive_ref,
            negative_ref=negative_ref,
            next_node_id=next_node_id,
        )
        workflow["3"] = {
            "class_type": "KSampler",
            "inputs": {
                "seed": int(params["seed"]),
                "steps": int(params["steps"]),
                "cfg": float(params["cfg"]),
                "sampler_name": params["sampler_name"],
                "scheduler": params["scheduler"],
                "denoise": 1,
                "model": final_model,
                "positive": positive_ref,
                "negative": negative_ref,
                "latent_image": ["5", 0],
            },
        }
        workflow["8"] = {
            "class_type": "VAEDecode",
            "inputs": {"samples": ["3", 0], "vae": vae_ref},
        }
        workflow["9"] = {
            "class_type": "SaveImage",
            "inputs": {
                "filename_prefix": params.get("filename_prefix") or "hackme_web",
                "images": ["8", 0],
            },
        }
        return workflow

    def build_image_to_image_workflow(self, params):
        workflow, final_model, _final_clip, vae_ref, next_node_id = self._build_text_to_image_base(params)
        source_image = params.get("source_image_ref") if isinstance(params.get("source_image_ref"), dict) else None
        if not source_image:
            raise ComfyUIError("圖生圖缺少來源圖片")
        workflow["5"] = {
            "class_type": "LoadImage",
            "inputs": {"image": source_image["filename"], "upload": "image"},
        }
        workflow["10"] = {
            "class_type": "VAEEncode",
            "inputs": {"pixels": ["5", 0], "vae": vae_ref},
        }
        positive_ref = ["6", 0]
        negative_ref = ["7", 0]
        positive_ref, negative_ref, next_node_id = self._attach_controlnet(
            workflow,
            params,
            positive_ref=positive_ref,
            negative_ref=negative_ref,
            next_node_id=next_node_id,
        )
        workflow["3"] = {
            "class_type": "KSampler",
            "inputs": {
                "seed": int(params["seed"]),
                "steps": int(params["steps"]),
                "cfg": float(params["cfg"]),
                "sampler_name": params["sampler_name"],
                "scheduler": params["scheduler"],
                "denoise": float(params.get("denoise_strength") or 0.65),
                "model": final_model,
                "positive": positive_ref,
                "negative": negative_ref,
                "latent_image": ["10", 0],
            },
        }
        workflow["8"] = {
            "class_type": "VAEDecode",
            "inputs": {"samples": ["3", 0], "vae": vae_ref},
        }
        workflow["9"] = {
            "class_type": "SaveImage",
            "inputs": {
                "filename_prefix": params.get("filename_prefix") or "hackme_web",
                "images": ["8", 0],
            },
        }
        return workflow

    def build_inpaint_workflow(self, params):
        workflow, final_model, _final_clip, vae_ref, next_node_id = self._build_text_to_image_base(params)
        source_image = params.get("source_image_ref") if isinstance(params.get("source_image_ref"), dict) else None
        mask_image = params.get("mask_image_ref") if isinstance(params.get("mask_image_ref"), dict) else None
        if not source_image or not mask_image:
            raise ComfyUIError("局部重繪缺少來源圖片或遮罩")
        workflow["5"] = {
            "class_type": "LoadImage",
            "inputs": {"image": source_image["filename"], "upload": "image"},
        }
        workflow["11"] = {
            "class_type": "LoadImageMask",
            "inputs": {"image": mask_image["filename"], "channel": "alpha"},
        }
        workflow["10"] = {
            "class_type": "VAEEncodeForInpaint",
            "inputs": {"pixels": ["5", 0], "mask": ["11", 0], "vae": vae_ref, "grow_mask_by": 6},
        }
        positive_ref = ["6", 0]
        negative_ref = ["7", 0]
        positive_ref, negative_ref, next_node_id = self._attach_controlnet(
            workflow,
            params,
            positive_ref=positive_ref,
            negative_ref=negative_ref,
            next_node_id=next_node_id,
        )
        workflow["3"] = {
            "class_type": "KSampler",
            "inputs": {
                "seed": int(params["seed"]),
                "steps": int(params["steps"]),
                "cfg": float(params["cfg"]),
                "sampler_name": params["sampler_name"],
                "scheduler": params["scheduler"],
                "denoise": float(params.get("denoise_strength") or 0.8),
                "model": final_model,
                "positive": positive_ref,
                "negative": negative_ref,
                "latent_image": ["10", 0],
            },
        }
        workflow["8"] = {
            "class_type": "VAEDecode",
            "inputs": {"samples": ["3", 0], "vae": vae_ref},
        }
        workflow["9"] = {
            "class_type": "SaveImage",
            "inputs": {
                "filename_prefix": params.get("filename_prefix") or "hackme_web",
                "images": ["8", 0],
            },
        }
        return workflow

    def build_outpaint_workflow(self, params):
        workflow, final_model, _final_clip, vae_ref, next_node_id = self._build_text_to_image_base(params)
        source_image = params.get("source_image_ref") if isinstance(params.get("source_image_ref"), dict) else None
        if not source_image:
            raise ComfyUIError("向外延展缺少來源圖片")
        expand = params.get("outpaint") if isinstance(params.get("outpaint"), dict) else {}
        workflow["5"] = {
            "class_type": "LoadImage",
            "inputs": {"image": source_image["filename"], "upload": "image"},
        }
        workflow["10"] = {
            "class_type": "ImagePadForOutpaint",
            "inputs": {
                "image": ["5", 0],
                "left": int(expand.get("left") or 0),
                "top": int(expand.get("top") or 0),
                "right": int(expand.get("right") or 0),
                "bottom": int(expand.get("bottom") or 0),
                "feathering": int(expand.get("feathering") or 24),
            },
        }
        workflow["11"] = {
            "class_type": "VAEEncodeForInpaint",
            "inputs": {"pixels": ["10", 0], "mask": ["10", 1], "vae": vae_ref, "grow_mask_by": 6},
        }
        positive_ref = ["6", 0]
        negative_ref = ["7", 0]
        positive_ref, negative_ref, next_node_id = self._attach_controlnet(
            workflow,
            params,
            positive_ref=positive_ref,
            negative_ref=negative_ref,
            next_node_id=next_node_id,
        )
        workflow["3"] = {
            "class_type": "KSampler",
            "inputs": {
                "seed": int(params["seed"]),
                "steps": int(params["steps"]),
                "cfg": float(params["cfg"]),
                "sampler_name": params["sampler_name"],
                "scheduler": params["scheduler"],
                "denoise": float(params.get("denoise_strength") or 0.9),
                "model": final_model,
                "positive": positive_ref,
                "negative": negative_ref,
                "latent_image": ["11", 0],
            },
        }
        workflow["8"] = {
            "class_type": "VAEDecode",
            "inputs": {"samples": ["3", 0], "vae": vae_ref},
        }
        workflow["9"] = {
            "class_type": "SaveImage",
            "inputs": {
                "filename_prefix": params.get("filename_prefix") or "hackme_web",
                "images": ["8", 0],
            },
        }
        return workflow

    def build_upscale_workflow(self, params):
        source_image = params.get("source_image_ref") if isinstance(params.get("source_image_ref"), dict) else None
        upscale_model = str(params.get("upscale_model") or "").strip()
        if not source_image:
            raise ComfyUIError("放大修復缺少來源圖片")
        if not upscale_model:
            raise ComfyUIError("請選擇放大模型")
        workflow = {
            "3": {
                "class_type": "UpscaleModelLoader",
                "inputs": {"model_name": upscale_model},
            },
            "4": {
                "class_type": "LoadImage",
                "inputs": {"image": source_image["filename"], "upload": "image"},
            },
            "5": {
                "class_type": "ImageUpscaleWithModel",
                "inputs": {"upscale_model": ["3", 0], "image": ["4", 0]},
            },
            "9": {
                "class_type": "SaveImage",
                "inputs": {
                    "filename_prefix": params.get("filename_prefix") or "hackme_web",
                    "images": ["5", 0],
                },
            },
        }
        return workflow

    def build_generation_workflow(self, params):
        mode = str(params.get("generation_mode") or "txt2img").strip().lower()
        if mode == "txt2img":
            return self.build_text_to_image_workflow(params)
        if mode == "img2img":
            return self.build_image_to_image_workflow(params)
        if mode == "inpaint":
            return self.build_inpaint_workflow(params)
        if mode == "outpaint":
            return self.build_outpaint_workflow(params)
        if mode == "upscale":
            return self.build_upscale_workflow(params)
        raise ComfyUIError("ComfyUI 產圖模式不支援")

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

    def wait_for_images(self, prompt_id, *, timeout_seconds=1800, poll_interval=1.0, expected_count=1, websocket_conn=None, progress_callback=None):
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

    def wait_for_first_image(self, prompt_id, *, timeout_seconds=1800, poll_interval=1.0):
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

    def generate_from_workflow(self, workflow, *, timeout_seconds=1800, expected_count=1, progress_callback=None):
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
                expected_count=expected_count,
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

    def generate_image(self, params, *, timeout_seconds=1800, progress_callback=None):
        workflow = self.build_generation_workflow(params)
        return self.generate_from_workflow(
            workflow,
            timeout_seconds=timeout_seconds,
            expected_count=int(params.get("batch_size") or 1),
            progress_callback=progress_callback,
        )
