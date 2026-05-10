# Job Center 統一任務中心規劃

## 結論

Job Center 是目前最值得優先新增的基礎功能。ComfyUI 生成、影音轉碼、HLS 產生、報告產生、QA 掃描、上線前檢查、備份、匯入匯出、Discord sync、未來 AI Agent 工具執行，都需要一個統一的任務狀態與進度介面。

第一版建議做成「可觀測任務中心」，先集中顯示任務狀態，不急著重寫所有現有任務執行器。

## 目標

- 統一顯示所有長時間任務。
- 任務必須有進度、階段、開始時間、更新時間、耗時、錯誤、重試與取消狀態。
- 使用者只看得到自己的任務；admin/root 可看全站任務。
- 任務錯誤要顯示在前台可見區域，不放在頁面底部或 console。
- 任何任務不可靜默失敗。

## 第一批適用功能

- ComfyUI 生成與排隊。
- 影音上傳、轉碼、HLS 產生。
- 上線前檢查與 QA 腳本。
- 備份、還原前檢查、snapshot verify。
- 報告產生。
- Cloud Drive 大檔案上傳或安全掃描。

## 建議資料表

```sql
CREATE TABLE job_center_jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_uuid TEXT NOT NULL UNIQUE,
    owner_user_id INTEGER,
    created_by_user_id INTEGER,
    job_type TEXT NOT NULL,
    title TEXT NOT NULL,
    description TEXT,
    source_module TEXT NOT NULL,
    source_ref TEXT,
    status TEXT NOT NULL CHECK (status IN (
        'queued', 'running', 'waiting_external', 'succeeded',
        'failed', 'cancelled', 'retry_wait', 'expired'
    )),
    progress_percent INTEGER NOT NULL DEFAULT 0,
    stage TEXT NOT NULL DEFAULT 'queued',
    stage_detail TEXT,
    error_code TEXT,
    error_message TEXT,
    error_stage TEXT,
    retry_count INTEGER NOT NULL DEFAULT 0,
    max_retries INTEGER NOT NULL DEFAULT 0,
    cancellable INTEGER NOT NULL DEFAULT 0,
    cancel_requested_at TEXT,
    result_json TEXT,
    metadata_json TEXT,
    created_at TEXT NOT NULL,
    started_at TEXT,
    updated_at TEXT NOT NULL,
    finished_at TEXT,
    expires_at TEXT
);

CREATE TABLE job_center_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_uuid TEXT NOT NULL REFERENCES job_center_jobs(job_uuid),
    event_type TEXT NOT NULL,
    stage TEXT,
    message TEXT,
    progress_percent INTEGER,
    payload_json TEXT,
    created_at TEXT NOT NULL
);
```

## API 草案

```text
GET  /api/jobs
GET  /api/jobs/<job_uuid>
GET  /api/jobs/<job_uuid>/events
POST /api/jobs/<job_uuid>/cancel
POST /api/jobs/<job_uuid>/retry
GET  /api/admin/jobs
```

## UI 草案

- 右上角任務圖示顯示進行中數量。
- 任務中心頁面支援：
  - 進行中
  - 等待外部服務
  - 失敗
  - 已完成
  - 我的任務
  - 全站任務 admin/root only
- 每個任務卡顯示：
  - 標題
  - 模組
  - 狀態
  - 進度條
  - 目前階段
  - 錯誤摘要
  - 重試 / 取消
  - 詳細事件 timeline

## Server Mode 規則

- production：允許正式任務；高風險任務需走既有確認流程。
- internal_test/test：任務必須標記 test/shadow，不可污染 production 資料。
- maintenance：只允許 root 查看與取消；不啟動新任務。
- incident_lockdown：暫停新任務，只允許 root 檢查狀態。
- superweak：Job Center UI 可 read-only，執行器關閉。

## 驗收標準

- ComfyUI 排隊與執行能在 Job Center 顯示。
- 影音轉碼與 HLS 產生能顯示進度。
- 失敗任務會顯示明確錯誤階段。
- 使用者不能看其他使用者任務。
- admin/root 可查詢全站任務。
- 手機版任務卡不爆版。
