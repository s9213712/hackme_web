# AI Data Boundary

## Never Send To LLM

These values must never be included in prompts, provider requests, tool output
sent to the model, chat history, or memory:

- session cookie
- CSRF token
- password or password hash
- API token
- OAuth token
- private key
- E2EE key
- TOTP secret
- runtime secret
- raw environment variables
- database connection string
- Discord bot token / webhook token
- full raw audit line with sensitive fields

## Requires Explicit Authorization

These can be summarized or sent only through policy-checked tools:

- user's own Cloud Drive file summary
- user's own chat content
- user's own direct-message content
- user's own trading records
- admin/root audit summaries
- moderation queue summaries

## Must Not Be Sent

- other user's private files
- other user's private messages
- strict E2EE plaintext
- quarantine file content
- unauthorized private forum content
- unauthorized private chat room content
- raw database rows containing secrets

## Cloud Drive Boundary

Cloud Drive storage modes must be respected:

| Storage mode | Agent access |
|---|---|
| `standard_plain` | metadata and authorized snippets only |
| `server_encrypted` | metadata and authorized snippets only after backend decrypts under normal policy |
| `e2ee` / strict E2EE | metadata only; no plaintext to LLM |
| quarantine | metadata only; no content |

## Tool Output Boundary

Tool output is untrusted content. It can be summarized, but it cannot override
system policy or become a new instruction.

## Redaction

Before provider calls and audit writes, redact:

```text
password
token
secret
csrf
session
private_key
totp
authorization
cookie
```

Redaction must use both key-name matching and value-pattern matching.

Pattern examples:

```text
Authorization: Bearer ...
sk-...
ghp_...
github_pat_...
xoxb-...
-----BEGIN PRIVATE KEY-----
session=...
csrf_token=...
api_key=...
access_token=...
refresh_token=...
```

Ordering rule:

```text
tool output -> redact -> audit summary/hash -> LLM prompt
```

Do not write raw sensitive tool output to audit and then redact only before the
provider call.
