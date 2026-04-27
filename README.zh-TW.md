# hackme_web

[English README](README.md)

![status](https://img.shields.io/badge/status-active-2ea043)
![backend](https://img.shields.io/badge/backend-Flask-000000)
![database](https://img.shields.io/badge/database-SQLite-0f6ab4)
![security](https://img.shields.io/badge/focus-auth%20%2B%20RBAC%20%2B%20audit-b31d28)

`hackme_web` 是一個以安全性為核心的 Flask Web 應用，專門用來研究
認證、RBAC、moderation 狀態機、審計能力與單機服務的防護收斂。

它刻意設計在教學靶場與偏正式服務之間：

- 有真實的帳號、審核、違規、申覆與聊天流程
- 規模夠小，可以完整理解
- 防護機制夠真實，可以做功能與安全測試

## 快速開始

```bash
python3 -m pip install -r requirements.txt
export HTML_LEARNING_ROOT_PASSWORD='change-this-root-password'
export HTML_LEARNING_MANAGER_PASSWORD='change-this-manager-password'
export HTML_LEARNING_TEST_PASSWORD='change-this-test-password'
python3 server.py
```

開啟：

```text
https://127.0.0.1:5000/
```

初始化帳號不再硬編碼。全新資料庫啟動時，`root` 會從 `HTML_LEARNING_ROOT_PASSWORD` 建立；只有在設定 `HTML_LEARNING_MANAGER_PASSWORD`、`HTML_LEARNING_TEST_PASSWORD` 時，才會建立 `admin` 與 `test`。

## 部署常見問題

### 執行 `python3 server.py` 後網站打不開

先確認伺服器實際 listen 的 host 與 port。內建 Flask server 預設使用
`HTML_LEARNING_HOST=0.0.0.0` 與 `HTML_LEARNING_PORT=5000`。

```bash
export HTML_LEARNING_HOST=0.0.0.0
export HTML_LEARNING_PORT=5000
python3 server.py
```

如果 root 已經在管理 UI 修改 `server_listen_host` 或
`server_listen_port`，請先重啟伺服器再測試。bind 設定只會在下次啟動生效。

### 要開 `http://` 還是 `https://`？

如果專案根目錄存在 `cert.pem` 與 `key.pem`，服務會用 HTTPS 啟動；否則會用
HTTP。啟動 log 會印出實際 scheme。

### 全新資料庫 root 登不進去

第一次成功初始化資料庫前，必須先設定 `HTML_LEARNING_ROOT_PASSWORD`。如果
database 已經用其他密碼建立，就請使用原本 root 密碼；只有在你確定要重建全新
站台時，才刪除並重建資料庫。

### 改了環境變數但設定沒有變

多數 runtime 設定在 bootstrap 後會存到 SQLite 的 `system_settings`。root 可在
伺服器設定 UI 調整。環境變數主要是首次部署、目錄與 bind 的啟動 fallback。

### 資料庫與上傳檔案應該放哪裡？

請使用可持久化路徑，不要放在暫存目錄。預設重要資料在 `database/`、
`storage/`、`logs/`、`anchors/`、`chats/`。正式部署可改成絕對路徑：

```bash
export HTML_LEARNING_DB_DIR=/var/lib/hackme_web/database
export HTML_LEARNING_STORAGE_DIR=/var/lib/hackme_web/storage
export HTML_LEARNING_LOG_DIR=/var/log/hackme_web
```

不要把 `HTML_LEARNING_STORAGE_DIR` 指到 `/`、`/etc`、專案根目錄或 `public/`；
啟動時會拒絕危險 storage root，避免路徑穿越或覆蓋網站檔案。

### 顯示 maintenance mode 擋住存取

用瀏覽器登入 root 後，在伺服器設定關閉維護模式；或由 root 輪替 maintenance
bypass token，並在 API request 帶：

```text
X-Maintenance-Bypass-Token: <raw-token>
```

請使用輪替後只顯示一次的明文 token，不是 `maintenance_bypass_token_hash`。

### 如何確認伺服器跑的是最新版本？

看登入頁底部的發佈號，或呼叫：

```bash
curl http://127.0.0.1:5000/api/version
```

它應該與 `services/release_info.py` 和 README 內的發佈號一致。

### 管理 UI 顯示 listen IP/port 需要重啟

這是預期行為。root 可以先儲存 `server_listen_host` 與
`server_listen_port`，但已啟動的 socket 不會熱換，必須重啟服務器才會套用。

### 靜態頁面有出現，但 API 全部失敗

確認瀏覽器使用的 scheme、host、port 與 server 啟動 log 印出的位址一致。如果
放在 nginx/Caddy 後面，也要確認 forwarded headers 只在 trusted proxy IP 下啟用。

### push 或部署前該跑什麼？

建議跑與 CI 相同的本機 gate：

```bash
python3 scripts/pre_push_checks.py
```

開發中若只想快速檢查，可跑：

```bash
PYTHONPATH=. python3 -m pytest -q tests
```

## 專案目的

很多示範型登入系統只做到 login、logout 與少數保護路由。

這個 repo 的價值在於，它同時包含：

- 基於角色的帳號管理
- 需要審核的註冊流程
- 違規計點與申覆流程
- 聊天與訊息檢舉審核流程
- 可驗證完整性的審計鏈
- 可實際操作的系統設定與防護開關

## 功能總覽

### 認證與 Session

- Argon2id 密碼雜湊
- DB-backed session 驗證
- 伺服器持久化的 CSRF token
- logout 失效處理
- 登入失敗追蹤與可選 IP 封鎖
- 閒置自動登出

### 授權模型

- `super_admin`、`manager`、`user` 三層角色
- 敏感 API 一律做 server-side RBAC 檢查
- 新帳號需審核後才可正式登入
- 使用者可自助修改個資，但受欄位白名單限制

### Moderation 與狀態流程

- 違規點數追蹤
- 申覆送出與管理審核
- 訊息檢舉與管理審核
- 帳號角色與狀態的政策限制

### 審計與完整性

- SQLite 內的 tamper-evident audit chain
- `anchors/` 的 audit head 錨點快照
- 認證與 moderation 安全事件記錄
- 聊天紀錄 sidecar 檔案加密落盤

## 目前功能與預設值

登入頁底部會顯示發佈號，`GET /api/version` 也會回傳同一個版本資訊。
每次正式發布請更新 `services/release_info.py`。

- 目前發佈號：`2026.04.27-011`
- 目前 schema version：`18`

### 會員制度

會員資料已拆成可審計的基礎等級與實際生效等級：

- `base_level`：原始會員等級
- `effective_level`：實際生效等級
- `trust_score`：信任分
- `reputation`：聲望分
- `violation_score`：違規分
- `sanction_status`：`none`、`restricted`、`suspended`
- `sanction_until`：處分到期時間，可為空
- `level_updated_at`、`level_updated_by`、`level_update_reason`

`restricted` / `suspended` 會優先覆蓋 `base_level`。例如 `vip` 被處分時，
`base_level` 仍保留 `vip`，但 `effective_level` 會變成 `restricted` 或
`suspended`，到期或解除處分後才恢復。

| 等級 | 預設互動模型 |
|---|---|
| `newbie` | 可留言，發文低額度且需審核，不能私訊，不能上傳 |
| `normal` | 可正常發文、留言、私訊，預設不能上傳 |
| `trusted` | 較高額度，可上傳，檢舉權重較高 |
| `vip` | 最高配額，可上傳，升等需 admin/root 核准 |
| `restricted` | 只能閱讀，不能發文、留言、私訊、上傳 |
| `suspended` | 只能登入、查看通知與申訴入口，不能互動或檢舉 |

權限與門檻都從 DB table `member_level_rules` 載入，不在 route 內 hardcode。
root 可透過 `/api/admin/member-level-rules` 調整每級規則。

可配置欄位包括：

- 權限：發文、留言、私訊、上傳、檢舉
- rate limit：發文、留言、私訊、上傳
- 附件大小與總配額
- 發文是否需審核
- 檢舉權重
- 升等門檻：帳號天數、核准內容數、積分、信任分、聲望、最大違規分
- 降級/處分門檻
- 是否需要 admin/root 核准

所有會員等級變更都會寫入 `member_level_audit`，包含 actor、target、old/new
base level、old/new effective level、reason、source 與 created_at。

### 管理員制衡與治理紀錄

- `moderation_proposals` / `moderation_votes` 支援 admin 投票流程。
- 支援動作：`warn`、`mute`、`restrict`、`suspend`、`delete`、`downgrade_level`、`force_password_reset`。
- 提案通過後才可執行；root 可 override。
- 管理 UI 已提供「會員治理」頁籤，可建立提案、投票、執行、root override，並查看會員規則摘要。
- 治理紀錄分散在 `moderation_actions`、`user_mod_notes`、`reputation_events`。

### 快照、還原與伺服器模式

root 可用下列 API 管理回滾：

- `POST /api/admin/snapshots`
- `GET /api/admin/snapshots`
- `GET /api/admin/snapshots/daily`
- `POST /api/admin/snapshots/daily`
- `GET /api/admin/snapshots/<snapshot_id>`
- `POST /api/admin/snapshots/<snapshot_id>/restore`
- `DELETE /api/admin/snapshots/<snapshot_id>`
- `POST /api/admin/system-reset`
- `GET /api/admin/server-mode`
- `POST /api/admin/server-mode`
- `POST /api/admin/server-mode/exit-superweak`

snapshot 內容包含：

- SQLite database backup
- upload/media runtime files archive
- redacted config archive，不保存明文 secret
- `metadata.json`
- `manifest.json`
- `checksums.sha256`

伺服器模式：

- `preprod`：一般強化模式
- `test`：測試模式狀態
- `superweak`：刻意弱化供內部演練

進入 `superweak` 只能由 root 二次確認，且會自動建立 `before_superweak`
snapshot。離開時預設應還原該 snapshot；root 也可以明確選擇保留 dirty
state，但會寫入高風險 audit log。

daily auto snapshot 由 `snapshot_daily_auto_enabled`、
`snapshot_daily_time`、`snapshot_daily_last_date` 控制。伺服器背景 worker
會依排程檢查，每天最多建立一次 `scheduled` snapshot。
`POST /api/admin/system-reset` 是 root-only runtime reset：會先建立
`pre_reset` snapshot，再清空可重建的 runtime tables 與使用者檔案根目錄，
不會刪除 users、system_settings、audit logs 或 snapshot records。

伺服器存取控制：

- `GET /api/admin/access-controls`：root only，讀取 root IP whitelist、browser-only mode、maintenance bypass token 狀態。
- `PUT /api/admin/access-controls`：root only，更新 `root_ip_whitelist_enabled`、`root_ip_whitelist`、`browser_only_mode_enabled`，或清除 bypass token。
- `POST /api/admin/access-controls/maintenance-bypass-token`：root only，輪替 bypass token；明文 token 只回傳一次，DB 只保存 hash，預設 30 分鐘過期。

root IP whitelist 啟用後，非白名單 IP 不可 root 登入或使用 root API。
browser-only mode 啟用後，非瀏覽器 API client 會被阻擋，除非帶有效
maintenance bypass token。maintenance bypass token 可在維護模式中臨時允許
API 存取，而不需要關閉全站維護。
失敗回應會提示 header 名稱 `X-Maintenance-Bypass-Token`；使用者應提供明文
token，不能提供 `maintenance_bypass_token_hash`。

root 也可以在伺服器設定 UI/API 設定下一次啟動要 listen 的
`server_listen_host` 與 `server_listen_port`。host 留空或 port 設 `0`
會沿用 `HTML_LEARNING_HOST` / `HTML_LEARNING_PORT`。修改後必須重啟服務器，
因為已啟動的 socket 不能安全熱換 bind 位址。

### 健康監控中心

root 健康診斷已拆成獨立 API：

- `GET /api/admin/health/readiness`：檢查 DB/schema、runtime 目錄、audit chain、maintenance mode、snapshot service readiness。
- `GET /api/admin/health/anomaly`：檢查待處理治理佇列、隔離上傳檔、maintenance mode、audit chain 異常訊號。
- `GET /api/admin/health/audit-chain`：audit chain 完整性驗證結果。
- `GET /api/admin/health/db-integrity`：SQLite `quick_check`、foreign key check、schema version check。

### 隱私分級上傳安全

隱私上傳系統 Phase 1 已落地：DB 會記錄檔案 privacy mode、risk level、
scan status、E2EE encrypted file key、掃描結果、存取紀錄與可配置的檔案
類型政策。

支援模式：

- `public_attachment`：公開附件，伺服器可讀明文且必須掃描。
- `private_scannable`：私密但可掃描，上傳後可進入加密保存。
- `e2ee_vault`：只保存客戶端密文，server/root/admin 不可解密。
- `e2ee_vault_with_client_scan`：E2EE 加本機掃描回報，但回報不可完全信任。

預設政策會禁止 executable 類型公開/私密可掃描上傳，E2EE 檔案標記為
`unknown_encrypted` 或高風險，壓縮檔與巨集文件必須掃描後才能釋出。

雲端硬碟安全中心已提供：

- `GET /api/files/quota`：目前用量、剩餘容量、檔案數、會員等級限制、依隱私模式/風險/掃描狀態分組統計。
- `GET /api/files/security-policy`：目前啟用的雲端硬碟安全政策與使用者可見限制。
- `GET /api/files/privacy-modes`：四種上傳隱私模式與對應警告。

登入後 UI 會顯示「雲端硬碟」頁籤，包含已用容量、剩餘容量、單檔限制、
每日上傳限制、風險分布、掃描狀態、隱私模式分布與目前強制套用的安全措施。

### 功能開關與預設值

功能開關存在 DB-backed `system_settings`，root 可在管理 UI 調整。

| 設定 | 預設 |
|---|---:|
| `feature_chat_enabled` | `true` |
| `feature_community_enabled` | `true` |
| `feature_accounts_enabled` | `true` |
| `feature_appeals_enabled` | `true` |
| `feature_audit_log_enabled` | `true` |
| `feature_violation_center_enabled` | `true` |
| `feature_reports_enabled` | `true` |
| `feature_system_health_enabled` | `true` |
| `feature_identity_governance_enabled` | `true` |
| `feature_account_security_enabled` | `false` |
| `feature_member_governance_enabled` | `false` |
| `feature_server_modes_enabled` | `false` |
| `feature_snapshot_restore_enabled` | `false` |
| `feature_health_center_enabled` | `true` |
| `feature_forum_core_enabled` | `true` |
| `feature_ui_rebuild_enabled` | `false` |
| `feature_reports_notifications_enabled` | `true` |
| `feature_dm_enabled` | `false` |
| `feature_attachments_enabled` | `false` |
| `feature_storage_albums_enabled` | `false` |
| `feature_personalization_enabled` | `false` |
| `feature_social_search_enabled` | `false` |
| `feature_advanced_security_enabled` | `false` |
| `feature_privacy_uploads_enabled` | `false` |

其他重要預設：

| 設定 | 預設 |
|---|---:|
| `audit_chain_enabled` | `false` |
| `ip_blocking_enabled` | `true` |
| `maintenance_mode` | `false` |
| `root_ip_whitelist_enabled` | `false` |
| `root_ip_whitelist` | 空字串 |
| `browser_only_mode_enabled` | `false` |
| `maintenance_bypass_token_hash` | 空字串 |
| `maintenance_bypass_token_expires_at` | 空字串 |
| `server_listen_host` | 空字串，沿用 `HTML_LEARNING_HOST` |
| `server_listen_port` | `0`，沿用 `HTML_LEARNING_PORT` |
| `snapshot_daily_auto_enabled` | `false` |
| `snapshot_daily_time` | `03:00` |
| `snapshot_daily_last_date` | 空字串 |
| `allow_register` | `true` |
| `require_email_verification` | `false` |
| `max_login_failures` | `3` |
| `block_duration_minutes` | `10` |
| `session_ttl_hours` | `4` |

## 目前架構

後端已從單一巨石檔拆成 route modules 與 service modules。

### 後端路由模組

- `routes/public.py`
- `routes/chat.py`
- `routes/users.py`
- `routes/appeals.py`
- `routes/moderation.py`
- `routes/system_admin.py`
- `routes/operations.py`

### 後端服務模組

- `services/auth.py`
- `services/audit.py`
- `services/settings.py`
- `services/violations.py`
- `services/security_events.py`
- `services/bootstrap.py`
- `services/chat_support.py`
- `services/governance_records.py`
- `services/member_levels.py`
- `services/moderation_proposals.py`
- `services/permissions.py`
- `services/release_info.py`
- `services/snapshots.py`

### 前端結構

前端不再依賴單一巨大 `app.js`。

- `public/index.html` 依序載入 `public/js/` 內多個瀏覽器腳本
- `public/js/00-core.js`：共享狀態與工具函式
- `public/js/10-users.js`：帳號列表與顯示邏輯
- `public/js/20-chat.js`：聊天相關 UI 邏輯
- `public/js/30-appeals.js`：申覆與檢舉 UI 邏輯
- `public/js/40-auth-users.js`：登入、註冊、個資操作
- `public/js/50-admin.js`：管理端、審計、設定、健康度
- `public/js/90-bootstrap.js`：DOM 綁定與啟動流程
- `public/app.js`：僅保留相容性 stub

## 角色模型

| 角色 | 目的 | 權限 |
|---|---|---|
| `super_admin` | 完整控制面 | 帳號生命週期、設定、審核、審計、伺服器操作 |
| `manager` | 日常營運與 moderation | 查看帳號、審核註冊、處理一般用戶層級的管理動作 |
| `user` | 一般使用 | 登入、改個資、聊天、送檢舉、送申覆 |

## 資料保護模型

### 靜態資料保護

- 密碼使用 Argon2id 雜湊
- 暱稱、真實姓名、生日、身分證、電話等 PII 欄位在入庫前加密
- `chats/` 內的聊天 transcript sidecar 以 sealed 格式寫入
- session token 只以 hash 形式儲存在 SQLite session table

### 執行期儲存位置

- `database/`：SQLite 狀態
- `logs/`：runtime log
- `anchors/`：audit chain 錨點
- `chats/`：加密聊天 sidecar
- `.fkey`、`.csrfkey`、`.integrity_key`、`.chain_seed` 會在首次啟動時自動建立，重啟後必須持續保留

測試與 CI 可覆寫這些目錄：

- `HTML_LEARNING_DB_DIR`
- `HTML_LEARNING_LOG_DIR`
- `HTML_LEARNING_CHAT_DIR`
- `HTML_LEARNING_ANCHOR_DIR`
- `HTML_LEARNING_HOST`
- `HTML_LEARNING_PORT`

## 安全控制

目前已有的防護包括：

- Argon2id 密碼雜湊
- 統一化登入失敗訊息
- 公開敏感流程的 rate limit
- 寫入路由 CSRF 驗證
- DB-backed session 驗證
- Flask-Talisman 提供的 CSP
- audit chain 完整性驗證
- server-side 角色授權檢查
- 由 `system_settings` 控制的可選 IP 封鎖
- 完整性異常可切入緊急維護模式

## 測試策略

### 本機靜態與 Smoke 檢查

專案內建一個正式的 pre-push quality gate：

```bash
python3 scripts/pre_push_checks.py
```

這個 runner 會做：

- backend、scripts、tests 的 Python 語法編譯
- 使用隔離 runtime 目錄啟動一次乾淨的 Flask 服務
- 功能 smoke 測試
- 安全 smoke 測試

原本的 shell 入口仍保留：

```bash
./scripts/pre_push_scan.sh
```

### Smoke 測試覆蓋

`tests/smoke_suite.py` 目前涵蓋：

- 透過 bootstrap 環境變數建立的 `root`、`admin`、`test` 帳號登入
- `/api/me` 角色檢查
- manager 可用管理 API
- 一般使用者被正確拒於管理 API 之外
- 聊天室列表與建立聊天室
- 一般使用者的申覆列表讀取
- 無 CSRF 的 login 被拒絕
- 錯誤 CSRF 的 authenticated write 被拒絕
- cross-session CSRF token 濫用被拒絕
- logout 後 session 失效

### GitHub Actions CI

CI 會在 `main` push 與 pull request 時執行。

流程：

- 安裝 Python 依賴
- 執行 `python scripts/pre_push_checks.py --ci`

這讓本機與 GitHub 走同一套隔離 smoke/security gate。

## Repository Layout

| 路徑 | 用途 |
|---|---|
| `server.py` | Flask 入口與 app 組裝層 |
| `routes/` | 路由模組 |
| `services/` | domain / infra services |
| `public/index.html` | 前端結構 |
| `public/js/` | 拆分後的前端邏輯 |
| `public/styles.css` | 前端樣式 |
| `database/bootstrap.schema.sql` | bootstrap schema |
| `scripts/run_prod.sh` | production 啟動腳本 |
| `scripts/pre_push_scan.sh` | 靜態掃描 + quality gate wrapper |
| `scripts/pre_push_checks.py` | 隔離的功能/安全 pre-push runner |
| `tests/smoke_suite.py` | 端對端 smoke 與安全檢查 |
| `.github/workflows/ci.yml` | GitHub Actions pipeline |

## 設定模型

目前設定來源有三層：

1. 環境變數
2. DB-backed `system_settings`
3. application defaults

舊式 JSON 設定檔不再是主要真相來源。

## Production 啟動

使用內建範本：

```bash
cp .env.production.example .env
source .env
./scripts/run_prod.sh
```

建議的 production 預設值包括：

- `FORCE_HTTPS=true`
- `SESSION_COOKIE_SECURE=true`
- `SESSION_COOKIE_HTTPONLY=true`
- `SESSION_COOKIE_SAMESITE=Strict`
- `IP_BLOCKING_ENABLED=true`

## 運維備註

- 本機安全測試產物與攻擊腳本不進 Git
- runtime secrets 與 local state 檔不進 Git
- 這仍是一個單機 Flask 服務，不是分散式平台
- 內建 quality gate 之所以可重複執行，是因為它永遠使用隔離 runtime 目錄
