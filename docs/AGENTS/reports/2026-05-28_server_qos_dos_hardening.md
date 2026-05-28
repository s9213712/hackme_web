# Server QoS / DoS Hardening

Date: 2026-05-28

## Scope

- Server QoS classification and traffic observability.
- App-level edge burst protection for auth, root/admin, and upload entry
  points.
- Root backpressure dashboard visibility.
- Documentation for DB/QoS/reverse-proxy separation.

## Changes

- Added `classify_request_qos()` in the backpressure layer and return
  `X-Hackme-QoS-Class` on responses so probes and reverse proxies can distinguish
  health, static, auth, management, heavy, API read/write, and page traffic.
- Added a process-local `EdgeBurstGuard` before heavier route/session work for:
  CSRF/login/register/CAPTCHA/password reset, root/admin APIs, and upload or
  remote-download start paths.
- Edge-guard rejects return `429 edge_rate_limited`, `Retry-After`,
  `X-Hackme-Edge-Guard`, and `X-Hackme-Backpressure: edge_guard`.
- Backpressure traffic snapshots now count `edge_guard` rejections. The root
  capacity chart and status line show edge guard state and rejected bursts.
- Documented the boundary: app edge guard is a last-line safety net; production
  still needs Nginx or equivalent TLS, request-size, connection, and first-layer
  rate limiting.

## Verification

- `python3 -m py_compile services/server/backpressure.py tests/security/gates/test_flask_hardening.py tests/frontend/admin/test_frontend_security_center_layout.py`
- `node --check public/js/50-admin.js public/js/90-bootstrap.js`
- `pytest -q tests/security/gates/test_flask_hardening.py tests/frontend/admin/test_frontend_security_center_layout.py`
- `pytest -q tests/platform/test_release_policy.py tests/scripts/prepush/test_prepush_v2.py`
- `git diff --check`

## Next Queue

- Add a live HTTP burst probe that verifies `429 edge_rate_limited` under a
  lowered test limit while health/static routes remain available.
- Add Nginx template snippets that map `X-Hackme-QoS-Class` to separate access
  logs and rate-limit zones.
- Add cross-worker/shared edge guard support through Redis or another external
  low-latency store for multi-host production deployments.
