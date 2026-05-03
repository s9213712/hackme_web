# 05 Features Overview

一句話說明：這份文件用部署者與管理者能快速掃描的方式，整理目前所有主要功能、依賴、限制、測試與深層參考入口。

## 設計目的

過去相同主題散在 `WEB.md`、`VIDEO_PLATFORM.md`、`TRADING.md`、
`For_developer.md`、各種安全與 QA 文件裡。這份文件把「功能是什麼、要搭什麼才能完整用、失敗時看哪裡、怎麼驗」集中到同一份。

## 功能矩陣

| 功能 | 主要對象 | 依賴 / 一起開較完整 | 深層文件 |
|---|---|---|---|
| 帳號 / 認證 / Session | 全用戶 | CSRF、權限、通知 | [04_USER_GUIDE.md](04_USER_GUIDE.md), [06_SECURITY_MODEL.md](06_SECURITY_MODEL.md), [For_developer.md](For_developer.md) |
| 個人外觀 / 站點主題 | 全用戶 + root | root 全站預設、個人外觀覆寫開關 | [03_ADMIN_GUIDE.md](03_ADMIN_GUIDE.md), [04_USER_GUIDE.md](04_USER_GUIDE.md), [WEB.md](WEB.md) |
| 社群 / Chat / 論壇 / 公告 | 一般站點 | reports / notifications / moderation | [WEB.md](WEB.md) |
| Cloud Drive / 相簿 | 全用戶 | attachments、albums、upload security | [WEB.md](WEB.md) |
| Video Platform | 內容站點 | Cloud Drive、PointsChain | [VIDEO_PLATFORM.md](VIDEO_PLATFORM.md) |
| ComfyUI | AI 站點 | feature_comfyui、local/remote ComfyUI、Civitai 僅本地模式 | [WEB.md](WEB.md), [For_developer.md](For_developer.md) |
| Appeals / Notices / Governance | 有審核流程的站點 | reports、notifications、identity/member governance | [WEB.md](WEB.md) |
| Security Center / Server Mode | root | audit、integrity、snapshot/restore、health center | [06_SECURITY_MODEL.md](06_SECURITY_MODEL.md), [SERVER_MODE_V2_PROFILE_MATRIX.md](SERVER_MODE_V2_PROFILE_MATRIX.md) |
| PointsChain | 經濟功能 | wallet、ledger、video tips、trading | [07_POINTSCHAIN.md](07_POINTSCHAIN.md) |
| Trading / Bots / Backtest | 交易站點 | PointsChain、economy、price feeds、QA scripts | [08_TRADING_ENGINE.md](08_TRADING_ENGINE.md), [TRADING.md](TRADING.md) |
| Snapshot / Restore / Reset | root / 運維 | server mode、audit、integrity、PointsChain | [09_SNAPSHOT_RESET_RESTORE.md](09_SNAPSHOT_RESET_RESTORE.md) |
| WebTerminal | 已封存 | 不在 active main line | [10_WEB_TERMINAL.md](10_WEB_TERMINAL.md) |

## 模組詳解

### 帳號 / 認證 / Session

- 一句話說明：提供登入、註冊、CSRF、防暴力登入、密碼變更與角色/會員等級邊界。
- 設計目的：讓所有後續模組都站在同一套可審計的認證與權限模型上。
- 使用方法：先部署、登入、修改 bootstrap 密碼，再按角色使用功能頁；若要啟用 Cloudflare Turnstile，先把 `註冊 CAPTCHA 模式` 切到 `turnstile`，此時設定頁才會顯示 `Turnstile site key`。
- 原理：後端以 session + CSRF + RBAC + member level 重新驗證每個高風險請求。
- 失敗情境與提示：`csrf_invalid`、預設密碼強制變更、登入失敗但不暴露使用者是否存在、權限不足 `403`、找不到 `Turnstile site key` 時先確認目前 CAPTCHA 模式是不是 `turnstile`。
- 測試方式：帳號 happy path、錯誤密碼、越權 API、session 失效、idle logout。
- 相關文件連結：[04_USER_GUIDE.md](04_USER_GUIDE.md), [06_SECURITY_MODEL.md](06_SECURITY_MODEL.md), [For_developer.md](For_developer.md)

