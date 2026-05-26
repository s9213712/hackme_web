# Wallet Direct Call Inventory

- Generated at: `2026-05-23T02:02:49Z`
- Include tests: `False`
- Total findings: `41`
- Classification counts: `{"allowed_internal_primitive": 33, "test_helper": 8}`
- Symbol counts: `{"_record_transaction": 17, "points_wallets": 2, "record_transaction": 13, "spend_points": 1, "test_shadow_wallets": 8}`

| Classification | Kind | Symbol | File | Line | Rationale |
|---|---|---|---|---:|---|
| test_helper | ledger_service_call | `_record_transaction` | `scripts/security/pentest/video_module_pentest.py` | 104 | operator or validation script outside runtime product accounting |
| test_helper | ledger_service_call | `record_transaction` | `scripts/trading/validation/trading_exchange_validation.py` | 136 | operator or validation script outside runtime product accounting |
| test_helper | ledger_service_call | `record_transaction` | `scripts/trading/validation/trading_exchange_validation.py` | 244 | operator or validation script outside runtime product accounting |
| test_helper | ledger_service_call | `record_transaction` | `scripts/trading/validation/trading_exchange_validation.py` | 395 | operator or validation script outside runtime product accounting |
| test_helper | ledger_service_call | `record_transaction` | `scripts/trading/validation/trading_exchange_validation.py` | 480 | operator or validation script outside runtime product accounting |
| test_helper | ledger_service_call | `record_transaction` | `scripts/trading/validation/trading_exchange_validation.py` | 498 | operator or validation script outside runtime product accounting |
| test_helper | ledger_service_call | `record_transaction` | `scripts/trading/validation/trading_exchange_validation.py` | 516 | operator or validation script outside runtime product accounting |
| test_helper | ledger_service_call | `record_transaction` | `scripts/trading/validation/trading_exchange_validation.py` | 534 | operator or validation script outside runtime product accounting |
| allowed_internal_primitive | direct_wallet_balance_mutation | `points_wallets` | `services/points_chain/schema.py` | 1055 | PointsChain core implementation may append replayable ledger events |
| allowed_internal_primitive | direct_wallet_balance_mutation | `points_wallets` | `services/points_chain/service.py` | 359 | PointsChain core implementation may append replayable ledger events |
| allowed_internal_primitive | ledger_service_call | `_record_transaction` | `services/points_chain/service.py` | 4274 | PointsChain core implementation may append replayable ledger events |
| allowed_internal_primitive | ledger_service_call | `_record_transaction` | `services/points_chain/service.py` | 5316 | PointsChain core implementation may append replayable ledger events |
| allowed_internal_primitive | ledger_service_call | `_record_transaction` | `services/points_chain/service.py` | 6750 | PointsChain core implementation may append replayable ledger events |
| allowed_internal_primitive | ledger_service_call | `_record_transaction` | `services/points_chain/service.py` | 6892 | PointsChain core implementation may append replayable ledger events |
| allowed_internal_primitive | ledger_service_call | `_record_transaction` | `services/points_chain/service.py` | 6908 | PointsChain core implementation may append replayable ledger events |
| allowed_internal_primitive | ledger_service_call | `_record_transaction` | `services/points_chain/service.py` | 6924 | PointsChain core implementation may append replayable ledger events |
| allowed_internal_primitive | ledger_service_call | `record_transaction` | `services/points_chain/service.py` | 7587 | PointsChain core implementation may append replayable ledger events |
| allowed_internal_primitive | ledger_service_call | `record_transaction` | `services/points_chain/service.py` | 7603 | PointsChain core implementation may append replayable ledger events |
| allowed_internal_primitive | ledger_service_call | `record_transaction` | `services/points_chain/service.py` | 7630 | PointsChain core implementation may append replayable ledger events |
| allowed_internal_primitive | ledger_service_call | `record_transaction` | `services/points_chain/service.py` | 7652 | PointsChain core implementation may append replayable ledger events |
| allowed_internal_primitive | ledger_service_call | `record_transaction` | `services/points_chain/service.py` | 7705 | PointsChain core implementation may append replayable ledger events |
| allowed_internal_primitive | ledger_service_call | `_record_transaction` | `services/points_chain/service.py` | 7994 | PointsChain core implementation may append replayable ledger events |
| allowed_internal_primitive | ledger_service_call | `_record_transaction` | `services/points_chain/service.py` | 8035 | PointsChain core implementation may append replayable ledger events |
| allowed_internal_primitive | ledger_service_call | `_record_transaction` | `services/points_chain/service.py` | 8264 | PointsChain core implementation may append replayable ledger events |
| allowed_internal_primitive | ledger_service_call | `_record_transaction` | `services/points_chain/service.py` | 8278 | PointsChain core implementation may append replayable ledger events |
| allowed_internal_primitive | ledger_service_call | `_record_transaction` | `services/points_chain/service.py` | 8408 | PointsChain core implementation may append replayable ledger events |
| allowed_internal_primitive | ledger_service_call | `_record_transaction` | `services/points_chain/service.py` | 8674 | PointsChain core implementation may append replayable ledger events |
| allowed_internal_primitive | ledger_service_call | `_record_transaction` | `services/points_chain/service.py` | 10205 | PointsChain core implementation may append replayable ledger events |
| allowed_internal_primitive | ledger_service_call | `spend_points` | `services/points_chain/wallet_facade.py` | 61 | PointsChain core implementation may append replayable ledger events |
| allowed_internal_primitive | ledger_service_call | `record_transaction` | `services/points_chain/wallet_facade.py` | 81 | PointsChain core implementation may append replayable ledger events |
| allowed_internal_primitive | ledger_service_call | `_record_transaction` | `services/points_chain/wallet_facade.py` | 106 | PointsChain core implementation may append replayable ledger events |
| allowed_internal_primitive | ledger_service_call | `_record_transaction` | `services/points_chain/wallet_facade.py` | 363 | PointsChain core implementation may append replayable ledger events |
| allowed_internal_primitive | ledger_service_call | `_record_transaction` | `services/points_chain/wallet_facade.py` | 418 | PointsChain core implementation may append replayable ledger events |
| allowed_internal_primitive | direct_wallet_balance_mutation | `test_shadow_wallets` | `services/snapshots/schema.py` | 870 | server-mode or shadow-wallet isolation code, not production wallet truth |
| allowed_internal_primitive | direct_wallet_balance_mutation | `test_shadow_wallets` | `services/snapshots/schema.py` | 881 | server-mode or shadow-wallet isolation code, not production wallet truth |
| allowed_internal_primitive | direct_wallet_balance_mutation | `test_shadow_wallets` | `services/snapshots/schema.py` | 892 | server-mode or shadow-wallet isolation code, not production wallet truth |
| allowed_internal_primitive | direct_wallet_balance_mutation | `test_shadow_wallets` | `services/snapshots/schema.py` | 903 | server-mode or shadow-wallet isolation code, not production wallet truth |
| allowed_internal_primitive | direct_wallet_balance_mutation | `test_shadow_wallets` | `services/snapshots/tester_shadow.py` | 407 | server-mode or shadow-wallet isolation code, not production wallet truth |
| allowed_internal_primitive | direct_wallet_balance_mutation | `test_shadow_wallets` | `services/snapshots/tester_shadow.py` | 412 | server-mode or shadow-wallet isolation code, not production wallet truth |
| allowed_internal_primitive | direct_wallet_balance_mutation | `test_shadow_wallets` | `services/trading/shadow.py` | 34 | server-mode or shadow-wallet isolation code, not production wallet truth |
| allowed_internal_primitive | direct_wallet_balance_mutation | `test_shadow_wallets` | `services/trading/shadow.py` | 225 | server-mode or shadow-wallet isolation code, not production wallet truth |
