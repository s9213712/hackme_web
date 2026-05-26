# PC0 Dual Rail Wallet Model

Status: active implementation note for the PC0 / PC1 refactor.

Architecture umbrella: [POINTSCHAIN_FINANCIAL_SETTLEMENT_NETWORK.md](POINTSCHAIN_FINANCIAL_SETTLEMENT_NETWORK.md).

## Core Rule

`pc0` is an internal, custodial, platform-managed ledger namespace. It is not a
chain-reachable address.

The production interpretation is:

- `pc1`: canonical settlement chain and the only canonical asset-supply truth.
- `pc0`: wrapped operational layer, backed by bridge/accounting events and used
  for fast in-app settlement.

Any flow that appears to move funds between a cold/external address and a `pc0`
internal custody wallet must be modeled as a bridge with two separate records:

1. A chain-side deposit or withdrawal event involving a platform-controlled
   chain address.
2. An internal ledger event involving `pc0` wallets.

The system must reject or rewrite any API flow that tries to submit a direct
chain transaction with a `pc0` source or destination.

`pc0` ledger rows must not be sealed into `pc1` canonical chain blocks. A PC1
block may include canonical chain rails such as `cold_chain` and future
withdrawal broadcast/confirm rows, but it must exclude `internal_hot_wallet`,
`internal_system_burn`, `deposit_bridge_credit`, `withdrawal_bridge_lock`, and
`withdrawal_bridge_refund`. Those rows remain append-only internal audit records
and are covered by replay, row-hash, snapshot-boundary, and invariant checks
rather than by PC1 block finality. Restorable ledger backups are disabled by
policy because replaying a backup would overwrite append-only financial
history.

## Wallet Roles

- `pc0_user_hot`: exactly one member internal custody wallet per user, shown as
  「站內託管錢包」. Users cannot create this wallet manually; it is created by the
  platform at registration or account repair time.
- `pc0_deposit_clearing`: internal source for credited deposits after chain
  confirmation.
- `pc0_withdrawal_clearing`: internal holding wallet for withdrawal requests.
- `pc0_exchange_fund`: internal exchange operating fund.
- `pc0_promo_fund`: internal promo/reward fund.
- `pc0_treasury`: internal official treasury, counted as platform funds rather
  than member custodial balance.
- `mint000...000`: system-special mint source address. This is not a pc0
  official wallet and cannot be user-spent.
- `000...000`: system-special burn sink address. This is not a pc0 official
  wallet and cannot be spent.
- `deposit_address`: chain-side address controlled by the platform and assigned
  to a user or deposit request.
- `withdrawal_vault`: chain-side platform address used to pay withdrawals.
- `cold_wallet`: user self-custody chain address.

If the address encoder cannot represent role-specific prefixes such as `pc1d`
or `pc1v` yet, those labels remain wallet roles in metadata. The important
invariant is that no chain rail treats `pc0` as a valid external destination.

## Deposit Flow

Preferred design: one active deposit address per user per supported chain.

```text
external/cold wallet
  -> platform deposit_address              chain rail
  -> confirmations / risk checks
pc0_deposit_clearing
  -> pc0_user_hot_wallet                   internal ledger
```

Required records:

- `deposit_address` record:
  - `user_id`
  - `chain`
  - `address`
  - `vault_key`
  - `status`
  - `created_at`
- chain deposit event:
  - `chain_tx_hash`
  - `source_address`
  - `deposit_address`
  - `amount_points`
  - `network_fee_points`
  - `confirmations`
  - `risk_status`
  - `status`
- internal ledger credit:
  - `source_wallet_address=pc0_deposit_clearing`
  - `destination_wallet_address=pc0_user_hot_wallet`
  - `transaction_type=deposit_credit`
  - `settlement_rail=deposit_bridge_credit`
  - `chain_required=false`
  - `approval_required=false`
  - `network_fee_points=0`
  - `reference_chain_tx_hash`

The chain event must never use `pc0_user_hot_wallet` as the actual destination.
The bridge invariant is:

```text
pc0 wrapped operational supply <= pc1 escrow / bridge-backed supply
```

Every `deposit_bridge_credit` must be traceable to a chain-side bridge event and
must not be treated as PC1 native issuance.

## Withdrawal Flow

```text
pc0_user_hot_wallet
  -> pc0_withdrawal_clearing               internal ledger lock
platform withdrawal_vault
  -> user cold wallet                      chain rail
```

Required records:

- internal lock:
  - `transaction_type=withdrawal_lock`
  - `settlement_rail=withdrawal_bridge_lock`
  - source `pc0_user_hot_wallet`
  - destination `pc0_withdrawal_clearing`
- chain withdrawal event:
  - source `withdrawal_vault`
  - destination user cold wallet
  - amount net of withdrawal/network fee
  - pending/proved/confirmed lifecycle
