"""Validate every workflow shipped under workflows/comfyui/ passes
the importer pipeline: sanitize → analyze → allowlist enforcement.

Failing here means a builder change desynced the materialized JSON;
re-run ``python3 scripts/comfyui/materialize_system_workflows.py`` to
regenerate."""

import json
from pathlib import Path

import pytest

from services.comfyui.template.analyzer import analyze_workflow_json
from services.comfyui.template.safety import enforce_allowlist
from services.comfyui.validation.sanitize import sanitize_workflow_json


REPO_ROOT = Path(__file__).resolve().parents[2]
SYSTEM_DIR = REPO_ROOT / "workflows" / "comfyui"


def _system_ids():
    if not SYSTEM_DIR.exists():
        return []
    return sorted(p.name for p in SYSTEM_DIR.iterdir() if p.is_dir())


def test_system_dir_has_expected_workflows():
    ids = set(_system_ids())
    expected = {
        "txt2img_basic",
        "img2img_basic",
        "inpaint_basic",
        "outpaint_basic",
        "upscale_basic",
        "controlnet_canny",
    }
    missing = expected - ids
    assert not missing, f"missing system workflows: {missing}"


@pytest.mark.parametrize("workflow_id", _system_ids() or ["__placeholder__"])
def test_system_workflow_files_present(workflow_id):
    if workflow_id == "__placeholder__":
        pytest.skip("workflows/comfyui/ not populated yet")
    base = SYSTEM_DIR / workflow_id
    assert (base / "workflow.json").is_file(), f"{workflow_id}/workflow.json missing"
    assert (base / "manifest.json").is_file(), f"{workflow_id}/manifest.json missing"
    assert (base / "README.md").is_file(), f"{workflow_id}/README.md missing"


@pytest.mark.parametrize("workflow_id", _system_ids() or ["__placeholder__"])
def test_system_workflow_passes_sanitize(workflow_id):
    if workflow_id == "__placeholder__":
        pytest.skip("workflows/comfyui/ not populated yet")
    workflow = json.loads((SYSTEM_DIR / workflow_id / "workflow.json").read_text(encoding="utf-8"))
    sanitize_workflow_json(workflow)  # must not raise


@pytest.mark.parametrize("workflow_id", _system_ids() or ["__placeholder__"])
def test_system_workflow_passes_allowlist(workflow_id):
    if workflow_id == "__placeholder__":
        pytest.skip("workflows/comfyui/ not populated yet")
    workflow = json.loads((SYSTEM_DIR / workflow_id / "workflow.json").read_text(encoding="utf-8"))
    analysis = analyze_workflow_json(workflow)
    assert not analysis.denied_classes, f"{workflow_id} uses denied classes: {analysis.denied_classes}"
    enforce_allowlist(analysis)  # must not raise


@pytest.mark.parametrize("workflow_id", _system_ids() or ["__placeholder__"])
def test_system_manifest_schema_basics(workflow_id):
    if workflow_id == "__placeholder__":
        pytest.skip("workflows/comfyui/ not populated yet")
    manifest = json.loads((SYSTEM_DIR / workflow_id / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["schema_version"] == 1
    assert manifest["id"] == workflow_id
    assert manifest["workflow_file"] == "workflow.json"
    assert isinstance(manifest.get("name"), str) and manifest["name"]
    assert isinstance(manifest.get("description"), str)
    ui = manifest.get("ui") or {}
    assert isinstance(ui.get("panels"), list) and ui["panels"], (
        f"{workflow_id} has no UI panels"
    )


def test_txt2img_basic_has_minimal_node_count():
    """txt2img should be the smallest baseline."""
    workflow = json.loads((SYSTEM_DIR / "txt2img_basic" / "workflow.json").read_text(encoding="utf-8"))
    assert len(workflow) == 7, f"txt2img_basic should have 7 nodes, has {len(workflow)}"


def test_controlnet_canny_includes_preprocessor_and_apply():
    workflow = json.loads((SYSTEM_DIR / "controlnet_canny" / "workflow.json").read_text(encoding="utf-8"))
    classes = {n["class_type"] for n in workflow.values()}
    assert "ControlNetLoader" in classes
    assert "ControlNetApplyAdvanced" in classes
    assert "CannyEdgePreprocessor" in classes


def test_inpaint_basic_uses_inpaint_encoder():
    workflow = json.loads((SYSTEM_DIR / "inpaint_basic" / "workflow.json").read_text(encoding="utf-8"))
    classes = {n["class_type"] for n in workflow.values()}
    assert "VAEEncodeForInpaint" in classes
    assert "LoadImageMask" in classes


def test_outpaint_basic_includes_pad_for_outpaint():
    workflow = json.loads((SYSTEM_DIR / "outpaint_basic" / "workflow.json").read_text(encoding="utf-8"))
    classes = {n["class_type"] for n in workflow.values()}
    assert "ImagePadForOutpaint" in classes


def test_upscale_basic_uses_upscale_model_loader():
    workflow = json.loads((SYSTEM_DIR / "upscale_basic" / "workflow.json").read_text(encoding="utf-8"))
    classes = {n["class_type"] for n in workflow.values()}
    assert "UpscaleModelLoader" in classes
    assert "ImageUpscaleWithModel" in classes
