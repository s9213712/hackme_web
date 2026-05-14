# Trading Bot Audit

> 本文件對齊 `docs/AGENTS/TRADING_SYSTEM_QA_FOR_AGENTS.md` 的 bot 稽核要求，
> 說明目前已實作的 bot 稽核機制、可查的 evidence、以及後續仍可擴充的深度
> 對帳 / replay 規格。

## 設計目的

證明每個交易機器人「該觸發時有觸發、不該觸發時沒有誤觸發、訂單金額/手續費/盈虧/帳本可對帳」，並在異常時不可靜默，必須提醒 root 與用戶。

## 目前範圍

| 項目 | 狀態 | 備註 |
|---|---|---|
| `secure_audit` 主稽核鏈 | ✅ 已實作 | hash chain，記錄 `TRADING_BOT_CREATED / UPDATED / DELETED`、`TRADING_ORDER_*`、`TRADING_AUTO_LIQUIDATION_*` 等事件 |
| `trading_audit_events` 交易專用稽核表 | ✅ 已實作 | `services/trading/engine.py`；存 actor / target_user_id / market_symbol / metadata_json |
| `trading_bot_runs` 每次 bot 巡檢紀錄 | ✅ 已實作 | `services/trading/engine.py`；status (`triggered`/`skipped`/`failed`)、observed_price、error |
| Bot 觸發 / cooldown / max_runs 守護 | ✅ 已實作 | `services/trading/engine.py:_bot_trigger_hit` 與 `run_trading_bot_rows` |
| Wallet/Ledger replay 對帳 | ✅ 可離線跑 | 使用目前 tests / validation scripts 重產 evidence |
| 手算 spot/DCA 訂單金額/手續費/PnL | ✅ 可離線跑 | 使用目前 tests / validation scripts 重產 evidence |
| 用戶送 bug 報告 | ✅ 已實作 | `POST /api/bug-reports` 與 admin 端 `/api/admin/bug-reports/<id>/review`；`routes/bug_reports.py` |
| 定期 bot 稽核 | ✅ 已實作 | `run_due_bot_audits()`；預設每 `300s` 掃一次，可由 root 調整 |
| 納入稽核條件守門 | ✅ 已實作 | bot 至少成交 1 筆，或啟用已滿 `24h` 才從 `未稽核` 進入綠 / 黃 / 紅燈 |
| root-only 稽核 dashboard | ✅ 已實作 | `GET /api/root/trading/bot-audit/dashboard`；顯示未稽核 / 綠燈 / 黃燈 / 紅燈、最近錯誤、交易 bug reports |
| root 手動重跑稽核 | ✅ 已實作 | `POST /api/root/trading/bot-audit/run` |
| 排程自動執行稽核 | ✅ 已實作 | trading bot worker 內會依 root 設定的 interval / limit 自動跑 |
| 黃燈 / 紅燈通知 root 與 bot owner | ✅ 已實作 | 建立 notification 與 `TRADING_BOT_AUDIT_RUN` audit event |
| 訂單旁綠燈 / 黃燈 UI | ⚠️ 部分實作 | root dashboard 有燈號；交易列表本身尚未逐列顯示 |
| 一鍵「提交 bug」按鈕 | ⚠️ 部分實作 | bug report 清單已整合進 dashboard；仍未從特定 bot/order 行旁直接觸發 |
| Safe mode 自動鎖 trading | ✅ 已實作 | `trading_state.safe_mode` 旗標；`scan_margin_liquidations` / `_assert_writable` 路徑會檢查 |

## 使用方法

### 一般使用者

- 在交易頁建立 / 啟用 / 暫停 / 刪除自己的 bot：`/api/trading/bots`、`/api/trading/grid-bots`
- 查看自己 bot 的近期觸發紀錄：透過 dashboard 的 `bots`、`bot_runs`、`fills` 區塊
- 發現結果與預期不符時：使用 bug-reports 頁送 issue（含 bot_uuid、order_uuid、預期 vs 實際）

### Admin / Root

- `GET /api/admin/audit?event_type=TRADING_BOT_*` — 查 bot 生命週期事件
- `GET /api/admin/points/ledger` — 查 PointsChain ledger，搭配 reference_type=`trading_*` 過濾
- `GET /api/root/points/chain/verify` — 對帳 wallet vs ledger
- `GET /api/admin/health/audit-chain` — 主稽核鏈完整性
- `POST /api/trading/bots/scan` — 手動觸發 bot 巡檢（owner 角色）
- `POST /api/root/trading/liquidations/scan` — 手動觸發清算掃描（root）
- `GET /api/root/trading/bot-audit/dashboard` — 看 root-only 稽核總覽、未稽核原因、最近燈號與 trading bug 報告
- `POST /api/root/trading/bot-audit/run` — 立即重跑稽核
- `POST /api/admin/bug-reports/<id>/review` — 處理用戶 bug 報告

## 原理

