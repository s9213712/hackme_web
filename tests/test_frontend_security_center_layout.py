from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_security_center_logs_have_non_overlapping_layout():
    index_html = (ROOT / "public" / "index.html").read_text(encoding="utf-8")
    admin_js = (ROOT / "public" / "js" / "50-admin.js").read_text(encoding="utf-8")
    css = (ROOT / "public" / "styles.css").read_text(encoding="utf-8")

    assert 'class="security-log-grid"' in index_html
    assert 'id="security-audit-entries" class="security-log-box"' in index_html
    assert 'id="security-server-log" class="security-log-box security-log-pre"' in index_html
    assert 'id="security-server-output" class="security-log-box security-log-pre"' in index_html
    assert 'class="security-log-row"' in admin_js
    assert ".security-log-grid" in css
    assert "grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));" in css
    assert ".security-log-box" in css
    assert "overflow-wrap: anywhere;" in css
    assert ".security-log-row" in css
    assert "grid-template-columns: auto auto minmax(0, .9fr) minmax(0, .7fr) minmax(0, 1.6fr);" in css
