"""Compatibility fixes for known ComfyUI workflow-template drift."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping


def _node_inputs(node: Mapping[str, Any]) -> Mapping[str, Any]:
    inputs = node.get("inputs") if isinstance(node, Mapping) else None
    return inputs if isinstance(inputs, Mapping) else {}


def _clean_text(value: Any) -> str:
    return str(value or "").strip().lower().replace("\\", "/")


def _workflow_uses_qwen_image_vae(workflow: Mapping[str, Any]) -> bool:
    for node in workflow.values():
        if not isinstance(node, Mapping):
            continue
        if str(node.get("class_type") or "").strip() != "VAELoader":
            continue
        vae_name = _clean_text(_node_inputs(node).get("vae_name"))
        if "qwen_image_vae" in vae_name:
            return True
    return False


def _next_node_id(workflow: Mapping[str, Any]) -> str:
    numeric_ids = []
    for node_id in workflow.keys():
        try:
            numeric_ids.append(int(str(node_id)))
        except ValueError:
            continue
    if numeric_ids:
        candidate = max(numeric_ids) + 1
        while str(candidate) in workflow:
            candidate += 1
        return str(candidate)
    candidate = 1
    while f"compat_{candidate}" in workflow:
        candidate += 1
    return f"compat_{candidate}"


def _sampler_model_link(node: Mapping[str, Any]) -> list[Any] | None:
    model = _node_inputs(node).get("model")
    if isinstance(model, list) and len(model) == 2:
        return model
    return None


def _node_class(workflow: Mapping[str, Any], node_id: Any) -> str:
    node = workflow.get(str(node_id))
    return str((node or {}).get("class_type") or "").strip() if isinstance(node, Mapping) else ""


def apply_workflow_compatibility_fixes(workflow: Any) -> Any:
    """Return a workflow with narrow fixes for known broken legacy templates.

    Older stored ANIMA/Qwen-image-derived templates may wire UNETLoader directly
    into KSampler while using qwen_image_vae. Current working examples place
    ModelSamplingAuraFlow between the model loader and sampler. Without it,
    ComfyUI can finish sampling and then crash in VAEDecode with a latent/VAE
    shape mismatch. This function patches only that specific missing adapter.
    """
    if not isinstance(workflow, Mapping) or not workflow:
        return workflow
    if not _workflow_uses_qwen_image_vae(workflow):
        return workflow

    patched = None
    for node_id, node in workflow.items():
        if not isinstance(node, Mapping):
            continue
        if str(node.get("class_type") or "").strip() not in {"KSampler", "KSamplerAdvanced"}:
            continue
        model_link = _sampler_model_link(node)
        if not model_link:
            continue
        source_id = str(model_link[0])
        source_class = _node_class(workflow, source_id)
        if source_class == "ModelSamplingAuraFlow":
            continue
        if source_class != "UNETLoader":
            continue
        if patched is None:
            patched = deepcopy(dict(workflow))
        adapter_id = _next_node_id(patched)
        patched[adapter_id] = {
            "class_type": "ModelSamplingAuraFlow",
            "inputs": {
                "model": [source_id, 0],
                "shift": 3.0,
            },
            "_meta": {"title": "Model Shift / AuraFlow"},
        }
        patched[str(node_id)]["inputs"]["model"] = [adapter_id, 0]

    return patched if patched is not None else workflow


__all__ = ["apply_workflow_compatibility_fixes"]
