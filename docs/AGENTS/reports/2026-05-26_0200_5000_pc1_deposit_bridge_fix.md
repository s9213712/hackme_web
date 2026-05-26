# 2026-05-26 02:00 5000 pc1 Deposit Bridge Fix

## Scope

- Investigated live `:5000` incident where `admin` cold wallet sent `500` points to `test` platform deposit address, but `test` pc0 hot wallet was not credited.
- Applied backend fix to repo and live tmp instance:
  `/tmp/hackme_web_accept_20260526_server_mode_prelaunch_update_card/hackme_web`.

## Root Cause

- Confirmed cold-chain transfer to an active `points_chain_deposit_addresses.address` was treated as a normal unowned `pc1` destination.
- No `points_chain_bridge_events` row was created.
- No pc0 `deposit_credit` ledger was created.
- No user notification was created.
- Economy flow still counted the deposit address balance as bridge/external circulation.

## Fix

- Detect active deposit addresses during wallet transfer submission/finalization.
- On confirmed/proved cold-chain transfer to a deposit address:
  - Create or reuse one `points_chain_bridge_events` deposit row.
  - Credit the mapped user's pc0 official hot wallet exactly once.
  - Link `transfer_in_ledger_uuid` back to the deposit credit ledger.
  - Rewrite `recipient_user_id` and `destination_unowned` for the confirmed transfer.
  - Notify the recipient.
  - Append `deposit_bridge_credit` economy event from the deposit address to pc0 so closed-loop flow totals no longer double-count the deposit vault.
- Added reconciliation sweep for already-confirmed deposit-address transfers.

## Live Result

- `df509557ee4cfb7fe8ef64d5125a89996d6a8161716eb1a16a5ba110f96fc890`
  - Bridge event status: `credited`
  - Amount: `500`
  - Recipient: `test`
  - `test` pc0 hot wallet balance: `700`
  - Notification created for `test`
- Closed-loop flow:
  - `hot_to_cold_confirmed_points`: `1000`
  - `deposit_credited_points`: `500`
  - `economy_external_to_hot_points`: `500`
  - `current_cold_chain_or_bridge_external_points`: `499`
  - `economy_flow_reconciliation_gap_points`: `0`

## Verification

- `python3 -m py_compile services/points_chain/wallet_identity.py services/points_chain/schema.py services/points_chain/service.py routes/economy.py routes/public.py services/trading/engine.py`
- `python3 -m pytest tests/points/test_points_chain.py tests/points/test_points_explorer.py -q`
- Live gunicorn graceful reload completed and `:5000` remains listening.
