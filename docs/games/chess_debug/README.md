# Chess Debug / Engine Roadmap

本目錄保存西洋棋引擎實驗、debug 歷程、promotion gate 證據鏈與後續架構演進文件。

模型檔路徑、前台難度選項、auto-retrain candidate、promotion production path 的完整對照見：

- [`model_artifact_paths.md`](model_artifact_paths.md)

全域模型檔規則：

- `services/games/models` 只放發佈用 warm-up / bundled seed。
- 首次啟動時若 runtime model 不存在，才從 bundled seed 複製到 runtime。
- 前台實際對局讀取 runtime production model。
- auto-retrain 產物與 promotion 後的新 production model 都在 runtime 內。
- autoretrain 不改寫 `services/games/models`。

目前資料夾分工：

- [`exp3/`](exp3/)：保留 exp1-34 的完整 debug 歷程、每個實驗報告、以及原本的 `chess_debug.md` 主 ledger。exp3 開發目前暫停。
- [`exp4/`](exp4/)：後續 `Policy/Value network + MCTS` 路線文件放這裡。
- [`exp5/`](exp5/)：後續 `NNUE-like / NNUE + alpha-beta/PVS` 路線文件放這裡。

## 目前結論

exp3 的價值已經完成：它證明了 replay validation、deterministic gate、promotion evidence chain、artifact consistency、leakage guard、mistake retention、semantic debug report 這套治理流程可以落地。

但 exp3 不適合再被當成最終棋力模型繼續硬修。原因是 exp3 仍是 lightweight MLP + alpha-beta 的設計，經過 exp1-34 已確認它在 flank/context、hard semantic generalization、mixed scheduler retention 上接近架構上限。繼續修 exp3 會變成在小模型上堆補丁，而不是解決棋力架構問題。

後續重心：

- exp3：凍結為 baseline / governance reference。
- exp4：推進 Policy/Value + MCTS。
- exp5：推進 NNUE-like evaluator + alpha-beta/PVS。

### exp5 最新進度（截至 2026-05-12 exp5_14b）

- exp5_12 已把 exp5_08 / exp5_10 validated candidate promoted 到 runtime production model（sha256 `c47ef752...`）。
- exp5_13 補上 runtime rule-priority / stalemate hardening；model artifact unchanged，但 production runtime behavior changed by code path。
- exp5_13 validation：137 cases、72 true held-out、overlap audit 0；runtime candidate 115/137 = 0.839416，baseline 112/137 = 0.817518，Δ +0.021898。
- rule smoke 18/18，illegal_rate 0.0，suspicious_rate 0.0，clean_regressed_count 0，repeatability 5/5 且 std_delta 0.0。
- exp5_14 opening audit：27/27 opening rows are questionable；0 clean true opening regressions；opening weakness is not a production blocker but cannot be used as clean training evidence yet。
- exp5_14b clean opening expansion：31 clean multi-good rows，kept overlap 0；current production-equivalent opening score is only 1/31, so exp5_15 should target opening curriculum against current production。
- 詳見 [`exp5/README.md`](exp5/) 歷程總表 + 各輪 ledger。

## Experiment 1：基礎搜尋與對局學習

角色：

- exp1 是最早期的棋局學習 / engine-search baseline。
- 主要用途是驗證「棋局產生、replay 收集、基本 learning store、root dashboard」是否可運作。
- 它不是神經網路棋力模型。

Difficulty：

- `experiment`

主要程式：

- `services/games/chess_engine.py`

模型 / 資料位置：

- 預設 runtime：`$HACKME_RUNTIME_DIR/games/models/chess_experiment.db`
- 若未設定 `HACKME_RUNTIME_DIR`，使用伺服器 runtime root 下的 `games/models/chess_experiment.db`
- 可用環境變數覆蓋：`HTML_LEARNING_CHESS_ENGINE_DB_PATH`
- bundled seed：`services/games/models/chess_experiment.db`

使用方式：

- 前台電腦難度選 `實驗`。
- 後端會經由 `routes/games.py::choose_computer_move(...)` 呼叫 `choose_experiment_move(...)`。
- warm-start 會透過 `ensure_warm_start_chess_environment()` 確認 DB 存在。

目前方向：

- 保留，不再作為主要棋力突破方向。
- 可繼續作為 legacy baseline 與 replay/promotion dashboard 參照。

## Experiment 3：DL 語義平衡 baseline

角色：

