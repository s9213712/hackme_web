from __future__ import annotations

from scripts.prepush.context import PrepushContext
from scripts.prepush.result import CheckResult


REQUIRED_SYMBOLS = (
    "post_restore_validation",
    "restore_in_progress",
    "mode_switch_logs",
    "incident_lockdown",
)


def run(ctx: PrepushContext) -> CheckResult:
    source_paths = list((ctx.repo_root / "services").glob("*.py")) + list((ctx.repo_root / "routes").glob("*.py"))
    blob = "\n".join(path.read_text(encoding="utf-8", errors="replace") for path in source_paths)
    missing = [{"symbol": symbol} for symbol in REQUIRED_SYMBOLS if symbol not in blob]
    if missing:
        return CheckResult.fail(
            "snapshot restore gate",
            "restore safety symbols are missing",
            severity="high",
            details=missing,
            remediation="Restore must validate DB/files/PointsChain and enter incident_lockdown on failure.",
        )
    return CheckResult.pass_("snapshot restore gate", "restore safety hooks are present")
