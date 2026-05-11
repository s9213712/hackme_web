# Chess Exp1-34 / Exp3 Debug History

本文件集中記錄西洋棋 live-learning / quick-retrain / deterministic promotion gate 從 exp1 到 exp34 的 debug 歷程。重點不是功能清單，而是每一輪的目標要求、指令方向、驗收要求、修改項目、實跑數據、勝率或 deterministic gate 指標、結果判讀、exp3/exp4 適用範圍與後續經驗，作為之後調整訓練 pipeline 的依據。

## 總結

- exp1-2 證明「少量實盤勝率與 full-game benchmark」太慢、波動太高，不適合作為每次 promotion gate。
- exp3-6 將 gate 收斂成 quick deterministic evidence，並抓出「loss/hash 變了不等於 final decision 有學到」。
- exp7-13 從 exact-FEN memorization 推到 variants generalization，確認模型會背 seen variants，但 checkpoint 穩定性與 held-out 泛化不足。
- exp14-16 將題庫問題和模型問題分離，建立 clean held-out 與 label quality gate。
- exp17-20 將問題升級成 semantic representation debugging，建立語義平衡 clean gate。
- exp21-22 補齊 train/validation 語義覆蓋與 class-balanced sampling，排除 sampling skew 後，確認剩下的是模型表徵/任務設計問題。
- exp23 進入 per-semantic specialist probe，用來判斷 kingside/development 失敗是「單類本身學不會」還是「mixed multi-task interference」。
- exp24-25 將 kingside style preference 移出 balanced promotion gate，並把 development 改成 multi-good/top3 credit。
- exp26-28 專攻 central/flank semantic generalization，確認 flank 需要 context-conditioned learning，而不是粗略的 flank pawn push 類別。
- exp28.5 加入 distilled replay preprocessing，交叉確認 retrain 時間只小幅下降，主要瓶頸仍在 checkpoint consistency / clean held-out evaluation。
- exp29 將 flank context metadata 真的注入 trainer/policy scoring，證明 flank specialist 能改善，但 mixed gate 出現 central semantic regression。
- exp30a 修正 distilled replay held-out leakage 判定，加入 canonical leakage guard、evaluation cache key 與 smoke gate，將 checkpoint evaluation 從千秒級降回分鐘級，但 promotion 仍正確擋下。
- exp30b 將 semantic update 隔離成 central/flank/development adapter memory，並輸出 interference matrix；結果確認 flank 變強時 central retention 仍被打壞，下一步需要更嚴格的 loss budget / update scheduling。

## 報告與 Artifact 備查

- 本文件已從 `docs/chess_debug/chess_debug.md` 移到 `docs/games/chess_debug/exp3/chess_debug.md`。
- 詳細實驗報告位於本資料夾。
- `exp3/` 採扁平結構：每個 exp 只保留一份人類可讀 Markdown 報告；同一 exp 的多次 rerun 必須整理進同一份報告。
- `exp30a` 與 `exp30b` 合併在同一份 exp30 報告，並分別說明 data hygiene/cache 與 semantic interference isolation 各自解決的問題。
- 原始大型 artifact 仍以 `/home/s92137/chess_results/...` 作為實跑來源路徑記錄；本資料夾不再保存 root/engine `summary.json` / `SUMMARY.md` 資料夾 dump。
- 報告索引：[`INDEX.md`](INDEX.md)。
- 勝率欄位只在 full-game / 30-game 類驗證中有意義；quick deterministic gate 不使用實盤勝率作 promotion evidence。

## 固定原則

- exp3 目前暫停開發；若未來只做 exp3 baseline 回歸，必須追加記錄在本檔案。
- exp4 後續演進文件改放 `docs/games/chess_debug/exp4/`。
- exp5 後續演進文件改放 `docs/games/chess_debug/exp5/`。
- 每次實跑後，對應 engine 資料夾必須同步更新單一 Markdown 報告；若同一 exp 多次實跑，合併成同一份，不新增 run folder。
- Promotion gate 只能使用可重跑、低波動、可審計的 deterministic evidence。
- Full-game benchmark 只保留為 `stochastic_auxiliary`，不能單獨放行 promotion。
- `hash_changed`、`replay_loss` 下降、runtime/perft 都只能作為診斷資訊，不能當 learning success。
- `promotion_gate.passed=false` 是正常且必要的安全結果，只要 deterministic snapshot、retention、mistake probe、semantic coverage、label quality、poison/invalid gate 任一項不可信。
- exp2 已被淘汰，不再作為前台可選 engine；只保留 legacy data/artifact 相容。

## Exp3 / Exp4 適用範圍

- `exp3` 是 quick deterministic promotion gate 的實作驗證目標，後續 exp7-34 的 representation / semantic / distilled replay / evaluation-cache / semantic-interference 改動主要都以 exp3 DL artifact 實跑驗證。
- `exp4` 仍保留在 validation script 的 quick retrain gate / report framework 中，並支援 retrain、raw policy evaluation、decision breakdown 與 exp6 之後的基礎 evidence surface。
- `exp3` 與 `exp4` 共享 `RETRAIN_ENGINE_ALIASES={"exp3","exp4"}` 的 validation / report 管線；未來修正應預設同步到 exp3，並檢查 exp4 是否有對應 trainer/evaluator path。
- 目前 style audit、kingside/development specialist、semantic specialist 與多數 later semantic gate 主要是 exp3-centered；若某次 report 沒有 exp4 artifact，不可推論 exp4 已通過同等驗收。
- exp2 已移除前台 selectable engine；exp2 artifact 只作為 deprecated full-game benchmark / 30-game validation 的歷史證據。

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

## Exp28 - Context-Conditioned Flank Semantic Learning

目標：

- 不再只把 `flank_pawn_push` 當成 move 類別，而是要求模型與報告判斷「什麼局面條件下 flank push 才合理」。
- 新增 flank context features：`open/closed center`、`king castled side`、`wing space advantage`、`pawn chain direction`、`central tension`、`attack lane availability`、`opposite-side castling`、`side-to-move pressure`。
- 新增 flank reason tags：`space_gain`、`attack_prep`、`pawn_storm`、`prophylaxis`、`expansion`、`bad_random_flank_push`。
- 每個 flank case 必須進行 label audit v2，標出 reason tag；若是無理由亂推兵，不能進 balanced hard gate。
- 新增 `flank_only_contextual` specialist probe，區分「能選 flank move」和「能在正確 context 選正確 flank move」。
- 報告新增 `flank_reason_distribution`、`contextual_flank_pass_rate`、`bad_random_flank_push_confusion`、`non_flank_move_confusion`、`context_feature_importance`。
- Gate 要求 balanced clean >= 0.5、contextual flank hard clean > 0、不可 promotion bad random flank push、development/e/d retention 不退步、mistake retention 不退步。

實作：

- `scripts/games/chess_live_learning_validation.py` 新增 `FLANK_REASON_TAGS`、`_flank_context_features`、`_flank_reason_tag_for_move`、`_contextual_flank_performance_from_rows`、`_context_feature_importance`。
- Semantic balanced clean gate set、semantic balanced supervised variants、central/flank targeted variants、specialist training rows 都寫入 `flank_context_features` 與 `flank_reason_tag`。
- `_flank_label_audit_for_cases` 升級為 `exp28_flank_label_audit_v2`，新增 reason distribution、bad random count、excluded bad random cases，並讓 bad random flank 不具 balanced gate eligibility。
- Checkpoint consistency table 保留 `contextual_flank_performance`、`flank_reason_distribution`、`bad_random_flank_push_confusion`、`context_feature_importance`。
- Promotion gate 新增 contextual flank hard clean 0 時 blocking reason；bad random flank push 被真正 promotion 時也 blocking。
- 修正一個重要語義錯誤：非 flank move，例如 `e2e4`、`e7e5`、`d7d5`、`f8a3`，不再被誤報成 `bad_random_flank_push promoted`，而是歸類為 `non_flank_move_confusion`。只有實際選到無合理 flank context 的 flank move，才算 `bad_random_flank_push promoted`。
- `SUMMARY.md` 的 Central / Flank Semantic Improvement 區塊會列出 flank reason distribution、contextual flank pass、hard contextual hits、bad random promoted、feature importance。
- `tests/scripts/games/test_chess_live_learning_validation_script.py` 新增 exp28 fixture 測試，覆蓋 context features、reason tags、contextual flank performance、bad/random vs non-flank confusion、label audit v2 gate exclusion。

實跑：

- 結果目錄：`/home/s92137/chess_results/exp28_context_conditioned_flank_semantic_learning`。
- quick deterministic gate 使用 exp3、`--quick-retrain-gate`、`--semantic-specialist-probes`、seed `20260511`、`CHESS_EXP3_ABLATION_MODE=invariance_plus_hard_negative`。
- Root verdict：`HIGH_RISK`。
- Promotion gate：`false`。
- Deterministic strength snapshot：`passed=true`，但不能覆蓋 checkpoint instability 與 contextual flank failure。
- Timing breakdown：`total_wall_seconds=1562.966`、`retrain_seconds=45.539`、`deterministic_eval_seconds=48.695`、`semantic_specialist_probe_seconds=100.766`、`report_write_seconds` 約 1 秒級。

Checkpoint consistency：

- cp10 balanced clean retention：`0.3514`。
- cp10 by semantic：`e_pawn_central_break=4/9`、`d_pawn_central_break=0/9`、`flank_pawn_push=1/10`、`development_move=8/9`。
- cp10 contextual flank pass rate：`0.0`。
- cp10 contextual hard flank：`0/4`。
- cp10 bad_random_flank_push promoted：`0`。
- cp10 non_flank_move_confusion：`9`。
- cp20 balanced clean retention：`0.3784`。
- cp20 by semantic：`e_pawn_central_break=4/9`、`d_pawn_central_break=1/9`、`flank_pawn_push=1/10`、`development_move=8/9`。
- cp20 contextual flank pass rate：`0.0`。
- cp20 contextual hard flank：`0/4`。
- cp20 bad_random_flank_push promoted：`0`。
- cp20 non_flank_move_confusion：`8`。

Flank reason distribution：

