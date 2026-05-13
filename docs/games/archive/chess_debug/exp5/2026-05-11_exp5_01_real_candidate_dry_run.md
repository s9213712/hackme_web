# 2026-05-11 exp5_01 real candidate dry-run

## Scope

This run validates the exp5 NNUE/PVS path with real artifacts:

- teacher distill quality audit
- exp5 candidate retrain
- focused benchmark runner
- deterministic baseline-vs-candidate strength gate
- promotion blocking when strength evidence is insufficient

Exp5 does not reuse exp3/exp4 semantic promotion evidence. It shares only common safety floors such as legal move rate, suspicious match guard, and benchmark score-rate floor.

## Artifacts

- result root: `/tmp/hackme_exp5_01_real_dry_run`
- input FEN set: `/tmp/hackme_exp5_01_real_dry_run/positions.jsonl`
- distilled dataset: `/tmp/hackme_exp5_01_real_dry_run/distilled_exp5.jsonl`
- retrain report: `/tmp/hackme_exp5_01_real_dry_run/runtime/reports/games/chess_exp5_retrain_pipeline_20260511_065523.504624.json`
- focused benchmark report: `/tmp/hackme_exp5_01_real_dry_run/benchmark_focused_report.json`
- strength gate report: `/tmp/hackme_exp5_01_real_dry_run/runtime/reports/games/chess_exp5_strength_gate_20260511_070402.631666.json`

## Distill Quality

- input_fen_count: `8`
- distilled_rows: `8`
- duplicate_ratio: `0.0`
- legal_teacher_move_rate: `1.0`
- suspicious_teacher_move_rate: `0.0`
- teacher_top1_available_rate: `1.0`
- teacher_score_available_rate: `0.0`
- label_quality_summary: `pass`

Teacher score is not available from the current lightweight teacher API, so it is reported as `0.0` availability rather than inferred.

## Candidate Retrain

- baseline_model_path: `<repo>/services/games/models/chess_experiment_5_nnue.json`
- candidate_model_path: `/tmp/hackme_exp5_01_real_dry_run/candidate/chess_experiment_5_nnue.json`
- baseline_hash: `6fbafae703b94c173e10079aae09763a547719b410895332cbbfdf990ca487ec`
- candidate_hash: `1289747306448379fda468a437794ea4899bc25bed55cd9390f5577eeabd06ba`
- dataset_hash: `8a863575a732f6734e2c1ddd3df8c3ba5865701ffe46f5a34a2f7ad8f8747a6a`
- distill_config_hash: `906f728da681b160c2d3b79a768fe719e7d9c6104524549f34cd604df741e565`
- retrain_seconds: `0.128091`
- accepted_samples: `8`
- positive_updates: `8`

Hash changed is evidence that the model file changed. It is not treated as learning success.

## Benchmark

The full 7-engine round-robin timed out before producing a report in this dry-run, so a focused benchmark used the same runner with `teacher`, `hard`, and `experiment 5:nnue`.

- games_played: `6`
- exp5 games: `4`
- exp5 wins: `2`
- exp5 draws: `2`
- exp5 losses: `0`
- exp5 score_rate: `0.75`
- suspicious_matches: `0`
- human probes included exp5: `true`
- endgame suite included exp5: `true`

This benchmark is a safety signal, not sufficient promotion evidence by itself.

## Strength Gate

| Metric | Baseline | Candidate | Delta |
| --- | ---: | ---: | ---: |
| deterministic score | `0.833333` | `0.833333` | `0.0` |
| legal_rate | `1.0` | `1.0` | `0.0` |
| suspicious_rate | `0.0` | `0.0` | `0.0` |
| tactic_score | `1.0` | `1.0` | `0.0` |
| endgame_score | `0.5` | `0.5` | `0.0` |

Additional candidate metrics:

- teacher_agreement_rate: `0.833333`
- pvs_selected_move_rate: `1.0`
- smoke_score: `0.0`

Safety guard:

- illegal_rate_zero: `true`
- suspicious_rate_not_worse: `true`
- score_rate_not_below_baseline: `true`
- tactic_not_regressed: `true`
- endgame_not_regressed: `true`

## Verdict

- promotion_gate.passed: `false`
- blocked_by_strength_gate: `true`
- blocked_by_gate_skipped: `false`
- candidate staged: `false`
- candidate promoted: `false`
- blocking reason: `candidate_score_not_above_baseline`

The candidate is not worse on the current safety floors, but it also does not beat baseline on deterministic NNUE/PVS strength. Therefore it is not promotion evidence.
