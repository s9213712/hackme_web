# EXP28.5 - Distilled Replay Preprocessing

## 前一個實驗暴露的問題
Exp28 metadata/context reporting 不足以降低訓練噪音與時間，需要 distilled replay preprocessing。

## 實驗目標與要求
目標：

- 對 collected trusted valid games 先做 distilled replay preprocessing，不再把 raw valid games 全部逐步餵給 retrain。
- 蒸餾只降低資料噪音與 retrain 成本，不可當作 promotion evidence。
- distilled row 必須包含 teacher annotation：`expected_move`、`teacher_top3`、`teacher_top5`、`hard_negatives`、`static_best_move`、`static_cp_delta`、`label_quality`、`confidence`、`semantic_class`、`reason_tag`、`difficulty`、`source_game_ids`。
- 使用 `normalized_fen_hash`/FEN hash/expected move 去重合併，輸出 compression ratio、duplicate ratio before/after。
- clean held-out gate cases 不可進 distilled replay；若偵測到 leakage，必須報告並讓 promotion gate false。
- `kingside_aggression` 只保留 style audit，不可進 balanced hard gate；`bad_random_flank_push` 不可進 balanced training target。
- quick retrain 使用 distilled rows + retention anchors，並保留 class-balanced sampling、semantic weights、hard-negative / contrastive / invariance loss。
- 報告必須交叉檢查 retrain time 是否降低；若沒有明顯降低，至少要證明資料大小降低且訓練資料更精華。

實作：

- `scripts/games/chess_live_learning_validation.py` 新增 `_distill_quick_replay_rows`、`_static_teacher_annotation`、`_semantic_distribution_from_rows`、`_previous_quick_gate_retrain_seconds`。
- 每個 checkpoint 會寫出 `distilled_replay.jsonl` 與 `distilled_replay_summary.json`。
- `_run_quick_retrain_checkpoint` 在 formal dataset 產生後先執行 distillation，再把 distilled rows 寫回 checkpoint training dataset。
- Summary 新增 `distilled_replay_preprocessing` 區塊，包含 aggregate raw/distilled rows、compression、duplicate ratio、semantic distribution、leakage、previous retrain seconds、distilled retrain seconds、delta。
- Promotion gate 新增 distilled held-out leakage blocking reason。
- `SUMMARY.md` 新增 Distilled Replay Preprocessing 區塊，明確寫出 `promotion_evidence=false`。
- `tests/scripts/games/test_chess_live_learning_validation_script.py` 新增 exp28.5 fixture，驗證 dedupe/teacher annotation/flank context/style exclusion/leakage detection。

實跑：

- 結果目錄：`<chess_results>/exp28_5_distilled_replay_preprocessing`。
- quick deterministic gate 使用 exp3、`--quick-retrain-gate`、seed `20260511`、`CHESS_EXP3_ABLATION_MODE=invariance_plus_hard_negative`。
- 本次沒有跑 `--semantic-specialist-probes`，用來檢查 distilled quick gate 本體耗時。
- Root verdict：`HIGH_RISK`。
- Promotion gate：`false`。
- Deterministic strength snapshot：`passed=true`，但不能覆蓋 checkpoint instability、mistake retention、contextual flank failure 與 distilled leakage detection。

Timing cross-check：

- exp28 previous retrain baseline：`45.539s`。
- exp28.5 distilled retrain seconds：`42.985s`。
- retrain delta：`-2.554s`。
- `retrain_time_reduced=true`，但只屬於小幅降低。
- `total_wall_seconds=1357.035`。
- `total_checkpoint_seconds=1300.53`。
- `deterministic_eval_seconds=46.15`。
- `report_write_seconds=1.261`。
- 結論：distillation 有讓 retrain 小幅下降，但整體 pipeline 仍主要被 checkpoint consistency / clean held-out evaluation 佔用；目前最大耗時瓶頸不是 raw replay 資料大小。

Distilled replay health：

- aggregate raw replay rows：`100`。
- aggregate distilled replay rows：`93`。
- compression ratio：`0.93`。
- duplicate ratio before：`0.0`。
- duplicate ratio after：`0.0`。
- held_out_in_training：`false`。
- leakage_detected：`true`。
- 解讀：distiller 偵測到與 held-out overlap 的候選並排除，因此最終 training artifact 沒有 held-out 進訓練；但只要偵測到 leakage attempt，promotion gate 仍保持 false，作為資料治理保守策略。

Distilled semantic distribution：

- `e_pawn_central_break=7`。
- `d_pawn_central_break=5`。
- `flank_pawn_push=43`。
- `development_move=3`。
- `kingside_aggression=0`。
- `other=35`。
- 結論：蒸餾成功排除 kingside style hard target，但資料仍偏向 flank 與 other；這是後續 distillation scoring/semantic quota 要修的點。

Checkpoint distillation：

- cp10 raw rows：`36`。
- cp10 distilled rows：`33`。
- cp10 compression：`0.9167`。
- cp10 semantic distribution：`e_pawn=2`、`d_pawn=2`、`flank=18`、`development=1`、`kingside=0`、`other=10`。
- cp10 leakage_detected：`true`。
- cp20 raw rows：`64`。
- cp20 distilled rows：`60`。
- cp20 compression：`0.9375`。
- cp20 semantic distribution：`e_pawn=5`、`d_pawn=3`、`flank=25`、`development=2`、`kingside=0`、`other=25`。
- cp20 leakage_detected：`true`。

