# AI-managed Web Research

> Status: research proposal. Docs-only. Implementation is not authorized until root approves a specific phase.
> Canonical folder: `docs/AGENTS/research/AI_manage_WEB/`.

This folder evaluates a semi-autonomous AI management layer for `hackme_web`.
It builds on [LLM_WEBCHAT](../LLM_WEBCHAT/) and should not create a separate
agent stack.

## Conclusion

Feasibility: **7.5 / 10**

Recommended implementation level: **semi-autonomous operations**, not autonomous
site administration.

The site already has the right foundations: roles/RBAC, admin panels, audit,
server modes, snapshots, security gates, forum/chat/cloud drive/points/trading
modules, and the proposed LLM WebChat tool-policy layer. The main blocker is not
LLM capability; it is safety, auditability, confirmation, and correctly scoped
tools.

## What "Semi-autonomous" Means

AI can:

- observe dashboards and logs
- summarize status
- suggest actions
- create drafts
- prepare previews
- run allowlisted read-only checks
- queue low-risk tasks
- create pending actions for human approval

AI cannot:

- self-confirm high-risk actions
- bypass RBAC
- execute shell
- run raw SQL
- restore snapshots
- reset server
- approve integrity manifests
- run pentest directly
- change its own policy

## Document Map

| File | Purpose |
|---|---|
| [FEASIBILITY_REPORT.md](FEASIBILITY_REPORT.md) | Feasibility score, current project fit, blockers |
| [OPERATING_MODEL.md](OPERATING_MODEL.md) | Autonomy levels, roles, and approved management actions |
| [ARCHITECTURE.md](ARCHITECTURE.md) | System architecture on top of LLM_WEBCHAT |
| [ROADMAP.md](ROADMAP.md) | Phase plan and MVP recommendation |
| [SAFETY_POLICY.md](SAFETY_POLICY.md) | Permission, confirmation, prompt-injection, and kill-switch policy |
| [CURRENT_REPO_RECONCILIATION.md](CURRENT_REPO_RECONCILIATION.md) | Existing route/module boundaries and namespace rules |
| [AI_MANAGEMENT_DEPENDENCY_GATES.md](AI_MANAGEMENT_DEPENDENCY_GATES.md) | Required LLM_WEBCHAT foundations before each AI Management phase |
| [AI_MANAGEMENT_SERVER_MODE_MATRIX.md](AI_MANAGEMENT_SERVER_MODE_MATRIX.md) | Server Mode behavior by capability |
| [AI_MANAGEMENT_SCHEMA.md](AI_MANAGEMENT_SCHEMA.md) | Dashboard, recommendation, evidence, risk-card, and note tables |
| [AI_MANAGEMENT_ACTION_POLICY.md](AI_MANAGEMENT_ACTION_POLICY.md) | Action classes, blocked operations, and confirmation boundary |
| [AI_MANAGEMENT_EVIDENCE_MODEL.md](AI_MANAGEMENT_EVIDENCE_MODEL.md) | Evidence fields, sensitivity, redaction, and TTL rules |
| [AI_MANAGEMENT_TOOL_CATALOG.md](AI_MANAGEMENT_TOOL_CATALOG.md) | Read-only V1 tool catalog using the LLM_WEBCHAT tool schema shape |
| [AI_MANAGEMENT_API_CONTRACT.md](AI_MANAGEMENT_API_CONTRACT.md) | `/api/ai/management/*` API behavior spec |
| [AI_MANAGEMENT_DOMAIN_PLAYBOOKS.md](AI_MANAGEMENT_DOMAIN_PLAYBOOKS.md) | Domain-specific V1 allowed/blocked actions |
| [TEST_AND_ACCEPTANCE.md](TEST_AND_ACCEPTANCE.md) | QA, security, e2e, and acceptance gates |
| [SCAFFOLD_MANIFEST.md](SCAFFOLD_MANIFEST.md) | Files that can be pre-created when implementation starts |

## MVP Recommendation

First version should support:

1. AI operations overview dashboard.
2. Read-only status summaries.
3. Suggested remediation plans.
4. Evidence-backed recommendations.
5. Full audit trail for reads/recommendations.
6. Mobile-safe management console.

Do not include in MVP:

- pending-action execution
- confirmed medium-risk execution
- `snapshot.create`
- moderation actions
- points adjustment
- trading action
- root/admin automation

Do not start with autonomous root/admin actions.
