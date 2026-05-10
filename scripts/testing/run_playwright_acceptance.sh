#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RUNTIME_BASE="${PLAYWRIGHT_RUNTIME_BASE:-}"
KEEP_RUNTIME="${KEEP_PLAYWRIGHT_RUNTIME:-0}"

if [[ -z "${RUNTIME_BASE}" ]]; then
  RUNTIME_BASE="$(mktemp -d /tmp/hackme_web_playwright_acceptance_XXXXXX)"
fi

cleanup() {
  if [[ "${KEEP_RUNTIME}" != "1" && "${RUNTIME_BASE}" == /tmp/hackme_web_playwright_acceptance_* ]]; then
    rm -rf "${RUNTIME_BASE}"
  fi
}
trap cleanup EXIT

echo "[playwright] runtime base: ${RUNTIME_BASE}"
echo "[playwright] checking ComfyUI visual workflow builder"
python3 "${ROOT_DIR}/scripts/testing/playwright_comfyui_workflow_builder_check.py"

echo "[playwright] checking platform center health"
python3 "${ROOT_DIR}/scripts/testing/playwright_platform_health_check.py" \
  --runtime-root "${RUNTIME_BASE}/platform"

if [[ "${RUN_DEEP_PLAYWRIGHT:-0}" == "1" ]]; then
  echo "[playwright] checking deep site flow"
  python3 "${ROOT_DIR}/scripts/testing/playwright_deep_site_check.py" \
    --runtime-root "${RUNTIME_BASE}/deep" \
    --max-chess-human-moves "${MAX_CHESS_HUMAN_MOVES:-6}"
else
  echo "[playwright] deep site flow skipped; set RUN_DEEP_PLAYWRIGHT=1 to enable it"
fi

echo "[playwright] acceptance checks passed"
