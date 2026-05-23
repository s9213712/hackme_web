# PointsChain dev_ready Stress QA

## Result

No confirmed failures in the targeted PointsChain/trading stress pass.

## Evidence

- Isolated runtime: `/tmp/hackme_web_isolated_54343/hackme_web`
- Live URL: `https://127.0.0.1:54343`
- Server PID retained for follow-up testing: `488110`
- Stress report: `/tmp/hackme_web_isolated_54343/stress_reports/points_trading_100_accounts_030334.json`
- Targeted pytest:
  `pytest -q tests/points/test_chain_production_only.py tests/platform/test_db_mode_triggers.py tests/platform/test_routing_service.py tests/server_mode/test_smv2_acceptance.py::test_tester_trade_does_not_write_points_chain tests/server_mode/test_smv2_acceptance.py::test_production_trade_updates_chain_correctly tests/server_mode/test_smv2_acceptance.py::test_dev_ready_trading_is_enabled_for_prelive_verification`

## Coverage

- Switched runtime to `dev_ready` and confirmed block sealing is allowed by service guard, routing, and DB trigger.
- Created 100 active accounts, created one official hot wallet per account, and root submitted 100 official wallet grants of 5000 points each.
- Confirmed official grants stayed pending with zero recipient balance until proved; after forced proof all 100 accounts had exactly 5000 points.
- Submitted 100 user-initiated ring transfers with 1 point fee each.
- Confirmed pending transfers froze 11 points on each sender and did not credit recipients before proof.
- Confirmed duplicate `request_uuid` returned the original transaction hash without creating a second transaction.
- Confirmed insufficient-balance transfer was rejected with HTTP 409 and did not write a ledger entry.
- Confirmed proved ring transfers left each account at 4999 points and routed 100 total fees to BURN.
- Completed 100 spot buys and 100 spot sells; exchange fund did not lose principal during the spot flow.
- Drained trading funding pool from 908,163 available points to 36 available points through margin opens, then confirmed the next margin borrow was blocked with HTTP 409.
- Verified PointsChain and Trading after stress.
- Sealed remaining ledger entries in `dev_ready`; final PointsChain counts: 922 ledger entries, 5 sealed blocks, 0 unsealed entries, 203 wallets.

## Notes

This was a targeted economy/chain/trading stress pass, not a full deep-site Playwright audit.
