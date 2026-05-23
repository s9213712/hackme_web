# PointsChain Real Incident Gap Matrix

Date: 2026-05-23
Scope: RC1 is closed. This document maps real blockchain and exchange incident
patterns to RC1/RC1.1 guardrails. New public-chain, bridge, P2P, full DAO, or
generic user multisig-spend features remain post-RC1 unless explicitly reopened.

## Severity Policy

P0 items can directly corrupt balances, drain official funds, bypass
governance, or make operators sign malicious treasury payloads. They must be
hard-blocked or covered by release gates before production use.

P1 items can cause material loss, unfair execution, privacy leakage, or
operational failure as traffic grows. They must have a documented guardrail and
targeted regression tests before enabling higher-risk exchange/governance
features.

P2 items are important but either depend on post-RC1 expansion, need a broader
product decision, or can be mitigated with UI warnings and runbooks for now.

## P0 - Severe Incidents To Hard-Block

| Incident class | Real-world reference pattern | Current project risk | RC1/RC1.1 handling | Status |
| --- | --- | --- | --- | --- |
| Multisig signing UI / frontend supply-chain swap | Bybit/Safe-style masked signing where the displayed action differs from signed payload | Official treasury signers may approve a malicious payload if browser UI is compromised | Signer Center exposes canonical `execution_payload_hash`, signing payload, and signing payload hash; frontend shows payload/signing hashes before signature. Offline independent verifier UX remains RC1.1-B. | Backend/UI hash guard covered; external verifier pending |
| Governance capture / flash-loan-style fast takeover | Beanstalk on-chain governance attack | Public/common-interest or protocol proposals could be rushed or spammed | Trusted-only public proposal, sponsor/review, duplicate detection, rate limit, voter snapshot, no root veto for public proposals, timelock. | Covered by tests; keep gated |
| Genesis / migration / branch allocation replay | Bitcoin overflow and fork recovery lessons; project branch migrations | Re-running genesis/migration/fork seed could mint/fund twice or zero official funds | Genesis allocation, recovery branch seed, and system fund carry-forward must be idempotent and branch scoped. Supply equation must pass after fork/restore. | Covered; keep gated |
| Oracle / market manipulation | Mango Markets-style price manipulation | Future P2P/market-making/contract/lending features could treat local prices as final risk truth | Current RC1 must not enable high-risk derivatives. Before expansion, require TWAP/source quorum/liquidity floor/position cap/price circuit breaker. | Hard-block expansion; P1 design |
| Exchange asset/liability opacity | Mt. Gox / FTX-like asset-liability mismatch | Fund balance alone does not prove what the platform owes users | Add liability ledger v0 before exchange liability expansion; current treasury analysis separates official fund income/expense but not full proof-of-liability. | Active P0 for exchange expansion |
| Service revenue double accounting | High-frequency internal fee/tip settlement race | One user action can create debit/credit/fee compatibility rows and accidentally duplicate economy events | Product ledger compatibility rows must not double-count chain fund flow. Video tip debit is now internal; net creator credit and official fee are the only economy events. | Fixed in this pass |
| Supply expansion abuse | Emergency mint / monetary policy capture | Max supply can be diluted if root or treasury shortcuts exist | Hard cap by default; `SUPPLY_EXPANSION_REQUEST` only changes max supply after strict protocol governance. Mint remains a separate treasury flow. | Covered by tests; keep gated |
| Timelock / executor bypass | Governor/timelock misconfiguration class | Mint, freeze, rollback branch, treasury transfer, and supply expansion could execute directly | API execution checks proposal status, payload hash, timelock, veto, signer snapshot and multisig threshold. | Covered by tests; keep gated |
| Local integrity seed compromise | DB plus `.chain_seed` compromise | Local HMAC detects DB tamper only under host-integrity assumptions | Anchor v0 exports signed local checkpoints; external immutable anchor/offline checkpoint remains post-RC1 production hardening. | RC1.1-A covered; external anchor pending |

## P1 - Material Hardening Required Before Higher-Risk Expansion

