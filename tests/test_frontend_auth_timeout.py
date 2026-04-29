from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_inactivity_timeout_message_uses_configured_duration():
    core = (ROOT / "public" / "js" / "00-core.js").read_text(encoding="utf-8")
    auth = (ROOT / "public" / "js" / "40-auth-users.js").read_text(encoding="utf-8")

    assert "const DEFAULT_INACTIVITY_LOGOUT_MS = 10 * 60 * 1000;" in core
    assert "formatInactivityTimeoutLabel" in core
    assert "已閒置 ${formatInactivityTimeoutLabel()}，系統將自動登出。" in core
    assert "await doLogout({ immediate: true });" in core
    assert "function showLoginScreen()" in core
    assert "showLoginScreen();" in auth
    assert "if (!res.ok && !immediate)" in auth
    assert "已超過 3 分鐘未操作" not in core


def test_internal_test_login_token_is_hidden_outside_internal_test_mode():
    index = (ROOT / "public" / "index.html").read_text(encoding="utf-8")
    core = (ROOT / "public" / "js" / "00-core.js").read_text(encoding="utf-8")
    auth = (ROOT / "public" / "js" / "40-auth-users.js").read_text(encoding="utf-8")

    assert 'id="li-internal-test-token-field" style="display:none;"' in index
    assert 'siteConfig.server_mode === "internal_test"' in core
    assert "input.disabled = !showInternalTestToken;" in core
    assert "if (!showInternalTestToken) input.value = \"\";" in core
    assert "isInternalTestLoginMode() ? ($(\"li-internal-test-token\")?.value || \"\") : \"\"" in auth
    assert "if (internalTestToken) loginPayload.internal_test_token = internalTestToken;" in auth


def test_login_recovery_uses_human_facing_verification_wording():
    index = (ROOT / "public" / "index.html").read_text(encoding="utf-8")
    auth = (ROOT / "public" / "js" / "40-auth-users.js").read_text(encoding="utf-8")

    assert "寄送重設密碼驗證碼" in index
    assert "寄送 Email 驗證碼" in index
    assert "重設密碼 token" not in index
    assert "Email 驗證 token" not in index
    assert "無法取得 CSRF token" not in auth
    assert "安全驗證狀態失效" in auth
