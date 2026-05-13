# W8 — PGN teacher-audit lane (2026-05-12)

## What W8 ships

A teacher-audit gate between W7's raw PGN input lane and stage 4's
`seed_train --dry-run`. Raw PGN-derived rows are demoted to diagnostic
only; **only audited rows are training-safe**.

| File | Role |
|---|---|
| `scripts/games/chess_imported_replay_teacher_audit.py` | Standalone CLI. Classifies each per-ply row as `accepted` / `review` / `rejected` using legal-move + teacher top-K agreement; only accepted rows are stamped `trusted_source='imported_dataset_teacher_audited'`. |
| `scripts/games/chess_pipeline_dryrun.py` | Adds stage `00b_pgn_teacher_audit/`. Stage 4 consumes audit `accepted_replay.jsonl` by default; raw stage-00 output is now diagnostic only. |
| `scripts/games/chess_pipeline_report.py` | Recognises the new stage via the self-stamped `stage='pgn_teacher_audit'` field; exposes a new cross-stage invariant `unaudited_imported_dataset_used_for_seed_train`. |
| `scripts/games/chess_seed_train.py` | Whitelists the new trusted source `imported_dataset_teacher_audited` (cap 200 in `DEFAULT_EXTERNAL_CAPS`). The legacy `imported_dataset` source stays in the whitelist so existing prepared JSONLs keep loading, but the orchestrator no longer feeds raw PGN-derived rows in by default. |

## Where audit fits in the pipeline

```text
   chess_pgn_to_replay (W7)            game-level JSONL
            │
            ▼
   _expand_game_level_to_per_ply       raw per-ply replay
            │                          (training_eligible=False,
            │                           label_quality='review',
            │                           teacher_audit_status='not_run')
            ▼
   ┌────── stage 00_pgn_input ────────┐
   │   raw_output_jsonls              │
   └─────────────┬────────────────────┘
                 │                                                  W8 NEW
                 ▼
   ┌────── stage 00b_pgn_teacher_audit ─────────────────────────────┐
   │   chess_imported_replay_teacher_audit                          │
   │     • legal_move + valid_fen via python-chess                  │
   │     • teacher top-K via rank_experiment_pv_policy_moves        │
   │                       + rank_experiment_nnue_policy_moves      │
   │     • dedupe by (fen, side, move_uci)                          │
   │   ├── accepted_replay.jsonl   ← only stream that is training-safe
   │   ├── review_replay.jsonl     ← diagnostic, training_eligible=False
   │   ├── rejected_replay.jsonl   ← diagnostic, training_eligible=False
   │   └── audit_detail.jsonl      ← per-row teacher info for review
   └─────────────┬──────────────────────────────────────────────────┘
                 │
                 ▼
              stage 04_seed_train_dryrun
              (consumes accepted_replay.jsonl by default,
               + pvp / sparring streams; never raw stage-00 output
               unless --include-unaudited-pgn-in-dryrun-diagnostic)
```

## Audit profiles

| Profile | Accept rule | Use case |
|---|---|---|
| `strict` (default) | Candidate move is in top-K of **exp4 OR exp5** ranker; ambiguous rows go to `review`. | Safe default. |
| `very_strict` | Candidate must be in top-K of **both** rankers; one-engine agreement → `review`; neither → `rejected`. | Tighter — closer to "both engines vouch for the move". |
| `diagnostic` | Never accepts. Every row goes to `review` with an explicit reason. | Inventory / debugging without producing training-safe data. |

Top-K defaults to 3 and is configurable via `--pgn-audit-top-k`.

When neither `--pgn-audit-exp4-model-path` nor
`--pgn-audit-exp5-model-path` is given, all rows degrade to `review`
with reason `no_teacher_configured` — the safe behaviour for "audit
ran but no teacher was available".

## Trusted source labels

| Stream | `trusted_source` | `label_quality` | `training_eligible` | In whitelist? |
|---|---|---|---|---|
| Raw PGN per-ply (stage 00) | `imported_dataset` | `review` | `False` | Yes (legacy); but stage 4 no longer pulls these by default |
| Audit `accepted_replay.jsonl` | `imported_dataset_teacher_audited` | `clean` | `True` | Yes (cap 200) |
| Audit `review_replay.jsonl` | (unchanged from input) + `audit_status='review'` | (unchanged) | forced `False` | (irrelevant — never auto-fed) |
| Audit `rejected_replay.jsonl` | (unchanged from input) + `audit_status='rejected'` | (unchanged) | forced `False` | (irrelevant — never auto-fed) |
| PvP filtered (W1+W3) | `pvp_filtered` | `review` | `True` | Yes (cap 100) |
| Sparring objective-hit (W6) | `sparring_objective_hit` | `review` | `True` | Yes (cap 50) |

## Cross-stage invariant added in W8

`compute_invariants` now returns
`unaudited_imported_dataset_used_for_seed_train`:

- `False` (safe default): no `seed_train_dry_run` stage loaded a row
  with `trusted_source='imported_dataset'`. The audit-accepted stream
  uses `imported_dataset_teacher_audited`, which does not count.
