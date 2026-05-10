# Discord Sync Data Model

## Discord Accounts

```sql
CREATE TABLE discord_accounts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    discord_user_id TEXT NOT NULL UNIQUE,
    discord_username TEXT,
    discord_global_name TEXT,
    avatar_url TEXT,
    linked_at TEXT NOT NULL,
    last_seen_at TEXT,
    status TEXT NOT NULL DEFAULT 'active'
        CHECK (status IN ('active', 'revoked', 'blocked')),
    oauth_scopes_json TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
```

Purpose:

- map `hackme_web` user to Discord user
- enable permission checks for inbound Discord events
- support OAuth2 account linking and revocation

V1 scope should request only `identify`.

## OAuth State

```sql
CREATE TABLE discord_oauth_states (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    state_hash TEXT NOT NULL UNIQUE,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    redirect_after TEXT,
    code_verifier_hash TEXT,
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'used', 'expired', 'revoked')),
    expires_at TEXT NOT NULL,
    used_at TEXT,
    created_at TEXT NOT NULL
);
```

Rules:

- Store only a hash of `state`.
- State is single-use.
- State has a short TTL.
- Callback must bind `state` to the logged-in user who started linking.
- OAuth tokens must not be stored in this table.

## Sync Bindings

```sql
CREATE TABLE discord_sync_bindings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    binding_uuid TEXT NOT NULL UNIQUE,

    source_type TEXT NOT NULL CHECK (source_type IN (
        'forum_board',
        'forum_thread',
        'chat_room',
        'dm_conversation'
    )),
    source_id TEXT NOT NULL,

    discord_guild_id TEXT,
    discord_channel_id TEXT NOT NULL,
    discord_thread_id TEXT,
    discord_webhook_id TEXT,
    discord_webhook_secret_ref TEXT,
    policy_version TEXT NOT NULL DEFAULT '1',
    config_hash TEXT NOT NULL,
    server_mode_scope TEXT NOT NULL DEFAULT 'production'
        CHECK (server_mode_scope IN ('production', 'test_guild', 'shadow')),

    direction TEXT NOT NULL DEFAULT 'two_way'
        CHECK (direction IN ('web_to_discord', 'discord_to_web', 'two_way')),

    sync_mode TEXT NOT NULL DEFAULT 'mirror'
        CHECK (sync_mode IN ('mirror', 'digest', 'manual_review')),

    require_account_link INTEGER NOT NULL DEFAULT 1,
    allow_attachments INTEGER NOT NULL DEFAULT 0,
    allow_edits INTEGER NOT NULL DEFAULT 1,
    allow_deletes INTEGER NOT NULL DEFAULT 1,
    allow_reactions INTEGER NOT NULL DEFAULT 0,

    status TEXT NOT NULL DEFAULT 'active'
        CHECK (status IN ('active', 'paused', 'revoked', 'error')),
    paused_reason TEXT,

    created_by INTEGER REFERENCES users(id),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
```

## Message Mappings

```sql
CREATE TABLE discord_message_mappings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    binding_id INTEGER NOT NULL REFERENCES discord_sync_bindings(id) ON DELETE CASCADE,

    web_source_type TEXT NOT NULL CHECK (web_source_type IN (
        'forum_thread',
        'forum_reply',
        'chat_message',
        'dm_message'
    )),
    web_message_id TEXT NOT NULL,

    discord_guild_id TEXT,
    discord_channel_id TEXT NOT NULL,
    discord_thread_id TEXT,
    discord_message_id TEXT NOT NULL,

    origin TEXT NOT NULL CHECK (origin IN ('web', 'discord')),
    author_user_id INTEGER REFERENCES users(id),
    discord_author_id TEXT,

    web_content_hash TEXT,
    discord_content_hash TEXT,

    last_sync_direction TEXT,
    last_synced_at TEXT,
    deleted_web_at TEXT,
    deleted_discord_at TEXT,

    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,

    UNIQUE(binding_id, web_source_type, web_message_id),
    UNIQUE(discord_channel_id, discord_message_id)
);
```

## Events And Jobs

```sql
CREATE TABLE discord_sync_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_uuid TEXT NOT NULL UNIQUE,
    binding_id INTEGER REFERENCES discord_sync_bindings(id),
    event_source TEXT NOT NULL CHECK (event_source IN ('web', 'discord')),
    event_type TEXT NOT NULL CHECK (event_type IN (
        'message_create',
        'message_update',
        'message_delete',
        'reaction_add',
        'reaction_remove',
        'thread_create',
        'thread_update',
        'binding_changed'
    )),
    source_event_id TEXT,
    payload_json TEXT NOT NULL,
    payload_hash TEXT NOT NULL,
    redacted_payload_json TEXT,
    server_mode TEXT NOT NULL,
    idempotency_key TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'processing', 'done', 'failed', 'ignored')),
    error_json TEXT,
    created_at TEXT NOT NULL,
    processed_at TEXT
);

CREATE TABLE discord_sync_jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_uuid TEXT NOT NULL REFERENCES discord_sync_events(event_uuid),
    job_type TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'queued'
        CHECK (status IN ('queued', 'running', 'done', 'failed', 'retry_wait', 'dead')),
    attempts INTEGER NOT NULL DEFAULT 0,
    next_run_at TEXT NOT NULL,
    rate_limit_bucket TEXT,
    retry_after_seconds REAL,
    locked_by TEXT,
    locked_at TEXT,
    dead_lettered_at TEXT,
    error_json TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
```

## Audit Logs

```sql
CREATE TABLE discord_sync_audit_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    audit_uuid TEXT NOT NULL UNIQUE,
    actor_user_id INTEGER REFERENCES users(id),
    actor_role TEXT,
    discord_user_id TEXT,
    binding_id INTEGER REFERENCES discord_sync_bindings(id),
    binding_uuid TEXT,
    event_uuid TEXT,
    job_id INTEGER REFERENCES discord_sync_jobs(id),
    server_mode TEXT,
    action TEXT NOT NULL,
    decision TEXT NOT NULL,
    reason TEXT,
    input_hash TEXT,
    output_hash TEXT,
    input_summary TEXT,
    output_summary TEXT,
    success INTEGER NOT NULL DEFAULT 0,
    ip TEXT,
    user_agent TEXT,
    created_at TEXT NOT NULL
);
```

Audit logs must not store bot token, webhook token, OAuth token, or private
message plaintext beyond summaries required for moderation.

## DM Bridge Consent

```sql
CREATE TABLE discord_dm_bridge_consents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id TEXT NOT NULL,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    discord_user_id TEXT NOT NULL,
    consent_status TEXT NOT NULL DEFAULT 'pending'
        CHECK (consent_status IN ('pending', 'approved', 'revoked', 'blocked', 'expired')),
    consent_token_hash TEXT NOT NULL UNIQUE,
    bridge_binding_id INTEGER REFERENCES discord_sync_bindings(id),
    requested_by INTEGER REFERENCES users(id),
    expires_at TEXT NOT NULL,
    approved_at TEXT,
    revoked_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(conversation_id, user_id)
);
```

DM bridge rules:

- Both participants must have `approved` consent before binding becomes active.
- Any `revoked` or `blocked` row pauses the binding.
- Consent token is hash-only, single-use, and TTL-bound.
- Consent does not override `hackme_web` block list.