- `space_gain=6`。
- `prophylaxis=3`。
- `expansion=1`。
- `attack_prep=0`。
- `pawn_storm=0`。
- `bad_random_flank_push=0`。
- 這代表 gate 題庫本身沒有 bad random flank labels；失敗主因不是題庫混入亂推兵，而是模型沒有在這些 context 下選到對應 flank move。

Context feature importance：

- cp10/cp20 top failure features 都集中在 `open_closed_center=closed`、`king_castled_side own/opponent=uncastled`、`kingside_space=neutral`、`pawn_chain_direction=balanced`。
- 這些 feature 目前沒有幫模型分辨「該 c-pawn counterplay / b-pawn support / 其他 flank role」。
- `central_tension=positive` 與 `c_file_open_or_tension=True` 在部分 hard/medium cases 出現，但仍沒有轉化成 contextual flank pass。

Specialist probe：

- `flank_only` specialist：`passed=true` 仍只能代表至少有少量 clean case pass。
- `flank_only` clean held-out final pass rate：`0.1`。
- `flank_only` hard clean held-out final pass rate：`0.0`。
- `flank_only` contextual flank pass rate：`0.1`。
- `flank_only` hard contextual：`0/4`。
- `flank_only` bad_random_flank_push promoted：`0`。
- `flank_only` non_flank_move_confusion：`1`。
- `flank_only_contextual` specialist：`passed=true` 同樣不能解讀為 contextual flank 已學會。
- `flank_only_contextual` clean held-out final pass rate：`0.1`。
- `flank_only_contextual` hard clean held-out final pass rate：`0.0`。
- `flank_only_contextual` contextual flank pass rate：`0.1`。
- `flank_only_contextual` hard contextual：`0/4`。
- `flank_only_contextual` bad_random_flank_push promoted：`0`。
- `flank_only_contextual` non_flank_move_confusion：`1`。

Promotion gate 失敗原因：

- `catastrophic regression detected`。
- cp10/cp20 seen retention below threshold。
- cp10/cp20 clean held-out retention below threshold。
- cp10 `d_pawn_central_break` pass count 仍為 0。
- cp10/cp20 contextual flank hard clean pass rate is zero。
- cp10/cp20 hard-negative margin 仍為負。
- cp10/cp20 semantic hard-negative margin 仍為負。
- cp10/cp20 targeted semantic centroid distance below threshold。
- cp10/cp20 sanity probe 仍只證明 exact FEN memorization，沒有通過 seen/clean held-out 泛化門檻。

驗證：

- `python3 -m py_compile scripts/games/chess_live_learning_validation.py services/games/chess_dl.py` 通過。
- `PYTHONPATH=/home/s92137/hackme_web python3 -m pytest tests/scripts/games/test_chess_live_learning_validation_script.py -q`：`34 passed in 492.33s`。
- `PYTHONPATH=/home/s92137/hackme_web python3 -m pytest tests/games -q`：`67 passed in 24.76s`。
- `git diff --check` 通過。
- quick deterministic gate + semantic specialist probes 實跑完成，artifact 寫入 `/home/s92137/chess_results/exp28_context_conditioned_flank_semantic_learning`。

經驗：

- exp28 把 flank 失敗原因拆得更乾淨：目前不是 bad random flank push 被 promotion，而是 flank 題大量被選成 non-flank move；模型仍傾向 central/development/general move，而不是 context-appropriate flank move。
- `flank_only_contextual` 沒有比 `flank_only` 改善 hard clean，表示只把 context metadata 寫進 replay/report 還不足以讓 trainer 真正使用這些 feature。
- 下一步如果要修模型，應該讓 trainer 或 representation 明確學習 flank sub-semantics，而不是只在 artifact 中標註 context。
- 需要把 `flank_pawn_push` 再拆成更細的 sub-semantic，例如 `c_pawn_counterplay`、`b_pawn_fianchetto_support`、`a_pawn_space_gain`、`anti_center_tension_flank_break`，否則 `a7a5`、`c7c5`、`b2b3` 仍會被同一個粗類別混在一起。
- Context feature 目前是 audit evidence，不是 learning signal；若不進入 loss 或 policy feature，模型不會自然學到「closed center + c-file tension -> c-pawn counterplay」這類規則。
- Gate 維持 false 是正確結果；目前 evidence 證明模型會記 exact mistake retention，但還不能證明 balanced flank/central 泛化能力。

## Exp28.5 - Distilled Replay Preprocessing

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

- 結果目錄：`/home/s92137/chess_results/exp28_5_distilled_replay_preprocessing`。
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
- `PYTHONPATH=/home/s92137/hackme_web python3 -m pytest tests/scripts/games/test_chess_live_learning_validation_script.py -q`：`36 passed in 489.11s`。
- `PYTHONPATH=/home/s92137/hackme_web python3 -m pytest tests/games -q`：`67 passed in 24.85s`。
- `git diff --check` 通過。
- quick deterministic gate with distilled replay 實跑完成，artifact 寫入 `/home/s92137/chess_results/exp28_5_distilled_replay_preprocessing`。

經驗：

- Distillation 可以降低資料大小與少量 retrain 時間，但目前壓縮率只有 `0.93`，代表 raw fixture 本身重複不高；主要收益是資料治理與 label 清理，而不是大幅省時。
- `kingside_aggression=0` 證明 style preference 沒有混進 balanced hard target，這是正確方向。
- `held_out_in_training=false` 但 `leakage_detected=true` 代表 preprocessor 有抓到 overlap attempt 並排除；對 promotion gate 來說仍應視為高風險資料治理訊號。
- 總牆鐘仍高的主因是 checkpoint consistency evaluation，尤其 clean held-out / contextual flank / retention chain，不是 retrain 本身。
- 下一步如果目標是降 pipeline 時間，應該做 evaluator caching、checkpoint audit 分級、只在必要時跑 full consistency matrix；如果目標是提升棋力，應該加強 distillation semantic quota 與 flank/context learning signal。

## Exp29 - Flank Context Feature Injection

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

- 結果目錄：`/home/s92137/chess_results/exp29_flank_context_feature_injection`。
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
- `PYTHONPATH=/home/s92137/hackme_web python3 -m pytest tests/scripts/games/test_chess_live_learning_validation_script.py -q`：`38 passed, 1 warning in 478.95s`。
- `PYTHONPATH=/home/s92137/hackme_web python3 -m pytest tests/games -q`：`67 passed, 1 warning in 28.47s`。
- artifact consistency spot-check 通過。

經驗：

- exp29 證明「flank context feature injection 有用」，但也暴露出「語義更新會互相覆蓋」。
- mixed training 裡 flank 能學起來，不代表 balanced promotion gate 可以過；如果 central break 被打壞，promotion 必須 false。
- 這輪後模型問題應拆成 semantic interference isolation，而不是繼續加 flank loss。
- 系統問題則是 exp28.5 的 leakage 語義太保守：pre-filter overlap 被當成 final leakage，下一步需要把「blocked candidate」和「post-filter leakage」分開。

## Exp30a - Distilled Replay Leakage Fix + Evaluation Cache

目標：

- 修掉 exp28.5/exp29 的 distilled replay held-out leakage hard blocker。
- 建立 held-out manifest，包含 `fen_hash`、`normalized_fen_hash`、`board_context_hash`、`semantic_class`、`expected_move`、`case_id`。
- distilled replay 產生前後都檢查 train vs clean held-out、train vs validation、train vs specialist probe overlap。
- 若 post-filter 仍有 overlap，才標 `held_out_in_training=true`、`promotion_gate=false`、reason=`distilled_replay_heldout_leakage`。
- pre-filter overlap 只記錄為 blocked candidate，不再等同於 final train leakage。
- 建立 evaluation cache key：`model_hash`、`case_set_hash`、`evaluator_config_hash`、`decision_mode`、`style_profile`、`semantic_gate_version`。
- 加入 incremental smoke gate：先跑少量 retention anchors、e/d/flank/development clean cases、mistake retention、leakage check；smoke gate fail 時不跑 full specialist probe。
- 不修改 promotion gate 門檻，不讓 gate 假通過。

實作：

- `scripts/games/chess_live_learning_validation.py` 新增 canonical leakage helpers：
  - `_fen_hash`。
  - `_board_context_hash`。
  - `_leakage_manifest_from_cases`。
  - `_exp30a_leakage_manifest`。
  - `_leakage_keys_from_manifest`。
  - `_row_leakage_matches`。
- `_distill_quick_replay_rows` 改成先排除 overlap candidate，再對 distilled output 做 post-filter leakage check。
- distilled report 新增：
  - `pre_filter_overlap_count`。
  - `blocked_leakage_candidate_count`。
  - `leakage_count`。
  - `leakage_case_ids`。
  - `leakage_hashes`。
  - `leakage_source_game_ids`。
  - `held_out_manifest`。
- 新增 cache / smoke gate helpers：
  - `_case_set_hash`。
  - `_evaluator_config_hash`。
  - `_cached_position_set_performance`。
  - `_evaluate_incremental_smoke_gate`。
  - `_skipped_sanity_learning_probe_from_smoke`。
- checkpoint 若 smoke gate fail，`sanity_learning_probe.result_kind=smoke_gate_failed_full_gate_skipped`，並記錄 `full_gate_skipped=true`。
- quick gate summary 新增 `exp30a_pipeline`，同步寫入 root/engine JSON 與 Markdown。
- `semantic_specialist_probes` 若 smoke gate 已 fail，會被跳過並報告 `full_gate_skipped=true`，避免再跑重型 specialist matrix。
- `tests/scripts/games/test_chess_live_learning_validation_script.py` 新增 exp30a cache key / smoke skip 測試，並修正 exp28.5 leakage fixture 語義。

實跑：

- 結果目錄：`/home/s92137/chess_results/exp30a_distilled_replay_leakage_fix_evaluation_cache`。
- Root verdict：`HIGH_RISK`。
- Promotion gate：`false`。
- total wall seconds：`129.95`。
- previous total checkpoint seconds：`1300.53`。
- new total checkpoint seconds：`71.747`。
- retrain seconds：`44.407`。
- deterministic eval seconds：`50.954`。
- semantic specialist probe seconds：`0.0`，因 smoke gate fail 正確跳過。
- skipped eval seconds estimate：`67.657`。
- cache hit count：`0`。
- cache miss count：`2`。
- cache hit ratio：`0.0`。
- 本輪第一次跑該 case-set/model hash，因此 cache 無命中；實際省時主要來自 smoke-gate early stop，不是 cache reuse。

