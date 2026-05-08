"""§15 feature flag regression — feature_comfyui_legacy_import_enabled
+ feature_comfyui_template_importer_strict are registered in the canonical
DEFAULT_SETTINGS and behave per spec defaults."""

import pytest

from services.platform.settings import DEFAULT_SETTINGS, FEATURE_FLAG_KEYS


def test_legacy_import_flag_is_registered():
    assert "feature_comfyui_legacy_import_enabled" in DEFAULT_SETTINGS


def test_template_importer_strict_flag_is_registered():
    assert "feature_comfyui_template_importer_strict" in DEFAULT_SETTINGS


def test_legacy_import_flag_default_true_for_back_compat():
    """Phase rollout (§15.5): legacy import path stays alive by default
    so existing /workflows/import callers don't break the moment the new
    code lands."""
    assert DEFAULT_SETTINGS["feature_comfyui_legacy_import_enabled"] is True


def test_template_importer_strict_flag_default_false():
    """Phase rollout (§15.7): strict 5-gate run mode is off by default
    until the importer has been validated for at least one release."""
    assert DEFAULT_SETTINGS["feature_comfyui_template_importer_strict"] is False


def test_flags_appear_in_feature_flag_keys_tuple():
    """settings.FEATURE_FLAG_KEYS is the auth boundary; flags missing
    from it can't be toggled by root via the admin features endpoint."""
    assert "feature_comfyui_legacy_import_enabled" in FEATURE_FLAG_KEYS
    assert "feature_comfyui_template_importer_strict" in FEATURE_FLAG_KEYS
