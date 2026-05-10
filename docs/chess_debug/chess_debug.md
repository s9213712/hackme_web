# Chess Exp1-23 Debug History

本文件集中記錄西洋棋 live-learning / quick-retrain / deterministic promotion gate 從 exp1 到 exp23 的 debug 歷程。重點不是功能清單，而是每一輪的目標要求、實跑結果、判斷結論與後續經驗，作為之後調整訓練 pipeline 的依據。

## 總結

- exp1-2 證明「少量實盤勝率與 full-game benchmark」太慢、波動太高，不適合作為每次 promotion gate。
- exp3-6 將 gate 收斂成 quick deterministic evidence，並抓出「loss/hash 變了不等於 final decision 有學到」。
- exp7-13 從 exact-FEN memorization 推到 variants generalization，確認模型會背 seen variants，但 checkpoint 穩定性與 held-out 泛化不足。
- exp14-16 將題庫問題和模型問題分離，建立 clean held-out 與 label quality gate。
- exp17-20 將問題升級成 semantic representation debugging，建立語義平衡 clean gate。
- exp21-22 補齊 train/validation 語義覆蓋與 class-balanced sampling，排除 sampling skew 後，確認剩下的是模型表徵/任務設計問題。
- exp23 進入 per-semantic specialist probe，用來判斷 kingside/development 失敗是「單類本身學不會」還是「mixed multi-task interference」。

## 固定原則

- 從 exp24 起，每個新實驗都必須追加記錄在本檔案 `docs/chess_debug.md`，不可另開分散檔案作為正式 debug 歷程。
- Promotion gate 只能使用可重跑、低波動、可審計的 deterministic evidence。
- Full-game benchmark 只保留為 `stochastic_auxiliary`，不能單獨放行 promotion。
- `hash_changed`、`replay_loss` 下降、runtime/perft 都只能作為診斷資訊，不能當 learning success。
- `promotion_gate.passed=false` 是正常且必要的安全結果，只要 deterministic snapshot、retention、mistake probe、semantic coverage、label quality、poison/invalid gate 任一項不可信。
- exp2 已被淘汰，不再作為前台可選 engine；只保留 legacy data/artifact 相容。

## Exp1 - Live Learning Validation Baseline

目標要求：

- 建立 exp1 live-learning validation。
- 每 10 盤有效 trusted game 觸發 retrain。
- 報告需包含 accepted/rejected、retrain checkpoint、model hash、benchmark、summary。

結果：

- 初版可以產出 live-learning validation report。
- 確認 retrain 觸發條件與 checkpoint artifact 可被記錄。
- 暴露報告太像 dashboard，缺少 promotion decision evidence chain。

經驗：

- 「有 retrain」不是證據，必須能追蹤 dataset hash、before/after model hash、benchmark skipped reason、gate decision。
- 報告要回答「Can This Model Be Promoted?」，不是只列指標。

## Exp2 - 30-game Full Validation 與 Deprecated Heavy Benchmark

目標要求：

- 使用 30-game 結構檢查 exp2。
- `trusted_valid=25`，`quarantine_invalid=5`。
- 每 10 盤 retrain，並補足 20-30 區段讓三個 stage win rate 可比較。
- 報告 stage win rate、retrain timing、mistake retention、benchmark。

結果：

- 30-game 實跑太慢，retrain 接近十分鐘。
- 20-25 stage 曾出現 `0.0` win rate，且 deterministic score 沒提升，mistake retention 下降。
- 判定疑似 catastrophic regression，而不是單純 stochastic noise。
- exp2 後續被刪除為正式 selectable engine，改以 exp3 優化版承接。

經驗：

- 小樣本實盤勝率不可復現，不能作為每次 promotion 的主要依據。
- Full-game benchmark 應改為 nightly/expensive validation 或 SPRT 大量對局，不應放在日常 retrain gate。

## Exp3 - Quick Retrain Gate

目標要求：

- 不再每次跑完整 30-game generation。
- 使用固定 trusted replay fixture、固定 seed、固定 retrain steps/epochs/max seconds。
- 產出 baseline、checkpoint@10、checkpoint@20、final。
- deterministic strength snapshot 成為正式 gate 主體。

結果：

- Quick gate 大幅縮短日常驗收時間。
- 報告開始包含 timing breakdown：replay generation、retrain、deterministic eval、report write、total wall time。
- 仍發現 loss 下降但 deterministic score 不提升。

經驗：

- 快速不等於可信；quick gate 必須保留 deterministic promotion gate。
- replay_loss 下降只能代表 trainer fit 了資料，不能代表 final decision 改善。

## Exp4 - Replay Fixture Diversity 與 Mistake Retention Probe

目標要求：

- 固定 replay fixture 去重、提升多樣性。
- 覆蓋 opening、tactic、endgame、blunder_avoid、mistake_retention。
- mistake retention replay 必須和 probe 對齊。
- 區分 `matched_expected`、`avoided_old_but_not_expected`、`repeated_old_mistake`。

結果：

- 報告加入 fixture health：duplicate ratio、category distribution、unique FEN、unique target move、fixture hash。
- mistake probe 開始輸出 before_move、after_move、expected_move、avoided_old_mistake、matched_expected、learning_signal_reason。
- 仍出現「loss 下降但棋力/決策不變」。

經驗：

- fixture health 是資料品質門檻，但不是學習成功證據。
- mistake retention 必須以 `matched_expected` 作為成功條件；只避開舊錯但沒走正解只能算 partial。

## Exp5 - Sanity Learning Probe Failure Diagnosis

目標要求：

- 診斷為什麼明確餵入 `expected=e7e5` 後，after top1 仍是 `a7a5`。
- 驗證 replay FEN、expected move、encoded move id、legal mask、target policy index。
- 驗證 move encode/decode、checkpoint load、overfit-one-position、policy logits。

結果：

- 確認 expected move 進入 dataset，legal mask 合法，encode/decode 沒有明顯映射錯誤。
- overfit-one-position 顯示 raw policy 可以被推動，但 final decision 不一定改變。
- 根因轉向：訓練目標與最終決策語義不一致。

經驗：

- 如果單一 FEN 高強度 overfit 都不能改 raw top1，才是資料/label/optimizer/load bug。
- 本輪更像 final decision path 把 raw policy 學到的訊號蓋掉。

## Exp6 - Contrastive Trainer 與 Raw/Final Decision Learning 拆分

目標要求：

