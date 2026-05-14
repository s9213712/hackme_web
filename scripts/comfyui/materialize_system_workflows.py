#!/usr/bin/env python3
"""Materialize built-in builder workflows and official native ComfyUI
template exports into
workflows/comfyui/<id>/ as static API-format JSON files.

Each generated subdir contains:
- workflow.json: the API-format graph the builder produces (pretty-printed).
- manifest.json: a minimal §18.3 manifest that registers it as a system
  workflow and describes the user-editable panels (auto-derived from the
  analyzer's UI schema).
- README.md: short Chinese description.

This is idempotent — re-running it overwrites with the current builder's
output, so when the builder evolves these stay in lockstep.

Usage:
  python3 scripts/comfyui/materialize_system_workflows.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from services.comfyui.template.analyzer import analyze_workflow_json  # noqa: E402
from services.comfyui.template.normalize import normalize_uploaded_workflow_json  # noqa: E402
from services.comfyui.template.safety import enforce_allowlist  # noqa: E402
from services.comfyui.template.ui_schema import build_ui_schema  # noqa: E402
from services.comfyui.validation.rules import WorkflowValidationError  # noqa: E402
from services.comfyui.validation.sanitize import sanitize_workflow_json  # noqa: E402
from services.comfyui.workflow.builder import (  # noqa: E402
    build_image_to_image_workflow,
    build_inpaint_workflow,
    build_outpaint_workflow,
    build_text_to_image_workflow,
    build_upscale_workflow,
)


# Common params reused across modes to keep the resulting workflows minimal
# and within the §3 limits (50 nodes, 256KB).
_COMMON_TXT2IMG_PARAMS = {
    "model": "v1-5-pruned.safetensors",
    "vae": "",
    "prompt": "a serene landscape painting, soft light",
    "negative_prompt": "low quality, blurry, watermark",
    "width": 512,
    "height": 512,
    "batch_size": 1,
    "seed": 42,
    "steps": 20,
    "cfg": 7.5,
    "sampler_name": "euler",
    "scheduler": "normal",
    "loras": [],
    "filename_prefix": "hackme_web",
}


def build_flux_text_to_image_workflow(params, *, error_cls):
    return {
        "1": {"class_type": "DualCLIPLoader", "inputs": {"clip_name1": "clip_l.safetensors", "clip_name2": "t5xxl_fp16.safetensors", "type": "flux", "device": "default"}},
        "2": {"class_type": "CLIPTextEncode", "inputs": {"text": params["prompt"], "clip": ["1", 0]}},
        "3": {"class_type": "UNETLoader", "inputs": {"unet_name": "flux1-dev.safetensors", "weight_dtype": "default"}},
        "4": {"class_type": "FluxGuidance", "inputs": {"conditioning": ["2", 0], "guidance": float(params.get("cfg") or 3.5)}},
        "5": {"class_type": "BasicGuider", "inputs": {"model": ["3", 0], "conditioning": ["4", 0]}},
        "6": {"class_type": "KSamplerSelect", "inputs": {"sampler_name": "euler"}},
        "7": {"class_type": "BasicScheduler", "inputs": {"model": ["3", 0], "scheduler": "simple", "steps": int(params["steps"]), "denoise": 1.0}},
        "8": {"class_type": "RandomNoise", "inputs": {"noise_seed": int(params["seed"])}},
        "9": {"class_type": "EmptyLatentImage", "inputs": {"width": int(params.get("width") or 1024), "height": int(params.get("height") or 1024), "batch_size": 1}},
        "10": {"class_type": "SamplerCustomAdvanced", "inputs": {"noise": ["8", 0], "guider": ["5", 0], "sampler": ["6", 0], "sigmas": ["7", 0], "latent_image": ["9", 0]}},
        "11": {"class_type": "VAELoader", "inputs": {"vae_name": "ae.safetensors"}},
        "12": {"class_type": "VAEDecode", "inputs": {"samples": ["10", 0], "vae": ["11", 0]}},
        "13": {"class_type": "SaveImage", "inputs": {"filename_prefix": "hackme_web_flux", "images": ["12", 0]}},
    }


def build_sd35_text_to_image_workflow(params, *, error_cls):
    return {
        "1": {"class_type": "TripleCLIPLoader", "inputs": {"clip_name1": "clip_l.safetensors", "clip_name2": "clip_g.safetensors", "clip_name3": "t5xxl_fp16.safetensors"}},
        "2": {"class_type": "CLIPTextEncode", "inputs": {"text": params["prompt"], "clip": ["1", 0]}},
        "3": {"class_type": "CLIPTextEncode", "inputs": {"text": params.get("negative_prompt") or "", "clip": ["1", 0]}},
        "4": {"class_type": "UNETLoader", "inputs": {"unet_name": "sd3.5_large.safetensors", "weight_dtype": "default"}},
        "5": {"class_type": "ModelSamplingSD3", "inputs": {"model": ["4", 0], "shift": 3.0}},
        "6": {"class_type": "EmptyLatentImage", "inputs": {"width": int(params.get("width") or 1024), "height": int(params.get("height") or 1024), "batch_size": 1}},
        "7": {"class_type": "KSampler", "inputs": {"seed": int(params["seed"]), "steps": int(params["steps"]), "cfg": float(params.get("cfg") or 4.5), "sampler_name": "euler", "scheduler": "sgm_uniform", "denoise": 1, "model": ["5", 0], "positive": ["2", 0], "negative": ["3", 0], "latent_image": ["6", 0]}},
        "8": {"class_type": "VAELoader", "inputs": {"vae_name": "sd3_vae.safetensors"}},
        "9": {"class_type": "VAEDecode", "inputs": {"samples": ["7", 0], "vae": ["8", 0]}},
        "10": {"class_type": "SaveImage", "inputs": {"filename_prefix": "hackme_web_sd35", "images": ["9", 0]}},
    }


def build_wan_i2v_workflow(params, *, error_cls):
    return {
        "1": {"class_type": "LoadImage", "inputs": {"image": "wan_start.png", "upload": "image"}},
        "2": {"class_type": "CLIPLoader", "inputs": {"clip_name": "umt5_xxl_fp16.safetensors", "type": "wan", "device": "default"}},
        "3": {"class_type": "CLIPTextEncode", "inputs": {"text": params["prompt"], "clip": ["2", 0]}},
        "4": {"class_type": "CLIPTextEncode", "inputs": {"text": params.get("negative_prompt") or "", "clip": ["2", 0]}},
        "5": {"class_type": "VAELoader", "inputs": {"vae_name": "wan_2.1_vae.safetensors"}},
        "6": {"class_type": "WanImageToVideo", "inputs": {"positive": ["3", 0], "negative": ["4", 0], "vae": ["5", 0], "width": int(params.get("width") or 832), "height": int(params.get("height") or 480), "length": int(params.get("length") or 81), "batch_size": 1, "start_image": ["1", 0]}},
        "7": {"class_type": "UNETLoader", "inputs": {"unet_name": "wan2.1_i2v_480p_14B_fp16.safetensors", "weight_dtype": "default"}},
        "8": {"class_type": "KSampler", "inputs": {"seed": int(params["seed"]), "steps": int(params["steps"]), "cfg": float(params.get("cfg") or 6), "sampler_name": "euler", "scheduler": "normal", "denoise": 1, "model": ["7", 0], "positive": ["6", 0], "negative": ["6", 1], "latent_image": ["6", 2]}},
        "9": {"class_type": "VAEDecode", "inputs": {"samples": ["8", 0], "vae": ["5", 0]}},
        "10": {"class_type": "SaveVideo", "inputs": {"filename_prefix": "hackme_web_wan", "images": ["9", 0], "fps": 16}},
    }


def _img_ref(filename: str) -> dict:
    """LoadImage params for builder helpers expecting a `source_image_ref` dict.

    Builder uses ``source_image["filename"]`` directly; mask helpers also
    need the same shape. Keep both name + filename for cross-helper compat.
    """
    return {
        "name": filename,
        "filename": filename,
        "subfolder": "",
        "type": "input",
    }


# (workflow_id, label, description, builder, extra_params)
_TARGETS = [
    (
        "txt2img_basic",
        "Text-to-Image（基礎）",
        "最簡單的 txt2img：CheckpointLoader + KSampler + VAEDecode + SaveImage。",
        build_text_to_image_workflow,
        {},
    ),
    (
        "img2img_basic",
        "Image-to-Image（基礎）",
        "在 txt2img 基礎上加入 LoadImage + VAEEncode 上行；denoise 由使用者調整。",
        build_image_to_image_workflow,
        {"source_image_ref": _img_ref("ref.png"), "denoise": 0.65},
    ),
    (
        "inpaint_basic",
        "Inpaint（基礎遮罩重繪）",
        "LoadImage + LoadImageMask + VAEEncodeForInpaint，搭配 inpainting checkpoint。",
        build_inpaint_workflow,
        {
            "source_image_ref": _img_ref("subject.png"),
            "mask_image_ref": _img_ref("subject_mask.png"),
            "denoise": 1.0,
            "grow_mask_by": 6,
            "model": "v1-5-inpainting.safetensors",
        },
    ),
    (
        "outpaint_basic",
        "Outpaint（單向外擴）",
        "Inpaint + ImagePadForOutpaint；預設往右外擴 256px。",
        build_outpaint_workflow,
        {
            "source_image_ref": _img_ref("subject.png"),
            "left": 0, "top": 0, "right": 256, "bottom": 0,
            "feathering": 32,
            "denoise": 1.0,
            "grow_mask_by": 6,
            "model": "v1-5-inpainting.safetensors",
        },
    ),
    (
        "upscale_basic",
        "Upscale（影像放大）",
        "LoadImage + UpscaleModelLoader + ImageUpscaleWithModel。",
        build_upscale_workflow,
        {
            "source_image_ref": _img_ref("photo.png"),
            "upscale_model": "RealESRGAN_x4plus.pth",
        },
    ),
    (
        "controlnet_canny",
        "ControlNet（Canny 邊緣引導）",
        "txt2img + Canny preprocessor + ControlNetApplyAdvanced；強度 / start / end 可調。",
        build_text_to_image_workflow,
        {
            # builder reads control["model_name"] / control["preprocessor"]
            "controlnet": {
                "enabled": True,
                "model_name": "control_canny.safetensors",
                "preprocessor": "CannyEdgePreprocessor",
                "type": "canny",
                "strength": 1.0,
                "start_percent": 0.0,
                "end_percent": 1.0,
                "image_ref": _img_ref("edge_source.png"),
            },
        },
    ),
    (
        "flux_txt2img_starter",
        "Flux（UNET / Dual CLIP 起手式）",
        "Flux text-to-image starter：DualCLIPLoader + UNETLoader + FluxGuidance + SamplerCustomAdvanced。",
        build_flux_text_to_image_workflow,
        {"generation_mode": "txt2img", "prompt": "a cinematic portrait, natural light, high detail", "width": 1024, "height": 1024, "steps": 24, "cfg": 3.5, "seed": 42},
    ),
    (
        "sd35_txt2img_starter",
        "SD3.5（Triple CLIP 起手式）",
        "SD3.5 text-to-image starter：TripleCLIPLoader + UNETLoader + ModelSamplingSD3 + KSampler。",
        build_sd35_text_to_image_workflow,
        {"generation_mode": "txt2img", "prompt": "a detailed cinematic scene, balanced composition", "negative_prompt": "low quality, blurry, watermark", "width": 1024, "height": 1024, "steps": 28, "cfg": 4.5, "seed": 42},
    ),
    (
        "wan_i2v_starter",
        "Wan（Image-to-Video 起手式）",
        "Wan image-to-video starter：LoadImage + WanImageToVideo + UNETLoader + SaveVideo；請依本地 Wan 節點版本調整模型檔名。",
        build_wan_i2v_workflow,
        {"generation_mode": "i2v", "prompt": "gentle camera movement, cinematic lighting", "negative_prompt": "low quality, flicker, artifacts", "width": 832, "height": 480, "steps": 20, "cfg": 6, "seed": 42},
    ),
]


_OFFICIAL_NATIVE_SOURCES = [
    (
        "image_z_image.json",
        "family_zit_txt2img",
        "Z-Image / ZIT（官方原生 T2I）",
        "由官方 ComfyUI Z-Image 原生模板轉換，subgraph 已展開為本專案 API workflow 格式。",
        "txt2img",
    ),
    (
        "image_anima_preview.json",
        "family_anima_txt2img",
        "Anima（官方原生 T2I）",
        "由官方 ComfyUI Anima preview 模板轉換，subgraph 已展開為本專案 API workflow 格式。",
        "txt2img",
    ),
    (
        "image_netayume_lumina_t2i.json",
        "family_netayume_txt2img",
        "NetaYume Lumina（官方原生 T2I）",
        "由官方 ComfyUI NetaYume Lumina 模板轉換，巢狀 subgraph 已展開為本專案 API workflow 格式。",
        "txt2img",
    ),
    (
        "image_flux2.json",
        "flux2_image_edit",
        "Flux.2（官方原生 Image Edit）",
        "由官方 ComfyUI Flux.2 image edit 模板轉換，保留圖片輸入、Flux.2 scheduler 與 turbo LoRA 參數。",
        "img2img",
    ),
    (
        "03_video_wan2_2_14B_i2v_subgraphed.json",
        "wan22_14b_i2v_subgraphed",
        "Wan 2.2 14B（官方原生 I2V）",
        "由官方 ComfyUI Wan 2.2 14B image-to-video subgraph 模板轉換。",
        "i2v",
    ),
    (
        "05_audio_ace_step_1_t2a_song_subgraphed.json",
        "ace_step_15_t2a_song",
        "ACE-Step 1.5（官方原生 T2A Song）",
        "由官方 ComfyUI ACE-Step 1.5 text-to-audio/song subgraph 模板轉換。",
        "t2a",
    ),
    (
        "api_bytedance_seedream_5_0_lite_t2i.json",
        "bytedance_seedream_5_lite_t2i",
        "ByteDance Seedream 5.0 Lite（官方 API T2I）",
        "由官方 ComfyUI API 節點模板轉換；需要本機 ComfyUI 具備對應 API node 與憑證設定。",
        "txt2img",
    ),
    (
        "api_grok_image_edit.json",
        "grok_image_edit",
        "Grok Image Edit（官方 API I2I）",
        "由官方 ComfyUI Grok image edit API 節點模板轉換；需要本機 ComfyUI 具備對應 API node 與憑證設定。",
        "img2img",
    ),
    (
        "sd3.5_simple_example.json",
        "sd35_simple_example",
        "SD3.5（官方 simple example）",
        "由官方 ComfyUI SD3.5 simple example 模板轉換。",
        "txt2img",
    ),
    (
        "sdxl_simple_example.json",
        "sdxl_simple_example",
        "SDXL（官方 simple example）",
        "由官方 ComfyUI SDXL simple example 模板轉換。",
        "txt2img",
    ),
]


def _materialize_one(workflow_id, label, description, builder, extra_params):
    params = dict(_COMMON_TXT2IMG_PARAMS)
    params.update(extra_params)
    workflow = builder(params, error_cls=WorkflowValidationError)

    analysis = analyze_workflow_json(workflow)
    schema = build_ui_schema(analysis=analysis)

    target_dir = REPO_ROOT / "workflows" / "comfyui" / workflow_id
    target_dir.mkdir(parents=True, exist_ok=True)

    (target_dir / "workflow.json").write_text(
        json.dumps(workflow, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )

    manifest = {
        "schema_version": 1,
        "id": workflow_id,
        "name": label,
        "description": description,
        "workflow_file": "workflow.json",
        "default_params": {
            "generation_mode": params.get("generation_mode") or "txt2img",
            "model": params.get("model") or "",
            "prompt": params.get("prompt") or "",
            "negative_prompt": params.get("negative_prompt") or "",
            "width": params.get("width") or 1024,
            "height": params.get("height") or 1024,
            "steps": params.get("steps") or 20,
            "cfg": params.get("cfg") or 7,
            "seed": params.get("seed") or 42,
        },
        "ui": {
            "initial_collapsed": True,
            "panels": schema.to_dict()["panels"],
        },
    }
    (target_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )

    (target_dir / "README.md").write_text(
        f"# {label}\n\n{description}\n\n"
        f"- Source: `scripts/comfyui/materialize_system_workflows.py`\n"
        f"- Regenerate: `python3 scripts/comfyui/materialize_system_workflows.py`\n",
        encoding="utf-8",
    )
    return target_dir, workflow


def _workflow_output_kinds(workflow):
    classes = {
        str((node or {}).get("class_type") or "").strip()
        for node in (workflow or {}).values()
        if isinstance(node, dict)
    }
    kinds = []
    if any(name in classes for name in {"SaveImage", "PreviewImage"}):
        kinds.append("image")
    if any("video" in name.lower() for name in classes):
        kinds.append("video")
    if any(token in name.lower() for name in classes for token in ("audio", "music", "wave", "wav")):
        kinds.append("music")
    return kinds or ["image"]


def _first_input(analysis, *names, category=None):
    for field_obj in analysis.user_inputs:
        if category is not None and field_obj.category != category:
            continue
        if field_obj.input_name in names and not field_obj.is_link:
            return field_obj.raw_value
    return None


def _official_default_params(analysis, generation_mode):
    prompt = _first_input(analysis, "prompt", "text", "string_b", "tags")
    negative_prompt = _first_input(analysis, "negative", "negative_prompt", "string_a")
    model = _first_input(
        analysis,
        "ckpt_name",
        "unet_name",
        "model",
        "clip_name",
        "clip_name1",
        "vae_name",
    )
    return {
        "generation_mode": generation_mode,
        "model": model or "",
        "prompt": prompt or "",
        "negative_prompt": negative_prompt or "",
        "width": _first_input(analysis, "width") or 1024,
        "height": _first_input(analysis, "height") or 1024,
        "steps": _first_input(analysis, "steps") or 20,
        "cfg": _first_input(analysis, "cfg", "cfg_scale", "guidance") or 7,
        "seed": _first_input(analysis, "seed", "noise_seed") or 42,
    }


def _materialize_official_native(source_name, workflow_id, label, description, generation_mode):
    source_path = REPO_ROOT / "workflows" / "comfyui" / source_name
    target_dir = REPO_ROOT / "workflows" / "comfyui" / workflow_id
    target_workflow_path = target_dir / "workflow.json"
    if source_path.is_file():
        payload = json.loads(source_path.read_text(encoding="utf-8"))
        workflow = normalize_uploaded_workflow_json(payload)
        workflow = sanitize_workflow_json(workflow)["workflow_json"]
        source = "official_comfyui_native"
        source_file = f"workflows/comfyui/{source_name}"
    elif target_workflow_path.is_file():
        workflow = sanitize_workflow_json(
            json.loads(target_workflow_path.read_text(encoding="utf-8"))
        )["workflow_json"]
        source = "official_comfyui_native_converted"
        source_file = ""
    else:
        raise WorkflowValidationError(
            f"缺少官方 workflow 來源：{source_path.relative_to(REPO_ROOT)}"
        )

    analysis = analyze_workflow_json(workflow)
    enforce_allowlist(analysis)
    schema = build_ui_schema(analysis=analysis)

    target_dir.mkdir(parents=True, exist_ok=True)

    (target_dir / "workflow.json").write_text(
        json.dumps(workflow, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )

    manifest = {
        "schema_version": 1,
        "id": workflow_id,
        "name": label,
        "description": description,
        "workflow_file": "workflow.json",
        "source": source,
        "source_file": source_file,
        "output_kinds": _workflow_output_kinds(workflow),
        "default_params": _official_default_params(analysis, generation_mode),
        "ui": {
            "initial_collapsed": True,
            "panels": schema.to_dict()["panels"],
        },
    }
    (target_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )

    source_line = (
        f"- Source: `{source_file}`\n"
        if source_file
        else "- Source: converted `workflow.json` checked into this bundle\n"
    )
    (target_dir / "README.md").write_text(
        f"# {label}\n\n{description}\n\n"
        f"{source_line}"
        f"- Converted Format: ComfyUI API workflow + hackme_web manifest\n"
        f"- Regenerate: `python3 scripts/comfyui/materialize_system_workflows.py`\n",
        encoding="utf-8",
    )
    return target_dir, workflow


def main():
    written = []
    for target in _TARGETS:
        path, workflow = _materialize_one(*target)
        written.append((target[0], path, len(workflow)))
        print(f"wrote {path.relative_to(REPO_ROOT)}  ({len(workflow)} nodes)")
    for source in _OFFICIAL_NATIVE_SOURCES:
        path, workflow = _materialize_official_native(*source)
        written.append((source[1], path, len(workflow)))
        print(f"wrote {path.relative_to(REPO_ROOT)}  ({len(workflow)} nodes)")
    print(f"\nDone. {len(written)} workflows materialized.")


if __name__ == "__main__":
    main()
