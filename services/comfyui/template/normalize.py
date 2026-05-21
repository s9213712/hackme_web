"""Normalize uploaded ComfyUI workflow payloads for the template importer.

The importer accepts two practical shapes:

1. API prompt format: ``{node_id: {"class_type": ..., "inputs": {...}}}``
2. Native UI graph format: ``{"nodes": [...], "links": [...]}``

UI graph exports are converted into API-format graphs before the existing
sanitize/analyze pipeline runs. This keeps run-time Gate 1 strict while still
letting the import preview accept the JSON users typically save from ComfyUI.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from services.comfyui.validation.rules import WorkflowValidationError


_UI_ONLY_NODE_TYPES = frozenset({
    "Note",
    "MarkdownNote",
    # rgthree UI control node. It toggles ComfyUI editor groups and has no
    # runtime API inputs; keeping it in API prompts makes ComfyUI object_info
    # checks fail on machines without rgthree installed.
    "Fast Groups Bypasser (rgthree)",
})
_PASSTHROUGH_NODE_TYPES = frozenset({"Reroute"})
_VALUE_FOLD_NODE_TYPES = frozenset(
    {
        "PrimitiveNode",
        "PrimitiveStringMultiline",
        "PrimitiveBoolean",
        "PrimitiveInt",
        "PrimitiveFloat",
    }
)
_MISSING = object()

_WIDGET_ORDER_OVERRIDES: dict[str, list[str]] = {
    "LoadImage": ["image", "upload"],
    "CheckpointLoaderSimple": ["ckpt_name"],
    "CLIPLoader": ["clip_name", "type", "device"],
    "DualCLIPLoader": ["clip_name1", "clip_name2", "type", "device"],
    "TripleCLIPLoader": ["clip_name1", "clip_name2", "clip_name3"],
    "UNETLoader": ["unet_name", "weight_dtype"],
    "UnetLoaderGGUF": ["unet_name"],
    "UnetLoaderGGUFAdvanced": ["unet_name", "dequant_dtype", "patch_dtype", "patch_on_device"],
    "CLIPLoaderGGUF": ["clip_name", "type", "device"],
    "DualCLIPLoaderGGUF": ["clip_name1", "clip_name2", "type", "device"],
    "TripleCLIPLoaderGGUF": ["clip_name1", "clip_name2", "clip_name3"],
    "VAELoader": ["vae_name"],
    "LoraLoaderModelOnly": ["lora_name", "strength_model"],
    "CLIPTextEncode": ["text"],
    "EmptyLatentImage": ["width", "height", "batch_size"],
    "EmptySD3LatentImage": ["width", "height", "batch_size"],
    "EmptyFlux2LatentImage": ["width", "height", "batch_size"],
    "ImageScaleToTotalPixels": ["upscale_method", "megapixels", "resolution_steps"],
    "ImageScale": ["upscale_method", "width", "height", "crop"],
    "LatentUpscaleBy": ["upscale_method", "scale_by"],
    "WanImageToVideo": ["width", "height", "length", "batch_size"],
    "WanVaceToVideo": ["width", "height", "length", "batch_size", "strength"],
    "ModelSamplingSD3": ["shift"],
    "ModelSamplingAuraFlow": ["shift"],
    "FluxGuidance": ["guidance"],
    "Flux2Scheduler": ["steps", "width", "height"],
    "KSamplerSelect": ["sampler_name"],
    "RandomNoise": ["noise_seed", "_skip_control_after_generate"],
    "CreateVideo": ["fps"],
    "SaveImage": ["filename_prefix"],
    "SaveVideo": ["filename_prefix", "format", "codec"],
    "SaveAudio": ["filename_prefix"],
    "SaveAudioMP3": ["filename_prefix", "quality"],
    "LoadVideo": ["file", "upload"],
    "ControlNetLoader": ["control_net_name"],
    "Canny": ["low_threshold", "high_threshold"],
    "ControlNetApplyAdvanced": ["strength", "start_percent", "end_percent"],
    "SDPoseKeypointExtractor": ["batch_size"],
    "ImageBlend": ["blend_factor", "blend_mode"],
    "CFGNorm": ["strength"],
    "TextEncodeQwenImageEditPlus": ["prompt"],
    "InpaintModelConditioning": ["noise_mask"],
    "ImagePadForOutpaint": ["left", "top", "right", "bottom", "feathering"],
    "UpscaleModelLoader": ["model_name"],
    "LoraLoader": ["lora_name", "strength_model", "strength_clip"],
    "ImageToMask": ["channel"],
    "ImageCompositeMasked": ["x", "y", "resize_source"],
    "ImageFromBatch": ["batch_index", "length"],
    "CLIPVisionLoader": ["clip_name"],
    "CLIPVisionEncode": ["crop"],
    "HunyuanVideo15ImageToVideo": ["width", "height", "length", "batch_size"],
    "BasicScheduler": ["scheduler", "steps", "denoise"],
    "ComfyMathExpression": ["expression"],
    "LTXAVTextEncoderLoader": ["text_encoder", "ckpt_name", "device"],
    "CFGGuider": ["cfg"],
    "ManualSigmas": ["sigmas"],
    "EmptyLTXVLatentVideo": ["width", "height", "length", "batch_size"],
    "EmptyAceStep1.5LatentAudio": ["seconds", "batch_size"],
    "TextEncodeAceStepAudio1.5": [
        "tags",
        "lyrics",
        "seed",
        "_skip_control_after_generate",
        "bpm",
        "duration",
        "timesignature",
        "language",
        "keyscale",
        "generate_audio_codes",
        "cfg_scale",
        "temperature",
        "top_p",
        "top_k",
        "min_p",
    ],
    "EmptyImage": ["width", "height", "batch_size", "color"],
    "ResizeImagesByLongerEdge": ["longer_edge"],
    "LTXVPreprocess": ["img_compression"],
    "LTXVImgToVideoInplace": ["strength", "bypass"],
    "LTXVEmptyLatentAudio": ["frames_number", "frame_rate", "batch_size"],
    "VAEDecodeTiled": ["tile_size", "overlap", "temporal_size", "temporal_overlap"],
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
    payload = _expand_subgraph_nodes(payload)
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
        for widget_name, widget_value in widget_values.items():
            if widget_name and not widget_name.startswith("_skip_") and widget_name not in api_inputs:
                api_inputs[widget_name] = widget_value

        api_node = {
            "class_type": class_type,
            "inputs": api_inputs,
        }
        meta = _node_metadata(node, payload)
        if meta:
            api_node["_meta"] = meta
        workflow[node_id] = api_node

    if not workflow:
        raise WorkflowValidationError("workflow UI graph 沒有可轉換的可執行節點")
    return workflow


def _expand_subgraph_nodes(payload: dict[str, Any]) -> dict[str, Any]:
    subgraphs = _subgraph_definitions(payload)
    if not subgraphs:
        return payload

    expanded = deepcopy(payload)
    for _depth in range(12):
        nodes = expanded.get("nodes")
        if not isinstance(nodes, list):
            return expanded
        if not any(
            isinstance(node, dict)
            and str(node.get("type") or "").strip() in subgraphs
            for node in nodes
        ):
            return expanded
        expanded = _expand_one_subgraph_node(expanded, subgraphs)
    raise WorkflowValidationError("workflow UI graph subgraph 巢狀層級過深")


def _subgraph_definitions(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    definitions = payload.get("definitions")
    if not isinstance(definitions, dict):
        return {}
    raw_subgraphs = definitions.get("subgraphs")
    if not isinstance(raw_subgraphs, list):
        return {}
    subgraphs: dict[str, dict[str, Any]] = {}
    for subgraph in raw_subgraphs:
        if not isinstance(subgraph, dict):
            continue
        subgraph_id = str(subgraph.get("id") or "").strip()
        if subgraph_id:
            subgraphs[subgraph_id] = subgraph
    return subgraphs


def _expand_one_subgraph_node(
    payload: dict[str, Any],
    subgraphs: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    nodes = payload.get("nodes")
    if not isinstance(nodes, list):
        return payload

    target_node: dict[str, Any] | None = None
    target_node_id = ""
    subgraph: dict[str, Any] | None = None
    for node in nodes:
        if not isinstance(node, dict):
            continue
        class_type = str(node.get("type") or "").strip()
        if class_type not in subgraphs:
            continue
        node_id = str(node.get("id") or "").strip()
        if not node_id:
            continue
        target_node = node
        target_node_id = node_id
        subgraph = subgraphs[class_type]
        break

    if target_node is None or subgraph is None:
        return payload

    links = list(_iter_link_records(payload.get("links")))
    root_link_sources = {
        link_id: (src_node_id, src_slot)
        for link_id, src_node_id, src_slot, _dst_node_id, _dst_slot, _link_type in links
    }
    outgoing_links = [
        record for record in links if record[1] == target_node_id
    ]

    node_id_alloc = _node_id_allocator(nodes)
    link_id_alloc = _link_id_allocator(links, subgraph.get("links"))

    id_map: dict[str, str] = {}
    copied_internal_nodes: dict[str, dict[str, Any]] = {}
    for internal_node in subgraph.get("nodes") or []:
        if not isinstance(internal_node, dict):
            continue
        old_id = str(internal_node.get("id") or "").strip()
        if not old_id or old_id in {"-10", "-20"}:
            continue
        new_id = node_id_alloc()
        id_map[old_id] = new_id
        copied = deepcopy(internal_node)
        copied["id"] = new_id
        copied_internal_nodes[old_id] = copied

    expanded_nodes = [
        deepcopy(node)
        for node in nodes
        if not (isinstance(node, dict) and str(node.get("id") or "").strip() == target_node_id)
    ]
    expanded_nodes.extend(copied_internal_nodes.values())

    expanded_links = [
        _link_list(record)
        for record in links
        if record[1] != target_node_id and record[3] != target_node_id
    ]

    for link in _iter_link_records(subgraph.get("links")):
        link_id, src_node_id, src_slot, dst_node_id, dst_slot, link_type = link
        if src_node_id == "-10":
            input_def = _node_input_for_subgraph_slot(target_node, subgraph, src_slot)
            external_link_id = input_def.get("link") if isinstance(input_def, dict) else None
            external_source = _link_source_by_id(external_link_id, root_link_sources)
            if external_source is None:
                _replace_internal_input_link(
                    copied_internal_nodes,
                    dst_node_id,
                    dst_slot,
                    link_id,
                    None,
                )
                continue
            new_link_id = link_id_alloc()
            expanded_links.append(
                [
                    new_link_id,
                    external_source[0],
                    external_source[1],
                    id_map.get(dst_node_id, dst_node_id),
                    dst_slot,
                    link_type,
                ]
            )
            _replace_internal_input_link(
                copied_internal_nodes,
                dst_node_id,
                dst_slot,
                link_id,
                new_link_id,
            )
            continue

        if dst_node_id == "-20":
            mapped_src = id_map.get(src_node_id, src_node_id)
            for root_link in outgoing_links:
                root_link_id, _root_src, root_src_slot, root_dst, root_dst_slot, root_link_type = root_link
                if root_src_slot != dst_slot:
                    continue
                expanded_links.append(
                    [root_link_id, mapped_src, src_slot, root_dst, root_dst_slot, root_link_type or link_type]
                )
            continue

        if src_node_id not in id_map or dst_node_id not in id_map:
            continue
        new_link_id = link_id_alloc()
        expanded_links.append(
            [new_link_id, id_map[src_node_id], src_slot, id_map[dst_node_id], dst_slot, link_type]
        )
        _replace_internal_input_link(
            copied_internal_nodes,
            dst_node_id,
            dst_slot,
            link_id,
            new_link_id,
        )

    expanded = dict(payload)
    expanded["nodes"] = expanded_nodes
    expanded["links"] = expanded_links
    return expanded


def _iter_link_records(raw_links: Any):
    if raw_links is None:
        return
    if not isinstance(raw_links, list):
        raise WorkflowValidationError("workflow UI graph links 格式不正確")
    for link in raw_links:
        record = _link_record(link)
        if record is not None:
            yield record


def _link_record(link: Any) -> tuple[int, str, int, str, int, Any] | None:
    if isinstance(link, (list, tuple)) and len(link) >= 5:
        try:
            link_id = int(link[0])
            src_node_id = str(link[1]).strip()
            src_slot = int(link[2])
            dst_node_id = str(link[3]).strip()
            dst_slot = int(link[4])
        except (TypeError, ValueError):
            return None
        if not src_node_id or not dst_node_id:
            return None
        link_type = link[5] if len(link) > 5 else None
        return (link_id, src_node_id, src_slot, dst_node_id, dst_slot, link_type)
    if isinstance(link, dict):
        try:
            link_id = int(link.get("id"))
            src_node_id = str(link.get("origin_id")).strip()
            src_slot = int(link.get("origin_slot"))
            dst_node_id = str(link.get("target_id")).strip()
            dst_slot = int(link.get("target_slot"))
        except (TypeError, ValueError):
            return None
        if not src_node_id or not dst_node_id:
            return None
        return (link_id, src_node_id, src_slot, dst_node_id, dst_slot, link.get("type"))
    return None


def _link_list(record: tuple[int, str, int, str, int, Any]) -> list[Any]:
    link_id, src_node_id, src_slot, dst_node_id, dst_slot, link_type = record
    return [link_id, src_node_id, src_slot, dst_node_id, dst_slot, link_type]


def _node_id_allocator(nodes: list[Any]):
    current = 0
    for node in nodes:
        if not isinstance(node, dict):
            continue
        try:
            current = max(current, int(node.get("id")))
        except (TypeError, ValueError):
            continue
    next_id = current + 1

    def allocate() -> str:
        nonlocal next_id
        value = str(next_id)
        next_id += 1
        return value

    return allocate


def _link_id_allocator(*raw_link_groups: Any):
    current = 0
    for raw_links in raw_link_groups:
        try:
            records = _iter_link_records(raw_links)
            for record in records:
                current = max(current, record[0])
        except WorkflowValidationError:
            continue
    next_id = current + 1

    def allocate() -> int:
        nonlocal next_id
        value = next_id
        next_id += 1
        return value

    return allocate


def _node_input_at_slot(node: dict[str, Any], slot: int) -> dict[str, Any] | None:
    inputs = node.get("inputs")
    if not isinstance(inputs, list) or slot < 0 or slot >= len(inputs):
        return None
    input_def = inputs[slot]
    return input_def if isinstance(input_def, dict) else None


def _subgraph_input_name_at_slot(subgraph: dict[str, Any], slot: int) -> str:
    inputs = subgraph.get("inputs")
    if not isinstance(inputs, list) or slot < 0 or slot >= len(inputs):
        return ""
    input_def = inputs[slot]
    if not isinstance(input_def, dict):
        return ""
    return str(input_def.get("name") or "").strip()


def _node_input_for_subgraph_slot(
    node: dict[str, Any],
    subgraph: dict[str, Any],
    slot: int,
) -> dict[str, Any] | None:
    wanted_name = _subgraph_input_name_at_slot(subgraph, slot)
    inputs = node.get("inputs")
    if wanted_name and isinstance(inputs, list):
        for input_def in inputs:
            if not isinstance(input_def, dict):
                continue
            if str(input_def.get("name") or "").strip() == wanted_name:
                return input_def
        return None
    return _node_input_at_slot(node, slot)


def _link_source_by_id(
    link_id: Any,
    link_sources: dict[int, tuple[str, int]],
) -> tuple[str, int] | None:
    try:
        return link_sources.get(int(link_id))
    except (TypeError, ValueError):
        return None


def _replace_internal_input_link(
    copied_internal_nodes: dict[str, dict[str, Any]],
    target_node_id: str,
    target_slot: int,
    old_link_id: int,
    new_link_id: int | None,
) -> None:
    node = copied_internal_nodes.get(str(target_node_id))
    if not node:
        return
    inputs = node.get("inputs")
    if not isinstance(inputs, list):
        return
    replaced = False
    for input_def in inputs:
        if not isinstance(input_def, dict):
            continue
        try:
            matches = int(input_def.get("link")) == int(old_link_id)
        except (TypeError, ValueError):
            matches = False
        if matches:
            input_def["link"] = new_link_id
            replaced = True
    if not replaced and 0 <= target_slot < len(inputs) and isinstance(inputs[target_slot], dict):
        inputs[target_slot]["link"] = new_link_id


def _build_link_map(raw_links: Any) -> dict[int, tuple[str, int]]:
    link_map: dict[int, tuple[str, int]] = {}
    for link_id, src_node_id, src_slot, _dst_node_id, _dst_slot, _link_type in _iter_link_records(raw_links):
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


def _node_metadata(node: dict[str, Any], payload: dict[str, Any]) -> dict[str, str]:
    meta: dict[str, str] = {}
    title = str(node.get("title") or "").strip()
    group_title = _node_group_title(node, payload)
    if title:
        meta["title"] = title
    if group_title:
        meta["group_title"] = group_title
        if not title:
            meta["title"] = group_title
    return meta


def _node_group_title(node: dict[str, Any], payload: dict[str, Any]) -> str:
    pos = node.get("pos")
    if not (isinstance(pos, list) and len(pos) >= 2):
        return ""
    try:
        x = float(pos[0])
        y = float(pos[1])
    except (TypeError, ValueError):
        return ""
    matches: list[tuple[float, str]] = []
    for group in payload.get("groups") or []:
        if not isinstance(group, dict):
            continue
        title = str(group.get("title") or "").strip()
        bounding = group.get("bounding")
        if not title or not (isinstance(bounding, list) and len(bounding) >= 4):
            continue
        try:
            gx = float(bounding[0])
            gy = float(bounding[1])
            width = float(bounding[2])
            height = float(bounding[3])
        except (TypeError, ValueError):
            continue
        if width <= 0 or height <= 0:
            continue
        if gx <= x <= gx + width and gy <= y <= gy + height:
            matches.append((width * height, title))
    if not matches:
        return ""
    return min(matches, key=lambda item: item[0])[1]


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
    class_type = str(node.get("type") or "").strip()
    if class_type == "ResizeImageMaskNode" and widgets:
        return _resize_image_mask_widget_value_map(widgets)
    names = _widget_names_for_node(node)
    values: dict[str, Any] = {}
    for index, name in enumerate(names):
        if index >= len(widgets):
            break
        if not name or name.startswith("_skip_"):
            continue
        values[name] = widgets[index]
    return values


def _resize_image_mask_widget_value_map(widgets: list[Any]) -> dict[str, Any]:
    if not widgets:
        return {}
    resize_type = str(widgets[0] or "").strip()
    values: dict[str, Any] = {"resize_type": widgets[0]}
    if resize_type == "scale dimensions":
        names = ["resize_type", "resize_type.width", "resize_type.height", "resize_type.crop", "scale_method"]
    elif resize_type == "scale total pixels":
        names = ["resize_type", "resize_type.megapixels", "scale_method"]
    elif resize_type == "scale longer dimension":
        names = ["resize_type", "resize_type.longer_size", "scale_method"]
    elif resize_type == "scale shorter dimension":
        names = ["resize_type", "resize_type.shorter_size", "scale_method"]
    elif resize_type == "scale by multiplier":
        names = ["resize_type", "resize_type.multiplier", "scale_method"]
    elif resize_type == "scale width":
        names = ["resize_type", "resize_type.width", "scale_method"]
    elif resize_type == "scale height":
        names = ["resize_type", "resize_type.height", "scale_method"]
    elif resize_type == "scale to multiple":
        names = ["resize_type", "resize_type.multiple", "scale_method"]
    else:
        names = ["resize_type", "scale_method"]
    for index, name in enumerate(names):
        if index >= len(widgets):
            break
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
