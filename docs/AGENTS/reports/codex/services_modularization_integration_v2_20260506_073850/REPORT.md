## Trading Integration Step 4

- Date: 2026-05-06 07:38:50 Asia/Taipei
- Branch: `03.Points`
- Behavior change: `No`

### Scope

Extract pure market registry / provider mapping / display helpers from
`services/trading_engine.py` into a single medium-granularity module:

- `services/trading/markets.py`

`services/trading_engine.py` remains the compatibility facade and keeps DB
queries, provider fetch flow, and runtime market orchestration in place.

### Files Changed

- `services/trading_engine.py`
- `services/trading/markets.py`
- `docs/AGENTS/reports/codex/services_modularization_integration_v2_20260506_073850/REPORT.md`

### Functions Moved

- `_provider_mapping_capabilities`
- `_market_seed_compare_value`
- `_registry_seed_status`
- `_normalize_market_symbol_on_conn` alias-map logic
- `_market_provider_ids_from_mappings`
- `_market_supports_live_price_on_conn` provider-row support predicate
- `_market_supports_reference_price_on_conn` provider-row support predicate
- `_market_display_symbol_on_conn` pure display/fallback logic

### Before / After Import Summary

Before:

- `services/trading_engine.py` contained market/provider alias normalization,
  registry seed drift comparison, and display fallback logic inline.

After:

- `services/trading_engine.py` imports pure helpers from
  `services.trading.markets`
- engine methods keep the same public names and DB orchestration
- provider HTTP fetchers and market DB mutation remain in engine

### Behavior Boundary Confirmation

- No provider API behavior change
- No price fetching change
- No market enable/disable behavior change
- No DB schema or migration change
- No route/API schema change

### Tests Run

- `python3 -m py_compile services/trading_engine.py services/trading/markets.py`
  - `pass`
- `git diff --check`
  - `pass`
- `PYTHONPATH=. python3 -m pytest -q tests/test_trading_engine.py -k "market or provider or live_price or price_fusion"`
  - `42 passed, 112 deselected`
- `PYTHONPATH=. python3 -m pytest -q tests/test_trading_reference_prices.py tests/test_frontend_economy.py`
  - `42 passed`
- `HACKME_RUNTIME_DIR=/tmp/hackme_web_integration_markets_<timestamp> PYTHONPATH=. python3 -m pytest -q tests/`
  - `1055 passed`
- `python3 scripts/pre_push_checks.py --ci`
  - `10 PASS / 1 FAIL`
  - merge blocker: `release id sync`

### Rollback Plan

If this step needs to be reverted:

1. revert only this integration commit
2. inline the moved market/provider helpers back into `services/trading_engine.py`
3. remove `services/trading/markets.py`
4. rerun the same targeted tests, full pytest, and pre-push checks
