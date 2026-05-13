import pytest

from services.comfyui.client import ComfyUIError
from services.comfyui.diffusers_client import DiffusersClient, diffusers_backend_url, repo_id_from_diffusers_url


def test_diffusers_backend_url_round_trips_repo_id():
    url = diffusers_backend_url("dhead/waiIllustriousSDXL_v150")

    assert url == "diffusers://local/dhead%2FwaiIllustriousSDXL_v150"
    assert repo_id_from_diffusers_url(url) == "dhead/waiIllustriousSDXL_v150"


def test_diffusers_client_requires_model_repo_before_dependency_check(tmp_path):
    client = DiffusersClient(storage_root=tmp_path)

    with pytest.raises(ComfyUIError) as exc:
        client.health_check()

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
