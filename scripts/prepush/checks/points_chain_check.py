from __future__ import annotations

from scripts.prepush.context import PrepushContext
from scripts.prepush.result import CheckResult


REQUIRED_MARKERS = (
    "verify_chain",
    "rebuild_wallet",
    "safe_mode",
    "backup restore is disabled",
)


def run(ctx: PrepushContext) -> CheckResult:
    paths = list((ctx.repo_root / "services").rglob("*points*.py")) + list((ctx.repo_root / "services" / "points_chain").rglob("*.py")) + [ctx.repo_root / "routes" / "economy.py"]
    blob = "\n".join(path.read_text(encoding="utf-8", errors="replace") for path in paths if path.exists()).lower()
    missing = [{"marker": marker} for marker in REQUIRED_MARKERS if marker.lower() not in blob]
    if missing:
        return CheckResult.warn(
            "PointsChain gate",
            "some PointsChain safety markers were not found by static scan",
            details=missing,
            remediation="Confirm ledger verification, wallet replay, safe mode, and disabled backup-restore policy remain wired.",
        )
    return CheckResult.pass_("PointsChain gate", "ledger verification/rebuild/safe-mode markers are present")
