from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path

from scripts.prepush.context import PrepushContext
from scripts.prepush.result import CheckResult


REPO_CACHE_DIR_NAMES = {"__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", "htmlcov", "dist", "build"}
REPO_CACHE_FILE_NAMES = {".coverage"}
REPO_CACHE_FILE_SUFFIXES = {".pyc", ".pyo"}
REPO_JUNK_FILE_SUFFIXES = {":Zone.Identifier"}
PROTECTED_CLEAN_PATHS = {"runtime"}
PROTECTED_CLEAN_FILES = {
    "bootstrap.schema.sql",
    "runtime/cert.pem",
    "runtime/key.pem",
    "runtime/.csrfkey",
    "runtime/.integrity_key",
    "runtime/.chain_seed",
    "runtime/integrity_manifest.json",
}
TEMP_PREFIXES = ("html_learning_prepush_", "html_learning_secrets_")


def relative_posix(path: Path, *, root: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def is_protected_clean_path(path: Path, *, root: Path) -> bool:
    try:
        relative = relative_posix(path, root=root)
    except ValueError:
        return True
    if relative in PROTECTED_CLEAN_FILES:
        return True
    return any(relative == protected or relative.startswith(protected + "/") for protected in PROTECTED_CLEAN_PATHS)


def tree_contains_tracked_or_gitkeep(path: Path, tracked: set[str], *, root: Path) -> bool:
    for item in path.rglob("*"):
        if item.name == ".gitkeep":
            return True
        try:
            relative = relative_posix(item, root=root)
        except ValueError:
            return True
        if relative in tracked:
            return True
    return False


def collect_repo_cache_candidates(*, root: Path, tracked: set[str] | None = None) -> list[Path]:
    root = Path(root)
    tracked = set(tracked or set())
    candidates: list[Path] = []
    for current_root, dirnames, filenames in os.walk(root):
        current = Path(current_root)
        if ".git" in current.parts:
            dirnames[:] = []
            continue
        if current != root and is_protected_clean_path(current, root=root):
            dirnames[:] = []
            continue
        for dirname in list(dirnames):
            target = current / dirname
            if is_protected_clean_path(target, root=root):
                dirnames.remove(dirname)
                continue
            if dirname not in REPO_CACHE_DIR_NAMES:
                continue
            if tree_contains_tracked_or_gitkeep(target, tracked, root=root):
                continue
            candidates.append(target)
            dirnames.remove(dirname)
        for filename in filenames:
            target = current / filename
            if filename == ".gitkeep" or is_protected_clean_path(target, root=root):
                continue
            try:
                relative = relative_posix(target, root=root)
            except ValueError:
                continue
            if relative in tracked:
                continue
            if (
                filename in REPO_CACHE_FILE_NAMES
                or target.suffix.lower() in REPO_CACHE_FILE_SUFFIXES
                or any(filename.endswith(suffix) for suffix in REPO_JUNK_FILE_SUFFIXES)
            ):
                candidates.append(target)
    return sorted(candidates)


def collect_temp_clean_candidates(*, tmp_root: Path | None = None, keep_latest: int = 2) -> list[Path]:
    tmp_root = Path(tmp_root or tempfile.gettempdir())
    candidates: list[Path] = []
    for prefix in TEMP_PREFIXES:
        candidates.extend(path for path in tmp_root.glob(prefix + "*") if path.exists())
    candidates = sorted(candidates, key=lambda path: path.stat().st_mtime if path.exists() else 0, reverse=True)
    keep = {path.resolve() for path in candidates[: max(0, keep_latest)]}
    return [path for path in candidates if path.resolve() not in keep]


def collect_repo_runtime_candidates(*, root: Path, tracked: set[str] | None = None) -> list[Path]:
    root = Path(root)
    tracked = set(tracked or set())
    runtime_root = root / "runtime"
    if not runtime_root.exists():
        return []
    if tree_contains_tracked_or_gitkeep(runtime_root, tracked, root=root):
        return []
    return [runtime_root]


def remove_candidates(candidates: list[Path]) -> int:
    removed = 0
    for path in candidates:
        if path.is_dir():
            shutil.rmtree(path, ignore_errors=True)
            removed += 1
        elif path.exists():
            path.unlink()
            removed += 1
    return removed


def confirm_delete(label: str, candidates: list[Path], *, yes: bool, is_ci: bool) -> bool:
    if not candidates:
        return False
    if yes:
        return True
    if is_ci:
        return False
    if not sys.stdin.isatty():
        raise RuntimeError(f"{label} requires confirmation; rerun with --yes")
    answer = input(f"{label}: delete {len(candidates)} item(s)? Type YES to continue: ").strip()
    return answer == "YES"


def cleanup_current_runtime(runtime_root: Path, *, success: bool, ci: bool, keep_temp: bool) -> str:
    if success and ci and not keep_temp:
        shutil.rmtree(runtime_root, ignore_errors=True)
        return "removed"
    return "kept"


def clean_repo_caches(*, yes: bool, root: Path, tracked: set[str] | None = None, is_ci: bool = False) -> tuple[int, list[Path]]:
    candidates = collect_repo_cache_candidates(root=root, tracked=tracked)
    if not confirm_delete("clean", candidates, yes=yes, is_ci=is_ci):
        return 0, candidates
    return remove_candidates(candidates), candidates


def clean_repo_runtime(*, yes: bool, root: Path, tracked: set[str] | None = None, is_ci: bool = False) -> tuple[int, list[Path]]:
    candidates = collect_repo_runtime_candidates(root=root, tracked=tracked)
    if not confirm_delete("clean-runtime", candidates, yes=yes, is_ci=is_ci):
        return 0, candidates
    return remove_candidates(candidates), candidates


def clean_temp_roots(*, keep_latest: int = 2, yes: bool, tmp_root: Path | None = None, is_ci: bool = False) -> tuple[int, list[Path]]:
    candidates = collect_temp_clean_candidates(tmp_root=tmp_root, keep_latest=keep_latest)
    if not confirm_delete("clean-temp", candidates, yes=yes, is_ci=is_ci):
        return 0, candidates
    return remove_candidates(candidates), candidates


def run_clean(ctx: PrepushContext) -> CheckResult:
    try:
        cache_removed, cache_candidates = clean_repo_caches(
            yes=ctx.yes,
            root=ctx.repo_root,
            tracked=set(ctx.tracked_files),
            is_ci=ctx.is_ci,
        )
        runtime_removed, runtime_candidates = clean_repo_runtime(
            yes=ctx.yes,
            root=ctx.repo_root,
            tracked=set(ctx.tracked_files),
            is_ci=ctx.is_ci,
        )
    except Exception as exc:
        return CheckResult.fail("clean repo caches", str(exc), remediation="Use --yes or run interactively.")
    candidates = cache_candidates + runtime_candidates
    removed = cache_removed + runtime_removed
    details = [{"path": ctx.relpath(path)} for path in candidates[:80]]
    return CheckResult.pass_(
        "clean repo caches/runtime",
        f"removed {removed} safe repo artifact(s)",
        details=details,
    )


def run_clean_temp(ctx: PrepushContext, *, keep_latest: int = 2) -> CheckResult:
    try:
        removed, candidates = clean_temp_roots(keep_latest=keep_latest, yes=ctx.yes, is_ci=ctx.is_ci)
    except Exception as exc:
        return CheckResult.fail("clean temp runtimes", str(exc), remediation="Use --yes or run interactively.")
    details = [{"path": ctx.sanitize_path(path)} for path in candidates[:80]]
    return CheckResult.pass_("clean temp runtimes", f"removed {removed} old temp item(s)", details=details)
