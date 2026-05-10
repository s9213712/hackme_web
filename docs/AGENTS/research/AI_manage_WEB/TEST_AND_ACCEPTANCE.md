# Test And Acceptance

## Required Tests

### Policy

- anonymous cannot access AI management
- normal user cannot use admin/root tools
- admin cannot execute critical root tools
- production mode blocks dangerous tools
- high-risk production execution is disabled in V1
- pending-action view cannot create independent action state
- superweak disables AI management

### Prompt Injection

- forum content cannot override policy
- file content cannot request secret reveal
- Discord bridge content cannot bypass confirmation
- tool output cannot become system instruction

### Audit

- every recommendation has trace id
- every tool call has action id when routed through LLM_WEBCHAT executor
- every recommendation has evidence
- evidence has source hash and redaction status
- no secrets in audit

### Execution

- read-only tools do not mutate DB
- dry-run writes do not mutate DB
- MVP does not execute pending actions
- MVP does not execute `snapshot.create`
- confirmation routes delegate to `/api/ai/agent/confirm`
- AI Management cannot mint confirmation tokens

### UI

Viewport checks:

```text
360x800
390x844
430x932
768x1024
1366x768
```

Checks:

- no horizontal scroll
- risk card visible
- evidence details visible
- action queue view is readable when enabled in a later phase
- audit details fold into `details/summary`
- table/card layout readable

## Acceptance Criteria

V1 is acceptable only if:

1. AI management can summarize site status with evidence links.
2. AI management can run read-only allowlisted tools.
3. AI management can create evidence-backed recommendations.
4. AI management cannot execute pending/high-risk actions directly.
5. Critical actions are blocked.
6. Every recommendation/read has audit.
7. Prompt injection tests pass.
8. Server mode rules are enforced.
9. Mobile UI is usable.
10. Kill switch works.

## Release Blockers

Any of these blocks release:

- direct shell execution
- raw SQL tool
- missing policy check
- missing audit for tool call
- high-risk action execution in V1
- `snapshot.create` execution in V1
- private data leak in prompt or response
- AI can change tool policy
- AI can approve its own pending action
- critical tool executable in production
