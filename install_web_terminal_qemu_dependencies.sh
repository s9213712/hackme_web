#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
read_repo_setting() {
  local key="$1"
  local db_path="$ROOT_DIR/database/database.db"
  [[ -f "$db_path" ]] || return 0
  python3 - "$db_path" "$key" <<'PY' 2>/dev/null || true
import sqlite3
import sys

db_path, key = sys.argv[1:3]
conn = sqlite3.connect(db_path)
row = conn.execute("SELECT value FROM system_settings WHERE key=?", (key,)).fetchone()
if row and row[0] is not None:
    print(row[0])
PY
}

DB_VM_ROOT="$(read_repo_setting web_terminal_qemu_storage_dir)"
DB_UBUNTU_RELEASE="$(read_repo_setting web_terminal_qemu_distro)"
DB_NETWORK_MODE="$(read_repo_setting web_terminal_qemu_network_mode)"

VM_ROOT="${WEB_TERMINAL_QEMU_STORAGE_DIR:-${DB_VM_ROOT:-/var/lib/hackme-vms}}"
UBUNTU_RELEASE="${WEB_TERMINAL_QEMU_DISTRO:-${DB_UBUNTU_RELEASE:-ubuntu-22.04}}"
NETWORK_MODE="${WEB_TERMINAL_QEMU_NETWORK_MODE:-${DB_NETWORK_MODE:-none}}"
SERVER_PORT="${HTML_LEARNING_PORT:-5000}"
BASE_DIR="$VM_ROOT/base"
IMAGE_2204="$BASE_DIR/jammy-server-cloudimg-amd64.img"
IMAGE_2404="$BASE_DIR/noble-server-cloudimg-amd64.img"

log() {
  printf '[web-terminal-qemu] %s\n' "$*"
}

usage() {
  cat <<'USAGE'
Usage:
  ./install_web_terminal_qemu_dependencies.sh [options]

Options:
  --all              Install system packages, Python dependency, storage dirs, and base image
  --system           Install libvirt/KVM host packages with apt
  --python           Install Flask WebSocket dependency into the current Python environment
  --xterm            Install/copy xterm.js frontend assets under public/vendor
  --dirs             Create /var/lib/hackme-vms directory structure
  --fix-vm-storage-permissions
                     Repair libvirt-qemu ACL permissions on VM storage
  --image            Download Ubuntu cloud image selected by WEB_TERMINAL_QEMU_DISTRO
  --image-22.04      Download Ubuntu 22.04 cloud image
  --image-24.04      Download Ubuntu 24.04 cloud image
  --doctor           Check host readiness without changing system state
  --doctor-server    Also check the running hackme_web server process groups
  --fix-host-network
                     Repair common libvirt NAT host networking issues
  --doctor-host-network
                     Print host NAT/forwarding diagnostics for libvirt guests
  --doctor-session VM_NAME HOST_PORT
                     Diagnose a created WebTerminal VM that cannot SSH/connect
  --print-server-command
                     Print a libvirt-aware local development server command
  --help             Show this help

Environment:
  WEB_TERMINAL_QEMU_STORAGE_DIR=/var/lib/hackme-vms
  WEB_TERMINAL_QEMU_DISTRO=ubuntu-22.04|ubuntu-24.04
  WEB_TERMINAL_QEMU_NETWORK_MODE=user|none|nat|restricted
  HTML_LEARNING_PORT=5000

If environment variables are not set, the script reads this repo's
database/system_settings values before falling back to defaults.

Run this script from the repository root:
  cd /path/to/hackme_web
  ./install_web_terminal_qemu_dependencies.sh --all
USAGE
}

need_sudo() {
  if [[ "${EUID}" -ne 0 ]]; then
    command -v sudo >/dev/null 2>&1 || {
      log "sudo is required for system package and /var/lib setup."
      exit 1
    }
    sudo "$@"
  else
    "$@"
  fi
}

