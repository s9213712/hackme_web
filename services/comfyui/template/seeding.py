"""§18.1 first-boot seeding for runtime/comfyui/.

The repo ships a set of system workflows under workflows/comfyui/ (txt2img,
img2img, inpaint, outpaint, upscale, controlnet). On first server start we
copy those into the runtime tree (``$HACKME_RUNTIME_DIR/comfyui/`` or
``runtime/comfyui/`` by default) so:

- Operators can edit / extend templates without git churn.
- The runtime tree stays gitignored, so customizations don't pollute the
  repo state.
- A fresh checkout still gets working defaults on first boot.

Idempotent: subsequent boots are a no-op once the runtime tree has any
workflows in it. The check is per-workflow-id (not "directory exists") so
operators can drop in new bundles without us blocking.

Spec reference: docs/comfyui/COMFYUI_TEMPLATE_IMPORTER_PLAN.md §18.1.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Iterable


REPO_SOURCE_DIR = Path(__file__).resolve().parents[3] / "workflows" / "comfyui"
SYSTEM_WORKFLOW_IDS = (
    "txt2img_basic",
    "img2img_basic",
    "inpaint_basic",
    "outpaint_basic",
    "upscale_basic",
    "controlnet_canny",
)


def _runtime_root() -> Path:
    """Resolve the runtime base dir (HACKME_RUNTIME_DIR or repo-root/runtime)."""
    env_dir = os.environ.get("HACKME_RUNTIME_DIR", "").strip()
    if env_dir:
        return Path(env_dir)
    return Path(__file__).resolve().parents[3] / "runtime"


def runtime_comfyui_dir(*, runtime_root: Path | None = None) -> Path:
    """Where seeded ComfyUI workflows live at runtime."""
    base = Path(runtime_root) if runtime_root is not None else _runtime_root()
    return base / "comfyui"


def _is_complete_workflow_dir(path: Path) -> bool:
    """A workflow directory must carry workflow.json + manifest.json."""
    if not path.is_dir():
        return False
    return (path / "workflow.json").is_file() and (path / "manifest.json").is_file()


def _list_seed_candidates(source_dir: Path) -> list[Path]:
    if not source_dir.is_dir():
        return []
    return sorted(p for p in source_dir.iterdir() if _is_complete_workflow_dir(p))


def seed_default_comfyui_workflows(
    *,
    source_dir: Path | None = None,
    runtime_root: Path | None = None,
    overwrite: bool = False,
) -> dict:
    """Copy any workflows missing from the runtime tree.

    By default we never overwrite an existing runtime workflow_id — operators
    may have edited it. Pass ``overwrite=True`` to force a re-copy (used by
    the admin "reset templates" endpoint or post-upgrade migrations).

    Returns a small report dict for ops dashboards / audit log:
    ``{"source_count", "runtime_count", "copied", "skipped", "destination"}``
    """
    source = Path(source_dir) if source_dir is not None else REPO_SOURCE_DIR
    target = runtime_comfyui_dir(runtime_root=runtime_root)

    source_dirs = _list_seed_candidates(source)
    if not source_dirs:
        return {
            "source_count": 0,
            "runtime_count": _list_runtime_count(target),
            "copied": [],
            "skipped": [],
            "destination": str(target),
        }

    target.mkdir(parents=True, exist_ok=True)

    copied: list[str] = []
    skipped: list[str] = []
    for src in source_dirs:
        dst = target / src.name
        if dst.exists() and _is_complete_workflow_dir(dst) and not overwrite:
            skipped.append(src.name)
            continue
        # Either dst is partial/corrupt (always replace) or overwrite=True.
        if dst.exists():
            shutil.rmtree(dst)
        shutil.copytree(src, dst)
        copied.append(src.name)

    return {
        "source_count": len(source_dirs),
        "runtime_count": _list_runtime_count(target),
        "copied": copied,
        "skipped": skipped,
        "destination": str(target),
    }


def _list_runtime_count(target: Path) -> int:
    if not target.exists():
        return 0
    return sum(1 for p in target.iterdir() if _is_complete_workflow_dir(p))


def list_runtime_workflows(*, runtime_root: Path | None = None) -> list[str]:
    """Workflow ids currently present at runtime/comfyui/. Used by the registry."""
    target = runtime_comfyui_dir(runtime_root=runtime_root)
    if not target.is_dir():
        return []
    return sorted(p.name for p in target.iterdir() if _is_complete_workflow_dir(p))


__all__ = [
    "REPO_SOURCE_DIR",
    "SYSTEM_WORKFLOW_IDS",
    "list_runtime_workflows",
    "runtime_comfyui_dir",
    "seed_default_comfyui_workflows",
]
