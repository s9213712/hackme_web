# 架構掃描報告（2026-04-26）

## 1) 檔案結構總覽
- 目錄主體由 `server.py`、`public/*`、`attack_test/*`、`database/`、`logs/` 構成。
- 已完成前端外部化：`public/styles.css`、`public/app.js`。
- 參考資料：`README.md`、`SECURITY.md`、`upgrade_plan.md`。

## 2) 冗餘與重複檢查
- 未發現同名功能重複實作的明顯重複檔案。
- `attack_test/` 為測試腳本與紀錄，屬流程文件，不屬冗餘。
- `migrate.py` 內含舊版遷移設計，建議加上「已存檔/棄用」標註避免未來誤用。

## 3) 過時文件
- 舊版文件曾出現預設密碼、權限邏輯與 CSP/速率限制描述與實作不一致。
- 已修正 `README.md`、`SECURITY.md` 主要欄位。

## 4) 代碼集中度
- `server.py` 約 2200 行，包含工具函式、DB 邏輯、路由與安全機制集中，為主要集中風險。
- 前端集中度已減少：`index.html` 僅保留結構，樣式與腳本分離。

## 5) 實體檔案與可讀性
- `public/index.html` 不再內嵌 1.5k 行 CSS/JS。
- 專案啟用 `logs/`、`database/` 專用目錄，根目錄檔案更乾淨。

## 6) 建議
1. 優先將後端切分：
   - `app/core.py`（設定、工具、加解密、驗證）
   - `app/db.py`（DB schema 與資料存取）
   - `app/routes.py`（API route handlers）
2. 在 push 前固定執行 `./scripts/pre_push_scan.sh`。
3. 建立 CI 快速掃描：大檔警示、TODO/FIXME 檢查、內嵌事件 handler 檢查。
