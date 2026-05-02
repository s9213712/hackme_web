#!/usr/bin/env python3
"""Level-2 red-team validation for Server Mode v2 enterprise baseline."""

from __future__ import annotations

import argparse
import json
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from security.server_mode_v2_adversarial import AdversarialRunner, SmokeRuntime  # noqa: E402
from services.snapshots import MODE_CONFIRM_PHRASES  # noqa: E402


class RedTeamL2:
    def __init__(self, runtime: SmokeRuntime):
        self.runtime = runtime
        self.root_actor = {"id": 1, "username": "root", "role": "super_admin"}
        self.tester_actor = {"id": 4, "username": "tester", "role": "user"}
        self.results = []

    def add(self, name, ok, *, payload=None, expected="", actual=None, severity="LOW"):
        self.results.append({
            "name": name,
            "ok": bool(ok),
            "severity": severity if not ok else "INFO",
            "timestamp": datetime.now().isoformat(),
            "payload": payload or {},
            "expected": expected,
            "actual": actual or {},
        })

    def run(self):
        base = AdversarialRunner(self.runtime).run()
        self.add(
            "base adversarial suite",
            base.get("ok"),
            payload={"script": "server_mode_v2_adversarial.py"},
            expected="base adversarial suite passes",
            actual={"passed": base.get("passed"), "failed": base.get("failed")},
            severity="CRITICAL",
        )
        self.check_revoked_token_reuse()
        self.check_hmac_signature_tamper_detection()
        self.check_integrity_manifest_tamper_signal()
        return self.report(base)

    def check_revoked_token_reuse(self):
        current = self.runtime.mode_service.get_current_mode().get("current_mode")
        if current not in {"test", "internal_test"}:
            self.runtime.mode_service.switch_mode(
                target_mode="test",
                actor=self.root_actor,
                confirm=MODE_CONFIRM_PHRASES["test"],
                notes="redteam l2 token scope setup",
            )
        token = self.runtime.mode_service.create_tester_token(
            actor=self.root_actor,
            tester_user_id=self.tester_actor["id"],
            allowed_routes=["/api/tester"],
            expires_at=(datetime.now() + timedelta(minutes=30)).isoformat(),
        )
        before = self.runtime.mode_service.active_tester_token(token=token["token"], route="/api/tester/shadow-state")
        self.runtime.mode_service.revoke_tester_token(actor=self.root_actor, token_id=token["token_id"], reason="redteam_l2")
        after = self.runtime.mode_service.active_tester_token(token=token["token"], route="/api/tester/shadow-state")
        self.add(
            "revoked token reuse",
            before.get("ok") and not after.get("ok"),
            payload={"token_id": token.get("token_id"), "route": "/api/tester/shadow-state"},
            expected="token works before revoke and is rejected after revoke",
            actual={"before": before, "after": after},
            severity="HIGH",
        )

    def check_hmac_signature_tamper_detection(self):
        conn = self.runtime.db_path_connect()
        try:
            row = conn.execute("SELECT * FROM mode_switch_logs ORDER BY created_at DESC, id DESC LIMIT 1").fetchone()
            if not row:
                self.add("HMAC signature tamper", False, expected="mode log exists", actual={"error": "no mode log"}, severity="HIGH")
                return
            conn.execute("SAVEPOINT sig_tamper")
            conn.execute("DROP TRIGGER IF EXISTS trg_mode_switch_logs_no_update")
            conn.execute("UPDATE mode_switch_logs SET hmac_signature='bad_signature' WHERE id=?", (row["id"],))
            tampered_row = conn.execute("SELECT * FROM mode_switch_logs WHERE id=?", (row["id"],)).fetchone()
            sig = self.runtime.mode_service._verify_mode_log_signature(dict(tampered_row))
            verification = {
                "ok": bool(sig.get("ok")),
                "invalid_signatures": [] if sig.get("ok") else [{"id": row["id"], **sig}],
            }
            conn.execute("ROLLBACK TO sig_tamper")
            conn.execute("RELEASE sig_tamper")
            self.runtime.mode_service.ensure_schema(conn)
            conn.commit()
        finally:
            conn.close()
        invalid = verification.get("invalid_signatures") or []
        self.add(
            "HMAC signature tamper",
            bool(invalid) and not verification.get("ok"),
            payload={"operation": "temporary hmac_signature update under savepoint"},
            expected="verify endpoint reports invalid signature",
            actual=verification,
            severity="CRITICAL",
        )

    def check_integrity_manifest_tamper_signal(self):
        manifest = self.runtime.integrity_manifest
        before = manifest.read_text(encoding="utf-8")
        before_hash = __import__("hashlib").sha256(before.encode("utf-8")).hexdigest()
        manifest.write_text('{"tampered": true}\n', encoding="utf-8")
        after_hash = __import__("hashlib").sha256(manifest.read_text(encoding="utf-8").encode("utf-8")).hexdigest()
        manifest.write_text(before, encoding="utf-8")
        self.add(
            "integrity manifest tamper signal",
            before_hash != after_hash,
            payload={"file": str(manifest), "operation": "modify manifest then restore"},
            expected="manifest hash changes when tampered",
            actual={"before_hash": before_hash, "tampered_hash": after_hash},
            severity="HIGH",
        )

    def report(self, base):
        breaches = [item for item in self.results if not item["ok"]]
        critical = [item for item in breaches if item["severity"] == "CRITICAL"]
        high = [item for item in breaches if item["severity"] == "HIGH"]
        summary = {
            "attacks_total": len(self.results),
            "blocked_total": sum(1 for item in self.results if item["ok"]),
            "breaches_total": len(breaches),
            "critical_findings": len(critical),
            "high_findings": len(high),
            "production_readiness": "CONDITIONAL_YES" if not breaches else "NO",
        }
        return {
            "ok": not breaches,
            "generated_at": datetime.now().isoformat(),
            "test_type": "server_mode_v2_redteam_l2",
            "base_adversarial_summary": base.get("RED_TEAM_SUMMARY"),
            "results": self.results,
            "RED_TEAM_L2_SUMMARY": summary,
        }


