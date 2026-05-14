# AI Management Schema

AI Management stores dashboard, recommendation, evidence, risk-card, and note
state. It does not own action execution state.

## Dashboards

```sql
CREATE TABLE ai_management_dashboards (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    dashboard_uuid TEXT NOT NULL UNIQUE,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    server_mode TEXT NOT NULL,
    scope TEXT NOT NULL,
    summary_json TEXT NOT NULL,
    generated_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    created_at TEXT NOT NULL
);
```

## Recommendations

```sql
CREATE TABLE ai_management_recommendations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    recommendation_uuid TEXT NOT NULL UNIQUE,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    domain TEXT NOT NULL,
    title TEXT NOT NULL,
    summary TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'open'
        CHECK (status IN ('open', 'dismissed', 'accepted', 'expired')),
    confidence TEXT NOT NULL
        CHECK (confidence IN ('low', 'medium', 'high')),
    risk_level TEXT NOT NULL
        CHECK (risk_level IN ('low', 'medium', 'high', 'critical')),
    action_policy TEXT NOT NULL,
    agent_action_id TEXT,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL
);
```

## Evidence

```sql
CREATE TABLE ai_management_evidence (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    evidence_uuid TEXT NOT NULL UNIQUE,
    recommendation_uuid TEXT REFERENCES ai_management_recommendations(recommendation_uuid),
    actor_user_id INTEGER REFERENCES users(id),
    source_tool_name TEXT NOT NULL,
    source_tool_version TEXT NOT NULL,
    source_result_hash TEXT NOT NULL,
    source_timestamp TEXT NOT NULL,
    server_mode TEXT NOT NULL,
    permission_context_json TEXT NOT NULL,
    sensitivity_level TEXT NOT NULL,
    redaction_status TEXT NOT NULL,
    confidence TEXT NOT NULL
        CHECK (confidence IN ('low', 'medium', 'high')),
    summary TEXT NOT NULL,
    link_target TEXT,
    created_at TEXT NOT NULL
);
```

## Indexes

```sql
CREATE INDEX idx_ai_mgmt_evidence_recommendation
    ON ai_management_evidence(recommendation_uuid);

CREATE INDEX idx_ai_mgmt_evidence_source_hash
    ON ai_management_evidence(source_tool_name, source_result_hash);

CREATE INDEX idx_ai_mgmt_evidence_server_mode
    ON ai_management_evidence(server_mode, created_at);

CREATE INDEX idx_ai_mgmt_recommendations_user_status
    ON ai_management_recommendations(user_id, status, expires_at);
```

## Risk Cards

```sql
CREATE TABLE ai_management_risk_cards (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    risk_card_uuid TEXT NOT NULL UNIQUE,
    domain TEXT NOT NULL,
    severity TEXT NOT NULL CHECK (severity IN ('info', 'low', 'medium', 'high', 'critical')),
    title TEXT NOT NULL,
    summary TEXT NOT NULL,
    related_recommendation_uuid TEXT REFERENCES ai_management_recommendations(recommendation_uuid),
    related_action_id TEXT,
    created_at TEXT NOT NULL,
    expires_at TEXT
);
```

## Operator Notes

```sql
CREATE TABLE ai_management_operator_notes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    note_uuid TEXT NOT NULL UNIQUE,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    domain TEXT NOT NULL,
    body TEXT NOT NULL,
    related_recommendation_uuid TEXT,
    related_action_id TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
```

## Non-goal

Do not create separate tables for action execution, confirmation tokens, or
action state. Use LLM_WEBCHAT's `ai_agent_actions` and
`ai_agent_confirmations`.
