# Code Inventory — Readability / Refactor Slice 2 Audit

- Agent: claude (Opus 4.7)
- Date: 2026-05-07
- Branch: `03.Points` (working tree)
- Scope: `services/`, `routes/`, `server.py`, `public/js/` (size only)
- Behavior change: **None proposed in this round.** Per project rule “Phase 0 blocker
  尚未全 close”時，本 slice 僅產出 docs（10 個 HIGH issues 仍 open，見最末節）。
- Builds on prior slice: codex `services_refactor_slice1_trading_helpers_20260506_020103`
  已抽出 `services/trading/{constants,validators,accounting/*}`. 本報告**不重複**
  Slice 1 已搬走的內容，只列出之後仍存在的問題。

---

## 0. Why this report exists

本檔不是「代碼風格 nitpick」清單，而是**找出最容易在未來造成 bug 的結構性問題**：

1. 過大檔案 / 過大函式 → reviewer 看不完，行為變更被埋進 PR
2. 同一語義在多處解析（bool、int、Decimal） → 任一處出錯就有 inconsistent 行為
3. silent fallback / coerce-to-default → invalid input 被吃成 0 / False，下游算出錯誤金額
4. reference-price 與 risk-grade-price 邏輯混在同一個 caller-無感知的函式 →
   strong-confidence path 退化為 weak-confidence path 而 caller 不知
5. 註解極少（services 1.7%、routes 0.9% docstring coverage），維護者不知「為什麼這樣寫」

---

## 1. 巨大檔案（>= 800 行 source code）

僅列 `services/` + `routes/` + `server.py`（Python source）；UI bundle (`public/js/*.js`)
已知大但本 slice 不處理。

