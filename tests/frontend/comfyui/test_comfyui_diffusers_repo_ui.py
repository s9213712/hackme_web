"""Frontend smoke checks for Hugging Face Diffusers repo preflight."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]


def _read(path):
    return (ROOT / path).read_text(encoding="utf-8")


def test_diffusers_generation_page_accepts_repo_and_variant_selection():
    html = _read("public/index.html")
    assert 'id="comfyui-diffusers-model-repo"' in html
    assert 'id="comfyui-diffusers-inspect-btn"' in html
    assert 'id="comfyui-diffusers-model-variant"' in html
    assert 'id="comfyui-diffusers-gguf-base-repo"' in html
    assert 'id="comfyui-diffusers-repo-status"' in html


def test_diffusers_js_preflights_huggingface_repo_before_generation():
    js = _read("public/js/36-comfyui.js")
    assert 'apiFetch(API + "/comfyui/diffusers/inspect"' in js
    assert "function inspectComfyuiDiffusersRepo" in js
    assert "diffusers_model_variant" in js
    assert "diffusers_gguf_file" in js
    assert "updateComfyuiDiffusersGgufOptions" in js
    assert "尚未開始下載" in js
    assert "避免重複下載" in js


def test_diffusers_cache_busts_preflight_ui_assets():
    html = _read("public/index.html")
    assert "/js/36-comfyui.js?v=20260514-comfyui-subtabs" in html
    assert "/js/36-comfyui-workflows.js?v=20260514-comfyui-subtabs" in html


def test_diffusers_generation_progress_surfaces_huggingface_download_bytes():
    js = _read("public/js/36-comfyui.js")
    assert 'phase === "downloading"' in js
    assert "下載 Hugging Face 模型" in js
    assert "progress.bytes_written" in js
    assert "progress.total_bytes" in js
    assert "progress.current_file" in js
    assert "progress.speed_bytes_per_sec" in js
    assert "progress.step" in js
    assert "formatDriveBytes(writtenBytes)" in js
    assert "上限由後端工作控制" in js
