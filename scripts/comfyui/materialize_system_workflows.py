#!/usr/bin/env python3
"""Materialize checked-in ComfyUI origin workflows as system bundles.

Raw upstream exports live under ``workflows/comfyui/origin/<category>/<mode>``.
This script converts every registered origin JSON into the project-consumable
bundle shape used by first-boot seeding:

- ``workflows/comfyui/<bundle_id>/workflow.json``: ComfyUI API prompt format.
- ``workflows/comfyui/<bundle_id>/manifest.json``: card/UI metadata.
- ``workflows/comfyui/<bundle_id>/README.md``: short traceability note.

Each file is normalized, sanitized, analyzed, and allowlist-checked. Unknown
custom nodes do not block materialization, but they are recorded in manifest
metadata so the UI/run gate can report required local ComfyUI nodes clearly.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from services.comfyui.template.analyzer import analyze_workflow_json  # noqa: E402
from services.comfyui.template.normalize import (  # noqa: E402
    is_ui_graph_workflow,
    normalize_uploaded_workflow_json,
)
from services.comfyui.template.safety import enforce_allowlist  # noqa: E402
from services.comfyui.template.ui_schema import build_ui_schema  # noqa: E402
from services.comfyui.validation.rules import WorkflowValidationError  # noqa: E402
from services.comfyui.validation.sanitize import sanitize_workflow_json  # noqa: E402


ORIGIN_DIR = REPO_ROOT / "workflows" / "comfyui" / "origin"
TARGET_DIR = REPO_ROOT / "workflows" / "comfyui"


@dataclass(frozen=True)
class OriginBundle:
    source_path: str
    workflow_id: str
    name: str
    description: str
    generation_mode: str


ORIGIN_BUNDLES: tuple[OriginBundle, ...] = (
    OriginBundle(
        "audio/t2a/audio_ace_step1_5_xl_base.json",
        "origin_audio_ace_step_15_xl_base",
        "ACE-Step 1.5 XL Base（T2A）",
        "ACE-Step 1.5 text-to-audio / music workflow converted from origin.",
        "t2s",
    ),
    OriginBundle(
        "image/controlnet/image_qwen_Image_2512_controlnet.json",
        "origin_qwen_image_controlnet_2512",
        "Qwen Image 2512 ControlNet",
        "Qwen image ControlNet workflow converted from origin.",
        "txt2img",
    ),
    OriginBundle(
        "image/controlnet/sd3.5_large_canny_controlnet_example.json",
        "origin_sd35_large_canny_controlnet",
        "SD3.5 Large Canny ControlNet",
        "SD3.5 large canny ControlNet example converted from origin.",
        "txt2img",
    ),
    OriginBundle(
        "image/controlnet/sd3.5_large_depth.json",
        "origin_sd35_large_depth_controlnet",
        "SD3.5 Large Depth ControlNet",
        "SD3.5 large depth ControlNet workflow converted from origin.",
        "txt2img",
    ),
    OriginBundle(
        "image/edit/Image_capybara_v0_1_image_edit.json",
        "origin_capybara_image_edit",
        "Capybara v0.1 Image Edit",
        "Capybara image-edit workflow converted from origin.",
        "img2img",
    ),
    OriginBundle(
        "image/edit/image_qwen_image_edit_2509.json",
        "origin_qwen_image_edit_2509",
        "Qwen Image Edit 2509",
        "Qwen image-edit workflow converted from origin.",
        "img2img",
    ),
    OriginBundle(
        "image/edit/flux_fill_inpaint_example.json",
        "origin_flux_fill_inpaint",
        "Flux Fill Inpaint",
        "Flux fill/inpaint workflow converted from origin.",
        "inpaint",
    ),
    OriginBundle(
        "image/edit/【50】一键动漫转真人.json",
        "origin_one_click_anime_to_real",
        "One-Click Anime to Real",
        "One-click anime-to-real image workflow converted from origin.",
        "img2img",
    ),
    OriginBundle(
        "image/outpaint/flux_fill_outpaint_example.json",
        "origin_flux_fill_outpaint",
        "Flux Fill Outpaint",
        "Flux fill/outpaint workflow converted from origin.",
        "outpaint",
    ),
    OriginBundle(
        "image/txt2img/ANIMA.json",
        "origin_anima_txt2img",
        "ANIMA Text-to-Image",
        "ANIMA text-to-image workflow converted from origin.",
        "txt2img",
    ),
    OriginBundle(
        "image/txt2img/SD3.5.json",
        "origin_sd35_txt2img",
        "SD3.5 Text-to-Image",
        "SD3.5 text-to-image workflow converted from origin.",
        "txt2img",
    ),
    OriginBundle(
        "image/txt2img/SDXL.json",
        "origin_sdxl_txt2img",
        "SDXL Text-to-Image",
        "SDXL text-to-image workflow converted from origin.",
        "txt2img",
    ),
    OriginBundle(
        "image/txt2img/ZIT.json",
        "origin_zit_txt2img",
        "ZIT Text-to-Image",
        "ZIT text-to-image workflow converted from origin.",
        "txt2img",
    ),
    OriginBundle(
        "image/txt2img/flux_dev_full_text_to_image.json",
        "origin_flux_dev_txt2img",
        "Flux Dev Full Text-to-Image",
        "Flux dev full text-to-image workflow converted from origin.",
        "txt2img",
    ),
    OriginBundle(
        "image/txt2img/image_qwen_image.json",
        "origin_qwen_image_txt2img",
        "Qwen Image Text-to-Image",
        "Qwen image text-to-image workflow converted from origin.",
        "txt2img",
    ),
    OriginBundle(
        "image/txt2img/netayume.json",
        "origin_netayume_txt2img",
        "NetaYume Text-to-Image",
        "NetaYume text-to-image workflow converted from origin.",
        "txt2img",
    ),
    OriginBundle(
        "utility/compare/compare_2checkpoints.json",
        "origin_compare_2checkpoints",
        "Compare Two Checkpoints",
        "Two-checkpoint comparison workflow converted from origin.",
        "txt2img",
    ),
    OriginBundle(
        "utility/pose/utility_sdpose_multi_person.json",
        "origin_sdpose_multi_person",
        "SDPose Multi-Person Utility",
        "Multi-person pose extraction utility workflow converted from origin.",
        "img2img",
    ),
    OriginBundle(
        "utility/segmentation/utility_image_segment_sam3.json",
        "origin_sam3_segmentation",
        "SAM3 Image Segmentation Utility",
        "SAM3 segmentation utility workflow converted from origin.",
        "img2img",
    ),
    OriginBundle(
        "utility/upscale/多種放大方法.json",
        "origin_multi_method_upscale",
        "Multi-Method Upscale Utility",
        "Multi-method image upscale workflow converted from origin.",
        "upscale",
    ),
    OriginBundle(
        "video/edit/video_capybara_v0_1_video_edit.json",
        "origin_capybara_video_edit",
        "Capybara v0.1 Video Edit",
        "Capybara video-edit workflow converted from origin.",
        "v2v",
    ),
    OriginBundle(
        "video/edit/video_wan_vace_inpainting.json",
        "origin_wan_vace_inpainting",
        "WAN VACE Video Inpainting",
        "WAN VACE video inpainting workflow converted from origin.",
        "v2v",
    ),
    OriginBundle(
        "video/i2v/03_video_wan2_2_14B_i2v_subgraphed.json",
        "origin_wan22_14b_i2v_subgraphed",
        "WAN 2.2 14B I2V Subgraphed",
        "WAN 2.2 14B image-to-video workflow converted from origin.",
        "i2v",
    ),
    OriginBundle(
        "video/t2v/video_ltx2_3_t2v.json",
        "origin_ltx23_t2v",
        "LTX 2.3 Text-to-Video",
        "LTX 2.3 text-to-video workflow converted from origin.",
        "t2v",
    ),
)


def _origin_json_paths() -> set[str]:
    if not ORIGIN_DIR.is_dir():
        return set()
    return {
        path.relative_to(ORIGIN_DIR).as_posix()
        for path in ORIGIN_DIR.glob("*/*/*.json")
    }


def _validate_bundle_registry() -> None:
    registered_sources = [bundle.source_path for bundle in ORIGIN_BUNDLES]
    registered_ids = [bundle.workflow_id for bundle in ORIGIN_BUNDLES]
    if len(registered_sources) != len(set(registered_sources)):
        raise WorkflowValidationError("origin workflow registry contains duplicate source paths")
    if len(registered_ids) != len(set(registered_ids)):
        raise WorkflowValidationError("origin workflow registry contains duplicate workflow ids")
    actual_sources = _origin_json_paths()
    missing = sorted(set(registered_sources) - actual_sources)
    extra = sorted(actual_sources - set(registered_sources))
    if missing or extra:
        raise WorkflowValidationError(
            "origin workflow registry is out of sync: "
            f"missing={missing or []} extra={extra or []}"
        )


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise WorkflowValidationError(f"{path} JSON parse failed: {exc}") from exc


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )


def _workflow_output_kinds(workflow: dict[str, Any]) -> list[str]:
    classes = {
        str((node or {}).get("class_type") or "").strip()
        for node in (workflow or {}).values()
        if isinstance(node, dict)
    }
    kinds: list[str] = []
    if any(name in classes for name in {"SaveImage", "PreviewImage", "VAEDecode"}):
        kinds.append("image")
    if any("video" in name.lower() for name in classes):
        kinds.append("video")
    if any(
        token in name.lower()
        for name in classes
        for token in ("audio", "music", "wave", "wav")
    ):
        kinds.append("music")
    return kinds or ["image"]


def _first_input(analysis, *names: str) -> Any:
    for field_obj in analysis.user_inputs:
        if field_obj.input_name in names and not field_obj.is_link:
            return field_obj.raw_value
    return None


def _first_present(*values: Any) -> Any:
    for value in values:
        if value is not None:
            return value
    return None


def _first_non_empty_input(analysis, *names: str) -> Any:
    for name in names:
        for field_obj in analysis.user_inputs:
            if field_obj.input_name != name or field_obj.is_link:
                continue
            if field_obj.raw_value not in (None, ""):
                return field_obj.raw_value
    return None


def _negative_prompt_hint(analysis) -> str | None:
    for field_obj in analysis.user_inputs:
        if field_obj.is_link or not isinstance(field_obj.raw_value, str):
            continue
        text = field_obj.raw_value.strip()
        if not text:
            continue
        haystack = f"{field_obj.node_title} {field_obj.input_name} {text}".lower()
        if any(
            token in haystack
            for token in (
                "negative",
                "負",
                "worst quality",
                "low quality",
                "bad anatomy",
                "blurry",
                "deformed",
                "watermark",
            )
        ):
            return field_obj.raw_value
    return None


def _positive_number_or_none(value: Any) -> Any:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)) and value > 0:
        return value
    return None


def _first_sampler(workflow: dict[str, Any]) -> tuple[str | None, dict[str, Any] | None]:
    for node_id, node in (workflow or {}).items():
        if not isinstance(node, dict):
            continue
        if str(node.get("class_type") or "") in {"KSampler", "KSamplerAdvanced"}:
            return str(node_id), node
    return None, None


def _linked_ref(workflow: dict[str, Any], value: Any) -> tuple[dict[str, Any], int] | None:
    if not (isinstance(value, list) and len(value) == 2):
        return None
    node = (workflow or {}).get(str(value[0]))
    if not isinstance(node, dict):
        return None
    try:
        output_slot = int(value[1])
    except (TypeError, ValueError):
        output_slot = 0
    return node, output_slot


def _linked_node(workflow: dict[str, Any], value: Any) -> dict[str, Any] | None:
    linked = _linked_ref(workflow, value)
    return linked[0] if linked else None


def _scalar_from_node_output(workflow: dict[str, Any], value: Any, *, depth: int = 0) -> Any:
    if not (isinstance(value, list) and len(value) == 2):
        return value
    if depth > 8:
        return None
    linked = _linked_ref(workflow, value)
    if not linked:
        return None
    node, _output_slot = linked
    class_type = str(node.get("class_type") or "")
    inputs = node.get("inputs") if isinstance(node.get("inputs"), dict) else {}
    if class_type == "ComfySwitchNode":
        selected = "on_true" if bool(inputs.get("switch")) else "on_false"
        return _scalar_from_node_output(workflow, inputs.get(selected), depth=depth + 1)
    if class_type == "RandomNoise":
        return _scalar_from_node_output(workflow, inputs.get("noise_seed"), depth=depth + 1)
    if class_type == "KSamplerSelect":
        return _scalar_from_node_output(workflow, inputs.get("sampler_name"), depth=depth + 1)
    return None


def _string_from_node_input(workflow: dict[str, Any], value: Any, *, depth: int = 0) -> str | None:
    if isinstance(value, str):
        return value
    if depth > 4:
        return None
    node = _linked_node(workflow, value)
    if not isinstance(node, dict):
        return None
    class_type = str(node.get("class_type") or "")
    inputs = node.get("inputs") if isinstance(node.get("inputs"), dict) else {}
    if class_type == "StringConcatenate":
        parts = []
        for key in ("string_a", "string_b"):
            part = _string_from_node_input(workflow, inputs.get(key), depth=depth + 1)
            if part:
                parts.append(part)
        delimiter = inputs.get("delimiter")
        if not isinstance(delimiter, str):
            delimiter = ""
        return delimiter.join(parts)
    if class_type in {"CR Text", "CR Prompt Text"}:
        for key in ("text", "prompt"):
            text = _string_from_node_input(workflow, inputs.get(key), depth=depth + 1)
            if isinstance(text, str):
                return text
    if class_type == "ProcessString":
        text = _string_from_node_input(workflow, inputs.get("input_string"), depth=depth + 1)
        return text if isinstance(text, str) else None
    return None


def _text_for_conditioning_link(workflow: dict[str, Any], value: Any, *, depth: int = 0) -> str | None:
    if depth > 8:
        return None
    linked = _linked_ref(workflow, value)
    if not linked:
        return None
    node, output_slot = linked
    class_type = str(node.get("class_type") or "")
    inputs = node.get("inputs") if isinstance(node.get("inputs"), dict) else {}
    if class_type in {"CLIPTextEncode", "CLIPTextEncodeFlux"}:
        text = _string_from_node_input(workflow, inputs.get("text"))
        return text if isinstance(text, str) else None
    if class_type in {"TextEncodeQwenImageEditPlus", "TextEncodeQwenImageEditPlusCustom_lrzjason"}:
        text = _string_from_node_input(workflow, inputs.get("prompt"))
        return text if isinstance(text, str) else None
    if class_type == "TextEncodeAceStepAudio1.5":
        text = _string_from_node_input(workflow, inputs.get("tags"))
        return text if isinstance(text, str) else None
    if class_type == "ConditioningZeroOut":
        return ""
    if class_type in {
        "ControlNetApplyAdvanced",
        "ControlNetApplySD3",
        "HunyuanVideo15ImageToVideo",
        "LTXVConditioning",
        "LTXVCropGuides",
        "WanImageToVideo",
        "WanImageToVideoApi",
        "WanVaceToVideo",
    }:
        input_name = "negative" if output_slot == 1 else "positive"
        return _text_for_conditioning_link(workflow, inputs.get(input_name), depth=depth + 1)
    if class_type == "ReferenceLatent":
        return _text_for_conditioning_link(workflow, inputs.get("conditioning"), depth=depth + 1)
    if class_type == "CFGGuider":
        input_name = "negative" if output_slot == 1 else "positive"
        return _text_for_conditioning_link(workflow, inputs.get(input_name), depth=depth + 1)
    return None


def _prompt_pair(workflow: dict[str, Any], analysis) -> tuple[str, str]:
    _, sampler = _first_sampler(workflow)
    if isinstance(sampler, dict):
        inputs = sampler.get("inputs") if isinstance(sampler.get("inputs"), dict) else {}
        prompt = _text_for_conditioning_link(workflow, inputs.get("positive"))
        negative_prompt = _text_for_conditioning_link(workflow, inputs.get("negative"))
        if prompt is not None or negative_prompt not in (None, ""):
            return prompt or "", negative_prompt or ""
    for node in (workflow or {}).values():
        if not isinstance(node, dict) or str(node.get("class_type") or "") != "CFGGuider":
            continue
        inputs = node.get("inputs") if isinstance(node.get("inputs"), dict) else {}
        prompt = _text_for_conditioning_link(workflow, inputs.get("positive"))
        negative_prompt = _text_for_conditioning_link(workflow, inputs.get("negative"))
        if prompt is not None or negative_prompt not in (None, ""):
            return prompt or "", negative_prompt or ""
    prompt = _first_non_empty_input(analysis, "prompt", "text", "string_b", "tags")
    negative_prompt = _first_non_empty_input(analysis, "negative", "negative_prompt", "string_a")
    return prompt or "", negative_prompt or ""


def _default_params(wrapper: dict[str, Any], analysis, generation_mode: str, workflow: dict[str, Any]) -> dict[str, Any]:
    base = dict(wrapper.get("default_params") or {})
    prompt, negative_prompt = _prompt_pair(workflow, analysis)
    prompt = prompt or _first_non_empty_input(analysis, "prompt", "text", "string_b", "tags") or ""
    negative_prompt = negative_prompt or _negative_prompt_hint(analysis) or ""
    _, sampler = _first_sampler(workflow)
    sampler_inputs = sampler.get("inputs") if isinstance(sampler, dict) and isinstance(sampler.get("inputs"), dict) else {}
    sampler_seed = _scalar_from_node_output(
        workflow,
        sampler_inputs.get("seed") if "seed" in sampler_inputs else sampler_inputs.get("noise_seed"),
    )
    sampler_steps = _scalar_from_node_output(workflow, sampler_inputs.get("steps"))
    sampler_cfg = _scalar_from_node_output(workflow, sampler_inputs.get("cfg"))
    sampler_name = _scalar_from_node_output(workflow, sampler_inputs.get("sampler_name"))
    sampler_scheduler = _scalar_from_node_output(workflow, sampler_inputs.get("scheduler"))
    sampler_denoise = _scalar_from_node_output(workflow, sampler_inputs.get("denoise"))
    checkpoint = _first_input(analysis, "ckpt_name")
    diffusion_model = _first_input(analysis, "unet_name")
    api_model = _first_input(analysis, "model")
    clip = _first_input(analysis, "clip_name", "clip_name1")
    vae = _first_input(analysis, "vae_name")
    model = _first_present(checkpoint, diffusion_model, api_model, base.get("model"))
    params = {
        "generation_mode": generation_mode,
        "model": model or "",
        "checkpoint": _first_present(checkpoint, base.get("checkpoint")) or "",
        "diffusion_model": _first_present(diffusion_model, base.get("diffusion_model")) or "",
        "clip": _first_present(clip, base.get("clip")) or "",
        "vae": _first_present(vae, base.get("vae")) or "",
        "prompt": _first_present(prompt, base.get("prompt")) or "",
        "negative_prompt": _first_present(negative_prompt, base.get("negative_prompt")) or "",
        "width": _first_present(
            _positive_number_or_none(_first_input(analysis, "width")),
            _positive_number_or_none(base.get("width")),
            1024,
        ),
        "height": _first_present(
            _positive_number_or_none(_first_input(analysis, "height")),
            _positive_number_or_none(base.get("height")),
            1024,
        ),
        "batch_size": _first_present(
            _positive_number_or_none(_first_input(analysis, "batch_size")),
            _positive_number_or_none(base.get("batch_size")),
            1,
        ),
        "steps": _first_present(
            _positive_number_or_none(_first_input(analysis, "steps")),
            _positive_number_or_none(sampler_steps),
            _positive_number_or_none(base.get("steps")),
            20,
        ),
        "cfg": _first_present(
            _first_input(analysis, "cfg", "cfg_scale", "guidance"),
            sampler_cfg,
            _positive_number_or_none(base.get("cfg")),
            7,
        ),
        "seed": _first_present(
            _first_input(analysis, "seed", "noise_seed"),
            sampler_seed,
            _positive_number_or_none(base.get("seed")),
            42,
        ),
        "sampler_name": _first_present(_first_input(analysis, "sampler_name"), sampler_name, base.get("sampler_name")) or "",
        "scheduler": _first_present(_first_input(analysis, "scheduler"), sampler_scheduler, base.get("scheduler")) or "",
        "denoise_strength": _first_present(_first_input(analysis, "denoise"), sampler_denoise, base.get("denoise_strength"), 0),
        "upscale_model": _first_present(_first_input(analysis, "model_name"), base.get("upscale_model")) or "",
        "loras": base.get("loras") if isinstance(base.get("loras"), list) else [],
        "controlnet": base.get("controlnet") if isinstance(base.get("controlnet"), dict) else None,
    }
    return params


def _materialize_bundle(bundle: OriginBundle) -> tuple[Path, dict[str, Any]]:
    source_file = ORIGIN_DIR / bundle.source_path
    raw_payload = _read_json(source_file)
    source_format = "ui_graph" if is_ui_graph_workflow(raw_payload) else "api_prompt"
    normalized = normalize_uploaded_workflow_json(raw_payload)
    wrapper = sanitize_workflow_json(normalized)
    workflow = wrapper["workflow_json"]
    analysis = analyze_workflow_json(workflow)
    if analysis.denied_classes:
        raise WorkflowValidationError(
            f"{bundle.source_path} uses denied classes: {sorted(analysis.denied_classes)}"
        )
    allowlist_status = "allowlisted"
    allowlist_message = ""
    try:
        enforce_allowlist(analysis)
    except Exception as exc:
        allowlist_status = "custom_nodes_required"
        allowlist_message = str(exc)
    schema = build_ui_schema(analysis=analysis, raw_workflow=workflow)

    conversion = {
        "source_path": bundle.source_path,
        "source_format": source_format,
        "node_count": len(workflow),
        "class_count": len(analysis.class_types),
        "structural_status": "pass",
        "allowlist_status": allowlist_status,
        "allowlist_message": allowlist_message,
        "unknown_classes": sorted(analysis.unknown_classes),
        "denied_classes": sorted(analysis.denied_classes),
    }
    manifest = {
        "schema_version": 1,
        "id": bundle.workflow_id,
        "name": bundle.name,
        "description": bundle.description,
        "workflow_file": "workflow.json",
        "source": "official_origin",
        "origin_source_path": bundle.source_path,
        "source_format": source_format,
        "output_kinds": _workflow_output_kinds(workflow),
        "default_params": _default_params(wrapper, analysis, bundle.generation_mode, workflow),
        "required_models": wrapper.get("required_models") or [],
        "required_loras": wrapper.get("required_loras") or [],
        "required_controlnets": wrapper.get("required_controlnets") or [],
        "required_custom_nodes": sorted(analysis.unknown_classes),
        "conversion": conversion,
        "ui": {
            "initial_collapsed": True,
            "panels": schema.to_dict()["panels"],
        },
    }

    bundle_dir = TARGET_DIR / bundle.workflow_id
    bundle_dir.mkdir(parents=True, exist_ok=True)
    _write_json(bundle_dir / "workflow.json", workflow)
    _write_json(bundle_dir / "manifest.json", manifest)
    unknown_note = (
        "None"
        if not analysis.unknown_classes
        else ", ".join(sorted(analysis.unknown_classes))
    )
    readme = (
        f"# {bundle.name}\n\n"
        f"{bundle.description}\n\n"
        f"- Source: `workflows/comfyui/origin/{bundle.source_path}`\n"
        f"- Source Format: `{source_format}`\n"
        f"- Structural Test: `pass` ({len(workflow)} nodes)\n"
        f"- Allowlist Status: `{allowlist_status}`\n"
        f"- Static Unknown Nodes: {unknown_note}\n"
        f"- Live Runtime Check: run `python3 scripts/comfyui/official_workflow_probe.py --preflight-only --only {bundle.workflow_id}` against a running ComfyUI.\n"
        f"- Regenerate: `python3 scripts/comfyui/materialize_system_workflows.py`\n"
    )
    (bundle_dir / "README.md").write_text(readme, encoding="utf-8")
    return bundle_dir, conversion


def main() -> None:
    _validate_bundle_registry()
    written = []
    for bundle in ORIGIN_BUNDLES:
        path, conversion = _materialize_bundle(bundle)
        written.append((bundle.workflow_id, path, conversion))
        rel = path.relative_to(REPO_ROOT)
        print(
            f"materialized {rel} "
            f"({conversion['node_count']} nodes, {conversion['allowlist_status']})"
        )
    print(f"\nDone. {len(written)} origin workflow bundles materialized.")


if __name__ == "__main__":
    main()
