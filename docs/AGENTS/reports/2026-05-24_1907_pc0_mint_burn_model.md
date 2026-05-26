# 2026-05-24 19:07 PC0 Mint/Burn Model QA

Scope: PointsChain pc0/pc1 dual-rail cleanup after correcting the model that MINT/BURN are system-special chain accounting addresses, not official pc0 wallets.

## Findings

No open P0 finding remains in the targeted slice.

## Fixed / Verified

- `pc0` remains the platform-custodial internal ledger namespace.
- MINT now uses `mint000...000`; BURN now uses `000...000`, with legacy `pc0...000` still recognized only for replay compatibility.
- `pc0 -> burn` now uses `internal_system_burn`, `network_fee_points=0`, and appends replayable burn accounting.
- Economy closed-loop report now exposes `system_burn_sink_balance`, `system_mint_unissued_balance`, `pc0_platform_internal_fund_balance`, and the formula `system_burn_sink + pc0_platform_funds + holder_circulating + system_mint_unissued = max_supply`.
- Trading auto-repairs legacy test/user accounts missing an official pc0 hot wallet before exchange-only operations.
- Explorer pending-transfer tests now use `pc0 -> pc1` withdrawal bridge behavior instead of the obsolete `pc0 -> pc0 pending` assumption.

## Commands

- `python3 -m py_compile services/points_chain/wallet_identity.py services/points_chain/schema.py services/points_chain/service.py routes/economy.py routes/public.py services/trading/engine.py`
- `node --check public/js/55-economy.js`
- `node --check public/js/56-trading.js`
- `python3 -m py_compile scripts/testing/pointschain_real_incident_attack_probe.py`
- `pytest -q tests/points/test_wallet_identity.py tests/points/test_points_chain.py tests/points/test_points_explorer.py tests/trading/core/test_trading_engine.py`

Result: all targeted checks passed.

## Follow-Up Inventory

- Cold-wallet service payment still has the old signed reserve/batch compatibility rail. It should be rewritten as a true cold-chain approval/payment flow or explicitly disabled until supported.
- Release/capacity scripts that assert specific pytest node ids need review whenever renamed tests are used; `pointschain_real_incident_attack_probe.py` was updated for the renamed pending transfer test.
- Broader browser/capacity scripts should be redesigned around pc0 internal transfers, deposit-address bridge credits, withdrawal bridge locks, and system-special MINT/BURN addresses before being used as RC1 gate evidence.

## 2026-05-24 Wallet UI / Legacy Batch Residue Update

No active "accumulate 100 then batch on-chain" service-fee path remains in the targeted UI/API slice. Remaining `service_fee_reserve` references are legacy audit/read compatibility or negative frontend assertions.

Fixed / verified:

- Wallet management no longer exposes a standalone chain-transfer card. Each wallet row now has `轉入` / `轉出`.
- pc0 receive flow shows both the pc0 inner address and the exact linked bridge pc1 deposit address.
- pc1/cold source to pc0 destination is blocked in the frontend before submit; backend already rejects pc0 as a chain-reachable destination.
- Favorite addresses are stored account-scoped in localStorage and filtered by transfer mode, so pc1 -> pc0 cannot be selected.
- Explorer wallet cards label pc0 addresses as `Inner Address`.
- `/api/admin/users` now returns manager/root-visible `official_hot_wallet_address`, live balance/frozen/pending values, and `official_hot_wallet_deposit_address`; legacy members on the current page are repaired with a pc0 wallet and deposit address when possible.
- `points_service_fee_payment` is now the service-fee signature action; `points_service_fee_reserve` is old audit compatibility only.

Commands:

- `python3 -m py_compile services/points_chain/wallet_identity.py services/points_chain/schema.py services/points_chain/service.py routes/economy.py routes/public.py routes/users.py services/trading/engine.py`
- `node --check public/js/55-economy.js`
- `node --check public/js/10-users.js`
- `pytest -q tests/frontend/trading/test_frontend_economy.py::test_root_points_page_is_chain_operations_console tests/frontend/test_points_chain_dispute_frontend.py tests/points/test_points_explorer.py tests/points/test_wallet_identity.py tests/points/test_points_chain.py tests/account/sessions/test_account_sessions.py tests/points/test_governance_branch.py::test_official_treasury_signer_center_reports_service_fee_income tests/points/test_governance_branch.py::test_service_fee_charge_is_branch_scoped_and_old_branch_charge_cannot_replay -q`

Live `:5000` verification:

- Restarted isolated runtime at `/tmp/hackme_web_pc0_5000_wallet_ui`, URL `https://127.0.0.1:5000`, accounts `root/root admin/admin test/test`.
- API smoke: `/api/admin/users` returned pc0 + bridge pc1 for root/admin/test.
- API smoke: test wallet onboarding returned pc0 + bridge pc1.
- API smoke: Explorer search for test pc0 returned `address_type=inner_address`.
- Playwright smoke: wallet row shows `轉入` / `轉出`; pc0 receive panel shows linked bridge pc1 wording; Explorer displays `Inner Address`.

Residual risk:

- Full `tests/points/test_governance_branch.py` still contains several old assumptions that pc0-to-pc0 transfers are pending chain transfers with fees. Those tests need a separate pc0-era rewrite around immediate internal transfers, withdrawal bridge locks, and fee-free inner ledger settlement.
