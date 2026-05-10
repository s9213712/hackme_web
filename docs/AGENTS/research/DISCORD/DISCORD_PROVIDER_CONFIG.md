# Discord Provider Config

All Discord configuration is root-controlled. Ordinary users and Discord
inbound events cannot change provider config.

## Settings

```text
discord.enabled = false
discord.environment = test | production
discord.application_id
discord.client_id
discord.client_secret_ref
discord.bot_token_ref
discord.public_key
discord.default_guild_id
discord.test_guild_id
discord.allowed_guild_ids_json
discord.require_message_content_intent = true
discord.outbound_enabled = false
discord.inbound_enabled = false
discord.dm_bridge_enabled = false
discord.attachments_enabled = false
discord.gateway_enabled = false
discord.webhook_mode = bot_rest | webhook
discord.queue_worker_enabled = false
discord.max_retry_attempts = 5
```

## Secret Rules

- Store secret references, not plaintext secrets, in normal settings.
- Runtime secret values must not appear in config API responses.
- Snapshot export must not include bot token, webhook token, OAuth client
  secret, signing secret, or HMAC key.
- Audit logs store only secret reference names or hashes.
- Error responses must not include secret values or upstream authorization
  headers.

## Guild Rules

- Production sync is allowed only for configured production guild IDs.
- Test and internal-test sync use `discord.test_guild_id` or fake adapters.
- Unknown guild IDs are rejected before queueing jobs.
- Root must explicitly enable any additional guild.

## Feature Flags

V1 defaults:

```text
discord.enabled = false
discord.outbound_enabled = false
discord.inbound_enabled = false
discord.dm_bridge_enabled = false
discord.attachments_enabled = false
discord.gateway_enabled = false
```

Outbound forum mirror can be enabled after account linking, root config, fake
adapter tests, queue, mapping, and audit are ready.
