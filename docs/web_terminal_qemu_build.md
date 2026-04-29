# WebTerminal QEMU/libvirt Build Tutorial

This guide explains how to build and enable the optional QEMU/libvirt
WebTerminal on branch `02-WebTerminal-qemu`.

The WebTerminal is optional. The main site can run without it. Enable it only
on a Linux host where you are willing to run libvirt/KVM virtual machines.

## What This Builds

The QEMU WebTerminal flow is:

```text
root opens WebTerminal
-> hackme_web checks libvirt/KVM environment
-> backend creates a temporary Ubuntu VM
-> frontend connects through xterm.js + WebSocket
-> session close/timeout destroys the VM
```

It does not open a host shell. It does not use Docker. It does not mount the
project root, `/`, `/etc`, `/var/run/docker.sock`, or arbitrary host paths into
the VM.

## Host Requirements

Recommended host:

- Ubuntu Server 22.04 LTS or 24.04 LTS
- CPU virtualization enabled in BIOS/UEFI
- `/dev/kvm` available
- enough RAM and disk for temporary VMs
- a user account that can join `libvirt` and `kvm`

Quick hardware check:

```bash
egrep -c '(vmx|svm)' /proc/cpuinfo
```

The result should be greater than `0`.

## 1. Run From The Repo Root

Always run the installer from the repository root:

```bash
cd /path/to/hackme_web
./install_web_terminal_qemu_dependencies.sh --all
```

`--all` does these steps:

- installs libvirt/KVM host packages with `apt`
- installs Python dependencies from `requirements.txt`
- installs/copies xterm.js assets into `public/vendor/xterm/`
- creates `/var/lib/hackme-vms`
- downloads the selected Ubuntu cloud image
- runs a doctor check

The default image is Ubuntu 22.04.

## 2. Choose Ubuntu Version

Default:

```bash
./install_web_terminal_qemu_dependencies.sh --image-22.04
```

Ubuntu 24.04:

```bash
WEB_TERMINAL_QEMU_DISTRO=ubuntu-24.04 ./install_web_terminal_qemu_dependencies.sh --image-24.04
```

The default image paths are:

```text
/var/lib/hackme-vms/base/jammy-server-cloudimg-amd64.img
/var/lib/hackme-vms/base/noble-server-cloudimg-amd64.img
```

## 3. Re-login After System Install

The system install adds your user to `libvirt` and `kvm`.

After this step, log out and log back in. Then check:

```bash
groups
virsh -c qemu:///system list --all
```

If `virsh` still fails with permission errors, the server user does not yet
have libvirt permissions.

## 4. Run Doctor

Run:

```bash
./install_web_terminal_qemu_dependencies.sh --doctor
```

Doctor reads this repo's `database/database.db` settings first, so it checks the
same distro, storage root, and network mode that root selected in the web UI.
Environment variables still override the DB values when you need an explicit
one-off check. To validate Ubuntu 24.04:

```bash
WEB_TERMINAL_QEMU_DISTRO=ubuntu-24.04 ./install_web_terminal_qemu_dependencies.sh --doctor
```

Expected important `ok` lines:

```text
ok: virsh
ok: virt-install
ok: qemu-img
ok: cloud-localds
ok: ssh
ok: ssh-keygen
ok: /dev/kvm exists
ok: libvirt qemu:///system reachable
ok: flask-sock installed
```

The selected Ubuntu image must be present. By default the selected image is
Ubuntu 22.04. If doctor reports the selected image is missing, run:

```bash
./install_web_terminal_qemu_dependencies.sh --image
```

Or download a specific version:

```bash
./install_web_terminal_qemu_dependencies.sh --image-22.04
./install_web_terminal_qemu_dependencies.sh --image-24.04
```

If doctor reports the image exists but is unreadable, repair ownership and
permissions:

```bash
./install_web_terminal_qemu_dependencies.sh --dirs
```

After the web server is running, also check the actual server process:

```bash
./install_web_terminal_qemu_dependencies.sh --doctor-server
```

This catches the common case where your shell has `libvirt` permission but the
already-running `hackme_web` process was started before group membership took
effect. If `--doctor-server` says the server PID does not have the `libvirt`
group, restart the server after logging out and back in, or use the development
command printed by:

