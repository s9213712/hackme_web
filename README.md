# hackme_web

[繁體中文入口](docs/README.zh-TW.md)

![status](https://img.shields.io/badge/status-active-2ea043)
![backend](https://img.shields.io/badge/backend-Flask-000000)
![database](https://img.shields.io/badge/database-SQLite-0f6ab4)
![security](https://img.shields.io/badge/focus-auth%20%2B%20RBAC%20%2B%20audit-b31d28)

**Current Release ID: `2026.05.05-116`**

`hackme_web` is a security-focused Flask web application that combines
authentication, RBAC, moderation, per-user appearance overrides, Cloud Drive,
ComfyUI integration, PointsChain, multi-exchange fused-price trading
experiments with richer chart indicators, expanded points-quoted markets, and
server-mode controls with auditable recovery tools in a single-node deployment.

Recent AI image workflow additions now include `img2img`, `inpaint`,
`outpaint`, ControlNet-assisted generation, upscale-model selection, and
history replay for saved prompts/assets. Root can now import local ComfyUI
model files directly from the web UI in addition to pasting a Civitai URL, and
there is a dedicated probe script for smoke-testing every supported generation
mode against a live ComfyUI backend.

This README keeps only the shortest entry route. Detailed deployment,
operations, feature, security, and QA references live under `docs/`.

## Fast Route

### First-time deployer

1. [docs/00_START_HERE.md](docs/00_START_HERE.md)
2. [docs/01_DEPLOY_QUICKSTART.md](docs/01_DEPLOY_QUICKSTART.md)
3. [docs/02_DEPLOY_PRODUCTION.md](docs/02_DEPLOY_PRODUCTION.md)

### Root / admin operator

1. [docs/03_ADMIN_GUIDE.md](docs/03_ADMIN_GUIDE.md)
2. [docs/05_FEATURES_OVERVIEW.md](docs/05_FEATURES_OVERVIEW.md)
3. [docs/11_QA_TESTING.md](docs/11_QA_TESTING.md)
4. [docs/12_TROUBLESHOOTING.md](docs/12_TROUBLESHOOTING.md)

### End user / product walkthrough

1. [docs/04_USER_GUIDE.md](docs/04_USER_GUIDE.md)
2. [docs/05_FEATURES_OVERVIEW.md](docs/05_FEATURES_OVERVIEW.md)

## Quick Start

Recommended first deployment:

```bash
./deploy.sh
```

Manual development start:

```bash
python3 -m venv .venv
. .venv/bin/activate
python3 -m pip install -r requirements.txt
python3 server.py
```

`python3 server.py` 會在本機自動準備開發用 `runtime/cert.pem` /
`runtime/key.pem`，而且資料庫、log、storage、runtime secrets 也預設都收在
`runtime/` 目錄下，因此預設通常是 `https://127.0.0.1:5000/`，不是純 HTTP。
若直接用 `curl` 檢查版本，請加 `-k`：

```bash
curl -k -sS https://127.0.0.1:5000/api/version
```

交易回測現在會在後端自動分段執行長區間資料；單次總上限為 `20,000` 根 K 線，
單批內部分段上限為 `10,000` 根。回測面板的開始 / 結束日期也會依目前週期直接提示
另一側最遠可選到哪裡，避免使用者自己換算資料根數。超過總量時，前後端都會明確要求
你縮小區間或改大時間週期。
root 另外可在交易所參數裡看到「融合價格即時比例」dashboard，直接檢查目前各 API 的真實占比、
被排除來源、以及是否已降級成保守模式。新版也多了 root-only 的「交易機器人定期稽核」
dashboard：新 bot 會先顯示 `未稽核`，等首筆成交或啟用滿 24 小時後，才會進入綠 / 黃 / 紅燈。
若你有接 BTC_trade，root 設定頁現在還有 `一鍵啟動預測`；它會先檢查資料與模型是否過期，
必要時補資料更新與重訓，再在背景執行預測並等待新的 report，不會因長時間訓練直接用 timeout 當失敗。
交易頁的 `目前價格` 現在每 `2` 秒用輕量 `live-price` API 更新一次，漲綠跌紅；買入/賣出預估也會跟著同一節奏重算；積分錢包裡的現貨/進階交易浮盈虧、root 虛擬總額也會一起跟著最新價格刷新。現貨明細現在也會直接顯示「持有成本（含單顆成本）」與「損益平均價格（含預估賣出手續費）」；若 live fused price
已降級到 fallback / cached source，前端會直接亮黃燈，而不是假裝仍是正常來源。
新版也把價格語義正式拆成兩層：`reference price` 用於展示、一般估值與 K 線參考；`risk-grade price` 用於融資、強平、保證金、未實現盈虧、bot 風控與交易限制。`live-price`、`reference-prices` 與 dashboard 會明確回 `price_type / source / confidence / stale / degraded / provider_count`，前端也會直接標出這些重要數字的用途；若價格已降級、stale、fallback 或只剩參考級模式，頁面會說人話提示，不會再靜默沿用模糊價格。
交易所即時行情也開始使用 WebSocket 當 provider input：Binance、OKX、Coinbase、Kraken 會優先吃 ticker / depth websocket，斷線時自動退回 HTTP polling，但 WebSocket 只是 provider input，不會取代 `reference price / risk-grade price` 的語義。後端現在會對外明確回 `connected / fallback / stale / degraded / confidence / provider_count / last_update_at / exclusion_reason / transport_state`，讓 UI、bot、融資與風控都能審計目前價格是否處在可接受狀態。
網格機器人建立頁也會先做 fee-aware preview：同時顯示每格毛利、手續費、扣費後淨利、損益兩平間距與紅/黃/綠燈，不再只給毛利價差。
另外，交易相關 root 設定已從 `計費` 分頁拆成獨立 `交易所` 分頁，不再和一般扣點 catalog 混在一起。
同一頁現在也集中管理現貨手續費、Grid 折扣、BTC/ETH 與 USDT/POINTS 的年利率 APR、
每小時計息規則，以及累積交易量統計；其中交易量會持續按使用者累加，供後續 VIP 系統使用。
交易市場 catalog 也已擴充到 `XRP/USDT`、`BNB/USDT`、`PAXG/USDT` 顯示對，
並維持內部 `*/POINTS` canonical symbols，讓新資產可共用相同的 live-price、
reference-price、bot 與回測路徑。
Cloud Drive 檔案瀏覽器現在也支援直接雙擊資料夾列進入，不再只能靠右側 `開啟` 按鈕。
交易市場與多交易所 provider 對應現在也集中在 `services/trading_markets.py`；未來若要新增
`SOL`、`GOLD` 之類的新積分交易標的，主線只需要先補這份 market catalog，再讓 UI / 行情 /
回測共用同一份定義。
影音平台的大檔串流也已進入 Phase C：影片頁現在有 `playback` 決策 API、HLS
prepare/status 路由，以及 plain / `server_encrypted` 媒體的背景 HLS derivative
基礎；公開/持連結可看影片與伺服器端加密影音會優先自動準備 HLS 衍生檔，影片詳情頁也可手動重建或重試；Safari 保留原生 HLS，桌機 Chrome / Firefox / Edge 會改用同源 `hls.js` 播放器，若 HLS 初始化失敗才退回既有直接串流。嚴格 `e2ee`
影音則維持瀏覽器端解密播放：擁有者在發布 `持連結可看` 的 E2EE 影音時，會在本地輸入一次原始 E2EE 密碼，把 file key 重新包成分享授權；分享控制面板現在也會顯示分享狀態、剩餘觀看次數、分享密碼狀態、到期日與最大觀看次數，並明確提醒 fragment 遺失不可復原，只能重新產生分享。觀看者只需要完整分享連結中的 fragment，
若有設定第二層分享密碼則再加上分享密碼即可播放，伺服器仍拿不到原始 E2EE 密碼或 raw file key。
功能開關頁也新增 `全開` 與 `最低維運` 套餐：前者一鍵打開所有模組，後者則保留帳號、
Audit、健康燈、Server Mode 與 Snapshot 等最小維運骨架，方便 root 快速切站點形態。

Fresh local databases create `root/root`, `admin/admin`, and `test/test`, then
force those accounts to change password on first login. Set
`HTML_LEARNING_ROOT_PASSWORD`, `HTML_LEARNING_MANAGER_PASSWORD`, and
`HTML_LEARNING_TEST_PASSWORD` before first boot if you want different bootstrap
passwords.

If you enable Cloudflare Turnstile, keep the two keys separate:

- `TURNSTILE_SITE_KEY`: public frontend key used to render the widget
- `TURNSTILE_SECRET_KEY`: backend-only secret used by the server to verify the
  Turnstile token with Cloudflare

Do not put `TURNSTILE_SECRET_KEY` in frontend code or commit it into Git. If
registration CAPTCHA mode is not `turnstile`, you can leave these values unset.

## Documentation Map

### Start Here

- [docs/00_START_HERE.md](docs/00_START_HERE.md)
- [docs/01_DEPLOY_QUICKSTART.md](docs/01_DEPLOY_QUICKSTART.md)
- [docs/02_DEPLOY_PRODUCTION.md](docs/02_DEPLOY_PRODUCTION.md)

### Role Guides

- [docs/03_ADMIN_GUIDE.md](docs/03_ADMIN_GUIDE.md)
- [docs/04_USER_GUIDE.md](docs/04_USER_GUIDE.md)
- [docs/05_FEATURES_OVERVIEW.md](docs/05_FEATURES_OVERVIEW.md)

### Core Systems

- [docs/06_SECURITY_MODEL.md](docs/06_SECURITY_MODEL.md)
- [docs/07_POINTSCHAIN.md](docs/07_POINTSCHAIN.md)
- [docs/08_TRADING_ENGINE.md](docs/08_TRADING_ENGINE.md)
- [docs/09_SNAPSHOT_RESET_RESTORE.md](docs/09_SNAPSHOT_RESET_RESTORE.md)
- [docs/10_WEB_TERMINAL.md](docs/10_WEB_TERMINAL.md)

### QA And Support

- [docs/11_QA_TESTING.md](docs/11_QA_TESTING.md)
- [docs/12_TROUBLESHOOTING.md](docs/12_TROUBLESHOOTING.md)
- [docs/AGENTS/README.md](docs/AGENTS/README.md)

### Deep Reference

- [docs/API_REFERENCE.md](docs/API_REFERENCE.md)
- [docs/CLI_ADMIN_PLAYBOOK.md](docs/CLI_ADMIN_PLAYBOOK.md)
- [docs/README.md](docs/README.md)
- [docs/For_developer.md](docs/For_developer.md)
- [docs/ENCRYPTION_RUNTIME_BOUNDARY.md](docs/ENCRYPTION_RUNTIME_BOUNDARY.md)
- [docs/EXTERNAL_API_COMMAND_MATRIX.md](docs/EXTERNAL_API_COMMAND_MATRIX.md)
- [docs/WEB.md](docs/WEB.md)
- [docs/TRADING.md](docs/TRADING.md)
- [docs/VIDEO_PLATFORM.md](docs/VIDEO_PLATFORM.md)
- [docs/VIDEO_STREAMING_ARCHITECTURE.md](docs/VIDEO_STREAMING_ARCHITECTURE.md)
- [docs/UPDATE_SUMMARY.md](docs/UPDATE_SUMMARY.md)

## Local Checks

```bash
python3 scripts/pre_push_checks.py
security/run_functional_smoke.sh --port 50741
security/run_pentest.sh --target https://127.0.0.1:5000
python3 scripts/comfyui_feature_probe.py --base-url https://127.0.0.1:5000 --username root --password RootSmoke123! --insecure
```

The installed `hooks/pre-push` now auto-runs the same gate in `--ci` mode, but
it first removes safe repo-local Python caches and a mistakenly generated
repo-root `runtime/` directory so transient artifacts do not keep leaking into
`git status`.

`tests/smoke_suite.py`, `security/run_functional_smoke.sh`, and
`security/run_pentest.sh --only functional-permissions` now share the same
default smoke credentials (`RootSmoke123! / ManagerSmoke123! / TestSmoke123!`).
The pentest wrapper also gives `whole-site-production-gate` a longer floor
timeout automatically, so the default `180s` wrapper no longer kills that gate
prematurely.


## PointsChain v2 區塊鏈化規劃 (2026-05-04 拍板, 尚未實作)

全站積分系統將升級為 permissioned chain，含地址化錢包、多簽治理、用戶互轉、self-custody opt-in、區塊瀏覽器。鏈化前的
Phase 0 cleanup / final review 已完成，本地 final review、isolated live API 驗證與 full pytest 皆通過；
目前狀態是 **ALLOW PHASE 1 CANDIDATE**，等待 root 最終批准是否正式動工。

- 用戶白皮書：[`docs/BLOCKCHAIN/POINTSCHAIN_WHITEPAPER.md`](docs/BLOCKCHAIN/POINTSCHAIN_WHITEPAPER.md)
- 工程設計：[`docs/BLOCKCHAIN/POINTSCHAIN_ENGINEERING.md`](docs/BLOCKCHAIN/POINTSCHAIN_ENGINEERING.md)
- 地址規格：[`docs/BLOCKCHAIN/POINTS_WALLET_ADDRESSING.md`](docs/BLOCKCHAIN/POINTS_WALLET_ADDRESSING.md)
- 轉帳 API：[`docs/BLOCKCHAIN/POINTS_TRANSFER_API.md`](docs/BLOCKCHAIN/POINTS_TRANSFER_API.md)
- 多簽錢包：[`docs/BLOCKCHAIN/MULTISIG_WALLETS.md`](docs/BLOCKCHAIN/MULTISIG_WALLETS.md)
- QA Mining / 貢獻獎勵 (Phase 7)：[`docs/BLOCKCHAIN/POINTS_MINING_REWARDS.md`](docs/BLOCKCHAIN/POINTS_MINING_REWARDS.md)
- QA / Release Gate：[`docs/BLOCKCHAIN/POINTSCHAIN_QA.md`](docs/BLOCKCHAIN/POINTSCHAIN_QA.md)

**狀態：設計已拍板（root, 2026-05-04），尚未實作完成。** 正式規格以 `docs/BLOCKCHAIN/` 為準；`docs/AGENTS/reports/`
下的 prechain / audit / final review 報告只作歷史 evidence，不再作為 current gate 的 canonical 規格來源。
