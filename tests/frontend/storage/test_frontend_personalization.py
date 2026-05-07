from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]


def test_personal_appearance_editor_and_routes_are_wired():
    index_html = (ROOT / "public" / "index.html").read_text(encoding="utf-8")
    core_js = (ROOT / "public" / "js" / "00-core.js").read_text(encoding="utf-8")
    auth_js = (ROOT / "public" / "js" / "40-auth-users.js").read_text(encoding="utf-8")
    public_py = (ROOT / "routes" / "public.py").read_text(encoding="utf-8")
    admin_js = (ROOT / "public" / "js" / "50-admin.js").read_text(encoding="utf-8")

    assert "/js/40-auth-users.js?v=20260503-appearance-reset" in index_html
    assert 'id="edit-user-appearance-section" style="display:none;"' in index_html
    assert 'id="edit-user-appearance-preset"' in index_html
    assert 'id="edit-user-appearance-reset"' in index_html
    assert '視窗底部的「恢復全站預設」' in index_html
    assert 'id="edit-user-appearance-status"' in index_html
    assert 'id="edit-user-site-radius-px"' in index_html
    assert 'id="edit-user-site-font-scale"' in index_html
    assert 'id="edit-user-site-content-width"' in index_html
    assert 'id="edit-user-site-font-family"' in index_html
    assert 'id="edit-user-site-background-style"' in index_html
    assert 'id="edit-user-site-panel-style"' in index_html
    assert 'id="edit-user-site-sidebar-width"' in index_html
    assert 'id="s-site-radius-px"' in index_html
    assert 'id="s-site-font-scale"' in index_html
    assert 'id="s-site-content-width"' in index_html
    assert 'id="s-site-font-family"' in index_html
    assert 'id="s-site-background-style"' in index_html
    assert 'id="s-site-panel-style"' in index_html
    assert 'id="s-site-sidebar-width"' in index_html
    assert 'id="s-feature-personalization-enabled"' in index_html
    assert "let globalSiteConfig = {};" in core_js
    assert "let userSiteAppearanceConfig = {};" in core_js
    assert 'const SITE_FONT_FAMILY_MAP = {' in core_js
    assert 'const SITE_SIDEBAR_WIDTH_MAP = {' in core_js
    assert 'function clearUserAppearanceConfig()' in core_js
    assert 'applySiteConfig(json.appearance_settings, { scope: "user" })' in core_js
    assert 'const USER_APPEARANCE_PRESETS = {' in auth_js
    assert 'function userAppearanceFeatureEnabled()' in auth_js
    assert 'function setUserAppearanceEditorDisabled(disabled)' in auth_js
    assert 'if (resetBtn) resetBtn.style.display = "none";' in auth_js
    assert 'if (resetBtn) resetBtn.disabled = !enabled;' in auth_js
    assert 'function saveUserAppearanceSettings()' in auth_js
    assert 'API + "/me/appearance"' in auth_js
    assert 'function updateUserAppearanceEditorVisibility()' in auth_js
    assert '@app.route("/api/me/appearance", methods=["GET", "PUT", "DELETE"])' in public_py
    assert 'require_csrf_safe = deps["require_csrf_safe"]' in public_py
    assert 'get_profile_appearance(conn, ctx["id"])' in public_py
    assert '"require_csrf_safe": require_csrf_safe,' in (ROOT / "server.py").read_text(encoding="utf-8")
    assert 'if ($("s-site-radius-px")) $("s-site-radius-px").value = String(s.site_radius_px || 12);' in admin_js
    assert 'if ($("s-site-font-family")) $("s-site-font-family").value = s.site_font_family || "system";' in admin_js
