"""ComfyUI constants shared across client, workflow, and validation layers."""


CONTROLNET_TYPE_DEFINITIONS = {
    "canny": {
        "label": "Canny",
        "default_preprocessor": "CannyEdgePreprocessor",
        "preprocessor_candidates": ["CannyEdgePreprocessor"],
        "model_keywords": ["canny"],
    },
    "depth": {
        "label": "Depth",
        "default_preprocessor": "DepthAnythingPreprocessor",
        "preprocessor_candidates": ["DepthAnythingPreprocessor", "MiDaS-DepthMapPreprocessor"],
        "model_keywords": ["depth"],
    },
    "openpose": {
        "label": "OpenPose",
        "default_preprocessor": "OpenposePreprocessor",
        "preprocessor_candidates": ["OpenposePreprocessor", "DWPreprocessor"],
        "model_keywords": ["openpose", "pose"],
    },
    "lineart": {
        "label": "Lineart",
        "default_preprocessor": "LineArtPreprocessor",
        "preprocessor_candidates": ["LineArtPreprocessor", "LineartStandardPreprocessor"],
        "model_keywords": ["lineart", "line-art"],
    },
    "scribble": {
        "label": "Scribble",
        "default_preprocessor": "PiDiNetPreprocessor",
        "preprocessor_candidates": ["PiDiNetPreprocessor", "ScribblePreprocessor"],
        "model_keywords": ["scribble"],
    },
    "softedge": {
        "label": "SoftEdge",
        "default_preprocessor": "SoftEdgePreprocessor",
        "preprocessor_candidates": ["SoftEdgePreprocessor", "HEDPreprocessor", "PiDiNetPreprocessor"],
        "model_keywords": ["softedge", "soft-edge", "hed"],
    },
    "tile": {
        "label": "Tile",
        "default_preprocessor": "TilePreprocessor",
        "preprocessor_candidates": ["TilePreprocessor"],
        "model_keywords": ["tile"],
    },
}

GENERATION_MODE_DEFINITIONS = {
    "txt2img": {"label": "文字生圖", "output_kind": "image"},
    "img2img": {"label": "圖生圖", "output_kind": "image", "source_kind": "image"},
    "inpaint": {"label": "局部重繪", "output_kind": "image", "source_kind": "image", "mask_kind": "image"},
    "outpaint": {"label": "向外延展", "output_kind": "image", "source_kind": "image"},
    "upscale": {"label": "放大修復", "output_kind": "image", "source_kind": "image"},
    "t2v": {
        "label": "文字生影片",
        "output_kind": "video",
        "workflow_only": True,
        "recommended_model_families": ["wan", "flux"],
    },
    "i2v": {
        "label": "圖生影片",
        "output_kind": "video",
        "source_kind": "image",
        "workflow_only": True,
        "recommended_model_families": ["wan"],
    },
    "v2v": {
        "label": "影片生影片",
        "output_kind": "video",
        "source_kind": "video",
        "workflow_only": True,
        "recommended_model_families": ["wan"],
    },
    "t2s": {
        "label": "文字轉語音",
        "output_kind": "audio",
        "workflow_only": True,
        "recommended_model_families": ["tts"],
    },
    "t2sv": {
        "label": "文字生成語音影片",
        "output_kind": "video",
        "source_kind": "audio",
        "workflow_only": True,
        "recommended_model_families": ["wan", "tts"],
    },
}

MODEL_FAMILY_DEFINITIONS = {
    "sdxl": {
        "label": "SDXL",
        "aliases": ["sdxl", "sd xl", "stable diffusion xl"],
        "model_dirs": ["checkpoints", "loras", "vae"],
        "modes": ["txt2img", "img2img", "inpaint"],
    },
    "illustrious": {
        "label": "Illustrious / WAI",
        "aliases": ["illustrious", "waiillustrious", "wai_illustrious", "wai illustrious"],
        "model_dirs": ["checkpoints", "loras", "vae"],
        "modes": ["txt2img", "img2img", "inpaint"],
    },
    "pony": {
        "label": "Pony",
        "aliases": ["pony", "ponyxl", "pony xl"],
        "model_dirs": ["checkpoints", "loras", "vae"],
        "modes": ["txt2img", "img2img", "inpaint"],
    },
    "noob": {
        "label": "NoobAI / Noob",
        "aliases": ["noob", "noobai", "noob ai"],
        "model_dirs": ["checkpoints", "loras", "vae"],
        "modes": ["txt2img", "img2img", "inpaint"],
    },
    "flux": {
        "label": "FLUX / Kontext",
        "aliases": ["flux", "flux1", "flux.1", "schnell", "kontext"],
        "model_dirs": ["diffusion_models", "text_encoders", "vae", "loras", "controlnet"],
        "modes": ["txt2img", "img2img", "inpaint"],
    },
    "sd35": {
        "label": "Stable Diffusion 3.5",
        "aliases": ["sd3.5", "sd3_5", "sd35", "stable diffusion 3.5", "stable_diffusion_3.5"],
        "model_dirs": ["checkpoints", "clip", "text_encoders", "vae"],
        "modes": ["txt2img", "img2img"],
    },
    "wan": {
        "label": "Wan / Wan2.x Video",
        "aliases": ["wan", "wan2", "wan2.1", "wan_2", "wan-2"],
        "model_dirs": ["diffusion_models", "text_encoders", "clip_vision", "vae"],
        "modes": ["t2v", "i2v", "v2v", "t2sv"],
    },
    "anima": {
        "label": "Anima",
        "aliases": ["anima", "circlestone", "qwen_image", "qwen_3", "qwen3"],
        "model_dirs": ["diffusion_models", "text_encoders", "vae"],
        "modes": ["txt2img"],
    },
    "netayume": {
        "label": "NetaYume / NTYM / Lumina",
        "aliases": ["netayume", "neta yume", "ntym", "neta_lumina", "neta lumina", "lumina"],
        "model_dirs": ["diffusion_models", "text_encoders", "vae"],
        "modes": ["txt2img"],
    },
    "animagine": {
        "label": "Animagine XL",
        "aliases": ["animagine", "anim4gine"],
        "model_dirs": ["checkpoints", "loras", "vae"],
        "modes": ["txt2img", "img2img", "inpaint"],
    },
    "tts": {
        "label": "TTS / Voice",
        "aliases": ["tts", "index-tts", "indextts", "f5-tts", "f5tts", "chatterbox", "cosyvoice"],
        "model_dirs": ["audio", "text_encoders"],
        "modes": ["t2s", "t2sv"],
    },
}


def detect_model_families(model_names):
    detected = []
    for key, definition in MODEL_FAMILY_DEFINITIONS.items():
        aliases = [str(alias or "").lower() for alias in definition.get("aliases") or []]
        matches = sorted(
            {
                original
                for original in (model_names or [])
                if any(alias and alias in str(original or "").lower() for alias in aliases)
            }
        )
        detected.append(
            {
                "key": key,
                "label": definition.get("label") or key,
                "aliases": aliases,
                "model_dirs": list(definition.get("model_dirs") or []),
                "modes": list(definition.get("modes") or []),
                "installed": bool(matches),
                "matching_models": matches[:12],
            }
        )
    return detected
