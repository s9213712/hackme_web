import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]


def test_chat_room_delete_ui_is_wired():
    index_html = (ROOT / "public" / "index.html").read_text(encoding="utf-8")
    core_js = (ROOT / "public" / "js" / "00-core.js").read_text(encoding="utf-8")
    chat_js = (ROOT / "public" / "js" / "20-chat.js").read_text(encoding="utf-8")
    drive_js = (ROOT / "public" / "js" / "35-drive.js").read_text(encoding="utf-8")
    css = (ROOT / "public" / "styles.css").read_text(encoding="utf-8")
    chat_route = (ROOT / "routes" / "chat.py").read_text(encoding="utf-8")

    # Asset references — match any cache-bust version so Codex / Claude
    # bumping the ?v=… string for browser caching doesn't tip these
    # tests over. The behavior under test is "the file is referenced",
    # not "the file is referenced at exactly version X".
    assert "/js/20-chat.js?v=20260429-official-chat-protect" in index_html
    assert re.search(r"/js/00-core\.js\?v=", index_html)
    assert re.search(r"/js/90-bootstrap\.js\?v=", index_html)
    assert re.search(r"/styles\.css\?v=", index_html)
    assert 'id="chat-friend-username"' in index_html
    assert 'id="chat-pending-attachment-list"' in index_html
    assert 'id="chat-attachment-pick-btn"' in index_html
    assert 'id="chat-shared-attachment-panel"' in index_html
    assert "選檔後會立即加入待送附件" in index_html
    assert "聊天室附件" not in index_html
    assert 'data-chat-sticker="smile"' in index_html
    assert "🙂" in index_html
    assert "🥹" in index_html
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
    assert 'smile: "🙂"' in chat_js
    assert 'thanks: "🥹"' in chat_js
    assert "sticker.glyph || sticker.label" in chat_js
    assert "pendingChatAttachments" in chat_js
    assert "function removePendingChatAttachment(fileId)" in chat_js
    assert "function syncChatSharedAttachmentPanel(refs)" in chat_js
    assert "function handlePendingChatAttachmentClick(event)" in chat_js
    assert 'data-remove-chat-pending-attachment="${sanitize(item.file_id || "")}"' in chat_js
    assert "刪除</button>" in chat_js
    assert "const refs = await loadContextAttachments(\"group_chat\", id, \"chat-attachment-list\")" in chat_js
    assert "attachment_file_ids" in chat_js
    assert "function openChatAttachmentPicker()" in drive_js
    assert "async function uploadPendingChatAttachment()" in drive_js
    assert "async function addExistingChatFileToPending(fileId)" in drive_js
    assert "if (!selectedFileId) return;" in drive_js
    assert 'apiFetch(API + `/chat/rooms/${encodeURIComponent(roomId)}`' in chat_js
    assert ".chat-room-delete-btn" in css
    assert ".chat-sticker-bar" in css
    assert ".chat-sticker-bar .chat-sticker-btn" in css
    assert ".chat-friend-panel" in css
    assert ".chat-message-attachments" in css
    assert ".chat-message-image-preview" in css
    assert ".chat-composer-tools" in css
    assert '"glyph": "🙂"' in chat_route
    assert '"glyph": "🥲"' in chat_route
