# EXP31 - Semantic Loss Budget Scheduler

## 前一個實驗暴露的問題
Exp30b 證明 adapters alone 不夠，真正 blocker 是 semantic update scheduling 與 loss budget。

## 實驗目標與要求
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

## 實驗命令完整全文
legacy `summary.json` 未保存原始 argv；以下為依 artifact output_root、engine 與模式重建的完整命令。若同一 exp 有多次 rerun，全部合併列在本報告。
### exp31_semantic_loss_budget_scheduler
```bash
PYTHONPATH=/home/s92137/hackme_web python3 /home/s92137/hackme_web/scripts/games/chess_live_learning_validation.py --engines exp3 --quick-retrain-gate --semantic-specialist-probes --output-root /home/s92137/chess_results/exp31_semantic_loss_budget_scheduler
```

## 分析及修改項目
詳細內容保留在上方原始 ledger 段落；同一 exp 的多次 rerun 已合併在本報告，不再保存多個 run 資料夾。

## 修改後實際結果
| Run | Engine | Verdict | Promotion | Retrain s | Wall s | Eval s | Checkpoint s | Deterministic gate | Leakage | Smoke | Mistake repair |
| --- | --- | --- | --- | ---: | ---: | ---: | ---: | --- | --- | --- | --- |
| exp31_semantic_loss_budget_scheduler | - | HIGH_RISK | - | 49.323 | - | - | 81.346 | true | false | - | - |

最後一次 run 原始結果目錄：`/home/s92137/chess_results/exp31_semantic_loss_budget_scheduler`。

## 結果判讀
最後一次 run verdict=`HIGH_RISK`，promotion=`-`。若 promotion=false，代表 gate 沒有因單一改善指標而誤放。

## 未來修正方向
下一步已由後續 exp 承接；不要降低 promotion gate，應修正被 gate 擋下的模型、資料或評分根因。

## 適用 exp3 / exp4
主要落在 exp3 DL quick-gate/trainer；exp4 使用共用 validation/report surface，若無專門 artifact 則視為部分適用。
