# PointsChain Governance Security Model

Status: RC1 enforcement model.

## Rule Summary

Governance approval never grants direct wallet control. Every sensitive action is split into proposal, voting, timelock, execution-bundle verification, optional root veto, official multisig signing, execution, and append-only audit.

## Governance Domains

| Domain | Proposal Right | Vote Right | Execution Right | Root Veto |
| --- | --- | --- | --- | --- |
| PUBLIC_COMMON_INTEREST | manager+ direct; trusted/vip users via REVIEW + sponsor | active users | manager+ after checks | no |
| OFFICIAL_TREASURY | manager+ | manager+ | manager+ after timelock + multisig | yes |
| EMERGENCY_SECURITY | root/security/emergency council; RC1 manager+ | emergency council / manager+ | manager+ after checks | no for rollback |
| PROTOCOL_PARAMETER | RC1 manager+ | public or manager+ by impact | manager+ after checks | action-specific |
| ADMIN_POLICY | manager+ | manager+ | manager+ after checks | yes |

## Action Placement

| Action | Domain | Notes |
| --- | --- | --- |
| MARK_SCAM | PUBLIC_COMMON_INTEREST | Public explorer risk label; root cannot veto. |
| FREEZE_ADDRESS / UNFREEZE_ADDRESS | PUBLIC_COMMON_INTEREST | Blocks outgoing transfers only; no confiscation. |
| ROLLBACK_BRANCH | EMERGENCY_SECURITY | Branch-isolated recovery fork; old ledger rows remain immutable. |
| EMERGENCY_LOCKDOWN | EMERGENCY_SECURITY | Safe-mode/incident lockdown path. |
| MINT_REQUEST | OFFICIAL_TREASURY | Vote + root veto window + timelock + official multisig. |
| TREASURY_TRANSFER | OFFICIAL_TREASURY | Official fund source only, never manager private wallet. |
| EXCHANGE_FUND_REPLENISH | OFFICIAL_TREASURY | Treasury-governed liquidity movement. |
| CONTEST_REWARD_PAYOUT | OFFICIAL_TREASURY | Treasury-funded payout. |
| PARAMETER_CHANGE / FEATURE_ACTIVATION | PROTOCOL_PARAMETER | RC1 records approval; direct mutation needs a handler. |
| HARD_FORK_ACCEPTANCE | PROTOCOL_PARAMETER | Not open to public direct proposal in RC1. |

## Signer Security

RC1 separates these identities:

- Manager identity: account role used for governance vote/sponsor/execute.
- Treasury signer identity: wallet key used to sign official-wallet execution.
- Official fund wallet: the fund source controlled by policy.
- Recipient wallet: destination address.

Official multisig policy is snapshotted into each treasury proposal:

- signer set
- signer wallet addresses
- signer weights
- signer id
- device id
- public-key fingerprint
- signer creation time
- threshold count
- threshold weight
- fund key
- policy version

Execution requires both signature count threshold and signature weight threshold. Revoked or closed signer wallets do not count. Changing the signer set after proposal creation does not change the proposal payload.

## Proposal Snapshot

At creation time the proposal freezes:

- eligible voter ids
- eligible voter count
- quorum count
- threshold rates
- proposal severity
- timelock/expires policy
- execution bundle hash
- official multisig policy when applicable

This prevents mid-vote voter/signer manipulation from changing an active proposal.

## Execution Bundle

The execution bundle hashes:

- action type
- governance domain
- target wallet
- target address
- target branch
- requested amount
- requested asset
- payload metadata

Execution rejects payload hash mismatch and returns a human-readable error.

## Rollback Scope

RC1 supports chain-branch recovery, not mutable database rollback:

- Ledger rollback: not allowed in RC1.
- Governance rollback: not allowed by direct mutation; use a new governance proposal.
- Runtime snapshot rollback: ops-only recovery, separate from chain governance.
- Chain fork/recovery branch: allowed through EMERGENCY_SECURITY.

Recovery branch semantics:

- Every ledger and pending transfer carries `chain_branch`.
- Only one branch is canonical and write-enabled.
- The old branch remains readable, but is read-only and non-canonical.
- Wallet balances are replayed only inside the active branch.
- A recovery branch seeds a new branch-local genesis balance by replaying the
  parent branch while excluding the incident transaction references approved by
  governance.
- Old-branch assets cannot be spent on the new branch.
- Same wallet address may have different balances on different branches.
- Cross-branch balance merge is forbidden because it creates double-spend or
  inflation risk.

This follows the social-consensus fork pattern used in real chains: Ethereum's
DAO hard fork changed the chain accepted by the community while the non-fork
chain continued separately; Bitcoin's March 2013 chain fork resolution chose
one valid history as canonical; Binance's 2019 Bitcoin reorg discussion shows
why theft rollback is treated as an extreme governance/security action rather
than a routine admin tool.

References:

- Ethereum Foundation, Hard Fork Completed: https://blog.ethereum.org/2016/07/20/hard-fork-completed
- Ethereum Foundation, Onward from the Hard Fork: https://blog.ethereum.org/2016/07/26/onward-from-the-hard-fork
- Bitcoin.org, 11/12 March 2013 Chain Fork Information: https://bitcoin.org/chainfork
- BIP 50 March 2013 Chain Fork Post-Mortem: https://bips.dev/50/
- Coindesk, Binance Bitcoin rollback/reorg discussion: https://www.coindesk.com/markets/2019/05/08/what-a-bitcoin-reorg-is-and-what-binance-has-to-do-with-it

## UI Boundaries

- Public governance UI is visible only to trusted/vip users and manager+.
- Treasury governance UI is visible to manager+.
- Emergency Security UI is visible to manager+ and styled as high risk.
- Root sees veto only when `root_veto_allowed=true`.
- Proposal cards must show timeline, readiness, timelock, multisig state, payload state, and audit hash.

## Current RC1 Deferred Items

- Dedicated security/finance/research roles.
- Full signer rotation governance UI.
- On-chain proposal-deposit reserve/refund/burn.
- Public observer explorer page separate from the economy tab.
- Parameter-specific execution handlers.
