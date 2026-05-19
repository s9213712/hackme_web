from services.comfyui.workflow.summary import extract_workflow_summary


def test_workflow_summary_detects_unet_clip_and_embedding_dependencies():
    workflow = {
        "1": {"class_type": "UNETLoader", "inputs": {"unet_name": "anima-preview2.safetensors"}},
        "2": {"class_type": "CLIPLoader", "inputs": {"clip_name": "qwen_3_06b_base.safetensors"}},
        "3": {"class_type": "VAELoader", "inputs": {"vae_name": "qwen_image_vae.safetensors"}},
        "5": {"class_type": "CLIPVisionLoader", "inputs": {"clip_name": "sigclip_vision_patch14_384.safetensors"}},
        "6": {"class_type": "LatentUpscaleModelLoader", "inputs": {"model_name": "ltx-2.3-spatial-upscaler-x2-1.1.safetensors"}},
        "4": {
            "class_type": "CLIPTextEncode",
            "inputs": {"clip": ["2", 0], "text": "anime, <embeddings:badhandv4.pt>, embedding:lazy series\\IL\\lazyneg"},
        },
    }

    summary = extract_workflow_summary(workflow)
    required = {(item["kind"], item["name"]) for item in summary["required_models"]}

    assert ("diffusion_model", "anima-preview2.safetensors") in required
    assert ("clip", "qwen_3_06b_base.safetensors") in required
    assert ("clip_vision", "sigclip_vision_patch14_384.safetensors") in required
    assert ("latent_upscale", "ltx-2.3-spatial-upscaler-x2-1.1.safetensors") in required
    assert ("vae", "qwen_image_vae.safetensors") in required
    assert ("embedding", "badhandv4.pt") in required
    assert ("embedding", "lazy series\\IL\\lazyneg") in required
    assert summary["default_params"]["diffusion_model"] == "anima-preview2.safetensors"
    assert summary["default_params"]["clip"] == "qwen_3_06b_base.safetensors"
    assert summary["default_params"]["upscale_model"] == ""


def test_workflow_summary_embedding_parser_stops_before_prompt_words():
    workflow = {
        "4": {
            "class_type": "CLIPTextEncode",
            "inputs": {
                "clip": ["2", 0],
                "text": "embedding:lazyneg blurry, embedding:lazypos embedding:lazywet embedding:lazyloli",
            },
        },
    }

    summary = extract_workflow_summary(workflow)
    required = {(item["kind"], item["name"]) for item in summary["required_models"]}

    assert ("embedding", "lazyneg") in required
    assert ("embedding", "lazypos") in required
    assert ("embedding", "lazywet") in required
    assert ("embedding", "lazyloli") in required
    assert ("embedding", "lazyneg blurry") not in required
    assert ("embedding", "lazypos embedding:lazywet embedding:lazyloli") not in required
