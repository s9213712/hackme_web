# Settings UI Redesign TODO

This file tracks the root settings cleanup requested after the settings area
became too hard to scan and too easy to duplicate.

## Done

- Server settings are grouped into focused tabs: security, features,
  appearance, system, billing, trading, cloud drive, and member levels.
- Low-frequency controls are folded into collapsible panels instead of one
  long settings wall.
- System environment includes CPU/RAM/GPU/VRAM gauges with a root-only poller.
- System environment shows upload/download speed, cumulative upload/download,
  and aggregate DB size across active SQLite files plus WAL/SHM sidecars.
- Server time and timezone checks are visible in the system settings area.
- Backpressure settings include a process-local traffic chart.
- Trading settings were partially regrouped to remove some old market/fund
  controls from crowded governance flows.

## In Progress

- Main DB split is planned and exportable, but most product domains are still
  routed through `database.db`; runtime service routing must move domain by
  domain.

## P0 Next

- Add a settings search box that finds controls by label, key, and short help
  text, then jumps to the correct tab/panel.
- Audit every `s-*` setting control for duplicated meaning, stale pc0/pc1 text,
  legacy batch-chain settlement text, and old trading fund controls.
- Make the settings page mobile-first: no horizontal overflow, no clipped form
  labels, stable button wrapping, and one-column panels below tablet width.
- Replace inline style-heavy settings markup with reusable classes for cards,
  field grids, help text, and compact tables.
- Separate root-only dangerous operations from routine settings, with clearer
  confirmation text and less visual noise.

## P1 Next

- Add per-tab summaries so root can see the current mode, changed values, and
  restart-required settings before saving.
- Add sticky save/reset actions inside the settings form for long mobile pages.
- Add feature dependency hints next to the affected control instead of only in
  a global advisory block.
- Add operator-friendly copy for pc0 official hot wallet, pc1 bridge/deposit
  addresses, internal ledger, and cold-chain approval semantics.
- Add snapshot/export buttons near high-risk settings groups.

## Database Split Work

- Keep `auth.db`, `audit.db`, and `control.db` as already active split DBs.
- Move storage/E2EE metadata into `storage_catalog.db` after routes stop joining
  directly to main `uploaded_files`.
- Move PointsChain wallet identities, ledgers, bridge events, governance, and
  economy snapshots into `points_chain.db`; keep replay/hash validation.
- Move exchange orders, fills, positions, bots, reserve/fund operations, and
  background trading jobs into `trading.db`.
- Move job-center state into `jobs.db` so completed/failed task cleanup does not
  churn the main DB.
- Keep cross-DB foreign keys out of SQLite schema; enforce cross-domain identity
  checks in services and hash/export reports.
