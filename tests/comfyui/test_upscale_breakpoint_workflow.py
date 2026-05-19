import json
from pathlib import Path

from services.comfyui.template.upscale_breakpoint import (
    FIRST_UPSCALE_STAGE,
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
