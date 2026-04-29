# hackme_web

[English README](../README.md)

![status](https://img.shields.io/badge/status-active-2ea043)
![backend](https://img.shields.io/badge/backend-Flask-000000)
![database](https://img.shields.io/badge/database-SQLite-0f6ab4)
![security](https://img.shields.io/badge/focus-auth%20%2B%20RBAC%20%2B%20audit-b31d28)

**目前 Release ID：`2026.04.29-022`**

`hackme_web` 是一個以安全性為核心的 Flask Web 應用，用來研究認證、
RBAC、moderation workflow、審計能力與單機服務防護。

README 現在只保留入口資訊。伺服器功能、預設設定與 API 細節已移出 README。

## 文件

- [文件總目錄](README.md)：所有主題教學與操作文件入口
- [WEB.md](WEB.md)：網站 UI 與使用者功能介紹
- [For_developer.md](For_developer.md)：API、伺服器預設設定、部署與開發說明
- [SECURITY.md](SECURITY.md)：安全政策
- [security/PRE_RELEASE_CHECKLIST.md](security/PRE_RELEASE_CHECKLIST.md)：上線前檢查清單
- [security/FUNCTIONAL_SMOKE.md](security/FUNCTIONAL_SMOKE.md)：功能 smoke 腳本
- [security/PENTEST.md](security/PENTEST.md)：滲透測試腳本
- [BRANCHING_AND_RELEASE.md](BRANCHING_AND_RELEASE.md)：分支編號與版本號規則

## 快速開始

```bash
scripts/run_prod.sh
```

全新 checkout 會自動建立 `.venv`、安裝 Python 套件、開啟初次部署設定精靈、
初始化資料庫並啟動 Gunicorn。開啟 server 啟動時印出的網址。預設本機網址：

```text
http://127.0.0.1:5000/
```

## 全新環境

本 repo 設計為只靠 git 追蹤檔即可啟動。資料庫、log、金鑰、storage、
integrity manifest 等 runtime 狀態會在啟動時產生，不應提交。

乾淨部署流程：

1. clone repo
2. 在終端機執行 `scripts/run_prod.sh`
3. 依照初次部署設定精靈完成設定

Runtime 檔案與營運預設值請看 [For_developer.md](For_developer.md)。

## 選用 Web Terminal

Web Terminal 是 root-only 選用功能。若要啟用，先執行：

```bash
./install_web_terminal_dependencies.sh --doctor --venv .venv
./install_web_terminal_dependencies.sh --all --venv .venv
```

腳本會盡量自動安裝 Docker、Node/npm、xterm.js、Python WebSocket 套件並建立
`hackme-web-terminal:base` container image。若 Docker 權限需要重新登入或重開
服務，腳本會列出具體修復指令。

Web Terminal 網路模式可由 root 在伺服器設定切換：

- `none`：離線容器，最安全
- `bridge`：標準 Docker 全網路模式，目前預設
- `host`：共用主機網路 namespace，風險最高，只建議除錯時短暫使用

## 本機檢查

push 前：

```bash
python3 scripts/pre_push_checks.py
```

快速測試：

```bash
PYTHONPATH=. python3 -m pytest -q tests
```
