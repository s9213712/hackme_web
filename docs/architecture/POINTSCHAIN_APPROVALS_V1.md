# PointsChain Approvals V1

Approval objects freeze the execution bundle before voting/signing.

Required fields:

| Field | Rule |
|---|---|
| `operation_type` | mint, treasury movement, exchange movement, emergency action, or production official transfer. |
| `source_wallet` / `destination_wallet` | public wallet address or official system fund address; no username target. |
| `amount` | immutable after proposal creation. |
| `required_signers` | signer snapshot captured at proposal creation. |
| `threshold` / `collected_signers` | weight counted against the snapshot only. |
| `timelock_until` | execution blocked before this time. |
| `reason`, `reference`, `idempotency_key` | mandatory. |
| `execution_payload_hash` | must match at execution. |

States:

`draft -> pending_signatures -> timelocked -> ready_to_execute -> executed`

Terminal states:

`cancelled`, `expired`, `rejected`, `vetoed`.

Enforcement:

- signer revocation invalidates pending signatures from that signer.
- signer set rotation does not change existing proposal snapshots.
- duplicate execution is rejected by idempotency and proposal status.
- public governance cannot be vetoed by root.
- treasury governance can be vetoed by root before execution.
- governance approval is not wallet control; official multisig signatures are still required.