- trainer 從 positive-only replay loss 改為 contrastive/ranking loss。
- expected move 作 positive，其他 legal moves 或 hard negatives 作 negative。
- sanity probe 拆成 `raw_policy_learning` 與 `final_decision_learning`。
- final decision path 輸出 raw_policy_score、static_eval_score、search_score、final_combined_score、chosen_reason。

結果：

- raw policy 可以更明確提高 expected move rank/margin。
- 報告能區分 raw policy 有學到但 final decision 被 search/static eval 擋住。
- Gate 語義修正：promotion 必須 final decision learning 成立；raw policy learned 只能算 partial。

經驗：

- 「先讓 policy 真的學會，再讓 search/static eval 不要蓋掉它」是後續架構原則。
- final decision unchanged 時必須 promotion false，並輸出 `blocked_by_search_or_static_eval`。

## Exp7 - Exact FEN 到 Seen/Unseen Variants

目標要求：

- 把 sanity probe 的 6 個 variants 加入 training replay。
- 分開評估 exact FEN、seen variants、unseen variants。
- 新增泛化指標：exact_fen_pass、seen_variant_pass_rate、unseen_variant_pass_rate、raw/final generalization rate。
- high confidence policy override 必須受 margin threshold 限制。

結果：

- exact FEN 通過。
- seen variants pass rate 達 1.0。
- unseen variants pass rate 為 0.0。
- deterministic final score 可高於 baseline，但 promotion 仍正確 blocked。

經驗：

- exp6 證明會學，exp7 證明會背；但還不能證明泛化。
- Promotion 不可只靠 exact FEN 或 seen variants。

## Exp8 - Unseen Variant Generalization

目標要求：

- 產生 easy/medium/hard unseen variants。
- 使用 curriculum：exact FEN、easy seen、medium seen、hard held-out。
- 增加 feature generalization debug：embedding similarity、expected rank、blocker reason。
- 修正 checkpoint@20 不能覆蓋 checkpoint@10 已學會能力。

結果：

- 更清楚看到 unseen failure 不是單純 search/static eval 壓掉。
- 部分 checkpoint 出現 learned policy 但 final decision 沒採納。
- checkpoint retention 開始成為 hard gate 條件。

經驗：

- 不增加 self-play 盤數也能定位泛化問題。
- 需要追蹤 checkpoint@10 到 checkpoint@20 的能力是否穩定保留。

## Exp9 - Policy-Search Integration

目標要求：

- 新增 adaptive policy override。
- 比較 strict_search、balanced_fusion、policy_preferred。
- 報告 policy_search_disagreement_rate、override_success_rate、override_regression_rate、fusion_mode_comparison。
- tactic/blunder 不得因 override 退步。

結果：

- fusion/override 沒有造成明顯 tactic/blunder regression。
- 但 unseen variants 失敗主因仍是 raw policy 本身沒有把 expected move 排上來。

經驗：

- Search-policy fusion 不是當前主要 blocker。
- 不能用 override 彌補 raw policy generalization 不足，否則只是把錯誤決策包裝成 learned decision。

## Exp10 - Raw Policy Unseen Generalization 與 Hard Negatives

目標要求：

- 擴大 supervised variant dataset，但不增加 self-play。
- 明確 train/validation/held-out split。
- 加入 hard-negative training：`a7a5`、`f8a3`、`b8c6` 等常見錯誤。
- 報告 expected vs hard-negative margin、failed_unseen_cases。

結果：

- Hard negatives 有幫助，但不足以讓 held-out 泛化過 gate。
- failed_unseen_cases 顯示 expected rank 常掉到 6-12。
- blocking_features 開始指向 board representation 問題。

經驗：

- 問題不是盤數，而是 supervised policy generalization。
- 只壓 hard negatives 不能替代 board semantics representation。

## Exp11 - Board Representation Invariance

目標要求：

- 加入 invariance / consistency loss。
- 同一棋理 variants 的 board embedding 應靠近。
- 加入 pairwise contrastive learning：positive pairs 同棋理/同 expected move，negative pairs 不同棋理/不同 expected move。
- 報告 embedding_similarity before/after、failed feature groups。

結果：

- low board embedding similarity 成為主要證據。
- 模型在 seen variants 可學，但 held-out 幾乎不泛化。
- 表徵層問題比單純 move margin 更明顯。

經驗：

- 泛化失敗不是只靠更大的 margin loss 能解決。
- 需要同時訓練 move target 與 board representation。

## Exp12 - Stability Curriculum 與 Checkpoint Consistency

目標要求：

- curriculum smoothing，避免 checkpoint@10 與 @20 replay 分布差太大。
- 新增 checkpoint stability metrics：exact/seen/unseen/hard-held-out retention、embedding drift、policy margin drift。
- instability detector：final unseen 下降、prior learned case 丟失、embedding drift 過大、hard-negative margin 轉負。

結果：

- 報告新增 checkpoint_consistency_table、embedding_drift_table、retention_chain、instability_reasons。
- 發現 generalized_to_variants 不一定能在 checkpoint@10、checkpoint@20、final 全鏈穩定成立。

經驗：

- 單一 final score 不足以 promotion。
- checkpoint evidence chain 必須穩定，否則代表 retrain pipeline 仍不可控。

## Exp13 - Early Checkpoint 與 Hard-negative Margin Stabilization

目標要求：

- checkpoint@10 前避免混入太難的 hard-held-out 類型。
- hard negatives 漸進加入。
- 對 `a7a5`、`h7h5`、`f8a3`、`b8a6`、`b8c6` 做 margin loss。
- 報告 hard_negative_margin_table、early_checkpoint_failure_analysis、embedding_similarity_delta_by_group。

結果：

- cp10 仍未穩定達到 unseen/hard-held-out 門檻。
- hard-negative margin 部分改善，但仍可為負。
- early checkpoint failure 顯示不是只要多訓練到 cp20 就可信。

經驗：

- Gate 不應因 cp20 偶然通過而放行。
- cp10/cp20 都要達最低泛化與 retention 門檻。

## Exp14 - Ablation 找出泛化失敗主因

目標要求：

- 固定跑 5 組 ablation：no_invariance_memory、invariance_memory_only、hard_negative_only、invariance+hard_negative、stronger_hard_negative_margin。
- 每組報告 cp10/cp20 final unseen、hard-held-out、min hard-negative margin、embedding delta、deterministic score、tactic/blunder regression、failed top3。
- 額外檢查 held-out labels 是否合理。

結果：

- 最佳組合是 invariance_plus_hard_negative，但仍遠低於 gate。
- stronger margin 反而更差。
- 發現 8 個 label quality warning，部分 expected move 在 static check 下落後 -330cp 到 -900cp。

經驗：

