# Wallet Direct Call Inventory

- Generated at: `2026-05-26T08:48:48Z`
- Include tests: `False`
- Total findings: `48`
- Classification counts: `{"allowed_internal_primitive": 40, "test_helper": 8}`
- Symbol counts: `{"_record_transaction": 24, "points_wallets": 2, "record_transaction": 13, "spend_points": 1, "test_shadow_wallets": 8}`

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
| allowed_internal_primitive | direct_wallet_balance_mutation | `points_wallets` | `services/points_chain/schema.py` | 1171 | PointsChain core implementation may append replayable ledger events |
| allowed_internal_primitive | direct_wallet_balance_mutation | `points_wallets` | `services/points_chain/service.py` | 473 | PointsChain core implementation may append replayable ledger events |
| allowed_internal_primitive | ledger_service_call | `_record_transaction` | `services/points_chain/service.py` | 4994 | PointsChain core implementation may append replayable ledger events |
| allowed_internal_primitive | ledger_service_call | `_record_transaction` | `services/points_chain/service.py` | 6563 | PointsChain core implementation may append replayable ledger events |
| allowed_internal_primitive | ledger_service_call | `_record_transaction` | `services/points_chain/service.py` | 7008 | PointsChain core implementation may append replayable ledger events |
| allowed_internal_primitive | ledger_service_call | `_record_transaction` | `services/points_chain/service.py` | 7252 | PointsChain core implementation may append replayable ledger events |
| allowed_internal_primitive | ledger_service_call | `_record_transaction` | `services/points_chain/service.py` | 9739 | PointsChain core implementation may append replayable ledger events |
| allowed_internal_primitive | ledger_service_call | `_record_transaction` | `services/points_chain/service.py` | 9903 | PointsChain core implementation may append replayable ledger events |
| allowed_internal_primitive | ledger_service_call | `_record_transaction` | `services/points_chain/service.py` | 9919 | PointsChain core implementation may append replayable ledger events |
| allowed_internal_primitive | ledger_service_call | `_record_transaction` | `services/points_chain/service.py` | 9935 | PointsChain core implementation may append replayable ledger events |
| allowed_internal_primitive | ledger_service_call | `_record_transaction` | `services/points_chain/service.py` | 10261 | PointsChain core implementation may append replayable ledger events |
| allowed_internal_primitive | ledger_service_call | `_record_transaction` | `services/points_chain/service.py` | 10277 | PointsChain core implementation may append replayable ledger events |
| allowed_internal_primitive | ledger_service_call | `_record_transaction` | `services/points_chain/service.py` | 10842 | PointsChain core implementation may append replayable ledger events |
| allowed_internal_primitive | ledger_service_call | `record_transaction` | `services/points_chain/service.py` | 10867 | PointsChain core implementation may append replayable ledger events |
| allowed_internal_primitive | ledger_service_call | `record_transaction` | `services/points_chain/service.py` | 10886 | PointsChain core implementation may append replayable ledger events |
| allowed_internal_primitive | ledger_service_call | `record_transaction` | `services/points_chain/service.py` | 10916 | PointsChain core implementation may append replayable ledger events |
| allowed_internal_primitive | ledger_service_call | `record_transaction` | `services/points_chain/service.py` | 10941 | PointsChain core implementation may append replayable ledger events |
| allowed_internal_primitive | ledger_service_call | `record_transaction` | `services/points_chain/service.py` | 10997 | PointsChain core implementation may append replayable ledger events |
| allowed_internal_primitive | ledger_service_call | `_record_transaction` | `services/points_chain/service.py` | 11291 | PointsChain core implementation may append replayable ledger events |
| allowed_internal_primitive | ledger_service_call | `_record_transaction` | `services/points_chain/service.py` | 11332 | PointsChain core implementation may append replayable ledger events |
| allowed_internal_primitive | ledger_service_call | `_record_transaction` | `services/points_chain/service.py` | 11589 | PointsChain core implementation may append replayable ledger events |
| allowed_internal_primitive | ledger_service_call | `_record_transaction` | `services/points_chain/service.py` | 11603 | PointsChain core implementation may append replayable ledger events |
| allowed_internal_primitive | ledger_service_call | `_record_transaction` | `services/points_chain/service.py` | 11747 | PointsChain core implementation may append replayable ledger events |
| allowed_internal_primitive | ledger_service_call | `_record_transaction` | `services/points_chain/service.py` | 11822 | PointsChain core implementation may append replayable ledger events |
| allowed_internal_primitive | ledger_service_call | `_record_transaction` | `services/points_chain/service.py` | 11941 | PointsChain core implementation may append replayable ledger events |
| allowed_internal_primitive | ledger_service_call | `_record_transaction` | `services/points_chain/service.py` | 12203 | PointsChain core implementation may append replayable ledger events |
| allowed_internal_primitive | ledger_service_call | `_record_transaction` | `services/points_chain/service.py` | 14611 | PointsChain core implementation may append replayable ledger events |
| allowed_internal_primitive | ledger_service_call | `spend_points` | `services/points_chain/wallet_facade.py` | 61 | PointsChain core implementation may append replayable ledger events |
| allowed_internal_primitive | ledger_service_call | `record_transaction` | `services/points_chain/wallet_facade.py` | 87 | PointsChain core implementation may append replayable ledger events |
| allowed_internal_primitive | ledger_service_call | `_record_transaction` | `services/points_chain/wallet_facade.py` | 112 | PointsChain core implementation may append replayable ledger events |
| allowed_internal_primitive | ledger_service_call | `_record_transaction` | `services/points_chain/wallet_facade.py` | 369 | PointsChain core implementation may append replayable ledger events |
| allowed_internal_primitive | ledger_service_call | `_record_transaction` | `services/points_chain/wallet_facade.py` | 424 | PointsChain core implementation may append replayable ledger events |
| allowed_internal_primitive | direct_wallet_balance_mutation | `test_shadow_wallets` | `services/snapshots/schema.py` | 873 | server-mode or shadow-wallet isolation code, not production wallet truth |
| allowed_internal_primitive | direct_wallet_balance_mutation | `test_shadow_wallets` | `services/snapshots/schema.py` | 884 | server-mode or shadow-wallet isolation code, not production wallet truth |
| allowed_internal_primitive | direct_wallet_balance_mutation | `test_shadow_wallets` | `services/snapshots/schema.py` | 895 | server-mode or shadow-wallet isolation code, not production wallet truth |
| allowed_internal_primitive | direct_wallet_balance_mutation | `test_shadow_wallets` | `services/snapshots/schema.py` | 906 | server-mode or shadow-wallet isolation code, not production wallet truth |
| allowed_internal_primitive | direct_wallet_balance_mutation | `test_shadow_wallets` | `services/snapshots/tester_shadow.py` | 407 | server-mode or shadow-wallet isolation code, not production wallet truth |
| allowed_internal_primitive | direct_wallet_balance_mutation | `test_shadow_wallets` | `services/snapshots/tester_shadow.py` | 412 | server-mode or shadow-wallet isolation code, not production wallet truth |
| allowed_internal_primitive | direct_wallet_balance_mutation | `test_shadow_wallets` | `services/trading/shadow.py` | 34 | server-mode or shadow-wallet isolation code, not production wallet truth |
| allowed_internal_primitive | direct_wallet_balance_mutation | `test_shadow_wallets` | `services/trading/shadow.py` | 225 | server-mode or shadow-wallet isolation code, not production wallet truth |
