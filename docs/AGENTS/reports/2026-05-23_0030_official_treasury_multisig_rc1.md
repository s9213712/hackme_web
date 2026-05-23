# Official Treasury Multisig RC1

Date: 2026-05-23 00:30 CST

## Scope

Implemented the RC1 rule that multisig spending is an official treasury feature only. General user multisig remains hidden/preview and receive-only.

## Implemented

- Added wallet identity fields:
  - `wallet_scope`: `user`, `official_treasury`, `system_reserve`, `exchange_fund`
  - `spend_capability`: `enabled`, `receive_only`, `disabled`
- Existing and newly created user multisig policy wallets are exposed as `user_multisig_preview` and forced to `spend_capability=receive_only`.
- User multisig wallets may receive and appear in Explorer / wallet lists, but backend spend paths reject them:
  - wallet transfer
  - wallet creation fee source
  - service fee source
- Official treasury governance proposals now expose `official_treasury_multisig` policy metadata.
- Added manager+ API:
  - `GET /api/admin/points/governance/treasury-signer-center`
- Added governance UI block:
  - `官方財庫多簽 Treasury Signer Center`
  - official wallet balance/address
  - signer role / weight / device / wallet address
  - threshold and weight threshold
  - pending/signable treasury proposals
  - canonical branch and readiness context
- Removed the general user `建立多簽錢包` frontend action.
- Updated RC1 wallet / API docs to state: RC1 only supports official treasury spendable multisig.

## Verified

Local tests:
- `python3 -m py_compile services/points_chain/wallet_identity.py services/points_chain/service.py routes/economy.py tests/points/test_wallet_identity.py tests/points/test_governance_branch.py tests/regressions/test_security_issue_regressions.py`
- `node --check public/js/55-economy.js`
- `pytest -q tests/points/test_wallet_identity.py` -> pass, 13 tests
- `pytest -q tests/points/test_governance_branch.py::test_official_treasury_requires_multisig_after_governance_passes tests/points/test_governance_branch.py::test_revoked_treasury_signer_signature_stops_counting tests/points/test_governance_branch.py::test_multisig_and_voter_snapshot_ignore_new_manager_after_proposal_creation` -> pass, 3 tests
- `pytest -q tests/regressions/test_security_issue_regressions.py` -> pass, 39 tests

Isolated runtime:
- Preserved `/tmp/hackme_web_isolated_54343/hackme_web`
- Restarted same port `54343`, PID `1582517`
- `pwdx 1582517` -> `/tmp/hackme_web_isolated_54343/hackme_web`
- `GET /api/version` -> 200
- Root login with `root/root` did not require password change
- `GET /api/admin/points/governance/treasury-signer-center` -> `ok=true`, `wallet_type=official_treasury_multisig`, `wallet_scope=official_treasury`
- Live HTML no longer contains `economy-wallet-create-multisig`; it contains `官方財庫多簽 Treasury Signer Center`

## Notes

- General-user spendable multisig remains post-RC1/deferred. Building it safely requires a real user-facing signing protocol, signer lifecycle, recovery, and abuse handling.
- Official treasury execution still requires proposal pass, timelock, payload hash verification, and signer threshold readiness.
