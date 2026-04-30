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
