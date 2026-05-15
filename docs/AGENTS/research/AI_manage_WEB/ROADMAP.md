# Roadmap

## Phase 0: Spec Reconciliation

Goal:

- align with `LLM_WEBCHAT`
- define autonomy levels
- identify read-only management tools
- decide first domains
- define current repo boundaries
- define dependency gates
- define evidence model
- define schema, action policy, API behavior, and domain playbooks

Exit gate:

- docs reviewed
- no implementation code
- root approves Phase 1 candidate
- LLM_WEBCHAT read-only registry/executor/audit dependency gate is satisfied

## Phase 1: Read-only AI Management Console

Goal:

- operations overview
- domain health cards
- read-only summaries
- evidence links

Scope:

- server mode status
- audit summary
- snapshot summary
- forum/community summary
- points/economy summary
- trading risk/audit summary

No writes.

Exit gate:

- all tools read-only
- no private data leaks
- mobile UI works
- audit records all AI reads

## Phase 2: Recommendations

Goal:

- AI suggests remediation
- every recommendation includes evidence

Allowed:

- moderation recommendation
- snapshot recommendation
- server mode / security checklist recommendation
- Discord queue summary after Discord outbound MVP

Exit gate:

- recommendations have evidence
- evidence is permission-scoped and redacted
- prompt injection tests pass

## Phase 3: Draft / Preview

Goal:

- AI creates drafts/previews only

Allowed:

- forum draft
- admin note draft
- cloud drive folder preview
- no publish

Exit gate:

- dry-run proves no DB mutation unless explicitly allowed
- draft actions are auditable
- expected changes are visible

## Phase 4: Pending-action Queue View

Goal:

- display and group `ai_agent_actions`
- allow cancellation through agent action service
- no direct high-risk execution

Blocked:

- `snapshot.create` execution by AI Management
- snapshot.restore
- server.reset
- shell.exec
- security.run_pentest
- integrity.approve_manifest

Exit gate:

- AI Management does not own action state
- cancellation writes audit
- confirmation is delegated to `/api/ai/agent/confirm`

## Phase 5: Confirmed Low/Medium User-owned Actions

Goal:

- allow narrow confirmed low/medium user-owned actions after LLM_WEBCHAT
  confirmation system is mature

Still blocked:

- high-risk production execution
- critical tools
- `snapshot.create` execution
- root/admin automation

## Phase 6: Domain Expansion

Goal:

- integrate more platform domains after Phase 1-5 prove safe

Candidates:

- Discord sync queue summary
- PointsChain readiness summary
- trading bot audit recommendations
- cloud drive security triage
- forum moderation queue assistance

Exit gate:

- each domain has tool policy
- each domain has tests
- no direct service bypass

## Phase 7: Controlled Automation Windows

Goal:

- allow narrow automation windows for low-risk routine tasks

Examples:

- nightly summary generation
- stale draft cleanup suggestion
- queue failure grouping
- report generation

Still not allowed:

- autonomous root actions
- autonomous user-impacting sanctions
- autonomous money/points mutation
- autonomous snapshot restore
