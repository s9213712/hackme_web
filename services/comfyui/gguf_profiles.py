"""Official GGUF model profiles for ComfyUI routing.

GGUF image models are not interchangeable single-file checkpoints.  Each
customer-facing option must be mapped to the companion text encoders, VAE,
loader class, and verified workflow family before it can be routed safely.
"""

from __future__ import annotations

from copy import deepcopy
from pathlib import PurePosixPath


_WAI_VARIANTS = [
    ("q4_0", "Q4_0", "WAI-NSFW-illustrious-SDXL-v110-Q4_0.gguf", 1491343328, False, "needs_validation"),
    ("q4_1", "Q4_1", "WAI-NSFW-illustrious-SDXL-v110-Q4_1.gguf", 1649768928, False, "needs_validation"),
    ("q4_k_s", "Q4_K_S", "WAI-NSFW-illustrious-SDXL-v110-Q4_K_S.gguf", 1491773408, False, "needs_validation"),
    ("q5_0", "Q5_0", "WAI-NSFW-illustrious-SDXL-v110-Q5_0.gguf", 1808194528, False, "needs_validation"),
    ("q5_k_m", "Q5_K_M", "WAI-NSFW-illustrious-SDXL-v110-Q5_K_M.gguf", 1844424928, False, "needs_validation"),
    ("q5_k_s", "Q5_K_S", "WAI-NSFW-illustrious-SDXL-v110-Q5_K_S.gguf", 1808194528, False, "needs_validation"),
    ("q6_k", "Q6_K", "WAI-NSFW-illustrious-SDXL-v110-Q6_K.gguf", 2144848928, False, "needs_validation"),
    ("q8_0", "Q8_0", "WAI-NSFW-illustrious-SDXL-v110-Q8_0.gguf", 2758748128, True, "verified"),
    ("f16", "F16", "WAI-NSFW-illustrious-SDXL-v110-F16.gguf", 5135086048, False, "needs_validation"),
]


_SD35_VARIANTS = [
    ("q4_0", "Q4_0", "sd3.5_large-q4_0.gguf", 4770000000, False, "draft"),
    ("q4_1", "Q4_1", "sd3.5_large-q4_1.gguf", 5270000000, False, "draft"),
    ("q5_0", "Q5_0", "sd3.5_large-q5_0.gguf", 5770000000, False, "draft"),
    ("q5_1", "Q5_1", "sd3.5_large-q5_1.gguf", 6270000000, False, "draft"),
    ("q8_0", "Q8_0", "sd3.5_large-q8_0.gguf", 8780000000, False, "draft"),
    ("f16", "F16", "sd3.5_large-f16.gguf", 16300000000, False, "draft"),
]


def _variant(variant_id, label, filename, size_bytes, enabled, status):
    return {
        "id": variant_id,
        "label": label,
        "gguf_file": filename,
        "filename": filename,
        "size_bytes": int(size_bytes or 0),
        "enabled": bool(enabled),
        "status": status,
    }


OFFICIAL_GGUF_PROFILES = {
    "wai_illustrious_v110_sdxl": {
        "id": "wai_illustrious_v110_sdxl",
        "label": "WAI Illustrious SDXL v11",
        "family": "sdxl",
        "status": "verified",
        "enabled": True,
        "repo_id": "kekusprod/WAI-NSFW-illustrious-SDXL-v110-GGUF",
        "base_repo": "stabilityai/stable-diffusion-xl-base-1.0",
        "workflow_family": "sdxl_dual_clip_gguf",
        "clip_loader_class": "DualCLIPLoaderGGUF",
        "clip_type": "sdxl",
        "source_url": "https://huggingface.co/kekusprod/WAI-NSFW-illustrious-SDXL-v110-GGUF",
        "sampler_defaults": {"sampler_name": "euler", "scheduler": "normal", "cfg": 5.0, "steps": 24},
        "companions": [
            {
                "role": "clip_l",
                "repo_id": "calcuis/illustrious",
                "filename": "illustrious_clip_l_fp8_e4m3fn.safetensors",
                "model_type": "clip",
                "install_subdir": "text_encoders",
                "slot": "clip_name1",
            },
            {
                "role": "clip_g",
                "repo_id": "calcuis/illustrious",
                "filename": "illustrious_clip_g_fp8_e4m3fn.safetensors",
                "model_type": "clip",
                "install_subdir": "text_encoders",
                "slot": "clip_name2",
            },
            {
                "role": "vae",
                "repo_id": "calcuis/illustrious",
                "filename": "illustrious_v110_vae_fp8_e4m3fn.safetensors",
                "model_type": "vae",
                "install_subdir": "vae",
                "slot": "vae_name",
            },
        ],
        "variants": [_variant(*item) for item in _WAI_VARIANTS],
    },
    "sd35_large_gguf": {
        "id": "sd35_large_gguf",
        "label": "Stable Diffusion 3.5 Large GGUF",
        "family": "sd3.5",
        "status": "draft",
        "enabled": False,
        "repo_id": "calcuis/sd3.5-large-gguf",
        "base_repo": "stabilityai/stable-diffusion-3.5-large",
        "workflow_family": "sd3_triple_clip_gguf",
        "clip_loader_class": "TripleCLIPLoaderGGUF",
        "clip_type": "sd3",
        "source_url": "https://huggingface.co/calcuis/sd3.5-large-gguf",
        "sampler_defaults": {"sampler_name": "euler", "scheduler": "normal", "cfg": 4.5, "steps": 28},
        "companions": [
            {
                "role": "clip_g",
                "repo_id": "calcuis/sd3.5-large-gguf",
                "filename": "clip_g.safetensors",
                "model_type": "clip",
                "install_subdir": "clip",
                "slot": "clip_name1",
            },
            {
                "role": "clip_l",
                "repo_id": "calcuis/sd3.5-large-gguf",
                "filename": "clip_l.safetensors",
                "model_type": "clip",
                "install_subdir": "clip",
                "slot": "clip_name2",
            },
            {
                "role": "t5",
                "repo_id": "calcuis/sd3.5-large-gguf",
                "filename": "t5xxl_fp8_e4m3fn.safetensors",
                "model_type": "clip",
                "install_subdir": "clip",
                "slot": "clip_name3",
            },
            {
                "role": "vae",
                "repo_id": "calcuis/sd3.5-large-gguf",
                "filename": "diffusion_pytorch_model.safetensors",
                "model_type": "vae",
                "install_subdir": "vae",
                "slot": "vae_name",
            },
        ],
        "variants": [_variant(*item) for item in _SD35_VARIANTS],
    },
}


