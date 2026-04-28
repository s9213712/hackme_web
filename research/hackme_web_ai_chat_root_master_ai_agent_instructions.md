# hackme_web 站內 AI 聊天系統 + Root 主 AI 監控系統 Agent 指令檔 v1.0

> 目標：在 hackme_web 加入一套站內 AI 聊天系統，底層可接 Ollama 或 LM Studio，讓一般用戶能使用「受限能力的聊天 AI」，root 則擁有「主 AI」用於伺服器狀態、審計報表、異常行為與入侵事件監測。  
> 核心概念：一般用戶 AI 是 root 主 AI 的「分割 / 受限子 AI」，不得擁有 root 權限，不得直接操作系統高危功能。  
> 重要安全原則：AI 可以輔助、整理、分析、提醒，但不能在未授權下執行破壞性或高權限操作。

---

## 0. 最高設計原則

請為 hackme_web 建立：

```text
User AI Assistant
+
Root Master AI
+
AI Tool Permission System
+
AI Audit / Incident Reporting
+
Server Health & Security Monitoring
```

必須遵守：

```text
1. 一般用戶 AI 與 root 主 AI 權限完全隔離。
2. 一般用戶 AI 只能操作該用戶授權的資料。
3. 一般用戶 AI 不得讀取其他用戶資料。
4. 一般用戶 AI 不得直接讀取 root/admin 報表。
5. 一般用戶 AI 不得執行 shell、刪檔、改權限、停服務等危險操作。
6. root 主 AI 可讀取審計資料與伺服器狀態，但高危操作仍需 root 確認。
7. AI 發現異常行為只能上報，不得自動懲罰用戶，除非規則明確允許低風險暫停。
8. 所有 AI 工具呼叫必須記錄 audit log。
9. 所有對雲端硬碟的整理動作必須先產生計畫，經使用者確認後才執行。
10. 所有模型請求必須透過後端 AI Gateway，不得讓前端直接連 Ollama / LM Studio。
```

---

# Part A — 系統角色

## A1. User AI Assistant

一般用戶可使用的聊天 AI。

功能：

```text
1. 說明網站如何使用。
2. 協助搜尋自己的公告、貼文、留言、雲端硬碟檔案。
3. 協助整理自己的雲端硬碟檔案。
4. 協助產生文章草稿、摘要、分類建議。
5. 協助理解積分、商城、AI 生圖、Server 租用等功能。
6. 發現用戶行為異常時，向 Root Master AI 上報。
7. 對用戶顯示安全、友善、有限權限的回答。
```

限制：

```text
1. 不能看其他使用者資料。
2. 不能看 admin/root 專用資料。
3. 不能直接刪除檔案。
4. 不能直接移動大量檔案。
5. 不能直接改密碼、改權限、改積分。
6. 不能呼叫伺服器 shell。
7. 不能繞過系統權限。
8. 不能幫助攻擊 hackme_web 或其他用戶。
```

---

## A2. Root Master AI

root 專用主 AI。

功能：

```text
1. 檢查伺服器健康狀態。
2. 分析安全審計報表。
3. 監測登入異常、權限異常、API 濫用。
4. 監測積分經濟異常、私有鏈 ledger 異常。
5. 監測 ComfyUI / libvirt / 雲端硬碟 / 商城等子系統狀態。
6. 接收 User AI Assistant 上報的異常事件。
7. 產生 root 審計摘要。
8. 產生 incident report。
9. 建議 root 採取修復或封鎖措施。
10. 高危操作需要 root 明確確認後才可執行。
```

限制：

```text
1. 不得自動刪除使用者資料。
2. 不得自動永久封鎖帳號，除非 root 設定明確自動化政策。
3. 不得自動關閉主服務，除非進入 root 設定的 emergency policy。
4. 不得把敏感資料完整輸出到一般聊天。
5. 不得將 root 審計資料暴露給一般用戶。
```

---

# Part B — AI Gateway 架構

## B1. 架構

