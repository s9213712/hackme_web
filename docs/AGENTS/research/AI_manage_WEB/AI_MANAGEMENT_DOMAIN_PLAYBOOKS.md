# AI Management Domain Playbooks

Domain playbooks define what AI Management can do in V1 and what remains
blocked.

## Server Mode

Allowed:

- read status
- explain blockers
- recommend next manual step

Blocked:

- changing server mode
- bypassing mode restrictions

## Snapshot

Allowed:

- read status
- list recent snapshots
- recommend snapshot before risky operation

V1 blocked:

- executing `snapshot.create`
- `snapshot.restore`
- `server.reset`

## PointsChain

Allowed:

- read verification status
- explain safe mode
- summarize economy health
- recommend root review

Blocked:

- transfer
- mint
- burn
- balance adjustment

## Trading

Allowed:

- read risk summary
- summarize bot audit output
- recommend review

Blocked:

- autonomous trade
- leverage change
- liquidation-affecting operation

## Cloud Drive

Allowed:

- storage summary
- quota summary
- own-file metadata summary

Blocked:

- cross-user private file reading
- strict E2EE plaintext access
- destructive file actions

## Forum / Chat

Allowed:

- moderation summary
- draft response
- recommend review

Blocked:

- autonomous delete
- autonomous ban
- mass moderation

## Discord Sync

Allowed after Discord outbound MVP:

- queue summary
- dead-letter grouping
- outbound mirror status summary

Blocked:

- inbound canonical write
- DM bridge operation
- Discord role sync
- attachment import
