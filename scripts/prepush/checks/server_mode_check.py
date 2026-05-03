from __future__ import annotations

import sys

from scripts.prepush import utils
from scripts.prepush.context import PrepushContext
from scripts.prepush.result import CheckResult


def run(ctx: PrepushContext) -> CheckResult:
    script = ctx.repo_root / "security" / "server_mode_v2_clean_smoke.py"
    if not script.exists():
        return CheckResult.fail("Server Mode v2", "server_mode_v2_clean_smoke.py is missing", severity="critical")
    out_dir = ctx.ensure_temp_root() / "server_mode_reports"
    out_dir.mkdir(parents=True, exist_ok=True)
    command = [sys.executable, str(script), "--out", str(out_dir)]
    if not ctx.is_ci:
        command.append("--keep-runtime")
    proc = utils.run_command(command, cwd=ctx.repo_root, timeout=240)
    if proc.returncode != 0:
        output = "\n".join((proc.stdout + proc.stderr).splitlines()[-80:])
        return CheckResult.fail(
            "Server Mode v2",
            "clean smoke failed",
            severity="high",
            details=[{"output": utils.sanitize_path(output), "out": ctx.sanitize_path(out_dir)}],
            remediation="Run security/server_mode_v2_clean_smoke.py and inspect generated report.",
        )
    return CheckResult.pass_("Server Mode v2", "clean mode-switch smoke passed", details=[{"out": ctx.sanitize_path(out_dir)}])
