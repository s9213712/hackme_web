# 2026-05-11 exp5 scaffold and compatibility review

## 修改歷程

- commit：`5a07667 Add exp5 chess retrain scaffold`
- 新增 `services/games/chess_nnue.py`
  - difficulty：`experiment 5:nnue`
  - architecture：`nnue-like-sparse-accumulator-v1`
  - runtime model：`chess_experiment_5_nnue.json`
  - replay ledger：`chess_experiment_5_nnue_replay.jsonl`
  - 提供 `choose_experiment_nnue_move`、candidate ranking、decision breakdown、sample normalize、最小 replay trainer。
- 新增 `services/games/models/chess_experiment_5_nnue.json`
  - bundled seed model，只保存 exp5 JSON schema 與初始 evaluator 權重。
- 新增 `scripts/games/chess_exp5_dataset_train.py`
  - 接受 FEN/move JSONL。
  - 寫入 exp5 model/replay。
  - 明確回報 `strength_validation_supported=false`、`promotion_gate_supported=false`。
- 新增 `scripts/games/chess_exp5_retrain_pipeline.py`
  - exp5-only 最小 retrain pipeline。
  - 預設輸出到 `candidate_paths_for_run(run_id)` 下的 exp5 candidate model/replay。
  - 產生 JSON/Markdown report，但不宣稱棋力提升或 promotion-ready。
- 接上前後端選項
  - `routes/games.py` 允許 `experiment 5:nnue`，並 dispatch 到 exp5 engine。
  - `public/index.html`、`public/js/38-games.js` 顯示 exp5。
- promotion 周邊只做 schema consistency
  - `ensure_warm_start_chess_environment` 會建立 exp5 runtime model。
  - candidate inventory 包含 exp5 path。
  - `promotion_report_consistency` 會檢查 exp5 architecture、version、sample_count、training_objective、weight sections。
- 新增測試
  - `tests/games/test_chess_exp5_architecture.py`
  - `tests/scripts/games/test_chess_exp5_dataset_train_script.py`
  - `tests/frontend/games/test_frontend_games.py` 更新 exp5 UI wiring assertions。

## 相容性結論

exp5 不是和 exp3/exp4「完全不相容」。比較準確的界線是：

- 可共用：資料來源、FEN/move 中介格式、run-scoped artifacts、部分 orchestration、benchmark 框架、promotion staging 的外層流程。
- 不可直接共用：exp3/exp4 的模型特徵、trainer update rule、semantic replay assumptions、quick retrain gate、promotion learning evidence。

也就是說，exp5 應該共用「外層管線能力」，但要保留自己的「模型 adapter、訓練 adapter、棋力 gate adapter」。

## 分層判斷

| 層級 | 能否共用 | 判斷 |
| --- | --- | --- |
| trusted/quarantine replay ledger | 可以 | 原始對局紀錄是 engine-agnostic。只要能還原 FEN、side、move，就能給 exp3/4/5 各自轉換。 |
| `chess_replay_prepare.py` 輸出的 FEN/move JSONL | 可以 | 目前 train/eval rows 已包含 `fen`、`move_uci`、`side`、`target`、`weight`。這正好可被 exp5 trainer 吃下。 |
| teacher distillation 的「老師選 move」 | 可以共用概念 | exp3 已有 `--teacher-distill-jsonl`，核心是 FEN -> teacher move。exp5 可共用 teacher move 產生器，但必須輸出 exp5 sample format。 |
| exp3 feature replay | 不可直接共用 | exp3 direct replay 是 49 floats + semantic memory/context fields，對 exp5 sparse piece-square evaluator 沒有直接意義。 |
| exp4 board/move feature replay | 不可直接共用 | exp4 direct replay 是 781 board planes + 49 move features，結構可轉概念，不能直接餵 exp5。 |
| exp3 semantic replay labels | 不可直接當 gate | flank/context/semantic adapter 是 exp3 的學習目標，不等於 exp5 棋力提升證據。 |
| `chess_train_pipeline.py` 外層 phase | 可以抽象共用 | prepare、candidate paths、report、stage/promote 是可共用外殼，但目前 hard-code exp3/exp4 refine 與 benchmark arguments。 |
| `PIPELINE_RETRAIN_ENGINES` auto-retrain | 目前不可直接加入 exp5 | 現在只允許 exp3/exp4。直接加入 exp5 會讓 pipeline 看似支援，但 seed_train、benchmark、gate 還不完整。 |
| benchmark match runner | 可以共用，但需接 adapter | self-play/round-robin 指標可以比較任意 engine；目前 committed runner 尚未把 exp5 model path 與 move dispatcher 納入完整 benchmark matrix。 |
| promotion staging | 可以部分共用 | file-based candidate staging 可共用；exp5 已加入 schema consistency。正式 promote 仍需要 exp5 專用 benchmark/gate evidence。 |
| promotion gate threshold | 不應完全共用 | legal rate、score rate、suspicious match 等安全底線可共用；但 exp5 還需要 NNUE/PVS 專用 deterministic suite、search setting record、candidate-vs-baseline comparison。 |

