# 12 Troubleshooting

一句話說明：這份文件集中列出新部署者、root、一般使用者最常遇到的錯誤與第一輪排查方式。

## 設計目的

過去錯誤排查散在各功能文件，部署者容易知道「它壞了」但不知道「先去哪一份找解法」。這份文件把常見故障改成固定分類與穩定 ID，方便快速搜尋與轉貼。

## 使用方法

先找對分類，再搜尋穩定 ID，例如：

- `TRB-BOOT-001`
- `TRB-AUTH-001`
- `TRB-TRADING-001`

## A. 啟動 / 部署

### TRB-BOOT-001 服務啟動了但頁面打不開

先檢查：

- host / port 是否正確
- 先看 server console 印出的實際 URL，不要先假設一定是 HTTP
- 若你是直接執行 `python3 server.py`，本機通常應優先嘗試
  `https://127.0.0.1:5000/`
- port 是否被占用

### TRB-BOOT-002 頁面正常但登入或寫入 API 全部 `403`

優先看：

- CSRF token 是否失效
- 是否剛改完 bootstrap 密碼；改密碼後舊 session 會立即失效
- 是否在舊分頁上送請求

### TRB-BOOT-003 repo 根目錄冒出很多 runtime 檔

不能 commit。DB、logs、storage、reports、keys、certs 都應留在部署地 runtime。
若你不確定 runtime 邊界，回頭看 [02_DEPLOY_PRODUCTION.md](02_DEPLOY_PRODUCTION.md)。

## B. 登入 / CSRF / Session

### TRB-AUTH-001 root 忘記密碼

不要走登入頁的 `忘記密碼`。正式補救方式是到站台實體 runtime 上執行：

```bash
python3 scripts/root_recovery.py --prompt-password
```

這會撤銷 root 既有 session，並要求下次登入立刻改密碼。

### TRB-AUTH-002 改完 bootstrap 密碼後被登出

這是預期安全行為。重新登入、重新取得 CSRF token 後再繼續操作。

## C. 權限 / Feature Flags

### TRB-FEATURE-001 看到「此功能目前已由 root 關閉」

這通常不是 bug，而是 feature flag 或父功能未完整開啟。先看：

- [03_ADMIN_GUIDE.md](03_ADMIN_GUIDE.md)
- [05_FEATURES_OVERVIEW.md](05_FEATURES_OVERVIEW.md)

### TRB-FEATURE-002 看到權限不足

先分辨：

- 你真的角色不夠
- 該模組需要更高 member level
- root 只開了入口，沒有開完整底層功能

## D. Cloud Drive / Upload / Preview

### TRB-DRIVE-001 root 上傳大檔直接收到 HTTP `413`

先分清楚這不是配額，而是單次 request body 上限。先看：

- `HTML_LEARNING_MAX_CONTENT_MB`
- 反向代理的 body size 限制
- 這台 runtime 是否其實還跑舊版 server code

### TRB-DRIVE-002 PDF / 壓縮檔 / 一般檔案預覽不正常

先分辨：

- 是不是舊前端快取
- plain / `server_encrypted` PDF 是否能走原生 viewer
- strict `e2ee` PDF 是否改走瀏覽器端解密或新分頁備援
- 壓縮檔預覽是否仍像單段文字；若是，多半是舊快取

### TRB-DRIVE-003 第二個 E2EE 檔案又要求重新輸入密碼

新版會先嘗試同一次登入 session 最近成功過的密碼。若仍跳出詢問，通常代表：

- 兩個檔案不是同一組密碼
- 你中途已登出
- 或前端仍是舊快取

## E. Video / E2EE / HLS

### TRB-VIDEO-001 影片無法預覽 / 播放

先看：

- E2EE 檔案本來就不能走伺服器端 HLS
- `server_encrypted` 影音的舊 key 是否仍可用
- 檔案是否被 quarantine / 權限不足 / visibility 不符

### TRB-VIDEO-002 strict E2EE 共享影音一直顯示讀取中

共享頁新版應依序顯示：

1. `正在讀取 E2EE 分享授權`
2. `正在下載加密影音檔`
3. `正在瀏覽器端解密影音`

若你只看到單句 `讀取中`，多半是前端快取未更新。

## F. ComfyUI / Civitai

### TRB-AI-001 ComfyUI 有頁面但不能下載模型

