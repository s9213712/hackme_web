# exp4 convergence to learning-only（2026-05-12）

## 結論

- exp4_guarded_overlay_status: `parked_not_promotion_ready`
- promotion: `false`
- runtime_mutated: `false`
- retrain_attempted: `false`
- production_default: `disabled`

exp4 guarded overlay promotion is parked. The runtime guarded overlay remains diagnostic/opt-in only and is not a production default.

## Reason

exp4_23 broad sanity blocked guarded overlay promotion. exp4_24 then found:

- broad_sanity_unsafe_override_count: `26`
- unsafe_guard_reason: `runtime_static_and_rule_guard_passed`
- main pattern: ordinary e/d central pawn or flank pawn moves overriding a baseline move that was already correct

exp4_25 tightened the runtime guard and replayed the 26 unsafe rows:

- unsafe_after_guard: `0`
- blocked_after_guard_tightening: `26`
- guard_reason_after: `ordinary_runtime_margin_insufficient`

That made the overlay safe on the known unsafe rows, but the deterministic positive overlay gain disappeared. Therefore the guarded overlay is not promotion-ready.

## Safety Default

Code status is exposed by `services.games.chess_pv_guarded_overlay.exp4_guarded_overlay_parking_status()`.

Default behavior:

- frontend/gameplay exp4 still uses the baseline runtime PV model
- `HTML_LEARNING_CHESS_EXP4_GUARDED_OVERLAY` defaults off
- auto pipeline default promotion targets exclude exp4
- exp4 promotion requires explicit operator opt-in instead of being a default autorun result

## Learning Path Still Alive

exp4 can still participate in:

- web gameplay as `experiment 4:pv`
- shared replay collection with exp5
- replay quarantine / trusted tiering
- W7/W8 dry-run and audited replay ingestion
- `chess_seed_train.py --dry-run`
- explicit staging/candidate commands for operator review

Do not require guarded overlay promotion for exp4 learning. Exp4 improvement should come from real games and audited replay, not manual synthetic benchmark chasing.

## Reopening Condition

Reopen exp4 guarded overlay only if real-game/live-learning evidence shows a repeated production weakness and W8-audited data supports a no-label runtime guard change.
