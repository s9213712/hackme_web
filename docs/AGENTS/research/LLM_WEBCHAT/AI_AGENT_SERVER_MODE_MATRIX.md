# AI Agent Server Mode Matrix

| Mode | WebChat | Read-only tools | Draft tools | Write tools | High-risk | Critical |
|---|---:|---:|---:|---:|---:|---:|
| `production` | on | on | preview only | confirmation only | pending only | blocked |
| `internal_test` | on | on | shadow only | shadow only | pending only | blocked |
| `test` | on | on | on | isolated only | pending only | blocked |
| `dev_ready` | on | limited | limited | off by default | blocked | blocked |
| `maintenance` | root only | root status only | off | off | off | blocked |
| `incident_lockdown` | root only | rescue status only | off | off | off | blocked |
| `superweak` | off recommended | off | off | off | off | blocked |

## Rules

1. Non-production tools must not mutate production data.
2. Internal/test modes use shadow or isolated scopes.
3. Maintenance pauses write execution.
4. Incident lockdown disables all writes and permits root status inspection only.
5. Superweak disables AI Agent.
6. Critical tools are blocked in every mode for v1.

## Production Defaults

```text
AI_AGENT_ALLOW_WRITE_TOOLS=false
AI_AGENT_ALLOW_HIGH_RISK=false
AI_AGENT_ALLOW_CRITICAL=false
AI_AGENT_REQUIRE_CONFIRMATION=true
AI_AGENT_PRODUCTION_SAFE_MODE=true
```
