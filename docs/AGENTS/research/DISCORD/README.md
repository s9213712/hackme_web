# Discord Sync Research

> Status: research proposal. Docs-only. Implementation is not authorized until root approves a specific phase.
> Canonical folder: `docs/AGENTS/research/DISCORD/`.

This folder defines the proposed `hackme_web` private message / forum / chat /
Discord synchronization system.

Core conclusion:

- Feasible.
- Do not start with "all DMs, all forums, all Discord channels fully bridged".
- `hackme_web` should remain the canonical source of truth.
- Discord should act as an external mirror / bridge.
- Forum can be the first two-way target.
- Private messages require explicit opt-in and must not use self-bots or user
  Discord tokens.

## Document Map

| File | Purpose |
|---|---|
| [DISCORD_SYNC_DESIGN.md](DISCORD_SYNC_DESIGN.md) | Overall goals, phases, architecture, and source-of-truth model |
| [DISCORD_SYNC_DATA_MODEL.md](DISCORD_SYNC_DATA_MODEL.md) | Proposed SQLite tables and idempotency model |
| [DISCORD_SYNC_FLOWS.md](DISCORD_SYNC_FLOWS.md) | Outbound, inbound, forum, chat, DM, attachments, edits, deletes |
| [DISCORD_SYNC_SECURITY.md](DISCORD_SYNC_SECURITY.md) | OAuth2, bot-only policy, private DM opt-in, secrets, loop and mention safety |
| [CURRENT_REPO_RECONCILIATION.md](CURRENT_REPO_RECONCILIATION.md) | Current `hackme_web` module boundaries and namespace rules |
| [DISCORD_SYNC_SERVER_MODE_MATRIX.md](DISCORD_SYNC_SERVER_MODE_MATRIX.md) | Server Mode behavior matrix for link, outbound, inbound, queue, DM, attachments |
| [DISCORD_PROVIDER_CONFIG.md](DISCORD_PROVIDER_CONFIG.md) | Root-controlled Discord config keys and secret-reference rules |
| [DISCORD_OAUTH_SECURITY.md](DISCORD_OAUTH_SECURITY.md) | OAuth state, callback, collision, revoke, and scope rules |
| [DISCORD_GATEWAY_INTENTS.md](DISCORD_GATEWAY_INTENTS.md) | Gateway and Message Content intent gates by phase |
| [DISCORD_CONTENT_FORMATTING.md](DISCORD_CONTENT_FORMATTING.md) | Web-to-Discord and Discord-to-web formatting and sanitization |
| [DISCORD_PERMISSION_MAPPING.md](DISCORD_PERMISSION_MAPPING.md) | Inbound identity, role, board, chat, block, and mode checks |
| [DISCORD_ATTACHMENT_POLICY.md](DISCORD_ATTACHMENT_POLICY.md) | V1 link-only and V2 quarantine/import attachment rules |
| [DISCORD_AUDIT_EVENT_CONTRACT.md](DISCORD_AUDIT_EVENT_CONTRACT.md) | Discord audit event names and required fields |
| [DISCORD_SYNC_STATE_MACHINE.md](DISCORD_SYNC_STATE_MACHINE.md) | Binding, event, job, mapping, and DM consent lifecycles |
| [DISCORD_SYNC_PRIVACY_BOUNDARY.md](DISCORD_SYNC_PRIVACY_BOUNDARY.md) | Data classes, DM privacy, E2EE/attachment boundaries, retention |
| [DISCORD_SYNC_RATE_LIMITS.md](DISCORD_SYNC_RATE_LIMITS.md) | Retry, bucket, global pause, and worker queue behavior |
| [DISCORD_POLICY_REFERENCES.md](DISCORD_POLICY_REFERENCES.md) | Official Discord policy/API constraints to verify before implementation |
| [DISCORD_SYNC_API_UI.md](DISCORD_SYNC_API_UI.md) | Proposed root/admin/user APIs and UI |
| [DISCORD_SYNC_QA.md](DISCORD_SYNC_QA.md) | Unit, integration, security, and manual smoke tests |
| [SCAFFOLD_MANIFEST.md](SCAFFOLD_MANIFEST.md) | Files that can be pre-created when implementation starts |

## MVP Recommendation

MVP should include only:

1. Discord account linking.
2. Root/admin Discord config.
3. Forum board to Discord channel/thread binding.
4. Forum outbound mirror from `hackme_web` to Discord.
5. Queue, retry, rate-limit bucket, and dead-letter handling.
6. Message mapping table.
7. Audit log.
8. `maintenance` and `incident_lockdown` pause.
9. Fake Discord adapter tests.

Do not include in MVP:

- Discord inbound canonical writes
- chat room two-way sync
- private DM bridge
- binary attachment import
- reaction sync
- Discord role sync
- multi-guild federation
- PointsChain paid DM / tips
