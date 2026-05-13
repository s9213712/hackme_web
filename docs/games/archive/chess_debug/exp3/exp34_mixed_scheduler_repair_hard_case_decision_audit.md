# EXP34 - Mixed Scheduler Repair + Hard Case Decision Audit

## 前一個實驗暴露的問題

Exp33 把 smoke failure 拆得更細，結論是：

- easy e-pawn / easy flank 單獨 isolated overfit 可以學會，但 mixed training 後仍失敗。
- hard e-pawn isolated 時 raw policy 可以被推動，但 final decision 仍可能被 search/static path 擋住。
- hard flank isolated 也學不動，偏 label/context/decision path 問題。
- cp20 mistake retention 在 exp33 仍 repeated old mistake，因此當時只能 fallback 到 cp10。

這表示問題不是單純「模型完全不能學」，而是：

- mixed scheduler 沒保住 isolated 可學的 easy anchor。
- hard case 需要拆成 raw policy failure、final decision blocker、或 label questionable。
- retention checkpoint 必須有版本審計與 safe checkpoint selection，不能讓壞掉的 cp20 成為 final。

## 實驗目標與要求

Exp34 目標不是降低 gate，而是讓 smoke failure 可定位、讓 hard case 可審計、讓 cp20 retention 不可信時自動 fallback。

要求：

- 保留 exp30a leakage guard、evaluation cache、smoke early stop。
- 保留 exp31 semantic loss budget scheduler。
- 保留 exp32 development multi-good credit。
- 保留 exp33 safe checkpoint selection。
- 不降低 promotion gate 門檻。
- 不把 `kingside_aggression` 放回 balanced hard gate。
- 不用 train/seen performance、`hash_changed` 或 replay loss 宣稱 learning success。
- 對 retention case 做 version audit，避免同一 case 出現 `a5a4` / `a7a5` 這種 expected move 混亂。
- 對 easy e/flank 做 mixed rehearsal repair，但每次 repair 後仍要重跑 smoke。
- 對 hard e-pawn 輸出 final decision blocker breakdown。
- 對 hard flank 做 label/context audit；questionable hard flank 不可作 promotion hard evidence。
- smoke gate 分成 level 1 foundation 與 level 2 hard generalization。

## 實驗命令完整全文

第一次實跑命令：

```bash
PYTHONPATH=<repo> python3 scripts/games/chess_live_learning_validation.py --engines exp3 --quick-retrain-gate --semantic-specialist-probes --seed 20260511 --quick-retrain-max-samples 220 --quick-retrain-max-seconds 120 --output-root <chess_results>/exp34_mixed_scheduler_repair_hard_case_decision_audit
```

第一次 run 被中止，原因是 exp34 mixed rehearsal 後舊 trigger 只看 `smoke_gate.passed`，導致 smoke 一過門檻就啟動 full sanity gate，開始跑 144 seen + 126 unseen variants，quick gate 退化成重型驗收。

修正後實跑命令：

```bash
PYTHONPATH=<repo> python3 scripts/games/chess_live_learning_validation.py --engines exp3 --quick-retrain-gate --semantic-specialist-probes --seed 20260511 --quick-retrain-max-samples 220 --quick-retrain-max-seconds 120 --output-root <chess_results>/exp34_mixed_scheduler_repair_hard_case_decision_audit_fixed
```

## 分析及修改項目

- 新增 `_exp34_retention_case_version_audit`：
  - 記錄 `case_id`、FEN、old mistake、expected move、source experiment/version。
  - 若同一 retention case 出現多個 expected move，標 `retention_label_version_conflict=true`。
- 強化 safe checkpoint evidence：
  - report 明確輸出 `selected_safe_checkpoint`。
  - 若 cp20 retention fail，必須 fallback 或 no-safe-checkpoint。
- 新增 `_exp34_easy_mixed_rehearsal_repair`：
  - 對 isolated 可學但 mixed fail 的 easy e-pawn / flank anchors 加入小型 mixed rehearsal。
  - rehearsal schedule 固定為 central easy anchor、flank easy anchor、development anchor、mistake retention anchor、mixed semantic batch、retention check。
  - 輸出 before/after semantic pass delta。
- 新增 `_exp34_hard_case_decision_audits`：
  - hard e-pawn 輸出 raw score、static eval、search score、final score、selected move score、rejection reason。
  - hard flank 輸出 reason tag、context features、static/search best、label quality、capability gap。
- 新增 `_exp34_smoke_level_report`：
  - level 1：leakage、mistake retention、easy e-pawn、easy flank、development。
  - level 2：hard e-pawn、hard flank、semantic margin。
  - failure 分類為 `foundation_fail` 或 `hard_generalization_fail`。