install_system() {
  log "Installing libvirt/KVM host packages."
  need_sudo apt update
  need_sudo apt install -y \
    qemu-kvm \
    libvirt-daemon-system \
    libvirt-clients \
    virtinst \
    bridge-utils \
    cloud-image-utils \
    genisoimage \
    libguestfs-tools \
    cpu-checker \
    jq \
    curl \
    wget \
    acl \
    openssh-client \
    uuid-runtime
  need_sudo systemctl enable --now libvirtd || true
  if [[ "${SUDO_USER:-}" ]]; then
    need_sudo usermod -aG libvirt "$SUDO_USER" || true
    need_sudo usermod -aG kvm "$SUDO_USER" || true
    log "User $SUDO_USER was added to libvirt/kvm groups. Log out and back in before running the server."
  else
    need_sudo usermod -aG libvirt "$USER" || true
    need_sudo usermod -aG kvm "$USER" || true
    log "User $USER was added to libvirt/kvm groups. Log out and back in before running the server."
  fi
}

install_python() {
  log "Installing Python WebSocket dependency from requirements.txt."
  python3 -m pip install -r "$ROOT_DIR/requirements.txt"
}

install_xterm() {
  log "Installing xterm.js frontend assets."
  if ! command -v npm >/dev/null 2>&1; then
    log "npm is missing. Install nodejs/npm first or use your distro package manager."
    return 1
  fi
  (cd "$ROOT_DIR" && npm install)
  mkdir -p "$ROOT_DIR/public/vendor/xterm"
  cp "$ROOT_DIR/node_modules/@xterm/xterm/lib/xterm.js" "$ROOT_DIR/public/vendor/xterm/xterm.js"
  cp "$ROOT_DIR/node_modules/@xterm/xterm/css/xterm.css" "$ROOT_DIR/public/vendor/xterm/xterm.css"
  cp "$ROOT_DIR/node_modules/@xterm/addon-fit/lib/addon-fit.js" "$ROOT_DIR/public/vendor/xterm/addon-fit.js"
  log "xterm.js copied to public/vendor/xterm."
}

create_dirs() {
  log "Creating VM storage tree at $VM_ROOT."
  need_sudo mkdir -p "$VM_ROOT"/{base,images/terminal,seed,sessions,logs,backups,templates}
  need_sudo chown -R root:libvirt "$VM_ROOT"
  need_sudo chmod -R g+rwX "$VM_ROOT"
  need_sudo find "$VM_ROOT" -type d -exec chmod 2770 {} +
  need_sudo find "$VM_ROOT" -type f -exec chmod 0640 {} +
  grant_libvirt_qemu_storage_access
}

grant_libvirt_qemu_storage_access() {
  if ! getent passwd libvirt-qemu >/dev/null 2>&1; then
    log "warn: libvirt-qemu user not found; skipping VM storage ACL repair"
    return 0
  fi
  if ! command -v setfacl >/dev/null 2>&1; then
    log "missing: setfacl; install the acl package or run ./install_web_terminal_qemu_dependencies.sh --system"
    return 1
  fi
  log "Repairing VM storage ownership and granting libvirt-qemu access at $VM_ROOT."
  need_sudo chown -R root:libvirt "$VM_ROOT"
  need_sudo chmod -R g+rwX "$VM_ROOT"
  need_sudo find "$VM_ROOT" -type d -exec chmod 2770 {} +
  need_sudo find "$VM_ROOT" -type f -exec chmod 0660 {} +
  need_sudo find "$VM_ROOT" -type d -exec setfacl -m u:libvirt-qemu:rwx -m d:u:libvirt-qemu:rwx {} +
  need_sudo find "$VM_ROOT" -type f -exec setfacl -m u:libvirt-qemu:rw- {} +
}

fix_image_permissions() {
  local image_path="$1"
  need_sudo chown root:libvirt "$image_path"
  need_sudo chmod 0640 "$image_path"
}

selected_image_path() {
  if [[ "$UBUNTU_RELEASE" == "ubuntu-24.04" ]]; then
    printf '%s\n' "$IMAGE_2404"
  else
    printf '%s\n' "$IMAGE_2204"
  fi
}

