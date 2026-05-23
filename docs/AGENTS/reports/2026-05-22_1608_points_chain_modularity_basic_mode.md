# PointsChain Modularity / Basic Points Mode QA

## Result

No confirmed blocker found in this pass. The points system now supports a basic-only mode where `feature_economy_enabled=true` and `feature_points_chain_enabled=false`.

## Verified Behavior

- Basic points endpoints still work with PointsChain disabled:
  - `GET /api/points/wallet`
  - `GET /api/points/ledger`
  - `GET /api/points/catalog`
  - `POST /api/points/spend`
- Chain endpoints return controlled `503` with `code=points_chain_disabled`:
  - wallet onboarding
  - wallet-to-wallet transactions
  - Explorer fee estimate
  - root chain report
  - official Treasury grant
- Root Economy UI does not blank in basic-only mode.
- Chain-only tabs/cards are hidden in basic-only mode:
  - transaction management
  - Explorer
  - private chain management
  - root system wallet management
- Settings were restored after live probing.
- Isolated default-account password flags were cleared without changing passwords after restart verification; `HTML_LEARNING_DISABLE_DEFAULT_PASSWORD_CHANGE` now aliases the existing default-password-policy disable switch.

## Evidence

- Live API + Playwright artifact:
  `/tmp/hackme_web_isolated_54343/hackme_web/runtime/reports/security/points_chain_modularity_probe_20260522.json`
- Restart verification artifact:
  `/tmp/hackme_web_isolated_54343/hackme_web/runtime/reports/security/points_chain_modularity_probe_20260522_after_restart.json`
- Playwright screenshot:
  `/tmp/hackme_web_isolated_54343/hackme_web/runtime/reports/security/points_chain_modularity_1779438026.png`
- Runtime tested:
  `https://127.0.0.1:54343`

## Commands

- `python3 -m py_compile services/platform/settings.py services/server/startup.py services/points_chain/service.py routes/economy.py routes/system_admin.py services/snapshots/schema.py scripts/testing/points_chain_modularity_probe.py`
- `python3 -m py_compile services/platform/bootstrap.py`
- `node --check public/js/55-economy.js`
- `node --check public/js/50-admin.js`
- `python3 -m pytest -q tests/points/test_points_explorer.py tests/platform/test_feature_flags.py tests/platform/test_startup_worker_feature_gates.py`
- `python3 -m pytest -q tests/frontend/trading/test_frontend_economy.py::test_root_points_page_is_chain_operations_console tests/security/smoke/test_functional_permission_pentest.py::test_feature_closed_response_is_treated_as_not_applicable_not_failure tests/snapshots/test_snapshots.py::test_builtin_security_profiles_refresh_and_close_superweak_controls tests/server_mode/test_smv2_acceptance.py::test_superweak_trading_remains_disabled tests/server_mode/test_smv2_acceptance.py::test_dev_ready_trading_is_enabled_for_prelive_verification`
- `python3 -m pytest -q tests/platform/test_bootstrap_compat.py tests/platform/test_feature_flags.py::test_save_feature_settings_rejects_required_child_without_parent`
- `python3 scripts/testing/points_chain_modularity_probe.py --base-url https://127.0.0.1:54343 --root-password root --admin-password admin --out /tmp/hackme_web_isolated_54343/hackme_web/runtime/reports/security/points_chain_modularity_probe_20260522.json`
- `python3 scripts/testing/points_chain_modularity_probe.py --base-url https://127.0.0.1:54343 --root-password root --admin-password admin --out /tmp/hackme_web_isolated_54343/hackme_web/runtime/reports/security/points_chain_modularity_probe_20260522_after_restart.json`

## Notes

- `feature_economy_enabled` is now the basic ledger/catalog/spend switch.
- `feature_points_chain_enabled` is the wallet identity, Explorer, transaction finality, sealing, backup, and root chain management switch.
- Trading now requires both basic points and PointsChain.
- Raspberry feature bundle now keeps basic points enabled while leaving PointsChain and trading disabled.
