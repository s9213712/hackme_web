# Blockchain Wallet Value-Flow Inventory

This inventory is the PointsChain MVP RC1 static guardrail for wallet and ledger
write touchpoints.

The scanner is:

```bash
python3 scripts/security/gate/wallet_direct_call_inventory.py
```

Release-gate usage is:

```bash
python3 scripts/security/gate/wallet_direct_call_inventory.py --fail-on-blocker
```

`--fail-on-blocker` must exit successfully before RC1 can be accepted.

## RC1 Classification Rules

| Classification | Rule |
|---|---|
| `allowed_internal_primitive` | PointsChain core, approved internal facade, shadow/server-mode accounting, or schema/rebuild primitives that are not product runtime bypasses. |
| `approved_facade` | Product-facing Economy / PointsChain facade entrypoints approved for RC1. |
| `test_helper` | Tests and maintained validation/pentest/operator scripts outside runtime product accounting. |
| `migration_only` | Code retained only for migrations or reviewed non-product compatibility. |
| `deprecated_dead_path` | Dead runtime path kept temporarily but blocked from execution. |
| `blocker_product_bypass` | Runtime product code that directly calls ledger write APIs or mutates wallet balances instead of an approved facade. |

## Before / After

Before RC1 cleanup, generated with the RC1 scanner on 2026-05-22:

| Metric | Count |
|---|---:|
| Total findings | 47 |
| `allowed_internal_primitive` | 28 |
| `test_helper` | 8 |
| `blocker_product_bypass` | 11 |
| Direct official wallet balance mutation outside core | 0 |

After RC1 cleanup:

| Metric | Count |
|---|---:|
| Total findings | 39 |
| `allowed_internal_primitive` | 31 |
| `test_helper` | 8 |
| `blocker_product_bypass` | 0 |
| Direct official wallet balance mutation outside core | 0 |

The former 11 blocker findings were migrated behind `rc1_facade()` entrypoints.
`--fail-on-blocker` now passes.

## Product Value-Flow Inventory

| Domain | Current Touchpoint | RC1 Status | Required RC1 Handling |
|---|---|---|---|
| Bug reports / contribution reward | `routes/bug_reports.py` | migrated | Uses `points_service.rc1_facade().grant_reward(...)`. |
| ComfyUI billing | `routes/comfyui_sections/billing_helpers.py` | migrated | Uses `points_service.rc1_facade().spend_service_fee(...)`. |
| Economy spend API | `routes/economy.py` | migrated | Uses `points_service.rc1_facade().spend_service_fee(...)`. |
| Storage purchase | `routes/files.py` | migrated | Uses `points_service.rc1_facade().spend_service_fee(...)`. |
| Games daily/score rewards | `routes/games.py` | migrated | Uses `points_service.rc1_facade().grant_reward(...)`. |
| Video boost / tips / creator credit / platform fee | `services/media/videos.py` | migrated | Uses `points_service.rc1_facade().append_product_ledger_locked(...)`. |
| Trading chain-funded order bridge | `services/trading/engine.py` | migrated | Uses `points_service.rc1_facade().append_product_ledger_locked(...)` while preserving shadow-ledger routing. |
| PointsChain core ledger writer | `services/points_chain/service.py` | allowed | Internal append-only primitive. |
| Wallet facade compensation | `services/points_chain/wallet_facade.py` | allowed | Internal facade primitive; product callers must enter via facade methods. |
| Validation scripts | `scripts/**` | test helper | Kept inventoried but outside runtime product accounting. |
| Tests | `tests/**` | test helper | Test fixtures and regression coverage. |

## Cleaned Blocker Findings

| Former Classification | Kind | Symbol | File | Line | RC1 Handling |
|---|---|---|---|---:|---|
| `blocker_product_bypass` | ledger_service_call | `record_transaction` | `routes/bug_reports.py` | 137 | `grant_reward(...)` facade. |
| `blocker_product_bypass` | ledger_service_call | `spend_points` | `routes/comfyui_sections/billing_helpers.py` | 88 | `spend_service_fee(...)` facade. |
| `blocker_product_bypass` | ledger_service_call | `spend_points` | `routes/economy.py` | 694 | `spend_service_fee(...)` facade. |
| `blocker_product_bypass` | ledger_service_call | `spend_points` | `routes/files.py` | 2285 | `spend_service_fee(...)` facade. |
| `blocker_product_bypass` | ledger_service_call | `record_transaction` | `routes/games.py` | 1146 | `grant_reward(...)` facade. |
| `blocker_product_bypass` | ledger_service_call | `record_transaction` | `routes/games.py` | 1222 | `grant_reward(...)` facade. |
| `blocker_product_bypass` | ledger_service_call | `_record_transaction` | `services/media/videos.py` | 1310 | `append_product_ledger_locked(...)` facade. |
| `blocker_product_bypass` | ledger_service_call | `_record_transaction` | `services/media/videos.py` | 1699 | `append_product_ledger_locked(...)` facade. |
| `blocker_product_bypass` | ledger_service_call | `_record_transaction` | `services/media/videos.py` | 1713 | `append_product_ledger_locked(...)` facade. |
| `blocker_product_bypass` | ledger_service_call | `_record_transaction` | `services/media/videos.py` | 1730 | `append_product_ledger_locked(...)` facade. |
| `blocker_product_bypass` | ledger_service_call | `_record_transaction` | `services/trading/engine.py` | 2046 | `append_product_ledger_locked(...)` facade. |

## RC1 Guardrails

- Product code must not call `record_transaction(...)` directly.
- Product code must not call `_record_transaction(...)` directly.
- Product code must not directly mutate `points_wallets` balances or frozen
  columns.
- Product code must not treat derived wallet cache as financial truth.
- Product code must enter through approved facades for service fees, rewards,
  transfers, exchange fund movement, Treasury movement, or burn settlement.
- Any new blocker finding from the scanner is a release blocker.
