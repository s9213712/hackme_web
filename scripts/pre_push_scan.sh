#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

echo "scripts/pre_push_scan.sh is a legacy compatibility wrapper."
echo "Use python3 scripts/pre_push_checks.py directly for the maintained pre-push gate."
exec python3 scripts/pre_push_checks.py "$@"
