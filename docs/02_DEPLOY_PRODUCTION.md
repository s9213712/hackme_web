# 02 Deploy Production

一句話說明：這份文件給正式部署者，說明如何把 `hackme_web` 安全地放到可長期營運的環境，而不是只在本機跑起來。

## 設計目的

本專案的風險不在「能不能起來」，而在「起來後是否留下錯誤預設、沒有備份、沒有驗證、把 runtime 汙染進 repo、或讓未授權流量直接打進 root 控制面」。這份文件把正式部署必做項整理成可執行順序。

## 使用方法

### 推薦部署路線

1. 先用 [01_DEPLOY_QUICKSTART.md](01_DEPLOY_QUICKSTART.md) 完成本機或 staging 驗證。
2. 用 `./one_click_setup.sh` 或 `./one_click_setup.sh --wizard` 建立 `.env`。
3. 把 runtime 根目錄放在獨立資料區，不要放 repo 內。
4. 決定是否由反向代理處理 HTTPS。
5. 建立上線前 snapshot。
6. 跑功能 smoke、權限 pentest、壓力測試與必要的 production gate。

### 重要部署決策

#### 1. Runtime 路徑

建議把 runtime 放在部署地自己的資料目錄，例如：

```text
$HOME/.local/share/hackme_web
```

至少要與 repo 分離：

- database
- logs
- chats
- anchors
- storage
- reports
- secrets / key files / certs

#### 2. HTTPS 與 Cookie

若服務會透過 HTTPS 對外：

- `FORCE_HTTPS=true`
- `SESSION_COOKIE_SECURE=true`
- `SESSION_COOKIE_HTTPONLY=true`
- `SESSION_COOKIE_SAMESITE=Strict`

如果 TLS 終止在反向代理：

- 應由前端代理處理憑證
- app 仍需正確設定 HTTPS / secure cookie
- 若信任 `X-Forwarded-For`，只信任你自己的 proxy IP，並設定
  `USE_XFF=true` 與 `TRUSTED_PROXY_IPS=...`

#### 3. Bootstrap 帳號

- `root` 僅用於第一次進站與高風險操作
- 正式上線通常不建議建立 `test` 帳號
- `admin` / `manager` 是否建立，取決於是否有實際管理流程

#### 4. 備份與恢復

正式上線前至少要確認三件事：

1. 你知道如何建立 server snapshot
2. 你知道 PointsChain restore 與整站 snapshot restore 的界線
3. 你已在非 production 環境驗證過 restore / reset

補充：

- root 後台的 `上線前檢查` 是 preflight gate，不要求你先把站切成
  `production`。
- production profile 的 HTTPS / audit chain / Integrity Guard /
  browser-only 等安全設定會在 `GO_LIVE` 切換成功時自動套用，不應被理解成
  「必須先手動打開才能過檢查」。
- 被動健康檢查與審計頁現在只會回報 audit chain / integrity 異常，不會因 root 單純
  查看 `/api/admin/health` 或 `/api/admin/audit` 就自動把站切成 maintenance mode。
- Integrity Guard strict mode 在正常更新 / 重啟後若發現 high-risk findings，啟動會
  保持可用並留下警告，但 `GO_LIVE` / pre-production gate 仍會拒絕，直到 root review。

### 反向代理建議

本 repo 不綁定單一代理實作，但部署者至少要做到：

- 只公開代理層入口，不讓 app 直接裸露在公網
- 代理層正確傳遞 scheme / host
- 若使用 `X-Forwarded-For`，app 僅信任受控 proxy IP
- 保留 access log / error log 與應用 log 分層

### 上線前必跑

```bash
python3 scripts/prepush/pre_push_checks.py
PYTHONPATH=. python3 -m pytest -q tests
scripts/security/pentest/run_functional_smoke.sh --port 50741
scripts/security/pentest/run_pentest.sh --target https://<host>
python3 scripts/security/pentest/stress_test.py --target https://<host> --i-own-this-target
```

如果本次要評估整站 production readiness：

```bash
PYTHONPATH=. scripts/security/pentest/run_pentest.sh \
  --target https://<host> \
  --only whole-site-production-gate
```

如果你要一次產出 production gate 要求的 13 份報告，可直接用：

```bash
./on_live_reports_make.sh --base-url https://<host> --root-password '<ROOT_PASSWORD>'
```

這會把 raw outputs 放進 `runtime/reports/security/production_gate/runs/<RUN_ID>/`，
並把上傳用的穩定 payload 放在 `runtime/reports/security/production_gate/`。

13 份 production gate 報告的對照表、固定 pytest 測項數與預設報告落點，統一放在
[11_QA_TESTING.md](11_QA_TESTING.md) 的「Production Gate 13 份報告對照表」。
部署者上線前若要確認報告應該生成在哪裡、哪些是動態腳本、哪些是固定 pytest
回歸，請以那張表為準。

## 原理

- `./one_click_setup.sh` 會產生 `.env` 與本機 secret/key 類 runtime 檔案，這些不應從 Git 複製。
- HTTPS、secure cookies、proxy trust、runtime 路徑與備份策略，決定的是營運風險，不只是功能是否可用。
- `hackme_web` 把 snapshot、PointsChain、audit chain、integrity guard 分開，是為了避免一個恢復動作默默覆蓋另一個保護層。

## 失敗情境與提示

- 上線後仍使用預設密碼：
  這不是小問題；立即 rotate，並檢查是否已有可疑登入。
- 把 repo 內 `bootstrap.schema.sql`、`logs/`、`storage/` 當 production runtime：
  之後很容易把營運資料誤提交或被開發流程覆蓋，應立即搬出 repo。
- 開了 HTTPS 但 cookie 仍不安全：
  檢查 `FORCE_HTTPS`、`SESSION_COOKIE_SECURE`、proxy 設定與瀏覽器 response header。
- snapshot 能建立但 restore 沒演練過：
  視同沒有備份。
- root 認為「只開某個功能就夠」但使用者一直看到功能關閉警告：
  請看 [03_ADMIN_GUIDE.md](03_ADMIN_GUIDE.md) 與 [05_FEATURES_OVERVIEW.md](05_FEATURES_OVERVIEW.md)
  的功能組合說明。

## 測試方式

- [security/PRE_RELEASE_CHECKLIST.md](security/PRE_RELEASE_CHECKLIST.md)
- [security/PRODUCTION_SIGNOFF_CHECKLIST.md](security/PRODUCTION_SIGNOFF_CHECKLIST.md)
- [11_QA_TESTING.md](11_QA_TESTING.md)
- 實際做一次 snapshot / restore / reset 演練
- 實際跑一次對外入口的 smoke / pentest / stress

## 相關文件連結

- [01_DEPLOY_QUICKSTART.md](01_DEPLOY_QUICKSTART.md)
- [03_ADMIN_GUIDE.md](03_ADMIN_GUIDE.md)
- [06_SECURITY_MODEL.md](06_SECURITY_MODEL.md)
- [09_SNAPSHOT_RESET_RESTORE.md](09_SNAPSHOT_RESET_RESTORE.md)
- [11_QA_TESTING.md](11_QA_TESTING.md)
- [12_TROUBLESHOOTING.md](12_TROUBLESHOOTING.md)
- [DEPLOYMENT.md](DEPLOYMENT.md)
- [security/PRE_RELEASE_CHECKLIST.md](security/PRE_RELEASE_CHECKLIST.md)
- [security/PRODUCTION_SIGNOFF_CHECKLIST.md](security/PRODUCTION_SIGNOFF_CHECKLIST.md)
