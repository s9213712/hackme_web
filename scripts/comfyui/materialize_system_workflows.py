#!/usr/bin/env python3
"""Refresh checked-in official ComfyUI workflow bundles.

The canonical source is the current folder layout under
``workflows/comfyui/<workflow_id>/``. Each bundle must already contain a
platform-ready ``workflow.json`` in ComfyUI API prompt format.

This script validates each official bundle and rewrites only the project
metadata files:

- ``manifest.json``: system registration metadata and generated UI panels.
- ``README.md``: short bundle note.

It intentionally does not read deleted native ComfyUI UI exports and does not
recreate removed legacy starter folders. If a bundle folder is deleted, remove
it from ``_OFFICIAL_BUNDLES`` and ``SYSTEM_WORKFLOW_IDS``.

Usage:
  python3 scripts/comfyui/materialize_system_workflows.py
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from services.comfyui.template.analyzer import analyze_workflow_json  # noqa: E402
from services.comfyui.template.safety import enforce_allowlist  # noqa: E402
from services.comfyui.template.ui_schema import build_ui_schema  # noqa: E402
from services.comfyui.validation.rules import WorkflowValidationError  # noqa: E402
from services.comfyui.validation.sanitize import sanitize_workflow_json  # noqa: E402


@dataclass(frozen=True)
class OfficialBundle:
    workflow_id: str
    name: str
    description: str
    generation_mode: str


_OFFICIAL_BUNDLES: tuple[OfficialBundle, ...] = (
    OfficialBundle(
        "txt2img_basic",
        "Text-to-Image（基礎）",
        "最簡單的 txt2img：CheckpointLoader + KSampler + VAEDecode + SaveImage。",
        "txt2img",
    ),
    OfficialBundle(
        "img2img_basic",
        "Image-to-Image（基礎）",
        "在 txt2img 基礎上加入 LoadImage + VAEEncode 上行；denoise 由使用者調整。",
        "img2img",
    ),
    OfficialBundle(
        "inpaint_basic",
        "Inpaint（基礎遮罩重繪）",
        "LoadImage + LoadImageMask + VAEEncodeForInpaint，搭配 inpainting checkpoint。",
        "inpaint",
    ),
    OfficialBundle(
        "outpaint_basic",
        "Outpaint（單向外擴）",
        "Inpaint + ImagePadForOutpaint；預設往右外擴 256px。",
        "outpaint",
    ),
    OfficialBundle(
        "upscale_basic",
        "Upscale（影像放大）",
        "LoadImage + UpscaleModelLoader + ImageUpscaleWithModel。",
        "upscale",
    ),
    OfficialBundle(
        "controlnet_canny",
        "ControlNet（Canny 邊緣引導）",
        "txt2img + Canny preprocessor + ControlNetApplyAdvanced；強度 / start / end 可調。",
        "txt2img",
    ),
    OfficialBundle(
        "family_zit_txt2img",
        "Z-Image / ZIT（官方 T2I）",
        "目前保留的 Z-Image / ZIT 官方系統模組；workflow.json 是平台可執行格式。",
        "txt2img",
    ),
    OfficialBundle(
        "family_anima_txt2img",
        "Anima（官方 T2I）",
        "目前保留的 Anima 官方系統模組；workflow.json 是平台可執行格式。",
        "txt2img",
    ),
    OfficialBundle(
        "family_netayume_txt2img",
        "NetaYume Lumina（官方 T2I）",
        "目前保留的 NetaYume Lumina 官方系統模組；workflow.json 是平台可執行格式。",
        "txt2img",
    ),
    OfficialBundle(
        "flux2_image_edit",
        "Flux.2（官方 Image Edit）",
        "目前保留的 Flux.2 image edit 官方系統模組；workflow.json 是平台可執行格式。",
        "img2img",
    ),
    OfficialBundle(
        "wan22_14b_i2v_subgraphed",
        "Wan 2.2 14B（官方 I2V）",
        "目前保留的 Wan 2.2 14B image-to-video 官方系統模組。",
        "i2v",
    ),
    OfficialBundle(
        "ace_step_15_t2a_song",
        "ACE-Step 1.5（官方 T2A Song）",
        "目前保留的 ACE-Step 1.5 text-to-audio/song 官方系統模組。",
        "t2a",
    ),
    OfficialBundle(
        "bytedance_seedream_5_lite_t2i",
        "ByteDance Seedream 5.0 Lite（官方 API T2I）",
        "目前保留的 Seedream API 官方系統模組；需要本機 ComfyUI 具備對應 API node 與憑證設定。",
        "txt2img",
    ),
    OfficialBundle(
        "grok_image_edit",
        "Grok Image Edit（官方 API I2I）",
        "目前保留的 Grok image edit API 官方系統模組；需要本機 ComfyUI 具備對應 API node 與憑證設定。",
        "img2img",
    ),
    OfficialBundle(
        "sd35_simple_example",
        "SD3.5（官方 simple example）",
        "目前保留的 SD3.5 官方 simple example 系統模組。",
        "txt2img",
    ),
    OfficialBundle(
        "sdxl_simple_example",
        "SDXL（官方 simple example）",
        "目前保留的 SDXL 官方 simple example 系統模組。",
        "txt2img",
    ),
)


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
    if any(
        token in name.lower()
        for name in classes
        for token in ("audio", "music", "wave", "wav")
    ):
        kinds.append("music")
    return kinds or ["image"]


def _first_input(analysis, *names):
    for field_obj in analysis.user_inputs:
        if field_obj.input_name in names and not field_obj.is_link:
            return field_obj.raw_value
    return None


def _default_params(analysis, generation_mode):
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


def _load_bundle_workflow(bundle: OfficialBundle):
    bundle_dir = REPO_ROOT / "workflows" / "comfyui" / bundle.workflow_id
    workflow_path = bundle_dir / "workflow.json"
    if not workflow_path.is_file():
        raise WorkflowValidationError(
            f"缺少官方 workflow bundle：{bundle.workflow_id}/workflow.json"
        )
    workflow = json.loads(workflow_path.read_text(encoding="utf-8"))
    return sanitize_workflow_json(workflow)["workflow_json"]


def _write_json(path: Path, payload):
    path.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )


def _refresh_bundle(bundle: OfficialBundle):
    bundle_dir = REPO_ROOT / "workflows" / "comfyui" / bundle.workflow_id
    workflow = _load_bundle_workflow(bundle)
    analysis = analyze_workflow_json(workflow)
    enforce_allowlist(analysis)
    schema = build_ui_schema(analysis=analysis)

    manifest = {
        "schema_version": 1,
        "id": bundle.workflow_id,
        "name": bundle.name,
        "description": bundle.description,
        "workflow_file": "workflow.json",
        "source": "official",
        "output_kinds": _workflow_output_kinds(workflow),
        "default_params": _default_params(analysis, bundle.generation_mode),
        "ui": {
            "initial_collapsed": True,
            "panels": schema.to_dict()["panels"],
        },
    }
    _write_json(bundle_dir / "manifest.json", manifest)

    readme = (
        f"# {bundle.name}\n\n"
        f"{bundle.description}\n\n"
        f"- Source: current checked-in `workflows/comfyui/{bundle.workflow_id}/workflow.json`\n"
        f"- Module Type: official system workflow\n"
        f"- Regenerate: `python3 scripts/comfyui/materialize_system_workflows.py`\n"
    )
    (bundle_dir / "README.md").write_text(readme, encoding="utf-8")
    return bundle_dir, workflow


def main():
    written = []
    for bundle in _OFFICIAL_BUNDLES:
        path, workflow = _refresh_bundle(bundle)
        written.append((bundle.workflow_id, path, len(workflow)))
        print(f"refreshed {path.relative_to(REPO_ROOT)}  ({len(workflow)} nodes)")
    print(f"\nDone. {len(written)} official workflow bundles refreshed.")


if __name__ == "__main__":
    main()