- exp3 是 lightweight deep-learning baseline。
- 架構是小型 MLP evaluator + replay buffer + alpha-beta search。
- 它承載了 exp1-34 的大部分 debug pipeline，包括 deterministic gate、mistake retention、semantic held-out、distilled replay、leakage guard、smoke gate、artifact consistency。

Difficulty：

- `experiment 3:dl`

主要程式：

- `services/games/chess_dl.py`
- `scripts/games/chess_live_learning_validation.py`
- `tests/scripts/games/test_chess_live_learning_validation_script.py`

模型 / replay 位置：

- 模型預設 runtime：`$HACKME_RUNTIME_DIR/games/models/chess_experiment_3_dl.json`
- replay 預設 runtime：`$HACKME_RUNTIME_DIR/games/models/chess_experiment_3_dl_replay.jsonl`
- 可用環境變數覆蓋模型：`HTML_LEARNING_CHESS_ENGINE_DL_MODEL_PATH`
- 可用環境變數覆蓋 replay：`HTML_LEARNING_CHESS_ENGINE_DL_REPLAY_PATH`
- bundled seed model：`services/games/models/chess_experiment_3_dl.json`

使用方式：

- 前台電腦難度選 `實驗 3：DL 語義平衡學習`。
- quick deterministic gate / validation 仍可用來回歸 governance pipeline。
- 不建議把 exp3 當作後續主要棋力提升路線。

暫停原因：

- exp3 已證明治理流程有效，但棋力模型能力不足。
- exp34 最終狀態顯示：development 與部分 central anchor 可修，但 flank contextual learning、hard semantic generalization、mixed scheduler retention 仍不穩。
- exp3 的小型 MLP 表徵能力不足，繼續堆 semantic memory / rehearsal / gate 修補，會增加複雜度但不保證泛化。
- 因此 exp3 暫停開發，保留為 baseline 與驗收框架參照。

詳細紀錄：

- [`exp3/chess_debug.md`](exp3/chess_debug.md)
- [`exp3/INDEX.md`](exp3/INDEX.md)
- [`exp3/exp3_pause_conclusion.md`](exp3/exp3_pause_conclusion.md)
- [`exp3/exp3_closeout_model_autoretrain_verification.md`](exp3/exp3_closeout_model_autoretrain_verification.md)

收尾驗證：

- bundled seed model 不隨 autoretrain 改變，只作首次 warm-start；目前已用 exp3 closeout 最佳模型作發佈 warm-up seed。
- 目前 repo runtime production model 已替換為 exp34 checkpoint@20。
- bundled seed hash：`333ed8e72524836d39851b74f4c209c6e08f2652720cacf36a13aa2ac8448dee`
- runtime production hash：`333ed8e72524836d39851b74f4c209c6e08f2652720cacf36a13aa2ac8448dee`
- 前後端 `experiment 3:dl` 串接、warm-start、trusted replay 收集、autorun candidate retrain、production/candidate 模型隔離已實測成立。
- 已知限制：production auto-retrain 目前仍走 `chess_train_pipeline.py` full pipeline，不是 exp34 quick deterministic balanced gate；若要用 deterministic gate 作自動 promotion，需另行接入。

## Experiment 4：Policy/Value + MCTS

角色：

- exp4 是後續主要神經網路棋力路線之一。
- 方向是 Policy/Value network + MCTS，類似 AlphaZero / Leela 方向，但目前仍是 repo 內的輕量 prototype。
- exp4 已保留 alpha-beta fallback，避免一次替換既有穩定搜尋。

Difficulty：

- `experiment 4:pv`

主要程式：

- `services/games/chess_pv.py`

模型位置：

- 預設 runtime：`$HACKME_RUNTIME_DIR/games/models/chess_experiment_4_pv.json`
- 可用環境變數覆蓋：`HTML_LEARNING_CHESS_ENGINE_PV_MODEL_PATH`
- bundled seed model：`services/games/models/chess_experiment_4_pv.json`

使用方式：

- 前台電腦難度選 `實驗 4：Policy/Value + MCTS`。
- `routes/games.py` 目前呼叫 `choose_experiment_pv_move(..., decision_mode="mcts")`。
- 若要保守回退，可在程式層改用 `decision_mode="alpha_beta"`。

後續方向：

- 補完整 MCTS visit statistics、root policy/value breakdown。
- 把 deterministic strength snapshot 接到 MCTS decision mode。
- 檢查 tactic/blunder regression，避免 policy prior 或 override 蓋掉明顯戰術。
- 建立 exp4 專用 report 與 promotion gate，不直接沿用 exp3 的語義 replay 成功定義。

