from services.comfyui.workflow.summary import extract_workflow_summary


def test_workflow_summary_detects_unet_clip_and_embedding_dependencies():
    workflow = {
        "1": {"class_type": "UNETLoader", "inputs": {"unet_name": "anima-preview2.safetensors"}},
        "2": {"class_type": "CLIPLoader", "inputs": {"clip_name": "qwen_3_06b_base.safetensors"}},
        "3": {"class_type": "VAELoader", "inputs": {"vae_name": "qwen_image_vae.safetensors"}},
        "4": {
            "class_type": "CLIPTextEncode",
            "inputs": {"clip": ["2", 0], "text": "anime, <embeddings:badhandv4.pt>"},
        },
    }

    summary = extract_workflow_summary(workflow)
    required = {(item["kind"], item["name"]) for item in summary["required_models"]}

    assert ("diffusion_model", "anima-preview2.safetensors") in required
    assert ("clip", "qwen_3_06b_base.safetensors") in required
    assert ("vae", "qwen_image_vae.safetensors") in required
    assert ("embedding", "badhandv4.pt") in required
    assert summary["default_params"]["diffusion_model"] == "anima-preview2.safetensors"
    assert summary["default_params"]["clip"] == "qwen_3_06b_base.safetensors"
