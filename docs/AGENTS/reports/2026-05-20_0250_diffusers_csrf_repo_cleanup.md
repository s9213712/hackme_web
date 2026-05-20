# Diffusers / CSRF / Repo Cleanup Report

Date: 2026-05-20

Scope:

- Diffusers progress wording, frontend progress log visibility, and repo
  inspect CSRF behavior.
- Authenticated CSRF false-alert audit for multi-tab and concurrent requests.
- Repo cache/runtime cleanup and orphan script/test registration review.

Findings and actions:

- Removed repo-local cache artifacts (`__pycache__`, `.pytest_cache`,
  `.mypy_cache`, `.ruff_cache`) outside `.git`; no root `runtime/` directory
  exists in this workspace.
- Confirmed no untracked repo files after cleanup, so no orphan generated files
  needed deletion.
- Confirmed maintained QA/security script registration is covered by
  `scripts/prepush/checks/scripts_index_check.py`; no new script entrypoints
  were added in this change.
- Checked GitHub Actions through the public API. The latest visible branch
  failure was an older scheduled `playwright-qa` run on commit
  `a41b4b0f3add3dac2fe274da8267aa5643b2ae8b`, where the workflow builder smoke
  assumed catalog nodes were visible even though the toolbox is now collapsed by
  category.
- Confirmed the repository default branch is `03.Points`, but workflow push
  triggers only covered `main` and/or the older `03b.Comfyui` branch. Updated
  `.github/workflows/ci.yml`, `playwright-qa.yml`, and
  `security-secrets-scan.yml` so pushes to `03.Points` run CI directly.
- After enabling push CI, `security-secrets-scan` failed because
  `scripts/security/gate/scan_plaintext_secrets.py` could not import the
  project `scripts` package as a direct CI entrypoint. Added the repo-root
  `sys.path` prologue used by other maintained scripts.
- Once the entrypoint ran, the plaintext scanner flagged historical fake
  fixtures and dynamic request values. Updated the scanner's dynamic assignment
  exemptions and the documented allowlist for tests, QA scripts, pentest
  scripts, and explicit tutorial examples.
- Updated `scripts/testing/playwright_comfyui_workflow_builder_check.py` to
  reveal catalog and fixed tools through search before clicking, preserving the
  collapsed toolbox behavior.
- Updated release-visible docs and troubleshooting notes for Diffusers progress
  and authenticated CSRF token rotation behavior.

Focused validation:

- `python3 -m pytest tests/security/auth/test_auth_csrf_safe.py tests/frontend/comfyui/test_comfyui_diffusers_repo_ui.py tests/frontend/comfyui/test_comfyui_idle_retry.py tests/comfyui/test_diffusers_client.py tests/comfyui/generation/test_comfyui_generation.py::test_comfyui_diffusers_mode_lists_repo_and_generates_without_comfyui_nodes tests/comfyui/generation/test_comfyui_generation.py::test_comfyui_diffusers_stale_progress_does_not_say_comfyui_backend tests/frontend/test_platform_centers_frontend.py -q`
- `python3 scripts/testing/playwright_comfyui_workflow_builder_check.py`
- `python3 scripts/security/gate/scan_plaintext_secrets.py --fail-on high --report-json /tmp/hackme_secrets_scan.json --report-md /tmp/hackme_secrets_scan.md`
- `python3 -m pytest tests/scripts/prepush/test_prepush_v2.py -q`
- `python3 -m compileall services/users/auth.py services/comfyui/diffusers_client.py routes/comfyui.py routes/comfyui_sections/runtime_routes.py`
- `git diff --check`
