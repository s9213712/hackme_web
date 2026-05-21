"""Workflow builder helpers for ComfyUI generation modes."""

from services.comfyui.template.safety import next_safe_node_id


def build_text_to_image_base(params):
    workflow = {
        "4": {
            "class_type": "CheckpointLoaderSimple",
            "inputs": {"ckpt_name": params["model"]},
        },
        "6": {
            "class_type": "CLIPTextEncode",
            "inputs": {"text": params["prompt"], "clip": ["4", 1]},
        },
        "7": {
            "class_type": "CLIPTextEncode",
            "inputs": {"text": params.get("negative_prompt") or "", "clip": ["4", 1]},
        },
    }
    final_model = ["4", 0]
    final_clip = ["4", 1]
    # Allocator (§7.4) returns max(used)+1 (which is 8 for the 4/6/7 base above).
    # Keep the historical floor of 10 so existing baseline / regression tests that
    # assert specific id placement (LoraLoader → "10", VAELoader → "11", etc.)
    # stay stable; the allocator still bumps above 10 if any caller pre-spliced
    # nodes at id ≥ 10 before invoking the builder helper.
    next_node_id = max(next_safe_node_id(workflow), 10)
    for item in params.get("loras") or []:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        node_id = str(next_node_id)
        next_node_id += 1
        workflow[node_id] = {
            "class_type": "LoraLoader",
            "inputs": {
                "model": final_model,
                "clip": final_clip,
                "lora_name": name,
                "strength_model": float(item.get("strength_model", 1.0)),
                "strength_clip": float(item.get("strength_clip", 1.0)),
            },
        }
        final_model = [node_id, 0]
        final_clip = [node_id, 1]
    vae_ref = ["4", 2]
    vae_name = str(params.get("vae") or "").strip()
    if vae_name:
        vae_node_id = str(next_node_id)
        next_node_id += 1
        workflow[vae_node_id] = {
            "class_type": "VAELoader",
            "inputs": {"vae_name": vae_name},
        }
        vae_ref = [vae_node_id, 0]
    workflow["6"]["inputs"]["clip"] = final_clip
    workflow["7"]["inputs"]["clip"] = final_clip
    return workflow, final_model, final_clip, vae_ref, next_node_id


def attach_controlnet(workflow, params, *, positive_ref, negative_ref, next_node_id, error_cls):
    control = params.get("controlnet") if isinstance(params.get("controlnet"), dict) else None
    if not control:
        return positive_ref, negative_ref, next_node_id
    control_image = control.get("image_ref") if isinstance(control.get("image_ref"), dict) else None
    if not control_image or not control_image.get("filename"):
        raise error_cls("ControlNet 缺少控制圖")
    loader_id = str(next_node_id)
    next_node_id += 1
    workflow[loader_id] = {
        "class_type": "LoadImage",
        "inputs": {"image": control_image["filename"], "upload": "image"},
    }
    image_ref = [loader_id, 0]
    preprocessor = str(control.get("preprocessor") or "").strip()
    if preprocessor:
        preprocessor_id = str(next_node_id)
        next_node_id += 1
        workflow[preprocessor_id] = {
            "class_type": preprocessor,
            "inputs": {"image": image_ref},
        }
        image_ref = [preprocessor_id, 0]
    model_id = str(next_node_id)
    next_node_id += 1
    workflow[model_id] = {
        "class_type": "ControlNetLoader",
        "inputs": {"control_net_name": control["model_name"]},
    }
    apply_id = str(next_node_id)
    next_node_id += 1
    workflow[apply_id] = {
        "class_type": "ControlNetApplyAdvanced",
        "inputs": {
            "positive": positive_ref,
            "negative": negative_ref,
            "control_net": [model_id, 0],
            "image": image_ref,
            "strength": float(control.get("strength") or 1.0),
            "start_percent": float(control.get("start_percent") or 0.0),
            "end_percent": float(control.get("end_percent") or 1.0),
        },
    }
    return [apply_id, 0], [apply_id, 1], next_node_id