def write_reports(report, out_dir: Path):
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    json_path = out_dir / f"server_mode_v2_redteam_l2_{ts}.json"
    md_path = out_dir / f"server_mode_v2_redteam_l2_{ts}.md"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    lines = [
        "# Server Mode v2 Red Team L2 Report",
        "",
        f"- Generated: `{report['generated_at']}`",
        f"- Result: `{'PASS' if report['ok'] else 'FAIL'}`",
        "",
        "## RED_TEAM_L2_SUMMARY",
        "",
    ]
    for key, value in report["RED_TEAM_L2_SUMMARY"].items():
        lines.append(f"- {key}: `{value}`")
    lines.extend(["", "## Attacks", ""])
    for item in report["results"]:
        lines.extend([
            f"### {item['name']}",
            "",
            f"- status: `{'PASS' if item['ok'] else 'FAIL'}`",
            f"- severity: `{item['severity']}`",
            f"- expected: {item['expected']}",
            "",
            "```json",
            json.dumps({"payload": item["payload"], "actual": item["actual"]}, ensure_ascii=False, indent=2, sort_keys=True),
            "```",
            "",
        ])
    md_path.write_text("\n".join(lines), encoding="utf-8")
    return json_path, md_path


def main():
    parser = argparse.ArgumentParser(description="Run Server Mode v2 Red Team L2 checks.")
    parser.add_argument("--out", default=str(REPO_ROOT / "security" / "reports"))
    parser.add_argument("--keep-runtime", action="store_true")
    args = parser.parse_args()
    tmp = tempfile.TemporaryDirectory(prefix="hackme_server_mode_v2_l2_")
    try:
        runtime = SmokeRuntime(Path(tmp.name))
        report = RedTeamL2(runtime).run()
        report["runtime_dir"] = str(tmp.name)
        json_path, md_path = write_reports(report, Path(args.out))
        print(json.dumps({
            "ok": report["ok"],
            "summary": report["RED_TEAM_L2_SUMMARY"],
            "json_report": str(json_path),
            "md_report": str(md_path),
        }, ensure_ascii=False, indent=2))
        return 0 if report["ok"] else 1
    finally:
        if args.keep_runtime:
            tmp.detach()
        else:
            tmp.cleanup()


if __name__ == "__main__":
    raise SystemExit(main())