Distilled replay hygiene：

- raw replay rows：`100`。
- distilled replay rows：`93`。
- compression ratio：`0.93`。
- previous retrain seconds：`45.539`。
- distilled retrain seconds：`44.407`。
- retrain seconds delta：`-1.132`。
- retrain_time_reduced：`true`。
- pre_filter_overlap_count：`6`。
- blocked_leakage_candidate_count：`6`。
- post_filter leakage_count：`0`。
- leakage_detected：`false`。
- held_out_in_training：`false`。
- leakage_case_ids：`[]`。
- leakage_hashes：`[]`。
- 結論：exp30a 修掉的是 promotion evidence 的資料治理語義。蒸餾前確實有 overlap 候選，但已在進入 train artifact 前擋掉；最終 distilled replay 沒有 held-out leakage。

Distilled semantic distribution：

- `e_pawn_central_break=7`。
- `d_pawn_central_break=5`。
- `flank_pawn_push=43`。
- `development_move=3`。
- `kingside_aggression=0`。
- `other=35`。
- 解讀：leakage 修掉後，distilled data 仍偏向 flank/other；這是資料品質問題，不是本輪 exp30a 的 gate 目標。

Smoke gate evidence：

- cp10 smoke clean held-out pass rate：`0.125`。
- cp10 by semantic：
  - `e_pawn_central_break=0/2`。
  - `d_pawn_central_break=1/2`。
  - `flank_pawn_push=0/2`。
  - `development_move=0/2`。
- cp10 mistake retention：`matched_expected=true`。
- cp10 full gate skipped：`true`，reason=`smoke_clean_heldout_pass_rate_below_threshold`。
- cp20 smoke clean held-out pass rate：`0.125`。
- cp20 by semantic：
  - `e_pawn_central_break=0/2`。
  - `d_pawn_central_break=0/2`。
  - `flank_pawn_push=1/2`。
  - `development_move=0/2`。
- cp20 mistake retention：`repeated_old_mistake`，learning signal false。
- cp20 full gate skipped：`true`，reason=`mistake_retention_probe_failed; smoke_clean_heldout_pass_rate_below_threshold`。

Timing 判讀：

- exp29 total checkpoint seconds：`1626.684`。
- exp28.5 total checkpoint seconds：`1300.53`。
- exp30a new total checkpoint seconds：`71.747`。
- exp30a total wall seconds：`129.95`。
- 主要省時來源是 incremental smoke gate fail 後跳過 full clean held-out / specialist matrix。
- Cache infrastructure 已存在，但本輪 cache hit ratio `0.0`，因為第一次跑沒有可重用 cache；後續相同 model hash + case set hash + evaluator config 才會命中。
- retrain 本身仍約 `44s`，不是主要瓶頸；distillation 只小幅降低 retrain time，但有助於資料乾淨度。

Promotion gate 失敗原因摘要：

- `catastrophic regression detected`。
- checkpoint instability：cp10/cp20 exact retention failed、seen retention below threshold、clean held-out below threshold。
- cp10/cp20 hard clean labels missing，因 full gate 被 smoke gate 跳過，不能把 full gate evidence 當已通過。
- cp10 e_pawn / flank / development smoke pass count 為 0。
- cp20 e_pawn / d_pawn / development smoke pass count 為 0。
- cp20 mistake retention repeated old mistake。
- full deterministic gate skipped after smoke gate failure。
- engine verdict `HIGH_RISK`。

驗證：

- `python3 -m py_compile scripts/games/chess_live_learning_validation.py services/games/chess_dl.py` 通過。
- `PYTHONPATH=/home/s92137/hackme_web python3 -m pytest tests/scripts/games/test_chess_live_learning_validation_script.py -q`：`40 passed in 488.30s`。
- `PYTHONPATH=/home/s92137/hackme_web python3 -m pytest tests/games -q`：`67 passed in 23.48s`。
- quick gate with distilled replay hygiene 實跑完成。
- artifact consistency：`_report_consistency_issues(...) == []`。
- `git diff --check` 通過。

經驗：

- exp30a 明確分離了兩件事：pre-filter overlap 是 blocked candidate；post-filter leakage 才是 promotion blocker。
- 這修掉了 exp28.5/exp29 的硬 blocker：本輪 `held_out_in_training=false` 且 `leakage_detected=false`。
- 但 promotion 仍正確 false，因為 smoke gate 與 mistake retention 已足夠證明模型不該進 full promotion gate。
- 現在 pipeline 可以在早期失敗時從 1000+ 秒降到約 130 秒，避免每次都跑完整 specialist probes。
- 下一步模型線應做 exp30b：semantic interference isolation。exp29 已證明 flank 可以被學起來，但會覆蓋 central；exp30a 只是讓這種失敗更快、更乾淨地被擋下。

## Exp30b - Semantic Interference Isolation

目標：

- 修正 exp29 暴露的 catastrophic semantic interference：flank context feature injection 有效，但 mixed checkpoint 讓 e/d central break 幾乎歸零。
- 不再只是加 flank loss，而是隔離 semantic updates，避免某一類語義更新直接覆蓋所有語義。
- 新增 semantic-specific adapters / heads：
  - `central_head`。
  - `flank_head`。
  - `development_head`。
  - `other_head`。
- shared trunk 保留，但 semantic-specific update 要有獨立 adapter memory 與 update count。
- 根據 context features / semantic class 輸出 routing weights。
- 每個 checkpoint 都要報 central/flank/development/mistake retention。
- 新增 semantic loss budget 與 interference matrix。
- Gate 不變：balanced clean、semantic pass、mistake retention、illegal/blunder/tactic、held-out hygiene 任一不可信都不可 promotion。

實作：

- `services/games/chess_dl.py` 新增 `semantic_head_memory`，作為現有 MLP + memory architecture 下的 semantic-specific adapter。
- 新增 `_semantic_head_name`、`_semantic_head_key`、`_semantic_head_memory_bias`、`_update_semantic_head_memory`。
- policy scoring path 現在會加上 semantic adapter bias，但仍受 balanced fusion / legality / static/search path 約束。
- trainer 統計新增：
  - `semantic_specific_adapters=true`。
  - `semantic_head_update_count`。
  - `semantic_loss_budget`。
  - `semantic_specific_adapter_loss=true`。
  - `semantic_loss_budget_guard=true`。
- training objective 改為 `contrastive_policy_ranking_with_flank_context_auxiliary_semantic_adapters`。
- `scripts/games/chess_live_learning_validation.py` 新增：
  - `_semantic_routing_weights_for_case`。
  - `_semantic_interference_isolation_report`。
  - `exp30b_pipeline` root/engine summary。
  - Markdown `Exp30b Semantic Interference Isolation` 區塊。
- 每個 checkpoint 用 smoke clean cases 做 before/after semantic pass-rate delta，並輸出 interference matrix。
- 若偵測到 interference，promotion gate reason 追加 `semantic interference: ...`。

實跑：

- 結果目錄：`/home/s92137/chess_results/exp30b_semantic_interference_isolation`。
- Root verdict：`HIGH_RISK`。
- Promotion gate：`false`。
- total wall seconds：`138.717`。
- total checkpoint seconds：`78.741`。
- retrain seconds：`46.379`。
- deterministic eval seconds：`53.199`。
- semantic specialist probe seconds：`0.0`，因 smoke gate fail 正確跳過。
- skipped eval seconds estimate：`74.317`。

Distilled replay hygiene：

- raw replay rows：`100`。
- distilled replay rows：`93`。
- compression ratio：`0.93`。
- pre_filter_overlap_count：`6`。
- blocked_leakage_candidate_count：`6`。
- post-filter leakage_count：`0`。
- leakage_detected：`false`。
- held_out_in_training：`false`。
- distilled retrain seconds：`46.379`。
- previous retrain seconds：`45.539`。
- retrain_seconds_delta_vs_previous：`+0.84`。
- retrain_time_reduced：`false`。
- 解讀：semantic adapter / interference reporting 增加一點 retrain/eval 成本；蒸餾仍維持資料治理價值，但本輪不是 retrain time improvement。

Semantic adapter update evidence：

- `semantic_specific_adapters=true`。
- `semantic_head_update_count`：
  - `central_head=5708`。
  - `flank_head=3973`。
  - `development_head=444`。
  - `other_head=1696`。
- `semantic_loss_budget`：
  - `central_head=3526.45`。
  - `flank_head=2157.75`。
  - `development_head=247.05`。
  - `other_head=909.0`。
- `semantic_loss_budget_skew=true`，因 development budget 遠低於 central/flank，表示雖然有 adapter，訓練壓力仍不平衡。

Checkpoint semantic interference：

- cp10 model hash：`025d2a88... -> 0d33a639...`。
- cp10 mistake retention：`matched_expected=true`。
- cp10 before smoke pass rate：
  - `e_pawn=0/2`。
  - `d_pawn=0/2`。
  - `flank=0/2`。
  - `development=0/2`。
- cp10 after smoke pass rate：
  - `e_pawn=0/2`。
  - `d_pawn=1/2`。
  - `flank=0/2`。
  - `development=0/2`。
- cp10 interference reasons：`semantic_loss_budget_skew`。
- cp20 model hash：`0d33a639... -> 037b1e05...`。
- cp20 mistake retention：`repeated_old_mistake=false learning_signal`。
- cp20 before smoke pass rate：
  - `e_pawn=0/2`。
  - `d_pawn=1/2`。
  - `flank=0/2`。
  - `development=0/2`。
- cp20 after smoke pass rate：
  - `e_pawn=0/2`。
  - `d_pawn=0/2`。
  - `flank=1/2`。
  - `development=0/2`。
- cp20 deltas：
  - `d_pawn=-0.5`。
  - `flank=+0.5`。
  - `e_pawn=0.0`。
  - `development=0.0`。
- cp20 interference reasons：
  - `flank_update_caused_central_retention_drop`。
  - `semantic_loss_budget_skew`。

