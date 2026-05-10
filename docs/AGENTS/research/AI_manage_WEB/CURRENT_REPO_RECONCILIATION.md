# Current Repo Reconciliation

AI Management is an operations layer on top of LLM_WEBCHAT. It must fit current
`hackme_web` modules and must not replace existing admin, chat, security, or
agent routes.

## Existing Boundaries

- `routes/chat.py` is the existing social chat / direct-message route.
- `routes/ai_chat.py` and `routes/ai_agent.py` belong to LLM_WEBCHAT.
- AI Management uses `routes/ai_management.py`.
- API namespace is `/api/ai/management/*`.
- Existing Security Center, Server Mode, Snapshot/Restore, and admin pages stay
  authoritative for their native workflows.
- AI Management does not own low-level domain writes.

## Forbidden Shortcuts

Do not:

- call raw DB directly
- execute shell
- read arbitrary server files
- bypass `services/agent/*`
- bypass registered tool policy
- bypass confirmation system
- overwrite Security Center or Server Mode root UI
- create a separate action/confirmation queue
- mutate PointsChain, trading, snapshot, Discord Sync, or user management state
  outside allowlisted backend tools

## Required Namespace

```text
services/ai_management/
routes/ai_management.py
public/js/ai_management.js
public/css/ai_management.css
/api/ai/management/*
```

Use underscores in static file names to match existing AI namespace style.