- 不能繼續調權重，必須先清理 held-out 題庫。
- 錯標或 questionable labels 會讓 promotion gate 懲罰模型走較合理的棋。

## Exp15 - Held-out Label Quality Gate

目標要求：

- 每個 held-out case 輸出 expected_move、legal、static_best_move、static_cp_delta、expected_rank、label_quality。
- static_cp_delta 落後超過 -150cp 標 questionable，超過 -300cp 不可作為 promotion hard label。
- clean/questionable/invalid 分流，questionable 不參與 gate。

結果：

- questionable labels 被排除後，gate 更可信。
- clean held-out 數量太少，cp20 clean cases 只有 4 題，hard clean 也只有 4 題。
- cp20 clean pass rate 只有 0.25。

經驗：

- exp15 證明 gate 不是壞了，而是題庫還不夠當正式 promotion 證據。
- 下一步必須建立足夠數量、標籤可信、難度分級清楚的 clean held-out set。

## Exp16 - Rebuild Clean Held-out Pool

目標要求：

- 建立 clean held-out pool，easy/medium/hard 各至少 10 題。
- expected_move 必須合法，static_cp_delta 不得低於 -150cp。
- clean/questionable/invalid 分層，並防止 train/validation/held-out leakage。

結果：

- 題庫問題與模型問題被分開。
- leakage、label questionable、search override、tactic/blunder regression 不再是主要失敗原因。
- 乾淨 held-out 上仍失敗，cp20 比 cp10 更差，clean held-out 0.30 降到 0.20。

經驗：

- 失敗主因轉為模型 policy 泛化能力不足。
- 模型似乎學到「中央兵通常不錯」，但無法穩定分辨 `e7e5`、`d7d5`、`f5f4`、`h6g4` 的局面語義。

## Exp17 - Central Pawn Structure 與 Move Semantics Disentanglement

目標要求：

- 將 replay/held-out 分群：e-pawn central break、d-pawn central break、flank pawn push、kingside aggression、development move。
- 加入 semantic-negative training。
- 報告 board semantic features：central control、pawn structure、king safety、development state、open/closed center、side-to-move pressure。
- 輸出 semantic confusion matrix。

結果：

- 第一次量化「錯在哪種棋理」。
- cp10 大量把 e-pawn central break 錯到 kingside aggression。
- cp20 對 d-pawn central break 常錯到 kingside aggression、flank pawn push、少量 e-pawn break。

經驗：

- 模型不是隨機亂走，而是過度偏向攻擊性兵推進語義。
- 語義邊界太粗，必須讓 embedding 空間分離不同 move semantics。

## Exp18 - Semantic Embedding Separation

目標要求：

- 加入 semantic contrastive loss。
- 同 semantic 類別 embedding 拉近，不同 semantic 類別拉遠。
- 建立 semantic centroid analysis，輸出 centroid distance、overlap score、nearest-confused semantic。
- 對 confusion matrix 中最常混淆 pair 增加 targeted replay pairs。

結果：

- semantic margin 與 centroid distance 開始被報告。
- 仍可看到 e-pawn/d-pawn/kingside/flank 之間邊界不夠 sharp。
- promotion gate 仍維持 false。

經驗：

- Move-level hard negatives 有幫助但不夠。
- 真正需要的是 semantic embedding separation，而不是只把某幾個錯步壓低。

## Exp19 - Semantic Class Balance 與 Style Profile 分離

目標要求：

- 檢查 train/validation/held-out 各 semantic class 數量。
- 防止 kingside_aggression 樣本或 bias 壓過 central break。
- centroid separation loss 聚焦最混淆 pair。
- 保留 style profile，但 promotion gate 固定 balanced，attacking/defensive 只做 audit。

結果：

- 報告加入 semantic class distribution、centroid distance before/after、confusion matrix。
- 確立 style preference 不得參與 promotion gate。
- 攻擊/防守人格只能在合理候選步中改排序，不能覆蓋基本棋力。

經驗：

- 可以有 style layer，但不能讓 style 凌駕棋力。
- Promotion gate 測的是基礎正確性，不是偏好。

## Exp20 - Semantic-balanced Clean Gate Set

目標要求：

- 建立語義平衡 gate 題庫，5 個 semantic classes：`e_pawn_central_break`、`d_pawn_central_break`、`flank_pawn_push`、`kingside_aggression`、`development_move`。
- 每類 easy/medium/hard 各 3 題，共 45 clean cases。
- 每題用 evaluator/static check 驗證：legal、static_cp_delta、label_quality、source_reason。
- 若任何 semantic class count=0，promotion false，reason=`semantic_coverage_missing`。

結果：

- clean gate 45 題，語義覆蓋完整。
- questionable/invalid = 0。
- cp20 結果顯示能力集中在少數 e-pawn 類型：e_pawn 2/9、d_pawn 0/9、flank 1/9、kingside 0/9、development 0/9。

經驗：

- Gate 成功把真相攤開：模型不是廣泛棋理能力，只是在少數 e-pawn 類型上有局部能力。
- 下一步不能再調 gate，必須改訓練資料本身。

## Exp21 - Semantic-balanced Training Set

目標要求：

- train/validation replay 也要和 clean gate 一樣語義平衡。
- 五類 semantic classes 每類至少 N 題，且 easy/medium/hard 都有。
- 若 train 或 validation 任一 semantic class count=0，promotion false，reason=`train_validation_semantic_coverage_incomplete`。
- 報告 train_semantic_distribution、validation_semantic_distribution、train_to_gate_semantic_gap、pass_rate_by_semantic、failed_by_semantic_top3。

結果：

- train/validation semantic coverage 補齊。
- 但 sampling 仍失衡：cp10 e_pawn 過重，cp20 flank 過重。
- kingside/development 仍 0/9，retention 也失敗。

經驗：

- 「有教材」不等於「訓練時每類權重公平」。
- 下一步要做 class-balanced sampling / loss weighting。

## Exp22 - Semantic Class-balanced Sampling

目標要求：

- 每個 semantic class 每輪抽樣數一致，或使用 inverse-frequency loss weight。
- 報告 effective_sample_weight_by_semantic。
- checkpoint@10 / @20 分布不得偏斜，`max_class_count / min_class_count <= 2`。
- cp20 不可丟失 cp10 exact / mistake retention。

結果：