exp4 棋力小結（2026-05-12，exp4_06 → exp4_13）：

- 會：合法棋、mate-in-1、free-queen avoid、開局多好棋等價、long castle、queen/knight/rook promotion、stalemate avoidance、mistake retention、認輸 invariants。
- 不會：short castle、en-passant take、失子後王安全（4-anchor curriculum × 3 weight 還沒效）、unseen variant broad generalization、hard flank。
- 致命弱點與 exp3 example/example2 同類：ply 5 Bxc6 主教換兵、失子後王走中央、engine-lost replay 進訓練（quarantine 已防 source，trainer side label weight 待改）。
- 對標：~1100-1400 elo / stockfish level 1-3；HIGH_RISK，promotion 從未 pass。
- 詳細能力矩陣與量化指標進程見 [`exp4/README.md`](exp4/)。

exp4 歷程 (2026-05-11 → 2026-05-12)：

- exp4_06：deterministic +0.0538 baseline，但 evidence accounting 不可信
- exp4_07-09：cleanup — catastrophic_regression_source 拆出、e_pawn=0 是 multi-good scoring 而非真錯、`opening_develop_white` MCTS artifact 識別、`gate_e_pawn_hard_001` 是 label_questionable
- exp4_10-11：anti-poison + chess_pv override search guard + multi-good revoke + 5 ply quarantine wiring
- exp4_12：audit/guard score-source 一致性（real alpha-beta 取代 MCTS unvisited −999996 artifact）
- exp4_13：special-rule curriculum 1/7→5/7，但 catastrophic forgetting（deterministic −0.0539、sanity exact 失敗、d_pawn 歸零）
- exp4_14：降權 + 18 row retention rehearsal + budget + rollback guard，翻盤 forgetting：deterministic +0.0538、special_rule 保 5/7、d_pawn 回來、sanity exact 過、gate reasons 從 33 縮減到 21；唯一新 blocker 是 `mistake_retention_regressed`

詳細歷程總表見 [`exp4/README.md`](exp4/)。

exp4_15 retention guard bug fix + chess_pv rule_type trainer consumption + king-safety isolated probe（2026-05-12）：

- 修 retention guard bug：exp4_14 `mistake_retention_regressed` 是 false alarm（guard 讀錯來源），實際 probe 兩個 checkpoint 都 pass。改讀 `before_after_eval.checkpoints[*].mistake_retention_probe`。
- chess_pv `train_experiment_pv_from_replay_samples` 真的消費 `rule_type`：`RULE_FEATURE_BOOST_TYPES`（castling/e.p. 2.5、underpromote 2.0、knight_mate 2.0）給 rule rows 額外 reinforcement repeats。`rule_feature_metadata_only` 從 True 翻為 False。
- 新 `_king_safety_isolated_probe_run`：複製 baseline，只訓練 king-safety anchors × 3 weight，eval king_safety gate；isolated 0/2 即可確認是 feature/decision-path gap，不是 weight 問題。
- 新 `_rule_targeted_probe`：targeted castle_short_white + en_passant_white before vs after；`rank_improved_count` 才是真進步訊號。
- 詳細欄位變更見 [`exp4/README.md`](exp4/)。

exp4_16 rule-aware final fusion for special moves（2026-05-12）：

- 核心修正：exp4_15 已證明 raw policy 學到 short castle / en-passant，但 final decision 不採用；exp4_16 改 final fusion，而不是再加 anchors 或 weights。
- `chess_pv` 新增 guarded rule-aware bonus：castling / en-passant / promotion / underpromotion 只有在 legal、raw rank <= 3、real alpha-beta guard 不反對時才可採用。
- rule-aware final fusion 成功後會鎖住 final move，ordinary policy override 不可再覆蓋；explain path 會標 `rule_aware_fusion_locked_final_move`。
- `_candidate_alpha_beta_score` 改 deterministic fixed-depth (`time_budget_ms=None`)。
- result：`/home/s92137/chess_results/exp4_16_rule_aware_final_fusion_locked`
- deterministic：`0.8693 -> 0.9231`，但 promotion 仍 false。
- targeted：short castle `d2d4 -> e1g1`，en-passant 維持 `d5e6`；兩者 `rule_bonus_after=420`、guard pass。
- special-rule gate：`6/7`，新 blocker 是 `promotion_white_knight_mate` 選成 `e7e8r` 而非 `e7e8n`。
- exp3 replay lesson：example/example2 顯示 king-safety 崩、早后/側翼/中央兵 prior 過強、trusted replay 污染風險；exp4 保留 quarantine + real alpha-beta guard，但 king-safety feature gap 留 exp4_17。
- 詳細報告：[`exp4/2026-05-12_exp4_16_rule_aware_final_fusion.md`](exp4/2026-05-12_exp4_16_rule_aware_final_fusion.md)。

