# 2026-05-26 15:34 - 5000 root wallet and governance probe QA

## Findings

### Fixed: root login/onboarding exposed a member official hot wallet

Root is a system/operator account and should manage official/system wallets, not appear as a member hot-wallet holder. The live `:5000` login payload still exposed an existing root `official_hot` wallet and deposit address through `wallet_onboarding`.

Fix:

- Added `system_account_wallet_onboarding_status()` to sanitize root/system onboarding payloads.
- Root `/api/login` wallet onboarding now returns no member wallet, no member deposit address, no allowed member wallet creation modes.
- Root `/api/points/wallet` and `/api/points/deposit-address` now return explicit system-account placeholders instead of a member hot wallet.
- Root POST `/api/points/wallet/onboarding` now returns `403 system_account_no_member_wallet`.
- Existing append-only wallet rows were not deleted; they are no longer exposed as root member wallet state.

Verification:

- Root login: `wallet_onboarding.wallet=null`, `wallets=[]`, `deposit_address=""`, `allowed_modes=[]`, `system_account=true`.
- `/api/points/wallet`: `system_account=true`, no active wallet address.
- `/api/points/deposit-address`: no member deposit address.
- `/api/admin/users`: root still reports `official_hot_wallets=[]`.

### Fixed: governance/dispute Playwright probe used removed legacy UI selectors

`scripts/testing/pointschain_governance_dispute_probe.py` still expected the removed standalone public-governance creation panel and old treasury governance form. The probe now accepts the current UI split:

- public governance creation is no longer a standalone form.
- treasury creation has moved out of the governance page into official wallet management.
- if the old treasury form exists in a branch, the probe expects pc0 destination semantics instead of pc1.

## Validation

- `python3 -m py_compile services/points_chain/wallet_identity.py services/points_chain/__init__.py routes/public.py routes/economy.py`: passed.
- `python3 -m py_compile scripts/testing/pointschain_governance_dispute_probe.py`: passed.
- `pytest tests/points/test_wallet_identity.py::test_system_account_onboarding_status_hides_member_wallet_fields -q`: passed.
- `pointschain_governance_dispute_probe.py` against `https://127.0.0.1:5000`: passed.
- `points_chain_post_stress_playwright.py` against `https://127.0.0.1:5000`: passed, no browser errors.
- `chat_video_share_link_probe.py` against `https://127.0.0.1:5000`: passed.
- `pointschain_dispute_api_probe.py` as `admin/admin`: passed; dispute created, manager review generated rollback/risk/freeze proposals, provisional freeze active, no identity leak.
- `system_stress_probe.py` after reload: passed, no server_busy and no 5xx.

Stress summary after reload:

- 12 logical users, 96 requested ops, concurrency 8.
- Throughput `27.63 ops/s`.
- p50 `36.098ms`, p95 `74.509ms`, p99 `444.138ms`.
- hard failure rate `0`.
- server_busy rate `0`.

Artifacts:

- `/tmp/hackme_web_qa_5000_pointschain_poststress_after_root_wallet_fix.json`
- `/tmp/hackme_web_qa_5000_chat_video_share_link_after_root_wallet_fix.json`
- `/tmp/hackme_web_qa_5000_governance_dispute_probe_after_script_fix.json`
- `/tmp/hackme_web_qa_5000_dispute_api_probe_admin.json`
- `/tmp/hackme_web_qa_5000_stress_after_root_wallet_fix.json`

## Runtime

`:5000` was reloaded and left running:

- master PID `1279448`
- workers `1279506`, `1279507`, `1279526`, `1279527`

The large-video subtitle server on `:51475` was not stopped.
