from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_restart_button_waits_for_offline_then_online():
    index_html = (ROOT / "public" / "index.html").read_text(encoding="utf-8")
    admin_js = (ROOT / "public" / "js" / "50-admin.js").read_text(encoding="utf-8")

    assert 'id="restart-server-status"' in index_html
    assert "waitForRestartOffline(25000)" in admin_js
    assert "waitForRestartOnline(previousStartedAt, 180000)" in admin_js
    assert "25 秒內沒有偵測到伺服器離線" in admin_js
    assert "3 分鐘內未重新連線" in admin_js
    assert "location.reload()" in admin_js
