from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_security_center_logs_have_non_overlapping_layout():
    index_html = (ROOT / "public" / "index.html").read_text(encoding="utf-8")
    admin_js = (ROOT / "public" / "js" / "50-admin.js").read_text(encoding="utf-8")
    css = (ROOT / "public" / "styles.css").read_text(encoding="utf-8")

    assert 'class="security-log-grid"' in index_html
    assert 'id="security-audit-entries" class="security-log-box"' in index_html
    assert 'id="security-server-log" class="security-log-box security-log-pre"' in index_html
    assert 'id="security-server-output" class="security-log-box security-log-pre"' in index_html
    assert 'class="security-log-row"' in admin_js
    assert ".security-log-grid" in css
    assert "grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));" in css
    assert ".security-log-box" in css
    assert "overflow-wrap: anywhere;" in css
    assert ".security-log-row" in css
    assert "grid-template-columns: auto auto minmax(0, .9fr) minmax(0, .7fr) minmax(0, 1.6fr);" in css


def test_saving_settings_preserves_current_admin_surface():
    admin_js = (ROOT / "public" / "js" / "50-admin.js").read_text(encoding="utf-8")
    save_body = admin_js.split("async function saveSettings()", 1)[1].split("async function loadServerEnv()", 1)[0]

    assert "setAuthState({" not in save_body
    assert "const activeModule = currentModuleTab;" in save_body
    assert "const activeServerTab = currentServerTab;" in save_body
    assert "const activeSettingsSection = currentSettingsSection;" in save_body
    assert "switchModuleTab(activeModule);" in save_body


def test_prelaunch_tests_include_stress_progress_and_logs():
    index_html = (ROOT / "public" / "index.html").read_text(encoding="utf-8")
    admin_js = (ROOT / "public" / "js" / "50-admin.js").read_text(encoding="utf-8")
    bootstrap_js = (ROOT / "public" / "js" / "90-bootstrap.js").read_text(encoding="utf-8")

    assert 'id="security-stress-start-btn"' in index_html
    assert 'id="security-stress-requests"' in index_html
    assert 'id="security-stress-concurrency"' in index_html
    assert "startSecurityStressTest" in admin_js
    assert 'API + "/root/security-tests/stress"' in admin_js
    assert "drive-progress-fill" in admin_js
    assert "job.log_tail" in admin_js
    assert "securityStressStart" in bootstrap_js
    assert 'securityTestMsg("滲透測試啟動中..."' in admin_js
    assert 'securityTestMsg("全功能測試啟動中..."' in admin_js
    assert 'securityTestMsg("壓力測試啟動中..."' in admin_js
    assert 'msg show ${ok ? "ok" : "err"}' in admin_js
    assert 'securityPentestStart.addEventListener("click", startSecurityPentest)' in bootstrap_js
    assert 'securityFunctionalStart.addEventListener("click", startSecurityFunctionalSmoke)' in bootstrap_js
    assert 'securityStressStart.addEventListener("click", startSecurityStressTest)' in bootstrap_js


def test_points_chain_auto_handle_lives_in_audit_area_and_integrity_buttons_are_single_bound():
    index_html = (ROOT / "public" / "index.html").read_text(encoding="utf-8")
    admin_js = (ROOT / "public" / "js" / "50-admin.js").read_text(encoding="utf-8")
    bootstrap_js = (ROOT / "public" / "js" / "90-bootstrap.js").read_text(encoding="utf-8")
    audit_section = index_html.split('id="sec-server-audit"', 1)[1].split('id="sec-server-security"', 1)[0]
    economy_recovery_section = index_html.split('id="economy-recovery-card"', 1)[1].split('id="economy-account-query-card"', 1)[0]

    assert 'id="economy-recovery-auto-handle-btn"' in audit_section
    assert 'id="economy-recovery-auto-handle-btn"' not in economy_recovery_section
    assert 'integrityBulkApprove.addEventListener("click", () => reviewSelectedIntegrityFindings("approve"))' in bootstrap_js
    assert 'igBulkApprove.addEventListener("click", () => reviewSelectedIntegrityFindings("approve"))' not in admin_js


def test_custom_security_profile_uses_form_controls_not_raw_json():
    index_html = (ROOT / "public" / "index.html").read_text(encoding="utf-8")
    admin_js = (ROOT / "public" / "js" / "50-admin.js").read_text(encoding="utf-8")
    profile_section = index_html.split("新增自定義設定檔", 1)[1].split('id="security-profile-save-btn"', 1)[0]
    save_body = admin_js.split("async function saveSecurityProfile()", 1)[1].split("function healthStatusColor", 1)[0]

    assert 'id="security-profile-settings-json"' not in profile_section
    assert 'id="security-profile-thresholds-json"' not in profile_section
    assert "settings JSON" not in profile_section
    assert "thresholds JSON" not in profile_section
    assert 'id="security-profile-ip-blocking-enabled"' in profile_section
    assert 'id="security-profile-security-pending-chat-reports-threshold"' in profile_section
    assert 'collectSecurityProfileDraft("security-profile")' in save_body
    assert "JSON.parse" not in save_body


def test_settings_area_uses_collapsible_groups_to_reduce_clutter():
    index_html = (ROOT / "public" / "index.html").read_text(encoding="utf-8")
    css = (ROOT / "public" / "styles.css").read_text(encoding="utf-8")
    server_settings = index_html.split('id="sec-server-settings"', 1)[1].split('id="sec-server-env"', 1)[0]
    security_center = index_html.split('id="sec-server-security"', 1)[1].split('id="sec-server-health"', 1)[0]

    assert server_settings.count('class="drive-collapsible-panel settings-collapse') >= 12
    assert security_center.count('class="drive-collapsible-panel settings-collapse') >= 5
    assert "Snapshot / Restore / Reset" in server_settings
    assert "危險區" in server_settings
    assert "上線前測試" in security_center
    assert "審計與伺服器輸出" in security_center
    assert ".settings-collapse" in css
    assert ".settings-collapse.danger-collapse" in css
