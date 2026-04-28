# hackme_web 實作等級功能擴充企劃 v3
版本：v3 implementation-level  
定位：論壇型網站 + 安全治理平台 + 安全測試靶場  
目標：保留既有安全防護，新增會員治理、論壇功能、伺服器模式、快照還原、健康監控與忘記密碼功能。

---

## ⚠️ 強制分支要求

**本建議案之所有實作，嚴禁直接 commit 至 `main` 或 `master` 分支。**

所有實作內容必須遵循以下分支策略：

```
main                  ← 受保護分支，禁止直接推送
feature/forum-governance-security-modes  ← 主要功能分支
```

實作流程：
1. 從 `main` 建立新功能分支（例：`feature/storage-album`）
2. 在功能分支內完成開發、測試
3. 透過 Pull Request 合併至 `main`
4. PR 須通過所有 CI/CD 測試，並經過 code review

任何直接推送至 `main` 的 commit 將被視為違反本規範，須回溯修正。

---

# 0. 專案總目標

將 hackme_web 從單純的登入 / 權限 / CSRF 測試網站，升級為：

1. 類論壇會員網站
2. 帳號治理與管理員投票平台
3. 可切換安全強度的安全測試靶場
4. 可快照、還原、重設的實驗環境
5. 有完整健康狀態、異常狀態與 audit log 的管理系統

完成後，系統應具備：

- 一般會員分級
- 管理員處分投票
- root 三種伺服器模式
- 準上線燈 / 異常燈
- Danger Zone
- Snapshot / Restore
- Forgot Password
- 積分 / 威望 / 信任分數
- 版區 / 版主制度
- 檢舉 / 申訴
- 安全事件中心
- 權限矩陣
- 自動備份
- 系統完整性檢查

---

# 1. 核心安全原則

## 1.1 權限原則

所有敏感操作必須在後端驗證，不得只靠前端 UI 隱藏。

角色層級：

```text
root
admin
security_admin
content_admin
moderator
user
guest
```

基本規則：

1. root 擁有最高權限，但所有操作仍需 audit log。
2. admin 不得修改 root。
3. admin 不得自行提升為 root。
4. admin 對刪除、停權、降級帳戶等高風險操作需投票。
5. moderator 只能管理指定版區。
6. user 不可呼叫 admin/root API 成功。
7. guest 只能讀取公開頁面與註冊 / 登入 / 忘記密碼。

---

## 1.2 高風險操作原則

以下操作必須具備：

- CSRF token
- 登入狀態
- 權限檢查
- 二次確認
- audit log
- 操作原因 reason
- 操作結果紀錄
- 測試覆蓋

高風險操作包含：

- 刪除帳號
- 停權帳號
- 降級會員
- 改變伺服器模式
- 進入 superweak mode
- reset server
- restore snapshot
- 修改 security settings
- 修改權限矩陣
- 大量刪除文章 / 使用者
- 清空 audit log

---

## 1.3 Audit Log 原則

所有重要操作都要記錄：

```text
audit_logs
- id
- actor_user_id
- actor_username
- actor_role
- action
- target_type
- target_id
- target_summary
- ip_address
- user_agent
- request_id
- server_mode
- security_context
- success
- failure_reason
- created_at
- prev_hash
- entry_hash
```

要求：

1. audit log 必須有 hash chain。
2. superweak mode 不得污染正式 audit log。
3. reset server 前必須先 snapshot。
4. restore snapshot 必須留下 restore audit 記錄。
5. log hash chain 斷裂時，異常燈必須變紅。

---

# 2. 資料庫 Schema 設計

以下以 SQLite / SQLAlchemy / Prisma / Knex 任一 ORM 均可落地，請依現有專案技術棧調整。

---

## 2.1 users

```text
users
- id INTEGER PRIMARY KEY
- username TEXT UNIQUE NOT NULL
- email TEXT UNIQUE NULL
- password_hash TEXT NOT NULL
- role TEXT NOT NULL DEFAULT 'user'
- member_level TEXT NOT NULL DEFAULT 'normal'
- status TEXT NOT NULL DEFAULT 'active'
- trust_score INTEGER NOT NULL DEFAULT 0
- points INTEGER NOT NULL DEFAULT 0
- reputation INTEGER NOT NULL DEFAULT 0
- email_verified BOOLEAN NOT NULL DEFAULT false
- two_factor_enabled BOOLEAN NOT NULL DEFAULT false
- failed_login_count INTEGER NOT NULL DEFAULT 0
- last_login_at DATETIME NULL
- password_changed_at DATETIME NULL
- must_change_password BOOLEAN NOT NULL DEFAULT false
- is_default_password BOOLEAN NOT NULL DEFAULT false
- created_at DATETIME NOT NULL
- updated_at DATETIME NOT NULL
- deleted_at DATETIME NULL
```

role：

```text
root / admin / security_admin / content_admin / moderator / user
```

member_level：

```text
newbie / normal / trusted / vip / restricted / suspended
```

status：

```text
active / limited / muted / suspended / deleted
```

---

## 2.2 member_level_rules

```text
member_level_rules
- id
- level
- can_post BOOLEAN
- can_comment BOOLEAN
- can_send_dm BOOLEAN
- can_upload_attachment BOOLEAN
- daily_post_limit INTEGER
- daily_dm_limit INTEGER
- max_attachment_size_mb INTEGER
- requires_moderation BOOLEAN
- min_points INTEGER
- min_trust_score INTEGER
- created_at
- updated_at
```

用途：

- 控制一般會員分級功能。
- 不影響 admin/root 權限。
- 權限仍需後端檢查。

---

## 2.3 moderation_proposals

```text
moderation_proposals
- id
- target_user_id
- action_type
- proposed_by_user_id
- reason
- status
- required_votes
- approve_count
- reject_count
- expires_at
- executed_at
- created_at
- updated_at
```

action_type：

```text
warn
mute
restrict
suspend
delete
downgrade_level
force_password_reset
```

status：

```text
pending / approved / rejected / expired / cancelled / executed
```

---

## 2.4 moderation_votes

```text
moderation_votes
- id
- proposal_id
- voter_user_id
- vote
- comment
- created_at
```

vote：

```text
approve / reject
```

限制：

- UNIQUE(proposal_id, voter_user_id)
- 同一 admin 不可重複投票

---

## 2.5 server_settings

```text
server_settings
- id
- key TEXT UNIQUE
- value TEXT
- value_type TEXT
- updated_by_user_id
- updated_at
```

建議 key：

```text
server_mode
api_lan_only_enabled              -- IP 白名單（只允許指定 IP/區網訪問，與瀏覽器限制無關）
allowed_ip_whitelist              -- 允許存取的 IP 清單（CIDR 或 IP，pre_production 模式時生效）
browser_only_mode_enabled         -- 準上線模式：拒絕非瀏覽器 client（curl/Python/CLI → 403，瀏覽器 + maintenance_token 正常訪問）
maintenance_bypass_token          -- SHA256 hash，root 自行設定，帶此 token 的 CLI 請求可通過 browser_only_mode（不為空時生效）
csrf_enabled
rate_limit_enabled
audit_log_enabled
login_ip_lock_enabled             -- pre_production：同 IP 同時登入不同帳號 → 阻擋
excessive_points_ban_enabled
auto_downgrade_enabled
account_delete_enabled
password_policy_enabled
admin_vote_required_enabled
maintenance_mode_enabled
```

---

## 2.6 snapshots

```text
snapshots
- id
- name
- description
- snapshot_type
- created_by_user_id
- server_mode
- checksum
- size_bytes
- encrypted
- file_path
- created_at
- restored_at
- restored_by_user_id
```

snapshot_type：

```text
manual
auto_before_superweak
auto_before_reset
daily_auto
before_restore
```

---

## 2.7 password_reset_tokens

```text
password_reset_tokens
- id
- user_id
- token_hash
- expires_at
- used_at
- created_at
- request_ip
- user_agent
```

要求：

- token 不可明文存 DB
- token 一次性
- token 有效期建議 15~30 分鐘
- 重設後清除所有 session

---

## 2.8 forum_categories

```text
forum_categories
- id
- name
- slug
- description
- sort_order
- is_public
- created_at
- updated_at
```

---

## 2.9 forum_boards

```text
forum_boards
- id
- category_id
- name
- slug
- description
- sort_order
- required_member_level
- post_requires_moderation
- created_at
- updated_at
```

---

## 2.10 board_moderators

```text
board_moderators
- id
- board_id
- user_id
- created_at
```

限制：

- moderator 僅能管理 assigned board

---

## 2.11 posts

```text
posts
- id
- board_id
- author_user_id
- title
- body
- status
- is_pinned
- is_locked
- is_featured
- created_at
- updated_at
- deleted_at
```

status：

```text
draft / pending_review / published / hidden / deleted
```

---

## 2.12 comments

```text
comments
- id
- post_id
- author_user_id
- body
- status
- created_at
- updated_at
- deleted_at
```

---

## 2.13 reports

```text
reports
- id
- reporter_user_id
- target_type
- target_id
- reason
- status
- handled_by_user_id
- resolution
- created_at
- handled_at
```

target_type：

```text
user / post / comment / dm / chat_message
```

status：

```text
pending / accepted / rejected / escalated
```

---

## 2.14 appeals

```text
appeals
- id
- user_id
- related_proposal_id
- reason
- status
- handled_by_user_id
- resolution
- created_at
- handled_at
```

---

## 2.15 notifications

```text
notifications
- id
- user_id
- type
- title
- body
- read_at
- created_at
```

---

## 2.16 security_events

```text
security_events
- id
- event_type
- severity
- actor_user_id
- ip_address
- user_agent
- details_json
- created_at
```

event_type：

```text
login_failed
csrf_failed
permission_denied
rate_limited
admin_action
mode_changed
snapshot_created
snapshot_restored
hash_chain_broken
suspicious_ip
```

severity：

```text
info / warning / high / critical
```

## 2.17 user_storage

儲存每個用戶的雲端硬碟配額與使用量。

```text
user_storage
- id
- user_id              (UNIQUE, FK -> users.id)
- role_quota_mb        INTEGER  -- 角色預設配額（MB）
- level_quota_mb       INTEGER  -- 等級額外配額（MB）
- total_quota_mb       INTEGER  -- role_quota_mb + level_quota_mb（-1 = 無上限）
- max_file_size_mb     INTEGER  -- 單檔大小上限（MB），0 = 不允許上傳
- used_bytes           INTEGER  -- 目前已用位元組數（含軟刪除檔案）
- trash_bytes          INTEGER  -- 回收筒內檔案大小（不計入 used_bytes）
- created_at
- updated_at
```

**is_unlimited 判定：** `total_quota_mb = -1` 代表 root 無上限，API 回傳時翻譯為 `is_unlimited: true`。

**配額規則（角色 x 等級矩陣）：**

| 角色 \ 等級 | newbie | normal | trusted | vip | restricted | suspended |
|-------------|--------|--------|---------|-----|-------------|-----------|
| root        | 無上限  | 無上限  | 無上限   | 無上限 | 無上限      | 無上限     |
| admin       | 100 MB | 100 MB | 100 MB  | 100 MB | 100 MB    | 100 MB   |
| security_admin | 100 MB | 100 MB | 100 MB | 100 MB | 100 MB | 100 MB |
| content_admin | 100 MB | 100 MB | 100 MB | 100 MB | 100 MB | 100 MB |
| moderator   | 100 MB | 100 MB | 100 MB  | 100 MB | 100 MB   | 100 MB   |
| user        | 10 MB  | 10 MB  | 10 MB   | 10 MB | 10 MB     | 10 MB    |
| guest       | 0 MB   | 0 MB   | 0 MB    | 0 MB  | 0 MB      | 0 MB     |

**單檔大小上限（max_file_size_mb）：**

| 角色 | 上限 |
|------|------|
| root | 500 MB |
| admin / security_admin / content_admin / moderator | 100 MB |
| user | 50 MB |
| guest | 0 MB（禁止上傳）|

> 如 `member_level_rules.max_attachment_size_mb` 有更嚴格限制，取兩者較小值。

**配額計算時機：**
- 用戶登入時重新計算 role_quota_mb + level_quota_mb，寫入 user_storage。
- 權限變更（role 或 member_level 改變）時立即重新計算並更新。
- admin / security_admin / content_admin / moderator 統一為 100 MB，與會員等級脫鉤。
- 等級配額（level_quota_mb）預設為 0，預留未來 vip 等級擴充。

**低水位警告：**
- `used_bytes > total_quota_mb × 0.8` → API 回傳 `usage_percent` 含 `warning: true`
- `used_bytes >= total_quota_mb`（且非無限）→ 阻擋上傳，回傳 HTTP 413

**配額同步校正：**
- 每日凌晨快照時執行一次 `sync_used_bytes`：實際遍歷 `storage_files`（排除 soft-deleted）重新加總，比對 `used_bytes`，不符時自動修正並寫入 `storage_quota_log`（action = 'sync_correction'）。
- 管理員可從 admin UI 手動觸發「配額同步校正」。

**回收筒自動清理：**
- `trash_retention_days` 設定（預設 30 天），CRON 每日執行。
- 軟刪除超過期限的檔案執行永久刪除（實體檔案移除 + `storage_quota_log` action = 'trash_auto_purge'）。

---


---

## 2.18 storage_files

雲端硬碟中的實際檔案。

```text
storage_files
- id
- user_id              (FK -> users.id, 索引)
- parent_id            (FK -> storage_files.id, 自身遞迴，根目錄為 NULL)
- name                 TEXT NOT NULL
- stored_name          TEXT NOT NULL    -- UUID 儲存檔名（不含副檔名）
- extension            TEXT NOT NULL    -- 副檔名（小寫，如 'jpg', 'pdf'）
- mime_type            TEXT NOT NULL
- size_bytes           INTEGER NOT NULL
- stored_path          TEXT NOT NULL    -- 實際儲存於 filesystem 的路徑
- is_folder            BOOLEAN NOT NULL DEFAULT false
- deleted_at           (軟刪除，進入回收筒)
- permanent_deleted_at (永久刪除時間，NULL 表示仍在回收筒)
```

**UNIQUE 約束：**
- `UNIQUE(user_id, parent_id, name, deleted_at)` — 同一資料夾下不可有同名檔案/資料夾（軟刪除檔案同名不受此限制）。
- `UNIQUE(stored_path)` — 實體路徑不得重複。

**儲存路徑規則：**
```
uploads/{user_id}/{uuid_v4}.{extension}
```
- 使用 UUID v4 杜絕猜測，絕對禁止使用原始檔名當儲存檔名。
- 副檔名純化（小寫、正規化），杜絕 `test.php.jpg`、`NULL` 等惡意名稱。
- MIME type 以 magic bytes（檔案內容）驗證為主，副檔名為輔；兩者衝突時以 magic bytes 為準。
- 嚴禁路徑穿越：`name` / `parent_id` 查詢時後端嚴格過濾 `..`、絕對路徑、控制字元。
- 軟刪除（`deleted_at` 設值）進入回收筒，實體檔案暫存不刪。
- `permanent_deleted_at` 有值時代表已從回收筒永久刪除，實體檔案已移除。

**MIME 白名單（嚴格模式）：**

| 類別 | 允許的 MIME |
|------|-------------|
| 圖片 | `image/jpeg`, `image/png`, `image/gif`, `image/webp`, `image/svg+xml` |
| 文件 | `application/pdf`, `text/plain` |
| 影音 | `video/mp4`, `video/webm`, `audio/mpeg`, `audio/ogg`, `audio/wav` |
| 封裝 | `application/zip`, `application/x-tar`, `application/gzip` |

**拒絕清單（無論副檔名一律阻擋）：**
```
application/x-msdownload  (.exe, .scr, .pif, .com, .bat, .cmd, .vbs ...)
application/x-sh          (.sh)
application/x-shellscript
text/x-python
text/x-java
text/x-php
text/html
application/javascript   (.js)
application/x-javascript
```
> SVG 允許上傳但內嵌 script 的 SVG 必須在伺服器端 strip script 後再儲存。

**封面 / 縮圖規則：**
- 相簿封面由 `albums.cover_file_id` 指向，自動抓第一張時由 application logic 計算。
- 圖片類檔案上傳後產生一枚 `thumbnail_small`（200px）和 `thumbnail_large`（800px），儲存於 `uploads/{user_id}/thumbs/`。

---


---

## 2.19 storage_quota_log

配額變更歷史（超重要！用於審計誰用了多少空間）。

```text
storage_quota_log
- id
- user_id          (FK -> users.id)
- action           TEXT NOT NULL   -- 'upload' | 'delete' | 'folder_create' | 'folder_delete' | 'admin_adjust'
- file_id          (FK -> storage_files.id, 可為 NULL)
- bytes_delta      INTEGER         -- 這次操作的位元組增減（刪除為負）
- used_bytes_before INTEGER
- used_bytes_after  INTEGER
- reason           TEXT
- performed_by_user_id (FK -> users.id)
- ip_address       TEXT
- created_at
```

---

## 2.20 albums

相簿主體。

