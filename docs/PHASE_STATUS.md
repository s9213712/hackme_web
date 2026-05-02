# Phase 狀態

最後更新：2026-05-02

## Phase 12 前完成狀態

- Phase 1-5 核心安全、治理、伺服器模式、snapshot、restore、reset 已完成，並有針對性測試覆蓋。
- Phase 6 帳號復原缺口已補齊：註冊可填 Email、忘記密碼與 Email 驗證 token 流程已實作、啟動與 bootstrap schema 會建立所需資料表、token 具備一次性與過期限制、密碼重設會撤銷既有 session，登入頁也提供最小可操作的復原面板。
- Phase 7-11 論壇、檢舉/申訴/通知基礎、多人聊天室、上傳安全、頭像、Markdown、CAPTCHA、雲端硬碟與 storage 基礎已完成，並有針對性測試覆蓋。舊站內信入口已停用，私訊改由聊天室處理。

## Phase 12 後待處理

- Server Mode v2 企業級防禦基線已完成並標記為 completed。驗收證據：
  clean smoke 13/13 PASS、adversarial 8/8 PASS、Red Team L2
  `breaches_total=0`、live HTTP smoke 6/6 PASS、critical/high findings 皆為
  0。此處的 `production_readiness=YES` 僅代表 Server Mode v2 控制面完成，
  不等於整站已可正式上線。
- 下一階段重心改為整站 production gate 缺項補測：stress、permission、
  functional、pentest、snapshot_restore、points_chain_consistency、
  cloud_drive_quota_permission、off-host append-only audit backup /
  immutable log replication。
- Economy Phase 2 交易引擎基礎已完成第一版現貨 MVP：BTC/POINTS、ETH/POINTS 內部市場、BTC/USDT、ETH/USDT 前台顯示、市價/限價、取消訂單、限價單掃描撮合、Binance/OKX/Coinbase/Kraken/Gemini/Bitstamp/CoinGecko 公開行情 fallback、last-good-price fallback、保守資金池、PointsChain 結算、交易審計、現貨成本/已實現/未實現損益報表、snapshot/restore 一致性檢查與 `security/trading_stress_pentest.py`。交易 UI 以 `1 POINT = 1 USDT` 顯示，參考圖預設 15 分線，可切換其他週期。交易機器人已分為 DCA、節點式 Workflow 策略與回測，Workflow Editor 輸出 `nodes`/`edges` graph 並支援 TRUE/FALSE、nested AND/OR/NOT、cooldown 與 step 控制。BTC_trade 屬預設關閉的軟性整合，root 啟用後可自動 clone/update V15b+ 分支、下載資料、訓練與產生預測；建置失敗只隱藏 BTC-only 信號，不影響交易所；橋接交易事件的腳本已移入本專案。期貨與 PVP 撮合仍屬高風險功能，除 root 模擬與實驗性借貸測試外，不對一般用戶開放。
- 完整 `AuthLayout` 重構待後續處理；目前登入頁先保留可操作的最小復原 UI。
- 真實 SMTP 或外部寄信服務待後續部署整合；目前 mail adapter 會把 token 信件寫入資料庫 `mail_outbox`，足以支援本機測試與部署端接線。
- WebSocket 即時通知與 Email 通知摘要待後續處理。
- 完整 app layout/component 重構、前端 service layer 拆分、手機版細修、使用者可切換的深色模式持久化待後續處理。
- 個人主頁、個人簽名檔、自訂稱號、成就徽章、在線名單、通知偏好、reactions、引用回覆、mentions、編輯歷史、polls、wiki/bounty/accepted answer、訂閱/收藏/未讀狀態、FTS 搜尋、tags、hot score、草稿自動儲存待後續處理。
- 進階可選安全功能待後續處理：spam detection、multi-account detection、GDPR export/delete grace period、WebAuthn、live chat、browse history。
