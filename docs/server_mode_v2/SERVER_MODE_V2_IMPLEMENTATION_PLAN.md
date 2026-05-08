---
status: draft (awaiting user approval; do NOT auto-implement)
owner: claude
created: 2026-05-05
parent_specs:
  - SERVER_MODE_V2_PROFILE_MATRIX.md
  - SERVER_MODE_V2_TRADING_AND_POINTSCHAIN.md
purpose: |
  Sequenced, agent-executable work plan to land the Server Mode v2 工程實作版 spec
  into the live hackme_web codebase. Phase ordering prioritizes anti-contamination
  guards (chain production-only) over convenience (DB triggers).
hard_rule: |
  This file is a plan. NO source-code change is to be made on the basis of this
  file until the user gives explicit go-ahead per phase.
---

# Server Mode v2 — Implementation Plan

> **不變式**
> 1. 本計畫不動源碼，只列順序 + 驗收
> 2. PointsChain production-only 是最高優先（早於 DB trigger）
> 3. SQLite 現階段做法 + PostgreSQL/Redis 翻譯路徑都要寫，不可只寫一半
> 4. #76 / #77 是 token 驗證腳本實跑，**主線開工前先做完**（§5）
> 5. CSRF 政策：on in every mode **except** `superweak`（superweak = 最弱網頁模式定位；其餘 6 模式 CSRF 仍 on）

---

## 0. Stack 約束（不要為對齊 spec 換 stack）

| 項目 | 現況 | spec 範例 | 處理 |
|---|---|---|---|
| Web framework | Flask + `@app.before_request` | FastAPI ASGI middleware | 用 before_request hook 實作同等語意 |
| DB | SQLite + Python sqlite3 | PostgreSQL `current_setting()` | 用 connection-scoped Python function 暴露 mode |
| Cache | 進程內 dict + 檔案 | Redis | 寫 helper enforce key prefix；不引入 Redis |
| Queue | 進程內函式呼叫 | Celery / pub-sub | namespace 透過參數傳遞 |
| Async | 同步 Flask | async / await | 不換成 async |

> ⚠️ 任何 PR 引入 Redis / Celery / FastAPI / asyncpg 一律 reject。

---

## 1. 三類工作的差別（讀本計畫前先看清）

| 類別 | 例子 | 標記 |
|---|---|---|
| **文件 spec** | YAML 規範、表格說明、規則陳述 | 📄 |
| **Runtime enforcement** | before_request hook、service-layer guard、DB trigger、cache helper | ⚙️ |
| **QA 驗收** | pytest test、shell smoke、實跑腳本 | ✅ |

每個 phase 都會清楚標。**只更新文件不算完成 enforcement。**

---

## 2. 已完成盤點（What's done）

### 2.1 文件 spec 📄（全部完成）
| 路徑 | 內容 |
|---|---|
| `docs/SERVER_MODE_V2_PROFILE_MATRIX.md` | 7 模式 / 13 報告 / Per-Mechanism / Cache / YAML |
| `docs/SERVER_MODE_V2_TRADING_AND_POINTSCHAIN.md` | trading 雙引擎 + chain production-only |
| `docs/server_mode_v2/` | README + 兩個 token 範例 + 13 報告 playbook |

### 2.2 Runtime enforcement ⚙️（部分完成）
| 既有檔案 | 已落地內容 |
|---|---|
| `services/snapshots.py` | 7 模式 profile / `mode_switch_logs` chain / 13 報告檢查 / 預設 `dev_ready` / internal_test 關 trading |
| `services/auth.py` | `require_csrf` / `require_csrf_safe`（**目前**無 mode bypass；spec 已更正為 superweak 應 bypass，待後續 phase 落地） |
| `server.py:1235-1426` | 6 個 before_request hook（browser_only / cors / feature flags / static page / root ip whitelist / required password change） |
| `services/snapshots.py:3158+` | `tester_shadow_state` / `set_tester_shadow_role` / `adjust_tester_shadow_wallet` |
| `server.py:561` | `tester_token_username_from_request`（路由白名單 + rate limit） |

### 2.3 QA 驗收 ✅（部分完成）
| 測試檔 | 涵蓋範圍 |
|---|---|
| `tests/test_auth_csrf_safe.py` | 既有 9 條（含 3 條 always-on 回歸）；待加 superweak bypass 對應測試 |
| `tests/test_snapshots.py` | mode 切換 / superweak / mode_switch_logs / tester token shadow（41 tests passing） |

---

## 3. 落差盤點（What's missing）

