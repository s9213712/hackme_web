# 00 Start Here

一句話說明：這是 `hackme_web` 的總入口，先幫你判斷「你是誰、現在要做什麼、應該先讀哪一份」。

## 設計目的

本專案功能很多，若直接打開 `For_developer.md`、`WEB.md`、`TRADING.md`
或 QA runbook，部署者很容易先被進階細節淹沒。這份文件把閱讀順序改成
角色導向，先解決「如何跑起來、如何安全上線、如何驗證有沒有壞」。

## 使用方法

### 如果你是第一次部署的人

1. 先看 [01_DEPLOY_QUICKSTART.md](01_DEPLOY_QUICKSTART.md)。
2. 能在本機或測試機跑起來後，再看 [02_DEPLOY_PRODUCTION.md](02_DEPLOY_PRODUCTION.md)。
3. 上線前一定看 [11_QA_TESTING.md](11_QA_TESTING.md) 與
   [12_TROUBLESHOOTING.md](12_TROUBLESHOOTING.md)。

### 如果你是 root / admin

1. 先看 [03_ADMIN_GUIDE.md](03_ADMIN_GUIDE.md)。
2. 再看 [05_FEATURES_OVERVIEW.md](05_FEATURES_OVERVIEW.md) 了解各模組依賴。
3. 需要做風險操作時，再看 [09_SNAPSHOT_RESET_RESTORE.md](09_SNAPSHOT_RESET_RESTORE.md)、
   [06_SECURITY_MODEL.md](06_SECURITY_MODEL.md)、
   [11_QA_TESTING.md](11_QA_TESTING.md)。
4. 如果你要管 ComfyUI / Civitai，最後再看 [WEB.md](WEB.md) 的 ComfyUI 章節，
   裡面會說明 local/remote、Embedding、VAE 與 root-only 下載工具限制；
   `remote` 模式只負責生圖，不提供本地模型下載，所以 `Civitai API Key`
   也只會在 `local` 模式顯示。
5. 如果你要改註冊 CAPTCHA，`Turnstile site key` 只會在 `turnstile`
   模式顯示；`none / math / image` 模式下不會再看到這個 token 欄位。
6. 如果你要調整全站預設外觀或決定是否開放使用者個人外觀覆寫，先看
   [03_ADMIN_GUIDE.md](03_ADMIN_GUIDE.md) 再回 [05_FEATURES_OVERVIEW.md](05_FEATURES_OVERVIEW.md)。
7. 如果你要啟用交易，先看 [03_ADMIN_GUIDE.md](03_ADMIN_GUIDE.md) 和
   [08_TRADING_ENGINE.md](08_TRADING_ENGINE.md) 裡的融合價格設定；
   新版預設是多交易所加權平均，root 可切成手動權重，而定投機器人的
   `最多執行次數` 也支援 `-1` 代表不限制。若要跑大區間回測，`20,000`
   根以內會由後端自動分成 `10,000` 根批次續跑，不必再手動拆兩次。若
   你是 root，設定頁現在也能直接看到融合價格即時比例、排除來源與價格降級狀態。
   交易相關 root 設定也已從 `計費` 拆成獨立 `交易所` 分頁，比較不容易和
   一般服務扣點 catalog 混淆。
   交易圖表除了 MA / EMA / 布林線，現在也支援 `RSI14` 與 `KD(9,3,3)` 副圖，
   可以直接在站內看趨勢、均值與超買超賣，不必再切去外部圖表工具。
   同一區也有 `交易機器人定期稽核` dashboard，新 bot 會先標 `未稽核`，
   等首筆成交或啟用滿 24 小時後才會進入綠 / 黃 / 紅燈。
   若你有接外部 `BTC_trade` repo，現在同一區也能用 `一鍵啟動預測`，由後端先檢查
   資料與模型是否過期，再在背景更新 / 重訓 / 等待新預測，不需要自己盯 timeout。
   交易頁的 `目前價格` 現在也會每 `2` 秒刷新一次；漲綠跌紅，買入/賣出預估也會跟著同步重算；若來源已降級成
   fallback / cached source，前端會直接亮黃燈。
   網格機器人建立前也會先試算每格毛利、手續費、扣費後淨利與損益兩平間距；紅燈直接阻擋，黃燈需二次確認，
   不再只看「每格價差」就誤以為策略一定賺錢。
   交易所分頁同時也是 root 調整現貨 fee、Grid 折扣、BTC/ETH 與
   USDT/POINTS APR、每小時計息規則的地方；後端也會累積所有使用者交易量，
   供後續 VIP 系統使用。
   若你要快速切整站功能形態，設定頁的功能開關現在也有 `全開` 與 `最低維運`
   套餐；`最低維運` 會直接把站點收斂到帳號、Audit、健康燈、Server Mode、
   Snapshot 這組最小維運骨架。
   一般使用者在回測頁選開始或結束時間時，系統也會直接提示另一側最遠能選到哪裡，
   不必自己理解 `20,000` 根 K 線代表多久。

