# Exp5：NNUE + AlphaBeta/PVS

本資料夾保存 exp5 後續演進文件。

## 定位

exp5 是後續主要棋力路線之一，方向是：

- NNUE-like / NNUE evaluator
- efficiently updatable accumulator
- alpha-beta / PVS search
- stronger move ordering
- deterministic strength gate

目前 exp5 已新增 `services/games/chess_nnue.py`。現階段是 repo 內可演進的 NNUE-like skeleton，不是 Stockfish 相容 NNUE。

## 目前狀態

- 可選引擎、warm-start artifact、模型 schema、sample format、candidate inventory scaffold 已建立。
- `chess_exp5_dataset_train.py` 是 exp5 專用最小 trainer，能從 FEN/move JSONL 更新 exp5 NNUE-like JSON model/replay。
- `chess_exp5_retrain_pipeline.py` 是 exp5 專用最小 retrain pipeline，只產 candidate 與 report，不接 exp3/exp4 semantic gate。
- auto-retrain / promotion 外層已支援 exp5，但 promotion 必須先通過 exp5 專用 strength gate；quick retrain gate 仍不沿用 exp3/exp4 semantic evidence。
- 修改歷程與相容性判斷：`2026-05-11_scaffold_and_compatibility.md`
- real candidate dry-run：`2026-05-11_exp5_01_real_candidate_dry_run.md`

## Difficulty

- `experiment 5:nnue`

## 模型位置

- runtime model：`$HACKME_RUNTIME_DIR/games/models/chess_experiment_5_nnue.json`
- env override：`HTML_LEARNING_CHESS_ENGINE_NNUE_MODEL_PATH`
- bundled seed：`services/games/models/chess_experiment_5_nnue.json`

模型生命週期：

- bundled seed 只作首次 warm-start，不會被 auto-retrain 改寫。
- 前台 exp5 對局讀取 runtime model。
- future exp5 retrain candidate 應寫入 runtime candidates。
- future exp5 promotion 通過後才替換 runtime production model。

## 使用方式

前台選擇：

- `實驗 5：NNUE + AlphaBeta/PVS`

程式呼叫：

```python
from services.games.chess_nnue import choose_experiment_nnue_move

move = choose_experiment_nnue_move(
    board,
    "black",
    search_profile="fast",
)
```

## 後續文件規則

- exp5 的每次 evaluator、search、gate、promotion decision 都寫在本資料夾。
- 不要直接沿用 exp3 的 semantic replay labels 作為 exp5 promotion evidence。
- 每份報告必須標明：
  - model path
  - evaluator architecture
  - search settings
  - deterministic case set
  - legality / tactic / blunder evidence
  - promotion verdict
