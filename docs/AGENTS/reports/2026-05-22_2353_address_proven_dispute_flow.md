# Address-Proven Dispute Flow QA

## Scope

- Implemented Anonymous Address-Proven Dispute Flow for PointsChain transaction disputes.
- Disputes and replies now prove address ownership by local wallet signature. Private keys remain client-side.
- Root/admin dispute APIs no longer serialize reporter user id or username.

## Confirmed Behavior

- `address_dispute_open` payloads include tx hash, from/to address, amount, statement hash, evidence hash, nonce, chain branch, and purpose.
- `address_dispute_reply` uses a separate purpose and must be signed by the To address.
- Creating a dispute immediately applies a one-hour provisional outbound freeze on the To address.
- Escalating to governance extends the provisional freeze to 24 hours and shortens the freeze vote expiry to 10 minutes before the freeze expiry.
- Rejected/cancelled disputes release provisional freezes.
- Expired freeze governance proposals release linked provisional freezes and write audit events.
- Provisional freeze expiry writes an audit event when evaluated.
- Provisional freeze does not mutate balance or `points_frozen`; it only blocks outbound spend.

## Tests

- `python3 -m py_compile services/points_chain/wallet_identity.py services/points_chain/service.py routes/economy.py tests/points/test_governance_branch.py`
- `node --check public/js/55-economy.js`
- `pytest -q tests/points/test_governance_branch.py`
- `python3 scripts/qa/points_chain_release_gate.py --skip-live`
- Live runtime drill:
  `scripts/testing/pointschain_realistic_recovery_drill.py --runtime-root /tmp/hackme_web_isolated_54343/hackme_web/runtime`
- Playwright:
  `scripts/testing/pointschain_governance_dispute_probe.py --base-url https://127.0.0.1:54343 --username root --password root`
- Live API identity redaction check on `/api/points/transactions/disputes?limit=5`.

## Result

- Governance branch test file: 31 passed.
- Release gate skip-live: ok, scanner blockers 0, production guard pass.
- Live recovery drill: ok. Created `pcdispute:fd4ad181-ba57-49f4-bca6-9231425bc267`, executed recovery/risk/freeze governance, and left the 54343 server running.
- Playwright governance dispute probe: ok.
- Root API dispute list: no `reporter_user_id`, `reporter_username`, `username`, `email`, or `ip` fields returned.
- Dispute create/reply app audit calls use an anonymous actor and blank IP, so normal audit views do not expose reporter network identity for this flow.
