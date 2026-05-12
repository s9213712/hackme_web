# 西洋棋模型檔與 retrain 產物路徑對照

本文記錄前台選擇西洋棋難度後，後端實際讀取哪個模型檔，以及 auto-retrain / 手動 retrain 預設把候選模型放在哪裡。

## 路徑規則總覽

所有檔案型 chess 模型預設都走同一套 runtime path helper：

- runtime root：`HACKME_RUNTIME_DIR`
- 未設定 `HACKME_RUNTIME_DIR` 時：`/home/s92137/hackme_web/runtime`
- chess 模型目錄：`$HACKME_RUNTIME_DIR/games/models`
- 若設定 `HTML_LEARNING_CHESS_MODEL_DIR`，則整個 chess 模型目錄改用該路徑。
- bundled seed：`/home/s92137/hackme_web/services/games/models`

核心規則：

- `services/games/models` 只保存發佈時附帶的 warm-up / bundled seed。
- bundled seed 只在 runtime model 不存在時由 warm-start 複製一次。
- 前台實際對局讀取的是 runtime production model。
- auto-retrain 產生的新模型放在 `$HACKME_RUNTIME_DIR/games/models/candidates/...`。
- promotion gate 通過後，只替換 `$HACKME_RUNTIME_DIR/games/models/...` 內的 runtime production model。
- auto-retrain / promotion 不應改寫 `services/games/models`。

相關程式：

- `services/games/chess_model_registry.py`
- `services/server/runtime.py`
- `services/games/chess_promotion.py`

warm-start 由 `ensure_warm_start_chess_environment()` 執行。若 runtime 模型不存在，會先從 bundled seed 複製；若 bundled seed 也不存在，會用 template 建立可啟動的初始模型。若 runtime 模型已存在，warm-start 不會用 bundled seed 覆蓋 runtime，避免蓋掉 autoretrain 產生並 promotion 過的新模型。

## 前台難度到模型檔

前台選項來自：

- `public/index.html`
- `public/js/38-games.js`

後端落點：

- `routes/games.py::create_chess_practice()`
- `routes/games.py::choose_computer_move()`
- `routes/games.py::submit_chess_move()` 後續電腦回合也走同一個 `choose_computer_move()`

| 前台/DB difficulty | 引擎 | 前台預設讀取模型 | 可覆蓋環境變數 | 主要程式 |
|---|---|---|---|---|
| `experiment` | exp1 | `$HACKME_RUNTIME_DIR/games/models/chess_experiment.db` | `HTML_LEARNING_CHESS_ENGINE_DB_PATH` | `services/games/chess_engine.py` |
| `experiment 3:dl` | exp3 | `$HACKME_RUNTIME_DIR/games/models/chess_experiment_3_dl.json` | `HTML_LEARNING_CHESS_ENGINE_DL_MODEL_PATH` | `services/games/chess_dl.py` |
| `experiment 4:pv` | exp4 | `$HACKME_RUNTIME_DIR/games/models/chess_experiment_4_pv.json` | `HTML_LEARNING_CHESS_ENGINE_PV_MODEL_PATH` | `services/games/chess_pv.py` |
| `experiment 5:nnue` | exp5 | `$HACKME_RUNTIME_DIR/games/models/chess_experiment_5_nnue.json` | `HTML_LEARNING_CHESS_ENGINE_NNUE_MODEL_PATH` | `services/games/chess_nnue.py` |

前台選單位置：

- `public/index.html`
- `public/js/38-games.js`

DB schema 允許 difficulty 的位置：

- `routes/games.py`

後端選路：

- `routes/games.py::choose_computer_move()`
- exp1 呼叫 `choose_experiment_move(...)`
- exp3 呼叫 `choose_experiment_dl_move(...)`
- exp4 呼叫 `choose_experiment_pv_move(..., decision_mode="mcts")`
- exp5 呼叫 `choose_experiment_nnue_move(...)`

目前 exp4 前台路徑已走 MCTS：

```python
choose_experiment_pv_move(board, side, search_profile="fast", decision_mode="mcts")
```

exp5 前台目前是 NNUE-like evaluator + alpha-beta search：

```python
choose_experiment_nnue_move(board, side, search_profile="fast")
```

## exp1：SQLite learning store

exp1 不是 JSON 神經網路模型，而是 SQLite learning store。

- production runtime DB：`$HACKME_RUNTIME_DIR/games/models/chess_experiment.db`
- bundled seed DB：`services/games/models/chess_experiment.db`
- path helper：`default_chess_engine_db_path()`
- 前台呼叫：`choose_experiment_move(...)`
- store 類別：`ChessExperimentStore`

exp1 的 dataset refine 指令在 full pipeline 內可產生/更新 candidate DB：

```bash
python3 scripts/games/chess_exp1_dataset_train.py \
  --input-jsonl <dataset_root>/train.jsonl \
  --db-path <candidate_root>/chess_experiment.db
```

full pipeline 內 exp1 candidate path 目前直接指向 `default_chess_engine_db_path()`，且通常透過 `--skip-exp1-refine` 避免混入舊式 DB promotion。

