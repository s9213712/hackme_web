# Runtime Reset, Snapshot, And PointsChain Recovery

This document defines the ownership boundary between the three recovery tools.

## Runtime Reset

Runtime reset is a destructive cleanup tool for returning the live server to a
minimal runnable state.

It does:

- create a `pre_reset` server snapshot first
- clear resettable application tables such as forum, chat, DM, storage, album,
  report, notification, moderation, game, and runtime feature data
- clear configured runtime file roots such as uploads, avatars, attachments,
  media, and chat files
- reset PointsChain live tables through `PointsLedgerService.reset_runtime_chain`
- reset the secure audit chain through `reset_audit_chain_with_event`
- remove local deployment-generated secrets and manifests:
  - `.chain_seed`
  - `.csrfkey`
  - `.fkey`
  - `.fley`
  - `.integrity_key`
  - `integrity_manifest.json`
  - `cert.pem`
  - `key.pem`
- switch the server back to management-only feature defaults
- return `requires_restart: true`

It does not delete the `pre_reset` snapshot. That snapshot is the recovery point
if reset was triggered accidentally.

After reset, restart the server. The next boot regenerates the local secrets and
TLS certificate/key files.

## Server Snapshot / Restore

Server snapshot is a whole-server recovery mechanism.

It includes:

- SQLite database backup
- runtime file archive for configured file roots
- selected config archive with `.env` redacted
- manifest, checksums, metadata, and snapshot audit events

It excludes deployment secrets. Snapshot metadata records
`secrets_excluded: true`. Restoring a snapshot does not restore `.fkey`,
`.csrfkey`, `.chain_seed`, `.integrity_key`, `cert.pem`, or `key.pem`.

Server restore should be used for whole-server rollback, migration, or
cross-machine restore.

## PointsChain Ledger Backup / Restore

PointsChain backup is independent from server snapshot. It protects the economy
ledger and chain data specifically.

It includes:

- `points_ledger`
- `points_chain_blocks`
- block signatures
- chain audit logs
- wallet state snapshot
- schema/version metadata
- manifest and HMAC signature

When restoring PointsChain, wallet balances are rebuilt from the restored
healthy ledger. The old `points_wallets` balance is not trusted as source of
truth.

PointsChain restore is only valid in PointsChain safe mode and requires root
confirmation. It does not replace the whole server database and it does not
restore unrelated application state.

## Conflict Rules

- Use server snapshot restore when the whole site state must roll back together.
- Use PointsChain restore when only the economy ledger is corrupt or tampered.
- Do not run PointsChain restore immediately after full server restore unless a
  new chain verification fails and safe mode prepares a restore plan.
- Reset may create a pre-reset server snapshot, but reset itself intentionally
  creates a fresh PointsChain and audit chain.
- Deployment secrets are local-only runtime files. They are not snapshot
  payloads and are regenerated after reset or first boot.

These boundaries prevent a server snapshot from silently overriding the
independent ledger-backup policy, and prevent wallet balances from being trusted
without ledger replay.