exp4_16 vs exp5_08 diagnostic sparring（2026-05-12）：

- 詳細報告：[`exp4/2026-05-12_exp4_16_vs_exp5_08_sparring.md`](exp4/2026-05-12_exp4_16_vs_exp5_08_sparring.md)。
- result dir：`/home/s92137/chess_results/exp4_vs_exp5_smoke_20260512_032501`
- 性質：6-game smoke，`diagnostic_only=true`，不可作 promotion evidence，也不可作正式 strength evidence。
- 結果：exp4 3 wins / exp5 0 wins / draws 3，illegal=0，exp4 audit coverage 65/65，exp5 audit coverage 60/60。
- 判讀：exp4_16 special-rule final fusion 已進真 choose path，但暴露 subtype 問題：expected kingside castling 可能選 queenside castling，promotion 也有 queen/rook/knight piece selection 不穩。
- 下一步：exp4_17 優先修 `castling_short vs castling_long` 與 `promotion_piece_subtype`，並為 exp4 sparring 補 deterministic / fixed-depth profile，避免 time-budget variance。

exp4_17 special-rule subtype + gate accounting cleanup（2026-05-12）：

- 詳細報告：[`exp4/2026-05-12_exp4_17_special_rule_subtype_consistency.md`](exp4/2026-05-12_exp4_17_special_rule_subtype_consistency.md)。
- result dirs：
  - `/home/s92137/chess_results/exp4_17_special_rule_subtype_consistency`
  - `/home/s92137/chess_results/exp4_17_gate_accounting_cleanup`
- 修正：`castling_short` / `castling_long`、`promotion_queen` / `promotion_knight_mate` / `underpromotion_*` 分成 subtype；新增 `fixed_depth_*` profile。
- special-rule deterministic gate：`7/7`，`promotion_white_knight_mate` 從 `e7e8r` 修成 `e7e8n`。
- gate accounting cleanup：low-margin override 只要沒有 counted_as_learning_success 就不再作 blocker；opening alignment 排除 mistake_retention rows。
- promotion 仍 false：deterministic final 沒高於 baseline，heavy sanity skipped，balanced_fusion final decision generalization 未過，hard flank gap 未解。

exp4_18 full broad learning diagnostic + e_pawn gate accounting fix（2026-05-12）：

- 詳細報告：[`exp4/2026-05-12_exp4_18_full_broad_learning_diagnostic.md`](exp4/2026-05-12_exp4_18_full_broad_learning_diagnostic.md)。
- result dirs：
  - `/home/s92137/chess_results/exp4_18_full_broad_learning_diagnostic`
  - `/home/s92137/chess_results/exp4_18_e_pawn_gate_accounting_fix`
- full heavy sanity 結論：`HIGH_RISK`，promotion false；special-rule 維持 `7/7`，但 deterministic final `0.8693` 與 baseline 打平。
- sanity generalization：trusted=10 unseen `0.3968`，trusted=20 unseen `0.3889`；exact FEN 會，但 broad generalization 未證明。
- timing：full diagnostic `total_wall_seconds=2438.614`、`total_checkpoint_seconds=2264.592`；瓶頸是 final decision seen/unseen before/after，不是 retrain。
- 修正：`gate_e_pawn_easy_002/003` 中黑方 `d7d5` 這類 quiet-opening 合理中央回應不再被誤判為 `e7e5` learning failure；新 classifier 把 `true_e_pawn_final_decision_blocked` 從 4 降為 0，`e_pawn_equivalent_credit_pass_rate` 從 0.7778 升到 1.0。
- quick confirmation：`PARTIAL`，promotion false；e_pawn false blocker 已移除，但 heavy sanity skipped、deterministic 未提升、balanced_fusion generalization 未證明仍阻擋 promotion。

exp4_19 guarded overlay attribution（2026-05-12）：