## exp3：DL JSON 模型與 replay

production runtime：

- model：`$HACKME_RUNTIME_DIR/games/models/chess_experiment_3_dl.json`
- replay：`$HACKME_RUNTIME_DIR/games/models/chess_experiment_3_dl_replay.jsonl`

env override：

- model：`HTML_LEARNING_CHESS_ENGINE_DL_MODEL_PATH`
- replay：`HTML_LEARNING_CHESS_ENGINE_DL_REPLAY_PATH`

主要 trainer：

```bash
python3 scripts/games/chess_exp3_dataset_train.py \
  --input-jsonl <dataset_root>/train.jsonl \
  --model-path <candidate_model> \
  --replay-path <candidate_replay>
```

full pipeline candidate：

- model：`$HACKME_RUNTIME_DIR/games/models/candidates/runs/<run_id>/chess_experiment_3_dl.json`
- replay：`$HACKME_RUNTIME_DIR/games/models/candidates/runs/<run_id>/chess_experiment_3_dl_replay.jsonl`

quick gate candidate：

- model：`<output_root>/exp3/checkpoints/10/exp3_quick_candidate_model.json`
- model：`<output_root>/exp3/checkpoints/20/exp3_quick_candidate_model.json`
- replay：`<output_root>/exp3/checkpoints/<trusted>/exp3_quick_candidate_replay.jsonl`

promotion/stage：

- staged candidate：`$HACKME_RUNTIME_DIR/games/models/candidates/experiment_3_dl`
- promoted production：`$HACKME_RUNTIME_DIR/games/models/chess_experiment_3_dl.json`

exp3 目前暫停開發，保留為 governance / deterministic gate 參照。

2026-05-11 closeout runtime production：

- bundled seed：`services/games/models/chess_experiment_3_dl.json`
- bundled seed sha256：`333ed8e72524836d39851b74f4c209c6e08f2652720cacf36a13aa2ac8448dee`
- current repo runtime production：`runtime/games/models/chess_experiment_3_dl.json`
- runtime source：`/home/s92137/chess_results/exp34_mixed_scheduler_repair_hard_case_decision_audit_fixed/exp3/checkpoints/20/exp3_quick_candidate_model.json`
- runtime sha256：`333ed8e72524836d39851b74f4c209c6e08f2652720cacf36a13aa2ac8448dee`
- 語義：bundle 是發佈用 warm-up 初始種子，已採用目前最佳 exp3 closeout 模型。runtime 才是前台對局讀取的 production model。autoretrain/promotion 應替換 runtime，不替換 bundle。

## exp4：Policy/Value JSON 模型

production runtime：

- model：`$HACKME_RUNTIME_DIR/games/models/chess_experiment_4_pv.json`

env override：

- model：`HTML_LEARNING_CHESS_ENGINE_PV_MODEL_PATH`

主要 trainer：

```bash
python3 scripts/games/chess_exp4_dataset_train.py \
  --input-jsonl <dataset_root>/train.jsonl \
  --model-path <candidate_model>
```

full pipeline candidate：

- model：`$HACKME_RUNTIME_DIR/games/models/candidates/runs/<run_id>/chess_experiment_4_pv.json`

quick gate candidate：

- model：`<output_root>/exp4/checkpoints/10/exp4_quick_candidate_model.json`
- model：`<output_root>/exp4/checkpoints/20/exp4_quick_candidate_model.json`
- distilled replay：`<output_root>/exp4/checkpoints/<trusted>/distilled_replay.jsonl`
- before/after evidence：`<output_root>/exp4/checkpoints/<trusted>/retrain_result.json`

promotion/stage：

- staged candidate：`$HACKME_RUNTIME_DIR/games/models/candidates/experiment_4_pv`
- promoted production：`$HACKME_RUNTIME_DIR/games/models/chess_experiment_4_pv.json`

目前 exp4 quick gate 使用 exp3 exp34 同等的診斷框架：

- distilled replay hygiene
- held-out leakage guard
- deterministic strength snapshot
- smoke gate
- full sanity seen/unseen variants
- mistake retention probe
- safe checkpoint selection
- semantic interference / scheduler report

但 exp4 的棋力語義不能直接沿用 exp3 結論。exp4 的決策路徑是 policy/value + MCTS，因此報告必須同時看 raw policy、final decision、MCTS/opening principle fallback 與 promotion gate。

## exp5：NNUE-like JSON 模型與 replay

production runtime：

- model：`$HACKME_RUNTIME_DIR/games/models/chess_experiment_5_nnue.json`
- replay：`$HACKME_RUNTIME_DIR/games/models/chess_experiment_5_nnue_replay.jsonl`

env override：

- model：`HTML_LEARNING_CHESS_ENGINE_NNUE_MODEL_PATH`
- replay：`HTML_LEARNING_CHESS_ENGINE_NNUE_REPLAY_PATH`

主要 trainer：

```bash
python3 scripts/games/chess_exp5_dataset_train.py \
  --input-jsonl <dataset_root>/train.jsonl \
  --model-path <candidate_model> \
  --replay-path <candidate_replay>
```

