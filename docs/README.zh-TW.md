# hackme_web（繁體中文入口）

[English README](../README.md)

**目前 Release ID：`2026.05.07-155`**

這份文件是中文捷徑版入口，不再承擔全部教學。它只回答三件事：

1. 我現在應該先看哪份
2. 第一次部署最短路線是什麼
3. 完整文件地圖在哪裡

## 最短閱讀路線

### 第一次部署

1. [00_START_HERE.md](00_START_HERE.md)
2. [01_DEPLOY_QUICKSTART.md](01_DEPLOY_QUICKSTART.md)
3. [02_DEPLOY_PRODUCTION.md](02_DEPLOY_PRODUCTION.md)

補充：
- `上線前檢查` 現在是純粹的 preflight gate，不再要求你先切成
  `production`，也不再把 production profile 會在 mode switch 時自動套用的
  HTTPS / audit chain / Integrity Guard / browser-only 設定當成手動前置條件。
- launch-check 內的 playbook / tests 捷徑現在會在站內直接開啟文件檢視，不再跳
  `NOT FOUND`；每張 production gate report 卡也都內建 `上傳報告` 入口，可
  直接貼上或上傳 JSON 後重整 B 區狀態。
- 安全中心的 root 測試面板現在分成四張獨立卡：滲透測試、越權 / 權限濫用測試、
  全功能測試、壓力測試；每張卡都有自己的進度條、最近任務狀態與詳細 log。
- 審計鏈與 Integrity Guard 對正常維運的敏感度也已收斂：被動查看健康度/審計狀態時，
  audit chain 斷裂只會顯示 `critical` 與 `需人工處理`，不會因單純查狀態就自動把站
  切進維護模式；Integrity Guard strict mode 在重啟 / 更新後若看到高風險 findings，
  會保留警告並阻擋 `GO_LIVE`，但不會直接拒絕啟動。
- 交易價格信任等級也已收斂：若只是部分 order-book coverage 不完整、或系統自動排除
  少數不合格來源，但剩餘來源仍足以形成健康的 risk-grade price，前台會維持綠燈並說明
  「已自動排除部分來源，但風控級價格仍可使用」。只有真的遇到 stale / fallback /
  provider 斷線 / conservative mode / 異常價格狀態時，才會顯示黃色警示並暫停高風險交易。

### root / admin

1. [03_ADMIN_GUIDE.md](03_ADMIN_GUIDE.md)
2. [05_FEATURES_OVERVIEW.md](05_FEATURES_OVERVIEW.md)
3. [11_QA_TESTING.md](11_QA_TESTING.md)
4. [12_TROUBLESHOOTING.md](12_TROUBLESHOOTING.md)

### 一般使用者

1. [04_USER_GUIDE.md](04_USER_GUIDE.md)
2. [05_FEATURES_OVERVIEW.md](05_FEATURES_OVERVIEW.md)

## 最短啟動

目前正式入口只保留三條：

```bash
python3 server.py --doctor
python3 server.py
./test_for_develop.sh --port 50785
```

建議這樣理解：

- `python3 server.py --doctor`
  - 只做環境檢查；若 runtime 目錄、權限或必要檔案條件不成立，會直接報錯
- `python3 server.py`
  - 正式 / 手動啟動入口；不會再幫你靜默補建環境
- `./test_for_develop.sh --port 50785`
  - 開發專用；先把 repo 複製到 `/tmp/.../hackme_web`，再從 `/tmp` 副本啟站，
    避免污染 repo 工作樹

全新資料庫仍會建立 `root/root`、`admin/admin`、`test/test`。正式資料庫預設仍要求第一次登入後改密碼；
`test_for_develop.sh` 則會額外放寬一批妨礙開發的保護設定，方便反覆 debug。

