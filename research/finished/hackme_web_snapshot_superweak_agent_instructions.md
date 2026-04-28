# Agent 實作指令檔：Server Snapshot + Superweak Sandbox Rollback 系統

## 0. 任務目標

請在 hackme_web 專案中實作「伺服器快照與還原系統」，用於支援：

1. root 手動建立伺服器快照
2. 啟用 superweak 模式前自動建立快照
3. 離開 superweak 模式後可完整還原到啟用前狀態
4. 支援測試模式 / 準上線模式 / superweak 模式切換
5. 確保資料庫、使用者上傳檔案、設定、權限規則、審核狀態一致
6. 所有快照、還原、模式切換都必須寫入 audit log
7. 快照不可變成一般備份功能，必須以「可完整回復系統狀態」為目標

---

## 1. 核心設計原則

### 1.1 Snapshot 不只是檔案備份

Snapshot 必須包含可重建應用狀態所需資料：

- database dump
- uploaded files / avatars / attachments
- server config
- feature flags
- security mode settings
- member_level_rules
- moderation queues
- admin vote state
- sanction / restriction / suspension state
- audit log checkpoint
- app version / schema version
- snapshot metadata
- checksum

### 1.2 Restore 必須保證一致性

還原後必須滿足：

- DB 記錄的附件路徑都存在
- 不存在 DB 沒記錄的孤兒附件，或至少被標記為 orphan
- 使用者等級、權限、處分狀態正確
- 管理員投票、檢舉、申訴流程不中斷
- superweak 模式造成的資料變更全部回滾
- audit log 保留還原紀錄，不得被靜默刪除

### 1.3 superweak 模式必須是沙盒式

進入 superweak 模式時：

1. root 必須確認
2. 系統自動建立 before_superweak snapshot
3. 記錄目前模式與快照 ID
4. 降低安全限制供測試
5. 離開時必須可選擇：
   - restore to before_superweak snapshot
   - discard restore but keep current dirty state，僅 root 可用，且必須強警告
6. 預設行為應該是還原，而不是保留 dirty state

---

## 2. 建議資料結構

請依現有框架調整，但至少要有以下資料表或等價模型。

### 2.1 snapshots

欄位建議：

```sql
CREATE TABLE snapshots (
    id TEXT PRIMARY KEY,
    type TEXT NOT NULL,
    status TEXT NOT NULL,
    created_by INTEGER NOT NULL,
    created_at DATETIME NOT NULL,
    completed_at DATETIME,
    app_version TEXT,
    schema_version TEXT,
    source_mode TEXT,
    includes_json TEXT NOT NULL,
    storage_path TEXT NOT NULL,
    db_dump_path TEXT,
    files_archive_path TEXT,
    config_archive_path TEXT,
    checksum TEXT,
    size_bytes INTEGER,
    notes TEXT,
    error_message TEXT
);
```

type 建議：

- manual
- before_superweak
- scheduled
- pre_restore
- pre_migration
- emergency

status 建議：

- creating
- ready
- failed
- restoring
- restored
- deleted

---

### 2.2 snapshot_restore_events

```sql
CREATE TABLE snapshot_restore_events (
    id TEXT PRIMARY KEY,
    snapshot_id TEXT NOT NULL,
    restored_by INTEGER NOT NULL,
    started_at DATETIME NOT NULL,
    completed_at DATETIME,
    status TEXT NOT NULL,
    restore_mode TEXT NOT NULL,
    pre_restore_snapshot_id TEXT,
    checksum_verified INTEGER NOT NULL DEFAULT 0,
    dry_run INTEGER NOT NULL DEFAULT 0,
    error_message TEXT
);
```

restore_mode：

- full
- db_only
- files_only
- config_only
- dry_run

正式功能第一版可以只允許 full restore，其他模式先保留 enum 但不開放 UI。

---

### 2.3 server_modes

若已有設定表，整合即可。

```sql
CREATE TABLE server_modes (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    current_mode TEXT NOT NULL,
    previous_mode TEXT,
    active_snapshot_id TEXT,
    mode_changed_by INTEGER,
    mode_changed_at DATETIME,
    notes TEXT
);
```

