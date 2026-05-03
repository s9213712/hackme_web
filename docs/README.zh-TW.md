# hackme_web

[English README](../README.md)

![status](https://img.shields.io/badge/status-active-2ea043)
![backend](https://img.shields.io/badge/backend-Flask-000000)
![database](https://img.shields.io/badge/database-SQLite-0f6ab4)
![security](https://img.shields.io/badge/focus-auth%20%2B%20RBAC%20%2B%20audit-b31d28)

**目前 Release ID：`2026.05.03-052`**

`hackme_web` 是一個以安全性為核心的 Flask Web 應用，用來研究認證、
RBAC、moderation workflow、審計能力與單機服務防護。

`2026.05.03-052` 版新增 root 可選擇是否走 ComfyUI 加速 API、在 AI 頁面顯示
ComfyUI 剩餘點數、讓 save/share/discard 依照實際產圖 backend 回源處理，並把
Civitai 模型下載改成可輪詢進度的工作流程與進度條。

`2026.05.02-047` 版新增整站 production gate，並把 Video Platform 納入整站
驗收範圍。最新影音模組變更後仍需重新跑整站 gate，才可把結果視為最終
release evidence。

`2026.05.02-045` 版強化 Server Mode v2 企業級上線驗收：新增 live HTTP
smoke，實際走 Flask session/cookie/CSRF、測試員 token traversal、superweak
狀態下 kill -9 後重啟 rollback、incident_lockdown 後舊 session/token 失效，
以及 live mode log 驗證。Server Mode v2 控制面已標記
`production_readiness=YES`，但整站正式上線仍需完成剩餘 production gate。
另降低 SQLite session `last_seen` 更新造成的鎖定機率，並補清楚模式 token
文件。

`2026.05.02-044` 版新增更新時自動 stash 運行中檔案、pre-push 版號自動遞增
hook、DCA 機器人首次扣款修正、Binance 回測分頁取得最多 5000 根 K 棒，及
設定頁面更新後顯示更新摘要。

`2026.05.02-043` 版將 BTC_trade 信號整合改為預設關閉，新增 root 啟用後
自動 clone/update/build 的建置流程，實測乾淨部署與 BTC_trade 首次建置，
並修正 production DB 初始化腳本。

`2026.05.02-042` 版將官方交易 Workflow 模板整理到 `workflows/`，補上
詳細模板說明，新增官方模板觸發與 K 線回測驗證腳本，並在 UI/API 顯示
回測長度限制。

`2026.05.02-041` 版強化 root 的 GitHub 更新流程：套用更新前會先建立
server snapshot 與 PointsChain ledger backup，任一保護點失敗就中止更新，
更新成功後會自動重啟伺服器。

`2026.05.02-040` 版讓定投機器人建立後立即執行第一筆、在機器人卡片顯示
下次執行倒數、改善機器人操作失敗提示、補強 Workflow 模板與編輯器行為，
並讓 root 的 GitHub 更新中心顯示本次更新摘要。

`2026.05.02-039` 版將 BTC_trade 橋接程式移入本專案，更新交易頁的
BTC 信號區以支援新版 BTC_trade runtime 報告欄位，並同步整理交易系統文件。

`2026.05.01-038` 版新增瀏覽器端 E2EE 預覽、整合雲端硬碟檔案工具列，
並改善 direct link / BT 遠端下載判斷與入口。

`2026.05.01-037` 版新增 root 專用的一鍵處理異常 PointsChain、整理伺服器
健康度儀表板，並同步更新功能 smoke、越權滲透、交易壓力測試與 pre-push
腳本。Economy 線包含現貨交易 MVP、實驗性借貸交易、定投機器人、節點式
Workflow 策略機器人與回測。

README 現在只保留入口資訊。伺服器功能、預設設定與 API 細節已移出 README。

## 文件

- [文件總目錄](README.md)：所有主題教學與操作文件入口
- [WEB.md](WEB.md)：網站 UI 與使用者功能介紹
- [TRADING.md](TRADING.md)：交易系統、交易機器人、Workflow Editor、回測與驗證腳本
- [research_reports/GRID_TRADING_BOT_DESIGN_REPORT.md](research_reports/GRID_TRADING_BOT_DESIGN_REPORT.md)：
  未來網格交易機器人的研究設計報告，尚未啟用為正式功能
- [SERVER_MODE_V2_PROFILE_MATRIX.md](SERVER_MODE_V2_PROFILE_MATRIX.md)：Server Mode v2 模式矩陣、確認詞與 production gate
- [SERVER_MODE_V2_MIGRATION_PLAN.md](SERVER_MODE_V2_MIGRATION_PLAN.md)：Server Mode v2 六階段遷移計畫
- [SERVER_MODE_V2_TEST_PLAN.md](SERVER_MODE_V2_TEST_PLAN.md)：Server Mode v2 測試與驗收計畫
- [For_developer.md](For_developer.md)：API、伺服器預設設定、部署與開發說明
- [SECURITY.md](SECURITY.md)：安全政策
- [security/PRE_RELEASE_CHECKLIST.md](security/PRE_RELEASE_CHECKLIST.md)：上線前檢查清單
- [security/PRODUCTION_SIGNOFF_CHECKLIST.md](security/PRODUCTION_SIGNOFF_CHECKLIST.md)：Server Mode v2 最終上線審核表
- [security/SERVER_MODE_V2_RED_TEAM_PLAYBOOK.md](security/SERVER_MODE_V2_RED_TEAM_PLAYBOOK.md)：Server Mode v2 紅隊攻擊測試腳本
- [security/FUNCTIONAL_SMOKE.md](security/FUNCTIONAL_SMOKE.md)：功能 smoke 腳本
- [security/PENTEST.md](security/PENTEST.md)：滲透測試腳本
- [BRANCHING_AND_RELEASE.md](BRANCHING_AND_RELEASE.md)：分支編號與版本號規則

## 快速開始

```bash
python3 -m venv .venv
. .venv/bin/activate
python3 -m pip install -r requirements.txt
python3 server.py
```

全新資料庫會建立 `root/root`、`admin/admin`、`test/test`，並在第一次登入
後強制改密碼。若要改初始密碼，請在第一次啟動前設定
`HTML_LEARNING_ROOT_PASSWORD`、`HTML_LEARNING_MANAGER_PASSWORD`、
`HTML_LEARNING_TEST_PASSWORD`。

開啟 server 啟動時印出的網址。預設本機網址：

```text
http://127.0.0.1:5000/
```

## 全新環境

本 repo 設計為只靠 git 追蹤檔即可啟動。資料庫、log、金鑰、本地 TLS
憑證、storage、integrity manifest 等 runtime 狀態會在啟動時產生，不應提交。

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

這個阻擋式 pre-push gate 會編譯 Python、確認版本文件同步、拒絕追蹤 runtime
檔案與本機工作站路徑、執行 `git diff --check`、掃描明文 secrets、在本機有
安裝時額外執行 `gitleaks` 與 `node --check`、跑核心 pytest。預設模式刻意保持
快速，不會啟動伺服器；只有明確加 `--full` 才會跑 isolated `/tmp` server smoke、
API contract、snapshot/restore、Server Mode、PointsChain 與 log-chain 檢查。
`--ci` 代表非互動與輸出淨化，不等於重型測試。可加 `--clean --yes` 清 repo 內安全快取，或加
`--clean-temp --yes` 清舊的 `/tmp/html_learning_prepush_*`、
`/tmp/html_learning_secrets_*`，預設保留最新兩個。

快速測試：

```bash
PYTHONPATH=. python3 -m pytest -q tests
```
