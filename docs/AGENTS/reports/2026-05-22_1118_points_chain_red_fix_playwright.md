# PointsChain RED Fix And Deep Playwright QA

## Findings

No confirmed failures after the fix.

## Fixed

- Root economy health was RED after the 100-account stress run because the closed-loop formula counted only PointsChain wallet balances as off-fund supply.
- Margin lending had moved exchange-fund points to external borrower addresses in `points_economy_events`, but those external balances and exchange-fund receivables were not included in the formula or health calculation.
- The replay now tracks external address balances, external supply, exchange receivable principal, and exchange total assets.
- Exchange-fund health now distinguishes solvency from liquidity:
  - Low cash with receivable principal becomes a liquidity warning.
  - True non-receivable exchange asset drain remains RED.
- The frontend formula now displays chain external circulation instead of only wallet aggregate outstanding.

## Verification

- Stress runtime: `/tmp/hackme_web_isolated_54343/hackme_web`
- Stress server kept running: `https://127.0.0.1:54343`
- Post-fix economy status on the stressed runtime:
  - health: `yellow`
  - reason: `exchange_fund_liquidity_critical`
  - formula total: `100000000`
  - formula gap: `0`
  - external supply: `6009764`
  - wallet outstanding: `1009800`
  - off-wallet external: `4999964`
  - exchange receivable principal: `5000164`
  - exchange total assets: `5000200`
  - chain verify: `ok`

## Tests

- `pytest -q tests/economy/test_economy_layer.py tests/points/test_points_chain.py::test_economy_stats_reports_member_circulating_supply tests/points/test_points_chain.py::test_official_wallet_grant_debits_official_fund_by_wallet_address tests/points/test_points_explorer.py::test_root_official_wallet_grant_uses_pending_transaction_management tests/trading/core/test_trading_engine.py::test_spot_trade_principal_does_not_enter_exchange_fund_only_fee_does tests/trading/core/test_trading_engine.py::test_margin_open_rejects_when_funding_pool_is_insufficient`
  - result: 15 passed

## Deep Playwright Audit

- Runtime root: `/tmp/hackme_web_isolated_54343/playwright_deep_runtime`
- JSON report: `/tmp/hackme_web_isolated_54343/playwright_deep_runtime/reports/qa/playwright_deep_site_check_20260522T031551Z.json`
- Markdown report: `/tmp/hackme_web_isolated_54343/playwright_deep_runtime/reports/qa/playwright_deep_site_check_20260522T031551Z.md`
- Result: `ok=true`
- Checks: 33 passed, 0 failed
- Browser/page errors: none

## Coverage

- Auth/register/login/session.
- Admin settings and member management.
- Forum thread/reply/reaction.
- Drive upload with standard and E2EE modes.
- Video upload/share/HLS playback.
- Games catalog, chess, and solo flow.
- Economy wallet/order flow.
- Trading dashboard/order flow.
- Launch check and security health.
- ComfyUI workflow builder/editor offline guard paths.
- Desktop and mobile module-tab navigation.