- Raw distribution 仍不均，但 effective distribution 已平衡。
- cp10 raw：e_pawn=28、d_pawn=9、flank=10、kingside=9、development=9。
- cp10 effective：約 16.7-18.0，各類 skew ratio 1.08。
- cp20 raw：e_pawn=10、d_pawn=9、flank=27、kingside=9、development=9。
- cp20 effective：約 16.4-18.5，各類 skew ratio 1.12。
- sampling gate 通過，`semantic_sampling_skew` 不再是 blocker。
- clean gate 仍失敗：kingside/development 仍 0/9，cp20 mistake retention 從 expected 走回 `f8a3`。

經驗：

- Sampling 問題已排除，剩下是模型表徵/任務設計問題。
- cp20 retention 失敗表示多任務或 checkpoint drift 仍會覆蓋已學能力。

## Exp23 - Per-semantic Specialist Learning Probe

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

## Exp24 - Kingside / Development Specialist Audit

目標要求：

- 不再調 sampling/gate 讓模型硬過，針對 `kingside_aggression` 與 `development_move` 做 label、feature、decision path 三層審計。
- kingside audit 要輸出 expected_move、static_best_move、static_cp_delta、search_best_move、expected_rank、final_top3、label_quality。
- 若 `g2g4` / `h7h5` 這類 attacking move 被 static/search 明顯拒絕，標 `questionable_style_label`。
- `kingside_aggression` 不再作 balanced promotion hard label，改為 style profile audit。
- development audit 要檢查 `g1f3` / `b8c6` 等 development move 是否真的是合理 top candidate。
- development 多個合理好棋時，不可死盯單一 expected top1，需標 `multi_good_move_case` 並允許 top3/multi-good credit。
- failed cases 要輸出 raw_policy_score、static_eval_score、search_score、final_score、rejection_reason。

目前實作：

- 新增 quick gate 旗標：`--kingside-development-audit`。
- 新增 artifact：`kingside_development_audit.json`。
- `summary.json` 與 `SUMMARY.md` 會寫入 `kingside_development_audit` 區塊。
- Balanced hard gate semantic scope 改為：`e_pawn_central_break`、`d_pawn_central_break`、`flank_pawn_push`、`development_move`。
- `kingside_aggression` 轉為 `style_profile_audit_only`，仍會被報告，但不作 balanced 棋力硬標籤。

結果：

- 實跑目錄：`/home/s92137/chess_results/exp24_kingside_development_audit`。
- 主要 artifact：`/home/s92137/chess_results/exp24_kingside_development_audit/exp3/kingside_development_audit.json`。
- 整體 verdict：`HIGH_RISK`，promotion 維持 false。
- `timing_breakdown.total_wall_seconds=1072.663`，其中 `semantic_specialist_probe_seconds=65.213`、`kingside_development_audit_seconds=35.605`、`deterministic_eval_seconds=48.298`、`retrain_seconds=44.162`。
- Balanced hard gate semantic scope 已改為：`e_pawn_central_break`、`d_pawn_central_break`、`flank_pawn_push`、`development_move`。
- `kingside_aggression_balanced_hard_label=false`，`style_audit_semantics=["kingside_aggression"]`。
- `kingside_label_audit.case_count=9`，`questionable_style_label_count=9`。
- `development_label_audit.case_count=9`，`multi_good_move_case_count=8`，`top3_or_multigood_credit_rate=0.8889`。
- Specialist context：`kingside_can_learn_alone=false`，`development_can_learn_alone=true`，總診斷仍為 `specialist_capability_or_label_design_failure`。
- Specialist rerun 結果與 exp23 一致：`kingside_only` clean held-out final/raw 仍為 0.0；`development_only` clean held-out final/raw 仍為 0.3333。

Kingside audit 代表案例：

- `gate_kingside_easy_001` expected `g2g4`，final top1 `e2e4`，raw rank 7，search_best `e2e3`，標 `questionable_style_label`。
- `gate_kingside_easy_003` expected `h7h5`，final top1 `e7e5`，raw rank 8，search_best `e7e5`，search_delta -138，標 `questionable_style_label`。
- `gate_kingside_medium_001` expected `f7f5`，final top1 `d7d5`，raw rank 19，search_best `e7e5`，search_delta -100，標 `questionable_style_label`。
- `gate_kingside_hard_003` expected `h7h5`，final top1 `e7e5`，raw rank 13，search_best `f6e4`，search_delta -150，標 `questionable_style_label`。

Development audit 代表案例：

- `gate_development_easy_001` expected `g1f3`，raw top3 包含 `g1f3`，因此給 multi-good credit；final top1 是 `e2e4`。
- `gate_development_medium_001` expected `g1f3`，final top1 `f1b5`，raw top3 是 bishop development 類候選，因此標 multi-good。
- `gate_development_hard_001` expected `f1c4`，raw top3 包含 `f1c4`，因此給 multi-good credit；final top1 是 `f3e5`。
- 唯一非 multi-good：`gate_development_hard_002` expected `g8f6`，final top1/search_best/static_best 都偏向 `d5c4`，raw top3 不含 expected，仍是明確 development failure。

經驗：

- exp23 已證明 kingside 單類也學不起來；exp24 要先判斷 kingside 題是否本質上是 style preference，而不是 balanced strength label。
- development 可能是 multi-good move 問題；如果 `g1f3`、`b1c3`、bishop development 都合理，gate 應用 top3/multi-good credit，而不是要求單一 top1。
- exp24 實跑確認 kingside 題庫目前全數更像 attacking style preference，不應放在 balanced promotion hard gate。
- development 題庫大多是多好棋情境，改用 top3/multi-good credit 比單一 top1 更合理；但仍需保留少數真正 failure case，例如 `gate_development_hard_002`。

## Exp25 - Balanced Gate Semantic Cleanup

目標要求：

- promotion gate 改成真正的 balanced 棋力驗收，不再用 `kingside_aggression` 這類 style preference 當硬標籤。
- Balanced hard gate 保留：`e_pawn_central_break`、`d_pawn_central_break`、`flank_pawn_push`、`development_move`。
- `kingside_aggression` 移到 `attacking_style_audit`，只審計 unsafe override，不影響 balanced promotion pass/fail。
- `development_move` 改用 multi-good credit：expected top1 給 full credit；expected in top3 或 static/search 同等合理候選不可直接視為 fail。
- 報告必須新增：`balanced_gate_semantic_set`、`excluded_style_semantics`、`attacking_style_audit`、`development_multi_good_credit`、`balanced_clean_pass_rate_by_semantic`。
- Gate 條件維持：balanced clean held-out >= 0.5、每個 balanced semantic class 至少 pass > 0、illegal_rate=0、blunder_avoid=1、tactic 不退步。

目前實作：

