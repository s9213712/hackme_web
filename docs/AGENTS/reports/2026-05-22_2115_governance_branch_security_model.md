# PointsChain Governance Branch Security Model

## Scope

Implemented and re-tested targeted RC1 governance / branch attack hardening:

- Public proposal creation is now trusted/vip or manager+ only.
- Rollback/recovery branch proposals are `EMERGENCY_SECURITY`, not public direct proposals.
- Official treasury proposals keep vote approval separate from multisig execution.
- Official multisig policy snapshots signer id, signer wallet, weight, device id, public-key fingerprint, threshold count, and threshold weight.
- Revoked signer wallets stop counting toward multisig readiness even if they signed before revocation.
- Proposal payloads expose execution bundle and readiness checks.
- Frontend separates Public Governance, Official Treasury, and Emergency Security entry points.
- Ledger and transfer requests now carry `chain_branch`.
- Recovery branch creates a new branch-isolated asset universe by replaying parent branch balances while excluding governance-approved incident tx refs.
- Old branch assets become read-only/non-canonical and cannot be spent in the new branch.
- Service-fee reserves, economy fund replay, transfer signing, and backup/restore are branch-aware.
- Cold-wallet and governance multisig signatures are bound to branch, proposal/request, action type, payload hash, and signer key id.
- Existing legacy economy bootstrap events with branchless request hashes remain idempotent after the branch-aware migration.
- Isolated/dev runtime can honor `HTML_LEARNING_DISABLE_DEFAULT_PASSWORD_POLICY=1` and `HACKME_DEV_DEFAULT_ACCOUNT_PASSWORDS=1` at request-guard time, not only at bootstrap time.

## Verification

Passed:

- `python3 -m py_compile services/points_chain/schema.py services/points_chain/service.py services/points_chain/economy_layer.py services/points_chain/wallet_identity.py routes/economy.py`
- `node --check public/js/55-economy.js`
- `python3 -m pytest -q tests/points/test_governance_branch.py` -> 21 passed
- `python3 -m pytest -q tests/points/test_points_chain.py tests/frontend/trading/test_frontend_economy.py` -> 48 passed
- `python3 -m pytest -q tests/points/test_wallet_identity.py tests/points/test_points_explorer.py -k "governance or official_wallet_grant or accelerate or fee_estimate or transfer or csrf"` -> 6 passed
- `python3 -m pytest -q tests/points/test_wallet_identity.py` -> 13 passed
- `python3 -m pytest -q tests/economy/test_economy_layer.py tests/platform/test_feature_flags.py -k "bootstrap or default_password_change_guard or feature_gate_maps_existing_modules"` -> 5 passed
- `python3 -m pytest -q tests/trading/core/test_trading_engine.py -k "exchange_fund or funding_pool or dashboard or reserve_pool"` -> 11 passed
- `python3 -m pytest -q tests/frontend/trading/test_frontend_economy.py` -> 9 passed
- `python3 scripts/testing/points_chain_post_stress_playwright.py --base-url https://127.0.0.1:54343 ...` -> pass
- `git diff --check` on touched files -> clean

Live Playwright artifact:

- `/tmp/hackme_web_isolated_54343/hackme_web/runtime/reports/qa/pointschain_governance_branch_attack_playwright.json`

Live server left running for inspection:

- `https://127.0.0.1:54343`
- PID at verification time: `1258873`

## Branch Drill

Added regression coverage simulating:

1. Official grant to victim wallet on `main`.
2. Compromised transfer from victim to attacker.
3. Same request id re-submit remains idempotent and does not duplicate ledger effects.
4. Different request id double-spend attempt is blocked because pending outgoing value is frozen.
5. Finality confirmation of stolen transfer.
6. Emergency recovery branch proposal and manager+ vote.
7. New canonical branch creation excluding the stolen tx hash.
8. Victim balance restored in new branch.
9. Attacker old-branch balance not recognized in new branch.
10. Replay of old request id rejected as non-canonical.
11. New post-fork transfer succeeds only on the new canonical branch.
12. Signed official-treasury proposal becomes non-ready when a signer wallet is revoked before execution.

## Attack Gate

The RC1 12-point attack gate is covered by `tests/points/test_governance_branch.py` plus targeted wallet/API/browser checks:

1. Signer compromise: revoked signer signatures stop counting; disabled signer cannot sign again.
2. Multisig snapshot: proposal voter/signer set, weights, and threshold stay frozen after proposal creation.
3. Cold wallet signature replay: signatures are rejected across branch, action, request, and signer key contexts.
4. API auth / CSRF negative tests: user cannot hit admin/emergency/veto/execute paths; CSRF failures are rejected; root cannot veto public governance.
5. Concurrency race: duplicate signer clicks count once, concurrent execution executes once, concurrent wallet sends do not double spend.
6. Official fund branch accounting: treasury/exchange fund balances are branch scoped; recovery branch does not reuse parent fund balances.
7. Service-fee reserve branch safety: old-branch reserves cannot settle after a new canonical branch is created.
8. Branch seed poisoning: recovery replay covers fund/user/unowned-address state and records excluded tx refs/rows.
9. Acceleration abuse: high priority fee cannot bypass pending freeze, finality, or branch canonical checks.
10. Snapshot/restore attack: restore verifies canonical pointer and governance audit chain; mismatch enters incident lockdown.
11. Governance spam/capture basic controls: trusted-only public proposals, duplicate detection, rate limit, and manager sponsor audit.
12. Cross-branch explorer confusion: old branch tx/wallet lookup is marked non-canonical and not shown as spendable balance.

## Live Issues Found And Fixed

- Isolated/default-password policy was only applied during bootstrap. Existing runtime rows with `must_change_password=1` still blocked PointsChain APIs. `services/server/request_guards.py` now honors the isolated disable flags and the dev default-account-password flag at request time.
- Root PointsChain report and trading dashboard returned 500 on older runtime data because branch-aware economy idempotency hashes did not accept pre-branch bootstrap hashes. `services/points_chain/economy_layer.py` now treats main-branch legacy branchless hashes as the same idempotent event.

## Remaining RC1 Work

- Dedicated signer rotation/revocation UI.
- Public observer governance explorer outside the economy tab.
- On-chain proposal deposit reserve/refund/burn settlement beyond current rate-limit / duplicate / sponsor controls.
- Parameter-specific execution handlers for protocol governance.
