from __future__ import annotations

from pathlib import Path

from scripts.prepush.context import PrepushContext
from scripts.prepush.result import CheckResult


SCOPES = ("server.py", "routes", "services", "security", "scripts", "tests")
EXCLUDED_PARTS = {"venv", ".venv", "__pycache__", ".git", "build", "dist", "node_modules"}


def iter_python_files(repo_root: Path):
    for rel in SCOPES:
        path = repo_root / rel
        if path.is_file() and path.suffix == ".py":
            yield path
        elif path.is_dir():
            for item in sorted(path.rglob("*.py")):
                if set(item.relative_to(repo_root).parts) & EXCLUDED_PARTS:
                    continue
                yield item


def run(ctx: PrepushContext) -> CheckResult:
    failures = []
    count = 0
    for path in iter_python_files(ctx.repo_root):
        count += 1
        try:
            source = path.read_text(encoding="utf-8")
            compile(source, str(path), "exec")
        except SyntaxError as exc:
            failures.append({"file": ctx.relpath(path), "error": str(exc)})
        except UnicodeDecodeError as exc:
            failures.append({"file": ctx.relpath(path), "error": f"encoding error: {exc}"})
    if failures:
        return CheckResult.fail(
            "python syntax",
            f"{len(failures)} Python file(s) failed compilation",
            severity="critical",
            details=failures[:40],
            remediation="Fix syntax errors before pushing.",
        )
    return CheckResult.pass_("python syntax", f"compiled {count} Python file(s)")