- 修正 full gate trigger：
  - 不再只看 `smoke_gate.passed`。
  - 必須同時通過 exp34 smoke level 1 與 level 2 才跑 full deterministic sanity gate。
  - 若 hard generalization 未過，記錄 `exp34_smoke_level_gate_failed`，跳過 full gate。
- 修正 exp32 repair summary 語義：
  - 若後續 mixed repair 後最終 mistake retention probe 已 matched expected，不再把舊的 `repair_success=false` 當成最終 blocker。

## 修改後實際結果

結果目錄：

`<chess_results>/exp34_mixed_scheduler_repair_hard_case_decision_audit_fixed`

總體：

| 指標 | 結果 |
| --- | --- |
| verdict | `HIGH_RISK` |
| promotion_gate.passed | `false` |
| total_wall_seconds | `428.454` |
| total_checkpoint_seconds | `229.8` |
| retrain_seconds | `49.143` |
| deterministic_eval_seconds | `53.031` |
| semantic_specialist_probe_seconds | `118.662` |
| skipped_eval_seconds_estimate | `207.701` |

時間判讀：

- 修正 full gate trigger 後，沒有再跑 144/126 variants 的 full sanity gate。
- 但本輪仍比 exp31/32 慢，原因是：
  - 每個 checkpoint 都多了 isolated probes。
  - 每個 checkpoint 都跑 mixed easy-anchor rehearsal。
  - 命令包含 `--semantic-specialist-probes`，額外花 `118.662s`。
- checkpoint evaluation 仍比 exp28.5 的 `1300.53s` 快很多，但已超過 exp34 預期的 `100~150s`。

Smoke level 結果：

| Checkpoint | level 1 | level 1 reasons | level 2 | level 2 reasons | classification |
| --- | --- | --- | --- | --- | --- |
| cp10 | `false` | `easy_e_pawn_failed`, `easy_flank_failed` | `false` | `hard_e_pawn_failed`, `hard_flank_failed` | `foundation_fail` |
| cp20 | `false` | `easy_flank_failed` | `false` | `hard_e_pawn_failed`, `hard_flank_failed` | `foundation_fail` |

Mixed rehearsal before/after：

| Checkpoint | e_pawn | d_pawn | flank | development | 判讀 |
| --- | ---: | ---: | ---: | ---: | --- |
| cp10 before | `0/2` | `1/2` | `0/2` | `2/2` | e/flank foundation fail |
| cp10 after | `0/2` | `2/2` | `0/2` | `2/2` | d_pawn 改善，e/flank 無改善 |
| cp20 before | `0/2` | `1/2` | `0/2` | `2/2` | e/flank foundation fail |
| cp20 after | `1/2` | `1/2` | `0/2` | `2/2` | e_pawn 有改善，flank 仍 0 |

Mistake retention：

| Checkpoint | before | after | expected | result |
| --- | --- | --- | --- | --- |
| cp10 | `b8a6` | `e7e5` | `e7e5` | `matched_expected` |
| cp20 | `f8a3` | `a7a5` | `a7a5` | `matched_expected` |

Safe checkpoint：

| 欄位 | 結果 |
| --- | --- |
| cp10_retention_pass | `true` |
| cp20_retention_pass | `true` |
| cp20_rejected_by_retention | `false` |
| selected_safe_checkpoint | `cp20` |
| selected_model_hash | `333ed8e72524836d39851b74f4c209c6e08f2652720cacf36a13aa2ac8448dee` |

Retention case version audit：

| case_id | old_mistake | expected_move | result |
| --- | --- | --- | --- |
| `game:900001:ply:1:e7e5` | `b8a6` | `e7e5` | `matched_expected` |
| `game:900001:ply:3:a7a5` | `f8a3` | `a7a5` | `matched_expected` |

`retention_label_version_conflict=false`。本輪沒有發現同一 retention case expected move 版本衝突。

Hard e-pawn decision audit：

| Checkpoint | case | expected | raw_top1 | final_top1 | expected_rank | static_cp_delta | blocker |
| --- | --- | --- | --- | --- | ---: | ---: | --- |
| cp10 | `gate_e_pawn_hard_001` | `e7e5` | `c7c5` | `d5c4` | `14` | `-100` | `final_decision_blocked_by_search` |
| cp20 | `gate_e_pawn_hard_001` | `e7e5` | `c7c5` | `d5c4` | `15` | `-100` | `raw_policy_or_label_unresolved` |

判讀：

- hard e-pawn 在 mixed checkpoint 中 raw policy 沒把 expected move 排上來。
- final decision 也偏向 `d5c4`。
- `static_cp_delta=-100` 還在 clean gate 可接受範圍內，但不是強制優勢步；不應直接調低 search/static gate。

