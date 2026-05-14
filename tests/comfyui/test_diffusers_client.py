import pytest

from services.comfyui.client import ComfyUIError
from services.comfyui.diffusers_client import DiffusersClient, diffusers_backend_url, repo_id_from_diffusers_url
from services.comfyui.huggingface import build_diffusers_variant_options, detect_diffusers_supported_modes
from services.comfyui.settings import normalize_huggingface_repo_id


def test_diffusers_backend_url_round_trips_repo_id():
    url = diffusers_backend_url("dhead/waiIllustriousSDXL_v150")

    assert url == "diffusers://local/dhead%2FwaiIllustriousSDXL_v150"
    assert repo_id_from_diffusers_url(url) == "dhead/waiIllustriousSDXL_v150"


def test_huggingface_repo_normalizer_accepts_repo_id_and_model_page_url():
    assert normalize_huggingface_repo_id("dhead/waiIllustriousSDXL_v150") == "dhead/waiIllustriousSDXL_v150"
    assert (
        normalize_huggingface_repo_id("https://huggingface.co/dhead/waiIllustriousSDXL_v150/tree/main")
        == "dhead/waiIllustriousSDXL_v150"
    )
    assert normalize_huggingface_repo_id("https://example.com/dhead/waiIllustriousSDXL_v150") is None


def test_huggingface_diffusers_metadata_groups_precision_variants_by_size():
    options = build_diffusers_variant_options([
        {"rfilename": "unet/diffusion_pytorch_model.safetensors", "size": 1000},
        {"rfilename": "vae/diffusion_pytorch_model.safetensors", "size": 200},
        {"rfilename": "unet/diffusion_pytorch_model.fp16.safetensors", "size": 520},
        {"rfilename": "vae/diffusion_pytorch_model.fp16.safetensors", "size": 110},
    ])

    assert [item["value"] for item in options] == ["__default__", "fp16"]
    assert options[0]["size_bytes"] == 1200
    assert options[1]["size_bytes"] == 630


def test_huggingface_diffusers_metadata_lists_gguf_files_as_selectable_options():
    options = build_diffusers_variant_options([
        {"rfilename": "WAI-illustrious-SDXL-v140-Q8_0.gguf", "size": 3_200_000_000},
        {"rfilename": "WAI-illustrious-SDXL-v140-Q5_K_M.gguf", "size": 2_100_000_000},
    ])

    assert [item["kind"] for item in options] == ["gguf", "gguf"]
    assert options[0]["value"].startswith("gguf::")
    assert options[0]["gguf_file"].endswith(".gguf")
    assert options[0]["requires_base_repo"] is True


def test_huggingface_diffusers_metadata_detects_unsupported_video_pipeline():
    assert detect_diffusers_supported_modes(
        repo_id="owner/video-model",
        pipeline_tag="text-to-video",
        library_name="diffusers",
        tags=["diffusers"],
        siblings=[{"rfilename": "model_index.json"}],
    ) == []


def test_huggingface_diffusers_metadata_detects_gguf_text_to_image_only():
    assert detect_diffusers_supported_modes(
        repo_id="sothmik/Wai-NSFW-Illustrious-v140-Q8-GGUF",
        pipeline_tag="text-to-image",
        library_name="gguf",
        tags=["GGUF"],
        siblings=[{"rfilename": "WAI-NSFW-Illustrious-v140-Q8_0.gguf"}],
    ) == ["txt2img"]


def test_diffusers_health_allows_blank_default_repo_for_generation_page_override(tmp_path, monkeypatch):
    client = DiffusersClient(storage_root=tmp_path)

    monkeypatch.setattr(client, "_missing_dependency_names", lambda: [])

    health = client.health_check()

    assert health["ok"] is True
    assert health["model_repo"] == ""


def test_diffusers_client_requires_effective_model_repo_before_dependency_check(tmp_path):
    client = DiffusersClient(storage_root=tmp_path)

    with pytest.raises(ComfyUIError) as exc:
        client.generate_image({"generation_mode": "txt2img", "prompt": "test"})

    assert "尚未設定 Hugging Face model repo" in str(exc.value)


def test_diffusers_client_upload_fetch_and_discard_round_trip(tmp_path):
    client = DiffusersClient(model_repo="dhead/waiIllustriousSDXL_v150", storage_root=tmp_path)

    image_ref = client.upload_image_bytes(b"png-bytes", "source.png", image_type="input")
    image = client.fetch_image(image_ref)
    discarded = client.discard_image(image_ref)

    assert image.filename.endswith("source.png")
    assert image.type == "input"
    assert image.data == b"png-bytes"
    assert discarded["file_deleted"] is True
