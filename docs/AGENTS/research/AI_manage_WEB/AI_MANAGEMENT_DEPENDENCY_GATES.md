# AI Management Dependency Gates

AI Management must not fork the agent stack. Implementation can start only after
the required LLM_WEBCHAT foundation exists.

## Phase 1 Gate: Read-only Overview

Required before any AI Management implementation:

- LLM adapter layer exists
- tool registry exists
- policy engine exists
- read-only executor exists
- agent audit exists
- data boundary rules exist
- Server Mode matrix exists
- quota/rate-limit rules exist
- provider/tool output redaction exists

If any item is missing, implement it in LLM_WEBCHAT first.

## Phase 2 Gate: Recommendations

Required before recommendations:

- evidence model implemented
- recommendation storage implemented
- read-only tools have output schemas
- sensitive tool outputs are redacted before model/audit exposure
- prompt injection tests pass for tool output and domain content

Discord Sync cards/tools are disabled until DISCORD outbound MVP schema, fake
adapter, queue, mapping, and audit are implemented. AI Management must not
invent its own Discord queue summary.

## Phase 3 Gate: Draft / Preview

Required before draft or preview actions:

- tool schema shape supports dry-run/preview
- each write-capable tool has explicit `read_only=false`
- write tools are disabled by default in production
- audit records expected changes and payload hash

## Phase 4 Gate: Pending-action View

Required before pending-action queue UI:

- `ai_agent_actions` exists
- `ai_agent_confirmations` exists
- action state machine is enforced
- AI Management action queue is a view/wrapper only
- cancel routes call the agent action service

## Blocked Until Later

- high-risk production execution
- autonomous admin/root execution
- `snapshot.create` execution
- `snapshot.restore`
- `server.reset`
- `security.run_pentest`
- `integrity.approve_manifest`
- `points.adjust_balance`
- autonomous trading actions
