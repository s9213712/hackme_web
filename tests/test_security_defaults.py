from services.settings import DEFAULT_SETTINGS, MANAGEMENT_ONLY_RESET_SETTINGS


def test_initial_deploy_security_defaults_enable_integrity_and_audit_chain():
    assert DEFAULT_SETTINGS["audit_chain_enabled"] is True
    assert DEFAULT_SETTINGS["integrity_guard_enabled"] is True


def test_initial_deploy_defaults_only_enable_management_and_security_modules():
    enabled_features = {
        key for key, value in DEFAULT_SETTINGS.items()
        if key.startswith("feature_") and value is True
    }
    assert enabled_features == {
        "feature_accounts_enabled",
        "feature_audit_log_enabled",
        "feature_violation_center_enabled",
        "feature_system_health_enabled",
        "feature_identity_governance_enabled",
        "feature_member_governance_enabled",
        "feature_server_modes_enabled",
        "feature_snapshot_restore_enabled",
        "feature_health_center_enabled",
    }
    assert DEFAULT_SETTINGS["feature_forum_core_enabled"] is False
    assert DEFAULT_SETTINGS["feature_comfyui_enabled"] is False
    assert DEFAULT_SETTINGS["feature_games_enabled"] is False
    assert DEFAULT_SETTINGS["feature_privacy_uploads_enabled"] is False
    assert DEFAULT_SETTINGS["feature_storage_albums_enabled"] is False


def test_runtime_reset_keeps_integrity_and_audit_chain_enabled():
    assert MANAGEMENT_ONLY_RESET_SETTINGS["audit_chain_enabled"] is True
    assert MANAGEMENT_ONLY_RESET_SETTINGS["integrity_guard_enabled"] is True
