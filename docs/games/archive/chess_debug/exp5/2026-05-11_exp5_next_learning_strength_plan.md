# 2026-05-11 exp5 next learning / strength plan

This note records the next recommended direction after `exp5_03`.

## Latest report

- result root: `<chess_results>/exp5_03_repeatability_fix3`
- report JSON: `<chess_results>/exp5_03_repeatability_fix3/chess_exp5_repeatability_20260511_082907.153618.json`
- baseline scores: `[0.640625, 0.640625, 0.640625]`
- candidate scores: `[0.6875, 0.6875, 0.6875]`
- score delta: `[0.046875, 0.046875, 0.046875]`
- mean / min / max delta: `0.046875 / 0.046875 / 0.046875`
- std delta: `0.0`
- pass count: `0 / 3`
- heldout rows: `24`
- smoke cases: `4`
- smoke score: `1.0`
- case pass rate: `0.6875`
- legal rate: `1.0`
- suspicious rate: `0.0`
- tactic score: `0.75`
- endgame score: `0.833333`
- regression count / rate: `2 / 0.03125`
- regression budget: pass, max allowed `0.10`
- leakage: `overlap_count=0`, `held_out_in_training=false`
- train agreement delta: `0.0`
- train margin delta: `-35.333333`
- retrain effect visible on train rows: `false`
- tier: `blocked`
- stage candidate: `false`
- shadow candidate: `false`
- production promote: `false`

## Current interpretation

`exp5_03` has a repeatable positive deterministic delta, but it is still below the current gate because `case_pass_rate=0.6875` is under the required `0.70`.

The main issue is not safety. Safety is clean: legal rate is `1.0`, suspicious rate is `0.0`, leakage is `0`, smoke is present and passes. The main issue is learning strength visibility:

- The candidate gains deterministic score, but not enough to pass the case-rate gate.
- Train-row teacher agreement did not improve.
- Teacher margin got worse, so the update is not clearly aligning the candidate with the distilled teacher signal.
- The same two regressions repeat across all three seeds.

## Recommended next direction

### 1. Make retrain updates visible before expanding promotion

Next work should focus on proving that exp5 training changes the NNUE/PVS decision path on the rows it trained on.

Recommended changes:

- Add a train-row decision audit that compares baseline/candidate top move, teacher rank, teacher score, and margin before/after.
- Track `teacher_rank_delta`, not only teacher agreement.
- Add an explicit failure reason when the candidate file hash changes but top-move/rank/margin do not move in the expected direction.
- Verify the PVS chooser is loading the candidate model weights in every path used by the gate.

Promotion should stay blocked until train-row learning is visible or there is a clear explanation for why train-row agreement is not the right metric.

### 2. Fix repeated regression cases first

The repeated regressions are stable across seeds:

- `exp5_02_case_026`, category `baseline_teacher_disagreement`, teacher move `a5a4`, candidate chose `g8h6`
- `exp5_02_case_053`, category `blunder_avoid`, teacher move `e2d1`, candidate chose `f1b1`

Recommended changes:

- Add these as retention/anti-regression anchors.
- Weight `blunder_avoid` regressions higher than ordinary review labels.
- Add a per-category regression budget, not only a global regression rate.
- Require zero regression for smoke and blunder-avoid cases before `shadow_candidate`.

### 3. Improve dataset signal quality

The current dataset is still small and partly noisy.

Recommended changes:

- Increase clean distill rows from `60` to at least `200-500`.
- Prioritize rows where baseline disagrees with teacher and teacher confidence is high.
- Downweight `review` labels and exclude teacher-label-questionable rows from promotion scoring.
- Keep a retention slice where baseline is already correct so the candidate does not forget solved cases.
- Split train/heldout by normalized board signature and category, not random row order only.

### 4. Raise gate resolution without lowering thresholds

The candidate is close to the `0.70` pass-rate threshold, but lowering the threshold would weaken promotion evidence.

Recommended changes:

- Expand deterministic cases from `64` to at least `120-200`.
- Keep category balance: opening, tactic, endgame, blunder_avoid, teacher_hard, baseline_teacher_disagreement, quiet_positional, smoke.
- Report confidence interval or bootstrap stability over the deterministic case set.
- Keep `focused benchmark` as auxiliary only.

### 5. Add tier-specific criteria

Current result should remain blocked. Next useful milestones:

- `stage_candidate`: case pass-rate >= `0.70`, safety pass, leakage pass.
- `shadow_candidate`: repeatability pass plus no repeated blunder/smoke regression.
- `production_promote`: repeatability pass, larger heldout pass, train learning visible or explained, smoke pass, no high-severity regression.

## Next experiment proposal

Run `exp5_04` as `learning visibility + regression repair`:

- Keep the same `exp5_03` report as baseline.
- Add train-row rank/margin delta audit.
- Add the two repeated regressions as mandatory retention rows.
- Expand clean distill rows to at least `200`.
- Run 3 seeds again.
- Do not stage unless every run reaches `case_pass_rate >= 0.70` and no smoke/blunder regression appears.

Expected success condition:

- mean score delta remains positive,
- min score delta remains positive,
- pass count is `3 / 3`,
- train-row teacher rank or margin improves,
- repeated regression count drops to `0`,
- stage candidate becomes true but production remains false until a larger heldout gate passes.
