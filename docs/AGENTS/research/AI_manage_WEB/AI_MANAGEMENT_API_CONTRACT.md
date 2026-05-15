# AI Management API Behavior Spec

AI Management APIs live under the existing AI namespace.

## Routes

```text
GET  /api/ai/management/overview
POST /api/ai/management/recommend
GET  /api/ai/management/actions
POST /api/ai/management/actions/<action_id>/cancel
POST /api/ai/management/actions/<action_id>/confirm
GET  /api/ai/management/evidence/<evidence_id>
```

Do not use `/api/ai-management/*`.

## Overview

```text
GET /api/ai/management/overview
```

Returns dashboard summary, domain health cards, and evidence references scoped
to the current user and server mode.

## Recommend

```text
POST /api/ai/management/recommend
```

Creates recommendations from read-only tools. V1 does not execute actions.

## Actions

```text
GET /api/ai/management/actions
```

Returns a grouped view of `ai_agent_actions`. AI Management does not own action
state.

Cancel:

```text
POST /api/ai/management/actions/<action_id>/cancel
```

Delegates to the agent action service.

Confirm:

```text
POST /api/ai/management/actions/<action_id>/confirm
```

Not implemented in MVP. In a later phase, this is only a UI pass-through that
delegates to `/api/ai/agent/confirm` after the LLM_WEBCHAT confirmation system
exists. AI Management must not create or validate confirmation tokens itself.

## Evidence

```text
GET /api/ai/management/evidence/<evidence_id>
```

Returns redacted evidence only if the current user is allowed to see the source
tool output.