download_image() {
  local distro="$1"
  create_dirs
  if [[ "$distro" == "ubuntu-24.04" ]]; then
    log "Downloading Ubuntu 24.04 cloud image."
    need_sudo wget -O "$IMAGE_2404" https://cloud-images.ubuntu.com/noble/current/noble-server-cloudimg-amd64.img
    fix_image_permissions "$IMAGE_2404"
  else
    log "Downloading Ubuntu 22.04 cloud image."
    need_sudo wget -O "$IMAGE_2204" https://cloud-images.ubuntu.com/jammy/current/jammy-server-cloudimg-amd64.img
    fix_image_permissions "$IMAGE_2204"
  fi
}

set_alternative_if_available() {
  local name="$1"
  local target="$2"
  if [[ -x "$target" ]]; then
    log "Setting $name alternative to $target."
    need_sudo update-alternatives --set "$name" "$target"
  else
    log "skip: $target not found for $name"
  fi
}

ensure_iptables_rule() {
  local table="$1"
  local chain="$2"
  local insert_or_append="$3"
  shift 3
  if [[ "$table" == "filter" ]]; then
    if need_sudo iptables -C "$chain" "$@" 2>/dev/null; then
      log "ok: iptables $chain rule already exists: $*"
    else
      log "Adding iptables $chain rule: $*"
      need_sudo iptables "$insert_or_append" "$chain" "$@"
    fi
  else
    if need_sudo iptables -t "$table" -C "$chain" "$@" 2>/dev/null; then
      log "ok: iptables $table/$chain rule already exists: $*"
    else
      log "Adding iptables $table/$chain rule: $*"
      need_sudo iptables -t "$table" "$insert_or_append" "$chain" "$@"
    fi
  fi
}

ensure_libvirt_nat_rules() {
  local out_iface
  local out_ip
  out_iface="$(ip -4 route show default 2>/dev/null | awk '{print $5; exit}')"
  if [[ -z "$out_iface" ]]; then
    log "failed: cannot detect default IPv4 output interface"
    return 1
  fi
  out_ip="$(ip -4 addr show "$out_iface" 2>/dev/null | awk '/inet / {sub(/\/.*/, "", $2); print $2; exit}')"
  log "Ensuring libvirt NAT egress from virbr0 to $out_iface."
  need_sudo sysctl -w net.ipv4.conf.all.rp_filter=0 >/dev/null || true
  need_sudo sysctl -w net.ipv4.conf.virbr0.rp_filter=0 >/dev/null || true
  need_sudo sysctl -w "net.ipv4.conf.${out_iface}.rp_filter=0" >/dev/null || true
  ensure_iptables_rule filter FORWARD -I -i virbr0 -o "$out_iface" -j ACCEPT
  ensure_iptables_rule filter FORWARD -I -i "$out_iface" -o virbr0 -m conntrack --ctstate RELATED,ESTABLISHED -j ACCEPT
  if [[ -n "$out_ip" ]]; then
    ensure_iptables_rule nat POSTROUTING -I -s 192.168.122.0/24 -o "$out_iface" -j SNAT --to-source "$out_ip"
  fi
  ensure_iptables_rule nat POSTROUTING -A -s 192.168.122.0/24 -o "$out_iface" -j MASQUERADE
  ensure_iptables_rule nat POSTROUTING -A -s 192.168.122.0/24 ! -d 192.168.122.0/24 -j MASQUERADE
}

doctor_host_network() {
  local out_iface
  out_iface="$(ip -4 route show default 2>/dev/null | awk '{print $5; exit}')"
  log "Host route and forwarding diagnostics."
  ip -4 route show default || true
  ip -4 addr show virbr0 || true
  [[ -n "$out_iface" ]] && ip -4 addr show "$out_iface" || true
  sysctl net.ipv4.ip_forward net.ipv4.conf.all.forwarding net.ipv4.conf.virbr0.forwarding 2>/dev/null || true
  [[ -n "$out_iface" ]] && sysctl "net.ipv4.conf.${out_iface}.forwarding" 2>/dev/null || true

  log "iptables backend."
  readlink -f /usr/sbin/iptables || true
  iptables -V || true

  log "libvirt network state."
  if command -v virsh >/dev/null 2>&1; then
    virsh -c qemu:///system net-info default || true
  fi

  log "iptables filter/FORWARD policy and counters."
  need_sudo iptables -L FORWARD -n -v --line-numbers || true
  log "iptables nat/POSTROUTING policy and counters."
  need_sudo iptables -t nat -L POSTROUTING -n -v --line-numbers || true
  log "iptables-save relevant rules."
  need_sudo iptables-save | grep -E 'LIBVIRT|virbr0|192\.168\.122|POSTROUTING|FORWARD' || true

  log "To test counters: run a ping from the VM, then rerun --doctor-host-network and compare packet counters."
}

