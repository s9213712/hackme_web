#!/usr/bin/env bash
set -euo pipefail

BASE_URL="${BASE_URL:-http://127.0.0.1:5000}"
TIMEOUT="${TIMEOUT:-8}"

echo "=== 04_low_hidden_endpoint_scan ==="
echo "Target: $BASE_URL"
echo "Goal: 探測常見隱藏路徑/調試端點回應狀態，用於邊界盤點"

paths=(
  "/"
  "/api/"
  "/api/debug"
  "/api/health"
  "/api/version"
  "/api/admin"
  "/api/admin/"
  "/api/admin/users"
  "/api/admin/audit"
  "/api/admin/violations"
  "/api/admin/settings"
  "/api/admin/restart"
  "/api/csrf-token"
  "/.env"
  "/.git/config"
  "/.fkey"
  "/server.py"
  "/database.db"
  "/robots.txt"
  "/config"
  "/status"
  "/logout"
)

for path in "${paths[@]}"; do
  status="$(curl -sS --max-time "$TIMEOUT" -o /tmp/attack_scan_body.txt -w "%{http_code}" "$BASE_URL$path" || echo 000)"
  printf "%-24s %s\n" "$path" "$status"
done

echo
echo "Done."