exp5 另有獨立 pipeline script：

```bash
python3 scripts/games/chess_exp5_retrain_pipeline.py
```

full pipeline helper 已定義 exp5 candidate paths：

- model：`$HACKME_RUNTIME_DIR/games/models/candidates/runs/<run_id>/chess_experiment_5_nnue.json`
- replay：`$HACKME_RUNTIME_DIR/games/models/candidates/runs/<run_id>/chess_experiment_5_nnue_replay.jsonl`

目前通用 auto-retrain pipeline 的 `PIPELINE_RETRAIN_ENGINES` 已包含：

- `experiment 3:dl`
- `experiment 4:pv`
- `experiment 5:nnue`

但 exp5 尚未完成和 exp3/exp4 同等深度的 deterministic learning / mistake-retention 驗收報告；因此它可進入 auto-retrain candidate flow，但不應把 exp3/exp4 的 promotion evidence 直接套用到 exp5。

promotion/stage：

- staged candidate：`$HACKME_RUNTIME_DIR/games/models/candidates/experiment_5_nnue`
- promoted production：`$HACKME_RUNTIME_DIR/games/models/chess_experiment_5_nnue.json`

dashboard selection path：

- 前台對局：`routes/games.py::choose_computer_move()` -> `choose_experiment_nnue_move(...)`
- dashboard command：`services/games/chess_dashboard.py::_pipeline_defaults()`
- strength gate report：`$HACKME_RUNTIME_DIR/reports/games/chess_exp5_strength_gate_<timestamp>.json`

2026-05-11 exp5_01 dry-run paths：

- baseline exp5 model：`/home/s92137/hackme_web/services/games/models/chess_experiment_5_nnue.json`
- baseline sha256：`6fbafae703b94c173e10079aae09763a547719b410895332cbbfdf990ca487ec`
- distilled dataset：`/tmp/hackme_exp5_01_real_dry_run/distilled_exp5.jsonl`
- candidate exp5 model：`/tmp/hackme_exp5_01_real_dry_run/candidate/chess_experiment_5_nnue.json`
- candidate sha256：`1289747306448379fda468a437794ea4899bc25bed55cd9390f5577eeabd06ba`
- candidate replay：`/tmp/hackme_exp5_01_real_dry_run/candidate/chess_experiment_5_nnue_replay.jsonl`
- focused benchmark report：`/tmp/hackme_exp5_01_real_dry_run/benchmark_focused_report.json`
- strength gate report：`/tmp/hackme_exp5_01_real_dry_run/runtime/reports/games/chess_exp5_strength_gate_20260511_070402.631666.json`
- promotion path if gate passes：`$HACKME_RUNTIME_DIR/games/models/chess_experiment_5_nnue.json`
- result：gate failed because candidate score did not exceed baseline; candidate was not staged or promoted.

2026-05-11 exp5_02 decision delta audit paths：

- baseline exp5 model：`/home/s92137/hackme_web/services/games/models/chess_experiment_5_nnue.json`
- baseline sha256：`6fbafae703b94c173e10079aae09763a547719b410895332cbbfdf990ca487ec`
- input train rows：`/tmp/hackme_exp5_02_candidate_audit/positions_train_raw.jsonl`（60 筆）
- held-out rows：`/tmp/hackme_exp5_02_candidate_audit/positions_heldout_raw.jsonl`（4 筆）
- distilled dataset：`/tmp/hackme_exp5_02_candidate_audit/distilled_exp5_exp02.jsonl`
- distilled sha256：`7db42aa08bee26396dfb15b9374cac00db677190311c674330ced12220ae36a3`
- strength cases：`/tmp/hackme_exp5_02_candidate_audit/strength_cases_exp5_02.jsonl`
- candidate exp5 model：`/tmp/hackme_exp5_02_candidate_audit/candidate/chess_experiment_5_nnue.json`
- candidate sha256：`a18338ca8f5e41bca2169fdd981808ea1083edc19cfc5e49dbd7a9eda1ef5de1`
- candidate replay：`/tmp/hackme_exp5_02_candidate_audit/candidate/chess_experiment_5_nnue_replay.jsonl`
- replay sha256：`7db42aa08bee26396dfb15b9374cac00db677190311c674330ced12220ae36a3`
- focused benchmark report：`/tmp/hackme_exp5_01_real_dry_run/benchmark_focused_report.json`
- strength gate report：`/tmp/hackme_exp5_02_candidate_audit/chess_exp5_strength_gate_20260511_074705.014534.json`
- result root：`/tmp/hackme_exp5_02_candidate_audit`
- promotion path if gate passes：`$HACKME_RUNTIME_DIR/games/models/chess_experiment_5_nnue.json`
- result：gate passed（`promotion_gate.passed=true`），但提升幅度/學習可見性仍需下一輪驗證收斂。

2026-05-11 exp5_03 repeatability/stability paths：