### 個人外觀 / 站點主題

- 一句話說明：root 控制全站預設外觀，而每位已登入用戶都可選擇是否覆寫成自己的字體、背景、面板、側邊欄與配色風格。
- 設計目的：讓部署者維持全站品牌與預設可讀性，同時不必把每位使用者都綁死在同一套視覺配置。
- 使用方法：root 到 `Security Center -> Settings -> Appearance` 設定全站預設，並決定是否開啟 `允許使用者覆寫個人外觀`；一般使用者到 `修改資料 -> 個人外觀` 儲存自己的主題。
- 原理：前端會先套 root 的全域 site config，再覆蓋登入使用者的個人 appearance settings；後端只接受白名單欄位與有限選項，不信任任意 CSS 或自由字串。
- 失敗情境與提示：root 關閉個人外觀覆寫時，使用者編輯器會顯示停用提示並阻止儲存；若沒按儲存，只是暫時預覽；全站預設永遠不會被一般使用者改到。
- 測試方式：驗證 root 可改全站預設、一般使用者只能改自己的畫面；驗證預覽、儲存、恢復預設、關閉個人覆寫後的停用提示；驗證字體/背景/面板/側邊欄寬度在重新登入後仍正確套用。
- 相關文件連結：[03_ADMIN_GUIDE.md](03_ADMIN_GUIDE.md), [04_USER_GUIDE.md](04_USER_GUIDE.md), [11_QA_TESTING.md](11_QA_TESTING.md), [WEB.md](WEB.md)

### 社群 / Chat / 論壇 / 公告

- 一句話說明：提供聊天室、站內信、討論區、公告與內容審核/檢舉流程。
- 設計目的：驗證權限、審核、通知與治理流程在同一站內的互動。
- 使用方法：使用者建房、發文、回覆、檢舉；管理者審核或處理異常內容。
- 原理：聊天、論壇、檢舉、通知彼此連動，並受角色與 member level 限制。
- 失敗情境與提示：無權發文、板權限不足、檢舉/公告功能未開啟時會顯示關閉或權限訊息。
- 測試方式：逐角色測發文/回覆/檢舉/公告/管理工具，並驗證 UI/API/DB 對帳。
- 相關文件連結：[04_USER_GUIDE.md](04_USER_GUIDE.md), [WEB.md](WEB.md), [11_QA_TESTING.md](11_QA_TESTING.md)

### Cloud Drive / 相簿

- 一句話說明：提供上傳、分享、預覽、隱私模式、資料夾、垃圾桶與相簿。
- 設計目的：集中處理檔案、權限、加密模式與媒體功能的共同基礎。
- 使用方法：上傳檔案、選擇隱私模式、必要時建立相簿與分享連結。
- 原理：不同隱私模式決定 server 能否掃描 / 預覽 / 解密，並影響影片等上層模組。
- 失敗情境與提示：配額不足、加密模式不支援某些預覽、權限不足、檔案被 quarantine。
- 測試方式：上傳、預覽、分享、刪除、恢復、相簿操作、E2EE / server_encrypted 邊界。
- 相關文件連結：[04_USER_GUIDE.md](04_USER_GUIDE.md), [WEB.md](WEB.md), [12_TROUBLESHOOTING.md](12_TROUBLESHOOTING.md)

### Video Platform

- 一句話說明：把 Cloud Drive 內的影片檔變成可觀看、評論、按讚、打賞的影音頁。
- 設計目的：重用既有 storage/permission/PointsChain，而不是再造第二套媒體系統。
- 使用方法：先上傳影片到 Cloud Drive，再從影音頁發布。
- 原理：影片 metadata 與互動是 presentation layer，實際檔案仍由 Cloud Drive 提供。
- 失敗情境與提示：E2EE 檔案不可發布；server_encrypted 若遇舊 key 不可解會回 `decrypt_unavailable`。
- 測試方式：發布、播放、private/unlisted、評論、打賞、權限與解密失敗情境。
- 相關文件連結：[VIDEO_PLATFORM.md](VIDEO_PLATFORM.md), [07_POINTSCHAIN.md](07_POINTSCHAIN.md), [11_QA_TESTING.md](11_QA_TESTING.md)

### ComfyUI

