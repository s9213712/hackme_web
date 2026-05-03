from __future__ import annotations

from pathlib import PurePosixPath

from scripts.prepush.context import PrepushContext
from scripts.prepush.result import CheckResult


FORBIDDEN_PATTERNS = (
    "*.db",
    "*.sqlite",
    "*.sqlite3",
    "*.log",
    "*.pem",
    "*.key",
    ".csrfkey",
    ".integrity_key",
    ".chain_seed",
    "integrity_manifest.json",
    "reports/**",
    "storage/**",
    "logs/**",
    "runtime/**",
    "hackme_web_runtime/**",
    "html_learning_storage/**",
    "**/__pycache__/**",
    ".pytest_cache/**",
    ".mypy_cache/**",
    ".ruff_cache/**",
    "node_modules/**",
    "dist/**",
    "build/**",
)


def is_forbidden(rel: str) -> bool:
    if rel.endswith("/.gitkeep") or rel == ".gitkeep":
        return False
    if any(rel == prefix or rel.startswith(prefix + "/") for prefix in ("reports", "storage", "logs", "runtime", "hackme_web_runtime", "html_learning_storage", "node_modules", "dist", "build")):
        return True
    path = PurePosixPath(rel)
    return any(path.match(pattern) for pattern in FORBIDDEN_PATTERNS)


def run(ctx: PrepushContext) -> CheckResult:
    violations = []
    for source, files in (("tracked", ctx.tracked_files), ("staged", ctx.staged_files)):
        for rel in files:
            if is_forbidden(rel):
                violations.append({"source": source, "file": rel})
    if violations:
        return CheckResult.fail(
            "forbidden runtime files",
            "runtime/cache/report/key artifacts are tracked or staged",
            severity="critical",
            details=violations[:80],
            remediation="Remove generated artifacts from git; keep only .gitkeep placeholders where needed.",
        )
    return CheckResult.pass_("forbidden runtime files", "no forbidden runtime artifacts are tracked or staged")
