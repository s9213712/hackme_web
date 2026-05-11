# 2026-05-11 exp5_02 candidate decision audit

本輪 focus：`exp5_02 candidate decision delta audit + distill expansion`。
在實體化 60 筆 distill/train rows 後，完成 teacher distilled rows 學習痕跡與 baseline-vs-candidate 決策對照。

## Scope

- input train rows：`/tmp/hackme_exp5_02_candidate_audit/positions_train_raw.jsonl`（60 筆）
- held-out rows：`/tmp/hackme_exp5_02_candidate_audit/positions_heldout_raw.jsonl`（4 筆）
- distilled rows：`/tmp/hackme_exp5_02_candidate_audit/distilled_exp5_exp02.jsonl`（60 筆）
- strength cases：`/tmp/hackme_exp5_02_candidate_audit/strength_cases_exp5_02.jsonl`（60 筆）
- benchmark report（沿用）：`/tmp/hackme_exp5_01_real_dry_run/benchmark_focused_report.json`
- strength gate report：`/tmp/hackme_exp5_02_candidate_audit/chess_exp5_strength_gate_20260511_074705.014534.json`

## Distill quality（本輪）

- input_fen_count: `60`
- distilled_rows: `60`
- duplicate_ratio: `0.0`
- legal_teacher_move_rate: `1.0`
- suspicious_teacher_move_rate: `0.0`
- label_quality 分佈：`clean=40`、`review=20`
- confidence：`min=0.72`、`max=0.92`、`avg=0.853333...`
- teacher_top1/score 可用欄位：`N/A`（此輪資料主要是 FEN+move label，未提供 top1/score）

## Candidate retrain 結果

- baseline model: `/home/s92137/hackme_web/services/games/models/chess_experiment_5_nnue.json`
- candidate model: `/tmp/hackme_exp5_02_candidate_audit/candidate/chess_experiment_5_nnue.json`
- baseline hash: `6fbafae703b94c173e10079aae09763a547719b410895332cbbfdf990ca487ec`
- candidate hash: `a18338ca8f5e41bca2169fdd981808ea1083edc19cfc5e49dbd7a9eda1ef5de1`
- candidate replay: `/tmp/hackme_exp5_02_candidate_audit/candidate/chess_experiment_5_nnue_replay.jsonl`
- replay hash: `7db42aa08bee26396dfb15b9374cac00db677190311c674330ced12220ae36a3`
- dataset hash: `7db42aa08bee26396dfb15b9374cac00db677190311c674330ced12220ae36a3`（同上游 distilled payload）

## Strength gate outcome

- baseline_score: `0.633333`
- candidate_score: `0.666667`
- score_delta: `0.033334`
- case_count: `60`
- cases_passed: `40`
- case_pass_rate: `0.6667`
- smoke_score: `0.0`
- illegal_rate: `0.0`
- suspicious_rate: `0.0`
- pvs_selected_move_rate: `1.0`
- teacher_agreement_rate: `0.666667`
- tactic_score: `0.75`
- endgame_score: `0.833333`
- safety guard：全部 pass（illegal_rate_zero / suspicious_rate_not_worse / score_rate_not_below_baseline / tactic_not_regressed / endgame_not_regressed）
- promotion gate summary：
  - `blocked_by_gate_skipped: false`
  - `blocked_by_strength_gate: false`
  - `candidate_can_be_staged: true`
  - `candidate_can_be_promoted: true`
  - `promotion_gate.passed: true`

## Decision category（每例對比）摘要

- case categories：
  - opening: `12`
  - tactic: `12`
  - endgame: `6`
  - blunder_avoid: `12`
  - teacher_hard: `6`
  - baseline_teacher_disagreement: `6`
  - quiet_positional: `6`
- decision_category 分佈：
  - `unchanged_correct`: `36`
  - `candidate_improved`: `4`
  - `candidate_regressed`: `2`
  - `unchanged_wrong`: `11`
  - `teacher_label_questionable`: `7`

代表變化（完整 per-case 請看 report）：

| id | category | teacher_move | baseline_move | candidate_move | baseline_score | candidate_score | score_delta |
| --- | --- | --- | --- | --- | ---: | ---: | ---: |
| exp5_02_case_001 | tactic | a7a5 | a7a6 | a7a5 | 0.0 | 1.0 | 1.0 |
| exp5_02_case_002 | endgame | a5a4 | f8a3 | a5a4 | 0.0 | 1.0 | 1.0 |
| exp5_02_case_042 | endgame | a5a4 | d5c4 | a5a4 | 0.0 | 1.0 | 1.0 |
| exp5_02_case_050 | opening | b5a4 | e1b4 | b5a4 | 0.0 | 1.0 | 1.0 |
| exp5_02_case_026 | baseline_teacher_disagreement | a5a4 | a5a4 | g8h6 | 1.0 | 0.0 | -1.0 |
| exp5_02_case_053 | blunder_avoid | e2d1 | e2d1 | f1b1 | 1.0 | 0.0 | -1.0 |

## Train-row learning sanity

- baseline_teacher_agreement_on_train: `0.066667`
- candidate_teacher_agreement_on_train: `0.066667`
- train_agreement_delta: `0.0`
- baseline_teacher_margin: `-1419.55`
- candidate_teacher_margin: `-1488.0`
- margin_delta: `-68.45`
- retrain_effect_not_visible: `true`
- learned_train_not_generalized: `false`

解讀：train 行為上沒有可見 teacher agreement 改善，因此需警覺模型更新可能只對訓練集外樣本帶來局部優化；不過在本批 held-out 無重疊前提下，仍無法直接據此判定 regression。

## Leakage guard

- held_out_rows: `4`
- train_rows: `60`
- overlap_count: `0`
- held_out_in_training: `false`
- overlap examples: `[]`

## Smoke audit

這次強化版 case set 是 60 筆固定分層訓練/驗證盤面，未包含 `category="smoke"`，因此：
- `smoke_audit=[]`
- `smoke_candidates=[]`
- `smoke_score=0.0`
- `smoke_case_too_hard_count=0`

## 結論

- exp5_02 相較 exp5_01 已補齊了「更大 distill」「train-row decision sanity」「case diff audit」三段紀錄，並證實該 run 的 promotion gate 判斷可放行（`promotion_gate.passed=true`）。
- 但目前仍是「safe, not proven 強提升」：提升幅度很小，且學習可見性不足，需下一輪把 `candidate_improved` / `candidate_regressed` 比例與 candidate-smoke 構成再壓縮到更穩定的指標版本再接到正式 production 行為。
- `result_dir`: `/tmp/hackme_exp5_02_candidate_audit`