```bash
./install_web_terminal_qemu_dependencies.sh --print-server-command
```

If the Web UI shows `base_image`, `vm_storage_dir`, and `libvirt_connection` as
the failed items at the same time, check these in order:

```bash
groups
virsh -c qemu:///system list --all
./install_web_terminal_qemu_dependencies.sh --doctor-server
```

The important point is that the user who starts `server.py` must be able to read
`/var/lib/hackme-vms` and connect to `qemu:///system`.

If NAT mode fails because host firewall rules cannot be applied, run:

```bash
./install_web_terminal_qemu_dependencies.sh --fix-host-network
```

This helper repairs the common Ubuntu/libvirt mismatch where `iptables-nft`
reports `table filter is incompatible, use nft tool`. It switches available
iptables frontends to legacy, enables IPv4 forwarding, restarts libvirtd so it
uses the new frontend, marks the default network as autostart, and starts the
default NAT network. It also ensures explicit `virbr0 -> default interface`
FORWARD rules and a `192.168.122.0/24` MASQUERADE rule, because some WSL or
mixed firewall environments show the libvirt network as active while guest VMs
still cannot reach the internet. On WSL2 it also adds an explicit SNAT rule to
the host interface IP and disables reverse-path filtering for the involved
interfaces. It changes host-level network settings, so run it from your normal
terminal where `sudo` can ask for your password.

## 5. Start hackme_web

Start the server after dependencies are ready:

```bash
python3 server.py
```

If you use the production helper:

```bash
scripts/run_prod.sh
```

The server process must run as a user that can access libvirt/KVM. On a local
development machine, if you have just added yourself to `libvirt` but have not
opened a new login session yet, use:

```bash
./install_web_terminal_qemu_dependencies.sh --print-server-command
```

Run the printed command, then verify:

```bash
./install_web_terminal_qemu_dependencies.sh --doctor-server
```

## 6. Enable In Root Settings

Login as `root`, then open:

```text
安全中心 -> 伺服器設定 -> 系統 -> WebTerminal（選用，libvirt/KVM）
```

Recommended first settings:

```text
啟用 root WebTerminal: on
Ubuntu 發行版: Ubuntu 22.04
網路模式: QEMU user-mode NAT（WSL 推薦）
VM 儲存根目錄: /var/lib/hackme-vms
Base image 路徑: leave empty
vCPU: 1
記憶體 MB: 1024
磁碟 GB: 10
閒置逾時秒數: 900
```

Save settings.

Why user-mode NAT first: WSL2 often drops return traffic for nested libvirt
bridge NAT. QEMU user-mode NAT lets the QEMU process proxy outbound connections
directly and exposes guest SSH through a temporary `127.0.0.1` host port.
`none` is reserved for the later serial-console bridge and is blocked by health
checks in the current MVP.

## 7. Open WebTerminal

Open the sidebar item:

```text
WebTerminal
```

Then:

1. Click `環境檢查`.
2. If something fails, expand the failed rows and follow the repair text.
3. Click `開啟 Terminal`.
4. Wait for session status to become `ready`.
5. The browser connects to the VM terminal.

When every check passes, the Web UI hides the detailed checklist and shows only
a compact success message.

Closing the session calls libvirt destroy/undefine for that temporary VM.

## 8. Useful Partial Commands

Install only host packages:

```bash
./install_web_terminal_qemu_dependencies.sh --system
```

Install only Python dependencies:

```bash
./install_web_terminal_qemu_dependencies.sh --python
```

Install only xterm.js assets:

```bash
./install_web_terminal_qemu_dependencies.sh --xterm
```

Create VM directories only:

```bash
./install_web_terminal_qemu_dependencies.sh --dirs
```

Repair VM storage permissions only:

```bash
./install_web_terminal_qemu_dependencies.sh --fix-vm-storage-permissions
```

Use this if `virt-install` reports that a qcow2 file under
`/var/lib/hackme-vms/images/terminal` cannot be accessed as `uid:64055` or
`libvirt-qemu`.

Download image selected by environment:

