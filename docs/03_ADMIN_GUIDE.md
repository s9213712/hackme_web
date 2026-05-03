# 03 Admin Guide

一句話說明：這份文件給 `root` 與 `admin/manager`，聚焦在「站點啟用後怎麼管理、怎麼避免把功能開一半」。

## 設計目的

本專案很多功能不是單獨存在，而是要搭配 feature flags、權限、storage、
PointsChain、snapshot、server mode 一起看。這份文件把管理者最常做的事情整理成操作路徑與功能組合，降低誤開、誤關、只開半套的風險。

## 使用方法

### 第一次以 root 進站後先做

1. 修改 bootstrap 密碼
   改完後要重新登入，舊 session 會立即失效
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

#### 媒體與 AI 組

- videos 依賴 Cloud Drive
- 註冊 CAPTCHA 的 `Turnstile site key` 只在 `turnstile` 模式會出現；切回
  `none / math / image` 時會自動隱藏，避免誤把不相關 token 當成必填
- ComfyUI 與 Civitai 僅在對應模式下顯示完整工具
- ComfyUI 遠端模式是生圖用；模型下載工具只對本地模式有意義
- ComfyUI 設成遠端模式時，設定頁會直接隱藏 `Civitai API Key`，因為遠端
  API 無法把模型下載回本站本地磁碟
- ComfyUI 目前這套介面支援 checkpoint / LoRA / embedding / VAE；ControlNet / Hypernetwork 不在目前 UI 內
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

## 失敗情境與提示

- 使用者明明看到入口，點進去卻收到「此功能目前已由 root 關閉」：
  代表相關 feature flag、底層依賴或最低角色未完整開啟。先對照
  [05_FEATURES_OVERVIEW.md](05_FEATURES_OVERVIEW.md) 的模組依賴矩陣。新版訊息會盡量直接指出是哪個父功能被關閉，以及哪些已開模組會一起受影響。
- root 想開 ComfyUI 模型下載，但設定成 remote API：
  這是預期限制；遠端 API 模式不負責把模型下載到遠端主機。
- root 想找 `Turnstile site key`：
  先確認 `註冊 CAPTCHA 模式` 是否切到 `turnstile`；其他模式會刻意隱藏。
- root 想找 ControlNet / Hypernetwork 下載：
  這版介面故意不提供，避免下載了但主畫面沒有對應控制。
- 使用者加入 LoRA 時沒有自動補 trigger words：
  先確認那顆 LoRA 是不是透過 root 的 Civitai 下載面板下載，且該版本真的有官方 `trainedWords`；手動放進資料夾的 LoRA 不會自動補。
- 使用者說找不到個人外觀，或看得到但不能存：
  先檢查 `允許使用者覆寫個人外觀` 是否開啟；若已關閉，頁面現在會明確提示是 root 關閉，不會靜默失敗。
- admin 想做 snapshot restore / integrity approve / PointsChain rescue：
  這些是 root-only。
- 上線前只開了交易 UI，沒有先做 PointsChain、恢復、壓力測試：
  這不算完整啟用。
- root 說「我明明剛剛存過，為什麼 `設定已儲存` 一直掛著」：
  新版成功訊息會自動消失；若還留在畫面上，通常代表那不是成功訊息，而是尚未處理的依賴警告。

## 測試方式

- 以 root 檢查各模組頁面是否能看到完整設定與狀態
- 以 admin/manager 驗證被允許與被禁止的管理操作
- 跑 [11_QA_TESTING.md](11_QA_TESTING.md) 中的權限、snapshot、PointsChain、交易回歸
- 對照 [05_FEATURES_OVERVIEW.md](05_FEATURES_OVERVIEW.md) 檢查各功能組是否成套

## 相關文件連結

- [05_FEATURES_OVERVIEW.md](05_FEATURES_OVERVIEW.md)
- [06_SECURITY_MODEL.md](06_SECURITY_MODEL.md)
- [07_POINTSCHAIN.md](07_POINTSCHAIN.md)
- [08_TRADING_ENGINE.md](08_TRADING_ENGINE.md)
- [09_SNAPSHOT_RESET_RESTORE.md](09_SNAPSHOT_RESET_RESTORE.md)
- [WEB.md](WEB.md)
- [For_developer.md](For_developer.md)