- 詳細報告：[`exp4/2026-05-12_exp4_19_guarded_overlay_attribution.md`](exp4/2026-05-12_exp4_19_guarded_overlay_attribution.md)。
- result dir：`/home/s92137/chess_results/exp4_19_guarded_overlay_attribution`
- 結果：full replacement 仍是 `0.8693`，但 baseline-default guarded overlay attribution 可到 `0.9231`，delta `+0.0538`。
- 關鍵：採用 final 的 `mistake_retention_game_900002_ply_1: d7d5`，但對 `promotion_white` 回退 baseline `e7e8q`，因此避免 final candidate 的局部 regression。
- 判讀：這是 label-based upper-bound，不是 production evidence；promotion 仍 false。下一步應把它改成 runtime 可用的 guarded overlay，使用 search/static/special-rule/oracle 等 runtime 訊號，而不是 deterministic expected label。

exp4_20 runtime guarded overlay simulator（2026-05-12）：

- 詳細報告：[`exp4/2026-05-12_exp4_20_runtime_guarded_overlay.md`](exp4/2026-05-12_exp4_20_runtime_guarded_overlay.md)。
- result dir：`/home/s92137/chess_results/exp4_20_runtime_guarded_overlay`
- 結果：no-label runtime simulator 也達到 `0.9231`，delta vs baseline `+0.0538`，`unsafe_override_after_scoring=0`。
- 關鍵：guard 不讀 expected label；用合法性、static-like score window、promotion subtype oracle 判斷是否採用 final。
- `mistake_retention_game_900002_ply_1`：採用 final `d7d5`；`promotion_white`：擋住 final `e7e8n`，回退 baseline `e7e8q`。
- 判讀：exp4_20 已證明 runtime guard 規則本身有效，但尚未接到 production choose path；promotion 仍 false。

exp4_21 runtime guarded overlay integration draft（2026-05-12）：

- 詳細報告：[`exp4/2026-05-12_exp4_21_runtime_guarded_overlay_integration.md`](exp4/2026-05-12_exp4_21_runtime_guarded_overlay_integration.md)。
- 新增 `services/games/chess_pv_guarded_overlay.py`，讓 validation simulator 與 runtime path 共用同一個 no-label guard。
- 前台 exp4 path 已可透過 `HTML_LEARNING_CHESS_EXP4_GUARDED_OVERLAY=1` 啟用 guarded overlay；預設關閉，不改 production 行為。
- guard input 已 sanitized，只吃 `fen / side / baseline_move_uci / final_move_uci / score_cp / final_illegal`，不吃 expected label / top1_correct / pass-fail。
- result dir：`/home/s92137/chess_results/exp4_21_runtime_guarded_overlay_integration`
- quick targeted gate：baseline `0.8693`，full final replacement `0.8693`，runtime guarded `0.9231`，delta `+0.0538`，`unsafe_override_after_scoring=0`，special-rule `7/7`。
- 關鍵 case：`mistake_retention_game_900002_ply_1` 採用 final `d7d5`；`promotion_white` fallback baseline `e7e8q`。
- 判讀：這是 runtime integration draft，不是 promotion；quick targeted gate 已驗證 shared guard 行為，但 heavy sanity skipped、production flag 預設關閉，仍需 full broad diagnostic。

exp4_22 actual runtime guarded overlay full diagnostic（2026-05-12）：

- 詳細報告：[`exp4/2026-05-12_exp4_22_actual_runtime_guarded_overlay_full.md`](exp4/2026-05-12_exp4_22_actual_runtime_guarded_overlay_full.md)。
- quick result dir：`/home/s92137/chess_results/exp4_22_actual_runtime_guarded_overlay_quick`
- full result dir：`/home/s92137/chess_results/exp4_22_actual_runtime_guarded_overlay_full`
- actual runtime guarded score：`0.9231`，delta vs baseline `+0.0538`，`unsafe_override=0`，`simulator_selected_mismatch=0`。
- full diagnostic verdict：`HIGH_RISK`，promotion `false`，total wall seconds `2515.596`。
- 判讀：actual runtime overlay 本身沒 drift；真正問題是 current broad sanity 仍評估 full final replacement，不是 guarded overlay。已新增 `guarded_overlay_sanity` 派生欄位，下一輪 full run 要用它判斷 guarded overlay broad behavior。

exp4_14 balanced curriculum + retention rehearsal + budget + rollback guard（2026-05-12）：

