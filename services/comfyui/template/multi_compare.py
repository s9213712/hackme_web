"""Dynamic helpers for the experimental multi-checkpoint compare template."""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any, Mapping


MULTI_COMPARE_CHECKPOINTS_TEST_ID = "origin_multi_compare_checkpoints_test"
MULTI_COMPARE_WORKFLOW_IDS = frozenset({MULTI_COMPARE_CHECKPOINTS_TEST_ID})
MAX_MULTI_COMPARE_CHECKPOINTS = 8
MAX_MULTI_COMPARE_LORAS = 8

_BASE_BRANCHES = (
    {"ckpt": "4", "sampler": "3", "decode": "8", "preview": "51"},
    {"ckpt": "48", "sampler": "17", "decode": "18", "preview": "50"},
)
_POSITIVE_NODE_ID = "6"
_NEGATIVE_NODE_ID = "7"
_SHARED_SAMPLER_SOURCE_ID = "3"


class MultiCompareWorkflowError(ValueError):
    """Raised when a multi-compare run request is malformed."""


@dataclass
class MultiCompareExpansion:
    workflow: dict[str, Any]
    user_inputs: dict[str, dict[str, Any]]
    output_labels: list[str] = field(default_factory=list)


def is_multi_compare_workflow_id(bundle_id: Any) -> bool:
    return str(bundle_id or "").strip() in MULTI_COMPARE_WORKFLOW_IDS


def _clean_text(value: Any, *, limit: int = 260) -> str:
    return str(value or "").strip()[:limit]


