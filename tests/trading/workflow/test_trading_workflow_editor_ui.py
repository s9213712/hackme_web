from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]


def test_trading_workflow_editor_has_full_node_editor_surface():
    html = (ROOT / "public" / "trading-workflow-editor.html").read_text(encoding="utf-8")
    js = (ROOT / "public" / "js" / "trading-workflow-editor.js").read_text(encoding="utf-8")

    assert "節點工具箱" in html
    assert "策略檢查" in html
    assert "回測預覽" in html
    assert "可讀 JSON" in html
    assert '<details class="top-action-menu">' in html
    assert '<div class="top-action-menu-body">' in html
    assert '<details class="tool-group" open>' in html
    assert '<summary class="tool-title">Graph 節點 <span class="tool-count">3</span></summary>' in html
    assert '<summary class="tool-title">條件節點 <span class="tool-count">8</span></summary>' in html
    assert '<summary class="tool-title">行為節點 <span class="tool-count">5</span></summary>' in html
    assert '<summary class="tool-title">控制節點 <span class="tool-count">1</span></summary>' in html
    assert 'href="/trading-workflow-editor.css?v=20260506-workflow-preview"' in html
    assert 'src="/js/trading-workflow-editor.js?v=20260506-workflow-preview"' in html
    assert 'id="workflow-preview-market"' in html
    assert 'id="workflow-preview-run-btn"' in html
    assert 'data-add-node="condition:price_below"' in html
    assert 'data-add-node="condition:ma_position"' in html
    assert 'data-add-node="action:buy_percent"' in html
    assert 'data-add-node="action:close_all"' in html
    assert "<script>" not in html
    assert "<style>" not in html
    assert 'style="' not in html
    assert "workflow_graph" in js
    assert '<details class="branch-action-menu">' in js
    assert '<summary class="branch-tab">圖表操作</summary>' in js
    assert '<div class="branch-action-menu-body">' in js
    assert "async function fetchWorkflowPreviewJson(path, options = {}, retryOnCsrf = true)" in js
    assert 'headers["X-CSRF-Token"] = await fetchWorkflowPreviewCsrfToken({ force: true });' in js
    assert 'json && json.error === "csrf_invalid"' in js
    assert "return fetchWorkflowPreviewJson(path, options, false);" in js
    assert "data-port-node" in js
    assert "graph-edge-layer" in js
    assert "renderGraphEdgeLayer" in js
    assert "edgePath" in js
    assert "data-node-inline" in js
    assert "renderNodeInlineControls" in js
    assert "refreshGraphEdgeLayer" in js
    assert "TRUE/FALSE branch" in js
    assert "Nested AND" in js
    assert "validateWorkflow" in js
    assert "workflowValidationErrorSummary" in js
    assert 'previewStatus(workflowValidationErrorSummary(errors, "Workflow validation 未通過"), false);' in js
    assert 'setStatus(workflowValidationErrorSummary(errors), false);' in js
    assert '詳見「策略檢查」' in js
    assert "Math.max(GRAPH_NODE_WIDTH + 260" in js
    assert "Math.max(GRAPH_NODE_HEIGHT + 260" in js
    assert "Math.max(1500" not in js
    assert "Math.max(1000" not in js
    assert '"/trading/workflow-editor/backtest"' in js
    assert "runWorkflowPreviewBacktest" in js
    assert "workflow-preview-metrics" in js
    assert "renderInspector" in js
    assert "applyGraphNodePositions" in js
    assert "window.HackmeTradingWorkflowEditor" in js
    assert 'style="' not in js

    css = (ROOT / "public" / "trading-workflow-editor.css").read_text(encoding="utf-8")
    assert ".graph-edge-layer" in css
    assert ".top-action-menu-body" in css
    assert ".tool-group[open] > .tool-title::before" in css
    assert ".branch-action-menu-body" in css
    assert ".graph-edge.positive" in css
    assert ".node-inline-controls" in css
    assert ".preview-metrics" in css


def test_trading_workflow_editor_static_page_requires_login():
    server = (ROOT / "server.py").read_text(encoding="utf-8")

    assert "def protect_sensitive_static_pages()" in server
    assert '"/trading-workflow-editor.html"' in server
    assert '"/comfyui-workflow-editor.html"' in server
    assert "get_current_user_ctx()" in server
    assert "STATIC_PAGE_UNAUTH_DENIED" in server
    assert 'resp.headers["Location"] = "/"' in server
    assert 'is_feature_enabled("feature_trading_enabled")' in server
    assert 'is_feature_enabled("feature_comfyui_enabled")' in server
