# Playwright Frontend Smoke

- Date: 2026-05-11 09:00 Asia/Taipei
- Branch: `03b.Comfyui`
- Scope: frontend Playwright smoke for silent failures, console/page errors, ComfyUI workflow UI, and offline ComfyUI guard behavior.

## Findings

- No confirmed frontend product bugs found.
- The first deep run exposed a Playwright script race in `auth_registration_login_flow`: the script read `#reg-msg` after a fixed 1.6s sleep, before the registration success message was guaranteed to render. The app flow itself succeeded: pending login returned 401, root approval succeeded, and approved login returned 200.
- Fixed the QA script to wait for a non-empty registration message and include `reg_msg` in the JSON report.

## Verification

- `timeout 180s python3 scripts/testing/playwright_comfyui_workflow_builder_check.py`
  - PASS: ComfyUI visual workflow builder rendered, dragged nodes, wired/deleted edges, imported JSON, and passed mobile layout.
- `timeout 180s python3 scripts/testing/playwright_deep_site_check.py --max-chess-human-moves 0`
  - First run: FAIL only on the registration-message timing race.
  - Report: `/tmp/hackme_web_playwright_deep_20260511T005646Z/reports/qa/playwright_deep_site_check_20260511T005646Z.md`
- `python3 -m py_compile scripts/testing/playwright_deep_site_check.py`
  - PASS.
- `timeout 180s python3 scripts/testing/playwright_deep_site_check.py --max-chess-human-moves 0`
  - PASS.
  - Report: `/tmp/hackme_web_playwright_deep_20260511T005916Z/reports/qa/playwright_deep_site_check_20260511T005916Z.md`
  - `browser_errors`: none.

## Coverage Notes

- ComfyUI live backend smoke was intentionally not run because live ComfyUI is currently unavailable.
- ComfyUI offline checks passed: editor login guard, visual editor, main-page visual workflow button, workflow CRUD, and Civitai missing-key guard.
- Chess code was not edited. The deep script still visited games routes in an isolated `/tmp` runtime with `--max-chess-human-moves 0`.