- `_evaluate_sanity_learning_probe()` 會額外產出 balanced clean held-out performance，並排除 `kingside_aggression`。
- `_balanced_gate_performance_for_case_ids()` 只統計 balanced semantic set，style semantics 不進分母。
- `_development_multi_good_credit()` 對 development 類加入 top3/static-equivalent credit，並輸出 credit reason。
- `checkpoint_consistency` 與 `SUMMARY.md` 新增 balanced gate semantic cleanup 區塊。
- `_fusion_mode_comparison()` 的 variant generalization comparison 已限制在 balanced semantic set，避免 style audit 間接造成 balanced gate fail。

結果：

- 修正版實跑目錄：`/home/s92137/chess_results/exp25_balanced_gate_semantic_cleanup_v2`。
- 整體 verdict：`HIGH_RISK`，promotion 維持 false。
- `timing_breakdown.total_wall_seconds=973.428`，其中 `retrain_seconds=43.941`、`deterministic_eval_seconds=47.49`、`kingside_development_audit_seconds=34.513`、`report_write_seconds=4.235`。
- Balanced gate semantic set：`e_pawn_central_break`、`d_pawn_central_break`、`flank_pawn_push`、`development_move`。
- Excluded style semantics：`kingside_aggression`。
- `fusion_mode_comparison` 已改用 balanced variant cases：36 題；style excluded：9 題。
- `strict_search`、`balanced_fusion`、`policy_preferred` 三種 fusion mode 的 balanced final decision generalization 都是 `0.3333`，且 tactic/blunder regression 都是 false。

Balanced clean held-out 結果：

- cp10 overall balanced clean pass rate：`0.3333`。
- cp10 by semantic：`e_pawn_central_break=3/9`、`d_pawn_central_break=0/9`、`flank_pawn_push=1/9`、`development_move=8/9`。
- cp20 overall balanced clean pass rate：`0.3333`。
- cp20 by semantic：`e_pawn_central_break=2/9`、`d_pawn_central_break=1/9`、`flank_pawn_push=1/9`、`development_move=8/9`。
- cp10/cp20 都未達 `balanced clean held-out >= 0.5`，因此 promotion gate 必須 false。

Development multi-good credit：

- cp10 development cases：9；multi-good cases：8；credit applied：8。
- cp20 development cases：9；multi-good cases：8；credit applied：8。
- Development 不再因 `expected_move` 不是 final top1 就全部失敗；若 expected 在 top3 或 static-equivalent 範圍內，會明確記錄 `multi_good_credit_applied` 與 reason。

Attacking style audit：

- attacking style audit case count：9。
- cp10 strict final pass rate：`0.0`，raw policy pass rate：`0.1111`。
- cp20 strict final pass rate：`0.0`，raw policy pass rate：`0.0`。
- `kingside_aggression` 仍會作為 attacking style audit 觀察，但不再進 balanced hard gate 分母，也不再用來直接決定 balanced promotion pass/fail。

Promotion gate 仍失敗的主要原因：

- catastrophic regression detected。
- cp10/cp20 seen retention below threshold。
- cp10/cp20 balanced clean held-out retention below threshold。
- cp10 `d_pawn_central_break` pass count 仍為 0；cp20 雖變成 1/9，但 overall 仍不足。
- hard-negative margin 與 semantic hard-negative margin 仍為負。
- cp20 exact retention failed，mistake retention 在 trusted=20 仍 repeated old mistake。
- `balanced_fusion` final decision generalization 仍低於 threshold。

驗證：

- `python3 -m py_compile scripts/games/chess_live_learning_validation.py services/games/chess_dl.py` 通過。
- `PYTHONPATH=/home/s92137/hackme_web python3 -m pytest tests/scripts/games/test_chess_live_learning_validation_script.py -q`：`27 passed in 279.82s`。
- `PYTHONPATH=/home/s92137/hackme_web python3 -m pytest tests/games -q`：`67 passed in 24.08s`。
- `git diff --check` 通過。
- artifact consistency 自檢通過：root/engine JSON verdict 與 promotion gate 一致，root/engine Markdown 存在，engine SUMMARY 含 `Can This Model Be Promoted?` 與 `Balanced Gate Semantic Cleanup`。

經驗：

- Style preference 不等於 balanced promotion evidence。
- Development 類若存在多個同等好棋，promotion gate 不應用單一 top1 硬標籤懲罰模型；應報告 multi-good credit 的適用範圍與理由。
- exp25 清理後，模型看起來不再被 kingside hard label 直接懲罰，但 balanced clean pass rate 只有 0.3333，問題仍是 d_pawn/flank/generalization/retention 不足，而不是 gate 不公平。

## Exp26 - Central / Flank Balanced Semantic Improvement

目標要求：

- 在 exp25 公平 gate 基礎上，專攻 `e_pawn_central_break`、`d_pawn_central_break`、`flank_pawn_push` 三類的泛化能力。
- 不再調整 `kingside_aggression` / `development_move` 的 gate 定義；development 保留 multi-good credit，且不可 regression。
- 分析 e/d/flank failed cases：failed top3、expected rank、static/search score、semantic confusion target、raw policy fail vs final decision fail。
- 建立 targeted curriculum：明確對比 e-pawn vs d-pawn、central break vs flank push、flank push 何時合理。
- 加入 semantic pair contrast：e positive 時 d/flank 作 negatives；d positive 時 e/flank 作 negatives；flank positive 時 central pawn pushes 作 negatives。
- Gate 條件維持：balanced clean pass rate >= 0.5、e/d/flank 每類 pass > 0、development 不退步、illegal_rate=0、blunder_avoid=1、tactic 不退步、retention 不退步。

目前實作：

- 新增 `CENTRAL_FLANK_FOCUS_SEMANTICS`，明確限定 exp26 focus 為 e/d/flank。
- `_central_flank_targeted_supervised_variants()` 只從 clean semantic templates 產生 e/d/flank targeted train/validation variants，不碰 kingside/development。
- `_semantic_negative_moves()` 對 e/d/flank 改成優先使用互相對比的 semantic negatives，kingside 只排在後面。
- `_sanity_seen_variant_training_rows()` 會把 targeted curriculum rows 標為 `central_flank_targeted_curriculum_replay`，提高權重並記錄 `semantic_pair_contrast`。
- `_central_flank_failed_case_analysis()` 會輸出 e/d/flank failed cases 的 raw/final failure type、expected rank、top3、static/search score、confusion target、decision path。
- `SUMMARY.md` 新增 `Central / Flank Semantic Improvement` 區塊。

結果：

