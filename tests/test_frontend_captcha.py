from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_captcha_ui_and_settings_are_wired():
    index_html = (ROOT / "public" / "index.html").read_text(encoding="utf-8")
    auth_js = (ROOT / "public" / "js" / "40-auth-users.js").read_text(encoding="utf-8")
    admin_js = (ROOT / "public" / "js" / "50-admin.js").read_text(encoding="utf-8")
    bootstrap_js = (ROOT / "public" / "js" / "90-bootstrap.js").read_text(encoding="utf-8")

    assert 'id="captcha-field"' in index_html
    assert 'id="captcha-answer"' in index_html
    assert 'id="s-captcha-mode"' in index_html
    assert "async function loadCaptchaChallenge()" in auth_js
    assert 'apiFetch(API + "/captcha/challenge"' in auth_js
    assert "captcha_answer" in auth_js
    assert "captcha_mode" in admin_js
    assert "captcha_ttl_seconds" in admin_js
    assert 'captchaRefresh.addEventListener("click", loadCaptchaChallenge)' in bootstrap_js
