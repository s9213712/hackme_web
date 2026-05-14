from __future__ import annotations

from scripts.prepush import utils
from scripts.prepush.context import PrepushContext
from scripts.prepush.result import CheckResult


CONFLICT_MARKERS = ("<<<<<<<", "=======", ">>>>>>>")


def has_conflict_marker(line: str) -> bool:
    stripped = line.lstrip()
    return any(stripped.startswith(marker) for marker in CONFLICT_MARKERS)


def run(ctx: PrepushContext) -> CheckResult:
    failures = []
    for label, command in (
        ("worktree", ["git", "diff", "--check"]),
        ("staged", ["git", "diff", "--cached", "--check"]),
    ):
        proc = utils.run_command(command, cwd=ctx.repo_root, timeout=30)
        if proc.returncode != 0:
            failures.append({"check": label, "output": utils.sanitize_path(proc.stdout + proc.stderr)[-1200:]})

    scan_files = sorted(set(ctx.staged_files + ctx.changed_files))
    for path in utils.iter_repo_text_files(ctx.repo_root, scan_files):
        for line_no, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), start=1):
            if has_conflict_marker(line):
                failures.append({"file": ctx.relpath(path), "line": line_no, "problem": "conflict marker"})

    if failures:
        return CheckResult.fail(
            "git diff hygiene",
            "diff whitespace/conflict-marker checks failed",
            severity="medium",
            details=failures[:40],
            remediation="Run git diff --check and remove conflict markers/trailing whitespace.",
        )
    return CheckResult.pass_("git diff hygiene", "git diff --check and conflict marker scan passed")