doctor_session() {
  local vm_name="${1:-}"
  local host_port="${2:-}"
  local failed=0
  if [[ ! "$vm_name" =~ ^hackme-term-u[0-9]+-[a-f0-9]{10}$ ]]; then
    log "failed: VM name is missing or not a WebTerminal VM name"
    log "usage: ./install_web_terminal_qemu_dependencies.sh --doctor-session hackme-term-u1-abcdef1234 45601"
    return 2
  fi
  if [[ ! "$host_port" =~ ^[0-9]+$ ]] || (( host_port < 1 || host_port > 65535 )); then
    log "failed: host port is missing or invalid"
    log "usage: ./install_web_terminal_qemu_dependencies.sh --doctor-session hackme-term-u1-abcdef1234 45601"
    return 2
  fi

  log "Diagnosing WebTerminal session VM $vm_name with host SSH port $host_port."
  if ! virsh -c qemu:///system dominfo "$vm_name" >/tmp/hackme-webterminal-dominfo.$$ 2>/tmp/hackme-webterminal-dominfo.err.$$; then
    log "failed: libvirt cannot find or read domain $vm_name"
    sed 's/^/[web-terminal-qemu] virsh: /' /tmp/hackme-webterminal-dominfo.err.$$ || true
    rm -f /tmp/hackme-webterminal-dominfo.$$ /tmp/hackme-webterminal-dominfo.err.$$
    return 1
  fi
  sed 's/^/[web-terminal-qemu] dominfo: /' /tmp/hackme-webterminal-dominfo.$$ || true
  rm -f /tmp/hackme-webterminal-dominfo.$$ /tmp/hackme-webterminal-dominfo.err.$$

  log "Domain network XML."
  virsh -c qemu:///system dumpxml "$vm_name" | sed -n '/<interface/,/<\/interface>/p' | sed 's/^/[web-terminal-qemu] xml: /' || true

  log "QEMU process hostfwd arguments."
  local qemu_line
  qemu_line="$(ps -ef | grep qemu-system | grep "$vm_name" | grep -v grep || true)"
  if [[ -n "$qemu_line" ]]; then
    if grep -q 'hostfwd' <<<"$qemu_line"; then
      grep -o 'hostfwd[^ ]*' <<<"$qemu_line" | sed 's/^/[web-terminal-qemu] qemu: /'
    else
      log "qemu: no hostfwd argument in process line. This is expected when hostfwd was added later via QEMU monitor."
    fi
  else
    log "failed: QEMU process for $vm_name is not running"
    failed=1
  fi

  log "QEMU monitor user networking state."
  if virsh -c qemu:///system qemu-monitor-command "$vm_name" --hmp "info usernet" >/tmp/hackme-webterminal-usernet.$$ 2>/tmp/hackme-webterminal-usernet.err.$$; then
    sed 's/^/[web-terminal-qemu] usernet: /' /tmp/hackme-webterminal-usernet.$$ || true
    if ! grep -qE "127\.0\.0\.1[: ].*${host_port}|${host_port}.*22" /tmp/hackme-webterminal-usernet.$$; then
      log "warn: QEMU monitor output does not clearly show $host_port -> 22 forwarding"
    fi
  else
    log "warn: cannot query QEMU monitor usernet info"
    sed 's/^/[web-terminal-qemu] monitor: /' /tmp/hackme-webterminal-usernet.err.$$ || true
  fi
  rm -f /tmp/hackme-webterminal-usernet.$$ /tmp/hackme-webterminal-usernet.err.$$

  log "Host listen check for 127.0.0.1:$host_port."
  if ss -ltn 2>/dev/null | awk '{print $4}' | grep -Eq "(^|:)${host_port}$"; then
    log "ok: host port $host_port is listening"
  else
    log "failed: host port $host_port is not listening"
    log "repair hint: the backend should call virsh qemu-monitor-command $vm_name --hmp 'hostfwd_add tcp:127.0.0.1:$host_port-:22'"
    failed=1
  fi

  log "SSH banner check."
  if python3 - "$host_port" <<'PY' >/tmp/hackme-webterminal-ssh.$$ 2>/tmp/hackme-webterminal-ssh.err.$$
import socket
import sys

port = int(sys.argv[1])
with socket.create_connection(("127.0.0.1", port), timeout=5) as sock:
    sock.settimeout(5)
    banner = sock.recv(128)
    if not banner.startswith(b"SSH-"):
        raise SystemExit(f"unexpected banner: {banner!r}")
    print(banner.decode("utf-8", errors="replace").strip())
PY
  then
    log "ok: SSH service answered on 127.0.0.1:$host_port"
    sed 's/^/[web-terminal-qemu] ssh: /' /tmp/hackme-webterminal-ssh.$$ || true
  else
    log "failed: SSH service did not answer on 127.0.0.1:$host_port"
    sed 's/^/[web-terminal-qemu] ssh: /' /tmp/hackme-webterminal-ssh.err.$$ || true
    log "if the port is listening, wait for cloud-init/sshd or inspect the VM console; if it is not listening, check hostfwd."
    failed=1
  fi
  rm -f /tmp/hackme-webterminal-ssh.$$ /tmp/hackme-webterminal-ssh.err.$$

  if [[ "$failed" -eq 0 ]]; then
    log "session doctor result: ok"
  else
    log "session doctor result: failed"
  fi
  return "$failed"
}

