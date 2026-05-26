# 2026-05-26 02:38 PC0/PC1 Bridge Ledger Guardrail

## Scope

Reviewed the PC0/PC1 architecture concern that PC0 internal wallet rows could
pollute the PC1 canonical chain ledger. Implemented the first guardrail: PC1
block sealing now excludes PC0/internal operational ledger rows.

## Decision

The project model is now documented as:

- PC1: canonical settlement chain and supply truth.
- PC0: wrapped operational layer / platform custodial internal ledger.
- Bridge: chain-side event plus internal PC0 credit/debit; never a direct
  PC1 transaction to a PC0 address.

PC0 ledger rows remain append-only and hash verified, but they are not PC1 block
members.

## Changes

- `services/points_chain/service.py`
  - Added PC0 operational rail and PC1 canonical rail classification.
  - `seal_block()` now selects only PC1 canonical sealable ledgers.
  - Block verification and ledger proof now use `chain_block_id` membership,
    not `first_ledger_id..last_ledger_id` ranges, so PC1 blocks can skip
    internal rows without accidentally including them.
  - Verification now reports:
    - `pc1_canonical_entries`
    - `pc1_unsealed_entries`
    - `pc0_operational_entries`
    - `pc0_operational_unsealed_entries`
  - Verification fails with `block_contains_noncanonical_ledger` if a PC1 block
    contains PC0/internal operational ledgers.
- `docs/architecture/PC0_DUAL_RAIL_WALLET_MODEL.md`
  - Clarified PC1 canonical settlement chain vs PC0 wrapped operational layer.
  - Added rule that PC0 rows must not be sealed into PC1 canonical blocks.
  - Added bridge backing invariant text.
- `tests/points/test_points_chain.py`
  - Added coverage that PC0 internal transfers and deposit bridge credits are
    not sealed into PC1 blocks.
  - Updated seal/proof tests to use explicit PC1 canonical test rows.

## Verification

Passed:

```text
python3 -m py_compile services/points_chain/service.py services/points_chain/economy_layer.py services/points_chain/schema.py routes/economy.py
python3 -m pytest tests/points/test_points_chain.py tests/points/test_points_explorer.py tests/economy/test_economy_layer.py -q
python3 -m pytest tests/points/test_chain_production_only.py tests/points/test_points_explorer.py -q
python3 -m pytest tests/points/test_points_chain.py::test_schema_integrity_validator_reports_pc0_bridge_and_transfer_corruption tests/points/test_points_chain.py::test_cold_chain_transfer_to_deposit_address_auto_credits_pc0_and_notifies tests/points/test_points_chain.py::test_pc0_to_pc1_wallet_transfer_creates_withdrawal_bridge_lock -q
```

Applied to current `:5000` instance and reloaded gunicorn.

Live verification:

```text
/api/root/points/chain/verify ok=true error_count=0
ledger_entries=11
pc1_canonical_entries=2
pc1_unsealed_entries=2
pc0_operational_entries=9
pc0_operational_unsealed_entries=9
sealed_blocks=0
```

Live DB contamination check:

```text
bad_cold_to_pc0=0
deposit_dest_pc0=0
deposit_hot_not_pc0=0
pc0_ledger_sealed_rows=0
```

## Remaining Design Work

This guardrail prevents PC0 rows from entering future PC1 blocks. The larger
design cleanup still remains:

- Split physical ledgers/databases for PC1 canonical chain and PC0 operational
  ledger.
- Add explicit bridge reserve proof:
  `pc0_wrapped_supply <= pc1_bridge_escrow_locked_supply`.
- Rename UI/report text so PC0 balances are shown as wrapped/internal
  operational balances, not PC1 native chain balances.
