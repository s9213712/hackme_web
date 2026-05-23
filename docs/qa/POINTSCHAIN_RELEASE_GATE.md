# PointsChain Release Gate

Canonical RC1 gate document: `docs/RELEASE/RC1_RELEASE_GATE.md`.

RC1 gate command:

```bash
python3 scripts/qa/points_chain_release_gate.py
```

Live isolated gate:

```bash
python3 scripts/qa/points_chain_release_gate.py \
  --base-url https://127.0.0.1:54343 \
  --runtime-root /tmp/hackme_web_isolated_54343/hackme_web/runtime \
  --root-password root
```

Required pass criteria:

| Area | Gate |
|---|---|
| Legacy bypass | `scripts/security/gate/wallet_direct_call_inventory.py --fail-on-blocker` returns 0 blockers. |
| Wallet/transfer/freeze | `tests/points/test_wallet_identity.py`, `tests/points/test_points_explorer.py`, `tests/points/test_governance_branch.py`. |
| Governance/branch | signer snapshot, replay, auth, concurrency, branch recovery, provisional freeze, dispute review, compensation mode. |
| Trading taint | selected wallet balance, trial credit boundary, real chain spend trace, spot position freeze on tainted source. |
| Feature flags | economy/chain disabled behavior and production-only chain guards. |
| UI/live | optional Playwright governance probe against an isolated runtime. |

Output:

```json
{
  "release_candidate": "PointsChain MVP RC1",
  "scanner_blockers": 0,
  "chain_verify": "pass",
  "replay_verify": "pass",
  "derived_cache_verify": "pass",
  "playwright": "pass",
  "legacy_bypass_paths": 0,
  "production_profile_guard": "pass"
}
```

RC1 cannot ship if any blocker appears in the scanner, chain/replay tests fail,
production profile guard fails, or a live UI/API probe silently fails.
