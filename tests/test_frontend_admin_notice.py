from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_admin_notice_panel_and_bindings_exist():
    index_html = (ROOT / "public" / "index.html").read_text(encoding="utf-8")
    admin_js = (ROOT / "public" / "js" / "50-admin.js").read_text(encoding="utf-8")
    bootstrap_js = (ROOT / "public" / "js" / "90-bootstrap.js").read_text(encoding="utf-8")
    core_js = (ROOT / "public" / "js" / "00-core.js").read_text(encoding="utf-8")

    assert 'id="tab-notices"' in index_html
    assert 'id="admin-notice-user-id"' in index_html
    assert 'id="admin-notice-template"' in index_html
    assert 'id="admin-notice-send-btn"' in index_html
    assert 'action: "admin:notices"' in core_js
    assert 'switchAdminTab("notices")' in bootstrap_js
    assert 'addEventListener("change", applyAdminNoticeTemplate)' in bootstrap_js
    assert 'function renderAdminNoticeTargetOptions' in admin_js
    assert 'apiFetch(API + "/admin/notifications/send"' in admin_js