fix_host_network() {
  log "Repairing common libvirt NAT host networking issues."
  log "This may ask for sudo because it changes host firewall alternatives and sysctl settings."

  set_alternative_if_available iptables /usr/sbin/iptables-legacy
  set_alternative_if_available ip6tables /usr/sbin/ip6tables-legacy
  set_alternative_if_available ebtables /usr/sbin/ebtables-legacy
  set_alternative_if_available arptables /usr/sbin/arptables-legacy

  need_sudo sysctl -w net.ipv4.ip_forward=1
  if [[ "${EUID}" -ne 0 ]]; then
    printf 'net.ipv4.ip_forward=1\n' | sudo tee /etc/sysctl.d/99-hackme-webterminal-qemu.conf >/dev/null
  else
    printf 'net.ipv4.ip_forward=1\n' > /etc/sysctl.d/99-hackme-webterminal-qemu.conf
  fi

  need_sudo systemctl enable --now libvirtd || true
  need_sudo systemctl restart libvirtd || true
  need_sudo virsh -c qemu:///system net-autostart default || true
  if need_sudo virsh -c qemu:///system net-info default 2>/dev/null | grep -q 'Active:.*yes'; then
    log "ok: libvirt default NAT network already active"
  elif need_sudo virsh -c qemu:///system net-start default; then
    log "ok: libvirt default NAT network started"
  elif need_sudo virsh -c qemu:///system net-info default 2>/dev/null | grep -q 'Active:.*yes'; then
    log "ok: libvirt default NAT network is active after start attempt"
  else
    log "failed: libvirt default NAT network still cannot start"
    log "next: run journalctl -u libvirtd -n 80 --no-pager and inspect host firewall errors"
    return 1
  fi
  need_sudo virsh -c qemu:///system net-list --all
  ensure_libvirt_nat_rules
}

