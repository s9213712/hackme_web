import importlib.util
import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "scripts" / "games" / "setup_katago.py"


def _load_setup_module():
    spec = importlib.util.spec_from_file_location("setup_katago_test_module", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_setup_katago_default_urls_are_current_official_defaults():
    module = _load_setup_module()

    assert module.DEFAULT_KATAGO_VERSION == "1.16.4"
    assert module.DEFAULT_MODEL_NAME == "kata1-zhizi-b40c768nbt-fdx6d"
    assert module._default_binary_url("1.16.4", "opencl").endswith(
        "/v1.16.4/katago-v1.16.4-opencl-linux-x64.zip"
    )
    assert module.DEFAULT_MODEL_URL.endswith("/kata1-zhizi-b40c768nbt-fdx6d.bin.gz")


def test_setup_katago_dry_run_prints_paths_without_downloading(tmp_path):
    proc = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--dry-run",
            "--install-dir",
            str(tmp_path / "katago"),
        ],
        cwd=str(ROOT),
        text=True,
        capture_output=True,
        check=True,
    )

    payload = json.loads(proc.stdout)
    assert payload["ok"] is True
    assert payload["dry_run"] is True
    assert payload["backend"] == "opencl"
    assert payload["binary_path"].endswith("/katago")
    assert payload["config_path"].endswith("/analysis.cfg")
    assert "HACKME_KATAGO_MODEL" in "\n".join(payload["env"])
    assert not (tmp_path / "katago").exists()
