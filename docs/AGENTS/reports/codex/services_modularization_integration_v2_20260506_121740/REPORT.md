# Issue Fix Batch

- Branch: `03.Points`
- Scope: issue fixes before further modularization
- Behavior change: `Intended hardening only`

## Files Changed

- `requirements.txt`
- `services/cloud_drive.py`
- `services/comfyui_workflows.py`
- `services/points_chain.py`
- `services/snapshots.py`
- `tests/test_cloud_drive_attachments.py`
- `tests/test_comfyui_integration.py`
- `tests/test_points_chain.py`
- `tests/test_snapshots.py`

## Exact Fixes

- Added `websocket-client` to `requirements.txt`
  - fixes undeclared runtime dependency used by `services/comfyui_client.py`
- Made snapshot restore fail closed if `maintenance_mode=true` cannot be enabled
  - `restore_snapshot()` now records a failed prepare event and returns early
  - it no longer silently continues after a maintenance-mode write failure
- Made `PointsLedgerService._rebuild_wallets_from_ledger()` transaction-safe when called standalone
  - starts `BEGIN IMMEDIATE` only if no transaction is already active
  - commits or rolls back only when it opened the transaction itself
- Added ComfyUI workflow DOS guards
  - top-level node count limit
  - nesting depth limit
  - JSON byte-size limit
- Tightened `server_encrypted` cloud-drive upload handling
  - scans plaintext from a temporary path
  - writes ciphertext to the final storage path only after scanning
  - deletes the temporary plaintext file in `finally`

## Risk Notes

- The `server_encrypted` fix removes plaintext from the final storage path during scan and narrows the exposure window materially.
- It is not yet a full streaming-encryption design. The plaintext still exists in a temporary file during scanning because current scanners operate on file paths.

## Tests Run

- `PYTHONPATH=. python3 -m pytest -q tests/test_snapshots.py tests/test_points_chain.py`
  - `62 passed`
- `PYTHONPATH=. python3 -m pytest -q tests/test_comfyui_integration.py -k "workflow_import_rejects_bad_json_and_unsafe_paths or workflow_import_rejects_too_many_nodes_and_deep_nesting"`
  - `2 passed`
- `PYTHONPATH=. python3 -m pytest -q tests/test_cloud_drive_attachments.py -k "server_encrypted_upload_stores_ciphertext_but_downloads_plaintext or server_encrypted_upload_scans_temp_plaintext_not_final_storage_path"`
  - `2 passed`
- `HACKME_RUNTIME_DIR=/tmp/hackme_web_issuefix_full_20260506 PYTHONPATH=. python3 -m pytest -q tests/`
  - `1063 passed`
- `python3 scripts/pre_push_checks.py --ci`
  - `10 PASS / 1 FAIL`
  - merge blocker only: `release id sync`
- `git diff --check`
  - `pass`

## Rollback Plan

- Revert commit `fix: harden snapshot, pointschain, cloud-drive, and comfyui guards`
- No DB schema migration is involved
- Risk-sensitive behavior returns to the previous implementation immediately
