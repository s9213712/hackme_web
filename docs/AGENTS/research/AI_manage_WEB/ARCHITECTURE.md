# Architecture

AI-managed web is an operations layer on top of
[LLM_WEBCHAT](../LLM_WEBCHAT/). It must not fork the agent stack.

## Layering

```text
AI Management Console
  ├─ Operations dashboard
  ├─ Risk cards
  ├─ Agent action queue view
  ├─ Evidence links
  └─ Mobile single-column mode

Agent Platform Control (LLM_WEBCHAT)
  ├─ LLM adapters
  ├─ Planner
  ├─ Executor
  ├─ Tool registry
  ├─ Policy engine
  ├─ Confirmation system
  ├─ Safety filter
  └─ Audit logger

Platform Domains
  ├─ Forum / Chat / DM
  ├─ Cloud Drive
  ├─ Points / Economy / PointsChain
  ├─ Marketplace
  ├─ Trading / Bot audit
  ├─ Snapshot / Restore
  ├─ Server Mode
  └─ Security gates
```

## New Conceptual Modules

Implementation can later introduce:

```text
services/ai_management/
  __init__.py
  dashboard.py
  domain_summary.py
  risk_cards.py
  action_queue.py
  recommendations.py
  evidence.py
```

These modules should call `services/agent/*` and registered tools. They should
not talk directly to LLM providers, raw DB, shell, or private service internals.
`action_queue.py` is only a view/grouping wrapper over LLM_WEBCHAT
`ai_agent_actions`; it does not own action state, confirmation state, or payload
hash validation.

## Proposed Routes

```text
routes/ai_management.py
```

Suggested APIs:

```text
GET  /api/ai/management/overview
POST /api/ai/management/recommend
GET  /api/ai/management/actions
POST /api/ai/management/actions/<action_id>/cancel
POST /api/ai/management/actions/<action_id>/confirm
GET  /api/ai/management/evidence/<evidence_id>
```

## Proposed Frontend

```text
public/js/ai_management.js
public/css/ai_management.css
```

UI sections:

- global operations summary
- domain health cards
- agent recommendations
- agent action queue view
- audit timeline
- mobile action drawer

## Data Sources

V1 should use existing or proposed safe tools:

- `ai_management.get_overview`
- `server_mode.get_status`
- `production_gate.get_status`
- `snapshot.get_status`
- `snapshot.list_recent`
- `audit.get_summary`
- `points_chain.get_status`
- `trading.get_risk_summary`
- `cloud_drive.get_storage_summary`
- `forum.get_moderation_summary`

If a read-only tool does not exist, add it to the LLM_WEBCHAT tool registry
before AI management consumes it.

## Important Boundary

AI management may aggregate and prioritize, but authorization remains at the
tool level.

```text
dashboard permission != tool permission
recommendation permission != execution permission
root view permission != root execution permission
```
