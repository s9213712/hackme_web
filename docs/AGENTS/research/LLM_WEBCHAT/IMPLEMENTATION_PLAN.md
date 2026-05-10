# Implementation Plan

## Goal

Build a WebChat + Ollama / LM Studio + AI Agent control layer that can help users
operate `hackme_web` through safe backend tools.

Target areas:

- forum
- cloud drive
- points system
- marketplace
- trading records
- admin center
- audit logs
- snapshot status
- security checks

The agent must never bypass existing backend authorization.

## Core Principles

1. AI can only operate through backend allowlisted tools.
2. AI cannot execute shell.
3. AI cannot directly access the database.
4. AI cannot self-escalate privileges.
5. AI cannot confirm high-risk operations.
6. Every tool re-checks user role and permissions.
7. Every AI action writes audit logs.
8. Write operations default to dry-run / preview.
9. High / critical risk operations require human confirmation.
10. Production mode disables dangerous tools.
11. User content, files, posts, comments, and tool output are untrusted content.
12. Prompt injection cannot change system policy.
13. Desktop, tablet, and mobile UI must be supported.

## Phase Order

| Phase | Name | Status Rule |
|---|---|---|
| 0 | Docs reconciliation | `/api/ai/*`, `routes/ai_chat.py`, `routes/ai_agent.py`, data boundary, schema, mode matrix |
| 1 | LLM Adapter Layer | Ollama / LM Studio; no tools |
| 2 | AI WebChat | `/api/ai/chat`, providers, basic UI; no tools |
| 3 | Tool Registry + Policy Engine | Read-only tools only |
| 4 | Read-only Agent Planner | Plan only; registry tools only |
| 5 | Read-only Executor | Safe read-only tool execution |
| 6 | Audit + Action Log | Plan/action audit required |
| 7 | Draft / Preview Low-risk Tools | No direct publishing |
| 8 | Confirmation System | Token, TTL, payload hash binding |
| 9 | Medium-risk Tools | Confirmation required |
| 10 | Mobile / E2E / Injection Acceptance | Release gate |

## Recommended MVP

The first real implementation should stop at:

- WebChat with Ollama / LM Studio provider switching.
- Agent plan generation.
- Read-only tools.
- Draft / preview low-risk actions.
- Manual confirmation flow for medium-risk actions.

Do not start with:

- `snapshot.restore`
- `server.reset`
- `security.run_pentest`
- `integrity.approve_manifest`
- `shell.exec`
- direct `snapshot.create` execution in v1; prefer `snapshot.status` and `snapshot.list` first

## Safe Defaults

```text
AI_AGENT_ENABLED=true
AI_AGENT_ALLOW_WRITE_TOOLS=false
AI_AGENT_ALLOW_HIGH_RISK=false
AI_AGENT_ALLOW_CRITICAL=false
AI_AGENT_REQUIRE_CONFIRMATION=true
AI_AGENT_PRODUCTION_SAFE_MODE=true
```

In production:

- Critical tools are disabled.
- `shell.exec` is forbidden.
- `security.run_pentest` is forbidden.
- `snapshot.restore` is forbidden.
- `server.reset` is forbidden.
- `integrity.approve_manifest` is forbidden.
- High-risk tools can only create pending actions.
