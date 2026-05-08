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

The active project now sits at the end of the `03.Economy` cleanup line and is
being prepared as a Phase 0 candidate for later PointsChain work. The current
direction emphasizes:

- simple single-node deployment with isolated runtime directories
- local runtime generation of secrets and TLS key material
- SQLite-backed application state that can be snapshotted and restored
- root-controlled security center, feature flags, and incident lockdown
- PointsChain as an audit chain and economy ledger, not a decentralized coin
- full-feature smoke testing, role-based pentesting, and release-gate QA
- modular trading services that can grow into more assets without copy-paste

## Current Release Story

The current published server line is `2026.05.04-096`.

Recent work from `2026.05.04-083` through `2026.05.04-096` focused on Phase 0
stabilization rather than starting a new product branch:

- chat and Cloud Drive UX were tightened, including inline message attachments,
  standardized `/attachments/` storage, and double-click folder navigation
- large Cloud Drive uploads now honor real quota and request-size policy
  instead of failing early at a stale `50 MB` Flask cap
- ComfyUI interaction rules were hardened: unsupported LoRA families are
  blocked, long generations can wait up to 30 minutes, and prompt helpers now
  add and remove LoRA / Embedding tokens predictably
- the trading system moved from a mostly single-source price model to a fused
  multi-exchange model with price health, excluded-source reporting, and
  root-visible diagnostics
- live trading UI now refreshes on a documented 2-second cadence, keeps wallet
  PnL in sync with the live price loop, and surfaces gross-vs-net Grid profit
  instead of only raw spread
- trading market metadata was centralized so future assets such as `SOL` or
  `GOLD` can be added through one market catalog instead of multiple hardcoded
  maps
- root gained a dedicated trading settings page, bot-audit controls, BTC_trade
  one-click orchestration, and clearer price-fusion status visibility
- the final Phase 0 cleanup pass closed the remaining blockers around
  validation, self-target guards, scan-window triggers, and stale docs drift

The current release story is therefore less about one headline feature and more
about making the existing stack trustworthy enough for future economy and
PointsChain phases.

## Economy Work Leading Into Phase 0

Release `2026.05.04-091` introduced the centralized trading market catalog,
which is the base needed for future points-quoted assets and later root
configuration of which markets are available.

Release `2026.05.04-089` removed the stale `50 MB` request cap for Cloud Drive
uploads and made oversized requests return structured API errors.

Release `2026.05.04-087` and `2026.05.04-088` cleaned up chat attachment UX and
standardized attachment storage under `/attachments/`.

Release `2026.05.04-086` through `2026.05.04-084` focused on ComfyUI safety and
operator clarity: reversible LoRA/Embedding prompt helpers, unsupported base
model blocking, and a longer default wait budget for heavy generation runs.

Release `2026.05.04-083` through `2026.05.04-080` focused on operator-visible
behavior in the trading UI: cleaner notification actions, wallet PnL refresh
alignment, and clearer fee-aware position details.

Release `2026.05.04-079` formalized fee-aware Grid Bot previews so the UI shows
gross profit, fees, net profit, break-even spread, and risk color instead of
only raw grid spacing.

Release `2026.05.04-078` through `2026.05.04-075` cleaned up storage plan
catalog behavior, lending APR defaults, grid fee discounts, and volume
tracking needed for future VIP work.

Release `2026.05.04-074` through `2026.05.04-068` reorganized the root trading
settings surface, added price-fusion diagnostics, and aligned the live-price
API with frontend behavior.

Release `2026.05.04-067` removed the effective `5000` candle wall by making
backtests auto-segment up to `20,000` candles while preserving strategy state
across chunks.

Release `2026.05.04-066` and the surrounding QA reports concentrated on
historical backtest replay, open-issue closure, and Phase 0 evidence gathering.

Release `2026.05.02-043` turns BTC_trade into a disabled-by-default optional
signal integration, adds root-triggered automatic clone/update/build setup,
verifies clean deployment and first BTC_trade build, and updates production DB
initialization so fresh installs can initialize all current schemas.

Release `2026.05.02-042` moves official trading Workflow templates into the
tracked `workflows/system/` directory, keeps user-created templates as runtime
data under `runtime/workflows/custom/`, adds structured explanations to every official
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
- server snapshot restores whole-site state and replays configured runtime secret files
- PointsChain backup/restore repairs economy ledger state independently and
  rebuilds wallets from ledger replay

See [Runtime Reset And Recovery](ops_boundaries/RUNTIME_RESET_AND_RECOVERY.md) for the exact
scope boundaries.
