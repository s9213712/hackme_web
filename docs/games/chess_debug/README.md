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
