# AI Management Action Policy

AI Management classifies recommendations and UI actions. The underlying
permission decision still comes from LLM_WEBCHAT policy engine and tool policy.

## Action Classes

```text
explain_only
read_only
draft_only
preview_only
pending_only
confirmed_execute
blocked
```

## V1 Policy

Allowed in V1:

- `explain_only`
- `read_only`
- `draft_only`
- `preview_only`
- `pending_only` for selected medium/high recommendations

Blocked in V1:

- high-risk production execution
- critical execution
- autonomous admin/root execution
- AI calling confirm endpoint
- AI generating confirmation token
- AI changing risk classification
- AI changing tool policy

## Snapshot Policy

```text
snapshot.status     -> read_only
snapshot.list       -> read_only
snapshot.recommend  -> explain_only / pending_only recommendation
snapshot.create     -> pending_only in V1, not executable by AI Management
snapshot.restore    -> blocked
server.reset        -> blocked
```

V1 may recommend a snapshot and create a root-visible pending item only if the
agent action system supports it. Actual snapshot creation must happen through
the native root-safe flow or a later approved phase.

## Confirmation Boundary

`POST /api/ai/management/actions/<action_id>/confirm` is a UI pass-through to
the agent confirmation system. AI Management does not mint or validate
confirmation tokens itself.
