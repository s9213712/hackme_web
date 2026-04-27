from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_dm_ui_assets_are_wired():
    index_html = (ROOT / "public" / "index.html").read_text(encoding="utf-8")
    core_js = (ROOT / "public" / "js" / "00-core.js").read_text(encoding="utf-8")
    admin_js = (ROOT / "public" / "js" / "50-admin.js").read_text(encoding="utf-8")
    bootstrap_js = (ROOT / "public" / "js" / "90-bootstrap.js").read_text(encoding="utf-8")
    dm_js = (ROOT / "public" / "js" / "33-dm.js").read_text(encoding="utf-8")

    assert 'id="tab-module-dm"' in index_html
    assert 'id="module-dm"' in index_html
    assert 'id="dm-thread-list"' in index_html
    assert 'id="dm-message-list"' in index_html
    assert '<script src="/js/33-dm.js" defer></script>' in index_html

    assert 'canAccessModule("dm")' in core_js
    assert 'normTab === "dm"' in admin_js
    assert 'tabModuleDm.addEventListener("click", () => switchModuleTab("dm"))' in bootstrap_js
    assert 'fetch(API + "/dm/threads"' in dm_js
    assert 'fetch(API + `/dm/threads/${encodeURIComponent(selectedDmThreadId)}/messages`' in dm_js
    assert 'fetch(API + "/dm/blocks"' in dm_js
