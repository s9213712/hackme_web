# 2026-05-11 exp5_03 repeatability / stability audit

本輪 focus：`exp5_03 repeatability and robust promotion tier`，重點是確認前輪 `heldout=0` 的問題，並做 3-run 重複驗證。
實驗已保留固定資料來源與 seed 管控，用於評估 exp5 候選是否可從一次性過關提升到可重複 reproducibility。

## Scope

- input train rows：`/tmp/hackme_exp5_02_candidate_audit/positions_train_raw.jsonl`（60 筆）
- distilled dataset：`/tmp/hackme_exp5_02_candidate_audit/distilled_exp5_exp02.jsonl`（60 筆）
- strength cases：`/tmp/hackme_exp5_02_candidate_audit/strength_cases_exp5_02.jsonl`（60 筆）
- heldout source：`/tmp/hackme_exp5_02_candidate_audit/strength_cases_exp5_02.jsonl`
- benchmark report：`/tmp/hackme_exp5_01_real_dry_run/benchmark_focused_report.json`
- heldout rows output：`/home/s92137/chess_results/exp5_03_repeatability_fix3/heldout_rows_exp5_03.jsonl`
- smoke rows output：`/home/s92137/chess_results/exp5_03_repeatability_fix3/smoke_rows_exp5_03.jsonl`
- baseline model：`/home/s92137/hackme_web/services/games/models/chess_experiment_5_nnue.json`
- repeatability run result：
  - `/home/s92137/chess_results/exp5_03_repeatability_fix3/chess_exp5_repeatability_20260511_082907.153618.json`
  - `/home/s92137/chess_results/exp5_03_repeatability_fix3/chess_exp5_repeatability_20260511_082907.153618.md`

## 實驗參數

- run_count：`3`
- seeds：`11, 12, 13`
- heldout_count：`24`
- smoke_count：`4`
- search profile：`strong`
- require-smoke：`true`
- benchmark min thresholds（沿用既有腳本預設）：
  - `min_case_pass_rate=0.70`
  - `min_benchmark_score_rate=0.45`
  - `min_benchmark_games=2`
- min_regression_rate：`0.10`
- max_regression_rate：`0.10`

## 重點修正

本輪發現並修正了 `heldout_rows` 選取邏輯不一致的缺陷：

- 先前版本使用與 `strength_gate` 不同的 signature，會把 `heldout` 與 `train` 判定為重疊（pool=0 或 overlap_count>0）。
- 已改成與 `chess_exp5_strength_gate.py::_train_row_signature` 對齊的簽名規則，並在 fallback 時嘗試翻轉 FEN side-to-move，避免與 train 重疊。
- 修正後 `overlap_count` 由 `24` 下降到 `0`，`held_out_in_training=false`。

## 結果摘要

- baseline score（3 run）：`[0.640625, 0.640625, 0.640625]`
- candidate score（3 run）：`[0.6875, 0.6875, 0.6875]`
- score delta（3 run）：`[0.046875, 0.046875, 0.046875]`
- heldout_count：`24`
- smoke_case_count：`4`

### Repeatability

- pass_count：`0 / 3`
- mean_delta：`0.046875`
- min/max delta：`0.046875 / 0.046875`
- std_delta：`0.0`

### Promotion tier（本次）

- blocked：`true`
- stage_candidate：`false`
- shadow_candidate：`false`
- production_promote：`false`
- stage_reasons：
  - `all_runs_failed`
  - `not_all_runs_passed`

### per-run summary（每 run）

| run | seed | heldout | baseline | candidate | delta | gate_pass | overlap_count |
|---|---:|---:|---:|---:|---:|---:|
| 1 | 11 | 24 | 0.640625 | 0.6875 | 0.046875 | false | 0 |
| 2 | 12 | 24 | 0.640625 | 0.6875 | 0.046875 | false | 0 |
| 3 | 13 | 24 | 0.640625 | 0.6875 | 0.046875 | false | 0 |

### Candidate artifact（可追溯）

- run_1 seed_11 candidate：`/home/s92137/chess_results/exp5_03_repeatability_fix3/run_1_seed_11/candidate/chess_experiment_5_nnue.json`
  - hash：`c2d464d38bda8c038e0dd729ff4da390ba1958260d2d575a8f1666d5924f041f`
- run_2 seed_12 candidate：`/home/s92137/chess_results/exp5_03_repeatability_fix3/run_2_seed_12/candidate/chess_experiment_5_nnue.json`
  - hash：`8a61db88c41fccc54717dc27afe3e3dda997014ae926553a905357bffa28806f`
- run_3 seed_13 candidate：`/home/s92137/chess_results/exp5_03_repeatability_fix3/run_3_seed_13/candidate/chess_experiment_5_nnue.json`
  - hash：`38fe192712c4b1086846cf67c80273b4f387208e04f4f82326b7bd5122dc970e`
- shared baseline：`6fbafae703b94c173e10079aae09763a547719b410895332cbbfdf990ca487ec`
- distill hash：`c0479267994f767341ce48bf7049f76151995680af85e1e87e21be3580e8e4ea`

## 安全/一致性

- case pass rate：`0.6875`（每 run）
- illegal_rate：`0.0`
- suspicious_rate：`0.0`
- smoke_score：`1.0`（有 smoke 類別但被列為輔助）
- train-row learning 指標（run_1）：
  - `baseline_teacher_agreement_on_train=0.066667`
  - `candidate_teacher_agreement_on_train=0.066667`
  - `train_agreement_delta=0.0`
  - `retrain_effect_not_visible=true`
  - `learned_train_not_generalized=false`

## 結論

- exp5_03 重複性結果顯示：候選在同組資料與三個 seed 下**穩定地提升約 +0.046875**（可重複）；
- 但由於 `gate_pass=false`（case pass-rate 未達要求），本次仍 `blocked`，僅可定位為可監測的候選訊號，不是可上 production 的 evidence；
- `heldout=24`、`overlap_count=0` 已修正，先前 0 heldout 的問題已解決；
- `exp5_03` 可作為下一輪調整門檻與 case set 的基線：`stage/shadow` 還未開放，`production promote` 保持 `false`。

## Next

下一步建議已整理在 `2026-05-11_exp5_next_learning_strength_plan.md`：

- 先證明 retrain update 會影響 train-row teacher rank / margin / PVS decision path。
- 把兩個重複 regression case 加入 retention/anti-regression anchor。
- 擴大 clean distill dataset 到至少 `200-500` rows。
- 擴大 deterministic gate case set 到至少 `120-200` cases。
- 不降低 `case_pass_rate >= 0.70` 門檻；候選必須先達到 `3 / 3` repeatability pass 才能進 stage/shadow。
