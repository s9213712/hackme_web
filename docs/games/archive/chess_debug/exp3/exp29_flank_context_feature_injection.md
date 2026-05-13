# EXP29 - Flank Context Feature Injection

## 前一個實驗暴露的問題
Exp28/28.5 顯示 metadata-only 不夠；flank context features 需要真正進 trainer/policy scoring。

## 實驗目標與要求
目標：

- 讓 exp28 的 flank context features 不只出現在 report，而是真的進入 trainer / policy scoring。
- 將 `open_or_closed_center`、`king_castled_side`、`wing_space`、`pawn_chain_direction`、`central_tension`、`attack_lane_available`、`opposite_side_castling`、`side_to_move_pressure` 編入 flank context feature vector。
- 將 flank reason tag 作 auxiliary target：`space_gain`、`prophylaxis`、`expansion`、`attack_prep`、`pawn_storm`、`bad_random_flank_push`。
- `bad_random_flank_push` 不可作正樣本，只能作 negative / rejection case。
- 新增 flank auxiliary loss evidence：`flank_context_classification_loss`、`flank_reason_tag_loss`、`flank_vs_nonflank_margin_loss`。
- 對 flank positive 建立 central push、generic development、random flank push hard negatives。
- 保留 balanced promotion gate，不因 flank metadata 或 loss 存在就放行 promotion。

實作：

- `services/games/chess_dl.py` 加入 flank context/reason memory、feature vector、trainer auxiliary updates、context-conditioned policy scoring bias。
- trainer objective 更新為 `contrastive_policy_ranking_with_flank_context_auxiliary`，但仍不允許用 `hash_changed` 或 `replay_loss` 當 learning success。
- `scripts/games/chess_live_learning_validation.py` 新增 `_flank_context_feature_vector`、`_flank_context_feature_injection_report`，並把 checkpoint/root report 都納入 `flank_context_feature_injection`。
- `tests/scripts/games/test_chess_live_learning_validation_script.py` 新增 exp29 feature-vector / trainer auxiliary / report shape 測試。
- `tests/games/test_games.py` 更新 objective assertion。
- exp3 實跑；exp4 共用 trainer/report surfaces，但本輪 artifact 只以 exp3 驗證。

實跑：

- 結果目錄：`<chess_results>/exp29_flank_context_feature_injection`。
- Root verdict：`HIGH_RISK`。
- Promotion gate：`false`。
- total wall seconds：`1810.748`。
- total checkpoint seconds：`1626.684`。
- retrain seconds：`46.207`。
- deterministic eval seconds：`57.18`。
- semantic specialist probe seconds：`113.964`。
- distilled replay rows：`100 -> 93`，compression ratio `0.93`。
- distilled leakage 仍被舊 exp28.5 語義標為 `leakage_detected=true`，但 `held_out_in_training=false`。

Trainer / feature injection evidence：

- `trainer_feature_injection=true`。
- `flank_context_classification_updates=274`。
- `flank_reason_tag_updates=274`。
- `flank_vs_nonflank_margin_updates=1644`。
- `bad_random_flank_rejection_updates=0`。
- `bad_random_flank_push promoted=0`，表示沒有因 context injection 放行隨機 flank push。

Checkpoint evidence：

- cp10 model hash：`025d2a88... -> 35a880b5...`，hash changed。
- cp20 model hash：`35a880b5... -> 7da64236...`，hash changed。
- cp10 mistake retention：`matched_expected=true`，learning signal true。
- cp20 mistake retention：`repeated_old_mistake`，learning signal false。
- cp10 balanced clean held-out retention：`0.4595`。
- cp20 balanced clean held-out retention：`0.4054`。
- cp10 contextual flank hard clean：仍為 0。
- cp20 contextual flank hard clean：仍為 0。

Semantic pass-rate 解讀：

