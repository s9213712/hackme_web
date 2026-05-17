from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]


def test_language_switcher_is_wired_into_frontend():
    index_html = (ROOT / "public" / "index.html").read_text(encoding="utf-8")
    switcher_css = (ROOT / "public" / "i18n-language-switcher.css").read_text(encoding="utf-8")
    i18n_js = (ROOT / "public" / "js" / "05-i18n.js").read_text(encoding="utf-8")

    assert 'id="app-language-select"' in index_html
    assert 'data-language-select' in index_html
    assert '/js/05-i18n.js?v=' in index_html
    assert "/i18n-language-switcher.css?v=" in index_html
    assert ".global-language-switcher" in switcher_css
    assert "body.app-authenticated .global-language-switcher:not(.global-language-switcher-inline)" in switcher_css
    assert "top: 3.72rem;" in switcher_css

    assert "SUPPORTED_LOCALES" in i18n_js
    assert "'zh-TW': '繁體中文'" in i18n_js
    assert "en: 'English'" in i18n_js
    assert "hackme_web.locale" in i18n_js
    assert "MutationObserver" in i18n_js
    assert "scopedElementRoot" in i18n_js
    assert "window.setAppLocale = setLocale;" in i18n_js
    assert "window.translateUiText = translateSourceText;" in i18n_js


def test_standalone_editors_share_language_switcher():
    pages = [
        ROOT / "public" / "trading-workflow-editor.html",
        ROOT / "public" / "comfyui-workflow-editor.html",
    ]
    for page in pages:
        html = page.read_text(encoding="utf-8")
        assert 'id="app-language-select"' in html
        assert 'data-language-select' in html
        assert "/i18n-language-switcher.css?v=" in html
        assert "/js/05-i18n.js?v=" in html


def test_initial_english_dictionary_covers_core_navigation_and_auth():
    i18n_js = (ROOT / "public" / "js" / "05-i18n.js").read_text(encoding="utf-8")

    expected_pairs = {
        "'登入': 'Log in'",
        "'註冊': 'Register'",
        "'帳號': 'Username'",
        "'密碼': 'Password'",
        "'聊天': 'Chat'",
        "'個人面板': 'Profile'",
        "'雲端硬碟': 'Cloud Drive'",
        "'任務中心': 'Job Center'",
        "'分享管理': 'Share Management'",
        "'帳號管理': 'Account Management'",
        "'安全中心': 'Security Center'",
    }
    missing = [pair for pair in expected_pairs if pair not in i18n_js]
    assert not missing


def test_english_dictionary_has_cjk_phrase_fallback_for_mixed_ui_text():
    i18n_js = (ROOT / "public" / "js" / "05-i18n.js").read_text(encoding="utf-8")

    assert "translateByPhraseFallback" in i18n_js
    assert "hasCjkText(trimmed)" in i18n_js
    assert ".filter((key) => key.length >= 2)" in i18n_js

    expected_pairs = {
        "'剩餘容量': 'Remaining capacity'",
        "'單檔限制': 'Single-file limit'",
        "'測試 / 內測 token（可取代密碼）': 'Test / internal test token (can replace password)'",
        "'發布影音': 'Publish media'",
        "'Stockfish 深度': 'Stockfish depth'",
        "'Civitai 模型頁網址': 'Civitai model page URL'",
    }
    missing = [pair for pair in expected_pairs if pair not in i18n_js]
    assert not missing
