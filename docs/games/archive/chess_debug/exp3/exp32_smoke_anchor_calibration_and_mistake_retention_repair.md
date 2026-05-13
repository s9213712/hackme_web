# EXP32 - Smoke Anchor Calibration and Mistake Retention Repair

## 前一個實驗暴露的問題
Exp31 壓下 semantic interference，但 smoke flank/development 與 cp20 mistake retention 仍不穩。

## 實驗目標與要求
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

- 結果目錄：`<chess_results>/exp32_smoke_anchor_calibration_mistake_retention_repair`。
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
  - `PYTHONPATH=<repo> python3 scripts/games/chess_live_learning_validation.py --engines exp3 --quick-retrain-gate --semantic-specialist-probes --seed 20260511 --quick-retrain-max-samples 220 --quick-retrain-max-seconds 120 --output-root <chess_results>/exp32_smoke_anchor_calibration_mistake_retention_repair`。
  - 完成，verdict `HIGH_RISK`，promotion gate `false`。

經驗：

- 先修 smoke scoring 是必要的；否則 development 會被錯殺。
- 修完 smoke scoring 後，剩餘 failure 是真模型問題，不是 gate 誤判。
- 小型 rehearsal 對 cp20 mistake retention 無效，代表該 case 可能被 final decision/static/search path 或 move semantics bias 壓住。
- 下一步若繼續，不應再調 gate，而應針對：
  - `gate_e_pawn_easy_001` 為何 raw rank `14`。
  - `gate_flank_easy_001` 為何 raw top1 偏 `d2d4`，expected `c2c4` 只 rank `3`。
  - cp20 `a7a5` rehearsal 為何 raw rank/prob 沒轉成 final top1。

## 實驗命令完整全文
legacy `summary.json` 未保存原始 argv；以下為依 artifact output_root、engine 與模式重建的完整命令。若同一 exp 有多次 rerun，全部合併列在本報告。
### exp32_smoke_anchor_calibration_mistake_retention_repair
```bash
PYTHONPATH=<repo> python3 <repo>/scripts/games/chess_live_learning_validation.py --engines exp3 --quick-retrain-gate --semantic-specialist-probes --seed 20260511 --quick-retrain-max-samples 220 --quick-retrain-max-seconds 120 --output-root <chess_results>/exp32_smoke_anchor_calibration_mistake_retention_repair
```

## 分析及修改項目
詳細內容保留在上方原始 ledger 段落；同一 exp 的多次 rerun 已合併在本報告，不再保存多個 run 資料夾。

## 修改後實際結果
| Run | Engine | Verdict | Promotion | Retrain s | Wall s | Eval s | Checkpoint s | Deterministic gate | Leakage | Smoke | Mistake repair |
| --- | --- | --- | --- | ---: | ---: | ---: | ---: | --- | --- | --- | --- |
| exp32_smoke_anchor_calibration_mistake_retention_repair | - | HIGH_RISK | - | 49.313 | - | - | 107.404 | true | false | - | - |

最後一次 run 原始結果目錄：`<chess_results>/exp32_smoke_anchor_calibration_mistake_retention_repair`。

## 結果判讀
最後一次 run verdict=`HIGH_RISK`，promotion=`-`。若 promotion=false，代表 gate 沒有因單一改善指標而誤放。
Development smoke scoring 修正有效：strict 0/2 經 multi-good credit 後為 2/2；剩餘 e_pawn/flank 與 cp20 mistake retention 是模型/訓練問題。

## 未來修正方向
下一步應聚焦 e_pawn/flank smoke anchor raw policy 學習，以及 cp20 mistake retention rehearsal 為何無法壓掉 f8a3 舊錯；不要降低 gate。

## 適用 exp3 / exp4
主要落在 exp3 DL quick-gate/trainer；exp4 使用共用 validation/report surface，若無專門 artifact 則視為部分適用。
