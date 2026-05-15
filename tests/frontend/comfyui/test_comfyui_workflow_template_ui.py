"""Frontend smoke checks for compact ComfyUI workflow template selection."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]


def _read(path):
    return (ROOT / path).read_text(encoding="utf-8")


def test_template_details_are_hidden_until_template_selected():
    html = _read("public/index.html")
    js = _read("public/js/36-comfyui-workflows.js")
    css = _read("public/styles.css")

    assert 'id="comfyui-template-summary" class="comfyui-template-summary" hidden' in html
    assert 'id="comfyui-template-panels" class="comfyui-template-panels" hidden' in html
    assert "summary.hidden = true;" in js
    assert "host.hidden = true;" in js
    assert "summary.hidden = false;" in js
    assert "host.hidden = false;" in js
    assert ".comfyui-template-detail-panel" in css


def test_direct_template_fields_are_editable_for_large_model_workflows():
    js = _read("public/js/36-comfyui-workflows.js")
    css = _read("public/styles.css")
    assert 'return { kind: "direct", fieldId: field.id };' in js
    assert 'binding.kind === "direct"' in js
    assert "comfyuiTemplateDirectHint" in js
    assert ".comfyui-template-direct-hint" in css


def test_comfyui_tools_are_split_into_subviews():
    html = _read("public/index.html")
    js = _read("public/js/36-comfyui.js")
    css = _read("public/styles.css")

    assert 'data-comfyui-view="generate"' in html
    assert 'data-comfyui-view="history"' in html
    assert 'data-comfyui-view="workflow"' in html
    assert 'data-comfyui-view="models" hidden' in html
    assert 'data-comfyui-view-panel="generate"' in html
    assert 'data-comfyui-view-panel="history"' in html
    assert 'data-comfyui-view-panel="workflow"' in html
    assert 'data-comfyui-view-panel="models"' in html
    assert "function setComfyuiView" in js
    assert "bindComfyuiSubnav" in js
    assert ".comfyui-subview[hidden]" in css


def test_local_model_management_hides_outside_local_root_mode():
    html = _read("public/index.html")
    js = _read("public/js/36-comfyui.js")
    css = _read("public/styles.css")

    assert 'data-comfyui-view="models" hidden' in html
    assert "function canManageComfyuiLocalModels" in js
    assert 'return currentUser === "root" && mode === "local";' in js
    assert 'const modelsUnavailable = selected === "models" && (!canManageComfyuiLocalModels() || (modelTab && modelTab.hidden));' in js
    assert "const showLocalModels = canManageComfyuiLocalModels(mode);" in js
    assert 'if (panel) panel.style.display = showLocalModels ? "" : "none";' in js
    assert "if (modelsTab) modelsTab.hidden = !showLocalModels;" in js
    assert "if (details && !showLocalModels) details.open = false;" in js
    assert 'document.addEventListener("hackme:account-context-changed"' in js
    assert ".comfyui-subtab[hidden]" in css