Interference matrix 判讀：

- exp30b 成功把 exp29 的現象量化：cp20 flank pass 從 `0/2` 到 `1/2`，同時 d-pawn central 從 `1/2` 掉到 `0/2`。
- 這不是 search override 的問題，而是 semantic update / loss budget 仍互相干擾。
- semantic adapter 已存在，但還不夠；原因是 adapter 層仍共享同一批 replay update pressure，且 loss budget 不平衡。
- `development_move` 仍 `0/2`，表示 development 雖已在 exp25 用 multi-good credit 修過 full gate 的公平性，但在 smoke adapter path 裡仍缺乏有效學習訊號。

Promotion gate 主要失敗原因：

- `catastrophic regression detected`。
- cp10/cp20 exact retention failed、seen retention below threshold、clean held-out below threshold。
- cp20 mistake retention repeated old mistake。
- full deterministic gate skipped after smoke gate failure。
- `semantic interference: flank_update_caused_central_retention_drop`。
- `semantic interference: semantic_loss_budget_skew`。
- engine verdict `HIGH_RISK`。

驗證：

- `python3 -m py_compile scripts/games/chess_live_learning_validation.py services/games/chess_dl.py` 通過。
- targeted exp30b tests：`3 passed in 1.06s`。
- `PYTHONPATH=/home/s92137/hackme_web python3 -m pytest tests/scripts/games/test_chess_live_learning_validation_script.py -q`：`41 passed in 471.43s`。
- `PYTHONPATH=/home/s92137/hackme_web python3 -m pytest tests/games -q`：`67 passed in 25.30s`。
- quick gate with semantic interference isolation 實跑完成。
- artifact consistency：`_report_consistency_issues(...) == []`。

經驗：

- exp30b 證明「加 adapter」本身不會自動解決 semantic interference；如果 loss budget / replay schedule 仍偏，flank 變強仍會打掉 central。
- 現在已經能具體量化「哪個 semantic update 影響哪個 semantic pass-rate」，這比 exp29 的整體 pass-rate regression 更可診斷。
- 下一步不應再盲目加 feature 或 hard negative，應該做 loss budget scheduler / semantic update freezing：
  - flank update 後 central smoke anchors 失敗時 rollback 或降低 flank budget。
  - cp10 已學到的 d-pawn anchor 進 cp20 前應被 retention anchor 保護。
  - development budget 不可長期低於 central/flank 一個數量級。
- Promotion gate 維持 false 是正確結果；exp30b 是診斷與隔離，不是 promotion 放行修正。

## Exp31 - Semantic Loss Budget Scheduler

日期：2026-05-11。

使用者目標：

- 修正 exp30b 已確認的 semantic interference：flank 更新能提升 flank，但會造成 e/d central retention regression。
- 保留 exp30a 的 distilled replay leakage guard、`held_out_in_training=false`、smoke gate early stop、evaluation cache key、semantic-specific adapters、balanced promotion gate。
- 不降低 promotion gate 門檻。
- 不把 `kingside_aggression` 放回 balanced hard gate。
- 不用 train/seen performance 當 promotion evidence。
- 不再只靠增加 flank loss 解問題。

要求：

- 新增 semantic loss budget：
  - `e_pawn_central_break`。
  - `d_pawn_central_break`。
  - `flank_pawn_push`。
  - `development_move`。
- 報告：
  - `loss_budget_by_semantic`。
  - `consumed_budget_by_semantic`。
  - `effective_gradient_norm_by_semantic`。
  - `update_count_by_semantic`。
  - `margin_delta_by_semantic`。
  - `semantic_loss_budget_skew`。
- 新增 retention-aware update scheduler：
  - 避免連續大量更新同一 semantic。
  - 交錯 central / flank / development / retention anchors。
  - flank update 後檢查 central anchors。
  - central update 後檢查 flank anchors。
- 新增 semantic rehearsal anchors：
  - e-pawn anchors。
  - d-pawn anchors。
  - flank anchors。
  - development anchors。
  - mistake retention anchors。
- 新增 rollback / dampening guard：
  - 若 semantic budget skew、central retention drop、mistake retention fail、hard-negative margin negative，必須在 report 中標記 rollback/dampening 狀態。
- 新增 shared trunk protection：
  - 比較 `adapters_only_update` 和 `low_lr_shared_trunk_adapter_updates` 的保護語義。
  - 本輪採用 `low_lr_shared_trunk_adapter_updates`，保留既有 policy-learning path，但將 trunk update 以 multiplier 降低到 `0.55`。
- 新增 gradient conflict diagnostics：
  - `gradient_conflict_matrix`。
  - `negative_cosine_like_conflict_count`。
  - `conflict_pair_examples`。

修改項目：

- `services/games/chess_dl.py`：
  - 新增 `_SEMANTIC_BUDGET_CLASSES`、`_SEMANTIC_SCHEDULER_ORDER`、budget skew limit、dampened weight。
  - 新增 `_sample_semantic_class()`，從 sample metadata 或 FEN/move 推導 semantic class。
  - 新增 `_semantic_interleaved_batch()`，將 replay batch 改成 semantic-interleaved schedule。
  - 新增 `_semantic_gradient_conflict_from_budgets()`，用 deterministic proxy 估計 semantic loss conflict。
  - `_train_from_replay()` 新增：
    - `semantic_loss_budget_scheduler=true`。
    - budget/consumed/effective gradient/update count/margin delta。
    - `update_schedule_trace`。
    - `anchor_check_after_each_semantic`。
    - `retention_delta_after_update`。
    - rollback/dampening metadata。
    - shared trunk protection metadata。
    - gradient conflict matrix。
  - training objective 改為 `contrastive_policy_ranking_with_flank_context_auxiliary_semantic_adapters_budget_scheduler`。
- `scripts/games/chess_live_learning_validation.py`：
  - 新增 `_semantic_loss_budget_scheduler_report()`。
  - 每個 checkpoint 寫入 `semantic_loss_budget_scheduler`。
  - root/engine summary 新增 `exp31_pipeline`。
  - promotion gate 若 exp31 偵測 semantic scheduler interference、budget skew、catastrophic semantic interference，必須加入 gate reasons。
  - Markdown SUMMARY 新增 `Exp31 Semantic Loss Budget Scheduler` 區塊。
  - artifact consistency check 新增 root/engine `exp31_pipeline` 一致性檢查。
- Tests：
  - 更新 exp29/exp3 trainer tests 以接受新 training objective。
  - 新增 exp31 scheduler report blocker test，驗證 budget skew / catastrophic semantic interference / rollback reason 可擋 promotion。

實跑：

- 結果目錄：`/home/s92137/chess_results/exp31_semantic_loss_budget_scheduler`。
- 扁平報告：
  - `docs/games/chess_debug/exp3/exp31_semantic_loss_budget_scheduler.md`。
- Root verdict：`HIGH_RISK`。
- Promotion gate：`false`。
- total wall seconds：`141.698`。
- total checkpoint seconds：`81.346`。
- retrain seconds：`49.323`。
- deterministic eval seconds：`53.449`。
- specialist probe seconds：`0.0`，因 smoke gate fail 正確跳過 full specialist。
- skipped eval seconds estimate：`76.962`。

Distilled replay hygiene：

- `held_out_in_training=false`。
- `leakage_detected=false`。
- `post_filter_leakage_count=0`。
- `blocked_leakage_candidate_count=6`。
- raw replay rows：`100`。
- distilled replay rows：`93`。
- compression ratio：`0.93`。
- 解讀：exp30a leakage guard 持續有效，distilled replay 可以作為訓練來源；promotion 仍只看 held-out deterministic evidence。

Timing / cache：

- previous total checkpoint seconds baseline：`1300.53`。
- exp30a total checkpoint seconds：`71.747`。
- exp30b total checkpoint seconds：`78.741`。
- exp31 total checkpoint seconds：`81.346`。
- cache hit ratio：`0.0`。
- 解讀：
  - exp31 比 exp30b 多約 `2.605s` checkpoint 成本，主要是新增 scheduler/report 統計，不是重回 1000 秒級 bottleneck。
  - 第一次跑同 model/case-set cache hit 仍是 `0.0` 合理。
  - 大幅省時仍主要來自 smoke gate early stop、full specialist probe skip、leakage pre-filter。

Exp31 budget scheduler evidence：

- `loss_budget_by_semantic`：
  - `e_pawn_central_break=192.0`。
  - `d_pawn_central_break=192.0`。
  - `flank_pawn_push=192.0`。
  - `development_move=192.0`。
  - `other=192.0`。
- `consumed_budget_by_semantic`：
  - `e_pawn_central_break=864.0`。
  - `d_pawn_central_break=820.8`。
  - `flank_pawn_push=820.8`。
  - `development_move=820.8`。
  - `other=820.8`。
- `effective_gradient_norm_by_semantic`：
  - `e_pawn_central_break=562.68`。
  - `d_pawn_central_break=538.92`。
  - `flank_pawn_push=538.92`。
  - `development_move=538.92`。
  - `other=538.92`。
- `update_count_by_semantic`：
  - `e_pawn_central_break=1440`。
  - `d_pawn_central_break=1368`。
  - `flank_pawn_push=1368`。
  - `development_move=1368`。
  - `other=1368`。
- `margin_delta_by_semantic`：
  - `e_pawn_central_break=40.8976`。
  - `d_pawn_central_break=19.6528`。
  - `flank_pawn_push=18.6344`。
  - `development_move=3.8879`。
  - `other=20.7146`。
- `semantic_loss_budget_skew=false`。
- `catastrophic_semantic_interference=false`。
- `negative_cosine_like_conflict_count=0`。
- `rollback_applied=false`。
- `dampened_semantics=["e_pawn_central_break"]`。

Update schedule / anchors：

- `update_schedule_trace` 已記錄 semantic interleaving。
- `anchor_check_after_each_semantic` 已記錄：
  - flank update 後 schedule `e_pawn_anchor`、`d_pawn_anchor`、`development_anchor`、`mistake_retention_anchor`。
  - central update 後 schedule `flank_anchor`、`development_anchor`、`mistake_retention_anchor`。
  - development update 後 schedule `e_pawn_anchor`、`d_pawn_anchor`、`flank_anchor`、`mistake_retention_anchor`。
