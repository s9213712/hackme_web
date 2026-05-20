# hackme_web

[繁體中文入口](docs/README.zh-TW.md)

![status](https://img.shields.io/badge/status-active-2ea043)
![backend](https://img.shields.io/badge/backend-Flask-000000)
![database](https://img.shields.io/badge/database-SQLite-0f6ab4)
![security](https://img.shields.io/badge/focus-auth%20%2B%20RBAC%20%2B%20audit-b31d28)

**Current Release ID: `2026.05.20-165`**

`hackme_web` 是一個部署者優先的 Flask 單機站點，整合了帳號與權限、
Cloud Drive、ComfyUI、PointsChain、交易實驗、Snapshot/Restore 與
Server Mode 等能力。

這份 README 故意只保留最短入口。最近功能更新請看
[docs/UPDATE_SUMMARY.md](docs/UPDATE_SUMMARY.md)，完整文件地圖請看
[docs/README.md](docs/README.md)，系統依賴總表請看
[docs/SYSTEM_DEPENDENCIES.md](docs/SYSTEM_DEPENDENCIES.md)。

## First-Time Deployer Route

1. [docs/00_START_HERE.md](docs/00_START_HERE.md)
2. [docs/01_DEPLOY_QUICKSTART.md](docs/01_DEPLOY_QUICKSTART.md)
3. [docs/02_DEPLOY_PRODUCTION.md](docs/02_DEPLOY_PRODUCTION.md)
4. Production templates: [deploy/README.md](deploy/README.md)

## Quick Start

本 repo 的公開入口現在只保留三條：

- `python3 -m pip install -r requirements-minimal.txt`
  只安裝最小啟動伺服器所需套件。開發測試請再加
  `requirements-dev.txt`，特定功能後端請再加 `requirements-features.txt`。
  舊流程仍可用 `requirements.txt` 一次安裝全部相容依賴。

- `python3 server.py --doctor`
  檢查目前 runtime 環境是否已存在且可寫；缺目錄時會明確報錯，不會靜默補建。
- `python3 server.py`
  手動 / 本機檢查入口。只有 doctor 通過時才會繼續啟 server。正式對外服務請使用
  `deploy/nginx/` + `deploy/systemd/` 的 Nginx / Gunicorn 範本。
- `./test_for_develop.sh`
  開發專用入口。它會先把 repo 複製到 `/tmp/.../hackme_web`，把開發用 runtime、
  cache、venv 都留在 `/tmp`，再從 `/tmp` 內的 `server.py` 啟動。
  若你要驗 `server mode` / `production gate` 的 `target_commit` 規則，
  `HTML_LEARNING_GIT_REPO_DIR` 必須指向**真實 git repo**，不可指向沒有 `.git`
  的 `/tmp` copy；`test_for_develop.sh` 現在預設會保留 source repo 當 target
  commit 來源。

日常原則仍然不變：**不要直接在 repo 工作樹內啟 server 或 pytest**。
請優先使用 `/tmp` 複本，避免 `runtime/`、cache、pycache 汙染 repo。

## Local Workflow

```bash
python3 server.py --doctor
./test_for_develop.sh --port 50785
scripts/testing/pytest_in_tmp.sh -q tests
```

若你真的要在目前工作樹直接啟動，先自己準備好 runtime 目錄，再執行：

```bash
python3 server.py --doctor
python3 server.py
```

正式部署不要直接對外開 `python3 server.py`。請先看
[docs/02_DEPLOY_PRODUCTION.md](docs/02_DEPLOY_PRODUCTION.md)，再套用
[deploy/README.md](deploy/README.md) 的 Nginx/systemd 範本。

啟動後請以 server console 或腳本印出的實際 URL 為準。一般情況：

- `./test_for_develop.sh`：通常會是 `https://127.0.0.1:<port>/`
- `python3 server.py`：依 `server_ssl_enabled` 與 runtime cert 狀態決定 HTTP/HTTPS

若不確定，直接探測：

```bash
for scheme in https http; do
  curl -ksSf "${scheme}://127.0.0.1:5000/api/version" && echo "$scheme works"
done
```

Fresh local databases 會建立：

- `root/root`
- `admin/admin`
- `test/test`

`test_for_develop.sh` 會額外關掉強制改密碼、登入安全限制、Integrity Guard、
audit chain 等妨礙開發的保護，並保留預設帳密方便反覆 debug。同時它也會把
trading market registry 切成開發可測狀態（`allow_spot / allow_margin /
allow_bots / allow_risk_grade_usage = 1`），避免 `/tmp` 開發站一開機就把現貨、
Grid Bot 與借貸交易整體封死。若你要手動啟動，
仍可在第一次建 DB 前先設：

- `HTML_LEARNING_ROOT_PASSWORD`
- `HTML_LEARNING_MANAGER_PASSWORD`
- `HTML_LEARNING_TEST_PASSWORD`

## Documentation Map

- 文件總索引：[docs/README.md](docs/README.md)
- 系統依賴總表：[docs/SYSTEM_DEPENDENCIES.md](docs/SYSTEM_DEPENDENCIES.md)
- root/admin 管理入口：[docs/03_ADMIN_GUIDE.md](docs/03_ADMIN_GUIDE.md)
- 使用者教學：[docs/04_USER_GUIDE.md](docs/04_USER_GUIDE.md)
- 功能總覽：[docs/05_FEATURES_OVERVIEW.md](docs/05_FEATURES_OVERVIEW.md)
- QA 與驗證路線：[docs/11_QA_TESTING.md](docs/11_QA_TESTING.md)
- 故障排查：[docs/12_TROUBLESHOOTING.md](docs/12_TROUBLESHOOTING.md)
- 最近更新摘要：[docs/UPDATE_SUMMARY.md](docs/UPDATE_SUMMARY.md)

## Local Checks

```bash
python3 scripts/prepush/pre_push_checks.py
scripts/testing/pytest_in_tmp.sh -q tests
python3 scripts/testing/playwright_platform_health_check.py
```

`playwright_platform_health_check.py` 會啟動隔離 QA server 到 `/tmp`、使用隨機非
`5000` port，並以真實瀏覽器驗 Job Center、Notification Center、Share Link
Management、Trading Asset Overview 與 mobile viewport。它不是正式 runtime 測試，
報告會寫到該次 `/tmp/.../reports/qa/`。
