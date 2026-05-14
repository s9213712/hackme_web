import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]


def test_server_mode_v2_examples_readme_lists_extended_bundle():
    readme = (REPO_ROOT / "docs" / "server_mode_v2" / "README.md").read_text(encoding="utf-8")
    assert "04_pentest_smv2.sh" in readme
    assert "05_stress_smv2.sh" in readme
    assert "06_full_feature_smv2.sh" in readme
    assert "07_privilege_escalation_smv2.sh" in readme
    assert "python3 scripts/security/server_mode/server_mode_v2_full_smoke.py" in readme
    assert "shadow-table activity did not leak into production wallet" in readme


def test_server_mode_v2_full_smoke_references_extended_bundle_and_isolation_checks():
    script = (REPO_ROOT / "scripts" / "security" / "server_mode" / "server_mode_v2_full_smoke.py").read_text(encoding="utf-8")
    token_smoke = (REPO_ROOT / "scripts" / "security" / "server_mode" / "server_mode_v2_token_smoke.py").read_text(encoding="utf-8")
    assert "04_pentest_smv2.sh" in script
    assert "05_stress_smv2.sh" in script
    assert "06_full_feature_smv2.sh" in script
    assert "07_privilege_escalation_smv2.sh" in script
    assert 'REPO_ROOT / "docs" / "server_mode_v2"' in script
    assert 'REPO_ROOT / "docs" / "server_mode_v2"' in token_smoke
    assert "test_shadow_wallets" in script
    assert "points_wallets" in script
    assert "all_scripts_passed" in script
    assert "prod_clean" in script
    assert "time.sleep(5)" in script


def test_server_mode_v2_full_smoke_help_exits_without_booting_runtime():
    script_path = REPO_ROOT / "scripts" / "security" / "server_mode" / "server_mode_v2_full_smoke.py"
    result = subprocess.run(
        [sys.executable, str(script_path), "--help"],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert "full set of SMv2" in result.stdout
    assert "hackme_full_smoke_" not in result.stdout
    assert result.stderr == ""


def test_full_feature_script_rotates_internal_test_token_with_target_username():
    script = (REPO_ROOT / "docs" / "server_mode_v2" / "06_full_feature_smv2.sh").read_text(encoding="utf-8")
    assert "ROTATE_INTERNAL_TEST_TOKEN" in script
    assert "target_username" in script
    assert "$TESTER_USER" in script
