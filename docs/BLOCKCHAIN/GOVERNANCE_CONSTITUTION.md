# PointsChain Governance Constitution

Status: RC1 governance blueprint and enforcement baseline.

PointsChain governance is an enforceable control layer, not only a voting UI.
Financially sensitive operations must pass proposal lifecycle, vote policy,
timelock, payload-hash verification, veto rules where applicable, multisig
signing where required, and append-only audit logging before execution.

## Reference Model

- Ethereum/EIP and Bitcoin/BIP style: proposal documents must include a clear
  specification, rationale, evidence, discussion record, and dissent record.
- Aave style: proposals require quorum, approval threshold, vote differential,
  lifecycle state, queue/timelock, and explicit execution.
- MakerDAO style: emergency shutdown/lockdown is a last resort for severe
  market abnormality, exploit, hack, or security incident.
- OpenZeppelin Governor/Timelock style: a passed proposal is queued and cannot
  execute until timelock and payload integrity checks pass.

Reference links:
- Ethereum EIP-1: https://eips.ethereum.org/EIPS/eip-1
- Aave governance voting: https://aave.com/help/governance/voting
- Maker Protocol Emergency Shutdown: https://docs.makerdao.com/smart-contract-modules/shutdown
- OpenZeppelin governance/timelock: https://docs.openzeppelin.com/contracts/4.x/api/governance

## Governance Domains

### PUBLIC_COMMON_INTEREST

Scope:
- Scam address marking.
- Public address freeze/unfreeze.
- Auto burn policy for inflation control.
- Public protocol trust decisions.

Proposal authority:
- Manager+ can directly create a public proposal.
- Trusted/vip users may create public proposals only through the gated public
  proposal path.
- Trusted-user public proposals enter REVIEW and require manager+ sponsor before
  voting.
- Normal-user public proposal abuse is controlled by rate limits, duplicate
  detection, severity, and proposal deposit metadata.

Voting authority:
- Active users vote.
- Root has no veto.
- Root can propose, vote, sponsor if manager+ by role, and execute a passed
  proposal, but cannot cancel or override the result.

Execution:
- Requires SUCCEEDED/QUEUED/TIMELOCKED -> executable state.
- Requires timelock elapsed.
- Requires execution_payload_hash unchanged.
- Writes append-only governance audit.
- Rollback/recovery branch and hard-fork acceptance are not filed through the
  public proposal endpoint in RC1. Users can report incidents; manager/security
  sponsors must convert them into formal emergency/protocol proposals.

### OFFICIAL_TREASURY

Scope:
- Mint request.
- Official treasury transfer.
- Exchange fund replenish.
- Contest reward payout.
- Official fund rebalance.

Proposal authority:
- Manager+ only.
- Normal users may submit suggestions outside this layer, but cannot create
  official treasury proposals directly in RC1.

Voting authority:
- Manager+ vote.
- Root may vote as manager+.
- Root has final veto.

Execution:
- Manager+ vote passing is not enough to move money.
- After governance passes and timelock clears, the official multisig signer
  threshold must be reached.
- Official multisig policy is captured into the proposal payload at proposal
  creation.
- Manager/root private wallets stay separate from official funds. A manager
  wallet may be a signer wallet, but it is never the source of official funds.
- Treasury execution always spends from the official treasury fund wallet or
  mints from the mint fund according to proposal action.

Multisig signing:
- Each signer signs the immutable execution payload hash for the proposal.
- A signer wallet must belong to the signing manager+ account and be listed in
  the captured official multisig policy.
- Signer identity is separate from manager identity. RC1 binds a signer to a
  manager/root-owned wallet and snapshots `signer_id`, weight, device id,
  public-key fingerprint, signer creation time, and revocation state.
- Signatures must satisfy both signer-count threshold and signer-weight
  threshold.
- Self-custody wallets require local signature verification.
- Server-hot official signer wallets use server-attested signatures in RC1 and
  are marked as such in audit data.
- Execution fails with a human-readable error if threshold is not reached.

### EMERGENCY_SECURITY

Scope:
- Incident lockdown.
- Emergency exploit response.
- Emergency freeze candidates.
- Rollback/recovery branch proposal.
- Severe system-risk response.

Proposal authority:
- Root, security admin, or emergency/manager council.
- RC1 maps this to manager+ until dedicated security roles exist.

Voting authority:
- Emergency council / manager+ fast vote.
- Root has no veto over emergency rollback/recovery execution in RC1.
- If user balances or public trust are affected, a public after-action review
  and ratification report is required before release.

Execution:
- May enter safe mode / incident lockdown.
- May activate a recovery branch pointer.
- Must write forensic/audit records.
- Must include reason, evidence, impact, and follow-up public report.