| # | 落差 | 類別 | 影響 phase |
|---|---|---|---|
| G1 | 沒有集中的 request context（`g.smv2_ctx`） | ⚙️ | Phase 1 |
| G2 | PointsChain 寫入無 mode 守門 | ⚙️ | Phase 7 ⭐ |
| G3 | 沒有 `test_shadow_orders` / `test_shadow_positions` / `test_shadow_ledger` | ⚙️ | Phase 4 |
| G4 | 沒有 `resolve_table(logical, ctx)` routing service | ⚙️ | Phase 2 |
| G5 | spec §8 的 9 條 acceptance 測試不存在 | ✅ | Phase 8 |
| G6 | cache key helper 不強制 mode prefix | ⚙️ | Phase 6 |
| G7 | trading_engine.py mode-agnostic（無 prod/shadow 分流） | ⚙️ | Phase 5 |
| G8 | SQLite 沒有 mode-aware DB trigger | ⚙️ | Phase 3 |
| G9 | CSRF 在 superweak 仍開（與 spec 不符；spec 要 superweak bypass） | ⚙️ | Phase 0 (preflight) |

---

## 4. 主線優先順序（user-mandated）

> 主線：anti-contamination 優先，convenience 後做。

```
Pre-Phase 0  Token script 實跑驗證 (#76 / #77)        ← 最先做（§5）
   ↓
Phase 0   CSRF superweak bypass 落地（spec 對齊）
   ↓
Phase 1   request context
   ↓
Phase 7   PointsChain production-only guard           ⭐ 最高優先（核心防污染）
   ↓
Phase 4   shadow tables 補齊
   ↓
Phase 2   routing service
   ↓
Phase 8   QA acceptance（先有測試框架）
   ↓
Phase 6   cache namespace guard
   ↓
Phase 5   trading 雙引擎（要等 1/2/4 都好）
   ↓
Phase 3   DB trigger / SQLite guard（最後一道防線）
```

**理由**：
- Phase 7 提早 → 服務層直接擋住污染路徑，不必等 DB trigger
- Phase 3 拉到最後 → SQLite trigger 不像 PostgreSQL 乾淨，先確保 service guard + QA 都到位再加底層
- Phase 5 拉到後段 → trading 動工前必須有 ctx (1) / shadow tables (4) / routing (2)，否則容易做出假隔離

---

## 5. Pre-Phase 0 — Token 驗證腳本實跑（**主線開工前必做**）

> **更正（2026-05-05）**：#76 / #77 是純 **token 驗證腳本測試**，不是 enforcement gap 修補。
> 但要在 Phase 1 開工前先做完，理由：
> 1. 確認既有 token infra 可運作（內 test login token + tester token 兩條路徑）
> 2. 給後續 phase 一個 known-good baseline（出錯時可區分是新 phase 引入還是既有缺陷）
> 3. 可同時 catch 既有源碼隱性 bug（例如 token expiry / route 白名單）

| Task | 內容 | 條件 |
|---|---|---|
| **#76** | 起 isolated test server，跑 `docs/server_mode_v2/01_internal_test_login_token.sh` | 需 isolated server |
| **#77** | 同 server 跑 `docs/server_mode_v2/02_tester_token_shadow_api.sh`（先切到 internal_test mode） | 需 isolated server + internal_test mode |
| S-C | 把實跑結果回填進 `docs/server_mode_v2/README.md`（已知 limitations / 預期輸出） | #76 + #77 後 |

**驗收條件**：
- 兩個 .sh 都 `200 OK` + `{"ok": true}` JSON
- shadow wallet adjust 後 `tester_shadow_state` 回傳的 balance 正確改變
- production tables（`wallets` / `points_chain_blocks`）數量無變化（用 sqlite 直接 SELECT 確認）

**做完後再進 §Phase 1**。

---

## 6. Phase 規格（agent-executable）

每個 phase 結構：
```
目標 / 要改的檔案 / 不可違反規則 / SQLite 現階段做法 /
PostgreSQL+Redis 上線版做法 / 測試指令 / 驗收條件 / 失敗時提示
```

---

### Phase 0 — CSRF superweak bypass 落地 ⚙️（小工作，先做）

**目標**：依最新 spec，superweak mode 下關閉 CSRF（其餘 6 模式維持 on）。

