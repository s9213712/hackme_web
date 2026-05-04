# Trading Bot Audit Daemon Agent Command

## 任務名稱

建立「全站交易機器人自動稽核巡檢器 / Trading Bot Audit Daemon」，並新增後台與前台訂單可視化稽核狀態。

---

## 核心目標

你是一位專業後端工程師、QA 工程師與交易系統稽核工程師。請在 `hackme_web/` 專案中新增一套後台定時任務，定期自動檢查全站所有交易機器人、歷史訂單、觸發紀錄、成交金額、盈虧、手續費、利息、wallet、ledger、position 是否正確。

這不是普通 smoke test，而是交易系統正式上線前必備的 Release Gate。

系統必須能證明：

1. 該觸發時有觸發。
2. 不該觸發時沒有誤觸發。
3. 機器人訂單時間正確。
4. 成交價格、數量、金額正確。
5. 手續費正確。
6. 盈虧正確。
7. wallet / ledger / position 可對帳。
8. 異常不可靜默，必須提醒。
9. BLOCKER 異常必須自動保護系統。
10. 稽核結果必須在機器人訂單旁可視化顯示。

---

## 必須遵守的專案工作原則

新增功能時必須同步更新：

- README
- 教學文件
- 後台說明文件
- QA 文件
- 測試腳本
- smoke / regression 測試

所有失敗情境都必須有明確提示，不准靜默失敗。

所有前端提示必須人性化，並支援手機版。

所有可在伺服器端運算的交易、稽核、盈虧、手續費、利息、帳本對帳，都必須在伺服器端完成，不可交給客戶端自行計算。

---

## 建議新增模組

依專案既有架構調整，但至少應新增或整合以下模組：

```text
services/trading_bot_auditor.py
services/trading_audit_scheduler.py
routes/admin_trading_audit.py
templates/admin_trading_audit.html
```

若專案已有 scheduler / background job / admin route，請整合進既有系統，不要重複造輪子。

---

## 巡檢頻率

root 後台必須可設定巡檢頻率：

```text
每 1 分鐘
每 5 分鐘
每 15 分鐘
每 1 小時
每日
手動立即執行
```

預設建議：

```text
每 5 分鐘：輕量稽核
每 1 小時：完整稽核
每日：歷史深度稽核
```

---

## 稽核範圍

### 1. Bot 執行狀態檢查

檢查每個啟用中的 bot：

```text
- bot 是否 enabled
- bot_type 是否合法
- strategy config 是否完整
- next_run_at 是否正確
- last_run_at 是否更新
- last_error 是否有記錄
- 是否超過預定時間仍未執行
- 是否重複執行
- 是否跳過但沒有 reason
- disabled bot 是否仍然下單
```

異常例子：

```text
- bot 應每 1 小時檢查一次，但 3 小時未執行
- bot 已 disabled 卻仍下單
- bot enabled 但 scheduler 沒有紀錄
- bot 觸發失敗但沒有錯誤提示
```

---

### 2. 觸發條件稽核

對每筆 bot decision / trigger log 重新計算一次條件。

必須檢查：

```text
- 價格條件
- MA / EMA
- RSI
- KD
- MACD
- Bollinger Band
- ADX
- CHOP
- 等待秒數
- 每日 / 每週 / 每小時觸發時間
- 且 / 或 條件樹
- 巢狀 workflow node
```

每筆紀錄要驗證：

```text
expected_trigger = auditor 重新計算結果
actual_trigger = 系統當時是否觸發
```

若出現：

```text
expected=true, actual=false
```

代表「應觸發卻沒觸發」，列為 High severity。

若出現：

```text
expected=false, actual=true
```

代表「不該觸發卻誤觸發」，列為 High severity 或 Release Blocker。

---

### 3. 歷史訂單時間稽核

檢查每筆由 bot 建立的訂單：

