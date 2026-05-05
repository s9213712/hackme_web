# 01 Deploy Quickstart

一句話說明：這份文件只做一件事，讓你用最短路線在 10 到 20 分鐘內把
`hackme_web` 跑起來並完成第一輪基本驗證。

## 設計目的

部署者第一次接手時，最需要的是「成功啟動、知道資料放哪裡、知道下一步驗什麼」。
因此這份文件只保留最短路徑，不先塞入完整 API、風險模型、歷史設計或全部模組細節。

## 使用方法

### 你需要準備

- Linux / WSL / 可跑 Python 3 的環境
- `git`
- `python3`
- `curl`

### 最短部署流程

從 repo 根目錄執行：

```bash
./deploy.sh
```

若你已經知道要接本地 ComfyUI 與 root-only Civitai 搜尋/下載，可直接：

```bash
./deploy.sh --with-comfyui http://127.0.0.1:8192 --with-civitai-key '<CIVITAI_API_KEY>'
```

如果你想手動方式：

```bash
python3 -m venv .venv
. .venv/bin/activate
python3 -m pip install -r requirements.txt
python3 server.py
```

### 第一次啟動後要確認

1. 能打開啟動訊息中的網址，預設通常是 `http://127.0.0.1:5000/`。
   如果你是直接執行 `python3 server.py`，本機預設通常會是
   `https://127.0.0.1:5000/`，因為開發模式會自動準備本地 TLS 憑證。
2. `GET /api/version` 有回應。
3. 你知道 bootstrap 帳號：
   - `root/root`
   - `admin/admin`
   - `test/test`
4. 第一次登入後，預設密碼會被要求立刻修改。
5. 改完 bootstrap 密碼後，請重新登入；高權限 session 會被立即撤銷，這是預期安全行為。

### 若要改第一次密碼

在第一次建 DB 前先設定：

- `HTML_LEARNING_ROOT_PASSWORD`
- `HTML_LEARNING_MANAGER_PASSWORD`
- `HTML_LEARNING_TEST_PASSWORD`

### 最短驗證

```bash
python3 scripts/pre_push_checks.py
security/run_functional_smoke.sh --port 50741
```

如果你只想看版本與頁面是否起來：

```bash
curl -k -sS https://127.0.0.1:5000/api/version
```

## 原理

- `./deploy.sh` 是推薦入口，會幫你建立 `.venv`、安裝 requirements、委派
  `scripts/run_prod.sh` 的部署精靈，並初始化 DB / 啟動服務。
- 若 `.venv` 已備妥、你只想在隔離環境做快速檢查，可用：
  `./deploy.sh --check-only --skip-install`
- `scripts/run_prod.sh --check` 現在除了基本 env/路徑檢查，還會提醒你目前是否缺：
  - `ffmpeg` / `ffprobe`（影音 HLS 衍生檔）
  - `CIVITAI_API_KEY`（root-only Civitai 搜尋/下載）
  這些不會阻擋一般部署，只是能力提示。
- repo 只追蹤原始碼；DB、logs、storage、keys、TLS 憑證、reports 都是
  runtime 檔，啟動後才生成。
- 這種設計降低 clone 後的人工整理成本，也避免把別人的 runtime 狀態帶進來。

## 失敗情境與提示

- `./deploy.sh` 找不到或權限不足：
  請在 repo 根目錄執行，並確認檔案可執行。
- 能啟動但頁面打不開：
  先看 bind host / port 是否被占用，再看
  [12_TROUBLESHOOTING.md](12_TROUBLESHOOTING.md)。
- 啟動後生成很多 runtime 檔，不知道能不能 commit：
  不行；runtime 檔不應提交到 Git。看 [02_DEPLOY_PRODUCTION.md](02_DEPLOY_PRODUCTION.md)
  與 [For_developer.md](For_developer.md) 的 runtime 說明。
- 只想用遠端 ComfyUI：
  先把站跑起來，再由 root 在設定頁配置；不要把 ComfyUI 整合視為第一步部署阻塞項。

## 測試方式

- `python3 scripts/pre_push_checks.py`
- `security/run_functional_smoke.sh --port 50741`
- `curl -k -sS https://127.0.0.1:5000/api/version`
- 手動登入 `root`，確認首頁、設定頁、主要模組頁可載入

## 相關文件連結

- [00_START_HERE.md](00_START_HERE.md)
- [02_DEPLOY_PRODUCTION.md](02_DEPLOY_PRODUCTION.md)
- [03_ADMIN_GUIDE.md](03_ADMIN_GUIDE.md)
- [11_QA_TESTING.md](11_QA_TESTING.md)
- [12_TROUBLESHOOTING.md](12_TROUBLESHOOTING.md)
- [DEPLOYMENT.md](DEPLOYMENT.md)
- [For_developer.md](For_developer.md)
