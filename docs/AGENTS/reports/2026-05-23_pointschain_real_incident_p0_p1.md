# PointsChain Real Incident Gap Review P0/P1/P2

Date: 2026-05-23
Scope: RC1 closed; apply only as regression gates, RC1.1 operational hardening, or post-RC1 backlog.

Canonical matrix: `docs/BLOCKCHAIN/POINTSCHAIN_REAL_INCIDENT_GAP_MATRIX.md`.

## P0 - Must Be Gated Or Explicitly Hard-Blocked

| Incident class | Real-world reference pattern | Project relevance | Required handling |
| --- | --- | --- | --- |
| Fork / branch replay | Ethereum DAO fork and later chain-id replay-protection lessons | PointsChain has recovery branches and signed wallet payloads | Keep branch_id / purpose / request_uuid / payload_hash in every signature. Gate cross-branch replay tests. |
| Signed message replay / copycat drain | Nomad-style replay/copycat bridge drain pattern | Dispute open/reply, cold-wallet spend, treasury multisig signing | Signature idempotency and purpose isolation must remain P0 tests. Duplicate signed payload must fail. |
| Multisig signer compromise | Ronin / bridge validator-key compromise pattern | Official treasury multisig is the highest-value wallet | Revoke/rotation drill, signer snapshot immutability, disabled signer cannot sign, threshold cannot be changed mid-proposal. |
| Signature verification bypass | Wormhole guardian-signature validation failure pattern | Wallet signatures, official multisig signatures, dispute address proof | Payload hash must cover full execution bundle; no partial verification; execution must verify exact payload hash. |
| Governance timelock / executor bypass | Governor/timelock misconfiguration class | Mint, treasury transfer, freeze, branch recovery, supply expansion | No direct API execution. Queue/timelock/ready state and root veto rules must be enforced server-side. |
| Oracle / market manipulation | Mango-style oracle/market manipulation | Trading prices, exchange fund health, future margin/lending | Current spot/trading must not treat manipulable local price as final risk truth; before margin/liability expansion, add TWAP/source quorum/price bounds. |
| Service-fee reserve double-spend | High-frequency fee settlement race | New service-fee subledger and batch settlement | Reserved service fees must freeze spendable balance; batch settlement must be idempotent and branch scoped. |
| Local integrity seed compromise | Host compromise of DB plus `.chain_seed` | RC1 tamper detection is local HMAC | External anchor v0/offline checkpoint is operational P0 for production, not RC1 feature expansion. |
| Supply expansion abuse | Monetary-policy capture / emergency mint risk | Hard cap plus constitutional expansion clause | Supply expansion must be separate from mint/spend; high quorum/timelock; root cannot directly raise max_supply. |
| Operator/safe-mode abuse | Centralized emergency halt concerns | Permissioned single-node chain | Safe mode must be audited, read-only views remain available, unblock/unfreeze runbook required. |
| Multisig signing UI / frontend supply-chain swap | Bybit/Safe-style masked signing | Official treasury signer browser can be compromised | Show canonical payload details and hash before signing; add offline verifier/checksum as RC1.1-B. |
| Genesis / migration / branch allocation replay | Value-overflow/fork recovery and migration replay class | Genesis allocation and branch seed can duplicate or zero funds | Idempotent genesis/migration/fork seed; total supply equation must pass after replay/restore/fork. |
| Exchange asset/liability opacity | Mt. Gox / FTX-like mismatch | Fund balance does not prove user liabilities | Add exchange liability ledger before liability expansion. |
| Service revenue double accounting | Product-ledger compatibility rows can duplicate economy events | Video tip gross debit plus net/fee rows can overstate flow | Gross debit is internal; net creator credit and official fee are the only economy events. |

## P1 - Next Hardening Backlog