def build_text_to_image_workflow(params, *, error_cls):
    workflow, final_model, _final_clip, vae_ref, next_node_id = build_text_to_image_base(params)
    workflow["5"] = {
        "class_type": "EmptyLatentImage",
        "inputs": {
            "width": int(params["width"]),
            "height": int(params["height"]),
            "batch_size": int(params.get("batch_size") or 1),
        },
    }
    positive_ref = ["6", 0]
    negative_ref = ["7", 0]
    positive_ref, negative_ref, next_node_id = attach_controlnet(
        workflow,
        params,
        positive_ref=positive_ref,
        negative_ref=negative_ref,
        next_node_id=next_node_id,
        error_cls=error_cls,
    )
    workflow["3"] = {
        "class_type": "KSampler",
        "inputs": {
            "seed": int(params["seed"]),
            "steps": int(params["steps"]),
            "cfg": float(params["cfg"]),
            "sampler_name": params["sampler_name"],
            "scheduler": params["scheduler"],
            "denoise": 1,
            "model": final_model,
            "positive": positive_ref,
            "negative": negative_ref,
            "latent_image": ["5", 0],
        },
    }
    workflow["8"] = {
        "class_type": "VAEDecode",
        "inputs": {"samples": ["3", 0], "vae": vae_ref},
    }
    workflow["9"] = {
        "class_type": "SaveImage",
        "inputs": {
            "filename_prefix": params.get("filename_prefix") or "hackme_web",
            "images": ["8", 0],
        },
    }
    return workflow


def build_gguf_text_to_image_base(params, *, error_cls):
    unet_name = str(params.get("comfyui_gguf_unet_name") or params.get("diffusion_model") or params.get("model") or "").strip()
    clip_name1 = str(params.get("clip") or params.get("clip_name1") or "").strip()
    clip_name2 = str(params.get("clip2") or params.get("clip_name2") or "").strip()
    vae_name = str(params.get("vae") or "").strip()
    if not unet_name:
        raise error_cls("ComfyUI-GGUF workflow 缺少 UNet GGUF 模型")
    if not clip_name1 or not clip_name2:
        raise error_cls("ComfyUI-GGUF workflow 缺少 SDXL CLIP-L / CLIP-G 文字編碼器")
    if not vae_name:
        raise error_cls("ComfyUI-GGUF workflow 缺少 VAE；請選擇 SDXL VAE")

    workflow = {
        "4": {
            "class_type": "UnetLoaderGGUF",
            "inputs": {"unet_name": unet_name},
        },
        "10": {
            "class_type": "DualCLIPLoader",
            "inputs": {
                "clip_name1": clip_name1,
                "clip_name2": clip_name2,
                "type": str(params.get("clip_type") or "sdxl").strip() or "sdxl",
                "device": str(params.get("clip_device") or "default").strip() or "default",
            },
        },
        "11": {
            "class_type": "VAELoader",
            "inputs": {"vae_name": vae_name},
        },
        "6": {
            "class_type": "CLIPTextEncode",
            "inputs": {"text": params["prompt"], "clip": ["10", 0]},
        },
        "7": {
            "class_type": "CLIPTextEncode",
            "inputs": {"text": params.get("negative_prompt") or "", "clip": ["10", 0]},
        },
    }
    final_model = ["4", 0]
    final_clip = ["10", 0]
    next_node_id = 12
    for item in params.get("loras") or []:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        node_id = str(next_node_id)
        next_node_id += 1
        workflow[node_id] = {
            "class_type": "LoraLoader",
            "inputs": {
                "model": final_model,
                "clip": final_clip,
                "lora_name": name,
                "strength_model": float(item.get("strength_model", 1.0)),
                "strength_clip": float(item.get("strength_clip", 1.0)),
            },
        }
        final_model = [node_id, 0]
        final_clip = [node_id, 1]
    workflow["6"]["inputs"]["clip"] = final_clip
    workflow["7"]["inputs"]["clip"] = final_clip
    return workflow, final_model, final_clip, ["11", 0], next_node_id


def build_gguf_text_to_image_workflow(params, *, error_cls):
    workflow, final_model, _final_clip, vae_ref, next_node_id = build_gguf_text_to_image_base(params, error_cls=error_cls)
    workflow["5"] = {
        "class_type": "EmptyLatentImage",
        "inputs": {
            "width": int(params["width"]),
            "height": int(params["height"]),
            "batch_size": int(params.get("batch_size") or 1),
        },
    }
    workflow["3"] = {
        "class_type": "KSampler",
        "inputs": {
            "seed": int(params["seed"]),
            "steps": int(params["steps"]),
            "cfg": float(params["cfg"]),
            "sampler_name": params["sampler_name"],
            "scheduler": params["scheduler"],
            "denoise": 1,
            "model": final_model,
            "positive": ["6", 0],
            "negative": ["7", 0],
            "latent_image": ["5", 0],
        },
    }
    workflow["8"] = {
        "class_type": "VAEDecode",
        "inputs": {"samples": ["3", 0], "vae": vae_ref},
    }
    workflow["9"] = {
        "class_type": "SaveImage",
        "inputs": {
            "filename_prefix": params.get("filename_prefix") or "hackme_web",
            "images": ["8", 0],
        },
    }
    return workflow


