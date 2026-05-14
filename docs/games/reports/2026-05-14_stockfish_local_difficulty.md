# 2026-05-14 Stockfish Local Difficulty

## Summary

新增西洋棋 `stockfish` 難度。它只會在 server 偵測到本機可執行
Stockfish UCI binary 時出現在遊戲目錄與難度選單；repo 不提交、不下載、
不打包 Stockfish binary 或 NNUE 檔。

## Visibility Rule

後端會依序解析：

1. `HTML_LEARNING_CHESS_STOCKFISH_PATH`
2. `STOCKFISH_PATH`
3. `stockfish` on `PATH`
4. `~/reference_repos/Stockfish/src/stockfish`

只有解析到存在且可執行的 binary 時，`/api/games/catalog` 才會回傳：

```json
{"key":"stockfish","label":"Stockfish（本機）","local_only":true}
```

若 binary 不存在，線上環境與一般使用者看不到這個難度；若有人要使用，
需要自行下載、編譯並透過上述路徑提供 binary。

## Runtime Settings

- `HTML_LEARNING_CHESS_STOCKFISH_DEPTH`: 預設 `10`。
- `HTML_LEARNING_CHESS_STOCKFISH_MOVETIME_MS`: 預設 `0`，代表使用 depth。

非法整數設定會退回預設值，不會讓走棋 API 直接失敗。

## License Boundary

本 repo 只提供外部 UCI adapter 與本機偵測邏輯，沒有散布 Stockfish binary、
NNUE 權重或開局庫，因此不把 Stockfish 當成網站部署依賴，也不在 UI 中加入
bundled-engine 版權宣告。

若未來任何部署、壓縮包或 release 直接夾帶 Stockfish 或其 NNUE 資產，必須
隨該散布物保留 GPL/copyright/source 對應義務。

## Changed Files

- `services/games/chess_stockfish_teacher.py`
  - 新增本機 UCI Stockfish adapter。
  - 同時供 teacher audit 與 runtime `stockfish` 難度使用。
- `routes/games.py`
  - catalog 動態加入 `stockfish`。
  - practice difficulty 只有在 binary 可用時接受 `stockfish`。
  - DB enum/check 保留 `stockfish`，避免已建立的本機對局紀錄失效。
- `public/js/games/chess.js`
  - 新增 `Stockfish（本機）` label 與說明。
- `public/js/41-game-modules.js`
  - 新增 chess strength text。
- `scripts/games/chess_stockfish_teacher_audit.py`
  - 記錄為可維護的本機外部 teacher/filter 腳本。
- `bootstrap.schema.sql`
  - 同步 `game_matches.computer_difficulty` check constraint。
- `tests/games/test_games.py`
  - 覆蓋 catalog 隱藏/顯示與 practice 接受/拒絕。
- `tests/frontend/games/test_frontend_games.py`
  - 確認靜態 HTML 不硬塞 Stockfish option，前端 label 可顯示。

## Verification

已通過：

```text
python3 -m py_compile routes/games.py services/games/chess_stockfish_teacher.py \
  scripts/games/chess_stockfish_teacher_audit.py scripts/games/chess_exp5_teacher_distill.py

python3 -c "... stockfish_available/resolve_stockfish_path/choose_stockfish_move ..."

python3 -m pytest -q \
  tests/games/test_games.py::test_game_matches_difficulty_enum_in_sync_across_bootstrap_and_runtime \
  tests/games/test_games.py::test_game_catalog_includes_solo_games \
  tests/games/test_games.py::test_game_catalog_adds_stockfish_only_when_local_binary_available \
  tests/games/test_games.py::test_chess_practice_difficulty_is_persisted_and_rejects_invalid_value \
  tests/frontend/games/test_frontend_games.py::test_game_zone_frontend_assets_are_wired
```

Targeted pytest result:

```text
5 passed
```
