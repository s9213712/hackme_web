#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="${ENV_FILE:-$ROOT_DIR/.env}"
VENV_DIR="${VENV_DIR:-$ROOT_DIR/.venv}"
MODE="run"
WITH_COMFYUI=0
COMFYUI_URL="${COMFYUI_URL:-http://127.0.0.1:8192}"
WITH_TURNSTILE=0
TURNSTILE_SECRET="${TURNSTILE_SECRET:-}"
LITE_HINT=0

usage() {
  cat <<'USAGE'
Usage:
  ./deploy.sh [options]

One-command deployment helper for Hackme Web.

Options:
  --check-only            Install/check dependencies and validate config, do not start.
  --init-db-only          Install/check dependencies and initialize/migrate DB only.
  --with-comfyui URL      Add COMFYUI_API_URL to .env before launch.
  --with-turnstile SECRET Add TURNSTILE_SECRET_KEY to .env before launch.
  --lite-hint             Print Raspberry Pi / low-end device deployment hints.
  --no-start              Alias for --check-only.
  -h, --help              Show this help.

Environment:
  ENV_FILE                Default: .env
  VENV_DIR                Default: .venv

The first run delegates the interactive setup wizard to scripts/run_prod.sh.
Runtime secrets, cert.pem, key.pem, DB, logs, storage, and manifests are local
generated files and are ignored by git.
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --check-only|--no-start)
      MODE="check"
      shift
      ;;
    --init-db-only)
      MODE="init-db-only"
      shift
      ;;
    --with-comfyui)
      WITH_COMFYUI=1
      COMFYUI_URL="${2:?missing ComfyUI URL}"
      shift 2
      ;;
    --with-turnstile)
      WITH_TURNSTILE=1
      TURNSTILE_SECRET="${2:?missing Turnstile secret}"
      shift 2
      ;;
    --lite-hint)
      LITE_HINT=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

say() {
  printf '[deploy] %s\n' "$*"
}

ensure_python() {
  command -v python3 >/dev/null 2>&1 || {
    echo "python3 is required. Install it with your OS package manager." >&2
    exit 1
  }
}

ensure_venv() {
  if [[ ! -x "$VENV_DIR/bin/python3" ]]; then
    say "creating virtualenv at $VENV_DIR"
    python3 -m venv "$VENV_DIR"
  fi
  # shellcheck disable=SC1091
  . "$VENV_DIR/bin/activate"
  say "installing Python dependencies"
  python3 -m pip install --upgrade pip
  python3 -m pip install -r "$ROOT_DIR/requirements.txt"
}

append_or_replace_env() {
  local key="$1"
  local value="$2"
  local tmp="$ENV_FILE.tmp"
  mkdir -p "$(dirname "$ENV_FILE")"
  touch "$ENV_FILE"
  chmod 600 "$ENV_FILE"
  if grep -qE "^${key}=" "$ENV_FILE"; then
    awk -v key="$key" -v value="$value" 'BEGIN{q=sprintf("%c",39)} $0 ~ "^" key "=" {$0=key "=" q value q} {print}' "$ENV_FILE" > "$tmp"
    mv "$tmp" "$ENV_FILE"
  else
    printf "%s='%s'\n" "$key" "$value" >> "$ENV_FILE"
  fi
}

print_lite_hints() {
  cat <<'EOF'
[deploy] Low-end device hints:
[deploy] - use branch hackme_web_lite when it exists locally/remotely
[deploy] - set GUNICORN_WORKERS=1
[deploy] - keep ComfyUI and heavy security scanners disabled
[deploy] - prefer local-only storage and scheduled maintenance during idle hours
[deploy] - use SQLite on local disk, not network storage
EOF
}

main() {
  cd "$ROOT_DIR"
  ensure_python
  ensure_venv

  if [[ "$WITH_COMFYUI" == "1" ]]; then
    append_or_replace_env "COMFYUI_API_URL" "$COMFYUI_URL"
  fi
  if [[ "$WITH_TURNSTILE" == "1" ]]; then
    append_or_replace_env "TURNSTILE_SECRET_KEY" "$TURNSTILE_SECRET"
  fi
  if [[ "$LITE_HINT" == "1" ]]; then
    print_lite_hints
  fi

  case "$MODE" in
    check)
      ENV_FILE="$ENV_FILE" scripts/run_prod.sh --check
      ;;
    init-db-only)
      ENV_FILE="$ENV_FILE" scripts/run_prod.sh --init-db-only
      ;;
    run)
      ENV_FILE="$ENV_FILE" scripts/run_prod.sh
      ;;
  esac
}

main
