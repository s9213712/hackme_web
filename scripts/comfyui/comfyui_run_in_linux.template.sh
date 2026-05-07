#!/usr/bin/env bash
set -euo pipefail

# Copy this file into a ComfyUI portable install and edit the values to fit
# the local environment. It is a template, not a repo-side wrapper.

COMFYUI_ROOT="${COMFYUI_ROOT:-$HOME/ComfyUI}"
PYTHON_BIN="${PYTHON_BIN:-python3}"
LISTEN_HOST="${LISTEN_HOST:-127.0.0.1}"
LISTEN_PORT="${LISTEN_PORT:-8192}"

cd "$COMFYUI_ROOT"
exec "$PYTHON_BIN" main.py --listen "$LISTEN_HOST" --port "$LISTEN_PORT" "$@"
