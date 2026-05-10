# Discord Gateway Intents

Gateway and Message Content requirements must be phase-gated. Do not enable
inbound canonical writes unless required intents are present and root has
verified current Discord policy.

## Phase Matrix

| Scope | Gateway required | Message Content required | Notes |
|---|---:|---:|---|
| Forum outbound mirror | no | no | Use webhook or bot REST send only |
| Forum inbound | yes | likely yes | Required for normal message text/content |
| Chat room two-way | yes | likely yes | Enforce room membership before write |
| DM bridge | phase-specific | flow-specific | No native user DM scraping |

## If Message Content Is Unavailable

- Disable Discord inbound canonical writes.
- Keep inbound events as ignored/review records with payload hash and redacted
  summary only.
- Show root/admin UI blocked reason.
- Permit outbound mirror if other config is valid.
- Consider slash command or explicit component-based fallback only in a future
  design.

## Gateway Safety

- Gateway worker must ignore bot's own messages.
- Gateway worker must resolve channel/thread to active binding.
- Gateway worker must check linked account, permissions, server mode, content
  policy, and binding direction.
- Gateway worker must not write canonical content for unlinked users in V1.
- Gateway worker must not process events while binding is paused, revoked, or
  error.
