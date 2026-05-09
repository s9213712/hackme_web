# Scripts Map

`scripts/` is for operator tooling, validation tooling, and subsystem-specific
helper scripts.

It is not a runtime data directory, and it should not become a dumping ground
for one-off experiments.

## Canonical Entry Points

- repo root `python3 server.py --doctor`
  Validate that the current runtime directories already exist and are writable.
  This is the required preflight before a direct `server.py` startup.
- repo root [test_for_develop.sh](../test_for_develop.sh)
  Canonical daily development launcher. It copies the repo to `/tmp` and
  starts the copied `server.py` there with development-friendly defaults.
- [testing/pytest_in_tmp.sh](testing/pytest_in_tmp.sh)
  Canonical pytest entrypoint. Tests must run against a `/tmp` repo copy.
- [security/gate/on_live_reports_make.py](security/gate/on_live_reports_make.py)
  Canonical 13-report production-gate orchestrator.
- [prepush/pre_push_checks.py](prepush/pre_push_checks.py)
  Canonical local validation entrypoint.
- [admin/root_recovery.py](admin/root_recovery.py)
  Offline root recovery CLI.

## Current Subtrees

- `scripts/admin/`
  Operator repair and recovery tooling.
- `scripts/dev/`
  Development docs only. The old tmp launch wrappers were removed; use
  repo-root `test_for_develop.sh` instead.
- `scripts/comfyui/`
  ComfyUI probe tooling and ComfyUI-specific local startup template.
- `scripts/games/`
  Chess experiment training and other game-related operator tooling.
- `scripts/prepush/`
  Pre-push framework internals and checks.
- `scripts/security/`
  Security gate, pentest, dependency, and server-mode validation tooling.
- `scripts/trading/`
  Trading probes, benchmarks, validation, and integration bridges.

## Root Rule

Do not add new feature scripts directly under `scripts/` root.

New code should go into one of the existing domain subtrees unless it is a
cross-domain framework component with a clear long-term reason to live at the
top level.

## Placement Rules

The final placement policy lives in:

- [PLACEMENT_RULES.md](PLACEMENT_RULES.md)

Use that file as the canonical rulebook for what may or may not live under
`scripts/`.

## Production Gate Live Regression Rule

When changing production-gate logic, do not stop at unit tests.

At minimum, QA must run:

1. `scripts/security/gate/on_live_reports_make.py` or the equivalent 13-report
   generation flow against an isolated `/tmp` server.
2. A live regression proving:
   - 13 verified `old/fake target_commit` reports **cannot** unlock production
   - 13 verified `current target_commit` reports **can** unlock production

If you launch the isolated server with [test_for_develop.sh](../test_for_develop.sh),
`HTML_LEARNING_GIT_REPO_DIR` must still point at a real git repo with `.git`;
do not point it at the `/tmp` copied workspace when validating `target_commit`.
