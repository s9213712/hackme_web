# Production Profile Guardrails

`development` and `isolated` profiles may keep default local credentials and
developer override paths. `production` must fail closed.

Production blockers:

| Blocker | Required behavior |
|---|---|
| Default credentials | `root/root`, `admin/admin`, `test/test` are rejected by startup or release gate. |
| Dev override | single-sign root override, unsafe reset, debug grant, and untimelocked mint are rejected. |
| Direct mutation | product paths cannot call ledger primitives or mutate wallet balance columns directly. |
| Mint/treasury/exchange | must require proposal, idempotency key, reason, payload hash, timelock, and required approvals. |
| Legacy admin APIs | wallet query by username, sanction, rollback, and pending reward direct approval remain disabled/410. |

Allowed in isolated:

| Feature | Reason |
|---|---|
| Default accounts | Local QA speed; user explicitly requested defaults stay unchanged. |
| Root single approval | Development-only governance shortcut, shown as dev override in UI/report. |
| Unsafe local reset | Isolated runtime only. |

Before production:

```bash
python3 scripts/security/gate/wallet_direct_call_inventory.py --fail-on-blocker
python3 scripts/qa/points_chain_release_gate.py
```
