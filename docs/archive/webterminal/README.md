# Archived WebTerminal Setup Scripts

These files are kept as historical reference only.

Active development moved away from WebTerminal. The `02-WebTerminal-docker` and
`02-WebTerminal-qemu` branches are preserved for investigation history, but they
are no longer maintained as product branches.

## Included Files

- `docker/install_web_terminal_dependencies.sh`
- `docker/Dockerfile`
- `qemu/install_web_terminal_qemu_dependencies.sh`

The Docker script and Dockerfile came from `02-WebTerminal-docker`.
The QEMU/libvirt script came from `02-WebTerminal-qemu`.

## Do Not Treat As Product Setup

These scripts are not part of the normal Hackme Web install flow. They may
change host Docker, libvirt, KVM, firewall, virtual machine storage, or package
state. They are archived so future development can inspect what was tried and
why it was abandoned.

Reasons for abandoning WebTerminal as an active line:

- Docker required the web backend to access the Docker daemon.
- Docker group and socket permissions caused repeated setup confusion.
- QEMU/libvirt required host virtualization, storage ACLs, firewall/NAT repair,
  image management, and VM lifecycle debugging.
- Both approaches made a web app deployment depend on host operations that are
  hard to support reliably for normal users.

If WebTerminal is revisited later, start from a new design document instead of
reviving these scripts as-is.
