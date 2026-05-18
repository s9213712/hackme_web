"""§4 Node Allowlist for the ComfyUI template importer.

Design principle: allowlist > blocklist. Three handling tiers:
- Allowlist hit → accepted (further capability check still applies at run).
- Explicit denylist hit → rejected at preview/import/run.
- Unknown class (neither allow nor deny) → preview passes with
  ``capability.overall == "UNSUPPORTED"``; import / run still reject.

Spec reference: docs/comfyui/COMFYUI_TEMPLATE_IMPORTER_PLAN.md §4.
"""

from __future__ import annotations

import re

from services.comfyui.validation.rules import (
    WORKFLOW_BLOCKED_CLASS_RE,
    WORKFLOW_BLOCKED_COMMAND_RE,
)


# §4.1 Core MVP allowlist
CORE_ALLOWLIST = frozenset(
    {
        # Loaders
        "CheckpointLoaderSimple",
        "VAELoader",
        "LoraLoader",
        "ControlNetLoader",
        "UpscaleModelLoader",
        # Inputs
        "LoadImage",
        "LoadImageMask",
        "EmptyLatentImage",
        # Encoders
        "CLIPTextEncode",
        "VAEEncode",
        "VAEEncodeForInpaint",
        # Sampling
        "KSampler",
        "KSamplerAdvanced",
        # Decoders
        "VAEDecode",
        # ControlNet apply
        "ControlNetApplyAdvanced",
        # Outpaint helper
        "ImagePadForOutpaint",
        # Upscale apply
        "ImageUpscaleWithModel",
        # Save
        "SaveImage",
    }
)


# §4.2 ControlNet preprocessor allowlist; aligned with services/comfyui/constants.py
# CONTROLNET_TYPE_DEFINITIONS — extend in lockstep when adding controlnet types.
CONTROLNET_PREPROCESSOR_ALLOWLIST = frozenset(
    {
        "Canny",
        "CannyEdgePreprocessor",
        "DepthAnythingPreprocessor",
        "MiDaS-DepthMapPreprocessor",
        "OpenposePreprocessor",
        "DWPreprocessor",
        "LineArtPreprocessor",
        "LineartStandardPreprocessor",
        "PiDiNetPreprocessor",
        "ScribblePreprocessor",
        "SoftEdgePreprocessor",
        "HEDPreprocessor",
    }
)

MEDIA_WORKFLOW_ALLOWLIST = frozenset(
    {
        # Native / common video workflow nodes
        "CLIPLoader",
        "DualCLIPLoader",
        "TripleCLIPLoader",
        "UNETLoader",
        "CLIPVisionLoader",
        "CLIPVisionEncode",
        "ModelSamplingSD3",
        "WanImageToVideo",
        "WanImageToVideoApi",
        "WanSoundImageToVideo",
        "WanHuMoImageToVideo",
        "WanAnimateToVideo",
        "WanVaceToVideo",
        "CreateVideo",
        "SaveVideo",
        "SaveWEBM",
        "SaveAudioMP3",
        "GetVideoComponents",
        "LoadVideo",
        "VHS_LoadVideo",
        "VHS_VideoCombine",
        "VHS_LoadImages",
        "VHS_SplitImages",
        "VHS_DuplicateImages",
        "VHS_SelectEveryNthImage",
        "VHS_PruneOutputs",
        "AnimateDiffLoader",
        "AnimateDiffSampler",
        "AnimateDiffCombine",
        "ImageOnlyCheckpointLoader",
        "LoraLoaderModelOnly",
        "ConditioningSetTimestepRange",
        "BasicGuider",
        "BasicScheduler",
        "RandomNoise",
        "SamplerCustomAdvanced",
        "KSamplerSelect",
        "SplitSigmas",
        "FluxGuidance",
        "FluxDisableGuidance",
        "Flux2Scheduler",
        "FluxKontextImageScale",
        "FluxProFillNode",
        "FluxProDepthNode",
        "CLIPTextEncodeFlux",
        "StabilityStableImageSD_3_5Node",
        "ImageScaleToTotalPixels",
        "EmptySD3LatentImage",
        "EmptyFlux2LatentImage",
        "GetImageSize",
        "ReferenceLatent",
        "ComfySwitchNode",
        "ModelSamplingAuraFlow",
        "StringConcatenate",
        "ByteDanceSeedreamNode",
        "GrokImageEditNode",
        # Native / common audio workflow nodes
        "LoadAudio",
        "SaveAudio",
        "PreviewAudio",
        "ConditioningZeroOut",
        "EmptyAceStep1.5LatentAudio",
        "TextEncodeAceStepAudio1.5",
        "VAEDecodeAudio",
        "IndexTTSNode",
        "TimbreAudioLoader",
        "AudioCleanupNode",
        "F5TTS",
        "F5TTSNode",
        "CosyVoiceNode",
    }
)


# §4.3 explicitly denied class types (kept short; the regex below handles families).
# These are notable enough that we want named-deny instead of regex catch-all
# so audit / error messages can call them out by name.
EXPLICIT_DENYLIST = frozenset(
    {
        # IP / face — out of scope for v1 (privacy + multi-stage pipeline complexity)
        "IPAdapterApply",
        "IPAdapterModelLoader",
        "FaceDetailer",
        "DetailerForEach",
        "ReActorFaceSwap",
        "ReActorBuildFaceModel",
        # Multi-stage pipe wrappers — failure mode unclear, defer
        "DetailerPipe",
        "ToDetailerPipe",
    }
)


# Classes whose name pattern alone is enough to block (regex from validation/rules.py).
# Re-exported here so importer code can stay in the template package.
def _matches_blocked_pattern(class_type: str) -> bool:
    if not class_type:
        return False
    return bool(WORKFLOW_BLOCKED_CLASS_RE.search(class_type)) or bool(
        WORKFLOW_BLOCKED_COMMAND_RE.search(class_type)
    )


def is_allowed_class(class_type: str) -> bool:
    """True when the class type is on the core allowlist or controlnet preprocessor allowlist.

    A class can simultaneously be in the regex blocklist (e.g., a custom
    "ScriptedSampler" that contains "script") and never reach this function
    via the importer because preview rejects on regex blocklist first; this
    function therefore does not re-check regex.
    """
    if not class_type:
        return False
    return (
        class_type in CORE_ALLOWLIST
        or class_type in CONTROLNET_PREPROCESSOR_ALLOWLIST
        or class_type in MEDIA_WORKFLOW_ALLOWLIST
    )


def is_explicitly_denied_class(class_type: str) -> bool:
    """True when the class type is on the explicit denylist or matches a blocked regex pattern."""
    if not class_type:
        return False
    if class_type in EXPLICIT_DENYLIST:
        return True
    return _matches_blocked_pattern(class_type)


# Re-export for callers that want to wire their own checks.
__all__ = [
    "CORE_ALLOWLIST",
    "CONTROLNET_PREPROCESSOR_ALLOWLIST",
    "MEDIA_WORKFLOW_ALLOWLIST",
    "EXPLICIT_DENYLIST",
    "is_allowed_class",
    "is_explicitly_denied_class",
]