- `retention_delta_after_update` 使用 margin delta proxy，checkpoint gate 仍負責真實 held-out/retention 判定。

Retention / semantic result：

- exp30b semantic interference 本輪為 `false`。
- cp10 central retention after flank updates：
  - `e_pawn=0.5`。
  - `d_pawn=0.5`。
  - `min_delta=0.5`。
- cp20 central retention after flank updates：
  - `e_pawn=0.5`。
  - `d_pawn=0.5`。
  - `min_delta=0.0`。
- flank retention after central updates：
  - cp10 `0.0`。
  - cp20 `0.0`。
- development retention after updates：
  - cp10 `0.0`。
  - cp20 `0.0`。
- mistake retention：
  - cp10：`matched_expected=true`，expected `e7e5`，before `b8a6`，after `e7e5`。
  - cp20：`matched_expected=false`，expected `a7a5`，before `f8a3`，after `f8a3`，`repeated_old_mistake`。

Promotion gate 主要失敗原因：

- `catastrophic regression detected`。
- cp10/cp20 exact retention failed。
- cp10/cp20 seen retention below threshold。
- cp10/cp20 clean held-out retention below threshold。
- cp10/cp20 clean held-out pool insufficient / hard clean missing。
- flank/development clean held-out pass count is zero。
- cp20 mistake retention repeated old mistake。
- smoke gate failed，full deterministic specialist probe skipped。
- `balanced_fusion final decision generalization below threshold`。
- `exp31 semantic scheduler: mistake_retention_failed`。
- engine verdict `HIGH_RISK`。

結果判讀：

- exp31 成功把 exp30b 的「budget skew + central/flank interference」壓下來：本輪 `semantic_loss_budget_skew=false`、`catastrophic_semantic_interference=false`、exp30b `interference=false`。
- 但是 promotion 仍正確維持 false，因為 scheduler 只解決「更新比例/互相覆蓋」的一部分，沒有解決：
  - flank/development smoke pass 仍為 0。
  - cp20 mistake retention 回到舊錯誤。
  - balanced full gate 因 smoke gate fail 沒有資格跑。
- 本輪最大價值是把 blocker 從「semantic update scheduling 明顯失衡」收斂到「retention anchor / semantic能力仍不足，尤其 cp20 mistake retention 和 flank/development smoke gate」。
- 不可把 `hash_changed`、budget balance、margin delta 上升當 learning success；promotion 仍只接受 held-out deterministic evidence 和 retention evidence。

適用 exp3/exp4：

- exp31 trainer 修改直接適用 exp3 DL trainer。
- exp4 仍共用 validation/report/gate surface；若 exp4 未使用 `services/games/chess_dl.py` 的 DL replay trainer，則 exp31 的 semantic budget scheduler 不會自動改善 exp4 模型，只會在報告欄位和 gate consistency 層面受益。
- 後續若要 exp4 等效，需要把 exp4 dataset trainer 接同一套 semantic budget / retention scheduler，或在 exp4 PV trainer 實作同等 update scheduling。

驗證：

- `python3 -m py_compile scripts/games/chess_live_learning_validation.py services/games/chess_dl.py`：通過。
- targeted tests：
  - `test_exp29_flank_context_feature_vector_and_trainer_auxiliary`。
  - `test_exp31_semantic_loss_budget_scheduler_report_blocks_interference`。
  - `test_experiment_dl_contrastive_replay_can_make_expected_raw_policy_top1`。
  - 結果：`3 passed in 0.85s`。
- quick deterministic gate：
  - `PYTHONPATH=/home/s92137/hackme_web python3 scripts/games/chess_live_learning_validation.py --engines exp3 --quick-retrain-gate --semantic-specialist-probes --seed 20260511 --quick-retrain-max-samples 220 --quick-retrain-max-seconds 120 --output-root /home/s92137/chess_results/exp31_semantic_loss_budget_scheduler`。
  - 完成，verdict `HIGH_RISK`，promotion gate `false`。

經驗：

- exp31 證明 budget scheduler 可以讓 semantic update distribution 變得更平衡，也能消除本輪 exp30b interference signal。
- 但「更新平衡」不等於「能力通過」；flank/development pass 仍未恢復，cp20 mistake retention 仍失敗。
- 下一步若繼續，應該聚焦：
  - cp20 mistake retention anchor 為何從 cp10 pass 變成 cp20 repeated old mistake。
  - flank/development smoke anchors 為何在 scheduler 後仍 0。
  - scheduler 的 rollback 目前只做 metadata/dampening，若要更強，需要實作真正 checkpoint-level rollback 或 per-semantic adapter snapshot restore。

## Exp32 - Smoke Anchor Calibration and Mistake Retention Repair

日期：2026-05-11。

使用者目標：

- exp31 已壓下 semantic budget skew 與 catastrophic central/flank interference，但 promotion 仍被 flank/development smoke gate 0/2 與 cp20 mistake retention failed 擋下。
- exp32 不降低 gate 門檻，不新增大型模型架構；先審計 smoke anchors、修正 development multi-good scoring 是否進 smoke gate，並加強 mistake retention rollback/rehearsal。

要求：

- 保留：
  - exp30a leakage guard。
  - smoke gate early stop。
  - evaluation cache key。
  - semantic-specific adapters。
  - exp31 semantic loss budget scheduler。
  - balanced promotion gate。
  - `kingside_aggression` 排除 balanced hard gate。
  - development multi-good credit。
- 不做：
  - 不降低 promotion gate 門檻。
  - 不把 kingside 放回 balanced hard gate。
  - 不用 train/seen performance 當 promotion evidence。
  - 不用 `hash_changed` / `replay_loss` 當 learning success。
- 新增：
  - smoke anchor audit table。
  - development smoke scoring alignment。
  - flank smoke anchor stratification。
  - scheduler budget calibration report。
  - cp20 mistake retention rehearsal。
  - smoke gate failed reason type。

修改項目：

- `scripts/games/chess_live_learning_validation.py`：
  - `_exp30a_smoke_gate_cases()` 改為每個 balanced semantic class 選 2 題：
    - 1 題 easy/medium representative。
    - 1 題 hard retention/contextual anchor。
  - `_position_set_performance()` 新增 `use_development_multi_good_credit`。
    - development case 不再只看 single expected top1。
    - 若 expected in top3 或 static-equivalent，依 multi-good rule 給 credit。
  - evaluator cache key 新增 `development_multi_good_credit`，避免沿用舊 smoke scoring cache。
  - `_evaluate_incremental_smoke_gate()` 使用 exp32 cache version：`exp32_smoke_anchor_calibration_v1`。
  - 新增 `_smoke_anchor_audit_report()`：
    - 每題輸出 case_id、semantic、difficulty、expected、legal、final_top1/top3、raw_top1/top3、expected_rank、static_best、static_cp_delta、search_best proxy、failure_reason。
    - failure reason 分類：
      - `passed`。
      - `raw_policy_fail`。
      - `anchor_too_hard_or_raw_policy_fail`。
      - `final_decision_blocked`。
      - `label_questionable`。
      - `multi_good_credit_missing`。
      - `scheduler_undertraining`。
  - 初版逐題跑 full decision breakdown 太慢，後改為 fast smoke audit：
    - 保留 raw/final/static/failure reason。
    - `search_best_move` 標記為 `balanced_final_top1_proxy_for_fast_smoke_audit`。
    - 避免每題額外跑昂貴 decision decomposition。
  - 新增 `_attempt_mistake_retention_repair()`：
    - 若 mistake probe 是 `repeated_old_mistake`，建立 `mistake_retention_rehearsal.jsonl`。
    - 用 expected move 當 positive，old mistake 作 hard negative。
    - 重新訓練 candidate checkpoint。
    - 立刻重跑 mistake retention probe。
  - rehearsal 初版 16 rows 仍失敗且較慢；改為 8 rows / max 16 samples，保留 blocker evidence 並降低成本。
  - root/engine summary 新增 `exp32_pipeline`。
  - Markdown SUMMARY 新增 `Exp32 Smoke Anchor Calibration` 區塊。
  - promotion gate 若 repair applied 但仍失敗，新增 reason：`exp32 mistake retention repair did not restore expected move`。
  - artifact consistency 新增 root/engine `exp32_pipeline` 一致性檢查。
- Tests：
  - 新增 `test_exp32_smoke_gate_cases_are_stratified`。
  - 新增 `test_exp32_development_multi_good_credit_can_lift_smoke_pass`。

實跑：

- 結果目錄：`/home/s92137/chess_results/exp32_smoke_anchor_calibration_mistake_retention_repair`。
- 扁平報告：
  - `docs/games/chess_debug/exp3/exp32_smoke_anchor_calibration_and_mistake_retention_repair.md`。
- Root verdict：`HIGH_RISK`。
- Promotion gate：`false`。
- total wall seconds：`166.423`。
- total checkpoint seconds：`107.404`。
- retrain seconds：`49.313`。
- deterministic eval seconds：`52.133`。
- specialist probe seconds：`0.0`，因 smoke gate fail 正確跳過。
- skipped eval seconds estimate：`102.879`。

Timing 判讀：

- exp28.5 baseline total checkpoint seconds：`1300.53`。
- exp30a：`71.747`。
- exp31：`81.346`。
- exp32 heavy audit 初跑：`146.758`。
- exp32 fast audit + 8-row rehearsal：`107.404`。
- 解讀：
  - exp32 比 exp31 慢，主要因新增 cp20 mistake-retention rehearsal。
  - fast audit 把 heavy per-case decision breakdown 的額外成本移除。
  - 最終仍略高於 100 秒級，但保留了 rehearsal evidence；若要嚴格壓回 <100 秒，下一步應把 rehearsal 改成 in-process adapter update 或只在 nightly 跑。

Smoke gate 結果：

- cp10 smoke final pass rate：`0.375`。
- cp20 smoke final pass rate：`0.375`。
- cp10 by semantic：
  - `e_pawn_central_break=0/2`。
  - `d_pawn_central_break=1/2`。
  - `flank_pawn_push=0/2`。
  - `development_move=2/2`。
