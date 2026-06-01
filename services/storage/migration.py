import shutil
from pathlib import Path


def sync_storage_root_contents(source_root, target_root, *, skip_names=None):
    """Copy existing storage files into a new storage root before switching roots.

    The migration intentionally copies instead of deleting from the source root.
    Storage-root changes are high-risk operations; keeping the old tree intact
    prevents data loss if the admin points at the wrong target or the server is
    restarted mid-change.
    """
    source = Path(source_root or "").expanduser().resolve()
    target = Path(target_root or "").expanduser().resolve()
    skip = set(skip_names or {".upload_tmp"})
    summary = {
        "source_root": str(source),
        "target_root": str(target),
        "same_root": source == target,
        "source_exists": source.is_dir(),
        "created_dirs": 0,
        "copied_files": 0,
        "skipped_existing_files": 0,
        "skipped_temp_files": 0,
        "copied_bytes": 0,
    }
    if source == target:
        return summary
    if source in target.parents or target in source.parents:
        raise ValueError("storage root migration does not allow nested source/target directories")
    target.mkdir(parents=True, exist_ok=True)
    if not source.is_dir():
        return summary
    for item in source.rglob("*"):
        rel = item.relative_to(source)
        if any(part in skip for part in rel.parts):
            if item.is_file():
                summary["skipped_temp_files"] += 1
            continue
        dest = target / rel
        if item.is_dir():
            if not dest.exists():
                dest.mkdir(parents=True, exist_ok=True)
                summary["created_dirs"] += 1
            continue
        if not item.is_file():
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        if dest.exists():
            summary["skipped_existing_files"] += 1
            continue
        shutil.copy2(item, dest)
        summary["copied_files"] += 1
        try:
            summary["copied_bytes"] += int(item.stat().st_size)
        except OSError:
            pass
    return summary