- 一句話說明：提供本地或遠端 ComfyUI 生圖、LoRA 權重與 trigger words、自動 Embedding 快速插入、VAE 選擇、預覽儲存與 root 專用 Civitai 下載工具。
- 設計目的：把 AI 圖像生成功能整合到既有帳號、Cloud Drive、論壇與權限模型中。
- 使用方法：選模型、VAE、提示詞與 LoRA；頁面標題會明確顯示目前是本地模式還是雲端 / 遠端模式；需要時直接點 Embedding 快捷按鈕把 token 插進正向提示詞；若該 LoRA 是經由 root 的 Civitai 面板下載且有官方 trigger words，加入 LoRA 時會自動把缺少的 trigger words 補進正向提示詞；root 在本地模式下可用底部折疊區讀取 Civitai 版本 / trigger words 並下載 checkpoint、LoRA、embedding、VAE；若切到遠端模式，設定頁與主畫面都不會再顯示本地模型下載 / Civitai API Key。
- 原理：生圖可走 async job；前端 Embedding 按鈕會插入 `<embeddings:名稱>`，送出前由後端轉成 ComfyUI 可用 syntax；LoRA 的 trigger words 會透過下載時保存的 sidecar metadata 回填；遠端模式只負責生圖，本地模式才有啟停與模型下載管理；ComfyUI 長工作進行中會暫停閒置登出倒數，避免本地啟動、生圖或模型下載做到一半被自動登出。
- 失敗情境與提示：後端 unreachable、job 中斷、模型不存在、remote 模式看不到 Civitai 下載工具、手動放進 `models/loras` 但沒有 metadata 的 LoRA 不會自動補 trigger words、ControlNet / Hypernetwork 不在此介面支援範圍內；若頁面回 `此功能目前已由 root 關閉`，新版錯誤會盡量直接指出被擋的是哪個父功能。
- 測試方式：status、model list、LoRA metadata / trigger words、Embedding/VAE 列表、generate、custom VAE workflow、async progress、save/share/discard、Civitai trigger words、權限與模式切換。
- 相關文件連結：[WEB.md](WEB.md), [For_developer.md](For_developer.md), [12_TROUBLESHOOTING.md](12_TROUBLESHOOTING.md)

### Appeals / Notices / Governance

- 一句話說明：提供違規通知、治理通知、申訴與審核流。
- 設計目的：讓權限、處分與可回溯治理流程可被記錄與追蹤。
- 使用方法：使用者查看通知、提申訴；管理者審核、批准、拒絕。
- 原理：通知、申訴、治理動作會連動權限與審計記錄。
- 失敗情境與提示：功能關閉、身分不足、通知不存在或已處理。
- 測試方式：多角色逐步測申訴、通知、審核、審計記錄。
- 相關文件連結：[WEB.md](WEB.md), [11_QA_TESTING.md](11_QA_TESTING.md)

### Security Center / Server Mode

- 一句話說明：提供 root 的站點安全儀表板、server mode、integrity、審計與高風險操作控制面。
- 設計目的：把營運級保護做成可驗證、可切換、可回滾的控制面。
- 使用方法：root 在 Security Center 看健康度、套 profile、切 mode、做 integrity / snapshot / restore。
- 原理：mode、checkpoint、audit chain、integrity findings、protected logs 各自維持邊界。
- 失敗情境與提示：缺 confirmation string、production gate 未滿足、incident lockdown、生效功能組未完整啟用。
- 測試方式：mode switch、superweak rollback、incident lockdown、log verify、permission pentest。
- 相關文件連結：[06_SECURITY_MODEL.md](06_SECURITY_MODEL.md), [09_SNAPSHOT_RESET_RESTORE.md](09_SNAPSHOT_RESET_RESTORE.md), [SERVER_MODE_V2_PROFILE_MATRIX.md](SERVER_MODE_V2_PROFILE_MATRIX.md)

### PointsChain

