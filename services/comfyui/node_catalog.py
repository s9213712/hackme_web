"""Safe ComfyUI /object_info summaries for the workflow visual editor."""

from __future__ import annotations

from services.comfyui.api_nodes import detect_paid_api_nodes


LINK_INPUT_TYPES = {
    "MODEL",
    "CLIP",
    "VAE",
    "LATENT",
    "IMAGE",
    "MASK",
    "CONDITIONING",
    "CONTROL_NET",
    "UPSCALE_MODEL",
    "AUDIO",
    "VIDEO",
}


def _text(value, limit=160):
    raw = str(value or "").strip()
    if len(raw) <= limit:
        return raw
    return f"{raw[:limit - 1]}..."


def _node_info(raw):
    return raw if isinstance(raw, dict) else {}


def _section_inputs(info):
    inputs = {}
    input_info = info.get("input") if isinstance(info.get("input"), dict) else {}
    for section in ("required", "optional"):
        values = input_info.get(section)
        if not isinstance(values, dict):
            continue
        for name, spec in values.items():
            inputs[str(name)] = _input_spec(str(name), spec)
    return inputs


def _raw_input_type(raw_spec):
    if not isinstance(raw_spec, (list, tuple)) or not raw_spec:
        return ""
    first = raw_spec[0]
    if isinstance(first, str):
        return first
    return ""


def _enum_options(raw_spec):
    if not isinstance(raw_spec, (list, tuple)) or not raw_spec:
        return []
    first = raw_spec[0]
    if isinstance(first, list):
        return [_text(item, 120) for item in first if str(item or "").strip()][:120]
    if len(raw_spec) > 1 and isinstance(raw_spec[1], dict):
        options = raw_spec[1].get("options")
        if isinstance(options, list):
            return [_text(item, 120) for item in options if str(item or "").strip()][:120]
    return []


def _metadata(raw_spec):
    if isinstance(raw_spec, (list, tuple)) and len(raw_spec) > 1 and isinstance(raw_spec[1], dict):
        return raw_spec[1]
    return {}


def _input_spec(name, raw_spec):
    raw_type = _raw_input_type(raw_spec).strip()
    normalized = raw_type.upper()
    options = _enum_options(raw_spec)
    meta = _metadata(raw_spec)
    if normalized in LINK_INPUT_TYPES:
        return {"type": "link", "label": raw_type or name, "raw_type": raw_type}
    if options:
        return {
            "type": "select",
            "label": name,
            "raw_type": "enum",
            "options": options,
        }
    if normalized in {"INT", "FLOAT"}:
        item = {"type": "number", "label": name, "raw_type": raw_type}
        if "step" in meta:
            item["step"] = str(meta.get("step") or 1)
        return item
    if normalized == "BOOLEAN":
        return {"type": "checkbox", "label": name, "raw_type": raw_type}
    if "text" in name.lower() or "prompt" in name.lower() or normalized in {"STRING"}:
        return {"type": "textarea" if meta.get("multiline") else "text", "label": name, "raw_type": raw_type}
    return {"type": "text", "label": name, "raw_type": raw_type}


def _outputs(info):
    raw_outputs = info.get("output")
    raw_names = info.get("output_name")
    outputs = []
    if isinstance(raw_names, (list, tuple)):
        outputs = [_text(item, 80) for item in raw_names if str(item or "").strip()]
    if not outputs and isinstance(raw_outputs, (list, tuple)):
        outputs = [_text(item, 80) for item in raw_outputs if str(item or "").strip()]
    return outputs[:24]


def build_node_catalog(object_info, *, limit=500):
    """Build a compact, non-secret node catalog for browser-side builders."""
    if not isinstance(object_info, dict):
        return {"nodes": [], "count": 0, "truncated": False}
    nodes = []
    for class_type, raw_info in sorted(object_info.items(), key=lambda item: str(item[0]).lower()):
        info = _node_info(raw_info)
        class_type = _text(class_type, 180)
        if not class_type:
            continue
        paid_api = detect_paid_api_nodes({"1": {"class_type": class_type, "inputs": {}}}, object_info=object_info)
        inputs = _section_inputs(info)
        node = {
            "class_type": class_type,
            "display_name": _text(info.get("display_name") or class_type, 180),
            "category": _text(info.get("category") or info.get("display_category") or "custom", 180),
            "inputs": inputs,
            "outputs": _outputs(info),
            "paid_api_required": bool(paid_api.get("required")),
        }
        nodes.append(node)
        if len(nodes) >= limit:
            break
    return {
        "nodes": nodes,
        "count": len(nodes),
        "truncated": len(object_info) > len(nodes),
    }
