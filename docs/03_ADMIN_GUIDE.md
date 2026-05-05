# 03 Admin Guide

一句話說明：這份文件給 `root` 與 `admin/manager`，聚焦在「站點啟用後怎麼管理、怎麼避免把功能開一半」。

## 設計目的

本專案很多功能不是單獨存在，而是要搭配 feature flags、權限、storage、
PointsChain、snapshot、server mode 一起看。這份文件把管理者最常做的事情整理成操作路徑與功能組合，降低誤開、誤關、只開半套的風險。

## 使用方法

### 第一次以 root 進站後先做

1. 修改 bootstrap 密碼
   改完後要重新登入，舊 session 會立即失效
1a. root 若日後忘記密碼，不走一般 Web 忘記密碼流程；正式補救方式是到實體 runtime 上執行
    `python3 scripts/root_recovery.py`
    產生臨時密碼。這會撤銷 root 既有 session，並要求下次登入立刻改密碼
2. 確認站點版本與基本設定
3. 檢查 server mode / snapshot / audit / integrity 狀態
4. 決定是否建立 manager/admin 與 test 帳號
5. 決定哪些可選模組要啟用

### 建議的功能組合

#### 基礎社群組

適合一般站點先上：

- 帳號與認證
- chat / community / reports / notifications
- storage / attachments / albums

#### 營運安全組

這組建議一起開，不要只開單點：

- server modes
- snapshot / restore
- audit log
- integrity guard
- health center
- advanced security / account security / identity governance（依你需要）

#### 經濟與交易組

這組建議按順序啟用：

1. PointsChain / economy
2. 規則與 catalog
3. video tips 等經濟相依功能
4. trading
5. 壓力 / 恢復 / 異常處理驗證
6. 交易相關 root 設定現在已從 `計費` 拆成獨立 `交易所` 分頁。價格來源預設改成多交易所融合價格；
   若你要人工控制各家交易所占比，再切到手動權重模式調整 Binance / OKX / Coinbase / Kraken / Gemini /
   Bitstamp 比例。新版同頁還有 root-only 的 `融合價格即時比例` dashboard，
   可直接看到各 provider 在本系統價格融合中的實際使用權重、被排除來源，以及是否已降級成保守模式
6.1. 交易費率與借貸預設也集中在這裡：
   現貨 fee 預設 `0.10%`、Grid 預設吃現貨 fee 的 `75%`（25% 折扣）、
   `BTC / ETH = 8% APR`、`USDT / POINTS = 10% APR`、每 `1` 小時計息、
   不足 `1` 小時以 `1` 小時計。這些都可由 root 調整。一般使用者建立
   Grid Bot 前，後端也會先回一份 fee-aware preview；若每格扣完費預期虧損
   會直接紅燈阻擋，利潤過薄則要求二次確認
7. 檢查 `交易機器人定期稽核` 是否要啟用，並確認 root-only dashboard 目前哪些
   bot 是 `未稽核`、哪些已進入綠燈 / 黃燈 / 紅燈；剛啟用但尚未成交的 bot
   在 24 小時內維持 `未稽核` 是預期行為，不是故障
8. 若你接了外部 `BTC_trade` 專案，可在同一個 `交易所參數` 區塊先按
   `檢查 BTC_trade` 看腳本是否齊全，再用 `一鍵啟動預測`：
   這會先判定資料是否過期、模型是否晚於資料，必要時補做資料更新與重訓，
   最後在背景執行預測並等待新的 report；訓練久時會顯示執行中，不會直接因 timeout 報錯

#### 媒體與 AI 組

- videos 依賴 Cloud Drive
- 註冊 CAPTCHA 的 `Turnstile site key` 只在 `turnstile` 模式會出現；切回
  `none / math / image` 時會自動隱藏，避免誤把不相關 token 當成必填
- ComfyUI 與 Civitai 僅在對應模式下顯示完整工具
- ComfyUI 遠端模式是生圖用；模型下載工具只對本地模式有意義
- ComfyUI 設成遠端模式時，設定頁會直接隱藏 `Civitai API Key`，因為遠端
  API 無法把模型下載回本站本地磁碟
- ComfyUI 目前這套介面支援 checkpoint / LoRA / embedding / VAE，也支援 `img2img / inpaint / outpaint / upscale / ControlNet`；Hypernetwork 仍不在目前 UI 內
- root 的模型匯入折疊面板現在有兩種來源：
  - `Civitai 網址`
  - `本地檔案上傳`
  兩者都只在本地模式出現，remote mode 不會再顯示可操作入口
- `Civitai 網址` 模式現在可先做關鍵字搜尋，支援 `base model / 類型 / Safe/NSFW`
  篩選；搜尋結果會先顯示版本、檔案大小、hash 與相容模型摘要，再帶入下方
  版本/檔案下拉。真正下載前仍會再跳一次確認。