## 對 retrain 的判斷

不能把 exp5 直接塞進目前 exp3/exp4 retrain 流程，原因有三個：

- exp3/exp4 trainer 的 direct feature schema 不同。
- exp3 quick gate 的語意 replay 假設是為 DL semantic memory 設計，不是 NNUE-like evaluator 的證據。
- 現有 full pipeline benchmark command 主要處理 exp3/exp4 candidate paths，還沒有 exp5 專用 model path、matchups、report consistency 與 promotion verdict。

但 exp5 可以共用 retrain pipeline 的外層形式：

- prepare trusted replay dataset
- train candidate model in run-scoped path
- emit JSON/Markdown report
- run deterministic validation
- stage candidate
- promote only when gate passes

因此後續建議不是複製整份 pipeline，也不是把 exp5 硬塞進 exp3/exp4；而是把 `chess_train_pipeline.py` 逐步改成 engine adapter registry：

- `prepare_adapter`
- `train_adapter`
- `distill_adapter`
- `benchmark_adapter`
- `promotion_gate_adapter`

exp3、exp4、exp5 各自註冊 adapter，共用外殼。

## 對資料蒸餾的判斷

資料蒸餾不是不能共用，但要分清楚共用的是哪一層：

- 可共用：teacher search、FEN case set、side inference、teacher move extraction、quality/source weighting。
- 不可共用：exp3 的 feature vector、semantic auxiliary labels、flank context loss budget、exp4 的 board/move tensor layout。

exp5 合理的最小蒸餾格式應維持：

```json
{"fen":"...","side":"black","move_uci":"e7e5","target":1.0,"weight":1.4,"source":"teacher_distill_exp5"}
```

之後若要強化，可以再加 exp5 專用欄位，但不要沿用 exp3 語意欄位當必要條件：

- `teacher_score_cp`
- `candidate_score_cp`
- `principal_variation`
- `depth`
- `nodes`
- `hard_negatives`
- `tactic_tags`

## 對棋力驗證的判斷

棋力驗證框架可以共用，promotion verdict 不可共用。

可共用的底線指標：

- legal move rate
- game completion
- suspicious match count
- score rate / win rate
- draw rate
- low-quality move rate
- candidate-vs-production head-to-head

exp5 需要另建的驗證：

- deterministic opening/middlegame/endgame case set
- NNUE evaluator raw score before/after delta
- candidate move rank delta
- search profile 固定記錄：depth、quiescence、time budget、move ordering mode
- tactical blunder guard：mate-in-1、hang queen、forced recapture、king safety
- regression retention：不能只學會單一 replay move 後破壞基本戰術

正式 promotion evidence 應該長這樣：

- candidate model path
- baseline model path
- replay dataset hash
- deterministic case report
- benchmark report
- legal/tactic/regression summary
- exp5 gate verdict

## 下一步建議順序

1. 補 `chess_exp5_teacher_distill.py`
   - 已完成：只做 FEN -> teacher move -> exp5 JSONL，不碰 gate。
2. 讓 benchmark runner 支援 exp5 model path 與 engine dispatch
   - 已完成：`chess_self_play_train.py` / `self_play_training.py` 可載入 exp5 model path，round-robin、human probes、endgame suite 都會列入 `experiment 5:nnue`。
   - 此階段只做 benchmark support，不做 promotion。
3. 建 `chess_exp5_strength_gate.py`
   - 已完成：固定 deterministic suite，輸出 gate JSON/Markdown。
   - 標準判斷：不完全沿用 exp3/4；共用 legal/suspicious/score safety floors，但 exp5 必須另外通過 NNUE/PVS deterministic case 與 candidate rank trace。
4. 把 exp5 接入 full pipeline 的 adapter interface
   - 已完成第一版：full pipeline 可產 exp5 candidate/replay，autorun target 允許 `experiment 5:nnue`，dashboard command 也列出 exp5。
   - promotion 仍受 exp5 strength gate 保護；gate skipped/failed 時不 stage/promote exp5。

## 目前不可宣稱

- 不可宣稱 exp5 已有完整 auto-retrain。
- 不可宣稱 exp5 可以沿用 exp3 semantic replay gate。
- 不可宣稱 exp5 replay trainer 的 policy probe 等於棋力提升。
- 不可宣稱 exp5 已 promotion-ready。
