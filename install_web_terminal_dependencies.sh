#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENDOR_DIR="$ROOT_DIR/public/vendor/xterm"
IMAGE_NAME="${WEB_TERMINAL_IMAGE:-hackme-web-terminal:base}"
DOCKERFILE_PATH="$ROOT_DIR/docker/web-terminal/Dockerfile"

usage() {
  cat <<'EOF'
Usage:
  ./install_web_terminal_dependencies.sh [options]

Options:
  --system        Install system packages with sudo apt: docker.io nodejs npm
  --python        Install Python websocket packages: flask-sock simple-websocket
  --xterm         Install local xterm.js assets into public/vendor/xterm
  --image         Build terminal container image if docker/web-terminal/Dockerfile exists
  --all           Run --system --python --xterm --image
  --venv PATH     Install Python packages into the given virtualenv path
  --check         Print current dependency status only
  --doctor        Same as --check, plus print concrete repair commands
  -h, --help      Show this help

Examples:
  ./install_web_terminal_dependencies.sh --doctor --venv .venv
  ./install_web_terminal_dependencies.sh --all
  ./install_web_terminal_dependencies.sh --all --venv .venv
  ./install_web_terminal_dependencies.sh --system --python --xterm
  ./install_web_terminal_dependencies.sh --python --venv .venv

Notes:
  - The script will use sudo for apt and Docker image build when needed.
  - Docker group changes still require opening a new login shell before a
    long-running Flask/Gunicorn server can use Docker without sudo.
  - xterm.js is copied locally; the Web Terminal must not use CDN assets.
  - The terminal container must never mount /, /etc, /var, /run, the project root,
    or /var/run/docker.sock.
EOF
}

log() {
  printf '[web-terminal-deps] %s\n' "$*"
}

need_cmd() {
  command -v "$1" >/dev/null 2>&1
}

docker_daemon_accessible() {
  docker info >/dev/null 2>&1
}

sudo_available() {
  need_cmd sudo
}

docker_daemon_accessible_with_sudo_no_prompt() {
  sudo_available && sudo -n docker info >/dev/null 2>&1
}

docker_sock_group() {
  if [[ -S /var/run/docker.sock ]]; then
    stat -c '%G' /var/run/docker.sock 2>/dev/null || true
  fi
}

current_user_in_group() {
  local group="$1"
  [[ -n "$group" ]] || return 1
  id -nG "${USER:-$(id -un)}" 2>/dev/null | tr ' ' '\n' | grep -Fxq "$group"
}

print_docker_repair_hint() {
  local sock_group
  sock_group="$(docker_sock_group)"
  log "Docker daemon is not reachable by the current shell."
  if [[ -n "$sock_group" && "$sock_group" != "UNKNOWN" ]]; then
    log "Docker socket group: $sock_group"
    if [[ "$sock_group" == "docker" ]] && ! current_user_in_group "$sock_group"; then
      log "Suggested repair:"
      log "  sudo usermod -aG $sock_group ${USER:-$(id -un)}"
    elif [[ "$sock_group" != "docker" ]]; then
      log "The Docker socket is not owned by the usual 'docker' group on this host."
      log "If Docker was installed by a package manager, restart Docker and check:"
      log "  sudo systemctl restart docker"
      log "  ls -l /var/run/docker.sock"
      if getent group docker >/dev/null 2>&1; then
        log "Also make sure the service user is in the docker group:"
        log "  sudo usermod -aG docker ${USER:-$(id -un)}"
      fi
    fi
  else
    log "Suggested repair:"
    log "  sudo usermod -aG docker ${USER:-$(id -un)}"
  fi
  log "Then log out and back in, or restart the service from a new login shell."
  log "For just building the image now, this script can use sudo when run from an interactive terminal."
}

