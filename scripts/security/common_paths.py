from __future__ import annotations

import os
from pathlib import Path
from datetime import datetime


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_RUNTIME_ROOT = REPO_ROOT / "runtime"


def runtime_root() -> Path:
    raw = str(os.environ.get("HACKME_RUNTIME_DIR") or "").strip()
    if raw:
        return Path(raw).expanduser()
    return DEFAULT_RUNTIME_ROOT


def reports_parent_root() -> Path:
    raw = str(os.environ.get("HTML_LEARNING_REPORTS_DIR") or "").strip()
    if raw:
        return Path(raw).expanduser()
    return runtime_root() / "reports"


def security_reports_root() -> Path:
    return reports_parent_root() / "security"


def timestamped_security_report_paths(prefix: str, *, stamp: str | None = None) -> tuple[Path, Path]:
    ts = stamp or datetime.now().strftime("%Y%m%d_%H%M%S")
    root = security_reports_root()
    return root / f"{prefix}_{ts}.json", root / f"{prefix}_{ts}.md"
