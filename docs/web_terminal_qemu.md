# WebTerminal QEMU/libvirt Guide

`02-WebTerminal-qemu` uses libvirt/KVM for the optional root WebTerminal.
Docker WebTerminal is deprecated on this branch and kept only as archived
history under `docs/archive/`.

## Scope

- Only `root` can use the first WebTerminal version.
- The backend creates an isolated libvirt/KVM VM session.
- The frontend uses xterm.js when `public/vendor/xterm/` is installed, with a
  plain text fallback for incomplete development environments.
- The VM must not mount `/`, `/etc`, the project directory, the Docker socket,
  or arbitrary host paths.
- Cloud Drive is the persistent source of user files. The QEMU design uses a
  staged sync model; it does not trust live VM state as snapshot/restore data.

## Install

Run from the repository root:

```bash
./install_web_terminal_qemu_dependencies.sh --all
```

Useful partial commands:

```bash
./install_web_terminal_qemu_dependencies.sh --doctor
./install_web_terminal_qemu_dependencies.sh --system
./install_web_terminal_qemu_dependencies.sh --python
./install_web_terminal_qemu_dependencies.sh --xterm
./install_web_terminal_qemu_dependencies.sh --image-22.04
./install_web_terminal_qemu_dependencies.sh --image-24.04
```

After `--system`, log out and back in so the server user receives the
`libvirt` and `kvm` group memberships.

## Root Settings

Root can configure these in `安全中心 -> 伺服器設定 -> 系統`:

- Enable WebTerminal
- Ubuntu distro: `ubuntu-22.04` or `ubuntu-24.04`
- Network mode: `none`, `nat`, or `restricted`
- VM storage root, default `/var/lib/hackme-vms`
- base image path
- vCPU, memory, disk size
- idle timeout

The first implementation only accepts `qemu:///system` as the libvirt URI.

## Runtime Flow

1. Root opens the WebTerminal page.
2. The browser calls `/api/root/web-terminal/qemu/health`.
3. The server verifies commands, `/dev/kvm`, libvirt, storage, and base image.
4. Root starts a session through `/api/root/web-terminal/qemu/sessions`.
5. The backend creates a safe VM name: `hackme-term-u{user_id}-{short_uuid}`.
6. The backend creates an overlay qcow2 disk and cloud-init seed ISO.
7. `virt-install` imports the VM.
8. For NAT mode, the server waits for an IP and then bridges SSH to WebSocket.
9. Closing the session destroys and undefines the VM.

## Audit

The backend writes audit events for:

- health checks
- blocked session creation
- session creation
- provisioning failure
- WebSocket open/close/failure
- session close/failure

Audit detail includes VM name, distro, network mode, resource limits, and the
fact that host mounts are not used.

## Security Notes

- User input never controls VM names, disk paths, libvirt XML, or cloud-init.
- Subprocess calls use argument lists, not shell string concatenation.
- VM storage must be an absolute non-project path.
- QEMU/libvirt VM state is not trusted by snapshot/restore. Cloud Drive and
  database state remain the persistent sources.
- `network=none` is safest. NAT mode is required for the current SSH bridge.

## Current MVP Limits

- This branch is the QEMU/libvirt direction, not the full Server Rental Manager.
- Full paid VM rental, subscription expiry, and user SSH key management should
  be implemented as a separate Server Rental module later.
- `restricted` network mode currently uses the same libvirt default network
  check path as NAT; host firewall rules still need a dedicated implementation.

