# Version Story And Abandoned Branches

Hackme Web started as a compact Flask authentication practice app. It later grew
into a single-node security lab for RBAC, moderation, auditability, cloud-drive
workflows, PointsChain economy experiments, ComfyUI integration, games, and
operational hardening.

## Active Main Line

The active default branch is `main`.

The former `01.POINTSCHAIN` line was merged back into `main` after the
PointsChain foundation stabilized. New project work should land on `main` unless
a feature branch is explicitly created.

`03.Economy` is the branch reserved for the real economy-model design work
that builds on top of the PointsChain foundation.

## Current Direction

The active project emphasizes:

- simple single-node deployment
- local runtime generation of secrets and TLS key material
- SQLite-backed application state
- root-controlled security center
- PointsChain as an audit chain, not a decentralized cryptocurrency
- full-feature smoke testing and role-based functional pentesting
- practical install scripts that reduce manual host debugging

## Current Economy Work

Release `2026.05.02-042` moves official trading Workflow templates into the
tracked `workflows/system/` directory, keeps user-created templates as runtime
data under `workflows/custom/`, adds structured explanations to every official
template, and introduces a validation script that checks trigger behavior,
downloads public K-line data, runs backend backtests, and compares them with an
independent replay.

Release `2026.05.02-041` makes the root GitHub update flow safer by creating a
server snapshot and a PointsChain ledger backup before applying a fast-forward
update, aborting if either protection point fails, and scheduling an automatic
server restart after a successful update.

Release `2026.05.02-040` keeps the active Economy workflow line focused on
trading automation usability: DCA bots execute their first run immediately,
bot cards show next-run countdowns, failed bot actions show visible reasons,
Workflow templates are easier to apply, and the root update center displays the
tracked update summary from `docs/UPDATE_SUMMARY.md`.

Release `2026.05.02-039` kept the active Economy workflow line focused on
simulated trading correctness and operator-visible behavior. BTC_trade is a
soft integration: hackme_web can read runtime signal files from a configured
BTC_trade folder, but missing files keep the signal panel hidden instead of
breaking the exchange. The bridge helper lives in hackme_web as
`scripts/btc_signal_bridge.py` so the external BTC_trade project does not need
to carry hackme_web-specific helper code.

## Abandoned WebTerminal Branches

Two WebTerminal branches are intentionally preserved but abandoned:

- `02-WebTerminal-docker`
- `02-WebTerminal-qemu`

They are not deleted so their history remains auditable, but they should not be
merged into the active main line.

Detailed historical notes are archived under
[docs/archive/webterminal](archive/webterminal/README.md).

### Docker Attempt

Docker WebTerminal used short-lived containers connected to a browser terminal.
It was abandoned because the web backend needed Docker daemon access, Docker
socket permissions were confusing in normal deployments, and the security
boundary was not strong enough for a root-facing terminal feature without
significant host hardening.

### QEMU/libvirt Attempt

QEMU WebTerminal used temporary Ubuntu VMs through libvirt/KVM. It improved
isolation but made deployment depend on host virtualization, KVM permissions,
libvirt daemon state, storage ACLs, cloud images, NAT/firewall behavior, and VM
SSH boot timing. That level of host operations is too heavy for this project.

## What Was Removed From Active Main

The active main line does not include WebTerminal routes, services, frontend
entry points, Dockerfiles, QEMU scripts, xterm assets, or WebTerminal settings.

Future terminal-like features should start from a fresh design document. They
should not revive the abandoned scripts as-is.

## Recovery Design Story

Runtime reset, server snapshot/restore, and PointsChain backup/restore now have
separate jobs:

- runtime reset clears generated runtime state and local secrets
- server snapshot restores whole-site state but excludes deployment secrets
- PointsChain backup/restore repairs economy ledger state independently and
  rebuilds wallets from ledger replay

See [Runtime Reset And Recovery](RUNTIME_RESET_AND_RECOVERY.md) for the exact
scope boundaries.
