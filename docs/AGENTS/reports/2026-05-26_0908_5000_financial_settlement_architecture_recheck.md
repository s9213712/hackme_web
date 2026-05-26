# 2026-05-26 09:08 5000 Financial Settlement Architecture Recheck

Scope: recheck the latest PointsChain architecture direction against the repo and
live `https://127.0.0.1:5000` after the project shifted from a single-chain
private blockchain model to a permissioned multi-ledger financial settlement
network.

## Result

No new defect was confirmed in this pass.

The repo and live frontend already use the formal layered model:

- PC1 Canonical Settlement Layer
- PC0 Operational Wrapped Layer
- Bridge Cross-Ledger Settlement Layer
- Audit / reserve invariant layer

The old single-equation wording reported earlier, including
`鏈上/橋外在外流通`, `pc0出站`, `入金入站`, `帳本/事件差`, and `殘差舊算法`,
is not present in the repo frontend bundle or the live `:5000` bundle served at
this time. If it is still visible in a browser, the likely cause is a stale page
or cached static JS.

## Live Invariant Snapshot

`GET /api/root/points/financial-invariants` on live `:5000` returned:

- `ok: true`
- `status: pass`
- `model: pc1_canonical_reserve_pc0_wrapped_operational_v1`
- `flow_gap_points: 0`
- `pc0_out_confirmed_points: 1000`
- `deposit_credited_points: 500`
- `current_cold_chain_or_bridge_external_points: 499`
- `bridge_settlement_integrity: pass`
- `pc0_operational_ledgers_not_sealed_into_pc1_blocks: pass`

The `499` external/bridge value is therefore not a current reconciliation
failure. It is the reconstructed external circulation after `1000` PC0-out,
`500` deposit credit, and bridge/network fees, with `flow_gap_points` at zero.

## Commands

- `pytest tests/points/test_financial_settlement_architecture_docs.py -q`
- `pytest tests/frontend/trading/test_frontend_economy.py -q`
- `python3 -m py_compile services/points_chain/service.py routes/economy.py`
- `node --check public/js/55-economy.js`
- `curl -k -sS -b /tmp/hackme_live_root_qa.cookies https://127.0.0.1:5000/api/root/points/financial-invariants`

## Notes

The current implementation is still a transitional storage model using the
classified `points_ledger`. The formal target remains physical separation into:

- `pc1_settlement_ledger`
- `pc0_operational_ledger`
- `bridge_settlement_events`
- `reserve_audit_snapshots`

That physical split is a migration task, not a safe live hotfix.