**要改的檔案**：
- `services/auth.py`：在 `require_csrf` / `require_csrf_safe` 內加 `if get_runtime_server_mode() == 'superweak': return func(...)` bypass
- `tests/test_auth_csrf_safe.py`：
  - 加 `test_require_csrf_bypassed_in_superweak`
  - 加 `test_require_csrf_safe_bypassed_in_superweak`
  - 修正既有 3 條「csrf_always_on」測試的註解 → 改為「csrf-on-default; superweak bypass is the single exception」

**不可違反規則**：
- bypass 條件**只能**是 `mode == 'superweak'`，不可寫成 `mode != 'production'` 或其他寬鬆形式
- bypass 觸發時必須 record `csrf_skipped_superweak` security event（保留稽核痕跡）
- 任何其他 6 模式都要照樣執行 CSRF 檢查
- 不可預讀 cache、必須每 request 直接讀 mode（避免 mode 切換瞬間的時序窗）

**SQLite 現階段做法**：
```python
# services/auth.py (sketch)
def require_csrf(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        if _read_current_mode() == "superweak":
            record_security_event("csrf_skipped_superweak", get_client_ip(), ...)
            return func(*args, **kwargs)
        # ... existing CSRF check
    return wrapper
```

**PostgreSQL+Redis 上線版做法**：
- 同樣邏輯；mode 改從 Redis cached value 讀
- security event 同步進 Redis stream `audit:csrf` 觸發 ops 觀測

**測試指令**：
```bash
scripts/testing/pytest_in_tmp.sh tests/test_auth_csrf_safe.py -v
```

**驗收條件**：
- 11 個 test 全綠（既有 9 + 新增 2）
- 在 superweak mode 下對 `/api/*` POST 不帶 CSRF token → 200
- 在 production / dev_ready / internal_test / test / maintenance / incident_lockdown 任一模式下對 `/api/*` POST 不帶 CSRF token → 403

**失敗時提示**：
- 若 bypass 誤觸發在其他模式 → grep 確認 `mode == 'superweak'` 是 strict equality，沒寫成 `in {'superweak', ...}`

---

### Phase 1 — Request context 集中化 ⚙️

**目標**：每個 request 在第一個 before_request hook 注入 `flask.g.smv2_ctx`，含 `mode` / `tester_id` / `actor_role` / `request_id`，後續所有 hook + service 一律讀 `g.smv2_ctx`，不再各自查 DB。

**要改的檔案**：
- 新增 `services/server_mode_context.py`（`SmV2Context` dataclass + `attach_to_g(req)` + `current_ctx()`）
- 改 `server.py`：在 `protect_sensitive_static_pages` 之前插入新 hook `attach_smv2_ctx`
- 改既有 hook（`enforce_root_ip_whitelist` / `enforce_browser_only_mode` / `restrict_cors` / `enforce_feature_flags`）改用 `current_ctx().mode` 取代 `get_runtime_server_mode()` 內聯呼叫

**不可違反規則**：
- ctx 物件 immutable（用 `@dataclass(frozen=True)`），request 期間不可改
- 沒有 ctx 的 service 函式收到 `ctx=None` 一律 raise，**不允許默認 production**
- `tester_id` 只在 `tester_token_username_from_request` 認證成功才填，其他情況 `None`

**SQLite 現階段做法**：
```python
# services/server_mode_context.py
from dataclasses import dataclass
from flask import g, request, has_request_context

@dataclass(frozen=True)
class SmV2Context:
    mode: str
    tester_id: int | None
    actor_role: str | None
    request_id: str

def attach_to_g():
    g.smv2_ctx = SmV2Context(
        mode=_read_current_mode(),
        tester_id=_resolve_tester_id(request),
        actor_role=_resolve_actor_role(request),
        request_id=_new_request_id(),
    )

def current_ctx() -> SmV2Context:
    if not has_request_context():
        raise RuntimeError("smv2 ctx requested outside request")
    return g.smv2_ctx
```

**PostgreSQL+Redis 上線版做法**：
- ctx 不變，但 `_read_current_mode` 改從 Redis pub/sub cached value 讀（避免每 request 打 DB）
- 同時把 ctx serialize 進 PG `SET LOCAL app.mode = ...`，讓 §Phase 3 的 PG trigger 可以讀

**測試指令**：
```bash
scripts/testing/pytest_in_tmp.sh tests/test_smv2_context.py -v
```

**驗收條件**：
- 100 個 concurrent request 跑 1000 次，沒有 ctx 串流（用 `request_id` UUID 比對）
- 既有 6 個 before_request hook 不再呼叫 `get_runtime_server_mode()`（grep 確認）
- `scripts/testing/pytest_in_tmp.sh tests/` 全綠

