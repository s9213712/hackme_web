# RC1.1 Restore Drill

The RC1.1 restore drill proves that snapshot and PointsChain restore mechanics
work in an isolated runtime. It is safe to run from a developer checkout because
it creates a synthetic runtime under `/tmp` unless `--workdir` is supplied.

## Command

```bash
python3 scripts/ops/rc1_restore_drill.py \
  --out artifacts/ops/restore_drill_manual.json
```

The drill:

1. Creates a temporary runtime and SQLite database.
2. Seeds root/admin/test users and required settings.
3. Creates PointsChain genesis ledger/block data.
4. Creates a PointsChain ledger backup.
5. Creates a server snapshot.
6. Adds dirty DB rows, dirty runtime files, and a dirty ledger entry.
7. Restores the snapshot.
8. Runs PointsChain verify.
9. Checks that dirty data was removed and baseline files/ledger counts returned.

## Artifact

The output JSON includes:

- `ok`
- snapshot id
- PointsChain ledger backup id
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
use it as a substitute for live backup verification or off-host backup storage.
