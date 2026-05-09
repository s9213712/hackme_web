# Server Mode v2 — Trading + PointsChain Implementation Spec

> **Status (2026-05-05):** Engineering-grade companion spec to [`SERVER_MODE_V2_PROFILE_MATRIX.md`](SERVER_MODE_V2_PROFILE_MATRIX.md). Covers the trading engine + PointsChain behavior under each mode, with hard rules to keep PointsChain uncontaminated.
>
> **Owner:** root (canonical author). Cross-referenced from main mode matrix.

---

## 0. Core Idea

```
Trading      = behavior (orders, matching, positions)
PointsChain  = real ledger (must NOT be polluted)

Every mode design exists to protect PointsChain.
```

---

## 1. Architecture

```
                ┌──────────────┐
                │ Trading Engine│
                └──────┬───────┘
                       │
        ┌──────────────┼──────────────┐
        │                             │
┌──────────────┐              ┌──────────────┐
│ Shadow World │              │ Production   │
│ (internal_test)│             │ World        │
└──────────────┘              └──────────────┘
        │                             │
 test_shadow_* tables        real tables
        │                             │
        └──────────────┬──────────────┘
                       │
                PointsChain (production only)
```

Two engines must be implemented separately:

| Mode | trading backend |
|---|---|
| `production` | `real` |
| `internal_test` | `shadow` (isolated matching, isolated positions, isolated ledger) |
| `test` | `isolated` (whole isolated runtime) |
| `dev_ready` | `disabled` |
| `maintenance` / `incident_lockdown` | trading off (read-only for audit) |
| `superweak` | trading + economy both off |

---

## 2. Hardwired Rule: PointsChain only in `production`

```yaml
points_chain:
  production:
    enabled: true
  internal_test:
    enabled: false   # MUST NOT write production chain
  test:
    enabled: false
  dev_ready:
    enabled: false
  maintenance:
    enabled: false   # writes paused; reads ok for verify
  incident_lockdown:
    enabled: false
  superweak:
    enabled: false
```

Any non-`production` mode that writes to `points_chain_blocks` is a **release blocker**.

---

## 3. Per-Mode Trading Spec

### 3.1 `internal_test` (most important)

```yaml
internal_test_trading:
  orders:
    table: test_shadow_orders
  positions:
    table: test_shadow_positions
  wallets:
    table: test_shadow_wallets
  ledger:
    table: test_shadow_ledger
  matching_engine:
    isolated: true
  liquidation_engine:
    source: test_shadow_positions
    must_not_touch: production_positions
```

**Constraints (hard rules)**:

```yaml
constraints:
  must_not_write:
    - points_ledger
    - points_chain_blocks
    - wallets (production)
    - orders (production)
    - positions (production)
  must_not_affect:
    - liquidation_engine_production
    - funding_rate_production
    - matching_engine_production
```

**Price source (critical)**:

```yaml
price_source:
  reference_price:
    source: production_market_data
    readonly: true            # tester can READ live prices
  risk_price:
    mode: simulated OR reference   # but writes never affect prod price
```

Tester actions **never** influence the production market price feed.

### 3.2 `test` (isolated QA)

```yaml
test_trading:
  backend: isolated
  constraints:
    - must_not_connect_production_db: true
    - must_not_use_real_points_chain: true
    - must_run_in_isolated_runtime: true     # docker / tmp / separate host
```

In `test` mode the entire runtime is isolated (separate DB, separate runtime/, separate cache namespace), so even though trading is "real" inside that runtime, it has no path to production data.

### 3.3 `production`

```yaml
production_trading:
  orders: orders
  positions: positions
  wallets: wallets
  ledger: points_ledger
  points_chain:
    enabled: true
    strict_hash_validation: true
```

**Hardwired rules**:

```yaml
rules:
  - every_wallet_change_must_emit_ledger_entry: true
  - every_ledger_entry_must_link_chain_block: true
  - chain_hash_must_match_previous: true
  - reject_writes_when_chain_state_unverified: true
```

Boot path: PointsChain must verify hash chain on startup; failure → `incident_lockdown`.

### 3.4 `maintenance`

```yaml
maintenance_trading:
  trading_enabled: false
  allowed_operations:
    - read_positions
    - audit_wallets
    - verify_chain
    - export_ledger
```

Trading writes paused; auditing / verification permitted.

### 3.5 `incident_lockdown`

```yaml
incident_trading:
  trading_enabled: false
  allowed_operations:
    - read_only_wallet
    - audit_chain
    - export_ledger
  forbidden:
    - any_state_mutation
```

Read-mostly, no mutation.

### 3.6 `superweak`

```yaml
superweak_trading:
  trading_enabled: false
  economy_enabled: false
```

Trading **must be off** in `superweak`; opening it = unrecoverable disaster (no audit chain, no integrity guard, dirty ephemeral data hits real economy).

### 3.7 `dev_ready`

```yaml
dev_ready_trading:
  backend: disabled
  feature_trading_enabled: false
```

Trading off by default in dev. If a developer needs to QA trading flow, switch to `internal_test` (shadow) or `test` (isolated runtime).

---

## 4. DB Schema (split worlds)

### Production tables (only `production` mode writes)

```
wallets
points_ledger
points_chain_blocks
orders
positions
```

