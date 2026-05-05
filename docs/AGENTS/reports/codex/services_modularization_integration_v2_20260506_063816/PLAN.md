# Services Modularization Integration Plan v2

Status:
- `docs-only`
- `implementation not authorized in this round`
- `source code changes not authorized in this round`

Planning goal:
- functionality first
- extensibility
- modularity
- maintainability
- no over-splitting
- behavior preserved
- each step reviewable and reversible

## 1. Final Target Tree

The target is to keep the current large entrypoint services as compatibility façades while moving stable helper domains into medium-granularity packages.

```text
services/
├── trading_engine.py
├── snapshots.py
├── points_chain.py
├── upload_security.py
├── videos.py
├── storage_albums.py
│
├── trading/
│   ├── __init__.py
│   ├── settings_schema.py
│   ├── audit.py
│   ├── notifications.py
│   ├── payloads.py
│   ├── markets.py
│   ├── backtest.py
│   ├── grid.py
│   ├── price_fusion/
│   │   ├── __init__.py
│   │   ├── orderbook.py
│   │   ├── weights.py
│   │   └── context.py
│   ├── accounting/
│   │   ├── __init__.py
│   │   ├── core.py
│   │   ├── interest.py
│   │   ├── trial_credit.py
│   │   └── funding_pool.py
│   └── bots/
│       ├── __init__.py
│       ├── workflow.py
│       ├── indicators.py
│       └── audit.py
│
├── snapshots/
│   ├── __init__.py
│   ├── snapshot_store.py
│   ├── restore.py
│   ├── mode_switch.py
│   ├── tester_tokens.py
│   ├── production_reports.py
│   ├── reset.py
│   ├── integrity.py
│   └── payloads.py
│
├── points_chain/
│   ├── __init__.py
│   ├── ledger.py
│   ├── wallet.py
│   ├── verify.py
│   ├── catalog.py
│   ├── sanctions.py
│   ├── replay.py
│   └── payloads.py
│
├── upload_security/
│   ├── __init__.py
│   ├── scanner.py
│   ├── verdicts.py
│   ├── quarantine.py
│   └── reports.py
│
├── videos/
│   ├── __init__.py
│   ├── publishing.py
│   ├── share_links.py
│   ├── playback.py
│   └── interactions.py
│
└── storage/
    ├── __init__.py
    ├── albums.py
    ├── organize.py
    └── output_albums.py
```

## 2. Why This Shape

This plan intentionally avoids over-splitting.

Key decisions:
- keep existing top-level large services as compatibility façades
- use medium-granularity domain modules instead of one-file-per-helper slicing
- use package subfolders only where a domain is clearly multi-part and still growing
- collapse previously over-fine slice ideas into broader maintainable modules

Examples of intentional consolidation:
- `payloads` stays `payloads.py`, not six tiny payload files
- workflow logic stays `bots/workflow.py`, not split across condition/validation micro-files
- backtest stays `backtest.py` unless it later proves too large
- grid stays `grid.py` unless preview and orchestration grow enough to justify a split
- market registry/provider mapping stays `markets.py`, not fragmented too early
- units/notional/fees/simple pnl belong in `accounting/core.py`

This structure is designed to improve maintainability, not to maximize file count reduction.

## 3. Trading Integration Branch Commit Map

Recommended integration branch name:
- `services-modularization-integration-trading-v1`

Implementation rule:
- one integration branch
- no stash-and-abandon slice workflow
- every commit must be real, reviewable, and kept in branch history

Trading integration v1 guardrail:
- no DB schema or migration changes are allowed in trading integration v1
- if a helper extraction discovers a schema concern, stop and open a separate issue

Recommended commit sequence:

1. `trading: bootstrap package and extract settings/accounting core`
- create `services/trading/`
- create `settings_schema.py`
- create `accounting/core.py`
- move pure validators/settings parsing/accounting core helpers
- keep `trading_engine.py` as façade

2. `trading: extract price fusion helpers`
- create `price_fusion/orderbook.py`
- create `price_fusion/weights.py`
- create `price_fusion/context.py`
- move pure depth/weight/context helpers only

3. `trading: extract payload and markets helpers`
- create `payloads.py`
- create `markets.py`
- move row-to-payload serializers and market/provider mapping helpers