- cp20 by semantic：
  - `e_pawn_central_break=0/2`。
  - `d_pawn_central_break=1/2`。
  - `flank_pawn_push=0/2`。
  - `development_move=2/2`。

Development multi-good credit：

- `development_multi_good_credit_applied=true`。
- cp10 development before credit：`0/2`。
- cp10 development after credit：`2/2`。
- cp20 development before credit：`0/2`。
- cp20 development after credit：`2/2`。
- 結論：
  - exp31 的 development 0/2 主要是 smoke scoring 問題，不是 development 完全不會。
  - exp32 修正後 development 不再是主要 blocker。

Flank smoke calibration：

- flank smoke difficulty distribution：
  - cp10：`easy=1, hard=1`。
  - cp20：`easy=1, hard=1`。
- contextual flank reason tags：
  - cp10：`space_gain=1, prophylaxis=1`。
  - cp20：`space_gain=1, prophylaxis=1`。
- flank pass：
  - cp10：`0/2`。
  - cp20：`0/2`。
- 結論：
  - flank 不是因為 smoke anchors 全是 hard contextual 而被誤殺；easy representative flank 也沒過。
  - flank 仍是模型能力 blocker。

Smoke anchor audit 範例：

- `gate_e_pawn_easy_001`：
  - expected `e2e4`。
  - final `d2d4`。
  - raw `d2d4`。
  - expected_rank `14`。
  - failure_reason `raw_policy_fail`。
- `gate_e_pawn_hard_001`：
  - expected `e7e5`。
  - final `d5c4`。
  - raw `c7c5`。
  - expected_rank `16`。
  - failure_reason `anchor_too_hard_or_raw_policy_fail`。
- `gate_d_pawn_easy_001`：
  - expected `d2d4`。
  - final `d2d4`。
  - raw `d2d4`。
  - failure_reason `passed`。
- `gate_flank_easy_001`：
  - expected `c2c4`。
  - final `d2d4`。
  - raw `d2d4`。
  - expected_rank `3`。
  - failure_reason `raw_policy_fail`。
- `gate_flank_hard_001`：
  - expected `c7c5`。
  - final `b7b5`。
  - raw `b7b5`。
  - expected_rank `6`。
  - failure_reason `anchor_too_hard_or_raw_policy_fail`。
- `gate_development_easy_001`：
  - expected `g1f3`。
  - final `d2d4`。
  - expected_rank `4`。
  - strict top1 fail，但 multi-good credit 後 pass。

Smoke failure classification：

- cp10 failure counts：
  - `passed=3`。
  - `raw_policy_fail=2`。
  - `anchor_too_hard_or_raw_policy_fail=3`。
- cp20 failure counts：
  - `passed=3`。
  - `raw_policy_fail=2`。
  - `anchor_too_hard_or_raw_policy_fail=3`。
- `smoke_gate_failed_reason_type=model_failure`。
- `model_failure_vs_gate_scoring_issue=model_failure`。
- 結論：
  - development scoring issue 已修。
  - 剩餘 smoke fail 不是 gate scoring issue，而是 raw policy / anchor difficulty 下的模型 failure。

Scheduler budget calibration：

- `consumed_budget_by_semantic`：
  - `e_pawn_central_break=864.0`。
  - `d_pawn_central_break=820.8`。
  - `flank_pawn_push=820.8`。
  - `development_move=820.8`。
  - `other=820.8`。
- `update_count_by_semantic`：
  - `e_pawn_central_break=1440`。
  - `d_pawn_central_break=1368`。
  - `flank_pawn_push=1368`。
  - `development_move=1368`。
  - `other=1368`。
- `semantic_loss_budget_skew=false`。
- `negative_cosine_like_conflict_count=0`。
- 結論：
  - flank/development 不是因為 budget 明顯偏低而 0/2。
  - 目前更像 supervised signal / representation / decision preference 沒有把 flank/e-pawn anchors 排上來。

Anchor pass delta：

- cp10：
  - `d_pawn_central_break=+0.5`。
  - `development_move=+0.5`。
  - `e_pawn_central_break=0.0`。
  - `flank_pawn_push=0.0`。
- cp20：
  - 全部 `0.0`。
- 結論：
  - cp10 有 d-pawn/development 改善。
  - cp20 沒有額外改善，且 mistake retention 失敗。

Mistake retention repair：

- cp10：
  - before `b8a6`。
  - after `e7e5`。
  - expected `e7e5`。
  - `matched_expected=true`。
- cp20 初始：
  - before `f8a3`。
  - after `f8a3`。
  - expected `a7a5`。
  - `repeated_old_mistake=true`。
- exp32 rehearsal：
  - `rehearsal_rows=8`。
  - `mistake_retention_anchor_weight=3.0`。
  - `rollback_or_rehearsal_applied=true`。
  - after rehearsal move：`f8a3`。
  - `repair_success=false`。
- 結論：
  - cp20 mistake retention 不是單純沒混入 anchor；小型 rehearsal 仍無法改變 final decision。
  - 這指出下一步應查該 case 的 raw policy / final decision path，或做真正 per-case adapter override/rollback，而不是再增加一般 replay。

Promotion gate 主要失敗原因：

- `catastrophic regression detected`。
- cp10/cp20 exact retention failed。
- cp10/cp20 seen retention below threshold。
- cp10/cp20 clean held-out retention below threshold。
- e-pawn/flank clean held-out pass count is zero。
- cp20 mistake retention repeated old mistake。
- full deterministic gate skipped after smoke gate fail。
- `exp31 semantic scheduler: central_retention_zero_after_semantic_updates`。
- `exp31 semantic scheduler: mistake_retention_failed`。
- `exp32 mistake retention repair did not restore expected move`。
- engine verdict `HIGH_RISK`。

結果判讀：

- exp32 成功修正 smoke gate 的 development multi-good scoring；development 從 strict `0/2` 變成 credited `2/2`。
- flank smoke anchor 已分層，確認 `0/2` 不是「兩題都太 hard」造成；easy flank 仍 raw_policy_fail。
- cp20 mistake-retention repair 已實作並實測，但 8-row rehearsal 仍失敗，final move 仍是 `f8a3`。
- promotion gate false 正確。
- 目前 blocker 已收斂為：
  - e-pawn smoke easy/hard raw policy fail。
  - flank smoke easy/hard raw policy fail。
  - cp20 mistake retention final decision 對 `a7a5` 學不動。

適用 exp3/exp4：

- exp32 的 smoke scoring / report / gate consistency 適用 exp3/exp4。
- mistake-retention rehearsal 對 exp3 直接走 `chess_exp3_dataset_train.py`；exp4 也有對應 `chess_exp4_dataset_train.py` path，但目前實跑與數據是 exp3。
- development multi-good credit 是 evaluator 層修正，因此 exp4 若跑 quick gate 也會受益。

驗證：

- `python3 -m py_compile scripts/games/chess_live_learning_validation.py services/games/chess_dl.py`：通過。
- targeted tests：
  - `test_exp32_smoke_gate_cases_are_stratified`。
  - `test_exp32_development_multi_good_credit_can_lift_smoke_pass`。
  - 結果：`2 passed in 0.32s`。
- quick deterministic gate：
  - `PYTHONPATH=/home/s92137/hackme_web python3 scripts/games/chess_live_learning_validation.py --engines exp3 --quick-retrain-gate --semantic-specialist-probes --seed 20260511 --quick-retrain-max-samples 220 --quick-retrain-max-seconds 120 --output-root /home/s92137/chess_results/exp32_smoke_anchor_calibration_mistake_retention_repair`。
  - 完成，verdict `HIGH_RISK`，promotion gate `false`。

經驗：

- 先修 smoke scoring 是必要的；否則 development 會被錯殺。
- 修完 smoke scoring 後，剩餘 failure 是真模型問題，不是 gate 誤判。
- 小型 rehearsal 對 cp20 mistake retention 無效，代表該 case 可能被 final decision/static/search path 或 move semantics bias 壓住。
- 下一步若繼續，不應再調 gate，而應針對：
  - `gate_e_pawn_easy_001` 為何 raw rank `14`。
  - `gate_flank_easy_001` 為何 raw top1 偏 `d2d4`，expected `c2c4` 只 rank `3`。
  - cp20 `a7a5` rehearsal 為何 raw rank/prob 沒轉成 final top1。

## Exp33 - Failed Smoke Anchor Microdiagnosis + Safe Checkpoint Retention

日期：2026-05-11。

前一輪問題：

- Exp32 已修正 development smoke scoring，development `0/2 -> 2/2`。
- 剩餘 blocker 是 e_pawn `0/2`、flank `0/2`、cp20 mistake retention repeated old mistake。
- exp33 目標不是 promotion，而是判斷 failed anchors 是單題學不會、mixed scheduler 學不起來、final decision 擋掉，或 dampening/budget 分配造成。

修改項目：

- `scripts/games/chess_live_learning_validation.py`：
  - smoke anchor audit 增加 `expected_raw_score`、`expected_final_score`、`failure_type`、decision-path 欄位。
  - 新增 `exp33_e_pawn_dampening_audit`。
  - 新增 failed e_pawn/flank smoke anchor isolated overfit probe。
  - mistake retention repair 強化為 exp33 stronger rehearsal：12 rows、weight 5.0、max samples 24。
  - 新增 `safe_checkpoint_selection`：
    - cp20 retention pass 才選 cp20。
    - cp20 fail 且 cp10 pass 則 final fallback cp10。
    - cp10/cp20 都 fail 則 no safe checkpoint。
  - final model path 改依 safe checkpoint selection，不再讓 known failed-retention cp20 自動成為 final。
- Tests：
  - 新增 safe checkpoint fallback 測試。
  - 新增 e_pawn dampening overapplied audit 測試。

實跑命令：

```bash
PYTHONPATH=/home/s92137/hackme_web python3 /home/s92137/hackme_web/scripts/games/chess_live_learning_validation.py --engines exp3 --quick-retrain-gate --semantic-specialist-probes --seed 20260511 --quick-retrain-max-samples 220 --quick-retrain-max-seconds 120 --output-root /home/s92137/chess_results/exp33_failed_smoke_anchor_microdiagnosis_safe_checkpoint_retention
```

實跑結果：

