"""§10.3.2 cleanup_run_temp_files + 24h sweeper.

Why this matters: §7.3 / Gate 5 copies cloud-drive image bytes into ComfyUI's
``input/<run_id>/`` subfolder so the workflow can reference them. If the
run fails between Gate 5 and queue, those temp files would otherwise sit
forever — every failed import becomes a permanent disk leak. This module
covers two paths:

1. **Synchronous cleanup** (``cleanup_run_temp_files``): the run handler
   calls this from its except branch when Gate 5 / queue fails.
2. **Sweeper** (``sweep_orphaned_run_dirs``): a background reaper that
   walks the in-memory run-dir registry and reaps subfolders older than
   ``COMFYUI_RUN_TTL_SECONDS`` (default 24h). Operators can invoke it
   from cron / systemd-timer if the in-process scheduler isn't running.

Note: ComfyUI input/ lives on the ComfyUI server's filesystem, not ours.
We delete via the ComfyUI HTTP API (``DELETE /input/<subfolder>``) when
available; otherwise we keep a registry so a follow-up admin call /
manual cleanup can target the same paths.

Spec reference: docs/comfyui/COMFYUI_TEMPLATE_IMPORTER_PLAN.md §10.3.2.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable

from services.comfyui.template.safety import _safe_run_id


COMFYUI_RUN_TTL_SECONDS = 24 * 60 * 60  # 24h reap window per §10.3.2


# ----------------------------------------------------------------------------
# Run-dir registry
#
# We can't enumerate ComfyUI's input/ directly (it's on the server's FS, not
# ours). Instead, every successful Gate 5 image upload registers its
# (run_id, subfolder, created_at) here so the sweeper can replay deletions.
# ----------------------------------------------------------------------------


@dataclass
class _RunDirEntry:
    run_id: str
    created_at: float
    user_id: int
    purged: bool = False


_registry: dict[str, _RunDirEntry] = {}
_registry_lock = threading.Lock()


def register_run_dir(*, run_id: str, user_id: int, clock: Callable[[], float] = time.monotonic) -> None:
    """Record that we wrote bytes into ``ComfyUI input/<run_id>/`` so a
    sweeper can later reap it. Idempotent on repeated calls for the same
    ``run_id`` — only the first registration's timestamp is kept."""
    safe = _safe_run_id(run_id)
    now = clock()
    with _registry_lock:
        if safe not in _registry:
            _registry[safe] = _RunDirEntry(
                run_id=safe,
                created_at=now,
                user_id=int(user_id),
            )


def reset_registry() -> None:
    """Test helper / admin endpoint hook — drop the entire registry."""
    with _registry_lock:
        _registry.clear()


def registry_size() -> int:
    with _registry_lock:
        return len(_registry)


def list_active_run_dirs() -> list[_RunDirEntry]:
    """Snapshot of every non-purged entry — used by the sweeper + admin views."""
    with _registry_lock:
        return [entry for entry in _registry.values() if not entry.purged]


# ----------------------------------------------------------------------------
# Synchronous cleanup
# ----------------------------------------------------------------------------


class CleanupCallback(Callable[..., bool]):  # pragma: no cover - typing only
    """``cleanup_callback(*, run_id, user_id) -> True if reaped successfully``.

    Implementations call ComfyUI's delete API (or a local rmtree if the
    deployment runs ComfyUI on the same filesystem). Returning False means
    the cleanup was attempted but couldn't be completed; the entry stays
    in the registry so the sweeper can retry later.
    """


def cleanup_run_temp_files(
    *,
    run_id: str,
    user_id: int,
    cleanup_callback: Callable[..., bool],
    audit: Callable[..., None] | None = None,
    audit_user: str | None = None,
    audit_ip: str = "",
    audit_ua: str = "",
    reason: str = "gate5_failure",
) -> bool:
    """§10.3.1 entry point: invoke from the run handler on Gate 5 / queue
    failure. Calls the caller-supplied ``cleanup_callback`` to do the actual
    delete, marks the registry entry purged, and emits a
    ``COMFYUI_TEMPLATE_RUN_INPUT_CLEANUP`` audit row per §10.3.

    The cleanup_callback signature is ``(run_id: str, user_id: int) -> bool``.
    """
    safe = _safe_run_id(run_id)
    success = False
    detail = ""
    try:
        success = bool(cleanup_callback(run_id=safe, user_id=int(user_id)))
        detail = "ok" if success else "callback_returned_false"
    except Exception as exc:  # pragma: no cover - defensive
        detail = f"callback_raised: {type(exc).__name__}: {exc}"
        success = False

    if success:
        with _registry_lock:
            entry = _registry.get(safe)
            if entry is not None:
                entry.purged = True

    if audit is not None:
        try:
            audit(
                "COMFYUI_TEMPLATE_RUN_INPUT_CLEANUP",
                audit_ip,
                user=audit_user or "-",
                success=success,
                ua=audit_ua,
                detail=f"run_id={safe} reason={reason} detail={detail}",
            )
        except Exception:  # pragma: no cover - audit must never crash cleanup
            pass

    return success


# ----------------------------------------------------------------------------
# 24h sweeper
# ----------------------------------------------------------------------------


def sweep_orphaned_run_dirs(
    *,
    cleanup_callback: Callable[..., bool],
    audit: Callable[..., None] | None = None,
    ttl_seconds: float = COMFYUI_RUN_TTL_SECONDS,
    clock: Callable[[], float] = time.monotonic,
    audit_user: str = "-",
) -> dict[str, Any]:
    """Reap registry entries older than ``ttl_seconds``.

    Per §10.3.2 only acts on this run's <run_id> subtree — never glob
    across run_ids; every reap goes through the same single-run cleanup
    path the synchronous handler uses.
    """
    now = clock()
    targets: list[_RunDirEntry] = []
    with _registry_lock:
        for entry in list(_registry.values()):
            if entry.purged:
                continue
            if (now - entry.created_at) >= ttl_seconds:
                targets.append(entry)

    reaped = 0
    failed = 0
    for entry in targets:
        ok = cleanup_run_temp_files(
            run_id=entry.run_id,
            user_id=entry.user_id,
            cleanup_callback=cleanup_callback,
            audit=audit,
            audit_user=audit_user,
            reason="sweeper_24h",
        )
        if ok:
            reaped += 1
        else:
            failed += 1

    return {
        "ttl_seconds": ttl_seconds,
        "candidates": len(targets),
        "reaped": reaped,
        "failed": failed,
        "remaining": registry_size() - reaped,
    }


__all__ = [
    "COMFYUI_RUN_TTL_SECONDS",
    "cleanup_run_temp_files",
    "list_active_run_dirs",
    "register_run_dir",
    "registry_size",
    "reset_registry",
    "sweep_orphaned_run_dirs",
]