若 root 把 ComfyUI 設成 `remote` API 模式，這是預期限制；模型下載只對
`local` 模式有意義。

### TRB-AI-002 找不到 Embedding / VAE / trigger words

先分辨：

- `Embedding` / `VAE` 清單是否真的有被 ComfyUI API 回傳
- LoRA 是否是透過 root 的 Civitai 下載面板下載
- 目前模型類型是否屬於 UI 支援範圍

### TRB-AI-003 ComfyUI 長任務逾時

先分辨：

- 是 ComfyUI 真正在排隊 / 載模型 / 生成太久
- 還是你目前瀏覽器頁面仍是舊前端快取

若 log 裡仍是後端先回 `ComfyUI 產圖逾時`，再檢查模型大小、顯卡負載與
ComfyUI 服務本身狀態。

## G. PointsChain / Wallet / Ledger

### TRB-POINTS-001 餘額看起來不對

先驗證：

- PointsChain verify
- 是否其實在看 root 模擬交易餘額，而不是真實 wallet
- 是否是 restore / recovery 後尚未重建 wallet

### TRB-POINTS-002 restore 後 wallet / ledger 不一致

先停在 root-only 工具鏈，不要直接手改 DB。先看：

- [07_POINTSCHAIN.md](07_POINTSCHAIN.md)
- [09_SNAPSHOT_RESET_RESTORE.md](09_SNAPSHOT_RESET_RESTORE.md)

## H. Trading / Price / Bot / Backtest

### TRB-TRADING-001 交易頁數字正常但成交失敗

先看：

- live price provider 是否失效
- 如果 root 用的是融合價格，是否只剩太少健康來源
- circuit breaker 是否擋下異常價格
- 餘額 / 借貸池 / 手續費條件是否不足

### TRB-TRADING-002 交易圖表看不到 RSI / KD，或指標線顯示怪異

先分辨：

- 你是不是只開了價格 overlay，沒有勾 `RSI14` 或 `KD(9,3,3)`
- 頁面是不是仍為舊快取
- 資料窗口是否不足以畫出部分指標

### TRB-TRADING-003 bot / backtest / dashboard 行為不如預期

先看：

- 回測 K 棒上限是否足夠
- 目前價格是不是 degraded / fallback
- Bot 是否仍處於 `未稽核`
- 若牽涉 BTC_trade，外部 repo 狀態是否完整

## I. Snapshot / Restore / Reset

### TRB-RESTORE-001 restore 後狀態不對

先分辨：

- 是 DB 還原問題
- storage / secrets / reports 未同步回來
- 還是 wallet / ledger 需要重建

先看 [09_SNAPSHOT_RESET_RESTORE.md](09_SNAPSHOT_RESET_RESTORE.md)，不要直接在 production runtime 手改資料。

### TRB-RESTORE-002 不知道要 rollback 還是重新 restore

先確認：

- 這次 restore 前是否已有 `pre_restore` snapshot
- 問題是資料不一致，還是單純功能開關 / server mode 狀態不同

## J. Production Gate / Security Center

### TRB-GATE-001 launch-check / 文件捷徑打不開

先確認這台 runtime 是否已更新到最新 code，並重新整理 root 安全中心頁面。

### TRB-GATE-002 production gate 被擋下，但看不懂原因

先看：

- 哪一張卡是紅燈
- 是缺報告、報告未驗簽、還是前置條件未完成
- 是 root 狀態問題，還是 staging/prod 設定問題

### TRB-GATE-003 安全測試卡片顯示異常

新版安全中心應把滲透、越權、全功能、壓力測試拆成獨立卡片。若看起來仍是舊的單一卡片，多半是舊前端快取。

## 相關文件連結

- [01_DEPLOY_QUICKSTART.md](01_DEPLOY_QUICKSTART.md)
- [02_DEPLOY_PRODUCTION.md](02_DEPLOY_PRODUCTION.md)
- [03_ADMIN_GUIDE.md](03_ADMIN_GUIDE.md)
- [05_FEATURES_OVERVIEW.md](05_FEATURES_OVERVIEW.md)
- [07_POINTSCHAIN.md](07_POINTSCHAIN.md)
- [09_SNAPSHOT_RESET_RESTORE.md](09_SNAPSHOT_RESET_RESTORE.md)
- [11_QA_TESTING.md](11_QA_TESTING.md)
