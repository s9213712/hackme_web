# Repository Structure Cleanup Report

## Verdict

PASS

This slice does not move code or runtime paths. It defines the canonical
placement logic for future cleanup so later refactors are reviewable and do not
turn into another one-shot repo reshuffle.

## Scope

- define where `docs/`, `scripts/`, and `tests/` should evolve
- define which top-level runtime-like folders are legacy baggage
- define which large source files are the next bounded split candidates
- avoid moving executable source or tests in the same slice

## Files Changed

- [docs/REPOSITORY_STRUCTURE.md](/home/s92137/hackme_web/docs/REPOSITORY_STRUCTURE.md)
- [scripts/README.md](/home/s92137/hackme_web/scripts/README.md)
- [tests/README.md](/home/s92137/hackme_web/tests/README.md)
- [docs/README.md](/home/s92137/hackme_web/docs/README.md)
- [docs/RELEASE_LAYOUT.md](/home/s92137/hackme_web/docs/RELEASE_LAYOUT.md)

## Findings

### Docs

- `docs/` currently mixes entry guides, system references, operator runbooks,
  security gates, historical plans, competition reports, and agent reports.
- The top-level doc count is still manageable, but archival and deep-reference
  content needs a firmer placement rule so future additions do not keep landing
  at `docs/` root.

### Scripts

- `scripts/` only has a few true operator entrypoints, but several feature
  probes still live at root with names that look equally primary.
- The current stable root entrypoints are:
  - `run_prod.sh`
  - `pre_push_checks.py`
  - `root_recovery.py`
- The current move candidates are:
  - `btc_signal_bridge.py`
  - `trading_backtest_20000_probe.py`
  - `comfyui_feature_probe.py`
  - `comfyui_run_in_linux.template.sh`

### Tests

- `tests/` currently contains more than one hundred top-level files.
- The volume itself is not the main bug; the bigger issue is that top-level
  names mix frontend UI checks, backend invariants, script wrappers, smoke
  checks, and release gates without a visible ownership model.
- Consolidation should be domain-first, not file-count-first.

### Legacy Baggage

- `attachments/`, `avatars/`, `media/`, and `uploads/` still exist as root
  directories in the working tree.
- They are not canonical runtime homes anymore and should be treated as legacy
  baggage. New code should use `runtime/` instead.

## Canonical Placement Rules

- `README.md` stays a deployer wizard and should not become a feature manual.
- `docs/README.md` is the canonical document map.
- `docs/REPOSITORY_STRUCTURE.md` is the canonical cleanup and placement policy.
- `scripts/README.md` defines which scripts deserve top-level entrypoint status.
- `tests/README.md` defines which tests should be extended vs split.

## Next Bounded Slices

1. move feature probes under `scripts/trading/`, `scripts/comfyui/`, and
   `scripts/templates/` with compatibility wrappers
2. regroup script tests under `tests/scripts/`
3. regroup small frontend page tests into domain suites
4. continue bounded route/UI god-file splits:
   - `routes/files.py`
   - `routes/comfyui.py`
   - `public/js/50-admin.js`
   - `public/js/35-drive.js`
   - `public/js/36-comfyui.js`
   - `public/js/56-trading.js`

## Behavior Change

None.

## Tests Run

- `git diff --check`

## Known Risks

- This slice intentionally does not move any script or test path yet, so the
  clutter is documented before it is removed.
- The working tree already contained unrelated local modifications before this
  slice; they were not reverted or normalized here.

## Rollback Plan

- Revert the five documentation files added or modified in this slice.