def build_image_to_image_workflow(params, *, error_cls):
    workflow, final_model, _final_clip, vae_ref, next_node_id = build_text_to_image_base(params)
    source_image = params.get("source_image_ref") if isinstance(params.get("source_image_ref"), dict) else None
    if not source_image:
        raise error_cls("圖生圖缺少來源圖片")
    workflow["5"] = {
        "class_type": "LoadImage",
        "inputs": {"image": source_image["filename"], "upload": "image"},
    }
    workflow["10"] = {
        "class_type": "VAEEncode",
        "inputs": {"pixels": ["5", 0], "vae": vae_ref},
    }
    positive_ref = ["6", 0]
    negative_ref = ["7", 0]
    positive_ref, negative_ref, next_node_id = attach_controlnet(
        workflow,
        params,
        positive_ref=positive_ref,
        negative_ref=negative_ref,
        next_node_id=next_node_id,
        error_cls=error_cls,
    )
    workflow["3"] = {
        "class_type": "KSampler",
        "inputs": {
            "seed": int(params["seed"]),
            "steps": int(params["steps"]),
            "cfg": float(params["cfg"]),
            "sampler_name": params["sampler_name"],
            "scheduler": params["scheduler"],
            "denoise": float(params.get("denoise_strength") or 0.65),
            "model": final_model,
            "positive": positive_ref,
            "negative": negative_ref,
            "latent_image": ["10", 0],
        },
    }
    workflow["8"] = {
        "class_type": "VAEDecode",
        "inputs": {"samples": ["3", 0], "vae": vae_ref},
    }
    workflow["9"] = {
        "class_type": "SaveImage",
        "inputs": {
            "filename_prefix": params.get("filename_prefix") or "hackme_web",
            "images": ["8", 0],
        },
    }
    return workflow


def build_inpaint_workflow(params, *, error_cls):
    workflow, final_model, _final_clip, vae_ref, next_node_id = build_text_to_image_base(params)
    source_image = params.get("source_image_ref") if isinstance(params.get("source_image_ref"), dict) else None
    mask_image = params.get("mask_image_ref") if isinstance(params.get("mask_image_ref"), dict) else None
    if not source_image or not mask_image:
        raise error_cls("局部重繪缺少來源圖片或遮罩")
    workflow["5"] = {
        "class_type": "LoadImage",
        "inputs": {"image": source_image["filename"], "upload": "image"},
    }
    workflow["11"] = {
        "class_type": "LoadImageMask",
        "inputs": {"image": mask_image["filename"], "channel": "alpha"},
    }
    workflow["10"] = {
        "class_type": "VAEEncodeForInpaint",
        "inputs": {"pixels": ["5", 0], "mask": ["11", 0], "vae": vae_ref, "grow_mask_by": 6},
    }
    positive_ref = ["6", 0]
    negative_ref = ["7", 0]
    positive_ref, negative_ref, next_node_id = attach_controlnet(
        workflow,
        params,
        positive_ref=positive_ref,
        negative_ref=negative_ref,
        next_node_id=next_node_id,
        error_cls=error_cls,
    )
    workflow["3"] = {
        "class_type": "KSampler",
        "inputs": {
            "seed": int(params["seed"]),
            "steps": int(params["steps"]),
            "cfg": float(params["cfg"]),
            "sampler_name": params["sampler_name"],
            "scheduler": params["scheduler"],
            "denoise": float(params.get("denoise_strength") or 0.8),
            "model": final_model,
            "positive": positive_ref,
            "negative": negative_ref,
            "latent_image": ["10", 0],
        },
    }
    workflow["8"] = {
        "class_type": "VAEDecode",
        "inputs": {"samples": ["3", 0], "vae": vae_ref},
    }
    workflow["9"] = {
        "class_type": "SaveImage",
        "inputs": {
            "filename_prefix": params.get("filename_prefix") or "hackme_web",
            "images": ["8", 0],
        },
    }
    return workflow