- special-rule weights 大幅下調（castling/e.p. 3→1.5、knight_mate/underpromote 4→2、queen 1→0.75）；新增 3 個 short-castle FEN 變體。
- 新 `_retention_rehearsal_anchors`（~16 row）：開局 multi-good × 10、d/e_pawn easy retention × N、mistake_retention echo × 2，weights 1.5–2.0。
- `_curriculum_budget_summary` 報告 special_rule_mass_ratio、retention_mass_ratio、special_rule_mass_budget_passed (≤0.30)。
- `_checkpoint_retention_guard` 偵測 catastrophic forgetting：deterministic delta < −0.02 / sanity_exact_fen_failed / d_pawn=0 / mistake_retention regressed 任一觸發 rollback_recommended。
- 新 gate reasons：`special_rule_curriculum_budget_exceeded`、`checkpoint_retention_guard: <reason>`。
- `rule_feature_metadata_only=True`：明示 trainer 不用 chess_label_features flags；en-passant 學習要 wait for 下一輪 trainer 改造。
- `king_safety_isolated_probe` 旗標：本輪不跑 isolated，留給 exp4_15。
- artifact path 修正：curriculum jsonl 從 engine_dir/checkpoints/audits 改回 engine_dir/audits。
- 詳細欄位變更見 [`exp4/README.md`](exp4/)。

exp4_13 special-rule curriculum + king-safety recovery curriculum + draw fixture（2026-05-12）：

- 修 `draw_lone_king_must_play_legal.good_moves` 加 `e1c1`（castle 在該 FEN 合法）。
- 新增 `_special_rule_curriculum_anchors`（8 row）與 `_king_safety_recovery_curriculum_anchors`（4 row），weight × 1–4，注入 quick retrain checkpoint training。
- summary 加 `special_rule_pass_rate_before/after`、`king_safety_pass_rate_before/after`、`*_by_rule_type` before/after。
- 新 gate scope policy：castling 阻擋 opening_specialist；en-passant / underpromotion / king-safety / draw_handling 只阻擋 general_model。
- 詳細欄位變更見 [`exp4/README.md`](exp4/)。

exp4_12 audit/guard score-source 一致性 + quarantine post-filter semantics（2026-05-11）：

- `policy_override_audit` 改用 `policy_override.search_guard.disagreement_cp`（chess_pv 真實 alpha-beta）取代 MCTS final_combined_score 差距；舊 MCTS 路徑保留為 `mcts_disagreement_cp / mcts_score_diagnostic_only=True`。
- 新欄位：`override_against_search_count_after_fix`, `override_rejected_by_engine_guard_count`, `mcts_artifact_false_alarm_count`, `max_real_disagreement_cp`, `max_mcts_artifact_disagreement_cp`。`opening_develop_white` 不再因 MCTS unvisited -999996 artifact 被誤報。
- `_opening_target_margin_audit` 內 multi_good_revoke 同樣改用 real_disagreement_cp；新欄位 `multi_good_revoked_by_real_search_guard_count` 與 `multi_good_revoked_by_mcts_artifact_count`。
- `quarantine_summary` 拆 `raw_trusted_replay_blunder_flagged_count` vs `post_filter_poison_training_rows / post_filter_poison_eval_rows`。promotion_gate 不再因 raw flag > 0 而 fail；只在 `poison_filter_not_applied` 或 `post_filter_poison_*` 非 0 時 block。
- 詳細欄位變更見 [`exp4/README.md`](exp4/)。

exp4_12 求和 + 認輸 + 特殊走法擴充 + chess label features（2026-05-11，延後並合進 exp4_13 範圍）：

- 新增 `resignation_deterministic_gate`（4 case）、`draw_handling_deterministic_gate`（3 case，含 avoid_stalemate_when_winning / 50move_reset / lone_king_legal_move）。
- `_special_rule_deterministic_gate` 擴充：加入 `underpromotion_rook_avoid_stalemate`、`en_passant_window_closed`，從 5 → 7 case。
- `services/games/chess_pv.py` 新增 `should_resign` 診斷函式（30 ply forbidden + mate-distance ≤ 5 allowed + 預設不認輸）。引擎本身仍不會自動投降。
- 新增 `_chess_label_features` 暴露 castling / en_passant / promotion / threefold / 50-move / mate_distance / resign_allowed 等 row-label flags（待 trainer 消費）。
- 詳細欄位變更見 [`exp4/README.md`](exp4/)。

exp4_11 anti-poison quarantine + chess_pv override search guard + multi-good revoke（2026-05-11）：

