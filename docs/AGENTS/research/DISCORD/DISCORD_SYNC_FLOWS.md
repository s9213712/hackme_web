# Discord Sync Flows

## Forum Board To Discord Channel

Recommended mapping:

```text
hackme_web forum board <-> Discord forum channel or text channel
hackme_web thread      <-> Discord thread / forum post
hackme_web reply       <-> Discord message in thread
```

When Discord uses forum channels, a new Discord forum post creates both a thread
and the first message.

## Forum Thread Outbound

```text
web forum thread created
  -> create Discord thread/post
  -> first post becomes starter message
  -> mapping: web_thread_id <-> discord_thread_id / starter_message_id
```

## Forum Thread Inbound

```text
Discord THREAD_CREATE + first MESSAGE_CREATE
  -> create hackme_web forum thread
  -> Discord author must be linked
```

Inbound thread creation requires Message Content privileged intent. If content
is unavailable, create only an ignored/review event with payload hash and
redacted summary; do not create a canonical forum thread.

If Discord user is not linked:

- do not write canonical forum content in V1
- create review item or ignored event
- notify admin/root if configured

## Replies

Outbound:

```text
forum_reply_created
  -> send Discord message to mapped thread
```

Inbound:

```text
MESSAGE_CREATE in mapped thread
  -> create forum reply
```

Loop guard:

```text
if discord_author_id == bot_user_id: ignore
if message has known bridge marker: ignore
if discord_message_id exists in mapping: ignore
```

## Chat Room Two-way

```text
hackme_web chat_room <-> Discord channel/thread
```

Rules:

- linked user required for inbound
- member-level permission enforced by `hackme_web`
- attachment link-only in early phase
- reported Discord messages create review / moderation entries, not automatic bans

## Private DM Bridge

Private messages are the highest-risk part of this plan.

V1 should not sync native Discord user-to-user DMs. Use one of:

### Option A: Private Bridge Channel / Thread

```text
hackme_web DM conversation #123
  <-> Discord private thread/channel #abc
```

Requirements:

1. Both `hackme_web` users opt in.
2. Both Discord accounts are linked.
3. The specific conversation is selected.
4. Either side can revoke.
5. Block by either side pauses sync.
6. Discord permission drift pauses sync.

### Option B: Bot-mediated DM Inbox

```text
User A -> Bot: /dm @linked_user hello
Bot -> hackme_web DM
hackme_web DM -> Bot DM to User B
```

This is not native Discord DM sync. It is bot-mediated messaging and still
requires explicit permission to contact the target user.

## First DM Recommendation

Use Option A only after forum/chat sync is stable.

Rules:

- default off
- conversation-level opt-in
- both users approve
- any revoke pauses immediately
- block pauses immediately
- soft-delete mirrors as tombstone
- E2EE / highly private content is not synced
- attachments are disabled or link-only

DM bridge activation requires two `approved` consent rows in
`discord_dm_bridge_consents`. A revoke, block, expired consent, missing linked
account, or Discord permission drift immediately pauses the binding. See
[DISCORD_SYNC_STATE_MACHINE.md](DISCORD_SYNC_STATE_MACHINE.md).

## Attachments

V1:

- Web attachment -> Discord shows `hackme_web` file page link.
- Discord attachment -> `hackme_web` shows Discord CDN link or pending external attachment.
- No binary import.

V2:

```text
Discord attachment
  -> download into quarantine
  -> upload_security scan
  -> Cloud Drive external_import
  -> forum/chat/dm attachment
```

Never:

- auto-decrypt E2EE
- dump private storage content into Discord
- let Discord CDN links bypass `hackme_web` permissions

## Edits, Deletes, Reactions

Edits:

- web edit -> Discord edit
- Discord edit -> web edit
- missing mapping -> create correction reply instead of overwriting

Deletes:

- web soft-delete -> Discord edit to `[message deleted on hackme_web]`
- Discord delete -> web soft-delete / tombstone
- do not hard-delete canonical audit

Reactions:

- not in V1
- later map emoji reaction both ways with loop guard and rate limits

## Rate Limit And Retry

Do not hard-code Discord rate limits. Honor response headers and `retry_after`;
details live in [DISCORD_SYNC_RATE_LIMITS.md](DISCORD_SYNC_RATE_LIMITS.md).

Minimum queue state:

- `rate_limit_bucket`
- `retry_after_seconds`
- `next_run_at`
- `locked_by`
- `locked_at`
- `dead_lettered_at`
- `idempotency_key`

Default retry strategy:

| Attempt | Delay |
|---|---|
| 1 | immediately |
| 2 | 10s |
| 3 | 60s |
| 4 | 5m |
| 5 | 30m |
| after 5 | dead-letter + root alert |

Workers must stop picking new jobs during `maintenance` and
`incident_lockdown`; they may only expose queue status to root/admin.