### 如果你是一般使用者或要寫教學給一般使用者

1. 先看 [04_USER_GUIDE.md](04_USER_GUIDE.md)。
2. 再看 [05_FEATURES_OVERVIEW.md](05_FEATURES_OVERVIEW.md)。
3. 若你想只改自己的畫面風格，不改全站預設，`04_USER_GUIDE.md` 內有個人外觀入口與限制。
4. 想放棄自己的外觀覆寫時，不必自己把每個欄位改回來；新版可直接用編輯視窗底部的
   `恢復全站預設`。
4. 某個模組需要更多細節時，再進深層參考文件。

### 如果你是開發者 / API 維護者 / QA

1. 先看 [05_FEATURES_OVERVIEW.md](05_FEATURES_OVERVIEW.md)。
2. 再看 [For_developer.md](For_developer.md) 了解 API、schema、runtime、
   feature flags。
3. 若你要規劃大檔影音串流、HLS、E2EE / `server_encrypted` 的媒體衍生策略，
   再看 [VIDEO_STREAMING_ARCHITECTURE.md](VIDEO_STREAMING_ARCHITECTURE.md)。
4. QA 與驗車流程看 [11_QA_TESTING.md](11_QA_TESTING.md)；
   agent 級深度 runbook 看 [QA_MISSION_FOR_AGENTS.md](QA_MISSION_FOR_AGENTS.md)。
5. 若你要直接接手 smoke / pentest，自 `2026.05.03-063` 起，
   `smoke_suite.py`、`run_functional_smoke.sh` 與
   `run_pentest.sh --only functional-permissions` 的預設 smoke 帳密已對齊，
   可先沿用 `RootSmoke123! / ManagerSmoke123! / TestSmoke123!` 這組隔離測試密碼。

## 原理

文件分成三層：

1. 第一層：`README.md` + 本文件 + `01/02/03/04/05/11/12`。
2. 第二層：主題導引，如 `06_SECURITY_MODEL.md`、`07_POINTSCHAIN.md`、
   `08_TRADING_ENGINE.md`、`09_SNAPSHOT_RESET_RESTORE.md`、`10_WEB_TERMINAL.md`。
3. 第三層：現有深層參考文件與 runbook，如 `WEB.md`、`TRADING.md`、
   `VIDEO_PLATFORM.md`、`VIDEO_STREAMING_ARCHITECTURE.md`、
   `For_developer.md`、`docs/security/*.md`、
   `QA_MISSION_FOR_AGENTS.md`。

原則是先讓部署者完成正確決策，再進細節，不反過來。

## 失敗情境與提示

- 不知道該看哪份：
  先選角色，再照上面的路線走。
- 本機可跑、但不知道可不可以上線：
  直接跳到 [02_DEPLOY_PRODUCTION.md](02_DEPLOY_PRODUCTION.md) 的上線前檢查。
- 功能頁面顯示「此功能目前已由 root 關閉」：
  新版訊息會盡量直接說出是哪個父功能沒開、哪些已開功能會一起受影響。先看
  [03_ADMIN_GUIDE.md](03_ADMIN_GUIDE.md) 的功能組合與開關建議，再回
  [05_FEATURES_OVERVIEW.md](05_FEATURES_OVERVIEW.md) 看該模組依賴。
- 文件很多、怕重複：
  先以本文件與 [docs/README.md](README.md) 為準；舊文件若保留，視為深層
  參考或歷史設計說明。

## 測試方式

- 檢查 [README.md](../README.md) 與 [docs/README.md](README.md) 是否都把本文件當成
  第一入口。
- 檢查新部署者只靠 `README.md -> 00 -> 01` 是否能找到完整部署路線。
- 檢查 root/admin 是否能只靠 `00 -> 03 -> 05 -> 11` 找到管理、依賴與驗證指引。
- 文件更新後，至少重跑文件連結檢查與 release/doc index 測試。

## 相關文件連結

- [README.md](../README.md)
- [01_DEPLOY_QUICKSTART.md](01_DEPLOY_QUICKSTART.md)
- [02_DEPLOY_PRODUCTION.md](02_DEPLOY_PRODUCTION.md)
- [03_ADMIN_GUIDE.md](03_ADMIN_GUIDE.md)
- [04_USER_GUIDE.md](04_USER_GUIDE.md)
- [05_FEATURES_OVERVIEW.md](05_FEATURES_OVERVIEW.md)
- [11_QA_TESTING.md](11_QA_TESTING.md)
- [12_TROUBLESHOOTING.md](12_TROUBLESHOOTING.md)
