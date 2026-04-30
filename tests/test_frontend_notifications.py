from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_notification_ui_assets_are_wired():
    index_html = (ROOT / "public" / "index.html").read_text(encoding="utf-8")
    core_js = (ROOT / "public" / "js" / "00-core.js").read_text(encoding="utf-8")
    bootstrap_js = (ROOT / "public" / "js" / "90-bootstrap.js").read_text(encoding="utf-8")
    notifications_js = (ROOT / "public" / "js" / "32-notifications.js").read_text(encoding="utf-8")

    assert 'id="notification-toggle"' in index_html
    assert 'id="notification-badge"' in index_html
    assert 'id="notification-list"' in index_html
    assert 'src="/js/32-notifications.js' in index_html

    assert "startNotificationPoll()" in core_js
    assert "stopNotificationPoll()" in core_js
    assert "notification-toggle" in bootstrap_js
    assert "notification-read-all" in bootstrap_js

    assert 'fetch(API + "/notifications?limit=20"' in notifications_js
    assert 'fetch(API + `/notifications/${notificationId}/read`' in notifications_js
    assert 'fetch(API + "/notifications/read-all"' in notifications_js
