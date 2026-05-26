# Incident Runbook RC1

Status: minimum operational runbook for controlled PointsChain RC1.

Every high-risk incident action must write audit logs. If an action cannot
write audit, keep the system in safe/maintenance mode until audit is restored
or a manual incident report is appended.

## 1. Initial Containment

1. Enable safe mode or maintenance mode.
2. Stop user outbound transfer.
3. Stop product direct spend.
4. Stop exchange collateral movement and high-risk trading operations.
5. Stop treasury execute.
6. Keep read-only status, login, root/admin audit view, and necessary recovery
   actions available.

Safe mode ON means:

- user outbound transfer is forbidden
- product direct spend is forbidden
- exchange collateral movement is forbidden
- treasury execute is forbidden
- read-only status is allowed
- root/admin audit review is allowed
- necessary unfreeze/recovery admin actions may run only with audit

## 2. Preserve Evidence

1. Record incident time, actor, affected route, affected wallet addresses, and
   suspected tx hashes.
2. Back up the DB.
3. Back up chain artifacts, including `.chain_seed`, chain backups, and runtime
   logs.
4. Do not edit ledger rows manually.
5. Do not delete blocks, proposals, disputes, or wallet identities.

## 3. Verify Chain Integrity

Run the release-gate chain checks:

```bash
python3 scripts/qa/points_chain_release_gate.py --skip-live
```

If only block-tamper verification is needed, run the targeted tamper tests in:

```bash
pytest -q tests/points/test_points_chain.py \
  -k "tamper or forged or append_only or auto_resign"
```

If verify fails, keep safe mode on and treat the runtime as compromised until
the branch/governance recovery plan is chosen.

## 4. Scanner Check

Run:

```bash
python3 scripts/security/gate/wallet_direct_call_inventory.py --fail-on-blocker
```

Any blocker means release remains stopped until the path is removed, gated, or
classified as non-runtime migration/test code.

## 5. Dispute Freeze Stuck

1. Identify the dispute UUID and To address.
2. Check whether the dispute is rejected, cancelled, expired, or escalated.
3. If rejected/cancelled/expired, run the expiry/unfreeze job or the existing
   dispute review path to release the provisional freeze.
4. Confirm explorer shows no `governance_freeze` for the address.
5. Append audit with reason and operator.

## 6. Mistaken Freeze

1. Confirm whether freeze is provisional or governance-backed.
2. Provisional freeze may be dismissed by root/manager review according to the
   anonymous address-proven dispute flow.
3. Governance freeze requires the matching unfreeze governance path unless it
   expired by policy.
4. Do not confiscate, refund, or rollback assets directly.

## 7. Official Treasury Proposal Stuck

Check:

- proposal status/lifecycle
- root veto status
- timelock time
- execution payload hash
- signer snapshot
- signature count and weight
- signer revocation state

If a signer is compromised, revoke or rotate the signer through the signer
lifecycle controls and invalidate affected pending signatures where policy
requires it.

## 8. Maintenance Bypass Token

- Bypass token must be sent only through `X-Maintenance-Bypass-Token`.
- Query string bypass token is invalid.
- Rotate the token after any suspected exposure.
- Logs must not echo token values.

## 9. Restore

1. Restore DB and chain artifacts from the same backup set.
2. Verify canonical branch pointer.
3. Verify ledger, blocks, governance audit hash, and derived cache.
4. If branch pointer, audit hash, DB, and chain artifacts disagree, enter
   incident lockdown and do not accept writes.

## 10. Authority

- root: emergency containment, audit view, allowed veto only for treasury
  proposals, no public-governance veto.
- manager+: treasury proposal/vote/sign where eligible, governance review,
  signer center actions where policy allows.
- ops: runtime backup/restore and safe-mode operations according to deployment
  policy.
- normal user: address-proven dispute submission and public governance voting
  where eligible.