- baseline exp5 model：`/home/s92137/hackme_web/services/games/models/chess_experiment_5_nnue.json`
- baseline sha256：`6fbafae703b94c173e10079aae09763a547719b410895332cbbfdf990ca487ec`
- input train rows：`/tmp/hackme_exp5_02_candidate_audit/positions_train_raw.jsonl`（60 筆）
- distilled dataset：`/tmp/hackme_exp5_02_candidate_audit/distilled_exp5_exp02.jsonl`（60 筆）
- distilled hash：`c0479267994f767341ce48bf7049f76151995680af85e1e87e21be3580e8e4ea`
- strength cases：`/tmp/hackme_exp5_02_candidate_audit/strength_cases_exp5_02.jsonl`（60 筆）
- held-out output（run）：`/home/s92137/chess_results/exp5_03_repeatability_fix3/heldout_rows_exp5_03.jsonl`（24 筆）
- smoke output（run）：`/home/s92137/chess_results/exp5_03_repeatability_fix3/smoke_rows_exp5_03.jsonl`（4 筆）
- focused benchmark report：`/tmp/hackme_exp5_01_real_dry_run/benchmark_focused_report.json`
- repeatability report：`/home/s92137/chess_results/exp5_03_repeatability_fix3/chess_exp5_repeatability_20260511_082907.153618.json`
- repeatability md：`/home/s92137/chess_results/exp5_03_repeatability_fix3/chess_exp5_repeatability_20260511_082907.153618.md`
- run_1 candidate（seed 11）：`/home/s92137/chess_results/exp5_03_repeatability_fix3/run_1_seed_11/candidate/chess_experiment_5_nnue.json`
  - sha256：`c2d464d38bda8c038e0dd729ff4da390ba1958260d2d575a8f1666d5924f041f`
- run_2 candidate（seed 12）：`/home/s92137/chess_results/exp5_03_repeatability_fix3/run_2_seed_12/candidate/chess_experiment_5_nnue.json`
  - sha256：`8a61db88c41fccc54717dc27afe3e3dda997014ae926553a905357bffa28806f`
- run_3 candidate（seed 13）：`/home/s92137/chess_results/exp5_03_repeatability_fix3/run_3_seed_13/candidate/chess_experiment_5_nnue.json`
  - sha256：`38fe192712c4b1086846cf67c80273b4f387208e04f4f82326b7bd5122dc970e`
- gate payload（固定）：`/home/s92137/hackme_web/services/games/chess_exp5_strength_gate.py`
- promotion path if gate passes：`$HACKME_RUNTIME_DIR/games/models/chess_experiment_5_nnue.json`（尚未放行）
- result：repeatability 有穩定 +0.046875，gate 未通過（`all_runs_failed`），結果仍 blocked；stage/shadow/production promote 全為 false。

2026-05-12 exp5_07 stage candidate paths（Cell B from exp5_06）：

- baseline exp5 model：`/home/s92137/hackme_web/services/games/models/chess_experiment_5_nnue.json`
- baseline sha256：`6fbafae703b94c173e10079aae09763a547719b410895332cbbfdf990ca487ec`
- stage candidate model：`/home/s92137/chess_results/exp5_07_stage_candidate/chess_experiment_5_nnue_stage_candidate.json`
- stage candidate sha256：`f0bfa376432b734994a7e8b7e9af3cfd74211b6ee7f054959b7d2c258fd2378f`
- source distill：`/home/s92137/chess_results/exp5_06_clean_pool/inputs/exp5_06_train_clean_only.jsonl`（60 rows, all `label_quality=clean`）
- training config：epochs=4, auto-hard-negative-topk=2, multi-good-margin-cp=30.0, label-quality-weight={clean=1.0, review=0.4, questionable=0.0}, search-profile=fixed_depth_strong
- strength gate dry-run：`/home/s92137/chess_results/exp5_07_stage_candidate/stage_gate_dry_run.json`
- repeatability rerun (3 seeds)：`/home/s92137/chess_results/exp5_06_clean_pool/ablation/cell_B_e4_t2_exp507_rerun/stdout.json`
- runtime production model 不變（NOT staged into runtime path）：`$HACKME_RUNTIME_DIR/games/models/chess_experiment_5_nnue.json`
- promotion path if shadow_candidate / production_promote 之後通過：`$HACKME_RUNTIME_DIR/games/models/candidates/experiment_5_nnue/` → `$HACKME_RUNTIME_DIR/games/models/chess_experiment_5_nnue.json`
- promotion_gate (new tier semantics):
  - candidate_can_be_staged: **True**
  - candidate_can_be_shadowed: False (`benchmark_report_missing_for_shadow_or_production`)
  - candidate_can_be_production_promoted: False (same)
  - stage_pass_count: 3/3 seeds
  - shadow_pass_count: 0/3 (benchmark missing)
- result：deterministic strength criteria 全 3 seeds 通過（candidate 0.8043 > baseline 0.7826, case_pass_rate 0.8043, train_agreement_delta +0.283, regression 0/46, castling floor no regress, leakage clean）。**exp5 第一個 stage_candidate=True 的 candidate**。benchmark report 缺 → shadow/production 仍 blocked。candidate 尚未複製到 runtime；本路徑僅供 exp5_07 staging artifact 留檔。

