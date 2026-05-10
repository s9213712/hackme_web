from pathlib import Path


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
    assert "RUN_DEEP_PLAYWRIGHT: \"0\"" in text
    assert "03b.Comfyui" in text


def test_playwright_qa_workflow_is_installed_in_github_actions():
    workflow = ROOT / ".github" / "workflows" / "playwright-qa.yml"
    text = workflow.read_text(encoding="utf-8")

    assert "name: playwright-qa" in text
    assert "python -m playwright install --with-deps chromium" in text
    assert "bash scripts/testing/run_playwright_acceptance.sh" in text
    assert "RUN_DEEP_PLAYWRIGHT: \"0\"" in text
    assert "03b.Comfyui" in text


def test_comfyui_workflow_editor_can_download_preset_json():
    html = (ROOT / "public" / "comfyui-workflow-editor.html").read_text(encoding="utf-8")
    js = (ROOT / "public" / "js" / "comfyui-workflow-editor.js").read_text(encoding="utf-8")

    assert 'id="downloadJsonBtn"' in html
    assert "function downloadJson()" in js
    assert "workflowExportFileName()" in js
    assert 'downloadJsonBtn")?.addEventListener("click", downloadJson)' in js
