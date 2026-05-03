# Documentation Audit Report

## 範圍

本次重整以「部署者視角」為主，掃描了：

- `README.md`
- `docs/*.md`
- `docs/security/*.md`
- `docs/archive/webterminal/*.md`
- `workflows/README.md`
- 測試與驗證相關說明文件

另同步盤點了：

- `scripts/pre_push_checks.py` / `scripts/prepush/*`
- `security/*.py` / `security/*.sh`
- 對應的 `tests/*` 文件規則與腳本測試

## 合併了哪些文件主題

- 部署入口：
  原本散在 `README.md`、`docs/README.zh-TW.md`、`DEPLOYMENT.md`、
  `For_developer.md` 的啟動與部署說明，整併為
  [00_START_HERE.md](00_START_HERE.md)、
  [01_DEPLOY_QUICKSTART.md](01_DEPLOY_QUICKSTART.md)、
  [02_DEPLOY_PRODUCTION.md](02_DEPLOY_PRODUCTION.md)。
- 使用者 / 管理者入口：
  原本散在 `WEB.md`、`VIDEO_PLATFORM.md`、`TRADING.md`、
  `For_developer.md` 的操作說明，整併為
  [03_ADMIN_GUIDE.md](03_ADMIN_GUIDE.md)、
  [04_USER_GUIDE.md](04_USER_GUIDE.md)、
  [05_FEATURES_OVERVIEW.md](05_FEATURES_OVERVIEW.md)。
- 安全 / 恢復 / 經濟：
  原本散在 `SECURITY.md`、Server Mode v2 文件、
  `RUNTIME_RESET_AND_RECOVERY.md`、`For_developer.md` 的說明，整併為
  [06_SECURITY_MODEL.md](06_SECURITY_MODEL.md)、
  [07_POINTSCHAIN.md](07_POINTSCHAIN.md)、
  [09_SNAPSHOT_RESET_RESTORE.md](09_SNAPSHOT_RESET_RESTORE.md)。
- 測試 / QA：
  原本散在 `QA_MISSION_FOR_AGENTS.md`、`docs/security/*.md`、
  `PRE_RELEASE_CHECKLIST.md` 的測試入口，整併為
  [11_QA_TESTING.md](11_QA_TESTING.md)。

## 拆分了哪些文件

- `README.md`
  從「專案簡介 + release 歷史 + 快速開始 + 大量細節」拆成
  「專案簡介 + 快速路線 + 文件地圖」。
- `docs/README.md`
  從單純索引頁，改成分層閱讀的文件地圖。
- `docs/README.zh-TW.md`
  從接近第二份 README，改成中文捷徑與分層導航。

## 標記為第二層 / 深層參考的文件

這些文件保留內容，但不再作為新部署者第一站：

- `docs/DEPLOYMENT.md`
- `docs/For_developer.md`
- `docs/WEB.md`
- `docs/TRADING.md`
- `docs/VIDEO_PLATFORM.md`
- `docs/RUNTIME_RESET_AND_RECOVERY.md`
- `docs/SECURITY.md`
- `docs/QA_MISSION_FOR_AGENTS.md`
- `docs/security/FUNCTIONAL_SMOKE.md`
- `docs/security/PENTEST.md`
- `docs/security/FUNCTIONAL_PERMISSION_PENTEST.md`

## 哪些文件移到 archive

本次沒有新增移動實體檔案到 `docs/archive/`。

原因：

- 目前已有大量既有連結、測試與操作習慣綁定現有檔名。
- 這一輪先用「建立新主入口 + 將舊文件降級為深層參考 / deprecated entry」
  的方式降學習成本，而不是大規模改路徑。
- 現有已封存內容仍維持在 `docs/archive/webterminal/`。

## 腳本是否有重複測試項目

有交集，但已重新標記用途，避免誤認為完全重複：

- `scripts/pre_push_checks.py`
  是快速本機 gate，偏 repo 衛生、文件同步、輕量 pytest。
- `security/run_functional_smoke.sh`
  是隔離 runtime 的功能回歸。
- `security/run_pentest.sh`
  是外層 orchestrator，包多種安全檢查與子腳本。
- `security/functional_permission_pentest.py`
  是角色 / 權限 / 異常輸入專測。
- `security/trading_stress_pentest.py`
  是交易正確性 / 壓力 / restore consistency 專測。
- `tests/smoke_suite.py`
  與 functional smoke 有交集，但仍偏 pytest / repo 內回歸層。

仍保留的一個相容型重複入口：

- `scripts/pre_push_scan.sh`
  已是 legacy compatibility wrapper，真正邏輯只在 `scripts/pre_push_checks.py`
  與 `scripts/prepush/*`。

## 發現並修正的明確矛盾

- `docs/For_developer.md` 的 feature flag 預設值與 `services/settings.py`
  不一致，本次已更新為目前程式預設。
- 文件入口原本同時由 `README.md`、`docs/README.zh-TW.md`、`docs/README.md`
  各自承擔首站角色，造成新部署者不知道先看哪份；本次改成
  `README.md -> docs/00_START_HERE.md` 的單一路線。
- 測試 / QA 入口原本散在多份文件，本次用 [11_QA_TESTING.md](11_QA_TESTING.md)
  收斂。

## 哪些內容仍需人工確認

- 若未來真的要把 `docs/implementation_workflow.md`、`PHASE_STATUS.md`、
  `VERSION_STORY.md` 再往 archive 移，應先確認是否還有使用者把它們當活文件。
- 若未來要把舊深層參考文件改名成 `*_REFERENCE.md`，應先同步修正所有測試與既有書籤。
- `docs/research/*` 目前仍保留大量設計草案；它們是歷史與規劃資料，不是現行操作文件。是否再細分 archive / research 目錄，建議人工決策。

## 是否仍存在重複或矛盾說明

已大幅降低，但仍保留「可接受的深層參考重複」：

- `WEB.md`、`VIDEO_PLATFORM.md`、`TRADING.md` 仍會和新總覽文件有主題重疊；
  這是刻意保留的第二層參考，不是入口衝突。
- `For_developer.md` 仍會覆蓋部署、API、測試、運維等多主題；目前已透過新入口文件把它降成 reference。
- `docs/security/*.md` 仍保留各自完整腳本細節；`11_QA_TESTING.md` 只做導航與關係說明。

結論：

- 新手部署入口已收斂。
- 重複內容沒有直接硬刪，而是改成分層閱讀。
- 深層技術文件與歷史文件仍完整保留。