```text
- created_at 是否落在 bot 執行窗口內
- triggered_at 是否早於或等於 order created_at
- filled_at 是否晚於或等於 created_at
- cancelled_at 是否晚於或等於 created_at
- 同一 bot 是否短時間重複觸發
- 是否違反 cooldown
- 是否違反 max_orders_per_period
- 是否使用 stale price
- 是否時間倒退
```

Release Blocker：

```text
- 時間倒退
- 未觸發卻產生訂單
- disabled bot 產生訂單
- cooldown 內重複下單
- 使用過期價格下單
```

---

### 4. 金額 / 盈虧 / 手續費重算

對每筆成交重新計算：

```text
notional = price * quantity
fee = notional * fee_rate
buy_cost = notional + fee
sell_return = notional - fee
realized_pnl = sell_return - cost_basis
unrealized_pnl = current_price * position_qty - cost_basis
```

必須使用 Decimal，不准使用 float 處理金額。

必須檢查：

```text
- 訂單金額是否正確
- 手續費是否正確
- 買入成本是否正確
- 賣出收益是否正確
- 已實現盈虧是否正確
- 未實現盈虧是否正確
- 平倉後 position 是否歸零
- 小數是否被錯誤四捨五入成 0
- 交易後 wallet 是否正確扣款 / 入帳
- 利息是否即時計算並反映到前台
```

任何差異超過設定容忍值，例如：

```text
0.00000001 points
```

都必須記錄。

---

### 5. Wallet / Ledger / Position 對帳

每日深度稽核必須從 ledger / fills 重新 replay：

```text
wallet balance
trading balance
locked balance
spot position
futures position
fee ledger
interest ledger
trial credit balance
```

必須檢查：

```text
- wallet 是否可由 ledger 重建
- position 是否可由 fills 重建
- bot order 是否都有 ledger event
- ledger event 是否都有對應 order/fill
- fee 是否入帳
- interest 是否入帳
- trial_credit 是否沒有污染正式資產
```

Release Blocker：

```text
wallet != ledger replay
position != fills replay
fee missing
interest missing
trial_credit 混入正式 wallet
```

---

## 稽核結果分級

每次巡檢必須產生 audit report：

```text
PASS
WARN
FAIL
BLOCKER
```

建議分級：

```text
BLOCKER:
- 金額錯
- wallet/ledger 不一致
- 不該觸發卻下單
- disabled bot 下單
- stale price 下單
- silent fallback
- trial credit 污染正式資產

FAIL:
- 應觸發但沒觸發
- cooldown 失效
- 手續費顯示錯
- PnL 顯示錯
- bot scheduler 延遲過久

WARN:
- 某交易所價格來源失敗但已排除
- bot 延遲但尚未超過上限
- 小額 rounding 接近容忍值

PASS:
- 全部對帳一致
```

---

## 訂單旁稽核燈號與提交 Bug 按鈕

### 1. 機器人訂單列表必須顯示稽核狀態

在所有 bot order / trading bot order / workflow bot order / DCA order / grid bot order 的列表中，每一筆訂單旁邊都要顯示稽核狀態燈號。

燈號規則：

```text
綠燈：audit_status = PASS
黃燈：audit_status = WARN / FAIL / BLOCKER / UNKNOWN / NOT_AUDITED
```

不可只用顏色，必須同時提供文字與 tooltip，避免色盲或手機使用者看不懂。

範例：

```text
🟢 稽核通過
🟡 待確認 / 發現異常 / 尚未稽核
```

若是 BLOCKER，可以在黃燈旁額外顯示：

```text
高風險
```

但基本規則仍是：

```text
PASS = 綠燈
非 PASS = 黃燈 + 提交 bug 按鈕
```

---

### 2. 黃燈訂單必須顯示「提交 Bug」按鈕

當訂單稽核狀態不是 PASS 時，該訂單旁必須出現：

```text
提交 Bug
```

按鈕功能：

- 只有 root / admin 可提交。
- 一般使用者不可提交內部 bug，但可看到人性化提示，例如「此訂單正在審核中」。
- 點擊後自動帶入該筆訂單的稽核資料。
- 不要求人工重新複製一堆資訊。

