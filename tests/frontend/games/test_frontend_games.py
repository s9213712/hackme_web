from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]


def test_game_zone_frontend_assets_are_wired():
    index_html = (ROOT / "public" / "index.html").read_text(encoding="utf-8")
    trading_workflow_html = (ROOT / "public" / "trading-workflow-editor.html").read_text(encoding="utf-8")
    trading_workflow_css = (ROOT / "public" / "trading-workflow-editor.css").read_text(encoding="utf-8")
    comfyui_workflow_html = (ROOT / "public" / "comfyui-workflow-editor.html").read_text(encoding="utf-8")
    comfyui_workflow_css = (ROOT / "public" / "comfyui-workflow-editor.css").read_text(encoding="utf-8")
    games_js = (ROOT / "public" / "js" / "38-games.js").read_text(encoding="utf-8")
    game_modules_js = (ROOT / "public" / "js" / "41-game-modules.js").read_text(encoding="utf-8")
    fps_js = (ROOT / "public" / "js" / "38-fps-arena.js").read_text(encoding="utf-8")
    core_js = (ROOT / "public" / "js" / "00-core.js").read_text(encoding="utf-8")
    bootstrap_js = (ROOT / "public" / "js" / "90-bootstrap.js").read_text(encoding="utf-8")
    styles_css = (ROOT / "public" / "styles.css").read_text(encoding="utf-8")

    assert 'id="tab-module-games"' in index_html
    assert 'id="module-games"' in index_html
    assert "/js/38-games.js?v=20260512-inline-games" in index_html
    assert 'id="game-practice-side"' in index_html
    assert 'id="game-practice-difficulty"' in index_html
    assert 'id="game-offer-draw-btn"' in index_html
    assert 'id="game-accept-draw-btn"' in index_html
    assert 'id="game-reject-draw-btn"' in index_html
    assert 'id="game-claim-draw-btn"' in index_html
    assert 'id="game-chess-uci-form"' in index_html
    assert 'id="game-chess-uci-input"' in index_html
    assert 'placeholder="d1c2 / e7e8q"' in index_html
    assert 'id="game-root-chess-panel"' in index_html
    assert 'id="game-root-chess-refresh-btn"' in index_html
    assert 'id="game-root-chess-warm-start-btn"' in index_html
    assert 'id="game-root-chess-pipeline"' in index_html
    assert 'id="game-root-chess-prepare-command"' in index_html
    assert 'id="game-root-chess-seed-command"' in index_html
    assert 'id="game-root-chess-exp3-command"' in index_html
    assert 'id="game-root-chess-benchmark-command"' in index_html
    assert 'id="game-root-chess-pipeline-command"' in index_html
    assert 'id="game-root-chess-stage-btn"' in index_html
    assert 'id="game-root-chess-promote-btn"' in index_html
    assert 'value="experiment 3:dl"' in index_html
    assert 'value="experiment 4:pv"' in index_html
    assert 'value="experiment 5:nnue"' in index_html
    assert 'value="experiment 2:nn"' not in index_html
    assert "實驗 2：NN 小型神經網路" not in index_html
    assert "實驗 3：DL 語義平衡學習" in index_html
    assert "實驗 4：Policy/Value + MCTS" in index_html
    assert "實驗 5：NNUE + AlphaBeta/PVS" in index_html
    assert 'id="sudoku-game-panel"' in index_html
    assert 'id="sudoku-board"' in index_html
    assert 'id="minesweeper-game-panel"' in index_html
    assert 'id="minesweeper-board"' in index_html
    assert 'id="minesweeper-difficulty"' in index_html
    assert 'id="onea2b-game-panel"' in index_html
    assert 'id="onea2b-guess-input"' in index_html
    assert 'placeholder="例如 1234"' in index_html
    assert 'placeholder="例如 0123"' not in index_html
    assert 'id="onea2b-history"' in index_html
    assert 'id="tetris-game-panel"' in index_html
    assert 'id="tetris-board"' in index_html
    assert 'id="tetris-pause-btn"' in index_html
    assert 'id="space-shooter-game-panel"' in index_html
    assert 'id="space-shooter-board"' in index_html
    assert 'id="fps-arena-game-panel"' in index_html
    assert 'id="fps-arena-stage"' in index_html
    assert 'id="fps-arena-mode"' in index_html
    assert 'class="fps-arena-scope"' in index_html
    assert 'class="fps-arena-damage"' in index_html
    assert "/js/three.min.js?v=0.160.0" in index_html
    assert "/js/41-game-modules.js?v=20260512-arcade-six" in index_html
    assert "/js/38-fps-arena.js?v=20260512-fps-feedback" in index_html
    assert 'id="game-select"' in games_js
    assert 'id="game-open-page-btn"' not in games_js
    assert "openStandaloneGamePage" not in games_js
    assert "gameShouldOpenInStandalonePage" not in games_js
    assert "mountInlineModuleGame" in games_js
    assert "INLINE_MODULE_GAME_KEYS" in games_js
    assert 'id="inline-module-game-panel"' in index_html
    assert 'id="inline-module-game-root"' in index_html
    assert 'id="inline-module-game-controls"' in index_html
    assert "貪食蛇" in index_html
    assert "2048" in index_html
    assert "打磚塊" in index_html
    assert "黑白棋" in index_html
    assert "圍棋" in index_html
    assert "五子棋" in index_html
    assert "使用下拉選單在同一頁切換遊戲" in index_html
    assert "/game.html" not in index_html
    assert "/js/42-game-page.js" not in index_html
    assert "HACKME_GAME_CATALOG" in game_modules_js
    assert "modules.snake" in game_modules_js
    assert "modules.game_2048" in game_modules_js
    assert "modules.brick_breaker" in game_modules_js
    assert "modules.reversi" in game_modules_js
    assert "modules.go" in game_modules_js
    assert "modules.gomoku" in game_modules_js
    assert "touchstart" in games_js
    assert "submitInlineModuleScore" in games_js
    assert "gameInitialSelectedKey" in games_js
    assert "requestedModuleParam === \"games\"" in core_js
    assert "game-standalone-mode" not in games_js
    assert "game-standalone-mode" not in styles_css
    assert 'class="drive-collapsible-panel game-rules-panel"' in index_html
    assert "西洋棋玩法說明" in index_html
    assert "數獨玩法說明" in index_html
    assert "踩地雷玩法說明" in index_html
    assert "1A2B 玩法說明" in index_html
    assert "俄羅斯方塊玩法說明" in index_html
    assert "宇宙戰機玩法說明" in index_html
    assert "3D 射擊場玩法說明" in index_html
    assert "<details" in index_html
    assert "<details class=\"drive-collapsible-panel game-rules-panel\" open" not in index_html
    assert 'module: "games"' in core_js
    assert 'switchModuleTab("games")' in bootstrap_js
    assert "/games/chess/practice" in games_js
    assert "side = $(\"game-practice-side\")?.value || \"white\"" in games_js
    assert "difficulty = $(\"game-practice-difficulty\")?.value || \"normal\"" in games_js
    assert "隨機走棋" not in index_html
    assert 'data-game-touch="tetris-left"' in index_html
    assert 'data-game-touch="shooter-fire"' in index_html
    assert 'data-game-touch="fps-fire"' in index_html
    assert "gameDifficultyLabel" in games_js
    assert "gameOpponentColor" in games_js
    assert "buildOptimisticChessMatch" in games_js
    assert "normalizeChessUciInput" in games_js
    assert "submitChessUciMove" in games_js
    assert "chessKingSquare" in games_js
    assert "checkmated-king" in games_js
    assert "兵升變請輸入 q / r / b / n" in games_js
    assert "/games/chess/matches/${encodeURIComponent(gameSelectedMatchId)}/offer-draw" in games_js
    assert "/games/chess/matches/${encodeURIComponent(gameSelectedMatchId)}/respond-draw" in games_js
    assert "已提出和棋，等待對方回覆。" in games_js
    assert "已接受和棋，棋局結束。" in games_js
    assert "已拒絕和棋。" in games_js
    assert "目前不能提和，可能已有待回覆的和棋。" in games_js
    assert "目前沒有待回覆的和棋。" in games_js
    assert "/games/chess/matches/${encodeURIComponent(gameSelectedMatchId)}/claim-draw" in games_js
    assert "目前沒有三次重複或 50 步和棋可申請" in games_js
    assert "已申請和棋並結束棋局" in games_js
    assert "renderChessRootDashboard" in games_js
    assert "loadChessRootDashboard" in games_js
    assert "warmStartChessModels" in games_js
    assert "latest_replay_prepare" in games_js
    assert "latest_seed_training_report" in games_js
    assert "latest_pipeline_report" in games_js
    assert "pipeline_recommendation" in games_js
    assert "stageChessCandidate" in games_js
    assert "promoteChessCandidate" in games_js
    assert "renderChessPracticeDifficultyOptions" in games_js
    assert 'if (difficulty === "experiment 4:pv") return "實驗 4：Policy/Value + MCTS";' in games_js
    assert 'if (difficulty === "experiment 5:nnue") return "實驗 5：NNUE + AlphaBeta/PVS";' in games_js
    assert 'if (difficulty === "experiment 2:nn") return "實驗 2：NN";' not in games_js
    assert 'if (difficulty === "experiment 3:dl") return "實驗 3：DL 語義平衡";' in games_js
    assert "/games/chess/leaderboard" in games_js
    assert "/root/games/chess/engines/dashboard" in games_js
    assert "/root/games/chess/warm-start" in games_js
    assert "/root/games/chess/promotion/stage" in games_js
    assert "/root/games/chess/promotion/promote" in games_js
    assert "chess_replay_prepare.py" in games_js
    assert "chess_seed_train.py" in games_js
    assert "chess_exp3_dataset_train.py" in games_js
    assert "chess_train_pipeline.py" in games_js
    assert "fetchCsrfToken({ force: true })" in games_js
    assert "gameRequestNeedsFreshCsrf" in games_js
    assert "const mutates = upperMethod !== \"GET\"" in games_js
    assert "setCsrfToken(null)" in games_js
    assert "refreshGameZoneAfterMutation" in games_js
    assert 'cache: "no-store"' in games_js
    assert "data-chess-square" in games_js
    assert "let chessMoveInFlight = false" in games_js
    assert "if (chessMoveInFlight) return;" in games_js
    assert "const from = gameSelectedSquare;" in games_js
    assert "const optimisticMatch = buildOptimisticChessMatch(match, chosenMove);" in games_js
    assert "UCI 格式需為 d1c2 或 e7e8q。" in games_js
    assert "不是合法走法" in games_js
    assert "這步不需要升變棋子" in games_js
    assert "pending_computer_response" in games_js
    assert "你已走棋，電腦思考中" in games_js
    assert "已送出走棋，等待電腦回應" in games_js
    assert "gameSelectedSquare = null;" in games_js
    assert "chessMoveInFlight = true;" in games_js
    assert "chessMoveInFlight = false;" in games_js
    assert "const isOwnPiece = piece &&" in games_js
    assert "isOwnPiece && myTurn" in games_js
    assert "data-game-delete-match" in games_js
    assert "data-game-key" in games_js
    assert "SUDOKU_PUZZLES" in games_js
    assert "startSudokuGame" in games_js
    assert "按「開始」後才會出現題目並開始計時" in games_js
    assert "sudokuState.penaltySeconds += 10" in games_js
    assert "data-sudoku-index" in games_js
    assert "startMinesweeperGame" in games_js
    assert "startOneA2BGame" in games_js
    assert "startTetrisGame" in games_js
    assert "tickTetrisGame" in games_js
    assert "data-tetris-cell" in games_js
    assert "startSpaceShooterGame" in games_js
    assert "tickSpaceShooterGame" in games_js
    assert "fps_arena" in games_js
    assert "currentFpsArenaMode" in games_js
    assert "startFpsArenaGame" in fps_js
    assert "Aim Trainer" in fps_js
    assert "PvE Arena" in fps_js
    assert "Bomb Defuse" in fps_js
    assert "Bot Match" in fps_js
    assert 'submitSoloGameScore("fps_arena", state)' in fps_js
    assert "new THREE.WebGLRenderer" in fps_js
    assert "new THREE.CapsuleGeometry" in fps_js
    assert "fpsArenaRegisterHumanPart" in fps_js
    assert "breathOffset" in fps_js
    assert "FPS_ARENA_SCOPE_SWAY" in fps_js
    assert "FPS_ARENA_BOT_FIRE_RANGE" in fps_js
    assert "fpsArenaUpdateBotFire" in fps_js
    assert "fpsArenaLineOfSightClear" in fps_js
    assert "botTracers" in fps_js
    assert "botProjectiles" in fps_js
    assert "fpsArenaUpdateBotProjectiles" in fps_js
    assert "fpsArenaProjectileHitsCover" in fps_js
    assert "fpsArenaAddPlayerFireEffects" in fps_js
    assert "fpsArenaPlaySound" in fps_js
    assert "fpsArenaAddShake" in fps_js
    assert "navigator.vibrate" in fps_js
    assert "handleGameTouchAction" in games_js
    assert "setOneA2BNotice" in games_js
    assert "generateOneA2BSecret" in games_js
    assert "scoreOneA2BGuess" in games_js
    assert 'digit === "0"' in games_js
    assert "/^[1-9][0-9]{3}$/.test(value)" in games_js
    assert "首位不可為 0，例如 1234" in games_js
    assert "例如 0123" not in games_js
    assert 'submitSoloGameScore("1a2b", oneA2BState)' in games_js
    assert 'submitSoloGameScore("tetris", tetrisState)' in games_js
    assert 'submitSoloGameScore("space_shooter", spaceShooterState)' in games_js
    assert "guesses_then_time" in games_js
    assert "score_desc" in games_js
    assert "score: Number(state.score || 0)" in games_js
    assert "guess_count" in games_js
    assert "超過 5 分鐘，不列入排行榜" in games_js
    assert "startedAt: Date.now()" in games_js
    assert "solo-leaderboard" in games_js
    assert "solo-scores" in games_js
    assert "rank_mode === \"time_asc\"" in games_js
    assert "#minesweeper-difficulty" in games_js
    assert "data-mine-index" in games_js
    assert "contextmenu" in games_js
    assert "async function deleteFinishedGame" in games_js
    assert "已認輸並結束棋局" in games_js
    assert "這局已經結束，不需要再認輸" in games_js
    assert "請先選擇要認輸的棋局" in games_js
    assert "找不到要刪除的棋局，請先刷新遊戲區" in games_js
    assert "method: \"DELETE\"" in games_js
    assert "grid-template-rows: repeat(8, minmax(0, 1fr))" in styles_css
    assert ".chess-board-grid" in styles_css
    assert ".chess-rank-labels" in styles_css
    assert ".chess-file-labels" in styles_css
    assert ".chess-square.checkmated-king" in styles_css
    assert ".chess-uci-form" in styles_css
    assert "padding: 0" in styles_css
    assert ".chess-square span" in styles_css
    assert ".game-match-item" in styles_css
    assert ".sudoku-board" in styles_css
    assert ".minesweeper-board" in styles_css
    assert ".onea2b-history" in styles_css
    assert ".tetris-board" in styles_css
    assert ".space-shooter-board" in styles_css
    assert ".fps-arena-stage" in styles_css
    assert ".fps-arena-scope" in styles_css
    assert ".fps-arena-reticle" in styles_css
    assert ".fps-arena-damage" in styles_css
    assert "--fps-shake-x" in styles_css
    assert "var(--panel)" in styles_css
    assert ".arcade-canvas" in styles_css
    assert ".game-2048-board" in styles_css
    assert ".board-game-grid" in styles_css
    assert 'class="standalone-editor-page"' in trading_workflow_html
    assert 'class="editor-bg-grid"' in trading_workflow_html
    assert "radial-gradient(circle at 18% 8%" in trading_workflow_css
    assert "backdrop-filter: blur(12px)" in trading_workflow_css
    assert 'class="standalone-editor-page"' in comfyui_workflow_html
    assert 'class="editor-bg-grid"' in comfyui_workflow_html
    assert "radial-gradient(circle at 18% 8%" in comfyui_workflow_css
    assert "backdrop-filter: blur(12px)" in comfyui_workflow_css
