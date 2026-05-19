from services.comfyui.validation.sanitize import sanitize_workflow_json
from services.comfyui.workflow.compat import apply_workflow_compatibility_fixes


ANIMA_LEGACY_WORKFLOW = {
    "62": {"class_type": "VAELoader", "inputs": {"vae_name": "qwen_image_vae.safetensors"}},
    "64": {"class_type": "EmptyLatentImage", "inputs": {"width": 1024, "height": 1024, "batch_size": 1}},
    "65": {"class_type": "CLIPTextEncode", "inputs": {"text": "bad", "clip": ["61", 0]}},
    "66": {
        "class_type": "KSampler",
        "inputs": {
            "seed": 1,
            "steps": 30,
            "cfg": 4,
            "sampler_name": "er_sde",
            "scheduler": "simple",
            "denoise": 1,
            "model": ["68", 0],
            "positive": ["67", 0],
            "negative": ["65", 0],
            "latent_image": ["64", 0],
        },
    },
    "67": {"class_type": "CLIPTextEncode", "inputs": {"text": "anime", "clip": ["61", 0]}},
    "68": {"class_type": "UNETLoader", "inputs": {"unet_name": "anima-preview2.safetensors"}},
    "69": {"class_type": "VAEDecode", "inputs": {"samples": ["66", 0], "vae": ["62", 0]}},
    "70": {"class_type": "SaveImage", "inputs": {"images": ["69", 0], "filename_prefix": "Anima"}},
}


def test_qwen_image_vae_workflow_adds_missing_model_sampling_aura_flow():
    patched = apply_workflow_compatibility_fixes(ANIMA_LEGACY_WORKFLOW)

    adapter_id = patched["66"]["inputs"]["model"][0]
    assert adapter_id != "68"
    assert patched[adapter_id]["class_type"] == "ModelSamplingAuraFlow"
    assert patched[adapter_id]["inputs"] == {"model": ["68", 0], "shift": 3.0}
    assert ANIMA_LEGACY_WORKFLOW["66"]["inputs"]["model"] == ["68", 0]


def test_qwen_image_vae_workflow_does_not_duplicate_existing_model_sampling():
    workflow = apply_workflow_compatibility_fixes(ANIMA_LEGACY_WORKFLOW)
    patched_again = apply_workflow_compatibility_fixes(workflow)

    adapters = [
        node_id
        for node_id, node in patched_again.items()
        if node.get("class_type") == "ModelSamplingAuraFlow"
    ]
    assert len(adapters) == 1


def test_sanitize_applies_qwen_image_vae_workflow_compatibility_fix():
    sanitized = sanitize_workflow_json(ANIMA_LEGACY_WORKFLOW)["workflow_json"]
    adapter_id = sanitized["66"]["inputs"]["model"][0]

    assert sanitized[adapter_id]["class_type"] == "ModelSamplingAuraFlow"


def test_string_concatenate_gets_empty_delimiter_for_newer_comfyui():
    workflow = {
        "1": {
            "class_type": "StringConcatenate",
            "inputs": {"string_a": "hello", "string_b": "world"},
        },
    }

    patched = apply_workflow_compatibility_fixes(workflow)

    assert patched["1"]["inputs"]["delimiter"] == ""
    assert "delimiter" not in workflow["1"]["inputs"]
