# Readability Refactor Inventory

## Status

- Branch: `05.readability-refactor`
- Mode: `inventory-only`
- Reason:
  - `python3 scripts/pre_push_checks.py --ci` is green
  - full pytest baseline is **not green**
  - Per refactor charter, no source-code refactor should start until baseline is stable

## Baseline

- `python3 scripts/pre_push_checks.py --ci`
  - `11 PASS / 0 FAIL`
- `HACKME_RUNTIME_DIR=/tmp/hackme_web_readability_refactor_baseline_20260506 PYTHONPATH=/home/s92137/hackme_web python3 -m pytest -q /home/s92137/hackme_web/tests/`
  - `1 failed, 1093 passed`
  - Failure:
    - `tests/test_snapshots.py::test_server_mode_v2_root_api_is_root_only_and_exposes_requirements`
    - observed error: `GET /api/root/launch-check/doc?path=docs/API_REFERENCE.md` returned `404`, expected `200`

## Open Blockers

1. Full pytest baseline is red on `05.readability-refactor`.
2. Because baseline is not green, this round should stop at:
   - inventory report
   - refactor plan
   - module split proposal
   - no behavior-changing source edits

## 3.1 巨大檔案 / 巨大函式

### Files over 800 lines

| File | Lines | Risk | Suggested split |
|---|---:|---|---|
| `public/styles.css` | 6552 | Frontend styling monolith | Split by page/domain tokens and shared primitives |
| `public/js/50-admin.js` | 6172 | Admin UI god file | Split into health, security center, updates, server mode, snapshots |
| `public/index.html` | 4913 | Page shell + all tabs tightly coupled | Split by partials or template fragments |
| `public/js/56-trading.js` | 4818 | Trading UI god file | Split by bot family, reporting, backtest panel, shared formatting |
| `routes/comfyui.py` | 4585 | HTTP + validation + upload + job orchestration mixed | Split by jobs, civitai, model management, workflow routes |
| `services/trading/engine.py` | 3983 | Core trading orchestrator still too large | Continue bounded splits around settings schema, validators, fee/pnl, reporting |
| `public/js/35-drive.js` | 3806 | Cloud Drive UI god file | Split by browser, uploads, previews, shares, quota |
| `routes/files.py` | 3594 | Cloud drive, sharing, preview, quota, E2EE mixed | Split by file CRUD, shares, previews, key endpoints, admin/quota |
| `routes/system_admin.py` | 3239 | Root/admin operational monolith | Split by health, integrity, updates, server mode, settings |
| `public/js/36-comfyui.js` | 3193 | ComfyUI UI monolith | Split by generation, civitai, models, workflow tools |
| `routes/community.py` | 2322 | Threads, replies, reactions, schema mixed | Split by thread/reply/reaction/report domains |
| `services/points_chain/service.py` | 2317 | Wallet, ledger, sanctions, catalog, reports mixed | Split by ledger replay, wallet ops, sanctions, catalog, reporting |
| `services/snapshots/server_mode.py` | 2033 | Mode switching, production checks, tester flows mixed | Split by mode transitions, tester tokens, production reports |
| `routes/videos.py` | 1967 | Video CRUD + stream delivery + comments + tipping | Split by publishing, streaming, comments, monetization |
| `routes/trading.py` | 1952 | History export, market APIs, bot APIs, root controls mixed | Split by market data, bots, admin/root, history/export |
| `services/trading/price_runtime.py` | 1911 | Reference/risk price and provider runtime still dense | Split by reference price, risk-grade price, provider transport state |
| `routes/users.py` | 1769 | Auth-adjacent admin/user ops mixed | Split by admin user ops, profile ops, lifecycle ops |
| `services/trading/margin.py` | 1675 | Margin lifecycle + liquidation + risk payload mixed | Split by open/close, collateral, liquidation, payloads |
| `services/media/videos.py` | 1300 | Video service still broad | Split by schema, shares, stream state, engagement |
| `services/trading/bots/service.py` | 1256 | Bot orchestration and audit mixed | Split by scheduling/run, audit, notifications |
| `services/snapshots/schema.py` | 1263 | Schema + manifest + signature helpers dense | Split by manifest/signature and schema setup |
| `services/snapshots/service.py` | 1129 | Snapshot CRUD + restore still sizable | Split by creation, verification, restore, archive import |
| `services/storage/catalog.py` | 1019 | Storage catalog logic broad | Split by file graph vs maintenance metadata |
| `server.py` | 902 | Better than before, still a large entrypoint | Future app-factory/config split, but not top priority now |
| `services/storage/albums.py` | 886 | Albums + share logic dense | Split by album CRUD vs share/public access |
| `services/system/integrity_guard.py` | 804 | Scan + classification + review logic mixed | Split by scanning, classification, review actions |
| `services/trading/orders.py` | 811 | Order placement + matching + execution mixed | Split by placement vs execution once tests are stronger |

