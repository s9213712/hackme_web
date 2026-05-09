"""Allowlist / denylist regression for the ComfyUI template importer (§4)."""

import pytest

from services.comfyui.template.allowlist import (
    CONTROLNET_PREPROCESSOR_ALLOWLIST,
    CORE_ALLOWLIST,
    EXPLICIT_DENYLIST,
    is_allowed_class,
    is_explicitly_denied_class,
)


def test_core_allowlist_size_matches_spec():
    """Keep the curated core allowlist explicit as importer support grows."""
    assert len(CORE_ALLOWLIST) == 18


def test_core_allowlist_required_classes_present():
    """A workflow that hits the core txt2img / inpaint / controlnet path needs these names."""
    must_have = {
        "CheckpointLoaderSimple",
        "CLIPTextEncode",
        "EmptyLatentImage",
        "KSampler",
        "KSamplerAdvanced",
        "VAEDecode",
        "SaveImage",
        "LoadImage",
        "LoadImageMask",
        "VAEEncode",
        "VAEEncodeForInpaint",
        "ControlNetLoader",
        "ControlNetApplyAdvanced",
        "VAELoader",
        "LoraLoader",
        "UpscaleModelLoader",
        "ImagePadForOutpaint",
        "ImageUpscaleWithModel",
    }
    assert must_have <= CORE_ALLOWLIST


def test_core_and_controlnet_disjoint():
    assert not (CORE_ALLOWLIST & CONTROLNET_PREPROCESSOR_ALLOWLIST)


def test_denylist_named_high_risk_classes():
    """Animation, face swap, IPAdapter, FaceDetailer should all be on the explicit denylist."""
    expected = {
        "AnimateDiffLoader",
        "FaceDetailer",
        "ReActorFaceSwap",
        "IPAdapterApply",
    }
    assert expected <= EXPLICIT_DENYLIST


def test_is_allowed_class_simple_cases():
    assert is_allowed_class("KSampler") is True
    assert is_allowed_class("CannyEdgePreprocessor") is True  # controlnet preprocessor
    assert is_allowed_class("KSamplerAdvanced") is True
    assert is_allowed_class("AnimateDiffLoader") is False
    assert is_allowed_class("") is False
    assert is_allowed_class(None) is False  # type: ignore[arg-type]


def test_is_explicitly_denied_class_named_set():
    assert is_explicitly_denied_class("ReActorFaceSwap") is True
    assert is_explicitly_denied_class("FaceDetailer") is True
    assert is_explicitly_denied_class("VHS_VideoCombine") is True
    assert is_explicitly_denied_class("KSampler") is False  # allowed, not denied
    assert is_explicitly_denied_class("") is False


def test_is_explicitly_denied_class_regex_patterns():
    """Names matching the rules.py blocklist regex should also count as denied."""
    assert is_explicitly_denied_class("MyShellExecNode") is True  # 'shell' / 'exec'
    assert is_explicitly_denied_class("CustomDownloadURLNode") is True  # 'downloadurl'
    assert is_explicitly_denied_class("HTTPRequestNode") is True  # 'httprequest'
    assert is_explicitly_denied_class("RunCodeWidget") is True  # 'runcode'


def test_unknown_class_neither_allowed_nor_denied():
    """The third bucket (unknown) is the one that drives §4 capability=UNSUPPORTED."""
    name = "SomeNewCommunityNode"
    assert is_allowed_class(name) is False
    assert is_explicitly_denied_class(name) is False
