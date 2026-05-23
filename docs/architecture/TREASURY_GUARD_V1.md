# TreasuryGuard V1

Official treasury movement is governed asset control, not admin adjustment.

Allowed movement types:

| Type | Use |
|---|---|
| `treasury_to_promo` | promo fund allocation. |
| `treasury_to_exchange` | exchange fund replenishment; destination is the exchange fund address only. |
| `treasury_to_user_grant` | official grant to a public wallet address, never username/user id. |
| `treasury_to_burn` | governed burn/buyback. |
| `treasury_internal_rebalance` | official fund rebalance. |

Required payload:

`source`, `destination`, `amount`, `transaction_type`, `reason`,
`reference`, `idempotency_key`, `operator`, `approval_mode`,
`policy_version`, and `execution_payload_hash`.

Execution rules:

- manager+ vote approves the intent.
- root may veto treasury proposals only when `root_veto_allowed=true`.
- approval does not control the official wallet by itself.
- official multisig signers must sign the frozen execution bundle.
- execution appends chain ledger and governance audit records.
- abnormal movement writes an economic incident.
