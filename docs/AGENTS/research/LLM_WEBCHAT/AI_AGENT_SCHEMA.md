# AI Agent Schema

## Chat Threads

```sql
CREATE TABLE ai_chat_threads (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    thread_uuid TEXT NOT NULL UNIQUE,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title TEXT,
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    archived_at TEXT
);
```

## Chat Messages

```sql
CREATE TABLE ai_chat_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    thread_uuid TEXT NOT NULL REFERENCES ai_chat_threads(thread_uuid) ON DELETE CASCADE,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    role TEXT NOT NULL CHECK (role IN ('system', 'user', 'assistant', 'tool')),
    content_text TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    provider TEXT,
    model TEXT,
    token_usage_json TEXT,
    safety_flags_json TEXT,
    created_at TEXT NOT NULL
);
```

## Agent Plans

```sql
CREATE TABLE ai_agent_plans (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    plan_id TEXT NOT NULL UNIQUE,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    user_prompt_hash TEXT NOT NULL,
    goal_summary TEXT NOT NULL,
    plan_json TEXT NOT NULL,
    risk_summary_json TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'planned'
        CHECK (status IN ('planned', 'executing', 'succeeded', 'failed', 'cancelled', 'expired')),
    expires_at TEXT NOT NULL,
    created_at TEXT NOT NULL
);
```

Plan status is intentionally coarse-grained. It describes the whole plan. The
full action lifecycle is stored on `ai_agent_actions.status`.

## Agent Actions

```sql
CREATE TABLE ai_agent_actions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    action_id TEXT NOT NULL UNIQUE,
    plan_id TEXT REFERENCES ai_agent_plans(plan_id),
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    tool_name TEXT NOT NULL,
    tool_version TEXT NOT NULL,
    policy_version TEXT NOT NULL,
    registry_version TEXT,
    input_hash TEXT NOT NULL,
    input_summary TEXT,
    output_summary TEXT,
    risk_level TEXT NOT NULL CHECK (risk_level IN ('low', 'medium', 'high', 'critical')),
    read_only INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'planned'
        CHECK (status IN (
            'planned',
            'policy_checked',
            'preview_ready',
            'pending_confirmation',
            'confirmed',
            'executing',
            'succeeded',
            'failed',
            'cancelled',
            'expired',
            'blocked'
        )),
    policy_decision_json TEXT NOT NULL,
    confirmation_required INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    executed_at TEXT
);
```

## Confirmations

```sql
CREATE TABLE ai_agent_confirmations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    confirmation_token_hash TEXT NOT NULL UNIQUE,
    action_id TEXT NOT NULL REFERENCES ai_agent_actions(action_id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    tool_name TEXT NOT NULL,
    tool_version TEXT NOT NULL,
    policy_version TEXT NOT NULL,
    action_payload_hash TEXT NOT NULL,
    confirmation_type TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    used_at TEXT,
    created_at TEXT NOT NULL
);
```

Rules:

- Store confirmation token hash only.
- Token is single-use.
- Token is bound to user, action, tool, and payload hash.
- Tool name, tool version, and policy version are duplicated here to prevent
  confirmation reuse under a changed tool context.
- Payload mutation invalidates token.
- Expired action cannot be confirmed.
- AI cannot confirm its own action.

## Memory

```sql
CREATE TABLE ai_agent_memory (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    memory_key TEXT NOT NULL,
    memory_json TEXT NOT NULL,
    scope TEXT NOT NULL DEFAULT 'user',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(user_id, memory_key, scope)
);
```

Memory must never be used as an authorization source.
