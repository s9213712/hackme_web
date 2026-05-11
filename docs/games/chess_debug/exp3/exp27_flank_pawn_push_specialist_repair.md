# EXP27 - Flank Pawn Push Specialist Repair

## 前一個實驗暴露的問題
Exp26 改善 e/d central 與 development retention，但 flank_pawn_push 仍不足。

## 實驗目標與要求
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

## 實驗命令完整全文
legacy `summary.json` 未保存原始 argv；以下為依 artifact output_root、engine 與模式重建的完整命令。若同一 exp 有多次 rerun，全部合併列在本報告。
### exp27_flank_pawn_push_specialist_repair
```bash
PYTHONPATH=/home/s92137/hackme_web python3 /home/s92137/hackme_web/scripts/games/chess_live_learning_validation.py --engines exp2 --semantic-specialist-probes --output-root /home/s92137/chess_results/exp27_flank_pawn_push_specialist_repair
```

## 分析及修改項目
詳細內容保留在上方原始 ledger 段落；同一 exp 的多次 rerun 已合併在本報告，不再保存多個 run 資料夾。

## 修改後實際結果
| Run | Engine | Verdict | Promotion | Retrain s | Wall s | Eval s | Checkpoint s | Deterministic gate | Leakage | Smoke | Mistake repair |
| --- | --- | --- | --- | ---: | ---: | ---: | ---: | --- | --- | --- | --- |
| exp27_flank_pawn_push_specialist_repair | - | HIGH_RISK | - | 44.623 | - | - | 1375.045 | true | - | - | - |

最後一次 run 原始結果目錄：`/home/s92137/chess_results/exp27_flank_pawn_push_specialist_repair`。

## 結果判讀
最後一次 run verdict=`HIGH_RISK`，promotion=`-`。若 promotion=false，代表 gate 沒有因單一改善指標而誤放。

## 未來修正方向
下一步已由後續 exp 承接；不要降低 promotion gate，應修正被 gate 擋下的模型、資料或評分根因。

## 適用 exp3 / exp4
主要落在 exp3 DL quick-gate/trainer；exp4 使用共用 validation/report surface，若無專門 artifact 則視為部分適用。
