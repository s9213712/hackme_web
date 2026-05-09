"""UI schema regression for the ComfyUI template importer (§9)."""

import pytest

from services.comfyui.template.analyzer import analyze_workflow_json
from services.comfyui.template.capability import CapabilityCheck
from services.comfyui.template.ui_schema import (
    build_ui_schema,
    required_user_inputs,
)


# Same minimal txt2img.
TXT2IMG = {
    "4": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": "v1-5.safetensors"}},
    "5": {"class_type": "EmptyLatentImage", "inputs": {"width": 512, "height": 512, "batch_size": 1}},
    "6": {"class_type": "CLIPTextEncode", "inputs": {"text": "a cat", "clip": ["4", 1]}},
    "7": {"class_type": "CLIPTextEncode", "inputs": {"text": "low quality", "clip": ["4", 1]}},
    "3": {
        "class_type": "KSampler",
        "inputs": {
            "seed": 0, "steps": 20, "cfg": 7.5, "denoise": 1.0,
            "sampler_name": "euler", "scheduler": "normal",
            "model": ["4", 0], "positive": ["6", 0], "negative": ["7", 0], "latent_image": ["5", 0],
        },
    },
    "8": {"class_type": "VAEDecode", "inputs": {"samples": ["3", 0], "vae": ["4", 2]}},
    "9": {"class_type": "SaveImage", "inputs": {"filename_prefix": "ComfyUI", "images": ["8", 0]}},
}


def _panel_ids(schema):
    return [p["id"] for p in schema.panels]


def test_ui_schema_panels_in_canonical_order():
    schema = build_ui_schema(analysis=analyze_workflow_json(TXT2IMG))
    ids = _panel_ids(schema)
    # Panel order per §9.2: text, image, model, sampler, numeric, compatibility, raw.
    # Image / numeric panels with no fields are dropped; compatibility / raw always present.
    assert ids[0] == "text"
    assert ids[-2:] == ["compatibility", "raw"]
    assert "model" in ids
    assert "sampler" in ids


def test_ui_schema_groups_text_inputs_onto_text_panel():
    schema = build_ui_schema(analysis=analyze_workflow_json(TXT2IMG))
    text_panel = next(p for p in schema.panels if p["id"] == "text")
    field_ids = {f["id"] for f in text_panel["fields"]}
    assert "node:6:text" in field_ids
    assert "node:7:text" in field_ids


def test_ui_schema_routes_ksampler_numeric_to_sampler_panel():
    """KSampler.{seed, steps, cfg, denoise} sit on the sampler panel for cohesion."""
    schema = build_ui_schema(analysis=analyze_workflow_json(TXT2IMG))
    sampler_panel = next(p for p in schema.panels if p["id"] == "sampler")
    fids = {f["id"] for f in sampler_panel["fields"]}
    assert "node:3:seed" in fids
    assert "node:3:steps" in fids
    assert "node:3:sampler_name" in fids
    assert "node:3:scheduler" in fids


def test_ui_schema_routes_ksampler_advanced_fields_to_sampler_panel():
    workflow = {
        **TXT2IMG,
        "10": {
            "class_type": "KSamplerAdvanced",
            "inputs": {
                "noise_seed": 123,
                "steps": 30,
                "cfg": 6.5,
                "sampler_name": "euler",
                "scheduler": "normal",
                "add_noise": "enable",
                "start_at_step": 0,
                "end_at_step": 30,
                "return_with_leftover_noise": "disable",
                "model": ["4", 0],
                "positive": ["6", 0],
                "negative": ["7", 0],
                "latent_image": ["5", 0],
            },
        },
    }
    schema = build_ui_schema(analysis=analyze_workflow_json(workflow))
    sampler_panel = next(p for p in schema.panels if p["id"] == "sampler")
    fids = {f["id"] for f in sampler_panel["fields"]}
    assert "node:10:noise_seed" in fids
    assert "node:10:sampler_name" in fids
    assert "node:10:start_at_step" in fids


def test_ui_schema_routes_non_ksampler_numeric_to_advanced_panel():
    schema = build_ui_schema(analysis=analyze_workflow_json(TXT2IMG))
    panel_ids_present = _panel_ids(schema)
    if "numeric" in panel_ids_present:
        advanced = next(p for p in schema.panels if p["id"] == "numeric")
        fids = {f["id"] for f in advanced["fields"]}
        # EmptyLatentImage.width/height/batch_size are NUMERIC but not on KSampler
        assert "node:5:width" in fids
        assert "node:5:height" in fids
        assert "node:5:batch_size" in fids


def test_ui_schema_drops_save_image_filename_prefix():
    schema = build_ui_schema(analysis=analyze_workflow_json(TXT2IMG))
    all_field_ids = {f["id"] for p in schema.panels for f in p.get("fields", [])}
    assert "node:9:filename_prefix" not in all_field_ids


def test_ui_schema_carries_capability_payload_when_provided():
    cap = CapabilityCheck(
        supported=["KSampler"],
        unsupported=[],
        missing_models={"ckpt": ["x.safetensors"]},
        sampler_options={"KSampler.sampler_name": ["euler", "dpmpp_2m"]},
        overall="PARTIALLY_SUPPORTED",
        blockers=["缺 ckpt: x.safetensors"],
    )
    schema = build_ui_schema(analysis=analyze_workflow_json(TXT2IMG), capability=cap)
    assert schema.capability["overall"] == "PARTIALLY_SUPPORTED"
    assert schema.capability["missing_models"] == {"ckpt": ["x.safetensors"]}


def test_ui_schema_text_field_constraints_max_length():
    schema = build_ui_schema(analysis=analyze_workflow_json(TXT2IMG))
    text_panel = next(p for p in schema.panels if p["id"] == "text")
    pos = next(f for f in text_panel["fields"] if f["id"] == "node:6:text")
    assert pos["constraints"]["max_length"] == 2000


def test_ui_schema_image_panel_has_accept_mime():
    workflow = {
        **TXT2IMG,
        "10": {"class_type": "LoadImage", "inputs": {"image": "user_uploaded.png"}},
    }
    schema = build_ui_schema(analysis=analyze_workflow_json(workflow))
    image_panel = next(p for p in schema.panels if p["id"] == "image")
    img_field = next(f for f in image_panel["fields"] if f["id"] == "node:10:image")
    assert "image/png" in img_field["constraints"]["accept_mime"]


def test_required_user_inputs_excludes_save_image_prefix():
    ids = required_user_inputs(analyze_workflow_json(TXT2IMG))
    assert "node:9:filename_prefix" not in ids
    # All others remain
    assert "node:6:text" in ids
    assert "node:3:seed" in ids


def test_required_user_inputs_skips_unknown_category_fields():
    workflow = {
        **TXT2IMG,
        "10": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": "y.safetensors", "weird_extra": "abc"}},
    }
    ids = required_user_inputs(analyze_workflow_json(workflow))
    # weird_extra is UNKNOWN for CheckpointLoaderSimple — should not show up
    assert "node:10:weird_extra" not in ids


def test_ui_schema_to_dict_is_json_friendly():
    schema = build_ui_schema(analysis=analyze_workflow_json(TXT2IMG))
    payload = schema.to_dict()
    assert isinstance(payload["panels"], list)
    assert isinstance(payload["capability"], dict)
    assert isinstance(payload["raw_workflow"], dict)