- 結果目錄：`/home/s92137/chess_results/exp33_failed_smoke_anchor_microdiagnosis_safe_checkpoint_retention`。
- 扁平報告：`docs/games/chess_debug/exp3/exp33_failed_smoke_anchor_microdiagnosis_safe_checkpoint_retention.md`。
- Verdict：`HIGH_RISK`。
- Promotion gate：`false`。
- total wall seconds：`211.779`。
- total checkpoint seconds：`149.043`。
- retrain seconds：`47.683`。
- deterministic eval seconds：`55.186`。
- specialist probe seconds：`0.0`，因 smoke gate fail 正確跳過。

Smoke gate：

- cp10：`0.375`。
  - e_pawn `0/2`。
  - d_pawn `1/2`。
  - flank `0/2`。
  - development `2/2`。
- cp20：`0.25`。
  - e_pawn `0/2`。
  - d_pawn `0/2`。
  - flank `0/2`。
  - development `2/2`。

e_pawn dampening audit：

- cp10：
  - update count `720`。
  - consumed budget `432.0`。
  - effective gradient norm `281.34`。
  - margin delta `29.2218`。
  - dampened semantic `e_pawn_central_break`。
  - `possibly_overapplied=false`。
- cp20：
  - update count `720`。
  - consumed budget `432.0`。
  - effective gradient norm `281.34`。
  - margin delta `11.6758`。
  - dampened semantic `e_pawn_central_break`。
  - `possibly_overapplied=false`。
- 判讀：目前沒有足夠證據說 e_pawn 0/2 是 dampening 過度造成；它比較像 mixed scheduler/decision path 問題。

Failed anchor isolated overfit：

- `gate_e_pawn_easy_001`：
  - isolated exact pass：`true`。
  - variant pass rate：`1.0`。
  - raw top1：`d2d4 -> e2e4`。
  - final top1：`d2d4 -> e2e4`。
  - 判讀：單題可學，mixed fail 偏 scheduler/interference/budget allocation。
- `gate_e_pawn_hard_001`：
  - isolated exact pass：`false`。
  - variant pass rate：`1.0`。
  - raw top1：`c7c5 -> e7e5`。
  - final top1：`d5c4 -> d5c4`。
  - 判讀：raw policy 會學，但 final decision 擋住。
- `gate_flank_easy_001`：
  - isolated exact pass：`true`。
  - variant pass rate：`0.75`。
  - raw top1：`d2d4/b1c3 -> c2c4`。
  - final top1：`d2d4/b1c3 -> c2c4`。
  - 判讀：單題可學，mixed fail 偏 scheduler/interference/budget allocation。
- `gate_flank_hard_001`：
  - isolated exact pass：`false`。
  - variant pass rate：`0.25`。
  - raw/final 仍偏 `b7b5`。
  - 判讀：hard flank 可能是 label/context/decision path 問題，不該只靠更多 rehearsal。

Mistake retention stronger repair：

- cp10：
  - `b8a6 -> e7e5`，expected `e7e5`。
  - retention pass。
- cp20：
  - before `f8a3`。
  - after `f8a3`。
  - expected `a7a5`。
  - stronger repair applied。
  - after repair 仍 `f8a3`。
  - `repair_success=false`。

Safe checkpoint selection：

- cp10 retention pass：`true`。
- cp20 retention pass：`false`。
- selected safe checkpoint：`cp10_fallback`。
- final model hash：`795597604ad8cabce2777b2c6c57c093860643f853717b8b8a35259710a2f46b`。
- 判讀：這是正確安全行為；promotion 仍 false，但 final artifact 不再指向已知 repeated-old-mistake 的 cp20。

結果判讀：

- exp33 有效，因為它將 e_pawn/flank fail 拆成兩類：
  - easy anchors：isolated 能學，mixed 失敗。
  - hard anchors：isolated 仍有 final decision 或 label/context 問題。
- cp20 不只 retention fail，還讓 smoke gate 從 `0.375` 降到 `0.25`，且 d_pawn 從 `1/2` 掉到 `0/2`；因此 cp20 fallback 被擋下是正確的。
- promotion false 正確。

後續方向：

- 針對 easy e_pawn/easy flank：修 mixed scheduler、semantic rehearsal 或 per-semantic update allocation。
- 針對 hard e_pawn：檢查 final decision path，因 raw policy 已能到 expected rank1 但 final 不採納。
- 針對 hard flank：重新做 label/context audit，確認它是否適合當 balanced hard gate target。
- 針對 cp20 retention：下一步不要再只加同型 rehearsal，應做 decision breakdown 或 rollback policy。

## Exp34 - Mixed Scheduler Repair + Hard Case Decision Audit

日期：2026-05-11。

前一輪問題：

- Exp33 證明 easy e-pawn / easy flank 單獨 isolated overfit 可以學會，但 mixed training 後失敗。
- hard e-pawn raw policy / final decision 需要拆開看，不能只用 final top1 當唯一診斷。
- hard flank isolated 也不穩，偏 label/context/decision path 問題。
- cp20 retention 在 exp33 fail，因此需要 safe checkpoint fallback；同時要檢查 retention expected move 是否有版本衝突。

修改項目：

- `scripts/games/chess_live_learning_validation.py`：
  - 新增 `exp34_retention_case_version_audit`，輸出 case_id、FEN、old mistake、expected move、source version。
  - 新增 `exp34_mixed_scheduler_repair`，對 isolated 可學但 mixed fail 的 easy e/flank anchors 做小型 mixed rehearsal。
  - 新增 hard e-pawn decision audit，輸出 raw/static/search/final score 與 blocker。
  - 新增 hard flank audit，輸出 reason tag、context features、static/search best、label quality。
  - 新增 smoke level report，把 foundation failure 與 hard generalization failure 分開。
  - 修正 full gate trigger：必須 exp34 smoke level 1 與 level 2 都過，才跑 full deterministic sanity gate。
  - 修正 exp32 repair summary：若最終 checkpoint probe 已 matched expected，不再讓舊 repair attempt 的 `repair_success=false` 形成矛盾。
- Tests：
  - 新增 retention version conflict 測試。
  - 新增 smoke level 分層測試。
  - 新增 hard flank questionable label quarantine 測試。

實跑命令：

```bash
PYTHONPATH=/home/s92137/hackme_web python3 scripts/games/chess_live_learning_validation.py --engines exp3 --quick-retrain-gate --semantic-specialist-probes --seed 20260511 --quick-retrain-max-samples 220 --quick-retrain-max-seconds 120 --output-root /home/s92137/chess_results/exp34_mixed_scheduler_repair_hard_case_decision_audit_fixed
```

第一次同實驗 run 曾用 `/home/s92137/chess_results/exp34_mixed_scheduler_repair_hard_case_decision_audit`，但因舊 trigger 直接啟動 full sanity gate，超過時間目標後中止；已合併記錄於扁平 exp34 報告。

實跑結果：

- 結果目錄：`/home/s92137/chess_results/exp34_mixed_scheduler_repair_hard_case_decision_audit_fixed`。
- 扁平報告：`docs/games/chess_debug/exp3/exp34_mixed_scheduler_repair_hard_case_decision_audit.md`。
- Verdict：`HIGH_RISK`。
- Promotion gate：`false`。
- total wall seconds：`428.454`。
- total checkpoint seconds：`229.8`。
- retrain seconds：`49.143`。
- deterministic eval seconds：`53.031`。
- semantic specialist probe seconds：`118.662`。
- artifact consistency：`_report_consistency_issues(...) == []`。

Smoke level：

- cp10：
  - level 1 failed：`easy_e_pawn_failed`, `easy_flank_failed`。
  - level 2 failed：`hard_e_pawn_failed`, `hard_flank_failed`。
  - classification：`foundation_fail`。
- cp20：
  - level 1 failed：`easy_flank_failed`。
  - level 2 failed：`hard_e_pawn_failed`, `hard_flank_failed`。
  - classification：`foundation_fail`。

Mixed rehearsal 結果：

- cp10：
  - e_pawn `0/2 -> 0/2`。
  - d_pawn `1/2 -> 2/2`。
  - flank `0/2 -> 0/2`。
  - development `2/2 -> 2/2`。
- cp20：
  - e_pawn `0/2 -> 1/2`。
  - d_pawn `1/2 -> 1/2`。
  - flank `0/2 -> 0/2`。
  - development `2/2 -> 2/2`。

Mistake retention：

- cp10：`b8a6 -> e7e5`，expected `e7e5`，matched expected。
- cp20：`f8a3 -> a7a5`，expected `a7a5`，matched expected。
- selected safe checkpoint：`cp20`。
- cp20 rejected by retention：`false`。
- retention label version conflict：`false`。

Hard case audit：

- hard e-pawn：
  - cp10 expected `e7e5`，raw top1 `c7c5`，final top1 `d5c4`，expected rank `14`，blocker `final_decision_blocked_by_search`。
  - cp20 expected `e7e5`，raw top1 `c7c5`，final top1 `d5c4`，expected rank `15`，blocker `raw_policy_or_label_unresolved`。
- hard flank：
  - expected `c7c5`，raw/final top1 都是 `b7b5`。
  - expected rank `6`。
  - reason_tag `prophylaxis`。
  - label_quality `questionable_hard_flank_label`。
  - 不可作 promotion hard evidence。

Semantic specialist probes：

- diagnosis：`specialist_capability_or_label_design_failure`。
- central_can_learn_alone：`true`。
- flank_can_learn_alone：`false`。
- contextual_flank_can_learn_alone：`false`。
- development_can_learn_alone：`true`。
- kingside_can_learn_alone：`false`。

結果判讀：

- Exp34 有效，因為它修正了 cp20 retention，並證明 safe checkpoint 可以選 cp20。
- Exp34 沒有讓 promotion 通過，這是合理的。
- easy e-pawn 在 cp20 mixed rehearsal 有局部改善，但 flank 仍完全沒有站起來。
- hard flank 被 quarantine，代表目前 flank hard gate 題目本身還不能當乾淨 promotion evidence。
- hard e-pawn 在 mixed checkpoint 中 raw policy 仍沒有穩定把 expected move 排上來，所以目前不該調 fusion 門檻硬放行。
- 模型尚未完成學習要求的主要原因不是「不會任何東西」，而是：
  - mixed scheduler 只能局部修 e-pawn。
  - flank semantic 邊界仍不乾淨。
  - hard flank label/context 需要重審。
  - central/flank interference 還有殘留。

