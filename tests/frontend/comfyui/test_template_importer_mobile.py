"""Mobile-responsive smoke checks for the ComfyUI template importer modal."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]


def _read(path):
    return (ROOT / path).read_text(encoding="utf-8")


def test_index_html_has_viewport_meta_tag():
    """Mobile responsiveness starts with the viewport meta tag — without it
    the browser zooms out and panel labels become illegible."""
    html = _read("public/index.html")
    assert 'name="viewport"' in html, "missing viewport meta — mobile won't scale"
    assert "width=device-width" in html


def test_template_importer_modal_inset_zero_uses_full_viewport():
    """The modal background should fill the viewport on small screens; the
    inline style ``inset:0`` is the canonical CSS trick for that."""
    js = _read("public/js/36-comfyui.js")
    assert 'modalEl.style.inset = "0"' in js


def test_template_importer_modal_caps_card_height_for_scroll():
    """On small screens the modal card must scroll instead of clipping
    inputs off-screen — max-height + overflow:auto is the cheap fix."""
    js = _read("public/js/36-comfyui.js")
    assert "max-height:88vh" in js
    assert "overflow:auto" in js


def test_template_importer_card_uses_viewport_relative_max_width():
    """Avoid hardcoded pixel widths bigger than mobile viewports; the
    `max-width:720px;margin:5vh auto` construct degrades to viewport-fit
    on small screens."""
    js = _read("public/js/36-comfyui.js")
    assert "max-width:720px" in js
    assert "margin:5vh auto" in js


def test_template_importer_field_rows_use_flex_for_wrap():
    """Each field row should use flexbox so on a narrow screen the input
    wraps below its label rather than overflowing horizontally."""
    js = _read("public/js/36-comfyui.js")
    assert 'row.style.display = "flex"' in js
    assert "flex" in js  # double-check inline flex is present


def test_styles_css_carries_mobile_breakpoint_or_responsive_layout():
    """The repo-wide stylesheet should declare at least one mobile media
    query so the surrounding chrome (tabs, header, etc.) reflows at
    narrow widths. We don't dictate exact breakpoints — just require
    *some* responsive declaration is present."""
    css = _read("public/styles.css")
    assert "@media" in css, "styles.css has no media queries"
    # Common phone breakpoints; accept any of them
    assert any(token in css for token in ("max-width: 480px", "max-width: 600px", "max-width: 768px", "max-width: 900px"))
