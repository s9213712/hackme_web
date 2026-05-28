# Admin Performance / Mobile Operations Optimization

Date: 2026-05-28

## Scope

- Root server-management browser polling.
- System health / platform stats page load behavior.
- Mobile layout for admin, health, resource, and wide table sections.

## Changes

- Added a root management visibility guard in `public/js/50-admin.js`.
  Server-output, backpressure-traffic, and system-resource pollers now stop when
  the browser tab is hidden or unloaded, and resume only for the currently active
  root management tab.
- Added an idle scheduling helper for non-critical management reads. Opening the
  health page still loads the primary health summary immediately, while platform
  stats and update-status reads are deferred to browser idle time.
- Added active-tab guards to server-output, security-center, health,
  environment, platform-stats, backpressure, and system-resource refresh paths so
  stale timers or delayed idle callbacks cannot refresh hidden management pages.
- Hardened mobile CSS for root operations: admin panels, health rows, resource
  gauges, environment key/value panels, process commands, and wide table wrappers
  now collapse or scroll without page-wide overflow.

## Verification

- `node --check public/js/50-admin.js public/js/90-bootstrap.js`
- `pytest -q tests/frontend/admin/test_frontend_security_center_layout.py tests/frontend/admin/test_frontend_health_center.py tests/frontend/layout/test_mobile_responsive_layout.py tests/frontend/layout/test_frontend_button_sizing.py tests/frontend/layout/test_ui_polish.py`
- `pytest -q tests/platform/test_release_policy.py tests/scripts/prepush/test_prepush_v2.py`
- `git diff --check`

## Next Queue

- Add a Playwright mobile root-operations smoke that opens health, capacity, and
  environment pages at a phone viewport and checks for horizontal page overflow.
- Add lightweight frontend timing marks for management page first-summary and
  secondary-chart completion, then surface slow admin reads in the health center.