def _number(value: Any, default: float = 1.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = default
    if number < -2:
        return -2.0
    if number > 2:
        return 2.0
    return round(number, 4)


def _normalize_spec(spec: Mapping[str, Any] | None) -> tuple[list[str], list[dict[str, Any]]]:
    if not isinstance(spec, Mapping):
        raise MultiCompareWorkflowError("multi-compare 設定格式錯誤")
    checkpoints = [
        _clean_text(item)
        for item in (spec.get("checkpoints") if isinstance(spec.get("checkpoints"), list) else [])
    ]
    checkpoints = [item for item in checkpoints if item]
    if len(checkpoints) < 2:
        raise MultiCompareWorkflowError("Multi-Compare 至少需要選擇 2 個大模型")
    if len(checkpoints) > MAX_MULTI_COMPARE_CHECKPOINTS:
        raise MultiCompareWorkflowError(f"Multi-Compare 最多一次比較 {MAX_MULTI_COMPARE_CHECKPOINTS} 個大模型")

    seen_loras = set()
    loras = []
    for item in (spec.get("loras") if isinstance(spec.get("loras"), list) else []):
        if not isinstance(item, Mapping):
            continue
        name = _clean_text(item.get("name"))
        if not name or name in seen_loras:
            continue
        seen_loras.add(name)
        loras.append({
            "name": name,
            "strength_model": _number(item.get("strength_model"), 1.0),
            "strength_clip": _number(item.get("strength_clip"), 1.0),
        })
        if len(loras) >= MAX_MULTI_COMPARE_LORAS:
            break
    return checkpoints, loras


def _require_node(workflow: Mapping[str, Any], node_id: str) -> dict[str, Any]:
    node = workflow.get(str(node_id))
    if not isinstance(node, dict) or not isinstance(node.get("inputs"), dict):
        raise MultiCompareWorkflowError(f"Multi-Compare 基礎模板缺少必要 node {node_id}")
    return node


def _dynamic_branch_ids(branch_index: int) -> dict[str, str]:
    base = 9000 + branch_index * 100
    return {
        "ckpt": str(base),
        "sampler": str(base + 1),
        "decode": str(base + 2),
        "preview": str(base + 3),
    }


def _lora_node_id(branch_index: int, lora_index: int) -> str:
    return str(8000 + branch_index * 100 + lora_index)


def _ensure_patch(user_inputs: dict[str, dict[str, Any]], node_id: str) -> dict[str, Any]:
    patch = user_inputs.setdefault(str(node_id), {})
    if not isinstance(patch, dict):
        patch = {}
        user_inputs[str(node_id)] = patch
    return patch


def _shared_sampler_values(workflow: Mapping[str, Any], user_inputs: Mapping[str, Any]) -> dict[str, Any]:
    source_node = _require_node(workflow, _SHARED_SAMPLER_SOURCE_ID)
    source_inputs = source_node.get("inputs") or {}
    source_patch = user_inputs.get(_SHARED_SAMPLER_SOURCE_ID)
    source_patch = source_patch if isinstance(source_patch, Mapping) else {}
    values = {}
    for key in ("seed", "steps", "cfg", "sampler_name", "scheduler", "denoise"):
        if key in source_patch:
            values[key] = source_patch[key]
        elif key in source_inputs:
            values[key] = source_inputs[key]
    return values


def _set_meta_title(node: dict[str, Any], title: str) -> None:
    meta = node.get("_meta") if isinstance(node.get("_meta"), dict) else {}
    meta = dict(meta)
    meta["title"] = title
    node["_meta"] = meta


def _comparison_label(index: int, checkpoint: str, loras: list[dict[str, Any]]) -> str:
    base = checkpoint.replace("\\", "/").rsplit("/", 1)[-1] or checkpoint
    if not loras:
        return f"比較 #{index + 1}: {base}"
    lora_names = ", ".join(item["name"].replace("\\", "/").rsplit("/", 1)[-1] for item in loras)
    return f"比較 #{index + 1}: {base} + LoRA {lora_names}"


def _add_lora_chain(
    workflow: dict[str, Any],
    user_inputs: dict[str, dict[str, Any]],
    *,
    branch_index: int,
    checkpoint_node_id: str,
    loras: list[dict[str, Any]],
) -> tuple[list[Any], list[Any]]:
    model_source: list[Any] = [str(checkpoint_node_id), 0]
    clip_source: list[Any] = [str(checkpoint_node_id), 1]
    for lora_index, lora in enumerate(loras):
        node_id = _lora_node_id(branch_index, lora_index)
        workflow[node_id] = {
            "class_type": "LoraLoader",
            "inputs": {
                "model": model_source,
                "clip": clip_source,
                "lora_name": lora["name"],
                "strength_model": lora["strength_model"],
                "strength_clip": lora["strength_clip"],
            },
            "_meta": {"title": f"比較 #{branch_index + 1} LoRA #{lora_index + 1}"},
        }
        _ensure_patch(user_inputs, node_id).update({
            "lora_name": lora["name"],
            "strength_model": lora["strength_model"],
            "strength_clip": lora["strength_clip"],
        })
        model_source = [node_id, 0]
        clip_source = [node_id, 1]
    return model_source, clip_source


def expand_multi_compare_workflow(
    workflow: Mapping[str, Any],
    user_inputs: Mapping[str, Any] | None,
    spec: Mapping[str, Any] | None,
) -> MultiCompareExpansion:
    """Clone the base two-checkpoint graph into N compare branches.

    The stored template remains a normal two-branch ComfyUI API prompt. This
    helper is only used at run time for the experimental test template.
    """
    checkpoints, loras = _normalize_spec(spec)
    patched_workflow: dict[str, Any] = copy.deepcopy(dict(workflow or {}))
    patched_user_inputs: dict[str, dict[str, Any]] = copy.deepcopy(dict(user_inputs or {}))
    shared_sampler = _shared_sampler_values(patched_workflow, patched_user_inputs)

    for branch in _BASE_BRANCHES:
        for node_id in branch.values():
            _require_node(patched_workflow, node_id)

    output_labels = []
    branches = []
    for index, checkpoint in enumerate(checkpoints):
        if index < len(_BASE_BRANCHES):
            ids = dict(_BASE_BRANCHES[index])
        else:
            ids = _dynamic_branch_ids(index)
            patched_workflow[ids["ckpt"]] = copy.deepcopy(patched_workflow[_BASE_BRANCHES[1]["ckpt"]])
            patched_workflow[ids["sampler"]] = copy.deepcopy(patched_workflow[_BASE_BRANCHES[1]["sampler"]])
            patched_workflow[ids["decode"]] = copy.deepcopy(patched_workflow[_BASE_BRANCHES[1]["decode"]])
            patched_workflow[ids["preview"]] = copy.deepcopy(patched_workflow[_BASE_BRANCHES[1]["preview"]])
        branches.append(ids)

        ckpt_node = _require_node(patched_workflow, ids["ckpt"])
        ckpt_node["inputs"]["ckpt_name"] = checkpoint
        _set_meta_title(ckpt_node, f"比較標的 #{index + 1}")
        _ensure_patch(patched_user_inputs, ids["ckpt"])["ckpt_name"] = checkpoint

        model_source, clip_source = _add_lora_chain(
            patched_workflow,
            patched_user_inputs,
            branch_index=index,
            checkpoint_node_id=ids["ckpt"],
            loras=loras,
        )

        sampler_node = _require_node(patched_workflow, ids["sampler"])
        sampler_inputs = sampler_node["inputs"]
        sampler_inputs.update(shared_sampler)
        sampler_inputs["model"] = model_source
        sampler_inputs["latent_image"] = ["5", 0]
        sampler_inputs["positive"] = [_POSITIVE_NODE_ID, 0]
        sampler_inputs["negative"] = [_NEGATIVE_NODE_ID, 0]
        _set_meta_title(sampler_node, f"比較取樣 #{index + 1}")
        _ensure_patch(patched_user_inputs, ids["sampler"]).update(shared_sampler)

        decode_node = _require_node(patched_workflow, ids["decode"])
        decode_node["inputs"]["samples"] = [ids["sampler"], 0]
        decode_node["inputs"]["vae"] = [ids["ckpt"], 2]
        _set_meta_title(decode_node, f"比較解碼 #{index + 1}")

        label = _comparison_label(index, checkpoint, loras)
        preview_node = _require_node(patched_workflow, ids["preview"])
        preview_node["inputs"]["images"] = [ids["decode"], 0]
        _set_meta_title(preview_node, label)
        output_labels.append(label)

        if index == 0 and loras:
            for text_node_id in (_POSITIVE_NODE_ID, _NEGATIVE_NODE_ID):
                text_node = _require_node(patched_workflow, text_node_id)
                text_node["inputs"]["clip"] = clip_source

    # Remove any stale base branch beyond the requested count is unnecessary:
    # the base template has exactly two branches and the minimum request is two.
    return MultiCompareExpansion(
        workflow=patched_workflow,
        user_inputs=patched_user_inputs,
        output_labels=output_labels,
    )


__all__ = [
    "MAX_MULTI_COMPARE_CHECKPOINTS",
    "MAX_MULTI_COMPARE_LORAS",
    "MULTI_COMPARE_CHECKPOINTS_TEST_ID",
    "MULTI_COMPARE_WORKFLOW_IDS",
    "MultiCompareExpansion",
    "MultiCompareWorkflowError",
    "expand_multi_compare_workflow",
    "is_multi_compare_workflow_id",
]