Checkpoint consistency：

- cp10 balanced clean retention：`0.3514`。
- cp10 by semantic：`e_pawn_central_break=3/9`、`d_pawn_central_break=1/9`、`flank_pawn_push=1/10`、`development_move=8/9`。
- cp10 contextual flank pass rate：`0.0`。
- cp10 contextual hard flank：`0/4`。
- cp20 balanced clean retention：`0.4324`。
- cp20 by semantic：`e_pawn_central_break=5/9`、`d_pawn_central_break=2/9`、`flank_pawn_push=1/10`、`development_move=8/9`。
- cp20 contextual flank pass rate：`0.0`。
- cp20 contextual hard flank：`0/4`。

Mistake retention：

- cp10 mistake retention：`learning_signal=false`。
- cp10 result：avoided old wrong move but did not match expected move。
- cp10 before/after/expected：`b8a6 -> e7e6`，expected `e7e5`。
- cp20 mistake retention：`learning_signal=true`。
- cp20 before/after/expected：`e7e6 -> e7e5`，expected `e7e5`。
- Gate 仍 false，因為 cp10 retention failed、sanity/generalization thresholds failed、checkpoint instability 存在。

Promotion gate 失敗原因摘要：

- `catastrophic regression detected`。
- cp10/cp20 seen retention below threshold。
- cp10/cp20 clean held-out retention below threshold。
- cp10/cp20 contextual flank hard clean pass rate is zero。
- cp10 prior learned case retention regressed。
- cp10/cp20 hard-negative margin is negative。
- cp10/cp20 semantic hard-negative margin is negative。
- cp10 central break to kingside semantic confusion exceeds threshold。
- cp10/cp20 targeted semantic centroid distance below threshold。
- cp20 policy margin drift left hard-negative margin negative。
- cp10 mistake retention did not match expected move。
- cp10/cp20 sanity probe only memorized exact FEN or failed seen/clean held-out thresholds。
- distilled replay held-out leakage detected。
- engine verdict `HIGH_RISK`。

驗證：

- `python3 -m py_compile scripts/games/chess_live_learning_validation.py services/games/chess_dl.py` 通過。
- `PYTHONPATH=<repo> python3 -m pytest tests/scripts/games/test_chess_live_learning_validation_script.py -q`：`36 passed in 489.11s`。
- `PYTHONPATH=<repo> python3 -m pytest tests/games -q`：`67 passed in 24.85s`。
- `git diff --check` 通過。
- quick deterministic gate with distilled replay 實跑完成，artifact 寫入 `<chess_results>/exp28_5_distilled_replay_preprocessing`。

經驗：

- Distillation 可以降低資料大小與少量 retrain 時間，但目前壓縮率只有 `0.93`，代表 raw fixture 本身重複不高；主要收益是資料治理與 label 清理，而不是大幅省時。
- `kingside_aggression=0` 證明 style preference 沒有混進 balanced hard target，這是正確方向。
- `held_out_in_training=false` 但 `leakage_detected=true` 代表 preprocessor 有抓到 overlap attempt 並排除；對 promotion gate 來說仍應視為高風險資料治理訊號。
- 總牆鐘仍高的主因是 checkpoint consistency evaluation，尤其 clean held-out / contextual flank / retention chain，不是 retrain 本身。
- 下一步如果目標是降 pipeline 時間，應該做 evaluator caching、checkpoint audit 分級、只在必要時跑 full consistency matrix；如果目標是提升棋力，應該加強 distillation semantic quota 與 flank/context learning signal。

## 實驗命令完整全文
legacy `summary.json` 未保存原始 argv；以下為依 artifact output_root、engine 與模式重建的完整命令。若同一 exp 有多次 rerun，全部合併列在本報告。
### exp28_5_distilled_replay_preprocessing
```bash
PYTHONPATH=<repo> python3 <repo>/scripts/games/chess_live_learning_validation.py --engines exp2 --output-root <chess_results>/exp28_5_distilled_replay_preprocessing
```

## 分析及修改項目
詳細內容保留在上方原始 ledger 段落；同一 exp 的多次 rerun 已合併在本報告，不再保存多個 run 資料夾。

## 修改後實際結果
| Run | Engine | Verdict | Promotion | Retrain s | Wall s | Eval s | Checkpoint s | Deterministic gate | Leakage | Smoke | Mistake repair |
| --- | --- | --- | --- | ---: | ---: | ---: | ---: | --- | --- | --- | --- |
| exp28_5_distilled_replay_preprocessing | - | HIGH_RISK | - | 42.985 | - | - | 1300.53 | true | - | - | - |

最後一次 run 原始結果目錄：`<chess_results>/exp28_5_distilled_replay_preprocessing`。

## 結果判讀
最後一次 run verdict=`HIGH_RISK`，promotion=`-`。若 promotion=false，代表 gate 沒有因單一改善指標而誤放。

## 未來修正方向
下一步已由後續 exp 承接；不要降低 promotion gate，應修正被 gate 擋下的模型、資料或評分根因。

## 適用 exp3 / exp4
主要落在 exp3 DL quick-gate/trainer；exp4 使用共用 validation/report surface，若無專門 artifact 則視為部分適用。
