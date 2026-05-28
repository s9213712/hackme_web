import os
from pathlib import Path

from services.comfyui.diffusers_client import DiffusersClient


def test_diffusers_client_sets_huggingface_cache_root(monkeypatch, tmp_path):
    monkeypatch.delenv("HF_HOME", raising=False)
    monkeypatch.delenv("HF_HUB_CACHE", raising=False)
    cache_root = tmp_path / "hf-cache"
    client = DiffusersClient(huggingface_cache_root=str(cache_root))

    backend = client._configure_huggingface_download_backend()

    assert Path(backend["cache_root"]) == cache_root
    assert Path(backend["hub_cache"]) == cache_root / "hub"
    assert Path(os.environ["HF_HOME"]) == cache_root
    assert Path(os.environ["HF_HUB_CACHE"]) == cache_root / "hub"
    assert (cache_root / "hub").is_dir()


def test_diffusers_repo_cache_dir_prefers_configured_root(tmp_path):
    cache_root = tmp_path / "hf-cache"
    client = DiffusersClient(huggingface_cache_root=str(cache_root))

    assert client._huggingface_repo_cache_dir("owner/model") == cache_root / "hub" / "models--owner--model"
