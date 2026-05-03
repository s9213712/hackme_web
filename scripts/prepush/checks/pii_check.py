from __future__ import annotations

import re

from scripts.prepush import utils
from scripts.prepush.context import PrepushContext
from scripts.prepush.result import CheckResult


TAIWAN_ID = re.compile(r"\b[A-Z][12]\d{8}\b")
PHONE = re.compile(r"(?<!\d)(?:\+?886[- ]?)?09\d{2}[- ]?\d{3}[- ]?\d{3}(?!\d)")
EMAIL = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
ALLOW_EMAIL_DOMAINS = ("example.com", "example.org", "example.net", "test.local")


def run(ctx: PrepushContext) -> CheckResult:
    findings = []
    for path in utils.iter_repo_text_files(ctx.repo_root, sorted(set(ctx.staged_files))):
        rel = ctx.relpath(path)
        if rel.startswith("scripts/prepush/"):
            continue
        for line_no, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), start=1):
            if TAIWAN_ID.search(line):
                findings.append({"file": rel, "line": line_no, "pattern": "TAIWAN_ID"})
            if PHONE.search(line):
                findings.append({"file": rel, "line": line_no, "pattern": "PHONE"})
            email_match = EMAIL.search(line)
            if email_match and not email_match.group(0).endswith(ALLOW_EMAIL_DOMAINS):
                findings.append({"file": rel, "line": line_no, "pattern": "EMAIL"})
    if findings:
        return CheckResult.fail(
            "PII scan",
            "possible plaintext personal data in staged files",
            severity="high",
            details=findings[:80],
            remediation="Use synthetic example.com/test.local values or redact personal data before staging.",
        )
    return CheckResult.pass_("PII scan", "no staged plaintext PII patterns found")
