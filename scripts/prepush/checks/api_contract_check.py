from __future__ import annotations

import json

from scripts.prepush.context import PrepushContext
from scripts.prepush.result import CheckResult


CONTRACT = "tests/contracts/api_contract_snapshot.json"
REQUIRED_APIS = (
    "/api/healthz",
    "/api/me",
    "/api/login",
    "/api/admin/server-mode",
    "/api/points/wallet",
    "/api/cloud-drive/files",
    "/api/trading/markets",
)


def run(ctx: PrepushContext) -> CheckResult:
    path = ctx.repo_root / CONTRACT
    if not path.exists():
        return CheckResult.fail("API contract", "contract snapshot is missing", severity="medium", remediation=f"Create {CONTRACT}.")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return CheckResult.fail("API contract", f"contract JSON is invalid: {exc}", severity="medium")
    endpoints = data.get("endpoints", {})
    missing = [{"endpoint": endpoint} for endpoint in REQUIRED_APIS if endpoint not in endpoints]
    if missing:
        return CheckResult.fail("API contract", "required API contract entries are missing", severity="medium", details=missing)

    source_blob = "\n".join(path.read_text(encoding="utf-8", errors="replace") for path in sorted((ctx.repo_root / "routes").rglob("*.py")))
    absent = [{"endpoint": endpoint} for endpoint in REQUIRED_APIS if endpoint not in source_blob]
    if absent:
        return CheckResult.warn("API contract", "some contracted API literals were not found in routes", details=absent)
    return CheckResult.pass_("API contract", f"{len(REQUIRED_APIS)} critical API contracts are present")
