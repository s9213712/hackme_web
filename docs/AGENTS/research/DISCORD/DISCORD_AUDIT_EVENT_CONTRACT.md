# Discord Audit Event Spec

Discord Sync audit must be useful for incident review without leaking secrets or
private message plaintext.

## Event Names

```text
DISCORD_ACCOUNT_LINK_STARTED
DISCORD_ACCOUNT_LINKED
DISCORD_ACCOUNT_REVOKED
DISCORD_CONFIG_CHANGED
DISCORD_CONNECTION_TESTED
DISCORD_BINDING_CREATED
DISCORD_BINDING_PAUSED
DISCORD_BINDING_RESUMED
DISCORD_BINDING_REVOKED
DISCORD_OUTBOUND_EVENT_QUEUED
DISCORD_OUTBOUND_SENT
DISCORD_OUTBOUND_FAILED
DISCORD_INBOUND_RECEIVED
DISCORD_INBOUND_IGNORED
DISCORD_INBOUND_WRITTEN
DISCORD_LOOP_GUARD_DROPPED
DISCORD_RATE_LIMIT_APPLIED
DISCORD_JOB_DEAD_LETTERED
DISCORD_RECONCILIATION_RUN
DISCORD_PERMISSION_DRIFT_DETECTED
DISCORD_DM_SYNC_REQUESTED
DISCORD_DM_SYNC_APPROVED
DISCORD_DM_SYNC_REVOKED
DISCORD_OUTPUT_REDACTED
```

## Required Fields

Each event should include:

```text
audit_uuid
actor_user_id
actor_role
discord_user_id
binding_id
binding_uuid
event_uuid
job_id
source_type
source_id
direction
decision
reason
input_hash
output_hash
server_mode
success
created_at
```

## Redaction Rules

Do not store:

- bot token
- webhook token
- OAuth token
- client secret
- signing secret
- HMAC key
- full private message plaintext
- private direct storage path
- secret-bearing CDN or callback URL

Allowed audit content:

- redacted summary
- hash
- source type
- source ID
- policy decision
- failure reason
- queue/dead-letter state