```text
albums
- id
- user_id              (FK -> users.id, 索引)
- name                 TEXT NOT NULL
- slug                 TEXT NOT NULL  -- URL-friendly slug，自動從 name 產生
- description          TEXT
- cover_file_id        (FK -> storage_files.id, NULL = 自動抓第一張照片)
- is_public            BOOLEAN NOT NULL DEFAULT false
- share_token          (UNIQUE, NULL = 無分享連結)
- share_expires_at     (分享連結過期時間，NULL = 永不過期)
- share_password_hash  (bcrypt, NULL = 無密碼保護)
- photo_count          INTEGER NOT NULL DEFAULT 0
- created_at
- updated_at
- deleted_at           (軟刪除)
```

**slug 自動產生規則：**
- `name = "我的相簿"` → `slug = "wo-de-xiang-bu"`（pinyin + hyphens）
- 重複時自動加 suffix：`wo-de-xiang-bu-2`、`wo-de-xiang-bu-3`
- slug 只允許 `a-z 0-9 -`

**封面自動計算邏輯：**
- `cover_file_id = NULL` 時，API 回傳時動態取 `album_files` 中 `sort_order` 最小且 `file.deleted_at IS NULL` 的 `file_id` 作為 cover。

**分享連結：**
- `share_token` = 32 字隨機種子，URL 格式 `/album/shared/{token}`
- 讀取分享相簿無需登入，輸入密碼後透過 session 驗證
- `share_expires_at` 有值且已過期 → 回傳 410 Gone

---


---

## 2.21 album_files

相簿與檔案的多對多關聯（同一照片可屬於多個相簿）。

```text
album_files
- id
- album_id             (FK -> albums.id, 索引)
- file_id              (FK -> storage_files.id, 索引)
- sort_order           INTEGER NOT NULL DEFAULT 0
- added_by_user_id     (FK -> users.id)
- created_at
```

**UNIQUE 約束：**
- `UNIQUE(album_id, file_id)` — 同一檔案不可重複加入同一相簿。

**業務規則：**
- 同一檔案可加入多個不同相簿（多對多）。
- `albums.photo_count` 在 INSERT 時 +1，DELETE 時 -1（由 application logic 維護）。
- 軟刪除的檔案（`storage_files.deleted_at IS NOT NULL`）仍可留在 `album_files`，但不計入 `photo_count`。
- 回收筒永久刪除前，須先從所有 `album_files` 移除（設 NULL 或 cascade）。

---


---

---

# 3. API 設計

所有 API 預設回傳 header：

```text
X-Hackme-Web-Mode: pre_production | test | superweak
X-Request-Id: <request_id>
```

superweak 模式下額外回傳：

```text
X-Hackme-Web-Sandbox: enabled
```

---

## 3.1 Auth API

```text
POST /api/login
POST /api/logout
GET  /api/me
POST /api/forgot-password
POST /api/reset-password
POST /api/change-password
POST /api/sessions/logout-all
```

忘記密碼規則：

1. 無論 email 是否存在，都回傳相同訊息。
2. token 只存 hash。
3. token 有效期限 15~30 分鐘。
4. 使用後立即失效。
5. 重設成功後清除該使用者所有 session。
6. 寫入 security_events。
7. 同 IP / 同 email 有 rate limit。

---

## 3.2 Member Level API

```text
GET   /api/admin/member-level-rules
PATCH /api/admin/member-level-rules/:level
PATCH /api/admin/users/:id/member-level
PATCH /api/admin/users/:id/status
```

權限：

- root 可直接修改。
- admin 修改高風險狀態時需 proposal。
- user 不可呼叫成功。

---

## 3.3 Moderation Proposal API

```text
POST /api/admin/moderation/proposals
GET  /api/admin/moderation/proposals
GET  /api/admin/moderation/proposals/:id
POST /api/admin/moderation/proposals/:id/vote
POST /api/admin/moderation/proposals/:id/execute
POST /api/root/moderation/proposals/:id/override
```

業務規則：

1. target 不可為 root。
2. proposal 過期不可投票。
3. 同一 admin 不可重複投票。
4. 達 required_votes 後 status = approved。
5. approved 後才可 execute。
6. root override 仍需 audit log。

---

## 3.4 Server Mode API

```text
GET   /api/root/server-mode
POST  /api/root/server-mode
GET   /api/root/security-settings
PATCH /api/root/security-settings
GET   /api/root/ip-whitelist
PUT   /api/root/ip-whitelist
```

模式：

```text
pre_production
test
superweak
```

pre_production 檢查：

- root/admin 預設密碼已改
- CSRF enabled
- rate limit enabled
- audit log enabled
- api_lan_only enabled 或客戶 IP 在 allowed_ip_whitelist 內
- browser_only_mode enabled：User-Agent 不符合瀏覽器特徵 → 403
  （帶有效 maintenance_bypass_token 者例外，可通過 CLI 緊急維護）
  （瀏覽器 UA（Chrome/Firefox/Safari/Edge）直接通過）
- login_ip_lock enabled
- log hash chain valid
- no active superweak sandbox
- no critical security events unresolved

test 模式：

- 關閉 login_ip_lock_enabled（**同 IP 可同時登入不同帳號，無限制**）
- 關閉 excessive_points_ban_enabled
- 關閉 auto_downgrade_enabled
- 關閉 account_delete_enabled
- 關閉 api_lan_only_enabled（**IP 白名單限制暫停，任何 IP 均可存取**）
- 關閉 browser_only_mode_enabled（**關閉瀏覽器限制，任何 client 均可存取**）
- 保留 CSRF / auth / permission check

superweak 模式：

- 進入前自動 snapshot
- 啟用 sandbox
- 可選擇安全機制開關
- 離開後恢復進入前 snapshot
- 不得污染正式資料
- **同 IP 可同時登入不同帳號（login_ip_lock_enabled 自動暫停）**
- **IP 白名單限制自動暫停（api_lan_only_enabled 自動關閉）**

---

## 3.5 Health API

```text
GET /api/health
GET /api/health/readiness
GET /api/health/anomaly
GET /api/health/integrity
```

readiness_light：

```text
green / yellow / red
```

綠燈條件：

- server_mode = pre_production
- 預設密碼已修改
- CSRF enabled
- rate_limit enabled
- audit_log enabled
- api_lan_only enabled 或客戶 IP 在 allowed_ip_whitelist 內
- browser_only_mode enabled（已啟動瀏覽器限制）
- login_ip_lock enabled（同 IP 同時登入不同帳號被阻擋）
- log hash chain valid
- snapshot system healthy
- no critical unresolved security event

anomaly_light：

```text
green / yellow / red
```

紅燈條件：

- ERROR log
- critical security event
- log hash chain broken
- DB integrity failed
- snapshot checksum failed
- superweak sandbox leak
- suspicious admin operation burst

---

## 3.6 Danger Zone API

```text
POST /api/root/danger-zone/reset-server
POST /api/root/snapshots
GET  /api/root/snapshots
GET  /api/root/snapshots/:id
POST /api/root/snapshots/:id/restore
DELETE /api/root/snapshots/:id
```

reset-server 要求：

```json
{
  "confirm_text": "RESET HACKME_WEB",
  "reason": "..."
}
```

流程：

1. 確認 root。
2. 驗證 CSRF。
3. 驗證 confirm_text。
4. 自動建立 auto_before_reset snapshot。
5. 清除所有資料。
6. 重建預設帳號。
7. 重建預設設定。
8. 清除所有 session。
9. audit log 記錄 reset。
10. 回傳成功。

預設帳號：

```text
root
admin
test 或 user
```

注意：

- reset 後 root/admin 應標記 is_default_password = true。
- pre_production 不可通過，直到密碼被修改。

---

## 3.7 Forum API

```text
GET  /api/forum/categories
POST /api/admin/forum/categories
PATCH /api/admin/forum/categories/:id
DELETE /api/admin/forum/categories/:id

GET  /api/forum/boards
POST /api/admin/forum/boards
PATCH /api/admin/forum/boards/:id
DELETE /api/admin/forum/boards/:id

GET  /api/forum/posts
POST /api/forum/posts
GET  /api/forum/posts/:id
PATCH /api/forum/posts/:id
DELETE /api/forum/posts/:id

POST /api/forum/posts/:id/comments
PATCH /api/forum/comments/:id
DELETE /api/forum/comments/:id
```

權限：

- user 可發文，但受 member_level / trust_score / rate limit 限制。
- newbie 發文可進 pending_review。
- moderator 可管理自己版區。
- content_admin 可管理所有內容。
- admin/root 可管理全站。

---

## 3.8 Report / Appeal API

```text
POST /api/reports
GET  /api/admin/reports
POST /api/admin/reports/:id/resolve

POST /api/appeals
GET  /api/admin/appeals
POST /api/admin/appeals/:id/resolve
```

---

## 3.9 Notification API

```text
GET  /api/notifications
POST /api/notifications/:id/read
POST /api/notifications/read-all
```

---

## 3.10 Security Center API

```text
GET /api/admin/security/events
GET /api/admin/security/summary
GET /api/admin/security/audit-logs
GET /api/admin/security/hash-chain/check
```


## 3.11 Storage & Cloud Drive API

### 3.11.1 Quota

```text
GET /api/storage/quota
```

回傳：
```json
{
  "role_quota_mb": 100,
  "level_quota_mb": 0,
  "total_quota_mb": 100,
  "max_file_size_mb": 50,
  "used_bytes": 5242880,
  "trash_bytes": 1048576,
  "used_mb": 5.0,
  "available_mb": 95.0,
  "trash_mb": 1.0,
  "usage_percent": 5.0,
  "is_unlimited": false,
  "warning": false,
  "can_upload": true
}
```

### 3.11.2 File Browse

```text
GET /api/storage/files?parent_id=:id&page=1&per_page=50
GET /api/storage/files/:id
```

**Query 参数：**
- `parent_id` — NULL（或省略）= 根目錄，`:id` = 該資料夾內容
- `page` / `per_page` — 分頁，預設 50 筆
- `include_deleted` — `true` = 含回收筒檔案（預設 false）

**響應（列表）：**
```json
{
  "items": [
    {
      "id": 1,
      "name": "my_photo.jpg",
      "extension": "jpg",
      "mime_type": "image/jpeg",
      "size_bytes": 204800,
      "is_folder": false,
      "parent_id": null,
      "created_at": "2026-01-01T00:00:00Z",
      "thumbnail_url": "/api/storage/files/1/thumb/small",
      "url": "/api/storage/files/1/download"
    }
  ],
  "total": 1,
  "page": 1,
  "per_page": 50
}
```

### 3.11.3 Upload

```text
POST /api/storage/upload
Content-Type: multipart/form-data
```

**欄位：**
- `file`（必需）— multipart 檔案
- `parent_id`（可選）— 上傳到哪個資料夾

**檢查順序：**
1. 驗證 session 用戶已認證
2. 驗證 `max_file_size_mb > 0`（guest / suspended = 0 → 直接 403）
3. 驗證 `used_bytes + file.size <= total_quota_mb`（root 無限則跳過配額檢查）
4. MIME 白名單檢查（magic bytes 優先）
5. 惡意副檔名過濾（`..`、`NTFS Alternate Data Streams`、NULL byte）
6. 路徑穿越防護（杜絕 `../`）
7. 寫入 `storage_files`（`stored_name = uuid_v4`，`stored_path = uploads/{user_id}/{uuid}.{ext}`）
8. 更新 `user_storage.used_bytes += file.size`（transaction）
9. 寫入 `storage_quota_log`（action = 'upload'）
10. 實體檔案寫入磁碟

**成功回傳（201）：**
```json
{ "id": 99, "name": "my_photo.jpg", "size_bytes": 204800, "url": "/api/storage/files/99/download" }
```

**錯誤：**
- 413 — 配額不足或單檔超過 `max_file_size_mb`
- 415 — MIME 不允許
- 400 — 檔名惡意（`../`、`NULL`、白名單外副檔名）

### 3.11.4 Download & Thumbnail

```text
GET /api/storage/files/:id/download
GET /api/storage/files/:id/thumb/:size   # size = small | large
```

**安全規則：**
- 僅 `file.user_id = session.user_id` 可下載本人檔案（IDOR 防護）。
- `content_admin` / `moderator` 可下載任意用戶檔案。

**縮圖：**
- 僅圖片類 MIME 支援縮圖（`image/jpeg/png/webp/gif`）
- `small` = 200px，`large` = 800px
- 非圖片回傳 404

### 3.11.5 Folder

```text
POST /api/storage/folder
PATCH /api/storage/files/:id/move
```

**建立資料夾 POST /api/storage/folder：**
```json
{ "name": "我的照片", "parent_id": null }
```
- `name` 長度 1-255，不可包含 `/ \ : * ? " < > |`
- 同名資料夾不可存在於同一 `parent_id`
- 資料夾大小為 0，不計入配額

**移動 PATCH /api/storage/files/:id/move：**
```json
{ "parent_id": 5 }
```
- 不可移動到自己的子資料夾（遞迴 cycle 防護）
- 不可移動到軟刪除的資料夾

### 3.11.6 Rename

```text
PATCH /api/storage/files/:id
```
```json
{ "name": "new_name.jpg" }
```
- 資料夾亦可重新命名
- 同名檢查（同 `parent_id` 下不可衝突）

### 3.11.7 Soft Delete (Trash)

```text
DELETE /api/storage/files/:id
```

- 設 `deleted_at = NOW()`（軟刪除）
- `used_bytes` 不變，`trash_bytes += size_bytes`
- 資料夾遞迴軟刪除所有子檔案

### 3.11.8 Restore

```text
POST /api/storage/files/:id/restore
```

- 清除 `deleted_at`
- `trash_bytes -= size_bytes`
- 父資料夾若仍在回收筒則 restore 失敗（需先還原父資料夾）

### 3.11.9 Permanent Delete

```text
DELETE /api/storage/files/:id/permanent
```

- 僅 `deleted_at IS NOT NULL` 的檔案可永久刪除
- 實體檔案從磁碟移除
- `user_storage.used_bytes -= size_bytes`，`trash_bytes -= size_bytes`
- 寫入 `storage_quota_log`（action = 'permanent_delete'）
- 從所有 `album_files` 移除（設 NULL）

### 3.11.10 Trash

```text
GET /api/storage/trash?page=1&per_page=50
DELETE /api/storage/trash/empty
```

**Empty Trash：**
- 永久刪除該用戶所有 `deleted_at IS NOT NULL` 且 `permanent_deleted_at IS NULL` 的檔案
- 不可逆，需二次確認（`DELETE /api/storage/trash/empty` 本體就是危險操作，需 CSRF + confirm text）

### 3.11.11 Quota Sync (Admin)

```text
POST /api/storage/users/:id/sync
```

- 觸發指定用戶的 `sync_used_bytes`
- 附帶 `reason` 必填，寫入 `storage_quota_log`（action = 'admin_sync'）

---

## 3.12 Album API

### 3.12.1 Album CRUD

```text
GET    /api/albums?page=1&per_page=20      # 我的相簿列表
POST   /api/albums
GET    /api/albums/:id
PATCH  /api/albums/:id
DELETE /api/albums/:id
```

**POST /api/albums：**
```json
{
  "name": "2026 旅行照片",
  "description": "日本關西之旅",
  "is_public": false,
  "share_password": null
}
```
- `name` 長度 1-255
- `slug` 自動從 `name` 產生（pinyin + hyphens）
- `share_password` 可選（bcrypt 雜湊後儲存）

**PATCH /api/albums/:id：**
- 可更新 `name`（同時更新 `slug`）、`description`、`is_public`、`cover_file_id`
- 僅 `album.user_id = session.user_id` 可修改

**DELETE /api/albums/:id（軟刪除）：**
- `deleted_at = NOW()`
- 不影響 `storage_files` 本體

### 3.12.2 Public Albums

```text
GET /api/albums/public?page=1&per_page=20
```

- 回傳所有 `is_public = true` 且 `deleted_at IS NULL` 的相簿
- 按 `created_at DESC` 排序
- 不需登入

### 3.12.3 Shared Album Access

```text
GET /api/albums/shared/:token
POST /api/albums/shared/:token/verify
```

**GET：** 讀取分享相簿（無需登入）
- token 有效且未過期 → 回傳相簿 metadata + 照片列表（不含 private 欄位）
- 有密碼保護 → 回傳 `requires_password: true`，不暴露任何內容
- 過期 → 410 Gone
- 無效 → 404 Not Found

**POST：** 驗證分享密碼
```json
{ "password": "mysecret" }
```
- 成功 → 建立 session 或 set cookie，之後當作已認證用戶存取

### 3.12.4 Album Photos

```text
GET /api/albums/:id/photos?page=1&per_page=30
POST /api/albums/:id/files
DELETE /api/albums/:id/files/:file_id
PATCH /api/albums/:id/files/reorder
```

**加入照片 POST /api/albums/:id/files：**
```json
{
  "file_ids": [1, 2, 3]
}
```
- 全部 `file_ids` 必須屬於 `session.user_id`
- 全部 `file_ids` 不得已在 `album_id` 中（UNIQUE 約束）
- `photo_count += len(file_ids)`

**移除照片 DELETE /api/albums/:id/files/:file_id：**
- 從 `album_files` 移除，album 不受影響
- `albums.photo_count -= 1`

