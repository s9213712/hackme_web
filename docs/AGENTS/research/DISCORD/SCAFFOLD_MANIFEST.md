# Scaffold Manifest

This manifest lists files that can be pre-created after root authorizes a
specific implementation phase. Do not create empty implementation modules before
then; stale placeholders make imports, review, and ownership unclear.

## Docs To Promote After Approval

```text
docs/discord_sync/DISCORD_SYNC_DESIGN.md
docs/discord_sync/DISCORD_SYNC_SECURITY.md
docs/discord_sync/DISCORD_SYNC_QA.md
docs/discord_sync/DISCORD_SYNC_API.md
docs/discord_sync/CURRENT_REPO_RECONCILIATION.md
docs/discord_sync/DISCORD_SYNC_SERVER_MODE_MATRIX.md
docs/discord_sync/DISCORD_PROVIDER_CONFIG.md
docs/discord_sync/DISCORD_OAUTH_SECURITY.md
docs/discord_sync/DISCORD_GATEWAY_INTENTS.md
docs/discord_sync/DISCORD_CONTENT_FORMATTING.md
docs/discord_sync/DISCORD_PERMISSION_MAPPING.md
docs/discord_sync/DISCORD_ATTACHMENT_POLICY.md
docs/discord_sync/DISCORD_AUDIT_EVENT_CONTRACT.md
```

Until implementation is approved, keep the canonical proposal in:

```text
docs/AGENTS/research/DISCORD/
```

## Phase 1: Schema And Fake Adapter

```text
services/discord_sync/__init__.py
services/discord_sync/schema.py
services/discord_sync/adapter.py
services/discord_sync/queue.py
tests/test_discord_sync_schema.py
tests/test_discord_sync_rate_limits.py
```

Pre-create when schema, fake adapter, queue, mapping, and audit work starts.

## Phase 2: Account Linking And Root Config

```text
services/discord_sync/service.py
services/discord_sync/oauth.py
routes/discord_sync.py
tests/test_discord_sync_oauth.py
tests/test_discord_sync_config.py
```

Pre-create only after root approves account linking and config work.

## Phase 3: Forum Outbound Sync

```text
services/discord_sync/permissions.py
services/discord_sync/formatter.py
tests/test_discord_sync_outbound.py
tests/test_discord_sync_permissions.py
tests/test_discord_sync_formatting.py
```

MVP implementation stops here. No inbound canonical writes, chat two-way, DM
bridge, attachment import, reaction sync, role sync, or history backfill.

## Phase 4: Inbound Forum Sync

```text
services/discord_sync/gateway.py
tests/test_discord_sync_inbound.py
tests/test_discord_sync_state_machine.py
tests/test_discord_sync_privacy_boundary.py
```

Pre-create when Gateway worker / fake Gateway tests are ready.

## Phase 6: DM Opt-in Bridge

```text
tests/test_discord_sync_dm_opt_in.py
```

Do not create DM execution code until forum/chat sync, account linking,
permission guard, audit, and revoke flow are stable.

## Files Not Allowed

Do not add:

```text
discord_selfbot.py
user_token_login.py
discord_dm_scraper.py
```

Do not implement:

- self-bot
- user token automation
- native Discord DM scraping
- automatic E2EE attachment export

## Pre-implementation Gates

Before creating implementation modules:

1. Re-check official Discord policy/API constraints in
   [DISCORD_POLICY_REFERENCES.md](DISCORD_POLICY_REFERENCES.md).
2. Confirm Message Content intent availability or keep inbound canonical writes
   disabled.
3. Confirm runtime secret storage location for bot/webhook/OAuth secrets.
4. Confirm fake Discord adapter coverage for REST, Gateway, 429, edit/delete,
   permission drift, and Message Content unavailable cases.
5. Confirm Server Mode test guild / shadow binding boundaries.
