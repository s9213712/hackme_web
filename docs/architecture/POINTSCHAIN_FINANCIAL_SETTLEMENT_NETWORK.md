# PointsChain Permissioned Financial Settlement Network

Status: active architecture direction for the PC0 / PC1 refactor.

PointsChain must no longer be treated as a traditional single-chain blockchain
dashboard. The production model is a permissioned multi-ledger financial
settlement network with formal boundaries between canonical reserve accounting,
operational wrapped accounting, and bridge settlement.

This terminology is not cosmetic. Product flows, dashboards, explorers,
governance actions, and QA gates must preserve these boundaries so operational
state cannot be mistaken for canonical reserve truth.

## Layer Definitions

| Layer | Formal name | Purpose | Must not do |
| --- | --- | --- | --- |
| PC1 | Canonical Settlement Layer | reserve, treasury, governance, mint/burn authority, final settlement, canonical ownership, bridge escrow | process exchange bots, game actions, high-frequency service debits, or reversible app runtime state |
| PC0 | Operational Wrapped Layer | exchange balances, game economy, bot trading, lending runtime, fast transfers, service payments, margin/liquidation runtime | mutate canonical reserve supply or present itself as a self-custody chain asset |
| Bridge | Cross-Ledger Settlement Layer | lock/mint, burn/unlock, settlement queues, reconcile, reserve invariant checks, bridge audit | appear as a direct PC1 transaction to a PC0 address |

The project should describe this architecture as:

```text
Permissioned Financial Settlement Network
```

It should not present PC0 as a trustless public chain, and it should not blur
PC0 operational balances with PC1 canonical assets.

## Supply Semantics

The following values are different financial categories and must be displayed,
tested, and audited separately:

- `Canonical Supply`: PC1 reserve-backed asset supply and mint/burn authority.
- `Wrapped Supply`: finalized PC0 operational liabilities.
- `Pending Settlement`: bridge transition state that has not finalized on both
  sides.
- `Treasury Reserve`: official PC1/PC0 reserve or operating funds, depending on
  the specific wallet role.
- `Operational Liquidity`: exchange, lending, bot, margin, game, and service
  runtime liquidity.

Pending settlement must not be merged into finalized reserve or finalized
wrapped liabilities. A dashboard may show these values together only when it
visually labels the layer and reconciliation meaning.

## Required Invariant Engine

The root financial invariant endpoint and release gates must cover these
categories:

1. Reserve invariants.
2. Bridge settlement invariants.
3. Mint/burn invariants.
4. Rollback isolation invariants.
5. Replay/idempotency invariants.
6. Ledger-boundary invariants.

Mandatory invariants:

```text
wrapped_supply <= canonical_locked_reserve
every PC0 mint must map to a PC1 reserve lock
every PC1 unlock must map to a PC0 wrapped burn
PC0 operations must never directly modify canonical reserve supply
bridge events must be append-only
operational rollback must never mutate canonical reserve
duplicate bridge events must not double-credit
pending settlement must not count as finalized reserve or finalized liability
```

## Mandatory Ledger Separation

The target physical layout is:

- `pc1_settlement_ledger`: canonical settlement entries, sealable into PC1
  blocks.
- `pc0_operational_ledger`: wrapped operational balance entries, append-only but
  not PC1 block-sealed.
- `bridge_settlement_events`: bridge state machine events and cross-ledger
  references.
- `reserve_audit_snapshots`: proof-of-reserve, proof-of-liability, invariant,
  and reconstruction snapshots.

The current implementation may remain transitional while using a classified
`points_ledger`, but every transition-state guard must assume the target
separation above. In particular, a `pc0` operational row inside a PC1 block is a
critical ledger-boundary violation.

## Bridge State Machine

Bridge settlement is a first-class financial subsystem. It should not be
implemented or displayed as a generic transfer table.

Canonical lifecycle states:

```text
PENDING_LOCK
LOCKED
CONFIRMED
MINTED
SETTLED
BURN_PENDING
BURNED
UNLOCK_PENDING
RELEASED
FAILED
REORGED
FROZEN
```

Deposit-like flow:

```text
PC1 lock / confirmed deposit
  -> Bridge event accepted
  -> PC0 wrapped mint or credit
  -> settled
```

