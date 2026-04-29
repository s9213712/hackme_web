#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VM_ROOT="${WEB_TERMINAL_QEMU_STORAGE_DIR:-/var/lib/hackme-vms}"
UBUNTU_RELEASE="${WEB_TERMINAL_QEMU_DISTRO:-ubuntu-22.04}"
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
  --image            Download Ubuntu cloud image selected by WEB_TERMINAL_QEMU_DISTRO
  --image-22.04      Download Ubuntu 22.04 cloud image
  --image-24.04      Download Ubuntu 24.04 cloud image
  --doctor           Check host readiness without changing system state
  --help             Show this help

Environment:
  WEB_TERMINAL_QEMU_STORAGE_DIR=/var/lib/hackme-vms
  WEB_TERMINAL_QEMU_DISTRO=ubuntu-22.04|ubuntu-24.04

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
  log "xterm.js copied to public/vendor/xterm."
}

create_dirs() {
  log "Creating VM storage tree at $VM_ROOT."
  need_sudo mkdir -p "$VM_ROOT"/{base,images/terminal,seed,sessions,logs,backups,templates}
  need_sudo chown -R root:libvirt "$VM_ROOT"
  need_sudo chmod -R 0770 "$VM_ROOT"
}

download_image() {
  local distro="$1"
  create_dirs
  if [[ "$distro" == "ubuntu-24.04" ]]; then
    log "Downloading Ubuntu 24.04 cloud image."
    need_sudo wget -O "$IMAGE_2404" https://cloud-images.ubuntu.com/noble/current/noble-server-cloudimg-amd64.img
    need_sudo chmod 0640 "$IMAGE_2404"
  else
    log "Downloading Ubuntu 22.04 cloud image."
    need_sudo wget -O "$IMAGE_2204" https://cloud-images.ubuntu.com/jammy/current/jammy-server-cloudimg-amd64.img
    need_sudo chmod 0640 "$IMAGE_2204"
  fi
}

doctor() {
  local failed=0
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
  if virsh -c qemu:///system list --all >/dev/null 2>&1; then
    log "ok: libvirt qemu:///system reachable"
  else
    log "failed: libvirt qemu:///system not reachable"
    failed=1
  fi
  if [[ -r "$IMAGE_2204" ]]; then
    log "ok: Ubuntu 22.04 image $IMAGE_2204"
  else
    log "missing: Ubuntu 22.04 image $IMAGE_2204"
  fi
  if [[ -r "$IMAGE_2404" ]]; then
    log "ok: Ubuntu 24.04 image $IMAGE_2404"
  else
    log "missing: Ubuntu 24.04 image $IMAGE_2404"
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
    --image) download_image "$UBUNTU_RELEASE" ;;
    --image-22.04) download_image "ubuntu-22.04" ;;
    --image-24.04) download_image "ubuntu-24.04" ;;
    --doctor) doctor ;;
    --help) usage ;;
    *)
      log "Unknown option: $1"
      usage
      exit 2
      ;;
  esac
  shift
done
