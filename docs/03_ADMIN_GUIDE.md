# 03 Admin Guide

一句話說明：這份文件給 `root` 與 `admin/manager`，聚焦在「站點啟用後怎麼管理、怎麼避免把功能開一半」。

## 設計目的

本專案很多功能不是單獨存在，而是要搭配 feature flags、權限、storage、
PointsChain、snapshot、server mode 一起看。這份文件只保留管理入口與啟用順序；
細部功能說明請跳到對應深層文件。

## 第一次以 root 進站後先做

1. 修改 bootstrap 密碼。
2. 確認站點版本與基本設定。
3. 檢查 server mode / snapshot / audit / integrity 狀態。
4. 決定是否建立 manager/admin 與 test 帳號。
5. 決定哪些可選模組要啟用。

補充：

- root 若忘記密碼，不走一般 Web 忘記密碼流程；正式補救方式是到實體 runtime
  上執行 `python3 scripts/admin/root_recovery.py`
- 上線前不要只看 UI 能打開；至少再跑一次 [11_QA_TESTING.md](11_QA_TESTING.md)

## root / admin 分工建議

- `root`：server mode、snapshot restore、system reset、integrity、PointsChain root 操作、部署設定、交易 root 設定、ComfyUI 設定
- `admin/manager`：使用者審核、檢舉 / 申訴 / 治理通知、社群管理、日常審核；為管理目的可私訊非好友用戶，但一般用戶的好友限制仍由後端執行

## 建議的功能啟用順序

### 1. 基礎站點

- 帳號與認證
- chat / community / reports / notifications
- storage / attachments / albums

### 2. 營運安全組

這組建議一起開，不要只開單點：

- server modes
- snapshot / restore
- audit log
- integrity guard
- health center
- system resource board（CPU / GPU / VRAM / RAM）
- advanced security / account security / identity governance（依你需要）

### 3. 經濟與交易組

建議順序：

1. PointsChain / economy
2. 規則與 catalog
3. video tips 等經濟相依功能
4. trading
5. 壓力 / 恢復 / 異常處理驗證

root 積分錢包應檢查「資金池管理」、「全用戶倉位管理」與 PointsChain 目前在外積分統計；這些是部署前確認資金池、用戶部位與鏈上供給口徑的唯讀入口。交易費率、價格來源、回測容量、Bot 稽核、BTC_trade 整合與風控價格細節，都請改看深層文件。

### 4. 媒體與 AI 組

1. videos 依賴 Cloud Drive
2. HLS、E2EE streaming、BT/direct link 與大檔轉檔都應走背景任務或外部 worker，不要讓主 server request 同步解碼、轉檔或等待長時間下載
3. ComfyUI / Civitai 先決定是 `local` 還是 `remote`
4. root-only 模型下載、workflow preset、ControlNet / VAE / LoRA 等細節，請看專門文件；小 VRAM 主機請優先閱讀 ComfyUI performance hardening

### 5. 社群 / 好友 / 指定對象組

1. 個人面板與好友管理是一般使用者主功能，不放到 root 帳號管理當主要入口
2. 一般用戶在 PM、private group、指定對象分享等流程應只看到合法好友候選
3. root / manager 因站務可在會員管理、指定對象通知、官方群與管理 PM 中看到全站用戶；若對方也是自己的好友，列表應置頂並明確標示
4. 帳號管理可查看主頁、好友狀態、申請紀錄與 audit，但用途是治理 / 稽核，不是代替使用者管理好友

### 6. 站點外觀組

1. root 可改全站預設外觀
2. `允許使用者覆寫個人外觀` 決定一般用戶是否可儲存自己的主題
3. 若只想讓站點先穩定上線，外觀不是第一優先

## 高風險操作入口

- Snapshot / Restore / Reset：
  [09_SNAPSHOT_RESET_RESTORE.md](09_SNAPSHOT_RESET_RESTORE.md)
- Security Center / Production Gate：
  [11_QA_TESTING.md](11_QA_TESTING.md)、
  [12_TROUBLESHOOTING.md](12_TROUBLESHOOTING.md)
- PointsChain / Wallet / Ledger：
  [07_POINTSCHAIN.md](07_POINTSCHAIN.md)
