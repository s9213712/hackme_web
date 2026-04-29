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
  -h, --help      Show this help

Examples:
  ./install_web_terminal_dependencies.sh --check
  ./install_web_terminal_dependencies.sh --all
  ./install_web_terminal_dependencies.sh --system --python --xterm
  ./install_web_terminal_dependencies.sh --python --venv .venv

Notes:
  - Docker group changes require logout/login before they apply.
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

run_sudo_apt() {
  if ! need_cmd sudo; then
    log "sudo is required for --system on this machine."
    exit 1
  fi
  log "Installing system packages: docker.io nodejs npm"
  sudo apt update
  sudo apt install -y docker.io nodejs npm
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
  if ! docker_daemon_accessible; then
    log "docker is installed, but this user cannot access the Docker daemon."
    log "Either log out and back in after --system added you to the docker group, or run:"
    log "  sudo $0 --image"
    exit 1
  fi
  if [[ ! -f "$DOCKERFILE_PATH" ]]; then
    log "Dockerfile not found: $DOCKERFILE_PATH"
    log "Skipping image build. Create the Dockerfile during Web Terminal implementation."
    return 0
  fi
  docker build -t "$IMAGE_NAME" -f "$DOCKERFILE_PATH" "$ROOT_DIR"
}

check_status() {
  log "Checking dependency status"
  local docker_daemon_ok=0
  if need_cmd docker; then
    docker --version || true
    if docker_daemon_accessible; then
      docker_daemon_ok=1
    else
      log "docker daemon: permission denied or not running"
      log "docker image $IMAGE_NAME: cannot verify until Docker daemon access works"
    fi
  else
    log "docker: missing"
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
  python3 - <<'PY'
import importlib.util
for name in ("flask_sock", "simple_websocket"):
    print(f"{name}: {'ok' if importlib.util.find_spec(name) else 'missing'}")
PY
  for file in "$VENDOR_DIR/xterm.js" "$VENDOR_DIR/xterm.css"; do
    if [[ -f "$file" ]]; then
      log "$(realpath --relative-to="$ROOT_DIR" "$file"): ok"
    else
      log "$(realpath --relative-to="$ROOT_DIR" "$file" 2>/dev/null || echo "$file"): missing"
    fi
  done
  if [[ "$docker_daemon_ok" == "1" ]]; then
    if docker image inspect "$IMAGE_NAME" >/dev/null 2>&1; then
      log "docker image $IMAGE_NAME: ok"
    else
      log "docker image $IMAGE_NAME: missing"
    fi
  fi
}

DO_SYSTEM=0
DO_PYTHON=0
DO_XTERM=0
DO_IMAGE=0
DO_CHECK=0
VENV_PATH=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --system) DO_SYSTEM=1 ;;
    --python) DO_PYTHON=1 ;;
    --xterm) DO_XTERM=1 ;;
    --image) DO_IMAGE=1 ;;
    --all) DO_SYSTEM=1; DO_PYTHON=1; DO_XTERM=1; DO_IMAGE=1 ;;
    --check) DO_CHECK=1 ;;
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
  check_status
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
