# 12 Troubleshooting

一句話說明：這份文件集中列出新部署者、root、一般使用者最常遇到的錯誤與第一輪排查方式。

## 設計目的

過去錯誤排查散在各功能文件，部署者容易知道「它壞了」但不知道「先去哪一份找解法」。這份文件把常見故障先收斂成運維與使用情境導向的入口。

## 使用方法

### 啟動 / 部署類

#### 1. 服務啟動了但打不開

先檢查：

- host / port 是否正確
- 如果你是直接執行 `python3 server.py`，是否其實應該用
  `https://127.0.0.1:5000/` 而不是 `http://127.0.0.1:5000/`
- port 是否被占用
- 代理 / HTTPS / cookie 設定是否跟實際部署拓樸一致

#### 2. 頁面正常但登入或寫入 API 全部 `403`

優先看：

- CSRF token 是否失效
- 是否剛改完 bootstrap 密碼；改密碼後舊 session 會立即失效，需重新登入再取新 CSRF token
- 是否剛改密碼 / 登出 / 權限切換 / reset 過
- 是否在舊分頁上送請求

#### 3. 啟動後跑出很多 runtime 檔，不確定能不能 commit

不能。DB、logs、storage、reports、keys、certs 都應留在部署地 runtime。

### 功能關閉 / 權限類

#### 4. 看到「此功能目前已由 root 關閉」

代表 feature flag 或相依模組未完整開啟，不一定是 bug。先看：

- [03_ADMIN_GUIDE.md](03_ADMIN_GUIDE.md)
- [05_FEATURES_OVERVIEW.md](05_FEATURES_OVERVIEW.md)

新版訊息若有帶出「被關閉的父功能」或「會一起受影響的已開功能」，先照那份提示回頭檢查，不要只看你原本想用的那個頁面開關。

#### 5. 看到權限不足

先分辨：

- 你真的角色不夠
- 該模組需要更高 member level
- root 只開了入口沒開完整底層功能

#### 5-1. 找不到個人外觀，或外觀欄位無法編輯

先分辨：

- 你是不是用自己的帳號開 `修改資料`
- root 是否已關掉 `允許使用者覆寫個人外觀`
- 你是不是只做了預覽、但還沒按儲存
- 想直接回到全站預設時，請用編輯視窗底部的 `恢復全站預設`，再按一次 `儲存`

#### 5-2. 找不到 `Turnstile site key`

先分辨：

- `註冊 CAPTCHA 模式` 是不是 `turnstile`
- 如果目前是 `none / math / image`，這個 token 欄位現在會刻意隱藏
- 你是不是還停在舊快取頁面；先重新整理設定頁

#### 5-3. `設定已儲存` 一直掛著不消失

先分辨：

- 你看到的是不是黃色依賴警告，而不是綠色成功訊息
- 新版綠色 `設定已儲存` 會自動消失；若還一直停著，先重新整理確認是不是舊前端快取
- 若訊息內容有提到 `缺少父功能`，那不是 save 卡住，而是設定已寫入、但功能組合仍不完整

### Cloud Drive / Video / ComfyUI 類

#### 6. 影片或檔案無法預覽 / 播放

常見原因：

- E2EE 檔案無法走 server-side 影片串流
- `server_encrypted` 檔案的舊 key 已不可用
- 檔案被 quarantine / 權限不足 / visibility 不符

#### 7. ComfyUI 有頁面但不能下載模型

如果 root 把 ComfyUI 設成 remote API 模式，這是預期限制；模型下載只對
本地模式有意義。設定頁裡的 `Civitai API Key` 也只會在本地模式顯示。

#### 8. ComfyUI 找不到 Embedding / VAE / trigger words

先分辨：

- 頁面標題現在會明確顯示是本地模式還是雲端 / 遠端模式；先確認你看的模式是不是你以為的那個
- `Embedding` / `VAE` 清單是從 ComfyUI API 讀的；如果 ComfyUI 本身沒有列出，
  網頁也不會憑空顯示
- Civitai `trigger words` 只有 root、本地模式、且成功讀到該版本資訊時才會顯示
- LoRA 自動補 trigger words 只對「透過 root 的 Civitai 下載面板下載，且有保存 sidecar metadata」的 LoRA 生效
- ControlNet / Hypernetwork 下載選項不在目前 UI，這是刻意限制，不是載入失敗

#### 9. ComfyUI 長任務跑到一半