- Embedding 快速插入與 VAE 選擇屬於生圖表單；Civitai trigger words 會先在 root 的本地模式下載折疊區顯示，之後同一顆 LoRA 被使用者加入時會自動補進正向提示詞
- ComfyUI 進行長工作時，前端會暫停閒置登出倒數；目前包含本地啟動、生圖、root 模型下載

#### 站點外觀組

- root 仍是唯一可改「全站預設外觀」的人
- `允許使用者覆寫個人外觀` 開啟後，所有已登入用戶都能在 `修改資料 -> 個人外觀` 只改自己的畫面
- 個人外觀目前除了顏色外，還可調字體風格、背景風格、面板風格、側邊欄寬度、版面密度、圓角、字級、內容寬度
- 若你暫時不想讓使用者存自己的主題，可以關掉個人外觀覆寫，但全站預設外觀設定仍照常可用

### root / admin 分工建議

- `root`：server mode、snapshot restore、system reset、integrity、PointsChain root 操作、部署設定、ComfyUI 設定
- `admin/manager`：使用者審核、檢舉 / 申訴 / 治理通知、社群管理、日常審核

## 原理

- 本專案把高風險操作放在 root 專屬控制面，是為了把「可日常委派」與
  「會改變站點安全或資料邊界」的能力分開。
- 許多 optional feature 共用底層服務，例如 Video 依賴 Cloud Drive，
  Trading 依賴 PointsChain，Snapshot/Restore 與 Server Mode / Audit /
  Integrity 又彼此關聯，因此只開單一頁面入口常會得到不完整服務。
- 功能開關上方的套餐現在分成兩種：`全開 / 最低維運` 會直接改整組勾選狀態；
  其他像 `帳號治理整套`、`社群互動整套` 則屬於加開型快捷鍵，只會補勾相關模組。

## 失敗情境與提示

- 使用者明明看到入口，點進去卻收到「此功能目前已由 root 關閉」：
  代表相關 feature flag、底層依賴或最低角色未完整開啟。先對照
  [05_FEATURES_OVERVIEW.md](05_FEATURES_OVERVIEW.md) 的模組依賴矩陣。新版訊息會盡量直接指出是哪個父功能被關閉，以及哪些已開模組會一起受影響。
- root 按了 `最低維運`，結果某些頁面整批消失：
  這是預期行為；這個套餐不是「少開一點」，而是直接把站點切回最小可維運骨架。
  若只是想補齊單一服務，改用下方的整套快捷鍵。
- root 想開 ComfyUI 模型下載，但設定成 remote API：
  這是預期限制；遠端 API 模式不負責把模型下載到遠端主機。
- root 想找 `Turnstile site key`：
  先確認 `註冊 CAPTCHA 模式` 是否切到 `turnstile`；其他模式會刻意隱藏。
- root 想知道交易價格怎麼融合，或找不到交易相關設定：
  先切到設定頁的 `交易所` 分頁，不要再去 `計費` 找。
  預設是 `融合價格（多交易所加權平均）`，會依各交易所掛單簿深度自動分配權重；
  若改成 `root 手動權重`，0 代表該交易所不參與，API 失效時系統會自動用剩餘健康來源重新分配。
  若要看目前實際占比，不用自己手算，直接看 `交易所參數` 裡的
  `融合價格即時比例` dashboard；若所有手動權重都設成 0，畫面會明講已退回
  `auto_depth`，不是靜默照 0 權重硬算。
  另外 `borrow_interest_pool_pressure_multiplier` 現在可真的設成 `0`，不會再被系統默默退回預設倍率；
  借貸 APR、每小時計息規則與 Grid 折扣也都在同一頁
- root 想知道交易量有沒有被累積，準備日後做 VIP：
  後端現在會把每位使用者的現貨 / 借貸成交名目、總 fee 與成交次數累積到
  `trading_user_volume_stats`。目前主要供 root report / 後續 VIP 規則使用，
  不是只算單次頁面暫時計算值
- root 想知道某個 bot 為什麼沒有燈號：
  先看 `交易機器人定期稽核` dashboard。若顯示 `未稽核`，代表它還沒成交、
  也尚未啟用滿 24 小時；若已黃燈 / 紅燈，畫面會直接列出最近錯誤與 bot 類型，
  下方也會同步列出 trading bug reports 供 root 追查。
- root 按了 BTC_trade `一鍵啟動預測` 但一直在跑：
  先看狀態列是不是停在 `重訓 BTC_trade 模型`。新版會改成背景工作並持續輪詢，
  長時間訓練屬預期，不會再把 timeout 直接顯示成失敗；只有腳本真的退出非 0
  或等不到新的 report，才會轉成失敗訊息。