**重新排序 PATCH /api/albums/:id/files/reorder：**
```json
{
  "orders": [
    { "file_id": 3, "sort_order": 0 },
    { "file_id": 1, "sort_order": 1 },
    { "file_id": 2, "sort_order": 2 }
  ]
}
```
- 批量更新 `sort_order`，一次 request 內全有或全無（transaction）

### 3.12.5 Cover Photo

```text
PATCH /api/albums/:id
```
```json
{ "cover_file_id": 5 }
```
- `cover_file_id` 必須是 `album_id` 中存在的 `file_id`
- 設為 `null` → 恢復自動計算邏輯

---

## 3.13 Storage Admin API

### 3.13.1 Overview

```text
GET /api/admin/storage/overview
```

回傳全站儲存統計：
```json
{
  "total_users_with_storage": 150,
  "total_used_bytes": 5368709120,
  "total_trash_bytes": 1073741824,
  "total_files": 1234,
  "top_users": [
    { "user_id": 5, "username": "alice", "used_bytes": 1073741824 },
    { "user_id": 8, "username": "bob", "used_bytes": 536870912 }
  ]
}
```

### 3.13.2 User Storage Detail

```text
GET /api/admin/storage/users/:id
POST /api/admin/storage/users/:id/adjust-quota
```

**調整配額 POST：**
```json
{
  "role_quota_mb": 200,
  "reason": "VIP 用戶申請擴充"
}
```
- `reason` 必填，寫入 `storage_quota_log`（action = 'admin_adjust'）
- 若新配額小於已使用空間，則新配額無效（系統不得因此砍檔案）

### 3.13.3 Quota Log

```text
GET /api/admin/storage/quota-logs?user_id=:id&page=1&per_page=50
```

- audit trail，查看所有 storage 操作的歷史

### 3.13.4 Storage Cleanup

```text
POST /api/admin/storage/cleanup-trash
POST /api/admin/storage/sync-all
```

- `cleanup-trash` — 強制執行回收筒清理（依 `trash_retention_days`）
- `sync-all` — 對全站用戶執行配額同步校正

---


---

# 4. 伺服器模式實作細節

## 4.1 pre_production

啟用時強制設定：

```text
csrf_enabled = true
rate_limit_enabled = true
audit_log_enabled = true
api_lan_only_enabled = true
allowed_ip_whitelist = [root 設定的允許 IP 清單，空白 = 只允許本機 / 區網]
browser_only_mode_enabled = true    -- 拒絕非瀏覽器 client（curl/Python/CLI → 403）
maintenance_bypass_token = ''       -- CLI 緊急維護通道，設定後攜帶有效 token 可通過（不建議留空）
login_ip_lock_enabled = true       -- 同 IP 同時登入不同帳號 → 阻擋
excessive_points_ban_enabled = true
auto_downgrade_enabled = true
account_delete_enabled = true
password_policy_enabled = true
admin_vote_required_enabled = true
```

切換前檢查：

1. root 密碼非預設。
2. admin 密碼非預設。
3. 沒有 active default password admin。
4. log hash chain valid。
5. DB integrity OK。
6. API lan-only middleware 已啟用。
7. 無 active superweak sandbox。
8. snapshot system 可正常建立測試 snapshot。

失敗時回傳：

```json
{
  "ok": false,
  "mode": "pre_production",
  "reasons": [
    "root default password is still active",
    "admin default password is still active"
  ]
}
```

---

## 4.2 test

啟用時設定：

```text
login_ip_lock_enabled = false
excessive_points_ban_enabled = false
auto_downgrade_enabled = false
account_delete_enabled = false
browser_only_mode_enabled = false    -- 關閉瀏覽器限制，任何 client 均可存取
maintenance_bypass_token = ''         -- 重置為空（test 環境不需要緊急維護通道）
csrf_enabled = true
rate_limit_enabled = true
audit_log_enabled = true
```

目的：

- 方便內測。
- 不因測試登入錯誤而鎖 IP。
- 不因測試資料造成帳號處分。
- 仍保留基本安全防線。

---

## 4.3 superweak

啟用流程：

1. root 發送 POST /api/root/server-mode。
2. confirm_text 必須正確，例如 ENABLE SUPERWEAK。
3. 系統建立 auto_before_superweak snapshot。
4. 建立 sandbox database 或 transaction overlay。
5. 切換到 superweak。
6. UI 顯示紅色警告。
7. API header 顯示 mode 與 sandbox。
8. 離開 superweak 時還原 snapshot。
9. 刪除 sandbox 資料。

superweak 可以選擇關閉：

```text
csrf_enabled
rate_limit_enabled
login_ip_lock_enabled
excessive_points_ban_enabled
auto_downgrade_enabled
account_delete_enabled
password_policy_enabled
admin_vote_required_enabled
```

不得關閉：

```text
audit_log_enabled for sandbox log
root ownership check
sandbox boundary
mode marker
```

重要限制：

- superweak 中的變更不得寫入正式 DB。
- superweak 中的密鑰不得覆蓋正式密鑰。
- superweak 中的 audit log 應獨立存 sandbox_audit_logs。
- 離開 superweak 必須回到啟用前狀態。

---

# 5. Snapshot / Restore 實作細節

## 5.1 Snapshot 範圍

必須保存：

- users
- member_level_rules
- server_settings
- forum_categories
- forum_boards
- board_moderators
- posts
- comments
- reports
- appeals
- notifications
- moderation_proposals
- moderation_votes
- security_events metadata
- chat rooms / messages
- non-sensitive config

不得明文保存：

- password plaintext
- reset token plaintext
- secret plaintext

可保存：

- password_hash
- token_hash
- key hash
- checksum

---

## 5.2 Snapshot 格式

建議：

```text
snapshots/
  2026-04-27_120000_manual_<id>.json.gz
  2026-04-27_120000_manual_<id>.sha256
```

snapshot JSON：

```json
{
  "version": 1,
  "created_at": "...",
  "created_by": "root",
  "server_mode": "test",
  "tables": {
    "users": [],
    "posts": [],
    "settings": []
  },
  "checksum": "..."
}
```

---

## 5.3 Restore 流程

1. root 驗證。
2. CSRF 驗證。
3. confirm_text 驗證。
4. 檢查 snapshot checksum。
5. 建立 before_restore snapshot。
6. 暫停寫入。
7. restore tables。
8. 重建必要 index。
9. 檢查 DB integrity。
10. 寫入 audit log。
11. 清除 session。
12. 要求重新登入。

---

# 6. 忘記密碼實作細節

## 6.1 Request Reset

API：

```text
POST /api/forgot-password
```

Request：

```json
{
  "email": "user@example.com"
}
```

Response 永遠相同：

```json
{
  "ok": true,
  "message": "If the account exists, a reset link has been sent."
}
```

防護：

- email rate limit
- IP rate limit
- token hash only
- token expires
- audit / security event

---

## 6.2 Reset Password

API：

```text
POST /api/reset-password
```

Request：

```json
{
  "token": "...",
  "new_password": "..."
}
```

成功後：

1. 更新 password_hash。
2. password_changed_at = now。
3. is_default_password = false。
4. token used_at = now。
5. 清除所有 session。
6. 寫入 security_events。
7. 發通知。

---

# 7. 前端頁面規劃

## 7.1 root 後台

新增頁面：

```text
/admin/root/server-mode
/admin/root/security-settings
/admin/root/danger-zone
/admin/root/snapshots
/admin/root/health
/admin/root/integrity
```

Danger Zone UI：

- 紅色區塊
- 二次確認
- confirm text
- 顯示最後 snapshot
- reset server
- restore snapshot
- enter superweak

---

## 7.2 admin 後台

新增頁面：

```text
/admin/users
/admin/moderation/proposals
/admin/reports
/admin/appeals
/admin/security/events
/admin/audit-logs
/admin/member-levels
/admin/forum
/admin/permission-matrix
```

---

## 7.3 一般會員頁面

```text
/account/security
/account/password
/account/notifications
/account/appeals
/forum
/forum/boards/:id
/forum/posts/:id
```

---

## 7.4 全站模式 UI

所有頁面頂部顯示：

```text
Mode: pre_production / test / superweak
```

superweak：

- 紅色 banner
- 顯示「目前為沙盒，所有變更離開後會失效」
- 顯示被關閉的安全機制

---

# 8. 權限矩陣

| 功能 | guest | user | moderator | content_admin | security_admin | admin | root |
|---|---|---|---|---|---|---|---|
| 讀公開文章 | yes | yes | yes | yes | yes | yes | yes |
| 發文 | no | yes | yes | yes | yes | yes | yes |
| 管理指定版區 | no | no | yes | yes | no | yes | yes |
| 查看 security events | no | no | no | no | yes | yes | yes |
| 建立處分提案 | no | no | limited | yes | yes | yes | yes |
| 投票處分 | no | no | no | no | yes | yes | yes |
| 直接處分帳號 | no | no | no | no | no | no | yes |
| 切換 server mode | no | no | no | no | no | no | yes |
| reset server | no | no | no | no | no | no | yes |
| restore snapshot | no | no | no | no | no | no | yes |

| 上傳檔案 | no | yes | yes | yes | yes | yes | yes |
| 下載自己檔案 | no | yes | yes | yes | yes | yes | yes |
| 下載他人檔案 | no | no | board_only | yes | yes | yes | yes |
| 刪除/移動/重新命名自己檔案 | no | yes | yes | yes | yes | yes | yes |
| 回收筒讀取/還原自己 | no | yes | yes | yes | yes | yes | yes |
| 永久刪除自己檔案 | no | yes | yes | yes | yes | yes | yes |
| 查看自己相簿 | no | yes | yes | yes | yes | yes | yes |
| 建立/編輯/刪除自己相簿 | no | yes | yes | yes | yes | yes | yes |
| 管理他人相簿 | no | no | board_only | yes | yes | yes | yes |
| 訪問公開相簿 | yes | yes | yes | yes | yes | yes | yes |
| 訪問分享相簿（含密碼） | yes | yes | yes | yes | yes | yes | yes |
| 瀏覽全站相簿（admin用） | no | no | no | yes | yes | yes | yes |
| admin 調整用戶配額 | no | no | no | no | no | yes | yes |

| 修改權限矩陣 | no | no | no | no | no | no | yes |

---

# 9. 測試計畫

## 9.1 Auth 測試

- login 成功
- login 失敗
- CSRF 缺失
- CSRF 錯誤
- forgot password 不洩漏帳號存在
- reset token 一次性
- reset 後 session 清除
- 預設密碼使用者不得進 pre_production

---

## 9.2 權限測試

每個新增 API 都要測：

```text
guest -> 401
user -> 403
moderator -> limited
admin -> allowed / proposal required
root -> allowed
```

---

## 9.3 IDOR 測試

- user 修改別人的 member_level：403
- user 修改自己的 role：403 或忽略
- admin 修改 root：403
- moderator 跨版刪文：403
- user restore snapshot：403
- user reset server：403

---

## 9.4 Moderation 測試

- 建立 proposal
- 重複投票失敗
- 過期 proposal 不可投票
- 票數不足不可 execute
- 票數足夠可 execute
- root override 可執行
- target root 失敗

---

## 9.5 Server Mode 測試

- root 切 test 成功
- user 切 mode 失敗
- admin 切 mode 失敗
- pre_production 條件不足失敗
- pre_production 條件完整成功
- superweak 啟用前建立 snapshot
- superweak 操作離開後失效
- superweak 不污染正式 DB

---

## 9.6 Snapshot 測試

- 建立 snapshot
- checksum 正確
- restore 成功
- restore 前自動 snapshot
- checksum 錯誤拒絕 restore
- restore 後 session 清除
- reset 前自動 snapshot

---

## 9.7 Health 測試

- readiness green
- readiness red with reasons
- anomaly green
- ERROR log 觸發 anomaly red
- hash chain broken 觸發 anomaly red
- snapshot checksum fail 觸發 anomaly red

---

## 9.8 Forum 測試

- newbie 發文進 pending_review
- trusted 發文直接 published
- moderator 可鎖自己版文章
- moderator 不可跨版
- content_admin 可管理全部文章
- soft delete 可 restore

---

## 9.9 Storage & Album 測試

- guest 上傳被阻擋（403）
- 配額不足上傳被阻擋（413）
- 單檔過大上傳被阻擋（413）
- MIME 白名單阻擋（.exe / .php / .html → 415）
- magic bytes 欺騙阻擋（副檔名合法但內容為執行檔 → 415）
- 路徑穿越阻擋（檔名含 `../` → 400）
- 上傳成功後 used_bytes 增加正確
- soft delete 後 trash_bytes 增加，used_bytes 不變
- restore 後 trash_bytes 減少
- permanent delete 後 used_bytes 和 trash_bytes 均減少
- empty trash 永久刪除所有回收筒檔案
- 用戶下載他人檔案（IDOR → 403）
- content_admin 可下載任意用戶檔案
- 資料夾移動形成 cycle 被偵測並阻擋（400）
- 相簿 slug 自動產生且唯一
- 分享連結有密碼時無法讀取內容（需先 POST /verify）
- 分享連結過期回傳 410 Gone
- admin 調整配額寫入 storage_quota_log
- 配額同步後 used_bytes 與實際相符
- 軟刪除的檔案加入相簿後不計入 photo_count

---


# 10. 實作 Phase

## Phase 1：資料結構與權限基礎

目標：

- 完成 DB schema
- 完成 role/member_level/status
- 完成 permission middleware
- 完成 audit log 基礎
- 完成 security_events 基礎

交付：

- migrations
- models
- seed 預設帳號
- permission helper
- audit helper
- 基礎測試

驗收：

- role 越權測試全通過
- user 無法修改 role/member_level/status
- admin 無法修改 root

---

## Phase 2：會員分級與管理員投票

目標：

- member_level_rules
- moderation_proposals
- moderation_votes
- admin 處分投票流程
- root override

交付：

- API
- admin UI
- tests

驗收：

- admin 不能直接刪帳
- 必須 proposal + vote
- root 可 override
- audit log 完整

---

## Phase 3：Server Mode

目標：

- pre_production
- test
- superweak
- security_settings
- mode header
- superweak sandbox

交付：

- server mode API
- root UI
- middleware
- tests

驗收：

- pre_production 條件檢查正確
- test 模式關閉指定機制
- superweak 所有變更離開後失效

---

### browser_only_mode 實作方式（Phase 3 附錄）

**用途：** 準上線模式時，拒絕 curl / Python / Postman 等非瀏覽器 client，
避免機器人腳本意外攻擊或錯誤操作，同時保留緊急維護 CLI 通道。

**不通過的典型 client（被 403）：**
```text
curl
Python-requests / urllib / httpx
axios / node-fetch / fetch (Node.js)
Postman / Insomnia (非瀏覽器 UA)
任何未攜帶瀏覽器 UA 的 HTTP 工具
```

**通過的條件（滿足任一即通過）：**
1. User-Agent 符合瀏覽器特徵（`Chrome`、`Firefox`、`Safari`、`Edge`）
2. 帶有有效的 `Authorization: Bearer <maintenance_bypass_token>` header

**拒絕流程：**
```
請求抵達
  → 檢查 browser_only_mode_enabled 是否為 true
  → 若為 false：直接通過（test / superweak 模式）
  → 若為 true：
      ├─ UA 為瀏覽器 → 通過
      ├─ 有 Bearer token 且 hash 與 maintenance_bypass_token 比對成功 → 通過
      └─ 否則 → 403 Forbidden
```

**maintenance_bypass_token 實作細節：**
```text
- 儲存：SHA256 hash（不儲存明文）
- 格式：SHA256('<root_password>:<random_seed>')，由 root 自行生成
- 攜帶方式：curl -H "Authorization: Bearer <token>" ...
- 設定位置：server_settings key = 'maintenance_bypass_token'
- 日誌區分：所有來自 maintenance_token 的請求在 audit log 中標記
             event_type = 'maintenance_cli_access'，不同於一般 browser 訪問
- 最小權限：maintenance_token 只豁免 browser_only_mode 檢查，
            仍須通過 auth / permission / CSRF 等其他 middleware
```

**重要限制：**
- `maintenance_bypass_token` 不為空時才生效（為空 = 關閉此緊急通道）
- superweak 模式下 `browser_only_mode` 自動關閉，maintenance_token 無效
- `maintenance_bypass_token` 不可用於跨 mode 提升權限（root 仍需密碼）

---

---

## Phase 4：Health / Security Center

目標：

- readiness light
- anomaly light
- integrity check
- security center

交付：

- health API
- security events UI
- hash chain checker
- tests

驗收：

- 異常事件能觸發紅燈
- 準上線條件缺失能列出原因
- log hash chain broken 可偵測

---

## Phase 5：Danger Zone / Snapshot / Restore / Reset

目標：

- snapshot
- restore
- reset server
- before_reset snapshot
- before_restore snapshot

交付：

- root Danger Zone UI
- snapshot storage
- restore flow
- reset flow
- tests

驗收：

- reset 後回到三個預設帳號
- restore 可恢復資料
- checksum 錯誤不可還原
- reset/restore 都需二次確認

---

