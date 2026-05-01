from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_dm_ui_assets_are_wired():
    index_html = (ROOT / "public" / "index.html").read_text(encoding="utf-8")
    core_js = (ROOT / "public" / "js" / "00-core.js").read_text(encoding="utf-8")
    admin_js = (ROOT / "public" / "js" / "50-admin.js").read_text(encoding="utf-8")
    bootstrap_js = (ROOT / "public" / "js" / "90-bootstrap.js").read_text(encoding="utf-8")
    dm_js = (ROOT / "public" / "js" / "33-dm.js").read_text(encoding="utf-8")
    chat_js = (ROOT / "public" / "js" / "20-chat.js").read_text(encoding="utf-8")
    users_js = (ROOT / "public" / "js" / "10-users.js").read_text(encoding="utf-8")

    assert 'id="tab-module-dm"' in index_html
    assert 'id="module-dm"' in index_html
    assert 'id="dm-thread-list"' in index_html
    assert 'id="dm-message-list"' in index_html
    assert 'id="admin-users-msg"' in index_html
    assert '/js/33-dm.js?v=20260429-pm-image-preview' in index_html

    assert 'canAccessModule("dm")' in core_js
    assert 'normTab === "dm"' in admin_js
    assert 'tabModuleDm.addEventListener("click", () => switchModuleTab("dm"))' in bootstrap_js
    assert 'apiFetch(API + "/dm/threads"' in dm_js
    assert 'apiFetch(API + `/dm/threads/${encodeURIComponent(selectedDmThreadId)}/messages`' in dm_js
    assert 'apiFetch(API + "/dm/blocks"' in dm_js
    assert "function renderDmMessageAttachments(attachments)" in dm_js
    assert "data-drive-action=\"album-full-preview\"" in dm_js
    assert "/cloud-drive/files/${encodeURIComponent(fileId)}/preview/content" in dm_js
    assert "openPmWithUser(u.username)" in users_js
    assert 'canAccessModule("dm")' in chat_js
    assert 'switchModuleTab("dm")' in chat_js
    assert "await createDmThread()" in chat_js
    assert 'admin-users-msg' in chat_js
