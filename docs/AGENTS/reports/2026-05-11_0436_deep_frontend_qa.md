# Deep Frontend QA Report - 2026-05-11 04:36 CST

## Scope

- Target repo: `/home/s92137/hackme_web`
- Isolated dev runtime: `/tmp/hackme_web_qa_20260511_042100/hackme_web`
- Dev server: `https://127.0.0.1:51174`
- Platform health runtime: `/tmp/hackme_web_platform_qa_20260511_043300`
- Browser tool: Python Playwright `1.59.0`, Chromium headless

## Commands Run

```bash
./test_for_develop.sh --port 51174 --run-root /tmp/hackme_web_qa_20260511_042100
python3 scripts/testing/playwright_platform_health_check.py --runtime-root /tmp/hackme_web_platform_qa_20260511_043300
python3 scripts/testing/playwright_comfyui_workflow_builder_check.py
```

Additional exploratory Playwright pass drove the running dev server through login, root navigation, normal-user navigation, desktop/mobile screenshots, console collection, HTTP error collection, and visible control size checks.

## Verdict

Overall verdict: **PASS with UX/accessibility follow-ups**.

No release-blocking frontend regression was found in this pass. Existing platform acceptance checks passed for Job Center, Notification Center, Share Management, Trading Asset Overview, and key mobile platform views. The standalone ComfyUI workflow builder also passed render, drag, wire, delete-edge, JSON import, unknown-node preservation, and mobile overflow checks.

## Confirmed Passes

- `playwright_platform_health_check.py`: PASS.
- `playwright_comfyui_workflow_builder_check.py`: PASS.
- Root login via UI on the `test_for_develop.sh` server: PASS.
- Root module navigation smoke for Jobs, Shares, Trading, ComfyUI, Economy, Server, Accounts: PASS.
- Normal user login via UI: PASS.
- Normal user does not show root-only `tab-module-server` or `tab-module-accounts`: PASS.
- No Playwright request failures were observed during the exploratory pass.

## Findings

### QA-20260511-001 - Medium - Mobile and dense admin controls have small click/touch targets

The platform check and exploratory pass both found visible controls below the 44px touch target guideline.

Examples:

- `self-edit-btn`: about `34x38` on mobile.
- `notification-toggle`: about `34x34` on mobile.
- `bug-report-open-btn`: about `34x38` on mobile.
- `logout-btn`: about `34x34` on mobile.
- `sidebar-toggle`: about `34x34` on mobile.
- Account management row actions such as `封鎖`, `修改`, `刪除`: around `39px` wide in the root account table.

Risk: destructive or high-frequency controls are easy to miss or mis-tap, especially account-management row actions.

Suggested fix: set a minimum interactive box of `44px` for icon buttons and row action buttons, while keeping the visual icon/text compact if needed.

Evidence:

- `/tmp/hackme_web_platform_qa_20260511_043300/reports/qa/playwright_platform_health_check_20260510T203246Z.md`
- `/tmp/hackme_web_qa_20260511_042100/exploratory/exploratory_report.json`
- `/tmp/hackme_web_qa_20260511_042100/exploratory/02_root_after_login.png`
- `/tmp/hackme_web_qa_20260511_042100/exploratory/03_landing_mobile.png`

### QA-20260511-002 - Low - Expected auth/ComfyUI offline probes pollute browser console as errors

The exploratory browser console recorded:

- `401 UNAUTHORIZED` from `/api/me` on the unauthenticated landing page.
- `503 SERVICE UNAVAILABLE` from `/api/comfyui/models` when opening AI 產圖 while ComfyUI is offline.

The UI handles these states visibly, so this is not a functional failure. The downside is QA/debug noise: expected offline or unauthenticated states look like browser errors and can hide real frontend failures.

Suggested fix: route expected unauthenticated/offline probes through UI state handling that avoids noisy console errors where possible, or tag them in the QA harness as expected responses.

Evidence:

- `/tmp/hackme_web_qa_20260511_042100/exploratory/exploratory_report.json`

### QA-20260511-003 - Low - Normal-user first screen can become icon-only navigation

After normal-user login in the exploratory pass, the visible sidebar was an icon rail with no textual nav labels. Root-only controls were not visible, so this is not an authorization issue.

Risk: discoverability is weak for non-admin users unless they already know every icon. This is more noticeable because the page also shows a large success banner, pushing the actual workspace context down.

Suggested fix: ensure the default normal-user desktop state exposes labels, or add persistent tooltips/accessible labels and an obvious expand affordance.

Evidence:

- `/tmp/hackme_web_qa_20260511_042100/exploratory/04_test_user_after_login.png`

## Notes

- The first `test_for_develop.sh` attempt inside the sandbox failed to bind a socket with `PermissionError: [Errno 1] Operation not permitted`; rerunning with local port binding permission succeeded.
- The working tree already had unrelated modified files before this report was added. This QA pass only adds this report.
- Temporary evidence is under `/tmp`; copy or archive it before cleaning `/tmp` if long-term binary evidence is needed.

## Fix Status - 2026-05-11

- `QA-20260511-001`: Partially fixed in `8b2061b`. App action bar buttons and sidebar toggle were raised to a 44px touch target baseline. Dense account table row actions still need a separate UX pass if strict 44px row controls are required.
- `QA-20260511-002`: Partially fixed in `8b2061b`. `/api/comfyui/models` now returns a 200 degraded/offline payload when ComfyUI is unavailable. The unauthenticated `/api/me` 401 remains an expected auth probe and should be treated as QA noise unless product wants a separate unauthenticated status endpoint.
- `QA-20260511-003`: Not fixed. Normal-user icon-only sidebar discoverability remains a UX follow-up.

Current status: **PARTIAL**, not all findings in this report are fully closed.
