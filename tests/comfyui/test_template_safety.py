"""Safety helper regression for the ComfyUI template importer (§7)."""

import pytest

from services.comfyui.template.analyzer import analyze_workflow_json
from services.comfyui.template.safety import (
    SafetyError,
    enforce_allowlist,
    next_safe_node_id,
    rewrite_save_image_prefix,
)


# Reused from analyzer tests: minimal txt2img API workflow.
TXT2IMG = {
    "4": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": "v1-5.safetensors"}},
    "5": {"class_type": "EmptyLatentImage", "inputs": {"width": 512, "height": 512, "batch_size": 1}},
    "6": {"class_type": "CLIPTextEncode", "inputs": {"text": "cat", "clip": ["4", 1]}},
    "7": {"class_type": "CLIPTextEncode", "inputs": {"text": "low quality", "clip": ["4", 1]}},
    "3": {
        "class_type": "KSampler",
        "inputs": {
            "seed": 0, "steps": 20, "cfg": 7.5, "denoise": 1.0,
            "sampler_name": "euler", "scheduler": "normal",
            "model": ["4", 0], "positive": ["6", 0], "negative": ["7", 0], "latent_image": ["5", 0],
        },
    },
    "8": {"class_type": "VAEDecode", "inputs": {"samples": ["3", 0], "vae": ["4", 2]}},
    "9": {"class_type": "SaveImage", "inputs": {"filename_prefix": "ComfyUI", "images": ["8", 0]}},
}


def test_enforce_allowlist_passes_on_core_workflow():
    enforce_allowlist(analyze_workflow_json(TXT2IMG))  # must not raise


def test_enforce_allowlist_rejects_unknown_class():
    bad = {
        **TXT2IMG,
        "10": {"class_type": "FancyCommunityNode", "inputs": {}},
    }
    with pytest.raises(SafetyError, match="未授權的節點類型"):
        enforce_allowlist(analyze_workflow_json(bad))


def test_enforce_allowlist_rejects_explicit_denied_class():
    bad = {
        **TXT2IMG,
        "10": {"class_type": "ReActorFaceSwap", "inputs": {}},
    }
    with pytest.raises(SafetyError, match="未授權的節點類型"):
        enforce_allowlist(analyze_workflow_json(bad))


def test_enforce_allowlist_passes_with_controlnet_preprocessor():
    workflow = {
        **TXT2IMG,
        "20": {"class_type": "ControlNetLoader", "inputs": {"control_net_name": "canny.safetensors"}},
        "21": {"class_type": "CannyEdgePreprocessor", "inputs": {"image": ["8", 0]}},
        "22": {
            "class_type": "ControlNetApplyAdvanced",
            "inputs": {
                "strength": 1.0, "start_percent": 0.0, "end_percent": 0.7,
                "positive": ["6", 0], "negative": ["7", 0],
                "control_net": ["20", 0], "image": ["21", 0],
            },
        },
    }
    enforce_allowlist(analyze_workflow_json(workflow))


def test_next_safe_node_id_picks_above_max():
    assert next_safe_node_id({"1": {}, "9": {}, "100": {}}) == 101


def test_next_safe_node_id_handles_non_digit_keys():
    assert next_safe_node_id({"1": {}, "ignored": {}}) == 2


def test_next_safe_node_id_empty_returns_one():
    assert next_safe_node_id({}) == 1


def test_rewrite_save_image_prefix_replaces_user_supplied_value():
    out = rewrite_save_image_prefix(TXT2IMG, user_id=7, run_id="abc123")
    assert out["9"]["inputs"]["filename_prefix"] == "hackme/7/abc123"
    # Non-SaveImage nodes untouched
    assert out["6"]["inputs"]["text"] == TXT2IMG["6"]["inputs"]["text"]


def test_rewrite_save_image_prefix_does_not_mutate_input():
    original_prefix = TXT2IMG["9"]["inputs"]["filename_prefix"]
    rewrite_save_image_prefix(TXT2IMG, user_id=7, run_id="abc123")
    assert TXT2IMG["9"]["inputs"]["filename_prefix"] == original_prefix


def test_rewrite_save_image_prefix_handles_multiple_save_image_nodes():
    workflow = {
        **TXT2IMG,
        "10": {"class_type": "SaveImage", "inputs": {"filename_prefix": "second", "images": ["8", 0]}},
    }
    out = rewrite_save_image_prefix(workflow, user_id=42, run_id="run9")
    assert out["9"]["inputs"]["filename_prefix"] == "hackme/42/run9"
    assert out["10"]["inputs"]["filename_prefix"] == "hackme/42/run9"


def test_rewrite_save_image_prefix_rejects_empty_run_id():
    with pytest.raises(SafetyError, match="run_id"):
        rewrite_save_image_prefix(TXT2IMG, user_id=1, run_id="")


def test_rewrite_save_image_prefix_strips_unsafe_chars_from_run_id():
    out = rewrite_save_image_prefix(TXT2IMG, user_id=1, run_id="abc/../etc")
    assert out["9"]["inputs"]["filename_prefix"] == "hackme/1/abcetc"


def test_rewrite_save_image_prefix_rejects_non_dict():
    with pytest.raises(SafetyError):
        rewrite_save_image_prefix([], user_id=1, run_id="x")  # type: ignore[arg-type]