- 新增 `low_confidence_trusted_audit`（confidence<0.5 + trusted）、`misclassified_resign_audit`（resign 但最後 3 ply 內有吃子）、`replay_quarantine_index`（合併三個 audit）。
- `_extract_engine_move_samples_from_records` 接受 `quarantine_replay_ids` / `quarantine_ply_keys`；quick gate 在訓練前自動 quarantine 並寫 `audits/replay_blunder_quarantine.jsonl`。
- `services/games/chess_pv.py` 的 `_policy_override_info` 新增 `_override_search_guard`：search 偏好其它 move >200cp 或 chosen_search_score 為 mate-like 時 reject override。
- `_opening_target_margin_audit` 新增 `multi_good_revoked_by_search_guard`：當 best_other_search_score - chosen_search_score > 200cp 時 multi-good credit 失效。
- 詳細欄位變更見 [`exp4/README.md`](exp4/)。

exp4_10 anti-poison + special-rule + king-safety + override-search guard 診斷（2026-05-11）：

- 新增 `replay_blunder_screen`（see-after-recapture material loss）、`resignation_audit`、`king_safety_after_material_loss_audit`、`special_rule_deterministic_gate`、`policy_override_audit.override_against_search_count`。
- 全部為 diagnostic，不影響 promotion behavior；exp4_11 接成實際 filter / guard。
- 詳細欄位變更見 [`exp4/README.md`](exp4/)。

exp4_09 opening label audit + specialist gate cleanup（2026-05-11）：

- 新增 `opening_label_audit`：對每個 `true_e_pawn_raw_policy_fail` / `true_e_pawn_final_decision_blocked` / opening `raw_policy_fail` case 逐題給 `label_quality ∈ {clean_label, questionable_label, label_unverified, relabel_recommended, quarantine_recommended}` 與 `clean_true_failure` 旗標。
- `e_pawn_true_raw_policy_fail_count_clean` / `e_pawn_true_final_decision_blocked_count_clean` 把 questionable / relabel / quarantine 排除後重算；opening specialist gate 改用 `*_clean` count。
- `opening_specific_learning_evidence_status` 給出 `insufficient_clean_true_fail_cases` 或 `clean_true_failure_present`；前者代表剩下的真失敗是 label noise。
- `previous_e_pawn_failure_was_label_or_multigood_issue=true` 當且僅當 raw/final-blocked count 在 clean 後歸零。
- `engine_verdict_extension = PARTIAL_LABEL_AUDIT_CLEANUP_NO_BROAD_GENERALIZATION` 當 label cleanup 完成但 broad gate 未過。
- `summary_size_top_contributors`：列 summary.json top-8 最大 key（artifact slimming v2 的量化依據）。
- 本輪不做 rehearsal。詳細欄位變更見 [`exp4/README.md`](exp4/)。

exp4_08 e_pawn opening specialist repair（2026-05-11）：

- 對 e_pawn clean held-out 18 cases（trusted=10/20）做 case-level equivalence audit：teacher_top3/top5、static_best_move、static_cp_delta、margin、multi_good_equivalent。
- 失敗分類拆成 `strict_pass`、`equivalent_credit_pass`、`central_opening_equivalent_credit`、`opening_multi_good_tie`、`true_e_pawn_raw_policy_fail`、`true_e_pawn_final_decision_blocked`、`label_questionable`、`undertrained_opening_pattern`；equivalent credit 必須有 teacher_top3/top5 命中或 static_cp_delta 在 `OPENING_MULTI_GOOD_CP_THRESHOLD` 內的正面證據。
- 詳細 rows 寫入 `audits/opening_target_margin_audit.jsonl` 與 `audits/e_pawn_clean_held_out_diagnosis.jsonl`；summary.json 只留 totals + artifact path + inline_sample，預期 size 大幅下降。
- 新增 promotion_gate reasons：`true_e_pawn_raw_policy_fail_count_nonzero (N)`、`true_e_pawn_final_decision_blocked_count_nonzero (N)`；`e_pawn_strict_pass_zero_but_equivalent_credit_present` 屬 informational 放在 `non_blocking_notes`。
- opening specialist gate 不再被 e_pawn strict=0 擋（前提：equivalent-credit pass rate > 0）；general model gate 仍保留。
- 詳細欄位變更見 [`exp4/README.md`](exp4/)。

exp4_07 evidence accounting cleanup（2026-05-11）：