2026-05-12 exp5_08 stage candidate paths（Cell B smokefix from larger 116-row clean pool）：

- baseline exp5 model：`/home/s92137/hackme_web/services/games/models/chess_experiment_5_nnue.json`
- baseline sha256：`6fbafae703b94c173e10079aae09763a547719b410895332cbbfdf990ca487ec`
- stage candidate model：`/home/s92137/chess_results/exp5_08_stage_candidate/chess_experiment_5_nnue_stage_candidate.json`
- stage candidate sha256：`c47ef752aa69d7b8c813b587468228593f44d69c9b947313325e03797e4450dc`
- distill (full)：`/home/s92137/chess_results/exp5_08_clean_pool/distill/exp5_08_distill.jsonl`（341 rows after legal/suspicious filter）
- training input：`/home/s92137/chess_results/exp5_08_clean_pool/inputs/exp5_08_train_clean_only.jsonl`（116 rows, all `label_quality=clean`, dataset_hash16 `9accbee6b540be89`）
- training config：epochs=4, auto-hard-negative-topk=2, multi-good-margin-cp=30.0, label-quality-weight={clean=1.0, review=0.4, questionable=0.0}, search-profile=fixed_depth_strong
- strength cases：`/home/s92137/chess_results/exp5_08_clean_pool/inputs/exp5_08_strength_cases.jsonl`（64 eval-bucket cases, position_id-hashed split, 25 clean / 1 review / 38 quest）
- ablation root：`/home/s92137/chess_results/exp5_08_clean_pool/ablation/cell_B_e4_t2_smokefix/`
- promotion_gate (new tier semantics, after exp5_07 plumbing + exp5_08 smoke-default fix):
  - candidate_can_be_staged: **True** (3/3 seeds)
  - candidate_can_be_shadowed: False (`benchmark_report_missing_for_shadow_or_production`)
  - candidate_can_be_production_promoted: False (same)
  - stage_reasons: []
- repeatability：mean Δ +0.0294, std 0.0, baseline 0.7647 → candidate 0.7941, regression 2/64 (rate 0.029), train_agreement_delta +0.095, castling_floor no regress, leakage 0/24
- runtime production model 不變（NOT staged into runtime path）：`$HACKME_RUNTIME_DIR/games/models/chess_experiment_5_nnue.json`
- semantics：**比 exp5_07 stage candidate (60-row training, +0.0217) 提高到 116-row clean pool 的 +0.0294**。同樣 stage tier，更大 pool 同樣 deterministic + zero stage-blocking-reasons。candidate sits at staging artifact path only; production runtime unchanged.

2026-05-12 exp5_09 focused benchmark + shadow unlock（同一個 exp5_08 Cell B candidate）：

- baseline / candidate model paths：同 exp5_08（candidate sha256 `c47ef752aa69d7b8c813b587468228593f44d69c9b947313325e03797e4450dc`）
- focused benchmark cases：`/home/s92137/chess_results/exp5_08_clean_pool/inputs/exp5_09_benchmark_cases.jsonl`（68 cases, sha16 `ae0de9005d77fd0b`, 含 4 added smoke）
- focused benchmark report：`/home/s92137/chess_results/exp5_09_focused_benchmark/focused_benchmark.json`
- strength gate with benchmark：`/home/s92137/chess_results/exp5_09_focused_benchmark/stage_gate_with_bench.json`
- repeatability with benchmark (3 seeds)：`/home/s92137/chess_results/exp5_09_focused_benchmark/repeat/stdout.json`
- focused benchmark results: overall candidate 55/68 = 0.808, baseline 53/68 = 0.779, Δ +0.029, illegal=0, suspicious=0
- per-cluster delta: **endgame +0.114** (32/35 vs 28/35, 4 imp 0 reg)、tactic / special_rule / smoke 持平 (1.00 / 1.00 / 0.75)、opening −0.059 (1 reg)、quiet_positional −0.500 (1 reg of 2)
- benchmark_gate: pass=True, score_rate 0.808 >> 0.45 floor, 68 games >> 2 floor, 0 suspicious matches
- promotion_gate (with benchmark):
  - candidate_can_be_staged: True (3/3 seeds)
  - candidate_can_be_shadowed: **True (3/3 seeds — first exp5 shadow unlock)**
  - candidate_can_be_production_promoted: True per gate (3/3 seeds), **held per user policy**
- user-policy production check: expanded held-out (NOT met, 24 rows), comprehensive smoke (NOT met, 4 cases), repeatability (met, 3/3 seeds std 0). 2/3 missing → production stays held.
- runtime production model 仍不變：`$HACKME_RUNTIME_DIR/games/models/chess_experiment_5_nnue.json`
- semantics：第一次有 exp5 candidate 同時通過 deterministic strength gate + safety + benchmark；按 user policy 進入 shadow tier，可平行運行驗證但不替換 production。

2026-05-12 exp5_10 production-readiness validation（同一個 exp5_08 Cell B candidate）：

