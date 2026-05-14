"""Tests for the settings group / danger metadata layer (P1)."""

import sqlite3

import pytest

from services.platform import settings as settings_mod
from services.platform.settings_metadata import (
    DANGEROUS_SETTINGS,
    SETTING_GROUPS,
    find_dangerous_changes,
    setting_groups_payload,
)


def _with_isolated_settings(tmp_path):
    db_path = tmp_path / "settings.db"
    old_state = dict(settings_mod._STATE)
    old_system_settings = settings_mod._SYSTEM_SETTINGS

    def get_db():
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        return conn

    settings_mod.configure_settings_service(
        get_db=get_db,
        load_json=lambda path, default=None: default or {},
        base_dir=str(tmp_path),
    )
    conn = get_db()
    settings_mod.init_system_settings_table(conn)
    settings_mod._seed_missing_settings_to_db(conn)
    conn.commit()
    conn.close()
    settings_mod.refresh_system_settings()
    return old_state, old_system_settings


def test_groups_cover_every_default_setting():
    """Every key in DEFAULT_SETTINGS must end up in either an explicit group
    or the auto-generated ``other`` bucket — no key may be silently dropped."""
    payload = setting_groups_payload()
    placed = set()
    for group in payload:
        for entry in group["settings"]:
            placed.add(entry["key"])
    missing = set(settings_mod.DEFAULT_SETTINGS) - placed
    assert not missing, f"settings missing from metadata payload: {sorted(missing)}"


def test_groups_have_titles_and_descriptions():
    for group in SETTING_GROUPS:
        assert group["title"], f"group {group['key']} missing title"
        assert group["description"], f"group {group['key']} missing description"


def test_dangerous_keys_payload_marks_disable_side():
    payload = setting_groups_payload()
    audit_entry = None
    for group in payload:
        for entry in group["settings"]:
            if entry["key"] == "audit_chain_enabled":
                audit_entry = entry
                break
    assert audit_entry is not None, "audit_chain_enabled should appear in metadata"
    assert audit_entry["dangerous"]["side"] == "disable"
    assert "audit chain" in audit_entry["dangerous"]["warning"].lower()


def test_find_dangerous_changes_detects_disable_transition():
    risky = find_dangerous_changes(
        {"audit_chain_enabled": True},
        {"audit_chain_enabled": False},
    )
    assert len(risky) == 1
    key, _danger, transition = risky[0]
    assert key == "audit_chain_enabled"
    assert transition == "disable"


def test_find_dangerous_changes_skips_no_op():
    # Same value -> not a transition -> not risky.
    risky = find_dangerous_changes(
        {"audit_chain_enabled": True},
        {"audit_chain_enabled": True},
    )
    assert risky == []


def test_find_dangerous_changes_respects_enable_side_filter():
    """allow_register only triggers on enable transition (False -> True),
    so disabling it (True -> False) should not raise."""
    # allow_register default is True, "enable" side gate => disabling is fine.
    risky = find_dangerous_changes(
        {"allow_register": True},
        {"allow_register": False},
    )
    assert risky == []
    # But flipping it back on counts as a dangerous enable.
    risky = find_dangerous_changes(
        {"allow_register": False},
        {"allow_register": True},
    )
    assert len(risky) == 1


def test_enforce_dangerous_confirm_blocks_without_confirm(tmp_path):
    old_state, old_system_settings = _with_isolated_settings(tmp_path)
    try:
        with pytest.raises(settings_mod.DangerousChangeBlocked) as exc:
            settings_mod.enforce_dangerous_confirm(
                settings_mod.get_system_settings(),
                {"audit_chain_enabled": False},
            )
        keys = {item[0] for item in exc.value.risky}
        assert "audit_chain_enabled" in keys
    finally:
        settings_mod._STATE.update(old_state)
        settings_mod._SYSTEM_SETTINGS = old_system_settings


def test_enforce_dangerous_confirm_passes_with_matching_confirm(tmp_path):
    old_state, old_system_settings = _with_isolated_settings(tmp_path)
    try:
        # Single string form
        settings_mod.enforce_dangerous_confirm(
            settings_mod.get_system_settings(),
            {"audit_chain_enabled": False, "dangerous_confirm": "audit_chain_enabled"},
        )
        # List form
        settings_mod.enforce_dangerous_confirm(
            settings_mod.get_system_settings(),
            {
                "audit_chain_enabled": False,
                "integrity_guard_enabled": False,
                "dangerous_confirm": ["audit_chain_enabled", "integrity_guard_enabled"],
            },
        )
    finally:
        settings_mod._STATE.update(old_state)
        settings_mod._SYSTEM_SETTINGS = old_system_settings


def test_enforce_dangerous_confirm_blocks_partial_confirm(tmp_path):
    old_state, old_system_settings = _with_isolated_settings(tmp_path)
    try:
        with pytest.raises(settings_mod.DangerousChangeBlocked) as exc:
            settings_mod.enforce_dangerous_confirm(
                settings_mod.get_system_settings(),
                {
                    "audit_chain_enabled": False,
                    "integrity_guard_enabled": False,
                    "dangerous_confirm": "audit_chain_enabled",
                },
            )
        keys = {item[0] for item in exc.value.risky}
        assert keys == {"integrity_guard_enabled"}
    finally:
        settings_mod._STATE.update(old_state)
        settings_mod._SYSTEM_SETTINGS = old_system_settings


def test_dangerous_settings_table_has_required_fields():
    for key, entry in DANGEROUS_SETTINGS.items():
        assert entry["side"] in {"enable", "disable", "either", "value"}, key
        assert entry["warning"], f"{key} missing warning"
