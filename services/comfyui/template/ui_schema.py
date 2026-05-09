"""§9 UI Schema — derive a 6-panel layout from a WorkflowAnalysis.

Frontend renders one section per panel; each panel surfaces only the
user-editable inputs of its category. Image inputs are gathered onto the
``image`` panel as upload slots. The compatibility panel is read-only and
gets populated separately from the CapabilityCheck result.

Spec reference: docs/comfyui/COMFYUI_TEMPLATE_IMPORTER_PLAN.md §9.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Iterable

from services.comfyui.template.analyzer import (
    FieldCategory,
    InputField,
    WorkflowAnalysis,
)
from services.comfyui.template.capability import CapabilityCheck


# ----------------------------------------------------------------------------
# Panel field shape
# ----------------------------------------------------------------------------


def _field_id(field_obj: InputField) -> str:
    return f"node:{field_obj.node_id}:{field_obj.input_name}"


def _input_type_for_category(category: FieldCategory) -> str:
    return {
        FieldCategory.TEXT: "textarea",
        FieldCategory.IMAGE: "file_picker",
        FieldCategory.MODEL: "select",
        FieldCategory.NUMERIC: "number",
        FieldCategory.SAMPLER: "select",
        FieldCategory.UNKNOWN: "textarea",
    }[category]


# Default UI hints per (class_type, input_name); merged into per-field
# constraints. Values are advisory — caller may override based on capability
# check results (e.g., narrow `options` on `ckpt_name` to local files only).
_FIELD_CONSTRAINT_HINTS: dict[tuple[str, str], dict[str, Any]] = {
    ("CLIPTextEncode", "text"): {"max_length": 2000, "rows": 4},
    ("KSampler", "seed"): {"min": 0, "max": 2 ** 53, "step": 1},
    ("KSampler", "steps"): {"min": 1, "max": 150, "step": 1},
    ("KSampler", "cfg"): {"min": 0.5, "max": 30.0, "step": 0.1},
    ("KSampler", "denoise"): {"min": 0.0, "max": 1.0, "step": 0.05},
    ("KSamplerAdvanced", "noise_seed"): {"min": 0, "max": 2 ** 53, "step": 1},
    ("KSamplerAdvanced", "steps"): {"min": 1, "max": 150, "step": 1},
    ("KSamplerAdvanced", "cfg"): {"min": 0.5, "max": 30.0, "step": 0.1},
    ("KSamplerAdvanced", "start_at_step"): {"min": 0, "max": 150, "step": 1},
    ("KSamplerAdvanced", "end_at_step"): {"min": 0, "max": 150, "step": 1},
    ("LoraLoader", "strength_model"): {"min": -2.0, "max": 2.0, "step": 0.05},
    ("LoraLoader", "strength_clip"): {"min": -2.0, "max": 2.0, "step": 0.05},
    ("ControlNetApplyAdvanced", "strength"): {"min": 0.0, "max": 2.0, "step": 0.05},
    ("ControlNetApplyAdvanced", "start_percent"): {"min": 0.0, "max": 1.0, "step": 0.05},
    ("ControlNetApplyAdvanced", "end_percent"): {"min": 0.0, "max": 1.0, "step": 0.05},
    ("EmptyLatentImage", "width"): {"min": 64, "max": 4096, "step": 8},
    ("EmptyLatentImage", "height"): {"min": 64, "max": 4096, "step": 8},
    ("EmptyLatentImage", "batch_size"): {"min": 1, "max": 16, "step": 1},
    ("ImagePadForOutpaint", "left"): {"min": 0, "max": 4096, "step": 8},
    ("ImagePadForOutpaint", "top"): {"min": 0, "max": 4096, "step": 8},
    ("ImagePadForOutpaint", "right"): {"min": 0, "max": 4096, "step": 8},
    ("ImagePadForOutpaint", "bottom"): {"min": 0, "max": 4096, "step": 8},
    ("ImagePadForOutpaint", "feathering"): {"min": 0, "max": 256, "step": 1},
    ("VAEEncodeForInpaint", "grow_mask_by"): {"min": 0, "max": 64, "step": 1},
    ("LoadImage", "image"): {"accept_mime": ["image/png", "image/jpeg", "image/webp"]},
    ("LoadImageMask", "image"): {"accept_mime": ["image/png", "image/jpeg", "image/webp"]},
    ("LoadImageMask", "channel"): {"options": ["alpha", "red", "green", "blue"]},
}


def _label_zh(field_obj: InputField) -> str:
    """Best-effort 繁中 label; falls back to the raw input name."""
    table: dict[tuple[str, str], str] = {
        ("CLIPTextEncode", "text"): "提示詞",
        ("LoadImage", "image"): "上傳圖片",
        ("LoadImageMask", "image"): "上傳遮罩",
        ("LoadImageMask", "channel"): "遮罩通道",
        ("CheckpointLoaderSimple", "ckpt_name"): "Checkpoint 模型",
        ("VAELoader", "vae_name"): "VAE",
        ("LoraLoader", "lora_name"): "LoRA 模型",
        ("LoraLoader", "strength_model"): "LoRA 強度（model）",
        ("LoraLoader", "strength_clip"): "LoRA 強度（clip）",
        ("ControlNetLoader", "control_net_name"): "ControlNet 模型",
        ("UpscaleModelLoader", "model_name"): "放大模型",
        ("KSampler", "seed"): "種子",
        ("KSampler", "steps"): "步數",
        ("KSampler", "cfg"): "CFG",
        ("KSampler", "denoise"): "Denoise",
        ("KSampler", "sampler_name"): "取樣器",
        ("KSampler", "scheduler"): "排程器",
        ("KSamplerAdvanced", "add_noise"): "加入雜訊",
        ("KSamplerAdvanced", "noise_seed"): "雜訊種子",
        ("KSamplerAdvanced", "steps"): "步數",
        ("KSamplerAdvanced", "cfg"): "CFG",
        ("KSamplerAdvanced", "sampler_name"): "取樣器",
        ("KSamplerAdvanced", "scheduler"): "排程器",
        ("KSamplerAdvanced", "start_at_step"): "起始步數",
        ("KSamplerAdvanced", "end_at_step"): "結束步數",
        ("KSamplerAdvanced", "return_with_leftover_noise"): "保留剩餘雜訊",
        ("EmptyLatentImage", "width"): "寬度",
        ("EmptyLatentImage", "height"): "高度",
        ("EmptyLatentImage", "batch_size"): "批次大小",
        ("ControlNetApplyAdvanced", "strength"): "ControlNet 強度",
        ("ControlNetApplyAdvanced", "start_percent"): "ControlNet 起始 %",
        ("ControlNetApplyAdvanced", "end_percent"): "ControlNet 結束 %",
        ("ImagePadForOutpaint", "left"): "外擴 - 左",
        ("ImagePadForOutpaint", "top"): "外擴 - 上",
        ("ImagePadForOutpaint", "right"): "外擴 - 右",
        ("ImagePadForOutpaint", "bottom"): "外擴 - 下",
        ("ImagePadForOutpaint", "feathering"): "羽化",
        ("VAEEncodeForInpaint", "grow_mask_by"): "遮罩外擴",
        ("SaveImage", "filename_prefix"): "輸出檔名前綴（系統會改寫）",
    }
    return table.get(
        (field_obj.class_type, field_obj.input_name),
        f"{field_obj.class_type}.{field_obj.input_name}",
    )


def _serialize_field(field_obj: InputField) -> dict[str, Any]:
    """Build the §9.1 panel-field record for one InputField."""
    constraints = dict(_FIELD_CONSTRAINT_HINTS.get((field_obj.class_type, field_obj.input_name), {}))
    payload = {
        "id": _field_id(field_obj),
        "node_id": field_obj.node_id,
        "class_type": field_obj.class_type,
        "input_name": field_obj.input_name,
        "category": field_obj.category.value,
        "label": _label_zh(field_obj),
        "input_type": _input_type_for_category(field_obj.category),
        "required": True,
        "current_value": _safe_current_value(field_obj.raw_value),
    }
    if constraints:
        payload["constraints"] = constraints
    return payload


def _safe_current_value(raw_value: Any) -> Any:
    """JSON-friendly clone of `raw_value` for the panel `current_value` slot."""
    try:
        json.dumps(raw_value)
        return raw_value
    except (TypeError, ValueError):
        return str(raw_value)


# ----------------------------------------------------------------------------
# Public API: build_ui_schema
# ----------------------------------------------------------------------------


@dataclass
class UISchema:
    panels: list[dict[str, Any]] = field(default_factory=list)
    capability: dict[str, Any] = field(default_factory=dict)
    raw_workflow: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "panels": list(self.panels),
            "capability": dict(self.capability),
            "raw_workflow": dict(self.raw_workflow),
        }


_PANEL_ORDER: list[tuple[str, FieldCategory, str]] = [
    ("text", FieldCategory.TEXT, "文字輸入"),
    ("image", FieldCategory.IMAGE, "圖片輸入"),
    ("model", FieldCategory.MODEL, "模型需求"),
    ("sampler", FieldCategory.SAMPLER, "採樣設定"),
    ("numeric", FieldCategory.NUMERIC, "進階數值參數"),
]


def build_ui_schema(
    *,
    analysis: WorkflowAnalysis,
    capability: CapabilityCheck | None = None,
    raw_workflow: dict[str, Any] | None = None,
) -> UISchema:
    """Group user-editable inputs onto the §9.2 panel layout.

    Sampler enums (sampler_name / scheduler) are tagged into the ``sampler``
    panel so the UI can render them as dropdowns alongside numeric KSampler
    fields. NUMERIC fields that *also* sit on KSampler (seed/steps/cfg/denoise)
    appear on the ``sampler`` panel; everything else NUMERIC moves to the
    ``numeric`` advanced panel.
    """
    schema = UISchema()
    by_panel: dict[str, list[dict[str, Any]]] = {key: [] for key, _, _ in _PANEL_ORDER}

    for field_obj in analysis.user_inputs:
        # SaveImage.filename_prefix is overwritten by §7.2; not user-editable.
        if (field_obj.class_type, field_obj.input_name) == ("SaveImage", "filename_prefix"):
            continue
        panel_key = _panel_key_for_field(field_obj)
        if panel_key is None:
            continue
        by_panel[panel_key].append(_serialize_field(field_obj))

    for key, _category, label in _PANEL_ORDER:
        fields = by_panel.get(key, [])
        if not fields:
            continue
        schema.panels.append(
            {
                "id": key,
                "label": label,
                "collapsed_default": True,
                "fields": fields,
            }
        )

    schema.panels.append(
        {
            "id": "compatibility",
            "label": "相容性報告",
            "collapsed_default": False,
            "read_only": True,
            "fields": [],
        }
    )
    schema.panels.append(
        {
            "id": "raw",
            "label": "原始 workflow",
            "collapsed_default": True,
            "read_only": True,
            "fields": [],
        }
    )

    if capability is not None:
        schema.capability = capability.to_dict()
    if raw_workflow is not None:
        schema.raw_workflow = dict(raw_workflow)

    return schema


def _panel_key_for_field(field_obj: InputField) -> str | None:
    """Bucket a field onto a §9.2 panel."""
    cat = field_obj.category
    if cat == FieldCategory.TEXT:
        return "text"
    if cat == FieldCategory.IMAGE:
        return "image"
    if cat == FieldCategory.MODEL:
        return "model"
    if cat == FieldCategory.SAMPLER:
        return "sampler"
    if cat == FieldCategory.NUMERIC:
        # KSampler fields go onto the sampler panel for cohesion; everything
        # else (latent dims, controlnet strength, outpaint padding, lora
        # strength) goes onto the advanced numeric panel.
        if field_obj.class_type in {"KSampler", "KSamplerAdvanced"}:
            return "sampler"
        return "numeric"
    # FieldCategory.UNKNOWN — keep them out of UI so the user can't break the
    # workflow by editing fields whose semantics we don't model.
    return None


def required_user_inputs(analysis: WorkflowAnalysis) -> list[str]:
    """Field IDs that must be filled in before /run; consumed by §10 Gate 4."""
    ids: list[str] = []
    for field_obj in analysis.user_inputs:
        if (field_obj.class_type, field_obj.input_name) == ("SaveImage", "filename_prefix"):
            continue
        if field_obj.category == FieldCategory.UNKNOWN:
            continue
        ids.append(_field_id(field_obj))
    return ids


__all__ = [
    "UISchema",
    "build_ui_schema",
    "required_user_inputs",
]
