# Release Layout

This project keeps source, documentation, test scripts, and runtime data in
separate locations so a downloaded release starts cleanly.

## Tracked Source

| Path | Purpose |
|---|---|
| `server.py` | Flask entrypoint and runtime wiring. |
| `routes/` | HTTP route modules. |
| `services/` | Domain and persistence services. |
| `public/` | Browser assets. |
| `database/bootstrap.schema.sql` | Bootstrap schema only. Runtime SQLite databases are not tracked. |
| `tests/` | Automated regression tests. |
| `scripts/` | Operator and local validation scripts. |
| `security/` | Security, smoke, and pentest runner scripts. |
| `docs/` | User, admin, security, API, deployment, and release documentation. |

## Runtime Data

Runtime data is generated on the deployment host and must not be committed.

| Path | Runtime Data |
|---|---|
| `database/database.db` | SQLite runtime database. |
| `storage/` | Cloud Drive user files. |
| `reports/bugs/` | User bug reports. |
| `chats/` | Chat sidecar logs. |
| `anchors/` | Audit/integrity anchor files. |
| `logs/` | Server and audit text logs. |
| `security/reports/` | Security, smoke, and pentest reports. |
| `secure_backups/` | Legacy local PointsChain backup path; ignored. |
| `<runtime>/points_chain_backups/` | Current PointsChain ledger backup location when configured by runtime env. |
| `cert.pem`, `key.pem` | Local TLS files generated on first start. |
| `.chain_seed`, `.csrfkey`, `.fkey`, `.integrity_key`, `integrity_manifest.json` | Runtime secrets and integrity state generated locally. |

Tracked placeholder files such as `.gitkeep` are allowed only where an empty
directory needs to exist in a fresh checkout.

## Documentation Policy

- The repository root keeps only `README.md` and GitHub-required `SECURITY.md`.
- Long-form guides live under `docs/`.
- Security test usage guides live under `docs/security/`.
- Historical abandoned work lives under `docs/archive/`.
- Internal research belongs under `research/` or `docs/research/`; both are
  ignored and should not be part of release commits.

## Security Script Policy

- Executable test scripts live under `security/`.
- Generated reports live under `security/reports/`.
- Only `security/reports/.gitkeep` is tracked.
- Reports, raw responses, cookies, server output, and snapshots are local
  artifacts and should be regenerated when needed.

## Known Large Files

These files are intentionally still present but should be split in future
refactors because they are large maintenance surfaces:

- `public/index.html`
- `public/styles.css`
- `public/js/50-admin.js`
- `public/js/35-drive.js`
- `services/points_chain.py`
- `routes/files.py`
- `routes/community.py`
- `routes/system_admin.py`

Do not split these files during release cleanup. Split them only in dedicated
refactor branches with focused regression tests.