提交內容至少包含：

```text
- bot_id
- user_id
- order_id
- audit_report_id
- audit_status
- severity
- expected
- actual
- difference
- raw evidence
- server time
- affected module
- suggested issue title
- suggested reproduction steps
```

---

### 3. Bug 提交方式

可先實作成內部 bug report，不一定第一版就要直接打 GitHub API。

建議新增資料表或既有 issue/bug 模組整合：

```text
trading_audit_bug_reports
```

欄位建議：

```text
id
created_at
created_by
bot_id
order_id
user_id
audit_report_id
severity
status
summary
expected
actual
difference
evidence_json
linked_github_issue_url
acknowledged_by
acknowledged_at
```

若專案已有 GitHub issue 建立流程，可提供 root-only 按鈕：

```text
建立 GitHub Issue
```

但不得在沒有 root 確認時自動對外提交。

---

### 4. 訂單稽核狀態 API

訂單列表 API 應回傳稽核欄位：

```json
{
  "order_id": 123,
  "audit_status": "PASS",
  "audit_severity": null,
  "audit_report_id": 456,
  "audit_summary": "金額、時間、手續費、觸發條件皆通過",
  "can_submit_bug": false
}
```

非 PASS 範例：

```json
{
  "order_id": 124,
  "audit_status": "FAIL",
  "audit_severity": "HIGH",
  "audit_report_id": 457,
  "audit_summary": "應觸發條件為 false，但系統仍建立訂單",
  "can_submit_bug": true
}
```

---

### 5. UI 要求

後台與訂單列表必須支援：

```text
- 桌機版表格
- 手機版卡片式顯示
- 燈號 + 文字 + tooltip
- 黃燈旁顯示提交 Bug 按鈕
- 點開可看 expected / actual / difference
- loading state
- failed state
- 無稽核資料時顯示「尚未稽核」，不可空白
```

手機版不可把「提交 Bug」按鈕擠出畫面。

---

## 後台頁面

root / admin 後台新增：

```text
交易稽核中心
```

顯示：

```text
- 最近一次稽核時間
- 稽核狀態燈：綠 / 黃 / 紅 / 黑
- 啟用中 bot 數量
- 異常 bot 數量
- 異常訂單數量
- wallet/ledger mismatch 數量
- 手續費錯誤數量
- PnL 錯誤數量
- stale price 事件
- silent fallback 事件
- 已提交 bug 數量
- 待 root 確認 bug 數量
```

每個異常要能點開看到：

```text
- bot_id
- user_id
- order_id
- expected
- actual
- difference
- severity
- raw evidence
- 建議修復方向
- 提交 Bug 按鈕
- 若已提交，顯示 bug report id / GitHub issue URL
```

---

## 失敗提醒與 Safe Mode

所有異常都不能靜默。

必須通知：

```text
- 後台紅燈 / 黃燈
- admin audit log
- server log
- optional webhook / email
```

若 BLOCKER：

```text
- 自動進入 trading_safe_mode
- 暫停 bot 自動下單
- 允許人工平倉，但禁止新開倉
- root 必須確認後才能解除
```

---

## API 建議

新增或整合以下 API：

```text
GET  /api/admin/trading-audit/status
POST /api/admin/trading-audit/run
GET  /api/admin/trading-audit/reports
GET  /api/admin/trading-audit/reports/<id>
POST /api/admin/trading-audit/<id>/ack
POST /api/admin/trading-audit/safe-mode/enable
POST /api/admin/trading-audit/safe-mode/disable
POST /api/admin/trading-audit/reports/<id>/submit-bug
GET  /api/admin/trading-audit/bug-reports
GET  /api/admin/trading-audit/bug-reports/<id>
POST /api/admin/trading-audit/bug-reports/<id>/ack
POST /api/admin/trading-audit/bug-reports/<id>/create-github-issue
```

權限：

