#!/usr/bin/env bash
set -Eeuo pipefail

SOURCE_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RUN_ROOT="${PYTEST_TMP_ROOT:-$(mktemp -d /tmp/hackme_web_pytest_XXXXXX)}"
COPY_ROOT="$RUN_ROOT/hackme_web"
KEEP_TMP="${KEEP_TMP:-0}"

mkdir -p "$COPY_ROOT"

tar -C "$SOURCE_ROOT" \
  --exclude='./.git' \
  --exclude='./.pytest_cache' \
  --exclude='./.venv' \
  --exclude='./__pycache__' \
  --exclude='./cache' \
  --exclude='./runtime' \
  --exclude='*/.pytest_cache' \
  --exclude='*/__pycache__' \
  --exclude='*/cache' \
  --exclude='*.pyc' \
  -cf - . | tar -C "$COPY_ROOT" -xf -

cd "$COPY_ROOT"
export HACKME_RUNTIME_DIR="$COPY_ROOT/runtime"
mkdir -p "$HACKME_RUNTIME_DIR"
export PYTHONPATH="$COPY_ROOT"
export PYTHONPYCACHEPREFIX="$HACKME_RUNTIME_DIR/pycache"
export PYTEST_ADDOPTS="${PYTEST_ADDOPTS:-} -o cache_dir=$HACKME_RUNTIME_DIR/pytest_cache"

echo "[pytest-in-tmp] repo copy: $COPY_ROOT"
echo "[pytest-in-tmp] runtime:   $HACKME_RUNTIME_DIR"

set +e
python3 -m pytest "$@"
status=$?
set -e

if [[ "$status" == "0" && "$KEEP_TMP" != "1" ]]; then
  rm -rf "$RUN_ROOT"
else
  echo "[pytest-in-tmp] kept tmp copy for debug: $COPY_ROOT"
fi

exit "$status"