- baseline model：`/home/s92137/hackme_web/services/games/models/chess_experiment_5_nnue.json`（sha256 `6fbafae703b94c173e10079aae09763a547719b410895332cbbfdf990ca487ec`）
- candidate model：`/home/s92137/chess_results/exp5_08_stage_candidate/chess_experiment_5_nnue_stage_candidate.json`（sha256 `c47ef752aa69d7b8c813b587468228593f44d69c9b947313325e03797e4450dc`）
- production readiness root：`/home/s92137/chess_results/exp5_10_production_readiness/`
- cases：`/home/s92137/chess_results/exp5_10_production_readiness/exp5_10_benchmark_cases.jsonl`（135 cases, 70 true held-out）
- expanded benchmark：`/home/s92137/chess_results/exp5_10_production_readiness/focused_benchmark_expanded.json`
- strength gate expanded：`/home/s92137/chess_results/exp5_10_production_readiness/strength_gate_expanded.json`
- repeatability：`/home/s92137/chess_results/exp5_10_production_readiness/repeatability_5_seed.json`
- summary：`/home/s92137/chess_results/exp5_10_production_readiness/summary.json`
- markdown summary：`/home/s92137/chess_results/exp5_10_production_readiness/SUMMARY.md`
- overlap audit：`train_vs_benchmark_overlap_count=0`, `train_vs_heldout_overlap_count=0`, `position_id_overlap_count=0`, `overlap_counts_hardcoded=false`
- expanded benchmark：candidate 105/135 = 0.777778, baseline 103/135 = 0.762963, Δ `+0.014815`
- per-cluster：endgame `+0.075758`, tactic/special_rule/blunder/smoke hold, quiet_positional `0.0` after near-equivalence gate, opening `-0.111111` with questionable regressions
- repeatability：`case_order_repeatability`, no model retraining, 5 seeds all Δ `+0.014815`, std `0.0`; stage/shadow/production-internal 5/5 after rook mate fixture fix and quiet gate fix
- safety：legal_rate `1.0`, illegal_rate `0.0`, suspicious_rate `0.0`; suspicious matches cleared after replacing invalid K+R mate smoke FENs
- runtime check：bundled baseline unchanged; production runtime path `/home/s92137/hackme_web/runtime/games/models/chess_experiment_5_nnue.json` did not exist before/after, so `production_runtime_model_checked=false`, `production_runtime_unchanged=true_by_no_write_only`
- verdict：`shadow_candidate=True`, `production_promote_request_ready=True`, `production_promote=False`; runtime model unchanged, manual promotion still required

2026-05-12 exp5_11b quiet positional regression audit：

- audit root：`/home/s92137/chess_results/exp5_11b_quiet_regression_audit/`
- rows：`/home/s92137/chess_results/exp5_11b_quiet_regression_audit/quiet_regression_rows.jsonl`
- summary：`/home/s92137/chess_results/exp5_11b_quiet_regression_audit/summary.json`
- markdown summary：`/home/s92137/chess_results/exp5_11b_quiet_regression_audit/SUMMARY.md`
- audited blocker：`quiet_positional_clean_regression`
- regression row：`exp5_09_bench_d400404a65f3`, `k_and_p_symmetric`
- teacher / baseline / candidate：`g3f2` / `f3f4` / `h2h4`
- static eval：teacher `44`, baseline `32`, candidate `28`; candidate is `-16cp` vs teacher and `-4cp` vs baseline
- classification：`multi_good_scoring_issue=1`, `true_model_regression=0`, `fixture_issue=0`
- recommendation：replace the production blocker with `quiet_positional_gate_label_audit_required`, then rerun exp5_10 after gate/label fix; do not retrain before that

2026-05-12 exp5_11c quiet positional gate-label fix：

- updated runner：`scripts/games/chess_exp5_production_readiness.py`
- updated strength gate：`scripts/games/chess_exp5_strength_gate.py`
- quiet audit script：`scripts/games/chess_exp5_quiet_regression_audit.py`
- rule：`quiet_positional` cases accept moves within `50cp` of teacher and best static-eval move
- rank audit：candidate `h2h4` is ordinal rank `7` but dense-score rank `3`; gate uses cp window, not ordinal rank
- exp5_10 rerun summary：`/home/s92137/chess_results/exp5_10_production_readiness/summary.json`
- strength gate summary：`/home/s92137/chess_results/exp5_10_production_readiness/strength_gate_expanded.json`
- post-fix quiet audit：`/home/s92137/chess_results/exp5_11b_quiet_regression_audit/summary.json`（`quiet_clean_regression_count=0`）
- final state：`production_promote_request_ready=True`, `production_promote=False`, `runtime_model_mutated=False`

2026-05-12 exp5_12 production promote：

