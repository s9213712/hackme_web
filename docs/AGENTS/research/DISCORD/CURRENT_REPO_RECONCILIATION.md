# Current Repo Reconciliation

This proposal must fit the current `hackme_web` application instead of
replacing existing social modules.

## Existing Boundaries

- `routes/chat.py` is the existing site chat / direct-message / chat-room route.
- Existing chat and DM handlers own room password, invite, attachment,
  delete/withdraw, unread, block, and audit-safe behavior.
- Forum routes and services remain the canonical place for forum writes.
- Cloud Drive and upload security own file permissions, quarantine, scanning,
  and storage privacy decisions.
- Server Mode v2 owns production, internal test, test, maintenance,
  incident-lockdown, and superweak behavior.
- PointsChain, AI Agent, LLM WebChat, and Discord Sync are separate research
  surfaces. Discord Sync V1 must not depend on PointsChain or AI Agent.

## Required New Namespace

Implementation must use new Discord-specific modules:

```text
services/discord_sync/
routes/discord_sync.py
/api/root/discord/*
/api/admin/discord/*
/api/discord/link/*
/api/internal/discord/events
```

## Forbidden Repo Changes

Do not:

- overwrite or repurpose `routes/chat.py`
- place Discord inbound writes directly inside current chat handlers
- map Discord roles directly to `hackme_web` roles
- treat a Discord CDN URL as proof that a file passed Cloud Drive permission
- bypass Forum/Chat/DM permission services for inbound Discord content
- connect Discord V1 to PointsChain tips, paid DM, or transfer flows
- connect Discord V1 to LLM WebChat / AI Agent tool execution

## Implementation Gate

Before code starts, the implementer must state which existing service owns each
canonical write:

| Source type | Canonical write owner |
|---|---|
| Forum thread | Forum service / route |
| Forum reply | Forum service / route |
| Chat message | Existing chat service / route |
| DM message | Existing DM service / route |
| Attachment import | Cloud Drive / upload security |
| Audit row | Discord Sync audit wrapper plus existing audit facility |
