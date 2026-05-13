# EXP30 - Distilled Replay Hygiene + Semantic Interference Isolation

## 前一個實驗暴露的問題
Exp29 證明 flank feature injection 有效，但出現 held-out leakage 與 central semantic regression，需分成 hygiene/cache 與 interference isolation。

## 實驗目標與要求
### Exp30a 原始紀錄

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

- 結果目錄：`<chess_results>/exp30a_distilled_replay_leakage_fix_evaluation_cache`。
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
- `PYTHONPATH=<repo> python3 -m pytest tests/scripts/games/test_chess_live_learning_validation_script.py -q`：`40 passed in 488.30s`。
- `PYTHONPATH=<repo> python3 -m pytest tests/games -q`：`67 passed in 23.48s`。
- quick gate with distilled replay hygiene 實跑完成。
- artifact consistency：`_report_consistency_issues(...) == []`。
- `git diff --check` 通過。

經驗：

- exp30a 明確分離了兩件事：pre-filter overlap 是 blocked candidate；post-filter leakage 才是 promotion blocker。
- 這修掉了 exp28.5/exp29 的硬 blocker：本輪 `held_out_in_training=false` 且 `leakage_detected=false`。
- 但 promotion 仍正確 false，因為 smoke gate 與 mistake retention 已足夠證明模型不該進 full promotion gate。
- 現在 pipeline 可以在早期失敗時從 1000+ 秒降到約 130 秒，避免每次都跑完整 specialist probes。
- 下一步模型線應做 exp30b：semantic interference isolation。exp29 已證明 flank 可以被學起來，但會覆蓋 central；exp30a 只是讓這種失敗更快、更乾淨地被擋下。

### Exp30b 原始紀錄

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

- 結果目錄：`<chess_results>/exp30b_semantic_interference_isolation`。
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
- `PYTHONPATH=<repo> python3 -m pytest tests/scripts/games/test_chess_live_learning_validation_script.py -q`：`41 passed in 471.43s`。
- `PYTHONPATH=<repo> python3 -m pytest tests/games -q`：`67 passed in 25.30s`。
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

## 實驗命令完整全文
legacy `summary.json` 未保存原始 argv；以下為依 artifact output_root、engine 與模式重建的完整命令。若同一 exp 有多次 rerun，全部合併列在本報告。
### exp30a_distilled_replay_leakage_fix_evaluation_cache
```bash
PYTHONPATH=<repo> python3 <repo>/scripts/games/chess_live_learning_validation.py --engines exp3 --quick-retrain-gate --output-root <chess_results>/exp30a_distilled_replay_leakage_fix_evaluation_cache
```
### exp30b_semantic_interference_isolation
```bash
PYTHONPATH=<repo> python3 <repo>/scripts/games/chess_live_learning_validation.py --engines exp3 --quick-retrain-gate --semantic-specialist-probes --output-root <chess_results>/exp30b_semantic_interference_isolation
```

## 分析及修改項目
詳細內容保留在上方原始 ledger 段落；同一 exp 的多次 rerun 已合併在本報告，不再保存多個 run 資料夾。

## 修改後實際結果
| Run | Engine | Verdict | Promotion | Retrain s | Wall s | Eval s | Checkpoint s | Deterministic gate | Leakage | Smoke | Mistake repair |
| --- | --- | --- | --- | ---: | ---: | ---: | ---: | --- | --- | --- | --- |
| exp30a_distilled_replay_leakage_fix_evaluation_cache | - | HIGH_RISK | - | 44.407 | - | - | 71.747 | true | false | - | - |
| exp30b_semantic_interference_isolation | - | HIGH_RISK | - | 46.379 | - | - | 78.741 | true | false | - | - |

最後一次 run 原始結果目錄：`<chess_results>/exp30b_semantic_interference_isolation`。

## 結果判讀
最後一次 run verdict=`HIGH_RISK`，promotion=`-`。若 promotion=false，代表 gate 沒有因單一改善指標而誤放。
Exp30a 處理 distilled replay leakage、evaluation cache 與 smoke early stop；它解決的是資料可信度與驗收耗時。
Exp30b 處理 semantic interference isolation；它證明 adapters alone 不足，後續需要 scheduler/loss budget。

## 未來修正方向
下一步已由後續 exp 承接；不要降低 promotion gate，應修正被 gate 擋下的模型、資料或評分根因。

## 適用 exp3 / exp4
主要落在 exp3 DL quick-gate/trainer；exp4 使用共用 validation/report surface，若無專門 artifact 則視為部分適用。
