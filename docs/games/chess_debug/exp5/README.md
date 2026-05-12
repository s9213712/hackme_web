# Exp5：NNUE + AlphaBeta/PVS

本資料夾保存 exp5 後續演進文件。

## 定位

exp5 是後續主要棋力路線之一，方向是：

- NNUE-like / NNUE evaluator
- efficiently updatable accumulator
- alpha-beta / PVS search
- stronger move ordering
- deterministic strength gate

目前 exp5 已新增 `services/games/chess_nnue.py`。現階段是 repo 內可演進的 NNUE-like skeleton，不是 Stockfish 相容 NNUE。

## 術語規範（exp5_06 修訂）

在 exp5 所有文件、程式註解、報告裡：

- **「teacher distill」是 label *proposal*，不是 *ground truth***。
  exp5 目前使用的 teacher 是 `choose_teacher_move` (depth-3 static alpha-beta with `_teacher_static_eval`)。
  它的輸出是「在這個 1-3-ply 視野下 teacher 認為最好的步」——不等同 deep Stockfish 強監督。
- 寫 promotion 報告時，**禁止**使用：
  - "teacher said X so X is correct"
  - "ground truth move"
  - "true label"
  - "strong teacher signal"
- 應該使用：
  - "teacher proposal" / "teacher's depth-3 choice"
  - "label proposal subject to label_quality audit"
  - "static-teacher signal" / "1-ply static teacher ranking"
- label 的「真假」由 `label_quality` audit (`baseline_policy_gap_cp` 等) 判斷，不是由 teacher 本身。
- exp5_05b 的 `static_teacher_top_k=true` / `teacher_top_k_method=one_ply_static_eval` 兩個欄位就是這條規範的機讀版本。

## 目前狀態

- 可選引擎、warm-start artifact、模型 schema、sample format、candidate inventory scaffold 已建立。
- `chess_exp5_dataset_train.py` 是 exp5 專用最小 trainer，能從 FEN/move JSONL 更新 exp5 NNUE-like JSON model/replay。
- `chess_exp5_retrain_pipeline.py` 是 exp5 專用最小 retrain pipeline，只產 candidate 與 report，不接 exp3/exp4 semantic gate。
- auto-retrain / promotion 外層已支援 exp5，但 promotion 必須先通過 exp5 專用 strength gate；quick retrain gate 仍不沿用 exp3/exp4 semantic evidence。
- 修改歷程與相容性判斷：`2026-05-11_scaffold_and_compatibility.md`
- real candidate dry-run：`2026-05-11_exp5_01_real_candidate_dry_run.md`
- exp5_02 decision delta audit：`2026-05-11_exp5_02_candidate_decision_audit.md`
- exp5_03 repeatability stability：`2026-05-11_exp5_03_repeatability_stability.md`
- next learning / strength plan：`2026-05-11_exp5_next_learning_strength_plan.md`
- exp5_04 epochs/HN ablation：`2026-05-11_exp5_04_learning_capacity_ablation.md`
- exp5_05a/b 確定性 gate + label audit：`2026-05-11_exp5_05a_b_deterministic_gate_and_label_audit.md`
- exp5_05c closure + 06 clean pool：`2026-05-11_exp5_05c_closure_and_06_clean_pool.md`
- exp3 replay 例1 / 例2 lessons：`2026-05-11_exp3_replay_format_lessons_for_exp5.md` / `2026-05-11_exp3_replay_example2_5game_lessons_for_exp5.md`
- exp5_07 promotion tier plumbing：`2026-05-12_exp5_07_stage_gate_plumbing.md`
- exp5_08 larger clean pool + smoke-default fix：`2026-05-12_exp5_08_clean_pool_expansion.md`
- exp5_09 focused benchmark + shadow unlock：`2026-05-12_exp5_09_focused_benchmark.md`
- exp5_10 production-readiness validation：`2026-05-12_exp5_10_production_readiness.md`
- exp5_11a suspicious-rate root-cause audit：`2026-05-12_exp5_11a_suspicious_rate_audit.md`
- exp5_11b quiet positional regression audit：`2026-05-12_exp5_11b_quiet_regression_audit.md`
- exp5_11c quiet positional gate-label fix：`2026-05-12_exp5_11c_quiet_gate_fix.md`
- exp5_12 production promote：`2026-05-12_exp5_12_production_promote.md`
- exp5_13 rule smoke + stalemate fix：`2026-05-12_exp5_13_rule_smoke_and_stalemate_fix.md`
- exp5_14 opening label audit：`2026-05-12_exp5_14_opening_label_audit.md`
- exp5_14b clean opening held-out expansion：`2026-05-12_exp5_14b_clean_opening_heldout_expansion.md`

## 歷程總表

