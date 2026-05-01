#!/usr/bin/env python3
"""Plaintext secret scanner for local hooks and CI.

The scanner intentionally reports masked evidence only. It is not a replacement
for gitleaks/trufflehog; it catches project-specific plaintext patterns that are
easy to miss with generic entropy detectors.
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Iterable


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_JSON_REPORT = ROOT / "security" / "reports" / "secrets_scan_report.json"
DEFAULT_MD_REPORT = ROOT / "security" / "reports" / "secrets_scan_report.md"
DEFAULT_ALLOWLIST = ROOT / "security" / "secrets_allowlist.yml"

EXCLUDED_DIRS = {
    ".git",
    ".venv",
    "__pycache__",
    "build",
    "coverage",
    "dist",
    "node_modules",
    "vendor",
    "venv",
}
EXCLUDED_BINARY_SUFFIXES = {
    ".7z",
    ".avif",
    ".bmp",
    ".class",
    ".db",
    ".dll",
    ".exe",
    ".gif",
    ".gz",
    ".ico",
    ".jar",
    ".jpeg",
    ".jpg",
    ".pdf",
    ".png",
    ".pyc",
    ".sqlite",
    ".sqlite3",
    ".tar",
    ".webp",
    ".zip",
}
REPORT_GLOBS = {
    "security/reports/*.json",
    "security/reports/*.md",
}
SAFE_DYNAMIC_RHS = {
    "csrf",
    "currentPassword",
    "password",
    "passwordConfirm",
    "pw",
    "pwConfirm",
}
SAFE_PLACEHOLDER_RE = re.compile(r"(?i)^(<redacted>|redacted|changeme|change-me|replace-me|replace_me|example|dummy|placeholder|null|none|true|false)$")
SAFE_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


@dataclass(frozen=True)
class Rule:
    name: str
    regex: re.Pattern[str]
    risk: str
    recommendation: str
    logs_only: bool = False


RULES = [
    Rule(
        "plaintext_credential_assignment",
        re.compile(r"(?i)['\"]?\b(password|passwd|secret|jwt_secret|api_key|access_token|refresh_token)\b['\"]?\s*[:=]\s*['\"]?([^'\"\s#,;}]+)"),
        "high",
        "Move the value to an environment variable or secret manager; store passwords only as Argon2id/bcrypt hashes.",
    ),
    Rule(
        "authorization_header",
        re.compile(r"(?i)\bAuthorization\s*:\s*(Bearer|Basic)\s+[A-Za-z0-9._~+/=-]{8,}"),
        "high",
        "Do not commit Authorization headers. Use runtime secrets and redact logs.",
    ),
    Rule(
        "bearer_token",
        re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]{16,}"),
        "high",
        "Move bearer tokens to a secret manager and rotate the token if it was real.",
    ),
    Rule(
        "private_key_block",
        re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----"),
        "high",
        "Remove private keys from the repository and rotate the key immediately if it was real.",
    ),
    Rule(
        "database_connection_url",
        re.compile(r"(?i)\b(mysql|postgres|postgresql|redis|mongodb)://[^\s'\"<>]+"),
        "high",
        "Move DB connection strings to environment variables; rotate credentials if exposed.",
    ),
    Rule(
        "log_sensitive_cookie_or_session",
        re.compile(r"(?i)\b(cookie|set-cookie|session(?:_id)?|token|api_key|password)\b\s*[:=]\s*[^;\s]+"),
        "high",
        "Logs must mask cookies, session IDs, tokens, API keys, and passwords.",
        logs_only=True,
    ),
]

RISK_ORDER = {"low": 1, "medium": 2, "high": 3}


def relpath(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def is_excluded(path: Path) -> bool:
    relative = relpath(path)
    parts = set(Path(relative).parts)
    if parts & EXCLUDED_DIRS:
        return True
    if path.suffix.lower() in EXCLUDED_BINARY_SUFFIXES:
        return True
    return any(fnmatch.fnmatch(relative, pattern) for pattern in REPORT_GLOBS)


def is_probably_binary(path: Path) -> bool:
    try:
        chunk = path.read_bytes()[:4096]
    except OSError:
        return True
    return b"\x00" in chunk


def git_files(include_untracked: bool) -> list[Path]:
    cmd = ["git", "-C", str(ROOT), "ls-files", "--cached"]
    if include_untracked:
        cmd = ["git", "-C", str(ROOT), "ls-files", "--cached", "--others", "--exclude-standard"]
    try:
        result = subprocess.run(cmd, check=True, capture_output=True, text=True)
    except Exception:
        return []
    files: list[Path] = []
    for line in result.stdout.splitlines():
        if line.strip():
            files.append(ROOT / line.strip())
    return files


def walk_files() -> list[Path]:
    files: list[Path] = []
    for current_root, dirnames, filenames in os.walk(ROOT):
        dirnames[:] = [d for d in dirnames if d not in EXCLUDED_DIRS]
        for filename in filenames:
            files.append(Path(current_root) / filename)
    return files


def collect_files(args: argparse.Namespace) -> list[Path]:
    if args.paths:
        candidates = [Path(item).resolve() for item in args.paths]
    else:
        candidates = git_files(args.scan_untracked) or walk_files()
    clean = []
    seen = set()
    for path in candidates:
        if not path.is_file() or is_excluded(path) or is_probably_binary(path):
            continue
        key = path.resolve()
        if key in seen:
            continue
        seen.add(key)
        clean.append(path)
    return clean


def parse_allowlist(path: Path) -> tuple[list[dict], list[str]]:
    if not path.exists():
        return [], [f"allowlist file not found: {relpath(path)}"]
    entries: list[dict] = []
    errors: list[str] = []
    current: dict | None = None
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or line == "allowlist:":
            continue
        if line.startswith("- "):
            if current is not None:
                entries.append(current)
            current = {}
            line = line[2:].strip()
            if line:
                key, value = parse_yaml_pair(line)
                current[key] = value
            continue
        if current is None:
            errors.append(f"invalid allowlist line: {raw_line}")
            continue
        key, value = parse_yaml_pair(line)
        current[key] = value
    if current is not None:
        entries.append(current)

    today = date.today()
    for index, entry in enumerate(entries, start=1):
        missing = [key for key in ("file", "reason", "owner", "expiry") if not entry.get(key)]
        if missing:
            errors.append(f"allowlist entry {index} missing required fields: {', '.join(missing)}")
        if not entry.get("line") and not entry.get("pattern"):
            errors.append(f"allowlist entry {index} must define line or pattern")
        try:
            expiry = datetime.strptime(str(entry.get("expiry", "")), "%Y-%m-%d").date()
            if expiry < today:
                errors.append(f"allowlist entry {index} expired on {entry.get('expiry')}")
        except ValueError:
            errors.append(f"allowlist entry {index} has invalid expiry date: {entry.get('expiry')}")
    return entries, errors


def parse_yaml_pair(line: str) -> tuple[str, str]:
    if ":" not in line:
        return line, ""
    key, value = line.split(":", 1)
    value = value.strip()
    if len(value) >= 2 and value[0] in {"'", '"'} and value[-1] == value[0]:
        value = value[1:-1]
    return key.strip(), value


def is_allowlisted(finding: dict, entries: Iterable[dict]) -> bool:
    path = finding["file_path"]
    evidence = finding["masked_evidence"]
    line_number = finding["line_number"]
    rule = finding["matched_rule"]
    for entry in entries:
        if not fnmatch.fnmatch(path, str(entry.get("file", ""))):
            continue
        if entry.get("rule") and entry["rule"] != rule:
            continue
        if entry.get("line") and str(entry["line"]) != str(line_number):
            continue
        pattern = entry.get("pattern")
        if pattern and not re.search(str(pattern), evidence):
            continue
        return True
    return False


def mask_evidence(text: str) -> str:
    text = text.strip()
    text = re.sub(r"(?i)(Authorization\s*:\s*)(Bearer|Basic)\s+[^\s]+", r"\1\2 <redacted>", text)
    text = re.sub(r"(?i)\bBearer\s+[^\s]+", "Bearer <redacted>", text)
    text = re.sub(r"(?i)\b(mysql|postgres|postgresql|redis|mongodb)://[^\s'\"<>]+", r"\1://<redacted>", text)
    text = re.sub(
        r"(?i)(['\"]?\b(password|passwd|secret|jwt_secret|api_key|access_token|refresh_token|cookie|set-cookie|session(?:_id)?|token)\b['\"]?\s*[:=]\s*)['\"]?[^;\s,}]+",
        r"\1<redacted>",
        text,
    )
    if "PRIVATE KEY" in text:
        return "-----BEGIN <redacted> PRIVATE KEY-----"
    if len(text) > 160:
        return text[:120] + "...<truncated>"
    return text


def is_safe_dynamic_assignment(rule: Rule, match: re.Match[str]) -> bool:
    if rule.name != "plaintext_credential_assignment":
        return False
    rhs = (match.group(2) or "").strip().strip("'\"").rstrip("):")
    if not rhs:
        return True
    if rhs in SAFE_DYNAMIC_RHS:
        return True
    if SAFE_IDENTIFIER_RE.match(rhs) and ("_" in rhs or any(ch.isupper() for ch in rhs)):
        return True
    if rhs in {"[]", "{}"} or rhs.startswith(("[", "{")):
        return True
    if rhs.startswith(("password[", "pw[", "secret[", "token[")):
        return True
    if SAFE_PLACEHOLDER_RE.match(rhs):
        return True
    if rhs.startswith(("data.get(", "request.", "os.environ.", "settings.get(", "getenv(")):
        return True
    if "(" in rhs or "." in rhs:
        return True
    # Examples such as replace-me-with-long-random-string in .env.example are
    # acceptable placeholders. Real high-entropy values are handled by gitleaks.
    if "replace-me" in rhs.lower() or rhs.lower().endswith("-example"):
        return True
    return False


def scan_file(path: Path, allowlist: list[dict]) -> list[dict]:
    relative = relpath(path)
    is_log = relative.startswith("logs/") or path.suffix.lower() == ".log"
    findings = []
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError as exc:
        return [{
            "file_path": relative,
            "line_number": 0,
            "matched_rule": "read_error",
            "risk_level": "medium",
            "masked_evidence": str(exc),
            "recommendation": "Ensure CI can read the file or exclude it with a documented reason.",
            "allowlisted": False,
        }]
    for line_number, line in enumerate(lines, start=1):
        for rule in RULES:
            if rule.logs_only and not is_log:
                continue
            for match in rule.regex.finditer(line):
                if is_safe_dynamic_assignment(rule, match):
                    continue
                finding = {
                    "file_path": relative,
                    "line_number": line_number,
                    "matched_rule": rule.name,
                    "risk_level": rule.risk,
                    "masked_evidence": mask_evidence(match.group(0)),
                    "recommendation": rule.recommendation,
                    "allowlisted": False,
                }
                finding["allowlisted"] = is_allowlisted(finding, allowlist)
                findings.append(finding)
    return findings


def write_reports(findings: list[dict], allowlist_errors: list[str], files_checked: int, json_path: Path, md_path: Path) -> None:
    json_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "files_checked": files_checked,
        "finding_count": len(findings),
        "blocking_finding_count": len([item for item in findings if not item["allowlisted"]]),
        "allowlist_errors": allowlist_errors,
        "findings": findings,
        "rotation_notice": "If a real secret was committed, rotate it immediately; deleting only the latest git version is not sufficient.",
    }
    json_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    rows = [
        "# Secrets Scan Report",
        "",
        f"- Generated at: `{payload['generated_at']}`",
        f"- Files checked: `{files_checked}`",
        f"- Findings: `{len(findings)}`",
        f"- Blocking findings: `{payload['blocking_finding_count']}`",
        "",
        "If a real secret was committed, rotate it immediately; deleting only the latest git version is not sufficient.",
        "",
    ]
    if allowlist_errors:
        rows.extend(["## Allowlist Errors", ""])
        rows.extend(f"- {error}" for error in allowlist_errors)
        rows.append("")
    if findings:
        rows.extend([
            "## Findings",
            "",
            "| File | Line | Rule | Risk | Allowlisted | Evidence | Recommendation |",
            "|---|---:|---|---|---|---|---|",
        ])
        for item in findings:
            rows.append(
                "| {file} | {line} | {rule} | {risk} | {allowlisted} | `{evidence}` | {recommendation} |".format(
                    file=item["file_path"],
                    line=item["line_number"],
                    rule=item["matched_rule"],
                    risk=item["risk_level"],
                    allowlisted="yes" if item["allowlisted"] else "no",
                    evidence=item["masked_evidence"].replace("|", "\\|"),
                    recommendation=item["recommendation"].replace("|", "\\|"),
                )
            )
    else:
        rows.extend(["## Findings", "", "No plaintext secret findings."])
    md_path.write_text("\n".join(rows) + "\n", encoding="utf-8")


def should_fail(findings: list[dict], allowlist_errors: list[str], threshold: str) -> bool:
    if allowlist_errors:
        return True
    threshold_rank = RISK_ORDER[threshold]
    for finding in findings:
        if finding["allowlisted"]:
            continue
        if RISK_ORDER.get(finding["risk_level"], 0) >= threshold_rank:
            return True
    return False


def main() -> int:
    parser = argparse.ArgumentParser(description="Scan repository files for plaintext secrets.")
    parser.add_argument("--allowlist", default=str(DEFAULT_ALLOWLIST))
    parser.add_argument("--report-json", default=str(DEFAULT_JSON_REPORT))
    parser.add_argument("--report-md", default=str(DEFAULT_MD_REPORT))
    parser.add_argument("--fail-on", choices=sorted(RISK_ORDER), default="high")
    parser.add_argument("--scan-untracked", action="store_true", help="Include untracked non-ignored files.")
    parser.add_argument("--paths", nargs="*", help="Scan specific files instead of git-tracked files.")
    args = parser.parse_args()

    allowlist, allowlist_errors = parse_allowlist(Path(args.allowlist))
    files = collect_files(args)
    findings: list[dict] = []
    for path in files:
        findings.extend(scan_file(path, allowlist))
    write_reports(findings, allowlist_errors, len(files), Path(args.report_json), Path(args.report_md))

    blocking = [finding for finding in findings if not finding["allowlisted"]]
    if should_fail(findings, allowlist_errors, args.fail_on):
        print(f"Plaintext secrets scan failed: {len(blocking)} blocking finding(s), {len(allowlist_errors)} allowlist error(s).")
        print(f"Report: {relpath(Path(args.report_md))}")
        return 1
    print(f"Plaintext secrets scan passed: {len(files)} file(s), {len(findings)} finding(s), {len(blocking)} blocking.")
    print(f"Report: {relpath(Path(args.report_md))}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