- 實跑目錄：`/home/s92137/chess_results/exp26_central_flank_balanced_semantic_improvement_v2`。
- 整體 verdict：`HIGH_RISK`，promotion 維持 false。
- `timing_breakdown.total_wall_seconds=1328.984`，其中 `retrain_seconds=45.236`、`deterministic_eval_seconds=46.485`、`report_write_seconds=1.153`。
- central/flank targeted curriculum 已啟用，focus semantics 為 `e_pawn_central_break`、`d_pawn_central_break`、`flank_pawn_push`。
- targeted curriculum 新增 train rows：76；train offsets：`[2, 4, 8]`；validation offsets：`[7]`。
- `semantic_pair_contrast`：e/d/flank positive 會使用其他 central/flank semantics 作 hard negatives。
- development strategy：保留 exp25 的 multi-good credit，不把 development 作為 exp26 主攻方向。

Balanced clean held-out 結果：

- cp10 overall balanced clean pass rate：`0.3714`。
- cp10 by semantic：`e_pawn_central_break=3/9`、`d_pawn_central_break=2/9`、`flank_pawn_push=0/8`、`development_move=8/9`。
- cp20 overall balanced clean pass rate：`0.4286`。
- cp20 by semantic：`e_pawn_central_break=3/9`、`d_pawn_central_break=3/9`、`flank_pawn_push=1/8`、`development_move=8/9`。
- 相比 exp25 cp20 的 `0.3333`，exp26 提升到 `0.4286`；但仍低於 gate 門檻 `>=0.5`。
- `development_move` retention 維持 `8/9`，沒有被 exp26 的 e/d/flank targeted curriculum 破壞。

Central/flank failed case analysis：

- cp10 central/flank failed count：21。
- cp10 `d_pawn_central_break`：failed 7，raw policy fail 7，final decision fail 0；confusion target 為 `development_move=2`、`e_pawn_central_break=2`、`kingside_aggression=3`。
- cp10 `e_pawn_central_break`：failed 6，raw policy fail 6，final decision fail 0；confusion target 為 `d_pawn_central_break=3`、`kingside_aggression=3`。
- cp10 `flank_pawn_push`：failed 8，raw policy fail 8，final decision fail 0；confusion target 為 `d_pawn_central_break=2`、`development_move=1`、`e_pawn_central_break=2`、`kingside_aggression=3`。
- cp20 central/flank failed count：19。
- cp20 `d_pawn_central_break`：failed 6，raw policy fail 6，final decision fail 0；confusion target 為 `development_move=1`、`e_pawn_central_break=2`、`flank_pawn_push=2`、`other=1`。
- cp20 `e_pawn_central_break`：failed 6，raw policy fail 5，final decision fail 1；confusion target 為 `d_pawn_central_break=4`、`other=2`。
- cp20 `flank_pawn_push`：failed 7，raw policy fail 7，final decision fail 0；confusion target 為 `d_pawn_central_break=2`、`e_pawn_central_break=3`、`flank_pawn_push=1`、`other=1`。

Fusion / deterministic 結果：

- `strict_search` final decision generalization rate：`0.5`，balanced variant cases：35，style excluded：9，tactic/blunder regression 都是 false。
- `balanced_fusion` final decision generalization rate：`0.5`，balanced variant cases：35，style excluded：9，tactic/blunder regression 都是 false。
- `policy_preferred` final decision generalization rate：`0.5`，balanced variant cases：35，style excluded：9，tactic/blunder regression 都是 false。
- 這表示 exp26 的主要 failure 仍是 raw policy semantic generalization，不是 search/fusion 壓掉已學會的 move。

Promotion gate 仍失敗的主要原因：

- catastrophic regression detected。
- cp10/cp20 seen retention below threshold。
- cp10/cp20 clean held-out retention below threshold。
- cp10 hard clean held-out retention is zero。
- cp10 `flank_pawn_push` clean held-out pass count is zero。
- cp10/cp20 hard-negative margin 與 semantic hard-negative margin 仍為負。
- `semantic_coverage_missing: flank_pawn_push:hard` 仍存在。
- cp10 central break to kingside semantic confusion exceeds threshold。
- cp20 policy margin drift left hard-negative margin negative。
- trusted=20 的 mistake retention probe 仍 repeated old mistake，未 match expected move。

驗證：

- `python3 -m py_compile scripts/games/chess_live_learning_validation.py services/games/chess_dl.py` 通過。
- `PYTHONPATH=/home/s92137/hackme_web python3 -m pytest tests/scripts/games/test_chess_live_learning_validation_script.py -q`：`29 passed in 473.41s`。
- `PYTHONPATH=/home/s92137/hackme_web python3 -m pytest tests/games -q`：`67 passed in 24.24s`。
- quick deterministic gate 實跑完成，artifact 寫入 `/home/s92137/chess_results/exp26_central_flank_balanced_semantic_improvement_v2`。
- artifact consistency 自檢通過：root/engine JSON verdict 與 promotion gate 一致，root/engine Markdown 存在，engine SUMMARY 含 `Can This Model Be Promoted?` 與 `Central / Flank Semantic Improvement`。
- `git diff --check` 在本次程式與測試修改後通過；docs 追加後需再次檢查。

經驗：

- exp25 後主要 blocker 已轉為 central/flank semantic generalization，不再是 style gate 污染。
- exp26 targeted curriculum 有改善 d/e pawn 類與 overall balanced score，但 flank 仍是最弱類別；尤其 cp10 flank 0/8、cp20 flank 1/8。
- final decision path 不是主要 blocker；e/d/flank 失敗大多在 raw policy 階段已經沒有把 expected move 排上來。
- 下一步不應再調 gate，而應針對 flank hard coverage、central-vs-flank semantic boundary、hard-negative margin 轉正與 cp20 retention 做更細的資料/表徵設計。

## Exp27 - Flank Pawn Push Specialist Repair

目標要求：

- 保持 exp26 已改善的 e/d central 與 development retention，專門修 `flank_pawn_push` 泛化不足。
- 補齊 `flank_pawn_push:hard` clean gate cases；若 hard flank coverage missing，promotion gate 必須 false。
- 對每個 flank expected move 做 label audit；若只是風格偏好或 static/search 落後太多，標 questionable，不進 balanced hard gate。
- 新增 flank specialist probe：`flank_only` 訓練，測 exact、seen、clean held-out、hard clean。
- 建立 central push vs flank push confusion matrix；flank positive 時 e/d pawn push 作 semantic negatives。
- Gate 條件維持：balanced clean >= 0.5、flank pass > 0 且 hard flank coverage complete、e/d/development 不退步、mistake retention 不得 fail、illegal=0、blunder_avoid=1、tactic 不退步。

