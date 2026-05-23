# PointsChain RC1 Legacy Bypass Cleanup

Status: complete for the known RC1 blocker inventory.

## Result

- Before cleanup: `47` scanner findings, `11` `blocker_product_bypass`.
- After cleanup: `39` scanner findings, `0` `blocker_product_bypass`.
- Runtime product direct calls to `record_transaction(...)`, `_record_transaction(...)`, and `spend_points(...)` were removed from the scanner blocker set.
- Product flows now enter through `points_service.rc1_facade()`.

## Migrated Paths

| Product path | Before | After |
|---|---|---|
| Bug report reward | direct `record_transaction` | `grant_reward(...)` facade |
| ComfyUI billing | direct `spend_points` | `spend_service_fee(...)` facade |
| Economy spend endpoint | direct `spend_points` | `spend_service_fee(...)` facade |
| Storage upgrade purchase | direct `spend_points` | `spend_service_fee(...)` facade |
| Game weekly reward | direct `record_transaction` | `grant_reward(...)` facade |
| Game daily reward | direct `record_transaction` | `grant_reward(...)` facade |
| Video boost debit | private `_record_transaction` | `append_product_ledger_locked(...)` facade |
| Video tip payer debit | private `_record_transaction` | `append_product_ledger_locked(...)` facade |
| Video tip creator credit | private `_record_transaction` | `append_product_ledger_locked(...)` facade |
| Video tip platform fee | private `_record_transaction` | `append_product_ledger_locked(...)` facade |
| Trading ledger bridge | private `_record_transaction` | `append_product_ledger_locked(...)` facade |

## Verification

Commands run:

```bash
python3 -m py_compile services/points_chain/wallet_facade.py services/points_chain/service.py routes/bug_reports.py routes/comfyui_sections/billing_helpers.py routes/economy.py routes/files.py routes/games.py services/media/videos.py services/trading/engine.py
python3 scripts/security/gate/wallet_direct_call_inventory.py --json-out /tmp/pointschain_rc1_wallet_inventory_after_facade.json --md-out /tmp/pointschain_rc1_wallet_inventory_after_facade.md --fail-on-blocker
python3 -m pytest -q tests/static/test_wallet_direct_call_inventory.py tests/regressions/test_bug_reports.py tests/games/test_games.py tests/video/api/test_video_tips.py tests/video/api/test_video_management.py
python3 -m pytest -q tests/points/test_points_chain.py tests/points/test_wallet_facade_contract.py tests/points/test_points_explorer.py tests/points/test_wallet_identity.py
python3 -m pytest -q tests/trading/core/test_trading_engine.py tests/trading/core/test_trading_root_sitewide_api.py tests/storage/test_cloud_drive_attachments.py tests/frontend/trading/test_frontend_economy.py
git diff --check -- services/points_chain/wallet_facade.py services/points_chain/service.py routes/bug_reports.py routes/comfyui_sections/billing_helpers.py routes/economy.py routes/files.py routes/games.py services/media/videos.py services/trading/engine.py tests/regressions/test_bug_reports.py tests/games/test_games.py tests/comfyui/_integration_suite.py tests/video/api/test_video_management.py docs/architecture/BLOCKCHAIN_WALLET_VALUE_FLOW_INVENTORY.md docs/architecture/ECONOMY_LAYER_GUARDRAILS.md scripts/security/gate/wallet_direct_call_inventory.py tests/static/test_wallet_direct_call_inventory.py scripts/INDEX.md
```

Artifacts:

- `/tmp/pointschain_rc1_wallet_inventory_blockers.json`
- `/tmp/pointschain_rc1_wallet_inventory_after_facade.json`
- `/tmp/pointschain_rc1_wallet_inventory_after_facade.md`

## Remaining RC1 Risk

- This cleanup removes the static bypass blockers. It does not complete the
  later RC1 governance packages: MintGuard, TreasuryGuard, ExchangeFundPolicy,
  approval/timelock enforcement, release-gate automation, or production profile
  guardrails.
- `append_product_ledger_locked(...)` is intentionally narrow and should shrink
  further as product-specific facades mature.
