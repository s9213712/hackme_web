# Notification Center 統一通知中心規劃

## 結論

通知中心應該作為全站可見事件的統一入口。它不取代 audit log，而是把使用者需要知道的事件用可讀方式呈現，解決目前錯誤、完成狀態、警告分散在不同頁面的問題。

## 目標

- 集中顯示任務完成、交易成交、分享失效、上傳完成、ComfyUI 生成完成、系統警告、管理審核結果。
- 支援未讀、已讀、重要、分類、跳轉目標。
- 通知內容不可包含 secret、token、密碼、私鑰或敏感 raw payload。
- 通知必須 user scoped；admin/root 可接收全站警告。

## 通知類型

```text
job.completed
job.failed
comfyui.completed
video.transcode_completed
video.transcode_failed
share.expired
share.revoked
share.view_limit_reached
trading.order_filled
trading.order_failed
points.adjusted
cloud.upload_completed
cloud.scan_failed
security.warning
admin.review_required
system.maintenance
```

## 建議資料表

```sql
CREATE TABLE notifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    notification_uuid TEXT NOT NULL UNIQUE,
    user_id INTEGER,
    audience TEXT NOT NULL CHECK (audience IN ('user', 'admin', 'root', 'system')),
    type TEXT NOT NULL,
    severity TEXT NOT NULL CHECK (severity IN ('info', 'success', 'warning', 'error', 'critical')),
    title TEXT NOT NULL,
    body TEXT,
    link_url TEXT,
    source_module TEXT,
    source_ref TEXT,
    read_at TEXT,
    dismissed_at TEXT,
    metadata_json TEXT,
    created_at TEXT NOT NULL,
    expires_at TEXT
);
```

## API 草案

```text
GET  /api/notifications
GET  /api/notifications/unread-count
POST /api/notifications/<notification_uuid>/read
POST /api/notifications/read-all
POST /api/notifications/<notification_uuid>/dismiss
GET  /api/admin/notifications
```

## UI 草案

- 頁首鈴鐺顯示未讀數。
- 通知抽屜支援分類篩選。
- 高風險錯誤用固定 toast 顯示，不只放在頁面底部。
- 手機版採全螢幕通知頁或底部抽屜。

## 與 Job Center 關係

- Job Center 是任務狀態來源。
- Notification Center 只顯示任務結果與需要使用者注意的狀態。
- 失敗任務通知要連回 Job Center 詳情。

## 驗收標準

- 任務成功/失敗會產生通知。
- 交易下單失敗會立即可見。
- 分享失效與次數用完會通知擁有者。
- 通知不洩漏敏感內容。
- 手機版可閱讀、標記已讀與跳轉。
