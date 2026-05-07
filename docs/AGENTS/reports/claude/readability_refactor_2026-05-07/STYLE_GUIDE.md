# Style Guide — 註解、命名、helper 慣例

- Date: 2026-05-07
- 對象：本專案所有 Python service / route / pure helper

---

## 1. 註解策略

### 不寫的註解

```python
# 不要寫：
i += 1                # increment i
user = get_user()     # get current user
total = price * qty   # compute total
```

任何「重述程式碼字面行為」的註解，**刪除**。函式/變數名沒表達清楚是命名問題，不是
註解問題。

### 必寫的註解

凡函式落入下列任一類，**必須**有 docstring 說明 invariant：

1. 涉及金額 / 價格 / 手續費 / PnL
2. 寫入 wallet / ledger / chain
3. 觸發 bot / liquidation / margin call
4. 修改 settings 或 server-mode
5. 寫 audit
6. 牽涉 reference vs risk-grade price 區別
7. 任何 retry / idempotent 邏輯
8. 任何 fallback 路徑

### Docstring 範本

```python
def risk_grade_price_for_liquidation(symbol, *, market_def):
    """Return the risk-grade fused price for liquidation / margin / bot triggers.

    Invariant — fail closed:
      - require >= settings.price_fusion_min_provider_count providers
      - require coverage in REFERENCE_PRICE_CAPABLE_PROVIDERS
      - reject stale, deviation, one-sided depth, equal-weight fallback

    Why: a degraded reference price can trigger a wrong liquidation that
    burns user collateral.  Any caller that needs liquidation-grade price
    MUST use this function (not reference_price_for_ui), and MUST be
    prepared for PriceFailClosed.

    Risk: if this function ever silently falls back, the test
    `tests/test_price_fusion_split.py::test_risk_grade_does_not_share_fallback`
    will fail.  Do not regress that test.

    Raises:
        PriceFailClosed: gates not met.  Caller must reject the high-risk
            action with an operator-facing error (see issue #156 for
            an example of a regression where this was silently swallowed).
    """
```

### 行內註解

只在解釋「不能簡化」、「歷史 bug」、「invariant」時寫：

```python
# Wallet is a cache. Ledger replay is the source of truth.
# Any mismatch must be treated as a release blocker before PointsChain Phase 1.
wallet_balance = ledger_replay_balance

# Do not silently fall back to public ticker here.
# Backtests must fail closed when caller supplied isolated candles;
# otherwise synthetic QA inputs can be polluted by real Binance data (issue #97).
```

---

## 2. 命名規範

### 公開 vs 私有

- 模組對外 API：**不加底線**，名稱表達語義（`parse_bool_strict`、`reference_price_for_ui`）
- 模組內 helper：**加底線**（`_normalize_borrow_interest_timing`），且**不被其他模組
  import**

> 目前 `services/trading/validators.py` 全用底線命名但被 13 個模組 cross-import
> （INVENTORY §4.4），是 misleading — slice 2 修。

### Function 命名

- 動詞開頭：`fetch_`、`parse_`、`validate_`、`compute_`、`persist_`、`apply_`
- 純算函式（無 DB / IO）：`compute_*` / `derive_*`
- DB 寫入：`persist_*` / `record_*`
- 驗證：`validate_*` 拋 ValueError；`is_valid_*` 回 bool（無副作用）
- HTTP shape：`build_*_payload` / `serialize_*`

### Class 命名

- service：`*Service`（`TradingEngineService`、`PointsChainService`）
- DTO：`*Payload` / `*Snapshot` / `*Result`
- enum-like：plain class with class-level constants（見 STYLE_GUIDE §4）

### 變數命名

避免泛用 vague 名稱：

| 不要 | 改用 |
|------|------|
| `data` | `payload` / `record` / `row` 視語境 |
| `result` | `position`、`fill`、`audit_record` |
| `info` | `meta` 或具體名 |
| `tmp` | 用真實名（`unfrozen_collateral`） |
| `value` | 同上 |

---

## 3. Validation 集中化

所有 user input：

```python
from services.trading.validators import (
    parse_bool_strict, parse_int_strict,
    parse_decimal_strict, parse_price_float_strict,
)
```

Route handler 第一件事是驗證 + 拋 ValueError → 由 decorator catch → 回 400。

```python
# Good
def admin_settings_update(payload):
    raw = parse_bool_strict(payload.get("audit_chain_enabled"), name="audit_chain_enabled")
    fee = parse_decimal_strict(payload.get("fee_rate_percent"),
                               name="fee_rate_percent", minimum=0, maximum=100)
    ...

# Bad — coerces invalid input to False silently
def admin_settings_update(payload):
    raw = bool(payload.get("audit_chain_enabled"))  # {"x":1} → True
```

