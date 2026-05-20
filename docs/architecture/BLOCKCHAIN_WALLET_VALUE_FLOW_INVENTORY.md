# Blockchain Wallet Value-Flow Inventory

一句話說明：這是 `04.BLOCKCHAIN` Phase 0 第一個實作切片的全站錢包價值流盤點；它只列出現況與遷移分類，不改任何交易行為。

## Scope

- Branch: `04.BLOCKCHAIN`
- Phase: Phase 0 prework inventory
- Behavior changes: none
- Scanner: `scripts/security/gate/wallet_direct_call_inventory.py`
- Command:

```bash
python3 scripts/security/gate/wallet_direct_call_inventory.py \
  --json-out /tmp/wallet_inventory.json \
  --md-out /tmp/wallet_inventory.md
```

Phase 0 baseline scanner summary, excluding `tests/`:

| Classification | Count | Meaning |
|---|---:|---|
| `retain` | 31 | Core PointsChain implementation, shadow-mode isolation, or operator validation scripts; keep inventoried but do not migrate in Phase 0. |
| `migrate` | 14 | Product code directly calls PointsChain service APIs; migrate behind Wallet Service Facade in Phase 1+ after approval. |
| `unknown` | 0 | No current unclassified findings. |
| `blocker` | 0 | No non-core direct official `points_wallets` balance mutation found by the scanner. |

Phase 1 contract note: after adding the Wallet Service Facade skeleton, the scanner reports `47` findings with `33` retain and the same `14` migrate findings. The two new retain findings are the facade's internal append-only compensation calls inside `services/points_chain/wallet_facade.py`; no product flow has been migrated yet.

## Classification Rules

| Classification | Rule |
|---|---|
| `retain` | `services/points_chain/**`, `tests/**`, `scripts/**`, server-mode shadow-wallet code, and snapshot shadow-wallet code. |
| `migrate` | Runtime product code outside PointsChain core calling `_record_transaction`, `record_transaction`, `spend_points`, or `rollback_ledger`. |
| `unknown` | A finding the scanner cannot classify safely. |
| `blocker` | Non-core product code directly mutating official `points_wallets` balance or frozen columns. |

## Value-Flow Inventory

| Domain | Current Value Flow | Current Touchpoints | Classification | Phase 0 Notes |
|---|---|---|---|---|
| Account | Signup bonus, birthday gift, admin initial grant, admin weekly salary | `routes/public.py`, `routes/users.py`, `services/points_chain/service.py` | retain / migrate review | Award helpers live in PointsChain core; route callers should remain inventoried before facade design. |
| Community / Reports | Bug bounty and moderation / appeal corrections | `routes/bug_reports.py`, `routes/appeals.py` | migrate | Product routes call `record_transaction` / `rollback_ledger` directly; Phase 1 facade should absorb. |
| Storage | Cloud storage purchases and rollback on storage failure | `routes/files.py` | migrate | Uses `spend_points` and `rollback_ledger`; needs facade refund / rollback boundary later. |
| ComfyUI | Generation billing | `routes/comfyui_sections/billing_helpers.py` | migrate | Uses `spend_points`; Phase 1+ must introduce reserve / capture / release / refund, but not in Phase 0. |
| Video | Boost, tip debit, creator credit, platform fee | `services/media/videos.py` | migrate | Uses private `_record_transaction`; this is high-priority facade migration after Phase 0 approval. |
| Games | Daily / score reward writes | `routes/games.py` | migrate | Product route calls `record_transaction` directly; needs facade reward helper later. |
| Trading | Chain-funded order / settlement ledger writes | `services/trading/engine.py` | migrate | Uses private `_record_transaction`; migration must preserve trading freeze / unfreeze semantics. |
| Trading Shadow / Server Mode | Tester shadow wallet and shadow ledger | `services/trading/shadow.py`, `services/snapshots/**` | retain | Separate test/shadow accounting; not official `points_wallets` source of truth. |
| Root / Admin Economy | Points spend and rollback API surfaces | `routes/economy.py` | migrate | Existing API surface remains; Phase 1 facade should sit underneath or beside it. |
| Operator / Validation Scripts | Seed and validation ledger writes | `scripts/security/pentest/video_module_pentest.py`, `scripts/trading/validation/trading_exchange_validation.py` | retain | Kept as validation tooling; not product runtime behavior. |

