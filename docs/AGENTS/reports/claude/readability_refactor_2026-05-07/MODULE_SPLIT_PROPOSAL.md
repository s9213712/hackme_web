# Module Split Proposal — engine.py / price_runtime.py / route 大檔

- Date: 2026-05-07
- 對應：REFACTOR_PLAN.md slice 4 / 5 / 6
- 原則：**只搬位置，不改 SQL / 不改公開 API**

---

## §1. `services/trading/engine.py`（3,983 行）

### 現況

```
services/trading/engine.py
├── module-level helpers (L1-810)
├── ensure_trading_schema (L812-1551)            ← 740 行 / 77 SQL 語句
├── module-level helpers cont. (L1551-1553)
├── class TradingEngineService (L1554-3983)      ← 2,430 行 / 288 methods
└── (end)
```

### 目標切分（slice 4 + slice 5 完成後）

```
services/trading/
├── engine.py                               ← 收斂為 ~500 行：class definition + thin orchestration
├── migrations/                              ← slice 4
│   ├── __init__.py                          # MIGRATIONS = [...]
│   ├── m_001_create_markets.py
│   ├── m_002_create_orders_positions.py
│   ├── m_003_funding_columns.py
│   ├── m_004_margin_collateral.py
│   ├── m_005_bots_workflow.py
│   ├── m_006_price_provider_health.py
│   ├── m_007_idempotency_table.py
│   ├── m_008_audit_columns.py
│   └── ... (一個 logical migration 一檔)
├── engine_orderbook.py                      ← matching engine（L1691, L1718 起的 38+26 行 method 群）
├── engine_market_price.py                   ← _attach_market_price_contexts、_market_supports_reference_price
├── engine_funding.py                        ← settle_funding_adjustment、publish_funding_rate_snapshot
└── engine_volume.py                         ← _record_user_trade_volume、record_backtest_capacity_measurement
```

### 拆檔判準

把 method 依「資料族」拆。下例：

| 新檔 | 來自 engine.py 哪些 method |
|------|------------------------------|
| `engine_orderbook.py` | `_matching_orderbook_*`、`_position` |
| `engine_market_price.py` | `_market_supports_reference_price_*`、`_list_reference_price_market_symbols`、`_attach_market_price_contexts`、`_price_context_risk_grade_usable`、`_assert_price_meta_allows_high_risk_use` |
| `engine_funding.py` | `publish_funding_rate_snapshot`、`settle_funding_adjustment` |
| `engine_volume.py` | `_record_user_trade_volume`、`record_backtest_capacity_measurement`、`_spot_summary_payload`、`_notify_insufficient_balance` |

新檔內**仍是同一個 `TradingEngineService` class** — 用 mixin pattern：

```python
# services/trading/engine_orderbook.py
class OrderbookMixin:
    def _matching_orderbook_apply_order(self, ...): ...
    def _matching_orderbook_hydrate(self, ...): ...
```

```python
# services/trading/engine.py
from services.trading.engine_orderbook import OrderbookMixin
from services.trading.engine_market_price import MarketPriceMixin
from services.trading.engine_funding import FundingMixin
from services.trading.engine_volume import VolumeMixin

class TradingEngineService(
    OrderbookMixin, MarketPriceMixin, FundingMixin, VolumeMixin,
):
    def __init__(self, ...): ...
    # core orchestration only
```

**不**改 caller import。`from services.trading.engine import TradingEngineService` 完全相容。

### Risk

- Mixin 順序錯會破壞 method override → CI 測試保護
- 跨檔 method 互呼叫時的 `self.*` 不會出問題（Python MRO 處理）
- ★ 原本 method-level `_helper` 變成 mixin 之間共用，視為 protected — 規範以
  `_` 開頭、不從外部 import

### Rollback

每 mixin 一個 commit，獨立 revert。

---

## §2. `services/trading/price_runtime.py`（1,911 行 / 9 個 >=50 行 function）

### 現況

```
services/trading/price_runtime.py
├── build_price_context (L14-86)                       73 行
├── stored_market_price_contexts (L89-147)             59 行
├── provider_orderbook_with_fallback (L184-243)        60 行
├── transport_state_from_provider_rows (L373-453)      81 行
├── build_orderbook_snapshot (L456-524)                69 行
├── fetch_weighted_fused_price_points (L527-1248)     722 行  ★ 最長
├── root_price_fusion_status_on_conn (L1251-1400)     150 行
├── get_live_market_quote (L1403-1477)                 75 行
└── current_market_price_points (L1573-1911)          339 行  ★ 第二長
```

### 目標切分（slice 5 — 「reference vs risk-grade」拆）

