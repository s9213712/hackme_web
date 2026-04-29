# hackme_web

[English README](README.md)

![status](https://img.shields.io/badge/status-active-2ea043)
![backend](https://img.shields.io/badge/backend-Flask-000000)
![database](https://img.shields.io/badge/database-SQLite-0f6ab4)
![security](https://img.shields.io/badge/focus-auth%20%2B%20RBAC%20%2B%20audit-b31d28)

**目前 Release ID：`2026.04.29-020`**

`hackme_web` 是一個以安全性為核心的 Flask Web 應用，用來研究認證、
RBAC、moderation workflow、審計能力與單機服務防護。

README 現在只保留入口資訊。伺服器功能、預設設定與 API 細節已移出 README。

## 文件

- [WEB.md](WEB.md)：網站 UI 與使用者功能介紹
- [For_developer.md](For_developer.md)：API、伺服器預設設定、部署與開發說明
- [SECURITY.md](SECURITY.md)：安全政策
- [security/PRE_RELEASE_CHECKLIST.md](security/PRE_RELEASE_CHECKLIST.md)：上線前檢查清單
- [security/FUNCTIONAL_SMOKE.md](security/FUNCTIONAL_SMOKE.md)：功能 smoke 腳本
- [security/PENTEST.md](security/PENTEST.md)：滲透測試腳本
- [docs/BRANCHING_AND_RELEASE.md](docs/BRANCHING_AND_RELEASE.md)：分支編號與版本號規則

## 快速開始

```bash
python3 -m venv .venv
. .venv/bin/activate
python3 -m pip install -r requirements.txt
export HTML_LEARNING_ROOT_PASSWORD='change-this-root-password'
export HTML_LEARNING_MANAGER_PASSWORD='change-this-manager-password'
export HTML_LEARNING_TEST_PASSWORD='change-this-test-password'
python3 server.py
```

開啟 server 啟動時印出的網址。預設本機網址：

```text
http://127.0.0.1:5000/
```

## 全新環境

本 repo 設計為只靠 git 追蹤檔即可啟動。資料庫、log、金鑰、storage、
integrity manifest 等 runtime 狀態會在啟動時產生，不應提交。

乾淨部署流程：

1. clone repo
2. 安裝 `requirements.txt`
3. 在終端機執行 `scripts/run_prod.sh`，依照初次部署設定精靈完成設定

Runtime 檔案與營運預設值請看 [For_developer.md](For_developer.md)。

## 本機檢查

push 前：

```bash
python3 scripts/pre_push_checks.py
```

快速測試：

```bash
PYTHONPATH=. python3 -m pytest -q tests
```
