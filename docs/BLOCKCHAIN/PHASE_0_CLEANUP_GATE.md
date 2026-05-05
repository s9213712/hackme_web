# Phase 0 Cleanup Gate — PointsChain v2 鏈化前清債清單

> **Status:** Updated 2026-05-04 final review round（blockers closed, isolated live API verification passed, full pytest green）
> **Owner:** root（個別授權）
> **動工依據:** [IMPLEMENTATION_GUIDE.md §0](IMPLEMENTATION_GUIDE.md#0-動工流程-必讀必走) — Phase 0 cleanup 本身也是源碼變更，**動工前同樣需要 root 個別授權**。

---

## 0. 結論（Release Gate Verdict）

> **✅ ALLOW PHASE 1 CANDIDATE**
>
> 原先的 blocker / recommend / low issues（#122, #135–#142）已完成：
> - reproduction
> - fix
> - regression tests
> - isolated live API verification
> - full pytest
>
> 目前不再有 open High / Blocker issue 阻擋進入 Phase 1。
> 剩餘的 `incident_lockdown` 跨路徑 coverage 與 silent fallback 全站 audit 屬於後續架構強化，
> 不再作為本輪 release blocker。

> **說明**
>
> 下方 §2 仍保留每一件 issue / cleanup item 的原始風險描述、修法建議與歷史 evidence，
> 方便之後做設計回溯；但「目前是否仍 open」與「是否阻擋 Phase 1」以本節結論為準。

### 整體狀態（19 項）

| 維度 | 數量 | 詳情 |
|---|---|---|
| ✅ CLOSED / RESOLVED | 17 | #122 / #129 / #130 / #131 / #135 / #136 / #137 / #138 / #139 / #140 / #141 / #142 / PB-1 / Wallet replay / Trading fee+PnL / Restore v1 機制 / Docs+Tests sync |
| 🚫 BLOCKER（目前） | 0 | 無 open blocker issue |
| 🟡 RECOMMEND（仍值得後續做） | 0 | 無尚未關閉的 recommend issue |
| 🟡 PARTIAL（待 phase 1/3/4 補完） | 2 | incident_lockdown 跨路徑 coverage / silent fallback 全站 audit |
| ⚪ LOW（cleanup） | 0 | 已收斂 |

---

## 1. 系統性反 Pattern

> 多份 issue 不是孤立的單點 bug，而是**反覆出現的同一種寫法**。修一處沒用，必須當設計層問題處理。

### 1.1 Silent Fallback（沉默回退）

**寫法**：上游收到髒資料時，下游用 `try / except: return default` 或 `or {}` 吞掉，但 API 仍回 200 / 寫入成功；使用者完全不知道輸入被改寫或丟掉。

**命中的 issue**：
- **#136** `_coerce_setting_value` bool 分支：`'yes_please'` 不在 allowlist → 靜默變 False。
- **#137** `_coerce_setting_value` int 分支：`int(NaN)` 拋例外 → 回退到 default；admin 設 99 卻變回 5，無警告。
- **#139** `client_ip_allowed`：`except ValueError: continue`。bad entry 全部 silent skip。
- **#142** `prompt_password()`：stdout 污染被下游 `.strip()` 救回。
- **#129**（已 RESOLVED）backtest API candles<2 靜默 fetch binance 真實行情。

**修法（Phase 0 必做）**：
- 寫 `tests/test_no_silent_fallback.py`，列白名單模式以外的所有 `except Exception: return default` / `or {}` / `try: int(x); except: return default` 都被偵測並要求 audit。
- 每個 fallback 改寫為：(a) 拋 domain error 由 route 統一回 400 ＋ 明確訊息；或 (b) 維持 fallback 但 API response 強制夾帶 `silent_fallback_applied=true` 警示。

### 1.2 宣告但未強制（Schema declared, never enforced）

**寫法**：在某個 dict / metadata 宣告了 schema（type / range / 父子依賴），但實際寫入路徑不查那張表。

**命中的 issue**：
- **#136** / **#137** `DEFAULT_SETTINGS`：每個 key 暗示 type，但無 `validators[key]`。
- **#140** `FEATURE_DEPENDENCY_RULES`（`services/settings.py:151-176`）：宣告父子但 `save_settings()` 從不讀。

**修法（Phase 0 必做）**：
- 把 `DEFAULT_SETTINGS` 升級為中央 settings schema（見 §1.4）。
- 在 `save_settings()` 加 `enforce_feature_dependencies(updates, current)` pre-check，違反 required parent 即 400。

### 1.3 Self-Action Guard 不對齊

**寫法**：「不能對自己做 X」這條規則散在多個 endpoint 各自實作，有的有、有的漏。

**命中的 issue**：
- **#135** `POST /api/admin/users/<id>/block`：缺 `actor.id == user_id` 比對（同 endpoint 家族 `PUT/role`、`PUT/status`、`DELETE` 都已對齊，唯獨 `block` 漏）。

**修法（Phase 0 必做）**：
- 抽 helper：`reject_self_target(actor, user_id, action_label)`。
- 所有 `/api/admin/users/<id>/{block,unblock,promote,demote,review-registration,reset-violations,*}` 一律掛上。
- Phase 4 後 multisig 的 signer 操作也走同一 guard（actor 不可對自己關聯的 proposal 投票，但這是「related to self」更廣的概念）。

### 1.4 Settings 缺中央 Schema Validator

**寫法**：`/api/admin/settings` 的 PUT 路徑用 hand-pick 方式 if-block 一個個 key 做 range/format check（`captcha_ttl_seconds`、`storage_trash_retention_days`、`comfyui_*`、`server_listen_*`...）；其餘 key 直接 fall through 進 `_coerce_setting_value` 寬鬆 coerce。

**命中的 issue**：
- **#136**（bool 半調子 truthy parser）
- **#137**（`video_tip_fee_percent`、`video_tip_min_points`、`security_log_tail_lines`、`snapshot_daily_time` 全無 route-level guard）

**修法（Phase 0 必做）**：建立中央 schema：

```python
# services/settings_schema.py
SETTING_SCHEMA = {
    "video_tip_fee_percent": {
        "type": "int", "min": 0, "max": 100, "default": 5,
        "label": "影音打賞抽成 (%)",
    },
    "video_tip_min_points": {
        "type": "int", "min": 1, "max": 1_000_000, "default": 1,
        "label": "影音打賞最低點數",
    },
    "security_log_tail_lines": {
        "type": "int", "min": 1, "max": 10_000, "default": 200,
        "label": "Security log tail lines",
    },
    "snapshot_daily_time": {
        "type": "time_hhmm", "default": "03:00",
        "label": "每日 snapshot 時間 (HH:MM)",
    },
    "integrity_guard_enabled": {
        "type": "strict_bool", "default": True,  # 只接受 true/false/1/0/on/off/yes/no
        "label": "完整性守護",
    },
    # ... 全部 DEFAULT_SETTINGS 一一補
}

def validate_setting(key, raw_value):
    """returns (coerced_value, error_msg)"""
    schema = SETTING_SCHEMA.get(key)
    if not schema:
        return None, f"未知設定鍵: {key}"
    # 對 NaN/Infinity / 範圍 / 格式 嚴格檢查；違反則返 (None, msg)
```

`/api/admin/settings` PUT 路徑改成：先 `validate_setting()` 全部 key，遇 error 立即 400 + 詳列違反項；沒問題才呼叫 `save_settings(validated)`。

---

## 2. Cleanup Items（19 項）

> 每項都有 7 個欄位：issue id / risk / affected module / required fix / verification command / expected result / release gate status / evidence path。
> 標記 🚫 = Phase 1 blocker；🟡 = Phase 0 建議併修；⚪ = Low cleanup；✅ = 已 RESOLVED。

### Block-1. GitHub #122 — 30s polling 漏觸發 stop-loss / liquidation 🚫

| 欄位 | 值 |
|---|---|
| issue id | [#122](https://github.com/s9213712/hackme_web/issues/122) |
| severity | **High — Phase 1 blocker** |
| risk | liquidation worker 30s scan + price cache 900s。急跌（5s 內 -20%）→ 倉位 5s 即穿倉但要等 30s+ 才偵測；binance 中斷時最長 15 min 用 stale price，期間任何倉位無保護。鏈化後此延遲導致的「該清算未清算」會被永久寫進 chain block，補救只能再寫補償 ledger。|
| affected module | `server.py:start_trading_liquidation_worker`、`server.py:start_trading_bot_worker`、`services/trading_engine.py:scan_margin_liquidations`、`services/trading_engine.py:match_open_limit_orders`、`trading.max_price_staleness_seconds` setting |
| required fix | (a) liquidation worker interval 變數化（env + DB setting），建議降 ≤10s；(b) `match_open_limit_orders` 拆出獨立 ≤5s loop 或在 price update hook 內即時 match；(c) `max_price_staleness_seconds` 上限 60s，超過自動進 `safe_mode` + 通知 root；(d) 監控 dashboard 加 polling-gap-induced miss alert。**根治需 event-driven tick replay**，可列為後續 phase 任務。|
| verification command | `python3 docs/AGENTS/reports/claude/prechain_qa_2026-05-04/scripts/02_trading_handcalc.py` + 新增 `tests/test_liquidation_worker_interval.py` + 模擬急跌（isolated env 把 `manual_price_points` 強制下降，觀察 scan 觸發時間） |
| expected result | (a) liquidation worker `time.sleep` 上限 ≤10s；(b) limit-order match 跑在 ≤5s loop；(c) price staleness > 60s 自動 safe_mode；(d) 模擬急跌中 liquidation 在 ≤10s 內觸發 |
| release gate status | ✅ **RESOLVED 2026-05-04 — final review + live API + full pytest 通過** |
| evidence path | （待補；建議 `docs/AGENTS/reports/<agent>/pointschain_v2_phase0_<date>/evidence/scan_interval/`） |

### Block-2. GitHub #135 — Admin self-block 🚫

| 欄位 | 值 |
|---|---|
| issue id | [#135](https://github.com/s9213712/hackme_web/issues/135) |
| severity | **High — Phase 1 blocker** |
| pattern | §1.3 Self-action guard 不對齊 |
| risk | `POST /api/admin/users/<self_id>/block` 可成功並立即 `revoke_user_sessions(self_id)`。fresh single-admin 部署下 root 自我封鎖最長 24h hard lockout，恢復需直接 sqlite UPDATE。可能被 CSRF-via-XSS 觸發 → 計畫性 admin 失能。鏈化後若 super_admin 同時是 multisig signer，self-block 會破 3-of-5 quorum 假設。|
| affected module | `routes/users.py:1461-1513 admin_user_block` |
| required fix | (a) 在 `admin_user_block` 開頭：`if int(user_id) == int(actor["id"]): return json_resp({"ok":False,"msg":"不可自行封鎖"}), 403`；(b) 抽 helper `reject_self_target(actor, user_id, action_label)`；(c) audit sibling endpoints `block / unblock / promote / demote / reset-violations / review-registration` 全部掛上同一 helper；(d) Phase 4 後 multisig signer self-action 也用此 helper |
| verification command | `PYTHONPATH=. python3 -m pytest -q tests/test_access_controls.py -k "self_block or self_target"` + 新增 `tests/test_admin_self_action_guards.py` |
| expected result | 所有 `POST /api/admin/users/<self_id>/{block,unblock,promote,demote,reset-violations,review-registration}` 一律 403 「不可自行...」；非 self target 維持原有行為；audit log 記錄拒絕事件 |
| release gate status | ✅ **RESOLVED 2026-05-04 — self-target guard regression 已補** |
| evidence path | [`multi_role_audit_2026-05-04/evidence/probe4.json`](../AGENTS/reports/claude/multi_role_audit_2026-05-04/evidence/probe4.json) |

### Block-3. GitHub #136 — Settings silent boolean coerce 🚫

| 欄位 | 值 |
|---|---|
| issue id | [#136](https://github.com/s9213712/hackme_web/issues/136) |
| severity | **High — Phase 1 blocker** |
| pattern | §1.1 Silent fallback ＋ §1.4 缺中央 schema validator |
| risk | `_coerce_setting_value` bool 分支只接受 `{1,true,yes,on,y,t}`；其餘字串靜默變 False。`PUT /api/admin/settings integrity_guard_enabled='yes_please'` 回 200，但 `integrity_guard` 從此 OFF。同 vector 適用所有 `feature_*_enabled` / `audit_chain_enabled` / `integrity_guard_strict_mode` / `snapshot_daily_auto_enabled`。攻擊鏈：偷一個 root token / CSRF → silent disable integrity guard → 接下來竄改 `integrity_manifest.json` 不會被偵測。|
| affected module | `services/settings.py:327-344 _coerce_setting_value`、`services/settings.py:419-452 save_settings`、`routes/system_admin.py:1741-1900 admin_settings` |
| required fix | (a) 引入 §1.4 中央 schema：`SETTING_SCHEMA[key] = {type, validator, default, label}`；(b) 對 bool type 改成 `strict_bool`：只接受 `{true, false, 1, 0, on, off, yes, no}`（case-insensitive），其餘 returns `(None, "value must be boolean")`；(c) `admin_settings` PUT 路徑：先 `validate_setting()` 全部 key，遇 error 立即 400 + 詳列違反項；(d) `_coerce_setting_value` 從 settings 寫入路徑移除（可保留供讀取/migration 路徑舊資料用） |
| verification command | 新增 `tests/test_settings_strict_bool.py`：對 `feature_economy_enabled / integrity_guard_enabled / audit_chain_enabled` 等所有 bool key 試 `'yes_please' / 'enable' / 'absolutely' / 'yes please'` 都應回 400；canonical `'true' / 'false' / true / false / 1 / 0` 應正常通過；`PYTHONPATH=. python3 -m pytest -q tests/test_settings_strict_bool.py` |
| expected result | 全部非 canonical bool 字串 → 400 「value must be boolean」；canonical 通過；DB 未被 silent 改寫；admin 接收明確錯誤訊息 |
| release gate status | ✅ **RESOLVED 2026-05-04 — strict bool validation 已強制** |
| evidence path | [`multi_role_audit_2026-05-04/evidence/probe5.json`](../AGENTS/reports/claude/multi_role_audit_2026-05-04/evidence/probe5.json) |

### Block-4. GitHub #137 — Settings range / format validation gap 🚫

| 欄位 | 值 |
|---|---|
| issue id | [#137](https://github.com/s9213712/hackme_web/issues/137) |
| severity | **High — Phase 1 blocker** |
| pattern | §1.1 Silent fallback ＋ §1.4 缺中央 schema validator |
| risk | `video_tip_fee_percent=-5 / 99999`、`video_tip_min_points=-1 / 1e18`、`security_log_tail_lines=-1 / 1e9`、`snapshot_daily_time='25:99' / 'abcd' / '12:30:45'` 全部被寫入並回 200。後果：(a) 負費率反向給點 → 鏈化後 reward_pool 反向被洗（直接命中 Phase 7 QA Mining 公式）；(b) 1e18 min_points → DoS 影音打賞；(c) 1e9 log tail → admin log endpoint OOM；(d) 無效 daily_time → 每日 snapshot 停擺，違反「不要把錯誤永久化」承諾。NaN/Infinity 透過 `int(NaN)` 拋例外 → silent default 回退 → admin 以為設定生效實際沒有。|
| affected module | `services/settings.py:327-344 _coerce_setting_value`、`routes/system_admin.py:1741-1900 admin_settings`（hand-pick validation 漏網的 keys 全部） |
| required fix | (a) 同 #136，引入中央 SETTING_SCHEMA；(b) 對每個 key 標 type + range/format/regex；(c) `admin_settings` PUT 一律走 `validate_setting()`，所有 unknown / out-of-range / NaN / Infinity → 400；(d) 特別補：`video_tip_fee_percent: int 0-100`、`video_tip_min_points: int 1-1e6`、`security_log_tail_lines: int 1-10000`、`snapshot_daily_time: regex ^([01]\d\|2[0-3]):[0-5]\d$`；(e) NaN/Infinity 在 JSON 層拒絕（Flask `app.config["RESTRICT_JSON_NAN"] = True` 或 `request.get_json(force=False, silent=False)` 不允許 non-finite floats） |
| verification command | 新增 `tests/test_settings_range_validation.py`：對每個 SETTING_SCHEMA key 試 (a) under-min、(b) over-max、(c) wrong-type、(d) NaN、(e) Infinity、(f) 字串給 int 欄位 都應 400；canonical 值通過；`PYTHONPATH=. python3 -m pytest -q tests/test_settings_range_validation.py` |
| expected result | 全部 adversarial 輸入 → 400 + 明確 msg（key + 違反原因）；canonical 通過；DB 不被污染；NaN/Infinity 在 JSON parse 階段 reject |
| release gate status | ✅ **RESOLVED 2026-05-04 — range/format/NaN validation 已強制** |
| evidence path | [`multi_role_audit_2026-05-04/evidence/probe5.json`](../AGENTS/reports/claude/multi_role_audit_2026-05-04/evidence/probe5.json) |

### Recommend-5. GitHub #138 — wallets/<id> 500 + traceback leak 🟡

| 欄位 | 值 |
|---|---|
| issue id | [#138](https://github.com/s9213712/hackme_web/issues/138) |
| severity | **Medium — 建議 Phase 0 一併處理（Phase 1 必碰 wallet lifecycle）** |
| pattern | wallet 邊界 case |
| risk | `GET /api/admin/points/wallets/0` 與 `wallets/999999` 回 500 + Flask traceback；`ensure_wallet` 對 nonexistent user 直接 INSERT 撞 FK。Phase 1 鏈化後新增 `wallet_addresses` schema，相同 lazy-create 模式會在更多 path 出現；不修則進 ledger v2 後成更廣 surface。|
| affected module | `routes/economy.py:378-388 admin_points_wallet`、`services/points_chain.py:1379 ensure_wallet`、所有依賴 `ensure_wallet` 的 service 函式 |
| required fix | (a) `admin_points_wallet` 在 `points_service.get_wallet()` 前先 `SELECT 1 FROM users WHERE id=?`，不存在回 404 「找不到帳號」；(b) `ensure_wallet` 包 try/except 把 `sqlite3.IntegrityError` 轉成 `WalletUserNotFound` domain error；(c) 全域 Flask error handler：`@app.errorhandler(sqlite3.IntegrityError)` → JSON 500 不附 traceback；(d) audit 同 pattern：`/api/admin/points/ledger?user_id=...`、`/api/root/points/wallets/<id>/sanction`、Phase 1 之後新增的 `/api/wallet/...` |
| verification command | 新增 `tests/test_wallet_lifecycle_boundaries.py`：(a) `GET /api/admin/points/wallets/0` → 404；(b) `GET /api/admin/points/wallets/999999` → 404；(c) `GET /api/admin/points/wallets/-1` → 404 / 400；(d) 所有回應無 `traceback` / `IntegrityError` / 內部檔案路徑；`PYTHONPATH=. python3 -m pytest -q tests/test_wallet_lifecycle_boundaries.py` |
| expected result | 所有非法 user_id → 乾淨 404；無 stack trace；Phase 1 後新增 wallet path 全部繼承相同 boundary 行為 |
| release gate status | ✅ **RESOLVED 2026-05-04 — invalid user_id path 已回 404 / 無 traceback** |
| evidence path | [`multi_role_audit_2026-05-04/evidence/probe6.json`](../AGENTS/reports/claude/multi_role_audit_2026-05-04/evidence/probe6.json) + isolated env `runtime/server.out` |

### Recommend-6. GitHub #139 — IP whitelist accepts non-IP, silent skip 🟡

| 欄位 | 值 |
|---|---|
| issue id | [#139](https://github.com/s9213712/hackme_web/issues/139) |
| severity | **Medium — 建議 Phase 0 一併處理（Phase 4 multisig emergency_recovery 信任邊界）** |
| pattern | §1.1 Silent fallback ＋ §1.4 缺中央 schema validator |
| risk | `PUT /api/admin/access-controls root_ip_whitelist='javascript:alert(1)' / '999.999.999.999'` 回 200 並寫入。Enforcement 端 `client_ip_allowed` 對 invalid entry `try/except: continue` 靜默跳過。後果：(a) 全 invalid 清單 + `root_ip_whitelist_enabled=true` → root 自鎖在外，需 DB 修；(b) 部分 valid 清單默默丟掉 bad entry 造成隱性誤配；(c) Phase 4 multisig 設計把 `emergency_recovery_admin` 限制在某 IP 範圍時，靜默丟 entry 會破多簽 emergency unblock 的可信邊界。|
| affected module | `routes/system_admin.py:1955-1983 admin_access_controls`、`services/access_controls.py:26-43 client_ip_allowed`、`services/access_controls.py:17-23 parse_ip_whitelist` |
| required fix | (a) `admin_access_controls` PUT 路徑：對每個 entry 預先 `ipaddress.ip_address(e)` 或 `ipaddress.ip_network(e, strict=False)` 試 parse，bad list 即 400 + 列出 invalid entries；(b) 啟用 `root_ip_whitelist_enabled=true` 前檢查 list 非空且包含 actor 當前 IP，否則 409 「啟用白名單會把自己鎖在外」；(c) `client_ip_allowed` 改為「entry 必須先 lint 過才能進 DB」假設，不再容忍 silent skip（移除 `except ValueError: continue`） |
| verification command | 新增 `tests/test_root_ip_whitelist_validation.py`：(a) 各種 garbage entry 必 400；(b) mix valid + invalid 必 400；(c) all valid CIDR / IPv4 / IPv6 通過；(d) 啟用 white-list 但不含自己 → 409；`PYTHONPATH=. python3 -m pytest -q tests/test_root_ip_whitelist_validation.py` |
| expected result | 任何 invalid entry → 400 + 詳細 msg；DB 從不存 garbage；自鎖風險被擋下；client_ip_allowed 不再需要 silent skip |
| release gate status | ✅ **RESOLVED 2026-05-04 — whitelist 僅接受合法 IP/CIDR，invalid input 直接拒絕** |
| evidence path | [`multi_role_audit_2026-05-04/evidence/probe6.json`](../AGENTS/reports/claude/multi_role_audit_2026-05-04/evidence/probe6.json) |

### Recommend-7. GitHub #140 — FEATURE_DEPENDENCY_RULES not enforced 🟡

| 欄位 | 值 |
|---|---|
| issue id | [#140](https://github.com/s9213712/hackme_web/issues/140) |
| severity | **Medium — 建議 Phase 0 一併處理（Phase 0 capability gating 與此同表）** |
| pattern | §1.2 宣告但未強制 |
| risk | `services/settings.py:151-176 FEATURE_DEPENDENCY_RULES` 宣告 `feature_trading_enabled requires feature_economy_enabled`、`feature_storage_albums_enabled requires feature_privacy_uploads_enabled`，但 `save_settings()` / `save_feature_settings()` 不查此表。可進入「trading on / economy off」不一致 state，部分 endpoint 200 而部分 503，使用者體驗錯亂。Phase 7 QA Mining 把 trading bot 資料連回 economy ledger，若不一致 state 流入 Phase 7 → mining 公式運行於斷裂的資料上。|
| affected module | `services/settings.py:419-452 save_settings`、`services/settings.py:469-473 save_feature_settings`、`routes/system_admin.py admin_settings / admin_features` |
| required fix | (a) 在 `services/settings.py` 新增 `enforce_feature_dependencies(updates, current) → violations[]`：合併 updates 與 current state，walk `FEATURE_DEPENDENCY_RULES`；(b) `save_settings()` / `save_feature_settings()` 在持久化前呼叫；(c) `admin_settings / admin_features` 收到 violations 即 400 + 列出 missing parents；(d) 額外提供 boot-time invariant：`scripts/check_feature_dependencies.py` walk DB 找已存的 child-on / parent-off 組合，emit 啟動警告（Phase 0 一次性 fix 後保持 dirty 偵測）|
| verification command | 新增 `tests/test_feature_dependency_enforcement.py`：(a) PUT trading=on with economy=off → 400；(b) PUT storage_albums=on with privacy_uploads=off → 400；(c) PUT 單獨 enable parent → OK；(d) PUT 同時 enable 父子 → OK；`PYTHONPATH=. python3 -m pytest -q tests/test_feature_dependency_enforcement.py` |
| expected result | 違反 required parent 即 400 + 明確 msg「feature X 需要先啟用 feature Y」；boot-time 對既有不一致 state emit 警告 |
| release gate status | ✅ **RESOLVED 2026-05-04 — feature dependency 在寫入端已強制** |
| evidence path | [`multi_role_audit_2026-05-04/evidence/probe6.json`](../AGENTS/reports/claude/multi_role_audit_2026-05-04/evidence/probe6.json) |

### Resolved-8. GitHub #129 — backtest API candles<2 silent fetch ✅

| 欄位 | 值 |
|---|---|
| issue id | [#129](https://github.com/s9213712/hackme_web/issues/129) |
| severity | High（已 RESOLVED） |
| pattern | §1.1 Silent fallback |
| risk | 違反隔離測試前提；isolated env 對 binance 發外網請求；使用者得到非自己輸入的回測結果 |
| affected module | `routes/trading.py:1010-1015`（`fetch_reference_candles_for_backtest` fallback） |
| required fix | route 改成只有顯式 `auto_fetch_reference_candles=true` 才抓 reference candles，否則保留 isolation 並拒絕過短 candles；response 須含 `data_source_overridden` 警示 |
| verification command | `PYTHONPATH=. python3 -m pytest -q tests/test_trading_reference_prices.py::test_backtest_does_not_silently_replace_isolated_single_candle` |
| expected result | PASS |
| release gate status | ✅ **RESOLVED 2026-05-04** |
| evidence path | [PRE_BLOCKCHAIN_READINESS_REPORT.md §Follow-up](../AGENTS/reports/claude/prechain_qa_2026-05-04/PRE_BLOCKCHAIN_READINESS_REPORT.md) |

### Resolved-9. GitHub #130 — backtest engine no outlier filter ✅

| 欄位 | 值 |
|---|---|
| issue id | [#130](https://github.com/s9213712/hackme_web/issues/130) |
| severity | High（已 RESOLVED） |
| risk | 極端跳躍 candle 在 backtest 產生不真實利潤幻覺（10× return on 1 tick），誤導使用者交易決策；live trading 端有 jump 守護但 backtest 端沒有，行為不一致 |
| affected module | `services/trading_engine.py:4613-4620`（backtest 主迴圈 candle 處理） |
| required fix | 主迴圈套用 `max_price_jump_percent`（同 live trading）；超過跳躍門檻的 candle skip 或要求 `confirm_jump=true`；response 含 `range_warnings[]` 與 `skipped_count` |
| verification command | `PYTHONPATH=. python3 -m pytest -q tests/test_trading_engine.py::test_backtest_skips_outlier_jump_candles_instead_of_booking_fake_profit` |
| expected result | PASS |
| release gate status | ✅ **RESOLVED 2026-05-04** |
| evidence path | 同上 PRE_BLOCKCHAIN_READINESS_REPORT.md `#130` |

### Resolved-10. GitHub #131 — Bollinger Band false trigger on flat sequence ✅

| 欄位 | 值 |
|---|---|
| issue id | [#131](https://github.com/s9213712/hackme_web/issues/131) |
| severity | High（已 RESOLVED） |
| risk | 兩個 official template (`bollinger_reversion`、`swing_bb_ma50`) 在低波動行情會莫名買賣；使用者照官方範例啟用後遭遇盤整段就誤交易 |
| affected module | `services/trading_engine.py:4007-4011`（BB 計算）+ `4070-4075`（`bb_position` 條件 `<=` / `>=` 比較） |
| required fix | `bb_std=0` 時不產生穿越訊號（`bb_lower / bb_upper = None`）；`bb_position` 改嚴格 `>` / `<` 比較 |
| verification command | `PYTHONPATH=. python3 -m pytest -q tests/test_trading_engine.py::test_workflow_backtest_does_not_false_trigger_bollinger_on_flat_sequence` |
| expected result | PASS |
| release gate status | ✅ **RESOLVED 2026-05-04** |
| evidence path | 同上 |

### Resolved-11. PB-1 — NaN / invalid numeric input exception leak ✅

| 欄位 | 值 |
|---|---|
| issue id | PB-1（本地 finding，無獨立 GitHub issue） |
| severity | Medium（已 RESOLVED） |
| risk | 對抗輸入 `quantity:"NaN"` 直接外洩 `[<class 'decimal.InvalidOperation'>]` 內部例外字串給使用者；違反 [RULES_FOR_AGENTS.md §3](../AGENTS/RULES_FOR_AGENTS.md)「不洩漏敏感資訊」；鏈化後類似內部錯誤可能寫進 audit chain |
| affected module | `routes/trading.py:trading_place_order`、`services/trading_engine.py:place_order` 與其他接收 numeric 輸入的 route |
| required fix | service 層在 `Decimal()` 前 `math.isfinite()` 守；route 端用白名單訊息 (例：「無效的數量格式」) 取代 raw exception；同步 cover `quantity_to_units` 與 `_to_int` 路徑 |
| verification command | `PYTHONPATH=. python3 -m pytest -q tests/test_trading_reference_prices.py::test_trading_order_invalid_decimal_is_sanitized_for_user` |
| expected result | PASS；response.msg 不含 `decimal.InvalidOperation` / `Traceback` 等內部字串 |
| release gate status | ✅ **RESOLVED 2026-05-04** |
| evidence path | 同上 |

### Resolved-12. Wallet / Ledger Replay 一致性 ✅

| 欄位 | 值 |
|---|---|
| issue id | （無獨立 issue；屬鏈化前置健全性檢查）|
| severity | Blocker（已 PASS） |
| risk | 鏈化前若 `points_wallets` 與 `points_ledger` replay 結果已不一致，鏈化後錯誤被永久寫入 chain block，所有後續餘額查詢與排行榜全部失真 |
| affected module | `services/points_chain.py` (verify / replay)、`points_wallets`、`points_ledger`、`points_chain_blocks` |
| required fix | nightly diff job + boot-time invariant check：`Σ ledger.amount * direction_sign per (user_id, currency_type) == wallet.balance`；hash chain 連續無破洞；無 orphan ledger（user_id 不在 wallets）；無 negative wallet |
| verification command | `python3 docs/AGENTS/reports/claude/prechain_qa_2026-05-04/scripts/01_ledger_replay.py`（離線跑）+ 新 `tests/test_wallet_ledger_replay_invariant.py`（boot-time 模擬） |
| expected result | `wallet_replay_pass=true`、`orphan_ledger_pass=true`、`no_negative_balance_pass=true`、`hash_chain_pass=true` 全 4 項 PASS |
| release gate status | ✅ **PASS**（prechain_qa_2026-05-04 evidence/ledger/replay_check.json 已驗）|
| evidence path | [`evidence/ledger/replay_check.json`](../AGENTS/reports/claude/prechain_qa_2026-05-04/evidence/ledger/replay_check.json) |

### Resolved-13. Trading Fee / PnL Correctness ✅

| 欄位 | 值 |
|---|---|
| issue id | （主項：無獨立 issue；子項見下方 #143）|
| severity | Blocker（已 PASS） |
| risk | 鏈化後每筆交易事件進 chain block 永久不可改；若 fee/PnL 計算誤差累積，使用者帳戶可能被永久錯誤標記 |
| affected module | `services/trading_engine.py:fee_points` / `notional_points` / `_settle_*` / `place_order` / `scan_margin_liquidations` 等所有金流路徑 |
| required fix | 確認所有 fee / notional / PnL 計算用 integer POINTS + `Decimal.ROUND_HALF_UP`；spot round-trip 0 PnL 0 fee 守恆；DCA timing 與 budget 與實際扣款相符；現有 `test_trading_engine.py` 與 `test_trading_reference_prices.py` 涵蓋的所有 case 100% 綠 |
| verification command | `python3 docs/AGENTS/reports/claude/prechain_qa_2026-05-04/scripts/02_trading_handcalc.py` + `03_dca_timing.py` + `PYTHONPATH=. python3 -m pytest -q tests/test_trading_engine.py tests/test_trading_reference_prices.py` |
| expected result | (a) spot buy → sell round-trip 餘額 delta = 0（同價）；(b) DCA initial_run 立即觸發 + cooldown 後第二次觸發 + cooldown 內第三次被擋；(c) pytest 全 PASS |
| release gate status | ✅ **PASS**（prechain_qa_2026-05-04 evidence/trading 全綠 + 子項 #143 已收斂）|
| evidence path | [`evidence/trading/phase56_handcalc.json`](../AGENTS/reports/claude/prechain_qa_2026-05-04/evidence/trading/phase56_handcalc.json) + [`evidence/trading/dca_minimal.log`](../AGENTS/reports/claude/prechain_qa_2026-05-04/evidence/trading/dca_minimal.log) |

#### 子項 13.a — GitHub #143 incremental spot buys corrupt avg_cost_points ✅

> 補登紀錄（2026-05-04）：升級後的 `security/trading_exchange_validation.py` 在 Phase 0 closure 之後暴露此真實 product bug，並在當日 close。雖然發生在主 gate 已標 ALLOW PHASE 1 CANDIDATE 之後，但屬 §13 出口條件「spot 計算正確」直接子集，補在這裡留紀錄，避免後續 agent 不知道此條曾被打開又補回。

| 欄位 | 值 |
|---|---|
| issue id | [#143](https://github.com/s9213712/hackme_web/issues/143) |
| severity | High（已 RESOLVED） |
| risk | ETH/POINTS 多次 incremental buy（DCA + conditional）後，`trading_spot_positions.avg_cost_points` 飄到 `2.4e19` 級巨大值；後續 workflow `buy_amount` 在 `place_order` / `_execute_order` 內 `decimal.InvalidOperation`。鏈化後此誤差會永久污染 ledger v2。 |
| affected module | `services/trading_engine.py:_execute_order` spot buy path 的 avg_cost 重算 |
| root cause | 平均成本重算只把「新買」那項除 `next_qty`，沒把整個 `(prev_qty * prev_cost + new_qty * price)` 除 `next_qty`（推測） |
| verification command | `PYTHONPATH=/home/s92137/hackme_web python3 security/trading_exchange_validation.py --out /tmp/trading_exchange_validation_latest_check2` + 補上 product regression test「incremental spot buys preserve sane average cost accounting」+「workflow buy_amount still works after previous spot/DCA/conditional fills」 |
| expected result | (a) `avg_cost_points` 多次 incremental buy 後仍接近真實混合成本；(b) 後續 workflow `buy_amount` 不會 `decimal.InvalidOperation` |
| release gate status | ✅ **CLOSED 2026-05-04** |
| evidence path | GitHub #143 + 升級後 `security/trading_exchange_validation.py` 對應 PASS 紀錄 |

### Resolved-14. Restore / Snapshot Correctness ✅

| 欄位 | 值 |
|---|---|
| issue id | （無獨立 issue；對應 [POINTSCHAIN_ENGINEERING.md §0](POINTSCHAIN_ENGINEERING.md) 拍板「Snapshot/Restore：chain 不 rollback；restore 寫 marker；後續強制 reconcile」）|
| severity | Blocker（v1 機制 PASS；marker 待 Phase 2） |
| risk | snapshot/restore 流程在鏈化前若不可信，鏈化後 restore 行為會錯誤覆蓋鏈狀態 / 觸發 chain 不一致 / 用戶餘額被回滾但 chain 不回滾 |
| affected module | `services/snapshots.py`（SnapshotService / ServerModeService / restore 路徑）、Phase 2 後加 `points_chain_blocks_v2` 不允許被 restore 覆寫 |
| required fix | (a) restore 必須帶 `confirm:'RESTORE'` 二次確認（已實作）；(b) `post_restore_validation.ok=true` + `event_id` 回傳；(c) restore 後寫 `restore_marker` event（**Phase 2 完成時補完**）；(d) state_root + supply_root 對不上自動進 incident_lockdown |
| verification command | `python3 docs/AGENTS/reports/claude/prechain_qa_2026-05-04/scripts/04_snapshot_servermode.py` + 模擬 baseline → 殘留 → restore，檢查 trading_orders / trading_fills 計數回到 baseline |
| expected result | (a) restore response 含 `event_id` + `post_restore_validation.ok=true`；(b) 殘留資料移除；(c) baseline 保留；(d) Phase 2 後 `restore_marker` 寫入 ledger_v2 |
| release gate status | ✅ **PASS**（v1 機制已驗）；🟡 `restore_marker` 寫入需 Phase 2 完成才能補 |
| evidence path | [`evidence/snapshot/restore_test_v2.json`](../AGENTS/reports/claude/prechain_qa_2026-05-04/evidence/snapshot/restore_test_v2.json) + [`snapshot_mode.json`](../AGENTS/reports/claude/prechain_qa_2026-05-04/evidence/snapshot/snapshot_mode.json) |

### Partial-15. Incident Lockdown 跨路徑 Coverage 🟡

| 欄位 | 值 |
|---|---|
| issue id | （無獨立 issue；對應 [POINTSCHAIN_ENGINEERING.md §0](POINTSCHAIN_ENGINEERING.md) 拍板「incident_lockdown 同時擋 trading / transfer / mint / multisig execute」）|
| severity | High — Phase 1+ 補完 |
| risk | lockdown 期間若仍可下單 / 轉帳 / mint / execute multisig，緊急停機機制失效；鏈化後因 invariant 失敗自動進 lockdown 但仍可寫入錯誤事件，永久污染鏈 |
| affected module | `services/snapshots.py` (ServerModeService 進 incident_lockdown 路徑)、所有寫入 API 必須在進入時 check 模式；Phase 1+ 後新增的 transfer/mint/multisig 路徑也都要 check |
| required fix | (a) trading 寫路徑 check（**已實作**）；(b) transfer / mint / multisig execute path（**Phase 1/3/4 必補**，現在不存在所以無實際 reject 可測）；(c) 解除 lockdown 路徑必須走 multisig（**Phase 4 後生效**） |
| verification command | (a) `python3 docs/AGENTS/reports/claude/prechain_qa_2026-05-04/scripts/04_snapshot_servermode.py`（測現有 trading lockdown）；(b) 新 phase 完成後對應 pytest 補測 |
| expected result | trading 路徑：HTTP 503 + msg 含「事故封鎖模式中」；其餘路徑 Phase 1+ 完成後同樣行為 |
| release gate status | 🟡 **PARTIAL** — trading 已驗；transfer/mint/multisig 路徑要等 phase 1/3/4 完成才能補 coverage |
| evidence path | [`evidence/snapshot/snapshot_mode.json`](../AGENTS/reports/claude/prechain_qa_2026-05-04/evidence/snapshot/snapshot_mode.json) `phase8_lockdown_blocks_order` 條目 |

### Partial-16. Silent Fallback Audit（全站）🟡

| 欄位 | 值 |
|---|---|
| issue id | （無獨立 issue；對應 §1.1 Silent fallback pattern + [POINTSCHAIN_ENGINEERING.md §10 風險表](POINTSCHAIN_ENGINEERING.md)）|
| severity | High — known issue fixes closed; whole-site audit deferred to Phase 1+ hardening |
| pattern | §1.1 Silent fallback |
| risk | 系統在使用者輸入不足或外部系統失敗時靜默替換結果（如 #129 backtest fetch binance、#136 silent bool coerce、#139 silent IP skip），鏈化後使用者操作被 silently 改寫並寫進 chain，無從追溯原始意圖 |
| affected module | `routes/trading.py` (#129 已修)、`services/settings.py` (#136 / #137 已修)、`services/access_controls.py` (#139 已修)、`services/comfyui_client.py`、`services/btc_trade_bridge.py`、其他外部依賴的 service（後者三處仍待全站 audit） |
| required fix | (a) #129 / #136 / #137 / #139 個別修並驗證 — **全部已 close**；(b) 對其餘有 fallback 的路徑全 grep audit：搜尋 `or {}`、`except Exception: ... return ...`、`int(...)... except: return default`、`try: ip_address; except: continue` 等模式；(c) 找出 silent fallback 後改成 `data_source_overridden=true` 警示 + 在 audit event 紀錄；(d) 寫 `tests/test_no_silent_fallback.py` 列白名單模式以外的 fallback 全部報出 — (b) / (c) / (d) 屬 Phase 1+ 架構強化任務 |
| verification command | `grep -rnE "fallback\|or fetch_\|except [A-Za-z]*Exception\b.*\\n.*return" routes/ services/ \| tee silent_fallback_audit.md`；`PYTHONPATH=. python3 -m pytest -q tests/test_trading_reference_prices.py -k 'silently'`；`PYTHONPATH=. python3 -m pytest -q tests/test_settings_strict_bool.py tests/test_settings_range_validation.py tests/test_root_ip_whitelist_validation.py` |
| expected result | #129 / #136 / #137 / #139 PASS — **all closed**；全站 grep audit 報告產出，未閉合 fallback 路徑全部 list 並由 root 判定（保留 / 改 opt-in / 移除）；新增的 fallback 一律不靜默 |
| release gate status | 🟡 **PARTIAL** — known issue fixes are closed (#129 / #136 / #137 / #139 all closed and verified); broad whole-site fallback audit remains a Phase 1+ architecture hardening task and **does not block Phase 1 candidate**. |
| evidence path | （已 closed 部分：見 §3.1 / §3.2 表格內 PASS 紀錄；全站 audit 待補；建議 `docs/AGENTS/reports/<agent>/pointschain_v2_phase0_<date>/evidence/silent_fallback_audit.md`） |

### Resolved-17. Docs / Tests Sync ✅

| 欄位 | 值 |
|---|---|
| issue id | （PB-2 / PB-3 已 RESOLVED；屬持續維護項目）|
| severity | Medium（已 PASS） |
| risk | 文件與實作偏離 → 後續 agent 看到舊規格動工 → 鏈化分支撞錯方向；test 對 release_id / asset version 硬編碼 → 升版必失敗（先前 #115）|
| affected module | `docs/`（含 BLOCKCHAIN/）、`tests/test_release_policy.py`、`tests/test_frontend_*.py`、needle test |
| required fix | (a) needle test 已通過（PB-2）；(b) `docs/07_POINTSCHAIN.md` 確認既存（PB-3 false negative）；(c) `docs/TRADING_BOT_AUDIT.md` 已新增；(d) BLOCKCHAIN/ 8 份正式設計文件 + IMPLEMENTATION_GUIDE 就位；(e) Phase 0 完成時 `docs/BLOCKCHAIN/POINTSCHAIN_ENGINEERING.md §2` 與 `POINTSCHAIN_QA.md §2` 加上實際完成 commit hash 與 tag |
| verification command | `PYTHONPATH=. python3 -m pytest -q tests/test_release_policy.py tests/test_trading_engine.py -k 'legacy_rate_unit_label_removed'` + 人工檢查 `docs/BLOCKCHAIN/` 9 份檔存在 + 對外 README/ADMIN/TRADING/AUDIT/SNAPSHOT/SECURITY_MODES 已連結 |
| expected result | needle test PASS；release_policy test PASS；docs/BLOCKCHAIN/ 9 份檔齊全；7 份既有外部 docs 連結均指向 `BLOCKCHAIN/` |
| release gate status | ✅ **PASS** |
| evidence path | [`evidence/docs/core_pytest.log`](../AGENTS/reports/claude/prechain_qa_2026-05-04/evidence/docs/core_pytest.log) + [本指引文件](IMPLEMENTATION_GUIDE.md) |

### Low-18. GitHub #141 — test scans .venv site-packages ⚪

| 欄位 | 值 |
|---|---|
| issue id | [#141](https://github.com/s9213712/hackme_web/issues/141) |
| severity | **Low — docs/tests sync** |
| risk | 本地 dev 用標準 `.venv` 跑 pytest 必失敗（vendored `certifi/cacert.pem` 含 legacy rate-unit 字串）；test 在 CI 過、dev 不過，迫使 dev skip / 改 test |
| affected module | `tests/test_trading_engine.py:114-132 test_legacy_rate_unit_label_removed_from_repository_text` |
| required fix | `ignored_dirs` 增 `.venv`、`venv`、`env`、`.tox`、`.eggs`、`build`、`dist`；或改用 allowlist 掃 `routes / services / public / scripts / tests / docs / workflows` |
| verification command | 在 venv 環境跑 `PYTHONPATH=. python3 -m pytest -q tests/test_trading_engine.py::test_legacy_rate_unit_label_removed_from_repository_text` |
| expected result | PASS（在 venv 中也通過） |
| release gate status | ✅ **RESOLVED 2026-05-04 — test 掃描已排除 `.venv` 等非 repo 原始碼** |
| evidence path | [`multi_role_audit_2026-05-04/evidence/pytest_baseline.txt`](../AGENTS/reports/claude/multi_role_audit_2026-05-04/evidence/pytest_baseline.txt) |

### Low-19. GitHub #142 — prompt_password stdout pollution ⚪

| 欄位 | 值 |
|---|---|
| issue id | [#142](https://github.com/s9213712/hackme_web/issues/142) |
| severity | **Low — docs/tests sync（masked by `.strip()`）** |
| pattern | §1.1 Silent fallback（masked by downstream defensive code） |
| risk | `scripts/run_prod.sh prompt_password()` 把 `printf '\n'` 與 status `say` 寫進 stdout，被 `$()` 命令替換捕獲，導致 `.env` 內 `HTML_LEARNING_ROOT_PASSWORD='\n\nactualpassword'`。目前 `services/bootstrap.py:_bootstrap_password().strip()` 救回，第一次登入仍 work，但「下游 defensive code 補救上游 silent error」是反 pattern；下次重構若有人移除 `.strip()` 會 re-introduce。|
| affected module | `scripts/run_prod.sh prompt_password() / prompt_default()`、`services/bootstrap.py:179-183 _bootstrap_password` |
| required fix | `prompt_password` / `prompt_default` 內所有 `printf '\n'`、`say "..."` 全部 `>&2` 重新導向 stderr；只把純密碼字串寫到 stdout |
| verification command | bash heredoc 重現腳本：`bash docs/AGENTS/reports/claude/multi_role_audit_2026-05-04/scripts/08_prompt_password_pollution.sh`，捕獲到的 password byte-dump 必須與輸入完全一致（無前後 `\n`） |
| expected result | `od -c` 輸出 `0000000   m   y   S   e   c   r   e   t   P   w   1   2`（無前綴 `\n\n`） |
| release gate status | ✅ **RESOLVED 2026-05-04 — prompt stdout 汙染 regression 已補** |
| evidence path | [`multi_role_audit_2026-05-04/scripts/08_prompt_password_pollution.sh`](../AGENTS/reports/claude/multi_role_audit_2026-05-04/scripts/08_prompt_password_pollution.sh) + [`scripts/09_env_roundtrip.sh`](../AGENTS/reports/claude/multi_role_audit_2026-05-04/scripts/09_env_roundtrip.sh) |

---

## 3. Phase 0 完成出口（root 授權實作後）

當 root 決定 Phase 0 cleanup 進入實作後，動工 agent 須做到下列才算 Phase 0 完成：

### 3.1 必修四件（Block Phase 1）— 全部 close + verification PASS

- [x] **#122**：scan-window high/low 觸發、`last_scan_at` 僅在成功 scan 後更新、回歸與 full pytest 通過
- [x] **#135**：所有 `/api/admin/users/<id>/{block,unblock,promote,demote,reset-violations,review-registration}` 透過共用 self-target guard 對齊
- [x] **#136**：bool settings 不再 silent coerce；invalid bool 明確拒絕
- [x] **#137**：settings range/format/NaN/Infinity 驗證已強制；full pytest 通過

### 3.2 強烈建議併修（避免 Phase 1+ 重做）

- [x] **#138**：`admin_points_wallet` 非法 user_id 已回 404 / 不再洩漏 traceback
- [x] **#139**：`admin_access_controls` 只接受合法 IP/CIDR；invalid input 直接拒絕
- [x] **#140**：`FEATURE_DEPENDENCY_RULES` 已在寫入端強制

### 3.3 既有持續項目

- [x] #129 / #130 / #131 / PB-1 持續綠（final review regression 與 full pytest 已重跑）
- [ ] 全站 silent fallback grep audit 報告產出，root 簽核「保留/改 opt-in/移除」清單 — *屬 Phase 1+ 架構強化，不阻擋 Phase 1 candidate，但必須在後續 QA gate 持續追蹤*
- [ ] incident_lockdown 跨路徑 coverage 為 Phase 1+ 預留 hook（service 層 helper 函式）— *同上，Phase 1+ 架構強化任務*

> **這兩項屬於 Phase 1+ 架構強化，不再阻擋 Phase 1 candidate，但必須在後續 QA gate 持續追蹤。**
> They do not block Phase 1 candidate status, but must be tracked in Phase 1+ QA.

### 3.4 Low cleanup（不阻擋）

- [x] **#141**：test ignored_dirs 補 `.venv` 等 — RESOLVED 2026-05-04（見 Low-18）
- [x] **#142**：`prompt_password / prompt_default` 改 `>&2` 導向 stderr — RESOLVED 2026-05-04（見 Low-19）

### 3.5 Docs / 簽核

- [x] `docs/BLOCKCHAIN/POINTSCHAIN_ENGINEERING.md §2`、`POINTSCHAIN_QA.md §2` 已同步 final review 結論
- [x] 報告歸檔：`docs/AGENTS/reports/codex/final_open_issues_review_<timestamp>/report.md`
- [ ] root 是否批准正式啟動 `04.blockchain`

---

## 4. 與其他文件的關係

- **入口**：[IMPLEMENTATION_GUIDE.md §0.4](IMPLEMENTATION_GUIDE.md) 引用本檔。
- **設計來源**：[POINTSCHAIN_ENGINEERING.md §0](POINTSCHAIN_ENGINEERING.md)（snapshot/restore、incident_lockdown、silent fallback 紅線）、[POINTSCHAIN_QA.md §0](POINTSCHAIN_QA.md)（鏈化前必跑 invariants）。
- **Issue 證據**：
  - 第三輪 prechain QA：[`docs/AGENTS/reports/claude/prechain_qa_2026-05-04/`](../AGENTS/reports/claude/prechain_qa_2026-05-04/)
  - 第六輪 multi-role audit：[`docs/AGENTS/reports/claude/multi_role_audit_2026-05-04/`](../AGENTS/reports/claude/multi_role_audit_2026-05-04/)
- **GitHub issue list**：[reports/claude/README.md §對應 GitHub Issues](../AGENTS/reports/claude/README.md)。

---

*Document end. 本檔保留 Phase 0 清債的歷史 issue 明細與 evidence 線索；目前 canonical 判定已更新為 `ALLOW PHASE 1 CANDIDATE`。正式是否開工仍由 root 決定。*
