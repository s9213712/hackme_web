"""§12 minimal API-format ComfyUI workflows for template-importer tests.

Each helper returns a fresh deep copy so tests can mutate without leaking
state between cases. Workflows are kept *minimal* — they pass §3
sanitization and §4 allowlist but don't try to be production-quality
generation pipelines.
"""

from __future__ import annotations

import copy
from typing import Any


def _deep_copy(value: dict[str, Any]) -> dict[str, Any]:
    return copy.deepcopy(value)


# ----------------------------------------------------------------------------
# txt2img — the canonical 7-node baseline.
# ----------------------------------------------------------------------------

_TXT2IMG = {
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
    "8": {"class_type": "VAEDecode", "inputs": {"samples": ["3", 0], "vae": ["4", 2]}},
    "9": {
        "class_type": "SaveImage",
        "inputs": {"filename_prefix": "ComfyUI", "images": ["8", 0]},
    },
}


def txt2img_basic() -> dict[str, Any]:
    """7-node txt2img baseline."""
    return _deep_copy(_TXT2IMG)


# ----------------------------------------------------------------------------
# img2img — adds LoadImage + VAEEncode upstream of KSampler.
# ----------------------------------------------------------------------------

_IMG2IMG = {
    "4": {
        "class_type": "CheckpointLoaderSimple",
        "inputs": {"ckpt_name": "v1-5-pruned.safetensors"},
    },
    "10": {
        "class_type": "LoadImage",
        "inputs": {"image": "ref.png"},
    },
    "11": {
        "class_type": "VAEEncode",
        "inputs": {"pixels": ["10", 0], "vae": ["4", 2]},
    },
    "6": {
        "class_type": "CLIPTextEncode",
        "inputs": {"text": "a watercolor painting of a cat", "clip": ["4", 1]},
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
            "denoise": 0.65,
            "sampler_name": "euler",
            "scheduler": "normal",
            "model": ["4", 0],
            "positive": ["6", 0],
            "negative": ["7", 0],
            "latent_image": ["11", 0],
        },
    },
    "8": {"class_type": "VAEDecode", "inputs": {"samples": ["3", 0], "vae": ["4", 2]}},
    "9": {
        "class_type": "SaveImage",
        "inputs": {"filename_prefix": "ComfyUI", "images": ["8", 0]},
    },
}


def img2img_basic() -> dict[str, Any]:
    """txt2img + LoadImage + VAEEncode + denoise=0.65."""
    return _deep_copy(_IMG2IMG)


# ----------------------------------------------------------------------------
# inpaint — adds LoadImage(mask) + VAEEncodeForInpaint.
# ----------------------------------------------------------------------------

_INPAINT = {
    "4": {
        "class_type": "CheckpointLoaderSimple",
        "inputs": {"ckpt_name": "v1-5-inpainting.safetensors"},
    },
    "10": {
        "class_type": "LoadImage",
        "inputs": {"image": "subject.png"},
    },
    "11": {
        "class_type": "LoadImageMask",
        "inputs": {"image": "subject_mask.png", "channel": "alpha"},
    },
    "12": {
        "class_type": "VAEEncodeForInpaint",
        "inputs": {
            "pixels": ["10", 0],
            "vae": ["4", 2],
            "mask": ["11", 0],
            "grow_mask_by": 6,
        },
    },
    "6": {
        "class_type": "CLIPTextEncode",
        "inputs": {"text": "a sunny park", "clip": ["4", 1]},
    },
    "7": {
        "class_type": "CLIPTextEncode",
        "inputs": {"text": "low quality, blurry", "clip": ["4", 1]},
    },
    "3": {
        "class_type": "KSampler",
        "inputs": {
            "seed": 42,
            "steps": 24,
            "cfg": 7.0,
            "denoise": 1.0,
            "sampler_name": "euler",
            "scheduler": "normal",
            "model": ["4", 0],
            "positive": ["6", 0],
            "negative": ["7", 0],
            "latent_image": ["12", 0],
        },
    },
    "8": {"class_type": "VAEDecode", "inputs": {"samples": ["3", 0], "vae": ["4", 2]}},
    "9": {
        "class_type": "SaveImage",
        "inputs": {"filename_prefix": "ComfyUI", "images": ["8", 0]},
    },
}


def inpaint_basic() -> dict[str, Any]:
    """LoadImage + LoadImageMask + VAEEncodeForInpaint pipeline."""
    return _deep_copy(_INPAINT)


# ----------------------------------------------------------------------------
# controlnet — txt2img + ControlNetLoader + Canny preprocessor + Apply.
# ----------------------------------------------------------------------------

_CONTROLNET = {
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
        "inputs": {"text": "a sleeping cat", "clip": ["4", 1]},
    },
    "7": {
        "class_type": "CLIPTextEncode",
        "inputs": {"text": "low quality", "clip": ["4", 1]},
    },
    "20": {
        "class_type": "LoadImage",
        "inputs": {"image": "edge_source.png"},
    },
    "21": {
        "class_type": "CannyEdgePreprocessor",
        "inputs": {"image": ["20", 0]},
    },
    "22": {
        "class_type": "ControlNetLoader",
        "inputs": {"control_net_name": "control_canny.safetensors"},
    },
    "23": {
        "class_type": "ControlNetApplyAdvanced",
        "inputs": {
            "strength": 1.0,
            "start_percent": 0.0,
            "end_percent": 1.0,
            "positive": ["6", 0],
            "negative": ["7", 0],
            "control_net": ["22", 0],
            "image": ["21", 0],
        },
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
            "positive": ["23", 0],
            "negative": ["23", 1],
            "latent_image": ["5", 0],
        },
    },
    "8": {"class_type": "VAEDecode", "inputs": {"samples": ["3", 0], "vae": ["4", 2]}},
    "9": {
        "class_type": "SaveImage",
        "inputs": {"filename_prefix": "ComfyUI", "images": ["8", 0]},
    },
}


def controlnet_canny() -> dict[str, Any]:
    """txt2img + Canny preprocessor + ControlNetApplyAdvanced."""
    return _deep_copy(_CONTROLNET)


__all__ = [
    "controlnet_canny",
    "img2img_basic",
    "inpaint_basic",
    "txt2img_basic",
]