### Functions over 100 lines

| File | Function | Range | Risk | Suggested split |
|---|---|---|---|---|
| `routes/comfyui.py` | `register_comfyui_routes` | `115-4585` | Route god function; HTTP, validation, job orchestration, model/file ops mixed | Split registration by subdomain modules |
| `routes/files.py` | `register_file_routes` | `110-3594` | Cloud drive route god function | Split into file CRUD / previews / shares / E2EE key routes |
| `routes/system_admin.py` | `register_system_admin_routes` | `243-3239` | Root/admin operational monolith | Split by health, integrity, settings, updates, server mode |
| `routes/community.py` | `register_community_routes` | `12-2322` | Entire community feature in one function | Split by threads, posts, reactions |
| `routes/videos.py` | `register_video_routes` | `51-1967` | Large route monolith | Split by publish/stream/comment/tip |
| `routes/trading.py` | `register_trading_routes` | `58-1952` | Market data + bot + root controls mixed | Split by market APIs, bots, root/admin |
| `routes/users.py` | `register_user_routes` | `20-1769` | User/admin ops in one registrar | Split by self-service vs admin |
| `services/trading/engine.py` | `ensure_trading_schema` | `812-1551` | Schema setup too large and business-specific | Extract schema migration helpers per feature area |
| `services/trading/price_runtime.py` | `fetch_weighted_fused_price_points` | `527-1248` | Core reference/risk price fusion is too dense | Split weighting, provider fetch, degradation classification |
| `services/snapshots/schema.py` | `ensure_snapshot_schema` | `550-1218` | Schema bootstrap too wide | Split event tables, manifest tables, report tables |
| `services/trading/backtest.py` | `backtest_trading_bot` | `223-623` | DB, candle prep, bot execution, report assembly mixed | Split input prep, execution loop, report summarization |
| `services/trading/price_runtime.py` | `current_market_price_points` | `1573-1911` | High-risk reference/risk decision hub | Split manual/cached branch, live branch, metadata assembly |
| `services/points_chain/schema.py` | `ensure_points_economy_schema` | `263-590` | Schema bootstrap too dense | Split wallets/ledger/catalog/reward schema |
| `services/trading/margin.py` | `open_margin_position` | `633-955` | DB + pricing + accounting + audit | Split validation, accounting, persistence, payload |
| `services/trading/orders.py` | `execute_order` | `400-712` | Execution path mixes DB, accounting, audit, payload | Split accounting/persistence/audit composition |
| `services/trading/admin.py` | `update_root_settings` | `340-634` | Settings schema, coercion, side effects mixed | Move parsing into central schema/validator layer |
| `services/trading/margin.py` | `close_margin_position` | `1114-1472` | Similar mixed concerns | Same as open path |
| `services/trading/trial_credit.py` | `reclaim_trial_credit` | `304-501` | Forced sell, audit, blocking state mixed | Split decision vs effect vs payload |
| `services/snapshots/service.py` | `restore_snapshot` | `917-1114` | Restore orchestration is still critical and dense | Split prepare / db restore / file restore / finalize |
| `services/trading/grid.py` | `scan_one_grid_bot` | `565-776` | Scan, risk gating, fill, counter-order logic mixed | Split risk gate, fill decision, persistence |

### Deeply nested blocks

Files with max indentation depth above five levels are good bug predictors because they hide fallback and branching semantics.

| File | Max indent | Example line | Risk |
|---|---:|---:|---|
| `services/trading/backtest.py` | `40` | `482` | Execution loop too branchy; risk of mixed reference/live fallback |
| `services/trading/grid.py` | `35` | `747` | Fill/counter-order paths are hard to reason about |
| `services/users/auth.py` | `32` | `36` | Auth/CSRF logic buried in nested branches |
| `services/trading/margin.py` | `32` | `1549` | Liquidation/settlement path readability risk |
| `services/system/integrity_guard.py` | `32` | `444` | Scan classification and review state mixed |
| `services/snapshots/service.py` | `32` | `232` | Nested restore/import branches reduce auditability |
| `routes/public.py` | `32` | `652` | Login flow nesting raises correctness risk |
| `routes/comfyui.py` | `32` | `2175` | Route-local logic too branchy |

### Functions that mix DB + business logic + HTTP/UI payloads

- `routes/system_admin.py:admin_settings`
  - DB-backed settings writes, validation, response assembly