- Trading root 設定 / 風控價格 / 回測容量：
  [08_TRADING_ENGINE.md](08_TRADING_ENGINE.md)、
  [TRADING.md](trading/TRADING.md)、
  [BACKTEST_CAPACITY_AND_TEMPLATE_BENCHMARKS.md](trading/BACKTEST_CAPACITY_AND_TEMPLATE_BENCHMARKS.md)
- ComfyUI / Civitai / Workflow preset：
  [COMFYUI_ADMIN.md](comfyui/COMFYUI_ADMIN.md)、
  [COMFYUI_PERFORMANCE_HARDENING.md](comfyui/COMFYUI_PERFORMANCE_HARDENING.md)、
  [WEB.md](WEB.md)
- 個人主頁 / 好友 / 指定對象：
  [USER_PROFILES_AND_FRIENDS.md](social/USER_PROFILES_AND_FRIENDS.md)
- BTC_trade 整合：
  [BTC_TRADE_INTEGRATION.md](trading/BTC_TRADE_INTEGRATION.md)

## 失敗情境與提示

- 使用者明明看到入口，點進去卻收到「此功能目前已由 root 關閉」：
  代表相關 feature flag、底層依賴或最低角色未完整開啟。先對照
  [05_FEATURES_OVERVIEW.md](05_FEATURES_OVERVIEW.md) 的模組依賴矩陣。
- root 按了 `最低維運`，結果某些頁面整批消失：
  這是預期行為；這個套餐會把站點收斂到最小可維運骨架。
- root 想開 ComfyUI 模型下載，但設定成 remote API：
  這是預期限制；遠端 API 模式不負責把模型下載到遠端主機。
- root 想找 `Turnstile site key`：
  先確認 `註冊 CAPTCHA 模式` 是否切到 `turnstile`；其他模式會刻意隱藏。
- root 想看主機是否被 ComfyUI、HLS、BT 或上傳吃滿：
  先看 Security Center 的系統資源看板；它顯示 CPU / GPU / VRAM / RAM，並有短暫快取避免刷新本身變成壓力來源。
- root 想知道交易價格怎麼融合，或找不到交易相關設定：
  先切到設定頁的 `交易所` 分頁，不要再去 `計費` 找。
- root 看到交易報表或全站倉位頁回 `503`：
  代表 background snapshot 尚未產生或 worker 暫停；新版 root report / sitewide 頁應讀 snapshot，不應在 root request 內即時計算全站重報表。
- admin 想做 snapshot restore / integrity approve / PointsChain rescue：
  這些是 root-only。

## 深層文件

- [05_FEATURES_OVERVIEW.md](05_FEATURES_OVERVIEW.md)
- [06_SECURITY_MODEL.md](06_SECURITY_MODEL.md)
- [07_POINTSCHAIN.md](07_POINTSCHAIN.md)
- [08_TRADING_ENGINE.md](08_TRADING_ENGINE.md)
- [09_SNAPSHOT_RESET_RESTORE.md](09_SNAPSHOT_RESET_RESTORE.md)
- [COMFYUI_ADMIN.md](comfyui/COMFYUI_ADMIN.md)
- [COMFYUI_PERFORMANCE_HARDENING.md](comfyui/COMFYUI_PERFORMANCE_HARDENING.md)
- [USER_PROFILES_AND_FRIENDS.md](social/USER_PROFILES_AND_FRIENDS.md)
- [BTC_TRADE_INTEGRATION.md](trading/BTC_TRADE_INTEGRATION.md)
- [BACKTEST_CAPACITY_AND_TEMPLATE_BENCHMARKS.md](trading/BACKTEST_CAPACITY_AND_TEMPLATE_BENCHMARKS.md)
- [WEB.md](WEB.md)
- [For_developer.md](For_developer.md)

## 測試方式

- 以 root 檢查各模組頁面是否能看到完整設定與狀態
- 以 admin/manager 驗證被允許與被禁止的管理操作
- 跑 [11_QA_TESTING.md](11_QA_TESTING.md) 中的權限、snapshot、PointsChain、交易回歸
- 對照 [05_FEATURES_OVERVIEW.md](05_FEATURES_OVERVIEW.md) 檢查各功能組是否成套
