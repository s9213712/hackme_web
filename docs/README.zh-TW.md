# hackme_web（繁體中文入口）

[English README](../README.md)

**目前 Release ID：`2026.05.05-129`**

這份文件是中文捷徑版入口，不再承擔全部教學。它只回答三件事：

1. 我現在應該先看哪份
2. 第一次部署最短路線是什麼
3. 完整文件地圖在哪裡

## 最短閱讀路線

### 第一次部署

1. [00_START_HERE.md](00_START_HERE.md)
2. [01_DEPLOY_QUICKSTART.md](01_DEPLOY_QUICKSTART.md)
3. [02_DEPLOY_PRODUCTION.md](02_DEPLOY_PRODUCTION.md)

### root / admin

1. [03_ADMIN_GUIDE.md](03_ADMIN_GUIDE.md)
2. [05_FEATURES_OVERVIEW.md](05_FEATURES_OVERVIEW.md)
3. [11_QA_TESTING.md](11_QA_TESTING.md)
4. [12_TROUBLESHOOTING.md](12_TROUBLESHOOTING.md)

### 一般使用者

1. [04_USER_GUIDE.md](04_USER_GUIDE.md)
2. [05_FEATURES_OVERVIEW.md](05_FEATURES_OVERVIEW.md)

## 最短啟動

推薦：

```bash
./deploy.sh
```

若已經知道本機會接 ComfyUI 與 Civitai，也可在第一次部署時直接帶入：

```bash
./deploy.sh --with-comfyui http://127.0.0.1:8192 --with-civitai-key '<CIVITAI_API_KEY>'
```

手動：

```bash
python3 -m venv .venv
. .venv/bin/activate
python3 -m pip install -r requirements.txt
python3 server.py
```

全新資料庫會建立 `root/root`、`admin/admin`、`test/test`，第一次登入後會要求改密碼。

影音串流目前採雙路徑：
- `standard_plain` / `server_encrypted`：Safari 保留原生 HLS，桌機 Chrome / Firefox / Edge 走同源 `hls.js`，失敗才退回直接串流
- strict `e2ee`：維持瀏覽器端解密播放，不做伺服器端 HLS；若已建立 `E2EE Streaming v2` manifest，會改走密文分段下載 + Web Worker 解密 + `MediaSource` 播放，否則明確退回舊版完整解密，速度會較慢但不降級 E2EE 承諾
- `持連結可看` 的 E2EE 影音現在也有分享管理面板，可看分享狀態、剩餘觀看次數、到期日、密碼狀態；若完整連結 fragment 遺失，只能重新產生分享
- Cloud Drive 預覽現在也更接近日常檔案管理器：壓縮檔會顯示結構化檔案清單，PDF 會優先走原生檢視器；若是 strict `e2ee` PDF，會先在瀏覽器端解密，再用 `object/embed` 預覽或新分頁備援
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

交易系統除了既有 `reference price / risk-grade price` 與 WebSocket provider input，
現在也把交易市場升級成 root 可管理的 registry：root 可在後台新增 / 停用市場、調整
precision / lot size / tick size、維護各交易所 provider mapping，並先做 probe 再決定
是否允許 `risk-grade` 用途。市場停用後只會阻擋新下單，不會破壞既有歷史與報表。

Server Mode v2 的教學腳本也已擴充成完整 bundle：`docs/examples/server_mode_v2/`
除了原本的 token 教學，另外補了 focused pentest、stress、full-feature、
privilege-escalation 四支腳本。若要在隔離 runtime 一次跑完整 6 支並確認
shadow-table activity 沒有污染 production wallet / ledger tables，可直接執行：

```bash
PYTHONPATH=. python3 security/server_mode_v2_full_smoke.py
```

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
- [10_WEB_TERMINAL.md](10_WEB_TERMINAL.md)

### 深層參考

- [API_REFERENCE.md](API_REFERENCE.md)
- [CLI_ADMIN_PLAYBOOK.md](CLI_ADMIN_PLAYBOOK.md)
- [For_developer.md](For_developer.md)
- [ENCRYPTION_RUNTIME_BOUNDARY.md](ENCRYPTION_RUNTIME_BOUNDARY.md)
- [EXTERNAL_API_COMMAND_MATRIX.md](EXTERNAL_API_COMMAND_MATRIX.md)
- [WEB.md](WEB.md)
- [TRADING.md](TRADING.md)
- [VIDEO_PLATFORM.md](VIDEO_PLATFORM.md)
- [VIDEO_STREAMING_ARCHITECTURE.md](VIDEO_STREAMING_ARCHITECTURE.md)
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
- [archive/research/README.md](archive/research/README.md)
- [archive/webterminal/README.md](archive/webterminal/README.md)