後續方向：

- 先 quarantine / 重建 hard flank gate cases，不要再讓 questionable hard flank 擋 balanced promotion。
- 對 easy flank 做更小、更聚焦的 rehearsal 或 specialist adapter，不要同時牽動 central。
- hard e-pawn 先修 raw policy rank；raw rank 未穩定前，不應調 final decision fusion。
- 若要維持 100~150 秒日常 quick gate，`--semantic-specialist-probes` 應改成診斷模式，不應每次日常 gate 都跑。

適用 exp3/exp4：

- 本輪實跑是 exp3。
- retention version audit、smoke level report、hard case decision audit 屬於 validation/report 層，適用 exp3/exp4。
- mixed rehearsal path 已有 exp3 DL 與 exp4 PV 分支，但 exp4 尚未實跑。

## Architecture Split：exp3 / exp4 / exp5 路線調整

日期：2026-05-11

背景：

- exp1-34 已證明目前主要 blocker 不是單純測試或 gate，而是模型路線本身：小型 MLP + 搜尋很難穩定學出泛化棋理。
- exp3/exp4 目前可作為治理 pipeline、deterministic gate、debug instrumentation 的承載層，但不應再被誤認為現代西洋棋最常用的最終神經網路架構。
- 工程上需要把「輕量 baseline」、「Policy/Value + MCTS」、「NNUE + alpha-beta/PVS」拆開，避免所有實驗混成同一條不清楚的路。

本輪決策：

- exp3 保留為 lightweight DL baseline，用來驗證 replay、gate、報告、promotion evidence chain。
- exp4 轉向 Policy/Value + MCTS 路線，保留現有 alpha-beta fallback，不一次替換所有決策邏輯。
- 新增 exp5：NNUE-like evaluator + alpha-beta/PVS 路線，先作為可選引擎與 warm-start artifact，不直接混入 exp3/4 retrain gate。
- deterministic promotion gate 仍然維持，不因新增架構而降低驗收標準。

修改項目：

- 新增 `services/games/chess_nnue.py`：
  - difficulty：`experiment 5:nnue`。
  - model：`chess_experiment_5_nnue.json`。
  - architecture：`nnue-like-sparse-accumulator-v1`。
  - 搜尋：沿用 shared alpha-beta stack，使用 NNUE-like sparse evaluator。
  - 說明：這不是 Stockfish 相容 NNUE，而是 repo 內可演進的 NNUE-like 路線起點。
- 修改 `services/games/chess_pv.py`：
  - exp4 增加 deterministic root MCTS/PUCT decision mode。
  - 保留 alpha-beta 模式作 fallback。
  - 前台 exp4 呼叫改走 `decision_mode="mcts"`。
- 修改 `routes/games.py`：
  - `COMPUTER_DIFFICULTIES` 加入 `experiment 5:nnue`。
  - practice/catalog/schema CHECK constraints 加入 exp5。
  - catalog 顯示：
    - exp4：`實驗 4：Policy/Value + MCTS`
    - exp5：`實驗 5：NNUE + AlphaBeta/PVS`
- 修改 `services/games/chess_promotion.py`：
  - warm-start inventory 加入 exp5。
  - candidate staging 支援 exp5 檔案。
- 修改前台：
  - practice 難度選單加入 exp5。
  - root candidate engine 選單加入 exp5。
  - exp4 標題改成 Policy/Value + MCTS，避免再被看成一般 PV evaluator。
- 修改測試：
  - catalog expected difficulty list 加入 exp5。
  - practice 建局測試加入 exp5。
  - frontend asset test 加入 exp5 文字與 label。
  - warm-start dashboard inventory 檢查 exp5。

目前實際結果：

- `python3 -m py_compile services/games/chess_nnue.py services/games/chess_pv.py routes/games.py services/games/chess_promotion.py` 通過。
- exp4 MCTS smoke move 可產生合法 move。
- exp5 NNUE-like smoke move 可產生合法 move。
- exp5 已可進入前台選單、API catalog、warm-start inventory 與 promotion candidate inventory。

結果判讀：

- 這輪不是 promotion strength breakthrough，而是架構分流。
- exp3 不再承擔「最終棋力模型」期待；它更適合當治理與快速實驗 baseline。
- exp4 開始承擔 Policy/Value + MCTS 路線，但目前只是可用入口，還不是成熟 AlphaZero/Leela 類系統。
- exp5 開始承擔 NNUE + alpha-beta/PVS 路線，但目前是 NNUE-like skeleton，尚未有真正 large-scale feature transformer 與 PVS/LMR/null-move 等完整傳統引擎優化。
- 這樣做的價值是避免把 exp3 的 MLP learning failure 硬修成所有架構都共用的問題。

未來修正方向：

- exp4：
  - 把 deterministic strength snapshot 接到 Policy/Value + MCTS decision mode。
  - 補 MCTS visit/root policy/value debug。
  - 確認 tactic/blunder 不因 policy prior override 退步。
- exp5：
  - 補真正 NNUE feature accumulator。
  - 補 PVS、move ordering、history/countermove、LMR/null-move 等傳統搜尋優化。
  - 再建立 exp5 專用 deterministic gate，不直接沿用 exp3 的 semantic replay assumptions。
- governance：
  - exp3/exp4/exp5 的 promotion report 必須清楚寫明使用哪個 engine architecture。
  - 不可把 exp3 的 training success/failure 直接外推到 exp4/exp5。

適用 exp3/exp4：

- exp3：保留，主要用途是快速治理 baseline。
- exp4：本輪已套用 MCTS decision entry，但仍需後續實跑 gate。
- exp5：新路線，不屬於 exp3/4，但 future validation/report 層可共用 deterministic gate 原則。

## Exp3 Pause：暫停開發結論

日期：2026-05-11

結論：

- exp3 暫停開發。
- exp3 保留為 lightweight baseline、governance regression reference、deterministic gate/report 樣板。
- 後續棋力演進改走 exp4 `Policy/Value + MCTS` 與 exp5 `NNUE + AlphaBeta/PVS`。

暫停原因：

- exp3 已完成最重要的工程價值：把 replay validation、deterministic promotion gate、dataset integrity、leakage guard、mistake retention、semantic held-out、smoke gate、safe checkpoint selection、artifact consistency 這套可審計 pipeline 跑通。
- exp3 的棋力上限已經暴露：小型 MLP + alpha-beta 在 flank contextual learning、hard semantic generalization、mixed scheduler retention 上不穩。
- exp34 後 promotion 仍 false 是正確結果；硬調 gate 或繼續堆補丁會污染 evidence chain。
- 後續若要提升棋力，應切到更合理的架構，而不是繼續把 exp3 修成不是它原本設計能承擔的系統。

後續文件位置：

- exp3 歷史與暫停結論：`docs/games/chess_debug/exp3/`
- exp4 後續演進：`docs/games/chess_debug/exp4/`
- exp5 後續演進：`docs/games/chess_debug/exp5/`

## Exp3 Closeout：預設模型替換與 auto-retrain 串接驗證

日期：2026-05-11

目標：

- 將 exp34 checkpoint@20 固定為 exp3 runtime production final baseline。
- bundled seed 不隨 autoretrain 改變；但發佈用 warm-up seed 需採用目前最佳 exp3 closeout 模型。
- 確認前台選擇 `experiment 3:dl` 時後端走 exp3 model path。
- 確認有效 user game 會進 trusted replay。
- 確認達 retrain 門檻會啟動 candidate pipeline。
- 確認 retrain 完成與 promotion 前 production model 不被覆蓋。

實際結果：

- bundled seed 保持為初始 warm-start seed，不隨 autoretrain 改變；本次已改為 exp34 closeout 最佳模型。
- bundled seed hash：`333ed8e72524836d39851b74f4c209c6e08f2652720cacf36a13aa2ac8448dee`。
- 目前 repo runtime production model `runtime/games/models/chess_experiment_3_dl.json` 已替換為 exp34 checkpoint@20。
- runtime production hash：`333ed8e72524836d39851b74f4c209c6e08f2652720cacf36a13aa2ac8448dee`。
- isolated runtime warm-start 後，runtime exp3 model 會先由 bundled seed 建立；autoretrain/promotion 後應只替換 runtime。
- API 建立 `experiment 3:dl` practice 成功，match 中 `computer_difficulty=experiment 3:dl`，電腦初始走法由 exp3 path 產生。
- resign 後 replay ledger 產生 1 筆 trusted replay：`engine_name=experiment 3:dl`、`move_count=9`、`source=user_games`。
- default threshold 25 時，usable=1 不會啟動 autorun。
- threshold=1 測試時，autorun 啟動 `chess_train_pipeline.py --promote-engines 'experiment 3:dl' --skip-exp1-refine --skip-exp4 --skip-exp5`。
- candidate model 寫入 `runtime/games/models/candidates/runs/pipeline_20260511T055557Z/chess_experiment_3_dl.json`，hash `5174785e683b77b84ae6397c533d98507853bb685a932fa22a7f09f7f10ab9f0`。
- production runtime model hash 前後維持 `333ed8e72524836d39851b74f4c209c6e08f2652720cacf36a13aa2ac8448dee`。
- isolated autorun 測試使用 `--skip-promote`，因此沒有自動替換 production；正式收尾已手動固定 repo runtime production model。bundle 不應由 retrain 改寫。

結果判讀：

- exp3 模型檔替換、前後端串接、trusted replay 收集、retrain 門檻觸發、candidate/production 隔離均已確認。
- retrain 期間前台仍讀 production runtime model，candidate 未 promotion 前不會覆蓋 production。
- 但 production autorun 目前仍走 full `chess_train_pipeline.py`，不是 exp30a/exp34 quick deterministic balanced gate。
- 若要求「棋力進步才替換」嚴格等同 exp34 deterministic gate，還需要把 deterministic gate / mistake retention / safe checkpoint selection 接到 production promotion decision。

詳細報告：

- `docs/games/chess_debug/exp3/exp3_closeout_model_autoretrain_verification.md`