```
services/trading/price_fusion/                  ← 已存在（codex slice 1）
├── __init__.py
├── context.py                                  ← build_price_context 已 here?（驗證）
├── orderbook.py                                ← provider_orderbook_with_fallback、build_orderbook_snapshot
├── weights.py                                  ← weight 計算
├── reference.py                                ← NEW：唯一的 reference API
├── risk_grade.py                               ← NEW：唯一的 risk-grade API（fail closed）
├── transport.py                                ← transport_state_from_provider_rows、stored_market_price_contexts
└── shared.py                                   ← 共用 provider rotation
```

### `reference.py` 內容（提案）

```python
"""Reference price API — UI / preview / non-critical use only.

Allows partial coverage and provider degradation; returns explicit
`degraded` flag so callers can show yellow-light status to users.
"""

from dataclasses import dataclass

@dataclass(frozen=True)
class ReferencePrice:
    points: int
    source: str             # PriceSource.* constant
    provider_count: int
    degraded: bool          # True iff fewer providers than min, etc.
    degraded_reason: str    # human-readable for UI
    last_update_at: str

def reference_price_for_ui(symbol: str, *, market_def) -> ReferencePrice:
    """Never raises. Always returns a ReferencePrice (possibly degraded)."""
```

### `risk_grade.py` 內容（提案）

```python
"""Risk-grade price API — liquidation / margin / bot trigger.

**Fail closed**: any breach of provider count / coverage / staleness /
deviation / one-sided depth / equal-weight fallback raises
PriceFailClosed.  Caller MUST surface the failure to the user, never
silently fall back to reference price.
"""

from dataclasses import dataclass

class PriceFailClosed(RuntimeError):
    pass

@dataclass(frozen=True)
class RiskGradePrice:
    points: int
    source: str             # always PriceSource.FUSED_WEIGHTED
    provider_count: int     # always >= settings.price_fusion_min_provider_count
    last_update_at: str

def risk_grade_price_for_liquidation(symbol: str, *, market_def) -> RiskGradePrice:
    """Raises PriceFailClosed on any gate breach.  Never degraded."""
```

### 拆解後 `fetch_weighted_fused_price_points`（722 行 → ≤80 行）

```python
def fetch_weighted_fused_price_points(symbol, *, purpose, market_def):
    if purpose == "reference":
        return reference_price_for_ui(symbol, market_def=market_def).points
    if purpose == "risk_grade":
        return risk_grade_price_for_liquidation(symbol, market_def=market_def).points
    raise ValueError(f"unknown purpose: {purpose}")
```

舊行為：靠 caller 字串關鍵字決定 fallback。  
新行為：**Type system 強制**。

### Risk

最高。每個 caller 需驗證自己的 purpose 是否正確（reference vs risk_grade）。
**slice 5 不 migrate caller**，只新增 reference.py / risk_grade.py 雙 API；caller migrate
分到 slice 5b（每個 caller 一個 commit）。

---

## §3. Route container 拆檔（slice 6）

### `routes/comfyui.py`（4,585 行）

```
routes/comfyui/
├── __init__.py                  # register_comfyui_routes(app, deps): ~80 行 dispatcher
├── workflow.py                  # /api/comfyui/workflow/*
├── generation.py                # /api/comfyui/generations/*
├── model.py                     # /api/comfyui/models/*
├── preset.py                    # /api/comfyui/presets/*
└── civitai.py                   # /api/comfyui/civitai/*
```

每 submodule 暴露 `register_*_routes(app, deps)`，由 `__init__.py` 順序呼叫。

### `routes/files.py`（3,594 行）

```
routes/files/
├── __init__.py
├── upload.py                    # POST /api/files
├── download.py                  # GET /api/files/<id>/download
├── share.py                     # /api/files/<id>/share-link
├── quota.py                     # /api/files/quota、/api/files/quota-upgrade
├── albums.py                    # /api/storage-albums/*
└── privacy.py                   # privacy-mode 切換、e2ee envelope
```

### `routes/system_admin.py`（3,240 行）

```
routes/system_admin/
├── __init__.py
├── server_mode.py               # /api/admin/server-mode
├── settings.py                  # /api/admin/settings
├── snapshots.py                 # /api/admin/snapshots
├── integrity.py                 # /api/admin/integrity-guard
└── audit.py                     # /api/admin/audit/*
```

### `routes/community.py`（2,322 行）

```
routes/community/
├── __init__.py
├── threads.py
├── replies.py
├── moderation.py
└── search.py
```

### `routes/trading.py`（1,952 行）

```
routes/trading/
├── __init__.py
├── orders.py                    # /api/trading/orders
├── bots.py                      # /api/trading/bots
├── dashboard.py                 # /api/trading/dashboard
├── live_price.py                # /api/trading/live-price
├── backtest.py                  # /api/trading/backtest
└── margin.py                    # /api/trading/margin
```

### `routes/users.py`（1,769 行）

```
routes/users/
├── __init__.py
├── self_service.py              # 一般 user 自己的 /api/users/me、修改密碼等
├── admin_user.py                # /api/admin/users/*（admin 操作）
└── soft_delete.py               # 整 233 行 soft_delete_user_row 與相關 admin route
```

