from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "scripts" / "comfyui" / "local_connection_smoke.py"


def test_comfyui_local_connection_smoke_help_lists_required_arguments():
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert "--base-url" in result.stdout
    assert "--password" in result.stdout
    assert "--comfyui-base-dir" in result.stdout
    assert "--comfyui-local-script" in result.stdout


def test_comfyui_local_connection_smoke_mentions_root_connection_test_endpoint():
    text = SCRIPT.read_text(encoding="utf-8")
    assert "/api/root/comfyui/test-connection" in text
    assert "connection_mode" in text
    assert "local_script" in text