DB row：

```python
# Good — explicit "row may be NULL → use 0" semantic
from services.trading.validators import int_or_zero  # （slice 2 新增）
qty = int_or_zero(row, "quantity_units")

# Bad — implicit
qty = int(row["quantity_units"] or 0)
```

---

## 4. Magic value → constants

```python
# services/trading/constants.py（既有）
class PriceSource:
    MANUAL_ROOT = "manual_root"
    FUSED_WEIGHTED = "fused_weighted"
    AUTO_DEPTH = "auto_depth"
    SUPERWEAK = "superweak"
```

caller：

```python
from services.trading.constants import PriceSource

if context["source"] == PriceSource.MANUAL_ROOT:  # typo → AttributeError
    ...

if context["source"] == "manual_root":  # typo "manul_root" → silently skipped
    ...
```

---

## 5. Fallback 顯性化

任何 fallback **必須**：

1. 寫 `audit(...)` 或 `logger.warning(...)` 註明降級
2. 函式名/變數名包含 `degraded` / `fallback` / `partial` 字樣
3. 有對應 test 證明 degraded path 可被 caller 偵測

```python
# Good
try:
    fused = compute_weighted_fused_price(symbol)
    degraded = False
except PriceFusionInsufficient:
    fused = compute_single_provider_fallback(symbol)
    degraded = True
    audit("price.fusion.degraded", symbol=symbol)
return ReferencePrice(value=fused, degraded=degraded)

# Bad
try:
    fused = compute_weighted_fused_price(symbol)
except Exception:
    fused = compute_single_provider_fallback(symbol)  # 沒 audit、沒回報 degraded
return fused
```

---

## 6. Function 大小

- 公開函式：≤ 50 行（target），≤ 100 行（hard ceiling — 超過必須有架構說明）
- helper：≤ 30 行
- mixed-concern 4 件事（DB + 計算 + audit + HTTP shape）的函式 → 拆 3 層
  （`_validate_*` / `_compute_*` / `_persist_*`）

> 目前 7 個 mixed-concern function（INVENTORY §2 表）都需 slice 7 處理。

---

## 7. Bare `except:` 禁止

`except:` 連 `KeyboardInterrupt` 都吞 — 任何人寫了，PR review **拒絕 merge**。

例外：CI / 啟動 script 內的 final-stage cleanup 可寫 `except BaseException:` 但需註解
寫明為什麼。

```python
# routes/users.py:1723 (bad — 目前的)
except:
    pass

# Good
except (ValueError, KeyError, sqlite3.Error) as exc:
    audit("user.delete.cleanup_failed", error=str(exc))
```

---

## 8. 測試命名

testname 必須說明 business rule，不是 test 對象的 module / function：

```python
# Good
def test_risk_grade_price_fails_closed_when_provider_count_below_min():
def test_share_page_uses_external_js_so_csp_does_not_block():
def test_workflow_bot_step_counter_audits_when_exhausted_not_silent():

# Bad
def test_fetch_weighted_fused_price_points():
def test_shared_video_html():
def test_workflow_action_select():
```

---

## 9. Decimal vs float

**所有金額 / 價格 / 手續費 / PnL 的最終計算**：用 `Decimal`。

```python
# Good
from decimal import Decimal
fee = Decimal(quantity) * Decimal(price) * Decimal(fee_rate_bps) / Decimal(10000)
return int(fee.quantize(Decimal("1")))  # round to integer points

# Bad
fee = quantity * price * fee_rate / 10000  # float multiplication
return int(round(fee))  # rounding error accumulates
```

`float` 僅用於：UI 顯示、stat / metric、非金額的 ratio（例：cache hit rate）。

> 目前 `services/trading/` 共 350 處 `float(`、95 處 `Decimal(`（INVENTORY §4 數字）。
> 並非全部都該改 — 但**所有金額 critical path** 應該。slice 7 中順道盤點。

---

## 10. Commit 訊息規格

每 commit 必有：

```
<type>(<scope>): <one-line summary>

Changed:
  - file:line summary
  - ...
Why: <one-paragraph reason; cite issue # if applicable>
Behavior change: yes/no
Tests:
  - <command 1>
  - <command 2>
Risk: <low/medium/high>
Rollback: <how>
```

`type` ∈ `refactor / fix / feat / test / docs / chore`。

`refactor + fix + feat` **不可同 commit**。`refactor` 必須 `Behavior change: no`。

---

## End — 進入 MODULE_SPLIT_PROPOSAL.md 看具體模組拆分
