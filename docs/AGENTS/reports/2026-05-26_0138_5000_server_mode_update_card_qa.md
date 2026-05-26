# 2026-05-26 01:38 5000 Server Mode / Update Card QA

## Findings

No confirmed regressions in this round.

## Changes Verified

- `:5000` was restarted from `/tmp/hackme_web_accept_20260526_server_mode_prelaunch_update_card/hackme_web`.
- The production gate / launch check panel is attached to the Server Mode page and appears when the target mode dropdown is changed to `production`, before saving.
- Switching the dropdown back to `dev_ready` hides the launch check panel.
- The hidden System Management launch-check tab remains hidden.
- GitHub update UI is now a System Management / Health version check card.
- The frontend no longer exposes an online update apply button or `APPLY_UNVERIFIED_UPDATE` confirmation field.
- `/api/root/server-update/apply` returns HTTP 410 with a disabled message.

## Commands

- `node --check public/js/50-admin.js`
- `node --check public/js/51-admin-server-mode-launch-check.js`
- `node --check public/js/90-bootstrap.js`
- `python3 -m py_compile routes/system_admin.py routes/system_admin_sections/security_routes.py`
- `python3 -m pytest tests/frontend/admin/test_frontend_security_center_layout.py tests/platform/test_server_update_feature.py -q`
- Playwright root UI check against `https://127.0.0.1:5000`
- `python3 scripts/testing/system_stress_probe.py --base-url https://127.0.0.1:5000 --logical-users 8 --ops 120 --concurrency 8 --session-pool 4 --session-mode login ...`

## Stress Result

- `ok=true`, `degraded=false`
- `server_busy=0`, hard failure rate `0.0`
- Overall latency: p95 `135.556 ms`, p99 `375.497 ms`, max `960.231 ms`
- Resource peak: CPU `24.94%`, monitored RSS `439.33 MB`
- Server log showed expected local HTTPS self-signed certificate warnings from browser/curl tooling, but no application traceback in the sampled tail.