- root 想找 ControlNet / Hypernetwork 下載：
  這版介面故意不提供，避免下載了但主畫面沒有對應控制。
- 使用者加入 LoRA 時沒有自動補 trigger words：
  先確認那顆 LoRA 是不是透過 root 的 Civitai 下載面板下載，且該版本真的有官方 `trainedWords`；手動放進資料夾的 LoRA 不會自動補。
- 使用者說找不到個人外觀，或看得到但不能存：
  先檢查 `允許使用者覆寫個人外觀` 是否開啟；若已關閉，頁面現在會明確提示是 root 關閉，不會靜默失敗。
- admin 想做 snapshot restore / integrity approve / PointsChain rescue：
  這些是 root-only。
- root 忘記密碼時想走登入頁 `忘記密碼`：
  不行。root 已被排除在一般 web reset / email token / admin review 之外；請改用
  `scripts/root_recovery.py` 離線補救。
- 上線前只開了交易 UI，沒有先做 PointsChain、恢復、壓力測試：
  這不算完整啟用。
- root 說「我明明剛剛存過，為什麼 `設定已儲存` 一直掛著」：
  新版成功訊息會自動消失；若還留在畫面上，通常代表那不是成功訊息，而是尚未處理的依賴警告。

## 測試方式

- 以 root 檢查各模組頁面是否能看到完整設定與狀態
- 以 admin/manager 驗證被允許與被禁止的管理操作
- 跑 [11_QA_TESTING.md](11_QA_TESTING.md) 中的權限、snapshot、PointsChain、交易回歸
- 對照 [05_FEATURES_OVERVIEW.md](05_FEATURES_OVERVIEW.md) 檢查各功能組是否成套
- 驗證 `交易所參數` 裡的價格來源切換、融合權重模式與手動權重，並在關掉單一交易所來源時確認其餘來源仍能補位
- 驗證現貨 fee、Grid 折扣、BTC/ETH 與 USDT/POINTS APR、每小時計息與最小計息小時都可由 root 調整，且前台會正確顯示 `累積利息` 與 `下一次計息`
- 驗證成交後 `trading_user_volume_stats` / root report 內的累積交易量有同步增加，供後續 VIP 規則使用
- 驗證 root-only `融合價格即時比例` dashboard 會列出實際占比、排除來源與
  `價格來源降級` / 保守模式提示，而不是把 fallback 當成正常 fused price
- 驗證 root-only `交易機器人定期稽核` dashboard：
  - 新 bot 在「未成交且未滿 24h」時維持 `未稽核`
  - 至少一筆成交後轉成綠 / 黃 / 紅燈
  - 黃燈 / 紅燈時可同頁看到 recent findings 與 trading bug reports

## 相關文件連結

- [05_FEATURES_OVERVIEW.md](05_FEATURES_OVERVIEW.md)
- [06_SECURITY_MODEL.md](06_SECURITY_MODEL.md)
- [07_POINTSCHAIN.md](07_POINTSCHAIN.md)
- [08_TRADING_ENGINE.md](08_TRADING_ENGINE.md)
- [09_SNAPSHOT_RESET_RESTORE.md](09_SNAPSHOT_RESET_RESTORE.md)
- [WEB.md](WEB.md)
- [For_developer.md](For_developer.md)


---

## PointsChain v2 區塊鏈化規劃 (2026-05-04 拍板, 尚未實作)

本模組未來將與全站 PointsChain v2 區塊鏈化整合：

- 工程設計：[`docs/BLOCKCHAIN/POINTSCHAIN_ENGINEERING.md`](BLOCKCHAIN/POINTSCHAIN_ENGINEERING.md)
- 用戶白皮書：[`docs/BLOCKCHAIN/POINTSCHAIN_WHITEPAPER.md`](BLOCKCHAIN/POINTSCHAIN_WHITEPAPER.md)
- 地址規格：[`docs/BLOCKCHAIN/POINTS_WALLET_ADDRESSING.md`](BLOCKCHAIN/POINTS_WALLET_ADDRESSING.md)
- 轉帳 API：[`docs/BLOCKCHAIN/POINTS_TRANSFER_API.md`](BLOCKCHAIN/POINTS_TRANSFER_API.md)
- 多簽錢包：[`docs/BLOCKCHAIN/MULTISIG_WALLETS.md`](BLOCKCHAIN/MULTISIG_WALLETS.md)
- QA Mining / 貢獻獎勵 (Phase 7)：[`docs/BLOCKCHAIN/POINTS_MINING_REWARDS.md`](BLOCKCHAIN/POINTS_MINING_REWARDS.md)
- QA / Release Gate：[`docs/BLOCKCHAIN/POINTSCHAIN_QA.md`](BLOCKCHAIN/POINTSCHAIN_QA.md)

**狀態：設計已拍板（root, 2026-05-04），尚未實作完成。**
