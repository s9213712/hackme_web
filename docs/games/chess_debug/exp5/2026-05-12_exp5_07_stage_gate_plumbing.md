# exp5_07 — deterministic stage gate plumbing + Cell B stage candidate

Date: 2026-05-12
Status:
- **`candidate_can_be_staged = True`** for the exp5_06 Cell B candidate
  (3/3 seeds under `fixed_depth_strong`)
- `candidate_can_be_shadowed = False` (`benchmark_report_missing_for_shadow_or_production`)
- `candidate_can_be_production_promoted = False` (same)

This is the **first** exp5 candidate to clear `stage_candidate=True` on
deterministic strength evidence alone. exp5_07 was scoped to gate
plumbing — no model training or eval changes.

Predecessor: `2026-05-11_exp5_05c_closure_and_06_clean_pool.md`

## Why the plumbing change was needed

exp5_06's Cell B and Cell C had:

```
candidate_score      = 0.8043   (vs baseline 0.7826)
case_pass_rate       = 0.8043   (>= 0.70 threshold)
regression_rate      = 0.000
train_agreement_Δ    = +0.283
castling_floor       = no regress
leakage              = held_out_in_training=False
```

…but the outer promotion-gate logic forced every cell to `pass=False`
with reason `strength_gate_skipped_no_benchmark_report` because
`--benchmark-report-path` was not provided. The result was that we
could not even mark a **stage** candidate, let alone shadow/production.

The fix is conceptual: **benchmark absence is a shadow/production
blocker, not a stage blocker.** A candidate that beats baseline on the
deterministic gate, has zero illegal moves, no regression, and no
leakage, IS already eligible for stage — it just can't be promoted
without external benchmark evidence.

## Code changes

### `scripts/games/chess_exp5_strength_gate.py`

Split `reasons: list[str]` into three explicit lists:

| bucket | contents | gates |
|---|---|---|
| `stage_reasons` | consistency failure, deterministic strength below threshold, candidate not above baseline, illegality, regression, castling-cluster regression, leakage, smoke-candidate-fail | `candidate_can_be_staged` |
| `shadow_reasons` | benchmark missing (when `--allow-stage-without-benchmark`), benchmark fail | `candidate_can_be_shadowed` (also requires stage) |
| `production_reasons` | benchmark missing/fail, smoke-too-hard, smoke-score-zero | `candidate_can_be_production_promoted` (also requires shadow) |

The legacy `reasons` field stays as the union for backwards-compat readers.
New CLI flag `--allow-stage-without-benchmark` (default `True`,
`BooleanOptionalAction`) routes "benchmark missing" to shadow/production
instead of stage. Pass `--no-allow-stage-without-benchmark` to restore
pre-07 behaviour.

`promotion_gate` payload now emits all three tier booleans plus their
reason lists:

```jsonc
"promotion_gate": {
  "candidate_can_be_staged": true,
  "candidate_can_be_shadowed": false,
  "candidate_can_be_production_promoted": false,
  "candidate_can_be_promoted": false,          // legacy alias for production
  "stage_reasons": [],
  "shadow_reasons": ["benchmark_report_missing_for_shadow_or_production"],
  "production_reasons": ["benchmark_report_missing_for_shadow_or_production"],
  "allow_stage_without_benchmark": true,
  // ...legacy: passed / blocked_by_strength_gate / blocked_by_gate_skipped
}
```

### `scripts/games/chess_exp5_repeatability_gate.py`

`_determine_tier` rebuilt to use per-seed `candidate_can_be_staged` /
`candidate_can_be_shadowed` / `candidate_can_be_production_promoted`
(read from the inner strength gate) instead of the old
`gate_pass` (which coupled in benchmark). The tier output now emits:

```jsonc
"tier": {
  "stage_candidate": true,
  "shadow_candidate": false,
  "production_promote": false,
  "stage_pass_count": 3,
  "shadow_pass_count": 0,
  "production_pass_count": 0,
  "stage_reasons": [],
  "shadow_reasons": ["benchmark_report_missing_for_shadow_or_production"],
  "production_reasons": ["benchmark_report_missing_for_shadow_or_production"],
  // ...legacy pass_count / repeatability_delta
}
```

## Selected candidate: Cell B

| reason | value |
|---|---|
| selected_candidate_cell | **B** |
| selection_reason | clean_only_same_delta_lower_label_risk |
| training data | `exp5_06_train_clean_only.jsonl` (60 rows, all label_quality=clean) |
| epochs | 4 |
| auto-hard-negative-topk | 2 |
| review_weight | 0 (n/a — clean_only) |
| search_profile | fixed_depth_strong |
| dataset_hash16 | a8545ecf185daafc |
| candidate sha256 | `f0bfa376432b734994a7e8b7e9af3cfd74211b6ee7f054959b7d2c258fd2378f` |
| baseline sha256 | `6fbafae703b94c173e10079aae09763a547719b410895332cbbfdf990ca487ec` |
| staged_model_path | `/home/s92137/chess_results/exp5_07_stage_candidate/chess_experiment_5_nnue_stage_candidate.json` |
| baseline_model_path | `/home/s92137/hackme_web/services/games/models/chess_experiment_5_nnue.json` |

Why B over C: B and C have identical mean Δ (+0.0217) and identical
clean-tier deltas; B uses only `label_quality=clean` rows, so it does
not rely on review-tier labels at all. Lower label-quality risk per the
user's note that review rows didn't add additional signal in exp5_06.

## Stage gate dry-run (single-shot)

`chess_exp5_strength_gate.py` on the staged candidate vs baseline,
`fixed_depth_strong`, NO benchmark report:

