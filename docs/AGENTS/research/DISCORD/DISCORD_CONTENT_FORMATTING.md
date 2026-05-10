# Discord Content Formatting

Formatting is a security boundary. User-generated content must be converted
without enabling mention abuse, HTML injection, or permission bypass.

## Web To Discord

Rules:

- strip or render-safe unsafe HTML
- cap content to Discord message limits before send
- include canonical `hackme_web` link when useful
- set `allowed_mentions.parse=[]`
- do not allow user-controlled arbitrary embed URLs in V1
- do not attach private file bytes in V1
- preserve author attribution without impersonating another Discord user
- record `content_hash` used for idempotency

V1 payload should use the smallest required Discord fields:

```json
{
  "content": "...",
  "allowed_mentions": {"parse": []}
}
```

## Discord To Web

Rules:

- sanitize markdown into site-safe display format
- neutralize Discord mentions
- preserve Discord author attribution
- reject excessive length
- reject or review mass mention attempts
- convert custom emoji to safe text or approved image references only
- never treat Discord content as trusted HTML
- never treat Discord content as a site command

## Edits

- Web edit may update Discord mirror only if mapping exists.
- Discord edit may update web content only after permission checks.
- Missing mapping creates reconciliation item; it does not overwrite unrelated
  web content.

## Deletes

- Web soft-delete mirrors as a Discord tombstone edit where possible.
- Discord delete mirrors as web tombstone/soft-delete where allowed.
- Neither direction hard-deletes canonical audit.
