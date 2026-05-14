# Discord Sync State Machine

## Binding State

```text
active
paused
revoked
error
```

Transitions:

```text
active -> paused      admin pause, maintenance, incident_lockdown, rate-limit global pause
paused -> active      admin resume after policy re-check
active -> error       repeated job failures, permission drift, missing webhook
error -> paused       admin acknowledges failure
paused -> revoked     admin/root revokes binding
active -> revoked     source deleted or root revokes binding
```

Rules:

- `revoked` is terminal.
- `error` cannot resume directly to `active`; it must pass through `paused`
  after a reconciliation check.
- Any server mode transition into `maintenance` or `incident_lockdown` pauses
  execution without deleting queued jobs.

## Event State

```text
pending
processing
done
failed
ignored
```

Rules:

- `ignored` is used for bot loop guard, unlinked user, blocked user, or inactive
  binding.
- `failed` means processing attempted and failed.
- `done` means the event has no further job work.
- Each event has `idempotency_key` and `payload_hash`.

## Job State

```text
queued
running
done
failed
retry_wait
dead
```

Transitions:

```text
queued -> running
running -> done
running -> failed
failed -> retry_wait
retry_wait -> queued
failed/retry_wait -> dead
```

Rules:

- Worker must acquire job with `locked_by` and `locked_at`.
- Worker must be idempotent; retry cannot create duplicate Discord messages or
  duplicate web replies.
- `dead` requires admin/root visibility.
- Jobs must not run while binding is paused/revoked/error.

## Message Mapping State

Mapping rows are immutable identity links. Delete/edit state is represented by:

```text
deleted_web_at
deleted_discord_at
last_sync_direction
last_synced_at
```

Rules:

- Do not rewrite mapping to point at another Discord message.
- Missing mapping during edit/delete creates a reconciliation item.
- A Discord delete becomes a web tombstone/soft-delete, not a hard delete.

## DM Consent State

```text
pending
approved
revoked
blocked
expired
```

Rules:

- Both users must be `approved`.
- One `revoked` pauses sync.
- One `blocked` pauses sync and prevents automatic resume.
- Expired consent must be re-requested.
