# Post-RC1 Backlog

Status: explicitly out of RC1 implementation scope.

These items are important, but they must not be added to the RC1 hardening
round. After RC1 closure, they remain backlog-only until a separate post-RC1
scope is approved.

## Closure Backlog

The following items are explicitly outside RC1:

- external anchor
- HSM/offline signer
- generic user multisig spend
- P2P/validator/fork choice
- full DAO anti-capture
- full forensic taint graph
- external chain bridge
- public exchange liability expansion

## Production Integrity

- External immutable anchor.
- Offline checkpoint.
- Signed daily block-root export.
- File integrity monitoring.
- Backup verification schedule.
- Incident exercise schedule.

Production note: external anchoring/offline checkpointing is a production
requirement and post-RC1 implementation item, not a blocker for the controlled
single-node RC1 release.

## Key Custody

- HSM or hardware-backed key custody.
- Offline treasury signer.
- Signer device policy.
- Signer rotation drill.
- Signer revocation drill.

## Chain/Network

- P2P networking.
- Validator set.
- Fork choice.
- Public consensus.
- Public block explorer indexer.

## External Assets

- External chain deposit/withdraw.
- BSC bridge.
- Layer2 bridge.
- Cross-chain proof/reconciliation.

## Governance

- Full DAO anti-capture system.
- Delegation/liquid democracy.
- Staking-weight governance.
- Validator governance.
- Generic Safe-style user multisig spend.

## Trading/Economy

- Official market making.
- P2P matching expansion.
- Futures/liquidation expansion.
- Lending expansion.
- Exchange liability expansion.
- Full forensic taint propagation graph / AML engine.
