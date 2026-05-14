# Exp4_05 暫存工作紀錄：opening margin / MCTS 對齊

日期：2026-05-11

狀態：暫停，等待後續接續。

## 本輪目標

把 exp4 從「有 exp3/exp34 形式驗收鏈」推進到能更清楚回答：

- opening case 是否是多好棋 tie，而不是硬要求單一 top1。
- raw policy、MCTS、static/search、final decision 是否一致。
- low-margin policy override 不可被誤當 learning success。
- retrain 後模型是否真的有更新，且 mistake retention 是否能修正舊錯。

## 已修改項目

- `services/games/chess_pv.py`
  - 新增 MCTS root analysis debug，`explain_experiment_pv_decision(... decision_mode="mcts")` 會輸出 `mcts_prior`、`mcts_visit_count`、`mcts_q_value`、`mcts_final_score`。
  - 修正 MCTS report 中 `chess.Move` 不能 JSON serialize 的問題，report 只輸出 UCI 字串。
  - MCTS explain 的 per-move breakdown 不再額外對每個合法步跑 alpha-beta child search，避免 audit 成本不必要膨脹。

- `services/games/self_play_training.py`
  - self-play / training 選 exp4 時改用 `decision_mode="mcts"`，避免前台走 MCTS、訓練/驗收走 alpha-beta 的語義不一致。

- `scripts/games/chess_live_learning_validation.py`
  - 新增 `opening_target_margin_audit`。
  - 新增 opening 多好棋候選與 soft-label/top-K teacher distribution 欄位。
  - promotion gate 新增 exp4 opening 專屬理由：
    - targeted mistake-retention success 不能單獨證明 broad strength improvement。
    - low-margin policy override 不能算 learning success。
    - final decision alignment 未通過時必須擋 promotion。
  - JSON writer 改成安全序列化 `chess.Move`、`bytes`、`Path`、`set`，避免 debug artifact 因非 JSON 型別導致整輪 gate 崩潰。
  - exp4 quick gate 的 trainer `max_samples` 暫時 cap 到 64。原因是實測 256 samples 會超過 60 秒 timeout，導致候選模型 hash 不變，驗收沒有意義。

- `tests/games/test_games.py`
  - 新增 exp4 MCTS explain root stats 測試。

- `tests/scripts/games/test_chess_live_learning_validation_script.py`
  - 新增 exp4 opening target margin audit 測試。
  - fast-retrain wiring test 補檢查 opening audit / MCTS 欄位。

## 已跑驗證

已通過：

```bash
python3 -m py_compile <repo>/scripts/games/chess_live_learning_validation.py <repo>/services/games/chess_pv.py <repo>/services/games/self_play_training.py
```

已通過：

```bash
PYTHONPATH=<repo> python3 -m pytest <repo>/tests/scripts/games/test_chess_live_learning_validation_script.py -q
```

結果：`51 passed`

已通過：

```bash
PYTHONPATH=<repo> python3 -m pytest <repo>/tests/games -q
```

結果：`73 passed`

已通過 targeted tests：

```bash
PYTHONPATH=<repo> python3 -m pytest <repo>/tests/scripts/games/test_chess_live_learning_validation_script.py::test_exp4_opening_target_margin_audit_reports_mcts_and_multigood <repo>/tests/games/test_games.py::test_experiment_pv_mcts_decision_explain_reports_root_stats -q
```

結果：`2 passed`

## 實跑紀錄

### 1. 失敗 artifact：JSON 序列化問題

輸出目錄：

```text
<chess_results>/exp4_05_opening_margin_mcts_alignment
```

結果：

- quick gate 在 checkpoint@10 寫 `retrain_result.json` 時失敗。
- 原因：MCTS debug payload 包含 `chess.Move` 物件。
- 已修正。

### 2. 失敗 artifact：bytes 序列化問題

輸出目錄：

```text
<chess_results>/exp4_05_opening_margin_mcts_alignment_rerun
```

結果：

- quick gate 在 checkpoint@10 寫 `retrain_result.json` 時失敗。
- 原因：debug payload 包含 `bytes`。
- 已修正為 `_json_safe()`。

### 3. 完整 artifact：256 samples timeout，模型沒有更新

輸出目錄：

```text
<chess_results>/exp4_05_opening_margin_mcts_alignment_fixed
```

結果：

- `overall_verdict=HIGH_RISK`
- `promotion_gate.passed=false`
- `total_retrain_seconds=120.086`
- `total_checkpoint_seconds=653.266`
- `total_wall_seconds=720.658`
- checkpoint@10 retrain 超過 60 秒 timeout。
- checkpoint@20 retrain 超過 60 秒 timeout。
- checkpoint@10 / checkpoint@20 / final model hash 全部等於 baseline。
- 因為模型沒有更新，所以 deterministic score 也沒有變：
  - baseline = `0.8693`
  - checkpoint@10 = `0.8693`
  - checkpoint@20 = `0.8693`
  - final = `0.8693`

重要判讀：

- 這輪不能解讀成「模型學不到」。
- 直接原因是 trainer timeout，候選模型沒有寫入更新。
- gate 擋下是正確的。

opening audit 摘要：

- `case_count=6`
- `targeted_learning_success=true`
- `broad_strength_improvement=false`
- `final_decision_alignment_passed=false`
- `multi_good_tie_count=5`
- `multi_good_credit_applied_count=4`
- `low_margin_override_applied_count=0`
- `low_margin_override_rejected_count=5`
- `failure_type_counts={"multi_good_tie_not_failure": 1, "passed": 4, "raw_policy_fail": 1}`

