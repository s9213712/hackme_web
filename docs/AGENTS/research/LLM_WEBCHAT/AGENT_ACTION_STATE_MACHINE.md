# Agent Action State Machine

## States

```text
planned
policy_checked
preview_ready
pending_confirmation
confirmed
executing
succeeded
failed
cancelled
expired
blocked
```

## Transitions

```text
planned -> policy_checked
policy_checked -> executing              read-only low-risk only
policy_checked -> preview_ready          write dry-run / preview
preview_ready -> pending_confirmation    medium/high-risk or write action
pending_confirmation -> confirmed        human confirmation only
confirmed -> executing                   policy re-check required
executing -> succeeded
executing -> failed
planned/policy_checked/preview_ready/pending_confirmation -> cancelled
planned/policy_checked/preview_ready/pending_confirmation -> expired
any -> blocked                           policy violation, payload mismatch, critical tool
```

## Rules

1. `planned -> executing` is allowed only for read-only low-risk tools.
2. Write, medium-risk, and high-risk tools must pass through preview or pending confirmation.
3. `pending_confirmation -> confirmed` requires manual user action.
4. Before `confirmed -> executing`, rerun policy.
5. Payload hash mismatch blocks action.
6. Expired action cannot be restored.
7. Cancelled action cannot be restored.
8. Critical tools are always blocked in v1.
9. Confirmation token is single-use.
10. Executor must be idempotent where possible.

## Replay Defense

Executor must reject:

- reused confirmation token
- stale plan ID
- expired action
- action payload hash mismatch
- tool policy version mismatch
- action already succeeded