**失敗時提示**：
- 若 `g.smv2_ctx` AttributeError → 確認 `attach_smv2_ctx` 是 register 的第一個 before_request
- 若 ctx 跨 request 污染 → flask 的 `g` 是 request-scoped，檢查是否誤用 module global

---

### Phase 7 — PointsChain production-only guard ⭐ ⚙️

**目標**：`points_chain_blocks` 寫入路徑（service 層 + 任何直接 SQL 通道）在 `ctx.mode != 'production'` 時 raise `ChainModeViolation`。這是最高優先，因為 chain 污染不可逆。

**要改的檔案**：
- `services/points_chain.py`：在 `INSERT INTO points_chain_blocks`（line 2460 附近）前加 `_assert_production_mode(ctx)`
- 新增 `services/chain_mode_violation.py`：定義 `ChainModeViolation(RuntimeError)`
- `services/snapshots.py` 啟動 sequence：production 啟動時 verify_chain，失敗 → 自動切 `incident_lockdown`
- 新增 `tests/test_chain_production_only.py`

**不可違反規則**：
- **任何** `INSERT INTO points_chain_blocks` 路徑都要過 guard，**沒有例外**
- `superweak` / `incident_lockdown` / `maintenance` 視同 non-production，照樣擋
- guard 失敗的 exception 必須記錄 security_event（type=`chain_mode_violation`）
- 不可用「測試方便」名義加 bypass flag

**SQLite 現階段做法**：
```python
# services/points_chain.py (sealing entry point)
def seal_block(ctx, payload):
    _assert_production_mode(ctx)
    # ... existing INSERT logic

def _assert_production_mode(ctx):
    if ctx is None or ctx.mode != "production":
        record_security_event(
            "chain_mode_violation",
            get_client_ip(),
            detail=f"mode={ctx.mode if ctx else 'None'}",
        )
        raise ChainModeViolation(f"chain write forbidden in mode={ctx.mode}")
```

**PostgreSQL+Redis 上線版做法**：
- 多加 PG `BEFORE INSERT` trigger 在 `points_chain_blocks`（雙保險）
- guard violation event 同時 publish 到 Redis channel `chain:violation` 觸發 ops alert

**測試指令**：
```bash
scripts/testing/pytest_in_tmp.sh tests/test_chain_production_only.py -v
```

**驗收條件**：
- internal_test mode seal block → `ChainModeViolation`
- maintenance mode seal block → `ChainModeViolation`
- production mode seal block → 成功，row 寫入 `points_chain_blocks`
- 「mode 切換中」時序測試：mode 從 production → internal_test 切換瞬間的 seal 必須擋下

**失敗時提示**：
- 若有舊 callsite 沒帶 ctx → grep `seal_block(` / `INSERT.*points_chain_blocks` 全部找出補
- 若 production runtime 啟動時擋自己 → 確認 `_read_current_mode()` 在 server_modes table 還沒寫入時的回傳值，可能要 bootstrap-window flag

---

### Phase 4 — Shadow tables 補齊 ⚙️

**目標**：新增 `test_shadow_orders` / `test_shadow_positions` / `test_shadow_ledger` 三張表，讓 internal_test 模式下 trading 有獨立寫入空間。

**要改的檔案**：
- `services/snapshots.py` schema 區（line 788 附近）新增三張 CREATE TABLE
- 新增 `tests/test_shadow_schema.py`

**不可違反規則**：
- 三張新表名前綴必須是 `test_shadow_`（一致性）
- 欄位結構盡量比照對應的 prod 表（`orders` / `positions` / `points_ledger`），方便 routing service 用同一份 schema 邏輯
- 加 `tester_user_id` foreign key 欄位，便於日後清理單一 tester 資料

**SQLite 現階段做法**：
```sql
CREATE TABLE IF NOT EXISTS test_shadow_orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tester_user_id INTEGER NOT NULL,
    market_symbol TEXT NOT NULL,
    side TEXT NOT NULL,
    -- ... 比照 orders 表
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_shadow_orders_tester ON test_shadow_orders(tester_user_id);
-- 同樣模式建 test_shadow_positions / test_shadow_ledger
```

**PostgreSQL+Redis 上線版做法**：
- 同樣三張表，但用 partitioning by `tester_user_id`（每 tester 一個 partition）
- Redis 單獨用 `tester:{tester_id}:orderbook:{symbol}` namespace（與 §Phase 6 cache 對齊）

**測試指令**：
```bash
scripts/testing/pytest_in_tmp.sh tests/test_shadow_schema.py -v
```

