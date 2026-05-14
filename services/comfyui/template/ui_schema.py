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
    ("ByteDanceSeedreamNode", "prompt"): {"max_length": 4000, "rows": 5},
    ("GrokImageEditNode", "prompt"): {"max_length": 4000, "rows": 5},
    ("StringConcatenate", "string_a"): {"max_length": 3000, "rows": 3},
    ("StringConcatenate", "string_b"): {"max_length": 3000, "rows": 5},
    ("TextEncodeAceStepAudio1.5", "tags"): {"max_length": 2000, "rows": 4},
    ("TextEncodeAceStepAudio1.5", "lyrics"): {"max_length": 5000, "rows": 8},
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
    ("LoraLoaderModelOnly", "strength_model"): {"min": -2.0, "max": 2.0, "step": 0.05},
    ("ControlNetApplyAdvanced", "strength"): {"min": 0.0, "max": 2.0, "step": 0.05},
    ("ControlNetApplyAdvanced", "start_percent"): {"min": 0.0, "max": 1.0, "step": 0.05},
    ("ControlNetApplyAdvanced", "end_percent"): {"min": 0.0, "max": 1.0, "step": 0.05},
    ("EmptyLatentImage", "width"): {"min": 64, "max": 4096, "step": 8},
    ("EmptyLatentImage", "height"): {"min": 64, "max": 4096, "step": 8},
    ("EmptyLatentImage", "batch_size"): {"min": 1, "max": 16, "step": 1},
    ("EmptySD3LatentImage", "width"): {"min": 64, "max": 4096, "step": 8},
    ("EmptySD3LatentImage", "height"): {"min": 64, "max": 4096, "step": 8},
    ("EmptySD3LatentImage", "batch_size"): {"min": 1, "max": 16, "step": 1},
    ("EmptyFlux2LatentImage", "width"): {"min": 64, "max": 4096, "step": 8},
    ("EmptyFlux2LatentImage", "height"): {"min": 64, "max": 4096, "step": 8},
    ("EmptyFlux2LatentImage", "batch_size"): {"min": 1, "max": 16, "step": 1},
    ("ModelSamplingSD3", "shift"): {"min": 0.0, "max": 20.0, "step": 0.1},
    ("ModelSamplingAuraFlow", "shift"): {"min": 0.0, "max": 20.0, "step": 0.1},
    ("Flux2Scheduler", "steps"): {"min": 1, "max": 150, "step": 1},
    ("Flux2Scheduler", "width"): {"min": 64, "max": 4096, "step": 8},
    ("Flux2Scheduler", "height"): {"min": 64, "max": 4096, "step": 8},
    ("CreateVideo", "fps"): {"min": 1, "max": 120, "step": 1},
    ("ImageScaleToTotalPixels", "megapixels"): {"min": 0.1, "max": 64.0, "step": 0.1},
    ("ImageScaleToTotalPixels", "divisible_by"): {"min": 1, "max": 256, "step": 1},
    ("TextEncodeAceStepAudio1.5", "duration"): {"min": 1, "max": 600, "step": 1},
    ("TextEncodeAceStepAudio1.5", "cfg_scale"): {"min": 0.0, "max": 20.0, "step": 0.1},
    ("EmptyAceStep1.5LatentAudio", "seconds"): {"min": 1, "max": 600, "step": 1},
    ("ByteDanceSeedreamNode", "width"): {"min": 256, "max": 4096, "step": 64},
    ("ByteDanceSeedreamNode", "height"): {"min": 256, "max": 4096, "step": 64},
    ("ByteDanceSeedreamNode", "max_images"): {"min": 1, "max": 8, "step": 1},
    ("GrokImageEditNode", "number_of_images"): {"min": 1, "max": 8, "step": 1},
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
        ("CLIPLoader", "clip_name"): "CLIP / 文字編碼器模型檔名",
        ("DualCLIPLoader", "clip_name1"): "CLIP-L 模型檔名",
        ("DualCLIPLoader", "clip_name2"): "T5 / 第二文字編碼器檔名",
        ("TripleCLIPLoader", "clip_name1"): "CLIP-L 模型檔名",
        ("TripleCLIPLoader", "clip_name2"): "CLIP-G 模型檔名",
        ("TripleCLIPLoader", "clip_name3"): "T5 / 第三文字編碼器檔名",
        ("UNETLoader", "unet_name"): "Diffusion / UNet 模型檔名",
        ("LoraLoader", "lora_name"): "LoRA 模型",
        ("LoraLoaderModelOnly", "lora_name"): "LoRA 模型",
        ("LoraLoader", "strength_model"): "LoRA 強度（model）",
        ("LoraLoader", "strength_clip"): "LoRA 強度（clip）",
        ("LoraLoaderModelOnly", "strength_model"): "LoRA 強度",
        ("ControlNetLoader", "control_net_name"): "ControlNet 模型",
        ("UpscaleModelLoader", "model_name"): "放大模型",
        ("KSampler", "seed"): "種子",
        ("KSampler", "steps"): "步數",
        ("KSampler", "cfg"): "CFG",
        ("KSampler", "denoise"): "Denoise",
        ("KSampler", "sampler_name"): "取樣器",
        ("KSampler", "scheduler"): "排程器",
        ("KSamplerSelect", "sampler_name"): "取樣器",
        ("BasicScheduler", "scheduler"): "排程器",
        ("BasicScheduler", "steps"): "步數",
        ("BasicScheduler", "denoise"): "Denoise",
        ("RandomNoise", "noise_seed"): "種子",
        ("FluxGuidance", "guidance"): "Flux Guidance",
        ("Flux2Scheduler", "steps"): "步數",
        ("Flux2Scheduler", "width"): "寬度",
        ("Flux2Scheduler", "height"): "高度",
        ("ModelSamplingSD3", "shift"): "Model Shift",
        ("ModelSamplingAuraFlow", "shift"): "Model Shift",
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
        ("EmptySD3LatentImage", "width"): "寬度",
        ("EmptySD3LatentImage", "height"): "高度",
        ("EmptySD3LatentImage", "batch_size"): "批次大小",
        ("EmptyFlux2LatentImage", "width"): "寬度",
        ("EmptyFlux2LatentImage", "height"): "高度",
        ("EmptyFlux2LatentImage", "batch_size"): "批次大小",
        ("ControlNetApplyAdvanced", "strength"): "ControlNet 強度",
        ("ControlNetApplyAdvanced", "start_percent"): "ControlNet 起始 %",
        ("ControlNetApplyAdvanced", "end_percent"): "ControlNet 結束 %",
        ("ImagePadForOutpaint", "left"): "外擴 - 左",
        ("ImagePadForOutpaint", "top"): "外擴 - 上",
        ("ImagePadForOutpaint", "right"): "外擴 - 右",
        ("ImagePadForOutpaint", "bottom"): "外擴 - 下",
        ("ImagePadForOutpaint", "feathering"): "羽化",
        ("WanImageToVideo", "width"): "影片寬度",
        ("WanImageToVideo", "height"): "影片高度",
        ("WanImageToVideo", "length"): "影片幀數",
        ("WanImageToVideo", "batch_size"): "影片批次大小",
        ("VAEEncodeForInpaint", "grow_mask_by"): "遮罩外擴",
        ("SaveImage", "filename_prefix"): "輸出檔名前綴（系統會改寫）",
        ("SaveVideo", "filename_prefix"): "影片輸出檔名前綴（系統會改寫）",
        ("SaveAudioMP3", "filename_prefix"): "音訊輸出檔名前綴（系統會改寫）",
        ("ByteDanceSeedreamNode", "prompt"): "提示詞",
        ("ByteDanceSeedreamNode", "model"): "Seedream 模型",
        ("ByteDanceSeedreamNode", "size_preset"): "尺寸預設",
        ("ByteDanceSeedreamNode", "width"): "寬度",
        ("ByteDanceSeedreamNode", "height"): "高度",
        ("ByteDanceSeedreamNode", "max_images"): "張數",
        ("ByteDanceSeedreamNode", "seed"): "種子",
        ("ByteDanceSeedreamNode", "watermark"): "浮水印",
        ("ByteDanceSeedreamNode", "fail_on_partial"): "部分失敗時停止",
        ("GrokImageEditNode", "prompt"): "編輯提示詞",
        ("GrokImageEditNode", "model"): "Grok 模型",
        ("GrokImageEditNode", "resolution"): "解析度",
        ("GrokImageEditNode", "number_of_images"): "張數",
        ("GrokImageEditNode", "seed"): "種子",
        ("GrokImageEditNode", "aspect_ratio"): "長寬比",
        ("StringConcatenate", "string_a"): "固定提示前綴",
        ("StringConcatenate", "string_b"): "提示詞",
        ("TextEncodeAceStepAudio1.5", "tags"): "音樂標籤",
        ("TextEncodeAceStepAudio1.5", "lyrics"): "歌詞",
        ("TextEncodeAceStepAudio1.5", "duration"): "秒數",
        ("TextEncodeAceStepAudio1.5", "timesignature"): "拍號",
        ("TextEncodeAceStepAudio1.5", "language"): "語言",
        ("TextEncodeAceStepAudio1.5", "keyscale"): "調式",
        ("TextEncodeAceStepAudio1.5", "generate_audio_codes"): "生成 audio codes",
        ("TextEncodeAceStepAudio1.5", "cfg_scale"): "CFG",
        ("EmptyAceStep1.5LatentAudio", "seconds"): "音訊秒數",
        ("ImageScaleToTotalPixels", "upscale_method"): "縮放方式",
        ("ImageScaleToTotalPixels", "megapixels"): "目標百萬像素",
        ("ImageScaleToTotalPixels", "divisible_by"): "尺寸整除",
        ("CreateVideo", "fps"): "FPS",
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