current_mode：

- preprod
- test
- superweak

---

## 3. Snapshot 內容清單

請建立 SnapshotService，集中處理快照。

### 3.1 必備內容

每個 snapshot 至少包含：

#### A. Database Dump

包含：

- users
- roles / permissions
- member_level_rules
- sessions / tokens，如專案有存 DB
- posts
- comments
- private messages
- reports
- moderation queue
- admin votes
- sanctions
- audit logs
- server mode state
- feature flags
- rate limit rules
- app settings

SQLite 專案可使用：

- sqlite backup API
- 或鎖定寫入後複製 db 檔
- 或 `.dump`

若是 PostgreSQL/MySQL，請使用正式 dump 工具。

第一版若專案是 SQLite，優先做 SQLite backup API。

---

#### B. Uploaded Files

包含：

- uploads/
- avatars/
- attachments/
- user content images/
- any media storage directory

請不要包含：

- cache/
- tmp/
- logs/，除非是 audit logs 且不是 DB 內
- build/
- node_modules/
- venv/
- __pycache__/

---

#### C. Config Snapshot

包含：

- config.yaml
- .env.example
- runtime settings
- feature flag config
- mode config
- member level config
- rate limit config
- moderation config

注意：

真正的 `.env` 可能含 secrets，請不要明文打包。

做法：

- 如果需要記錄 .env，請只保存 key 名稱與 hash，不保存 secret value
- secrets 應由 secret manager 或部署環境另行管理
- 若目前專案沒有 secret manager，至少要在 snapshot metadata 裡標記 secrets_excluded=true

---

#### D. Metadata

每個 snapshot 目錄都要有：

```json
{
  "snapshot_id": "snap_20260427_153000_xxxxxx",
  "type": "before_superweak",
  "created_by": "root",
  "created_at": "2026-04-27T15:30:00+08:00",
  "app_version": "unknown-or-git-sha",
  "schema_version": "current-db-schema-version",
  "source_mode": "preprod",
  "includes": {
    "database": true,
    "uploads": true,
    "config": true,
    "audit_checkpoint": true
  },
  "secrets_excluded": true,
  "checksum_algorithm": "sha256",
  "checksum": "...",
  "notes": "Before enabling superweak mode"
}
```

---

## 4. 檔案目錄建議

建立：

```text
storage/
  snapshots/
    snap_YYYYMMDD_HHMMSS_xxxxxx/
      metadata.json
      db.sqlite3.backup
      uploads.tar.gz
      config.tar.gz
      manifest.json
      checksums.sha256
```

manifest.json 要列出封存內容：

```json
{
  "files": [
    {
      "path": "uploads/avatar/u1.png",
      "size": 12345,
      "sha256": "..."
    }
  ]
}
```

---

## 5. 權限要求

### 5.1 建立 snapshot

允許：

- root
- 或有 `snapshot:create` 權限的 admin

但 before_superweak snapshot 必須 root 觸發或 root 授權。

### 5.2 還原 snapshot

只允許：

- root

不允許一般 admin 還原整站快照。

### 5.3 刪除 snapshot

只允許：

- root

並且必須寫 audit log。

### 5.4 查看 snapshot 列表

允許：

- root
- 有 `snapshot:view` 權限的 admin

但 metadata 中不得暴露敏感資訊。

---

## 6. API 設計

請依專案現有 API style 實作。

### 6.1 建立快照

```http
POST /api/admin/snapshots
```

Body：

```json
{
  "type": "manual",
  "notes": "Before testing risky admin vote flow"
}
```

Response：

```json
{
  "ok": true,
  "snapshot_id": "snap_20260427_153000_abcd12",
  "status": "ready"
}
```

---

### 6.2 列出快照

```http
GET /api/admin/snapshots
```

Response：

```json
{
  "ok": true,
  "snapshots": [
    {
      "id": "snap_20260427_153000_abcd12",
      "type": "manual",
      "status": "ready",
      "created_at": "...",
      "created_by": "root",
      "size_bytes": 1234567,
      "source_mode": "preprod",
      "notes": "..."
    }
  ]
}
```

---

