# Economy / Governance Security Audit

Date: 2026-05-23
Branch: `04.BLOCKCHAIN_RC1`
Scope: user management, PointsChain private ledger, blockchain governance, points economy, and site-service economy.

## Findings

### P1 - Economy health under-reported releasable supply exhaustion

`economy_health()` warned on `max_supply - minted_total`, but ordinary mint safety is enforced against `max_supply - reserved_locked`. That meant the health card could still show a non-critical mint reserve while the releasable supply was fully exhausted. Enforcement already blocked mint beyond releasable supply, so this was an operational signal/formula bug rather than a direct inflation bypass.

Fixed in `services/points_chain/economy_layer.py`: health now evaluates `releasable_remaining` first and emits `releasable_supply_exhausted`, `releasable_remaining_below_20_percent`, or `releasable_remaining_below_50_percent`.

Regression: `tests/economy/test_economy_layer.py::test_economy_health_warns_on_releasable_supply_exhaustion`.

### P1 - Dispute escalation freeze proposal could fail its own execution guard

The dispute review flow creates a `FREEZE_ADDRESS` proposal, then shortens its voting deadline to match the 24h provisional freeze policy. The row deadline changed but `payload.execution_guard` and `execution_payload_hash` did not, so a legitimate passed freeze proposal could fail with `governance execution guard mismatch: voting_ends_at`.

Fixed in `services/points_chain/service.py`: deadline updates now go through `_update_governance_deadline_guard_locked()`, which updates the row fields, guard snapshot, and execution payload hash together. Direct DB deadline tampering still fails.

Regression: `tests/points/test_governance_branch.py::test_transaction_dispute_review_can_create_recovery_governance_proposal` and `tests/points/test_governance_branch.py::test_governance_deadline_guard_rejects_timelock_row_tamper`.

## Confirmed Guardrails

- Scanner: `wallet direct call inventory` reports `42 findings, 0 blocker(s)`.
- Supply: genesis bootstrap remains idempotent; mint cannot exceed releasable supply; supply expansion remains constitutional policy change, not direct mint/spend.
- Treasury: service-fee batch debit and video platform fee enter official Treasury; wallet transfer fee and acceleration fee remain BURN-only.
- Multisig: Treasury Signer Center exposes canonical signing payload hash and execution payload hash.
- Governance: payload tamper, deadline tamper, active timelock, and fast-forwarded local clock are blocked.
- Exchange: spot principal does not enter exchange fund; only retained fee affects exchange fund; reserve-pool tamper enters trading safe mode.
- Violation fines: three-strike fine, overdue restriction, interest, payment release, appeal approve/reject, duplicate prevention, and closed-fine guards pass.

## Remaining Economic Risks

- Exchange liability proof is still not complete. Current exchange fund balance does not prove the platform's total liability to users. Before P2P, futures, lending expansion, official market making, or external assets, add a liability ledger / proof-of-liability gate.
- RC1.1 anchor is a signed local checkpoint, not an immutable external anchor. Full host compromise can still rewrite DB plus local seed/checkpoint unless an external/offline anchor is added.
- User-facing self-custody signatures still rely on trusted frontend presentation. Canonical payload hashes exist, but independent/offline verification and release artifact integrity checks remain next hardening work.
- Service fee and trading flows still retain legacy/no-wallet compatibility in some paths. This is intentional for basic economy/disabled-chain operation, but production UX should continue forcing wallet selection for walletized payments.

## Real-World Comparison Anchors

- Bitcoin value-overflow incident: supply/integer invariant failure class.
- Maker Emergency Shutdown: emergency halt should be last-resort, audited and operationally constrained.
- Beanstalk governance attack: governance needs voter snapshots, timelocks, spam/capture resistance.
- Mango Markets: price/oracle manipulation becomes P0 once lending/margin/derivatives rely on market prices.
- Curve frontend DNS incidents and Bybit/Safe-style signing UI compromise: multisig and local signing still need payload verification outside the web UI.

## Verification

Commands run:

```bash
python3 -m pytest tests/economy/test_economy_layer.py tests/points/test_governance_branch.py::test_official_treasury_signer_center_reports_service_fee_income tests/points/test_governance_branch.py::test_official_treasury_signer_center_exposes_offline_payload_verifier tests/points/test_governance_branch.py::test_governance_deadline_guard_rejects_timelock_row_tamper tests/points/test_governance_branch.py::test_governance_clock_fast_forward_enters_safe_mode tests/points/test_governance_branch.py::test_supply_expansion_request_requires_exhausted_supply_and_critical_funds tests/points/test_governance_branch.py::test_supply_expansion_is_constitutional_policy_change_not_mint tests/trading/core/test_trading_engine.py::test_spot_trade_principal_does_not_enter_exchange_fund_only_fee_does tests/trading/core/test_trading_engine.py::test_official_exchange_fund_transfer_syncs_trading_reserve_pool tests/trading/core/test_trading_engine.py::test_reserve_pool_tampering_enters_trading_safe_mode tests/governance/test_violation_fines.py -q
```

Result: `33 passed`.

```bash
python3 scripts/qa/points_chain_release_gate.py --skip-live --out artifacts/qa/pointschain_economy_audit_gate_20260523.json
```

Result: `RC1 RELEASE GATE: PASS`; scanner blockers `0`; chain verify `pass`; replay verify `pass`; derived cache verify `pass`; Playwright/live skipped.
