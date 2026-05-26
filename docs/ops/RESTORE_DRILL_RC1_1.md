# RC1.1 Snapshot Boundary Drill

The RC1.1 drill proves that ordinary runtime snapshot/restore mechanics work
without reintroducing PointsChain ledger backup/restore. It is safe to run from
a developer checkout because it creates a synthetic runtime under `/tmp` unless
`--workdir` is supplied.

## Command

```bash
python3 scripts/ops/rc1_restore_drill.py \
  --out artifacts/ops/restore_drill_manual.json
```

The drill:

1. Creates a temporary runtime and SQLite database.
2. Seeds root/admin/test users and required settings.
3. Creates PointsChain genesis ledger/block data.
4. Confirms PointsChain ledger backup/restore is disabled.
5. Creates a server snapshot.
6. Adds dirty ordinary DB rows and dirty runtime files.
7. Restores the snapshot.
8. Runs PointsChain verify.
9. Checks that dirty ordinary data was removed while ledger backup/restore stayed disabled.

## Artifact

The output JSON includes:

- `ok`
- snapshot id
- PointsChain backup/restore disabled status
- baseline/dirty/restored counts
- restore result
- baseline and restored chain verify results
- invariant map

The drill passes only if every invariant is true.

## Operational Use

Run this drill:

- before RC1.1 signoff
- after snapshot/restore code changes
- after PointsChain schema changes
- after changing runtime secret or file-root configuration

For live deployments, run the drill against an isolated staging runtime. Do not
use it as a ledger rollback mechanism; PointsChain incidents must use safe mode,
forensic bundles, recovery branches, emergency governance, and append-only
correction transactions.