| Incident class | Project relevance | Recommended next step |
| --- | --- | --- |
| Mempool / ordering / MEV analog | Internal matching/order submission can still be ordered unfairly | Add order timestamp audit, deterministic queue policy, and admin/operator self-dealing alerts. |
| Governance spam / capture | Trusted users can submit public-interest disputes/proposals | Deposit/rate-limit/similarity hash, sponsor audit, voting power snapshot, high-risk longer timelock. |
| Address poisoning / dusting | Users may copy similar pc1 addresses or receive tiny funds | UI checksum/highlight, address book warnings, suspicious tiny inbound labeling. |
| Wallet-drain phishing | Self-custody signatures can be tricked by bad UI text | Human-readable signing payload preview and purpose-specific signer UI. |
| Snapshot / backup poisoning | Restore can preserve corrupted but hash-consistent state | Independent restore drill, external anchor comparison, pre-restore evidence pack. |
| Fee-model griefing | Attackers can generate many low-value service reserves | Per-address service fee reserve caps, batch throttle, stale reserve release job. |
| Exchange liability mismatch | Exchange fund and positions can diverge as features expand | Liability ledger before P2P/margin/liquidation expansion. |
| Stuck proposal / stuck freeze | Governance or timers can leave assets blocked | Repair tools with audit trail and expiry job monitoring. |
| Supply-chain dependency compromise | Wallet/signature/frontend JS is a critical trust boundary | Lockfile audit, SRI for third-party assets, release artifact checksum. |
| Privacy leak through admin annotations | Official hot wallet labels are manager-only | Snapshot tests for public APIs and UI role gating. |
| Frontend DNS / phishing signing prompt confusion | Local signature can still sign malicious prompt content | Purpose-specific payload preview and release integrity checks. |
| Server-time / timelock manipulation | Single-node time controls governance windows | Execution guard snapshots deadline fields; live process compares wall-clock elapsed against monotonic elapsed and enters safe mode on suspicious jumps. External NTP/anchor monitoring remains required for full host compromise. |

## P2 - Mitigate Without Expanding RC1 Scope

| Incident class | Project relevance | Recommended handling |
| --- | --- | --- |
| Dust privacy inference | Small inbound transfers can associate addresses with account behavior | Keep owner labels manager-only, add tiny inbound warning, avoid identity-bearing public notifications. |
| Public explorer confusion | Non-canonical branches and governance freezes can be mistaken for spendable balance | Keep branch/canonical status visible and separate amount freeze from governance outbound restriction. |
| Generic user multisig spend | Safe-like user wallets need full signer lifecycle and replay protection | Keep receive-only hard-block in RC1; design only until full gate exists. |
| Full forensic taint graph | Disputes need better address/tx evidence over time | Address/tx graph v0 can be RC1.1; full taint scoring remains post-RC1. |
| External bridge/deposit/withdraw | Bridge incidents are high-impact and out of RC1 scope | Keep disabled; require separate threat model and release gate. |

## Current Delta From This Task

- Site service-fee batch settlement is now modeled as official Treasury income.
- Chain transaction fee and acceleration fee remain BURN-only.
- Treasury Signer Center now exposes dynamic income/expense analysis from live ledger tables, not static copy.
- Pricing presets are editable settings and not hard-coded financial truth.
- Video tipping now avoids duplicate economy-event accounting: gross debit is an internal compatibility ledger row; net creator revenue and official platform fee are the chain fund-flow rows.
- Official Treasury signer center exposes canonical multisig signing payload + signing hash for signer-side comparison.
- Governance execution guard snapshots voting/timelock/expiry/quorum fields and rejects row-tampered deadlines.
- Governance vote/sign/execute paths now reject suspicious system-clock jumps by entering PointsChain safe mode before trusting timelock expiry.
- Economy health now keys mint-risk status off releasable supply, so reserved locked supply no longer masks releasable exhaustion.
- Dispute escalation freeze proposals now update the governance deadline guard and execution payload hash when their voting window is shortened to match the provisional-freeze deadline.

## Gate Additions

- P0: service_fee_batch_debit destination must be official_treasury.
- P0: wallet_transfer_fee and chain_acceleration_fee destination must remain burn.
- P0: Treasury analysis must be generated from current DB state and include generated_at.
- P0: video_tip_* economy events must sum to the gross tip once, not gross + net + fee.
- P0: official treasury signable item must include signing_payload_hash and execution_payload_hash.
- P1: proposal timelock row tamper must fail with execution guard mismatch.
- P1: system clock fast-forward must enter PointsChain safe mode and block governance execution.
- P1: releasable supply exhaustion must turn economy health red even when total max-supply remainder is non-zero.
- P1: dispute-driven freeze proposal deadline updates must keep execution guard valid while manual deadline tampering remains blocked.
- P1: UI must provide a manual refresh for Treasury analysis and quick service pricing controls.
- P2: public wallet/explorer UI must not leak manager-only wallet-owner annotations.
