# Games Documentation Map

本目錄是遊戲模組的教學與操作入口。先從這裡判斷你要處理的是一般遊戲前端、非西洋棋三棋 AI、還是西洋棋實驗引擎。

## 快速入口

| 主題 | 先讀文件 | 適用情境 |
|---|---|---|
| 黑白棋 / 圍棋 / 五子棋 AI 與棋力量化 | [BOARD_AI_BENCHMARK.md](BOARD_AI_BENCHMARK.md) | 要跑三棋 AI benchmark、看 Elo、檢查 skill suite、安裝 KataGo、規劃後續強化 |
| 西洋棋模型檔與 runtime/bundled 邊界 | [chess_model_files.md](chess_model_files.md) | 要理解 exp3/exp4/exp5 模型檔、warm-start、promotion artifact |
| 西洋棋訓練與 replay pipeline | [chess_training_pipeline.md](chess_training_pipeline.md) | 要跑 replay prepare、seed train、self-play、promotion pipeline |
| 西洋棋 debug / engine roadmap | [chess_debug/README.md](chess_debug/README.md) | 要追 exp3/exp4/exp5 歷史與目前治理結論 |

## 遊戲分類

### 同頁本機遊戲模組

這些遊戲由 `public/js/games/*.js` 註冊到同一個遊戲頁，不再使用額外分頁或 `inline/` 資料夾。

- `snake`
- `game_2048`
- `brick_breaker`
- `real_tetris`
- `reversi`
- `go`
- `gomoku`

若本機遊戲模組 JS 沒有載入或沒有註冊成功，前端 catalog 會把該遊戲過濾掉，不會影響其他已載入遊戲。

### 非西洋棋 AI 遊戲

目前三個遊戲有基礎 AI：

- 黑白棋 `reversi`
- 19 路圍棋 `go`
- 五子棋 `gomoku`

runtime AI 入口是 `POST /api/games/<game_key>/ai-move`，只接受這三個 `game_key`。圍棋多一個 `katago` 難度，會呼叫本機 KataGo analysis engine；若尚未安裝，可執行：

```bash
python3 scripts/games/setup_katago.py
```

預設會安裝到 `runtime/katago`，後端會自動偵測，不需要額外 export。若改用自訂路徑，source 該目錄下的 `hackme_katago.env`，或同格式設定 `HACKME_KATAGO_BIN`、`HACKME_KATAGO_CONFIG`、`HACKME_KATAGO_MODEL`。西洋棋不走這條 API。

### 西洋棋

西洋棋仍保留獨立的 match/practice/replay/training/promotion pipeline。不要把三棋 benchmark 或後續三棋神經網路訓練直接塞進西洋棋 `self_play_training.py`；兩邊的模型、報告、promotion gate 要分開。

## 調用地圖

### 使用者玩三棋 AI

1. 使用者在遊戲區選 `黑白棋 / 圍棋 / 五子棋`。
2. 前端模組由 `public/js/games/reversi.js`、`go.js`、`gomoku.js` 註冊。
3. 三棋共用棋盤邏輯在 `public/js/games/board-game-shared.js`。
4. 使用者切到 `對電腦` 後，前端呼叫 `POST /api/games/<game_key>/ai-move`。
5. `routes/games.py` 驗證登入、CSRF、game key、難度與棋盤 payload。
6. `services/games/board_ai.py` 產生 AI 決策；圍棋 `katago` 難度會先找環境變數，再找 `runtime/katago`。
7. 前端套用回傳的 `move/pass/finish`，並留在同一頁。

### 維護者量化三棋棋力

1. 執行 `python3 scripts/games/board_ai_benchmark.py`。
2. CLI 呼叫 `services/games/board_arena.py::run_board_ai_benchmark(...)`。
3. arena 跑 `random/easy/normal/hard` round-robin，並執行 deterministic skill suite。
4. 報告寫到 `runtime/reports/games/board_ai_benchmark_*.json`。
5. 先看 `illegal_moves`、`skill_suite.pass_rate`、`standings.score_rate`、`elo`，再決定是否允許後續 AI 強化或 promotion。

## 放置規則

- 三棋即時 AI：`services/games/board_ai.py`
- 三棋 benchmark / Elo / skill suite：`services/games/board_arena.py`
- 三棋 operator script：`scripts/games/board_ai_benchmark.py`
- KataGo 自動下載 / config 產生：`scripts/games/setup_katago.py`
- 三棋測試：`tests/games/test_board_ai.py`、`tests/games/test_board_arena.py`
- 真實版俄羅斯方塊：`public/js/games/real-tetris.js`
- 西洋棋仍使用 `services/games/chess*.py`、`scripts/games/chess_*.py`、`docs/games/chess_*.md`

新增三棋 AI 強化前，先更新 [BOARD_AI_BENCHMARK.md](BOARD_AI_BENCHMARK.md) 的量化規則與 promotion gate，避免只改演算法但沒有可比較的棋力證據。
