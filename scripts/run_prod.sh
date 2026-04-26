#!/usr/bin/env bash
set -euo pipefail

BASE_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$BASE_DIR"

export IP_BLOCKING_ENABLED="${IP_BLOCKING_ENABLED:-true}"
export FORCE_HTTPS="${FORCE_HTTPS:-true}"
export SESSION_COOKIE_SECURE="${SESSION_COOKIE_SECURE:-true}"
export SESSION_COOKIE_HTTPONLY="${SESSION_COOKIE_HTTPONLY:-true}"
export SESSION_COOKIE_SAMESITE="${SESSION_COOKIE_SAMESITE:-Strict}"

if ! command -v gunicorn >/dev/null 2>&1; then
  echo "缺少 gunicorn，請先安裝：pip install -r requirements.txt"
  exit 1
fi

python3 - <<'PY'
from server import init_db

init_db()
print("database ready")
PY

python3 -m gunicorn \
  --bind "${GUNICORN_BIND:-0.0.0.0:5000}" \
  --workers "${GUNICORN_WORKERS:-4}" \
  --timeout "${GUNICORN_TIMEOUT:-30}" \
  --access-logfile "${GUNICORN_ACCESS_LOG:--}" \
  --error-logfile "${GUNICORN_ERROR_LOG:--}" \
  --capture-output \
  --log-level "${GUNICORN_LOG_LEVEL:-info}" \
  server:app
