# Database Domain Split

`database.db` is currently too broad.  It still holds file/E2EE catalog data,
PointsChain ledgers, trading accounting, job state, social content, and core
identity/config tables.  The target model is multiple SQLite files under the
runtime database directory:

- `database.db`: core identity, settings, schema migrations, snapshots, integrity metadata.
- `auth.db`: sessions, CSRF, CAPTCHA, login attempts.  Already active.
- `audit.db`: secure audit hash chain.  Already active.
- `control.db`: server mode and production-control state.  Already active.
- `storage_catalog.db`: uploaded files, E2EE envelopes, storage folders/files, shares, albums, video/media catalog.
- `points_chain.db`: pc0/pc1 wallet identities, ledgers, bridge events, governance, economy snapshots.
- `trading.db`: exchange orders/fills/positions/bots/fund operations/background trading jobs.
- `jobs.db`: task center job state/events.

## Split Priority

P0 split candidates:

- `uploaded_files`, `encrypted_file_keys`, `storage_share_links`, `album_share_links`, `cloud_resumable_upload_sessions`
- `points_ledger`, `points_wallet_identities`, `points_chain_*`, `points_economy_*`
- `trading_orders`, `trading_fills`, `trading_*positions`, `trading_reserve_pool*`, `trading_bot*`
- `job_center_jobs`, `job_center_events`

P1 split candidates:

- `videos`, `video_*`, `media_stream_*`
- `chat_*`, `forum_*`, `notifications`, `reports`
- `comfyui_*`, `game_*`

Keep in main DB until their services are explicitly refactored:

- `users`, `user_passwords`, `user_profiles`
- `system_settings`, `schema_migrations`
- `snapshots`, `snapshot_restore_events`
- `integrity_*`, `security_events`

## Why This Cannot Be a Blind Table Move

SQLite foreign keys do not safely reference tables in another DB file.  Many
legacy tables also have direct joins to `users` or `uploaded_files`.  Dropping
tables from `database.db` before those routes are moved would break reads and
could silently remove application-level invariants.

The migration sequence is therefore:

1. Export domain DBs non-destructively and verify row hashes.
2. Add domain-specific service connection providers.
3. Refactor each service to use its own DB and replace cross-DB foreign keys
   with application-level identity checks or explicit mirrored identity rows.
4. Switch runtime routing per domain.
5. Only after verification, archive/drop legacy tables from `database.db`.

## Operator Tool

Analyze the current main DB:

```bash
python3 scripts/admin/split_main_database.py \
  --source /path/to/runtime/database/database.db \
  --mode analyze
```

Export domain DB files without changing the source DB:

```bash
python3 scripts/admin/split_main_database.py \
  --source /path/to/runtime/database/database.db \
  --mode export \
  --out-dir /path/to/runtime/database/split_export \
  --overwrite
```

The export writes `domain_split_manifest.json` with per-table row counts and
SHA-256 digests.  This is a staging/export step, not the final runtime switch.

## Runtime Visibility

The root system environment panel should treat database size as an aggregate of
all active SQLite files plus their WAL/SHM sidecars.  Showing only
`database.db` hides split-domain growth and can make operators miss storage,
PointsChain, trading, or job-center pressure after those domains move out of
the main DB.

The panel is intentionally a size/visibility aid.  It is not proof that a
domain is already routed to its split DB; routing is only complete after the
service for that domain opens its own DB connection and the old main-DB table
path has been retired.
