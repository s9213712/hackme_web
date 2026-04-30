# Version Story And Abandoned Branches

Hackme Web started as a compact Flask authentication practice app. It later grew
into a single-node security lab for RBAC, moderation, auditability, cloud-drive
workflows, PointsChain economy experiments, ComfyUI integration, games, and
operational hardening.

## Active Main Line

The active default branch is `01.POINTSCHAIN`.

`main` is preserved as an older clean baseline, but new project work should land
on `01.POINTSCHAIN` unless a new feature branch is explicitly created.

`03.Economy` is the new branch reserved for the real economy-model design work
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
