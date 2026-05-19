"""Runtime breakpoint selection for the Multi-Method Upscale template."""

from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Any, Mapping


MULTI_METHOD_UPSCALE_ID = "origin_multi_method_upscale"
UPSCALE_BREAKPOINT_WORKFLOW_IDS = frozenset({MULTI_METHOD_UPSCALE_ID})
FIRST_UPSCALE_STAGE = "first_upscale"
SECOND_UPSCALE_STAGE = "second_upscale"
UPSCALE_BREAKPOINT_STAGES = frozenset({FIRST_UPSCALE_STAGE, SECOND_UPSCALE_STAGE})

_FIRST_STAGE_OUTPUT_NODE = "76"
_FIRST_STAGE_IMAGE_SOURCE = ["64", 0]
_SECOND_STAGE_OUTPUT_NODE = "76"
_SECOND_STAGE_IMAGE_SOURCE = ["71", 0]
_OUTPUT_NODES_TO_REMOVE = {"66", "73", "93", "94"}
_ORIGIN_DECODE_NODE = "8"
_SECOND_STAGE_NODES = {"71", "77"}


class UpscaleBreakpointError(ValueError):
    """Raised when an upscale breakpoint request is malformed."""


@dataclass
class UpscaleBreakpointSelection:
    workflow: dict[str, Any]
    user_inputs: dict[str, dict[str, Any]]
    stage: str
    output_label: str


def is_upscale_breakpoint_workflow_id(bundle_id: Any) -> bool:
    return str(bundle_id or "").strip() in UPSCALE_BREAKPOINT_WORKFLOW_IDS


def normalize_upscale_breakpoint_stage(spec: Mapping[str, Any] | None) -> str:
    if not isinstance(spec, Mapping):
        return FIRST_UPSCALE_STAGE
    stage = str(spec.get("stage") or spec.get("breakpoint") or FIRST_UPSCALE_STAGE).strip()
    if stage in {"first", "once", "1", "一次放大"}:
        stage = FIRST_UPSCALE_STAGE
    elif stage in {"second", "twice", "2", "二次放大"}:
        stage = SECOND_UPSCALE_STAGE
    if stage not in UPSCALE_BREAKPOINT_STAGES:
        raise UpscaleBreakpointError("Multi-Method Upscale 斷點只能選擇一次放大或二次放大")
    return stage


def _require_node(workflow: Mapping[str, Any], node_id: str) -> dict[str, Any]:
    node = workflow.get(str(node_id))
    if not isinstance(node, dict) or not isinstance(node.get("inputs"), dict):
        raise UpscaleBreakpointError(f"Multi-Method Upscale 基礎模板缺少必要 node {node_id}")
    return node


def _set_meta_title(node: dict[str, Any], title: str) -> None:
    meta = node.get("_meta") if isinstance(node.get("_meta"), dict) else {}
    meta = dict(meta)
    meta["title"] = title
    meta["group_title"] = title
    node["_meta"] = meta


def _prune_user_inputs(
    user_inputs: Mapping[str, Any] | None,
    workflow: Mapping[str, Any],
) -> dict[str, dict[str, Any]]:
    pruned: dict[str, dict[str, Any]] = {}
    for node_id, patch in (user_inputs or {}).items():
        if str(node_id) not in workflow or not isinstance(patch, Mapping):
            continue
        pruned[str(node_id)] = dict(patch)
    return pruned


def apply_upscale_breakpoint(
    workflow: Mapping[str, Any],
    user_inputs: Mapping[str, Any] | None,
    spec: Mapping[str, Any] | None,
) -> UpscaleBreakpointSelection:
    """Return a workflow that stops at the selected upscale breakpoint.

    The stored origin-derived template keeps all nodes for editability. At run
    time we leave exactly one SaveImage output so ComfyUI does not execute the
    origin preview, first-pass preview, and second-pass output together.
    """
    stage = normalize_upscale_breakpoint_stage(spec)
    patched: dict[str, Any] = copy.deepcopy(dict(workflow or {}))
    _require_node(patched, "3")
    _require_node(patched, "61")
    _require_node(patched, "63")
    _require_node(patched, "64")
    output_node = _require_node(patched, _FIRST_STAGE_OUTPUT_NODE)
    if str(output_node.get("class_type") or "") != "SaveImage":
        raise UpscaleBreakpointError("Multi-Method Upscale 基礎模板 node 76 必須是 SaveImage")

    for node_id in _OUTPUT_NODES_TO_REMOVE | {_ORIGIN_DECODE_NODE}:
        patched.pop(node_id, None)

    if stage == FIRST_UPSCALE_STAGE:
        for node_id in _SECOND_STAGE_NODES:
            patched.pop(node_id, None)
        output_node["inputs"]["images"] = list(_FIRST_STAGE_IMAGE_SOURCE)
        _set_meta_title(output_node, "一次放大輸出")
        label = "一次放大"
    else:
        for node_id in _SECOND_STAGE_NODES:
            _require_node(patched, node_id)
        output_node["inputs"]["images"] = list(_SECOND_STAGE_IMAGE_SOURCE)
        _set_meta_title(output_node, "二次放大輸出")
        label = "二次放大"

    return UpscaleBreakpointSelection(
        workflow=patched,
        user_inputs=_prune_user_inputs(user_inputs, patched),
        stage=stage,
        output_label=label,
    )


__all__ = [
    "FIRST_UPSCALE_STAGE",
    "MULTI_METHOD_UPSCALE_ID",
    "SECOND_UPSCALE_STAGE",
    "UPSCALE_BREAKPOINT_WORKFLOW_IDS",
    "UPSCALE_BREAKPOINT_STAGES",
    "UpscaleBreakpointError",
    "UpscaleBreakpointSelection",
    "apply_upscale_breakpoint",
    "is_upscale_breakpoint_workflow_id",
    "normalize_upscale_breakpoint_stage",
]