resolve_docker_cmd() {
  if docker_daemon_accessible; then
    DOCKER_CMD=(docker)
    return 0
  fi
  if docker_daemon_accessible_with_sudo_no_prompt; then
    DOCKER_CMD=(sudo docker)
    return 0
  fi
  if sudo_available && [[ -t 0 ]]; then
    log "Docker requires sudo for this shell. You may be prompted for your sudo password."
    sudo docker info >/dev/null
    DOCKER_CMD=(sudo docker)
    return 0
  fi
  return 1
}

run_sudo_apt() {
  if ! need_cmd sudo; then
    log "sudo is required for --system on this machine."
    exit 1
  fi
  log "Installing system packages: docker.io nodejs npm python3-venv"
  sudo apt update
  sudo apt install -y docker.io nodejs npm python3-venv
  sudo systemctl enable --now docker
  if [[ -n "${USER:-}" ]]; then
    sudo usermod -aG docker "$USER"
    log "Added $USER to docker group. Log out and log back in before using docker without sudo."
  fi
}

install_python_packages() {
  local venv_path="$1"
  if [[ -n "$venv_path" ]]; then
    if [[ ! -d "$venv_path" ]]; then
      log "Creating virtualenv: $venv_path"
      python3 -m venv "$venv_path"
    fi
    # shellcheck disable=SC1090
    source "$venv_path/bin/activate"
    python3 -m pip install -r "$ROOT_DIR/requirements.txt"
    python3 -m pip install flask-sock simple-websocket
  else
    python3 -m pip install --user -r "$ROOT_DIR/requirements.txt"
    python3 -m pip install --user flask-sock simple-websocket
  fi
}

install_xterm_assets() {
  if ! need_cmd npm; then
    log "npm is required for --xterm. Run --system first or install nodejs/npm manually."
    exit 1
  fi
  log "Installing xterm.js packages locally with npm"
  (cd "$ROOT_DIR" && npm install @xterm/xterm @xterm/addon-fit)
  mkdir -p "$VENDOR_DIR"
  cp "$ROOT_DIR/node_modules/@xterm/xterm/lib/xterm.js" "$VENDOR_DIR/xterm.js"
  cp "$ROOT_DIR/node_modules/@xterm/xterm/css/xterm.css" "$VENDOR_DIR/xterm.css"
  if [[ -f "$ROOT_DIR/node_modules/@xterm/addon-fit/lib/addon-fit.js" ]]; then
    cp "$ROOT_DIR/node_modules/@xterm/addon-fit/lib/addon-fit.js" "$VENDOR_DIR/addon-fit.js"
  fi
  log "Copied xterm assets to $VENDOR_DIR"
}

build_terminal_image() {
  if ! need_cmd docker; then
    log "docker is required for --image. Run --system first or install Docker manually."
    exit 1
  fi
  if ! resolve_docker_cmd; then
    print_docker_repair_hint
    exit 1
  fi
  if [[ ! -f "$DOCKERFILE_PATH" ]]; then
    log "Dockerfile not found: $DOCKERFILE_PATH"
    log "Skipping image build. Create the Dockerfile during Web Terminal implementation."
    return 0
  fi
  log "Building terminal container image: $IMAGE_NAME"
  "${DOCKER_CMD[@]}" build -t "$IMAGE_NAME" -f "$DOCKERFILE_PATH" "$ROOT_DIR"
  "${DOCKER_CMD[@]}" image inspect "$IMAGE_NAME" >/dev/null
  log "docker image $IMAGE_NAME: ok"
}

