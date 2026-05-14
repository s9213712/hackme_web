# Discord Policy And API References

> Verify these official documents again before implementation. Discord API and
> policy requirements can change.

## Official Constraints To Re-check

1. Self-bots / normal user account automation are forbidden.
2. Applications must not request user passwords or login tokens.
3. Apps must not contact users without explicit permission.
4. Incoming webhooks are suitable for one-way messages into Discord.
5. Gateway / bot events are needed for Discord -> `hackme_web` inbound sync.
6. Message content, embeds, attachments, and components may be empty unless the
   app has Message Content privileged intent.
7. Rate limits must respect retry information from Discord responses.
8. Outbound user-generated messages should disable broad mentions via
   `allowed_mentions`.
9. OAuth2 account linking must use scoped authorization and must not collect
   user passwords or raw user tokens.

## Links Checked On 2026-05-10

- Discord self-bot support article:
  <https://support.discord.com/hc/en-us/articles/115002192352-Automated-user-accounts-self-bots->
- Discord Developer Policy:
  <https://support-dev.discord.com/hc/en-us/articles/8563934450327-Discord-Developer-Policy>
- Discord Webhooks documentation:
  <https://docs.discord.com/developers/resources/webhook>
- Discord Message Resource / Message Content privileged intent behavior:
  <https://docs.discord.com/developers/resources/message>
- Discord Gateway / intents documentation:
  <https://docs.discord.com/developers/events/gateway>
- Discord rate-limit handling reference:
  <https://docs.discord.com/developers/topics/rate-limits>
- Discord OAuth2 and permissions reference:
  <https://docs.discord.com/developers/platform/oauth2-and-permissions>

## Implementation Gate

Before Phase 1 implementation:

- root verifies bot/account policy still allows the chosen integration pattern
- root verifies required intents
- root confirms whether Message Content intent is approved or unavailable
- implementation chooses outbound-only if Message Content is unavailable
- rate-limit tests use fake Discord responses, not live API dependency
- implementation uses the current
  [CURRENT_REPO_RECONCILIATION.md](CURRENT_REPO_RECONCILIATION.md) namespace
  and does not modify `routes/chat.py`
