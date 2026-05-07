# Scripts Map

`scripts/` is for operator tooling, validation tooling, and subsystem-specific
helper scripts.

It is not a runtime data directory, and it should not become a dumping ground
for one-off experiments.

## Canonical Entry Points

- repo root [one_click_setup.sh](../one_click_setup.sh)
  Production setup, environment check, DB init, and Gunicorn launch.
- [prepush/pre_push_checks.py](prepush/pre_push_checks.py)
  Canonical local validation entrypoint.
- [admin/root_recovery.py](admin/root_recovery.py)
  Offline root recovery CLI.

## Current Subtrees

- `scripts/admin/`
  Operator repair and recovery tooling.
- `scripts/comfyui/`
  ComfyUI probe tooling and ComfyUI-specific local startup template.
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
