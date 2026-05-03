from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_main_app_has_mobile_responsive_overrides():
    index_html = (ROOT / "public" / "index.html").read_text(encoding="utf-8")
    css = (ROOT / "public" / "styles.css").read_text(encoding="utf-8")

    assert "/styles.css?v=20260503-appearance-v2" in index_html
    assert "Mobile ergonomics pass" in css
    assert "@media (max-width: 860px)" in css
    assert "@media (max-width: 720px)" in css
    assert ".app-action-bar" in css
    assert "left: .45rem;" in css
    assert "right: .45rem;" in css
    assert ".sidebar-nav.tabs" in css
    assert "overflow-x: auto;" in css
    assert "Mobile uses the same config-driven sidebar as desktop" in css
    assert "body.sidebar-collapsed .app-sidebar" in css
    assert "width: calc(100vw - 3.55rem);" in css
    assert "body.sidebar-collapsed .sidebar-nav .tab" in css
    assert "width: 2.75rem;" in css
    assert "min-height: 2.75rem;" in css
    assert "body.sidebar-collapsed .sidebar-icon-svg" in css
    assert "collapseSidebarAfterMobileNavigation" in (ROOT / "public" / "js" / "00-core.js").read_text(encoding="utf-8")
    assert ".settings-option-grid" in css
    assert "grid-template-columns: 1fr !important;" in css
    assert ".drive-file-row" in css
    assert ".trading-indicator-controls" in css
    assert ".trading-bot-tabs" in css
    assert ".chess-board" in css


def test_workflow_editor_has_mobile_responsive_overrides():
    css = (ROOT / "public" / "trading-workflow-editor.css").read_text(encoding="utf-8")

    assert "@media (max-width: 720px)" in css
    assert ".top-actions" in css
    assert "grid-template-columns: repeat(2, minmax(0, 1fr));" in css
    assert ".tool-grid" in css
    assert "max-height: 40dvh;" in css
    assert ".flow" in css
    assert ".logic-node" in css
    assert "@media (max-width: 460px)" in css