### PROTOCOL_PARAMETER

Scope:
- Chain fee model.
- Congestion and acceleration formula.
- Service-fee batch thresholds.
- Burn policy parameters.
- Trading risk parameters when they affect chain economics.
- Feature activation that changes financial rules.

Proposal authority:
- RC1: manager+.
- Post-RC1 can allow threshold-qualified users with sponsor and deposit.

Voting authority:
- Public vote for broad economic/user-rights impact.
- Manager+ vote for low-risk operational tuning.

Execution:
- Requires payload hash match and timelock.
- RC1 records approval; direct automatic parameter mutation should be added only
  per specific parameter handler.

### ADMIN_POLICY

Scope:
- Moderation policy.
- Upload/rate policy.
- Admin operational limits.
- UI policy that does not directly affect user balances.

Proposal authority:
- Manager+.

Voting authority:
- Manager+.
- Root veto allowed.

Execution:
- Must be audited.
- Must not directly mutate balances or ledger.

## Proposal Lifecycle

Canonical lifecycle:

1. DRAFT
2. REVIEW
3. VOTING
4. SUCCEEDED or FAILED
5. QUEUED
6. TIMELOCKED
7. EXECUTED, VETOED, EXPIRED, or CANCELLED

Current RC1 compatibility mapping:

- `status=voting` plus `lifecycle_status=REVIEW` means a user proposal is
  awaiting sponsor and cannot accept votes.
- `status=voting` plus `lifecycle_status=VOTING` means votes are open.
- `status=passed` plus `lifecycle_status=QUEUED` means vote passed and no
  active timelock remains.
- `status=passed` plus `lifecycle_status=TIMELOCKED` means vote passed but
  execution must wait.
- `status=executed` plus `lifecycle_status=EXECUTED` means the action ran.
- `lifecycle_status=VETOED` means root veto was used where allowed.

## Required Proposal Fields

Every proposal record must carry:

- `proposal_uuid` / `proposal_id`
- `title`
- `description`
- `reason`
- `evidence_refs`
- `governance_domain`
- `action_type`
- `proposal_severity`
- `proposer_user_id`
- `sponsor_required`
- `sponsor_user_id`
- `target_wallet`
- `target_address`
- `target_branch`
- `requested_amount`
- `requested_asset`
- `quorum_required`
- `yes_threshold`
- `vote_differential_required`
- `voting_starts_at`
- `voting_ends_at`
- `timelock_ends_at`
- `root_veto_allowed`
- `root_veto_used`
- `execution_payload_hash`
- `executed_at`
- `execution_result`
- `audit_hash`
- `prev_audit_hash`

## Proposal Authority Matrix

| Domain | Who Can Propose | Who Can Vote | Root Veto |
| --- | --- | --- | --- |
| PUBLIC_COMMON_INTEREST | manager+ directly; trusted+ users via REVIEW + sponsor | active users | no |
| OFFICIAL_TREASURY | manager+ | manager+ | yes |
| EMERGENCY_SECURITY | root/security/emergency council; RC1 manager+ | emergency council / manager+ | limited by action; no public rollback veto |
| PROTOCOL_PARAMETER | RC1 manager+ | active users or manager+ by impact | by action only |
| ADMIN_POLICY | manager+ | manager+ | yes |

## Authority Separation

The system treats these as separate powers:

- Proposal right: who can open or sponsor a proposal.
- Voting right: who can decide the proposal.
- Execution right: who can press execute after policy checks pass.
- Veto right: root veto only where domain policy allows it.
- Emergency right: temporary safety controls with audit and follow-up review.
- Multisig signing right: who can sign official wallet execution after
  governance passes.

Voting approval is not wallet authorization. Official treasury operations need
both governance approval and official multisig signing.

## Official Multisig Signing Flow

The jointly managed official wallet is a multisig-controlled fund wallet. Its
multisig configuration is not changed by a governance vote. Governance decides
whether an official-wallet action is allowed; multisig signing authorizes the
fund wallet to spend after that decision.

RC1 treats the official multisig policy as immutable per proposal: signer set,
threshold, fund key, and policy version are copied into the proposal payload
before voting. Later wallet/profile changes do not modify that proposal. A
future governance action may change the official multisig policy itself, but it
must be a separate high-severity treasury/admin proposal, not an implicit side
effect of a payout proposal.

Execution sequence:

1. Manager+ creates an OFFICIAL_TREASURY proposal.
2. The proposal payload captures the current official multisig policy, signer
   wallet addresses, threshold, target wallet, amount, action type, reason, and
   execution payload hash.
