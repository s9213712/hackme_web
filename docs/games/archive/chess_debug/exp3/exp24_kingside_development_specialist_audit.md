# EXP24 - Kingside / Development Specialist Audit

## 前一個實驗暴露的問題
Exp23 顯示 kingside/development specialist 本身需要重審，不是單純 sampling 或 interference。

## 實驗目標與要求
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

- 實跑目錄：`<chess_results>/exp24_kingside_development_audit`。
- 主要 artifact：`<chess_results>/exp24_kingside_development_audit/exp3/kingside_development_audit.json`。
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

## 實驗命令完整全文
legacy `summary.json` 未保存原始 argv；以下為依 artifact output_root、engine 與模式重建的完整命令。若同一 exp 有多次 rerun，全部合併列在本報告。
### exp24_kingside_development_audit
```bash
PYTHONPATH=<repo> python3 <repo>/scripts/games/chess_live_learning_validation.py --engines exp2 --semantic-specialist-probes --output-root <chess_results>/exp24_kingside_development_audit
```

## 分析及修改項目
詳細內容保留在上方原始 ledger 段落；同一 exp 的多次 rerun 已合併在本報告，不再保存多個 run 資料夾。

## 修改後實際結果
| Run | Engine | Verdict | Promotion | Retrain s | Wall s | Eval s | Checkpoint s | Deterministic gate | Leakage | Smoke | Mistake repair |
| --- | --- | --- | --- | ---: | ---: | ---: | ---: | --- | --- | --- | --- |
| exp24_kingside_development_audit | - | HIGH_RISK | - | 44.162 | - | - | 882.476 | true | - | - | - |

最後一次 run 原始結果目錄：`<chess_results>/exp24_kingside_development_audit`。

## 結果判讀
最後一次 run verdict=`HIGH_RISK`，promotion=`-`。若 promotion=false，代表 gate 沒有因單一改善指標而誤放。

## 未來修正方向
下一步已由後續 exp 承接；不要降低 promotion gate，應修正被 gate 擋下的模型、資料或評分根因。

## 適用 exp3 / exp4
主要落在 exp3 DL quick-gate/trainer；exp4 使用共用 validation/report surface，若無專門 artifact 則視為部分適用。
