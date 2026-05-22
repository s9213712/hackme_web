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

## Current Baseline

Generated with the RC1 scanner on 2026-05-22:

| Metric | Count |
|---|---:|
| Total findings | 47 |
| `allowed_internal_primitive` | 28 |
| `test_helper` | 8 |
| `blocker_product_bypass` | 11 |
| Direct official wallet balance mutation outside core | 0 |

The 11 blocker findings are the RC1 cleanup queue. They must be migrated,
runtime-blocked, or deleted before the release gate can pass.

## Product Value-Flow Inventory

| Domain | Current Touchpoint | RC1 Status | Required RC1 Handling |
|---|---|---|---|
| Bug reports / contribution reward | `routes/bug_reports.py` | blocker | Route through `RewardDistributionFacade` or an approved grant facade. |
| ComfyUI billing | `routes/comfyui_sections/billing_helpers.py` | blocker | Route through service-fee reserve / capture / release / batch burn. |
| Economy spend API | `routes/economy.py` | blocker | Route through approved service-spend facade, not direct `spend_points`. |
| Storage purchase | `routes/files.py` | blocker | Route through service-fee reserve / capture / release / refund. |
| Games daily/score rewards | `routes/games.py` | blocker | Route through `RewardDistributionFacade`. |
| Video boost / tips / creator credit / platform fee | `services/media/videos.py` | blocker | Route through service-fee or reward/transfer facades; no private `_record_transaction`. |
| Trading chain-funded order bridge | `services/trading/engine.py` | blocker | Route through `ExchangeFundService` / approved trading wallet facade preserving freeze/unfreeze semantics. |
| PointsChain core ledger writer | `services/points_chain/service.py` | allowed | Internal append-only primitive. |
| Wallet facade compensation | `services/points_chain/wallet_facade.py` | allowed | Internal facade primitive; product callers must enter via facade methods. |
| Validation scripts | `scripts/**` | test helper | Kept inventoried but outside runtime product accounting. |
| Tests | `tests/**` | test helper | Test fixtures and regression coverage. |

## Current Blocker Findings

| Classification | Kind | Symbol | File | Line | RC1 Decision |
|---|---|---|---|---:|---|
| `blocker_product_bypass` | ledger_service_call | `record_transaction` | `routes/bug_reports.py` | 137 | Migrate contribution reward behind approved reward facade. |
| `blocker_product_bypass` | ledger_service_call | `spend_points` | `routes/comfyui_sections/billing_helpers.py` | 88 | Migrate ComfyUI charge behind service-fee facade. |
| `blocker_product_bypass` | ledger_service_call | `spend_points` | `routes/economy.py` | 694 | Migrate public spend endpoint behind service-spend facade. |
| `blocker_product_bypass` | ledger_service_call | `spend_points` | `routes/files.py` | 2285 | Migrate storage purchase behind reserve/release facade. |
| `blocker_product_bypass` | ledger_service_call | `record_transaction` | `routes/games.py` | 1146 | Migrate game daily reward behind approved reward facade. |
| `blocker_product_bypass` | ledger_service_call | `record_transaction` | `routes/games.py` | 1222 | Migrate game score reward behind approved reward facade. |
| `blocker_product_bypass` | ledger_service_call | `_record_transaction` | `services/media/videos.py` | 1310 | Migrate video boost debit behind approved service-fee facade. |
| `blocker_product_bypass` | ledger_service_call | `_record_transaction` | `services/media/videos.py` | 1699 | Migrate video tip payer debit behind approved transfer/service-fee facade. |
| `blocker_product_bypass` | ledger_service_call | `_record_transaction` | `services/media/videos.py` | 1713 | Migrate video creator credit behind approved reward/transfer facade. |
| `blocker_product_bypass` | ledger_service_call | `_record_transaction` | `services/media/videos.py` | 1730 | Migrate video platform fee behind burn settlement facade. |
| `blocker_product_bypass` | ledger_service_call | `_record_transaction` | `services/trading/engine.py` | 2046 | Migrate trading ledger bridge behind approved exchange fund facade. |

## RC1 Guardrails

- Product code must not call `record_transaction(...)` directly.
- Product code must not call `_record_transaction(...)` directly.
- Product code must not directly mutate `points_wallets` balances or frozen
  columns.
- Product code must not treat derived wallet cache as financial truth.
- Product code must enter through approved facades for service fees, rewards,
  transfers, exchange fund movement, Treasury movement, or burn settlement.
- Any new blocker finding from the scanner is a release blocker.