Withdrawal-like flow:

```text
PC0 wrapped burn or lock
  -> Bridge event accepted
  -> PC1 unlock / release
  -> settled
```

Any bridge replay, duplicate webhook, delayed confirmation, or risk-status
change must be idempotent and auditable.

## Explorer Federation

Explorer UX must be federated, not flattened into a single chain explorer:

| Explorer | Scope |
| --- | --- |
| Settlement Explorer | PC1 canonical settlement blocks, canonical transactions, reserve wallets, governance/multisig settlement |
| Operational Explorer | PC0 wrapped operational balances, fast transfers, exchange/bot/game/service events |
| Bridge Explorer | lock/mint, burn/unlock, bridge state, cross-ledger links, invariant status |
| Audit Explorer | reserve, liabilities, pending settlement, Merkle liabilities, invariant snapshots |

Every displayed transaction should expose its layer and asset type. Cross-layer
links should use explicit references such as `pc1_tx_hash`, `pc0_op_uuid`, and
`bridge_event_uuid`; one identifier must not pretend to be all three.

## Hash-Chain Auditability

Reserve-critical records should migrate toward append-only hash-chain
auditability:

- settlement ledger
- bridge events
- governance events
- reserve snapshots
- mint/burn authority events
- treasury movement

Each such row should eventually carry `prev_hash` and `row_hash`, or an
equivalent domain-specific hash-chain proof.

## Reserve Transparency Dashboard Contract

Root and manager-facing finance dashboards should present settlement health as a
reserve/liability control plane, not as a single closed-loop blockchain formula.
The core dashboard contract is:

| Metric | Layer | Meaning |
| --- | --- | --- |
| `Canonical Reserve` | PC1 | finalized reserve truth reconstructed from canonical settlement events |
| `Wrapped Outstanding` | PC0 | finalized operational liabilities, including member balances and official operating funds |
| `Pending Settlement` | Bridge | bridge transitions not finalized on both sides |
| `Treasury Reserve` | PC1/PC0 by wallet role | official reserve or operating funds; must not be silently merged with member liabilities |
| `Operational Liquidity` | PC0 | exchange, lending, bot, margin, game, and service runtime liquidity |
| `Invariant Status` | Audit | machine-readable pass/fail for reserve, wrapped, bridge, replay, and boundary invariants |

The dashboard may show these values in one view, but each card must retain its
layer label and reconciliation meaning. `Pending Settlement` must be visually
isolated from finalized `Canonical Reserve` and finalized `Wrapped Outstanding`.

## Immutable Daily Audit Snapshots

The target audit system should close each day with an immutable snapshot row for:

- canonical reserve
- wrapped operational liabilities
- pending settlement
- bridge invariant state
- liability Merkle root
- treasury movement
- mint/burn authority events

Daily snapshots should be append-only and hash-chained. They are not a
replacement for live invariant checks; they are the accounting close record used
to compare historical reserve/liability state, detect retroactive mutation, and
support external review.

## Forbidden Mixing Patterns

Future changes must reject these patterns during review:

- showing `pc0` operational balances as canonical on-chain assets
- sealing `pc0` operational rows into PC1 blocks
- counting pending bridge settlement as finalized reserve or finalized liability
- using one transaction id as if it were simultaneously a PC1 tx, PC0 op, and
  bridge event
- letting PC0 rollback/fork code mutate PC1 canonical reserve or bridge escrow
- presenting bridge as a direct transfer to a `pc0` address
- using Treasury, exchange fund, PROMO fund, or member hot-wallet balances as
  interchangeable categories without explicit layer labels

## Release Gate Rule

No feature is release-ready if it blurs canonical reserve accounting and
operational wrapped accounting.

Before release, an agent must verify:

- UI labels distinguish canonical assets, wrapped operational assets, pending
  settlement, reserve-backed balances, and operational liquidity.
- PC0 rollback/fork paths cannot mutate PC1 canonical reserve.
- PC1 block sealing excludes PC0 operational rows.
- Bridge settlement has idempotent retry/approval behavior.
- Financial invariant output is machine-readable and fails closed on supply
  corruption.
- Documentation uses the permissioned financial settlement network model rather
  than a single-chain blockchain model.
