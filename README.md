# hackme_web

[繁體中文入口](docs/README.zh-TW.md)

![status](https://img.shields.io/badge/status-active-2ea043)
![backend](https://img.shields.io/badge/backend-Flask-000000)
![database](https://img.shields.io/badge/database-SQLite-0f6ab4)
![security](https://img.shields.io/badge/focus-auth%20%2B%20RBAC%20%2B%20audit-b31d28)

**Current Release ID: `2026.05.07-155`**

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

## Quick Start

推薦第一次部署直接從 repo 根目錄執行：

```bash
./one_click_setup.sh
```

若你一開始就知道要接本地 ComfyUI 與 root-only Civitai 搜尋/下載，可直接：

```bash
./one_click_setup.sh --with-comfyui http://127.0.0.1:8192 --with-civitai-key '<CIVITAI_API_KEY>'
```

手動開發啟動：

```bash
python3 -m venv .venv
. .venv/bin/activate
python3 -m pip install -r requirements.txt
python3 server.py
```

啟動後請以 server console 印出的實際 URL 為準。一般情況：

- `./one_click_setup.sh` / production wizard：依設定可能是 HTTP 或 HTTPS
- `python3 server.py`：本機開發模式通常會自動準備本地 TLS，因此多半是
  `https://127.0.0.1:5000/`

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

第一次登入後會被要求立即改密碼。若要自訂 bootstrap 密碼，請在第一次建 DB 前先設：

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
python3 scripts/pre_push_checks.py
PYTHONPATH=. python3 -m pytest -q tests
```
