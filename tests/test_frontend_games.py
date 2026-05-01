from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_game_zone_frontend_assets_are_wired():
    index_html = (ROOT / "public" / "index.html").read_text(encoding="utf-8")
    games_js = (ROOT / "public" / "js" / "38-games.js").read_text(encoding="utf-8")
    core_js = (ROOT / "public" / "js" / "00-core.js").read_text(encoding="utf-8")
    bootstrap_js = (ROOT / "public" / "js" / "90-bootstrap.js").read_text(encoding="utf-8")
    styles_css = (ROOT / "public" / "styles.css").read_text(encoding="utf-8")

    assert 'id="tab-module-games"' in index_html
    assert 'id="module-games"' in index_html
    assert "/js/38-games.js?v=20260501-1a2b-rank" in index_html
    assert 'id="game-practice-side"' in index_html
    assert 'id="game-practice-difficulty"' in index_html
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
    assert 'class="drive-collapsible-panel game-rules-panel"' in index_html
    assert "西洋棋玩法說明" in index_html
    assert "數獨玩法說明" in index_html
    assert "踩地雷玩法說明" in index_html
    assert "1A2B 玩法說明" in index_html
    assert "<details" in index_html
    assert "<details class=\"drive-collapsible-panel game-rules-panel\" open" not in index_html
    assert 'module: "games"' in core_js
    assert 'switchModuleTab("games")' in bootstrap_js
    assert "/games/chess/practice" in games_js
    assert "side = $(\"game-practice-side\")?.value || \"white\"" in games_js
    assert "difficulty = $(\"game-practice-difficulty\")?.value || \"easy\"" in games_js
    assert "gameDifficultyLabel" in games_js
    assert "/games/chess/leaderboard" in games_js
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
    assert "generateOneA2BSecret" in games_js
    assert "scoreOneA2BGuess" in games_js
    assert 'digit === "0"' in games_js
    assert "/^[1-9][0-9]{3}$/.test(value)" in games_js
    assert "首位不可為 0，例如 1234" in games_js
    assert "例如 0123" not in games_js
    assert 'submitSoloGameScore("1a2b", oneA2BState)' in games_js
    assert "guesses_then_time" in games_js
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
    assert "method: \"DELETE\"" in games_js
    assert "grid-template-rows: repeat(8, minmax(0, 1fr))" in styles_css
    assert "padding: 0" in styles_css
    assert ".chess-square span" in styles_css
    assert ".game-match-item" in styles_css
    assert ".sudoku-board" in styles_css
    assert ".minesweeper-board" in styles_css
    assert ".onea2b-history" in styles_css