## Phase 6：Forgot Password / Email Verify / Session Security

目標：

- forgot password
- reset password
- email verify
- logout all sessions
- login device record

交付：

- API
- UI
- mail adapter/mock
- tests

驗收：

- 不洩漏帳號存在
- token 一次性
- reset 後清 session
- 頻率限制有效

---

## Phase 7：論壇基礎功能

目標：

- categories
- boards
- posts
- comments
- moderator
- content review

交付：

- forum UI
- API
- moderation UI
- tests

驗收：

- 版主權限限制正確
- 新手審核正確
- soft delete 正確

---

## Phase 8：檢舉 / 申訴 / 通知 / 積分

目標：

- reports
- appeals
- notifications
- points / reputation
- trust_score

交付：

- API
- UI
- scoring service
- tests

驗收：

- 檢舉可處理
- 申訴可處理
- 處分通知正常
- 分數影響權限

---

## Phase 9：防濫用與完整性強化

目標：

- spam detection
- rate limit
- multi-account detection
- snapshot auto schedule
- integrity dashboard

交付：

- anti-abuse middleware
- scheduled snapshot
- admin dashboard
- tests

驗收：

- 發文頻率限制
- 私訊頻率限制
- snapshot checksum valid
- DB integrity check valid

## Phase 10：站內信系統（DM）

目標：
- direct_messages / dm_threads schema
- DM API（收發 / 已讀 / 軟刪除）
- DM UI（收件匣 + 對話串）
- blocked_users 整合（阻擋 DM 送達）
- daily_dm_limit 頻率限制

交付：
- schema：direct_messages、dm_threads、blocked_users
- API：GET /api/dm/threads、POST /api/dm/threads/:user_id/messages、DELETE /api/dm/threads/:user_id
- UI：DM 收件匣、對話串視圖
- 頻率限制 middleware
- tests

驗收：
- 會員可收發 DM
- 被封鎖者無法送達 DM
- 軟刪除雙方都刪才物理移除
- daily_dm_limit 正確限制頻率
- notification 正確觸發

## Phase 11：Storage 雲端硬碟與相簿

目標：
- user_storage 配額管理（含 trash_bytes、max_file_size_mb）
- storage_files 檔案管理（upload / download / thumb / folder / move / rename）
- 回收筒（soft delete / restore / permanent delete / empty trash）
- 配額同步校正（sync_used_bytes）
- albums 相簿 CRUD（含 slug 自動產生）
- album_files 多對多關聯（add / remove / reorder / cover）
- 分享連結（share_token / 密碼保護 / 過期）
- Storage Admin API（全站統計、配額調整、日誌）

交付：
- DB migrations（新增 5 個 table）
- Storage Service（配額計算、UUID 檔名、magic bytes 驗證）
- 上傳 / 下載 / 縮圖 API
- 相簿 API
- Admin Storage API
- 前端：FileManager（支援拖曳上傳、資料夾樹、回收筒）
- 前端：AlbumManager（相簿建立、照片管理、分享設定）
- 回收筒自動清理 CRON
- 配額同步 CRON
- tests

驗收：
- guest 無法上傳（HTTP 403）
- 超出配額上傳被阻擋（HTTP 413）
- MIME 阻擋（.exe / .php / .html 等）→ HTTP 415
- 上傳後 `used_bytes` 正確增加
- 軟刪除後 `trash_bytes` 正確增加，`used_bytes` 不變
- 永久刪除後 `used_bytes` 和 `trash_bytes` 均正確減少
- 用戶無法存取他人檔案（IDOR → 403）
- content_admin 可存取任意用戶檔案
- admin 調整配額寫入 `storage_quota_log`
- 配額同步後 `used_bytes` 與實際儲存總量一致
- 相簿 slug 自動產生且唯一
- 分享連結有密碼保護時無法直接看內容
- 過期分享連結回傳 410

---


---

# 11. Agent 執行要求

請 agent 依序執行：

1. 先掃描現有專案結構。
2. 列出目前已有的 models/routes/middleware/tests。
3. 不要重複實作既有功能。
4. 先建立 feature branch。
5. 每個 phase 小步提交。
6. 每個 phase 必須包含：
   - DB migration
   - backend API
   - frontend UI
   - tests
   - README/docs 更新
7. 每完成一個 phase，輸出：
   - 完成項目
   - 修改檔案
   - 測試結果
   - 尚未完成
   - 風險
8. 不得跳過測試。
9. 不得把安全檢查只寫在前端。
10. 不得讓 superweak 污染正式資料。

建議 branch：

```text
feature/forum-governance-security-modes
```

---

# 12. 最低驗收標準

整體完成後至少要通過：

```text
- auth tests
- csrf tests
- idor tests
- permission tests
- moderation vote tests
- server mode tests
- snapshot restore tests
- reset server tests
- forgot password tests
- health light tests
- forum permission tests
- audit log hash chain tests
```

最終驗收：

1. 一般 user 無法越權。
2. admin 無法單獨刪帳。
3. root 可管理高風險功能。
4. pre_production 必須安全條件完整才亮綠燈。
5. test mode 不會誤鎖測試者。
6. superweak 離開後所有變更消失。
7. reset 可回到三個預設帳號。
8. snapshot 可還原完整網站狀態。
9. forgot password 不洩漏帳號是否存在。
10. forum 權限與版主權限正確。
11. audit log 可追蹤所有高風險操作。
12. anomaly light 可反映錯誤與異常紀錄。

---

# 14. 完成後系統水準

完成後 hackme_web 將不只是靶場，而是具備：

- 類論壇功能
- 會員治理
- 角色權限控制
- 管理員制衡
- 安全模式切換
- 弱安全沙盒
- 快照還原
- 健康監控
- 安全事件追蹤
- 可用於滲透測試與防禦測試的完整平台

---

# 15. 與 eyny 對比：缺失功能補充

> 以下功能均未出現在 v3 既有章節，屬於新增補充。
> v3 的 `member_level_rules` 已宣告 `can_send_dm` / `can_upload_attachment` 等欄位，
> 但完全沒有對應 schema、API、UI 與 Phase，本章節補全這些缺口並新增其他論壇標配功能。

---

## 15.1 站內信系統（DM / Private Messages）

v3 的 `member_level_rules` 引用了 `can_send_dm` 與 `daily_dm_limit`，但全文無任何 DM 實作設計。

### Schema

```text
direct_messages
- id INTEGER PRIMARY KEY
- sender_id    INTEGER NOT NULL REFERENCES users(id)
- receiver_id  INTEGER NOT NULL REFERENCES users(id)
- subject      TEXT
- body         TEXT NOT NULL
- is_read      BOOLEAN NOT NULL DEFAULT false
- read_at      DATETIME NULL
- sender_deleted   BOOLEAN NOT NULL DEFAULT false
- receiver_deleted BOOLEAN NOT NULL DEFAULT false
- created_at   DATETIME NOT NULL

dm_threads
- id INTEGER PRIMARY KEY
- participant_a_id INTEGER NOT NULL REFERENCES users(id)
- participant_b_id INTEGER NOT NULL REFERENCES users(id)
- last_message_at  DATETIME NOT NULL
- created_at       DATETIME NOT NULL
- UNIQUE(participant_a_id, participant_b_id)
```

### API

```text
GET  /api/dm/threads
POST /api/dm/threads/:user_id/messages
GET  /api/dm/threads/:user_id/messages
POST /api/dm/threads/:user_id/messages/:id/read
DELETE /api/dm/threads/:user_id
```

### 業務規則

1. 受 `member_level_rules.can_send_dm` 與 `daily_dm_limit` 限制。
2. 被封鎖（blocked_users）者不得收到對方 DM。
3. 管理員可在緊急情況下查閱 DM（需 audit log）。
4. 刪除為軟刪除（`sender_deleted` / `receiver_deleted`），雙方都刪才物理移除。
5. DM 可作為 `reports.target_type = 'dm'` 被檢舉（v3 已宣告此 target_type）。
6. 新 DM 觸發 `notifications` 記錄。

---

## 15.2 附件 / 圖片上傳系統

v3 的 `member_level_rules` 宣告了 `can_upload_attachment` 與 `max_attachment_size_mb`，但無任何實作設計。

### Schema

```text
attachments
- id          INTEGER PRIMARY KEY
- uploader_id INTEGER NOT NULL REFERENCES users(id)
- target_type TEXT NOT NULL   -- 'post' | 'comment' | 'dm' | 'avatar'
- target_id   INTEGER NULL    -- NULL 代表尚未綁定（草稿附件）
- filename    TEXT NOT NULL
- stored_name TEXT NOT NULL   -- UUID 命名，防目錄遍歷
- mime_type   TEXT NOT NULL
- size_bytes  INTEGER NOT NULL
- width       INTEGER NULL
- height      INTEGER NULL
- checksum    TEXT NOT NULL   -- SHA256
- is_deleted  BOOLEAN NOT NULL DEFAULT false
- created_at  DATETIME NOT NULL
```

### API

```text
POST   /api/attachments/upload
GET    /api/attachments/:id
DELETE /api/attachments/:id
```

### 安全要求

1. 上傳前驗證 MIME type（不信任副檔名，讀取 magic bytes）。
2. 白名單：`image/jpeg`, `image/png`, `image/gif`, `image/webp`, `application/pdf`。
3. 圖片強制 re-encode（去除 EXIF metadata，防止 metadata 洩漏）。
4. 儲存路徑用 UUID 命名，不可從 URL 猜出。
5. 受 `max_attachment_size_mb` 限制。
6. 管理員可刪除任何附件並留下 audit log。

---

## 15.3 用戶個人主頁與個人化

### Schema 補充（附加到現有 users table）

```text
-- 建議以 migration 追加欄位到 users
users（追加）
- avatar_attachment_id  INTEGER NULL REFERENCES attachments(id)
- bio                   TEXT NULL        -- 自我介紹，限 500 字
- signature             TEXT NULL        -- 個人簽名檔，限 200 字，顯示在每則發文下方
- custom_title          TEXT NULL        -- 自訂稱號，需管理員核准或達成就解鎖
- show_online_status    BOOLEAN NOT NULL DEFAULT true
- website_url           TEXT NULL
- location              TEXT NULL
- birth_year            INTEGER NULL     -- 僅顯示年份
```

### 公開個人主頁

```text
user_profiles（獨立 view 或 API 聚合）
- 頭像
- username / custom_title
- bio
- 加入日期
- 發文數 / 回覆數
- 積分 / 威望 / 信任分數
- 徽章列表
- 最近發文（10 筆，依隱私設定）
- 粉絲數 / 追蹤數
```

### API

```text
GET   /api/users/:id/profile
PATCH /api/account/profile
POST  /api/account/avatar
DELETE /api/account/avatar
```

### 業務規則

1. 個人資料修改（bio/signature/avatar）不需 CSRF proposal，但需 audit log。
2. 自訂稱號（custom_title）由管理員核准，或透過成就系統自動解鎖。
3. 敏感欄位（email/birthdate/id_number）不在公開 profile 顯示。

---

## 15.4 文章互動系統

### 15.4.1 按讚 / 表情反應

```text
post_reactions
- id         INTEGER PRIMARY KEY
- post_id    INTEGER NOT NULL REFERENCES posts(id) ON DELETE CASCADE
- user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE
- reaction   TEXT NOT NULL   -- 'like' | 'helpful' | 'insightful' | 'funny'
- created_at DATETIME NOT NULL
- UNIQUE(post_id, user_id)   -- 每人每文只能一種反應（更換時 UPDATE）

comment_reactions
- id         INTEGER PRIMARY KEY
- comment_id INTEGER NOT NULL REFERENCES comments(id) ON DELETE CASCADE
- user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE
- reaction   TEXT NOT NULL
- created_at DATETIME NOT NULL
- UNIQUE(comment_id, user_id)
```

API：

```text
POST   /api/forum/posts/:id/reactions
DELETE /api/forum/posts/:id/reactions
POST   /api/forum/comments/:id/reactions
DELETE /api/forum/comments/:id/reactions
```

規則：
- 匿名用戶（guest）不可按讚。
- 自己的文章不可反應。
- 反應數影響 `posts.hot_score`（計算熱門排行）。
- 按讚獲得積分（受 `server_settings` 中 `points_on_reaction_enabled` 控制）。

### 15.4.2 文章瀏覽次數

```text
posts（追加）
- view_count INTEGER NOT NULL DEFAULT 0
```

- 每次 GET `/api/forum/posts/:id` 時後端遞增。
- 同一 session 15 分鐘內不重複計數（防刷）。

### 15.4.3 引用回覆

```text
comments（追加）
- parent_comment_id INTEGER NULL REFERENCES comments(id)   -- NULL = 直接回覆主文
- quote_body        TEXT NULL                               -- 被引用的原文快照
```

- 前端顯示引用區塊（blockquote 樣式）。
- 被引用者觸發 `notifications`。

### 15.4.4 @提及系統

```text
post_mentions
- id         INTEGER PRIMARY KEY
- post_id    INTEGER NULL REFERENCES posts(id) ON DELETE CASCADE
- comment_id INTEGER NULL REFERENCES comments(id) ON DELETE CASCADE
- mentioned_user_id INTEGER NOT NULL REFERENCES users(id)
- created_at DATETIME NOT NULL
```

- 發文/回覆時解析 `@username`，自動建立 mention 記錄。
- 被提及者觸發 `notifications`（type='mention'）。
- 已封鎖對方則不觸發通知。

### 15.4.5 文章編輯歷史

```text
post_edit_history
- id         INTEGER PRIMARY KEY
- post_id    INTEGER NOT NULL REFERENCES posts(id) ON DELETE CASCADE
- editor_id  INTEGER NOT NULL REFERENCES users(id)
- old_title  TEXT NULL
- old_body   TEXT NOT NULL
- edit_reason TEXT NULL
- created_at DATETIME NOT NULL

comment_edit_history
- id          INTEGER PRIMARY KEY
- comment_id  INTEGER NOT NULL REFERENCES comments(id) ON DELETE CASCADE
- editor_id   INTEGER NOT NULL REFERENCES users(id)
- old_body    TEXT NOT NULL
- created_at  DATETIME NOT NULL
```

API：

```text
GET /api/forum/posts/:id/history
GET /api/forum/comments/:id/history
```

規則：
- 作者可在發文後 30 分鐘內免留 edit_reason 編輯。
- 超過 30 分鐘必須填 edit_reason。
- 版主/管理員可查看任何文章的編輯歷史。
- 每次編輯自動記錄（不限次數）。

---

## 15.5 搜尋功能

```text
GET /api/search?q=<keyword>&type=post|comment|user|board&board_id=<id>&page=<n>
```

搜尋範圍：

| type | 說明 |
|------|------|
| post | 文章標題 + 內文全文搜尋 |
| comment | 回覆內文搜尋 |
| user | username + nickname 搜尋 |
| board | 版區名稱搜尋 |

技術要求：

1. 基本實作：SQLite FTS5（`posts_fts` virtual table）。
2. 搜尋結果依 `hot_score` 與 `created_at` 排序。
3. 搜尋關鍵字 highlight（前端 `<mark>` 包覆）。
4. 搜尋頻率 rate limit（防爬）。
5. guest 可搜尋公開版區，私有版區需登入。

Schema：

```text
-- SQLite FTS5 virtual table
CREATE VIRTUAL TABLE posts_fts USING fts5(
  title, body, content='posts', content_rowid='id'
);
```

---

## 15.6 訂閱與追蹤系統

### 15.6.1 追蹤文章

```text
thread_subscriptions
- id         INTEGER PRIMARY KEY
- user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE
- post_id    INTEGER NOT NULL REFERENCES posts(id) ON DELETE CASCADE
- created_at DATETIME NOT NULL
- UNIQUE(user_id, post_id)
```

- 有新回覆時，訂閱者收到 notification（type='thread_reply'）。

### 15.6.2 訂閱版區

```text
board_subscriptions
- id         INTEGER PRIMARY KEY
- user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE
- board_id   INTEGER NOT NULL REFERENCES forum_boards(id) ON DELETE CASCADE
- created_at DATETIME NOT NULL
- UNIQUE(user_id, board_id)
```

- 有新文章時，訂閱者收到 notification（type='board_new_post'）。

### 15.6.3 追蹤用戶

```text
user_follows
- id           INTEGER PRIMARY KEY
- follower_id  INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE
- following_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE
- created_at   DATETIME NOT NULL
- UNIQUE(follower_id, following_id)
```

- 被追蹤時，對方收到 notification（type='new_follower'），但可在設定中關閉。
- 追蹤的用戶發新文時，粉絲可在「追蹤動態」feed 中看到。
- 不可追蹤已封鎖自己的用戶。

### 15.6.4 封鎖用戶

```text
blocked_users
- id           INTEGER PRIMARY KEY
- blocker_id   INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE
- blocked_id   INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE
- created_at   DATETIME NOT NULL
- UNIQUE(blocker_id, blocked_id)
```

- 封鎖後，被封鎖方無法送 DM、@提及、反應。
- 被封鎖方的文章在封鎖者頁面自動折疊（前端）。
- root/admin 不可被一般 user 封鎖（僅隱藏通知）。

API：