- internal completion or refund:
  - confirmed: mark lock consumed
  - failed/expired: `pc0_withdrawal_clearing -> pc0_user_hot_wallet`
    with `transaction_type=withdrawal_refund`

## Transfer Resolver

```text
pc0 -> pc0
  settlement_rail=internal_hot_wallet
  no network fee
  no chain approval

pc0 -> burn special address
  settlement_rail=internal_system_burn
  no network fee
  no chain approval
  append economy burn event

cold/external -> pc0
  invalid as a direct transfer
  return deposit instructions / deposit_address

pc0 -> cold/external
  withdrawal bridge
  internal lock + chain withdrawal

cold -> cold
  cold_chain rail, if supported
  requires signature, fee, pending/proved/confirmed
```

## Financial Invariant Gate

PointsChain validation must treat the system as a permissioned financial
settlement network, not as a CRUD wallet table or traditional single-chain
blockchain.

The required accounting layers are:

- `PC1 canonical reserve`: settlement/supply truth reconstructed from
  `points_economy_events`.
- `PC0 wrapped operational liabilities`: member hot wallet balances, frozen hot
  wallet balances, root/internal hot wallet balances, official Treasury, PROMO
  fund, and exchange fund.
- `Pending bridge settlement`: bridge rows and transfer requests that are not
  finalized and must not be merged into finalized reserve or finalized
  liabilities.

The root report exposes a machine-readable `financial_invariants` section and
the root-only endpoint `/api/root/points/financial-invariants`.

Mandatory invariants:

1. `wrapped_supply <= canonical_locked_reserve`.
2. `system_burn_sink + pc0_platform_funds + member_internal_circulating +
   root_internal_circulating + off_wallet_circulating +
   system_mint_unissued = max_supply`.
3. Wallet ledger balances must reconcile to economy events.
4. Bridge flow reconstruction must match current cold-chain / bridge-external
   circulation.
5. Direct cold/external -> `pc0` transfer requests must remain zero.
6. Reserve, fund, and liability balances must never be negative.
7. A credited bridge deposit must have accepted risk, enough confirmations, a
   non-`pc0` chain-side destination, and exactly one internal credit ledger.
8. No `pc0` operational ledger row may have a `chain_block_id`; a sealed PC1
   block containing an internal hot-wallet, system-burn, deposit-credit, or
   withdrawal-lock/refund row is a critical ledger-boundary violation.
9. Pending bridge settlement must not be merged into finalized canonical
   reserve or finalized wrapped liabilities.
10. Operational rollback/fork paths must never mutate PC1 canonical reserve
    state.

Financial invariant failure is different from block/hash failure. Block
verification catches tampering in the append-only chain. Financial invariant
verification catches supply corruption, bridge desync, fake minting,
unreconciled rewards, pending settlement leakage, orphan bridge credits, and
PC0/PC1 ledger-boundary pollution.

## Member Management Rule

Users have exactly one pc0 internal custody wallet:

- created by the platform only
- not user-created
- not deletable by the user
- visible in member management for roles with member management permission
- member management shows the hot wallet address and live replay-derived
  balance/frozen/pending values

## Test Gate

The pc0 refactor is not acceptable until these tests pass:

1. Registration creates exactly one `pc0` internal custody wallet.
2. Re-running registration repair/onboarding cannot create a second pc0
   internal custody wallet.
3. User-facing wallet onboarding cannot create a pc0 internal custody wallet
   manually.
4. Cold wallet generation/binding rejects the `pc0` namespace.
5. Member management shows pc0 internal custody wallet address and live balance to
   manager/root only.
6. A direct transfer request with destination `pc0...` from a cold/external rail
   is rejected with deposit instructions.
7. A deposit address is generated for the user and is not `pc0`.
8. Confirmed chain deposit to the platform deposit address credits
   `pc0_user_hot_wallet` through internal ledger.
9. The chain-side deposit event does not contain `pc0` as destination.
10. Withdrawal from `pc0` creates an internal lock before any chain event.
11. Withdrawal failure refunds from `pc0_withdrawal_clearing` to
    `pc0_user_hot_wallet`.
12. Explorer distinguishes `internal_hot_wallet`, `deposit_bridge_credit`,
    `withdrawal_bridge_lock`, and `cold_chain`.
13. Mint and burn are system-special addresses, not official pc0 wallets.
14. Multi-ledger settlement reconciliation uses:
    `system_burn_sink + pc0_platform_funds + holder_circulating + system_mint_unissued = max_supply`.
15. Replay/verify covers both bridge legs and catches orphan chain events or
    orphan internal credits.
16. Explorer and dashboard UI use federated layer labels: Settlement Explorer,
    Operational Explorer, Bridge Explorer, and Audit Explorer.