### Shadow tables (`internal_test` writes; tester-scoped)

```
test_shadow_wallets
test_shadow_ledger
test_shadow_orders
test_shadow_positions
```

### Recommended DB-level guard (defensive)

```sql
-- Pseudocode (sqlite trigger flavor)
CREATE TRIGGER forbid_shadow_write_to_prod_wallets
BEFORE INSERT ON wallets
WHEN (SELECT current_mode FROM server_modes WHERE id=1)
        IN ('internal_test', 'test', 'superweak', 'dev_ready')
   OR (SELECT actor_role FROM session_state WHERE id=1) = 'tester'
BEGIN
    SELECT RAISE(ABORT, 'tester / non-production mode cannot write production wallet');
END;
```

(Equivalent triggers for `points_ledger`, `orders`, `positions`. Implementation note: SQLite triggers can read session-scoped state via app-level `PRAGMA` shims; in PostgreSQL deployments use `current_setting('app.mode')` patterns directly.)

---

## 5. Matching / Liquidation / Funding — Isolated Engines

Cross-world contamination is the #1 fatal-bug class. Hard rules:

```yaml
matching_engine:
  production:
    queue: matching_prod
  internal_test:
    queue: matching_shadow
  test:
    queue: matching_test_<runtime_id>

liquidation_engine:
  production:
    source: real_positions
    sink: real_wallets + real_ledger + real_chain
  internal_test:
    source: shadow_positions
    sink: shadow_wallets + shadow_ledger
    must_not_read: real_positions
    must_not_write: real_wallets

funding_rate:
  production:
    source: real_market_data + real_positions
  internal_test:
    source: simulated OR readonly_reference
    must_not_publish: real_funding_channel
```

A worker that subscribes to *both* `matching_prod` and `matching_shadow` is a **release blocker**: events crossing channels can fire production liquidation on shadow positions.

---

## 6. Cache / Queue Isolation (重申)

Per [`SERVER_MODE_V2_PROFILE_MATRIX.md §Cache / Job / Queue Isolation`](SERVER_MODE_V2_PROFILE_MATRIX.md#cache--job--queue-isolation):

```
orderbook:prod:BTC          # production
orderbook:test:BTC          # test runtime
orderbook:testerA:BTC       # internal_test, tester A's shadow
```

**Never** merge namespaces. Any helper that builds cache keys must accept `mode` + `tester_id` and refuse to emit a key without them.

---

## 7. Common Fatal Mistakes (must NOT happen)

| # | Mistake | Why fatal |
|---|---|---|
| 1 | Shadow trade triggers production liquidation | direct contamination of production wallets |
| 2 | Tester wallet write reaches `points_chain_blocks` | unrecoverable chain pollution; restore is the only fix |
| 3 | Shared Redis key (`orderbook:BTC` instead of scoped) | one mode's order book overwrites another's |
| 4 | Shared funding rate channel | shadow funding leaks into production positions |
| 5 | `internal_test` trades evaluate against production matching engine | production sees synthetic flow as real |
| 6 | `superweak` accidentally opens trading / economy | broken security layers + real ledger writes = total compromise |
| 7 | Test mode runs against production DB | test fixtures wipe / corrupt production data |

Each of the above is a **release blocker** if found in code review or QA.

---

## 8. QA Acceptance (must pass before release)

```yaml
qa:
  - tester_trade_does_not_change_production_wallet
  - tester_trade_does_not_write_points_chain
  - production_trade_updates_chain_correctly
  - liquidation_does_not_cross_world
  - restore_recovers_chain_integrity
  - funding_rate_does_not_cross_world
  - matching_engine_namespaces_separate
  - cache_keys_carry_mode_scope
  - superweak_trading_remains_disabled
```

These extend the §QA Acceptance Checklist in the main mode matrix. Implementation in `tests/` is required before opening a Phase 7 / Trading-related production gate.

---

## 9. Cross-references

| 文件 | 角色 |
|---|---|
| [`SERVER_MODE_V2_PROFILE_MATRIX.md`](SERVER_MODE_V2_PROFILE_MATRIX.md) | parent mode spec; this doc 是 trading/chain 子規範 |
| [`BLOCKCHAIN/POINTSCHAIN_ENGINEERING.md`](../archive/research/BLOCKCHAIN/POINTSCHAIN_ENGINEERING.md) | PointsChain v2 chain block + hash chain spec |
| [`BLOCKCHAIN/POINTS_TRANSFER_API.md`](../archive/research/BLOCKCHAIN/POINTS_TRANSFER_API.md) | Phase 3 transfer API (must respect production-only chain rule) |
| [`BLOCKCHAIN/MULTISIG_WALLETS.md`](../archive/research/BLOCKCHAIN/MULTISIG_WALLETS.md) | Phase 4 multisig (only valid in production) |
| [`BLOCKCHAIN/POINTSCHAIN_QA.md`](../archive/research/BLOCKCHAIN/POINTSCHAIN_QA.md) | per-phase chain QA gate |
| [`08_TRADING_ENGINE.md`](../08_TRADING_ENGINE.md) | trading engine user/admin facing doc |

---

## 10. Final Statement (engineering version)

```
Trading can be fake.
PointsChain absolutely cannot be faked, must not be touched.
```

Any pull request that contradicts this — for any "convenience" — is a release blocker.
