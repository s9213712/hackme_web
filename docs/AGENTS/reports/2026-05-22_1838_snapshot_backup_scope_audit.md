# Snapshot Backup Scope Audit - 2026-05-22 18:38

## Confirmed Findings

- No new blocker found in the snapshot backup/restore changes.
- Residual unrelated gate failure: `tests/security/gates/test_security_defaults.py::test_initial_deploy_defaults_only_enable_management_and_security_modules` still fails because `feature_points_chain_enabled` is currently enabled by default but the production default whitelist test does not allow it.

## Scope Changes Verified

- Server snapshot now covers primary `database.db` plus split runtime DB labels: `auth`, `audit`, `control`, `chess_engine`.
- Portable snapshot export includes `databases/*.sqlite3.backup` entries listed in `checksums.sha256`.
- `runtime/database/points_chain_backups` is now included in runtime file roots.
- `runtime/storage/snapshots` and `.imports` are excluded from file archive collection and preserved during restore cleanup.
- Snapshot verification now rejects unsafe checksum paths before hashing files.

## QA Commands

- `python3 -m py_compile services/snapshots/service.py services/snapshots/schema.py services/server/container.py server.py` - pass
- `python3 -m pytest -q tests/snapshots/test_snapshots.py` - 53 passed
- `python3 -m pytest -q tests/frontend/admin/test_frontend_snapshot_actions.py tests/platform/test_bootstrap_compat.py` - 5 passed
- `git diff --check -- services/snapshots/service.py services/server/container.py server.py tests/snapshots/test_snapshots.py docs/09_SNAPSHOT_RESET_RESTORE.md` - pass
- `python3 -m pytest -q tests/security/gates/test_security_defaults.py` - 1 failed, 6 passed; failure is the unrelated `feature_points_chain_enabled` default whitelist mismatch above

## Residual Risk

- Logs and QA reports remain intentionally outside server snapshot scope. They should be archived separately if operational retention is required.
- The existing production default whitelist mismatch should be resolved before release gate, but it is not caused by this snapshot scope change.
