"""Frontend smoke checks for the ComfyUI visual workflow builder."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]


def _read(path):
    return (ROOT / path).read_text(encoding="utf-8")


def test_visual_builder_node_toolbox_is_collapsible_and_categorized():
    html = _read("public/comfyui-workflow-editor.html")
    js = _read("public/js/comfyui-workflow-editor.js")
    css = _read("public/comfyui-workflow-editor.css")

    assert '<details class="tool-group catalog-loader" open>' in html
    assert '<details class="tool-group" open>' in html
    assert '<summary class="tool-title">模型 / 文字</summary>' in html
    assert '<summary class="tool-title">影像 / Latent / Inpaint</summary>' in html
    assert '<summary class="tool-title">Control / Upscale</summary>' in html
    assert '<summary class="tool-title">Custom / API</summary>' in html
    assert 'id="dynamicNodeCatalogCount"' in html
    assert 'class="catalog-category-list" id="dynamicNodeCatalogList"' in html

    assert ".tool-group > summary" in css
    assert ".tool-group[open] > .tool-title::before" in css
    assert ".catalog-category-list" in css
    assert ".catalog-category > summary" in css

    assert "const groups = new Map();" in js
    assert 'if (count) count.textContent = String(query ? items.length : nodeCatalog.length);' in js
    assert 'list.innerHTML = items.length ? Array.from(groups.entries()).map(([category, categoryItems]) => `' in js
    assert '<details class="catalog-category"${query ? " open" : ""}>' in js
    assert 'const searchText = `${node.class_type || ""} ${node.display_name || ""} ${category}`;' in js
    assert 'data-search-text="${html(searchText)}"' in js
    assert 'const categoryTitle = button.closest(".catalog-category")?.querySelector("summary")?.textContent || "";' in js
    assert 'button.getAttribute("data-search-text") || ""' in js
    assert "if (query && hasVisible) group.open = true;" in js
    assert "index === 0" not in js


def test_visual_builder_auto_layout_follows_workflow_flow_order():
    html = _read("public/comfyui-workflow-editor.html")
    js = _read("public/js/comfyui-workflow-editor.js")

    assert 'id="autoLayoutBtn" type="button">依流程自動整理</button>' in html
    assert "function workflowFlowLayers()" in js
    assert "const incomingCount = new Map(ids.map((id) => [id, 0]));" in js
    assert "const outgoing = new Map(ids.map((id) => [id, []]));" in js
    assert "depth.set(next, Math.max(depth.get(next) || 0, (depth.get(id) || 0) + 1));" in js
    assert "node.x = AUTO_LAYOUT_X + layerIndex * AUTO_LAYOUT_COLUMN_GAP;" in js
    assert "node.y = AUTO_LAYOUT_Y + rowIndex * AUTO_LAYOUT_ROW_GAP;" in js
    assert "workflow.nodes = layers.flat().map((id) => nodeMap.get(id)).filter(Boolean);" in js
    assert "function fitCanvasToWorkflow()" in js
    assert "來源在左、輸出在右" in js