```text
POST   /api/account/blocks
DELETE /api/account/blocks/:user_id
GET    /api/account/blocks
POST   /api/account/follows
DELETE /api/account/follows/:user_id
GET    /api/account/follows           -- 我追蹤的
GET    /api/account/followers         -- 追蹤我的
POST   /api/forum/posts/:id/subscribe
DELETE /api/forum/posts/:id/subscribe
POST   /api/forum/boards/:id/subscribe
DELETE /api/forum/boards/:id/subscribe
```

---

## 15.7 文章收藏

```text
bookmarks
- id         INTEGER PRIMARY KEY
- user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE
- post_id    INTEGER NOT NULL REFERENCES posts(id) ON DELETE CASCADE
- note       TEXT NULL           -- 個人備註
- created_at DATETIME NOT NULL
- UNIQUE(user_id, post_id)
```

API：

```text
POST   /api/bookmarks
DELETE /api/bookmarks/:post_id
GET    /api/bookmarks
```

- 收藏不公開（僅本人可見）。
- 文章被刪除時 bookmark 保留記錄但標記 post_deleted。
- 收藏夾可依版區/日期篩選。

---

## 15.8 文章標籤系統

```text
tags
- id         INTEGER PRIMARY KEY
- name       TEXT NOT NULL UNIQUE
- slug       TEXT NOT NULL UNIQUE
- color      TEXT NULL   -- hex color code，用於前端顯示
- created_by INTEGER NOT NULL REFERENCES users(id)
- created_at DATETIME NOT NULL

post_tags
- post_id    INTEGER NOT NULL REFERENCES posts(id) ON DELETE CASCADE
- tag_id     INTEGER NOT NULL REFERENCES tags(id) ON DELETE CASCADE
- PRIMARY KEY(post_id, tag_id)
```

API：

```text
GET    /api/tags
POST   /api/admin/tags
DELETE /api/admin/tags/:id
PATCH  /api/forum/posts/:id/tags     -- 作者/版主/管理員可修改
GET    /api/forum/tags/:slug/posts   -- 按標籤瀏覽文章
```

規則：
- 每篇文章最多 5 個標籤。
- 標籤由 content_admin 管理，user 只能從現有標籤中選取。
- 標籤可用於搜尋和版區篩選。

---

## 15.9 文章投票（Poll）

```text
polls
- id          INTEGER PRIMARY KEY
- post_id     INTEGER NOT NULL UNIQUE REFERENCES posts(id) ON DELETE CASCADE
- question    TEXT NOT NULL
- is_multiple BOOLEAN NOT NULL DEFAULT false    -- 是否允許多選
- ends_at     DATETIME NULL                     -- NULL = 永不截止
- created_at  DATETIME NOT NULL

poll_options
- id         INTEGER PRIMARY KEY
- poll_id    INTEGER NOT NULL REFERENCES polls(id) ON DELETE CASCADE
- text       TEXT NOT NULL
- sort_order INTEGER NOT NULL DEFAULT 0

poll_votes
- id         INTEGER PRIMARY KEY
- poll_id    INTEGER NOT NULL REFERENCES polls(id) ON DELETE CASCADE
- option_id  INTEGER NOT NULL REFERENCES poll_options(id) ON DELETE CASCADE
- user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE
- created_at DATETIME NOT NULL
- UNIQUE(poll_id, option_id, user_id)
```

API：

```text
POST /api/forum/posts/:id/poll         -- 建立投票（隨發文建立）
GET  /api/forum/posts/:id/poll         -- 查看投票結果
POST /api/forum/posts/:id/poll/vote    -- 投票
```

規則：
- 投票截止後結果公開，不可再投。
- 是否可查看即時結果由 poll 設定控制（可隱藏到截止）。
- 刪文後 poll 同步刪除。

---

## 15.10 熱門文章 / 探索功能

### hot_score 計算

```text
posts（追加）
- hot_score  REAL NOT NULL DEFAULT 0.0
- last_active_at DATETIME NOT NULL   -- 最後一則回覆的時間
```

hot_score 計算公式（Hacker News 變形）：

```
hot_score = (reactions + comments * 2 + views * 0.1) / (age_hours + 2)^1.5
```

定期（每 15 分鐘）由 background job 更新。

API：

```text
GET /api/forum/posts?sort=hot        -- 熱門文章（依 hot_score）
GET /api/forum/posts?sort=new        -- 最新文章
GET /api/forum/posts?sort=top&period=week|month|all  -- 歷史高分
GET /api/forum/trending              -- 全站即時熱門（前 20 筆）
```

---

## 15.11 未讀追蹤

```text
user_read_states
- user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE
- board_id    INTEGER NOT NULL REFERENCES forum_boards(id) ON DELETE CASCADE
- last_read_at DATETIME NOT NULL
- PRIMARY KEY(user_id, board_id)
```

規則：
- 訪問 `/api/forum/boards/:id/posts` 時更新 `last_read_at`。
- 版區列表 API 回傳 `has_unread: true/false`。
- 未讀版區在前端顯示紅點標記（badge）。
- 清除未讀：`POST /api/forum/boards/:id/mark-read`。

---

## 15.12 成就徽章系統

```text
achievement_definitions
- id          INTEGER PRIMARY KEY
- key         TEXT NOT NULL UNIQUE   -- 'first_post' | 'trusted_member' | 'moderator' ...
- name        TEXT NOT NULL
- description TEXT NOT NULL
- icon        TEXT NOT NULL          -- emoji 或 icon slug
- condition_type TEXT NOT NULL       -- 'post_count' | 'reaction_count' | 'manual' | 'level_up'
- condition_value INTEGER NULL       -- 達成門檻數值
- unlocks_custom_title TEXT NULL     -- 解鎖的稱號，NULL = 無

user_achievements
- id             INTEGER PRIMARY KEY
- user_id        INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE
- achievement_id INTEGER NOT NULL REFERENCES achievement_definitions(id)
- granted_by     TEXT NULL           -- 'system' | admin username
- granted_at     DATETIME NOT NULL
- UNIQUE(user_id, achievement_id)
```

預設成就範例：

| key | 條件 | 說明 |
|-----|------|------|
| first_post | 發第 1 篇文章 | 首篇發文 |
| prolific | 發文 ≥ 100 篇 | 資深鄉民 |
| helpful | 累積按讚被給 ≥ 50 次 | 熱心助人 |
| trusted | member_level 升為 trusted | 信任會員 |
| mod_cap | 被任命版主 | 版務人員 |
| veteran | 加入滿 1 年 | 一年老鳥 |

API：

```text
GET /api/users/:id/achievements
GET /api/admin/achievements
POST /api/admin/users/:id/achievements   -- 手動頒發
```

---

## 15.13 草稿管理

v3 的 `posts.status` 有 `draft`，但無草稿管理 API。

API：

```text
GET    /api/forum/drafts          -- 我的草稿列表
POST   /api/forum/drafts          -- 建立草稿
PATCH  /api/forum/drafts/:id      -- 更新草稿（含自動儲存）
DELETE /api/forum/drafts/:id
POST   /api/forum/drafts/:id/publish  -- 從草稿發布
```

規則：
- 草稿只有作者可見。
- 前端每 30 秒自動儲存（autosave），避免意外關閉遺失內容。
- 最多保留 10 份草稿，超過時自動刪除最舊。

---

## 15.14 在線狀態

```text
user_online_states
- user_id      INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE
- last_seen_at DATETIME NOT NULL
- is_invisible BOOLEAN NOT NULL DEFAULT false
```

API：

```text
GET /api/online                   -- 目前在線人數與公開用戶列表（最後活躍 ≤ 15 分鐘）
```

規則：
- 每次 API 請求刷新 `last_seen_at`（throttle：每 60 秒最多寫一次）。
- `is_invisible = true` 的用戶不在在線列表顯示，但計入在線人數。
- guest 只顯示在線人數，不顯示列表。

---

## 15.15 通知偏好設定

v3 的 `notifications` 表已存在，但缺乏用戶控制通知類型的設定。

```text
notification_preferences
- user_id    INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE
- on_mention    BOOLEAN NOT NULL DEFAULT true
- on_reply      BOOLEAN NOT NULL DEFAULT true
- on_reaction   BOOLEAN NOT NULL DEFAULT true
- on_dm         BOOLEAN NOT NULL DEFAULT true
- on_follow     BOOLEAN NOT NULL DEFAULT true
- on_board_post BOOLEAN NOT NULL DEFAULT false
- on_moderation BOOLEAN NOT NULL DEFAULT true
- email_on_dm   BOOLEAN NOT NULL DEFAULT false
- email_on_mention BOOLEAN NOT NULL DEFAULT false
- updated_at   DATETIME NOT NULL
```

API：

```text
GET   /api/account/notification-preferences
PATCH /api/account/notification-preferences
```

---

## 15.16 前端體驗補充

### 深色模式 / 主題

```text
-- 儲存在 localStorage（不需後端 schema）
theme: 'light' | 'dark' | 'auto'
```

- CSS custom properties 控制主題色彩。
- `auto` 跟隨 `prefers-color-scheme`。
- 主題選擇儲存 localStorage，重新整理後維持。

### 手機版優先設計

- 所有現有頁面需確保 max-width: 768px 以下可操作。
- 底部導覽列（mobile nav bar）：首頁、版區、通知、個人。
- 浮動發文按鈕（FAB）。

### 富文字編輯器

- 支援 Markdown 格式（粗體、斜體、引用、程式碼區塊、列表）。
- 預覽模式（寫作時可即時切換）。
- 圖片拖曳上傳（觸發 attachments API）。
- @username 自動補全（輸入 @ 後彈出建議列表）。

---

## 15.18 新增 Schema 快速索引

| 表名 | 用途 |
|------|------|
| direct_messages | 站內信訊息 |
| dm_threads | 站內信對話串 |
| attachments | 附件 / 圖片 |
| post_reactions | 文章按讚 / 表情反應 |
| comment_reactions | 回覆按讚 |
| post_mentions | @提及記錄 |
| post_edit_history | 文章編輯歷史 |
| comment_edit_history | 回覆編輯歷史 |
| tags | 標籤定義 |
| post_tags | 文章標籤關聯 |
| polls | 投票 |
| poll_options | 投票選項 |
| poll_votes | 投票紀錄 |
| bookmarks | 文章收藏 |
| thread_subscriptions | 文章訂閱 |
| board_subscriptions | 版區訂閱 |
| user_follows | 追蹤用戶 |
| blocked_users | 封鎖名單 |
| user_read_states | 未讀追蹤 |
| achievement_definitions | 成就定義 |
| user_achievements | 用戶成就 |
| user_online_states | 在線狀態 |
| notification_preferences | 通知偏好 |
| posts_fts | 全文搜尋虛擬表 |

---

## 15.19 新增 API 快速索引（15.1–15.18 範圍）

| 路徑 | 說明 |
|------|------|
| GET/POST /api/dm/threads | 站內信對話串 |
| GET/POST /api/dm/threads/:uid/messages | 站內信訊息 |
| POST /api/attachments/upload | 附件上傳 |
| GET /api/users/:id/profile | 用戶個人主頁 |
| PATCH /api/account/profile | 修改個人資料 |
| POST /api/account/avatar | 更換頭像 |
| POST/DELETE /api/forum/posts/:id/reactions | 文章反應 |
| POST/DELETE /api/forum/comments/:id/reactions | 回覆反應 |
| GET /api/forum/posts/:id/history | 文章編輯歷史 |
| GET /api/search | 全站搜尋 |
| POST/DELETE /api/account/follows/:uid | 追蹤/取消追蹤 |
| POST/DELETE /api/account/blocks/:uid | 封鎖/解鎖 |
| POST/DELETE /api/forum/posts/:id/subscribe | 訂閱文章 |
| POST/DELETE /api/forum/boards/:id/subscribe | 訂閱版區 |
| POST/DELETE /api/bookmarks | 收藏 |
| POST /api/forum/posts/:id/poll | 建立投票 |
| POST /api/forum/posts/:id/poll/vote | 投票 |
| GET /api/forum/posts?sort=hot | 熱門文章 |
| GET /api/forum/trending | 即時熱門 |
| GET /api/forum/drafts | 草稿列表 |
| GET /api/online | 在線名單 |
| GET/PATCH /api/account/notification-preferences | 通知偏好 |
| GET /api/users/:id/achievements | 用戶成就 |
| GET /api/tags | 標籤列表 |
| GET /api/forum/tags/:slug/posts | 依標籤瀏覽 |

## 15.20 與主流論壇安全性及功能對標分析

> 本節以 eyny（伊莉）、PTT、DCard、Stack Overflow、Reddit 為對照基準，
> 識別 hackme_web 當前缺口，分為「安全性」、「權限管理」、「介面功能」三大類。
> 已存在於文件中的項目（Section 1–16、15.1–15.19）不再重複。

---

### 15.20.1 安全性缺口（對標主流論壇標配）

| 項目 | 現況 | eyny/PTT/DCard | 建議 |
|------|------|----------------|------|
| **CAPTCHA 機制** | ❌ 完全缺失 | eyny 註冊/登入有圖形驗證；PTT 連線需 Boyer 多層驗證 | 新增 `captcha_type` 欄位（`none`/`math`/`image`/`turnstile`），用於註冊/登入/高風險操作 |
| **暴力破解鎖定** | ⚠️ `login_ip_lock_enabled` 只限制同 IP 登入不同帳號，未限制同帳號多密碼嘗試 | DCard 有帳號鎖定（5 次錯誤）；Stack Overflow 有 account lockout | 新增 `failed_login_attempts` + `locked_until` 欄位，達阈值鎖定並發 email 通知 |
| **密碼強度檢查** | ⚠️ 有 `password_policy_enabled`，但無實際強度評分機制 | Reddit/Stack Overflow 強制 8+ 字、數字、特殊字元 | 加入 `password_strength_score`（0–4），前端即時回饋、後端強制達到門檻 |
| **登入裝置管理** | ❌ 無 | DCard、Stack Overflow 有「活躍裝置」列表與遠端登出 | 新增 `user_sessions.device_info` + `user_sessions.user_agent`，API：`GET /api/account/sessions`、`DELETE /api/account/sessions/:id` |
| **Session 固定防護** | ⚠️ 只在密碼重設時清除所有 session | 主流論壇標配 | 更換密碼後強制重新登入（invalidate 所有舊 session token） |
| **Magic Link（無密碼登入）** | ❌ 無 | Auth0/reddit 可用 email magic link | 新增 `/api/auth/magic-link`（寄送一次性連結），支援不想設密碼的用戶 |
| **資料匯出（GDPR 相容）** | ❌ 無 | DCard（GDPR）、Stack Overflow 有「下載我的資料」 | 新增 `data_export_requests` schema，background job 生成 ZIP（posts/comments/DM/個人資料），email 通知下載連結 |
| **帳號永久刪除** | ⚌ 軟刪除（`is_deleted`）但無彻底刪除流程 | GDPR 要求；Stack Overflow 有「Delete Account」 | 新增 `account_deletion_requests` + 30 天 grace period，期滿物理刪除（含所有個資） |
| **生物特徵驗證（WebAuthn）** | ❌ 無 | 進階安全選項 | 新增 `user_webauthn_credentials` 表，支援 FIDO2/WebAuthn 作為 2FA 替代方案 |
| **IP 登入異常通知** | ❌ 無 | DCard、Steam 有新城市/IP 登入通知 | 新增 `login_location` 記錄，登入時比對，異常觸發 email 通知（但不禁用，僅通知） |

**Schema 建議（CAPTCHA）：**

```text
captchas
- id          INTEGER PRIMARY KEY
- session_key TEXT NOT NULL          -- 綁定 client session
- challenge   TEXT NOT NULL           -- 驗證問題/答案 hash
- answer_hash TEXT NOT NULL            -- SHA256 of answer
- expires_at  DATETIME NOT NULL
- used        BOOLEAN NOT NULL DEFAULT false
```

```text
user_sessions（追加欄位）
- device_info    TEXT NULL            -- JSON: {browser, os, device}
- user_agent     TEXT NULL
- ip_country     TEXT NULL            -- GeoIP 查詢結果
- last_activity_at DATETIME NOT NULL  -- 更新最後活躍時間
```

```text
failed_login_attempts
- id          INTEGER PRIMARY KEY
- user_id     INTEGER NOT NULL REFERENCES users(id)
- ip_hash     TEXT NOT NULL           -- 保護隱私，只存 hash
- attempted_at DATETIME NOT NULL
- success     BOOLEAN NOT NULL
```

```text
login_locations
- id          INTEGER PRIMARY KEY
- user_id     INTEGER NOT NULL REFERENCES users(id)
- ip_hash     TEXT NOT NULL
- country     TEXT NULL
- city        TEXT NULL
- login_at    DATETIME NOT NULL
- isSuspicious BOOLEAN NOT NULL DEFAULT false
```

```text
data_export_requests
- id          INTEGER PRIMARY KEY
- user_id     INTEGER NOT NULL REFERENCES users(id)
- status      TEXT NOT NULL           -- 'pending'|'processing'|'ready'|'expired'
- file_path   TEXT NULL
- requested_at DATETIME NOT NULL
- expires_at  DATETIME NOT NULL
```

