# 2026-05-24 22:46 Database Domain Split Pass

## Findings

### P0 - `database.db` still contains financial and E2EE metadata

The live main DB has 191 application tables.  Although `auth.db`, `audit.db`,
and `control.db` already exist, the main DB still contains:

- Storage/E2EE catalog: 32 tables / 716 rows.
- PointsChain: 38 tables / 586 rows.
- Trading/accounting: 39 tables / 5921 rows during export.
- Job center: 2 tables / 853 rows.

Impact: backup/restore, file compromise, accidental corruption, and lock
contention are still coupled across unrelated domains until runtime routing is
fully migrated.

Evidence: `python3 scripts/admin/split_main_database.py --source /tmp/hackme_web_pc0_5000_wallet_ui/runtime/database/database.db --mode analyze`

### P1 - Direct table moving is unsafe without service routing changes

Many split candidates still have `REFERENCES users` or direct joins to
`users/uploaded_files`, and trading still writes PointsChain ledger entries in
the same service flow.  Blindly dropping those tables from `database.db` would
break routes or financial invariants.

## Changes

- Added canonical table-domain map and non-destructive export helper in
  `services/server/domain_databases.py`.
- Added operator CLI `scripts/admin/split_main_database.py`.
- Added architecture note `docs/architecture/DATABASE_DOMAIN_SPLIT.md`.
- Added future runtime/snapshot DB path labels for:
  `storage_catalog.db`, `points_chain.db`, `trading.db`, `jobs.db`.
- Added unit coverage in `tests/platform/test_domain_database_split.py`.

## Live Export

Non-destructive live export path:

`/tmp/hackme_db_domain_split_live`

Exported files:

- `storage_catalog.db`: 32 tables / 716 rows / `b88e9f285887e576306f8855659bc11108c732095fd07db421dbc36edc90be7a`
- `points_chain.db`: 38 tables / 586 rows / `5c76268e12008c6fec4d8aa4f813da2ca0c5a0b4e68b37897a95c4a2b9b7beb3`
- `trading.db`: 39 tables / 5921 rows / `75cdee7d4375737f091c843948bfe6a9a33858bd2bdacc943f2290f7e8b59c13`
- `jobs.db`: 2 tables / 853 rows / `17a3aa34c98884416c167c45444673be4f4baea9bba3b6bdb7593edc5e2c80aa`

Manifest:

`/tmp/hackme_db_domain_split_live/domain_split_manifest.json`

## Verification

- `python3 -m py_compile services/server/domain_databases.py scripts/admin/split_main_database.py server.py`
- `pytest -q tests/platform/test_domain_database_split.py`
- `pytest -q tests/platform/test_auth_db_split.py tests/platform/test_audit_db_split.py tests/platform/test_domain_database_split.py`

All passed.

## Remaining Work

- Refactor storage routes/services to use `storage_catalog.db` before removing storage/E2EE tables from main.
- Refactor PointsChain service to use `points_chain.db` with explicit identity checks instead of cross-DB foreign keys.
- Refactor trading service so trading DB writes and PointsChain wallet ledger writes remain auditable across DB boundaries.
- Move job center to `jobs.db` after all producers accept a dedicated job DB provider.
- Add encrypted-at-rest handling for ledger DB files after the runtime split is active.

