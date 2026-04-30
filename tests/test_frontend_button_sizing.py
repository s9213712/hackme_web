from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]


def _block(css, selector):
    start = css.index(selector)
    open_brace = css.index("{", start)
    close_brace = css.index("}", open_brace)
    return css[open_brace + 1:close_brace]


def _rule_block(css, selector):
    pattern = re.compile(rf"^\s*{re.escape(selector)}\s*\{{(?P<body>.*?)^\s*\}}", re.MULTILINE | re.DOTALL)
    match = pattern.search(css)
    assert match, f"{selector} rule not found"
    return match.group("body")


def test_global_buttons_are_content_sized_and_wrap_long_labels():
    css = (ROOT / "public" / "styles.css").read_text(encoding="utf-8")
    btn = _rule_block(css, ".btn")

    assert "width: auto;" in btn
    assert "max-width: 100%;" in btn
    assert "display: inline-flex;" in btn
    assert "white-space: normal;" in btn
    assert "overflow-wrap: anywhere;" in btn
    assert "font-size: .84rem;" in btn
    assert "padding: .5rem .78rem;" in btn


def test_toolbar_and_tabs_do_not_force_oversized_buttons():
    css = (ROOT / "public" / "styles.css").read_text(encoding="utf-8")

    toolbar_btn = _block(css, ".admin-toolbar .btn")
    assert "width: auto;" in toolbar_btn
    assert "flex: 0 1 auto;" in toolbar_btn

    tabs = _block(css, ".tabs:not(.sidebar-nav)")
    assert "flex-wrap: wrap;" in tabs

    tab = _rule_block(css, ".tab")
    assert "flex: 1 1 7rem;" in tab
    assert "white-space: normal;" in tab
    assert "overflow-wrap: anywhere;" in tab


def test_small_button_class_uses_compact_dimensions():
    css = (ROOT / "public" / "styles.css").read_text(encoding="utf-8")
    small = _block(css, ".btn-sm,")

    assert "width: auto;" in small
    assert "min-height: 1.95rem;" in small
    assert "font-size: .76rem;" in small
    assert "overflow-wrap: anywhere;" in small