### 6.3 快照詳情

```http
GET /api/admin/snapshots/{snapshot_id}
```

---

### 6.4 還原快照

```http
POST /api/admin/snapshots/{snapshot_id}/restore
```

Body：

```json
{
  "confirm": "RESTORE",
  "dry_run": false,
  "reason": "Rollback after superweak test"
}
```

要求：

- confirm 必須等於 RESTORE
- root only
- 正式 restore 前自動建立 pre_restore snapshot
- restore 成功或失敗都要寫 audit log

---

### 6.5 Dry-run 還原

```http
POST /api/admin/snapshots/{snapshot_id}/restore
```

Body：

```json
{
  "confirm": "DRY_RUN",
  "dry_run": true,
  "reason": "Validate snapshot before restore"
}
```

Dry-run 必須檢查：

- snapshot metadata 是否存在
- checksum 是否正確
- db dump 是否可讀
- uploads archive 是否可解壓
- config archive 是否可解壓
- schema version 是否相容
- manifest 是否完整

不得修改現行系統。

---

## 7. Server Mode API

### 7.1 切換到 superweak

```http
POST /api/admin/server-mode
```

Body：

```json
{
  "mode": "superweak",
  "confirm": "ENABLE_SUPERWEAK",
  "notes": "Testing deliberately weak configuration"
}
```

流程：

1. 驗證 root 權限
2. 檢查目前不是 superweak
3. 自動建立 before_superweak snapshot
4. 將 active_snapshot_id 設為該 snapshot
5. 切換 current_mode = superweak
6. 套用 superweak 設定
7. 寫 audit log

---

### 7.2 離開 superweak 並還原

```http
POST /api/admin/server-mode/exit-superweak
```

Body：

```json
{
  "action": "restore",
  "confirm": "RESTORE_BEFORE_SUPERWEAK",
  "reason": "Finished weak-mode security test"
}
```

流程：

1. root only
2. 確認 current_mode == superweak
3. 找到 active_snapshot_id
4. 建立 pre_restore snapshot
5. 還原 active_snapshot_id
6. 模式恢復 previous_mode，通常是 preprod 或 test
7. 清空 active_snapshot_id
8. 寫 audit log

---

### 7.3 離開 superweak 但不還原

```http
POST /api/admin/server-mode/exit-superweak
```

Body：

```json
{
  "action": "keep_dirty_state",
  "confirm": "KEEP_DIRTY_SUPERWEAK_STATE",
  "reason": "Root intentionally keeps current state"
}
```

要求：

- root only
- 必須強制寫 audit log
- 必須在 response 回傳 warning
- UI 必須顯示危險提示
- 不建議作為預設選項

---

## 8. 模式設定要求

### 8.1 preprod mode

安全機制全開：

- CSRF on
- rate limit on
- login failure lock on
- admin/root password must not be default
- API restricted to internal network if configured
- debug off
- superweak endpoints disabled
- snapshot restore only root

---

### 8.2 test mode

測試用：

- CSRF 保持 on，除非專案明確有測試 bypass token
- 可放寬 login failure lock
- 可放寬 rate limit
- 不可使用預設 root 密碼
- 不可暴露危險 debug endpoint

---

### 8.3 superweak mode

刻意弱化：

- 可降低 rate limit
- 可開啟弱密碼測試
- 可允許危險測試 endpoint
- 可關閉部分防護供內部演練
- 但必須：
  - 只能 root 啟用
  - 啟用前自動 snapshot
  - 必須顯示全站警示 banner
  - 必須禁止在 public production host 啟用，除非 root 以二次確認覆蓋
  - 必須可 rollback

---

## 9. SnapshotService 介面要求

請建立集中式服務，不要把 snapshot 邏輯散落在 route。

建議介面：

```python
class SnapshotService:
    def create_snapshot(self, *, snapshot_type, actor, notes=None) -> SnapshotResult:
        pass

    def list_snapshots(self, *, actor) -> list:
        pass

    def get_snapshot(self, *, snapshot_id, actor):
        pass

    def verify_snapshot(self, *, snapshot_id) -> VerificationResult:
        pass

    def restore_snapshot(self, *, snapshot_id, actor, reason, dry_run=False) -> RestoreResult:
        pass

    def delete_snapshot(self, *, snapshot_id, actor, reason):
        pass
```

