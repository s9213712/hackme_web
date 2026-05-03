from __future__ import annotations

from scripts.prepush.context import PrepushContext
from scripts.prepush.result import CheckResult


def run(ctx: PrepushContext) -> CheckResult:
    source = (ctx.repo_root / "routes" / "system_admin.py").read_text(encoding="utf-8", errors="replace")
    markers = ("verify_mode_switch_logs", "prev_hash", "row_hash", "hmac_signature")
    missing = [{"marker": marker} for marker in markers if marker not in source]
    if missing:
        return CheckResult.fail("log hash chain", "mode switch log hash-chain verification markers missing", severity="high", details=missing)
    return CheckResult.pass_("log hash chain", "mode switch log hash-chain verification API is present")