### Risk

低（純 mechanical move），但 PR diff 大 — **一次只拆一個 closure**。每個拆分一個獨立
commit；commit message 寫「No behavior change — closure split only」+ 列出舊 → 新檔
mapping。

---

## §4. `ensure_trading_schema` 拆 migration（slice 4 細節）

### 現況：740 行、77 個 SQL 語句

問題：

- 新 migration 加在哪個 if 分支靠 reviewer
- 改舊 migration 沒有 audit trail（git blame 看 740 行 function 看不出單一 migration 的歷史）
- 部分 migration 有 try/except guard（idempotent），部分沒有 — 不一致

### 目標

```
services/trading/migrations/
├── __init__.py                              # MIGRATIONS = [...]
├── _base.py                                 # class Migration: name; apply(conn)
├── m_001_markets_table.py                   # CREATE TABLE markets
├── m_002_orders_table.py                    # CREATE TABLE orders + indexes
├── m_003_positions_table.py                 # CREATE TABLE positions
├── m_004_funding_columns.py                 # ALTER TABLE positions ADD funding_*
├── m_005_grid_bots_tables.py                # CREATE TABLE grid_bots, grid_orders
├── m_006_workflow_bots_tables.py            # CREATE TABLE workflow_bots
├── m_007_margin_collateral_freezes.py       # CREATE TABLE margin_collateral_freezes
├── m_008_idempotency_table.py               # CREATE TABLE trading_operation_idempotency
├── m_009_price_fusion_history.py            # CREATE TABLE price_fusion_history
├── m_010_audit_columns.py                   # ALTER TABLE * ADD audit_*
└── ... 拆到 ~20 個 migration 檔
```

### 規範

每個 migration 檔結構：

```python
"""Migration 003: positions table."""

NAME = "m_003_positions_table"

CREATE_SQL = """
CREATE TABLE IF NOT EXISTS positions (
    ...
);
CREATE INDEX IF NOT EXISTS idx_positions_user ON positions(user_id);
"""

def apply(conn):
    """Idempotent. Safe to run multiple times."""
    conn.executescript(CREATE_SQL)
```

`__init__.py`：

```python
from . import (
    m_001_markets_table,
    m_002_orders_table,
    ...
)

MIGRATIONS = [
    m_001_markets_table,
    m_002_orders_table,
    ...
]
```

`engine.py`：

```python
def ensure_trading_schema(conn):
    """Apply all trading schema migrations in declared order. Idempotent."""
    from services.trading.migrations import MIGRATIONS
    for m in MIGRATIONS:
        m.apply(conn)
```

### 行為驗證

slice 4 動工前：

```bash
sqlite3 /tmp/baseline.db ".schema" > /tmp/baseline_schema.sql  # 從現有 ensure_trading_schema 跑出來
```

動工後：

```bash
sqlite3 /tmp/refactor.db ".schema" > /tmp/refactor_schema.sql
diff /tmp/baseline_schema.sql /tmp/refactor_schema.sql  # 必須完全相同
```

把 diff 結果（empty）附 commit message。

---

## §5. 拆檔的禁忌

1. **不可同時拆 + 修 bug**（commit 規範 §10）
2. **不可改 SQL 字面**（含註解、空白），即使「看起來等價」
3. **不可改 import 路徑語義**（caller `from X import Y` 必須仍能 work；用 `__init__.py`
   re-export 補）
4. **不可同時拆兩個檔**（一個 commit 一個檔）
5. **不可在拆檔 commit 內加 docstring**（docstring 加進另一個 docs commit）
6. **拆檔 commit 必須 100% 由 `git mv` + import 修正組成**（用 `git diff -M` 看到 R100%
   檔案）

---

## §6. 預估時程

| Slice | 範圍 | 估時 | 阻擋條件 |
|------:|------|-----:|----------|
| 2 | strict parser alias + clock | 0.5 day | Phase 0 close |
| 3 | 22 bool callers + 7 _now_text migrate | 1 day | Slice 2 + root 授權（snapshots/service.py:781 行為變化） |
| 4 | ensure_trading_schema → migrations/ | 2 day | Slice 3 + tests pass |
| 5 | reference.py / risk_grade.py 雙 API（不 migrate caller） | 2 day | Slice 4 |
| 5b | caller migrate 到新 API | 4 day（一個 caller 一個 commit） | Slice 5 |
| 6 | 6 個 route closure 各自拆檔 | 6 day（一個 closure 一個 commit） | Slice 5b |
| 7 | 7 個 mixed-concern function 拆 helper | 7 day（一個 function 一個 commit） | Slice 6 |
| 8 | bare except 修 | 0.5 day（root 授權） | 任何時候 |

**總計 ~23 working days**，串行執行。

不可同時開兩 slice。不可在 slice 中途切到別的 slice。

---

## End

回到 INVENTORY.md / REFACTOR_PLAN.md 看其他段。
