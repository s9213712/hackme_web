from pathlib import Path

import pytest

from services.storage.paths import resolve_storage_path, validate_storage_root


def test_resolve_storage_path_accepts_safe_relative_path(tmp_path):
    target = resolve_storage_path(tmp_path, "users/1/file.bin", create_parent=True)
    assert target == (tmp_path / "users" / "1" / "file.bin").resolve()
    assert target.parent.exists()


def test_resolve_storage_path_rejects_path_traversal(tmp_path):
    with pytest.raises(ValueError):
        resolve_storage_path(tmp_path, "../server.py")
    with pytest.raises(ValueError):
        resolve_storage_path(tmp_path, "/etc/passwd")


def test_resolve_storage_path_rejects_symlink_escape(tmp_path):
    outside = tmp_path.parent / "outside-target"
    outside.mkdir(exist_ok=True)
    link = tmp_path / "link"
    link.symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError):
        resolve_storage_path(tmp_path, "link/escape.bin")


def test_validate_storage_root_rejects_dangerous_roots(tmp_path):
    with pytest.raises(ValueError):
        validate_storage_root("/")
    with pytest.raises(ValueError):
        validate_storage_root("relative/path")


def test_validate_storage_root_rejects_public_and_project_root(tmp_path):
    base = tmp_path / "app"
    public = base / "public"
    storage = base / "storage"
    public.mkdir(parents=True)
    storage.mkdir()
    with pytest.raises(ValueError):
        validate_storage_root(str(base), base_dir=base)
    with pytest.raises(ValueError):
        validate_storage_root(str(public / "uploads"), base_dir=base, create=True)
    assert validate_storage_root(str(storage), base_dir=base) == storage.resolve()