- `routes/files.py:cloud_drive_purchase_storage_upgrade`
  - auth, pricing, persistence, UI response mixed
- `routes/trading.py:trading_history_export_csv`
  - DB reads, cross-table business shaping, export payload formatting
- `services/trading/backtest.py:backtest_trading_bot`
  - DB/read model prep, execution, metrics, UI report payload mixed
- `services/trading/reporting.py:user_dashboard`
  - business metrics + payload shaping are tightly coupled

## 3.2 重複邏輯

### Settings validation

| Area | Locations | Difference | Can extract? | Risk |
|---|---|---|---|---|
| Server/system settings coercion | `routes/system_admin.py`, `services/server/bind.py`, `services/storage/paths.py` | Mixed route-local coercion vs helper-based validation | Yes, partially | High |
| Trading settings coercion | `services/trading/admin.py` | Has richer constraints but custom parser family | Yes, into `services/trading/settings_schema.py` | High |
| ComfyUI settings validation | `routes/system_admin.py` `validate_comfyui_*` | Route-local, not schema-driven | Yes | Medium |

### Bool / int / Decimal parsing

| Category | Locations | Difference | Can extract? | Risk |
|---|---|---|---|---|
| Positive int parsing | `server.py`, `services/server/validation.py`, many route-local `int(...)` guards in `routes/system_admin.py` and `routes/trading.py` | Some strict, some defaulting, some broad `int(float(...))` | Yes | High |
| Bool parsing | `services/trading/admin.py`, `routes/system_admin.py`, `services/server/bind.py`, many `bool(data.get(...))` paths | Some treat invalid strings as truthy/falsy implicitly | Yes | High |
| Decimal parsing | `services/trading/accounting/core.py`, `services/trading/engine.py`, route-local numeric conversions | Accounting paths are strict; route paths often use `float/int` for request coercion | Yes, but keep risk paths separate | High |

### API error response

| Pattern | Locations | Note | Can extract? | Risk |
|---|---|---|---|---|
| `json_resp({"ok": False, "msg": ...})` | pervasive across `routes/*` | Many repeated auth/permission/invalid-json/error responses | Partially | Medium |
| Auth failure helpers | `routes/economy.py`, `routes/system_admin.py`, `routes/chat.py` | Similar semantics but hand-written repeatedly | Yes | Medium |

### Role checking

| Pattern | Locations | Note | Can extract? | Risk |
|---|---|---|---|---|
| `role_rank(actor_role) < role_rank(...)` | `routes/system_admin.py`, `routes/reports_notifications.py`, others | Repeated with root/super_admin special casing | Yes | High |
| `actor["username"] == "root"` checks | many routes/services | Root override semantics are repeated inline | Partially | High |

### CSRF / auth handling

| Pattern | Locations | Note | Can extract? | Risk |
|---|---|---|---|---|
| `require_login` / CSRF policy | `services/users/auth.py`, route-local pre-checks | Base wrapper exists, but many routes still do local auth branching | Partially | Medium |

### Price source fallback

| Pattern | Locations | Note | Can extract? | Risk |
|---|---|---|---|---|
| `manual_root`, cached, degraded, transport fallback | `services/trading/price_runtime.py`, `services/trading/price_fusion/context.py`, route-level UI handling in `routes/trading.py` | Better separated than before, but still duplicated between runtime and payload assembly | Yes, carefully | High |

### Order / fee / PnL calculation

| Pattern | Locations | Note | Can extract? | Risk |
|---|---|---|---|---|
| Fee/notional math | `services/trading/accounting/core.py`, execution paths in `orders.py`, reporting payload layers | Core math is centralized, but call-site shaping still repeated | Partially | High |

### Wallet / ledger replay

| Pattern | Locations | Note | Can extract? | Risk |
|---|---|---|---|---|
| Wallet verification vs replay vs report | `services/points_chain/service.py` | Same file mixes source-of-truth replay and user-facing reporting | Yes | High |

### Bot trigger / audit result mapping

| Pattern | Locations | Note | Can extract? | Risk |
|---|---|---|---|---|
| Bot run findings, root notifications, audit summaries | `services/trading/bots/service.py`, `services/trading/grid.py`, `services/trading/trial_credit.py` | Similar mapping of runtime outcome -> audit/event/user payload | Yes | Medium |

## 3.3 Magic Numbers / Magic Strings

### Business-critical strings

- `manual_root`
  - `services/trading/admin.py`
  - `services/trading/price_runtime.py`
  - `routes/trading.py`
- `fused_weighted`
  - `services/trading/engine.py`
  - `services/trading/admin.py`
