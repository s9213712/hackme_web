"""§12 fixture regression — every fixture must clear analyze + sanitize +
allowlist on its own."""

import pytest

from services.comfyui.template.allowlist import (
    CONTROLNET_PREPROCESSOR_ALLOWLIST,
    CORE_ALLOWLIST,
)
from services.comfyui.template.analyzer import analyze_workflow_json
from services.comfyui.template.safety import enforce_allowlist
from services.comfyui.validation.sanitize import sanitize_workflow_json
from tests.comfyui.fixtures.workflows import (
    controlnet_canny,
    img2img_basic,
    inpaint_basic,
    txt2img_basic,
)

ALL_FIXTURES = {
    "txt2img_basic": txt2img_basic,
    "img2img_basic": img2img_basic,
    "inpaint_basic": inpaint_basic,
    "controlnet_canny": controlnet_canny,
}


@pytest.mark.parametrize("name,factory", list(ALL_FIXTURES.items()))
def test_fixture_passes_sanitize(name, factory):
    sanitize_workflow_json(factory())  # must not raise


@pytest.mark.parametrize("name,factory", list(ALL_FIXTURES.items()))
def test_fixture_analyze_collects_classes(name, factory):
    analysis = analyze_workflow_json(factory())
    assert analysis.class_types
    # No fixture should be denied (it would mean we shipped a fixture using
    # a class on the EXPLICIT_DENYLIST — that's a bug in the fixture).
    assert not analysis.denied_classes
    # Every class must be on the allowlist (CORE or controlnet preprocessors)
    allowed = CORE_ALLOWLIST | CONTROLNET_PREPROCESSOR_ALLOWLIST
    extra = analysis.class_types - allowed
    assert not extra, f"{name} uses classes outside the allowlist: {extra}"


@pytest.mark.parametrize("name,factory", list(ALL_FIXTURES.items()))
def test_fixture_passes_allowlist_enforcement(name, factory):
    analysis = analyze_workflow_json(factory())
    enforce_allowlist(analysis)  # must not raise


@pytest.mark.parametrize("name,factory", list(ALL_FIXTURES.items()))
def test_fixture_factory_returns_independent_copies(name, factory):
    """Factories deep-copy so test mutations don't leak between runs."""
    a = factory()
    b = factory()
    a["4"]["inputs"]["ckpt_name"] = "TAINTED.safetensors"
    assert b["4"]["inputs"]["ckpt_name"] != "TAINTED.safetensors"


def test_fixture_txt2img_has_baseline_node_set():
    workflow = txt2img_basic()
    classes = {node["class_type"] for node in workflow.values()}
    assert "CheckpointLoaderSimple" in classes
    assert "KSampler" in classes
    assert "SaveImage" in classes


def test_fixture_img2img_has_load_image_and_vaeencode():
    workflow = img2img_basic()
    classes = {node["class_type"] for node in workflow.values()}
    assert "LoadImage" in classes
    assert "VAEEncode" in classes


def test_fixture_inpaint_has_mask_and_inpaint_encoder():
    workflow = inpaint_basic()
    classes = {node["class_type"] for node in workflow.values()}
    assert "LoadImageMask" in classes
    assert "VAEEncodeForInpaint" in classes


def test_fixture_controlnet_has_loader_preprocessor_and_apply():
    workflow = controlnet_canny()
    classes = {node["class_type"] for node in workflow.values()}
    assert "ControlNetLoader" in classes
    assert "CannyEdgePreprocessor" in classes
    assert "ControlNetApplyAdvanced" in classes
