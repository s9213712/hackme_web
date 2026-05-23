# 2026-05-23 09:25 Auto Heuristic Debug

## Findings

### Fixed - Isolated default-password bypass alias was ignored

Live probes on the preserved 54343 runtime showed `test/test` and `root/root` still triggered the forced password-change overlay when the server was started directly with `HTML_LEARNING_ALLOW_DEFAULT_PASSWORDS=1`. This blocked the governance Playwright probe and prevented the address dispute API probe from reaching root review.

Fix:

- `services/server/request_guards.py` now accepts `HTML_LEARNING_ALLOW_DEFAULT_PASSWORDS=1` as a dev/isolated alias.
- The bypass is limited to `dev_ready`, `internal_test`, `test`, and `superweak`.
- Production/preprod remain blocked, and security-enabled dev runs still enforce password change.
- Added regression coverage in `tests/platform/test_feature_flags.py`.

Evidence:

- Before fix: `pointschain_rc1_release_gate_heuristic_54343.json` failed on `user-edit-overlay` intercepting the economy tab.
- Before fix: `pointschain_dispute_api_probe_heuristic_54343.json` returned password-change messages instead of running dispute review.
- After fix: `artifacts/qa/pointschain_rc1_release_gate_heuristic_54343_after_fix.json` passed.
- After fix: `artifacts/qa/pointschain_dispute_api_probe_heuristic_54343_after_fix_root.json` passed.

### Fixed - Frontend economy test pinned an obsolete cache-bust string

`tests/frontend/trading/test_frontend_economy.py` still required `/js/55-economy.js?v=20260523-governance-wallet-ui`, while the current frontend uses `/js/55-economy.js?v=20260523-chain-branch-tree`. The test already checked for cache-busting generically earlier, so the exact-version assertion was stale.

Fix:

- Changed the assertion to require `/js/55-economy.js?v=` instead of one fixed version.

## Coverage

- `python3 -m py_compile services/server/request_guards.py` passed.
- `pytest -q tests/platform/test_feature_flags.py tests/security/gates/test_flask_hardening.py tests/security/gates/test_security_defaults.py` passed.
- `pytest -q tests/points/test_points_chain.py tests/points/test_governance_branch.py tests/points/test_points_explorer.py tests/points/test_wallet_identity.py` passed.
- `pytest -q tests/frontend/community/test_frontend_governance.py tests/frontend/trading/test_frontend_economy.py tests/security/auth/test_access_controls.py tests/security/auth/test_auth_csrf_safe.py` passed.
- `scripts/qa/points_chain_release_gate.py` on 54343 passed.
- `scripts/testing/pointschain_dispute_api_probe.py` on 54343 passed.
- `scripts/testing/points_chain_modularity_probe.py` on 54343 passed and restored feature flags.
- `scripts/security/pentest/functional_permission_pentest.py --core-only` on 54343 passed: 87 passed / 0 failed.
- `scripts/testing/points_chain_destructive_stress.py` on 54344 passed with 20 accounts, 100 transfers, 60 trading ops, 10-way concurrency.
- `scripts/testing/points_chain_post_stress_playwright.py` on 54344 passed with no browser errors.

## Stress Notes

- Destructive stress produced no negative balances, duplicate active wallet address groups, duplicate request UUID groups, or chain verify errors.
- Fee market responded to congestion: idle -> busy -> congested, with base fee and suggested priority fee increasing.
- 54344 sealed block 2 after stress: 288 ledger entries sealed, chain verify passed.
- 54343 root report still verifies: 5,817 ledger entries, 56 sealed blocks, 48 unsealed entries, branch tree node count 9.

## Runtime State

- Preserved runtimes were reused; no new tmp runtime tree was created.
- Synced `services/server/request_guards.py` into:
  - `/tmp/hackme_web_isolated_54343/hackme_web`
  - `/tmp/hackme_web_isolated_54344/hackme_web`
- Live servers left running:
  - 54343 PID 2220299
  - 54344 PID 2220492
