# Runtime Reset, Snapshot, And PointsChain Recovery

This document defines the ownership boundary between the three recovery tools.

For the operator-first summary, start with
[09_SNAPSHOT_RESET_RESTORE.md](../09_SNAPSHOT_RESET_RESTORE.md). This file keeps
the detailed boundary and conflict rules.

## Runtime Reset

Runtime reset is a destructive cleanup tool for returning the live server to a
minimal runnable state.

It does:

- create a `pre_reset` server snapshot first
- clear resettable application tables such as forum, chat, DM, storage, album,
  report, notification, moderation, game, and runtime feature data
- clear configured canonical runtime file roots such as `runtime/storage/` and
  `runtime/chats/`
- reset PointsChain live tables through `PointsLedgerService.reset_runtime_chain`
- reset the secure audit chain through `reset_audit_chain_with_event`
- remove local deployment-generated secrets and manifests:
  - `runtime/.chain_seed`
  - `runtime/.csrfkey`
  - `runtime/.filekey`
  - `runtime/.fkey`
  - `.fley`
  - `runtime/.integrity_key`
  - `runtime/integrity_manifest.json`
  - `runtime/cert.pem`
  - `runtime/key.pem`
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

It also includes configured runtime secret files. Snapshot metadata records
`secrets_excluded: false` and lists `runtime_secret_files`, which currently
cover deployment-local files such as `runtime/.fkey`, `runtime/.filekey`,
`runtime/.csrfkey`, `runtime/.chain_seed`, `runtime/.integrity_key`,
`runtime/integrity_manifest.json`, `runtime/cert.pem`, and `runtime/key.pem`.
Restoring a snapshot replays those files and then validates their
hashes before the restore is accepted as complete.

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

Root can use the one-click anomaly handler from the PointsChain operations card
or `POST /api/root/points/chain/recovery/auto-handle`. That action still follows
the recovery boundary above: it first verifies the chain, only applies the
recommended healthy backup when safe mode already exists, rebuilds wallets from
ledger replay, and writes audit events for start, clean result, restore, manual
required, or failure outcomes. If there is no healthy backup, it returns manual
required instead of overwriting the live ledger.

## Conflict Rules

- Use server snapshot restore when the whole site state must roll back together.
- Use PointsChain restore when only the economy ledger is corrupt or tampered.
- Do not run PointsChain restore immediately after full server restore unless a
  new chain verification fails and safe mode prepares a restore plan.
- Reset may create a pre-reset server snapshot, but reset itself intentionally
  creates a fresh PointsChain and audit chain.
- Runtime reset still clears local runtime secrets and generated manifests.
  Snapshot restore and runtime reset therefore have different boundaries:
  snapshot restore replays the captured runtime secrets, while reset deletes
  them and expects regeneration or reinjection on next boot.

These boundaries prevent a server snapshot from silently overriding the
independent ledger-backup policy, and prevent wallet balances from being trusted
without ledger replay.


---

## PointsChain v2 區塊鏈化規劃 (2026-05-04 拍板, 尚未實作)

本模組未來將與全站 PointsChain v2 區塊鏈化整合：

- 工程設計：[`docs/archive/research/BLOCKCHAIN/POINTSCHAIN_ENGINEERING.md`](../archive/research/BLOCKCHAIN/POINTSCHAIN_ENGINEERING.md)
- 用戶白皮書：[`docs/archive/research/BLOCKCHAIN/POINTSCHAIN_WHITEPAPER.md`](../archive/research/BLOCKCHAIN/POINTSCHAIN_WHITEPAPER.md)
- 地址規格：[`docs/archive/research/BLOCKCHAIN/POINTS_WALLET_ADDRESSING.md`](../archive/research/BLOCKCHAIN/POINTS_WALLET_ADDRESSING.md)
- 轉帳 API：[`docs/archive/research/BLOCKCHAIN/POINTS_TRANSFER_API.md`](../archive/research/BLOCKCHAIN/POINTS_TRANSFER_API.md)
- 多簽錢包：[`docs/archive/research/BLOCKCHAIN/MULTISIG_WALLETS.md`](../archive/research/BLOCKCHAIN/MULTISIG_WALLETS.md)
- QA Mining / 貢獻獎勵 (Phase 7)：[`docs/archive/research/BLOCKCHAIN/POINTS_MINING_REWARDS.md`](../archive/research/BLOCKCHAIN/POINTS_MINING_REWARDS.md)
- QA / Release Gate：[`docs/archive/research/BLOCKCHAIN/POINTSCHAIN_QA.md`](../archive/research/BLOCKCHAIN/POINTSCHAIN_QA.md)

**狀態：設計已拍板（root, 2026-05-04），尚未實作完成。**