- promotion script：`scripts/games/chess_exp5_promote_candidate.py`
- promotion summary：`/home/s92137/chess_results/exp5_12_production_promote/summary.json`
- promoted candidate artifact：`/home/s92137/chess_results/exp5_08_stage_candidate/chess_experiment_5_nnue_stage_candidate.json`
- candidate sha256：`c47ef752aa69d7b8c813b587468228593f44d69c9b947313325e03797e4450dc`
- runtime production model：`/home/s92137/hackme_web/runtime/games/models/chess_experiment_5_nnue.json`
- staged runtime candidate：`/home/s92137/hackme_web/runtime/games/models/candidates/experiment_5_nnue`
- previous runtime existed：`False`
- rollback marker：`/home/s92137/chess_results/exp5_12_production_promote/rollback/previous_runtime_absent.json`
- post-promote validation summary：`/home/s92137/chess_results/exp5_12_post_promote_check/summary.json`
- post-promote benchmark：`/home/s92137/chess_results/exp5_12_post_promote_check/focused_benchmark_expanded.json`
- post-promote strength gate：`/home/s92137/chess_results/exp5_12_post_promote_check/strength_gate_expanded.json`
- post-promote repeatability：`/home/s92137/chess_results/exp5_12_post_promote_check/repeatability_5_seed.json`
- post-promote result：baseline `103/135 = 0.762963`, runtime candidate `106/135 = 0.785185`, delta `+0.022222`
- endgame result：baseline `54/66 = 0.818182`, runtime candidate `60/66 = 0.909091`, delta `+0.090909`
- safety：`illegal_rate=0.0`, `suspicious_rate=0.0`, `clean_regressed_count=0`
- repeatability：`5/5`, `std_delta=0.0`, `score_delta_per_seed=[0.022222, 0.022222, 0.022222, 0.022222, 0.022222]`
- final state：`production_promote=True`, `runtime_model_mutated=True`

2026-05-12 exp5_13 rule smoke and stalemate fix：

- updated runtime engine code：`services/games/chess_nnue.py`
- updated validation fixtures：`scripts/games/chess_exp5_production_readiness.py`
- validation summary：`/home/s92137/chess_results/exp5_13_rule_smoke_stalemate_fix_check/summary.json`
- benchmark：`/home/s92137/chess_results/exp5_13_rule_smoke_stalemate_fix_check/focused_benchmark_expanded.json`
- strength gate：`/home/s92137/chess_results/exp5_13_rule_smoke_stalemate_fix_check/strength_gate_expanded.json`
- repeatability：`/home/s92137/chess_results/exp5_13_rule_smoke_stalemate_fix_check/repeatability_5_seed.json`
- model artifact：unchanged runtime sha `c47ef752aa69d7b8c813b587468228593f44d69c9b947313325e03797e4450dc`
- post-fix result：baseline `112/137 = 0.817518`, runtime candidate `115/137 = 0.839416`, delta `+0.021898`
- smoke：baseline `18/18 = 1.0`, runtime candidate `18/18 = 1.0`
- safety：`illegal_rate=0.0`, `suspicious_rate=0.0`, `clean_regressed_count=0`
- repeatability：`5/5`, `std_delta=0.0`, `score_delta_per_seed=[0.021898, 0.021898, 0.021898, 0.021898, 0.021898]`
- final state：production model already promoted by exp5_12; exp5_13 improves runtime behavior and validation fixture correctness without replacing the model artifact

2026-05-12 exp5_14 opening label audit：

- audit script：`scripts/games/chess_exp5_opening_label_audit.py`
- source summary：`/home/s92137/chess_results/exp5_13_rule_smoke_stalemate_fix_check/summary.json`
- output root：`/home/s92137/chess_results/exp5_14_opening_label_audit/`
- summary：`/home/s92137/chess_results/exp5_14_opening_label_audit/summary.json`
- opening audit rows：`/home/s92137/chess_results/exp5_14_opening_label_audit/opening_label_audit.jsonl`
- opening fail rows：`/home/s92137/chess_results/exp5_14_opening_label_audit/opening_fail_rows.jsonl`
- clean opening curriculum：`/home/s92137/chess_results/exp5_14_opening_label_audit/clean_opening_curriculum.jsonl`
- model artifact：unchanged runtime sha `c47ef752aa69d7b8c813b587468228593f44d69c9b947313325e03797e4450dc`
- result：opening rows `27`, failed rows `15`, candidate regressed rows `3`
- label quality：`questionable=27`, `clean=0`
- classification：`teacher_label_too_narrow=17`, `multi_good_opening_equivalent=6`, `questionable_label_do_not_gate=4`
- decision：`production_blocker=false`, `clean_true_opening_regressions=0`, `exp5_15_clean_opening_curriculum_rows=0`
- next：build curated opening-book / stronger-teacher labels before exp5_15 candidate training

2026-05-12 exp5_14b clean opening held-out expansion：

