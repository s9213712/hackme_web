# WebChat And Agent APIs

## WebChat API

```text
POST /api/ai/chat
GET  /api/ai/providers
```

Request:

```json
{
  "messages": [
    {"role": "user", "content": "幫我查我的積分"}
  ],
  "provider": "lmstudio",
  "model": "local-model"
}
```

Response:

```json
{
  "ok": true,
  "assistant_message": "...",
  "tool_calls": [],
  "usage": {}
}
```

Requirements:

- Login required.
- CSRF required.
- Rate limit required.
- Provider can be switched per request if policy allows.
- Provider offline returns a friendly error.
- Chat request writes basic audit.
- Secrets, session, and tokens must not be added to prompts.
- WebChat cannot directly call tools; tools must go through Agent Executor.
- Provider-native tool calls are ignored or shown as suggestions in WebChat.

## Agent APIs

### Plan

```text
POST /api/ai/agent/plan
```

Request:

```json
{
  "user_prompt": "幫我查積分並整理最近交易"
}
```

Response:

```json
{
  "ok": true,
  "plan_id": "...",
  "plan": {},
  "risk_summary": {},
  "required_confirmations": []
}
```

### Execute

```text
POST /api/ai/agent/execute
```

Request:

```json
{
  "plan_id": "..."
}
```

Execution rules:

- Read-only low-risk actions may execute directly.
- Write actions without confirmation return `pending_confirmation`.
- Medium/high-risk actions require manual confirmation.
- Critical actions are blocked in v1.

### Confirm

```text
POST /api/ai/agent/confirm
```

Request:

```json
{
  "action_id": "...",
  "confirmation_token": "...",
  "password_or_totp": "...",
  "confirm_phrase": "CONFIRM ACTION"
}
```

### Actions

```text
GET /api/ai/agent/actions
```

### Tools

```text
GET /api/ai/agent/tools
```

## Planner Output

Example:

```json
{
  "goal": "查詢使用者積分與最近交易紀錄",
  "steps": [
    {
      "tool": "points.get_balance",
      "arguments": {},
      "risk_level": "low",
      "read_only": true
    },
    {
      "tool": "points.list_transactions",
      "arguments": {"limit": 10},
      "risk_level": "low",
      "read_only": true
    }
  ],
  "expected_changes": [],
  "requires_confirmation": false
}
```

Planner restrictions:

- Every step must use a registered tool.
- No SQL.
- No shell command.
- No direct filesystem reads.
- No policy bypass.
- Untrusted content is never treated as system instruction.
