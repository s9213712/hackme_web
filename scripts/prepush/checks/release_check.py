from __future__ import annotations

import ast

from scripts.prepush.context import PrepushContext
from scripts.prepush.result import CheckResult


RELEASE_FILE = "services/release_info.py"
DOCS = ["README.md", "docs/README.zh-TW.md", "docs/For_developer.md", "docs/UPDATE_SUMMARY.md"]
SIGNIFICANT_PREFIXES = (
    "server.py",
    "routes/",
    "services/",
    "security/",
    "public/js/",
    "public/css/",
    "templates/",
    "migrations/",
    "docs/UPDATE_SUMMARY.md",
)


def read_release_id(ctx: PrepushContext) -> str:
    source = (ctx.repo_root / RELEASE_FILE).read_text(encoding="utf-8")
    tree = ast.parse(source)
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "APP_RELEASE_ID":
                    if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
                        return node.value.value
    raise ValueError("APP_RELEASE_ID not found")


def run(ctx: PrepushContext) -> CheckResult:
    try:
        release_id = read_release_id(ctx)
    except Exception as exc:
        return CheckResult.fail("release id sync", str(exc), remediation="Define APP_RELEASE_ID in services/release_info.py.")

    missing = []
    for rel in DOCS:
        path = ctx.repo_root / rel
        if not path.exists() or release_id not in path.read_text(encoding="utf-8", errors="replace"):
            missing.append({"file": rel})
    if missing:
        return CheckResult.fail(
            "release id sync",
            f"release id {release_id} is missing from required docs",
            severity="medium",
            details=missing,
            remediation="Update README and docs/UPDATE_SUMMARY.md with the current APP_RELEASE_ID.",
        )

    changed = set(ctx.staged_files + ctx.changed_files)
    significant = sorted(item for item in changed if item.startswith(SIGNIFICANT_PREFIXES))
    if significant and RELEASE_FILE not in changed:
        message = "significant code/config files changed but release_info.py was not updated"
        details = [{"file": item} for item in significant[:40]]
        if ctx.strict:
            return CheckResult.fail(
                "release id sync",
                message,
                severity="medium",
                details=details,
                remediation="Bump APP_RELEASE_ID and update docs/UPDATE_SUMMARY.md before full/CI pre-push.",
            )
        return CheckResult.warn(
            "release id sync",
            message,
            details=details,
            remediation="Bump APP_RELEASE_ID before the final push.",
        )

    return CheckResult.pass_("release id sync", f"APP_RELEASE_ID {release_id} is documented")