```bash
WEB_TERMINAL_QEMU_DISTRO=ubuntu-24.04 ./install_web_terminal_qemu_dependencies.sh --image
```

## 9. Storage Layout

Default host storage:

```text
/var/lib/hackme-vms/base       base Ubuntu cloud images
/var/lib/hackme-vms/images     temporary VM qcow2 overlays
/var/lib/hackme-vms/seed       cloud-init seed files
/var/lib/hackme-vms/sessions   per-session SSH keys and metadata
/var/lib/hackme-vms/logs       future operational logs
/var/lib/hackme-vms/backups    future VM backup area
/var/lib/hackme-vms/templates  future cloud-init templates
```

The directory is owned by `root:libvirt` and mode `0770`.

## 10. Troubleshooting

### Permission denied for libvirt

Symptom:

```text
permission denied while connecting to qemu:///system
```

Fix:

```bash
sudo usermod -aG libvirt "$USER"
sudo usermod -aG kvm "$USER"
```

Then log out and back in. Restart `hackme_web` from the same user.

### `/dev/kvm` missing

Check BIOS/UEFI virtualization. On a VM host, nested virtualization may need to
be enabled by the outer hypervisor.

### Base image missing

Run one of:

```bash
./install_web_terminal_qemu_dependencies.sh --image-22.04
./install_web_terminal_qemu_dependencies.sh --image-24.04
```

Or set an absolute image path in root settings.

### xterm.js not loaded

Run:

```bash
./install_web_terminal_qemu_dependencies.sh --xterm
```

Then hard refresh the browser.

### Terminal starts but does not connect

Use QEMU user-mode NAT first on WSL2. It avoids the nested `virbr0 -> eth1`
forwarding path. Traditional libvirt NAT is still available on normal Linux hosts
where bridge forwarding works. Offline mode is reserved for the later
serial-console bridge and is intentionally blocked by health checks until that
bridge exists.

### VM creation says qcow2 permission denied

Symptom:

```text
Cannot access storage file '/var/lib/hackme-vms/images/terminal/...qcow2'
(as uid:64055, gid:109): Permission denied
```

Cause: the `server.py` process can create the qcow2, but the hypervisor runs VM
I/O as the `libvirt-qemu` system user. That user also needs search/write access
to `/var/lib/hackme-vms`, `images`, `images/terminal`, and `seed`.

Fix:

```bash
./install_web_terminal_qemu_dependencies.sh --fix-vm-storage-permissions
```

This applies ACLs for `libvirt-qemu` without making the VM storage world
readable.

### NAT mode says default network is inactive

Check:

```bash
WEB_TERMINAL_QEMU_NETWORK_MODE=nat ./install_web_terminal_qemu_dependencies.sh --doctor
```

Try:

```bash
./install_web_terminal_qemu_dependencies.sh --fix-host-network
```

If the host reports an iptables/nftables incompatibility, fix the host firewall
backend first or temporarily use offline mode until the host NAT network works.

If the VM can ping `192.168.122.1` but cannot ping `1.1.1.1`, the libvirt bridge
is up but host NAT forwarding is missing. Run:

```bash
./install_web_terminal_qemu_dependencies.sh --fix-host-network
```

Then test inside the terminal VM:

```bash
ping -c1 1.1.1.1
curl -4 -I https://cloud-images.ubuntu.com
```

If it still cannot reach the internet, print host forwarding counters:

```bash
./install_web_terminal_qemu_dependencies.sh --doctor-host-network
```

Run a ping from inside the VM, then rerun `--doctor-host-network`. If the
`FORWARD`/`POSTROUTING` counters do not increase, the host is not seeing guest
traffic. If they increase but the VM still gets no replies, the outer host or WSL
network may be dropping forwarded/NAT traffic.

## 11. Security Checklist

Before exposing this on a real host:

- keep WebTerminal disabled unless root needs it
- run VMs under libvirt/KVM, not host shell
- keep VM storage outside the project directory
- do not bind mount host system paths into the VM
- prefer `none` or restricted networking when the serial bridge is implemented
- review audit logs after every terminal session
- treat VM disk state as disposable; Cloud Drive remains the persistent source
