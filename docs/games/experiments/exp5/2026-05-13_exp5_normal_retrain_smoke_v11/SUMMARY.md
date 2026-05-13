# Exp5 Normal-Game Retrain Smoke

- generated_at: `2026-05-13T13:16:56+00:00`
- baseline_model_path: `services/games/models/chess_experiment_5_nnue.json`
- baseline_model_sha256: `88464dba7e3497e7be7474e0aae4272801fb2e98838985740e530f592f2ff992`
- default_model_mutated: `False`

## Phase Summary
- normal games: `10` games, AI `6`W/`4`D/`0`L, win_rate `60.00%`, score_rate `80.00%`, complete_game_rate `100.00%`
- extracted positions: `180` selected from `433`
- teacher distill: accepted `45` / input `180`, quarantine `133`
- split: train `31`, eval `14`, strength `14`
- repeatability: mean_delta `0.0`, stage_candidate `False`, shadow_candidate `False`, production_promote `False`
- advanced score: candidate `78.4954`, baseline_ref `84.1482`, delta `-5.6528`
- promotion decision: `report_only_rejected`, allowed `False`, reasons `['advanced_score_not_above_required_margin', 'complete_gauntlet_loss', 'gauntlet_win_count_below_v10', 'threefold_rate_too_high', 'repeatability_stage_gate_failed']`

## Score Check

Retrain did **not** improve the active v10 reference.

| Metric | v10 reference | v11 normal-game retrain candidate |
|---|---:|---:|
| advanced score | `84.1482/100` | `78.4954/100` |
| complete gauntlet | `18W/12D/0L` | `12W/17D/1L` |
| gauntlet score rate | `0.8000` | `0.6833` |
| threefold rate | `40.00%` | `56.67%` |
| tactical suite | `300/300` | `300/300` |
| legacy score probe | `40.00/40` | `40.00/40` |
| PGN exact match | `40/240 = 16.67%` | `41/240 = 17.08%` |

The candidate remains tactically stable on fixed probes, but complete-game
strength regressed. It must not replace the default model.

## Failure Analysis

- Data quality was the main bottleneck: `180` selected normal-game positions
  produced only `45` accepted teacher rows. `133` rows were dropped as
  questionable by baseline-policy gap, and `2` were rejected as suspicious
  teacher moves.
- The teacher disagreement signal is high: clean ratio was only `15.17%`, and
  `teacher_top3` did not contain the teacher's searched move in `127/180`
  audited rows. This confirms that the current top-K metadata is only a
  one-ply static ranking and is too weak to blindly trust as a "deep teacher
  confidence" signal.
- The candidate did learn locally: train-row teacher agreement improved from
  `45.16%` to `54.84%`, and average teacher margin improved by `12.61` raw
  policy-score units.
- The local learning did not generalize: repeatability gate stayed at
  `baseline_score=0.388889`, `candidate_score=0.388889`, `score_delta=0.0`,
  `stage_candidate=false`.
- The advanced score regression came from complete-game behavior, not tactical
  probes: gauntlet had one complete loss and more repetition draws. This is
  consistent with small normal-game retrain nudging policy weights without
  solving endgame conversion or anti-repetition planning.

Conclusion: "more experience" is not automatically stronger when the accepted
sample count is small, the teacher labels are noisy or disputed, and the model
update does not target the failure mode measured by the gate.

## Architecture Recommendation

The result supports moving from direct model replacement to a main-model plus
experience-model architecture.

- Keep the current exp5 model as the stable main model and production baseline.
- Each retrain produces a small versioned experience model / adapter with its
  own source rows, teacher audit, cluster tags, and gate report.
- At inference time, the main model generates candidates first. An adapter may
  add bias only when the current position matches its cluster and the proposed
  move passes rule safety, anti-repetition, and no-blunder checks.
- Add an arbiter layer that can reject adapter advice when the main model's
  search score, tactical safety, or repetition/endgame policy disagrees.
- Keep adapters individually analyzable: opening, endgame conversion,
  anti-repetition, human-probe, and tactical-trap adapters should remain
  separable until they repeatedly pass held-out gates.
- Promote by composition first: enable an adapter in shadow/stage mode before
  merging it into the main model. Direct main-model overwrite should require
  beating the v10 `84.1482` reference and having no complete-game losses.

This preserves experience without allowing a weak retrain batch to damage the
main engine. It is close to a small-scale MoE/LoRA-style direction, adapted to
the current JSON NNUE-like model.

## Artifacts
- normal_games_jsonl: `docs/games/2026-05-13_exp5_normal_retrain_smoke_v11/normal_games.jsonl`
- teacher_distill_jsonl: `docs/games/2026-05-13_exp5_normal_retrain_smoke_v11/normal_teacher_distill_all.jsonl`
- train_rows_jsonl: `docs/games/2026-05-13_exp5_normal_retrain_smoke_v11/normal_train_rows.jsonl`
- strength_cases_jsonl: `docs/games/2026-05-13_exp5_normal_retrain_smoke_v11/normal_strength_cases.jsonl`
- repeatability_report_dir: `docs/games/2026-05-13_exp5_normal_retrain_smoke_v11/repeatability_gate`
- candidate_model_path: `docs/games/2026-05-13_exp5_normal_retrain_smoke_v11/repeatability_gate/run_1_seed_31/candidate/chess_experiment_5_nnue.json`
- advanced_score_json: `docs/games/2026-05-13_exp5_normal_retrain_smoke_v11/candidate_advanced_score.json`

## Notes
- The script pins `HTML_LEARNING_CHESS_ENGINE_NNUE_MODEL_PATH` for both baseline games and candidate validation.
- Teacher `teacher_top3` / `teacher_top5` metadata is one-ply static ranking; questionable labels are quarantined, not trained.
- This report is candidate-only. If a candidate is later promoted, snapshot the previous default model first with the user-approved versioned snapshot name.
