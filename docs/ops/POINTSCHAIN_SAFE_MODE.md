# PointsChain Safe Mode

Safe mode is a fail-closed state for chain/accounting uncertainty. It is not a
normal governance shortcut.

Triggers:

| Trigger | Result |
|---|---|
| ledger hash mismatch | stop new chain writes, show verify failure. |
| governance audit mismatch | block proposal execution and treasury movement. |
| restore branch mismatch | enter incident lockdown. |
| scanner blocker in production | fail release gate. |
| exploit/dispute review | optional provisional address freeze for 24 hours. |

Allowed while safe:

| Operation | Policy |
|---|---|
| read explorer | allowed, with warning. |
| backup/export | allowed. |
| governance voting | allowed unless governance audit is invalid. |
| transfer/trading spend | blocked for affected branch/address. |

Provisional freeze:

- root/manager review can freeze an address for 24 hours without a vote.
- it blocks outgoing spend only.
- it does not seize, burn, or credit any balance.
- continuing freeze requires governance approval.
- rejected/cancelled dispute releases the provisional freeze.