```text
Browser
  ↓
hackme_web frontend
  ↓
/api/ai-chat/*
  ↓
AI Gateway
  ↓
Policy / Permission / Tool Router
  ↓
Ollama or LM Studio
```

不得讓前端直接連：

```text
http://127.0.0.1:11434
http://127.0.0.1:1234
其他本地 LLM API port
```

---

## B2. Provider 支援

支援兩種後端：

```text
Ollama
LM Studio OpenAI-compatible local server
```

設定：

```env
AI_PROVIDER=ollama
OLLAMA_BASE_URL=http://127.0.0.1:11434
OLLAMA_USER_MODEL=qwen2.5:7b
OLLAMA_ROOT_MODEL=qwen2.5:14b

LMSTUDIO_BASE_URL=http://127.0.0.1:1234/v1
LMSTUDIO_USER_MODEL=local-user-model
LMSTUDIO_ROOT_MODEL=local-root-model

AI_REQUEST_TIMEOUT_SECONDS=120
AI_MAX_CONTEXT_MESSAGES=20
AI_MAX_USER_DAILY_MESSAGES=100
AI_ENABLE_TOOLS=true
```

要求：

```text
1. AI provider 可切換。
2. User AI 與 Root AI 可使用不同模型。
3. AI Gateway 要支援 streaming 回應。
4. AI Gateway 要支援 tool calling 或 server-side tool routing。
5. 模型不可直接接觸資料庫，所有資料只能由受控 tool 提供。
```

---

# Part C — 權限分層

## C1. AI Persona 分層

```text
user_assistant：一般用戶 AI
admin_assistant：admin 輔助 AI
root_master_ai：root 主 AI
system_monitor_ai：背景監控 AI
```

---

## C2. Tool Permission Matrix

| Tool | user_assistant | admin_assistant | root_master_ai |
|---|---:|---:|---:|
| 查網站使用說明 | ✅ | ✅ | ✅ |
| 查自己的檔案 | ✅ | ✅ | ✅ |
| 整理自己的檔案計畫 | ✅ | ✅ | ✅ |
| 執行自己的檔案整理 | 需確認 | 需確認 | 需確認 |
| 查其他用戶資料 | ❌ | 受限 | ✅ |
| 查審計報表 | ❌ | 受限 | ✅ |
| 查伺服器狀態 | ❌ | 受限 | ✅ |
| 查安全事件 | ❌ | 受限 | ✅ |
| 停用帳號 | ❌ | 需權限/確認 | 需 root 確認 |
| 封鎖 IP | ❌ | 需權限/確認 | 需 root 確認 |
| 執行 shell | ❌ | ❌ | 預設 ❌，需 root 顯式允許 |
| 刪除資料 | ❌ | 需確認 | 需 root 確認 |

---

# Part D — 資料表設計

## D1. ai_chat_sessions

```sql
CREATE TABLE ai_chat_sessions (
  id BIGSERIAL PRIMARY KEY,
  session_uuid UUID NOT NULL UNIQUE,

  user_id BIGINT NOT NULL,
  ai_role VARCHAR(50) NOT NULL DEFAULT 'user_assistant',

  title VARCHAR(255),
  status VARCHAR(30) NOT NULL DEFAULT 'active',

  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,

  CHECK (ai_role IN ('user_assistant', 'admin_assistant', 'root_master_ai', 'system_monitor_ai')),
  CHECK (status IN ('active', 'archived', 'deleted'))
);
```

---

## D2. ai_chat_messages

```sql
CREATE TABLE ai_chat_messages (
  id BIGSERIAL PRIMARY KEY,

  session_id BIGINT NOT NULL,
  user_id BIGINT,

  role VARCHAR(30) NOT NULL,
  content TEXT NOT NULL,

  model_name VARCHAR(120),
  provider VARCHAR(50),

  token_input INT DEFAULT 0,
  token_output INT DEFAULT 0,

  safety_flag VARCHAR(50) DEFAULT 'none',

  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,

  CHECK (role IN ('user', 'assistant', 'system', 'tool'))
);
```

---

## D3. ai_tool_calls