目前實作：

- 新增 `FLANK_REPAIR_SEMANTIC` 與 `CENTRAL_VS_FLANK_BOUNDARY_SEMANTICS`，明確把 exp27 聚焦在 flank repair。
- 修正 `gate_flank_hard_002`，避免和 train/validation key 撞到；新增 `gate_flank_hard_004`，讓 hard flank clean gate coverage 有冗餘。
- 新增 `_flank_label_audit_for_cases()`，輸出 flank clean/questionable/invalid、合法性、semantic match、static cp delta、source reason 與 easy/medium/hard 分布。
- 新增 `_flank_difficulty_performance()`，輸出 flank easy/medium/hard pass rate 與 hard coverage 是否完整。
- 新增 `_central_vs_flank_boundary_report()`，量化 central-to-flank 與 flank-to-central confusion，並分 raw policy / final decision。
- semantic specialist probe 新增 hard clean held-out 與 by-difficulty held-out 結果，讓 `flank_only` 是否真能學 hard flank 可直接審計。
- `SUMMARY.md` 的 Central / Flank Semantic Improvement 區塊會列出 flank label audit、flank difficulty performance、central-vs-flank boundary。

結果：

- 實跑目錄：`/home/s92137/chess_results/exp27_flank_pawn_push_specialist_repair`。
- 整體 verdict：`HIGH_RISK`，promotion 維持 false。
- `timing_breakdown.total_wall_seconds=1515.086`，其中 `retrain_seconds=44.623`、`deterministic_eval_seconds=48.935`、`semantic_specialist_probe_seconds=81.598`、`report_write_seconds=1.346`。
- Artifact consistency 自檢通過：root/engine JSON verdict 與 promotion gate 一致，root/engine Markdown 存在，engine SUMMARY 含 `Can This Model Be Promoted?`、`flank_label_audit` 與 `central_vs_flank_boundary`。

Flank label audit：

- cp10/cp20 flank label audit 都是：clean=10、questionable=0、invalid=0。
- flank easy：3 clean / 0 questionable / 0 invalid。
- flank medium：3 clean / 0 questionable / 0 invalid。
- flank hard：4 clean / 0 questionable / 0 invalid。
- `hard_coverage_complete=true`，`flank_pawn_push:hard` coverage missing 已修正。
- 這代表 exp27 已排除「flank hard 題庫缺題或明顯錯標」這個 blocker。

Balanced clean held-out 結果：

- cp10 overall balanced clean pass rate：`0.3514`。
- cp10 by semantic：`e_pawn_central_break=4/9`、`d_pawn_central_break=0/9`、`flank_pawn_push=1/10`、`development_move=8/9`。
- cp20 overall balanced clean pass rate：`0.3784`。
- cp20 by semantic：`e_pawn_central_break=4/9`、`d_pawn_central_break=1/9`、`flank_pawn_push=1/10`、`development_move=8/9`。
- Development retention 仍維持 `8/9`，沒有被 flank repair 破壞。
- Mistake retention 在 trusted=20 這輪已 match expected：`before=f8a3`、`after=a5a4`、`expected=a5a4`。

Flank easy/medium/hard pass rate：

- cp10 flank easy：`0/3 = 0.0`。
- cp10 flank medium：`0/3 = 0.0`。
- cp10 flank hard：`1/4 = 0.25`。
- cp20 flank easy：`0/3 = 0.0`。
- cp20 flank medium：`0/3 = 0.0`。
- cp20 flank hard：`1/4 = 0.25`。
- flank hard coverage 已完整，但實際能力沒有明顯提升；easy/medium 仍完全失敗。

Flank failed case detail：

- cp10 `gate_flank_easy_001`：expected `c2c4`，rank `11`；final/raw 都選 `e2e4`，錯到 `e_pawn_central_break`。
- cp10 `gate_flank_easy_002`：expected `b2b3`，rank `17`；final/raw 都選 `e2e4`，錯到 `e_pawn_central_break`。
- cp10 `gate_flank_easy_003`：expected `c7c5`，rank `6`；final/raw 都選 `e7e5`，錯到 `e_pawn_central_break`。
- cp10 `gate_flank_medium_001`：expected `c7c5`，rank `4`；final/raw 都選 `e7e5`，錯到 `e_pawn_central_break`。
- cp10 `gate_flank_medium_002`：expected `c7c5`，rank `6`；final/raw 都選 `e7e5`，錯到 `e_pawn_central_break`。
- cp10 `gate_flank_medium_003`：expected `c2c4`，rank `6`；final/raw 都選 `h2h4`，錯到 `kingside_aggression`。
- cp10 `gate_flank_hard_001`：expected `c7c5`，rank `8`；final/raw 都選 `f8a3`，錯到 `development_move`。
- cp10 `gate_flank_hard_002`：expected `c7c5`，rank `5`；final/raw 都選 `e7e5`，錯到 `e_pawn_central_break`。
- cp10 `gate_flank_hard_003`：expected `c7c5`，rank `1`；final/raw 都選 `c7c5`，唯一通過 flank hard case。
- cp10 `gate_flank_hard_004`：expected `c7c5`，rank `5`；final/raw 都選 `d7d5`，錯到 `d_pawn_central_break`。
- cp20 `gate_flank_easy_001`：expected `c2c4`，rank `9`；final/raw 都選 `e2e4`，錯到 `e_pawn_central_break`。
- cp20 `gate_flank_easy_002`：expected `b2b3`，rank `12`；final/raw 都選 `e2e4`，錯到 `e_pawn_central_break`。
- cp20 `gate_flank_easy_003`：expected `c7c5`，rank `5`；final/raw 都選 `d7d5`，錯到 `d_pawn_central_break`。
- cp20 `gate_flank_medium_001`：expected `c7c5`，rank `3`；final/raw 都選 `e7e5`，錯到 `e_pawn_central_break`。
- cp20 `gate_flank_medium_002`：expected `c7c5`，rank `6`；final/raw 都選 `e7e5`，錯到 `e_pawn_central_break`。
- cp20 `gate_flank_medium_003`：expected `c2c4`，rank `7`；final/raw 都選 `f3e5`，錯到 `other`。
- cp20 `gate_flank_hard_001`：expected `c7c5`，rank `4`；final/raw 都選 `a7a5`，semantic 仍是 `flank_pawn_push`，但不是指定 expected move。
- cp20 `gate_flank_hard_002`：expected `c7c5`，rank `3`；final/raw 都選 `d5d4`，錯到 `d_pawn_central_break`。
- cp20 `gate_flank_hard_003`：expected `c7c5`，rank `1`；final/raw 都選 `c7c5`，仍是唯一通過 flank hard case。
- cp20 `gate_flank_hard_004`：expected `c7c5`，rank `5`；final/raw 都選 `d7d5`，錯到 `d_pawn_central_break`。

