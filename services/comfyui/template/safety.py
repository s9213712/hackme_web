"""§7 Safety helpers — allowlist enforcement + filename rewrite + node id allocator.

These helpers run at §10 Gates 3 and 5 (allowlist + safety rewrite). The
LoadImage / cloud-drive remap (§7.3) lives in a separate module that pulls
in the route-layer cloud-drive helpers; that one will land with Phase 4
when we wire it into the run handler.

Spec reference: docs/comfyui/COMFYUI_TEMPLATE_IMPORTER_PLAN.md §7.
"""

from __future__ import annotations

import copy
from typing import Any

from services.comfyui.template.allowlist import (
    CONTROLNET_PREPROCESSOR_ALLOWLIST,
    CORE_ALLOWLIST,
    MEDIA_WORKFLOW_ALLOWLIST,
    ORIGIN_WORKFLOW_ALLOWLIST,
)
from services.comfyui.template.analyzer import WorkflowAnalysis


class SafetyError(ValueError):
    """Raised when a §7 safety check rejects a workflow."""


# ----------------------------------------------------------------------------
# §7.1 enforce_allowlist
# ----------------------------------------------------------------------------


def enforce_allowlist(analysis: WorkflowAnalysis) -> None:
    """Reject the workflow if any class is outside the v1 allowlist."""
    not_allowed = (
        analysis.class_types
        - CORE_ALLOWLIST
        - CONTROLNET_PREPROCESSOR_ALLOWLIST
        - MEDIA_WORKFLOW_ALLOWLIST
        - ORIGIN_WORKFLOW_ALLOWLIST
    )
    if not_allowed:
        raise SafetyError(
            f"workflow 含未授權的節點類型：{sorted(not_allowed)}。"
            f"目前只支援核心節點、ControlNet 標準 preprocessor、以及已審核的影音/大型模型工作流節點。"
            f"完整清單見 docs/comfyui/COMFYUI_TEMPLATE_IMPORTER_PLAN.md §4。"
        )


# ----------------------------------------------------------------------------
# §7.4 next_safe_node_id allocator
# ----------------------------------------------------------------------------


def next_safe_node_id(workflow: dict[str, Any]) -> int:
    """Return an integer node id guaranteed not to collide with any existing key.

    ComfyUI API-format keys are stringified ints. Some workflows leave gaps; some
    use four-digit ids. Allocate ``max(used) + 1`` so that subsequent inserts
    keep growing rather than reusing released slots.
    """
    used: set[int] = set()
    for key in workflow.keys():
        try:
            used.add(int(key))
        except (TypeError, ValueError):
            continue
    return (max(used) + 1) if used else 1


# ----------------------------------------------------------------------------
# §7.2 rewrite_save_image_prefix
# ----------------------------------------------------------------------------


_SAVE_OUTPUT_CLASS_TYPES = {"SaveImage", "SaveVideo"}


def rewrite_save_image_prefix(
    workflow: dict[str, Any],
    *,
    user_id: int,
    run_id: str,
) -> dict[str, Any]:
    """Force output filename prefixes to a per-(user, run) safe value.

    Author-supplied prefixes are not trusted — they could include path
    traversal, leak sibling users' filenames, or collide across runs. We
    rewrite every SaveImage / SaveVideo node's filename_prefix to
    ``hackme/<user_id>/<run_id>``, which keeps outputs isolated per user
    and per run on the ComfyUI side.

    Returns a deep-copied workflow; the input is never mutated.
    """
    if not isinstance(workflow, dict):
        raise SafetyError("workflow 必須是物件 (API format)")
    new_wf = copy.deepcopy(workflow)
    safe_prefix = f"hackme/{int(user_id)}/{_safe_run_id(run_id)}"
    for node_id, node in new_wf.items():
        if not isinstance(node, dict):
            continue
        if str(node.get("class_type") or "") not in _SAVE_OUTPUT_CLASS_TYPES:
            continue
        inputs = node.get("inputs")
        if not isinstance(inputs, dict):
            inputs = {}
            node["inputs"] = inputs
        inputs["filename_prefix"] = safe_prefix
    return new_wf


def _safe_run_id(run_id: str) -> str:
    """Strip anything that's not an alphanumeric / dash / underscore from a run_id."""
    cleaned = "".join(ch for ch in str(run_id or "") if ch.isalnum() or ch in {"-", "_"})
    if not cleaned:
        raise SafetyError("run_id 不可為空字串")
    if len(cleaned) > 64:
        raise SafetyError("run_id 長度不可超過 64 字元")
    return cleaned


__all__ = [
    "SafetyError",
    "enforce_allowlist",
    "next_safe_node_id",
    "rewrite_save_image_prefix",
]
