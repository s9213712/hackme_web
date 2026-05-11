# Exp4：Policy/Value + MCTS

本資料夾保存 exp4 後續演進文件。

## 定位

exp4 是後續主要神經網路棋力路線之一，方向是：

- board representation
- policy head
- value head
- MCTS / PUCT decision
- deterministic strength gate

目前 exp4 已有 `services/games/chess_pv.py`，並新增 `decision_mode="mcts"` 的 deterministic root MCTS/PUCT 入口。現階段仍保留 alpha-beta fallback。

## Difficulty

- `experiment 4:pv`

## 模型位置

- runtime model：`$HACKME_RUNTIME_DIR/games/models/chess_experiment_4_pv.json`
- env override：`HTML_LEARNING_CHESS_ENGINE_PV_MODEL_PATH`
- bundled seed：`services/games/models/chess_experiment_4_pv.json`
- full pipeline candidate：`$HACKME_RUNTIME_DIR/games/models/candidates/runs/<run_id>/chess_experiment_4_pv.json`
- staged candidate：`$HACKME_RUNTIME_DIR/games/models/candidates/experiment_4_pv`
- quick gate checkpoint：`<output_root>/exp4/checkpoints/<trusted>/exp4_quick_candidate_model.json`

模型生命週期：

- bundled seed 只作首次 warm-start，不會被 auto-retrain 改寫。
- 前台 exp4 對局讀取 runtime model。
- quick gate checkpoint 與 full pipeline candidate 都不是 production。
- promotion gate 通過後才把 staged candidate 複製到 runtime model。

完整路徑對照：

- [`../model_artifact_paths.md`](../model_artifact_paths.md)

## 使用方式

前台選擇：

- `實驗 4：Policy/Value + MCTS`

程式呼叫：

```python
from services.games.chess_pv import choose_experiment_pv_move

move = choose_experiment_pv_move(
    board,
    "black",
    search_profile="fast",
    decision_mode="mcts",
)
```

## 後續文件規則

- exp4 的每次架構調整、gate 實跑、benchmark 設計、promotion decision 都寫在本資料夾。
- 不要把 exp3 的 semantic replay success/failure 直接複製成 exp4 結論。
- 每份報告必須標明：
  - model path
  - decision mode
  - deterministic case set
  - policy/value/MCTS evidence
  - promotion verdict

## 目前 exp4 推進狀態

目前 exp4 已接到和 exp3 exp34 同等級的驗收框架：

- quick retrain gate 產生 checkpoint@10 / checkpoint@20。
- smoke gate 通過後會跑 full sanity seen/unseen variants。
- mistake retention probe 會檢查「舊錯修正」與「已學會舊題保留」。
- safe checkpoint selection 不允許 retention-failed checkpoint 成為 promotion final candidate。
- validation artifacts 不會直接覆蓋前台 production model。

已修正的 exp4 專屬問題：

- validation decision path 改為 `decision_mode="mcts"`，避免測試走 alpha-beta 而前台走 MCTS。
- balanced opening 多好棋使用 top3 / multi-good credit，避免同一 starting FEN 中 `e2e4`、`d2d4`、`c2c4`、`g1f3` 被互相誤判。
- quick fixture 後續 filler moves 改成 `fixture_continuation`，不可再污染 mistake retention。
- mistake retention probe 只允許使用 `category=mistake_retention` 樣本，不可退回 fixture continuation。

最新實跑目錄：

- `/home/s92137/chess_results/exp4_02_mcts_opening_multigood`
- `/home/s92137/chess_results/exp4_03_retention_fixture_clean`
- `/home/s92137/chess_results/exp4_04_probe_policy_fixed`

其中 `exp4_04_probe_policy_fixed` 是目前用來驗證「probe policy 修正後」的正式 quick gate artifact。

## 歷程報告

- [2026-05-11 Exp4 對齊 Exp3 Exp34 驗收鏈](2026-05-11_exp4_exp34_gate_alignment.md)
- [2026-05-11 Exp4_05 暫存工作紀錄：opening margin / MCTS 對齊](2026-05-11_exp4_05_working_state_tmp.md)