- 一句話說明：站內點數、經濟帳本、封塊與驗證系統，是交易與打賞的可信來源。
- 設計目的：讓所有重要金額變動都走同一條可驗證鏈，而不是直接改 wallet balance。
- 使用方法：一般使用者透過正常功能消費；root 可調整、封塊、驗證、備份、恢復。
- 原理：ledger 是 source of truth，wallet 由 ledger replay 重建。
- 失敗情境與提示：safe mode、chain verify fail、恢復需要人工確認、餘額顯示與鏈不一致。
- 測試方式：credit/debit、seal/verify、backup/recovery、影片打賞、交易資金流。
- 相關文件連結：[07_POINTSCHAIN.md](07_POINTSCHAIN.md), [08_TRADING_ENGINE.md](08_TRADING_ENGINE.md), [RUNTIME_RESET_AND_RECOVERY.md](RUNTIME_RESET_AND_RECOVERY.md)

### Trading / Bots / Backtest

- 一句話說明：提供現貨交易、借貸交易、DCA / 網格 / workflow bot 與回測。
- 設計目的：驗證金額、風控、撮合、PointsChain 結算與策略流程。
- 使用方法：root 先啟用 economy / trading，再讓使用者交易或由 root 做模擬與設定。
- 原理：前台顯示是輔助，實際撮合與結算由後端重新驗證；關鍵金額不信任前端。交易帳本仍以整數 POINT 為最小單位，但手續費改用 `Decimal` 後端計算並採四捨五入到最近整點，避免舊版小額單長期偏向 `ceil` 超收。
- 失敗情境與提示：餘額不足、價格來源失效、circuit breaker、借貸池不足、功能旗標未完整啟用；若你在手算小額單手續費時看到與舊版不同，先確認是否已升到 `2026.05.03-063` 之後的 rounding 規則。
- 測試方式：正常交易、邊界輸入、精度、回測、stress pentest、restore consistency。
- 相關文件連結：[08_TRADING_ENGINE.md](08_TRADING_ENGINE.md), [TRADING.md](TRADING.md), [11_QA_TESTING.md](11_QA_TESTING.md)

### Snapshot / Restore / Reset

- 一句話說明：提供整站 snapshot、portable restore、runtime reset 與 PointsChain 恢復邊界。
- 設計目的：把「還原整站」與「修復帳本」分開，避免災難恢復時互相覆蓋。
- 使用方法：root 先建 snapshot，再進行 restore / reset / ledger recovery。
- 原理：server snapshot、PointsChain backup、audit chain、runtime reset 各自有明確所有權邊界。
- 失敗情境與提示：restore 後 secrets 不會回來、reset 需要重啟、PointsChain recovery 不能拿來代替全站 restore。
- 測試方式：create/list/download/restore/upload-restore/reset、post-restore consistency、offline/reconnect reset smoke。
- 相關文件連結：[09_SNAPSHOT_RESET_RESTORE.md](09_SNAPSHOT_RESET_RESTORE.md), [RUNTIME_RESET_AND_RECOVERY.md](RUNTIME_RESET_AND_RECOVERY.md), [11_QA_TESTING.md](11_QA_TESTING.md)

### WebTerminal

- 一句話說明：WebTerminal 是歷史封存主題，不是 active main line 的現行功能。
- 設計目的：保留曾嘗試過的 Docker / QEMU 設計，供未來重新設計時參考。
- 使用方法：只讀 archive，不要把它當現行部署功能。
- 原理：封存保留歷史脈絡，但避免誤導部署者以為目前站點有 terminal 模組。
- 失敗情境與提示：找不到前端入口、找不到設定、找不到服務，都是正常狀態。
- 測試方式：確認 active main line 沒有 routes / UI / settings 對外暴露 WebTerminal。
- 相關文件連結：[10_WEB_TERMINAL.md](10_WEB_TERMINAL.md), [docs/archive/webterminal/README.md](archive/webterminal/README.md)

## 相關文件連結

- [03_ADMIN_GUIDE.md](03_ADMIN_GUIDE.md)
- [04_USER_GUIDE.md](04_USER_GUIDE.md)
- [06_SECURITY_MODEL.md](06_SECURITY_MODEL.md)
- [07_POINTSCHAIN.md](07_POINTSCHAIN.md)
- [08_TRADING_ENGINE.md](08_TRADING_ENGINE.md)
- [09_SNAPSHOT_RESET_RESTORE.md](09_SNAPSHOT_RESET_RESTORE.md)
- [11_QA_TESTING.md](11_QA_TESTING.md)
- [12_TROUBLESHOOTING.md](12_TROUBLESHOOTING.md)
