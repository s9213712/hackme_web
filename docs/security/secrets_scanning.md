# Secrets Scanning

This project uses two layers of plaintext secret detection before code is merged:

- `gitleaks detect --source . --no-git --redact`
- `python3 scripts/security/scan_plaintext_secrets.py --fail-on high`

The custom scanner checks project-specific plaintext patterns such as credential
assignments, bearer authorization headers, private-key markers, and database
connection URLs. It also treats `logs/` specially: behavior logs are allowed,
but logs must not contain passwords, tokens, API keys, private keys, session IDs,
Authorization headers, cookies, or JWT material.

## Local Setup

Install pre-commit and gitleaks, then enable the hooks:

```bash
python3 -m pip install --user pre-commit
pre-commit install
```

Install `gitleaks` from the official project release instructions. The local
hook fails closed when `gitleaks` is missing so commits cannot silently skip the
generic scanner.

The gitleaks run uses `.gitleaks.toml` to exclude runtime/generated paths such
as local DB files, private runtime keys, snapshots, cache directories, and
generated reports.

Run the checks manually:

```bash
pre-commit run --all-files
python3 scripts/security/scan_plaintext_secrets.py --fail-on high
```

## Reports

The custom scanner writes masked reports to:

- `security/reports/secrets_scan_report.json`
- `security/reports/secrets_scan_report.md`

CI also uploads `security/reports/gitleaks_report.json` as an artifact. Reports
must not include complete secret values. Evidence is masked, for example:

- `token=<redacted>`
- `password=<redacted>`
- `Authorization: Bearer <redacted>`
- `postgres://<redacted>`

If a real secret has already been committed, rotate the secret immediately.
Deleting only the latest git version is not sufficient because earlier commits,
forks, caches, or CI logs may still contain it.

## Allowlist Policy

Temporary allowlist entries live in `security/secrets_allowlist.yml`. Each entry
must include:

- `file`
- `line` or `pattern`
- `reason`
- `owner`
- `expiry` in `YYYY-MM-DD`

Expired or incomplete allowlist entries fail the scan. Never allowlist real
private keys, real tokens, real passwords, production database URLs, session
secrets, or JWT signing secrets. Test fixtures should use clearly fake values
and a short-lived allowlist reason when needed.

## Fix Guidance

Passwords must not be stored in plaintext. Store only password hashes generated
with Argon2id or bcrypt.

Tokens, API keys, JWT secrets, and database URLs must live in environment
variables or a secret manager. Repository files should only keep examples such
as `.env.example` placeholders.

Logs must redact sensitive fields before writing them. Examples of acceptable
logged forms are `token=<redacted>` and `password=<redacted>`.