```text
account_deletion_requests
- id          INTEGER PRIMARY KEY
- user_id     INTEGER NOT NULL REFERENCES users(id)
- status      TEXT NOT NULL           -- 'pending'|'grace_period'|'completed'|'cancelled'
- requested_at DATETIME NOT NULL
- scheduled_at DATETIME NOT NULL       -- grace period 結束日（+30天）
- completed_at DATETIME NULL
```

```text
user_webauthn_credentials
- id              INTEGER PRIMARY KEY
- user_id         INTEGER NOT NULL REFERENCES users(id)
- credential_id   TEXT NOT NULL UNIQUE  -- WebAuthn credential ID
- public_key      TEXT NOT NULL
- device_name     TEXT NULL
- created_at      DATETIME NOT NULL
- last_used_at    DATETIME NULL
```

**API 新增：**

```text
GET  /api/captcha/new              -- 產生新 CAPTCHA
POST /api/captcha/verify           -- 驗證 CAPTCHA
POST /api/auth/magic-link          -- 發送 Magic Link
GET  /api/account/sessions         -- 列出活躍 sessions
DELETE /api/account/sessions/:id   -- 登出指定裝置
POST /api/account/sessions/logout-all -- 登出所有裝置
GET  /api/account/devices           -- 登入裝置列表
POST /api/account/data-export      -- 申請資料匯出
GET  /api/account/data-export/:id  -- 下載匯出檔案
POST /api/account/delete           -- 申請帳號刪除
DELETE /api/account/sessions/:id/permanent -- 遠端終止盜用 session
POST /api/account/webauthn/register     -- 註冊 WebAuthn
POST /api/account/webauthn/authenticate -- WebAuthn 驗證
```

**Session 固定防護（實作要點）：**
- 每次登入時重設 `session_token`（廢除舊 token、發新 token）
- 密碼變更時：invalidate 所有 session（`sessions.is_active = false`），強制重新登入
- Session 綁定 IP + User-Agent 指紋，異常時觸發 email 通知（不禁用）

---

### 15.20.2 權限管理缺口（對標 Moderator Tools 標配）

| 項目 | 現況 | eyny/PTT/Stack Overflow | 建議 |
|------|------|------------------------|------|
| **文章類型（類型系統）** | ❌ `posts.status` 只有 `published/draft/hidden`，無文章類型區分 | PTT 有 [公告]、[協助]、[心得]、[情報]、[認證]；Stack Overflow 有 Question/Answer/Wiki | 新增 `post_type`：`normal`/`announcement`/`question`/`howto`/`review`/`nsfw`，不同類型有不同 UI 標記和功能限制 |
| **置頂（Sticky Post）** | ⚠️ 只有版主可置頂，但無 API 文件化 | eyny 版主可「置頂」；Stack Overflow 有「pin」 | 在 `posts` 新增 `is_sticky BOOLEAN DEFAULT false`，API：`POST /api/forum/posts/:id/sticky`（限 moderator+） |
| **鎖文（Lock）** | ⚠️ `status='hidden'` 可隱藏但非正式鎖文 | PTT 版主可 LOCK 文章（不可回覆） | 新增 `is_locked BOOLEAN DEFAULT false`，鎖文後不可再回覆（`POST /api/forum/comments` 回 403） |
| **精華文（Curated/Pinned）** | ❌ 無 | PTT 有 m 文（精華）；Stack Overflow 有 Community Wiki | 新增 `is_curated BOOLEAN DEFAULT false`，精華文出現在版區頂部或精華區 |
| **版主動作日誌** | ⚌ `moderation_history` 有少部分，但 moderator 自己操作的記錄不足 | eyny 版主操作有私人記錄 | `moderation_actions` 獨立表，記錄 moderator 每一個 action（含自動 mod：spam 自動刪除），可audit |
| **版主評論（Mod Note）** | ❌ 無 | Reddit、Discord 有 Mod Note（僅 moderator 可見） | 新增 `post_mod_notes` / `user_mod_notes`，限 moderator+ 可見，普通會員看不見 |
| **使用者積分/威望看不見具體來源** | ⚠️ 有 `points`/`reputation`，但無明細 | Stack Overflow 威望有 +10/-2 明細；Reddit 有 karma breakdown | 新增 `reputation_events` 表，記錄每次威望變化的原因（+$V: 被按讚；-$W: 被檢舉成功扣分） |
| **舉報功能（Bounty）** | ❌ 無 | Stack Overflow 有賞金（自訂懸賞回答）；Reddit 有 Award | 新增 `post_bounties`：提問者可用積分懸賞，版主可將問答標記為 bounty，時間到了最高讚回答獲賞金 |
| **維基文章（Wiki Post）** | ❌ 無 | PTT 部分板有 Wiki；Stack Overflow 有 Community Wiki | 新增 `is_wiki BOOLEAN DEFAULT false`，Wiki 文章可由多人編輯（所有 editor 共同作者），編輯歷史完整保留 |
| **權限繼承與委託** | ❌ 無 | Discord 有「角色繼承」 | `moderator_permissions` 可設定：版主可委託部分權限（如：只能刪文、不能踢人） |
| **舉報處理工作流（Claim）** | ⚌ `moderation_proposals` 有提案，但無人認領機制 | Reddit/Discord 版主可「claim」舉報單，claim 後其他人看不見 | 新增 `moderation_reports.claimed_by INTEGER REFERENCES users(id)`，`claimed_at`，避免多人重複處理 |

**Schema 建議（文章類型與版主工具）：**

```text
posts（追加欄位）
- post_type      TEXT NOT NULL DEFAULT 'normal'  -- 'normal'|'announcement'|'question'|'howto'|'review'|'nsfw'
- is_sticky      BOOLEAN NOT NULL DEFAULT false
- is_locked      BOOLEAN NOT NULL DEFAULT false
- is_curated     BOOLEAN NOT NULL DEFAULT false
- is_wiki        BOOLEAN NOT NULL DEFAULT false
- wiki_contributors TEXT NOT NULL DEFAULT ''    -- JSON array of user_ids
```

```text
moderation_actions
- id           INTEGER PRIMARY KEY
- moderator_id INTEGER NOT NULL REFERENCES users(id)
- action_type  TEXT NOT NULL          -- 'hide'|'delete'|'lock'|'sticky'|'curate'|'warn'|'ban'
- target_type  TEXT NOT NULL          -- 'post'|'comment'|'user'|'attachment'
- target_id    INTEGER NOT NULL
- reason       TEXT NULL
- is_auto      BOOLEAN NOT NULL DEFAULT false   -- 系統自動執行的 action
- created_at   DATETIME NOT NULL
```

```text
user_mod_notes
- id          INTEGER PRIMARY KEY
- moderator_id INTEGER NOT NULL REFERENCES users(id)
- user_id     INTEGER NOT NULL REFERENCES users(id)
- note        TEXT NOT NULL
- created_at  DATETIME NOT NULL
```

```text
reputation_events
- id            INTEGER PRIMARY KEY
- user_id       INTEGER NOT NULL REFERENCES users(id)
- delta         INTEGER NOT NULL            -- 正或負的變化量
- reason        TEXT NOT NULL                -- 'post_upvoted'|'post_downvoted'|'comment_upvoted'|'answer_accepted'|'report_sustained'|'report_rejected'|'manual_adjustment'
- source_user_id INTEGER NULL                -- 觸發者（如：誰按了你讚）
- source_post_id INTEGER NULL                -- 關聯文章
- created_at    DATETIME NOT NULL
```

```text
post_bounties
- id         INTEGER PRIMARY KEY
- post_id    INTEGER NOT NULL UNIQUE REFERENCES posts(id) ON DELETE CASCADE
- user_id    INTEGER NOT NULL REFERENCES users(id) -- 發起者（用自己的積分）
- amount     INTEGER NOT NULL               -- 懸賞積分數量
- status     TEXT NOT NULL DEFAULT 'active'  -- 'active'|'awarded'|'expired'|'cancelled'
- ends_at    DATETIME NOT NULL
- awarded_to_comment_id INTEGER NULL REFERENCES comments(id)
- created_at DATETIME NOT NULL
```

```text
moderation_reports（追加欄位）
- claimed_by  INTEGER NULL REFERENCES users(id)
- claimed_at  DATETIME NULL
```

```text
forum_boards（追加欄位）
- moderator_notes TEXT NULL   -- 僅 moderator+ 可見的版區內部備註
```

```text
post_wiki_edits
- id          INTEGER PRIMARY KEY
- post_id     INTEGER NOT NULL REFERENCES posts(id) ON DELETE CASCADE
- editor_id   INTEGER NOT NULL REFERENCES users(id)
- old_body    TEXT NOT NULL
- new_body    TEXT NOT NULL
- edit_reason TEXT NULL
- is_minor    BOOLEAN NOT NULL DEFAULT false
- created_at  DATETIME NOT NULL
```

**API 新增：**

```text
PATCH /api/forum/posts/:id/type          -- 変更文章類型（moderator+）
POST  /api/forum/posts/:id/sticky        -- 置頂/取消置頂（moderator+）
POST  /api/forum/posts/:id/lock          -- 鎖文（moderator+）
POST  /api/forum/posts/:id/curate       -- 加入精華（moderator+）
POST  /api/forum/posts/:id/wiki/enable   -- 開啟維基模式（author+）
PATCH /api/forum/posts/:id/wiki          -- 維基文章編輯（任何貢獻者）
GET   /api/forum/posts/:id/wiki/history  -- 維基編輯歷史
POST  /api/forum/posts/:id/bounty        -- 發起懸賞（積分）
POST  /api/forum/posts/:id/bounty/award  -- 版主發放賞金（moderator+）
POST  /api/forum/comments/:id/accept      -- 提問者接受為最佳解答（OP only）

GET   /api/admin/moderation-actions       -- 版主操作日誌（admin+）
GET   /api/admin/mod-notes/:user_id       -- 查看用戶版主備註（moderator+）
POST  /api/admin/mod-notes/:user_id       -- 新增版主備註（moderator+）

GET   /api/account/reputation/history     -- 威望變化明細
GET   /api/account/reputation/summary    -- 威望總結（本月/本年/總計）

POST  /api/forum/reports/:id/claim        -- 認領舉報單（moderator+）
POST  /api/forum/reports/:id/unclaim      -- 取消認領（moderator+）
```

---

### 15.20.3 介面功能缺口（對標主流論壇 UX 標配）

| 項目 | 現況 | eyny/PTT/DCard | 建議 |
|------|------|----------------|------|
| **即時通知（WebSocket）** | ⚌ polling 方式，前端每 30 秒輪詢 | DCard、Discord 有 WebSocket 推送 | 新增 `notifications` WebSocket endpoint，支援即時 notification 推送 |
| **引用層次視覺化** | ⚌ `parent_comment_id` 已存在但前端無縮排顯示 | Reddit 有 comment collapse/expand；PTT 有推文樓層引用 | 前端 Comment 元件加入 `margin-left` 縮排（遞迴 3 層後折疊），以及「展開回覆」功能 |
| **即時聊天（Live Chat）** | ❌ 無 | Discord DM 即時；部分論壇有即時客服 | 可選 Phase 18：建立 `live_chatrooms` schema，基於 WebSocket 的多人聊天室（僅登入可進） |
| **「瀏覽過的文章」歷史** | ❌ 無 | DCard 有瀏覽紀錄 | 新增 `user_browse_history`（可選，不永久儲存，僅用於「看過」標記或推薦），或者用 Redis 限時儲存 |
| **Email 通知摘要** | ⚌ `notification_preferences` 有開關但無實際寄送機制 | DCard/Stack Overflow 有每日/每週 Email 摘要 | Background job 彙整未讀 notification，寄送 Email摘要（可設定頻率：即時/每日/每週） |
| **文章修訂請求（Edit Suggestion）** | ❌ 無（Wiki 模式才有共同編輯） | Stack Overflow 有 Edit Suggestion（任何人可提，修後由 OP/ moderator 核准） | 新增 `post_edit_suggestions`，非 Wiki 文章也可讓他人提修改建議，OP/moderator 可 accept/reject |
| **「常見問題」自動識別** | ❌ 無 | Stack Overflow 有「相似問題」提示 | 發文時 Backend 對比標題與 FTS 資料庫，彈出「這些問題可能相關」建議 |
| **公告強制閱讀** | ⚌ `post_type='announcement'` 有但無強制閱讀追蹤 | 部分企業內部論壇有「我已閱讀」按鈕 | 新增 `post_read_receipts`（公告才有），版主可看誰已讀/未讀 |
| **懶加載（Infinite Scroll）** | ⚌ 普通分頁，無無窮下滑 | DCard、Reddit 皆為 infinite scroll | 將文章列表 / 回覆列表改為 cursor-based 分頁 + 前端 infinite scroll（Intersection Observer） |
| **Markdown 儲存/預覽** | ⚌ Section 15.16 有提到但無 Schema 支援 | - | 儲存原始 Markdown（含 raw body），編輯時直接渲染 Markdown，前端雙視圖（寫作/預覽） |
| **Emoji 反应图示** | ⚌ `post_reactions` 有，但只有文字 label | Discord/Telegram 有豐富 Emoji | reaction 欄位支援 emoji 字串（如 👍❤️🎉），前端顯示實際 Emoji 而非文字 |
| **多螢幕適配** | ⚌ Section 15.16 有深色模式但無適配量化標準 | - | 制定響應式斷點（375px/768px/1024px/1440px），各斷點有對應截圖驗收 |

**Schema 建議（即時通知、文章修訂）：**

```text
notifications（追加欄位）
- is_read       BOOLEAN NOT NULL DEFAULT false   -- 現有 is_read，需確認是否已覆蓋
```

```text
post_read_receipts
- id          INTEGER PRIMARY KEY
- post_id     INTEGER NOT NULL REFERENCES posts(id) ON DELETE CASCADE
- user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE
- read_at     DATETIME NOT NULL
- UNIQUE(post_id, user_id)
```

```text
post_edit_suggestions
- id          INTEGER PRIMARY KEY
- post_id     INTEGER NOT NULL REFERENCES posts(id) ON DELETE CASCADE
- suggester_id INTEGER NOT NULL REFERENCES users(id)
- suggested_title TEXT NULL
- suggested_body  TEXT NOT NULL
- status      TEXT NOT NULL DEFAULT 'pending'  -- 'pending'|'accepted'|'rejected'
- reviewer_id INTEGER NULL REFERENCES users(id)
- review_note TEXT NULL
- created_at  DATETIME NOT NULL
- reviewed_at DATETIME NULL
```

```text
email_digest_subscriptions
- id           INTEGER PRIMARY KEY
- user_id      INTEGER NOT NULL UNIQUE REFERENCES users(id)
- frequency    TEXT NOT NULL DEFAULT 'weekly'  -- 'instant'|'daily'|'weekly'
- last_sent_at DATETIME NULL
- created_at   DATETIME NOT NULL
```

**API 新增：**

```text
WebSocket /ws/notifications              -- 即時通知通道（需 auth token）
GET  /api/notifications?cursor=<after>&limit=20  -- cursor 分頁
POST /api/notifications/mark-all-read   -- 全部標為已讀

POST /api/forum/posts/:id/read-receipt  -- 公告閱讀確認（POST，視為「我已讀」）

GET  /api/forum/posts/:id/edit-suggestions
POST /api/forum/posts/:id/edit-suggestions    -- 提交編輯建議（任何人）
PATCH /api/forum/posts/:id/edit-suggestions/:sid -- OP/moderator accept/reject

POST /api/forum/posts/:id/similar        -- 發文時查詢相似文章（POST title，回傳列表）
GET  /api/forum/posts?cursor=<after>&limit=20  -- cursor 分頁（替換 offset）

GET  /api/account/email-digest           -- 查詢目前的 email 摘要設定
PATCH /api/account/email-digest          -- 更新頻率（instant/daily/weekly）
```

---

### 15.20.4 缺口快速索引（15.20 範圍）

