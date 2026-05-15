from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]


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

    assert "data-notification-read-all" not in notifications_js
    assert "一鍵全部已讀" not in notifications_js
    assert "readAll.disabled = n <= 0" in notifications_js
    assert "const NOTIFICATION_POLL_MS = 60000" in notifications_js
    assert "const NOTIFICATION_INITIAL_DELAY_MS = 10000" in notifications_js
    assert "notificationPollBusy" in notifications_js
    assert "document.hidden" in notifications_js
    assert "loadNotifications({ force: true })" in notifications_js
    assert 'apiFetch(API + "/notifications?limit=20"' in notifications_js
    assert 'apiFetch(API + `/notifications/${notificationId}/read`' in notifications_js
    assert 'apiFetch(API + "/notifications/read-all"' in notifications_js