- cp10 clean held-out by semantic：
  - `e_pawn_central_break=1/9`。
  - `d_pawn_central_break=1/9`。
  - `flank_pawn_push=7/10`。
  - `development_move=0/9`。
  - `kingside_aggression=0/9`，僅 style audit，不作 balanced hard gate。
- cp20 clean held-out by semantic：
  - `e_pawn_central_break=0/9`。
  - `d_pawn_central_break=0/9`。
  - `flank_pawn_push=8/10`。
  - `development_move=0/9`。
  - `kingside_aggression=0/9`。
- 結論：flank feature injection 確實讓 flank 類別變強，但 mixed checkpoint 把 e/d central break 打到 0/9，這是典型 semantic interference / catastrophic central retention regression。

Promotion gate 主要失敗原因：

- `catastrophic regression detected`。
- cp10/cp20 seen retention below threshold。
- cp10/cp20 clean held-out retention below threshold。
- cp10/cp20 contextual flank hard clean pass rate is zero。
- cp20 exact retention failed。
- cp20 e/d central semantic pass count is zero。
- cp20 mistake retention repeated old mistake。
- distilled replay held-out leakage detected 仍以 exp28.5 舊語義進 gate reason。
- engine verdict `HIGH_RISK`。

驗證：

- `python3 -m py_compile scripts/games/chess_live_learning_validation.py services/games/chess_dl.py` 通過。
- `PYTHONPATH=<repo> python3 -m pytest tests/scripts/games/test_chess_live_learning_validation_script.py -q`：`38 passed, 1 warning in 478.95s`。
- `PYTHONPATH=<repo> python3 -m pytest tests/games -q`：`67 passed, 1 warning in 28.47s`。
- artifact consistency spot-check 通過。

經驗：

- exp29 證明「flank context feature injection 有用」，但也暴露出「語義更新會互相覆蓋」。
- mixed training 裡 flank 能學起來，不代表 balanced promotion gate 可以過；如果 central break 被打壞，promotion 必須 false。
- 這輪後模型問題應拆成 semantic interference isolation，而不是繼續加 flank loss。
- 系統問題則是 exp28.5 的 leakage 語義太保守：pre-filter overlap 被當成 final leakage，下一步需要把「blocked candidate」和「post-filter leakage」分開。

## 實驗命令完整全文
legacy `summary.json` 未保存原始 argv；以下為依 artifact output_root、engine 與模式重建的完整命令。若同一 exp 有多次 rerun，全部合併列在本報告。
### exp29_flank_context_feature_injection
```bash
PYTHONPATH=<repo> python3 <repo>/scripts/games/chess_live_learning_validation.py --engines exp2 --semantic-specialist-probes --output-root <chess_results>/exp29_flank_context_feature_injection
```

## 分析及修改項目
詳細內容保留在上方原始 ledger 段落；同一 exp 的多次 rerun 已合併在本報告，不再保存多個 run 資料夾。

## 修改後實際結果
| Run | Engine | Verdict | Promotion | Retrain s | Wall s | Eval s | Checkpoint s | Deterministic gate | Leakage | Smoke | Mistake repair |
| --- | --- | --- | --- | ---: | ---: | ---: | ---: | --- | --- | --- | --- |
| exp29_flank_context_feature_injection | - | HIGH_RISK | - | 46.207 | - | - | 1626.684 | true | - | - | - |

最後一次 run 原始結果目錄：`<chess_results>/exp29_flank_context_feature_injection`。

## 結果判讀
最後一次 run verdict=`HIGH_RISK`，promotion=`-`。若 promotion=false，代表 gate 沒有因單一改善指標而誤放。

## 未來修正方向
下一步已由後續 exp 承接；不要降低 promotion gate，應修正被 gate 擋下的模型、資料或評分根因。

## 適用 exp3 / exp4
主要落在 exp3 DL quick-gate/trainer；exp4 使用共用 validation/report surface，若無專門 artifact 則視為部分適用。