```
candidate_score   = 0.833333   (35/42 on exp5_06 eval bucket)
baseline_score    = 0.809524   (34/42)
score_delta       = +0.023809
case_pass_rate    = 0.8333  (>= 0.70 threshold)
legal_rate        = 1.0,  suspicious_rate = 0.0,  illegal_rate = 0.0
castling_floor    = baseline 0.25 / candidate 0.25  (no regress)
leakage           = overlap 0 / 24, held_out_in_training = False
train_rows_learning:
  baseline_teacher_agreement_on_train  = ...
  candidate_teacher_agreement_on_train = ...
  train_agreement_delta                = +0.283
  margin_delta                         = -78.25

promotion_gate:
  candidate_can_be_staged              = TRUE
  candidate_can_be_shadowed            = False
  candidate_can_be_production_promoted = False
  stage_reasons                        = []
  shadow_reasons                       = ["benchmark_report_missing_for_shadow_or_production"]
  production_reasons                   = ["benchmark_report_missing_for_shadow_or_production"]
```

Artifact: `chess_results/exp5_07_stage_candidate/stage_gate_dry_run.json`.

## Repeatability rerun (3 seeds, new tier semantics)

`chess_exp5_repeatability_gate.py` re-run with the new tier code on the
exp5_06 Cell B training input + strength cases:

```
baseline_scores   = [0.7826, 0.7826, 0.7826]   (std 0.0)
candidate_scores  = [0.8043, 0.8043, 0.8043]   (std 0.0)
score_delta       = [+0.0217, +0.0217, +0.0217]   (std 0.0)

tier:
  stage_candidate                = TRUE
  shadow_candidate               = False
  production_promote             = False
  stage_pass_count               = 3 / 3
  shadow_pass_count              = 0 / 3   (benchmark missing on each seed)
  production_pass_count          = 0 / 3
  stage_reasons                  = []
  shadow_reasons                 = ["benchmark_report_missing_for_shadow_or_production"]
  production_reasons             = ["benchmark_report_missing_for_shadow_or_production"]
  blocked                        = False
```

Per-seed view (all 3 seeds): `candidate_can_be_staged=True`,
`candidate_can_be_shadowed=False`, `candidate_can_be_production_promoted=False`,
`stage_reasons=[]`.

Artifact:
`chess_results/exp5_06_clean_pool/ablation/cell_B_e4_t2_exp507_rerun/`.

## What it means in plain language

- The candidate clears the deterministic strength gate **and the gate
  is now allowed to say so**. exp5_06 Cell B's positive evidence
  (`mean Δ = +0.0217`, `regression 0`, `train_agreement_delta = +0.283`)
  is no longer hidden behind a benchmark-coupling.
- It does NOT mean we can promote to production. The shadow / production
  gates still require benchmark evidence — they're correctly blocked.
- The runtime production model file (`$HACKME_RUNTIME_DIR/games/models/chess_experiment_5_nnue.json`)
  is unchanged. Cell B's candidate sits at
  `chess_results/exp5_07_stage_candidate/chess_experiment_5_nnue_stage_candidate.json`
  as a staging artifact only.

## What `--allow-stage-without-benchmark` does NOT do

It does not:

- bypass the deterministic strength check (still requires candidate >
  baseline AND case_pass_rate >= threshold AND zero illegal / suspicious
  regressions),
- bypass the castling-cluster floor (item 11),
- bypass the leakage guard,
- bypass the smoke-candidate-fail check,
- allow shadow or production promotion without benchmark.

It only re-routes **the missing-benchmark reason** from
`stage_reasons` into `shadow_reasons` / `production_reasons`.

## Files touched (exp5_07)

- `services/games/chess_nnue.py` — no change (item 10 already shipped)
- `scripts/games/chess_exp5_strength_gate.py`
  - `--allow-stage-without-benchmark` BooleanOptionalAction (default True)
  - `stage_reasons` / `shadow_reasons` / `production_reasons` split
  - `promotion_gate.{candidate_can_be_staged, candidate_can_be_shadowed,
    candidate_can_be_production_promoted}` + per-tier reason lists
  - legacy `reasons` union preserved
- `scripts/games/chess_exp5_repeatability_gate.py`
  - per-run `candidate_can_be_shadowed` / `candidate_can_be_production_promoted` / `stage_reasons` / `shadow_reasons` / `production_reasons` captured
  - `_determine_tier` rebuilt against the new per-seed tier booleans
- `docs/games/chess_debug/model_artifact_paths.md` — exp5_07 stage section added
- `docs/games/chess_debug/exp5/2026-05-12_exp5_07_stage_gate_plumbing.md` (this file)

## Artifacts

- `chess_results/exp5_07_stage_candidate/`
  - `chess_experiment_5_nnue_stage_candidate.json` — Cell B candidate, sha256 `f0bfa376432b734994a7e8b7e9af3cfd74211b6ee7f054959b7d2c258fd2378f`
  - `stage_gate_dry_run.json` — single-shot strength gate result
  - `runtime/` — strength gate report directory
- `chess_results/exp5_06_clean_pool/ablation/cell_B_e4_t2_exp507_rerun/` — 3-seed repeatability rerun under new tier semantics

## Tests

```
py_compile: 8 files OK
exp5 targeted tests + train pipeline + self-play tests: 22 passed
git diff --check: clean
```

## Next step: exp5_08

Pool expansion + special-rule curriculum. Already in flight at the time
of this document:

- 344 raw FENs generated (`chess_results/exp5_08_clean_pool/fen_sources/exp5_08_raw_fens.jsonl`)
- distribution: endgame 146 / opening 84 / special_rule 50 / tactic 46 / quiet_positional 16 / blunder_avoid 2
- expected clean yield ≈ 140-160 based on per-category yield ratios from exp5_06