4. `trading: extract bots workflow/indicator helpers`
- create `bots/workflow.py`
- create `bots/indicators.py`
- move pure workflow validation/evaluation and indicator helpers

5. `trading: extract backtest and grid pure helpers`
- create `backtest.py`
- create `grid.py`
- move candle normalization, replay helpers, grid preview/math/payload helpers

6. `trading: extract accounting edge helpers and service wrappers`
- create `accounting/interest.py`
- create `accounting/trial_credit.py`
- create `accounting/funding_pool.py`
- create `audit.py`
- create `notifications.py`
- move pure calculations plus formatting/wrapper helpers only

7. `trading: façade cleanup and integration verification`
- remove duplicate local helper definitions that are now truly redundant
- add façade boundary comments/docstrings
- keep all public method names stable
- run full regression

8. `trading: merge-candidate cleanup`
- one-time `release id sync`
- one-time release docs/update summary alignment
- only after integration branch is technically complete

Important:
- these commits are broader than the earlier slice names
- slice history is implementation input, not final module shape

## 4. Follow-up Refactor Order After Trading

Execution priority after trading integration:

1. `snapshots.py`
2. `points_chain.py`
3. `upload_security.py`
4. `videos.py`
5. `storage_albums.py`

Rationale:
- `snapshots.py` has the clearest multi-domain split and highest operational risk density
- `points_chain.py` is core state infrastructure and should be handled after trading is stabilized
- `upload_security.py` benefits from process-oriented decomposition
- `videos.py` and `storage_albums.py` are large but less foundational than snapshots/points_chain

## 5. Façade Retention Strategy

The following files remain stable entrypoints during migration:
- `services/trading_engine.py`
- `services/snapshots.py`
- `services/points_chain.py`
- `services/upload_security.py`
- `services/videos.py`
- `services/storage_albums.py`

Façade rules:
- existing imports continue to target these files
- routes do not switch import targets until a full domain integration is complete
- façades may delegate internally to new modules
- façades retain public method names and behavior
- façade removal is out of scope for this plan

## 6. Module Responsibility Boundaries

### Trading
- `settings_schema.py`: schema-driven settings parsing/normalization only
- `audit.py`: audit wrapper and metadata formatting only
- `notifications.py`: notification wrapper and payload builders only
- `payloads.py`: row/data to response payload serialization only
- `markets.py`: market symbol normalization, provider mapping, display helpers
- `backtest.py`: candle normalization, replay helpers, result summary formatting
- `grid.py`: grid preview/math/payload helpers, not bot execution
- `price_fusion/*`: orderbook/depth/weight/context helpers, not provider fetching
- `accounting/core.py`: units, notional, fees, simple pure pnl math
- `accounting/interest.py`: apr/daily/hourly interest pure calculations
- `accounting/trial_credit.py`: trial credit pure lifecycle/allocation/payload helpers
- `accounting/funding_pool.py`: funding pool utilization/pressure/payload helpers
- `bots/workflow.py`: workflow validation and decision helpers
- `bots/indicators.py`: indicator series and context helpers
- `bots/audit.py`: audit scoring/classification/dashboard summary helpers

### Snapshots
- `snapshot_store.py`: snapshot create/list/read primitives
- `restore.py`: restore workflow orchestration helpers
- `mode_switch.py`: server mode transition logic
- `tester_tokens.py`: tester/internal-test token workflows
- `production_reports.py`: production gate reports and validation
- `reset.py`: reset orchestration helpers
- `integrity.py`: snapshot-related integrity checks
- `payloads.py`: snapshot/mode/report payloads

### PointsChain
- `ledger.py`: canonical transaction recording/query helpers
- `wallet.py`: derived wallet state helpers
- `verify.py`: chain verification and release gate checks
- `catalog.py`: product/catalog accounting helpers
- `sanctions.py`: sanctions/holds policy helpers
- `replay.py`: rebuild/replay helpers
- `payloads.py`: points-chain related serializer helpers

### Upload Security
- `scanner.py`: scanner coordination
- `verdicts.py`: risk level / result classification
- `quarantine.py`: quarantine state transitions
- `reports.py`: report formatting/export

### Videos
- `publishing.py`: publish/unpublish flow
- `share_links.py`: share link/password/token semantics
- `playback.py`: playback metadata and stream decision helpers
- `interactions.py`: likes/comments/tips payload and interaction helpers

