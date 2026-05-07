# Refactor Plan — 順序與 rollback

- Date: 2026-05-07
- Builds on: Slice 1 (codex, 2026-05-06)
- Prerequisite: Phase 0 HIGH issues closed（目前 10 個 open，先解 → 再開動工）
- 原則：每 slice 一類事；先測試保護 → 再拆 → 再 commit。
- 每 slice 都需獨立 rollback（一個 commit 內、無跨 slice 依賴）。

---

## 進入動工前（即「Phase 0 解完後」）必跑 baseline

```bash
HACKME_RUNTIME_DIR=/tmp/hr_baseline python -m pytest tests/ -q \
  > /tmp/refactor_baseline.txt 2>&1
python3 scripts/pre_push_checks.py --ci > /tmp/refactor_prepush_baseline.txt 2>&1
git rev-parse HEAD > /tmp/refactor_baseline_commit.txt
```

把 3 個檔附在 slice 1 commit message，作為「behavior 不變」驗證起點。

---

## Slice 2 — Strict bool/int parser 集中（風險最低、覆蓋最廣）

### 動機

22 處重複的 `str(x).strip().lower() in {"1","true","yes","on"}`（INVENTORY §4.1）。
13 處 `_to_int / _to_decimal` 跨模組偷用底線命名（INVENTORY §4.4）。

### 變更

1. 新增 `services/trading/validators.py`（同檔擴充，避免另開 module 增加 import 路徑混亂）：
   - `parse_bool_strict(value, *, default=False, accept_y_t=False)` — return bool；invalid 拋 ValueError
   - `_to_int → parse_int_strict`（保留 `_to_int = parse_int_strict` 作 alias 1 個 release）
   - `_to_decimal → parse_decimal_strict`（保留 alias）
   - `_to_price_float → parse_price_float_strict`（保留 alias）
2. 新增 `services/trading/_clock.py`（純 helper）：
   - `def now_utc_text(): return datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")`
3. 不改任何 caller。本 slice 只是把 helper 命名公開化 + 加 `parse_bool_strict`。

### Tests

```bash
python3 -m pytest tests/ -q -k "validators or settings_schema or trading_engine"
```

新增 `tests/test_validators_strict.py`：

- `parse_bool_strict("on") == True`
- `parse_bool_strict("OFF", default=True) == False`
- `parse_bool_strict("yes") == True`
- `parse_bool_strict("y", accept_y_t=False)` raises ValueError
- `parse_bool_strict(None, default=False) == False`
- `parse_bool_strict({"x":1})` raises ValueError（**不**靜默回 False）
- `parse_int_strict("12.5", name="qty")` raises ValueError
- `parse_decimal_strict("nan")` raises ValueError
- `parse_decimal_strict("inf")` raises ValueError

### Behavior change

**None.** 既有 caller 仍呼叫舊名 `_to_int` 等；新名只是外加 alias。新 `parse_bool_strict`
無 caller，不影響執行路徑。

### Risk

低。只是新增 + alias。

### Rollback

`git revert <slice2-commit>`。

### Commit 範本

```
refactor(trading): publish strict parser names (alias _to_int → parse_int_strict)

Changed: services/trading/validators.py — add public-named aliases
         services/trading/_clock.py — extract _now_text helper
         tests/test_validators_strict.py — strict-parser invariants
Why: 13 caller modules import private-prefixed helpers (INVENTORY §4.4);
     22 sites duplicate bool parsing (§4.1).  Provide public names so
     the next caller doesn't reach for a 4th variant.
Behavior change: no
Tests: pytest tests/test_validators_strict.py + full pytest baseline
Risk: low — additive only, no callers migrated yet
Rollback: git revert HEAD
```

---

## Slice 3 — 全 codebase migrate 到 `parse_bool_strict` / `now_utc_text`

### 變更

1. 22 個 bool-parser 重複位置改 import `parse_bool_strict`（INVENTORY §4.1）
2. 7 個 `_now_text()` 定義刪除，改 import `now_utc_text`（INVENTORY §4.3）

### Tests

```bash
python3 -m pytest tests/ -q
python3 scripts/pre_push_checks.py --ci
```

特別注意：

- `services/snapshots/service.py:781`（INVENTORY §6.3）行為**會改變** — 從「invalid → False」
  變成「invalid → 400 ValueError」。**這一個位置必須單獨 commit + 加 admin migration note**。
  其他 21 處因為 caller 已先 `or ""`，行為等價。

