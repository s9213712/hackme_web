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
    "txt2img": {"label": "文字生圖"},
    "img2img": {"label": "圖生圖"},
    "inpaint": {"label": "局部重繪"},
    "outpaint": {"label": "向外延展"},
    "upscale": {"label": "放大修復"},
}
