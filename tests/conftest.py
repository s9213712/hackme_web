from __future__ import annotations

import atexit
import os
import shutil
import tempfile
from pathlib import Path


_TEMP_RUNTIME_ROOT: str | None = None


def _ensure_test_runtime_dir() -> None:
    global _TEMP_RUNTIME_ROOT
    if os.environ.get("HACKME_RUNTIME_DIR"):
        return
    runtime_root = tempfile.mkdtemp(prefix="hackme_web_pytest_runtime_")
    _TEMP_RUNTIME_ROOT = runtime_root
    os.environ["HACKME_RUNTIME_DIR"] = runtime_root


def _cleanup_test_runtime_dir() -> None:
    if _TEMP_RUNTIME_ROOT:
        shutil.rmtree(_TEMP_RUNTIME_ROOT, ignore_errors=True)


_ensure_test_runtime_dir()
atexit.register(_cleanup_test_runtime_dir)
