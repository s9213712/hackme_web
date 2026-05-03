from __future__ import annotations

from scripts.prepush import utils
from scripts.prepush.context import PrepushContext
from scripts.prepush.result import CheckResult


SCAN_EXTRA = (
    "README.md",
    "docs/README.zh-TW.md",
    "docs/00_START_HERE.md",
    "docs/01_DEPLOY_QUICKSTART.md",
    "docs/02_DEPLOY_PRODUCTION.md",
    "docs/03_ADMIN_GUIDE.md",
    "docs/04_USER_GUIDE.md",
    "docs/05_FEATURES_OVERVIEW.md",
    "docs/11_QA_TESTING.md",
    "docs/12_TROUBLESHOOTING.md",
    "docs/For_developer.md",
    "docs/DEPLOYMENT.md",
    "docs/UPDATE_SUMMARY.md",
    "scripts",
    "security",
)


def scan_line(rel: str, line: str, line_no: int) -> list[dict[str, object]]:
    findings = []
    for marker, name in utils.LOCAL_PATH_PATTERNS.items():
        if marker not in line:
            continue
        if rel in {"scripts/prepush/utils.py"}:
            continue
        if rel.startswith("scripts/prepush/"):
            continue
        if rel.startswith(("security/reports/", "reports/")):
            continue
        if rel.startswith("tests/") and ("sanitize" in line.lower() or "local path" in line.lower()):
            continue
        findings.append({"file": rel, "line": line_no, "pattern": name})
    return findings


def run(ctx: PrepushContext) -> CheckResult:
    targets: list[str] = sorted(set(ctx.staged_files + list(SCAN_EXTRA)))
    expanded = []
    for rel in targets:
        path = ctx.repo_root / rel
        if path.is_file():
            expanded.append(rel)
        elif path.is_dir():
            expanded.extend(item.relative_to(ctx.repo_root).as_posix() for item in path.rglob("*") if item.is_file())
    findings = []
    for path in utils.iter_repo_text_files(ctx.repo_root, expanded):
        rel = ctx.relpath(path)
        for line_no, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), start=1):
            findings.extend(scan_line(rel, line, line_no))
    if findings:
        return CheckResult.fail(
            "local path leak",
            "local workstation/runtime path markers found",
            severity="high",
            details=findings[:80],
            remediation="Replace machine-specific paths with relative paths or placeholders.",
        )
    return CheckResult.pass_("local path leak", "no local path markers found")