```sql
CREATE TABLE ai_tool_calls (
  id BIGSERIAL PRIMARY KEY,

  session_id BIGINT,
  user_id BIGINT,

  ai_role VARCHAR(50) NOT NULL,
  tool_name VARCHAR(120) NOT NULL,

  status VARCHAR(40) NOT NULL DEFAULT 'pending',

  input_json TEXT,
  output_json TEXT,

  requires_confirmation BOOLEAN NOT NULL DEFAULT FALSE,
  confirmed_by BIGINT,
  confirmed_at TIMESTAMP,

  risk_level VARCHAR(30) NOT NULL DEFAULT 'low',

  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  completed_at TIMESTAMP,

  CHECK (status IN ('pending', 'confirmed', 'running', 'completed', 'failed', 'denied', 'cancelled')),
  CHECK (risk_level IN ('low', 'medium', 'high', 'critical'))
);
```

---

## D4. ai_incident_reports

```sql
CREATE TABLE ai_incident_reports (
  id BIGSERIAL PRIMARY KEY,
  incident_uuid UUID NOT NULL UNIQUE,

  source VARCHAR(80) NOT NULL,
  reported_by_user_id BIGINT,
  related_user_id BIGINT,

  severity VARCHAR(30) NOT NULL,
  category VARCHAR(80) NOT NULL,

  title VARCHAR(255) NOT NULL,
  summary TEXT NOT NULL,
  evidence_json TEXT,

  status VARCHAR(40) NOT NULL DEFAULT 'open',

  reviewed_by BIGINT,
  resolution TEXT,

  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  reviewed_at TIMESTAMP,

  CHECK (severity IN ('info', 'low', 'medium', 'high', 'critical')),
  CHECK (status IN ('open', 'reviewing', 'resolved', 'false_positive', 'escalated'))
);
```

---

## D5. ai_system_monitor_snapshots

```sql
CREATE TABLE ai_system_monitor_snapshots (
  id BIGSERIAL PRIMARY KEY,

  snapshot_type VARCHAR(80) NOT NULL,

  status_summary TEXT NOT NULL,
  metrics_json TEXT,
  findings_json TEXT,

  severity VARCHAR(30) NOT NULL DEFAULT 'info',

  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,

  CHECK (severity IN ('info', 'low', 'medium', 'high', 'critical'))
);
```

---

## D6. ai_knowledge_docs

```sql
CREATE TABLE ai_knowledge_docs (
  id BIGSERIAL PRIMARY KEY,

  doc_key VARCHAR(160) NOT NULL UNIQUE,
  title VARCHAR(255) NOT NULL,
  category VARCHAR(80) NOT NULL,

  content TEXT NOT NULL,
  visibility VARCHAR(40) NOT NULL DEFAULT 'public',

  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,

  CHECK (visibility IN ('public', 'user', 'admin', 'root'))
);
```

用途：

```text
放網站使用說明、功能說明、FAQ、規則、積分說明、雲端硬碟整理說明。
```

---

# Part E — AI Tool 設計

## E1. User-safe tools

一般用戶 AI 可用：

```text
get_site_help(topic)
search_my_files(query)
list_my_cloud_drive(folder_id)
propose_file_organization(folder_id)
create_file_organization_plan(folder_id)
execute_file_organization_plan(plan_id) 需使用者確認
summarize_my_document(file_id)
search_my_posts(query)
explain_points_balance()
explain_feature_status(feature_key)
report_user_safety_concern(reason)
```

---

## E2. Admin tools

admin AI 可用：

```text
search_public_reports(query)
summarize_user_reports(user_id)
summarize_forum_reports()
review_incident_report(incident_uuid)
```

高風險 admin 工具需要確認：

```text
hide_post()
lock_thread()
freeze_points()
suspend_cloud_file()
```

---

## E3. Root tools

root 主 AI 可用：

```text
get_server_health()
get_service_status()
get_recent_login_events()
get_failed_login_summary()
get_security_audit_summary()
get_points_chain_status()
verify_points_chain()
get_comfyui_status()
get_libvirt_host_status()
get_cloud_drive_security_summary()
get_recent_error_logs()
get_resource_usage()
get_incident_reports()
generate_daily_root_report()
```