**驗收條件**：
- fresh DB 啟動後三張表存在
- 既有 prod 表 schema 不受影響（`PRAGMA table_info(orders)` 維持原樣）
- index 建得起來

**失敗時提示**：
- 若 migration 在 production-deployed DB 上跑時失敗 → 用 `IF NOT EXISTS`，並確認沒有舊測試殘留資料

---

### Phase 2 — Routing service ⚙️

**目標**：所有 service 透過 `resolve_table(logical_name, ctx)` 取得實際 table 名，禁止 hardcode。

**要改的檔案**：
- 新增 `services/server_mode_routing.py`
- 改 `services/snapshots.py` 內 tester_* 函式改用 routing
- 文件 `services/server_mode_routing.py` docstring 列完整 mapping table

**不可違反規則**：
- `resolve_table('points_chain_blocks', ctx)` 在 `ctx.mode != 'production'` 一律 raise（與 §Phase 7 一致）
- production 模式下 logical → 同名 prod 表
- internal_test 模式下 logical → `test_shadow_*`
- 其他模式（dev_ready / test / maintenance / incident_lockdown / superweak）對 trading-logical（orders/positions/ledger）一律 raise（呼叫端應在 mode 檢查時就擋下）

**SQLite 現階段做法**：
```python
# services/server_mode_routing.py
LOGICAL_TO_PROD = {"wallets": "wallets", "orders": "orders",
                   "positions": "positions", "points_ledger": "points_ledger",
                   "points_chain_blocks": "points_chain_blocks"}
LOGICAL_TO_SHADOW = {"wallets": "test_shadow_wallets",
                     "orders": "test_shadow_orders",
                     "positions": "test_shadow_positions",
                     "points_ledger": "test_shadow_ledger"}

def resolve_table(logical: str, ctx) -> str:
    if logical == "points_chain_blocks":
        if ctx.mode != "production":
            raise ChainModeViolation(...)
        return "points_chain_blocks"
    if ctx.mode == "production":
        return LOGICAL_TO_PROD[logical]
    if ctx.mode == "internal_test":
        return LOGICAL_TO_SHADOW[logical]
    raise RoutingNotAllowed(f"logical={logical} not routable in mode={ctx.mode}")
```

**PostgreSQL+Redis 上線版做法**：
- 同樣的 routing service，但 mapping 表 cached 在 Redis（mode 切換時 invalidate）
- 加 SQL 撰寫 helper：`fetch(ctx, "SELECT * FROM {wallets} WHERE ...")` auto-substitute

**測試指令**：
```bash
scripts/testing/pytest_in_tmp.sh tests/test_routing_service.py -v
```

**驗收條件**：
- 全部 5 個 logical name 都有 mapping
- `resolve_table('points_chain_blocks', ctx_internal_test)` raise
- `resolve_table('orders', ctx_dev_ready)` raise（trading 在 dev_ready 是 disabled）

**失敗時提示**：
- 若呼叫端漏掉 ctx → grep `f"INSERT INTO {LOGICAL_TO_PROD"` 確保沒有 hardcode

---

### Phase 8 — QA acceptance（先建框架）✅

**目標**：把 spec §8 的 9 條測試先建起來（即使部分當下還會 fail），讓 §Phase 6 / 5 / 3 動工時有對照。

**要改的檔案**：新增 `tests/test_smv2_acceptance.py`（9 個 test func）

**不可違反規則**：
- 9 條都要存在，不可只挑會過的寫
- 不會過的標 `@pytest.mark.xfail(reason="phase X not done", strict=True)`，phase 完成時拿掉
- 測試**不可**透過直接 SQL 繞過 service 層作弊

**SQLite 現階段做法**：
| 測試 | 邏輯草稿 |
|---|---|
| `test_tester_trade_does_not_change_production_wallet` | 切 internal_test → tester 下單 → assert `SELECT balance FROM wallets WHERE user_id=tester_user_id` 不變 |
| `test_tester_trade_does_not_write_points_chain` | 切 internal_test → tester 下單 → assert `SELECT COUNT(*) FROM points_chain_blocks` 不變 |
| `test_production_trade_updates_chain_correctly` | 切 production → 真用戶下單 → assert chain block +1 |
| `test_liquidation_does_not_cross_world` | shadow 持倉觸發爆倉 → assert prod wallets 不動 |
| `test_restore_recovers_chain_integrity` | snapshot → 污染 chain → restore → verify_chain ok |
| `test_funding_rate_does_not_cross_world` | shadow funding 不觸發 prod position 更新 |
| `test_matching_engine_namespaces_separate` | shadow order 不在 prod 撮合佇列 |
| `test_cache_keys_carry_mode_scope` | `make_cache_key('orderbook', logical_market='BTC')` 沒帶 mode → raise |
| `test_superweak_trading_remains_disabled` | 切 superweak → 嘗試下單 → 503 |

