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


def _linked_ref(workflow: Mapping[str, Any], value: Any) -> tuple[Mapping[str, Any], int] | None:
    if not (isinstance(value, list) and len(value) == 2):
        return None
    node = workflow.get(str(value[0]))
    if not isinstance(node, Mapping):
        return None
    try:
        output_slot = int(value[1])
    except (TypeError, ValueError):
        output_slot = 0
    return node, output_slot


def _linked_model_name(workflow: Mapping[str, Any], value: Any, *, depth: int = 0) -> str:
    if depth > 6:
        return ""
    linked = _linked_ref(workflow, value)
    if not linked:
        return ""
    node, _output_slot = linked
    if not isinstance(node, Mapping):
        return ""
    class_type = str(node.get("class_type") or "").strip()
    inputs = _node_inputs(node)
    if class_type == "UNETLoader":
        return _clean_text(inputs.get("unet_name"))
    if class_type == "LoraLoaderModelOnly":
        lora_name = _clean_text(inputs.get("lora_name"))
        upstream = _linked_model_name(workflow, inputs.get("model"), depth=depth + 1)
        return f"{upstream} {lora_name}".strip()
    if class_type == "ModelSamplingAuraFlow":
        return _linked_model_name(workflow, inputs.get("model"), depth=depth + 1)
    if class_type == "ComfySwitchNode":
        selected = "on_true" if bool(inputs.get("switch")) else "on_false"
        return _linked_model_name(workflow, inputs.get(selected), depth=depth + 1)
    return ""


def _sync_qwen_2512_lightning_switches(workflow: Mapping[str, Any]) -> Any:
    """Keep the official Qwen 2512 Lightning switches in a consistent preset.

    The source template splits one logical choice across three ComfySwitchNode
    instances: steps 50/4, cfg 4/1, and base/Lightning-LoRA model. If a user
    flips only part of that trio, Qwen can sample with an unstable half-preset
    and produce NaN/Inf pixels at SaveImage time.
    """
    step_switch_id = ""
    cfg_switch_id = ""
    model_switch_id = ""
    for node_id, node in workflow.items():
        if not isinstance(node, Mapping):
            continue
        if str(node.get("class_type") or "").strip() != "ComfySwitchNode":
            continue
        inputs = _node_inputs(node)
        on_false = inputs.get("on_false")
        on_true = inputs.get("on_true")
        if on_false == 50 and on_true == 4:
            step_switch_id = str(node_id)
        elif on_false == 4 and on_true == 1:
            cfg_switch_id = str(node_id)
        else:
            false_model = _linked_model_name(workflow, on_false)
            true_model = _linked_model_name(workflow, on_true)
            if (
                "qwen_image_2512" in false_model
                and "qwen-image-lightning-4steps" in true_model
            ):
                model_switch_id = str(node_id)
    switch_ids = [step_switch_id, cfg_switch_id, model_switch_id]
    if not all(switch_ids):
        return workflow
    enabled = any(bool(_node_inputs(workflow[switch_id]).get("switch")) for switch_id in switch_ids)
    if all(bool(_node_inputs(workflow[switch_id]).get("switch")) == enabled for switch_id in switch_ids):
        return workflow
    patched = deepcopy(dict(workflow))
    for switch_id in switch_ids:
        patched[switch_id].setdefault("inputs", {})["switch"] = enabled
    return patched


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
    patched_defaults = None
    for node_id, node in workflow.items():
        if not isinstance(node, Mapping):
            continue
        if str(node.get("class_type") or "").strip() != "StringConcatenate":
            continue
        inputs = _node_inputs(node)
        if "delimiter" in inputs:
            continue
        if patched_defaults is None:
            patched_defaults = deepcopy(dict(workflow))
        patched_defaults[str(node_id)].setdefault("inputs", {})["delimiter"] = ""
    if patched_defaults is not None:
        workflow = patched_defaults

    workflow = _sync_qwen_2512_lightning_switches(workflow)

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
