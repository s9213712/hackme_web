from __future__ import annotations

import os
import sys

from scripts.prepush import utils
from scripts.prepush.context import PrepushContext
from scripts.prepush.result import CheckResult


QUICK_TESTS = [
    "tests/test_auth_csrf_safe.py",
    "tests/test_access_controls.py",
    "tests/test_prepush_v2.py",
    "tests/test_frontend_account_admin.py",
    "tests/test_account_sessions.py",
    "tests/test_comfyui_integration.py",
    "tests/test_cloud_drive_attachments.py",
    "tests/test_sanction_notices.py",
    "tests/test_trading_engine.py",
    "tests/test_remote_downloads.py",
    "tests/test_video_publish.py",
    "tests/test_security_issue_regressions.py",
    "tests/test_user_csv_exports.py",
]
QUICK_PYTEST_TIMEOUT_SECONDS = 180


def run(ctx: PrepushContext) -> CheckResult:
    if not utils.tool_exists("pytest"):
        return CheckResult.fail("quick pytest", "pytest is not installed", severity="high", remediation="Install test dependencies with pip.")
    tests = [rel for rel in QUICK_TESTS if (ctx.repo_root / rel).exists()]
    if not tests:
        return CheckResult.skip("quick pytest", "quick pytest target files are missing")
    env = utils.env_without_local_runtime()
    env["PYTHONPATH"] = str(ctx.repo_root)
    env["HTML_LEARNING_TEST_RUNTIME"] = "1"
    # The quick gate deliberately covers a wide cross-section of backend,
    # frontend, trading, and ComfyUI regressions. As the selected corpus grew,
    # the old 90s ceiling started producing internal timeout errors even when
    # the tests were actually green, so the hook needs a realistic budget.
    proc = utils.run_command(
        [sys.executable, "-m", "pytest", "-q", *tests],
        cwd=ctx.repo_root,
        timeout=QUICK_PYTEST_TIMEOUT_SECONDS,
        env=env,
    )
    if proc.returncode != 0:
        output = "\n".join((proc.stdout + proc.stderr).splitlines()[-80:])
        return CheckResult.fail(
            "quick pytest",
            "selected quick tests failed",
            severity="high",
            details=[{"output": utils.sanitize_path(output)}],
            remediation="Run the listed pytest command locally and fix failing tests.",
        )
    return CheckResult.pass_("quick pytest", f"passed {len(tests)} quick test file(s)")
