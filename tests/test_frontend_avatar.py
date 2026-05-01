from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_avatar_upload_ui_is_wired():
    index_html = (ROOT / "public" / "index.html").read_text(encoding="utf-8")
    core_js = (ROOT / "public" / "js" / "00-core.js").read_text(encoding="utf-8")
    users_js = (ROOT / "public" / "js" / "10-users.js").read_text(encoding="utf-8")
    community_js = (ROOT / "public" / "js" / "25-community.js").read_text(encoding="utf-8")
    chat_js = (ROOT / "public" / "js" / "20-chat.js").read_text(encoding="utf-8")
    auth_js = (ROOT / "public" / "js" / "40-auth-users.js").read_text(encoding="utf-8")
    bootstrap_js = (ROOT / "public" / "js" / "90-bootstrap.js").read_text(encoding="utf-8")

    assert 'id="edit-user-avatar-file"' in index_html
    assert 'id="edit-user-avatar-upload"' in index_html
    assert 'id="edit-avatar-crop-width"' in index_html
    assert "async function uploadUserAvatar()" in auth_js
    assert "function selectedUserAvatarFile()" in auth_js
    assert "const avatarFile = selectedUserAvatarFile();" in auth_js
    assert "if (!Object.keys(payload).length && !avatarFile)" in auth_js
    assert "submitUserAvatarUpload({ reloadUsers: false })" in auth_js
    assert 'apiFetch(API + `/admin/users/${editingUserId}/avatar`' in auth_js
    assert "markUserAvatarUpdated(editingUserId)" in auth_js
    assert 'avatarUploadBtn.addEventListener("click", uploadUserAvatar)' in bootstrap_js
    assert "function avatarUrlForUser(userId)" in core_js
    assert "function userAvatarMarkup(userId, username" in core_js
    assert "avatar.innerHTML = currentUser ? userAvatarInnerMarkup(currentUserId, currentUser)" in core_js
    assert "userAvatarMarkup(m.sender_id, m.sender" in core_js
    assert "usernameCell.innerHTML = userIdentityMarkup(u.id, u.username" in users_js
    assert "openPmWithUser(u.username)" in users_js
    assert "chat-message-image-preview" in core_js
    assert "userIdentityMarkup(thread.author_user_id, thread.author_username" in community_js
    assert "userIdentityMarkup(post.author_user_id, post.author_username" in community_js


def test_admin_user_table_shows_online_light():
    index_html = (ROOT / "public" / "index.html").read_text(encoding="utf-8")
    users_js = (ROOT / "public" / "js" / "10-users.js").read_text(encoding="utf-8")
    css = (ROOT / "public" / "styles.css").read_text(encoding="utf-8")

    assert "<th>在線</th>" in index_html
    assert "online-dot" in users_js
    assert "u.is_online" in users_js
    assert ".online-dot.online" in css
