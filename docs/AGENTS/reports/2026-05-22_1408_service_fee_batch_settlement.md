# Service Fee Batch Settlement QA

Date: 2026-05-22 14:08 Asia/Taipei

## Findings

- No blocker found in the new service-fee settlement path.
- Remaining migration risk: wallet direct-call inventory still reports 11 `migrate` product paths. `spend_points()` callers now enter the reserve / batch layer, but video tips, games rewards, bug bounty, and one trading path still contain direct `record_transaction()` / `_record_transaction()` calls that must converge on the wallet facade before this area is considered fully clean.

## Verified Behavior

- `spend_points()` now creates `service_fee_reserve:<item_key>` freeze ledgers first. Available balance drops immediately and frozen balance rises, preventing double-spend before batch settlement.
- When reserved service fees for the same user wallet reach 100 points, the service appends `service_fee_batch_unfreeze` and `service_fee_batch_debit`; final debit flows to BURN.
- Self-custody / imported cold wallet service-fee reserves require a local private-key signature over `points_service_fee_reserve`.
- Frontend `spendEconomyItem()` now signs cold-wallet service fees, sends `request_uuid` + `signature`, and shows a visible success message instead of silent completion.
- Isolated runtime `https://127.0.0.1:54343` was reused. Changed files were copied into `/tmp/hackme_web_isolated_54343/hackme_web`; server restarted as PID `712202`.

## Evidence

- Pytest: `tests/points/test_points_chain.py`, `tests/points/test_wallet_identity.py`, `tests/points/test_points_explorer.py`, frontend economy static test, video tips, wallet direct-call inventory test, and ComfyUI generation tests passed: 80 tests.
- Compile / hygiene: `python -m py_compile ...` passed; `git diff --check` passed.
- Live API:
  - First service fee returned `ledger_direction=freeze`, `charge_status=reserved`, `reserved_total_points=1`, wallet frozen `1`.
  - After funding and a 100 point service fee, batch settlement created `service_fee_batch_unfreeze` + `service_fee_batch_debit`, settled `101` points, wallet frozen returned to `0`, debit destination was BURN.
- Live Playwright:
  - Login with `test/test` succeeded without forced password change in the isolated runtime.
  - Frontend service-fee payment showed: `服務費已凍結：1 點 · 累積 1/100 點後批次鏈上扣款`.
  - Console errors: none.
- Root verify on isolated runtime returned `ok=true`.

## Remaining Work

- Migrate the 11 remaining direct product ledger paths reported in `/tmp/wallet_direct_call_inventory_service_fee.md`.
- Product UIs that charge service fees should pass the selected payment wallet explicitly; self-custody wallets need the same local-signature prompt used by the generic economy helper.
