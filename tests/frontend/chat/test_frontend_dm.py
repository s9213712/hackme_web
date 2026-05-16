from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]


def test_dm_ui_removed_and_chat_group_controls_are_wired():
    index_html = (ROOT / "public" / "index.html").read_text(encoding="utf-8")
    core_js = (ROOT / "public" / "js" / "00-core.js").read_text(encoding="utf-8")
    admin_js = (
        (ROOT / "public" / "js" / "50-admin.js").read_text(encoding="utf-8")
        + "\n"
        + (ROOT / "public" / "js" / "51-admin-server-mode-launch-check.js").read_text(encoding="utf-8")
    )
    bootstrap_js = (ROOT / "public" / "js" / "90-bootstrap.js").read_text(encoding="utf-8")
    chat_js = (ROOT / "public" / "js" / "20-chat.js").read_text(encoding="utf-8")
    users_js = (ROOT / "public" / "js" / "10-users.js").read_text(encoding="utf-8")

    assert 'id="tab-module-dm"' not in index_html
    assert 'id="module-dm"' not in index_html
    assert 'src="/js/33-dm.js' not in index_html
    assert 'module: "dm"' not in core_js
    assert 'normTab === "dm"' not in admin_js
    assert 'switchModuleTab("dm")' not in bootstrap_js

    assert 'id="chat-room-invite-users"' in index_html
    assert 'id="chat-room-password"' in index_html
    assert 'id="chat-room-allow-anonymous"' in index_html
    assert 'id="chat-room-use-anonymous"' in index_html
    assert 'id="chat-create-room-toggle-btn"' in index_html
    assert 'id="chat-room-create-panel" hidden' in index_html
    assert 'id="chat-create-room-cancel-btn"' in index_html
    assert 'class="user-edit-overlay chat-room-dialog"' in index_html
    assert 'id="chat-join-room-open-btn"' in index_html
    assert 'id="chat-room-join-panel" hidden' in index_html
    assert 'id="chat-join-password"' in index_html
    assert 'id="chat-join-anonymous"' in index_html
    assert 'id="chat-join-room-cancel-btn"' in index_html
    assert 'id="chat-room-invite-btn"' in index_html
    assert 'id="chat-room-export-btn"' in index_html
    assert "function inviteChatRoomMembers()" in chat_js
    assert "function exportChatRoom()" in chat_js
    assert "function toggleChatCreatePanel()" in chat_js
    assert "function toggleChatJoinPanel()" in chat_js
    assert "setChatCreatePanelVisible(false)" in chat_js
    assert "setChatJoinPanelVisible(false)" in chat_js
    assert "allow_anonymous: allowAnonymous" in chat_js
    assert "anonymous" in chat_js
    assert "r.hide_member_count" in core_js
    assert "m.sender_original" in core_js
    assert "chat-official-badge" in core_js
    assert "chatCreateToggleBtn.addEventListener" in bootstrap_js
    assert "chatCreateCancelBtn.addEventListener" in bootstrap_js
    assert "chatJoinOpenBtn.addEventListener" in bootstrap_js
    assert "chatJoinCancelBtn.addEventListener" in bootstrap_js
    assert "inviteChatRoomMembers" in bootstrap_js
    assert "exportChatRoom" in bootstrap_js
    assert "openPmWithUser(u.username)" in users_js
