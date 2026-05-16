# 2026-05-16 Multi-Stress Stability QA

## Confirmed Findings

1. High: multi-feature pressure could make the server look offline without killing the process.
   - Evidence: `/tmp/hackme_web_multistress_20260516_02/multistress_result_01.json`.
   - The process stayed alive, but health checks had 8 failures, max consecutive health failures was 7, and the server log had 9 `database is locked` errors with 500 responses.
   - User impact: users would see connection instability or request timeouts even though the Flask PID did not exit.

2. High: SQLite write transactions were not serialized across request threads.
   - Evidence: `/tmp/hackme_web_multistress_20260516_03/multistress_result_02.json`.
   - Concurrent upload, resumable upload, trading reads, root trading status, and PointsChain report calls collided on SQLite writes.
   - Representative failures: `POST /api/storage/files`, `POST /api/cloud-drive/resumable-upload/.../chunks/...`, `GET /api/trading/asset-overview`, and `GET /api/root/points/report`.

3. Medium: read-looking paths still performed lazy writes.
   - `GET /api/trading/asset-overview` could create a missing wallet while building a read payload.
   - `GET /api/root/points/report` can verify/backfill PointsChain data.
   - Upload quota checks repeatedly entered upload security schema seeding.

## Fixes Applied

- `services/server/database.py`: database connections now use `SerializedWriteConnection`; the first mutating SQL statement acquires a process-wide SQLite write lock, released on `commit`, `rollback`, or `close`.
- `services/security/upload_schema.py`: upload security schema creation/seeding now has a per-DB ready cache and lock, so high-frequency quota checks do not keep re-running schema seed writes.
- `services/points_chain/service.py`: wallet creation is read-first and locked; read payloads now return a zero wallet view when no wallet exists instead of creating one from a read path.
- `services/trading/shadow.py`: production wallet payload reads now use the read-only PointsChain wallet payload helper.

## Verification

Final patched run: `/tmp/hackme_web_multistress_20260516_04/multistress_result_03.json`.

- Process alive at end: `true`.
- Health failures: `0`; max consecutive health failures: `0`.
- Server log findings: `[]`; no `Traceback`, no `500`, no `OperationalError`, no `database is locked`.
- Responses: `397` HTTP 200, `3` HTTP 202, `47` expected HTTP 400, `1` expected HTTP 409, `0` HTTP 500.
- Peak observed server RSS: `335680 KB`; peak threads: `39`; peak child count: `2`.
- Post-stress API health: `/api/version` returned ok.
- Post-stress mobile Playwright check: login `200`, `/api/me` ok, app shell visible, `#module-main-tabs` visible.
- Screenshot: `/tmp/hackme_web_multistress_20260516_04/poststress_mobile.png`.

Repeat retest: `/tmp/hackme_web_multistress_20260516_retest_01/multistress_retest_01.json`.

- Process alive at end: `true`.
- Server log findings: `[]`; no `Traceback`, no `500`, no `OperationalError`, no `database is locked`.
- Health failures: `2`; max consecutive health failures: `1`.
- Responses: `459` HTTP 200, `3` HTTP 202, `47` expected HTTP 400, `1` HTTP 403, `2` expected HTTP 409, `0` HTTP 500.
- Peak observed server RSS: `237324 KB`; peak threads: `42`; peak child count: `2`.
- Post-stress API health: `/api/version` returned ok.
- Post-stress mobile DOM check: login `200`, `/api/me` ok, app shell visible, `#module-main-tabs` visible.
- Screenshot: `/tmp/hackme_web_multistress_20260516_retest_01/poststress_mobile_retest.png`.

## Residual Notes

- The remaining HTTP 400 responses were expected validation failures from the stress probe, mostly duplicate storage paths and unreachable remote-download test URLs.
- The probe's PAGE status `0` samples were selector-timing false positives under rapid reload. A dedicated post-stress DOM check confirmed the mobile app shell and navigation were visible.
- Serialized SQLite writes trade some throughput for stability on the current single-process SQLite deployment. If write traffic grows, the deployment path should move hot write domains to a real worker queue or split DB/write service, not rely on unbounded concurrent Flask request writes.
