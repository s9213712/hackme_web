# WebTerminal QEMU/libvirt Guide

`02-WebTerminal-qemu` uses libvirt/KVM for the optional root WebTerminal.
Docker WebTerminal is deprecated on this branch and kept only as archived
history under `docs/archive/`.

For a step-by-step build flow, use
[WebTerminal QEMU Build Tutorial](web_terminal_qemu_build.md).

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
- Network mode: `user`, `nat`, `restricted`, or `none`
- VM storage root, default `/var/lib/hackme-vms`
- base image path
- vCPU, memory, disk size
- idle timeout
- default terminal rows/cols, default `51 x 209`

The first implementation only accepts `qemu:///system` as the libvirt URI.

## Runtime Flow

1. Root opens the WebTerminal page.
2. The browser calls `/api/root/web-terminal/qemu/health`.
3. The server verifies commands, `/dev/kvm`, libvirt, storage, and base image.
4. Root starts a session through `/api/root/web-terminal/qemu/sessions`.
5. The backend creates a safe VM name: `hackme-term-u{user_id}-{short_uuid}`.
6. The backend creates an overlay qcow2 disk and cloud-init seed ISO.
7. `virt-install` imports the VM.
8. For `user` mode, QEMU exposes guest SSH on a temporary `127.0.0.1` host port.
   The backend first creates the VM through libvirt, then uses QEMU monitor
   `hostfwd_add` to add `127.0.0.1:<host_port> -> guest:22`. This is intentional:
   some libvirt builds accept user-network port-forward XML in `--print-xml` but
   silently drop it when the domain is actually defined.
   For libvirt NAT modes, the server waits for a guest IP and then bridges SSH to
   WebSocket.
9. Before the browser can use the terminal, the backend waits for SSH and
   cloud-init bootstrap. The guest runs `apt update` and installs baseline tools
   including `sudo`, `ca-certificates`, `curl`, `wget`, `nano`, `vim-tiny`,
   `iputils-ping`, `dnsutils`, `net-tools`, `unzip`, `ncurses-term`, `screen`,
   `tmux`, and `htop`.
10. Closing the session destroys and undefines the VM.

Only one active session is kept per root user. Starting a new session closes and
removes the previous VM session first. Idle timeout can be set to `0` to disable
inactivity-based closing; VM cleanup still happens when the WebSocket closes or
root closes the session explicitly.

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

## Debug Workflow

Use the build tutorial for the long form. The short operational order is:

```bash
./install_web_terminal_qemu_dependencies.sh --doctor
./install_web_terminal_qemu_dependencies.sh --doctor-server
```

If a session is created but fails with `120 秒內無法透過 127.0.0.1:<port> SSH
連線`, inspect that exact VM and port before closing it:

```bash
./install_web_terminal_qemu_dependencies.sh --doctor-session hackme-term-u1-abcdef1234 45601
```

That command checks:

- whether libvirt still sees the temporary VM
- the VM network XML
- QEMU monitor `info usernet`
- whether the host is listening on `127.0.0.1:<port>`
- whether the SSH service answers with a banner

Interpretation:

- port not listening: user-mode `hostfwd_add` did not apply
- port listening but SSH banner missing: wait for cloud-init/sshd, then inspect
  VM console or cloud-init logs
- terminal opens but `apt install` cannot find packages: close the session and
  start a new one so the latest cloud-init baseline is used; then run
  `apt update` inside the VM if the mirror was temporarily unreachable during
  bootstrap
- VM missing: provisioning failed before `virt-install` completed, usually storage
  permissions or base image path
- `qemu-img` cannot open backing image: the overlay must be created with unsafe
  backing reference (`-u`); the final VM read is performed by `libvirt-qemu`

## Security Notes

- User input never controls VM names, disk paths, libvirt XML, or cloud-init.
- Subprocess calls use argument lists, not shell string concatenation.
- VM storage must be an absolute non-project path.
- QEMU/libvirt VM state is not trusted by snapshot/restore. Cloud Drive and
  database state remain the persistent sources.
- `network=none` is safest but is not interactive until the serial console bridge
  is implemented. `user` mode is recommended on WSL2 because it avoids nested
  bridge NAT. `nat` uses libvirt's default bridge network.
- The WebSocket bridge starts SSH with `TERM=xterm-256color`, forces the guest
  shell to use `TERM=xterm-256color`, `COLORTERM=truecolor`, and
  `LANG/LC_ALL=C.UTF-8`, then forwards xterm rows/cols resize events into the
  backend PTY. The browser loads xterm's FitAddon so cols/rows are calculated
  from the real rendered cell size instead of a rough estimate. Full-screen
  terminal apps such as `screen`, `tmux`, `htop`, and `btop` rely on this.
- Root can override the default terminal rows/cols in server settings. When set,
  the frontend xterm and backend PTY both use the configured size, so `stty size`
  should match the root setting after opening a new session.
- The bridge uses an incremental UTF-8 decoder for SSH output. This avoids
  corrupting box-drawing and block characters when a multi-byte character is
  split across WebSocket reads. Guest locale defaults to `C.UTF-8` so it matches
  the local server environment and does not depend on generating an extra locale
  inside the cloud image.

## Current MVP Limits

- This branch is the QEMU/libvirt direction, not the full Server Rental Manager.
- Full paid VM rental, subscription expiry, and user SSH key management should
  be implemented as a separate Server Rental module later.
- `restricted` network mode currently uses the same libvirt default network
  check path as NAT; host firewall rules still need a dedicated implementation.
