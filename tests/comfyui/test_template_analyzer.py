"""Analyzer regression for the ComfyUI template importer (§5)."""

import pytest

from services.comfyui.template.analyzer import (
    FieldCategory,
    analyze_workflow_json,
    classify_input_field,
)
from services.comfyui.validation.rules import WorkflowValidationError


# Minimal txt2img workflow in API format. Each node is just enough to flow through
# the analyzer without sanitize complaining (sanitize is exercised separately).
TXT2IMG_API = {
    "4": {
        "class_type": "CheckpointLoaderSimple",
        "inputs": {"ckpt_name": "v1-5-pruned.safetensors"},
    },
    "5": {
        "class_type": "EmptyLatentImage",
        "inputs": {"width": 512, "height": 512, "batch_size": 1},
    },
    "6": {
        "class_type": "CLIPTextEncode",
        "inputs": {"text": "a cat sitting in a window", "clip": ["4", 1]},
    },
    "7": {
        "class_type": "CLIPTextEncode",
        "inputs": {"text": "low quality", "clip": ["4", 1]},
    },
    "3": {
        "class_type": "KSampler",
        "inputs": {
            "seed": 42,
            "steps": 20,
            "cfg": 7.5,
            "denoise": 1.0,
            "sampler_name": "euler",
            "scheduler": "normal",
            "model": ["4", 0],
            "positive": ["6", 0],
            "negative": ["7", 0],
            "latent_image": ["5", 0],
        },
    },
    "8": {
        "class_type": "VAEDecode",
        "inputs": {"samples": ["3", 0], "vae": ["4", 2]},
    },
    "9": {
        "class_type": "SaveImage",
        "inputs": {"filename_prefix": "ComfyUI", "images": ["8", 0]},
    },
}


def test_classify_input_field_known_buckets():
    assert classify_input_field("CLIPTextEncode", "text") == FieldCategory.TEXT
    assert classify_input_field("LoadImage", "image") == FieldCategory.IMAGE
    assert classify_input_field("CheckpointLoaderSimple", "ckpt_name") == FieldCategory.MODEL
    assert classify_input_field("KSampler", "seed") == FieldCategory.NUMERIC
    assert classify_input_field("KSampler", "sampler_name") == FieldCategory.SAMPLER
    assert classify_input_field("Unmapped", "whatever") == FieldCategory.UNKNOWN


def test_analyze_collects_class_types_and_buckets():
    analysis = analyze_workflow_json(TXT2IMG_API)
    assert analysis.class_types == {
        "CheckpointLoaderSimple",
        "EmptyLatentImage",
        "CLIPTextEncode",
        "KSampler",
        "VAEDecode",
        "SaveImage",
    }
    assert analysis.allowed_classes == analysis.class_types
    assert analysis.unknown_classes == set()
    assert analysis.denied_classes == set()


def test_analyze_required_models_collected():
    analysis = analyze_workflow_json(TXT2IMG_API)
    assert analysis.required_models == {"ckpt": ["v1-5-pruned.safetensors"]}


def test_analyze_required_embeddings_from_prompt_tokens():
    workflow = {
        **TXT2IMG_API,
        "6": {
            "class_type": "CLIPTextEncode",
            "inputs": {"text": "portrait, <embeddings:badhandv4.pt>, embedding:easynegative.safetensors", "clip": ["4", 1]},
        },
    }
    analysis = analyze_workflow_json(workflow)
    assert analysis.required_models["embedding"] == ["badhandv4.pt", "easynegative.safetensors"]


def test_analyze_user_inputs_separates_links_from_scalars():
    analysis = analyze_workflow_json(TXT2IMG_API)
    user_input_keys = {(f.node_id, f.input_name) for f in analysis.user_inputs}
    # KSampler.model is a [4, 0] link → must NOT appear in user inputs
    assert ("3", "model") not in user_input_keys
    # KSampler.seed is a scalar → must appear
    assert ("3", "seed") in user_input_keys
    # Every user input must carry a category (UNKNOWN allowed for unmapped fields)
    assert all(isinstance(f.category, FieldCategory) for f in analysis.user_inputs)


def test_analyze_unknown_class_does_not_raise():
    """Per §4: analyze never blocks on unknown class; lets capability check decide."""
    workflow = {
        **TXT2IMG_API,
        "10": {
            "class_type": "FancyCommunityNode",
            "inputs": {"some_value": 1},
        },
    }
    analysis = analyze_workflow_json(workflow)
    assert "FancyCommunityNode" in analysis.unknown_classes
    assert "FancyCommunityNode" not in analysis.allowed_classes
    assert analysis.has_blocking_classes() is False  # unknown ≠ denied


def test_analyze_explicit_denylist_is_blocking():
    """Per §4: explicit denylist class causes has_blocking_classes()=True."""
    workflow = {
        **TXT2IMG_API,
        "10": {
            "class_type": "ReActorFaceSwap",
            "inputs": {"image": ["8", 0]},
        },
    }
    analysis = analyze_workflow_json(workflow)
    assert "ReActorFaceSwap" in analysis.denied_classes
    assert analysis.has_blocking_classes() is True


def test_analyze_rejects_non_dict_workflow():
    with pytest.raises(WorkflowValidationError):
        analyze_workflow_json([])  # type: ignore[arg-type]


def test_analyze_accepts_non_digit_string_node_id():
    analysis = analyze_workflow_json({"node_a": {"class_type": "X", "inputs": {}}})
    assert analysis.nodes[0].node_id == "node_a"


def test_analyze_rejects_blank_node_id():
    with pytest.raises(WorkflowValidationError, match="非空字串"):
        analyze_workflow_json({"": {"class_type": "X", "inputs": {}}})


def test_analyze_rejects_missing_class_type():
    with pytest.raises(WorkflowValidationError, match="class_type"):
        analyze_workflow_json({"1": {"inputs": {}}})


def test_analyze_rejects_inputs_not_dict():
    with pytest.raises(WorkflowValidationError, match="inputs"):
        analyze_workflow_json({"1": {"class_type": "KSampler", "inputs": []}})


def test_analyze_lora_strengths_and_other_numerics_classified():
    workflow = {
        "1": {
            "class_type": "LoraLoader",
            "inputs": {
                "lora_name": "lcm.safetensors",
                "strength_model": 1.0,
                "strength_clip": 0.8,
                "model": ["2", 0],
                "clip": ["2", 1],
            },
        },
        "2": {
            "class_type": "CheckpointLoaderSimple",
            "inputs": {"ckpt_name": "base.safetensors"},
        },
    }
    analysis = analyze_workflow_json(workflow)
    by_field = {(f.node_id, f.input_name): f for f in analysis.user_inputs}
    assert by_field[("1", "strength_model")].category == FieldCategory.NUMERIC
    assert by_field[("1", "strength_clip")].category == FieldCategory.NUMERIC
    # required_models picks up both ckpt_name and lora_name
    assert analysis.required_models["lora"] == ["lcm.safetensors"]
    assert analysis.required_models["ckpt"] == ["base.safetensors"]
