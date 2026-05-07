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
| `bootstrap.schema.sql` | Bootstrap schema only. Runtime SQLite databases are not tracked. |
| `tests/` | Automated regression tests. |
| `scripts/` | Operator, validation, security, and feature probe scripts. |
| `docs/` | User, admin, security, API, deployment, and release documentation. |

## Runtime Data

Runtime data is generated on the deployment host and must not be committed.
A fresh checkout starts in `test` server mode. Chat messages, forum content,
Cloud Drive files, PointsChain ledger rows, PointsChain blocks, ledger backups,
and audit chain rows are expected to start empty. Admin initial grants and
weekly salary jobs are not run at startup unless the operator explicitly sets
`HTML_LEARNING_BOOTSTRAP_POINTS_CHAIN=true` for a controlled test environment.

| Path | Runtime Data |
|---|---|
| `runtime/database/database.db` | SQLite runtime database. |
| `runtime/database/chess_experiment.db` | 西洋棋 `experiment` 難度的獨立學習資料庫。 |
| `runtime/models/chess_experiment_2_nn.json` | 西洋棋 `experiment 2:nn` 難度的獨立模型檔。 |
| `runtime/storage/` | Cloud Drive user files. |
| `runtime/reports/bugs/` | User bug reports. |
| `runtime/reports/server_mode_audit/` | Server mode audit export JSON / JSONL / SHA256 bundles. |
| `runtime/chats/` | Chat sidecar logs. |
| `runtime/anchors/` | Audit/integrity anchor files. |
| `runtime/logs/` | Server and audit text logs. |
| `runtime/reports/security/` | Security, smoke, and pentest reports. |
| `runtime/reports/games/` | 西洋棋自動對弈訓練報告。 |
| `secure_backups/` | Legacy local PointsChain backup path; ignored. |
| `runtime/database/points_chain_backups/` | Current PointsChain ledger backup location when using the default runtime layout. |
| `runtime/cert.pem`, `runtime/key.pem` | Local TLS files generated on first start. |
| `runtime/.chain_seed`, `runtime/.csrfkey`, `runtime/.fkey`, `runtime/.filekey`, `runtime/.integrity_key`, `runtime/integrity_manifest.json` | Runtime secrets and integrity state generated locally. |

Legacy root folders such as `attachments/`, `avatars/`, `media/`, and
`uploads/` are not canonical runtime homes anymore. Snapshot/reset wiring now
clears the canonical runtime roots (`runtime/storage/`, `runtime/chats/`)
instead of recreating those repo-root folders. Leftover legacy directories
should be treated as migration or cleanup targets, not as valid storage design.

Tracked placeholder files such as `.gitkeep` are allowed only where an empty
directory needs to exist in a fresh checkout.

## Documentation Policy

- The repository root keeps only `README.md` and GitHub-required `SECURITY.md`.
- Long-form guides live under `docs/`.
- Placement and cleanup policy lives in `docs/REPOSITORY_STRUCTURE.md`.
- Security test usage guides live under `docs/security/`.
- Historical abandoned work lives under `docs/archive/`.
- Internal research belongs under `research/` or `docs/research/`; both are
  ignored and should not be part of release commits.

## Security Script Policy

- Executable security test scripts live under `scripts/security/`.
- Generated reports live under `runtime/reports/security/`.
- Reports, raw responses, cookies, server output, and snapshots are local
  artifacts and should be regenerated when needed.

## Known Large Files

These files are intentionally still present but should be split in future
refactors because they are large maintenance surfaces:

- `public/index.html`
- `public/styles.css`
- `public/js/50-admin.js`
- `public/js/35-drive.js`
- `services/points_chain/service.py`
- `routes/files.py`
- `routes/community.py`
- `routes/system_admin.py`

Do not split these files during release cleanup. Split them only in dedicated
refactor branches with focused regression tests.
