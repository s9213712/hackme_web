## Trading Integration Step 5

- Date: 2026-05-06 07:47:54 Asia/Taipei
- Branch: `03.Points`
- Behavior change: `No`

### Scope

Remove over-fragmented accounting compatibility wrappers and keep the accounting
surface at the intended medium-granularity layout.

Deleted wrapper files:

- `services/trading/accounting/units.py`
- `services/trading/accounting/notional.py`
- `services/trading/accounting/fees.py`

Retained accounting entrypoints:

- `services/trading/accounting/__init__.py`
- `services/trading/accounting/core.py`

### Files Changed

- `services/trading/accounting/__init__.py`
- `services/trading/accounting/units.py` (deleted)
- `services/trading/accounting/notional.py` (deleted)
- `services/trading/accounting/fees.py` (deleted)
- `docs/AGENTS/reports/codex/services_modularization_integration_v2_20260506_074754/REPORT.md`

### Before / After Structure

Before:

- `core.py`
- `units.py` wrapper
- `notional.py` wrapper
- `fees.py` wrapper

After:

- `core.py`
- `__init__.py` export surface only

### Boundary Confirmation

- No formula change
- No rounding change
- No order execution change
- No wallet/ledger change
- No margin behavior change
- No API schema change

### Tests Run

- `python3 -m py_compile services/trading_engine.py services/trading/accounting/__init__.py services/trading/accounting/core.py`
  - `pass`
- `git diff --check`
  - `pass`
- `PYTHONPATH=. python3 -m pytest -q tests/test_trading_engine.py tests/test_trading_reference_prices.py tests/test_frontend_economy.py`
  - `196 passed`
- `HACKME_RUNTIME_DIR=/tmp/hackme_web_accounting_cleanup_<timestamp> PYTHONPATH=. python3 -m pytest -q tests/`
  - `1055 passed`
- `python3 scripts/pre_push_checks.py --ci`
  - `10 PASS / 1 FAIL`
  - merge blocker: `release id sync`

### Resulting Trading Tree Snapshot

```text
services/trading/
├── __init__.py
├── accounting/
│   ├── __init__.py
│   └── core.py
├── constants.py
├── markets.py
├── payloads.py
├── price_fusion/
│   ├── __init__.py
│   ├── context.py
│   ├── orderbook.py
│   └── weights.py
├── settings_schema.py
└── validators.py
```

### Rollback Plan

If this cleanup needs to be reverted:

1. revert only this integration commit
2. restore the three deleted wrapper modules
3. rerun the same targeted tests, full pytest, and pre-push checks
