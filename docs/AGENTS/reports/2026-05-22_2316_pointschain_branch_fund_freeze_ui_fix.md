# PointsChain Branch Fund / Freeze UI Fix

## Findings Fixed

| Severity | Finding | Fix |
|---|---|---|
| P1 | Recovery branch only seeded user balances, so official/PROMO/EXCHANGE/BURN funds could become zero on the canonical branch while the closed-loop formula still balanced. | Recovery branch activation now carries branch-scoped system funds from the parent branch, with ancestor fallback for branches created before the fix. |
| P2 | Explorer showed `凍結 0 點` for a governance-frozen scam address, which confused amount freeze with governance freeze. | Explorer and wallet management now show `金額凍結` separately from `治理凍結 / 短期審核凍結` and risk labels. |
| P2 | The private-chain abnormal recovery card looked like a direct root repair tool. | Card is now positioned as `Emergency / Recovery Console`; copy states it handles verify/safe mode/backup recovery only and cannot directly mutate balances or ledger history. |

## Live Runtime

- Runtime: `/tmp/hackme_web_isolated_54343/hackme_web`
- URL: `https://127.0.0.1:54343`
- Canonical branch after repair: `pcbranch:c16a3ca7-7746-438d-8689-0b11019ec1f5`
- Economy health after repair: `green`, reasons `ok`
- Supply equation gap after repair: `0`
- `pc11045c920fd3d9f6a891c2850a33d58588ab08a892e1ce8fc`: `confirmed_scam`, governance freeze active, `points_frozen=0` as expected.

## Verification

- `python3 -m py_compile ...` passed.
- `node --check public/js/55-economy.js` passed.
- `pytest -q tests/points/test_governance_branch.py ...` passed: 33 tests.
- `python3 scripts/qa/points_chain_release_gate.py --skip-live` passed.
- `python3 scripts/testing/pointschain_governance_dispute_probe.py --base-url https://127.0.0.1:54343 ...` passed.
