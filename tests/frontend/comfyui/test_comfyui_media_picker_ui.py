"""Frontend smoke checks for ComfyUI media modes and reusable image picker."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]


def _read(path):
    return (ROOT / path).read_text(encoding="utf-8")


def test_index_html_exposes_reusable_image_picker_and_media_modes():
    html = _read("public/index.html")
    assert 'id="comfyui-source-image-picker-btn"' in html
    assert 'id="comfyui-mask-image-picker-btn"' in html
    assert 'id="comfyui-control-image-picker-btn"' in html
    assert 'id="comfyui-image-picker-modal"' in html
    for mode in ("t2v", "i2v", "v2v", "t2s", "t2sv"):
        assert f'value="{mode}"' in html


def test_comfyui_js_imports_history_and_drive_images_for_inputs():
    js = _read("public/js/36-comfyui.js")
    assert 'apiFetch(API + "/comfyui/input-image-candidates"' in js
    assert 'apiFetch(API + "/comfyui/import-drive-image"' in js
    assert 'apiFetch(API + "/comfyui/import-history-image"' in js
    assert "cloudFileId" in js
    assert "function renderComfyuiGeneratedMedia(mediaItems" in js


def test_workflow_template_run_sends_image_field_assignments():
    workflow_js = _read("public/js/36-comfyui-workflows.js")
    assert "function collectComfyuiTemplateImageAssignments(detail)" in workflow_js
    assert "image_field_assignments: imageAssignmentState.assignments" in workflow_js
    assert 'data-comfyui-template-image-picker' in workflow_js


def test_image_picker_styles_are_responsive():
    css = _read("public/styles.css")
    assert ".comfyui-image-picker-modal" in css
    assert ".comfyui-image-picker-list" in css
    assert ".comfyui-generated-media" in css
    assert "@media (max-width: 860px)" in css