### Behavior change

**21 處等價，1 處（snapshots/service.py:781）會把無效值改為 400 錯誤。** 這一處需要：

- 拆成獨立 commit
- 在 commit message 寫「Behavior change: yes — invalid bool now rejects with 400」
- root 授權確認後再 merge

### Risk

中。22 處改動 + 1 處行為變更。

### Rollback

每位置一 commit，逐個 revert。

---

## Slice 4 — `ensure_trading_schema` 拆 migration

### 動機

`services/trading/engine.py:812-1551`（740 行、77 個 SQL 語句）是新 migration 最常出錯的
位置 — 加在哪個 if 分支、要不要包 try/except、版本號 bump 哪裡都靠 reviewer own knowledge。

### 變更

```
services/trading/migrations/
├── __init__.py                    # MIGRATIONS = [m_001_*, m_002_*, ...]
├── m_001_create_markets.py        # markets table
├── m_002_create_orders.py
├── m_003_create_positions.py
├── m_004_add_funding_columns.py   # ALTER TABLE patches
... (依時間順序，每個 migration 一檔)
```

`ensure_trading_schema(conn)` 變成 30-50 行 dispatcher：

```python
def ensure_trading_schema(conn):
    """Apply all trading schema migrations in order. Idempotent."""
    from services.trading.migrations import MIGRATIONS
    for migration in MIGRATIONS:
        migration.apply(conn)
```

每個 migration 檔內部就是現在的單個 `try / CREATE TABLE / ALTER TABLE` block。

### Tests

```bash
python3 -m pytest tests/test_trading_engine.py -q
python3 -m pytest tests/test_trading_schema.py -q  # 若有
HACKME_RUNTIME_DIR=/tmp/hr_migration python -m pytest tests/ -q
```

新增 `tests/test_trading_migrations.py`：

- `MIGRATIONS` 順序穩定（list 順序 = 名字字典序）
- 對空 DB 跑全部 → schema 與既有 fixture 等同
- 對既有 fixture DB 重跑 → no-op（idempotent）
- 跑兩次（連續）→ 結果相同

### Behavior change

**None.** SQL 語句**不改一個字**，只是搬位置。

### Risk

中。schema migration 改錯會讓 boot 失敗，但測試覆蓋面廣。

### Rollback

```
git revert <slice4-commit>
```

---

## Slice 5 — Reference vs Risk-grade Price 拆模組

### 動機

`fetch_weighted_fused_price_points` 722 行，reference + risk-grade 兩條路在同函式內依
caller 傳入的 `price_purpose` 分支（INVENTORY §8）。任何新 caller 漏設 purpose →
**靜默退化為 reference path 但被當 risk-grade 用**。

### 變更（已部分啟動 — `services/trading/price_fusion/` 已存在）

```
services/trading/price_fusion/
├── __init__.py
├── context.py        # 已存在
├── orderbook.py      # 已存在
├── weights.py        # 已存在
├── reference.py      # NEW — 唯一的 reference price API
├── risk_grade.py     # NEW — 唯一的 risk-grade price API（fail-closed）
└── shared.py         # NEW — 共用的 provider rotation
```

`reference.py` 公開：

```python
def reference_price_for_ui(symbol, *, market_def) -> ReferencePrice:
    """UI / preview only. May degrade to single-provider with warning."""
```

`risk_grade.py` 公開：

```python
def risk_grade_price_for_liquidation(symbol, *, market_def) -> RiskGradePrice:
    """Liquidation / bot trigger / margin only. **Fail closed**."""
    # Asserts min_provider_count + coverage + no stale + no deviation +
    # no equal-weight fallback.  Any breach raises PriceFailClosed.
```

兩個 API **不能互相 substitute** — type system 強制。

### Caller migration（不在本 slice）

`services/trading/engine.py` / `margin.py` / `bots/service.py` / `orders.py` 各自 caller
改用 `risk_grade_price_for_liquidation`，UI route handler 改用 `reference_price_for_ui`。

### Tests

```bash
python3 -m pytest tests/test_trading_reference_prices.py -q
python3 -m pytest tests/ -q -k "price_fusion or weighted"
```

新增 `tests/test_price_fusion_split.py`：

- `reference_price_for_ui` 在 partial coverage 下回傳 degraded warning，**不**拋
- `risk_grade_price_for_liquidation` 在同條件下**拋** `PriceFailClosed`
- 兩個 API **沒有共用的 silent fallback path**（cross-import 即 fail）