- builder script：`scripts/games/chess_exp5_clean_opening_expansion.py`
- output root：`/home/s92137/chess_results/exp5_14b_clean_opening_heldout/`
- summary：`/home/s92137/chess_results/exp5_14b_clean_opening_heldout/summary.json`
- clean opening cases：`/home/s92137/chess_results/exp5_14b_clean_opening_heldout/clean_opening_cases.jsonl`
- clean opening held-out：`/home/s92137/chess_results/exp5_14b_clean_opening_heldout/clean_opening_heldout.jsonl`
- clean opening curriculum：`/home/s92137/chess_results/exp5_14b_clean_opening_heldout/clean_opening_curriculum.jsonl`
- evaluation：`/home/s92137/chess_results/exp5_14b_clean_opening_heldout/clean_opening_evaluation.json`
- raw curated rows：`40`
- kept clean opening rows：`31`
- label quality：`clean=31`
- multi-good rows：`31`
- kept overlap：`train=0`, `benchmark=0`, `position_id=0`
- skipped overlap before keep：`raw_train=1`, `raw_benchmark=8`, `skipped_rows=9`
- dataset hash：`d8888d5116cb9ffd542748c2187b08c4db6535cd24ece4c1722bcf87df55dd70`
- evaluation model：`/home/s92137/chess_results/exp5_08_stage_candidate/chess_experiment_5_nnue_stage_candidate.json`
- evaluation model source：`promoted_stage_candidate_fallback` because local repo runtime override path was absent
- current production-equivalent opening score：`1/31 = 0.032258`
- bundled baseline opening score：`1/31 = 0.032258`
- decision：`exp5_14b pass=true`; clean opening curriculum is ready for exp5_15, but this is not promotion evidence

## auto-retrain 與 promotion 關係

auto-retrain 入口：

- `services/games/chess_pipeline.py::maybe_launch_chess_train_pipeline()`
- 由 replay buffer 狀態與 `HTML_LEARNING_CHESS_RETRAIN_MIN_REPLAYS` 控制是否啟動。
- 預設門檻：`25` usable replays。
- 預設 retrain exp3/exp4/exp5；exp1 通常透過 `--skip-exp1-refine` 排除舊式 DB refine。

啟動命令實際形式：

```bash
python3 scripts/games/chess_train_pipeline.py \
  --preset standard \
  --include-quarantine \
  --min-usable-replays <N> \
  --promote-engines 'experiment 3:dl,experiment 4:pv,experiment 5:nnue' \
  --skip-exp1-refine
```

full pipeline 產物：

- dataset：`$HACKME_RUNTIME_DIR/reports/games/chess_datasets/<run_id>/train.jsonl`
- eval：`$HACKME_RUNTIME_DIR/reports/games/chess_datasets/<run_id>/eval.jsonl`
- candidate root：`$HACKME_RUNTIME_DIR/games/models/candidates/runs/<run_id>/`
- pipeline report：`$HACKME_RUNTIME_DIR/reports/games/chess_train_pipeline_<timestamp>.json`
- autorun status：`$HACKME_RUNTIME_DIR/reports/games/chess_pipeline_autorun_status.json`
- promotion status：`$HACKME_RUNTIME_DIR/reports/games/chess_promotion_status.json`

stage 與 promote 分兩步：

1. `stage_candidate_model(...)` 把 candidate 複製到 `$HACKME_RUNTIME_DIR/games/models/candidates/<engine_safe_name>`。
2. `promote_candidate_model(...)` 在 promotion gate 通過後才複製到 production runtime model path。

所以「retrain 產生 candidate」不等於「前台已使用新模型」。前台只讀 production runtime model，除非使用環境變數 override 或在 validation script 中明確傳入 `model_path`。promotion 成功後的替換目標永遠是 runtime production model，不是 bundled seed。

此規則適用：

- exp1：runtime DB `chess_experiment.db`
- exp3：runtime JSON `chess_experiment_3_dl.json`
- exp4：runtime JSON `chess_experiment_4_pv.json`
- exp5：runtime JSON `chess_experiment_5_nnue.json`

## validation / quick gate artifact 路徑

`scripts/games/chess_live_learning_validation.py` 的 quick retrain gate 不會直接覆蓋 production model。它在 output root 下建立 isolated artifact：

```text
<output_root>/
  summary.json
  SUMMARY.md
  exp4/
    summary.json
    SUMMARY.md
    checkpoints/
      10/
        exp4_quick_candidate_model.json
        train_dataset.jsonl
        distilled_replay.jsonl
        retrain_result.json
      20/
        exp4_quick_candidate_model.json
        train_dataset.jsonl
        distilled_replay.jsonl
        retrain_result.json
```

這些 checkpoint 是驗收證據，不是 production model。要讓前台使用，必須通過 promotion 或手動設定 `HTML_LEARNING_CHESS_ENGINE_PV_MODEL_PATH` 指向指定候選模型。

## 常用檢查命令

查看目前 production model inventory：

```bash
python3 - <<'PY'
from services.games.chess_promotion import production_engine_inventory
for row in production_engine_inventory():
    print(row)
PY
```

查看 auto-retrain 狀態：

```bash
python3 - <<'PY'
from services.games.chess_pipeline import latest_pipeline_autorun_status, latest_pipeline_report
print(latest_pipeline_autorun_status())
print(latest_pipeline_report())
PY
```

查看 promotion 狀態：

```bash
python3 - <<'PY'
from services.games.chess_promotion import promotion_status_summary
print(promotion_status_summary())
PY
```
