from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_markdown_editor_assets_are_wired():
    index_html = (ROOT / "public" / "index.html").read_text(encoding="utf-8")
    markdown_js = (ROOT / "public" / "js" / "34-markdown-editor.js").read_text(encoding="utf-8")
    styles = (ROOT / "public" / "styles.css").read_text(encoding="utf-8")

    assert 'data-markdown-editor="1"' in index_html
    assert '<script src="/js/34-markdown-editor.js" defer></script>' in index_html
    assert "function markdownToSafeHtml" in markdown_js
    assert "function attachMarkdownEditor" in markdown_js
    assert "sanitize(input || \"\")" in markdown_js
    assert ".markdown-toolbar" in styles
    assert ".markdown-preview" in styles
