from __future__ import annotations

from scripts.prepush.context import PrepushContext
from scripts.prepush.result import CheckResult


def run(ctx: PrepushContext) -> CheckResult:
    source_paths = list((ctx.repo_root / "routes").rglob("*.py")) + list((ctx.repo_root / "services").rglob("*.py"))
    source = "\n".join(path.read_text(encoding="utf-8", errors="replace") for path in sorted(source_paths))
    markers = ("verify_mode_switch_logs", "prev_hash", "row_hash", "hmac_signature")
    missing = [{"marker": marker} for marker in markers if marker not in source]
    if missing:
        return CheckResult.fail("log hash chain", "mode switch log hash-chain verification markers missing", severity="high", details=missing)
    return CheckResult.pass_("log hash chain", "mode switch log hash-chain verification API is present")
