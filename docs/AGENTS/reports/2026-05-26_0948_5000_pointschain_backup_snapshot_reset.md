# 2026-05-26 09:48 5000 PointsChain Backup/Snapshot/Reset QA

## Findings

- Fixed: PointsChain ledger backup/restore is now disabled by policy. Manual backup and restore-approve endpoints return HTTP 410, block sealing no longer creates ledger backups, and the background block worker no longer schedules ledger backups.
- Fixed: safe mode no longer prepares a "healthy backup" restore plan. It now produces a forensic/branch/governance recovery plan, preserving append-only ledger history.
- Fixed: manual and daily full snapshots force any pending PC1 canonical block seal before writing the snapshot. This avoids returning a `points_block` that is not actually inside the snapshot archive.
- Fixed: system reset rejects an invalid confirmation before any pre-reset block sealing. For valid resets, the route force-seals PC1 state before the pre-reset snapshot.
- Verified: new live snapshot `snap_20260526_094555_64fb98` contains `points_ledger=18` and `points_chain_blocks=1`; `uploads.tar.gz` contains no `points_chain_backups/backups/` files.

## Notes

- Existing historical `POINTS_LEDGER_BACKUP_CREATED` audit events remain visible because they are real past events and should not be deleted. The old `points_chain_backup_catalog` rows may still exist in legacy DB snapshots, but backup APIs no longer expose them and restorable backup files are excluded from new snapshot archives.
- I did not run a destructive live `/api/admin/system-reset` on `:5000`; reset behavior was verified through targeted service and route tests to avoid wiping the current acceptance runtime.

## Verification

- `python3 -m py_compile server.py services/points_chain/backup_recovery.py services/points_chain/service.py routes/economy.py routes/system_admin.py routes/system_admin_sections/runtime_routes.py services/server/startup.py`
- `node --check public/js/55-economy.js`
- `pytest tests/points/test_points_chain.py::test_points_chain_seal_verify_and_proof tests/points/test_points_chain.py::test_points_chain_safe_mode_blocks_writes_and_backup_restore_is_disabled tests/points/test_points_chain.py::test_points_chain_repairs_wallet_cache_tamper_without_entering_restore_mode tests/points/test_points_chain.py::test_points_chain_seal_adds_local_signature_and_root_report tests/points/test_points_chain.py::test_points_chain_runtime_reset_clears_active_ledger_and_leaves_reset_audit tests/points/test_points_chain.py::test_points_chain_ledger_backups_are_disabled tests/points/test_governance_branch.py::test_branch_recovery_safe_mode_does_not_offer_backup_restore tests/frontend/trading/test_frontend_economy.py tests/platform/test_startup_worker_feature_gates.py -q`
- `pytest tests/snapshots/test_snapshots.py::test_snapshot_api_seals_points_block_before_writing_snapshot tests/snapshots/test_snapshots.py::test_system_reset_rejects_bad_confirm_without_sealing_points_block tests/snapshots/test_snapshots.py::test_daily_snapshot_and_reset_api_are_root_only -q`
- Live `POST /api/root/points/chain/backups` -> HTTP 410.
- Live `POST /api/root/points/chain/recovery/approve` -> HTTP 410.
- Live root report: `ledger_backups=[]`, `scheduled_backup.disabled=true`, `financial_ok=true`.
