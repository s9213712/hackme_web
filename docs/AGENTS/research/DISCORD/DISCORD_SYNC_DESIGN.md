# Discord Sync Design

## Goal

Build controlled synchronization between `hackme_web` and Discord for:

1. Forum.
2. Chat rooms.
3. Direct messages, only through explicit opt-in private bridge.

Recommended phase order:

| Phase | Scope |
|---|---|
| 0 | Docs hardening, repo reconciliation, config, mode, OAuth, intents, formatting, permission, attachments, audit |
| 1 | Schema, fake adapter, queue, mapping, audit |
| 2 | Discord account linking and root/admin config |
| 3 | Forum outbound mirror only |
| 4 | Discord inbound to Forum for linked users only |
| 5 | Chat room controlled outbound/inbound |
| 6 | Private DM opt-in bridge |
| 7 | Attachments, reactions, reconciliation |

Implementation must first pass the official-policy checklist in
[DISCORD_POLICY_REFERENCES.md](DISCORD_POLICY_REFERENCES.md). If Discord
Message Content intent is unavailable, inbound content sync stays disabled and
the first implementation remains outbound-only or inbound-review without
canonical writes.

## Non-goals For V1

Do not implement:

- stealing or mirroring user-to-user native Discord DMs
- self-bot automation
- large Discord server history backfill
- Discord role auto-mapping to `hackme_web` roles
- automatic private E2EE attachment sync
- multi-guild federation
- PointsChain paid DM / tipping sync

## Source Of Truth

`hackme_web` DB is canonical.

Discord messages are mirror copies. The sync system records both sides in
mapping tables and can retry, replay, reconcile, or tombstone Discord failures
without losing canonical `hackme_web` state.

Benefits:

1. `hackme_web` permissions, blocking, soft-delete, and moderation remain valid.
2. Discord API failure does not lose site data.
3. Sync jobs can be retried safely.
4. Server Mode v2 boundaries can be enforced.

## Architecture

```text
hackme_web
  ├─ Forum / Chat / DM services
  ├─ DiscordSyncService
  │    ├─ Outbound Dispatcher
  │    ├─ Inbound Event Handler
  │    ├─ Mapping Resolver
  │    ├─ Permission Guard
  │    ├─ Rate Limit Queue
  │    └─ Reconciliation Worker
  │
  ├─ SQLite tables
  │    ├─ discord_accounts
  │    ├─ discord_oauth_states
  │    ├─ discord_sync_bindings
  │    ├─ discord_sync_events
  │    ├─ discord_message_mappings
  │    ├─ discord_sync_jobs
  │    └─ discord_sync_audit_logs
  │
  └─ Discord Adapter
       ├─ REST API client
       ├─ Webhook sender
       ├─ Gateway listener
       └─ OAuth2 account linking

Discord
  ├─ Bot
  ├─ Webhooks
  ├─ Text channels
  ├─ Forum channels / threads
  └─ Private bridge channels / bot-mediated DM
```

## Outbound Model

When a site event occurs:

1. Original Forum / Chat / DM table is written first.
2. A `discord_sync_events` row is created.
3. A `discord_sync_jobs` row is queued.
4. Worker picks up job.
5. Worker checks binding, permission, server mode, and rate limit.
6. Worker checks the binding state machine and `server_mode_scope`.
7. Worker calls Discord webhook or bot REST API.
8. Worker writes `discord_message_mappings`.
9. Job status is updated.

Requests should not synchronously wait on Discord API calls.

MVP is outbound-only for forum content. Chat room outbound, inbound
canonical writes, DM bridge, attachment import, reactions, and bidirectional
edit/delete sync are later phases.

## Inbound Model

When Discord event arrives:

1. Bot Gateway receives create / update / delete event.
2. Channel/thread is resolved to a sync binding.
3. Bot's own mirror messages are ignored.
4. Discord user must be linked to an active `hackme_web` user.
5. Raw payload is hashed and redacted before audit summary storage.
6. `hackme_web` permissions, board permissions, and block lists are checked.
7. Message Content intent availability is checked.
8. Message is written to Forum / Chat / DM only if policy allows it.
9. Mapping and audit logs are written.

Unlinked Discord users should not directly write into canonical Forum/Chat/DM in
the first version.

Inbound implementation must follow:

- [DISCORD_SYNC_STATE_MACHINE.md](DISCORD_SYNC_STATE_MACHINE.md)
- [DISCORD_SYNC_PRIVACY_BOUNDARY.md](DISCORD_SYNC_PRIVACY_BOUNDARY.md)
- [DISCORD_SYNC_RATE_LIMITS.md](DISCORD_SYNC_RATE_LIMITS.md)

## Server Mode Behavior

| Server mode | Discord sync behavior |
|---|---|
| `production` | Enabled only by root config |
| `dev_ready` | Default off; fake adapter allowed |
| `test` | Isolated Discord test guild only |
| `internal_test` | Shadow binding only; no production Forum/DM writes |
| `maintenance` | Pause outbound and inbound queues |
| `incident_lockdown` | Pause all sync; root can inspect queue |
| `superweak` | Off |

Suggested settings:

```text
feature_discord_sync_enabled
discord_sync_mode = off | outbound_only | inbound_review | two_way
discord_sync_allow_dm = false
discord_sync_allow_attachments = false
discord_sync_require_account_link = true
```

Each binding records `server_mode_scope`:

```text
production   -> may write only production data after root enables sync
test_guild   -> may write only isolated test data
shadow       -> may not write production Forum/Chat/DM rows
```

Mode transitions into `maintenance` or `incident_lockdown` pause bindings and
queued jobs. Resume must re-check the binding policy version and current Discord
permissions before processing stored jobs.
