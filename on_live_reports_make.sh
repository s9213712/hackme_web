#!/usr/bin/env bash
set -Eeuo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$REPO_ROOT"

exec python3 "$REPO_ROOT/scripts/security/gate/on_live_reports_make.py" "$@"
