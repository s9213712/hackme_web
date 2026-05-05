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


def test_security_control_and_threshold_saves_show_visible_status():
    index_html = (ROOT / "public" / "index.html").read_text(encoding="utf-8")
    admin_js = (ROOT / "public" / "js" / "50-admin.js").read_text(encoding="utf-8")
    controls_body = admin_js.split("async function saveSecurityCenterControls()", 1)[1].split("async function saveSecurityThresholds()", 1)[0]
    thresholds_body = admin_js.split("async function saveSecurityThresholds()", 1)[1].split("async function applySecurityMode()", 1)[0]

    assert 'id="security-save-status"' in index_html
    assert "function setSecuritySaveStatus" in admin_js
    assert 'setSecuritySaveStatus("正在儲存安全開關..."' in controls_body
    assert 'setSecuritySaveStatus("正在儲存安全閾值..."' in thresholds_body
    assert "security-controls-msg" in controls_body
    assert "security-thresholds-msg" in thresholds_body
    assert "catch (err)" in controls_body
    assert "catch (err)" in thresholds_body
    assert "btn.disabled = true" in controls_body
    assert "btn.disabled = true" in thresholds_body


def test_server_update_ui_warns_and_requires_preview_then_apply():
    index_html = (ROOT / "public" / "index.html").read_text(encoding="utf-8")
    admin_js = (ROOT / "public" / "js" / "50-admin.js").read_text(encoding="utf-8")
    bootstrap_js = (ROOT / "public" / "js" / "90-bootstrap.js").read_text(encoding="utf-8")

    assert "GitHub 更新中心" in index_html
    assert 'id="server-update-branch-select"' in index_html
    assert 'id="server-update-preview-btn"' in index_html
    assert 'id="server-update-apply-btn"' in index_html
    assert 'id="server-update-diff"' in index_html
    assert "APPLY_UNVERIFIED_UPDATE" in index_html
    assert "loadServerUpdateStatus" in admin_js
    assert "previewServerUpdate" in admin_js
    assert "applyServerUpdate" in admin_js
    assert 'API + "/root/server-update/preview"' in admin_js
    assert 'API + "/root/server-update/apply"' in admin_js
    assert "此次更新未經驗證" in admin_js
    assert "serverUpdateRefresh.addEventListener" in bootstrap_js
    assert "serverUpdatePreview.addEventListener" in bootstrap_js
    assert "serverUpdateApply.addEventListener" in bootstrap_js


def test_launch_check_treats_production_profile_settings_as_auto_applied_not_manual_blockers():
    index_html = (ROOT / "public" / "index.html").read_text(encoding="utf-8")
    admin_js = (ROOT / "public" / "js" / "50-admin.js").read_text(encoding="utf-8")
    launch_body = admin_js.split("function launchCheckConditionList(sc, requirements) {", 1)[1].split("function jumpToAnchor", 1)[0]

    assert "production profile 的 HTTPS / audit chain / Integrity Guard / browser-only 等安全設定會在 mode switch 成功時自動套用" in index_html
    assert "不是</strong>你必須先手動打開的上線前檢查項目" in index_html
    assert "productionAutoSummary" in launch_body
    assert "上線前檢查可在非 production 執行；真正切換由 GO_LIVE 完成" in launch_body
    assert "這些安全設定會在切換到 production 時自動套用，不是上線前檢查的手動前置條件" in launch_body
    assert "production 必須開 Integrity Guard" not in launch_body
    assert "請先切到 dev_ready 再開上線檢查" not in launch_body


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