高危工具必須 root 確認：

```text
block_ip()
suspend_user()
force_logout_user()
disable_feature()
enter_maintenance_mode()
shutdown_sandbox_vm()
revoke_server_rental()
```

預設禁止：

```text
execute_shell_command()
delete_user_data()
modify_database_directly()
change_root_password()
disable_audit_log()
```

---

# Part F — 一般用戶雲端硬碟整理流程

## F1. AI 可做的事

一般用戶可問：

```text
幫我整理雲端硬碟
找出重複檔案
幫我分類圖片 / 文件
幫我建立資料夾建議
幫我把檔案按日期整理
```

AI 流程：

```text
1. 讀取該用戶自己的檔案列表。
2. 產生整理建議。
3. 顯示將要移動 / 建立資料夾 / 重新命名的清單。
4. 等待使用者確認。
5. 使用者確認後才執行。
6. 執行後產生操作紀錄。
7. 可提供 undo plan。
```

---

## F2. 禁止 AI 直接做

```text
1. 未確認直接刪除檔案。
2. 未確認直接大量移動檔案。
3. 整理其他用戶檔案。
4. 讀取使用者無權限的檔案。
5. 將檔案內容送給不受控外部 API。
```

---

## F3. 檔案整理計畫資料表

```sql
CREATE TABLE ai_file_organization_plans (
  id BIGSERIAL PRIMARY KEY,
  plan_uuid UUID NOT NULL UNIQUE,

  user_id BIGINT NOT NULL,

  status VARCHAR(40) NOT NULL DEFAULT 'draft',

  title VARCHAR(255) NOT NULL,
  summary TEXT NOT NULL,

  operations_json TEXT NOT NULL,
  undo_operations_json TEXT,

  created_by_ai_session BIGINT,

  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  confirmed_at TIMESTAMP,
  executed_at TIMESTAMP,

  CHECK (status IN ('draft', 'confirmed', 'executed', 'cancelled', 'failed'))
);
```

---

# Part G — 異常行為上報

## G1. User AI 發現異常時

一般用戶 AI 遇到以下狀況，不要當場懲罰用戶，只建立 incident report：

```text
1. 用戶詢問如何繞過權限。
2. 用戶詢問如何偷看他人資料。
3. 用戶要求 AI 刪除或竄改 audit log。
4. 用戶嘗試讓 AI 暴露 root 資料。
5. 用戶大量嘗試 prompt injection。
6. 用戶要求攻擊網站、其他用戶或內部服務。
7. 用戶要求產生惡意腳本。
8. 用戶行為疑似帳號被盜。
```

建立：

```text
ai_incident_reports
source = user_assistant
severity = low/medium/high
category = prompt_abuse / privilege_escalation / data_access_violation / malware_request / account_takeover_suspected
```

---

## G2. 上報給 Root Master AI

Root Master AI 的 incident inbox 顯示：

```text
事件時間
相關用戶
嚴重程度
分類
摘要
AI 判斷理由
相關訊息節錄
建議處置
```

要求：

```text
1. 敏感內容要遮蔽。
2. 不要把完整私密對話直接公開給 admin。
3. root 可查看完整證據。
4. false positive 可標記。
```

---

# Part H — Root 主 AI 監控

## H1. 監控範圍

Root Master AI 應監控：

```text
1. 登入成功 / 失敗異常
2. admin/root 操作紀錄
3. 權限變更
4. 積分 ledger / private chain 驗證狀態
5. 雲端硬碟異常存取
6. ComfyUI 生圖任務異常
7. libvirt sandbox VM 異常
8. Server 租借到期 / 違規
9. 系統資源 CPU/RAM/Disk
10. API error rate
11. 5xx 錯誤
12. 可疑 IP / UA
13. CSRF / auth / rate limit 事件
14. 檔案 hash chain / log hash chain 驗證
```

---

## H2. Daily Root Report

每天產生：

