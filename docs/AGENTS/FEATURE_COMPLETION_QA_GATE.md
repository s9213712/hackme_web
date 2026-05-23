# Feature Completion QA Gate

任何新功能、權限變更、金流/積分/交易流程、root/admin 工具、資料刪除/還原、
前端互動或安全控制完成後，都必須跑一次針對該功能的 QA gate。不得只用
「pytest 通過」或「手動按過正常流程」宣稱完成。

## 必測面向

每次新功能完成後，至少覆蓋：

- 正常流程：目標使用者能完成主要操作，成功訊息清楚。
- 找碴流程：空值、極大值、極小值、格式錯誤、重複送出、快速連點、跨頁返回。
- 例外流程：依賴服務失敗、DB/檔案缺失、timeout、部分成功、重試、取消。
- 權限流程：未登入、一般用戶、目標用戶、manager、admin、root、跨帳號存取。
- 提權流程：改 user_id、wallet address、role flag、owner id、proposal uuid、交易 hash。
- 違規流程：被凍結、被封鎖、餘額不足、quota 超限、rate limit、CSRF/Session 失效。
- 滲透流程：IDOR、CSRF、XSS/HTML 注入、SQL-like payload、路徑穿越、檔名/metadata 注入。
- 競態流程：並發提交、double spend、重複 idempotency key、同時 approve/execute/cancel。
- 壓力流程：高併發、burst、長時間輪詢、背景 worker 堆積、DB lock/backpressure。
- 性能流程：API latency、頁面互動延遲、查詢掃描量、N+1、記憶體/CPU/IO 明顯劣化。
- 觀測流程：audit/log/report 能追到原因，不得靜默失敗。
- 手機/前端流程：小螢幕不破版，按鈕/錯誤提示不重疊，操作有處理中/成功/失敗狀態。

## 強度分級

Low risk:
- 純文案、純展示、非敏感 UI。
- 至少跑靜態檢查、目標 pytest、前端 smoke、異常輸入。

Medium risk:
- 一般登入後功能、資料 CRUD、通知、上傳、背景任務。
- 另需權限矩陣、IDOR/CSRF、併發重複提交、手機檢查。

High risk:
- 積分、錢包、交易、治理、root/admin、刪除/還原、帳號安全、付款、公開分享。
- 另需針對性壓測、性能檢查、滲透式 QA、提權/違規/例外行為、race-condition、
  replay/對帳或資料不變量檢查。

## 完成回報格式

功能完成回報必須列出：

- Targeted QA gate：pass/fail。
- 跑了哪些壓力、性能、滲透、找碴、提權、違規、例外行為測試。
- 用到的命令、live URL、報告路徑、artifact 路徑。
- 發現的問題、修正狀態、重測結果。
- 未跑項目與原因。

若 gate 未跑或有 blocker，不得宣稱該功能完整完成。
