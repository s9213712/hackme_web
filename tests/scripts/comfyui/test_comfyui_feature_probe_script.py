from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "scripts" / "comfyui" / "feature_probe.py"


def test_comfyui_feature_probe_help_lists_supported_modes():
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert "--base-url" in result.stdout
    assert "--controlnet-type" in result.stdout


def test_comfyui_feature_probe_mentions_core_generation_modes():
    text = SCRIPT.read_text(encoding="utf-8")
    for keyword in ("txt2img", "img2img", "inpaint", "outpaint", "upscale", "history_rerun", "controlnet"):
        assert keyword in text
