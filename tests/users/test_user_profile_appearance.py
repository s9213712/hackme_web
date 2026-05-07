import sqlite3

from services.users.profiles import (
    clear_profile_appearance,
    ensure_user_profile_schema,
    get_profile_appearance,
    update_profile_appearance,
)


def _conn():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, username TEXT)")
    conn.execute("INSERT INTO users (id, username) VALUES (1, 'alice')")
    return conn


def test_user_profile_appearance_roundtrip_and_reset():
    conn = _conn()
    ensure_user_profile_schema(conn)
    actor = {"id": 1, "username": "alice"}

    saved = update_profile_appearance(conn, actor=actor, data={
        "site_font_family": "serif",
        "site_background_style": "aurora",
        "site_panel_style": "solid",
        "site_sidebar_width": "wide",
        "site_bg": "#101820",
        "site_surface": "#1b263b",
        "site_accent": "#ff7f50",
        "site_accent2": "#7bdff2",
        "site_text": "#f8f9fa",
        "site_muted": "#9aa5b1",
        "site_layout_mode": "wide",
        "site_density": "compact",
        "site_radius_px": 18,
        "site_font_scale": 1.08,
        "site_content_width": 1600,
        "site_bg_bad": "oops",
        "site_radius_bad": 999,
        "site_font_family_bad": "comic",
    })
    conn.commit()

    assert saved == {
        "site_font_family": "serif",
        "site_background_style": "aurora",
        "site_panel_style": "solid",
        "site_sidebar_width": "wide",
        "site_bg": "#101820",
        "site_surface": "#1b263b",
        "site_accent": "#ff7f50",
        "site_accent2": "#7bdff2",
        "site_text": "#f8f9fa",
        "site_muted": "#9aa5b1",
        "site_layout_mode": "wide",
        "site_density": "compact",
        "site_radius_px": 18,
        "site_font_scale": 1.08,
        "site_content_width": 1600,
    }
    assert get_profile_appearance(conn, 1) == saved

    cleared = clear_profile_appearance(conn, actor=actor)
    conn.commit()
    assert cleared == {}
    assert get_profile_appearance(conn, 1) == {}
