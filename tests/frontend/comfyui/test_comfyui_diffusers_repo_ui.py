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
    assert 'id="s-comfyui-allow-in-process-diffusers"' in html


def test_diffusers_js_preflights_huggingface_repo_before_generation():
    js = _read("public/js/36-comfyui.js")
    assert 'apiFetch(API + "/comfyui/diffusers/inspect?" + query.toString()' in js
    assert "new URLSearchParams" in js
    assert "function inspectComfyuiDiffusersRepo" in js
    assert "diffusers_model_variant" in js
    assert "diffusers_gguf_file" in js
    assert "updateComfyuiDiffusersGgufOptions" in js
    assert "尚未開始下載" in js
    assert "避免重複下載" in js


def test_diffusers_cache_busts_preflight_ui_assets():
    html = _read("public/index.html")
    assert "/js/36-comfyui.js?v=20260520-diffusers-csrf-audit" in html
    assert "/js/36-comfyui-workflows.js?v=20260520-embedding-empty-hide" in html


def test_diffusers_generation_progress_surfaces_huggingface_download_bytes():
    html = _read("public/index.html")
    js = _read("public/js/36-comfyui.js")
    assert 'phase === "downloading"' in js
    assert "下載 Hugging Face 模型" in js
    assert "下載 Diffusers model" in js
    assert "Diffusers 暫無新進度" in js
    assert 'String(progress.backend_kind || "").toLowerCase() === "diffusers"' in js
    assert "baseDetail = `${baseDetail}（${percent}%）`;" in js
    assert "python_log_tail" in js
    assert "comfyui-progress-python-log" in html
    assert "Diffusers Python log" in html
    assert "progress.bytes_written" in js
    assert "progress.total_bytes" in js
    assert "progress.current_file" in js
    assert "progress.speed_bytes_per_sec" in js
    assert "progress.step" in js
    assert "formatDriveBytes(writtenBytes)" in js
    assert "不設最長等待上限" in js


def test_diffusers_txt2img_hides_source_image_card_until_needed():
    js = _read("public/js/36-comfyui.js")

    assert "function comfyuiShouldShowSourceImageCard" in js
    assert "if (!isComfyuiDiffusersMode()) return true;" in js
    assert 'return comfyuiModeUsesSourceImage(mode) || comfyuiHasInputAsset("source") || comfyuiHasInputAsset("mask");' in js
    assert 'if (sourceCard) sourceCard.style.display = comfyuiShouldShowSourceImageCard(mode) ? "" : "none";' in js


def test_diffusers_in_process_runtime_confirmation_is_in_quick_settings():
    quick_js = _read("public/js/01-root-quick-settings.js")
    admin_js = _read("public/js/50-admin.js")
    html = _read("public/index.html")

    assert "s-comfyui-allow-in-process-diffusers" in quick_js
    assert "接受主程序 Diffusers 資源風險" in quick_js
    assert "comfyui_allow_in_process_diffusers" in admin_js
    assert "只有勾選主程序資源風險確認後才允許直接推論" in admin_js
    assert "/js/01-root-quick-settings.js?v=20260520-diffusers-runtime-confirm" in html
    assert "/js/50-admin.js?v=20260520-diffusers-runtime-confirm" in html


def test_embedding_quick_insert_hides_when_no_embeddings_are_available():
    html = _read("public/index.html")
    comfyui_js = _read("public/js/36-comfyui.js")
    workflows_js = _read("public/js/36-comfyui-workflows.js")

    assert 'id="comfyui-embedding-shortcuts-field" style="display:none;"' in html
    assert 'const field = $("comfyui-embedding-shortcuts-field") || box.closest(".field");' in comfyui_js
    assert 'field.style.display = comfyuiAvailableEmbeddings.length ? "" : "none";' in comfyui_js
    assert 'box.innerHTML = "";' in comfyui_js
    assert "if (!values.length) return;" in comfyui_js
    assert 'if (!values.length) return "";' in workflows_js
