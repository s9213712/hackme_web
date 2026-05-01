from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_legacy_dm_module_is_not_registered_or_shown():
    operations_py = (ROOT / "routes" / "operations.py").read_text(encoding="utf-8")
    index_html = (ROOT / "public" / "index.html").read_text(encoding="utf-8")
    core_js = (ROOT / "public" / "js" / "00-core.js").read_text(encoding="utf-8")
    bootstrap_js = (ROOT / "public" / "js" / "90-bootstrap.js").read_text(encoding="utf-8")

    assert "register_dm_routes" not in operations_py
    assert 'id="module-dm"' not in index_html
    assert 'id="tab-module-dm"' not in index_html
    assert 'src="/js/33-dm.js' not in index_html
    assert 'module: "dm"' not in core_js
    assert 'switchModuleTab("dm")' not in bootstrap_js