def _embedding_shortcuts_field(text_fields: Iterable[dict[str, Any]]) -> dict[str, Any]:
    field_ids = [str(field.get("id") or "") for field in text_fields if field.get("id")]
    return {
        "id": "text:embeddings",
        "node_id": "",
        "class_type": "EmbeddingShortcuts",
        "input_name": "embeddings",
        "category": FieldCategory.TEXT.value,
        "label": "Embedding 快速插入",
        "input_type": "embedding_shortcuts",
        "required": False,
        "current_value": "",
        "synthetic": True,
        "parent_category": "text",
        "constraints": {
            "target_field_ids": field_ids,
            "token_prefix": "<embeddings:",
        },
    }


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
        # Output filename prefixes are overwritten by §7.2; not user-editable.
        if (field_obj.class_type, field_obj.input_name) in {
            ("SaveImage", "filename_prefix"),
            ("SaveVideo", "filename_prefix"),
            ("SaveAudioMP3", "filename_prefix"),
        }:
            continue
        panel_key = _panel_key_for_field(field_obj)
        if panel_key is None:
            continue
        by_panel[panel_key].append(_serialize_field(field_obj))

    text_fields = by_panel.get("text", [])
    if any(
        field.get("class_type") == "CLIPTextEncode" and field.get("input_name") == "text"
        for field in text_fields
    ):
        text_fields.append(_embedding_shortcuts_field(text_fields))

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
        if (field_obj.class_type, field_obj.input_name) in {
            ("SaveImage", "filename_prefix"),
            ("SaveVideo", "filename_prefix"),
            ("SaveAudioMP3", "filename_prefix"),
        }:
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