3. Manager+ voters approve or reject the proposal.
4. Root may veto only when `root_veto_allowed=true`.
5. The proposal waits through timelock when required.
6. Each listed signer signs the immutable execution payload hash with their own
   manager/root private signer wallet.
7. The system records one signature per signer wallet in the append-only
   governance multisig table.
8. Execution is allowed only when the captured threshold is reached and the
   payload hash still matches.
9. The executor submits the transaction from the official treasury fund wallet;
   the manager/root private signer wallet is never the fund source.
10. The execution result is written to the governance audit hash chain.

Signer rules:

- A signer wallet must belong to the signing manager+ account.
- A signer wallet must be part of the captured official multisig policy.
- Signer readiness is weighted: RC1 stores root weight 3, super-admin weight 2,
  manager weight 1, and requires both count threshold and weight threshold.
- Device binding is snapshotted by `device_id` plus public-key fingerprint. A
  missing explicit device id is replaced with a deterministic wallet fingerprint
  so the proposal still has an auditable signer-device record.
- Revoked/closed signer wallets do not count toward readiness.
- Self-custody signer wallets must provide a local signature; the server never
  stores or echoes the private key.
- Server-hot signer wallets are allowed in RC1 only as server-attested signer
  entries and are clearly recorded as `server_attested`.
- The same signer wallet cannot count twice for one proposal.
- Changing signer wallets after proposal creation does not alter the captured
  policy for that proposal.

This keeps three identities separate:

- Official fund wallet: the source of official funds.
- Manager/root private wallet: the signer identity.
- User recipient wallet: the destination of the approved transfer.

## Anti-Governance-Abuse

RC1 baseline:

- Public proposals by normal users enter REVIEW.
- Public proposal creation requires trusted/vip member level or manager+.
- Manager+ sponsor is required before voting.
- Public proposals have rate limit metadata and same-target duplicate checks.
- Proposal severity changes quorum/timelock/deposit metadata.
- Proposal deposits are recorded as metadata in RC1; full reserve/burn/refund
  settlement is post-RC1 unless made a blocker later.

Recommended post-RC1 hardening:

- Reserve proposal deposit on-chain.
- Refund deposit if proposal passes or reaches minimum support.
- Burn part of deposit if rejected as spam.
- Cooldown duplicate failed proposals.
- Add reputation/stake/member-age gates.

## Enforcement Rules

- Mint cannot be executed by root directly.
- Mint in RC1 is an OFFICIAL_TREASURY `MINT_REQUEST`: manager+ proposal,
  manager+ vote, root veto allowed, timelock when configured, official multisig
  threshold, payload hash verification, then mint into the official fund.
- Supply expansion is not a mint request. It is a constitutional
  `PARAMETER_CHANGE` with `payload.proposal_type=SUPPLY_EXPANSION_REQUEST` and
  `payload.execution_class=MONETARY_POLICY_AMENDMENT`; root has no veto, the
  vote is active-user scoped with critical thresholds, and execution only
  increases `max_supply`. Follow-up minting still requires `MINT_REQUEST`.
- Official treasury transfer cannot be executed by root directly.
- Official treasury transfer requires manager+ vote, optional root veto window,
  timelock elapsed, payload hash unchanged, and official multisig threshold
  reached.
- Exchange fund replenish is an official treasury operation.
- Contest reward payout is an official treasury operation.
- Scam marking and public freeze/unfreeze are public-interest actions; root has
  no veto.
- Rollback/recovery branch is an emergency-security action. RC1 creates a
  branch-isolated asset universe: old ledger rows remain immutable and readable,
  the old branch becomes read-only/non-canonical, and the new branch seeds
  balances by replaying the parent branch while excluding governance-approved
  incident transaction references.
- Freeze blocks outgoing transfer only. It does not delete ledger, confiscate
  points, or transfer ownership.
- Failed execution must return a human-readable error. Silent failure is a bug.
- Governance audit log is append-only and hash-chained.

## Current RC1 Implementation Notes

Implemented:

- Governance proposal domain/action fields.
- Lifecycle status fields.
- Root veto field and root veto endpoint.
- Public proposal sponsor path.
- Official treasury proposal path.
- Official multisig signature table and threshold enforcement.
- Payload hash verification before execution.
- Timelock enforcement.
- Append-only governance audit hash chain verification.
- Root direct official grant is blocked unless tied to an executed governance
  proposal payload.

Still deferred:

- Real proposal deposit reserve/refund/burn settlement.
- Dedicated finance/security/research roles.
- Dedicated official multisig wallet management UI.
- True client-side multisig signing UX for all signer wallet types.
- Automatic parameter mutation handlers for each protocol parameter.
