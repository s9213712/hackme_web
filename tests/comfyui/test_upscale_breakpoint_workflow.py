import json
from pathlib import Path

from services.comfyui.template.upscale_breakpoint import (
    COMBINED_UPSCALE_MODE,
    FIRST_UPSCALE_STAGE,
    LATENT_UPSCALE_MODE,
    MODEL_UPSCALE_MODE,
    SECOND_UPSCALE_STAGE,
    apply_upscale_breakpoint,
)


ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_PATH = ROOT / "workflows" / "comfyui" / "origin_multi_method_upscale" / "workflow.json"


def _workflow():
    return json.loads(WORKFLOW_PATH.read_text(encoding="utf-8"))


def test_upscale_breakpoint_first_stage_keeps_only_first_upscale_output():
    original = _workflow()
    selection = apply_upscale_breakpoint(
        original,
        {"77": {"model_name": "unused.safetensors"}, "61": {"steps": 12}},
        {"stage": FIRST_UPSCALE_STAGE},
    )
    workflow = selection.workflow

    assert selection.stage == FIRST_UPSCALE_STAGE
    assert "77" not in workflow
    assert "71" not in workflow
    assert "8" not in workflow
    assert {"66", "73", "93", "94"}.isdisjoint(workflow)
    assert workflow["76"]["class_type"] == "SaveImage"
    assert workflow["76"]["inputs"]["images"] == ["64", 0]
    assert workflow["76"]["_meta"]["title"] == "一次放大輸出"
    assert "77" not in selection.user_inputs
    assert selection.user_inputs["61"]["steps"] == 12
    assert "77" in original


def test_upscale_breakpoint_second_stage_keeps_only_second_upscale_output():
    selection = apply_upscale_breakpoint(
        _workflow(),
        {"77": {"model_name": "ESRGAN\\OmniSR_X4_DIV2K.safetensors"}},
        {"stage": SECOND_UPSCALE_STAGE},
    )
    workflow = selection.workflow

    assert selection.stage == SECOND_UPSCALE_STAGE
    assert "77" in workflow
    assert "71" in workflow
    assert "8" not in workflow
    assert {"66", "73", "93", "94"}.isdisjoint(workflow)
    assert workflow["76"]["inputs"]["images"] == ["71", 0]
    assert workflow["76"]["_meta"]["title"] == "二次放大輸出"
    assert selection.user_inputs["77"]["model_name"] == "ESRGAN\\OmniSR_X4_DIV2K.safetensors"


def test_upscale_mode_model_only_uses_origin_decode_then_model_upscale():
    selection = apply_upscale_breakpoint(
        _workflow(),
        {"61": {"steps": 12}, "63": {"scale_by": 2.5}, "77": {"model_name": "ESRGAN\\OmniSR_X4_DIV2K.safetensors"}},
        {"mode": MODEL_UPSCALE_MODE},
    )
    workflow = selection.workflow

    assert selection.stage == MODEL_UPSCALE_MODE
    assert "8" in workflow
    assert {"61", "63", "64", "66", "73", "93", "94"}.isdisjoint(workflow)
    assert workflow["71"]["inputs"]["image"] == ["8", 0]
    assert workflow["76"]["inputs"]["images"] == ["71", 0]
    assert workflow["76"]["_meta"]["title"] == "模型放大輸出"
    assert "61" not in selection.user_inputs
    assert "63" not in selection.user_inputs
    assert selection.user_inputs["77"]["model_name"] == "ESRGAN\\OmniSR_X4_DIV2K.safetensors"


def test_upscale_mode_latent_only_hides_model_upscale_nodes():
    selection = apply_upscale_breakpoint(
        _workflow(),
        {"61": {"steps": 12}, "77": {"model_name": "unused.safetensors"}},
        {"mode": LATENT_UPSCALE_MODE},
    )
    workflow = selection.workflow

    assert selection.stage == LATENT_UPSCALE_MODE
    assert "8" not in workflow
    assert "77" not in workflow
    assert "71" not in workflow
    assert workflow["76"]["inputs"]["images"] == ["64", 0]
    assert workflow["76"]["_meta"]["title"] == "Latent 放大輸出"
    assert selection.user_inputs["61"]["steps"] == 12
    assert "77" not in selection.user_inputs


def test_upscale_mode_combined_uses_latent_then_model_upscale():
    selection = apply_upscale_breakpoint(
        _workflow(),
        {"61": {"steps": 12}, "77": {"model_name": "ESRGAN\\OmniSR_X4_DIV2K.safetensors"}},
        {"mode": COMBINED_UPSCALE_MODE},
    )
    workflow = selection.workflow

    assert selection.stage == COMBINED_UPSCALE_MODE
    assert "8" not in workflow
    assert "61" in workflow
    assert "63" in workflow
    assert "64" in workflow
    assert "77" in workflow
    assert workflow["71"]["inputs"]["image"] == ["64", 0]
    assert workflow["76"]["inputs"]["images"] == ["71", 0]
    assert workflow["76"]["_meta"]["title"] == "Latent + 模型放大輸出"
    assert selection.user_inputs["61"]["steps"] == 12
    assert selection.user_inputs["77"]["model_name"] == "ESRGAN\\OmniSR_X4_DIV2K.safetensors"
