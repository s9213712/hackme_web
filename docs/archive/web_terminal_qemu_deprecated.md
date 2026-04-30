# WebTerminal QEMU/libvirt Branch Postmortem

Branch: `02-WebTerminal-qemu`

Status: abandoned historical branch. Do not continue product development here.

This branch tested replacing the Docker-based WebTerminal with a libvirt/KVM VM
backend. The goal was stronger isolation, a full Ubuntu environment, optional
network access, and a browser terminal connected through xterm.js and WebSocket.

## Development Flow Tested

1. Install libvirt/KVM host packages and add the server user to `libvirt` and
   `kvm`.
2. Create `/var/lib/hackme-vms` with base images, overlay disks, seed ISO files,
   session directories, and logs.
3. Download Ubuntu cloud images:
   - Ubuntu 22.04 Jammy
   - Ubuntu 24.04 Noble
4. Let root enable WebTerminal and select distro/network mode in the web UI.
5. On session start, create a temporary VM with an overlay qcow2 disk and
   cloud-init seed.
6. Bridge browser xterm.js to the VM through SSH and a backend WebSocket.
7. Destroy and undefine the VM when the session closes.

The implementation intentionally avoided host shell access and did not mount the
project directory, `/`, `/etc`, `/var/run/docker.sock`, or arbitrary host paths.
Cloud Drive remained the only intended persistent data source.

## Errors Encountered

The QEMU route worked temporarily, but repeatedly failed in ways that are hard
to make reliable for ordinary deployments:

- `libvirt-qemu` could not read overlay disks under `/var/lib/hackme-vms`
  without extra ACL repair.
- Ubuntu 24.04 required more memory than the first test defaults.
- The libvirt default NAT network failed on hosts where iptables/nftables were
  mixed.
- Some environments showed the NAT network as active while guests still could
  not reach the internet.
- QEMU user-mode port forwarding had to be patched in after VM creation because
  some libvirt builds silently dropped the XML port-forward definition.
- VM creation could succeed while SSH never became reachable within the timeout.
- The backend server process often had different group memberships from the
  interactive shell, causing the UI health check to fail even when manual doctor
  checks looked healthy.
- Full-screen terminal programs such as `htop`, `btop`, `screen`, and `tmux`
  required extra PTY resize, locale, and xterm FitAddon work, and still depended
  on browser rendering details.
- Cloud Drive integration remained a staged sync design, not a direct shared
  filesystem.

## Debug Flow That Was Needed

The branch added these helpers to narrow down host and VM issues:

```bash
./install_web_terminal_qemu_dependencies.sh --doctor
./install_web_terminal_qemu_dependencies.sh --doctor-server
./install_web_terminal_qemu_dependencies.sh --doctor-host-network
./install_web_terminal_qemu_dependencies.sh --fix-host-network
./install_web_terminal_qemu_dependencies.sh --fix-vm-storage-permissions
./install_web_terminal_qemu_dependencies.sh --doctor-session VM_NAME HOST_PORT
```

The practical order was:

1. Check shell dependencies and selected image with `--doctor`.
2. Check the already-running server process with `--doctor-server`.
3. Repair storage ACLs if `libvirt-qemu` could not read disks.
4. Prefer QEMU user-mode networking on WSL-like hosts.
5. If NAT was selected, run host network diagnostics and inspect iptables rules.
6. If SSH timed out, inspect the live VM immediately with `--doctor-session`
   before closing the session.

## Why This Was Abandoned

QEMU/libvirt gives better isolation than Docker, but it raises the deployment
bar too high for this project:

- It depends on host virtualization, libvirt daemon state, KVM permissions,
  storage ACLs, and host firewall behavior.
- WSL and desktop Linux environments behave differently enough that one-click
  setup is unrealistic.
- Root WebTerminal became a host operations problem instead of a web app feature.
- The support burden is too high for users who should be able to follow project
  documentation without an AI agent debugging their host.

The branch is kept for historical reference only. The QEMU setup script may be
archived in `01.Economy` as a non-product reference, but WebTerminal QEMU source,
routes, UI, and settings should not be merged back into the active main line.
