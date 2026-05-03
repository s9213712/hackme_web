from __future__ import annotations

from scripts.prepush import utils
from scripts.prepush.context import PrepushContext
from scripts.prepush.result import CheckResult


def run(ctx: PrepushContext) -> CheckResult:
    if not utils.tool_exists("node"):
        if ctx.is_ci:
            return CheckResult.fail("frontend JS syntax", "node is missing in CI", severity="medium", remediation="Install node or disable frontend syntax gate explicitly.")
        return CheckResult.skip("frontend JS syntax", "node is not installed; skipped local JS syntax check")
    js_files = [path for path in sorted((ctx.repo_root / "public" / "js").glob("*.js")) if ".min." not in path.name]
    failures = []
    for path in js_files:
        proc = utils.run_command(["node", "--check", str(path)], cwd=ctx.repo_root, timeout=15)
        if proc.returncode != 0:
            failures.append({"file": ctx.relpath(path), "output": utils.sanitize_path(proc.stderr)[-1000:]})
    if failures:
        return CheckResult.fail(
            "frontend JS syntax",
            "node --check failed",
            severity="high",
            details=failures[:40],
            remediation="Fix JavaScript syntax errors in public/js.",
        )
    return CheckResult.pass_("frontend JS syntax", f"checked {len(js_files)} JS file(s)")
