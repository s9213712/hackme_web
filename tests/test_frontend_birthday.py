from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CORE_JS = ROOT / "public" / "js" / "00-core.js"
STYLES_CSS = ROOT / "public" / "styles.css"


def test_birthday_easter_egg_is_wired_to_birthdate_month_day():
    source = CORE_JS.read_text(encoding="utf-8")

    assert "function isBirthdayToday(birthdate)" in source
    assert "normalized.match(/^(\\d{4})-(\\d{2})-(\\d{2})$/)" in source
    assert "today.getMonth() + 1 === month && today.getDate() === day" in source
    assert "isBirthdayToday(json.birthdate)" in source
    assert "生日快樂" in source
    assert "welcomeMsg.classList.add(\"birthday-greeting\")" in source


def test_birthday_easter_egg_has_visible_style():
    styles = STYLES_CSS.read_text(encoding="utf-8")

    assert ".birthday-greeting" in styles
    assert "birthday-pop" in styles
    assert "birthday-glow" in styles

