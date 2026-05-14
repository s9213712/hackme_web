# Share Link Management 分享連結管理中心規劃

## 結論

分享功能已具備密碼、時間、次數與 session 行為，下一步應補上使用者可管理的「分享連結中心」。目前最重要的是可見性、撤銷能力、存取紀錄與清楚的結束狀態。

## 目標

- 使用者可查看自己建立的所有分享連結。
- 顯示到期時間、剩餘次數、是否需要密碼、最近存取、目前狀態。
- 支援一鍵撤銷、延長時間、修改密碼、重設次數。
- 分享結束頁必須顯示友善訊息，不直接 404。
- 分享影音使用 session 計次；重新整理、更換分頁、更換瀏覽器等新 session 需重新要求密碼並計次。

## 狀態模型

```text
active
expired
view_limit_reached
revoked
password_required
blocked
not_found
```

## 建議資料表補強

若既有 share table 已有核心欄位，優先擴充，不重建。

```sql
CREATE TABLE share_access_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    share_token_hash TEXT NOT NULL,
    share_session_id TEXT NOT NULL,
    user_id INTEGER,
    ip_hash TEXT,
    user_agent_hash TEXT,
    password_verified_at TEXT,
    counted_view_at TEXT,
    last_seen_at TEXT,
    created_at TEXT NOT NULL,
    UNIQUE(share_token_hash, share_session_id)
);

CREATE TABLE share_access_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    share_token_hash TEXT NOT NULL,
    event_type TEXT NOT NULL,
    share_session_id TEXT,
    user_id INTEGER,
    ip_hash TEXT,
    user_agent_hash TEXT,
    decision TEXT,
    reason TEXT,
    created_at TEXT NOT NULL
);
```

## API 草案

```text
GET  /api/shares
GET  /api/shares/<share_id>
PATCH /api/shares/<share_id>
POST /api/shares/<share_id>/revoke
POST /api/shares/<share_id>/rotate-password
GET  /api/shares/<share_id>/access-events
GET  /shared/<token>/status
```

## UI 草案

- 新增「我的分享」頁。
- 欄位：
  - 類型：檔案 / 影音 / 資料夾 / 文章
  - 狀態
  - 到期時間
  - 剩餘次數
  - 是否需要密碼
  - 最近存取
  - 操作：複製、撤銷、延長、修改密碼
- 手機版用卡片，不用寬表格。

## 安全要求

- share token 不以明文寫 audit。
- 密碼只存 hash。
- 存取事件不記 raw IP，使用 hash 或截斷資訊。
- 已撤銷或過期連結不可洩漏資源是否存在。
- 分享影音不可因刷新頁面繞過次數限制。

## 驗收標準

- 使用者可以撤銷分享。
- 已到期或用完次數顯示「分享已結束」。
- 影音分享不同 session 會重新要求密碼並計次。
- 管理者可檢查異常分享存取。
- 手機版可操作所有分享管理功能。
