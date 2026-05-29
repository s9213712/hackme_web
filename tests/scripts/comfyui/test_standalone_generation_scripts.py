from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[3]
SCRIPTS = (
    ROOT / "scripts" / "comfyui" / "standalone_regular_comfyui_txt2img.py",
    ROOT / "scripts" / "comfyui" / "standalone_hf_diffusers_txt2img.py",
    ROOT / "scripts" / "comfyui" / "standalone_gguf_txt2img.py",
)


def test_standalone_generation_scripts_expose_interactive_cli():
    for script in SCRIPTS:
        result = subprocess.run(
            [sys.executable, str(script), "--help"],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, script
        assert "--interactive" in result.stdout
