"""Validate every materialized workflow shipped under workflows/comfyui/.

The canonical source set is workflows/comfyui/origin/*/*/*.json. Each raw
workflow must have a direct system bundle with workflow.json + manifest.json so
first-boot seeding can copy it into runtime/comfyui/.
"""

import json
from pathlib import Path

import pytest

from services.comfyui.template.analyzer import analyze_workflow_json
from services.comfyui.template.seeding import SYSTEM_WORKFLOW_IDS
from services.comfyui.validation.sanitize import sanitize_workflow_json


REPO_ROOT = Path(__file__).resolve().parents[2]
SYSTEM_DIR = REPO_ROOT / "workflows" / "comfyui"
ORIGIN_DIR = SYSTEM_DIR / "origin"

EXPECTED_ORIGIN_WORKFLOW_IDS = {
    "origin_audio_ace_step_15_xl_base",
    "origin_qwen_image_controlnet_2512",
    "origin_sd35_large_canny_controlnet",
    "origin_sd35_large_depth_controlnet",
    "origin_capybara_image_edit",
    "origin_qwen_image_edit_2509",
    "origin_one_click_anime_to_real",
    "origin_one_click_replace_aio_2511",
    "origin_flux_fill_outpaint",
    "origin_anima_txt2img",
    "origin_sd35_txt2img",
    "origin_sdxl_txt2img",
    "origin_zit_txt2img",
    "origin_flux_dev_txt2img",
    "origin_qwen_image_txt2img",
    "origin_netayume_txt2img",
    "origin_compare_2checkpoints",
    "origin_sdpose_multi_person",
    "origin_sam3_segmentation",
    "origin_multi_method_upscale",
    "origin_capybara_video_edit",
    "origin_wan_vace_inpainting",
    "origin_wan22_14b_i2v_subgraphed",
    "origin_ltx23_t2v",
}


def _system_ids():
    if not SYSTEM_DIR.exists():
        return []
    return sorted(
        p.name
        for p in SYSTEM_DIR.iterdir()
        if p.is_dir()
        and not p.name.startswith("imported_")
        and (p / "workflow.json").is_file()
        and (p / "manifest.json").is_file()
    )


def _manifest(workflow_id):
    return json.loads((SYSTEM_DIR / workflow_id / "manifest.json").read_text(encoding="utf-8"))


def _workflow(workflow_id):
    return json.loads((SYSTEM_DIR / workflow_id / "workflow.json").read_text(encoding="utf-8"))


def test_system_registry_matches_origin_workflow_ids():
    assert set(SYSTEM_WORKFLOW_IDS) == EXPECTED_ORIGIN_WORKFLOW_IDS


def test_system_dir_has_materialized_origin_workflows():
    ids = set(_system_ids())
    missing = EXPECTED_ORIGIN_WORKFLOW_IDS - ids
    assert not missing, f"missing system workflows: {missing}"


def test_every_origin_workflow_has_converted_bundle():
    origin_paths = {
        path.relative_to(ORIGIN_DIR).as_posix()
        for path in sorted(ORIGIN_DIR.glob("*/*/*.json"))
    }
    converted_paths = {
        _manifest(workflow_id)["conversion"]["source_path"]
        for workflow_id in EXPECTED_ORIGIN_WORKFLOW_IDS
    }
    assert converted_paths == origin_paths


@pytest.mark.parametrize("workflow_id", sorted(EXPECTED_ORIGIN_WORKFLOW_IDS))
def test_system_workflow_files_present(workflow_id):
    base = SYSTEM_DIR / workflow_id
    assert (base / "workflow.json").is_file(), f"{workflow_id}/workflow.json missing"
    assert (base / "manifest.json").is_file(), f"{workflow_id}/manifest.json missing"
    assert (base / "README.md").is_file(), f"{workflow_id}/README.md missing"


@pytest.mark.parametrize("workflow_id", sorted(EXPECTED_ORIGIN_WORKFLOW_IDS))
def test_system_workflow_passes_sanitize_and_analyze(workflow_id):
    sanitized = sanitize_workflow_json(_workflow(workflow_id))["workflow_json"]
    analysis = analyze_workflow_json(sanitized)
    assert not analysis.denied_classes, f"{workflow_id} uses denied classes: {analysis.denied_classes}"


@pytest.mark.parametrize("workflow_id", sorted(EXPECTED_ORIGIN_WORKFLOW_IDS))
def test_system_manifest_schema_basics(workflow_id):
    manifest = _manifest(workflow_id)
    assert manifest["schema_version"] == 1
    assert manifest["id"] == workflow_id
    assert manifest["workflow_file"] == "workflow.json"
    assert manifest["source"] == "official_origin"
    assert manifest["origin_source_path"].endswith(".json")
    assert isinstance(manifest.get("name"), str) and manifest["name"]
    assert isinstance(manifest.get("description"), str)
    assert manifest.get("source_format") in {"api_prompt", "ui_graph"}
    assert manifest.get("output_kinds")
    assert (manifest.get("default_params") or {}).get("generation_mode")
    ui = manifest.get("ui") or {}
    assert isinstance(ui.get("panels"), list) and ui["panels"], (
        f"{workflow_id} has no UI panels"
    )


@pytest.mark.parametrize("workflow_id", sorted(EXPECTED_ORIGIN_WORKFLOW_IDS))
def test_origin_conversion_status_is_recorded(workflow_id):
    conversion = _manifest(workflow_id).get("conversion") or {}
    assert conversion["structural_status"] == "pass"
    assert conversion["source_format"] in {"api_prompt", "ui_graph"}
    assert conversion["allowlist_status"] in {"allowlisted", "custom_nodes_required"}
    if conversion["allowlist_status"] == "allowlisted":
        assert conversion["unknown_classes"] == []
    else:
        assert conversion["unknown_classes"]


def test_all_origin_workflows_clear_static_allowlist():
    statuses = {
        _manifest(workflow_id)["conversion"]["allowlist_status"]
        for workflow_id in EXPECTED_ORIGIN_WORKFLOW_IDS
    }
    assert statuses == {"allowlisted"}


def test_anima_origin_workflow_defaults_keep_model_stack_aligned():
    workflow = _workflow("origin_anima_txt2img")
    manifest = _manifest("origin_anima_txt2img")
    defaults = manifest["default_params"]

    assert workflow["68"]["inputs"]["unet_name"] == "anima-preview2.safetensors"
    assert defaults["model"] == "anima-preview2.safetensors"
    assert defaults["diffusion_model"] == "anima-preview2.safetensors"
    assert defaults["clip"] == "qwen_3_06b_base.safetensors"
    assert defaults["vae"] == "qwen_image_vae.safetensors"
    assert defaults["prompt"].startswith("masterpiece, best quality")
    assert defaults["negative_prompt"].startswith("worst quality, low quality")


def test_text_to_audio_origin_workflow_uses_text_to_speech_mode():
    manifest = _manifest("origin_audio_ace_step_15_xl_base")
    workflow = _workflow("origin_audio_ace_step_15_xl_base")
    classes = {node["class_type"] for node in workflow.values()}

    assert manifest["default_params"]["generation_mode"] == "t2s"
    assert manifest["output_kinds"] == ["music"]
    assert "TextEncodeAceStepAudio1.5" in classes
