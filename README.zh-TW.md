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

- 目前發佈號：`2026.04.27-004`
- 目前 schema version：`17`

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
- 治理紀錄分散在 `moderation_actions`、`user_mod_notes`、`reputation_events`。

### 快照、還原與伺服器模式

root 可用下列 API 管理回滾：

- `POST /api/admin/snapshots`
- `GET /api/admin/snapshots`
- `GET /api/admin/snapshots/<snapshot_id>`
- `POST /api/admin/snapshots/<snapshot_id>/restore`
- `DELETE /api/admin/snapshots/<snapshot_id>`
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
