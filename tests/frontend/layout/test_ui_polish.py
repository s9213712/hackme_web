from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]


def test_global_ui_polish_feedback_is_wired():
    index_html = (ROOT / "public" / "index.html").read_text(encoding="utf-8")
    styles_css = (ROOT / "public" / "styles.css").read_text(encoding="utf-8")
    core_js = (ROOT / "public" / "js" / "00-core.js").read_text(encoding="utf-8")
    admin_js = (ROOT / "public" / "js" / "50-admin.js").read_text(encoding="utf-8")

    assert 'id="toast-host"' in index_html
    assert 'role="status"' in index_html
    assert 'aria-relevant="additions text"' in index_html

    assert "function showAppToast" in core_js
    assert "function announceInlineMessage" in core_js
    assert "function installUiInteractionFeedback" in core_js
    assert "function animateActiveModule" in core_js
    assert "announceInlineMessage(text, ok);" in core_js
    assert "installUiInteractionFeedback();" in core_js
    assert 'closest?.(".btn, .tab, .icon-action-btn, .game-catalog-card' in core_js
    assert 'animateActiveModule(normTab);' in admin_js

    assert "@keyframes ui-module-enter" in styles_css
    assert "@keyframes ui-press-ripple" in styles_css
    assert "@keyframes ui-shimmer" in styles_css
    assert ".module-section.ui-module-enter > .admin-tools" in styles_css
    assert ".toast-host" in styles_css
    assert ".toast.show" in styles_css
    assert ".toast-ok::before" in styles_css
    assert ".toast-err::before" in styles_css
    assert ".btn.loading" in styles_css
    assert ".field:focus-within label" in styles_css
    assert "prefers-reduced-motion: reduce" in styles_css
