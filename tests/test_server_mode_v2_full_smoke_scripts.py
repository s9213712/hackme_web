from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_server_mode_v2_examples_readme_lists_extended_bundle():
    readme = (REPO_ROOT / "docs" / "examples" / "server_mode_v2" / "README.md").read_text(encoding="utf-8")
    assert "04_pentest_smv2.sh" in readme
    assert "05_stress_smv2.sh" in readme
    assert "06_full_feature_smv2.sh" in readme
    assert "07_privilege_escalation_smv2.sh" in readme
    assert "python3 security/server_mode_v2_full_smoke.py" in readme
    assert "shadow-table activity did not leak into production wallet" in readme


def test_server_mode_v2_full_smoke_references_extended_bundle_and_isolation_checks():
    script = (REPO_ROOT / "security" / "server_mode_v2_full_smoke.py").read_text(encoding="utf-8")
    assert "04_pentest_smv2.sh" in script
    assert "05_stress_smv2.sh" in script
    assert "06_full_feature_smv2.sh" in script
    assert "07_privilege_escalation_smv2.sh" in script
    assert "test_shadow_wallets" in script
    assert "points_wallets" in script
    assert "all_scripts_passed" in script
    assert "prod_clean" in script
    assert "time.sleep(5)" in script
