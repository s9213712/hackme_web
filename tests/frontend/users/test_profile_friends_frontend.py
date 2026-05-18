from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]


def test_profile_friends_panel_is_wired_as_user_module():
    index_html = (ROOT / "public" / "index.html").read_text(encoding="utf-8")
    core_js = (ROOT / "public" / "js" / "00-core.js").read_text(encoding="utf-8")
    admin_js = (ROOT / "public" / "js" / "50-admin.js").read_text(encoding="utf-8")
    bootstrap_js = (ROOT / "public" / "js" / "90-bootstrap.js").read_text(encoding="utf-8")
    profile_js = (ROOT / "public" / "js" / "58-profile-friends.js").read_text(encoding="utf-8")
    css = (ROOT / "public" / "styles.css").read_text(encoding="utf-8")

    chat_pos = index_html.index('id="tab-module-chat"')
    profile_pos = index_html.index('id="tab-module-profile"')
    announcements_pos = index_html.index('id="tab-module-announcements"')
    assert chat_pos < profile_pos < announcements_pos
    assert 'id="sidebar-user-card" role="button" tabindex="0"' in index_html
    assert 'id="module-profile"' in index_html
    assert 'data-profile-tab="home"' in index_html
    assert 'data-profile-tab="edit"' in index_html
    assert 'data-profile-tab="friends"' in index_html
    assert 'id="s-module-profile-min-role"' in index_html
    assert 'id="profile-avatar-cloud-file"' in index_html
    assert 'id="profile-avatar-cloud-use"' in index_html
    assert 'id="profile-avatar-crop-zoom" min="1" max="6"' in index_html
    assert "/js/58-profile-friends.js" in index_html
    assert 'tabId: "tab-module-profile"' in core_js
    assert 'action: "profile:friends"' in core_js
    assert 'switchModuleTab("profile")' in core_js
    assert 'currentModuleTab === "profile"' in core_js
    assert 'canAccessProfile' in admin_js
    assert 'module_profile_min_role' in admin_js
    assert 'modProfile.classList.toggle("active", normTab === "profile")' in admin_js
    assert 'loadProfilePanel()' in admin_js
    assert 'tabModuleProfile.addEventListener("click", () => switchModuleTab("profile"))' in bootstrap_js
    assert 'openMyProfilePanel("edit")' in bootstrap_js
    assert 'bindProfileFriendsControls()' in bootstrap_js
    assert '/users/me/profile' in profile_js
    assert '/friends/add-by-code' in profile_js
    assert '/friends/request' in profile_js
    assert '/users/target-options' in profile_js
    assert '["chat-room-target-user", "pm"]' in profile_js
    assert '["drive-share-account", "cloud_drive_share"]' in profile_js
    assert 'target-options-personal' in index_html
    assert '一般用戶限好友' in index_html
    users_js = (ROOT / "public" / "js" / "10-users.js").read_text(encoding="utf-8")
    assert "u.is_friend || canAdministrativePm" in users_js
    assert 'async function copyTextToClipboard(text)' in profile_js
    assert 'await navigator.clipboard.writeText(value)' in profile_js
    assert 'textarea.value = value' in profile_js
    assert 'button.textContent = "已複製"' in profile_js
    assert 'showActionFeedback(button || document.activeElement, "好友代碼已複製"' in profile_js
    assert "profileAvatarCloudFileIsUsable" in profile_js
    assert "cloud_file_id" in profile_js
    assert "/cloud-drive/files?user_id=" in profile_js
    assert "/preview/content" in profile_js
    assert '.profile-friend-columns' in css
    assert '.profile-avatar-cloud-row' in css
    assert '.sidebar-user-card:hover' in css
