from pathlib import Path


DANGEROUS_STORAGE_ROOTS = {
    Path("/"),
    Path("/bin"),
    Path("/boot"),
    Path("/dev"),
    Path("/etc"),
    Path("/lib"),
    Path("/lib64"),
    Path("/proc"),
    Path("/root"),
    Path("/run"),
    Path("/sbin"),
    Path("/sys"),
    Path("/usr"),
    Path("/var"),
}


def _is_relative_safe(relative_path):
    candidate = Path(str(relative_path or ""))
    return bool(str(relative_path or "").strip()) and not candidate.is_absolute() and ".." not in candidate.parts


def validate_storage_root(storage_root, *, base_dir=None, create=False):
    raw = str(storage_root or "").strip()
    if not raw:
        raise ValueError("storage root is required")
    root = Path(raw).expanduser()
    if not root.is_absolute():
        raise ValueError("storage root must be an absolute path")
    if create:
        root.mkdir(parents=True, exist_ok=True)
    resolved = root.resolve()
    if resolved in DANGEROUS_STORAGE_ROOTS:
        raise ValueError("storage root is too broad or unsafe")
    if base_dir:
        base = Path(base_dir).resolve()
        public_dir = (base / "public").resolve()
        if resolved == public_dir or public_dir in resolved.parents:
            raise ValueError("storage root must not be inside public web assets")
        if resolved == base:
            raise ValueError("storage root must not be the project root")
    return resolved


def resolve_storage_path(storage_root, relative_path, *, create_parent=False):
    if not _is_relative_safe(relative_path):
        raise ValueError("unsafe storage relative path")
    root = Path(storage_root).resolve()
    target = (root / str(relative_path)).resolve()
    if root != target and root not in target.parents:
        raise ValueError("path escapes storage root")
    if create_parent:
        target.parent.mkdir(parents=True, exist_ok=True)
    return target
