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
    assert "/js/38-games.js?v=20260429-game-refresh-csrf" in index_html
    assert 'module: "games"' in core_js
    assert 'switchModuleTab("games")' in bootstrap_js
    assert "/games/chess/practice" in games_js
    assert "/games/chess/leaderboard" in games_js
    assert "fetchCsrfToken({ force: true })" in games_js
    assert "gameRequestNeedsFreshCsrf" in games_js
    assert "const mutates = upperMethod !== \"GET\"" in games_js
    assert "_csrfToken = null" in games_js
    assert "refreshGameZoneAfterMutation" in games_js
    assert 'cache: "no-store"' in games_js
    assert "data-chess-square" in games_js
    assert "grid-template-rows: repeat(8, minmax(0, 1fr))" in styles_css
    assert "padding: 0" in styles_css
    assert ".chess-square span" in styles_css
