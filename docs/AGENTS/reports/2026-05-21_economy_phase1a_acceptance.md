# Phase 1A.5 Economy Layer Acceptance

Date: 2026-05-21
Branch: `04.BLOCKCHAIN`
Commit reviewed: `218246b`
Scope: PointsChain economy layer foundation only. No ComfyUI, Trading, Video, Storage, Games, gas, mempool, validator, or consensus integration was added.

## Findings

No open blockers or non-blockers remain for Phase 1A acceptance.

Resolved during this acceptance pass:

- Dashboard completeness: the root「積分私有鏈」summary already showed max supply, minted total, releasable remaining, reserved locked, fund balances, burn, replay, and health, but did not directly expose `mint_remaining`, `active_supply`, `circulating_supply`, snapshot height, or derived-cache verify status. These read-model fields were added to the dashboard before final acceptance.

Deferred by design:

- Phase 1B admin economy APIs are not implemented yet: dry-run, commit, ledger, replay-status, rebuild-derived-balances.
- Phase 1C / 1D product flows remain intentionally unconnected.

## Frontend Acceptance

Playwright evidence:

- Baseline JSON: `/tmp/hackme_web_phase1a5_acceptance2/evidence/baseline.json`
- After-restart JSON: `/tmp/hackme_web_phase1a5_acceptance2/evidence/after_restart.json`
- Baseline screenshot: `/tmp/hackme_web_phase1a5_acceptance2/evidence/baseline_00.png`
- After-restart screenshot: `/tmp/hackme_web_phase1a5_acceptance2/evidence/after_restart_00.png`
- Repo summary JSON: [2026-05-21_economy_phase1a_acceptance.json](2026-05-21_economy_phase1a_acceptance.json)

Accepted dashboard values:

| Field | Value |
|---|---:|
| max_supply | 100,000,000 |
| reserved_locked | 40,000,000 |
| releasable_supply | 60,000,000 |
| minted_total | 20,000,000 |
| mint_remaining | 80,000,000 |
| releasable_remaining | 40,000,000 |
| burned_total | 0 |
| active_supply | 20,000,000 |
| fund_supply | 20,000,000 |
| circulating_supply | 0 |
| official_treasury | 10,000,000 |
| promo_fund | 5,000,000 |
| exchange_fund | 5,000,000 |
| burn | 0 |
| replay_height | 3 |
| snapshot_height | 3 |
| derived_verify | ok |
| health | green |

The page was refreshed 5 times. `minted_total`, `replay_height`, `wallet_root_hash`, snapshot hash, fund balances, and derived verify stayed stable. The same isolated runtime was then restarted without rebuilding the database; after restart, the dashboard/API values matched the baseline.

## API And Cache Review

Confirmed:

- `economy_layer_report()` calls bootstrap, replay, rebuild derived balances, verify derived balances, and create snapshot before returning the read model.
- `points_economy_events` and `points_economy_incidents` have no-update/no-delete triggers.
- `points_economy_derived_balances` is marked `derived_cache=1` and is rebuilt from replay.
- Scanner output stayed at `47 findings, 0 blocker(s)`; no new product direct-ledger migration was introduced.

Important distinction:

- Existing `points_wallets` remains the legacy derived wallet cache for current product flows. Phase 1A did not alter those product flows. The new economy layer does not trust mutable balance fields for fund supply.

## Commands

```bash
python3 -m pytest -q tests/economy/test_economy_layer.py
node --check public/js/55-economy.js
python3 -m pytest -q tests/economy/test_economy_layer.py tests/frontend/trading/test_frontend_economy.py
python3 scripts/security/gate/wallet_direct_call_inventory.py --fail-on-blocker
python3 -m pytest -q tests/economy/test_economy_layer.py tests/frontend/trading/test_frontend_economy.py tests/static/test_wallet_direct_call_inventory.py tests/platform/test_release_policy.py
python3 /tmp/phase1a5_frontend_probe.py --base-url https://127.0.0.1:54243 --out-dir /tmp/hackme_web_phase1a5_acceptance2/evidence --label baseline --reloads 5
python3 /tmp/phase1a5_frontend_probe.py --base-url https://127.0.0.1:54243 --out-dir /tmp/hackme_web_phase1a5_acceptance2/evidence --label after_restart --reloads 0 --compare /tmp/hackme_web_phase1a5_acceptance2/evidence/baseline.json
```

Results:

- `tests/economy/test_economy_layer.py`: 8 passed.
- Economy frontend/static/release slice: 24 passed.
- Wallet direct-call scanner: 47 findings, 0 blockers.
- Playwright baseline/restart probes: passed.

## Decision

Phase 1A.5 acceptance passed. The next allowed work is Phase 1B admin economy API surface, still without product-flow integration.
