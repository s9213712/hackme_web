"""Normalize uploaded ComfyUI workflow payloads for the template importer.

The importer accepts two practical shapes:

1. API prompt format: ``{node_id: {"class_type": ..., "inputs": {...}}}``
2. Native UI graph format: ``{"nodes": [...], "links": [...]}``

UI graph exports are converted into API-format graphs before the existing
sanitize/analyze pipeline runs. This keeps run-time Gate 1 strict while still
letting the import preview accept the JSON users typically save from ComfyUI.
"""

from __future__ import annotations

from typing import Any

from services.comfyui.validation.rules import WorkflowValidationError


_UI_ONLY_NODE_TYPES = frozenset({"Note"})
_PASSTHROUGH_NODE_TYPES = frozenset({"Reroute"})
_VALUE_FOLD_NODE_TYPES = frozenset({"PrimitiveNode"})
_MISSING = object()

_WIDGET_ORDER_OVERRIDES: dict[str, list[str]] = {
    # ComfyUI UI graph stores the "control_after_generate" widget in
    # widgets_values even though it is not part of the API prompt inputs.
    "KSampler": [
        "seed",
        "_skip_control_after_generate",
        "steps",
        "cfg",
        "sampler_name",
        "scheduler",
        "denoise",
    ],
    "KSamplerAdvanced": [
        "add_noise",
        "noise_seed",
        "_skip_control_after_generate",
        "steps",
        "cfg",
        "sampler_name",
        "scheduler",
        "start_at_step",
        "end_at_step",
        "return_with_leftover_noise",
    ],
}


def is_ui_graph_workflow(payload: Any) -> bool:
    return isinstance(payload, dict) and isinstance(payload.get("nodes"), list)


def normalize_uploaded_workflow_json(payload: Any) -> Any:
    """Accept UI graph / wrapped prompt uploads and return API-format payload."""
    if not isinstance(payload, dict):
        return payload
    prompt = payload.get("prompt")
    if isinstance(prompt, dict) and not is_ui_graph_workflow(payload):
        return prompt
    if is_ui_graph_workflow(payload):
        return convert_ui_graph_to_api_workflow(payload)
    return payload


def convert_ui_graph_to_api_workflow(payload: dict[str, Any]) -> dict[str, Any]:
    """Convert a ComfyUI editor graph (`nodes` / `links`) into API prompt format."""
    nodes = payload.get("nodes")
    if not isinstance(nodes, list) or not nodes:
        raise WorkflowValidationError("workflow UI graph 缺少 nodes")

    node_by_id: dict[str, dict[str, Any]] = {}
    for node in nodes:
        if not isinstance(node, dict):
            raise WorkflowValidationError("workflow UI graph node 格式不正確")
        node_id = str(node.get("id") or "").strip()
        if not node_id:
            raise WorkflowValidationError("workflow UI graph node id 不可為空")
        node_by_id[node_id] = node

    link_map = _build_link_map(payload.get("links"))
    passthrough_sources = _build_passthrough_sources(node_by_id, link_map)
    primitive_values = _build_primitive_value_map(node_by_id)

    workflow: dict[str, Any] = {}
    for node_id, node in node_by_id.items():
        class_type = str(node.get("type") or "").strip()
        if not class_type:
            raise WorkflowValidationError(f"workflow UI graph node {node_id} 缺少 type")
        if class_type in _UI_ONLY_NODE_TYPES | _PASSTHROUGH_NODE_TYPES | _VALUE_FOLD_NODE_TYPES:
            continue

        widget_values = _widget_value_map(node)
        api_inputs: dict[str, Any] = {}
        for input_def in node.get("inputs") or []:
            if not isinstance(input_def, dict):
                continue
            input_name = str(input_def.get("name") or "").strip()
            if not input_name:
                continue
            value = _resolve_input_value(
                input_def,
                link_map=link_map,
                passthrough_sources=passthrough_sources,
                primitive_values=primitive_values,
                widget_values=widget_values,
            )
            if value is not _MISSING:
                api_inputs[input_name] = value

        workflow[node_id] = {
            "class_type": class_type,
            "inputs": api_inputs,
        }

    if not workflow:
        raise WorkflowValidationError("workflow UI graph 沒有可轉換的可執行節點")
    return workflow


def _build_link_map(raw_links: Any) -> dict[int, tuple[str, int]]:
    if raw_links is None:
        return {}
    if not isinstance(raw_links, list):
        raise WorkflowValidationError("workflow UI graph links 格式不正確")
    link_map: dict[int, tuple[str, int]] = {}
    for link in raw_links:
        if not isinstance(link, list) or len(link) < 4:
            continue
        try:
            link_id = int(link[0])
            src_node_id = str(link[1]).strip()
            src_slot = int(link[2])
        except (TypeError, ValueError):
            continue
        if src_node_id:
            link_map[link_id] = (src_node_id, src_slot)
    return link_map