- `True` (diagnostic): a `seed_train_dry_run` stage's
  `external_replay.load_stats.source_breakdown_raw` shows
  `imported_dataset > 0`. The only way this can happen is the
  explicit `--include-unaudited-pgn-in-dryrun-diagnostic` flag — the
  invariant exists precisely so an operator who uses the unsafe path
  cannot hide that fact from a downstream reviewer.

## Acceptance criteria

| | Status |
|---|---|
| `--pgn-path` local fixture works | ✅ (carried over from W7) |
| `pgn_to_replay` emits raw candidate rows | ✅ (W7) |
| `pgn_teacher_audit` emits accepted/review/rejected streams | ✅ |
| `seed_train_dry_run` consumes only accepted stream by default | ✅ |
| Aggregator `stages_seen` contains `pgn_to_replay` + `pgn_teacher_audit` + `seed_train_dry_run` | ✅ |
| `all_stages_diagnostic_only` = True | ✅ |
| `any_model_mutation` = False | ✅ |
| `any_production_runtime_mutation` = False | ✅ |
| `raw_internet_download` = False (W7 policy) | ✅ |
| `unaudited_imported_dataset_used_for_seed_train` = False | ✅ (safe default) |
| Tests cover skip / accepted / review / rejected / unsafe-override paths | ✅ |

## End-to-end verification

A 12-ply Ruy Lopez fixture (white wins, 2400/2300 Elo) using the
bundled `chess_experiment_4_pv.json` + `chess_experiment_5_nnue.json`
as teachers:

```text
stages_seen           : ['pgn_teacher_audit', 'pgn_to_replay', 'seed_train_dry_run']
all_diagnostic_only   : True
any_model_mutation    : False
any_production_runtime_mutation               : False
unaudited_imported_dataset_used_for_seed_train: False

pgn_to_replay      : games_imported=1 samples_emitted=12
pgn_teacher_audit  : profile=strict input=12 accepted=2 review=10 rejected=0
seed_train_dry_run : rows_kept=2 exp4 2/0 exp5 2/0
                     source_breakdown={'imported_dataset_teacher_audited': 2}
```

The bundled engines only confidently agree with the most basic
opening-book moves; the deeper master moves correctly fall into
`review` (legal moves, but no teacher top-K agreement). That is the
intended behaviour for `strict` profile + bundled production engines:
**fewer accepted rows, more review rows, no false acceptances**.

## W8 non-goals (carried + new)

- ❌ No real training. Stage 4 stays hard-coded `--dry-run`; there is
  no `--execute-staging-train` flag.
- ❌ No production runtime mutation.
- ❌ No network download. `policy.raw_internet_download = False`
  remains across stage 00 and stage 00b.
- ❌ No `human_in_the_loop` accept override yet. The reviewer cannot
  promote a `review` row to `accepted` from this tooling. v2 may add
  a teacher-audit override workflow.

## Recommended invocations

```bash
# Default safe flow: PGN → audit → dry-run → aggregate, audit on:
python3 scripts/games/chess_pipeline_dryrun.py \
  --pgn-path <local.pgn>                                \
  --pgn-audit-exp4-model-path <exp4_pv.json>            \
  --pgn-audit-exp5-model-path <exp5_nnue.json>          \
  --pgn-audit-profile strict                            \
  --output-root ~/chess_results

# Tighter: require both engines to agree
python3 scripts/games/chess_pipeline_dryrun.py \
  --pgn-path <local.pgn>                                \
  --pgn-audit-profile very_strict                       \
  …

# Diagnostic inventory only (never accepts):
python3 scripts/games/chess_pipeline_dryrun.py \
  --pgn-path <local.pgn>                                \
  --pgn-audit-profile diagnostic                        \
  …

# Unsafe override: includes raw PGN in stage 4 anyway. Aggregator
# will flip unaudited_imported_dataset_used_for_seed_train=True so the
# choice is auditable. Never use for a staging warm-up command.
python3 scripts/games/chess_pipeline_dryrun.py \
  --pgn-path <local.pgn>                                  \
  --pgn-skip-audit                                        \
  --include-unaudited-pgn-in-dryrun-diagnostic            \
  …
```

## Test coverage

| File | New / updated | What it locks |
|---|---|---|
| `tests/scripts/games/test_chess_imported_replay_teacher_audit_script.py` | **new** — 19 tests | classify_row for all profiles, stamp_accepted invariants, dedupe, summary policy block, --help. |
| `tests/scripts/games/test_chess_pipeline_dryrun.py` | updated — 2 new tests | run_pgn_teacher_audit_stage skip paths; raw rows now `training_eligible=False` / `label_quality='review'`. |
| `tests/scripts/games/test_chess_pipeline_report.py` | updated — 5 new tests | detect `pgn_teacher_audit`, normalize key metrics, compute the new invariant under safe vs unsafe-override vs no-seed-train. |

Total pipeline-line tests after W8: **160+** green, with no test
removed (W4.2 / W5 / W6 / W7 tests all preserved).