- `opening_target_margin_audit` 拆出 `override_applied_for_move_selection_count` 與 `override_counted_as_learning_success_count`；low-margin override 的 `low_margin_override_counted_success_count` 固定為 0。
- `opening_final_decision_alignment_passed` 與 `opening_specific_learning_evidence_passed` / `targeted_mistake_retention_success` / `opening_learning_evidence_passed` 拆開列出。
- 新增 `e_pawn_clean_held_out_diagnosis`：每個 e_pawn case 給 `raw_policy_fail` / `final_decision_blocked` / `multi_good_tie` / `undertrained_opening_pattern` classification。
- 新增 `hard_flank_scope_isolation`：`hard_flank_used_in_opening_specialist_gate=false`、`hard_flank_general_model_blocker` 獨立記錄；contextual flank hard clean=0 不再擋 opening specialist。
- 新增 `sanity_learning_summary`：trusted=10/20 各自給 verdict（含 `PARTIAL_EXACT_OR_LOW_MARGIN_ONLY`），不讓 exact-FEN 偽裝成 broad generalization。
- `stability.catastrophic_regression_source` 拆出 deterministic / retention / margin / generalization 各獨立來源，deterministic score 上升時 `deterministic_score_regression=false`。
- `promotion_gate` 提供 `opening_specialist_gate` 與 `general_model_promotion_gate` 兩個 scope，並把 `current_exp4_measured_blockers` 與 `historical_cross_experiment_risk_references` 分開。歷史 reference 不再阻擋 opening specialist。
- 詳細欄位變更見 [`exp4/README.md`](exp4/)。

演進文件：

- [`exp4/`](exp4/)

## Experiment 5：NNUE + AlphaBeta/PVS

角色：

- exp5 是另一條後續主要棋力路線。
- 方向是 NNUE-like evaluator + alpha-beta/PVS search，接近現代 Stockfish 類架構的工程方向。
- 目前已新增 repo 內可跑的 NNUE-like skeleton，但尚不是 Stockfish 相容 NNUE。

Difficulty：

- `experiment 5:nnue`

主要程式：

- `services/games/chess_nnue.py`

模型位置：

- 預設 runtime：`$HACKME_RUNTIME_DIR/games/models/chess_experiment_5_nnue.json`
- 可用環境變數覆蓋：`HTML_LEARNING_CHESS_ENGINE_NNUE_MODEL_PATH`
- bundled seed model：`services/games/models/chess_experiment_5_nnue.json`

使用方式：

- 前台電腦難度選 `實驗 5：NNUE + AlphaBeta/PVS`。
- 後端會經由 `routes/games.py::choose_computer_move(...)` 呼叫 `choose_experiment_nnue_move(...)`。
- warm-start 會建立 `chess_experiment_5_nnue.json` runtime artifact。

後續方向：

- 補真正 NNUE feature accumulator。
- 補 PVS、LMR、null-move pruning、killer/history/countermove ordering。
- 建立 exp5 專用 deterministic strength gate。
- 不直接把 exp3 的 semantic replay labels 當作 exp5 promotion evidence。

演進文件：

- [`exp5/`](exp5/)
- latest production-readiness ledger：[`exp5/2026-05-12_exp5_10_production_readiness.md`](exp5/2026-05-12_exp5_10_production_readiness.md)

## 常用操作

查看模型檔與 retrain 產物路徑：

- [`model_artifact_paths.md`](model_artifact_paths.md)

Warm-start 所有 chess engine artifact：

```bash
python3 - <<'PY'
from services.games.chess_promotion import ensure_warm_start_chess_environment
print(ensure_warm_start_chess_environment())
PY
```

檢查 production inventory：

```bash
python3 - <<'PY'
from services.games.chess_promotion import production_engine_inventory
for row in production_engine_inventory():
    print(row)
PY
```

快速確認 exp4 / exp5 能產生合法 move：

```bash
python3 - <<'PY'
from services.games.chess import initial_board
from services.games.chess_pv import choose_experiment_pv_move
from services.games.chess_nnue import choose_experiment_nnue_move

board = initial_board()
print("exp4", choose_experiment_pv_move(board, "black", search_profile="fast", decision_mode="mcts"))
print("exp5", choose_experiment_nnue_move(board, "black", search_profile="fast"))
PY
```

## 維護規則

- exp3 相關歷史與暫停原因寫入 `exp3/`。
- exp4 後續每次架構或 gate 演進，寫入 `exp4/`。
- exp5 後續每次架構或 gate 演進，寫入 `exp5/`。
- 根目錄 README 只放總覽、方向、模型位置與使用方法。
- 不同 engine 的 promotion evidence 不可混用；每份報告都必須清楚標出 architecture、model path、gate case set 與 verdict。