```text
root:
- 全部操作
- 可解除 safe mode
- 可建立 GitHub issue

admin:
- 只讀
- 可 ack
- 可提交內部 bug report
- 不可解除 safe mode
- 不可直接建立 GitHub issue，除非 root 授權

一般用戶:
- 不可存取後台稽核 API
- 可在自己的訂單看到人性化稽核狀態摘要
- 不可看到其他用戶、內部 raw evidence、server log
```

---

## 測試要求

必須新增測試腳本：

```text
tests/test_trading_bot_auditor.py
tests/test_trading_audit_scheduler.py
tests/test_trading_audit_financial_replay.py
tests/test_trading_audit_ui.py
tests/test_trading_audit_bug_report.py
```

必測案例：

```text
1. bot 應觸發但沒觸發
2. bot 不該觸發卻下單
3. disabled bot 下單
4. cooldown 內重複下單
5. 手續費少扣
6. PnL 算錯
7. wallet / ledger 不一致
8. position / fills 不一致
9. stale price 下單
10. trial_credit 污染正式資產
11. 小數 rounding 成 0
12. BLOCKER 自動進入 trading_safe_mode
13. safe mode 禁止新 bot order
14. root ack 後才能解除
15. PASS 訂單旁顯示綠燈
16. WARN / FAIL / BLOCKER / UNKNOWN 訂單旁顯示黃燈
17. 黃燈訂單顯示提交 Bug 按鈕
18. 綠燈訂單不顯示提交 Bug 按鈕，或顯示 disabled 狀態並說明無需提交
19. 提交 Bug 時自動帶入 bot_id / order_id / audit_report_id / expected / actual / evidence
20. 一般用戶不可存取內部 raw evidence
21. 手機版訂單卡片可正常顯示燈號與提交 Bug 按鈕
```

---

## QA / Release Gate

此功能完成後，交易系統 release gate 必須新增：

```text
Trading Bot Audit Gate
```

禁止 release 條件：

```text
- 有任何 BLOCKER 稽核異常
- 有 wallet / ledger mismatch
- 有 position / fills mismatch
- 有手續費或 PnL 重算錯誤
- 有不該觸發卻下單
- 有 disabled bot 下單
- 有 stale price 下單
- 有稽核異常但前台沒有燈號
- 有黃燈訂單但沒有提交 Bug 按鈕
- 有提交 Bug 卻缺 expected / actual / evidence
```

允許 release 條件：

```text
- 稽核 daemon 可定時執行
- 手動稽核可執行
- PASS 訂單顯示綠燈
- 非 PASS 訂單顯示黃燈
- 黃燈訂單可提交 Bug
- BLOCKER 會進 trading_safe_mode
- safe mode 解除需要 root
- 文件與測試同步更新
```

---

## 文件同步

新增或更新：

```text
README.md
docs/TRADING_ENGINE.md
docs/TRADING_BOT_AUDIT.md
docs/ADMIN_GUIDE.md
docs/QA_TRADING_AUDIT.md
```

文件必須說明：

```text
- 稽核器用途
- 巡檢頻率
- 異常分級
- safe mode 條件
- root 如何查看報告
- 如何手動重跑稽核
- 如何驗證 wallet / ledger
- 訂單旁綠燈 / 黃燈代表什麼
- 什麼情況會出現提交 Bug 按鈕
- 如何建立內部 bug report
- 如何由 root 建立 GitHub issue
```

---

## 最重要原則

交易機器人不是只要會下單就算完成。

必須能證明：

```text
1. 該下單時有下單
2. 不該下單時沒有下單
3. 下單時間正確
4. 金額正確
5. 手續費正確
6. 盈虧正確
7. 帳本正確
8. 失敗有提醒
9. 異常會自動保護系統
10. 使用者與管理員看得到稽核狀態
11. 非通過訂單可以一鍵提交 bug
```

最終驗收標準：

```text
可重算、可對帳、可追蹤、可提醒、可提交 bug、可阻擋 release。
```
