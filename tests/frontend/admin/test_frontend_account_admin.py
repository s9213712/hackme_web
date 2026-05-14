from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]


def test_admin_user_delete_shows_visible_account_page_feedback():
    users_js = (ROOT / "public" / "js" / "10-users.js").read_text(encoding="utf-8")
    auth_js = (ROOT / "public" / "js" / "40-auth-users.js").read_text(encoding="utf-8")
    index_html = (ROOT / "public" / "index.html").read_text(encoding="utf-8")

    assert 'id="admin-users-msg"' in index_html
    assert "function adminUsersMsgEl()" in users_js
    assert '$("admin-users-msg") || $("li-msg")' in users_js
    assert 'flash(adminUsersMsgEl(), json.msg || "會員清單讀取失敗", false);' in users_js
    assert 'flash(adminUsersMsgEl(), err.message || "會員清單讀取失敗", false);' in users_js

    assert "正在刪除帳號..." in auth_js
    assert "確定要刪除待審核帳號" in auth_js
    assert "此操作會移除該註冊申請" in auth_js
    assert "await loadUsers();" in auth_js
    assert 'flash(msgEl, json.msg || "帳號已刪除", true);' in auth_js
    assert 'flash(msgEl, json.msg || `刪除失敗（HTTP ${res.status}）`, false);' in auth_js
    assert 'flash(msgEl, err.message || "刪除失敗，請稍後再試", false);' in auth_js
    assert 'id="admin-add-msg" role="alert" aria-live="assertive"' in index_html
    assert 'required aria-describedby="admin-add-msg"' in index_html
    assert "function adminAddMsgEl()" in auth_js
    assert 'const dialogMsgEl = adminAddMsgEl();' in auth_js
    assert 'u.status === "deleted"' in users_js
    assert 'statusSpan.textContent = "已刪除"' in users_js
    assert '請至少填寫帳號、密碼、確認密碼與暱稱' in auth_js
    assert 'flash(dialogMsgEl || pageMsgEl, "請至少填寫帳號、密碼、確認密碼與暱稱", false);' in auth_js
    assert 'flash(pageMsgEl, json.msg || "帳號已建立", true);' in auth_js
    assert "真實姓名（選填）" in index_html
    assert "身分證（選填）" in index_html


def test_disabled_appeals_are_not_prefetched_for_users_or_root():
    core_js = (ROOT / "public" / "js" / "00-core.js").read_text(encoding="utf-8")
    appeals_js = (ROOT / "public" / "js" / "30-appeals.js").read_text(encoding="utf-8")

    assert 'if (currentRole === "super_admin" && canAccessModule("appeals")) {' in core_js
    assert 'if (currentRole !== "super_admin" && canAccessModule("appeals")) {' in core_js
    assert 'if (!wrap || !currentUser || !canAccessModule("appeals")) return;' in appeals_js
    assert 'if (!currentUser || currentRole !== "super_admin" || !canAccessModule("appeals")) return;' in appeals_js