### Behavior change

設計上 None — 但因為「拆模組」會逼出 caller 隱性 assumption，可能會發現 bug（這正是
目的）。**任何發現的 bug 不可在本 slice 內 fix**，新開 issue 處理。

### Risk

高。本 slice 是整個 plan 最高風險的一步。

### Rollback

```
git revert <slice5-commit>
```

---

## Slice 6 — `register_*` route container 拆檔

### 動機

`routes/comfyui.py`（4,585 行）、`routes/files.py`（3,594 行）等 6 個 closure 過大檔。
每次 review 都要 scroll 數千行。

### 變更

每個檔案拆成 5–6 個 sub-router，按業務領域：

```
routes/comfyui/
├── __init__.py          # register_comfyui_routes 變成 ≈80 行 dispatcher
├── workflow.py
├── generation.py
├── model.py
├── preset.py
└── civitai.py
```

`register_comfyui_routes(app, deps)` 在 `__init__.py` 內呼叫各 submodule 的 `register_*`。

### Tests

```bash
python3 -m pytest tests/ -q
```

route URL 與 method 不變，所有現有 test 仍綠。

### Behavior change

**None.**

### Risk

低（純 mechanical move），但 PR diff 巨大 — 必須**一次只拆一個 closure**。

### Rollback

每個 closure 一個 commit，逐個 revert。

---

## Slice 7 — Mixed-concern function 拆 helper

### 範圍

INVENTORY §2 列的 7 個 mixed-concern service-layer function：

- `services/trading/margin.py:1114` `close_margin_position`（359 行）
- `services/trading/price_runtime.py:1573` `current_market_price_points`（339 行）
- `services/trading/margin.py:633` `open_margin_position`（323 行）
- `services/trading/orders.py:431` `execute_order`（313 行）
- `services/trading/margin.py:958` `add_margin_collateral`（154 行）
- `services/trading/funding.py:273` `open_root_contract_position`（136 行）
- `services/snapshots/server_mode.py:1617` `switch_mode`（202 行）

每個函式拆 3 層：

1. `_validate_*` — 純 input 檢查，無 DB
2. `_compute_*` — 純算數，無 DB（金額用 Decimal）
3. `_persist_*` — DB transaction + audit
4. 公開函式 = 三層 orchestration（≤30 行）

### Tests

每個拆分**必須**有 before/after 等價測試：

- 既有 `tests/test_trading_engine.py` / `test_trading_margin*.py` 全綠
- 新增 `_validate_*` 與 `_compute_*` 的 unit tests（無 DB）

### Behavior change

**None**（嚴格行為保持）。

### Risk

中。每個拆分都有 transaction frame 風險。一次只動一個函式 + 全 pytest。

### Rollback

每函式一 commit。

---

## Slice 8 — Bare `except:` 修

```
routes/users.py:1723
routes/system_admin.py:1953
routes/public.py:399
```

3 處改為 `except Exception as exc:`，並把 swallowed exception 寫入 audit。

### Behavior change

**Yes**（`KeyboardInterrupt` 不再被吞）。

### Risk

中。需 root 授權，視為 Phase 0 follow-up。

---

## Slice Order Summary

| # | Slice | Risk | Behavior change | 預估 PR diff |
|--:|-------|:----:|:----------------:|:-------------:|
| 2 | Strict parser alias + clock helper | 低 | 否 | ~150 行 |
| 3 | Migrate 22 bool callers + 7 _now_text | 中 | 1 處有 | ~250 行 |
| 4 | ensure_trading_schema 拆 migration | 中 | 否 | ~1500 行 (大量 move) |
| 5 | Reference vs Risk-grade price split | 高 | 否（設計上） | ~800 行 |
| 6 | Route closure 拆 6 個檔案 | 低 | 否 | 一次 1 個 closure，總計 ~20000 行 move |
| 7 | Mixed-concern function helper extract | 中 | 否 | 一次 1 個函式 |
| 8 | Bare except 修（Phase 0 follow-up） | 中 | 是 | ~30 行 |

**強制順序**：2 → 3 → 4 → 5 → 6 → 7 → 8。**不可並行 / 不可亂序。**
原因：3 依賴 2 的 alias；5 在拆 price 前先讓 caller 用得到 strict parser；6 是純 move
不阻擋其他 slice 但 PR diff 大會卡 review。

---

## End — 進入 STYLE_GUIDE.md 看註解 / 命名規範