1. 任何寫入交易資料表（`trading_orders`、`trading_fills`、`trading_bot_runs`、`trading_margin_positions`...）都會 **同時** 寫一筆 `secure_audit`（hash chain）與 `trading_audit_events`（結構化 metadata）。
2. PointsChain ledger 用 `previous_ledger_hash` + `ledger_hash` 串接成不可變鏈；wallet 餘額可由 ledger replay 重建（`07_POINTSCHAIN.md`）。
3. Bot 每次巡檢依 `last_run_at` + `cooldown_seconds` 與 `interval_hours` 判斷是否該觸發；`run_count < max_runs` 限制最多執行次數。
4. 訂單金額、手續費、PnL 全部於伺服器端用 integer POINTS 計算 (`fee_points()` 用 `Decimal.ROUND_HALF_UP`、`notional_points()` 用 `ceil`)。
5. 異常透過 audit event + last_error 欄位 + 主稽核鏈 + 通知中心 (`/api/notifications`) 多重落點。
6. 稽核不是 bot 一啟用就立刻打燈。為避免新 bot 還沒碰到任何條件就被誤標，系統會先標成 `未稽核`；等它至少成交 1 筆，或啟用已滿 `24h`，才進入綠 / 黃 / 紅燈狀態。

## 失敗情境與提示

| 情境 | 提示位置 |
|---|---|
| Bot 觸發失敗 | `trading_bot_runs.error`、`trading_bots.last_error`、audit event `TRADING_BOT_RUN_FAILED` |
| 餘額 / ledger 對帳不一致 | `points_chain.verify` 回 `error_count > 0`，並寫 `POINTS_CHAIN_VERIFY_FAILED` 事件 |
| Bot 觸發 cooldown 守護生效 | scan response `skipped[].reason="cooldown"` |
| max_runs 限額達到 | `run_count >= max_runs` 時下次掃描 query 排除（`b.run_count < b.max_runs`） |
| Trading safe_mode 啟動 | `_assert_writable` 拋出，新單與 bot 巡檢都被擋 |
| 用戶側送 bug | `/api/bug-reports` 創建後通知 admin，root/admin 在 bug-reports 頁可 review |
| root 稽核 dashboard 看到 `未稽核` | 正常，表示該 bot 尚未成交，且也還沒啟用滿 24 小時 |
| root 稽核 dashboard 出現黃燈 / 紅燈 | 查看該 bot 的 `last_error`、recent findings 與 trading bug reports；系統同時會寫 `TRADING_BOT_AUDIT_RUN` audit event |

## 測試方式

```bash
# 1. 隔離環境啟動 (見 docs/AGENTS/QA_MISSION_FOR_AGENTS.md)
./test_for_develop.sh --port 50785

# 2. root bot audit dashboard / 手動稽核
curl -ksS https://127.0.0.1:5000/api/root/trading/bot-audit/dashboard
curl -ksS -X POST https://127.0.0.1:5000/api/root/trading/bot-audit/run

# 3. 引擎內建 deterministic 驗證
python3 scripts/trading/validation/trading_exchange_validation.py --out /tmp/trading_audit_check
python3 scripts/trading/validation/trading_workflow_template_validation.py --no-download --limit 200 --out /tmp/trading_audit_check
python3 scripts/trading/probes/backtest_20000_probe.py --include-route --json-out /tmp/trading_audit_check/backtest_20000.json

# 6. 既有 pytest 回歸
scripts/testing/pytest_in_tmp.sh -q tests/trading/core/test_trading_engine.py tests/points/test_points_chain.py
```

目前這三支交易驗證腳本的分工是：

- `scripts/trading/validation/trading_exchange_validation.py`
  - deterministic spot / DCA / workflow / grid / margin / liquidation 正確性
  - 額外檢查連續加倉後 `avg_cost_points` 是否仍合理，避免交易腳本靜默接受異常成本基礎
- `scripts/trading/validation/trading_workflow_template_validation.py`
  - 12 個 official workflow templates 的 trigger semantics
  - Bollinger 類模板的 `flat sequence` no-false-trigger guard
  - graph workflow 改用 trigger scenario + flat guard + engine sanity 檢查，不再沿用舊的過時 replay oracle
- `scripts/trading/probes/backtest_20000_probe.py`
  - `20,000` candle segmented backtest
  - four bot families / route payload / over-limit reject
  - `single_candle_rejected_without_silent_fetch`
  - `backtest_outlier_jump_skipped`
  - `workflow_flat_bollinger_guard`

## 相關文件連結

- QA 任務書：[`docs/AGENTS/TRADING_SYSTEM_QA_FOR_AGENTS.md`](../AGENTS/TRADING_SYSTEM_QA_FOR_AGENTS.md)
- 交易引擎：[`docs/08_TRADING_ENGINE.md`](../08_TRADING_ENGINE.md)
- PointsChain：[`docs/07_POINTSCHAIN.md`](../07_POINTSCHAIN.md)
- 已知未解 issue（鏈化前仍需注意）：[GitHub #122](https://github.com/s9213712/hackme_web/issues/122)