影音串流目前採雙路徑：
- `standard_plain` / `server_encrypted`：Safari 保留原生 HLS，桌機 Chrome / Firefox / Edge 走同源 `hls.js`，失敗才退回直接串流
- strict `e2ee`：維持瀏覽器端解密播放，不做伺服器端 HLS；若已建立 `E2EE Streaming v2` manifest，會改走密文分段下載 + Web Worker 解密 + `MediaSource` 播放，否則明確退回舊版完整解密，速度會較慢但不降級 E2EE 承諾
- `持連結可看` 的 E2EE 影音現在也有分享管理面板，可看分享狀態、剩餘觀看次數、到期日、密碼狀態；若完整連結 fragment 遺失，只能重新產生分享
- Cloud Drive 預覽現在也更接近日常檔案管理器：壓縮檔會顯示結構化檔案清單，PDF 會優先走原生檢視器；若是 strict `e2ee` PDF，會先在瀏覽器端解密，再用 iframe / 新分頁備援
- 同一次登入 session 內再開另一個 E2EE 檔案時，前端會先嘗試剛剛成功過的最近密碼；只有真的解不開才會再詢問
- 伺服器健康度現在是綠燈只顯示燈號，黃燈 / 紅燈才顯示文字訊息

ComfyUI 目前除了一般 txt2img，也支援：
- `img2img`
- `inpaint`
- `outpaint`
- ControlNet（Canny / Depth / OpenPose / Lineart / Scribble / SoftEdge / Tile）
- upscale model
- 歷史套回 / 重跑
- workflow JSON 匯入 / 匯出、個人 preset、root 官方 preset
- root 本地模式下可在同一個折疊面板選擇「Civitai 網址」或「本地檔案上傳」匯入模型
- 模型匯入區現在也支援 `放大模型 / Upscaler` 類型，並可選填 `ComfyUI/models/`
  底下的相對路徑；若留空則會依類型自動使用預設資料夾，例如 `upscale_models/`
  或 `loras/`

交易系統除了既有 `reference price / risk-grade price` 與 WebSocket provider input，
現在也把交易市場升級成 root 可管理的 registry：root 可在後台新增 / 停用市場、調整
precision / lot size / tick size、維護各交易所 provider mapping，並先做 probe 再決定
是否允許 `risk-grade` 用途。市場停用後只會阻擋新下單，不會破壞既有歷史與報表。
另外 registry 現在會明確標示 `catalog_seed` / `custom`、`seed_version` 與
`seed_sync_status`，讓 root 看得出某個市場是 bootstrap seed 還是 DB 自建市場，
以及目前 DB 定義是否已偏離 catalog；執行期仍以 DB registry 為 source of truth。
價格融合細節、reference / risk-grade 價格語義與 fallback / degraded 行為，現在另外整理在
[`TRADING_RISK_PRICE.md`](trading/TRADING_RISK_PRICE.md)。

平台中心現在包含三個日常監看區塊：Job Center 可看背景任務、進度、stage、錯誤並
取消 / 重試；Share Link Management 可集中查看 file / album / video 分享、到期、
次數、密碼狀態、撤銷與存取紀錄；Trading Asset Overview 會把可用點數、鎖定點數、
現貨市值、借貸 / 融資倉位權益與累積利息合併顯示，API 失敗時會在畫面上明確報錯。
通知面板也支援 `dismissed_at`，隱藏通知會同步寫回資料庫。

Server Mode v2 的教學腳本也已擴充成完整 bundle：`docs/server_mode_v2/`
除了原本的 token 教學，另外補了 focused pentest、stress、full-feature、
privilege-escalation 四支腳本。若要在隔離 runtime 一次跑完整 6 支並確認
shadow-table activity 沒有污染 production wallet / ledger tables，可直接執行：

```bash
PYTHONPATH=. python3 scripts/security/server_mode/server_mode_v2_full_smoke.py
```

若要驗平台中心前後端是否真的可用，不只跑 pytest，請跑：

```bash
python3 scripts/testing/playwright_platform_health_check.py
```

這支腳本會自建 `/tmp` 隔離 runtime、避開 port `5000`，用 Playwright 真實瀏覽器
操作 Job Center、通知、分享管理、交易資產總覽與手機 viewport，並輸出 JSON/Markdown
報告。

