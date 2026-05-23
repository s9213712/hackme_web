# PointsChain Destructive Stress / Performance QA

## Findings

1. Medium: direct Flask dev server returns controlled 503 backpressure at 48-way GET concurrency.
   - Evidence: `/tmp/hackme_web_isolated_54343/hackme_web/runtime/reports/security/stress_destructive_20260522/stress_20260522T061805Z.md`
   - Result: 1200 requests, 1107 HTTP 200, 93 HTTP 503, 0 transport failures, 0 hard 500; approx 94.01 RPS, p95 933.07 ms, p99 1309.86 ms.
   - Impact: process did not crash, but user-facing traffic can receive 503 under aggressive concurrency on the direct dev runner. Production/perf QA should use the gunicorn runner before treating this as final capacity.

## Fixed During This Pass

- Root transaction management now sweeps proved pending transactions beyond the current page limit before rendering the list.
  - Previous destructive run with more than 100 pending transfers left 23 proved requests pending until explorer search touched each hash.
  - Fix: `PointsLedgerService.list_wallet_transactions()` now calls a root-only batch finalizer before fetching the current page and reports `batch_*` summary counts.
  - Regression: `python3 -m pytest -q tests/points/test_points_explorer.py` passed, including the new 15-pending / `limit=5` sweep test.

- Destructive stress tooling now validates fee-market monotonicity against `congestion_ratio`, not raw pending count alone, and accelerates a pending transaction as its actual sender.
  - Regression: owner acceleration returned HTTP 200 in live stress.

## Live Results

- Runtime: existing `/tmp/hackme_web_isolated_54343/hackme_web`, same port `https://127.0.0.1:54343`, restarted in place after copying changed files. Current server PID at report time: `853943`.
- Destructive chain/trading artifact: `/tmp/hackme_web_isolated_54343/hackme_web/runtime/reports/security/points_chain_destructive_stress_20260522_1524_after_sweep_fix.json`
- Playwright artifact: `/tmp/hackme_web_isolated_54343/hackme_web/runtime/reports/security/points_chain_post_stress_playwright_20260522_1526_after_sweep_fix.json`

Destructive live pass:
- 12 accounts, 12 official grants, 125 wallet transfers, 10 trading limit buys, duplicate UUID replay, overspend burst, owner acceleration, margin exhaustion probe, root seal/verify.
- `wallet_transfer`: 125/125 HTTP 200.
- `overspend_transfer`: 2 accepted into pending, 10 rejected with HTTP 409; no negative-balance finding.
- `accelerate_pending`: HTTP 200.
- `prefix_confirmed=140`, `prefix_pending=0`, `prefix_failed=0`.
- `explorer_finalized_transfers.attempted=0`, proving root transaction management batch sweep handled the over-limit pending set.
- Duplicate request UUID groups: 0. Duplicate active wallet address groups: 0.
- Fee ledgers with burn metadata: 716.
- Chain verify: 2673 ledger entries, 20 sealed blocks, 0 unsealed entries, 3034 audit events, 307 wallets.

Fee / congestion behavior:
- Idle: congestion `0.0`, suggested priority fee `20`, suggested total `21`, zero-fee ETA `120-180s`.
- Pending grants: congestion `0.24`, suggested priority fee `39`, suggested total `42`, zero-fee ETA `163-245s`.
- Transfer burst: congestion `1.0`, suggested priority fee `100`, suggested total `110`, zero-fee ETA `300-450s`.
- After seal: congestion `0.588`, suggested priority fee `67`, suggested total `73`, zero-fee ETA `226-339s`.
- Suggested fee consistently cut ETA versus zero-fee estimate in these samples.

Playwright post-stress:
- Root login with default `root/root`: OK, no forced password change.
- Root PointsChain UI: chain status visible and complete, wallet management visible, transaction management visible.
- Root APIs: wallet, transactions, root report, fee estimate all HTTP 200.
- Member `admin/admin`: wallet, transactions, notifications all HTTP 200.
- Browser console/page errors: 0.

## Commands

- `python3 -m py_compile services/points_chain/service.py scripts/testing/points_chain_destructive_stress.py scripts/testing/points_chain_post_stress_playwright.py`
- `python3 -m pytest -q tests/points/test_points_explorer.py`
- `python3 scripts/security/pentest/stress_test.py --target https://127.0.0.1:54343 --mode count --requests 1200 --concurrency 48 --paths /,/api/version,/api/site-config,/api/captcha/challenge,/api/points/explorer/fee-estimate?fee_points=1 --timeout 8 --out /tmp/hackme_web_isolated_54343/hackme_web/runtime/reports/security/stress_destructive_20260522 --i-own-this-target`
- `python3 scripts/testing/points_chain_destructive_stress.py --base-url https://127.0.0.1:54343 --runtime-root /tmp/hackme_web_isolated_54343/hackme_web --out /tmp/hackme_web_isolated_54343/hackme_web/runtime/reports/security/points_chain_destructive_stress_20260522_1524_after_sweep_fix.json --root-password root --accounts 12 --grant-points 5000 --transfer-ops 125 --trading-ops 10 --concurrency 20 --timeout 20`
- `python3 scripts/testing/points_chain_post_stress_playwright.py --base-url https://127.0.0.1:54343 --out /tmp/hackme_web_isolated_54343/hackme_web/runtime/reports/security/points_chain_post_stress_playwright_20260522_1526_after_sweep_fix.json --root-password root --member-username admin --member-password admin`
