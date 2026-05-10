# Discord Sync API And UI

## Root / Admin APIs

```text
GET  /api/root/discord/status
POST /api/root/discord/config
POST /api/root/discord/test-connection
GET  /api/root/discord/policy-checklist
GET  /api/root/discord/rate-limits

GET  /api/admin/discord/bindings
POST /api/admin/discord/bindings
GET  /api/admin/discord/bindings/<binding_uuid>
PATCH /api/admin/discord/bindings/<binding_uuid>
POST /api/admin/discord/bindings/<binding_uuid>/pause
POST /api/admin/discord/bindings/<binding_uuid>/resume
POST /api/admin/discord/bindings/<binding_uuid>/reconcile

GET  /api/admin/discord/sync-events
GET  /api/admin/discord/sync-jobs
POST /api/admin/discord/sync-jobs/<id>/retry
GET  /api/admin/discord/dead-letter
POST /api/admin/discord/dead-letter/<id>/retry
POST /api/admin/discord/dead-letter/<id>/discard
GET  /api/admin/discord/reconciliation
```

## User APIs

```text
GET  /api/discord/link/status
GET  /api/discord/link/start
GET  /api/discord/link/callback
POST /api/discord/link/revoke

GET  /api/discord/dm-sync/options
POST /api/discord/dm-sync/conversations/<conversation_id>/request
POST /api/discord/dm-sync/conversations/<conversation_id>/approve
POST /api/discord/dm-sync/conversations/<conversation_id>/revoke
```

## Internal Gateway Endpoint

If Gateway worker runs as a separate process:

```text
POST /api/internal/discord/events
```

Requirements:

- internal HMAC
- localhost/private network only
- rate limit
- replay nonce
- timestamp window
- payload hash
- redacted payload storage

## Root Settings UI

Add "Discord Integration" panel:

- enable / disable
- bot connection status
- guild ID
- test guild / production guild
- required intents checklist
- Message Content intent warning
- self-bot / user-token prohibition checklist
- OAuth callback state status
- sync mode
- rate limit / queue status
- dead-letter count
- last reconciliation result

MVP UI must make inbound status explicit:

```text
Inbound canonical writes: disabled
DM bridge: disabled
Attachment import: disabled
Role sync: unsupported
```

## Forum Board Admin UI

Add "Sync to Discord":

- select Discord channel / forum channel
- direction
- allow Discord inbound
- unlinked user handling
- attachment policy

## DM UI

Add "Discord private message sync":

- status: disabled / waiting for other user / active / paused
- request sync
- approve sync
- revoke sync
- view Discord bridge link
- consent expiry and revoke history

## UX Defaults

- DM sync is off by default.
- Attachments are off by default.
- Inbound canonical writes are off in MVP.
- Chat room sync is off in MVP.
- Inbound unlinked users go to ignored/review state, not canonical posts.
- Admin UI must show queue failures and dead-letter items.
- Root UI must show when Message Content intent is unavailable.
- Retry/discard dead-letter actions require admin/root and write audit events.
