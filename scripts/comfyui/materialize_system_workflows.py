#!/usr/bin/env python3
"""Materialize the built-in t2i / i2i / inpaint / outpaint / upscale /
controlnet workflows from services/comfyui/workflow/builder.py into
workflows/comfyui/system/<id>/ as static API-format JSON files.

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
from services.comfyui.template.ui_schema import build_ui_schema  # noqa: E402
from services.comfyui.validation.rules import WorkflowValidationError  # noqa: E402
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
]


def _materialize_one(workflow_id, label, description, builder, extra_params):
    params = dict(_COMMON_TXT2IMG_PARAMS)
    params.update(extra_params)
    workflow = builder(params, error_cls=WorkflowValidationError)

    analysis = analyze_workflow_json(workflow)
    schema = build_ui_schema(analysis=analysis)

    target_dir = REPO_ROOT / "workflows" / "comfyui" / "system" / workflow_id
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
        f"- Source: `services/comfyui/workflow/builder.py`\n"
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
    print(f"\nDone. {len(written)} workflows materialized.")


if __name__ == "__main__":
    main()