### 4. 單獨 trainer 量測

使用 checkpoint@10 dataset 單獨跑：

```bash
python3 <repo>/scripts/games/chess_exp4_dataset_train.py --input-jsonl <chess_results>/exp4_05_opening_margin_mcts_alignment_fixed/exp4/checkpoints/10/train_dataset.jsonl --model-path /tmp/exp4_probe_model.json --max-samples 32
```

結果：

- 32 samples 可完成。
- `accepted_samples=32`
- trainer 有更新 policy probe：expected rank `10 -> 2`，但 top1 仍不是 expected。

使用 64 samples：

```bash
python3 <repo>/scripts/games/chess_exp4_dataset_train.py --input-jsonl <chess_results>/exp4_05_opening_margin_mcts_alignment_fixed/exp4/checkpoints/10/train_dataset.jsonl --model-path /tmp/exp4_probe_model_64.json --max-samples 64
```
結果：

- 64 samples 約 30 秒完成。
- `accepted_samples=64`
- expected rank `10 -> 2`
- raw top1 仍不是 expected。

判讀：

- exp4 trainer 不是完全不動。
- 256 samples 在 60 秒 quick gate timeout 下不可用。
- 64 samples 能產生候選模型，適合先用來驗證「能否正確學習」。

### 5. partial artifact：64 sample cap，中途暫停

輸出目錄：

```text
<chess_results>/exp4_05_opening_margin_mcts_alignment_sample64
```

狀態：

- 使用者要求暫停後已停止程序。
- 沒有完整 root `summary.json`。
- checkpoint@10 有完整 `retrain_result.json`。
- checkpoint@20 有 partial artifact，沒有 `retrain_result.json`。

checkpoint@10 重要結果：

- `retrain_duration_seconds=33.42`
- `checkpoint_duration_seconds=298.875`
- `trainer_result.ok=true`
- `trainer_result.accepted_samples=64`
- `hash_changed=true`
- previous hash: `e2f85306...`
- new hash: `0b63473a...`
- mistake retention:
  - before_move = `e7e5`
  - after_move = `d7d5`
  - expected_move = `d7d5`
  - `avoided_old_mistake=true`
  - `matched_expected=true`
- smoke gate:
  - `smoke_gate_passed=true`
  - `final_pass_rate=0.875`
  - `raw_policy_pass_rate=0.25`
- sanity:
  - `result_kind=memorized_exact_fen`
  - seen_variant_pass_rate = `0.4792`
  - unseen_variant_pass_rate = `0.3889`
  - raw_policy_unseen_generalization_rate = `0.2698`
  - final_decision_unseen_generalization_rate = `0.3889`
  - balanced_clean_held_out_pass_rate = `0.4324`

判讀：

- 64-sample cap 後，exp4 checkpoint@10 確實產生模型更新。
- mistake retention 這次不是只有 retained，而是實際從 `e7e5` 修到 `d7d5`。
- smoke gate 可過，但 full sanity 泛化仍不足。
- promotion 仍不能過，因為 seen/unseen/generalization 沒達門檻。
- checkpoint@10 的後處理仍接近 300 秒，最大耗時不是 retrain，而是 exp33/34 diagnostic / full sanity probe。

## 目前結論

exp4_05 已經把問題從「模型完全沒變」推進到：

- trainer 在 64 samples 下可以完成。
- model hash 會改。
- mistake retention 可修正指定舊錯。
- opening 多好棋 audit 可以區分 strict top1 failure 與 multi-good tie。
- MCTS/final decision debug artifact 可以落盤。

但 exp4 仍不是 promotion-ready：

- broad deterministic strength 沒證明提升。
- full sanity seen/unseen 泛化不足。
- `memorized_exact_fen` 仍是 blocker。
- flank / hard semantic 類仍未解。
- quick gate checkpoint 後處理仍太慢。

## 下一步建議

下一輪不要先追 promotion，先做 exp4_06：

1. 保留 64-sample quick retrain cap，確認 cp10/cp20 都能完整跑完且 hash changed。
2. 將 exp33/34 heavy diagnostics 改成 optional 或 smoke fail 才跑，否則 quick gate 每 checkpoint 約 300 秒。
3. 對 cp10 的 `memorized_exact_fen` 做 targeted generalization repair：
   - exact 已能學。
   - seen/unseen 未達標。
   - 應優先補 opening/central variants 的 supervised curriculum，不要增加 self-play。
4. 補 report 欄位：
   - `trainer_timeout=false`
   - `hash_changed=true`
   - `targeted_mistake_fixed=true`
   - `broad_strength_improvement=false`
   - `generalization_blocker=memorized_exact_fen`
5. 完整跑完後再更新 `docs/games/chess_debug/exp4/README.md` 與正式 exp4_05 報告。

## 接續命令

建議下一次從這個命令開始，但要先考慮是否關掉 heavy diagnostics：

```bash
python3 <repo>/scripts/games/chess_live_learning_validation.py --engines exp4 --quick-retrain-gate --seed 20260511 --output-root <chess_results>/exp4_05_opening_margin_mcts_alignment_sample64_retry
```

若只要快速驗證 trainer 能完成，可先跑：

```bash
python3 <repo>/scripts/games/chess_exp4_dataset_train.py --input-jsonl <chess_results>/exp4_05_opening_margin_mcts_alignment_fixed/exp4/checkpoints/10/train_dataset.jsonl --model-path /tmp/exp4_probe_model_64.json --max-samples 64
```
