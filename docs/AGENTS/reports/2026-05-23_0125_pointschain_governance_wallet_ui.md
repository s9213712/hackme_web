# PointsChain Governance / Wallet UI Targeted QA

Date: 2026-05-23 CST

## Fixed

- Added governance category filtering:
  - all
  - selected dispute case
  - public governance
  - emergency security
  - official treasury
  - mint request
  - parameter / feature / burn policy
- Dispute cases can now be selected; the governance list then shows only that
  case's linked proposal/vote items.
- Governance action success/failure now writes inline feedback and toast
  notifications instead of appearing silent.
- Transaction management dispute clicks now show immediate feedback before
  local address-signing prompts.
- Cold wallet actions moved onto each wallet row:
  - transfer to this address
  - set as trading default payment wallet
  - local backup-code verification
  - delete cold wallet
- Removed the old cold-wallet delete target dropdown.
- Official treasury signer center now returns system fund addresses so
  `EXCHANGE_FUND_REPLENISH` auto-fills and locks the EXCHANGE Fund address.

## Verified

Local:

```text
node --check public/js/55-economy.js
python3 -m py_compile services/points_chain/service.py scripts/testing/pointschain_governance_dispute_probe.py
pytest -q \
  tests/points/test_governance_branch.py::test_official_treasury_requires_multisig_after_governance_passes \
  tests/frontend/trading/test_frontend_economy.py::test_root_points_page_is_chain_operations_console \
  tests/security/gates/test_flask_hardening.py \
  tests/security/auth/test_access_controls.py::test_maintenance_bypass_token_only_uses_header_not_query_string \
  tests/regressions/test_security_issue_regressions.py::test_flask_base_security_guardrails_are_configured
```

Result: pass, 7 tests.

Existing isolated runtime:

```text
python3 -m pytest -q \
  /tmp/hackme_web_isolated_54343/hackme_web/tests/points/test_governance_branch.py::test_official_treasury_requires_multisig_after_governance_passes \
  /tmp/hackme_web_isolated_54343/hackme_web/tests/frontend/trading/test_frontend_economy.py::test_root_points_page_is_chain_operations_console \
  /tmp/hackme_web_isolated_54343/hackme_web/tests/security/gates/test_flask_hardening.py \
  /tmp/hackme_web_isolated_54343/hackme_web/tests/security/auth/test_access_controls.py::test_maintenance_bypass_token_only_uses_header_not_query_string \
  /tmp/hackme_web_isolated_54343/hackme_web/tests/regressions/test_security_issue_regressions.py::test_flask_base_security_guardrails_are_configured
```

Result: pass, 7 tests.

Playwright against existing `https://127.0.0.1:54343`:

```text
python3 scripts/testing/pointschain_governance_dispute_probe.py \
  --base-url https://127.0.0.1:54343 \
  --username root \
  --password root \
  --out /tmp/hackme_web_isolated_54343/hackme_web/runtime/reports/qa/pointschain_governance_dispute_ui_probe.json
```

Result: pass, 16 checks.

Artifact:

- `/tmp/hackme_web_isolated_54343/hackme_web/runtime/reports/qa/pointschain_governance_dispute_ui_probe.json`