| 類別 | 項目 | 檔次 |
|------|------|------|
| 安全 | CAPTCHA 機制 | ❌ 缺失 |
| 安全 | 暴力破解鎖定（帳號層級） | ⚠️ 不完整 |
| 安全 | 密碼強度評分 | ⚠️ 不完整 |
| 安全 | 登入裝置管理 / 遠端登出 | ❌ 缺失 |
| 安全 | Session 固定防護 | ⚠️ 不完整 |
| 安全 | Magic Link 無密碼登入 | ❌ 缺失 |
| 安全 | 資料匯出（GDPR） | ❌ 缺失 |
| 安全 | 帳號永久刪除（30天猶豫期） | ❌ 缺失 |
| 安全 | WebAuthn 生物特徵驗證 | ❌ 缺失 |
| 安全 | IP 登入異常通知 | ❌ 缺失 |
| 權限 | 文章類型系統 | ❌ 缺失 |
| 權限 | 置頂 / 鎖文 / 精華文 | ⚠️ 不完整 |
| 權限 | 版主動作日誌 | ⚌ 不完整 |
| 權限 | Mod Note（隱藏備註） | ❌ 缺失 |
| 權限 | 威望明細（reputation_events） | ❌ 缺失 |
| 權限 | 賞金懸賞系統 | ❌ 缺失 |
| 權限 | Wiki 共同編輯文章 | ❌ 缺失 |
| 權限 | 版主權限委託 | ❌ 缺失 |
| 權限 | 舉報處理 Claim 機制 | ⚌ 不完整 |
| 介面 | WebSocket 即時通知 | ❌ 缺失 |
| 介面 | 回覆引用層次視覺化 | ⚌ 不完整 |
| 介面 | 即時聊天（Live Chat） | ❌ 缺失（可選 Phase 18） |
| 介面 | 瀏覽過的文章歷史 | ❌ 缺失 |
| 介面 | Email 通知摘要 | ❌ 缺失 |
| 介面 | 文章修訂請求（Edit Suggestion） | ❌ 缺失 |
| 介面 | 相似問題自動提示 | ❌ 缺失 |
| 介面 | 公告強制閱讀確認 | ❌ 缺失 |
| 介面 | Infinite Scroll（cursor 分頁） | ⚌ 不完整 |
| 介面 | Markdown 原始格式儲存 | ⚌ 不完整 |
| 介面 | Emoji reaction 顯示 | ⚌ 不完整 |
| 介面 | 多螢幕響應式斷點標準 | ⚌ 不完整 |

---

# 16. 前端架構與 UI 設計規範（UI_improve 整合）

> 本章整合 UI_improve.md 的完整內容。
> 現有問題診斷：UI 不是「不好看」，而是**沒有結構**——layout、page、component 混在一起，
> API call 散落各處，CSS inline style 到處亂寫。目標是重構為有層次的論壇系統 UI。

---

## 16.1 三層架構原則（強制執行）

```
Layout 層（框架）→ Page 層（頁面）→ Component 層（元件）
```

**禁止事項：**

- ❌ 在 Page 裡寫 layout 結構
- ❌ 在 Component 裡直接呼叫 API（fetch/axios）
- ❌ inline style 散落各處
- ❌ `!important` 濫用
- ❌ 每頁自己寫獨立 CSS

---

## 16.2 Layout 拆分

建立三套獨立 layout：

```text
layouts/
  MainLayout      → 一般會員 / 論壇瀏覽
  AdminLayout     → admin / root 後台
  AuthLayout      → 登入 / 註冊 / 忘記密碼
```

### MainLayout 結構

```
<Header />
<NavBar />
<div class="container">
  <SidebarLeft />    ← 版區樹
  <MainContent />    ← 頁面主體
  <SidebarRight />   ← 用戶資訊 / 熱門 / 狀態燈
</div>
<Footer />
```

### AdminLayout 結構

```
<AdminHeader />      ← logo + mode badge + 用戶資訊
<AdminSidebar />     ← 管理功能導覽
<AdminContent />     ← 頁面主體
```

### AuthLayout 結構

```
<AuthCard />         ← 居中卡片，無 sidebar
```

---

## 16.3 Header 設計

| 區塊 | 內容 |
|------|------|
| 左側 | Logo（hackme_web）|
| 中間 | 搜尋框（全站搜尋，呼叫 `/api/search`）|
| 右側 | server mode badge + 頭像 + 會員等級 + 通知鈴 |

**Server mode badge 樣式：**

```
[PRE_PROD]    → 綠底白字
[TEST]        → 黃底黑字
[SUPERWEAK]   → 紅底白字 + 閃爍動畫
```

---

## 16.4 NavBar 設計

```
首頁 ／ 論壇 ／ 追蹤動態 ／ 安全中心（admin+）／ 管理後台（admin+）／ 健康狀態（root）
```

- 依角色動態顯示項目，不可見的項目不渲染（前端隱藏 ≠ 後端授權）。
- active 頁面底線高亮。

---

## 16.5 SidebarLeft — 版區樹（類 eyny）

```
📁 技術討論
  ├─ AI 研究
  ├─ 程式設計
  └─ 開源工具
📁 資訊安全
  ├─ 滲透測試
  └─ 漏洞分析
📁 閒聊水區
```

- 資料來自 `/api/forum/categories`，可折疊。
- 各子版顯示未讀紅點（整合 Section 15.11 未讀追蹤）。
- 版主名稱顯示在版區名旁（hover tooltip）。

---

## 16.6 SidebarRight — 資訊欄

```
┌─────────────────────┐
│ [頭像] username      │  ← UserCard
│ 等級：trusted VIP   │
│ 積分：1234  威望：89 │
├─────────────────────┤
│ 最近通知（3 則）      │  ← 最新 3 筆 notifications
├─────────────────────┤
│ 熱門文章（5 篇）      │  ← /api/forum/trending
├─────────────────────┤
│ 🟢 準上線燈          │  ← HealthLight readiness
│ 🟢 異常燈            │  ← HealthLight anomaly
└─────────────────────┘
```

---

## 16.7 Page 檔案結構

```text
pages/
  forum/
    index          → 版區列表（BoardList）
    board/[id]     → 子版文章列表（PostList）
    post/[id]      → 文章詳情（PostDetail + CommentList）
    new-post       → 發文（RichTextEditor）
    search         → 搜尋結果
    trending       → 熱門文章
    drafts         → 草稿列表
    tags/[slug]    → 依標籤瀏覽
  account/
    profile        → 個人主頁
    settings       → 帳號設定
    security       → 密碼 / 2FA / 登入紀錄
    notifications  → 通知列表
    bookmarks      → 收藏
    follows        → 追蹤 / 粉絲
    dm/            → 站內信收件匣
    dm/[user_id]   → 站內信對話
    achievements   → 成就徽章
  admin/
    users          → 用戶管理
    moderation     → 處分提案
    reports        → 檢舉
    appeals        → 申訴
    forum          → 版區管理
    security       → 安全事件
    audit-logs     → Audit log
    member-levels  → 等級規則
    permission-matrix → 權限矩陣
    achievements   → 成就管理
  root/
    server-mode    → 模式切換
    security-settings → 安全設定
    danger-zone    → Danger Zone
    snapshots      → 快照管理
    health         → 健康監控
    integrity      → 完整性檢查
  auth/
    login
    register
    forgot-password
    reset-password
```

---

## 16.8 Component 元件規範

### Forum 元件

```text
components/forum/
  BoardList        → 版區列表（含未讀紅點）
  BoardCard        → 單一版區卡片
  PostList         → 文章列表
  PostCard         → 文章摘要卡（標題 / 作者 / 時間 / 反應數 / 回覆數 / 瀏覽數）
  PostDetail       → 文章全文（含編輯歷史入口）
  CommentList      → 回覆列表（支援巢狀引用）
  CommentItem      → 單則回覆（含引用區塊 / @提及 / 反應）
  ReactionBar      → 按讚 / 表情反應列
  PollWidget       → 投票元件
  TagList          → 標籤列
  RichTextEditor   → Markdown 編輯器（含圖片上傳、@補全）
  SearchBar        → 搜尋框（含 debounce）
  SearchResults    → 搜尋結果列表
```

### User 元件

```text
components/user/
  UserCard         → 用戶卡片（頭像 / username / 等級 / 積分）
  UserAvatar       → 頭像（fallback 首字母）
  UserBadge        → 會員等級 badge（顏色對應 member_level）
  AchievementBadge → 成就徽章
  OnlineIndicator  → 在線狀態綠點
```

### Admin 元件

```text
components/admin/
  ProposalCard     → 處分提案卡（含投票進度條）
  VotePanel        → 投票按鈕組（approve / reject + 理由）
  AuditLogTable    → Audit log 表格（含 hash chain 狀態）
  ReportCard       → 檢舉卡片
  UserStatusBadge  → 帳號狀態 badge（active / muted / suspended...）
```


### Storage 與相簿元件
```text
components/storage/
  StorageQuotaBar   → 配額使用條（含 warning / full 顏色）
  FileList          → 檔案列表（支援 grid / list view 切換）
  FileCard          → 單一檔案卡片（圖片縮圖 / 名稱 / 大小 / 操作）
  FolderTree        → 資料夾樹狀導航（遞迴支援）
  TrashList         → 回收筒列表（含到期倒計時）
  UploadZone        → 拖曳上傳區（含進度條 / 配額不足提示）
  UploadButton      → 點擊上傳按鈕（支援多選）
  FilePreviewModal  → 檔案預覽（含圖片燈箱 / PDF 嵌入 / 影片播放）
  FileContextMenu   → 右鍵選單（重新命名 / 移動 / 下載 / 刪除）
  BatchActionBar    → 批次操作列（批次刪除 / 批次移動）

components/album/
  AlbumCard         → 相簿卡片（封面圖 / 名稱 / 照片數 / 公開狀態）
  AlbumGrid         → 相簿網格佈局（響應式 1-4 欄）
  AlbumDetail       → 相簿詳情（照片牆 + 燈箱）
  AlbumPhotoGrid    → 照片牆（masonry / 支援燈箱放大）
  PhotoLightbox     → 燈箱放大檢視（左右切換 / 縮圖列）
  AlbumShareModal   → 分享設定 modal（開關 / 密碼 / 連結複製）
  AlbumEditor       → 相簿建立/編輯表單
  AlbumFilePicker   → 從 storage 選擇照片加入相簿
  SharedAlbumView   → 公開/密碼分享相簿視圖（無需登入可看）
```

### Security / System 元件

```text
components/security/
  HealthLight      → 狀態燈（readiness / anomaly，green / yellow / red）
  ModeIndicator    → Server mode badge（含閃爍邏輯）
  SecurityEventList → 安全事件列表
  HashChainStatus  → Audit log hash chain 完整性指示
```

### 通用元件

```text
components/common/
  Modal            → 通用 modal（二次確認）
  ConfirmDialog    → 高風險操作確認（含 confirm text 輸入）
  LoadingSpinner   → 載入中
  ErrorBanner      → 錯誤訊息
  Pagination       → 分頁
  Toast            → 短暫通知（操作成功 / 失敗）
  EmptyState       → 空資料佔位
  InfiniteScroll   → 無限滾動（可選替代 Pagination）
```

---

## 16.9 顏色語意系統

| 語意 | 顏色 | 用途 |
|------|------|------|
| 正常 / 成功 | 綠（#22c55e）| pre_production、操作成功、在線 |
| 警告 | 黃（#eab308）| test mode、yellow health light |
| 危險 / 錯誤 | 紅（#ef4444）| superweak、error、Danger Zone |
| 一般操作 | 藍（#3b82f6）| 按鈕、連結、一般 badge |
| 停用 | 灰（#9ca3af）| disabled 按鈕、已過期 |
| 管理員 | 紫（#8b5cf6）| admin badge、proposal |
| root | 橙（#f97316）| root badge、高風險操作 |

---

## 16.10 CSS / Style 規範

**技術選擇**：TailwindCSS（優先）或 CSS Modules

**標準間距**（Tailwind spacing scale）：

```
p-2 (8px) / p-3 (12px) / p-4 (16px) / p-6 (24px)
gap-4 為預設 flex/grid 間距
```

**卡片風格（論壇核心元件）：**

```css
/* 卡片基底 */
background: white;
border: 1px solid #e5e7eb;   /* gray-200 */
border-radius: 8px;
box-shadow: 0 1px 3px rgba(0,0,0,0.1);
transition: box-shadow 0.15s;

/* hover */
box-shadow: 0 4px 6px rgba(0,0,0,0.1);
border-color: #93c5fd;       /* blue-300 */
```

**深色模式**（CSS custom properties）：

```css
:root { --bg: #ffffff; --text: #111827; --border: #e5e7eb; }
[data-theme="dark"] { --bg: #1f2937; --text: #f9fafb; --border: #374151; }
```

---

## 16.11 資料流架構

### API Service 分層

```text
services/
  authService      → login / logout / me / forgot / reset
  forumService     → categories / boards / posts / comments
  userService      → profile / follow / block / bookmark / dm
  adminService     → proposals / reports / appeals / audit-logs
  securityService  → events / health / mode / snapshots
  searchService    → search / trending
```

每個 service 只負責 API 呼叫，不含業務邏輯。

### 狀態管理建議

```
React Query   → 伺服器狀態（posts、notifications、health）
Zustand       → 全域 UI 狀態（currentUser、theme、serverMode）
```

**禁止**：Component 直接 `fetch()` 或 `axios.get()`。

### 全域狀態（Zustand store）

```js
{
  currentUser: null,        // GET /api/me
  serverMode: 'test',       // 從 API header X-Hackme-Web-Mode
  theme: 'light',           // localStorage
  unreadCount: 0,           // GET /api/notifications (unread count)
  readinessLight: 'green',  // GET /api/health/readiness
  anomalyLight: 'green',    // GET /api/health/anomaly
}
```

---

## 16.12 UX 行為規範

| 行為 | 規範 |
|------|------|
| 分頁 | 每頁 20 筆，URL query `?page=n`，支援鍵盤上下頁 |
| Sticky Header | 頁面捲動時 Header 固定頂部 |
| Hover 摘要 | PostCard hover 顯示前 200 字預覽（tooltip 或 popover）|
| 回覆樓層 | CommentItem 顯示 #1、#2…樓層號，可點擊 quote |
| 快速編輯 | 作者發文後 30 分鐘內可 inline 編輯（不離開頁面）|
| Loading 狀態 | 所有非同步操作顯示 LoadingSpinner 或 skeleton |
| Error 狀態 | API 失敗顯示 ErrorBanner（含 retry 按鈕）|
| 空資料 | 顯示 EmptyState 元件，不顯示空白頁 |
| 操作回饋 | 所有 POST/PATCH/DELETE 操作完成後顯示 Toast |
| 二次確認 | 高風險操作（刪除 / 停權 / reset）必須 ConfirmDialog |

---

## 16.13 Danger Zone UI 規範

```
┌──────────────────────────────────┐
│  ⚠ DANGER ZONE                  │  ← 紅色頁首
│  以下操作不可逆，請謹慎執行        │
├──────────────────────────────────┤
│  [RESET SERVER]                  │
│  輸入確認文字：RESET HACKME_WEB  │
│  原因：____________              │
│  ⚠ 按下後立即清除所有資料         │
│  [確認重置]  ← 輸入正確才可點     │
├──────────────────────────────────┤
│  [RESTORE SNAPSHOT]              │
│  選擇快照：v20260427_120000 ▼    │
│  確認文字：RESTORE               │
│  [確認還原]                       │
├──────────────────────────────────┤
│  [ENABLE SUPERWEAK MODE]         │
│  目前快照：v20260427_120000       │
│  確認文字：ENABLE SUPERWEAK       │
│  [進入沙盒模式]                   │
└──────────────────────────────────┘
```

所有 Danger Zone 按鈕：
- 預設為 disabled
- 輸入正確 confirm_text 才啟用（前端 + 後端雙重驗證）
- 點擊後顯示最終 Modal 二次確認

---

## 16.14 Proposal 投票 UI

```
┌──────────────────────────────────┐
│  [Proposal #12]  ─ pending       │
│  目標：user123                   │
│  操作：suspend（停權 7 天）       │
│  提案人：admin_alice             │
│  原因：多次騷擾其他用戶           │
├──────────────────────────────────┤
│  票數進度：██████░░  2 / 3       │
│  👍 approve (2)  👎 reject (0)   │
├──────────────────────────────────┤
│  理由：_______________           │
│  [投 approve]  [投 reject]       │
│  （已投票者顯示：您已投 approve） │
└──────────────────────────────────┘
```

---

## 16.15 UI Phase 補充（Phase 16）

### Phase 16：UI 全面重構

**分支名稱**：`feature/ui-forum-layout`

目標（依序執行）：

1. 刪除現有混亂 layout，建立 MainLayout / AdminLayout / AuthLayout
2. 重構 Header（搜尋框、mode badge、通知鈴）
3. 建立 SidebarLeft（版區樹，整合未讀紅點）
4. 建立 SidebarRight（UserCard、HealthLight、熱門文章）
5. 將所有 forum 頁面套入 MainLayout
6. 將所有 admin/root 頁面套入 AdminLayout
7. 建立通用 Component 庫（Modal、Toast、LoadingSpinner、EmptyState、Pagination）
8. 所有列表改為 PostCard / BoardCard 卡片元件
9. 所有高風險操作加入 ConfirmDialog
10. 所有操作加入 loading / error / success 狀態
11. 建立 services/ 分層，移除 component 直接 fetch
12. 導入 Zustand 管理全域狀態（user / theme / serverMode）
13. 實作深色模式切換（localStorage + CSS custom properties）
14. 手機版底部 NavBar + FAB 發文按鈕
15. 統一 CSS（移除所有 inline style，採 TailwindCSS 或 CSS Modules）

驗收：

```
✔ UI 有清楚的三層結構（Layout / Page / Component）
✔ forum 頁面視覺類似 eyny（版區列表 / 文章列表 / 文章詳情）
✔ admin 後台清楚分離
✔ root Danger Zone 明確且有防呆
✔ server mode 在所有頁面可見
✔ health 狀態燈在 sidebar 可見
✔ 手機版（375px）不崩版
✔ 所有操作有 loading / error / success feedback
✔ 深色模式正常切換
```

