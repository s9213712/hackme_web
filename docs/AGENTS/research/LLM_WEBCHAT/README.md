# LLM WebChat / AI Agent Platform Control

> Status: research proposal. Docs-only. Implementation is not authorized until root approves a specific phase.
> Canonical folder: `docs/AGENTS/research/LLM_WEBCHAT/`.

This folder defines the proposed WebChat + local LLM + AI Agent control layer for
`hackme_web`. The goal is to upgrade the site into an AI-assisted platform
control system, not just add a chat widget.

The first version must stay conservative:

- AI can chat, suggest, query, draft, and preview.
- AI cannot self-escalate privileges.
- AI cannot confirm high-risk actions.
- AI cannot execute shell, raw SQL, raw Python, snapshot restore, server reset,
  pentest, or integrity approval.
- Every tool call must pass backend policy checks and audit logging.

## Document Map

| File | Purpose |
|---|---|
| [CURRENT_REPO_RECONCILIATION.md](CURRENT_REPO_RECONCILIATION.md) | Avoid route/API/frontend naming conflicts with existing chat |
| [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md) | Phase 1-20 execution plan and MVP order |
| [ARCHITECTURE.md](ARCHITECTURE.md) | System architecture, proposed modules, and file scaffold |
| [LLM_ADAPTERS.md](LLM_ADAPTERS.md) | Ollama / LM Studio adapter response shape and config |
| [AGENT_API.md](AGENT_API.md) | WebChat and Agent HTTP API proposal |
| [TOOL_POLICY.md](TOOL_POLICY.md) | Tool registry, risk levels, allowed tools, and policy rules |
| [TOOL_SCHEMA_SPEC.md](TOOL_SCHEMA_SPEC.md) | Tool input/output schema shape and sensitive read-only risks |
| [DATA_BOUNDARY.md](DATA_BOUNDARY.md) | Data classification for what can be sent to LLM providers |
| [PROVIDER_SECURITY.md](PROVIDER_SECURITY.md) | Provider URL, SSRF, model allowlist, and tool-call safety |
| [AI_AGENT_SCHEMA.md](AI_AGENT_SCHEMA.md) | Proposed chat, plan, action, confirmation, and memory tables |
| [AGENT_ACTION_STATE_MACHINE.md](AGENT_ACTION_STATE_MACHINE.md) | Plan/preview/confirm/execute action lifecycle |
| [AI_AGENT_SERVER_MODE_MATRIX.md](AI_AGENT_SERVER_MODE_MATRIX.md) | Server Mode v2 behavior matrix for AI tools |
| [AI_USAGE_QUOTA.md](AI_USAGE_QUOTA.md) | Quota, context, timeout, and future billing boundaries |
| [SECURITY_AUDIT_MEMORY.md](SECURITY_AUDIT_MEMORY.md) | Prompt-injection defense, audit log, confirmation, memory |
| [FRONTEND_MOBILE.md](FRONTEND_MOBILE.md) | WebChat, Agent Console, and responsive mobile UI |
| [TEST_PLAN.md](TEST_PLAN.md) | Unit, integration, injection, audit, and mobile e2e tests |
| [SCAFFOLD_MANIFEST.md](SCAFFOLD_MANIFEST.md) | Files that can be pre-created when implementation starts |

## MVP Recommendation

Implement in this order:

0. Current repo reconciliation: use `routes/ai_chat.py`, `routes/ai_agent.py`, and `/api/ai/*`.
1. LLM Adapter Layer.
2. WebChat API and UI without tools.
3. Tool registry + policy engine with read-only tools only.
4. Agent planner/executor for read-only plans.
5. Draft/preview low-risk write tools.
6. Confirmation system before any medium/high-risk write execution.

Do not enable critical tools in v1.
