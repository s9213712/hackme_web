# Discord Sync Rate Limits

## Principle

Do not hard-code Discord route limits. Treat rate limit data from Discord
responses as authoritative for the current request.

The worker must handle:

- per-route bucket pause
- global pause
- retry-after seconds
- exponential fallback retry
- dead-letter after repeated failures

## Queue Fields

`discord_sync_jobs` should track:

```text
rate_limit_bucket
retry_after_seconds
next_run_at
attempts
locked_by
locked_at
dead_lettered_at
```

## Retry Policy

| Attempt | Delay |
|---|---|
| 1 | immediately |
| 2 | 10 seconds |
| 3 | 60 seconds |
| 4 | 5 minutes |
| 5 | 30 minutes |
| after 5 | dead-letter + root alert |

If Discord returns a longer `retry_after`, use the longer value.

## Worker Safety

- Flask request thread must not block on Discord.
- Outbound requests are queued.
- Inbound events are acknowledged quickly and queued.
- Queue processing stops during `maintenance` and `incident_lockdown`.
- Queue processing stops when binding is `paused`, `revoked`, or `error`.

## Idempotency

Every outbound message job must have an idempotency key derived from:

```text
binding_uuid
source_type
web_message_id
event_type
content_hash
```

Retry must resolve existing mapping before sending a new Discord message.