---

## 10. ServerModeService 介面要求

```python
class ServerModeService:
    def get_current_mode(self):
        pass

    def switch_mode(self, *, target_mode, actor, confirm, notes=None):
        pass

    def enter_superweak(self, *, actor, confirm, notes=None):
        pass

    def exit_superweak(self, *, actor, action, confirm, reason):
        pass
```

---

## 11. Audit Log 要求

以下事件必須記錄：

- SNAPSHOT_CREATE_STARTED
- SNAPSHOT_CREATE_READY
- SNAPSHOT_CREATE_FAILED
- SNAPSHOT_VERIFY_OK
- SNAPSHOT_VERIFY_FAILED
- SNAPSHOT_RESTORE_STARTED
- SNAPSHOT_RESTORE_COMPLETED
- SNAPSHOT_RESTORE_FAILED
- SNAPSHOT_DELETE
- SERVER_MODE_CHANGE
- SUPERWEAK_ENTER
- SUPERWEAK_EXIT_RESTORE
- SUPERWEAK_EXIT_KEEP_DIRTY_STATE

每筆 audit log 至少包含：

- actor
- target
- action
- old_value
- new_value
- reason
- ip
- user_agent
- created_at
- request_id

---

## 12. 安全要求

### 12.1 Path traversal 防護

snapshot_id 不可直接拼接路徑。

必須：

- 僅允許符合 `snap_YYYYMMDD_HHMMSS_xxxxxx` 格式
- 使用安全 path join
- 確認最終路徑仍在 snapshots root 下

---

### 12.2 壓縮檔解壓安全

restore uploads.tar.gz / config.tar.gz 時必須防止 Zip Slip / Tar Slip。

檢查：

- 不允許 `../`
- 不允許絕對路徑
- 解壓後 final path 必須在目標目錄內

---

### 12.3 Secrets

禁止把真實 secret 明文放進 snapshot。

若目前 `.env` 內含 secret：

- 不要打包 `.env`
- 改打包 `.env.snapshot.redacted`
- 值改為 `<redacted>`
- metadata 標記 secrets_excluded=true

---

### 12.4 Restore 前鎖定寫入

正式 restore 前必須阻止新寫入。

可行方式：

- 設定 maintenance mode
- 暫停 background jobs
- 拒絕非 root 寫入請求
- restore 完成後解除

---

## 13. 測試要求

請建立完整測試，至少包含以下案例。

### 13.1 Snapshot 建立測試

- root 可以建立 manual snapshot
- admin 無權時不可建立 snapshot
- 一般會員不可建立 snapshot
- snapshot metadata 正確
- snapshot 目錄建立成功
- db dump 存在
- uploads archive 存在
- config archive 存在
- checksum 存在
- audit log 正確

---

### 13.2 Restore 測試

流程：

1. 建立使用者 A
2. 建立文章 P1
3. 建立 snapshot
4. 新增文章 P2
5. 修改使用者 A 等級
6. restore snapshot
7. 確認：
   - P1 存在
   - P2 不存在
   - 使用者 A 等級恢復
   - audit log 有 restore event
   - pre_restore snapshot 被建立

---

### 13.3 Uploaded Files 一致性測試

流程：

1. 上傳附件 F1
2. 建立 snapshot
3. 上傳附件 F2
4. restore
5. 確認：
   - F1 存在
   - F2 不存在或被移到 orphan/quarantine
   - DB 中不引用 F2
   - manifest checksum 正確

---

### 13.4 Superweak 模式測試

- root 可以進入 superweak
- 進入前自動建立 before_superweak snapshot
- 一般 admin 不可進入 superweak
- superweak 中建立的資料在 restore exit 後消失
- exit-superweak restore 後 current_mode 恢復 previous_mode
- exit-superweak keep_dirty_state 只能 root 使用
- keep_dirty_state 必須產生高風險 audit log

---

### 13.5 權限測試

