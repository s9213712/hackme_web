# WebTerminal Archive

This directory preserves the abandoned WebTerminal design history. It is kept as
documentation only. The active `01.Economy` line does not ship WebTerminal
routes, services, frontend entry points, settings, Docker images, VM launchers,
or xterm assets.

Git does not track empty directories, so this archive must contain real files.
The subdirectories below document what was tried and why it was not kept:

- [Docker WebTerminal](docker/README.md)
- [QEMU/libvirt WebTerminal](qemu/README.md)

The historical branches remain available for audit and comparison:

- `02-WebTerminal-docker`
- `02-WebTerminal-qemu`

Do not merge those branches into the active main line. A future terminal feature
should start from a new design review instead of reviving these attempts as-is.