```text
系統健康摘要
登入異常摘要
高風險事件摘要
積分系統摘要
私有鏈驗證摘要
雲端硬碟安全摘要
ComfyUI 任務摘要
Server Rental VM 摘要
未處理 incident
建議 root 優先處理事項
```

---

## H3. Realtime Alert

若發生：

```text
root 登入異常
admin 權限提升
大量登入失敗
大量 403/401
points_chain verify failed
log hash chain broken
VM 嘗試連主資料庫
ComfyUI 任務暴增
磁碟快滿
疑似資料外洩
```

則：

```text
1. 建立 ai_incident_reports。
2. 通知 root dashboard。
3. 可選 email / webhook。
4. 嚴重等級 critical 時可進入安全模式建議。
```

---

# Part I — AI Chat API

## I1. User API

```http
POST /api/ai-chat/sessions
GET  /api/ai-chat/sessions
GET  /api/ai-chat/sessions/:session_uuid
POST /api/ai-chat/sessions/:session_uuid/messages
POST /api/ai-chat/tool-calls/:tool_call_id/confirm
POST /api/ai-chat/tool-calls/:tool_call_id/cancel
```

---

## I2. Root API

```http
GET  /api/root/ai/incidents
GET  /api/root/ai/incidents/:incident_uuid
POST /api/root/ai/incidents/:incident_uuid/review
POST /api/root/ai/chat
GET  /api/root/ai/daily-report
POST /api/root/ai/run-health-check
POST /api/root/ai/generate-audit-summary
```

---

## I3. Admin API

```http
GET  /api/admin/ai/incidents
GET  /api/admin/ai/reports
POST /api/admin/ai/chat
```

Admin API 只能看 admin 可見範圍，不可看 root-only secret。

---

# Part J — 前端 UI

## J1. 一般用戶 AI Chat

新增入口：

```text
Sidebar：AI 助手
路由：/ai-chat
```

UI：

```text
聊天視窗
歷史對話
工具確認卡片
檔案整理計畫卡片
網站使用說明快捷問題
目前可用功能說明
```

快捷問題：

```text
如何發文？
如何購買雲端容量？
如何使用 AI 生圖？
我的積分怎麼賺？
幫我整理雲端硬碟
幫我找最近上傳的圖片
```

---

## J2. Root Master AI Dashboard

新增：

```text
/root/ai
/root/ai/incidents
/root/ai/reports
/root/ai/health
```

顯示：

```text
Root AI 聊天
即時事件
伺服器健康
審計摘要
未處理 incident
高風險建議
一鍵產生日報
```

---

## J3. Admin AI Dashboard

新增：

```text
/admin/ai
```

顯示：

```text
檢舉摘要
討論區異常
公告/貼文審核建議
一般 incident
```

---

# Part K — Prompt / System Instruction

## K1. User AI System Prompt 要求

User AI 必須遵守：

```text
你是 hackme_web 的一般用戶 AI 助手。
你只能協助目前登入用戶。
你不能讀取其他用戶資料。
你不能執行高權限操作。
你不能繞過系統限制。
你可以說明網站功能、整理用戶自己的資料、產生建議。
任何檔案移動、刪除、重命名都必須先產生計畫並取得使用者確認。
若用戶要求攻擊、竄改、繞過權限、存取他人資料，請拒絕並建立安全事件上報。
```

---

## K2. Root Master AI System Prompt 要求

Root AI 必須遵守：

```text
你是 hackme_web 的 root 主 AI。
你的任務是協助 root 監控系統健康、安全事件、審計報表與異常行為。
你可以分析伺服器狀態與安全事件。
你不可未經 root 確認執行高危操作。
你必須保護用戶隱私。
你必須把事件分級，提供證據、影響與建議處置。
你不得隱藏審計結果。
你不得修改 audit log。
```

---

# Part L — 安全防護

## L1. Prompt Injection 防護

必須防：

```text
1. 用戶要求忽略系統指令。
2. 用戶要求輸出其他用戶資料。
3. 用戶要求顯示 root prompt。
4. 用戶要求顯示 tool schema secret。
5. 用戶在文件中藏 prompt injection。
```