**PostgreSQL+Redis 上線版做法**：
- 同樣 9 條測試，但加上 PG trigger 觸發測試（`SET LOCAL app.mode = 'internal_test'; INSERT INTO points_chain_blocks ...` → 應 raise）

**測試指令**：
```bash
scripts/testing/pytest_in_tmp.sh tests/test_smv2_acceptance.py -v
```

**驗收條件**：
- 9 個 test func 都存在
- `test_cache_keys_carry_mode_scope` + `test_superweak_trading_remains_disabled` 直接通過（其他依後續 phase）

**失敗時提示**：
- xfail 變 xpass → 表示對應 phase 已完成，移除標記

---

### Phase 6 — Cache namespace guard ⚙️

**目標**：`make_cache_key()` helper 不接受沒有 mode 的 key；既有 cache 用法全部走 helper。

**要改的檔案**：
- 新增 `services/cache_keys.py`
- 改 `services/trading_engine.py` 既有 cache 用法（orderbook、價格快取）

**不可違反規則**：
- helper 簽名 `make_cache_key(logical: str, *, mode: str, tester_id: int | None = None, **dims) -> str`
- 漏 `mode` → raise `TypeError`
- `mode == 'internal_test'` 時必填 `tester_id`
- 不允許自由格式 string concat 取代 helper

**SQLite 現階段做法**：
```python
# services/cache_keys.py
def make_cache_key(logical: str, *, mode: str, tester_id: int | None = None, **dims) -> str:
    if mode == "internal_test" and tester_id is None:
        raise ValueError("internal_test requires tester_id in cache key")
    parts = [logical, mode]
    if tester_id is not None:
        parts.append(f"tester{tester_id}")
    for k in sorted(dims):
        parts.append(f"{k}={dims[k]}")
    return ":".join(parts)
```

**PostgreSQL+Redis 上線版做法**：
- 同樣 helper，但呼叫端用 `redis.set(make_cache_key(...), ...)`
- 加 Redis SCAN 巡檢腳本：找出無 mode prefix 的舊 key 一律 alert

**測試指令**：
```bash
scripts/testing/pytest_in_tmp.sh tests/test_cache_keys_namespace.py -v
```

**驗收條件**：
- `make_cache_key('orderbook', logical_market='BTC')` 沒帶 mode → TypeError
- `make_cache_key('orderbook', mode='internal_test', logical_market='BTC')` 沒 tester_id → ValueError
- grep `trading_engine.py` 沒有 raw cache key concat

**失敗時提示**：
- 若太多 callsite 要改 → 分批 PR，每張 PR 改一個 logical（orderbook / price / position）

---

### Phase 5 — Trading 雙引擎 ⚙️

> ⚠️ **大工程**。預期 2-3 工作日，分多 PR。動工前 `git pull` + 看 Codex 最近 trading 提交。

**目標**：trading_engine.py 改成依 ctx 走 prod 或 shadow，不再寫死 prod 表。

**要改的檔案**：
- `services/trading_engine.py`（10,469 行；要改 entry point 的簽名 + 主要 SQL 撰寫處）
- `tests/test_trading_engine.py`（補對應測試，**保留 Codex 既有改動**）

**不可違反規則**：
- 任何 SQL 都要透過 `resolve_table(logical, ctx)`，不可 hardcode `orders` / `positions`
- liquidation 引擎必須 assert `ctx.mode == 'production'` xor `ctx.mode == 'internal_test'`，不可同時讀兩邊
- funding rate publish 在 internal_test 走 simulated channel，**不可**寫進 prod 的 funding 表
- 結算成功後 ledger entry 必須對應 chain block（production）或 shadow ledger（internal_test）

**SQLite 現階段做法**：
- 在 trading_engine entry point 把 ctx 帶進來（從 `g.smv2_ctx` 拿）
- 抽 helper `_t(logical) = resolve_table(logical, ctx)`，所有 SQL 改用 `f"INSERT INTO {_t('orders')} ..."`
- matching 函式接 ctx，內部 dict 用 `make_cache_key('orderbook', mode=ctx.mode, ...)` 區分