doctor() {
  local failed=0
  local selected_image
  selected_image="$(selected_image_path)"
  log "Checking command dependencies."
  for cmd in virsh virt-install qemu-img cloud-localds ssh ssh-keygen; do
    if command -v "$cmd" >/dev/null 2>&1; then
      log "ok: $cmd"
    else
      log "missing: $cmd"
      failed=1
    fi
  done
  if [[ -e /dev/kvm ]]; then
    log "ok: /dev/kvm exists"
  else
    log "missing: /dev/kvm"
    failed=1
  fi
  if id -nG 2>/dev/null | tr ' ' '\n' | grep -qx 'libvirt'; then
    log "ok: current shell user is in libvirt group"
  else
    log "warn: current shell user is not in libvirt group"
    log "hint: if libvirt checks fail, run sudo usermod -aG libvirt,kvm \"$USER\" and log in again; temporary dev launch can use sg libvirt"
  fi
  if virsh -c qemu:///system list --all >/dev/null 2>&1; then
    log "ok: libvirt qemu:///system reachable"
  else
    log "failed: libvirt qemu:///system not reachable"
    log "repair: sudo systemctl enable --now libvirtd；確認目前使用者與 server process 有 libvirt 群組"
    failed=1
  fi
  if [[ "$NETWORK_MODE" == "nat" || "$NETWORK_MODE" == "restricted" ]]; then
    if virsh -c qemu:///system net-info default 2>/dev/null | grep -q 'Active:.*yes'; then
      log "ok: libvirt default network active for $NETWORK_MODE mode"
    else
      log "failed: libvirt default network is not active but $NETWORK_MODE mode needs it"
      log "repair: sg libvirt -c 'virsh -c qemu:///system net-start default'"
      log "hint: if iptables/nftables conflict appears, fix host firewall backend before using NAT mode"
      failed=1
    fi
  else
    log "ok: network mode $NETWORK_MODE does not require libvirt default network"
  fi
  log "selected distro: $UBUNTU_RELEASE"
  if [[ -r "$IMAGE_2204" ]]; then
    log "ok: Ubuntu 22.04 image $IMAGE_2204"
  elif [[ -e "$IMAGE_2204" ]]; then
    log "unreadable: Ubuntu 22.04 image $IMAGE_2204"
  else
    log "missing: Ubuntu 22.04 image $IMAGE_2204"
  fi
  if [[ -r "$IMAGE_2404" ]]; then
    log "ok: Ubuntu 24.04 image $IMAGE_2404"
  elif [[ -e "$IMAGE_2404" ]]; then
    log "unreadable: Ubuntu 24.04 image $IMAGE_2404"
  else
    log "missing: Ubuntu 24.04 image $IMAGE_2404"
  fi
  if [[ -r "$selected_image" ]]; then
    log "ok: selected image for $UBUNTU_RELEASE is available"
  elif [[ -e "$selected_image" ]]; then
    log "failed: selected image for $UBUNTU_RELEASE exists but is not readable by this user"
    log "repair: ./install_web_terminal_qemu_dependencies.sh --fix-vm-storage-permissions"
    failed=1
  else
    log "failed: selected image for $UBUNTU_RELEASE is missing"
    log "repair: ./install_web_terminal_qemu_dependencies.sh --image"
    failed=1
  fi
  if python3 - <<'PY' >/dev/null 2>&1
import flask_sock
PY
  then
    log "ok: flask-sock installed"
  else
    log "missing: flask-sock"
    failed=1
  fi
  if [[ "$failed" -eq 0 ]]; then
    log "doctor result: ok"
  else
    log "doctor result: failed"
  fi
  return "$failed"
}