| Incident class | Real-world reference pattern | Project risk | Handling | Status |
| --- | --- | --- | --- | --- |
| Frontend DNS / phishing / signing prompt confusion | Curve DNS hijack and blind-signing incidents | Users may sign a valid key over malicious text on a poisoned page | Purpose-specific signing payloads, statement length validation, local signature only, and future signed-release/integrity UI. | Partially covered |
| Transaction malleability / economic idempotency mismatch | Historic tx-id malleability class | Same economic action might produce multiple hashes and bypass idempotency | Canonical payload hash, request UUID, purpose, chain branch, idempotency key and replay tests. | Covered for core paths |
| MEV / ordering / priority fee abuse | Ethereum MEV, sandwich, priority-gas behavior | Pending transfers/orders/disputes can leak actionable state | Keep transfer finality; add deterministic order queue audit, commit-reveal or batch matching before public high-value orderbook. | Pending P1 |
| Server-time / timelock manipulation | Timelock/voting deadline weakness | Single-node server time controls voting and execution windows | Proposal creation snapshots voting/timelock/quorum into `execution_guard`; row tampering cannot shorten timelock without guard mismatch. Governance writes also compare wall-clock elapsed against monotonic elapsed; large clock jumps enter PointsChain safe mode before vote/sign/execute. Full host compromise still needs external anchor/NTP monitoring. | RC1.1 local guard covered; external monitoring pending |
| Stablecoin/external reserve depeg | USDC/SVB, Terra UST | Future external assets cannot rely on on-chain balance alone | External asset reserve/depeg runbook is post-RC1; no external asset bridge in RC1. | Deferred by scope |
| Address poisoning / dusting | Public-chain privacy and copy/paste attacks | Tiny transfers can associate addresses or trick copy/paste | Public UI must not expose manager-only labels; add checksum/highlight, tiny inbound warning, and manager-only annotation tests. | Partially covered |
| Stuck freeze / stuck proposal | Governance ops failure | Temporary freeze or treasury proposal could strand funds | Expiry jobs, unfreeze audit and repair runbook; add observability alert in RC1.1-B. | Covered by tests, alert pending |
| Dependency / release artifact compromise | Wallet/signature frontend supply-chain attack | Wallet-signing JS is a critical trust boundary | Add release artifact checksum/SRI policy and CI diff review for wallet-signing bundle. | Pending P1 |

## P2 - Can Be Mitigated Without Expanding RC1 Scope

| Incident class | Project risk | Practical handling now | Status |
| --- | --- | --- | --- |
| Dust privacy inference | Users may infer account behavior from dusted addresses and notifications | Do not identify public wallet owners; manager-only labels never leak to public APIs; add UI warning for suspicious tiny inbound transactions. | Pending |
| Public explorer confusion | Users can confuse non-canonical branches, provisional freezes, and spendable balance | Explorer must show branch canonical status and separate balance freeze from governance outbound restriction. | Mostly covered |
| Generic user multisig spend | Premature Safe-like feature can introduce signing, rotation and replay bugs | RC1 keeps user multisig receive-only; full user multisig spend remains post-RC1 design. | Covered by hard-block |
| Full forensic taint graph | Without graph, dispute/recovery evidence is harder to review | Implement address/tx graph v0 only; full taint scoring stays post-RC1. | Deferred |
| External public-chain bridge | Bridge bugs are historically high-impact | No bridge in RC1/RC1.1; require separate threat model and release gate. | Deferred |

## Implemented In This Pass

- `service_fee_batch_debit` settles to the official Treasury fund, not BURN.
- Chain transfer fees and acceleration fees still go to BURN.
- Treasury Signer Center has dynamic income/expense analysis from live ledger
  and economy-event tables.
- Video tipping now records one net creator economy event and one official
  platform-fee economy event; the gross debit compatibility ledger row no
  longer creates a duplicate economy event.
- Governance proposals now include an execution guard snapshot for voting,
  timelock, expiry, quorum and threshold fields; execution rejects deadline row
  tampering before running the action.
- Governance vote/sign/execute paths now compare wall-clock elapsed against
  monotonic elapsed and enter PointsChain safe mode on suspicious local clock
  jumps instead of trusting a suddenly advanced system clock.
- Economy health now evaluates releasable supply before total max-supply
  remainder, so locked reserve cannot hide ordinary mint exhaustion.
- Dispute escalation deadline changes update the proposal deadline guard and
  execution payload hash atomically; direct row tampering still fails guard
  verification.
- Treasury Signer Center now exposes the canonical multisig signing payload and
  signing hash so signers can compare what they are about to sign.
- Service-fee pricing presets are editable settings suggestions, not financial
  source of truth.

## Gate Requirements

- Video tip economy events must total the user-paid gross amount exactly once.
- Treasury service revenue must reconcile to official fund economy events.
- Supply equation gap must remain zero after seal/replay/restore/fork tests.
- Releasable supply exhaustion must report red health even when
  `mint_remaining` still includes locked reserve.
- Governance execution must reject tampered payload hash and active timelock.
- Dispute-driven freeze proposal deadline changes must not break legitimate
  execution, but manual deadline tampering must still be rejected.
- Public/governance proposals must preserve voter/signature snapshots.
- User multisig remains receive-only in RC1.

## References

- Bitcoin value overflow incident / CVE-2010-5139:
  https://en.bitcoin.it/wiki/CVE-2010-5139
- Bybit / Safe signing incident technical analysis:
  https://www.certik.com/skynet-report/3wI26AFKF1UtSDjJEXNEDM-bybit-incident-technical-analysis
- Beanstalk governance attack disclosures:
  https://docs.bean.money/almanac/disclosures
- Mango Markets oracle manipulation analysis:
  https://www.certik.com/skynet-report/mango-market
- Parity multisig freeze incident:
  https://dn.institute/research/cyberattacks/incidents/2017-11-06-parity/
- Circle USDC / SVB depeg statement:
  https://www.circle.com/pressroom/3-3-billion-of-usdc-reserve-risk-removed-dollar-de-peg-closes
