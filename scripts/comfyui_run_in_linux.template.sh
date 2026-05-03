#!/usr/bin/env bash
# ComfyUI startup script template for WSL/Linux.
# Copy this file into a ComfyUI portable/project folder as run_in_linux.sh.
# First run creates or reuses a Linux venv and installs ComfyUI dependencies.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
COMFYUI_DIR="${COMFYUI_DIR:-$SCRIPT_DIR/ComfyUI}"
OUTPUT_DIR="${OUTPUT_DIR:-$COMFYUI_DIR/output}"
INPUT_DIR="${INPUT_DIR:-$COMFYUI_DIR/input}"
PORT="${PORT:-8192}"
LISTEN_HOST="${LISTEN_HOST:-0.0.0.0}"
PYTHON_BIN="${PYTHON_BIN:-python3}"
AUTO_PORT_SCAN="${AUTO_PORT_SCAN:-1}"
INSTALL_ONLY=0
DOCTOR_ONLY=0

log() {
    printf '[comfyui-linux] %s\n' "$*"
}

fail() {
    printf '[comfyui-linux] ERROR: %s\n' "$*" >&2
    exit 1
}

for arg in "$@"; do
    case "$arg" in
        --doctor|--check)
            DOCTOR_ONLY=1
            ;;
        --install-only)
            INSTALL_ONLY=1
            ;;
        --no-auto-port-scan)
            AUTO_PORT_SCAN=0
            ;;
        *)
            fail "Unknown option: $arg"
            ;;
    esac
done

if [ ! -f "$COMFYUI_DIR/main.py" ]; then
    fail "ComfyUI main.py not found: $COMFYUI_DIR/main.py"
fi

if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
    fail "python3 not found. Install it first: sudo apt install python3 python3-venv python3-pip"
fi

choose_venv_dir() {
    if [ -n "${VENV_DIR:-}" ]; then
        printf '%s\n' "$VENV_DIR"
        return
    fi
    if [ -n "${VIRTUAL_ENV:-}" ] && [ -x "$VIRTUAL_ENV/bin/python" ]; then
        printf '%s\n' "$VIRTUAL_ENV"
        return
    fi
    if [ -x "$SCRIPT_DIR/.venv/bin/python" ]; then
        printf '%s\n' "$SCRIPT_DIR/.venv"
        return
    fi
    if [ -x "$HOME/.comfyui/venv/bin/python" ]; then
        printf '%s\n' "$HOME/.comfyui/venv"
        return
    fi
    printf '%s\n' "$SCRIPT_DIR/.venv"
}

VENV_DIR="$(choose_venv_dir)"

doctor() {
    log "ComfyUI directory: $COMFYUI_DIR"
    log "Selected venv: $VENV_DIR"
    log "Output directory: $OUTPUT_DIR"
    log "Input directory: $INPUT_DIR"
    log "API listen: $LISTEN_HOST:$PORT"
    [ -f "$COMFYUI_DIR/main.py" ] && log "ok: main.py found" || fail "missing main.py"
    [ -f "$COMFYUI_DIR/requirements.txt" ] && log "ok: requirements.txt found" || fail "missing requirements.txt"
    command -v "$PYTHON_BIN" >/dev/null 2>&1 && log "ok: $PYTHON_BIN found" || fail "missing python"
    if [ -x "$VENV_DIR/bin/python" ]; then
        log "ok: existing venv detected"
        "$VENV_DIR/bin/python" -m pip --version >/dev/null 2>&1 && log "ok: pip available in venv" || log "warning: pip missing in venv"
    else
        log "info: venv does not exist yet; first normal run will create it"
    fi
}

ensure_venv() {
    if [ -x "$VENV_DIR/bin/python" ]; then
        log "Using existing Python virtual environment: $VENV_DIR"
        return
    fi
    log "Creating Python virtual environment: $VENV_DIR"
    if ! "$PYTHON_BIN" -m venv "$VENV_DIR"; then
        fail "Failed to create venv. On Ubuntu/WSL run: sudo apt install python3-venv python3-pip"
    fi
}

requirements_hash() {
    if command -v sha256sum >/dev/null 2>&1; then
        sha256sum "$COMFYUI_DIR/requirements.txt" | awk '{print $1}'
    else
        "$VENV_DIR/bin/python" - <<'PY'
import hashlib
from pathlib import Path
print(hashlib.sha256(Path("ComfyUI/requirements.txt").read_bytes()).hexdigest())
PY
    fi
}

ensure_dependencies() {
    ensure_venv
    # shellcheck disable=SC1091
    source "$VENV_DIR/bin/activate"

    REQ_FILE="$COMFYUI_DIR/requirements.txt"
    if [ ! -f "$REQ_FILE" ]; then
        fail "requirements.txt not found: $REQ_FILE"
    fi

    REQ_HASH="$(requirements_hash)"
    MARKER="$VENV_DIR/.comfyui_requirements_${REQ_HASH}.ok"
    if [ -f "$MARKER" ]; then
        log "Dependencies already installed for current requirements."
        return
    fi

    log "Upgrading pip tooling."
    python -m pip install --upgrade pip wheel setuptools

    if ! python - <<'PY' >/dev/null 2>&1
import torch
PY
    then
        log "Installing PyTorch. Override with TORCH_INSTALL_CMD if your CUDA version needs a specific wheel."
        if [ -n "${TORCH_INSTALL_CMD:-}" ]; then
            bash -lc "$TORCH_INSTALL_CMD"
        else
            python -m pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu121 \
                || python -m pip install torch torchvision torchaudio
        fi
    fi

    log "Installing ComfyUI requirements."
    python -m pip install -r "$REQ_FILE"

    rm -f "$VENV_DIR"/.comfyui_requirements_*.ok
    touch "$MARKER"
    log "Dependency installation completed."
}

port_in_use() {
    local port="$1"
    if command -v lsof >/dev/null 2>&1; then
        lsof -iTCP:"$port" -sTCP:LISTEN >/dev/null 2>&1
        return $?
    fi
    "$PYTHON_BIN" - "$port" <<'PY'
import socket
import sys
port = int(sys.argv[1])
sock = socket.socket()
sock.settimeout(0.2)
try:
    raise SystemExit(0 if sock.connect_ex(("127.0.0.1", port)) == 0 else 1)
finally:
    sock.close()
PY
}

while port_in_use "$PORT"; do
    if [ "$AUTO_PORT_SCAN" != "1" ]; then
        fail "Port $PORT is already in use. Set another ComfyUI API port in hackme_web or stop the existing process."
    fi
    log "Port $PORT is in use; trying next port."
    PORT=$((PORT + 1))
done
log "Using port: $PORT"

mkdir -p "$OUTPUT_DIR" "$INPUT_DIR"

if [ "$DOCTOR_ONLY" = "1" ]; then
    doctor
    exit 0
fi

ensure_dependencies

if [ "$INSTALL_ONLY" = "1" ]; then
    log "Install-only mode completed."
    exit 0
fi

cd "$COMFYUI_DIR"
# shellcheck disable=SC1091
source "$VENV_DIR/bin/activate"

log "Starting ComfyUI from $COMFYUI_DIR"
exec python main.py \
    --listen "$LISTEN_HOST" \
    --port "$PORT" \
    --output-directory "$OUTPUT_DIR" \
    --input-directory "$INPUT_DIR" \
    --lowvram \
    --force-fp16 \
    --use-split-cross-attention \
    --preview-method auto \
    --auto-launch
