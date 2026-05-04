from pathlib import Path

from security.scan_plaintext_secrets import parse_allowlist, scan_file


def _write(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


def test_plaintext_secret_assignment_is_blocked(tmp_path):
    path = _write(tmp_path / "config.txt", "password" + "=hunter2\n")

    findings = scan_file(path, [])

    assert len(findings) == 1
    assert findings[0]["matched_rule"] == "plaintext_credential_assignment"
    assert findings[0]["masked_evidence"] == "password=<redacted>"


def test_json_password_literal_is_masked(tmp_path):
    path = _write(tmp_path / "fixture.json", '{"password": "hunter2"}\n')

    findings = scan_file(path, [])

    assert len(findings) == 1
    assert findings[0]["masked_evidence"] == '"password": <redacted>'
    assert "hunter2" not in findings[0]["masked_evidence"]


def test_private_key_marker_is_blocked_and_masked(tmp_path):
    path = _write(tmp_path / "key.txt", "-----BEGIN " + "PRIVATE KEY-----\n")

    findings = scan_file(path, [])

    assert len(findings) == 1
    assert findings[0]["matched_rule"] == "private_key_block"
    assert "PRIVATE KEY" in findings[0]["masked_evidence"]
    assert "BEGIN PRIVATE KEY" not in findings[0]["masked_evidence"]


def test_log_sensitive_values_are_blocked(tmp_path):
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    path = _write(log_dir / "app.log", "token" + "=abcdef123456\n")

    findings = scan_file(path, [])

    assert len(findings) == 1
    assert findings[0]["matched_rule"] == "log_sensitive_cookie_or_session"
    assert findings[0]["masked_evidence"] == "token=<redacted>"


def test_dynamic_password_handling_is_not_flagged(tmp_path):
    path = _write(
        tmp_path / "app.py",
        "\n".join([
            "password = data.get(" + repr("password") + ", " + repr("") + ")",
            "payload.password = password",
            "const payload = { password: pw };",
        ]),
    )

    findings = scan_file(path, [])

    assert findings == []


def test_allowlist_requires_metadata_and_expiry(tmp_path):
    allowlist = _write(
        tmp_path / "allowlist.yml",
        "\n".join([
            "allowlist:",
            "  - file: " + repr("tests/*"),
            "    pattern: " + repr("<redacted>"),
            "    reason: " + repr("fake fixture"),
            "    owner: " + repr("security"),
            "    expiry: " + repr("2099-01-01"),
        ]),
    )

    entries, errors = parse_allowlist(allowlist)

    assert errors == []
    assert entries[0]["reason"] == "fake fixture"


def test_expired_allowlist_fails(tmp_path):
    allowlist = _write(
        tmp_path / "allowlist.yml",
        "\n".join([
            "allowlist:",
            "  - file: " + repr("tests/*"),
            "    pattern: " + repr("<redacted>"),
            "    reason: " + repr("expired fixture"),
            "    owner: " + repr("security"),
            "    expiry: " + repr("2000-01-01"),
        ]),
    )

    _, errors = parse_allowlist(allowlist)

    assert errors