def _build_passthrough_sources(
    node_by_id: dict[str, dict[str, Any]],
    link_map: dict[int, tuple[str, int]],
) -> dict[str, tuple[str, int]]:
    sources: dict[str, tuple[str, int]] = {}
    for node_id, node in node_by_id.items():
        if str(node.get("type") or "").strip() not in _PASSTHROUGH_NODE_TYPES:
            continue
        for input_def in node.get("inputs") or []:
            if not isinstance(input_def, dict):
                continue
            link_id = input_def.get("link")
            if link_id is None:
                continue
            source = _resolve_link_source(link_id, link_map, sources)
            if source is not None:
                sources[node_id] = source
                break
    return sources


def _build_primitive_value_map(
    node_by_id: dict[str, dict[str, Any]],
) -> dict[tuple[str, int], Any]:
    primitive_values: dict[tuple[str, int], Any] = {}
    for node_id, node in node_by_id.items():
        if str(node.get("type") or "").strip() not in _VALUE_FOLD_NODE_TYPES:
            continue
        value = _primitive_node_value(node)
        if value is _MISSING:
            continue
        output_defs = node.get("outputs")
        if isinstance(output_defs, list) and output_defs:
            for index, output_def in enumerate(output_defs):
                slot_index = index
                if isinstance(output_def, dict) and output_def.get("slot_index") is not None:
                    try:
                        slot_index = int(output_def.get("slot_index"))
                    except (TypeError, ValueError):
                        slot_index = index
                primitive_values[(node_id, slot_index)] = value
        else:
            primitive_values[(node_id, 0)] = value
    return primitive_values


def _primitive_node_value(node: dict[str, Any]) -> Any:
    widgets = node.get("widgets_values")
    if isinstance(widgets, list) and widgets:
        return widgets[0]
    if isinstance(widgets, dict) and widgets:
        return next(iter(widgets.values()))
    return _MISSING


def _widget_names_for_node(node: dict[str, Any]) -> list[str]:
    class_type = str(node.get("type") or "").strip()
    override = _WIDGET_ORDER_OVERRIDES.get(class_type)
    if override is not None:
        return list(override)
    names: list[str] = []
    for input_def in node.get("inputs") or []:
        if not isinstance(input_def, dict):
            continue
        widget = input_def.get("widget")
        if not isinstance(widget, dict):
            continue
        name = str(widget.get("name") or input_def.get("name") or "").strip()
        if name:
            names.append(name)
    return names


def _widget_value_map(node: dict[str, Any]) -> dict[str, Any]:
    widgets = node.get("widgets_values")
    if isinstance(widgets, dict):
        return {str(key).strip(): value for key, value in widgets.items() if str(key).strip()}
    if not isinstance(widgets, list):
        return {}
    names = _widget_names_for_node(node)
    values: dict[str, Any] = {}
    for index, name in enumerate(names):
        if index >= len(widgets):
            break
        if not name or name.startswith("_skip_"):
            continue
        values[name] = widgets[index]
    return values


def _resolve_input_value(
    input_def: dict[str, Any],
    *,
    link_map: dict[int, tuple[str, int]],
    passthrough_sources: dict[str, tuple[str, int]],
    primitive_values: dict[tuple[str, int], Any],
    widget_values: dict[str, Any],
) -> Any:
    link_id = input_def.get("link")
    if link_id is not None:
        source = _resolve_link_source(link_id, link_map, passthrough_sources)
        if source is not None:
            primitive = primitive_values.get(source, _MISSING)
            if primitive is not _MISSING:
                return primitive
            return [source[0], source[1]]
    widget = input_def.get("widget")
    widget_name = ""
    if isinstance(widget, dict):
        widget_name = str(widget.get("name") or "").strip()
    if widget_name and widget_name in widget_values:
        return widget_values[widget_name]
    input_name = str(input_def.get("name") or "").strip()
    if input_name and input_name in widget_values:
        return widget_values[input_name]
    return _MISSING


def _resolve_link_source(
    link_id: Any,
    link_map: dict[int, tuple[str, int]],
    passthrough_sources: dict[str, tuple[str, int]],
) -> tuple[str, int] | None:
    try:
        source = link_map.get(int(link_id))
    except (TypeError, ValueError):
        source = None
    if source is None:
        return None

    visited: set[str] = set()
    current = source
    while current[0] in passthrough_sources and current[0] not in visited:
        visited.add(current[0])
        current = passthrough_sources[current[0]]
    return current


__all__ = [
    "convert_ui_graph_to_api_workflow",
    "is_ui_graph_workflow",
    "normalize_uploaded_workflow_json",
]