另外：
- `internal_test` login token 現在必須綁定單一帳號，不再允許多個帳號共用同一顆 shared login token。
- `production report` upload 現在必須帶 `raw_report`、`sha256` `report_hash`、`hmac_sha256` `signature` 與 `key_version`；伺服器會自行重算 hash 並驗簽，未通過者不會被 production gate 接受。

補充：Server Mode v2 的 trading Phase 5b 目前已完成 SQL routing、matching
orderbook namespace、liquidation source/sink mode-lock，以及 funding publish /
settlement world split。production liquidation 維持正常，但 `internal_test`
liquidation 目前會先明確拒絕，避免 shadow world 留下任何 production wallet /
ledger / chain 污染；funding 則已改為依 `funding_channel_key(market, ctx)` 分
channel，shadow funding settlement 也只會寫到 shadow wallet / ledger。

## 文件地圖

### 先看這些

- [README.md](README.md)
- [00_START_HERE.md](00_START_HERE.md)
- [01_DEPLOY_QUICKSTART.md](01_DEPLOY_QUICKSTART.md)
- [02_DEPLOY_PRODUCTION.md](02_DEPLOY_PRODUCTION.md)
- [03_ADMIN_GUIDE.md](03_ADMIN_GUIDE.md)
- [04_USER_GUIDE.md](04_USER_GUIDE.md)
- [05_FEATURES_OVERVIEW.md](05_FEATURES_OVERVIEW.md)
- [11_QA_TESTING.md](11_QA_TESTING.md)
- [12_TROUBLESHOOTING.md](12_TROUBLESHOOTING.md)

### 主題文件

- [06_SECURITY_MODEL.md](06_SECURITY_MODEL.md)
- [07_POINTSCHAIN.md](07_POINTSCHAIN.md)
- [08_TRADING_ENGINE.md](08_TRADING_ENGINE.md)
- [09_SNAPSHOT_RESET_RESTORE.md](09_SNAPSHOT_RESET_RESTORE.md)

### 深層參考

- [API_REFERENCE.md](API_REFERENCE.md)
- [CLI_ADMIN_PLAYBOOK.md](CLI_ADMIN_PLAYBOOK.md)
- [For_developer.md](For_developer.md)
- [ENCRYPTION_RUNTIME_BOUNDARY.md](ops_boundaries/ENCRYPTION_RUNTIME_BOUNDARY.md)
- [EXTERNAL_API_COMMAND_MATRIX.md](EXTERNAL_API_COMMAND_MATRIX.md)
- [WEB.md](WEB.md)
- [TRADING.md](trading/TRADING.md)
- [TRADING_RISK_PRICE.md](trading/TRADING_RISK_PRICE.md)
- [VIDEO_PLATFORM.md](video/VIDEO_PLATFORM.md)
- [VIDEO_STREAMING_ARCHITECTURE.md](video/VIDEO_STREAMING_ARCHITECTURE.md)
- [DEPLOYMENT.md](DEPLOYMENT.md)
- [AGENTS/README.md](AGENTS/README.md)
- [AGENTS/QA_MISSION_FOR_AGENTS.md](AGENTS/QA_MISSION_FOR_AGENTS.md)
- [AGENTS/RULES_FOR_AGENTS.md](AGENTS/RULES_FOR_AGENTS.md)

### 測試與上線

- [security/FUNCTIONAL_SMOKE.md](security/FUNCTIONAL_SMOKE.md)
- [security/FUNCTIONAL_PERMISSION_PENTEST.md](security/FUNCTIONAL_PERMISSION_PENTEST.md)
- [security/PENTEST.md](security/PENTEST.md)
- [security/PRE_RELEASE_CHECKLIST.md](security/PRE_RELEASE_CHECKLIST.md)
- [security/PRODUCTION_SIGNOFF_CHECKLIST.md](security/PRODUCTION_SIGNOFF_CHECKLIST.md)

### 變更與歷史

- [UPDATE_SUMMARY.md](UPDATE_SUMMARY.md)
- [VERSION_STORY.md](VERSION_STORY.md)
- [AGENTS/research/BLOCKCHAIN/README.md](AGENTS/research/BLOCKCHAIN/README.md)
