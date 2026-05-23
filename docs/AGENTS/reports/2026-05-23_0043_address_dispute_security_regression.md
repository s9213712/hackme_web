# Address-Proven Dispute Security Regression

Date: 2026-05-23 00:43 Asia/Taipei

Scope:
- Anonymous Address-Proven Dispute Flow hardening.
- Replay, purpose mixing, runtime/branch binding, provisional freeze precision, and root/API de-identification regression checks.

Changes:
- Address dispute signatures now bind `runtime_mode` in addition to `tx_hash`, `from`, `to`, `amount`, `statement_hash`, `evidence_hash`, `nonce`, `chain_branch`, and `purpose`.
- Dispute rows store signed payload hashes and signature hashes for open/reply paths.
- Reusing the same signed payload or signature is rejected even after the original case is closed.
- Reply is single-submit for RC1; a second reply must create a new reviewed case instead of overwriting signed evidence.
- Manager/root dispute serialization no longer exposes reviewer numeric user ids; it returns `reviewed_by: governance_operator`.
- Frontend dispute signing payload mirrors backend runtime-mode binding and keeps private keys client-local.

Targeted tests:
- `test_address_dispute_rejects_signed_payload_and_signature_replay`
- `test_address_dispute_signature_purpose_and_mode_branch_are_bound`
- `test_address_dispute_provisional_freeze_is_outbound_only_for_to_address`
- `test_address_dispute_serializer_redacts_account_identity_fields`

Verification:
- `python3 -m py_compile services/points_chain/service.py services/points_chain/wallet_identity.py tests/points/test_governance_branch.py tests/regressions/test_security_issue_regressions.py`
- `node --check public/js/55-economy.js`
- `pytest -q tests/points/test_wallet_identity.py tests/points/test_governance_branch.py tests/regressions/test_security_issue_regressions.py`

Result:
- PASS. Targeted dispute security regressions and related wallet/governance tests passed.

