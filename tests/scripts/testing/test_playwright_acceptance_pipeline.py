from pathlib import Path

from scripts.testing.playwright_platform_health_check import ignored_browser_error


ROOT = Path(__file__).resolve().parents[3]


def test_playwright_acceptance_runner_uses_isolated_runtime_and_expected_checks():
    script = ROOT / "scripts" / "testing" / "run_playwright_acceptance.sh"
    text = script.read_text(encoding="utf-8")

    assert "playwright_comfyui_workflow_builder_check.py" in text
    assert "playwright_platform_health_check.py" in text
    assert "playwright_deep_site_check.py" in text
    assert "/tmp/hackme_web_playwright_acceptance_" in text
    assert "--runtime-root \"${RUNTIME_BASE}/platform\"" in text
    assert "RUN_DEEP_PLAYWRIGHT" in text
    assert "HTML_LEARNING_PORT=5000" not in text


def test_playwright_qa_workflow_template_installs_browser_and_runs_runner():
    workflow = ROOT / "scripts" / "testing" / "playwright-qa.workflow.yml"
    text = workflow.read_text(encoding="utf-8")

    assert "python -m playwright install --with-deps chromium" in text
    assert "bash scripts/testing/run_playwright_acceptance.sh" in text
    assert "workflow_dispatch:" in text
    assert "schedule:" in text
    assert "github.event.inputs.run_deep_playwright" in text
    assert "03b.Comfyui" in text


def test_playwright_qa_workflow_is_installed_in_github_actions():
    workflow = ROOT / ".github" / "workflows" / "playwright-qa.yml"
    text = workflow.read_text(encoding="utf-8")

    assert "name: playwright-qa" in text
    assert "python -m playwright install --with-deps chromium" in text
    assert "bash scripts/testing/run_playwright_acceptance.sh" in text
    assert "workflow_dispatch:" in text
    assert "schedule:" in text
    assert "github.event.inputs.run_deep_playwright" in text
    assert "03b.Comfyui" in text


def test_platform_health_filters_expected_offline_browser_http_failures():
    assert ignored_browser_error("503 https://127.0.0.1:40341/api/admin/trading/report")
    assert ignored_browser_error("503 https://127.0.0.1:40341/api/trading/btc-signal?market=BTC%2FUSDT")
    assert ignored_browser_error("Failed to load resource: the server responded with a status of 503")
    assert not ignored_browser_error("500 https://127.0.0.1:40341/api/storage/files")


def test_comfyui_workflow_editor_exports_comfyui_and_project_json_formats():
    html = (ROOT / "public" / "comfyui-workflow-editor.html").read_text(encoding="utf-8")
    js = (ROOT / "public" / "js" / "comfyui-workflow-editor.js").read_text(encoding="utf-8")

    assert 'id="downloadJsonBtn"' in html
    assert 'id="downloadApiJsonBtn"' in html
    assert 'id="downloadPresetJsonBtn"' in html
    assert "下載 ComfyUI Workflow" in html
    assert "下載本站 Preset" in html
    assert "function downloadJson()" in js
    assert "function exportComfyUiWorkflowGraph()" in js
    assert "function exportComfyUiApiPrompt()" in js
    assert "function uiWidgetValues(node)" in js
    assert '"randomize"' in js
    assert "function downloadApiJson()" in js
    assert "function downloadPresetJson()" in js
    assert "workflowExportFileName()" in js
    assert "workflowExportFileName(\".api-prompt\")" in js
    assert "workflowExportFileName(\".hackme-preset\")" in js
    assert "ComfyUI 不能直接載入" in js
    assert 'downloadJsonBtn")?.addEventListener("click", downloadJson)' in js
    assert 'downloadApiJsonBtn")?.addEventListener("click", downloadApiJson)' in js
    assert 'downloadPresetJsonBtn")?.addEventListener("click", downloadPresetJson)' in js


def test_deep_playwright_shared_video_uses_unlock_share_session():
    script = (ROOT / "scripts" / "testing" / "playwright_deep_site_check.py").read_text(encoding="utf-8")

    assert "share_session_id" in script
    assert 'share_session_query = f"?share_session={share_session_id}"' in script
    assert 'f"/api/videos/shared/{token}/playback{share_session_query}"' in script


def test_platform_health_auth_wait_and_screenshots_are_ci_tolerant():
    deep_script = (ROOT / "scripts" / "testing" / "playwright_deep_site_check.py").read_text(encoding="utf-8")
    platform_script = (ROOT / "scripts" / "testing" / "playwright_platform_health_check.py").read_text(encoding="utf-8")

    assert "def wait_for_auth_app(page, *, timeout: int = 30000)" in deep_script
    assert "screenshot capture failed" in platform_script
    assert "wait_for_auth_app(page)" in platform_script


def test_documented_playwright_health_entrypoints_exist_and_delegate():
    testing_dir = ROOT / "scripts" / "testing"
    full_site = (testing_dir / "playwright_full_site_check.py").read_text(encoding="utf-8")
    visual = (testing_dir / "playwright_visual_health_check.py").read_text(encoding="utf-8")
    mobile = (testing_dir / "playwright_mobile_viewports.py").read_text(encoding="utf-8")

    assert "playwright_deep_site_check.py" in full_site
    assert "--max-chess-human-moves" in full_site
    assert "playwright_comfyui_workflow_builder_check.py" in visual
    assert "playwright_platform_health_check.py" in visual
    assert "playwright_platform_health_check.py" in mobile