| Lines | File | Risk | 建議拆分 |
|------:|------|------|----------|
| 4,585 | `routes/comfyui.py` | 1 個 4,471 行 closure (`register_comfyui_routes`) | 依「workflow / generation / model / preset / civitai」拆 5 個 routes/comfyui_*.py |
| 3,983 | `services/trading/engine.py` | `class TradingEngineService` 2,430 行/288 methods + `ensure_trading_schema` 740 行 | 見 MODULE_SPLIT_PROPOSAL.md §1 |
| 3,594 | `routes/files.py` | 1 個 3,485 行 closure | 依「upload / download / share / quota / albums / privacy」拆 6 個 |
| 3,240 | `routes/system_admin.py` | 1 個 2,998 行 closure | 依「server-mode / settings / snapshots / integrity / audit」拆 5 個 |
| 2,322 | `routes/community.py` | 1 個 2,311 行 closure | 依「threads / replies / moderation / search」拆 4 個 |
| 2,317 | `services/points_chain/service.py` | sealed-ledger + recovery + 兌換 | 依「ledger / sealing / recovery / wallet」拆 4 個 |
| 2,033 | `services/snapshots/server_mode.py` | mode 切換 + bypass token + drain | 已有 `services/snapshots/server_mode/` 跡象，繼續拆 |
| 1,952 | `routes/trading.py` | 1,895 行 closure；含 6-provider price fallback (#174) | 依「orders / bots / dashboard / live-price / backtest / margin」拆 6 個 |
| 1,911 | `services/trading/price_runtime.py` | 含 722 行 `fetch_weighted_fused_price_points` + 339 行 `current_market_price_points` | 見 MODULE_SPLIT_PROPOSAL.md §2 |
| 1,769 | `routes/users.py` | 包含 admin / soft-delete / item mutate 三組權限路徑 | 拆 user / admin_user / soft_delete |
| 1,675 | `services/trading/margin.py` | open / close / liquidate / collateral / risk_payload 在同檔 | 依「lifecycle / risk / collateral」拆 3 個 |

完整名單（含 1,000–1,600 行的 11 個檔）見附錄 A。

---

## 2. 巨大函式（>= 100 行）

共 **102 個** 函式 >= 100 行。Top 15 依下：

| Lines | Location | Function | 主要問題 |
|------:|----------|----------|----------|
| 4,471 | `routes/comfyui.py:115` | `register_comfyui_routes` | route container（拆檔即拆函式） |
| 3,485 | `routes/files.py:110` | `register_file_routes` | 同上 |
| 2,998 | `routes/system_admin.py:243` | `register_system_admin_routes` | 同上 |
| 2,311 | `routes/community.py:12` | `register_community_routes` | 同上 |
| 1,895 | `routes/trading.py:58` | `register_trading_routes` | 同上 |
| 1,479 | `routes/videos.py:51` | `register_video_routes` | 同上 |
| 740 | `services/trading/engine.py:812` | `ensure_trading_schema` | **77 個 migration 語句**塞在一個 function；新 migration 需先讀完整 740 行才能放對位置 |
| 722 | `services/trading/price_runtime.py:527` | `fetch_weighted_fused_price_points` | reference + risk-grade 兩條路在同函式內分支；caller 拿到的「分」與「級」靠關鍵字決定 |
| 669 | `services/snapshots/schema.py:550` | `ensure_snapshot_schema` | 同 trading schema 模式 |
| 459 | `security/trading_exchange_validation.py:124` | `validation_scenarios` | scenarios 寫成一個函式而非 data table |
| 412 | `routes/reports_notifications.py:17` | `register_reports_notification_routes` | route container |
| 401 | `services/trading/backtest.py:223` | `backtest_trading_bot` | 同時做 candle prep / strategy run / fee calc / report |
| 359 | `services/trading/margin.py:1114` | `close_margin_position` | DB + 計算 + audit + HTTP-shape 四件事 |
| 339 | `services/trading/price_runtime.py:1573` | `current_market_price_points` | 同 fetch_weighted_fused…，但更小 |
| 323 | `services/trading/margin.py:633` | `open_margin_position` | 同上 |

### Service 層 mixed-concern 函式（DB + 計算 + audit + 驗證 在同一個 >=100 行函式）

| Lines | Location | Function |
|------:|----------|----------|
| 359 | `services/trading/margin.py:1114` | `close_margin_position` |
| 339 | `services/trading/price_runtime.py:1573` | `current_market_price_points` |
| 323 | `services/trading/margin.py:633` | `open_margin_position` |
| 313 | `services/trading/orders.py:431` | `execute_order` |
| 202 | `services/snapshots/server_mode.py:1617` | `switch_mode` |
| 154 | `services/trading/margin.py:958` | `add_margin_collateral` |
| 136 | `services/trading/funding.py:273` | `open_root_contract_position` |

這些是**架構性 bug 最常出現的位置** — 因為 DB transaction、金額計算、audit 寫入、HTTP
回應 shape 全擠在同一個 transaction frame 內，任何一處 fix 都可能誤動其他三件。

---

## 3. 過深 nesting（depth >= 6）

共 3 處：

| Depth | Location |
|------:|----------|
| 29 | `services/platform/bootstrap.py:618` `apply_schema_migrations` |
| 14 | `routes/trading.py:276` `service_error` |
| 10 | `security/trading_stress_pentest.py:800` `run_mode` |

`apply_schema_migrations` 的 depth 29 是 outlier — 應立即驗證為何 AST nesting 達到該深度
（可能是 try/except 巢狀於多層 if/with 內），即使行為正確，後人讀不懂。

---

## 4. 重複邏輯（高優先抽共用）

### 4.1 Bool 解析：22 處重複，13 個檔案

完全相同模式 `str(x).strip().lower() in {"1","true","yes","on"}`：

```
services/platform/settings.py:357
services/platform/bootstrap.py:71
services/server/runtime.py:192
services/server/startup.py:387
services/snapshots/service.py:781
routes/videos.py:115
routes/trading.py:626, 1002
routes/system_admin.py:65, 1599, 2528
routes/users.py:698
routes/reports_notifications.py:379
routes/files.py:452, 1147, 1266, 1675, 2252, 2453, 3317
routes/comfyui.py:872
```

**已存在但未統一使用**：`services/trading/settings_schema.py:11` 定義了
`TRUE_VALUES = {"true", "1", "yes"}` 與 `raw_bool_setting`，但 22 個重複位置沒有引用它。

差異點：

- 有人接 `{"y","t"}`、有人不接（`platform/settings.py` vs `bootstrap.py`）
- 有人 `.strip()`、有人沒有
- 有人對 `None` 先 `or ""`、有人對 `None` 沒處理（`reports_notifications.py:379` 直接
  `request.args.get("unread") in {"1","true","yes"}` — `None` 不會 match，行為其實正確
  但仰賴讀者 own knowledge）

→ **抽 `parse_bool_strict(raw, *, default=False, accept_y_t=True)` 集中處理**，並要求
所有 22 個位置改 import。

### 4.2 `int(x or 0)` 模式：342 處

幾乎所有 service 層 DB row 處理都用 `int(row["foo"] or 0)`，把 `NULL` / 空 string 當 0。
本身不是錯，但問題是 **同樣的 row 用 `_to_int(row["foo"], name="foo", minimum=0)`**
在某些金額 critical path 也存在（`services/trading/validators.py:7`）。

→ **business rule**：DB row + 金額欄位 ≠ user input。前者用 `int_or_zero(row, key)`
（明確語義：欄位允許 NULL → fallback 0）；後者用 `_to_int` strict（user input 不允許
NULL）。目前兩者混用 → 寫一個 helper 文件規範哪些路徑用哪個。

### 4.3 `_now_text()` 重複定義 7 次

```
services/trading/funding.py:20
services/trading/verification.py:11
services/trading/markets.py:25
services/trading/orders.py:21
services/trading/bots/service.py:42
services/trading/margin.py:37
services/trading/grid.py:17
```

完全相同實作。直接抽到 `services/trading/_clock.py` 或塞到既有 `validators.py` 末端。

### 4.4 跨模組偷用 `_to_int` / `_to_decimal` / `_to_price_float`

`services/trading/validators.py` 內所有函式以 `_` 開頭（Python 慣例 = 模組私有），
但被 13 個檔案 cross-import：

```
$ grep -rE "from services.trading.validators import" --include="*.py" | wc -l
13
```

這是 misleading API。要嘛改名（拿掉 `_`）公開化、要嘛加 `__all__` 明示對外。
建議改名（`_to_int → parse_int_strict`、`_to_decimal → parse_decimal_strict`）並
保留舊名 alias 一個 release。

### 4.5 Role 判斷：9 處

```
$ grep -rnE "role\s*[!=]=\s*['\"](root|admin|manager|user)" --include="*.py" services/ routes/ | wc -l
9
```

大多數其他 role check 已透過 `services/users/auth.py` decorator。剩下 9 處應改用
decorator 或統一 helper（`is_root_actor(actor)`、`is_at_least_admin(actor)`）。

---

## 5. Magic Numbers / Magic Strings

### 已集中（slice 1 成果，不重做）

`services/trading/constants.py`（67 行）已收：
- `ASSET_SCALE = 100_000_000`
- `DEFAULT_SPOT_FEE_RATE_PERCENT = 0.10`
- `TRADING_BOT_AUDIT_INTERVAL_SECONDS = 300`
- `TRADING_BOT_AUDIT_MIN_ENABLED_SECONDS = 86_400`
- `UNLIMITED_BOT_MAX_RUNS = 2_147_483_647`
- 其餘 trading 相關常數

### 仍散落

| Constant | 出現位置 | 建議 |
|----------|---------|------|
| `0.001 / 0.003 / 0.005`（spot fee 子率） | `services/trading/orders.py`、`grid.py`、`backtest.py` | 抽 `FEE_TIER_BPS`、由 catalog 取出 |
| `300 seconds` (cooldown) | `services/trading/bots/service.py:670`（issue #165 用 datetime.now()） | 已是常數但 timezone 處理是 #165 範圍 |
| `10000ms` (fetch timeout) | `public/js/shared-video.js`、`39-videos.js` | 抽 JS constants 模組 |
| `40%`、`100 levels`（grid） | `services/trading/grid.py` | 抽 `GRID_*` 常數 |
| `"manual_root"`、`"fused_weighted"`、`"auto_depth"`、`"superweak"`、`"incident_lockdown"` | `services/trading/price_runtime.py`、`engine.py`、`server_mode.py` | 抽 enum 或 frozenset；目前是字串字面量在多處比較，typo 不會 fail |

### Magic string 的真正風險

`"manual_root"` 在 `services/trading/price_runtime.py:1718, 1742, 1853` 各出現一次；
typo 變成 `"manul_root"` 時編譯不會錯、tests 若沒涵蓋該 branch 也不會 fail。
→ 建議：

```python
# services/trading/constants.py
class PriceSource:
    MANUAL_ROOT = "manual_root"
    FUSED_WEIGHTED = "fused_weighted"
    AUTO_DEPTH = "auto_depth"
    SUPERWEAK = "superweak"
```

---

## 6. Silent Fallback 位置

### 6.1 Bare except（極危險，不可有）

```
routes/users.py:1723         except:
routes/system_admin.py:1953   except:
routes/public.py:399          except: return json_resp({"ok":False,"msg":"Invalid JSON"}), 400
```

3 處 bare `except:` — 連 `KeyboardInterrupt` 都吞，是 release blocker 等級。
（`public.py:399` 範圍小、語義明確；`users.py:1723` 與 `system_admin.py:1953` 需逐個檢查）

### 6.2 `except Exception: pass` 與類似模式

`grep -rnE "except[^:]*:\s*$" services/trading/ services/points_chain/ services/storage/`
回傳 230 行。需要逐個檢查並分類為：

- **Acceptable**: 真的可以無聲忽略（例：log 寫 audit 失敗時不擋主流程）
- **Degraded**: 被吞錯但需要 audit log（例：reference price provider 取不到）
- **Release blocker**: 任何在 trading critical path 上吞 exception 而 caller 不知

→ 不在本 slice 修，但 REFACTOR_PLAN slice 4 處理。

### 6.3 Coerce-to-default

`services/snapshots/service.py:781` —

```python
enabled = enabled_raw if isinstance(enabled_raw, bool) else str(enabled_raw).strip().lower() in {"1","true","yes","on"}
```

任何非 bool 值（包含 `None`、`{"x":"y"}`、列表）都會被 coerce 成 `False`。在 admin
切換 server-mode 等場景下，admin UI 送錯型別會被當成「關掉功能」**而沒有 400 回應**。
→ 建議改用 `parse_bool_strict(value, name="...")` 拋 ValueError，由 route handler 回
400 給操作者。

---

## 7. 註解 / docstring 覆蓋率

| 範圍 | 函式總數 | 有 docstring | 覆蓋率 |
|------|---------:|-------------:|-------:|
| `services/` | 1,752 | 30 | **1.7%** |
| `routes/` | 900 | 8 | **0.9%** |

對比業界普遍對 critical-path 期望 ≥40%（高風險 ≥80%），目前的覆蓋率是 outlier。

→ 註解不是越多越好（見 STYLE_GUIDE.md），但**金額計算、price 路徑、bot 觸發、wallet
write、audit、settings 變更**這幾類函式必須 100% 寫 invariant docstring（見 §8）。

---

## 8. Reference vs Risk-grade Price 拆分現況

`services/trading/price_runtime.py` 內：

- `fetch_weighted_fused_price_points` (L527, **722 行**) — 同一函式內，依 caller 傳入
  的 `price_purpose`/`risk_grade` 決定 fallback 是否允許（找不到該關鍵字的單一處集中
  enforcement，分散在 internal helper 內）
- `_price_context_risk_grade_usable` (engine.py:2748, 24 行) — 只判斷 stale / coverage
- `_assert_price_meta_allows_high_risk_use` (engine.py:2828, 30 行) — 真正的 fail-closed gate

**問題**：

1. risk-grade 的 fail-closed 行為**不是模組級常數**，是分散在 engine.py 兩個 method
   名稱不對齊的 helper
2. 任何新增的 caller（例：未來新 bot 類型、新 liquidation flow）需要 reviewer 自己
   發現「我要呼叫 `_assert_price_meta_allows_high_risk_use`」— 不會被 schema 強制
3. test 覆蓋（`tests/test_trading_reference_prices.py`）測 reference / risk-grade 各
   自的單元行為，但不測「caller A 路徑漏掉 `_assert_*` gate」這種架構性 regression

→ MODULE_SPLIT_PROPOSAL.md §3 提案。

---

## 9. Bot Step Counter / Margin Idempotency 等已知 issue 的結構性根因

### Issue #156 — workflow bot step counter silently disables live bots

`services/trading/bots/workflow.py:449-454`：

```python
fallback_count = int(run_count or 0) if workflow.get("source") == "legacy_condition" else 0
step = int(branch_counts.get(branch.get("id"), fallback_count)) + 1
actions = sorted(branch.get("actions") or [], key=lambda row: int(row.get("step") or 1))
action = next((row for row in actions if int(row.get("step") or 1) >= step), None)
if not action:
    continue
```

**結構性問題**：當 `branch_counts[branch_id] >= len(actions)`，`next(...)` 回傳 `None`，
`continue` 跳過該 branch；外層找不到任何 branch 後直接 fall through，但 caller
`bots/service.py` 沒區分「無 match」與「step counter 已耗盡」，**被當成「無事可做」靜默吞**
而不是發 audit + 通知 owner。

→ 這不是 readability fix，是行為 bug。但 readability 角度的修法是：抽
`select_workflow_action(workflow, context)` 為獨立 function 並回傳 `Result(ok|exhausted|
no_match)` 三態，caller 必須 handle 才會編譯。

### Issue #181 — margin freeze leak

`services/trading/margin.py:653-693, 751-773` 用 `INSERT OR IGNORE` + idempotency table。
讀法：**第一次成功時 freeze；retry 時 idempotency table hit → 拿出 stored response，但
`open_margin_position` 共 323 行**，retry path 的 freeze 撤銷邏輯藏在 line 770 附近，
reviewer 不容易發現重複 freeze 的可能性。

→ readability 角度：把 idempotency check 與 freeze 各自抽 helper（`_open_margin_via_idempotency`
與 `_freeze_collateral_or_revert`），讓「retry 時不重複 freeze」這個 invariant 變成
function 名而非 inline 邏輯。

---

## 10. Phase 0 Open Blockers（決定本 slice 不動 source）

10 HIGH issues open at 2026-05-07：

| # | Title | Path |
|--:|-------|------|
| 181 | Margin collateral freeze leaks on retry | `services/trading/margin.py:653-693, 751-773` |
| 180 | CSRF compare uses `!=` not constant-time | `services/users/auth.py:134` |
| 179 | Log injection via raw chat room name | `routes/chat.py:455-469` |
| 178 | No SIGTERM handler | `server.py` / `services/server/startup.py` |
| 170 | Workflow editor 'validation 未通過' no list | `public/js/trading-workflow-editor.js:988-997` |
| 169 | N+1 user lookup in 4 routes | （chat invite / notifications / files quota / community） |
| 167 | Workflow editor unusable on mobile | `public/trading-workflow-editor.css:236, 545` |
| 157 | Server-encrypted upload writes plaintext during AV scan | `services/storage/cloud_drive.py` |
| 156 | Workflow bot step counter disables bots | `services/trading/bots/workflow.py:449-454` |
| 155 | CSRF token not rotated post-auth | `services/users/auth.py:319-367` |

依專案規則：「Phase 0 blocker 尚未全 close → 本任務只允許 inventory + plan + style guide
+ module split proposal，不允許 source code change」 → 本 slice 嚴格遵守。

---

## 附錄 A — 1,000–1,600 行檔案完整清單

```
1,529  routes/videos.py
1,300  services/media/videos.py
1,271  public/js/25-community.js                   (UI bundle, out of scope)
1,263  services/snapshots/schema.py
1,256  services/trading/bots/service.py
1,212  routes/chat.py
1,210  routes/games.py
1,160  public/js/trading-workflow-editor.js        (UI bundle, out of scope)
1,152  services/trading/btc_bridge.py
1,142  public/js/40-auth-users.js                  (UI bundle, out of scope)
1,140  services/snapshots/service.py
1,019  services/storage/catalog.py
1,006  routes/moderation.py
1,001  routes/public.py
```

---

## 附錄 B — Slice 1 已完成內容（不重做）

Codex 2026-05-06 已搬走：

- `services/trading/constants.py`（ASSET_SCALE、DEFAULT_SPOT_FEE_RATE_PERCENT、
  GRID_PREVIEW_YELLOW_NET_SPREAD_PERCENT、APR_DAYS_PER_YEAR、BOT 相關常數）
- `services/trading/validators.py`（`_to_int / _to_float / _to_decimal /
  _to_price_float / _decimal_text / _daily_percent_from_apr / _apr_percent_from_daily
  / _normalize_borrow_interest_timing / _billable_interest_hours_from_elapsed_seconds`）
- `services/trading/accounting/{units, notional, fees, funding_pool, interest, trial_credit}.py`
- `services/trading/price_fusion/{context, orderbook, weights}.py`

本 slice 提案的所有 split / 抽取**都不重複**上述項目。

---

## End — 進入 REFACTOR_PLAN.md 看下一步順序
