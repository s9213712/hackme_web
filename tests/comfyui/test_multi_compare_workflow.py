import json
from pathlib import Path

import pytest

from services.comfyui.execution import collect_output_refs
from services.comfyui.template.multi_compare import (
    MultiCompareWorkflowError,
    expand_multi_compare_workflow,
)


ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_PATH = ROOT / "workflows" / "comfyui" / "origin_multi_compare_checkpoints_test" / "workflow.json"


def _workflow():
    return json.loads(WORKFLOW_PATH.read_text(encoding="utf-8"))


def test_multi_compare_expands_extra_checkpoint_branches_without_mutating_base():
    original = _workflow()
    user_inputs = {
        "3": {
            "seed": 12345,
            "steps": 12,
            "cfg": 5.5,
            "sampler_name": "euler",
            "scheduler": "normal",
            "denoise": 0.75,
        }
    }

    expansion = expand_multi_compare_workflow(
        original,
        user_inputs,
        {
            "checkpoints": [
                "SDXL/base-a.safetensors",
                "SDXL/base-b.safetensors",
                "SDXL/base-c.safetensors",
            ],
            "loras": [
                {"name": "compare-style.safetensors", "strength_model": 0.7, "strength_clip": 0.6}
            ],
        },
    )
    expanded = expansion.workflow

    assert "9200" not in original
    assert expanded["4"]["inputs"]["ckpt_name"] == "SDXL/base-a.safetensors"
    assert expanded["48"]["inputs"]["ckpt_name"] == "SDXL/base-b.safetensors"
    assert expanded["9200"]["inputs"]["ckpt_name"] == "SDXL/base-c.safetensors"

    assert expanded["8000"]["class_type"] == "LoraLoader"
    assert expanded["8100"]["class_type"] == "LoraLoader"
    assert expanded["8200"]["class_type"] == "LoraLoader"
    assert expanded["6"]["inputs"]["clip"] == ["8000", 1]
    assert expanded["7"]["inputs"]["clip"] == ["8000", 1]

    assert expanded["9201"]["inputs"]["model"] == ["8200", 0]
    assert expanded["9201"]["inputs"]["latent_image"] == ["5", 0]
    assert expanded["9201"]["inputs"]["positive"] == ["6", 0]
    assert expanded["9201"]["inputs"]["negative"] == ["7", 0]
    assert expanded["9201"]["inputs"]["seed"] == 12345
    assert expanded["9201"]["inputs"]["sampler_name"] == "euler"
    assert expanded["9202"]["inputs"]["samples"] == ["9201", 0]
    assert expanded["9202"]["inputs"]["vae"] == ["9200", 2]
    assert expanded["9203"]["inputs"]["images"] == ["9202", 0]

    assert expansion.user_inputs["9200"]["ckpt_name"] == "SDXL/base-c.safetensors"
    assert expansion.user_inputs["9201"]["steps"] == 12
    assert expansion.user_inputs["8200"]["lora_name"] == "compare-style.safetensors"
    assert expansion.user_inputs["8200"]["strength_clip"] == 0.6
    assert "base-c.safetensors" in expanded["9203"]["_meta"]["title"]
    assert "compare-style.safetensors" in expanded["9203"]["_meta"]["title"]
    assert expansion.output_labels[-1] == expanded["9203"]["_meta"]["title"]


def test_multi_compare_requires_at_least_two_checkpoints():
    with pytest.raises(MultiCompareWorkflowError, match="至少需要選擇 2 個"):
        expand_multi_compare_workflow(_workflow(), {}, {"checkpoints": ["only-one.safetensors"]})


def test_output_refs_preserve_workflow_node_labels():
    workflow = {
        "51": {
            "class_type": "PreviewImage",
            "inputs": {"images": ["8", 0]},
            "_meta": {"title": "比較 #1: SDXL/base-a.safetensors"},
        },
        "50": {
            "class_type": "PreviewImage",
            "inputs": {"images": ["18", 0]},
            "_meta": {"title": "比較 #2: SDXL/base-b.safetensors"},
        },
    }
    refs = collect_output_refs(
        {
            "outputs": {
                "51": {"images": [{"filename": "a.png", "subfolder": "", "type": "output"}]},
                "50": {"images": [{"filename": "a.png", "subfolder": "", "type": "output"}]},
            }
        },
        workflow=workflow,
    )

    assert len(refs["images"]) == 2
    assert refs["images"][0]["output_node_id"] == "51"
    assert refs["images"][0]["output_label"] == "比較 #1: SDXL/base-a.safetensors"
    assert refs["images"][1]["output_node_id"] == "50"
    assert refs["images"][1]["output_label"] == "比較 #2: SDXL/base-b.safetensors"