### Storage
- `albums.py`: CRUD/listing for albums
- `organize.py`: smart organize logic
- `output_albums.py`: generated/output album grouping helpers

## 7. High-Risk Orchestration Not To Touch Without Separate Authorization

### Trading
- order execution
- open/close margin position
- liquidation scan
- run_due_trading_bots
- grid counter-order orchestration
- backtest strategy semantics
- provider HTTP fetch and live price execution
- price fusion risk gate semantics
- wallet/ledger writes

### Snapshots
- restore execution semantics
- reset semantics
- incident lockdown entry behavior
- production gate acceptance behavior

### PointsChain
- ledger write truth model
- wallet cache rebuild semantics
- release gate verify semantics

### Upload Security
- final quarantine enforcement semantics
- blocked verdict semantics

### Videos
- share password/token enforcement
- E2EE playback semantics

### Storage
- file ownership / permission semantics

No bug fix should be mixed into modularization work. If a real bug is discovered, it must be split into a dedicated bugfix branch/commit path.

## 8. Acceptance and Verification

Every integration step must be:
- behavior-preserving
- independently reviewable
- reversible

Trading minimum acceptance:
- `git diff --check`
- `python3 scripts/pre_push_checks.py --ci`
- `PYTHONPATH=. python3 -m pytest -q tests/test_trading_engine.py`
- `PYTHONPATH=. python3 -m pytest -q tests/test_trading_reference_prices.py`
- `PYTHONPATH=. python3 -m pytest -q tests/test_frontend_economy.py`
- `HACKME_RUNTIME_DIR=/tmp/... PYTHONPATH=. python3 -m pytest -q tests/`

Snapshots minimum acceptance:
- `PYTHONPATH=. python3 -m pytest -q tests/ -k "snapshot or restore or reset or server_mode"`

PointsChain minimum acceptance:
- `PYTHONPATH=. python3 -m pytest -q tests/ -k "points or ledger or wallet or chain"`

Upload/Video/Storage minimum acceptance:
- `PYTHONPATH=. python3 -m pytest -q tests/ -k "upload or storage or album or video"`

Review standard:
- report exact files changed
- report moved helpers
- report behavior change = `No`
- report rollback plan
- flag any `release id sync` blocker explicitly

Public API schema freeze:
- all public API response schemas must remain byte-for-byte equivalent for the same inputs, except unordered JSON object key order
- no field rename, removal, or semantic change is allowed

## 9. Rollback Plan

Rollback strategy is domain-local and commit-local:

- each integration commit must be revertable on its own
- façades remain intact, so rollback is import/local-call restoration rather than route-wide rewiring
- no mixed bugfix/refactor commits
- no schema changes in normal modularization commits

If a commit regresses:
1. revert the most recent modularization commit
2. rerun the domain acceptance suite
3. keep façade entrypoints unchanged
4. reopen implementation only after root review

## 10. Release ID Sync Strategy

`release id sync` should not be handled per micro-refactor commit.

Plan:
- allow intermediate integration commits to focus on behavior-preserving refactor only
- treat `release id sync` as a known merge-candidate blocker during in-progress integration
- perform one unified release-id/update-summary cleanup at the final merge-candidate commit for that integration branch

This keeps implementation commits focused and avoids contaminating each modularization step with release metadata churn.

## First Executable Implementation Commit Plan

Before opening implementation:
- record base commit
- run baseline pytest subset
- run full pytest if feasible
- record current pre_push status
- save baseline report path

First implementation commit on the future trading integration branch:

`trading: bootstrap modular package and extract settings/accounting core`

Scope:
- create `services/trading/__init__.py`
- create `services/trading/settings_schema.py`
- create `services/trading/accounting/__init__.py`
- create `services/trading/accounting/core.py`
- move pure settings parsing/normalization helpers
- move units/notional/fees/simple pure accounting helpers
- keep `services/trading_engine.py` public façade stable

Why first:
- lowest behavior risk
- highest reuse across later trading commits
- establishes the package boundary without over-fragmentation

## Docs-Only Confirmation

This planning round must remain:
- docs-only
- no `services/` source edits
- no `routes/` edits
- no `tests/` edits
- no `release_info.py` edits
- no implementation branch work yet