- `auto_depth`
  - `services/trading/engine.py`
  - `services/trading/admin.py`
  - `services/trading/price_runtime.py`
- `superweak`
  - `services/users/auth.py`
  - `services/snapshots/server_mode.py`
  - `routes/system_admin.py`
- `incident_lockdown`
  - `services/snapshots/server_mode.py`
  - `routes/system_admin.py`
  - `routes/economy.py`

### Numeric constants that should be schema-backed or centralized

- `300`
  - cooldown / rate limit / TTL values appear in:
    - `services/users/member_levels.py`
    - `services/security/captcha.py`
    - `routes/community.py`
    - `routes/trading.py`
    - `routes/comfyui.py`
- `86400`
  - cooldown / staleness / interval ceilings in:
    - `services/trading/admin.py`
    - `services/trading/bots/service.py`
    - `services/trading/bots/workflow.py`
    - `services/server/startup.py`
    - `routes/trading.py`
- `1000`, `200`, `100`, `50`
  - pagination and admin safety limits repeated through many routes

### Recommended centralization

- Trading:
  - `services/trading/constants.py`
  - `services/trading/settings_schema.py`
- Server/admin:
  - `services/platform/settings_schema.py`
  - or `services/server/settings_schema.py`
- UI rate limits and text-size caps:
  - do not centralize blindly unless semantics are truly shared

## 3.4 Silent Fallback Inventory

### Release-blocker style fallback hotspots

- `routes/files.py`
  - multiple `except Exception: pass`
  - high risk because file access, preview, and encrypted-path handling live here
- `routes/comfyui.py`
  - multiple swallowed exceptions inside large route registrar
- `routes/system_admin.py`
  - swallowed exceptions in root/admin operations should be reduced and audited
- `services/trading/engine.py`
  - several swallowed exceptions on critical trading orchestration edges
- `services/points_chain/service.py`
  - many broad catches in ledger/wallet service; not all are wrong, but several need explicit degraded/audit classification
- `services/snapshots/service.py` and `services/snapshots/server_mode.py`
  - broad exception handling remains, though some high-risk restore paths are already explicit

### Acceptable fallback candidates

These are fallback classes that may be acceptable if documented, test-protected, and auditable:

- UI/reference-only price degradation in trading
- notification best-effort delivery
- non-critical report enrichment
- optional external provider metadata fetch

### Degraded fallback candidates

- cached market price for UI display
- websocket transport degradation to HTTP polling with visible warning
- integrity/audit summary helpers that can still return partial status

### Release blocker fallback candidates

- any fallback that lets reference price leak into risk-grade execution
- wallet state accepted without ledger replay verification
- snapshot restore continuing after failed prepare or failed maintenance gate
- root/admin security operations swallowing errors without audit

## Recommended Refactor Order

Because baseline full pytest is red, this is a proposal only.

### Must split now

1. `routes/files.py`
2. `routes/system_admin.py`
3. `routes/comfyui.py`
4. `routes/trading.py`

### High-value service refactor slices

1. `services/trading/engine.py`
   - first slices:
     - `settings_schema.py`
     - `validators.py`
     - `fees.py`
     - `pnl.py`
   - do **not** re-merge reference and risk-grade price paths
2. `services/points_chain/service.py`
   - split ledger replay, wallet mutation, sanctions, catalog/reporting
3. `services/snapshots/server_mode.py`
   - split mode transitions vs production requirements vs tester-token flows

### Large but comparatively cohesive

- `services/trading/price_runtime.py`
- `services/trading/margin.py`
- `services/media/videos.py`

These are large, but already closer to bounded domain modules than the route god files.

## Guardrails For The Actual Refactor Phase

1. Do not start source refactor until the single failing full-suite baseline is understood and either fixed or explicitly waived.
2. Refactor by bounded area only:
   - one route registrar
   - or one validation family
   - or one trading helper family
3. Every fallback change must be classified as:
   - acceptable
   - degraded
   - blocker
4. Keep `reference price` and `risk-grade price` fully separate.
5. Prefer adding Chinese comments only where they explain invariants, historical bugs, or downgrade policy.

## Immediate Follow-up Proposal

1. Stabilize baseline failure in `tests/test_snapshots.py::test_server_mode_v2_root_api_is_root_only_and_exposes_requirements`
2. After baseline is green:
   - `Slice A`: route readability refactor for `routes/system_admin.py`
   - `Slice B`: centralize strict trading settings schema
   - `Slice C`: centralize shared auth/permission/error helpers for route registrars

## Notes

- No source-code behavior change was made in this inventory round.
- `release id sync` was intentionally left untouched in this phase.
