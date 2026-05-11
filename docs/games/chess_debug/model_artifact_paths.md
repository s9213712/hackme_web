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
