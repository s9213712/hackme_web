"""Workflow summary and inference helpers for ComfyUI JSON graphs."""

from services.comfyui.constants import CONTROLNET_TYPE_DEFINITIONS
from services.comfyui.validation.rules import WORKFLOW_BLOCKED_CLASS_RE, WorkflowValidationError


CONTROLNET_TYPE_ALIASES = {
    "canny": "canny",
    "depth": "depth",
    "openpose": "openpose",
    "pose": "openpose",
    "lineart": "lineart",
    "scribble": "scribble",
    "softedge": "softedge",
    "soft_edge": "softedge",
    "tile": "tile",
}


def infer_controlnet_type_from_name(name):
    normalized = str(name or "").strip().lower().replace("-", "_")
    if not normalized:
        return ""
    for token, control_type in CONTROLNET_TYPE_ALIASES.items():
        if token in normalized:
            return control_type
    for control_type in CONTROLNET_TYPE_DEFINITIONS:
        if control_type in normalized:
            return control_type
    return ""


def extract_workflow_summary(workflow_json):
    if not isinstance(workflow_json, dict):
        raise WorkflowValidationError("workflow JSON 必須是物件")
    required_models = []
    required_loras = []
    required_controlnets = []
    model_seen = set()
    lora_seen = set()
    control_seen = set()
    text_nodes = []
    generation_mode = "txt2img"
    default_params = {
        "generation_mode": "txt2img",
        "model": "",
        "vae": "",
        "prompt": "",
        "negative_prompt": "",
        "width": 0,
        "height": 0,
        "steps": 0,
        "cfg": 0,
        "seed": 0,
        "batch_size": 1,
        "sampler_name": "",
        "scheduler": "",
        "denoise_strength": 0,
        "upscale_model": "",
        "loras": [],
        "controlnet": None,
    }

    def add_model(kind, name):
        text = str(name or "").strip()
        if not text:
            return
        key = (kind, text)
        if key in model_seen:
            return
        model_seen.add(key)
        required_models.append({"kind": kind, "name": text})

    def add_lora(name, *, strength_model=None, strength_clip=None):
        text = str(name or "").strip()
        if not text or text in lora_seen:
            return
        lora_seen.add(text)
        entry = {"name": text}
        if strength_model is not None:
            entry["strength_model"] = strength_model
        if strength_clip is not None:
            entry["strength_clip"] = strength_clip
        required_loras.append(entry)
        default_params["loras"].append({
            "name": text,
            "strength_model": strength_model if strength_model is not None else 1,
            "strength_clip": strength_clip if strength_clip is not None else 1,
        })

    def add_controlnet(name, *, control_type="", preprocessor=""):
        text = str(name or "").strip()
        if not text:
            return
        key = (text, control_type or "", preprocessor or "")
        if key in control_seen:
            return
        control_seen.add(key)
        entry = {"name": text}
        if control_type:
            entry["type"] = control_type
        if preprocessor:
            entry["preprocessor"] = preprocessor
        required_controlnets.append(entry)
        if default_params["controlnet"] is None:
            default_params["controlnet"] = {
                "type": control_type or infer_controlnet_type_from_name(text),
                "model_name": text,
                "preprocessor": preprocessor or "",
                "strength": 1,
                "start_percent": 0,
                "end_percent": 1,
            }

    for node_id, node in workflow_json.items():
        if not isinstance(node, dict):
            raise WorkflowValidationError(f"workflow node {node_id} 格式不正確")
        class_type = str(node.get("class_type") or "").strip()
        if not class_type:
            raise WorkflowValidationError(f"workflow node {node_id} 缺少 class_type")
        if WORKFLOW_BLOCKED_CLASS_RE.search(class_type):
            raise WorkflowValidationError(f"workflow node {node_id} 使用了不允許的節點：{class_type}")
        inputs = node.get("inputs")
        if not isinstance(inputs, dict):
            raise WorkflowValidationError(f"workflow node {node_id} 缺少 inputs")
        lower_class = class_type.lower()

        ckpt_name = inputs.get("ckpt_name")
        if isinstance(ckpt_name, str) and ckpt_name.strip():
            add_model("checkpoint", ckpt_name)
            if not default_params["model"]:
                default_params["model"] = ckpt_name.strip()

        vae_name = inputs.get("vae_name")
        if isinstance(vae_name, str) and vae_name.strip():
            add_model("vae", vae_name)
            if not default_params["vae"]:
                default_params["vae"] = vae_name.strip()

        if "loraloader" in lower_class:
            add_lora(
                inputs.get("lora_name"),
                strength_model=inputs.get("strength_model"),
                strength_clip=inputs.get("strength_clip"),
            )

        if "controlnetloader" in lower_class:
            add_controlnet(
                inputs.get("control_net_name") or inputs.get("model_name"),
                control_type=infer_controlnet_type_from_name(inputs.get("control_net_name") or inputs.get("model_name")),
            )

        if "upscalemodelloader" in lower_class:
            add_model("upscale", inputs.get("model_name"))
            if not default_params["upscale_model"] and isinstance(inputs.get("model_name"), str):
                default_params["upscale_model"] = inputs.get("model_name").strip()

        if "ksampler" in lower_class:
            if isinstance(inputs.get("seed"), (int, float)):
                default_params["seed"] = int(inputs.get("seed"))
            if isinstance(inputs.get("steps"), (int, float)):
                default_params["steps"] = int(inputs.get("steps"))
            if isinstance(inputs.get("cfg"), (int, float)):
                default_params["cfg"] = float(inputs.get("cfg"))
            if isinstance(inputs.get("sampler_name"), str):
                default_params["sampler_name"] = inputs.get("sampler_name").strip()
            if isinstance(inputs.get("scheduler"), str):
                default_params["scheduler"] = inputs.get("scheduler").strip()
            if isinstance(inputs.get("denoise"), (int, float)):
                default_params["denoise_strength"] = float(inputs.get("denoise"))

        if lower_class == "cliptextencode" and isinstance(inputs.get("text"), str):
            text_nodes.append(inputs.get("text").strip())

        if lower_class == "emptylatentimage":
            if isinstance(inputs.get("width"), (int, float)):
                default_params["width"] = int(inputs.get("width"))
            if isinstance(inputs.get("height"), (int, float)):
                default_params["height"] = int(inputs.get("height"))
            if isinstance(inputs.get("batch_size"), (int, float)):
                default_params["batch_size"] = max(1, int(inputs.get("batch_size")))

        if lower_class == "loadimagemask":
            generation_mode = "inpaint"
        elif lower_class == "imagepadforoutpaint":
            generation_mode = "outpaint"
        elif lower_class == "imageupscalewithmodel":
            generation_mode = "upscale"
        elif lower_class == "loadimage" and generation_mode == "txt2img":
            generation_mode = "img2img"

        if isinstance(inputs.get("preprocessor"), str) and default_params["controlnet"]:
            default_params["controlnet"]["preprocessor"] = inputs.get("preprocessor").strip()

    default_params["generation_mode"] = generation_mode
    if generation_mode == "upscale":
        default_params["prompt"] = ""
        default_params["negative_prompt"] = ""
    elif text_nodes:
        default_params["prompt"] = text_nodes[0]
        default_params["negative_prompt"] = text_nodes[1] if len(text_nodes) > 1 else ""
    if default_params["controlnet"] and not default_params["controlnet"].get("type"):
        default_params["controlnet"]["type"] = infer_controlnet_type_from_name(default_params["controlnet"].get("model_name"))

    return {
        "required_models": required_models,
        "required_loras": required_loras,
        "required_controlnets": required_controlnets,
        "default_params": default_params,
        "node_count": len(workflow_json),
    }
