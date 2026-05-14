"""Detection and payload helpers for ComfyUI paid/API nodes."""

from __future__ import annotations

COMFYUI_ACCOUNT_EXTRA_DATA_KEY = "api_key_comfy_org"

API_NODE_CLASS_MARKERS = (
    "apikey",
    "api_key",
    "api node",
    "apinode",
    "comfyapi",
    "comfy_api",
    "fluxpro",
    "flux_pro",
    "flux pro",
    "gptimage",
    "openai",
    "stability",
    "runway",
    "kling",
    "luma",
    "minimax",
    "ideogram",
    "recraft",
    "pixverse",
    "veo",
)

API_NODE_INPUT_MARKERS = (
    "api_key",
    "apikey",
    "auth_token",
    "access_token",
    "bearer_token",
)


def _compact(value):
    return str(value or "").strip().lower().replace("-", "").replace("_", "").replace(" ", "")


def _node_class_type(node):
    if not isinstance(node, dict):
        return ""
    return str(node.get("class_type") or "").strip()


def _object_info_for_class(object_info, class_type):
    if not isinstance(object_info, dict) or not class_type:
        return {}
    info = object_info.get(class_type)
    return info if isinstance(info, dict) else {}


def _node_looks_like_api_node(class_type, node, info=None):
    compact_class = _compact(class_type)
    lowered_class = str(class_type or "").strip().lower()
    if any(_compact(marker) in compact_class or marker in lowered_class for marker in API_NODE_CLASS_MARKERS):
        return True
    info = info if isinstance(info, dict) else {}
    category = str(info.get("category") or info.get("display_category") or "").lower()
    if any(marker in category for marker in ("api", "partner", "comfy org", "comfyui account")):
        return True
    inputs = {}
    if isinstance(node, dict):
        inputs.update(node.get("inputs") if isinstance(node.get("inputs"), dict) else {})
    info_inputs = info.get("input") if isinstance(info.get("input"), dict) else {}
    for section in ("required", "optional", "hidden"):
        values = info_inputs.get(section)
        if isinstance(values, dict):
            inputs.update(values)
    return any(_compact(marker) in _compact(name) for name in inputs for marker in API_NODE_INPUT_MARKERS)


def detect_paid_api_nodes(workflow_json, *, object_info=None):
    """Return a safe summary of nodes that likely need a ComfyUI Account API key."""
    if not isinstance(workflow_json, dict):
        return {"required": False, "nodes": []}
    nodes = []
    for node_id, node in workflow_json.items():
        if not isinstance(node, dict):
            continue
        class_type = _node_class_type(node)
        info = _object_info_for_class(object_info, class_type)
        if not _node_looks_like_api_node(class_type, node, info):
            continue
        nodes.append({
            "node_id": str(node_id),
            "class_type": class_type,
            "title": str(node.get("_meta", {}).get("title") or info.get("display_name") or class_type),
        })
    return {"required": bool(nodes), "nodes": nodes}


def build_comfyui_account_extra_data(api_key):
    api_key = str(api_key or "").strip()
    if not api_key:
        return {}
    return {COMFYUI_ACCOUNT_EXTRA_DATA_KEY: api_key}