Flank detail interpretation：

- cp10 到 cp20 不是完全沒有變化，但變化主要是 `e_pawn` bias 轉成部分 `d_pawn` / `other` / generic flank move，沒有穩定學到 `c7c5` 或 `c2c4` 的觸發條件。
- `gate_flank_hard_003` 是唯一穩定通過案例，代表模型可以在某個相對窄的 flank pattern 上選對，但無法遷移到 easy/medium 或其他 hard flank contexts。
- cp20 `gate_flank_hard_001` 選 `a7a5`，semantic 被歸類為 flank，但 expected 是 `c7c5`；這說明模型可能學到「推側翼兵」這個粗語義，卻沒有學到「何時該推 c-pawn 而不是 a-pawn」。

Central vs flank boundary：

- cp10 central_to_flank_confusion：1；flank_to_central_confusion：7。
- cp10 raw_policy_central_to_flank_confusion：1；raw_policy_flank_to_central_confusion：7。
- cp20 central_to_flank_confusion：2；flank_to_central_confusion：7。
- cp20 raw_policy_central_to_flank_confusion：2；raw_policy_flank_to_central_confusion：7。
- 主要錯誤方向是 flank 被預測成 central push；這和 exp26 的「flank raw policy fail」一致。
- cp10 confusion matrix 顯示：flank expected 10 題中，預測為 `e_pawn_central_break=6`、`d_pawn_central_break=1`、`development_move=1`、`kingside_aggression=1`、`flank_pawn_push=1`。
- cp20 confusion matrix 顯示：flank expected 10 題中，預測為 `e_pawn_central_break=4`、`d_pawn_central_break=3`、`other=1`、`flank_pawn_push=2`。
- cp20 flank 正確語義數從 1 提到 2，但 exact expected move pass 仍只有 1/10；semantic-level improvement 不足以作 promotion evidence。

Flank specialist probe：

- `flank_only` specialist：`passed=true` 只是因為 clean held-out 有少量 >0 pass，不能解讀為 flank 已可用。
- `flank_only` exact final pass rate：`0.2`。
- `flank_only` seen final pass rate：`0.2`。
- `flank_only` clean held-out final pass rate：`0.1`。
- `flank_only` hard clean held-out final pass rate：`0.0`。
- `flank_only` hard-negative min margin：`-0.02643851`。
- `flank_only` by difficulty：easy `0.3333`、medium `0.0`、hard `0.0`。
- 結論：flank_only 單獨訓練仍低，尤其 hard clean 0.0；這偏向 label/feature/representation 設計問題，不是 mixed semantic interference。
- `flank_only` failed sample `gate_flank_easy_002`：expected `b2b3`，rank `3`，final/raw 都選 `c2c4`；同為 flank 類但 target move 不對，代表 specialist 在 flank 類內仍缺少 move-level boundary。
- `flank_only` failed sample `gate_flank_easy_003`：expected `c7c5`，rank `5`，final/raw 都選 `a7a5`；同樣是 flank 類內錯誤。
- `flank_only` failed sample `gate_flank_medium_001`：expected `c7c5`，rank `5`，final/raw 都選 `a7a5`；表示 black c-pawn counterplay 和 generic a-pawn flank push 邊界不清。
- 因此 `flank_only passed=true` 只代表「有至少一個 clean held-out pass」，不能代表 flank specialist 已學會；實際判讀應以 clean `0.1`、hard clean `0.0`、min margin negative 為主。

對 exp28 的具體經驗：

- 不要再單純補 flank 題數，因為 hard coverage 已完整且 label audit clean。
- 需要把 flank 類拆細：`c_pawn_counterplay`、`b_pawn_fianchetto_support`、`a_pawn_space_gain` 不能全部混成單一 `flank_pawn_push`。
- Balanced gate 若要求 exact move，應確認 flank 類是否存在多個同等好 flank moves；例如 `a7a5` vs `c7c5` 目前都被 semantic 分到 flank，但棋理目標不同。
- 下一輪應新增 flank sub-semantic confusion matrix，否則模型可能只學到「側翼兵可以推」，卻不知道推哪個側翼兵。
- flank feature 需要明確描述：對手中心兵、己方 c-pawn 是否可安全挑戰、d/e pawn center 是否已鎖定、a/b/c pawn 推進的角色差異。
- 如果 static evaluator 對所有 flank moves 都給 `static_cp_delta=0`，label audit 只能證明「不壞」，不能證明「唯一正解」；這應在 gate reason 中保留為多好棋風險。

Promotion gate 仍失敗的主要原因：

- catastrophic regression detected。
- cp10/cp20 seen retention below threshold。
- cp10/cp20 clean held-out retention below threshold。
- cp10 `d_pawn_central_break` pass count 仍為 0。
- cp10/cp20 hard-negative margin 與 semantic hard-negative margin 仍為負。
- cp10/cp20 targeted semantic centroid distance below threshold。
- cp10/cp20 sanity learning probe 仍只算 memorized exact FEN，seen/clean held-out 未達門檻。
- 整體 balanced clean 仍低於 `>=0.5`。

驗證：

- `python3 -m py_compile scripts/games/chess_live_learning_validation.py services/games/chess_dl.py` 通過。
- `PYTHONPATH=/home/s92137/hackme_web python3 -m pytest tests/scripts/games/test_chess_live_learning_validation_script.py -q`：`31 passed in 489.75s`。
- `PYTHONPATH=/home/s92137/hackme_web python3 -m pytest tests/games -q`：`67 passed in 23.83s`。
- quick deterministic gate + semantic specialist probes 實跑完成，artifact 寫入 `/home/s92137/chess_results/exp27_flank_pawn_push_specialist_repair`。

經驗：

- exp27 成功修掉 flank hard coverage missing，但沒有修掉 flank semantic generalization。
- flank labels 在目前 static audit 下是 clean，代表問題不再是題庫缺題或明顯錯標。
- flank_only specialist 仍無法通過 hard clean，顯示模型目前對 flank pawn push 的 feature/representation 不足；不是混合任務互相干擾造成。
- 下一步不應再只補 flank hard cases，而應重審 flank 類的 feature 設計：什麼盤面條件讓 c-pawn/b-pawn flank push 是「棋力正解」，以及如何和 generic central push bias 分離。