| 輪次 | 日期 | 核心發現 / 動作 | tier verdict |
|---|---|---|---|
| exp5_01 | 2026-05-11 | real-candidate dry-run; gate failed (candidate ≤ baseline) | blocked |
| exp5_02 | 2026-05-11 | 60-row distill candidate；decision audit；gate "passed" but learning unverifiable | blocked |
| exp5_03 | 2026-05-11 | repeatability 0/3，repeatability fix series；exposes timed-gate noise | blocked |
| exp5_04 | 2026-05-11 | epochs/topK ablation；revealed teacher labels are mostly questionable | blocked |
| exp5_05a | 2026-05-11 | **fixed_depth_strong** deterministic gate；timed strong unreliable | n/a (tool) |
| exp5_05b | 2026-05-11 | label_quality filter；exp5_02 distill 48/60 questionable | n/a (audit) |
| exp5_05c | 2026-05-11 | 12-row clean+review ablation — insufficient | blocked |
| exp5_06 | 2026-05-11 | 73-clean pool；first positive deterministic delta (+0.0217 Cell B) | (plumbing blocked) |
| exp5_07 | 2026-05-12 | promotion-tier plumbing split (stage / shadow / production) | **stage_candidate=True (first)** |
| exp5_08 | 2026-05-12 | 116-clean pool + smoke-default bugfix；mean Δ +0.0294 | **stage_candidate=True 3/3 seeds** |
| exp5_09 | 2026-05-12 | focused benchmark (68 cases，cluster-split)；endgame +0.114 | **shadow_candidate=True 3/3 (first); production held per user policy** |
| exp5_10 | 2026-05-12 | production-readiness validation；135 cases / 70 true held-out；overlap audit fixed and clean；invalid rook-mate smoke fixtures retested；overall Δ +0.0074，suspicious_rate 0，但 quiet clean regression remains pre-fix | **shadow_candidate=True; production_promote=False** |
| exp5_11a | 2026-05-12 | suspicious-rate audit；pre-fix 2/2 suspicious rows were invalid rook-mate fixtures；after fixture fix + exp5_10 rerun，suspicious_row_count=0 | **shadow_candidate=True; production still held by quiet regression** |
| exp5_11b | 2026-05-12 | quiet regression audit；唯一 clean regression 是 `k_and_p_symmetric` multi-good scoring issue，candidate 只比 teacher 低 16cp、比 baseline 低 4cp | **shadow_candidate=True; production held pending gate/label fix + exp5_10 rerun** |
| exp5_11c | 2026-05-12 | quiet positional near-equivalence gate；ordinal rank 7 / dense rank 3 tie-break clarified；exp5_10 rerun overall Δ +0.014815，quiet regression cleared | **production_promote_request_ready=True; runtime unchanged** |
| exp5_12 | 2026-05-12 | promoted exact staged candidate sha `c47ef752...` to runtime；post-promote 135-case validation Δ +0.022222，endgame +0.090909，5/5 repeatability，0 clean regressions | **production_promote=True; runtime_model_mutated=True** |
| exp5_13 | 2026-05-12 | rule-priority + fixture cleanup + stalemate avoidance；137-case validation Δ +0.021898，smoke 18/18，suspicious 0，5/5 repeatability | **production runtime improved; model sha unchanged** |
| exp5_14 | 2026-05-12 | opening label audit；27/27 opening rows are questionable，15 failed rows classified as 17 teacher-too-narrow / 6 multi-good / 4 do-not-gate，0 clean true opening regressions | **not a production blocker; no clean opening curriculum yet** |
| exp5_14b | 2026-05-12 | curated clean opening expansion；31 kept clean multi-good rows，kept overlap 0，dataset hash `d8888d511...`；current production-equivalent scores 1/31 | **clean opening curriculum ready for exp5_15; no runtime mutation** |

## Difficulty

- `experiment 5:nnue`

## 模型位置

- runtime model：`$HACKME_RUNTIME_DIR/games/models/chess_experiment_5_nnue.json`
- env override：`HTML_LEARNING_CHESS_ENGINE_NNUE_MODEL_PATH`
- bundled seed：`services/games/models/chess_experiment_5_nnue.json`
- current promoted runtime sha256：`c47ef752aa69d7b8c813b587468228593f44d69c9b947313325e03797e4450dc`

模型生命週期：

- bundled seed 只作首次 warm-start，不會被 auto-retrain 改寫。
- 前台 exp5 對局讀取 runtime model。
- future exp5 retrain candidate 應寫入 runtime candidates。
- future exp5 promotion 通過後才替換 runtime production model。

## 使用方式

前台選擇：

- `實驗 5：NNUE + AlphaBeta/PVS`

程式呼叫：

```python
from services.games.chess_nnue import choose_experiment_nnue_move

move = choose_experiment_nnue_move(
    board,
    "black",
    search_profile="fast",
)
```

## 後續文件規則

- exp5 的每次 evaluator、search、gate、promotion decision 都寫在本資料夾。
- 不要直接沿用 exp3 的 semantic replay labels 作為 exp5 promotion evidence。
- 每份報告必須標明：
  - model path
  - evaluator architecture
  - search settings
  - deterministic case set
  - legality / tactic / blunder evidence
  - promotion verdict