## Direct Call Findings

The following table is produced by the Phase 0 scanner. It is the current review list for `_record_transaction`, `record_transaction`, `spend_points`, `rollback_ledger`, and direct wallet balance mutations.

| Classification | Kind | Symbol | File | Line | Phase 0 Decision |
|---|---|---|---|---:|---|
| migrate | ledger_service_call | `rollback_ledger` | `routes/appeals.py` | 434 | Migrate behind rollback facade after Phase 0. |
| migrate | ledger_service_call | `record_transaction` | `routes/bug_reports.py` | 137 | Migrate behind reward / bounty facade after Phase 0. |
| migrate | ledger_service_call | `spend_points` | `routes/comfyui_sections/billing_helpers.py` | 103 | Migrate behind reserve / capture flow after Phase 0. |
| migrate | ledger_service_call | `spend_points` | `routes/economy.py` | 345 | Migrate API implementation behind facade after Phase 0. |
| migrate | ledger_service_call | `rollback_ledger` | `routes/economy.py` | 777 | Migrate rollback API implementation behind facade after Phase 0. |
| migrate | ledger_service_call | `rollback_ledger` | `routes/files.py` | 832 | Migrate behind rollback facade after Phase 0. |
| migrate | ledger_service_call | `spend_points` | `routes/files.py` | 2285 | Migrate storage purchase flow after Phase 0. |
| migrate | ledger_service_call | `record_transaction` | `routes/games.py` | 1146 | Migrate game reward flow after Phase 0. |
| migrate | ledger_service_call | `record_transaction` | `routes/games.py` | 1222 | Migrate game score / quest reward flow after Phase 0. |
| retain | ledger_service_call | `_record_transaction` | `scripts/security/pentest/video_module_pentest.py` | 104 | Retain as validation tooling. |
| retain | ledger_service_call | `record_transaction` | `scripts/trading/validation/trading_exchange_validation.py` | 136 | Retain as validation tooling. |
| retain | ledger_service_call | `record_transaction` | `scripts/trading/validation/trading_exchange_validation.py` | 244 | Retain as validation tooling. |
| retain | ledger_service_call | `record_transaction` | `scripts/trading/validation/trading_exchange_validation.py` | 395 | Retain as validation tooling. |
| retain | ledger_service_call | `record_transaction` | `scripts/trading/validation/trading_exchange_validation.py` | 480 | Retain as validation tooling. |
| retain | ledger_service_call | `record_transaction` | `scripts/trading/validation/trading_exchange_validation.py` | 498 | Retain as validation tooling. |
| retain | ledger_service_call | `record_transaction` | `scripts/trading/validation/trading_exchange_validation.py` | 516 | Retain as validation tooling. |
| retain | ledger_service_call | `record_transaction` | `scripts/trading/validation/trading_exchange_validation.py` | 534 | Retain as validation tooling. |
| migrate | ledger_service_call | `_record_transaction` | `services/media/videos.py` | 1310 | Migrate video boost debit after Phase 0. |
| migrate | ledger_service_call | `_record_transaction` | `services/media/videos.py` | 1699 | Migrate video tip payer debit after Phase 0. |
| migrate | ledger_service_call | `_record_transaction` | `services/media/videos.py` | 1713 | Migrate video tip creator credit after Phase 0. |
| migrate | ledger_service_call | `_record_transaction` | `services/media/videos.py` | 1730 | Migrate video tip platform fee after Phase 0. |
| retain | direct_wallet_balance_mutation | `points_wallets` | `services/points_chain/schema.py` | 572 | Retain as PointsChain schema migration / wallet cache rebuild path. |
| retain | direct_wallet_balance_mutation | `points_wallets` | `services/points_chain/service.py` | 186 | Retain as PointsChain core wallet rebuild path. |
| retain | ledger_service_call | `record_transaction` | `services/points_chain/service.py` | 700 | Retain as PointsChain helper. |
| retain | ledger_service_call | `record_transaction` | `services/points_chain/service.py` | 716 | Retain as PointsChain helper. |
| retain | ledger_service_call | `record_transaction` | `services/points_chain/service.py` | 736 | Retain as PointsChain helper. |
| retain | ledger_service_call | `record_transaction` | `services/points_chain/service.py` | 751 | Retain as PointsChain helper. |
| retain | ledger_service_call | `record_transaction` | `services/points_chain/service.py` | 771 | Retain as PointsChain helper. |
| retain | ledger_service_call | `_record_transaction` | `services/points_chain/service.py` | 980 | Retain as PointsChain public wrapper implementation. |
| retain | ledger_service_call | `_record_transaction` | `services/points_chain/service.py` | 1026 | Retain as PointsChain sanction implementation. |
| retain | ledger_service_call | `_record_transaction` | `services/points_chain/service.py` | 1044 | Retain as PointsChain sanction implementation. |
| retain | ledger_service_call | `_record_transaction` | `services/points_chain/service.py` | 1131 | Retain as PointsChain pending reward implementation. |
| retain | ledger_service_call | `_record_transaction` | `services/points_chain/service.py` | 1202 | Retain as PointsChain spend implementation. |
| retain | ledger_service_call | `record_transaction` | `services/points_chain/service.py` | 1240 | Retain as PointsChain admin adjustment wrapper. |
| retain | ledger_service_call | `_record_transaction` | `services/points_chain/service.py` | 1325 | Retain as PointsChain admin adjustment implementation. |
| retain | ledger_service_call | `_record_transaction` | `services/points_chain/service.py` | 1379 | Retain as PointsChain rollback implementation. |
| retain | direct_wallet_balance_mutation | `test_shadow_wallets` | `services/snapshots/schema.py` | 863 | Retain as shadow-wallet migration. |
| retain | direct_wallet_balance_mutation | `test_shadow_wallets` | `services/snapshots/schema.py` | 874 | Retain as shadow-wallet migration. |
| retain | direct_wallet_balance_mutation | `test_shadow_wallets` | `services/snapshots/schema.py` | 885 | Retain as shadow-wallet migration. |
| retain | direct_wallet_balance_mutation | `test_shadow_wallets` | `services/snapshots/schema.py` | 896 | Retain as shadow-wallet migration. |
| retain | direct_wallet_balance_mutation | `test_shadow_wallets` | `services/snapshots/tester_shadow.py` | 407 | Retain as server-mode tester shadow update. |
| retain | direct_wallet_balance_mutation | `test_shadow_wallets` | `services/snapshots/tester_shadow.py` | 412 | Retain as server-mode tester shadow insert. |
| migrate | ledger_service_call | `_record_transaction` | `services/trading/engine.py` | 1912 | Migrate trading ledger bridge after Phase 0. |
| retain | direct_wallet_balance_mutation | `test_shadow_wallets` | `services/trading/shadow.py` | 34 | Retain as trading shadow wallet setup. |
| retain | direct_wallet_balance_mutation | `test_shadow_wallets` | `services/trading/shadow.py` | 225 | Retain as trading shadow wallet update. |

## Phase 0 Blocker List

No blocker findings were found by the scanner in runtime product code.

Important constraints for the next phase:

- The 14 `migrate` findings must not be changed until Phase 1 Wallet Service Facade is approved.
- `wallet_reservations` / `wallet_transaction_groups` must not become a second financial truth source.
- ComfyUI capture authority must remain backend finalization / output store, not frontend preview.
- Any future non-core official `points_wallets` balance mutation must be treated as a blocker.
