from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_avatar_upload_ui_is_wired():
    index_html = (ROOT / "public" / "index.html").read_text(encoding="utf-8")
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
    assert 'avatarUploadBtn.addEventListener("click", uploadUserAvatar)' in bootstrap_js
