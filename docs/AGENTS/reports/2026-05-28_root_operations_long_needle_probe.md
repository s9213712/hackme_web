# Root Operations Mobile Smoke and Long Needle Probe

Date: 2026-05-28

## Scope

- Root operations mobile smoke for Health, Capacity, and Environment pages.
- Frontend timing marks for management-page health observability.
- Nginx boundary rate-limit lane template for auth, management, upload, and
  static traffic.
- Economy, private-chain, and full-feature long needle simulation probe.

## Changes

- Added a Playwright root-operations smoke that opens the actual system Health,
  Capacity, and Environment tabs at 390x844, 768x1024, and 1366x768, then checks
  root/module/section/right-edge overflow.
- Added frontend timing marks for `first-summary` and `secondary-chart`; the
  health center now renders those browser-side timings in the frontend
  observability section.
- Hardened the mobile Capacity/backpressure form so long select labels and form
  controls can shrink without section-level horizontal overflow.
- Extended the Nginx example with separate `limit_req_zone` lanes for auth,
  management/root, upload/heavy-transfer, static assets, and generic API traffic.
- Added `scripts/testing/long_needle_simulation_probe.py` to run
  PointsChain/economy destructive stress and full-feature system stress in one
  isolated runtime.
- Fixed the long needle harness to enable all feature flags before full-feature
  stress and to locate isolated `.chain_seed` files under `secrets/`.
- Split system-stress latency into raw overall latency and ordinary latency so
  expected defensive operations such as bad-login probes do not pollute ordinary
  user-facing p95/p99.
- Fixed compact root transaction listing so it still performs a bounded
  proved-pending finality sweep. This removed the long-needle pending backlog
  found in external pc1 transfer and overspend scenarios.

## Verification

- `python3 scripts/testing/playwright_platform_health_check.py --runtime-root /tmp/hackme_web_root_ops_mobile_smoke2`
  - PASS; browser errors: none.
  - Mobile root operations Health/Capacity/Environment: no viewport overflow.
  - Health frontend timing observed `first-summary` and `secondary-chart`.
- `python3 scripts/testing/long_needle_simulation_probe.py --runtime-root /tmp/hackme_web_long_needle_quick3 --profile quick`
  - PASS; findings: none.
  - `economy_private_chain`: PASS, prefix pending `0`, direct pc0 transfers
    `24/24`, direct errors `0`.
  - `full_feature`: PASS, transport/5xx failures `0`, server-busy `0`.
- `pytest -q tests/frontend/admin/test_frontend_health_center.py tests/scripts/testing/test_playwright_acceptance_pipeline.py tests/scripts/deploy/test_nginx_template.py tests/scripts/testing/test_system_stress_probe.py tests/points/test_points_explorer.py`
- `node --check public/js/50-admin.js`
- `python3 -m py_compile scripts/testing/playwright_platform_health_check.py scripts/testing/long_needle_simulation_probe.py scripts/testing/points_chain_destructive_stress.py scripts/testing/system_stress_probe.py services/points_chain/service.py`
- `git diff --check`

## Next Queue

- Promote the long needle quick profile into a scheduled non-blocking QA job and
  keep medium/long profiles manual for larger hardware windows.
- Add a compact transaction-list metric for sweep duration and finalized count
  to the health center so pending-finality backlog becomes visible without
  reading the full ledger.