def build_outpaint_workflow(params, *, error_cls):
    workflow, final_model, _final_clip, vae_ref, next_node_id = build_text_to_image_base(params)
    source_image = params.get("source_image_ref") if isinstance(params.get("source_image_ref"), dict) else None
    if not source_image:
        raise error_cls("向外延展缺少來源圖片")
    expand = params.get("outpaint") if isinstance(params.get("outpaint"), dict) else {}
    workflow["5"] = {
        "class_type": "LoadImage",
        "inputs": {"image": source_image["filename"], "upload": "image"},
    }
    workflow["10"] = {
        "class_type": "ImagePadForOutpaint",
        "inputs": {
            "image": ["5", 0],
            "left": int(expand.get("left") or 0),
            "top": int(expand.get("top") or 0),
            "right": int(expand.get("right") or 0),
            "bottom": int(expand.get("bottom") or 0),
            "feathering": int(expand.get("feathering") or 24),
        },
    }
    workflow["11"] = {
        "class_type": "VAEEncodeForInpaint",
        "inputs": {"pixels": ["10", 0], "mask": ["10", 1], "vae": vae_ref, "grow_mask_by": 6},
    }
    positive_ref = ["6", 0]
    negative_ref = ["7", 0]
    positive_ref, negative_ref, next_node_id = attach_controlnet(
        workflow,
        params,
        positive_ref=positive_ref,
        negative_ref=negative_ref,
        next_node_id=next_node_id,
        error_cls=error_cls,
    )
    workflow["3"] = {
        "class_type": "KSampler",
        "inputs": {
            "seed": int(params["seed"]),
            "steps": int(params["steps"]),
            "cfg": float(params["cfg"]),
            "sampler_name": params["sampler_name"],
            "scheduler": params["scheduler"],
            "denoise": float(params.get("denoise_strength") or 0.9),
            "model": final_model,
            "positive": positive_ref,
            "negative": negative_ref,
            "latent_image": ["11", 0],
        },
    }
    workflow["8"] = {
        "class_type": "VAEDecode",
        "inputs": {"samples": ["3", 0], "vae": vae_ref},
    }
    workflow["9"] = {
        "class_type": "SaveImage",
        "inputs": {
            "filename_prefix": params.get("filename_prefix") or "hackme_web",
            "images": ["8", 0],
        },
    }
    return workflow


def build_upscale_workflow(params, *, error_cls):
    source_image = params.get("source_image_ref") if isinstance(params.get("source_image_ref"), dict) else None
    upscale_model = str(params.get("upscale_model") or "").strip()
    if not source_image:
        raise error_cls("放大修復缺少來源圖片")
    if not upscale_model:
        raise error_cls("請選擇放大模型")
    return {
        "3": {
            "class_type": "UpscaleModelLoader",
            "inputs": {"model_name": upscale_model},
        },
        "4": {
            "class_type": "LoadImage",
            "inputs": {"image": source_image["filename"], "upload": "image"},
        },
        "5": {
            "class_type": "ImageUpscaleWithModel",
            "inputs": {"upscale_model": ["3", 0], "image": ["4", 0]},
        },
        "9": {
            "class_type": "SaveImage",
            "inputs": {
                "filename_prefix": params.get("filename_prefix") or "hackme_web",
                "images": ["5", 0],
            },
        },
    }


def build_generation_workflow(params, *, error_cls):
    mode = str(params.get("generation_mode") or "txt2img").strip().lower()
    if params.get("comfyui_gguf_unet_name"):
        if mode != "txt2img":
            raise error_cls("ComfyUI-GGUF 快捷 workflow 目前只支援文字生圖；其他模式請使用 workflow 模板。")
        return build_gguf_text_to_image_workflow(params, error_cls=error_cls)
    if mode == "txt2img":
        return build_text_to_image_workflow(params, error_cls=error_cls)
    if mode == "img2img":
        return build_image_to_image_workflow(params, error_cls=error_cls)
    if mode == "inpaint":
        return build_inpaint_workflow(params, error_cls=error_cls)
    if mode == "outpaint":
        return build_outpaint_workflow(params, error_cls=error_cls)
    if mode == "upscale":
        return build_upscale_workflow(params, error_cls=error_cls)
    if mode in {"t2v", "i2v", "v2v", "t2s", "t2sv"}:
        raise error_cls("這個 ComfyUI 模式需要透過支援的大模型 workflow 模板執行，請先匯入或選擇對應 workflow。")
    raise error_cls("ComfyUI 產圖模式不支援")
