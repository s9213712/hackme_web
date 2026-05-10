# Discord Sync Privacy Boundary

## Data Classes

| Data | Discord sync behavior |
|---|---|
| Public forum post | Sync if board binding active |
| Private forum post | Sync only if binding policy permits and Discord channel is private |
| Chat room message | Sync only for explicitly bound chat rooms |
| Direct message | Off by default; requires both users opt in |
| Cloud Drive standard link | Link-only in V1 |
| Server-encrypted file | Link-only; no plaintext export |
| E2EE file | Metadata only; no plaintext export |
| Quarantine file | No sync |
| Audit logs | Summary only; no raw sensitive fields |
| Tokens/secrets | Never sync |

## DM Boundary

Private message bridge must never:

- scrape native Discord DMs
- use user tokens
- auto-create bridge without both users approving
- bypass `hackme_web` block list
- export E2EE/plain private attachments

## Attachment Boundary

V1:

- web attachment -> Discord safe link
- Discord attachment -> external link or moderation pending item
- no binary import

V2 only after root approval:

- Discord file -> quarantine
- security scan
- import as Cloud Drive external attachment
- preserve permission checks

## Retention

Recommended retention:

- sync events: keep until reconciliation window closes, then summarize
- jobs: keep failures/dead-letter longer for root review
- audit logs: follow existing platform audit retention
- raw Discord payloads: avoid long-term retention; store redacted payload + hash

## Redaction

Before audit and UI display:

- redact bot token
- redact webhook token
- redact OAuth token
- redact Authorization headers
- redact cookies
- redact private URLs with embedded tokens

Order:

```text
Discord event -> validate -> redact -> audit summary/hash -> policy -> write
```
