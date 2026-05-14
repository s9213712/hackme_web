# Current Repo Reconciliation

## Purpose

This file prevents future agents from colliding with existing `hackme_web`
chat features while implementing LLM WebChat / AI Agent.

## Existing Chat Module

The current repository already uses:

```text
routes/chat.py
/api/chat/rooms
```

for the platform's social chat / direct message / chat room / attachment
features. That file is not the LLM WebChat route and must not be replaced.

## Required AI Namespace

Use AI-specific route files:

```text
routes/ai_chat.py
routes/ai_agent.py
```

Use AI-specific API namespace:

```text
POST /api/ai/chat
GET  /api/ai/providers
POST /api/ai/agent/plan
POST /api/ai/agent/execute
POST /api/ai/agent/confirm
GET  /api/ai/agent/actions
GET  /api/ai/agent/tools
```

Do not use:

```text
POST /api/chat
POST /api/agent/*
```

## Frontend Names

Use AI-specific frontend files:

```text
public/js/ai_chat.js
public/js/ai_agent.js
public/css/ai_chat.css
public/css/ai_agent.css
```

Do not overwrite existing social chat frontend files.

## Compatibility Rules

1. Do not modify existing chat-room APIs for LLM WebChat.
2. Do not route LLM prompts through social chat message handlers.
3. Do not share attachment upload paths unless a policy-checked tool wraps them.
4. WebChat cannot execute tools directly; tool execution goes through Agent Executor.
5. Provider tool calls from Ollama / LM Studio are suggestions only unless Agent
   Executor validates them against registry and policy.