**PostgreSQL+Redis 上線版做法**：
- matching engine 用獨立 worker 跑：`matching-prod` / `matching-shadow` 兩個 process 監聽不同 Redis stream
- 部署時用 supervisor / systemd 確保兩 worker 不能誤訂閱對方 channel

**測試指令**：
```bash
scripts/testing/pytest_in_tmp.sh tests/test_smv2_acceptance.py::test_tester_trade_does_not_change_production_wallet -v
scripts/testing/pytest_in_tmp.sh tests/test_smv2_acceptance.py::test_liquidation_does_not_cross_world -v
scripts/testing/pytest_in_tmp.sh tests/test_smv2_acceptance.py::test_matching_engine_namespaces_separate -v
```

**驗收條件**：
- §Phase 8 的 G/H 對應 4 條 acceptance test 全綠（去除 xfail）
- `test_trading_engine.py` 既有測試不 regress

**失敗時提示**：
- 若 PR 過大難 review → 拆成 G-1 ctx 注入 / G-2 routing 改寫 / G-3 matching 分流 / G-4 liquidation 分流 / G-5 funding 分流，5 個 PR
- 若 Codex 同時動 trading → 在 `~/agent_communication.txt` 同步 lock window

---

### Phase 3 — DB trigger / SQLite guard ⚙️

> 最後一道防線。前面 phase 全失靈時擋下污染。

**目標**：對 prod 表加 BEFORE INSERT/UPDATE trigger，mode != production 時 RAISE(ABORT)。

**要改的檔案**：
- `services/snapshots.py` schema migration 區
- 新增 `tests/test_db_mode_triggers.py`

**不可違反規則**：
- production 啟動 bootstrap window（mode 還沒寫進 server_modes）期間不可被自己擋住 → 用 settings flag `_smv2_bootstrap=1`
- 不可用 trigger 取代 service guard（service guard 要早觸發 + 帶 better error）
- trigger 觸發必須 record `chain_mode_violation` security_event

**SQLite 現階段做法**：
```python
# services/snapshots.py init_db
def _read_mode(conn):
    row = conn.execute("SELECT current_mode FROM server_modes WHERE id=1").fetchone()
    return row["current_mode"] if row else "bootstrap"

conn.create_function("app_mode", 0, lambda: _read_mode(conn))

conn.execute("""
CREATE TRIGGER IF NOT EXISTS forbid_nonprod_chain_insert
BEFORE INSERT ON points_chain_blocks
WHEN app_mode() NOT IN ('production', 'bootstrap')
BEGIN
    SELECT RAISE(ABORT, 'chain write forbidden in non-production mode');
END;
""")
# 同模式 trigger 加在 wallets / points_ledger / orders / positions
# （但這四張表 internal_test 模式下不該被寫，所以可以擋；shadow 是另一張表）
```

**PostgreSQL+Redis 上線版做法**：
```sql
CREATE OR REPLACE FUNCTION forbid_nonprod_chain_insert() RETURNS trigger AS $$
BEGIN
    IF current_setting('app.mode', true) NOT IN ('production', 'bootstrap') THEN
        RAISE EXCEPTION 'chain write forbidden in mode=%', current_setting('app.mode', true);
    END IF;
    RETURN NEW;
END $$ LANGUAGE plpgsql;

CREATE TRIGGER ... BEFORE INSERT ON points_chain_blocks
EXECUTE FUNCTION forbid_nonprod_chain_insert();
```
- ctx 透過 `SET LOCAL app.mode = ...` 在 connection 起始注入（FastAPI middleware 同時做）

**測試指令**：
```bash
scripts/testing/pytest_in_tmp.sh tests/test_db_mode_triggers.py -v
```

**驗收條件**：
- internal_test mode 下繞過 service 直接 `INSERT INTO points_chain_blocks` → `sqlite3.IntegrityError`
- production mode INSERT 正常
- bootstrap window INSERT 正常（避免啟動失敗）

**失敗時提示**：
- 若 SQLite trigger 拿不到 `app_mode()` → 確認 `create_function` 在每個新開的 connection 都呼叫；若用 connection pool 要 hook into pool factory
- 若 production 啟動失敗 → 檢查 bootstrap flag 是否在 mode insert 之前先 set

---

## 7. 整體 Acceptance（plan-level）