check_status() {
  local doctor="${1:-0}"
  local python_cmd="python3"
  if [[ -n "${VENV_PATH:-}" && -x "$VENV_PATH/bin/python3" ]]; then
    python_cmd="$VENV_PATH/bin/python3"
  elif [[ -x "$ROOT_DIR/.venv/bin/python3" ]]; then
    python_cmd="$ROOT_DIR/.venv/bin/python3"
  fi
  log "Checking dependency status"
  local docker_daemon_ok=0
  local docker_with_sudo_ok=0
  if need_cmd docker; then
    docker --version || true
    if docker_daemon_accessible; then
      docker_daemon_ok=1
    elif docker_daemon_accessible_with_sudo_no_prompt; then
      docker_with_sudo_ok=1
      log "docker daemon: reachable with sudo, not with current user"
    else
      log "docker daemon: permission denied or not running"
      log "docker image $IMAGE_NAME: cannot verify until Docker daemon access works"
      if [[ "$doctor" == "1" ]]; then
        print_docker_repair_hint
      fi
    fi
  else
    log "docker: missing"
    if [[ "$doctor" == "1" ]]; then
      log "Suggested repair: ./install_web_terminal_dependencies.sh --system"
    fi
  fi
  if need_cmd node; then
    node --version || true
  else
    log "node: missing"
  fi
  if need_cmd npm; then
    npm --version || true
  else
    log "npm: missing"
  fi
  "$python_cmd" - <<'PY'
import importlib.util
for name in ("flask_sock", "simple_websocket"):
    print(f"{name}: {'ok' if importlib.util.find_spec(name) else 'missing'}")
PY
  for file in "$VENDOR_DIR/xterm.js" "$VENDOR_DIR/xterm.css"; do
    if [[ -f "$file" ]]; then
      log "$(realpath --relative-to="$ROOT_DIR" "$file"): ok"
    else
      log "$(realpath --relative-to="$ROOT_DIR" "$file" 2>/dev/null || echo "$file"): missing"
      if [[ "$doctor" == "1" ]]; then
        log "Suggested repair: ./install_web_terminal_dependencies.sh --xterm"
      fi
    fi
  done
  if [[ "$docker_daemon_ok" == "1" ]]; then
    if docker image inspect "$IMAGE_NAME" >/dev/null 2>&1; then
      log "docker image $IMAGE_NAME: ok"
    else
      log "docker image $IMAGE_NAME: missing"
      if [[ "$doctor" == "1" ]]; then
        log "Suggested repair: ./install_web_terminal_dependencies.sh --image"
      fi
    fi
  elif [[ "$docker_with_sudo_ok" == "1" ]]; then
    if sudo -n docker image inspect "$IMAGE_NAME" >/dev/null 2>&1; then
      log "docker image $IMAGE_NAME: ok"
    else
      log "docker image $IMAGE_NAME: missing"
      if [[ "$doctor" == "1" ]]; then
        log "Suggested repair: sudo ./install_web_terminal_dependencies.sh --image"
      fi
    fi
  fi
}

DO_SYSTEM=0
DO_PYTHON=0
DO_XTERM=0
DO_IMAGE=0
DO_CHECK=0
DO_DOCTOR=0
VENV_PATH=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --system) DO_SYSTEM=1 ;;
    --python) DO_PYTHON=1 ;;
    --xterm) DO_XTERM=1 ;;
    --image) DO_IMAGE=1 ;;
    --all) DO_SYSTEM=1; DO_PYTHON=1; DO_XTERM=1; DO_IMAGE=1 ;;
    --check) DO_CHECK=1 ;;
    --doctor) DO_CHECK=1; DO_DOCTOR=1 ;;
    --venv)
      shift
      VENV_PATH="${1:-}"
      if [[ -z "$VENV_PATH" ]]; then
        log "--venv requires a path"
        exit 1
      fi
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      log "Unknown option: $1"
      usage
      exit 1
      ;;
  esac
  shift
done

if [[ "$DO_SYSTEM$DO_PYTHON$DO_XTERM$DO_IMAGE$DO_CHECK" == "00000" ]]; then
  usage
  exit 0
fi

if [[ "$DO_CHECK" == "1" ]]; then
  check_status "$DO_DOCTOR"
fi
if [[ "$DO_SYSTEM" == "1" ]]; then
  run_sudo_apt
fi
if [[ "$DO_PYTHON" == "1" ]]; then
  install_python_packages "$VENV_PATH"
fi
if [[ "$DO_XTERM" == "1" ]]; then
  install_xterm_assets
fi
if [[ "$DO_IMAGE" == "1" ]]; then
  build_terminal_image
fi

log "Done."
