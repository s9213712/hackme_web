# hackme_web — Hardened Flask Auth Server

A production-oriented single-page authentication server built with Flask, featuring defense-in-depth security controls, role-based access control (RBAC), tamper-evident audit logging, and automated violation tracking.

> 本系統為 html_learning 專案的核心認證與管理後端。

## 系統定位
專為「練習滲透測試」場景設計的合法目標系統。系統本身具備完整防御機制，並保留完整滲透測試與修補紀錄供後續回放。

## 安全機制
- Argon2id 密碼雜湊（time_cost=3, memory=64MB, parallelism=4）+ fake hash 防時序攻擊 + 計時模糊化
- CSRF：Double-submit cookie + 一次性 token + DB 持久化 + GET 端點用 `@require_csrf_safe`
- Session：Fernet 加密 + DB 追蹤 + 一次性 logout
- 速率限制：register 10次/分鐘、login 30次/分鐘
- 帳號枚舉防護：統一錯誤訊息
- CSP via Flask-Talisman（前端分離式 CSS/JS 後可逐步收斂到更嚴格策略）
- `users`/`user_passwords`/`sessions` 等正規化資料表 + HMAC-SHA256 hash chain 稽核日誌

## 角色權限
- `super_admin`（`root`，最多 1 人）：全部權限，含密碼複雜度繞過、使用者管理、審計與系統參數
- `manager`（最多 5 人）：查看帳號、審計、違規、封鎖/解封一般用戶
- `user`：一般操作

## 違規處理
- 管理者：3次違規計點會降級為一般用戶
- 一般用戶：5次直接刪除

## 快速啟動
```bash
pip install -r requirements.txt
python3 server.py
```

### 生產啟動（建議）
```bash
cp .env.production.example .env
# 編輯 .env（替換 SESSION_SECRET 與 CSRF_SECRET_KEY）
source .env
./scripts/run_prod.sh
```
> `.env.production.example` 內有 `SESSION_COOKIE_SECURE=true`、`IP_BLOCKING_ENABLED=true`、`FORCE_HTTPS=true` 等預設。

- 預設帳號：`root` / `admin`
- 管理員帳號：`admin` / `admin`

## API（核心）
公開：`GET /api/csrf-token`、`POST /api/register`、`POST /api/login`、`POST /api/logout`

管理（最低 `manager`）：
- `GET /api/admin/users`
- `GET /api/admin/violations`
- `GET /api/admin/audit`

超級管理者（`root`）：
- `POST /api/admin/users`
- `GET/PUT/DELETE /api/admin/users/<id>`
- `POST /api/admin/users/<id>/promote`
- `POST /api/admin/users/<id>/demote`
- `POST /api/admin/users/<id>/violation`
- `POST /api/admin/users/<id>/reset-violations`
- `POST /api/admin/users/<id>/block`
- `GET/PUT /api/admin/settings`
- `POST /api/admin/restart`

## 最新滲透掃描與修補
- XSS/SQLi/CSRF/Session 篡改/帳號枚舉/密碼儲存：✅ 已防護
- Type confusion 5xx：✅ 已緩解

## 專案結構
- `server.py`：核心後端
- `public/index.html`：前端入口（結構）
- `public/styles.css`：樣式
- `public/app.js`：前端行為邏輯
- `database/database.db`：SQLite
- `logs/audit.log`, `logs/server.log`
- `requirements.txt`
- `scripts/run_prod.sh`
- `scripts/migrate_legacy_json.py`
- `README.md`、`SECURITY.md`、`upgrade_plan.md`
- `attack_test/*`：滲透測試腳本與紀錄

### 資料層轉型（第 2 階段）
- 系統設定由 JSON 檔 (`system_settings.json`、`settings.json`) 轉為 SQLite 的 `system_settings` 表。
- 安全事件與舊版稽核紀錄可透過下列腳本一次性匯入：
```bash
python3 scripts/migrate_legacy_json.py
```
- `migrate_legacy_json.py` 建議保留：平常啟動時已自動遷移，但此腳本可作為遺留檔案稽核、資料補償、疑難故障處理的手動工具；確認環境完全穩定後可視情況再移除。
- 啟動時會透過 `schema_migrations` 表進行 schema 版本控制（目前版本：4），避免後續 DB 變更時重放失敗或遺漏欄位。
- 啟動時 `init_db()` 會自動偵測並嘗試補入 legacy JSON（`blocked_ips.json`、`fail_log.json`、`rate_limit.json`、`audit.log`）資料。
## 架構收斂與維運
- 前端已完成 CSS/JS 外部化，降低單檔集中。
- 後端 `server.py` 仍是主集中點（2200+ 行）並已規劃下一版拆分為 `core/` 與 `routes/` 模組。
- 每次交付前建議執行：`./scripts/pre_push_scan.sh`
- 上線前建議先填好 `.env.production.example` 並以 `./scripts/run_prod.sh` 啟動（會自動 `init_db` 並以 Gunicorn 對外服務）