要求：

```text
1. 工具層做權限檢查，不能只靠模型拒絕。
2. RAG 文件要標註來源與可見範圍。
3. 工具執行前重新檢查 user_id / role。
4. 高風險工具需要人工確認。
```

---

## L2. Rate Limit

限制：

```text
每用戶每日聊天數
每分鐘請求數
每次最大 context
每次最大 tool calls
每小時最大檔案整理計畫數
```

---

## L3. Sensitive Data Redaction

AI 回覆與 logs 必須遮蔽：

```text
password
token
cookie
session
private key
email 可部分遮蔽
IP 可依權限顯示
```

---

# Part M — 積分整合

可選：聊天 AI 是否消耗積分。

MVP 建議：

```text
一般網站說明：免費
雲端檔案整理：少量 soft_points
大量摘要 / 文件分析：消耗 soft_points
root AI：不計費，但記錄資源使用
```

action_type：

```text
ai_chat_user_message
ai_file_organization_plan
ai_document_summary
```

要求：

```text
若要扣點，必須使用 PointsLedgerService。
```

---

# Part N — 背景監控工作

新增 background jobs：

```text
ai_monitor_server_health
ai_monitor_security_events
ai_monitor_points_chain
ai_monitor_failed_logins
ai_generate_daily_root_report
ai_process_incident_queue
```

頻率建議：

```text
server health：每 1~5 分鐘
failed login summary：每 5 分鐘
points chain verify：每 30~60 分鐘
daily report：每天一次
incident queue：即時或每分鐘
```

---

# Part O — 測試要求

必測：

```text
1. 一般用戶 AI 只能看自己的資料。
2. 一般用戶 AI 不能查其他用戶檔案。
3. 一般用戶 AI 不能看 root report。
4. 檔案整理必須先產生計畫，確認後才執行。
5. 未確認不得移動 / 刪除檔案。
6. 異常 prompt 會建立 incident report。
7. Root AI 可看到 incident inbox。
8. Root AI 可產生伺服器健康摘要。
9. Root AI 高危操作需要確認。
10. AI Gateway 可切換 Ollama / LM Studio。
11. Ollama 連不上時有錯誤提示。
12. LM Studio 連不上時有錯誤提示。
13. prompt injection 不會繞過工具權限。
14. AI tool call 都有 audit log。
15. rate limit 有效。
16. sensitive data redaction 有效。
```

---

# Part P — 交付項目

請交付：

```text
1. AI Gateway service
2. OllamaProvider
3. LMStudioProvider
4. AIChatService
5. AIToolRouter
6. User Assistant tools
7. Root Master AI tools
8. Incident report system
9. Server health monitor
10. File organization plan system
11. ai_chat_sessions migration
12. ai_chat_messages migration
13. ai_tool_calls migration
14. ai_incident_reports migration
15. ai_system_monitor_snapshots migration
16. ai_knowledge_docs migration
17. /api/ai-chat/*
18. /api/root/ai/*
19. /ai-chat UI
20. /root/ai dashboard
21. tests
22. docs/ai_chat_system_design.md
23. docs/root_master_ai_monitoring.md
24. docs/ai_tool_security_model.md
```

---

# Part Q — 完成後回報格式

請用以下格式回報：

```text
# hackme_web AI Chat + Root Master AI 完成摘要

## 已完成
-

## AI Provider
-

## 新增資料表
-

## 新增 Service
-

## 新增 Tool
-

## User AI 功能
-

## Root Master AI 功能
-

## Incident 上報
-

## 檔案整理功能
-

## 安全限制
-

## 測試結果
-

## 尚未完成
-

## 需要 root 人工確認
-

## 建議下一階段
-
```

---

# Part R — 最高提醒

此系統的核心不是單純聊天，而是：

```text
一般用戶有安全受限的 AI 助手
root 有主 AI 監控全站安全與健康
所有 AI 工具都有權限邊界
所有高危操作都需要確認
所有異常行為可上報
AI 不可繞過審計、權限與資料隔離
```

請以「安全、可審計、可控」為最高原則。
