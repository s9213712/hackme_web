# EXP23 - Per-semantic Specialist Learning Probe

## 前一個實驗暴露的問題
Exp22 sampling 已平衡但 kingside/development 仍 0，需判斷是 mixed interference 還是單類本身學不會。

## 實驗目標與要求
目標要求：

- 分別訓練 semantic specialist：`kingside_only`、`development_only`、`central_break_only`、`flank_only`。
- 每組跑 exact pass、seen variant pass、clean held-out pass、hard-negative margin、final decision top1、retention。
- 若 kingside_only 或 development_only 仍 0/9，檢查 label、static/search blocker、semantic feature 是否可區分。
- 若 specialist 能過但 mixed 不能過，代表 multi-task interference；若 specialist 也不能過，代表該 semantic class 的資料、特徵或 move semantics 設計不足。

結果：

- 實跑目錄：`/home/s92137/chess_results/exp23_per_semantic_specialist_probe`。
- Specialist artifact：`/home/s92137/chess_results/exp23_per_semantic_specialist_probe/exp3/semantic_specialist_probes.json`。
- 整體 verdict：`HIGH_RISK`，promotion 維持 false。
- 總診斷：`specialist_capability_or_label_design_failure`。
- `central_break_only`：passed；exact final 0.3889、exact raw 0.7222、clean held-out final 0.3889、clean held-out raw 0.4444、min hard-negative margin -0.0454。
- `flank_only`：passed；exact final 0.6667、exact raw 0.7778、clean held-out final 0.1111、clean held-out raw 0.1111、min hard-negative margin 0.2767。
- `kingside_only`：failed；exact final 0.1111、exact raw 0.1111、clean held-out final 0.0、clean held-out raw 0.0、min hard-negative margin 0.4521。
- `development_only`：passed but weak；exact final 0.3333、exact raw 0.3333、clean held-out final 0.3333、clean held-out raw 0.3333、min hard-negative margin 0.7517。
- cp10 mistake retention passed：`b8a6 -> e7e5`，matched expected。
- cp20 mistake retention failed：`f8a3 -> f8a3`，expected `a5a4`，repeated old mistake。

經驗：

- `kingside_only` 單類訓練仍為 0/9 clean held-out，代表 kingside 失敗不是單純 mixed multi-task interference；優先檢查 kingside label quality、feature 表徵與 final decision path。
- `development_only` 能局部學到但 pass rate 只有 0.3333，代表 development 類也不是穩定能力；需檢查 training target 是否太分散，例如 `g1f3` / `b1c3` / `g8f6` 互相競爭。
- `central_break_only` 和 `flank_only` 在 exact/seen 上較好，但 clean held-out 仍弱，表示整體泛化還沒有達 promotion 條件。
- 下一步不應再調 sampling；應針對 kingside/development 做 label audit、feature probe、final decision blocker 分析，或考慮 semantic-specific heads/adapters。

## 重要 Artifact 與驗證項

- Exp22 結果目錄：`/home/s92137/chess_results/exp22_semantic_class_balanced_sampling`。
- Exp23 結果目錄：`/home/s92137/chess_results/exp23_per_semantic_specialist_probe`。
- 重要報告欄位：`deterministic_strength_snapshot`、`promotion_gate`、`checkpoint_consistency`、`mistake_retention_probe`、`semantic_distribution_by_split`、`clean_heldout_by_semantic`、`semantic_confusion_matrix`、`semantic_sampling`、`semantic_specialist_probes`。
- 重要測試命令：
  `python3 -m py_compile scripts/games/chess_live_learning_validation.py services/games/chess_dl.py`
  `python3 -m pytest tests/scripts/games/test_chess_live_learning_validation_script.py -q`
  `python3 -m pytest tests/games -q`
  `git diff --check`

## Debug 經驗沉澱

- 不要用 stochastic 20-30 盤勝率當 promotion 判準；它可以指出異常，但不能穩定證明棋力。
- 不要用 loss 下降或 model hash 改變當 learning success；那只證明訓練發生，不證明決策變好。
- Exact-FEN pass 只證明 memorization；seen variants pass 仍不足以 promotion；必須看 clean held-out。
- Gate 題庫必須先做 label quality audit；questionable labels 不可用來懲罰模型。
- Gate 題庫平衡後，train/validation 也要平衡；coverage 平衡後還要 sampling/effective weight 平衡。
- Sampling 平衡後仍失敗時，不要再調 gate 或權重，應轉向 representation / architecture / multi-task interference。
- Style profile 可以存在，但 promotion 一律使用 balanced profile。
- exp3/exp4 目前共享同一套 validation/gate/report 基礎；未來修正應預設同步 exp3，避免 exp3 落後於後續實驗。

## 實驗命令完整全文
legacy `summary.json` 未保存原始 argv；以下為依 artifact output_root、engine 與模式重建的完整命令。若同一 exp 有多次 rerun，全部合併列在本報告。
### exp23_per_semantic_specialist_probe
```bash
PYTHONPATH=/home/s92137/hackme_web python3 /home/s92137/hackme_web/scripts/games/chess_live_learning_validation.py --engines exp2 --semantic-specialist-probes --output-root /home/s92137/chess_results/exp23_per_semantic_specialist_probe
```

## 分析及修改項目
詳細內容保留在上方原始 ledger 段落；同一 exp 的多次 rerun 已合併在本報告，不再保存多個 run 資料夾。

## 修改後實際結果
| Run | Engine | Verdict | Promotion | Retrain s | Wall s | Eval s | Checkpoint s | Deterministic gate | Leakage | Smoke | Mistake repair |
| --- | --- | --- | --- | ---: | ---: | ---: | ---: | --- | --- | --- | --- |
| exp23_per_semantic_specialist_probe | - | HIGH_RISK | - | 44.787 | - | - | 886.099 | true | - | - | - |

最後一次 run 原始結果目錄：`/home/s92137/chess_results/exp23_per_semantic_specialist_probe`。

## 結果判讀
最後一次 run verdict=`HIGH_RISK`，promotion=`-`。若 promotion=false，代表 gate 沒有因單一改善指標而誤放。

## 未來修正方向
下一步已由後續 exp 承接；不要降低 promotion gate，應修正被 gate 擋下的模型、資料或評分根因。

## 適用 exp3 / exp4
主要落在 exp3 DL quick-gate/trainer；exp4 使用共用 validation/report surface，若無專門 artifact 則視為部分適用。
