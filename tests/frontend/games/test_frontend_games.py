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
    game_view_registry_js = (ROOT / "public" / "js" / "games" / "game-view-registry.js").read_text(encoding="utf-8")
    chess_module_js = (ROOT / "public" / "js" / "games" / "chess.js").read_text(encoding="utf-8")
    sudoku_module_js = (ROOT / "public" / "js" / "games" / "sudoku.js").read_text(encoding="utf-8")
    minesweeper_module_js = (ROOT / "public" / "js" / "games" / "minesweeper.js").read_text(encoding="utf-8")
    onea2b_module_js = (ROOT / "public" / "js" / "games" / "onea2b.js").read_text(encoding="utf-8")
    tetris_module_js = (ROOT / "public" / "js" / "games" / "tetris.js").read_text(encoding="utf-8")
    shooter_module_js = (ROOT / "public" / "js" / "games" / "space-shooter.js").read_text(encoding="utf-8")
    fps_module_js = (ROOT / "public" / "js" / "games" / "fps-arena.js").read_text(encoding="utf-8")
    local_snake_js = (ROOT / "public" / "js" / "games" / "snake.js").read_text(encoding="utf-8")
    local_2048_js = (ROOT / "public" / "js" / "games" / "game-2048.js").read_text(encoding="utf-8")
    local_brick_js = (ROOT / "public" / "js" / "games" / "brick-breaker.js").read_text(encoding="utf-8")
    local_bullet_js = (ROOT / "public" / "js" / "games" / "bullet-hell.js").read_text(encoding="utf-8")
    local_stickman_js = (ROOT / "public" / "js" / "games" / "stickman-shooter.js").read_text(encoding="utf-8")
    local_board_shared_js = (ROOT / "public" / "js" / "games" / "board-game-shared.js").read_text(encoding="utf-8")
    local_real_tetris_js = (ROOT / "public" / "js" / "games" / "real-tetris.js").read_text(encoding="utf-8")
    local_reversi_js = (ROOT / "public" / "js" / "games" / "reversi.js").read_text(encoding="utf-8")
    local_go_js = (ROOT / "public" / "js" / "games" / "go.js").read_text(encoding="utf-8")
    local_gomoku_js = (ROOT / "public" / "js" / "games" / "gomoku.js").read_text(encoding="utf-8")
    fps_js = (ROOT / "public" / "js" / "38-fps-arena.js").read_text(encoding="utf-8")
    core_js = (ROOT / "public" / "js" / "00-core.js").read_text(encoding="utf-8")
    bootstrap_js = (ROOT / "public" / "js" / "90-bootstrap.js").read_text(encoding="utf-8")
    styles_css = (ROOT / "public" / "styles.css").read_text(encoding="utf-8")

    assert 'id="tab-module-games"' in index_html
    assert 'id="module-games"' in index_html
    assert "/js/38-games.js?v=20260513-game-shell" in index_html
    assert 'id="game-practice-side"' in index_html
    assert 'id="game-practice-difficulty"' in index_html
    assert 'id="game-offer-draw-btn"' in index_html
    assert 'id="game-offer-draw-btn" type="button" style="display:none;">求和' in index_html
    assert 'id="game-accept-draw-btn"' in index_html
    assert 'id="game-reject-draw-btn"' in index_html
    assert 'id="game-claim-draw-btn"' in index_html
    assert 'id="game-chess-uci-form"' in index_html
    assert 'id="game-chess-uci-input"' in index_html
    assert 'id="game-clock-enabled"' in index_html
    assert 'id="game-clock-preset"' in index_html
    assert 'id="game-clock-main-minutes"' in index_html
    assert 'id="game-clock-increment-seconds"' in index_html
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
    assert 'id="minesweeper-flag-mode-btn"' in index_html
    assert 'aria-pressed="false">插旗模式' in index_html
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
    assert 'fps-arena-reticle-fixed' in index_html
    assert 'fps-arena-reticle-float' in index_html
    assert 'data-game-touch="fps-sprint"' in index_html
    assert 'id="game-fullscreen-btn"' in index_html
    assert 'id="fps-arena-fullscreen-btn"' in index_html
    assert "/js/three.min.js?v=0.160.0" in index_html
    assert "/js/41-game-modules.js?v=20260513-game-registry" in index_html
    assert "/js/games/snake.js?v=20260513-game-modules" in index_html
    assert "/js/games/game-2048.js?v=20260513-game-modules" in index_html
    assert "/js/games/brick-breaker.js?v=20260513-game-modules" in index_html
    assert "/js/games/bullet-hell.js?v=20260513-game-modules" in index_html
    assert "/js/games/stickman-shooter.js?v=20260513-game-modules" in index_html
    assert "/js/games/board-game-shared.js?v=20260513-game-modules" in index_html
    assert "/js/games/real-tetris.js?v=20260513-game-modules" in index_html
    assert "/js/games/reversi.js?v=20260513-game-modules" in index_html
    assert "/js/games/go.js?v=20260513-game-modules" in index_html
    assert "/js/games/gomoku.js?v=20260513-game-modules" in index_html
    assert "/js/games/game-view-registry.js?v=20260513-legacy-modules" in index_html
    assert "/js/games/chess.js?v=20260513-legacy-modules" in index_html
    assert "/js/games/sudoku.js?v=20260513-legacy-modules" in index_html
    assert "/js/games/minesweeper.js?v=20260513-legacy-modules" in index_html
    assert "/js/games/onea2b.js?v=20260513-legacy-modules" in index_html
    assert "/js/games/tetris.js?v=20260513-legacy-modules" in index_html
    assert "/js/games/space-shooter.js?v=20260513-legacy-modules" in index_html
    assert "/js/games/fps-arena.js?v=20260513-legacy-modules" in index_html
    assert "/js/38-fps-arena.js?v=20260512-fps-feedback" in index_html
    assert 'id="game-select"' in games_js
    assert 'id="game-open-page-btn"' not in games_js
    assert "openStandaloneGamePage" not in games_js
    assert "gameShouldOpenInStandalonePage" not in games_js
    assert "mountLocalGameModule" in games_js
    assert "filterAvailableGameCatalog" in games_js
    assert "isLocalGameModuleAvailable" in games_js
    assert "isLocalGameCatalogKey" in games_js
    assert 'id="local-module-game-panel"' in index_html
    assert 'id="local-module-game-root"' in index_html
    assert 'id="local-module-game-controls"' in index_html
    assert "貪食蛇" in index_html
    assert "2048" in index_html
    assert "打磚塊" in index_html
    assert "彈幕遊戲" in index_html
    assert "火柴人橫向射擊" in index_html
    assert "真實版俄羅斯方塊" in index_html
    assert "黑白棋" in index_html
    assert "圍棋" in index_html
    assert "五子棋" in index_html
    assert "使用下拉選單在同一頁切換遊戲" in index_html
    assert "/game.html" not in index_html
    assert "/js/42-game-page.js" not in index_html
    assert "HACKME_GAME_CATALOG" in game_modules_js
    assert "registerHackmeLocalGameModule" in game_modules_js
    assert "HACKME_LOCAL_GAME_HELPERS" in game_modules_js
    assert "hackmeGameDailyChallenge" in game_modules_js
    assert "createHackmeGameSeededRandom" in game_modules_js
    assert "recordHackmeGameAchievement" in game_modules_js
    assert "state.dailyChallenge?.key || api.key" in game_modules_js
    assert "modules.snake" not in game_modules_js
    assert "modules.game_2048" not in game_modules_js
    assert 'registerHackmeLocalGameModule("snake"' in local_snake_js
    assert 'registerHackmeLocalGameModule("game_2048"' in local_2048_js
    assert 'registerHackmeLocalGameModule("brick_breaker"' in local_brick_js
    assert 'registerHackmeLocalGameModule("bullet_hell"' in local_bullet_js
    assert 'registerHackmeLocalGameModule("stickman_shooter"' in local_stickman_js
    assert 'registerHackmeLocalGameModule("real_tetris"' in local_real_tetris_js
    assert "mountHackmeLocalDiscGame" in local_board_shared_js
    assert "data-board-clock" in local_board_shared_js
    assert 'data-action="clock"' in local_board_shared_js
    assert 'data-action="clock-preset"' in local_board_shared_js
    assert "/ai-move" in local_board_shared_js
    assert "AI 思考中" in local_board_shared_js
    assert 'data-action="mode"' in local_board_shared_js
    assert 'data-action="side"' in local_board_shared_js
    assert "玩家先手" in local_board_shared_js
    assert "玩家後手" in local_board_shared_js
    assert 'state.aiColor = other(state.humanColor);' in local_board_shared_js
    assert 'data-action="difficulty"' in local_board_shared_js
    assert "api.request" in local_board_shared_js
    assert 'registerHackmeLocalGameModule("reversi"' in local_reversi_js
    assert 'registerHackmeLocalGameModule("go"' in local_go_js
    assert 'registerHackmeLocalGameModule("gomoku"' in local_gomoku_js
    assert "centerRealTetrisCells" in local_real_tetris_js
    assert "integrateRealTetrisPhysics" in local_real_tetris_js
    assert "resolveRealTetrisCollisions" in local_real_tetris_js
    assert "clearRealTetrisRelaxedLines" in local_real_tetris_js
    assert "applyRealTetrisStackStability" in local_real_tetris_js
    assert "resolveRealTetrisSettledBlockCollisions" in local_real_tetris_js
    assert "realTetrisBlockElasticImpulse" in local_real_tetris_js
    assert "REAL_TETRIS_ROOT_PHYSICS_KEY" in local_real_tetris_js
    assert 'data-real-tetris-param="elasticity"' in local_real_tetris_js
    assert "stackTorque" in local_real_tetris_js
    assert 'data-real-tetris-param="stackDamping"' in local_real_tetris_js
    assert "REAL_TETRIS_MODES" in local_real_tetris_js
    assert "sticky" in local_real_tetris_js
    assert "smooth" in local_real_tetris_js
    assert "body.omega += (rx * ny - ry * nx)" in local_real_tetris_js
    assert "RELAXED_LINE_FILL = 0.78" in local_real_tetris_js
    assert 'api.setSwipeMode?.("hold");' in local_real_tetris_js
    assert 'api.setSwipeMode?.("hold");' in local_brick_js
    assert "showRealTetrisReady(api)" in local_real_tetris_js
    assert "showBulletHellReady(api)" in local_bullet_js
    assert "showStickmanShooterReady(api)" in local_stickman_js
    assert "按開始後才會計時" in local_snake_js
    assert "按開始後才會發球" in local_brick_js
    assert "按開始後才會產生初始方塊" in local_2048_js
    assert "GAME OVER" in local_snake_js
    assert "GAME OVER" in local_brick_js
    assert "GAME OVER" in local_2048_js
    assert "GAME OVER" in local_board_shared_js
    assert 'api.submitScore({' in local_real_tetris_js
    assert 'difficulty: `physics-${state.mode}`' in local_real_tetris_js
    assert 'typeof window.mountHackmeLocalDiscGame !== "function"' in local_reversi_js
    assert 'typeof window.mountHackmeLocalDiscGame !== "function"' in local_go_js
    assert 'typeof window.mountHackmeLocalDiscGame !== "function"' in local_gomoku_js
    assert "touchstart" in games_js
    assert "localGameModuleSwipeMode" in games_js
    assert "toggleGameFullscreen" in games_js
    assert "dailyChallenge(gameKey = gameSelectedKey)" in games_js
    assert "achievement(gameKey, id, label" in games_js
    assert "showGameDailyRewardFeedback" in games_js
    assert "daily_reward" in games_js
    assert "每日任務完成，獲得" in games_js
    assert 'setSwipeMode(mode)' in games_js
    assert 'localGameModuleSwipeMode === "hold"' in games_js
    assert "window.setTimeout(() =>" in games_js
    assert "onKey({ key, preventDefault() {} }, false)" in games_js
    assert "submitLocalGameModuleScore" in games_js
    assert "normalizeSoloScoreTiming" in games_js
    assert "payload.elapsed_ms = rawElapsed + penaltySeconds * 1000" in games_js
    assert "HACKME_GAME_VIEW_MODULES" in game_view_registry_js
    assert "registerHackmeGameViewModule" in game_view_registry_js
    assert 'key: "chess"' in chess_module_js
    assert 'key: "sudoku"' in sudoku_module_js
    assert 'key: "minesweeper"' in minesweeper_module_js
    assert 'key: "1a2b"' in onea2b_module_js
    assert 'key: "tetris"' in tetris_module_js
    assert "TETRIS_SIDE_REPEAT_MS" in tetris_module_js
    assert "tickTetrisInput" in tetris_module_js
    assert "setTetrisHeldKey" in tetris_module_js
    assert "holdTetrisPiece" in tetris_module_js
    assert "nextPiece" in tetris_module_js
    assert "heldPiece" in tetris_module_js
    assert "combo" in tetris_module_js
    assert "refillTetrisBag" in tetris_module_js
    assert 'key: "space_shooter"' in shooter_module_js
    assert "spawnSpaceShooterBoss" in shooter_module_js
    assert "weaponLevel" in shooter_module_js
    assert "enemyBullets" in shooter_module_js
    assert "powerups" in shooter_module_js
    assert 'key: "fps_arena"' in fps_module_js
    assert "dispatchActiveGameViewEvent" in games_js
    assert "legacyGameRuntime" in games_js
    assert "/games/sudoku/solo-leaderboard" in sudoku_module_js
    assert "/games/minesweeper/solo-leaderboard" in minesweeper_module_js
    assert "/games/1a2b/solo-leaderboard" in onea2b_module_js
    assert "/games/tetris/solo-leaderboard" in tetris_module_js
    assert "/games/space_shooter/solo-leaderboard" in shooter_module_js
    assert "/games/fps_arena/solo-leaderboard" in fps_module_js
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
    assert "/games/chess/practice" in chess_module_js
    assert "side = $(\"game-practice-side\")?.value || \"white\"" in chess_module_js
    assert "difficulty = $(\"game-practice-difficulty\")?.value || \"normal\"" in chess_module_js
    assert "隨機走棋" not in index_html
    assert 'data-game-touch="tetris-left"' in index_html
    assert 'data-game-touch="tetris-hold"' in index_html
    assert 'data-game-touch="shooter-fire"' in index_html
    assert 'data-game-touch="fps-fire"' in index_html
    assert "Boss 會發射子彈" in index_html
    assert "gameDifficultyLabel" in chess_module_js
    assert "gameOpponentColor" in chess_module_js
    assert "buildOptimisticChessMatch" in chess_module_js
    assert "normalizeChessUciInput" in chess_module_js
    assert "submitChessUciMove" in chess_module_js
    assert "chessKingSquare" in chess_module_js
    assert "checkmated-king" in chess_module_js
    assert "checked-king" in chess_module_js
    assert "dead-king" in chess_module_js
    assert "current_check" in chess_module_js
    assert "current_king_square" in chess_module_js
    assert "Checkmate：王死，遊戲結束" in chess_module_js
    assert "兵升變請輸入 q / r / b / n" in chess_module_js
    assert "/games/chess/matches/${encodeURIComponent(gameSelectedMatchId)}/offer-draw" in chess_module_js
    assert "/games/chess/matches/${encodeURIComponent(gameSelectedMatchId)}/respond-draw" in chess_module_js
    assert "已提出和棋，等待對方回覆。" in chess_module_js
    assert "已接受和棋，棋局結束。" in chess_module_js
    assert "已拒絕和棋。" in chess_module_js
    assert "目前不能提和，可能已有待回覆的和棋。" in chess_module_js
    assert "目前沒有待回覆的和棋。" in chess_module_js
    assert "/games/chess/matches/${encodeURIComponent(gameSelectedMatchId)}/claim-draw" in chess_module_js
    assert "目前沒有三次重複或 50 步和棋可申請" in chess_module_js
    assert "已申請和棋並結束棋局" in chess_module_js
    assert "renderChessRootDashboard" in chess_module_js
    assert "loadChessRootDashboard" in chess_module_js
    assert "warmStartChessModels" in chess_module_js
    assert "latest_replay_prepare" in chess_module_js
    assert "latest_seed_training_report" in chess_module_js
    assert "latest_pipeline_report" in chess_module_js
    assert "pipeline_recommendation" in chess_module_js
    assert "stageChessCandidate" in chess_module_js
    assert "promoteChessCandidate" in chess_module_js
    assert "renderChessPracticeDifficultyOptions" in chess_module_js
    assert 'if (difficulty === "experiment 4:pv") return "實驗 4：Policy/Value + MCTS";' in chess_module_js
    assert 'if (difficulty === "experiment 5:nnue") return "實驗 5：NNUE + AlphaBeta/PVS";' in chess_module_js
    assert 'if (difficulty === "experiment 2:nn") return "實驗 2：NN";' not in chess_module_js
    assert 'if (difficulty === "experiment 3:dl") return "實驗 3：DL 語義平衡";' in chess_module_js
    assert "/games/chess/leaderboard" in chess_module_js
    assert "/root/games/chess/engines/dashboard" in chess_module_js
    assert "/root/games/chess/warm-start" in chess_module_js
    assert "/root/games/chess/promotion/stage" in chess_module_js
    assert "/root/games/chess/promotion/promote" in chess_module_js
    assert "chess_replay_prepare.py" in chess_module_js
    assert "chess_seed_train.py" in chess_module_js
    assert "chess_exp3_dataset_train.py" in chess_module_js
    assert "chess_train_pipeline.py" in chess_module_js
    assert "fetchCsrfToken({ force: true })" in games_js
    assert "gameRequestNeedsFreshCsrf" in games_js
    assert "const mutates = upperMethod !== \"GET\"" in games_js
    assert "setCsrfToken(null)" in games_js
    assert "refreshGameZoneAfterMutation" in games_js
    assert 'cache: "no-store"' in games_js
    assert "data-chess-square" in chess_module_js
    assert "let chessMoveInFlight = false" in games_js
    assert "if (chessMoveInFlight) return;" in chess_module_js
    assert "const from = gameSelectedSquare;" in chess_module_js
    assert "const optimisticMatch = buildOptimisticChessMatch(match, chosenMove);" in chess_module_js
    assert "UCI 格式需為 d1c2 或 e7e8q。" in chess_module_js
    assert "不是合法走法" in chess_module_js
    assert "這步不需要升變棋子" in chess_module_js
    assert "pending_computer_response" in chess_module_js
    assert "你已走棋，電腦思考中" in chess_module_js
    assert "已送出走棋，等待電腦回應" in chess_module_js
    assert "gameSelectedSquare = null;" in games_js
    assert "chessMoveInFlight = true;" in chess_module_js
    assert "chessMoveInFlight = false;" in chess_module_js
    assert "const isOwnPiece = piece &&" in chess_module_js
    assert "isOwnPiece && myTurn" in chess_module_js
    assert "data-game-delete-match" in chess_module_js
    assert "data-game-key" in games_js
    assert "SUDOKU_PUZZLES" in sudoku_module_js
    assert "SUDOKU_PUZZLES" not in games_js
    assert "startSudokuGame" in sudoku_module_js
    assert "startSudokuGame" not in games_js
    assert "按「開始」後才會出現題目並開始計時" in sudoku_module_js
    assert "sudokuState.penaltySeconds += 10" in sudoku_module_js
    assert "data-sudoku-index" in sudoku_module_js
    assert "startMinesweeperGame" in minesweeper_module_js
    assert "startOneA2BGame" in onea2b_module_js
    assert "startTetrisGame" in tetris_module_js
    assert "tickTetrisGame" in tetris_module_js
    assert "data-tetris-cell" in tetris_module_js
    assert "startSpaceShooterGame" in shooter_module_js
    assert "tickSpaceShooterGame" in shooter_module_js
    assert "toggleMinesweeperFlagMode" in minesweeper_module_js
    assert "updateMinesweeperFlagModeButton" in minesweeper_module_js
    assert "minesweeperState?.flagMode" in minesweeper_module_js
    assert "插旗模式：點格子會切換旗標" in minesweeper_module_js
    assert "fps_arena" in games_js
    assert "real_tetris" in games_js
    assert "bullet_hell" in games_js
    assert "stickman_shooter" in games_js
    assert "彈幕遊戲" in game_modules_js
    assert "火柴人橫向射擊" in game_modules_js
    assert "spawnBulletHellBoss" in local_bullet_js
    assert "spawnStickmanRoom" in local_stickman_js
    assert "fireStickmanShot" in local_stickman_js
    assert 'aiState: "patrol"' in local_stickman_js
    assert "walkCycle" in local_stickman_js
    assert 'enemy.aiState = distance < 92 ? "retreat" : distance > 235 ? "chase" : "hold";' in local_stickman_js
    assert "boss-down" in local_stickman_js
    assert "makeStickmanTraps" in local_stickman_js
    assert "即死陷阱" in local_stickman_js
    assert "makeStickmanCrates" in local_stickman_js
    assert "問號補給" in local_stickman_js
    assert "applyStickmanPowerup" in local_stickman_js
    assert "fireFlower" in local_stickman_js
    assert "stickman-star" in local_stickman_js
    assert "stickman-mushroom" in local_stickman_js
    assert "updateStickmanHazards" in local_stickman_js
    assert "powerups-3" in local_stickman_js
    assert "api.submitScore({" in local_stickman_js
    assert "shotLevel" in local_bullet_js
    assert "nextBossWave" in local_bullet_js
    assert "powerups" in local_bullet_js
    assert "boss-down" in local_bullet_js
    assert "createHackmeCompetitionClock" in game_modules_js
    assert "Rapid 10+0" in game_modules_js
    assert "formatHackmeGameClock" in game_modules_js
    assert "真實版俄羅斯方塊" in game_modules_js
    assert "currentFpsArenaMode" in fps_module_js
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
    assert "FPS_ARENA_PLAYER_RADIUS" in fps_js
    assert "fpsArenaBuildCombatMap" in fps_js
    assert "fpsArenaAddCylinder" in fps_js
    assert "fpsArenaMoveWithCollision" in fps_js
    assert "spawnPoints" in fps_js
    assert "blocksPlayer" in fps_js
    assert "--fps-breathe-rot" in fps_js
    assert "--fps-breathe-scale" in fps_js
    assert "fpsArenaUpdateBotFire" in fps_js
    assert "fpsArenaLineOfSightClear" in fps_js
    assert "botTracers" in fps_js
    assert "botProjectiles" in fps_js
    assert "fpsArenaUpdateBotProjectiles" in fps_js
    assert "fpsArenaProjectileHitsCover" in fps_js
    assert "handleFpsArenaTouchPointerDown" in fps_js
    assert "handleFpsArenaTouchPointerMove" in fps_js
    assert "handleFpsArenaTouchPointerEnd" in fps_js
    assert "fpsArenaApplyLookDelta" in fps_js
    assert 'event.pointerType === "mouse"' in fps_js
    assert "fpsArenaAddPlayerFireEffects" in fps_js
    assert "fpsArenaAddBloodSplatter" in fps_js
    assert "fpsArenaKillTarget" in fps_js
    assert "deadBodies" in fps_js
    assert "mobileSprint" in fps_js
    assert "stamina" in fps_js
    assert "scream" in fps_js
    assert "fpsArenaPlaySound" in fps_js
    assert "fpsArenaAddShake" in fps_js
    assert "navigator.vibrate" in fps_js
    assert "handleGameTouchAction" not in games_js
    assert "handleFpsArenaTouch" in fps_module_js
    assert "chessCompetitionClock" in chess_module_js
    assert "applyChessClockConfig" in chess_module_js
    assert "syncChessClockWithMatch" in chess_module_js
    assert "setOneA2BNotice" in onea2b_module_js
    assert "generateOneA2BSecret" in onea2b_module_js
    assert "scoreOneA2BGuess" in onea2b_module_js
    assert 'digit === "0"' in onea2b_module_js
    assert "/^[1-9][0-9]{3}$/.test(value)" in onea2b_module_js
    assert "首位不可為 0，例如 1234" in onea2b_module_js
    assert "例如 0123" not in games_js
    assert "例如 0123" not in onea2b_module_js
    assert 'submitSoloGameScore("1a2b", oneA2BState)' in onea2b_module_js
    assert 'submitSoloGameScore("tetris", tetrisState)' in tetris_module_js
    assert 'submitSoloGameScore("space_shooter", spaceShooterState)' in shooter_module_js
    assert "guesses_then_time" in games_js
    assert "score_desc" in games_js
    assert "score: Number(state.score || 0)" in games_js
    assert "guess_count" in games_js
    assert "超過 5 分鐘，不列入排行榜" in onea2b_module_js
    assert "startedAt: Date.now()" in sudoku_module_js
    assert "startedAt: Date.now()" in tetris_module_js
    assert "startedAt: Date.now()" in local_snake_js
    assert "solo-leaderboard" in games_js
    assert "solo-scores" in games_js
    assert "rank_mode === \"time_asc\"" in games_js
    assert "#minesweeper-difficulty" in minesweeper_module_js
    assert "data-mine-index" in minesweeper_module_js
    assert "contextmenu" in games_js
    assert "async function deleteFinishedGame" in chess_module_js
    assert "已認輸並結束棋局" in chess_module_js
    assert "這局已經結束，不需要再認輸" in chess_module_js
    assert "請先選擇要認輸的棋局" in chess_module_js
    assert "找不到要刪除的棋局，請先刷新遊戲區" in chess_module_js
    assert "method: \"DELETE\"" in chess_module_js
    assert "grid-template-rows: repeat(8, minmax(0, 1fr))" in styles_css
    assert ".chess-board-grid" in styles_css
    assert ".chess-rank-labels" in styles_css
    assert ".chess-file-labels" in styles_css
    assert ".chess-square.checkmated-king" in styles_css
    assert ".chess-square.checked-king" in styles_css
    assert ".chess-square.dead-king::before" in styles_css
    assert ".chess-uci-form" in styles_css
    assert "padding: 0" in styles_css
    assert ".chess-square span" in styles_css
    assert ".game-match-item" in styles_css
    assert ".sudoku-board" in styles_css
    assert ".minesweeper-board" in styles_css
    assert ".onea2b-history" in styles_css
    assert ".tetris-board" in styles_css
    assert ".real-tetris-canvas" in styles_css
    assert ".real-tetris-root-controls" in styles_css
    assert ".space-shooter-board" in styles_css
    assert ".fps-arena-stage" in styles_css
    assert ".fps-arena-scope" in styles_css
    assert ".fps-arena-reticle" in styles_css
    assert ".fps-arena-damage" in styles_css
    assert "--fps-shake-x" in styles_css
    assert "--fps-breathe-rot" in styles_css
    assert "--fps-breathe-scale" in styles_css
    assert "clamp(96px, 22vw, 150px)" in styles_css
    assert ".game-clock-panel" in styles_css
    assert ".board-game-clock" in styles_css
    assert ".game-board-panel:fullscreen" in styles_css
    assert ".fps-arena-reticle-fixed" in styles_css
    assert ".fps-arena-reticle-float" in styles_css
    assert "var(--panel)" in styles_css
    assert ".arcade-canvas" in styles_css
    assert ".game-2048-board" in styles_css
    assert ".board-game-grid" in styles_css
    assert "touch-action: manipulation" in styles_css
    assert "calc(100dvw - 1.5rem)" in styles_css
    assert "position: sticky;" in styles_css
    assert "grid-template-columns: repeat(auto-fit, minmax(4.6rem, 1fr))" in styles_css
    assert "#local-module-game-actions" in styles_css
    assert ".board-game-grid.gomoku" in styles_css
    assert 'class="standalone-editor-page"' in trading_workflow_html
    assert 'class="editor-bg-grid"' in trading_workflow_html
    assert "radial-gradient(circle at 18% 8%" in trading_workflow_css
    assert "backdrop-filter: blur(12px)" in trading_workflow_css
    assert 'class="standalone-editor-page"' in comfyui_workflow_html
    assert 'class="editor-bg-grid"' in comfyui_workflow_html
    assert "radial-gradient(circle at 18% 8%" in comfyui_workflow_css
    assert "backdrop-filter: blur(12px)" in comfyui_workflow_css