Hard flank audit：

| Checkpoint | expected | raw_top1 | final_top1 | expected_rank | reason_tag | label_quality |
| --- | --- | --- | --- | ---: | --- | --- |
| cp10 | `c7c5` | `b7b5` | `b7b5` | `6` | `prophylaxis` | `questionable_hard_flank_label` |
| cp20 | `c7c5` | `b7b5` | `b7b5` | `6` | `prophylaxis` | `questionable_hard_flank_label` |

判讀：

- hard flank expected `c7c5` 沒進 final top3，raw 也只排第 6。
- static/search 並未強烈支持 expected 成為唯一正解。
- 這題應 quarantine/audit，不可作 balanced promotion hard evidence。

Semantic specialist probes：

| Specialist | clean held-out | hard clean | 判讀 |
| --- | ---: | ---: | --- |
| central_break_only | `0.1111` | `0.0` | central 單類仍弱 |
| flank_only | `0.6` | `0.25` | flank 單類可學部分 easy/medium，但 hard 弱 |
| flank_only_contextual | `0.6` | `0.25` | context 有幫助但不足 |
| kingside_only | `0.0` | `0.0` | style 類不適合 balanced hard gate |
| development_only | `0.3333` | `0.0` | development multi-good scoring 仍比 strict top1 更合理 |

Specialist diagnosis：

`specialist_capability_or_label_design_failure`

## 結果判讀

Exp34 有效，但沒有讓模型通過 promotion。

已改善：

- cp20 mistake retention 從 exp33 的 repeated old mistake 變成本輪 `matched_expected`。
- safe checkpoint selection 不再需要 fallback cp10，cp20 可以作為 retention-safe candidate。
- mixed rehearsal 對 cp20 e_pawn 有局部改善：`0/2 -> 1/2`。
- full gate trigger 修正後，不會因 smoke pass rate 一過舊門檻就誤跑重型 full gate。
- hard flank 被正確標為 `questionable_hard_flank_label`，不會拿不乾淨 hard label 當 promotion 證據。

仍未達成：

- promotion 仍 false，合理。
- smoke level 1 仍 fail，cp20 還有 `easy_flank_failed`。
- smoke level 2 仍 fail，hard e-pawn / hard flank 都未通過。
- hard e-pawn 的 raw policy 沒在 mixed checkpoint 中穩定學上來。
- hard flank 的 expected label/context 不夠乾淨，應 quarantine，不該繼續拿來當硬 gate。
- semantic interference 仍有 `flank_update_caused_central_retention_drop` 訊號。

為什麼模型尚未完成學習要求：

- 目前不是「完全不能學」，因為 retention 能修、cp20 e_pawn easy 能改善。
- 也不是單純資料量不足，因為 specialist 與 mixed rehearsal 都指出語義類別之間仍有衝突。
- 核心 blocker 是：
  - flank semantic 邊界仍不乾淨。
  - hard flank 題庫 label/context 仍有 questionable evidence。
  - mixed training 仍會讓 central/flank 互相干擾。
  - hard e-pawn 在 final decision path 中沒有形成穩定優勢。

## 未來修正方向

- 先重審 hard flank gate case；questionable hard flank 不應繼續作為 balanced hard gate blocker。
- 對 easy flank 做更小、更聚焦的 mixed rehearsal，不要同時拉動 central。
- 對 hard e-pawn 做 raw-policy rank 與 final decision blocker 拆分；若 raw rank 沒上來，先修 trainer；若 raw rank 上來但 final 不選，再看 fusion。
- 對 semantic specialist probes 加快或改成可選分級；本輪 `118.662s` 是總耗時主要來源之一。
- 若下一輪要保持 100~150 秒，日常 quick gate 應預設不跑 full specialist probes，只在 smoke level 1/2 需要診斷時啟用。

## 適用 exp3 / exp4

本輪實跑是 exp3。修改點大多是 validation/report/gate 層，適用 exp3/exp4：

- retention version audit 適用 exp3/exp4。
- smoke level 1/2 reporting 適用 exp3/exp4。
- hard case decision audit 適用 exp3/exp4。
- exp34 mixed rehearsal 已支援 exp3 DL trainer 與 exp4 PV trainer path，但本輪沒有 exp4 實跑數據。

## 驗證

- `python3 -m py_compile scripts/games/chess_live_learning_validation.py services/games/chess_dl.py`：通過。
- targeted tests：`python3 -m pytest tests/scripts/games/test_chess_live_learning_validation_script.py -q -k "exp34 or exp33"`，`5 passed`。
- artifact consistency：`_report_consistency_issues(...) == []`。
- quick deterministic gate：完成，結果目錄如上。