doctor_server() {
  local failed=0
  local pid=""
  log "Checking running server process on TCP port $SERVER_PORT."
  if command -v lsof >/dev/null 2>&1; then
    pid="$(lsof -nP -iTCP:"$SERVER_PORT" -sTCP:LISTEN -t 2>/dev/null | head -n 1 || true)"
  else
    log "missing: lsof; cannot inspect listening server process"
  fi
  if [[ -z "$pid" ]] && command -v pgrep >/dev/null 2>&1; then
    pid="$(pgrep -f "$ROOT_DIR/server.py" 2>/dev/null | head -n 1 || true)"
    if [[ -n "$pid" ]]; then
      log "warn: lsof did not expose the listening PID; fell back to pgrep for $ROOT_DIR/server.py"
    fi
  fi
  if [[ -z "$pid" ]]; then
    log "failed: no listening process found on port $SERVER_PORT"
    log "repair: start server after dependencies are ready; use --print-server-command for a local dev command"
    return 1
  fi
  log "ok: found server pid $pid on port $SERVER_PORT"
  local libvirt_gid=""
  local kvm_gid=""
  libvirt_gid="$(getent group libvirt 2>/dev/null | awk -F: '{print $3}' || true)"
  kvm_gid="$(getent group kvm 2>/dev/null | awk -F: '{print $3}' || true)"
  if [[ -z "$libvirt_gid" ]]; then
    log "failed: libvirt group does not exist"
    return 1
  fi
  if [[ -r "/proc/$pid/status" ]] && grep -E "^Groups:" "/proc/$pid/status" | grep -qw "$libvirt_gid"; then
    log "ok: server pid $pid has libvirt group ($libvirt_gid)"
  else
    log "failed: server pid $pid does not have libvirt group ($libvirt_gid)"
    log "repair: stop server and restart it after re-login, or run local dev server with the command from --print-server-command"
    failed=1
  fi
  if [[ -n "$kvm_gid" ]]; then
    if [[ -r "/proc/$pid/status" ]] && grep -E "^Groups:" "/proc/$pid/status" | grep -qw "$kvm_gid"; then
      log "ok: server pid $pid has kvm group ($kvm_gid)"
    else
      log "warn: server pid $pid does not have kvm group ($kvm_gid)"
      log "hint: if base images are group-owned by kvm, start server with the command from --print-server-command or run --fix-vm-storage-permissions"
    fi
  fi
  if [[ "$failed" -eq 0 ]]; then
    log "server doctor result: ok"
  else
    log "server doctor result: failed"
  fi
  return "$failed"
}

print_server_command() {
  cat <<EOF
Run the development server with kvm + libvirt groups applied:

  sg kvm -c "sg libvirt -c 'cd $ROOT_DIR && setsid -f env HTML_LEARNING_HOST=127.0.0.1 HTML_LEARNING_PORT=$SERVER_PORT PYTHONPATH=$ROOT_DIR python3 $ROOT_DIR/server.py > /tmp/hackme_web_$SERVER_PORT.out 2>&1'"

Then verify:

  sg kvm -c 'sg libvirt -c "./install_web_terminal_qemu_dependencies.sh --doctor"'
  ./install_web_terminal_qemu_dependencies.sh --doctor-server
EOF
}

if [[ "$#" -eq 0 ]]; then
  usage
  exit 0
fi

while [[ "$#" -gt 0 ]]; do
  case "$1" in
    --all)
      install_system
      install_python
      install_xterm
      create_dirs
      download_image "$UBUNTU_RELEASE"
      doctor
      ;;
    --system) install_system ;;
    --python) install_python ;;
    --xterm) install_xterm ;;
    --dirs) create_dirs ;;
    --fix-vm-storage-permissions) grant_libvirt_qemu_storage_access ;;
    --image) download_image "$UBUNTU_RELEASE" ;;
    --image-22.04) download_image "ubuntu-22.04" ;;
    --image-24.04) download_image "ubuntu-24.04" ;;
    --doctor) doctor ;;
    --fix-host-network) fix_host_network ;;
    --doctor-host-network) doctor_host_network ;;
    --doctor-session)
      session_vm="${2:-}"
      session_port="${3:-}"
      doctor_session "$session_vm" "$session_port"
      shift 2
      ;;
    --doctor-server)
      doctor_status=0
      server_status=0
      doctor || doctor_status=$?
      doctor_server || server_status=$?
      if [[ "$server_status" -eq 0 && "$doctor_status" -ne 0 ]]; then
        log "note: shell doctor failed, but server doctor passed. This usually means this terminal session has not reloaded group membership; the running web server is what the browser uses."
      fi
      if [[ "$server_status" -ne 0 ]]; then
        exit 1
      fi
      ;;
    --print-server-command) print_server_command ;;
    --help) usage ;;
    *)
      log "Unknown option: $1"
      usage
      exit 2
      ;;
  esac
  shift
done
