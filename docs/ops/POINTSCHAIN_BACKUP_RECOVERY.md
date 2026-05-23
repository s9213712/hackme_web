# PointsChain Backup And Recovery

Snapshot/backup scope must include every append-only financial truth source:

| Scope | Required |
|---|---|
| Chain ledger | `points_ledger`, transfer requests, blocks, chain branches, replay cache metadata. |
| Wallet identity | wallet identities, custody metadata, deleted/revoked state, branch-scoped balances derived by replay. |
| Governance | proposals, votes, vetoes, multisig signatures, governance audit hash chain. |
| Funds | economy events, official treasury, exchange fund buckets, burn/mint/system fund events. |
| Product accounting | service fee reserves, trading orders/fills/positions/bots, source wallet lineage. |
| Forensics | disputes, evidence refs, provisional freezes, address risk marks, recovery reports. |

Restore checks:

1. canonical branch pointer matches branch metadata.
2. ledger hash chain verifies.
3. governance audit hash chain verifies.
4. replay/derived cache rebuild matches stored summary.
5. branch-scoped official/exchange fund balances reconcile.
6. mismatch enters incident lockdown instead of silently continuing.

Recovery modes:

| Mode | Use |
|---|---|
| Compensation recovery | Default for local theft/phishing/exchange fault; keep history and compensate by governance result. |
| Tainted remainder return | User-negligence theft; return only unused tainted remainder by approved claimant ratio. |
| Branch recovery | Severe protocol corruption or systemic exploit; create a new canonical branch, old branch read-only. |