```yaml
plan_done_when:
  phases:
    - pre_phase_0_token_script_smoke: completed
    - phase_0_csrf_superweak_bypass: completed
    - phase_1_request_context: completed
    - phase_7_chain_production_only: completed
    - phase_4_shadow_tables: completed
    - phase_2_routing_service: completed
    - phase_8_qa_framework: completed
    - phase_6_cache_namespace: completed
    - phase_5_trading_dual_engine: completed
    - phase_3_db_triggers: completed
  tests:
    - pytest_full_suite: green
    - tests/test_smv2_acceptance.py: 9/9 green (no xfail)
  docs:
    - SERVER_MODE_V2_PROFILE_MATRIX.md §QA Checklist: marked done
    - per-phase report under docs/AGENTS/reports/claude/server_mode_v2_phase_<N>_<date>/
  cross_agent:
    - ~/agent_communication.txt: phase completion broadcast for each phase
```

---

## 8. 每 phase 結束標準動作

```
1. `scripts/testing/pytest_in_tmp.sh tests/` 全綠
2. 新增 docs/AGENTS/reports/claude/server_mode_v2_phase_<N>_<YYYY-MM-DD>/PHASE_REPORT.md
3. ~/agent_communication.txt append "Claude side update — phase <N> done"
4. 等用戶 review，明確 go ahead 才進下一 phase
```

---

## 9. SQLite ↔ PostgreSQL ↔ Redis 翻譯總表

| 概念 | SQLite 現階段 | PostgreSQL 上線 | Redis 上線 |
|---|---|---|---|
| ctx mode 暴露 | `conn.create_function("app_mode")` | `SET LOCAL app.mode` | cached value, pub/sub invalidate |
| Trigger | `CREATE TRIGGER ... BEFORE INSERT WHEN app_mode() != 'production'` | `CREATE TRIGGER ... EXECUTE FUNCTION` | n/a (DB-level) |
| Routing | Python `resolve_table()` | 同 + view-based partition | 同 |
| Cache namespace | dict key with prefix | n/a | Redis key with prefix |
| Matching queue | 進程內函式 | 進程內函式 | Redis stream `matching:prod` / `matching:shadow` |
| Funding channel | 進程內 dict | 進程內 dict | Redis pub/sub `funding:prod` / `funding:shadow` |

---

## 10. 與 Codex 的衝突避免

依 `~/agent_communication.txt` 既有約定：
- Phase 5 動 trading 前必 `git pull` + 查 Codex 最近 trading commit
- 不重寫 `tests/test_trading_engine.py` 既有本地修改
- 任何 schema migration（Phase 4 / 3）廣播到 `agent_communication.txt`
- Phase 7 動 points_chain 前確認 Codex PointsChain v2 phase 1 進度

---

## 11. 不在本計畫範圍

刻意不做，避免 scope creep：
- ❌ 引入 Redis / Celery / FastAPI / asyncpg
- ❌ 改 PointsChain v2 的 8 個 phase（另一份 doc）
- ❌ 動 AI Agent / Skill Layer
- ❌ 重命名既有 `test_shadow_*` 表
- ❌ 重寫 superweak rollback 邏輯（已驗證 OK）

---

## 12. 跨參考

| 文件 | 用途 |
|---|---|
| [`SERVER_MODE_V2_PROFILE_MATRIX.md`](SERVER_MODE_V2_PROFILE_MATRIX.md) | 7 模式正式 spec |
| [`SERVER_MODE_V2_TRADING_AND_POINTSCHAIN.md`](SERVER_MODE_V2_TRADING_AND_POINTSCHAIN.md) | trading + chain 子規範 |
| [`SERVER_MODE_V2_MIGRATION_PLAN.md`](SERVER_MODE_V2_MIGRATION_PLAN.md) | Codex 寫的 migration 步驟 |
| [`SERVER_MODE_V2_TEST_PLAN.md`](SERVER_MODE_V2_TEST_PLAN.md) | Codex 寫的 test plan |
| [`examples/server_mode_v2/`](examples/server_mode_v2/) | token 教學 + 13 報告 playbook |
| [`AGENTS/reports/claude/server_mode_acceptance_2026-05-05/`](../AGENTS/reports/claude/server_mode_acceptance_2026-05-05/) | 13 節驗收報告 |

---

## 13. 結尾

> Spec 已寫滿，源碼尚未打通。
>
> Plan 是 8 個 phase / ~30 task，每 phase 都有獨立 exit gate。
>
> **不要**為了趕速度跳 phase（Phase 7 chain guard 與 Phase 3 DB trigger 是雙保險，缺一不可）。
> **要**每 phase 結束後等用戶確認，**禁止**自動進下一 phase。
