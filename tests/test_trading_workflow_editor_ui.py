from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_trading_workflow_editor_has_full_node_editor_surface():
    html = (ROOT / "public" / "trading-workflow-editor.html").read_text(encoding="utf-8")

    assert "節點工具箱" in html
    assert "策略檢查" in html
    assert "可讀 JSON" in html
    assert 'data-add-node="condition:price_below"' in html
    assert 'data-add-node="condition:ma_position"' in html
    assert 'data-add-node="action:buy_percent"' in html
    assert 'data-add-node="action:close_all"' in html
    assert 'class="logic-node"' in html
    assert "validateWorkflow" in html
    assert "renderConditionInspector" in html
    assert "renderActionInspector" in html
    assert "window.HackmeTradingWorkflowEditor" in html


def test_trading_workflow_editor_static_page_requires_login():
    server = (ROOT / "server.py").read_text(encoding="utf-8")

    assert "def protect_sensitive_static_pages()" in server
    assert 'request.path != "/trading-workflow-editor.html"' in server
    assert "get_current_user_ctx()" in server
    assert "STATIC_PAGE_UNAUTH_DENIED" in server
    assert 'resp.headers["Location"] = "/"' in server
    assert 'is_feature_enabled("feature_trading_enabled")' in server
