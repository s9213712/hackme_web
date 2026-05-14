from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]


def test_grid_fee_ui_shows_net_profit_break_even_and_confirmation_wiring():
    index_html = (ROOT / "public" / "index.html").read_text(encoding="utf-8")
    trading_js = (ROOT / "public" / "js" / "56-trading.js").read_text(encoding="utf-8")

    assert 'id="trading-grid-preview"' in index_html
    assert "trading/grid/preview" in trading_js
    assert "網格費率試算（限價掛單 / maker）" in trading_js
    assert "損益兩平間距" in trading_js
    assert "最不利一格毛利" in trading_js
    assert "最不利一格手續費" in trading_js
    assert "最不利一格扣費後淨利" in trading_js
    assert "預估一輪全格總手續費" in trading_js
    assert "feePerTrade" not in trading_js
    assert "feePerBuyOrder" in trading_js
    assert "confirm_thin_profit" in trading_js
    assert "利潤過薄" in trading_js
