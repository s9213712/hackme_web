# Scaffold Manifest

This manifest lists implementation files that can be pre-created only after root
authorizes a specific phase. Do not create empty source files during research;
stale placeholders make imports and reviews harder.

## Phase 1: Read-only AI Management

```text
services/ai_management/__init__.py
services/ai_management/dashboard.py
services/ai_management/domain_summary.py
services/ai_management/evidence.py
routes/ai_management.py
public/js/ai_management.js
public/css/ai_management.css
tests/test_ai_management_policy.py
tests/test_ai_management_readonly.py
```

## Phase 2: Recommendations

```text
services/ai_management/recommendations.py
services/ai_management/risk_cards.py
tests/test_ai_management_recommendations.py
tests/test_ai_management_evidence.py
```

## Phase 3: Drafts And Previews

```text
tests/test_ai_management_dry_run.py
```

## Phase 4: Agent Action Queue View

```text
services/ai_management/action_queue.py
tests/test_ai_management_confirmations.py
tests/test_ai_management_audit.py
```

`action_queue.py` must only group/display `ai_agent_actions`. It must not create
an independent action state machine.

## Docs To Promote After Approval

After implementation starts, promote operator-facing docs to normal `docs/`:

```text
docs/AI_MANAGEMENT_CONSOLE.md
docs/AI_MANAGEMENT_SAFETY_POLICY.md
docs/AI_MANAGEMENT_RUNBOOK.md
```

## Files Not Allowed

Do not add:

```text
services/ai_management/shell.py
services/ai_management/raw_sql.py
services/ai_management/self_confirm.py
```

Do not implement v1 execution for:

```text
shell.exec
snapshot.create
snapshot.restore
server.reset
security.run_pentest
integrity.approve_manifest
points.adjust_balance without confirmation
```
