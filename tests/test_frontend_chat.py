from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_chat_room_delete_ui_is_wired():
    index_html = (ROOT / "public" / "index.html").read_text(encoding="utf-8")
    core_js = (ROOT / "public" / "js" / "00-core.js").read_text(encoding="utf-8")
    chat_js = (ROOT / "public" / "js" / "20-chat.js").read_text(encoding="utf-8")
    drive_js = (ROOT / "public" / "js" / "35-drive.js").read_text(encoding="utf-8")
    css = (ROOT / "public" / "styles.css").read_text(encoding="utf-8")

    assert "/js/20-chat.js?v=20260429-official-chat-protect" in index_html
    assert "/js/00-core.js?v=20260429-chat-attachment-delete" in index_html
    assert "/js/90-bootstrap.js?v=20260429-comfyui-load-last" in index_html
    assert "/styles.css?v=20260429-ui-polish" in index_html
    assert 'id="chat-friend-username"' in index_html
    assert 'id="chat-pending-attachment-list"' in index_html
    assert 'data-chat-sticker="smile"' in index_html
    assert "chat-room-row" in core_js
    assert "chat-room-delete-btn" in core_js
    assert "deleteChatRoom(r.id)" in core_js
    assert "data-recall-message" in core_js
    assert "chat-sticker" in core_js
    assert "chat-message-image-preview" in core_js
    assert 'data-drive-action="delete-context-attachment"' in core_js
    assert 'data-context-type="chat_message"' in core_js
    assert 'data-target-id="chat-messages"' in core_js
    assert "function canDeleteChatRoom(room)" in chat_js
    assert "room.is_official" in chat_js
    assert "async function deleteChatRoom(roomId)" in chat_js
    assert "async function sendChatSticker(stickerKey)" in chat_js
    assert "async function addChatFriend()" in chat_js
    assert "async function loadChatFriends()" in chat_js
    assert "pendingChatAttachments" in chat_js
    assert "function removePendingChatAttachment(fileId)" in chat_js
    assert "function handlePendingChatAttachmentClick(event)" in chat_js
    assert 'data-remove-chat-pending-attachment="${sanitize(item.file_id || "")}"' in chat_js
    assert "刪除</button>" in chat_js
    assert "attachment_file_ids" in chat_js
    assert "async function uploadPendingChatAttachment()" in drive_js
    assert "async function addExistingChatFileToPending(fileId)" in drive_js
    assert 'fetch(API + `/chat/rooms/${encodeURIComponent(roomId)}`' in chat_js
    assert ".chat-room-delete-btn" in css
    assert ".chat-sticker-bar" in css
    assert ".chat-friend-panel" in css
    assert ".chat-message-attachments" in css
    assert ".chat-message-image-preview" in css
