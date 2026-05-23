# MintGuard V1

Mint is not a root button. RC1 requires an enforceable proposal path.

Required fields:

| Field | Rule |
|---|---|
| reason/reference | mandatory human-readable reason and external/internal reference. |
| idempotency_key | mandatory; duplicate key cannot mint twice. |
| requested_amount | checked against proposal cap, daily cap, max supply, mint remaining, and reserved locked supply. |
| destination | official wallet/fund destination only; no username target. |
| payload_hash | execution payload must match the approved proposal. |

Lifecycle:

`DRAFT -> REVIEW -> VOTING -> SUCCEEDED -> QUEUED -> TIMELOCKED -> EXECUTED`

Profile enforcement:

| Profile | Approval |
|---|---|
| development/isolated | root single approval allowed, labeled dev override. |
| production | root + admin/manager approval, timelock, cap, and payload hash enforcement. |

Violation attempts append an economic/governance incident.