def _copy_profile(profile):
    return deepcopy(profile) if isinstance(profile, dict) else None


def official_gguf_profiles(*, include_disabled=True):
    profiles = []
    for profile in OFFICIAL_GGUF_PROFILES.values():
        if include_disabled or profile.get("enabled"):
            profiles.append(_copy_profile(profile))
    return sorted(profiles, key=lambda item: (not item.get("enabled"), str(item.get("label") or "")))


def get_official_gguf_profile(profile_id, *, include_disabled=True):
    profile = OFFICIAL_GGUF_PROFILES.get(str(profile_id or "").strip())
    if not profile:
        return None
    if not include_disabled and not profile.get("enabled"):
        return None
    return _copy_profile(profile)


def _variant_matches(variant, value):
    raw = str(value or "").strip()
    if not raw:
        return False
    name = PurePosixPath(raw.replace("\\", "/")).name
    return raw == variant.get("id") or raw == variant.get("gguf_file") or name == PurePosixPath(variant.get("gguf_file") or "").name


def get_official_gguf_variant(profile, variant_id="", gguf_file="", *, require_enabled=True):
    if not isinstance(profile, dict):
        return None
    candidates = [variant_id, gguf_file]
    enabled_profile = bool(profile.get("enabled"))
    for variant in profile.get("variants") or []:
        if not isinstance(variant, dict):
            continue
        if any(_variant_matches(variant, value) for value in candidates):
            if require_enabled and (not enabled_profile or not variant.get("enabled")):
                return None
            return deepcopy(variant)
    enabled_variants = [
        deepcopy(variant)
        for variant in (profile.get("variants") or [])
        if isinstance(variant, dict) and (not require_enabled or (enabled_profile and variant.get("enabled")))
    ]
    return enabled_variants[0] if not any(candidates) and len(enabled_variants) == 1 else None


def resolve_official_gguf_selection(profile_id="", variant_id="", *, repo_id="", gguf_file="", require_enabled=True):
    profile = get_official_gguf_profile(profile_id, include_disabled=not require_enabled)
    if profile:
        variant = get_official_gguf_variant(profile, variant_id, gguf_file, require_enabled=require_enabled)
        return (profile, variant) if variant else (profile, None)
    repo_text = str(repo_id or "").strip()
    file_text = str(gguf_file or "").strip()
    if not repo_text or not file_text:
        return None, None
    for candidate in official_gguf_profiles(include_disabled=not require_enabled):
        if str(candidate.get("repo_id") or "") != repo_text:
            continue
        variant = get_official_gguf_variant(candidate, variant_id, file_text, require_enabled=require_enabled)
        if variant:
            return candidate, variant
    return None, None


def public_gguf_profiles():
    result = []
    for profile in official_gguf_profiles(include_disabled=True):
        visible = {
            key: profile.get(key)
            for key in (
                "id",
                "label",
                "family",
                "status",
                "enabled",
                "repo_id",
                "base_repo",
                "workflow_family",
                "clip_loader_class",
                "source_url",
            )
        }
        visible["variants"] = [
            {
                key: variant.get(key)
                for key in ("id", "label", "gguf_file", "filename", "size_bytes", "enabled", "status")
            }
            for variant in (profile.get("variants") or [])
            if isinstance(variant, dict)
        ]
        visible["companions"] = [
            {
                key: item.get(key)
                for key in ("role", "repo_id", "filename", "model_type", "install_subdir", "slot")
            }
            for item in (profile.get("companions") or [])
            if isinstance(item, dict)
        ]
        result.append(visible)
    return result