# 17. 整份計畫優化執行順序

> 以下是整合 v3 原生 Phase 1–9、Section 15 補充 Phase 10–15、Section 15.20 對標 Phase 17、以及 Section 16 UI Phase 16 後的
> **完整建議執行優先順序**。以「先能跑、再安全、再完整、再好用」為原則，
> 參考 Stack Overflow/DCard/eyny 實作經驗重新排列。

---

## 第一優先級：基礎安全地基（不可跳過）

這些是整個系統的信任根基，任何功能都依賴它們。

| 順序 | 內容 | 對應 |
|------|------|------|
| 1 | DB schema + migration 系統（users/sessions/audit/security_events）| Phase 1 |
| 2 | 角色權限 middleware（role / member_level / status 三層檢查）| Phase 1 |
| 3 | Audit log hash chain 基礎建設 | Phase 1 |
| 4 | Security events 完整 event_type 覆蓋 | Phase 1 + Phase 4 |
| 5 | CSRF 中介層（已有，確認完整）| Phase 1 |
| 6 | Rate limiting（已有，確認覆蓋所有 API）| Phase 1 |
| 7 | 登入 / 登出 / session 管理（已有，確認安全）| Phase 1 |

**驗收門檻**：user 不得越權，admin 不得修改 root，所有請求有 audit trail。

---

## 第二優先級：帳號安全強化（對標 DCard/Stack Overflow）

參考 Section 15.20 安全性缺口，實作以下強化：

| 順序 | 內容 | 對應 |
|------|------|------|
| 8 | 忘記密碼 / 重設密碼（不洩漏帳號是否存在）| Phase 6 |
| 9 | Email 驗證（發送 token，驗證後標記 email_verified）| Phase 6 |
| 10 | 密碼強度評分（password_strength_score 0–4，前端即時回饋）| Phase 6 + Phase 17 |
| 11 | 暴力破解鎖定（failed_login_attempts + locked_until，5次鎖定）| Phase 17 |
| 12 | 登入裝置管理（user_sessions 增加 device_info / user_agent）| Phase 17 |
| 13 | Session 固定防護（更換密碼時 invalidate 所有舊 session）| Phase 17 |
| 14 | 預設密碼強制修改（is_default_password 檢查）| Phase 6 |
| 15 | IP 登入異常通知（login_locations GeoIP 比對，email 通知）| Phase 17 |
| 16 | 登出所有裝置（sessions/logout-all）| Phase 6 |

---

## 第三優先級：會員治理與管理員制衡（對標 PTT/Stack Overflow）

| 順序 | 內容 | 對應 |
|------|------|------|
| 17 | member_level_rules schema + API | Phase 2 |
| 18 | moderation_proposals + 投票流程 | Phase 2 |
| 19 | root override | Phase 2 |
| 20 | 處分執行（mute / suspend / downgrade）| Phase 2 |
| 21 | Proposal 投票 UI（ProposalCard + VotePanel）| Phase 2 + Phase 16 |
| 22 | 版主動作日誌（moderation_actions 獨立表，auto mod 也要記錄）| Phase 17 |
| 23 | Mod Note 隱藏備註（user_mod_notes，僅 moderator+ 可見）| Phase 17 |
| 24 | 版主權限委託（moderator_permissions，細緻化授權）| Phase 17 |
| 25 | 威望明細（reputation_events，每次變化有原因記錄）| Phase 17 |

---

## 第四優先級：伺服器模式（對標 PTT/eyny）

| 順序 | 內容 | 對應 |
|------|------|------|
| 26 | server_settings schema + GET/PUT /api/root/ip-whitelist | Phase 3 + Phase 17 |
| 26b | browser_only_mode middleware（UA 檢測 + maintenance_bypass_token Bearer auth）| Phase 3 + Phase 17 |
| 27 | test mode（關閉 IP lock / auto downgrade 等）| Phase 3 |
| 28 | pre_production 條件檢查（密碼 / CSRF / hash chain / IP 白名單）| Phase 3 |
| 29 | superweak sandbox（隔離寫入，進入前 auto snapshot，離開後復原）| Phase 3 |
| 30 | IP 白名單限制（同 IP 不可同時登入不同帳號，superweak exempt）| Phase 17 |
| 31 | Magic Link 無密碼登入（/api/auth/magic-link）| Phase 17 |
| 32 | ModeIndicator UI（所有頁面顯示 mode badge）| Phase 3 + Phase 16 |

---

## 第五優先級：快照 / 還原 / 重設（對標版本控制思維）

| 順序 | 內容 | 對應 |
|------|------|------|
| 33 | snapshots schema + 建立 / 刪除 | Phase 5 |
| 34 | restore 流程（checksum 驗證 / 暫停寫入 / 重建 index）| Phase 5 |
| 35 | reset server 流程（auto snapshot + 清除 + 重建預設）| Phase 5 |
| 36 | snapshot 自動排程（daily_auto）| Phase 9 |
| 37 | Danger Zone UI（ConfirmDialog + confirm text + 紅色區塊）| Phase 5 + Phase 16 |

**前置條件**：Phase 5 完成後才能進入 superweak 模式。

---

## 第六優先級：健康監控與安全中心（對標運維標配）

| 順序 | 內容 | 對應 |
|------|------|------|
| 38 | readiness light API（綠 / 黃 / 紅 + 原因列表）| Phase 4 |
| 39 | anomaly light API（錯誤 / hash chain broken / DB integrity）| Phase 4 |
| 40 | hash chain 完整性檢查 API | Phase 4 |
| 41 | HealthLight + HashChainStatus UI 元件 | Phase 4 + Phase 16 |
| 42 | DB integrity check dashboard | Phase 9 |

---

## 第七優先級：論壇核心功能（對標 eyny/PTT）

| 順序 | 內容 | 對應 |
|------|------|------|
| 43 | forum_categories + forum_boards schema | Phase 7 |
| 44 | posts + comments CRUD（含 soft delete）| Phase 7 |
| 45 | board_moderators + 版主權限 | Phase 7 |
| 46 | newbie 發文進 pending_review 審核流程 | Phase 7 |
| 47 | 文章類型系統（post_type：normal/announcement/question/howto/review/nsfw）| Phase 17 |
| 48 | 置頂 / 鎖文 / 精華文（is_sticky / is_locked / is_curated + API）| Phase 17 |
| 49 | 瀏覽次數（view_count，15 分鐘 session 去重）| Phase 13 |
| 50 | SidebarLeft 版區樹 UI | Phase 7 + Phase 16 |
| 51 | PostList / PostCard / CommentList 元件 | Phase 7 + Phase 16 |

---

## 第八優先級：UI 架構重構（對標 DCard/Reddit）

在論壇核心功能可用後，重構 UI 分層架構（避免在混亂 UI 上繼續疊加功能）。

| 順序 | 內容 | 對應 |
|------|------|------|
| 52 | 建立 MainLayout / AdminLayout / AuthLayout | Phase 16 |
| 53 | 建立通用 Component 庫（Modal / Toast / LoadingSpinner / Pagination）| Phase 16 |
| 54 | 所有 forum 頁面套入 MainLayout | Phase 16 |
| 55 | 所有 admin/root 頁面套入 AdminLayout | Phase 16 |
| 56 | services/ 分層（移除 component 直接 fetch）| Phase 16 |
| 57 | Zustand 全域狀態（user / theme / serverMode）| Phase 16 |
| 58 | 手機版適配（底部 NavBar + FAB，375px 不崩版）| Phase 16 |
| 59 | 深色模式（CSS custom properties + localStorage）| Phase 12 + Phase 16 |

---

## 第九優先級：檢舉 / 申訴 / 通知（對標 Reddit/Discord）

| 順序 | 內容 | 對應 |
|------|------|------|
| 60 | reports schema + 用戶提交檢舉 | Phase 8 |
| 61 | appeals schema + 用戶提交申訴 | Phase 8 |
| 62 | 舉報處理 Claim 機制（moderation_reports.claimed_by）| Phase 17 |
| 63 | notifications schema + 觸發 / 已讀 | Phase 8 |
| 64 | 積分 / 威望計算服務 | Phase 8 |
| 65 | 通知鈴 + 通知列表 UI | Phase 8 + Phase 16 |
| 66 | WebSocket 即時通知推送（/ws/notifications）| Phase 17 |
| 67 | Email 通知摘要（即時 / 每日 / 每週，background job）| Phase 17 |

---

## 第十優先級：站內信（對標 PTT/DCard）

| 順序 | 內容 | 對應 |
|------|------|------|
| 68 | direct_messages / dm_threads schema | Phase 10 |
| 69 | DM API（收發 / 已讀 / 軟刪除）| Phase 10 |
| 70 | DM UI（收件匣 + 對話串）| Phase 10 |
| 71 | 封鎖用戶整合（blocked_users，阻擋 DM 送達）| Phase 10 + Phase 14 |

---

## 第十一優先級：附件 / 圖片 / 頭像上傳（對標論壇標配）

| 順序 | 內容 | 對應 |
|------|------|------|
| 72 | attachments schema + 上傳 API（MIME 白名單 + magic bytes）| Phase 11 |
| 73 | 圖片 re-encode（去除 EXIF metadata）| Phase 11 |
| 74 | 頭像上傳 + 裁切 | Phase 11 |
| 75 | 富文字編輯器（Markdown + 圖片上傳 + @username 補全）| Phase 13 + Phase 16 |
| 76 | CAPTCHA 機制（none/math/image/turnstile，用於註冊/登入/高風險操作）| Phase 17 |

---

## 第十二優先級：Storage 雲端硬碟與相簿（對標 Google Drive/iCloud）

| 順序 | 內容 | 對應 |
|------|------|------|
| 77 | user_storage / storage_files / storage_quota_log schema | Phase 11 |
| 78 | albums / album_files schema + slug + share_token | Phase 11 |
| 79 | 上傳下載 API（配額檢查 / MIME 驗證 / magic bytes / 路徑防遍歷）| Phase 11 |
| 80 | 回收筒 API（soft delete / restore / permanent / empty）| Phase 11 |
| 81 | 相簿 API（CRUD / add files / reorder / cover）| Phase 11 |
| 82 | 分享連結 API（token / 密碼保護 / 過期）| Phase 11 |
| 83 | Storage Admin API（全站統計 / 配額調整 / 同步）| Phase 11 |
| 84 | FileManager 前端（拖曳上傳 / 資料夾樹 / 回收筒）| Phase 11 |
| 85 | AlbumManager 前端（建立 / 照片管理 / 分享設定）| Phase 11 |
| 86 | 回收筒清理 CRON / 配額同步 CRON | Phase 11 |

---

## 第十三優先級：用戶個人化（對標 DCard/Stack Overflow）

| 順序 | 內容 | 對應 |
|------|------|------|
| 87 | 個人主頁 API + UI（頭像 / bio / 積分展示）| Phase 12 |
| 88 | 個人簽名檔（顯示於每則發文下方）| Phase 12 |
| 89 | 自訂稱號（admin 核准流程）| Phase 12 |
| 90 | 成就徽章（achievement_definitions / user_achievements，自動授予）| Phase 15 |
| 91 | 在線名單（user_online_states，Zustand 整合）| Phase 15 |
| 92 | 通知偏好設定（notification_preferences，即時/每日/每週）| Phase 14 + Phase 17 |

---

## 第十四優先級：文章互動（對標 Stack Overflow/PTT）

| 順序 | 內容 | 對應 |
|------|------|------|
| 93 | post_reactions / comment_reactions（Emoji + 文字 label）| Phase 13 |
| 94 | 引用回覆（parent_comment_id + quote_body，前端縮排顯示）| Phase 13 |
| 95 | @mention 解析與通知（post_mentions，去除已封鎖通知）| Phase 13 |
| 96 | 文章編輯歷史（post_edit_history，30分鐘內免 reason）| Phase 13 |
| 97 | 文章投票 Poll（polls / poll_options / poll_votes）| Phase 13 |
| 98 | Wiki 共同編輯文章（is_wiki，任何人可貢獻，post_wiki_edits）| Phase 17 |
| 99 | 文章修訂請求（Edit Suggestion，非 Wiki 也可提，OP/moderator accept）| Phase 17 |
| 100 | 賞金懸賞系統（post_bounties，用積分懸賞回答）| Phase 17 |
| 101 | 公告強制閱讀確認（post_read_receipts，版主可看已讀/未讀）| Phase 17 |
| 102 | 相似問題自動提示（發文時 FTS 比對標題）| Phase 17 |
| 103 | 接受最佳解答（comment.accepted，OP 標記）| Phase 17 |

---

## 第十五優先級：社交與訂閱（對標 Reddit/DCard）

| 順序 | 內容 | 對應 |
|------|------|------|
| 104 | 追蹤用戶 / 封鎖用戶（user_follows / blocked_users）| Phase 14 |
| 105 | 訂閱文章 / 訂閱版區（thread_subscriptions / board_subscriptions）| Phase 14 |
| 106 | 文章收藏（bookmarks，可加個人備註）| Phase 14 |
| 107 | 未讀追蹤（user_read_states + 版區紅點 badge）| Phase 14 |
| 108 | Infinite Scroll（cursor-based 分頁，Intersection Observer）| Phase 17 |

---

## 第十六優先級：探索與搜尋（對標 Stack Overflow/Reddit）

| 順序 | 內容 | 對應 |
|------|------|------|
| 109 | 全站搜尋（SQLite FTS5，標題+內文，highlight + rate limit）| Phase 15 |
| 110 | 標籤系統（tags / post_tags，每文最多 5 個）| Phase 15 |
| 111 | 熱門排行（hot_score，15 分鐘 background job 更新）| Phase 15 |
| 112 | 草稿管理（forum_drafts，前端每 30 秒 autosave）| Phase 15 |

---

## 第十七優先級：防濫用與進階安全（對標 Stack Overflow/Discord）

| 順序 | 內容 | 對應 |
|------|------|------|
| 113 | spam detection（發文頻率分析）| Phase 9 |
| 114 | multi-account detection（IP + fingerprint）| Phase 9 |
| 115 | 資料匯出 GDPR（data_export_requests，ZIP + email 下載連結）| Phase 17 |
| 116 | 帳號永久刪除（account_deletion_requests，30 天 grace period）| Phase 17 |
| 117 | WebAuthn 生物特徵驗證（user_webauthn_credentials，FIDO2）| Phase 17 |

---

## 第十八優先級：可選進階功能（對標 Discord/企業論壇）

| 順序 | 內容 | 對應 |
|------|------|------|
| 118 | 即時聊天（Live Chat，live_chatrooms + WebSocket）| Phase 18 |
| 119 | 「瀏覽過的文章」歷史（user_browse_history，Redis 限時）| Phase 18 |

---

## 優先順序總表（縮略版）

```
[立即做]   1–7      基礎安全地基（schema / permission / audit / hash chain）
[立即做]   8–16     帳號安全強化（暴力鎖定 / 強度評分 / 裝置管理 / Session 防護）

[第一季]  17–25     會員治理（mod note / 動作日誌 / 威望明細 / 權限委託）
[第一季]  26–32     Server mode（IP 白名單 / Magic Link / superweak）
[第一季]  33–37     Snapshot / restore / reset / auto snapshot

[第二季]  38–42     Health monitor（readiness / anomaly / hash chain）
[第二季]  43–51     論壇核心（版區 / 文章 / 版主 / 文章類型 / 置頂鎖文精華）
[第二季]  52–59     UI 架構重構（Layout / Component / Services / Zustand）

[第三季]  60–67     檢舉 / 申訴 / 通知（Claim / WebSocket / Email 摘要）
[第三季]  68–71     站內信（DM + 封鎖整合）
[第三季]  72–76     附件上傳 / 頭像 / CAPTCHA

[第四季]  77–86     Storage 雲端硬碟與相簿
[第四季]  87–92     用戶個人化（主頁 / 簽名 / 成就 / 線上狀態）
[第四季]  93–103    文章互動（反應 / 引用 / @提及 / Wiki / 賞金 / 修訂請求）
[第四季]  104–108   社交訂閱（追蹤 / 封鎖 / 訂閱 / 收藏 / Infinite Scroll）

[第五季]  109–112   探索搜尋（全文 FTS / 標籤 / 熱門排行 / 草稿）
[第五季]  113–117   防濫用 + 進階安全（GDPR / 刪除 / WebAuthn）
[可選]    118–119   即時聊天 / 瀏覽紀錄
```

---

## 注意事項

1. **後端安全永遠優先於前端功能**：每個 Phase 的後端 API + 權限測試必須在 UI 之前完成。
2. **不得讓 UI 改動破壞後端安全邏輯**：Phase 16 只改前端，禁止修改後端驗證。
3. **每個 Phase 都要有測試**：參照 Section 9（測試計畫）逐 Phase 補充對應測試案例。
4. **Snapshot 必須在 Phase 5 完成後才能進入 superweak**：這是安全前置條件。
5. **Phase 17 優先於 Phase 18**：GDPR 刪除、資料匯出、WebAuthn 屬於基本帳號安全，不應放在倒數第二優先。
6. **UI 重構（Phase 16）建議在 Phase 7–8 後進行**：先確保功能可用，再整理架構。