- 非 root 不可 restore
- 非 root 不可 delete snapshot
- CSRF 必須保護 snapshot / mode API
- 未登入不可操作
- suspended user 不可呼叫 admin snapshot API
- restricted user 不可呼叫 admin snapshot API

---

### 13.6 安全測試

- snapshot_id path traversal 被拒絕
- 惡意 tar path traversal 被拒絕
- 缺 metadata 的 snapshot 不可 restore
- checksum 不符不可 restore
- schema version 不相容不可 restore，除非 root 使用 explicit override
- restore 失敗時系統不得進入半還原狀態

---

## 14. UI / 管理後台要求

若專案已有 admin UI，請新增：

### 14.1 Snapshot 管理頁

顯示：

- snapshot id
- type
- status
- created_at
- created_by
- source_mode
- size
- notes
- verify button
- restore button，root only
- delete button，root only

Restore button 必須有二次確認：

```text
請輸入 RESTORE 以確認還原。
此操作會覆蓋目前資料，系統會先建立 pre_restore snapshot。
```

---

### 14.2 Server Mode 管理頁

顯示：

- current mode
- previous mode
- active snapshot id
- last changed by
- last changed at

superweak 顯示紅色警告：

```text
目前系統處於 SUPERWEAK 模式。
安全防護已被刻意放寬。
請勿用於公開環境。
離開時建議還原至啟用前快照。
```

---

## 15. 實作順序

請按以下順序實作，不要一次亂改。

### Phase 1：基礎資料模型

- snapshots table
- snapshot_restore_events table
- server_modes table
- migration
- model / repository
- 基礎單元測試

### Phase 2：SnapshotService

- create snapshot
- metadata
- db dump
- uploads archive
- config redacted archive
- checksum
- manifest
- verify snapshot

### Phase 3：RestoreService

- dry-run restore
- full restore
- pre_restore snapshot
- maintenance/write lock
- failure handling
- audit log

### Phase 4：ServerModeService

- preprod/test/superweak mode state
- enter_superweak
- exit_superweak restore
- exit_superweak keep_dirty_state
- mode audit log

### Phase 5：API

- snapshot CRUD API
- restore API
- server mode API
- permission checks
- CSRF checks

### Phase 6：Admin UI

- snapshot list/detail
- restore confirmation
- server mode page
- superweak warning banner

### Phase 7：測試與文件

- unit tests
- integration tests
- security tests
- README / admin guide
- recovery playbook

---

## 16. 驗收標準

完成後必須通過：

1. root 可建立 snapshot
2. root 可 dry-run verify snapshot
3. root 可 restore snapshot
4. restore 前會自動建立 pre_restore snapshot
5. superweak 啟用前會自動建立 before_superweak snapshot
6. superweak 中造成的資料改動可完整回滾
7. 非 root 不能 restore
8. snapshot path traversal 被擋
9. 惡意 tar traversal 被擋
10. checksum 錯誤不可 restore
11. metadata 缺失不可 restore
12. audit log 完整記錄所有操作
13. DB 與 uploaded files 還原後一致
14. secrets 不會被明文打包
15. README 有清楚說明 snapshot / restore / superweak 流程

---

## 17. 禁止事項

請不要：

- 把 snapshot 邏輯寫死在 route 裡
- 只備份 DB 卻忽略 uploads
- 把 `.env` secret 明文打包
- 讓 admin 可以 restore 全站
- 讓 superweak 模式不用 snapshot 就啟用
- restore 時不建立 pre_restore snapshot
- restore 失敗卻不寫 audit log
- 使用未驗證 snapshot 還原
- 解壓 tar/zip 時不檢查路徑
- 把快照目錄放在 web 可直接下載的位置
- 讓 snapshot API 缺少 CSRF / auth / permission 檢查

---

## 18. 最終交付物

請交付：

1. migration files
2. SnapshotService
3. ServerModeService
4. API routes
5. admin UI
6. tests
7. README_snapshot_restore.md
8. recovery_playbook.md
9. security notes
10. 實測報告，列出：
    - 建立 snapshot 測試結果
    - restore 測試結果
    - superweak rollback 測試結果
    - 權限測試結果
    - path traversal / checksum 測試結果