- 前端會暫停閒置登出；目前包含本地啟動、生圖、root 模型下載
- 若 job 卡住，先看 status / job progress / backend reachability

### 經濟 / 交易類

#### 10. 餘額看起來不對

先驗證：

- PointsChain verify
- 是否為 root 模擬交易餘額而非正式 wallet
- 是否為 restore / recovery 後尚未重建 wallet

#### 11. 交易頁數字正常但成交失敗

先看：

- live price provider 是否失效
- 如果 root 用的是 `融合價格（多交易所加權平均）`，先看是否只剩太少健康來源，或手動權重把有效來源全設成 0
- circuit breaker 是否擋下異常價格
- 餘額 / 借貸池 / 手續費條件是否不足

#### 11-0. root 找不到交易所融合權重設定，或改了卻沒有生效

先分辨：

- `價格來源` 是否仍是 `融合價格（多交易所加權平均）`
- 只有在 `root 手動權重` 模式下，手動權重輸入框才會生效
- 若你把所有手動權重都設成 0，系統會安全退回自動深度權重，而不是照 0 權重硬算出錯價
- 若某家交易所 API 失效，系統會用剩餘健康來源重算；這不等於設定沒有生效

#### 11-1. 小額交易的手續費和你手算不同

先分辨：

- 你是不是還在用舊版 `ceil` 心智模型手算
- 目前 release 是否已經是 `2026.05.03-063` 之後；新版整數 POINT fee 會用
  `Decimal` 後端計算後四捨五入到最近整點
- 你比較的是 `預估值` 還是實際成交 fill

#### 11-2. 定投機器人明明設成 `-1`，卻好像還是停了

先分辨：

- 你看的是否是 DCA 機器人；`-1` 只對定投機器人代表不限制
- 它是不是卡在冷卻時間 / 間隔時間，而不是次數上限
- 若 UI 顯示 `已觸發 x / 不限制`，代表上限邏輯已生效；若仍沒跑，應回頭查餘額、價格區間或功能開關

### 恢復 / reset 類

#### 12. reset 後資料不見

這通常是預期結果。先找：

- `pre_reset` snapshot
- reset 後是否已重啟

#### 13. restore 完還以為 secrets / certs 會回來

目前的 server snapshot 會一起保存並回放設定好的 runtime secret files。
如果 restore 後這些檔案沒有回來，先看 restore event 是否出現
`runtime secret validation failed`，再檢查 snapshot metadata 內的
`runtime_secret_files` 清單。

## 原理

這些故障大多不是單一頁面的問題，而是：

- runtime 目錄與 repo 混在一起
- feature flags 與底層依賴未成套啟用
- session / CSRF / role / member level 邊界被忽略
- 把 snapshot restore、PointsChain restore、reset 當成同一件事

## 失敗情境與提示

- 問題看起來是 UI，但其實是權限或後端模式：
  先從 feature flags / role / mode / CSRF 開始排。
- 問題看起來是資料壞了，但其實只是顯示舊頁：
  先重新整理、重新登入、重新取 token。
- 問題看起來是功能 bug，但其實是部署拓樸錯誤：
  先檢查 HTTPS、proxy、runtime path、XFF 信任設定。
- 問題看起來像是 QA 腳本互打：
  先確認 smoke 與 pentest 是否共用同一組 smoke 帳密，以及 whole-site gate
  是否已用新版 timeout floor。

## 測試方式

- 把本文件列出的常見錯誤納入 smoke / pentest / 手動 QA
- 驗證錯誤訊息是否能讓使用者知道：
  - 發生什麼事
  - 為什麼可能失敗
  - 下一步可以怎麼做
- 驗證 root 可在 log / audit / job status 中查到原因

## 相關文件連結

- [01_DEPLOY_QUICKSTART.md](01_DEPLOY_QUICKSTART.md)
- [02_DEPLOY_PRODUCTION.md](02_DEPLOY_PRODUCTION.md)
- [03_ADMIN_GUIDE.md](03_ADMIN_GUIDE.md)
- [05_FEATURES_OVERVIEW.md](05_FEATURES_OVERVIEW.md)
- [06_SECURITY_MODEL.md](06_SECURITY_MODEL.md)
- [09_SNAPSHOT_RESET_RESTORE.md](09_SNAPSHOT_RESET_RESTORE.md)
- [11_QA_TESTING.md](11_QA_TESTING.md)
