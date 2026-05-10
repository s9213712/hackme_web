# Discord Sync Security

## Bot-only Policy

Before implementation, verify current Discord platform rules through
[DISCORD_POLICY_REFERENCES.md](DISCORD_POLICY_REFERENCES.md). This research
proposal does not authorize self-bot, user-token, or native Discord DM scraping
patterns even if a future library makes them technically easy.

Allowed:

- Discord Bot Token
- Discord OAuth2 account linking
- Discord Webhook
- Discord Gateway

Forbidden:

- user password collection
- user Discord token collection
- self-bot
- automating a normal Discord user account
- modifying Discord client

## Account Linking

Flow:

1. User clicks "link Discord" in `hackme_web`.
2. Redirect to Discord OAuth2.
3. User grants `identify`.
4. Callback verifies state, code, TTL, and same logged-in user.
5. `discord_accounts` row is written.
6. UI shows linked status.

V1 scope:

```text
identify
```

Bot guild installation should be a separate root/admin setup flow.

OAuth state rules:

- store only `state_hash`
- set a short TTL
- mark state single-use
- reject callback for a different logged-in user
- never store OAuth access/refresh tokens in `discord_oauth_states`
- redact OAuth errors before audit or UI output

## Permission Decision

Inbound Discord message can write into `hackme_web` only if:

1. Discord user is linked.
2. Linked `hackme_web` user is active.
3. User is not blocked / suspended.
4. Board / thread / chat / DM permission allows write.
5. Binding is active.
6. Server mode allows Discord sync.
7. Rate limit allows processing.
8. Content policy allows processing.
9. Message Content privileged intent is available when inbound text is needed.
10. Binding `policy_version` and `config_hash` still match current policy.

Discord roles are only external signals. They do not grant `hackme_web` admin,
manager, root, member-level, or moderation rights.

## Private Message Safety

Private message sync requires:

- both `hackme_web` users opt in
- both Discord accounts linked
- specific conversation selected
- revocation available at all times
- block immediately pauses sync
- no E2EE content auto-sync
- no user Discord token
- no native Discord DM scraping
- consent token is hash-only, single-use, and TTL-bound
- consent does not override `hackme_web` block list or account suspension

DM consent follows
[DISCORD_SYNC_STATE_MACHINE.md](DISCORD_SYNC_STATE_MACHINE.md) and data exposure
rules in [DISCORD_SYNC_PRIVACY_BOUNDARY.md](DISCORD_SYNC_PRIVACY_BOUNDARY.md).

## Secret Storage

Secrets:

```text
DISCORD_BOT_TOKEN
DISCORD_CLIENT_SECRET
DISCORD_WEBHOOK_TOKEN
signing secrets / HMAC keys
```

Rules:

- store in runtime secret file or encrypted settings
- never commit to git
- never expose in snapshot public export
- never show in audit detail
- never show in error response

## Inbound Event Trust

Preferred inbound path is Gateway worker, not arbitrary public POST.

If an internal endpoint is used:

```text
POST /api/internal/discord/events
```

It must require:

- internal HMAC
- localhost/private network restriction where possible
- rate limit
- replay nonce
- timestamp window

Inbound payload handling:

1. Verify source authenticity.
2. Compute `payload_hash`.
3. Redact secrets, tokens, private URLs, and mention payloads.
4. Store only `redacted_payload_json` or summaries in audit surfaces.
5. Run permission and content policy.
6. Write canonical content only after policy passes.

## Loop Guard

Do not rely on user-editable Discord message content for loop prevention.

Use:

- mapping table
- bot author ignore
- idempotency key
- event UUID
- content hashes

Optional visible metadata should be minimal.

## Mention Abuse

All outbound Discord messages should disable broad mentions:

```json
{
  "allowed_mentions": {
    "parse": []
  }
}
```

V1 forbids:

- `@everyone`
- `@here`
- role mention
- mass mention

Formatter tests must verify `allowed_mentions.parse` is empty for every
user-generated outbound message, including forum posts, chat messages, DM bridge
messages, edit payloads, and retry payloads.

## Moderation

Inbound Discord content must pass:

- spam check
- blocked words
- member status
- board permission
- attachment policy
- moderation queue when needed

## Incident Handling

`incident_lockdown`:

- pauses outbound
- pauses inbound
- allows root/admin to inspect queue
- does not process new writes

`maintenance`:

- pauses queues
- preserves jobs for replay after resume

Resume rules:

- re-check binding `policy_version`
- re-check Discord channel/thread permission drift
- re-check linked account status
- re-check DM consent state
- do not replay dead-letter jobs automatically
