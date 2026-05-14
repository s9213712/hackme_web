# AI WebChat Read-only MVP 規劃

## 結論

AI WebChat 第一版應只做「聊天 + read-only 查詢」，不做 write tools、不做 root/admin 自動操作、不做 snapshot restore、server reset、pentest、shell 或 raw SQL。

此文件承接 `docs/AGENTS/research/LLM_WEBCHAT` 的方向，但把 MVP 收斂為可先落地的最小功能。

## 目標

- 使用者可透過 `/api/ai/chat` 與本地 Ollama / LM Studio 對話。
- AI 可透過 read-only tools 查詢使用者自己的資料。
- 所有 tool call 經過 registry、schema validation、policy、audit。
- 不讀取 secret、session、CSRF、private key、E2EE 明文。
- WebChat 不直接執行 provider-native tool calls。

## MVP tools

```text
user.get_self_profile
points.get_balance
points.list_transactions
trading.get_portfolio_summary
cloud_drive.list_my_files_metadata
forum.search_public_posts
forum.get_public_post
job_center.list_my_jobs
notifications.list_my_notifications
```

敏感 read-only tools：

```text
admin.audit_summary
root.system_status
```

這些只允許 admin/root，必須 redaction，且不可回傳 raw audit lines。

## API 草案

```text
GET  /api/ai/providers
POST /api/ai/chat
POST /api/ai/agent/plan
POST /api/ai/agent/execute-readonly
GET  /api/ai/agent/actions
GET  /api/ai/agent/tools
```

MVP 不實作：

```text
POST /api/ai/agent/confirm
write tools
high-risk execution
critical tools
```

## 資料邊界

永遠不可送入 LLM：

```text
session cookie
CSRF token
password hash
API token
OAuth token
private key
E2EE key
TOTP secret
runtime secret
raw env
DB connection string
full raw audit line
other users private data
```

## Provider 安全

- provider URL 只能 root 設定。
- 預設只允許 localhost / 127.0.0.1 / ::1。
- LAN provider 必須 root 額外開啟。
- 每次 request 前 resolve hostname，檢查 resolved IP。
- 禁止 `file://`、`ftp://`、`gopher://`。
- 禁止 URL 帶 username/password。
- provider offline 回友善錯誤，不 crash server。

## UI 草案

- 新增 AI WebChat 頁。
- 顯示 provider 狀態。
- 顯示 tool call 摘要與資料來源。
- 顯示「此回覆依據哪些 read-only 工具」。
- 手機版單欄，輸入框固定底部或清楚可見。

## 驗收標準

- Ollama / LM Studio offline 時顯示友善錯誤。
- 一般使用者不能查 admin/root tools。
- AI 不能讀其他使用者私有檔案。
- prompt injection 不能改 policy。
- tool output 先 redact，再 audit，再送 LLM。
- 所有 tool call 有 action_id 與 audit。
