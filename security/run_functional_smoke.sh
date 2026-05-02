#!/usr/bin/env bash
set -Eeuo pipefail

HOST="${HOST:-127.0.0.1}"
PORT="${PORT:-50734}"
SMOKE_SCHEME="${SMOKE_SCHEME:-${SCHEME:-https}}"
REPORT_ROOT="${REPORT_ROOT:-security/reports}"
ROOT_PASSWORD="${ROOT_PASSWORD:-RootSmoke123!}"
ROOT_CHANGED_PASSWORD="${ROOT_CHANGED_PASSWORD:-RootSmokeChanged123!}"
MANAGER_PASSWORD="${MANAGER_PASSWORD:-ManagerSmoke123!}"
TEST_PASSWORD="${TEST_PASSWORD:-TestSmoke123!}"
START_TIMEOUT="${START_TIMEOUT:-45}"
RESET_OFFLINE_TIMEOUT="${RESET_OFFLINE_TIMEOUT:-20}"
RESET_RECONNECT_TIMEOUT="${RESET_RECONNECT_TIMEOUT:-180}"
KEEP_RUNTIME=0

usage() {
  cat <<'USAGE'
Usage:
  security/run_functional_smoke.sh [--port N] [--runtime DIR] [--out DIR] [--keep-runtime]

What it does:
  - creates an isolated runtime under /tmp by default
  - writes a pre-start filesystem snapshot before launching the server
  - starts hackme_web with all runtime paths redirected into that runtime
  - logs in as root and checks major public, auth, admin, community, chat, DM,
    file, report, notification, and moderation endpoints
  - removes the runtime after the test by default

Environment overrides:
  HOST, PORT, REPORT_ROOT, ROOT_PASSWORD, MANAGER_PASSWORD, TEST_PASSWORD,
  RUNTIME_ROOT, SMOKE_SCHEME, SCHEME, START_TIMEOUT, RESET_OFFLINE_TIMEOUT,
  RESET_RECONNECT_TIMEOUT
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --port)
      PORT="${2:?missing port}"
      shift 2
      ;;
    --runtime)
      RUNTIME_ROOT="${2:?missing runtime directory}"
      shift 2
      ;;
    --out)
      REPORT_ROOT="${2:?missing output directory}"
      shift 2
      ;;
    --keep-runtime)
      KEEP_RUNTIME=1
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

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

RUN_ID="$(date -u +%Y%m%dT%H%M%SZ)"
RUNTIME_ROOT="${RUNTIME_ROOT:-/tmp/hackme_web_functional_${RUN_ID}}"
OUT_DIR="$REPORT_ROOT/functional_${RUN_ID}"
RAW_DIR="$OUT_DIR/raw"
COOKIE_JAR="$OUT_DIR/cookies.txt"
SUMMARY="$OUT_DIR/00_FUNCTIONAL_SMOKE.md"
RESULTS_TSV="$OUT_DIR/results.tsv"
SERVER_LOG="$OUT_DIR/server.out"
BASE_URL="${SMOKE_SCHEME}://${HOST}:${PORT}"
CURL_TLS_ARGS=()
if [[ "$SMOKE_SCHEME" == "https" ]]; then
  CURL_TLS_ARGS=(-k)
fi
SERVER_PID=""
CSRF_TOKEN=""
FAILURES=0
SKIPS=0

mkdir -p "$RAW_DIR" "$RUNTIME_ROOT"/{database,logs,chats,anchors,storage,reports}
: > "$RESULTS_TSV"

PRE_START_SNAPSHOT="$OUT_DIR/pre_start_runtime_snapshot.tar.gz"
tar -C "$RUNTIME_ROOT" -czf "$PRE_START_SNAPSHOT" .

cleanup() {
  local code=$?
  if [[ -n "$SERVER_PID" ]] && kill -0 "$SERVER_PID" >/dev/null 2>&1; then
    kill "$SERVER_PID" >/dev/null 2>&1 || true
    wait "$SERVER_PID" >/dev/null 2>&1 || true
  fi
  if [[ "$KEEP_RUNTIME" == "1" ]]; then
    rm -rf "$RUNTIME_ROOT"
    mkdir -p "$RUNTIME_ROOT"
    tar -C "$RUNTIME_ROOT" -xzf "$PRE_START_SNAPSHOT"
  else
    rm -rf "$RUNTIME_ROOT"
  fi
  exit "$code"
}
trap cleanup EXIT

json_expr() {
  local expr="$1"
  local file="$2"
  python3 - "$expr" "$file" <<'PY'
import json
import sys

expr, path = sys.argv[1], sys.argv[2]
with open(path, "r", encoding="utf-8") as f:
    data = json.load(f)
safe_builtins = {"next": next, "len": len, "int": int, "str": str, "any": any}
value = eval(expr, {"__builtins__": safe_builtins}, {"data": data})
if value is None:
    raise SystemExit(1)
if isinstance(value, bool):
    print("true" if value else "false")
else:
    print(value)
PY
}

json_bool() {
  local expr="$1"
  local file="$2"
  [[ "$(json_expr "$expr" "$file" 2>/dev/null || echo false)" == "true" ]]
}

csrf_from_cookie() {
  awk '$6 == "csrf_token" { value=$7 } END { print value }' "$COOKIE_JAR"
}

safe_name() {
  printf '%s' "$1" | tr -c 'A-Za-z0-9_.-' '_'
}

record() {
  local name="$1"
  local status="$2"
  local detail="$3"
  printf '%s\t%s\t%s\n' "$name" "$status" "$detail" >> "$RESULTS_TSV"
}

pass() {
  record "$1" "pass" "$2"
  echo "[PASS] $1"
}

fail() {
  record "$1" "fail" "$2"
  FAILURES=$((FAILURES + 1))
  echo "[FAIL] $1 -- $2" >&2
}

skip() {
  record "$1" "skip" "$2"
  SKIPS=$((SKIPS + 1))
  echo "[SKIP] $1 -- $2"
}

expect_code() {
  local actual="$1"
  local expected_csv="$2"
  local code
  IFS=',' read -ra codes <<< "$expected_csv"
  for code in "${codes[@]}"; do
    if [[ "$actual" == "$code" ]]; then
      return 0
    fi
  done
  return 1
}

request() {
  local name="$1"
  local method="$2"
  local path="$3"
  local expected="$4"
  local body="${5:-}"
  local out="$RAW_DIR/$(safe_name "$name").json"
  local code
  local args=(-sS -b "$COOKIE_JAR" -c "$COOKIE_JAR" -o "$out" -w "%{http_code}" -X "$method")
  if [[ -n "$CSRF_TOKEN" ]]; then
    args+=(-H "X-CSRF-Token: $CSRF_TOKEN")
  fi
  if [[ "$method" != "GET" && "$method" != "HEAD" ]]; then
    args+=(-H "Content-Type: application/json")
    if [[ -n "$body" ]]; then
      args+=(-d "$body")
    fi
  fi
  code="$(curl "${CURL_TLS_ARGS[@]}" "${args[@]}" "$BASE_URL$path" || true)"
  if expect_code "$code" "$expected"; then
    pass "$name" "$method $path -> $code"
  else
    fail "$name" "$method $path -> $code, expected $expected, body=$out"
  fi
  if [[ "$method" != "GET" && "$method" != "HEAD" && "$path" != "/api/login" ]]; then
    refresh_csrf_quiet
  fi
}

refresh_csrf_quiet() {
  local out="$RAW_DIR/refresh_csrf_$(date +%s%N).json"
  local code
  code="$(curl "${CURL_TLS_ARGS[@]}" -sS -b "$COOKIE_JAR" -c "$COOKIE_JAR" -o "$out" -w "%{http_code}" "$BASE_URL/api/csrf-token" || true)"
  if [[ "$code" == "200" ]]; then
    CSRF_TOKEN="$(json_expr 'data["csrf_token"]' "$out" || echo "$CSRF_TOKEN")"
  fi
}

upload_file() {
  local name="$1"
  local path="$2"
  local file_path="$3"
  local expected="$4"
  local out="$RAW_DIR/$(safe_name "$name").json"
  local code
  code="$(curl "${CURL_TLS_ARGS[@]}" -sS -b "$COOKIE_JAR" -c "$COOKIE_JAR" -o "$out" -w "%{http_code}" \
    -H "X-CSRF-Token: $CSRF_TOKEN" \
    -F "privacy_mode=standard_plain" \
    -F "file=@${file_path};type=text/plain" \
    "$BASE_URL$path" || true)"
  if expect_code "$code" "$expected"; then
    pass "$name" "POST $path -> $code"
  else
    fail "$name" "POST $path -> $code, expected $expected, body=$out"
  fi
  refresh_csrf_quiet
}

check_unknown_options() {
  local name="unknown path options"
  local out="$RAW_DIR/$(safe_name "$name").body"
  local headers="$RAW_DIR/$(safe_name "$name").headers"
  local code allow
  code="$(curl "${CURL_TLS_ARGS[@]}" -sS -b "$COOKIE_JAR" -c "$COOKIE_JAR" -D "$headers" -o "$out" -w "%{http_code}" \
    -X OPTIONS -H "X-CSRF-Token: $CSRF_TOKEN" "$BASE_URL/not-real-functional-smoke" || true)"
  allow="$(awk 'BEGIN{IGNORECASE=1} /^Allow:/ {sub(/\r$/, ""); print substr($0, 8)}' "$headers" | tail -n1)"
  if ! expect_code "$code" "200,404"; then
    fail "$name" "OPTIONS unknown path -> $code, expected 200 or 404"
    return 0
  fi
  if [[ "$allow" == *PUT* || "$allow" == *DELETE* || "$allow" == *PATCH* ]]; then
    fail "$name" "unsafe methods advertised in Allow: $allow"
    return 0
  fi
  pass "$name" "OPTIONS unknown path -> $code, Allow: ${allow:-<none>}"
}

latest_raw() {
  echo "$RAW_DIR/$(safe_name "$1").json"
}

wait_for_server() {
  local deadline=$((SECONDS + START_TIMEOUT))
  local out="$RAW_DIR/wait_api_version.json"
  while (( SECONDS < deadline )); do
    if curl "${CURL_TLS_ARGS[@]}" -sS -o "$out" "$BASE_URL/api/version" >/dev/null 2>&1; then
      pass "server startup" "reachable at $BASE_URL"
      return 0
    fi
    sleep 1
  done
  fail "server startup" "not reachable within ${START_TIMEOUT}s; see $SERVER_LOG"
  return 1
}

server_started_at() {
  local out="$1"
  curl "${CURL_TLS_ARGS[@]}" -sS -o "$out" "$BASE_URL/api/version" >/dev/null 2>&1 || return 1
  json_expr 'data.get("started_at", "")' "$out" 2>/dev/null || true
}

wait_for_restart_reconnect() {
  local name="$1"
  local previous_started_at="$2"
  local offline_timeout="${3:-$RESET_OFFLINE_TIMEOUT}"
  local reconnect_timeout="${4:-$RESET_RECONNECT_TIMEOUT}"
  local offline_deadline=$((SECONDS + offline_timeout))
  local reconnect_deadline
  local out="$RAW_DIR/$(safe_name "$name").json"
  local code=""
  local started_at=""
  local observed_offline=0

  while (( SECONDS < offline_deadline )); do
    code="$(curl "${CURL_TLS_ARGS[@]}" -sS -b "$COOKIE_JAR" -c "$COOKIE_JAR" -o "$out" -w "%{http_code}" "$BASE_URL/api/version" || true)"
    if [[ "$code" == "000" || -z "$code" ]]; then
      observed_offline=1
      break
    fi
    if [[ "$code" == "200" ]]; then
      started_at="$(json_expr 'data.get("started_at", "")' "$out" 2>/dev/null || true)"
      if [[ -n "$started_at" && "$started_at" != "$previous_started_at" ]]; then
        pass "$name" "restart completed without an observable offline window; started_at changed ${previous_started_at:-unknown} -> $started_at"
        return 0
      fi
    fi
    sleep 1
  done

  if [[ "$observed_offline" != "1" ]]; then
    fail "$name" "server did not go offline within ${offline_timeout}s after restart request; last_http=${code:-none}, body=$out"
    return 1
  fi
  pass "${name} offline phase" "server became unreachable within ${offline_timeout}s"

  reconnect_deadline=$((SECONDS + reconnect_timeout))
  while (( SECONDS < reconnect_deadline )); do
    code="$(curl "${CURL_TLS_ARGS[@]}" -sS -b "$COOKIE_JAR" -c "$COOKIE_JAR" -o "$out" -w "%{http_code}" "$BASE_URL/api/version" || true)"
    if [[ "$code" == "200" ]]; then
      started_at="$(json_expr 'data.get("started_at", "")' "$out" 2>/dev/null || true)"
      if [[ -n "$started_at" && "$started_at" != "$previous_started_at" ]]; then
        pass "$name" "reconnected within ${reconnect_timeout}s after offline phase; started_at changed ${previous_started_at:-unknown} -> $started_at"
        return 0
      fi
    fi
    sleep 2
  done

  fail "$name" "server did not reconnect with a new started_at within ${reconnect_timeout}s after offline phase; previous=${previous_started_at:-unknown}, last_http=${code:-none}, body=$out"
  return 1
}

start_server() {
  echo "[*] Runtime: $RUNTIME_ROOT"
  echo "[*] Report: $OUT_DIR"
  echo "[*] Pre-start snapshot: $PRE_START_SNAPSHOT"
  env \
    HTML_LEARNING_HOST="$HOST" \
    HTML_LEARNING_PORT="$PORT" \
    HTML_LEARNING_DB_DIR="$RUNTIME_ROOT/database" \
    HTML_LEARNING_LOG_DIR="$RUNTIME_ROOT/logs" \
    HTML_LEARNING_CHAT_DIR="$RUNTIME_ROOT/chats" \
    HTML_LEARNING_ANCHOR_DIR="$RUNTIME_ROOT/anchors" \
    HTML_LEARNING_STORAGE_DIR="$RUNTIME_ROOT/storage" \
    HTML_LEARNING_REPORTS_DIR="$RUNTIME_ROOT/reports" \
    HTML_LEARNING_ROOT_PASSWORD="$ROOT_PASSWORD" \
    HTML_LEARNING_MANAGER_PASSWORD="$MANAGER_PASSWORD" \
    HTML_LEARNING_TEST_PASSWORD="$TEST_PASSWORD" \
    SESSION_COOKIE_SECURE=false \
    IP_BLOCKING_ENABLED=true \
    python3 server.py > "$SERVER_LOG" 2>&1 &
  SERVER_PID=$!
  if ! wait_for_server; then
    if ! kill -0 "$SERVER_PID" >/dev/null 2>&1; then
      record "server process" "fail" "process exited before readiness; see $SERVER_LOG"
    fi
    return 1
  fi
}

fetch_public_csrf() {
  local out="$RAW_DIR/00_csrf_token.json"
  local code
  code="$(curl "${CURL_TLS_ARGS[@]}" -sS -c "$COOKIE_JAR" -o "$out" -w "%{http_code}" "$BASE_URL/api/csrf-token" || true)"
  if [[ "$code" != "200" ]]; then
    fail "csrf token" "GET /api/csrf-token -> $code"
    return 1
  fi
  CSRF_TOKEN="$(json_expr 'data["csrf_token"]' "$out")"
  pass "csrf token" "received public token"
}

login_root() {
  request "auth login root" "POST" "/api/login" "200" "{\"username\":\"root\",\"password\":\"$ROOT_PASSWORD\",\"csrf_token\":\"$CSRF_TOKEN\"}"
  CSRF_TOKEN="$(csrf_from_cookie)"
  if [[ -z "$CSRF_TOKEN" ]]; then
    fail "auth csrf refresh" "missing csrf_token cookie after login"
    return 1
  fi
  pass "auth csrf refresh" "received per-user token"
}

login_smoke_user() {
  rm -f "$COOKIE_JAR"
  fetch_public_csrf || return 1
  request "auth login smoke user" "POST" "/api/login" "200" "{\"username\":\"smokeuser\",\"password\":\"SmokeUser123!\",\"csrf_token\":\"$CSRF_TOKEN\"}"
  CSRF_TOKEN="$(csrf_from_cookie)"
  if [[ -z "$CSRF_TOKEN" ]]; then
    fail "auth csrf refresh smoke user" "missing csrf_token cookie after smoke user login"
    return 1
  fi
  pass "auth csrf refresh smoke user" "received per-user token"
}

check_local_tls_files() {
  if [[ -s "$REPO_ROOT/cert.pem" && -s "$REPO_ROOT/key.pem" ]]; then
    pass "local TLS files generated" "cert.pem and key.pem exist locally"
  else
    fail "local TLS files generated" "cert.pem/key.pem missing after startup"
  fi
}

change_default_root_password() {
  request "auth change default root password" "PUT" "/api/admin/users/1" "200" "{\"current_password\":\"$ROOT_PASSWORD\",\"password\":\"$ROOT_CHANGED_PASSWORD\",\"password_confirm\":\"$ROOT_CHANGED_PASSWORD\"}"
  ROOT_PASSWORD="$ROOT_CHANGED_PASSWORD"
  rm -f "$COOKIE_JAR"
  fetch_public_csrf || return 1
  login_root || return 1
}

create_smoke_user() {
  local payload
  payload='{"username":"smokeuser","pass''word":"SmokeUser123!","pass''word_confirm":"SmokeUser123!","nickname":"Smoke User","real_name":"Smoke User","id_number":"A123456789","birthdate":"2000-01-01","phone":"0912345678","role":"user","status":"active","member_level":"normal"}'
  request "admin create smoke user" "POST" "/api/admin/users" "200,409" "$payload"
  request "admin list users after create" "GET" "/api/admin/users" "200"
  SMOKE_USER_ID="$(json_expr 'next(u["id"] for u in data["users"] if u["username"] == "smokeuser")' "$(latest_raw "admin list users after create")" || true)"
  if [[ -z "${SMOKE_USER_ID:-}" ]]; then
    skip "smoke user id" "smokeuser not found; dependent DM/mod-note checks skipped"
  else
    pass "smoke user id" "id=$SMOKE_USER_ID"
  fi
}

enable_smoke_feature_flags() {
  request "admin enable smoke feature flags" "PUT" "/api/admin/features" "200" '{
    "feature_chat_enabled": true,
    "feature_community_enabled": true,
    "feature_appeals_enabled": true,
    "feature_reports_enabled": true,
    "feature_forum_core_enabled": true,
    "feature_attachments_enabled": true,
    "feature_storage_albums_enabled": true,
    "feature_privacy_uploads_enabled": true,
    "feature_comfyui_enabled": true,
    "feature_economy_enabled": true,
    "feature_trading_enabled": true,
    "feature_games_enabled": true,
    "feature_account_security_enabled": true
  }'
  request "admin verify smoke feature flags" "GET" "/api/admin/features" "200"
}

create_forum_post_flow() {
  local prefix="$1"
  local category_var="$2"
  local board_var="$3"
  local thread_var="$4"
  local category_name="${prefix} Category $RUN_ID"
  local board_title="${prefix} Board $RUN_ID"
  local thread_title="${prefix} Thread $RUN_ID"

  request "${prefix} create category" "POST" "/api/community/categories" "200" "{\"name\":\"$category_name\",\"description\":\"$prefix functional category\",\"sort_order\":901}"
  request "${prefix} list categories" "GET" "/api/community/categories" "200"
  local category_id
  category_id="$(json_expr "next(c['id'] for c in data['categories'] if c['name'] == '$category_name')" "$(latest_raw "${prefix} list categories")" || true)"
  if [[ -z "$category_id" ]]; then
    skip "${prefix} forum post flow" "category id not found"
    return 1
  fi

  request "${prefix} create board" "POST" "/api/community/boards" "200" "{\"category_id\":$category_id,\"title\":\"$board_title\",\"description\":\"$prefix functional board\",\"rules\":\"be kind\",\"visibility\":\"public\",\"sort_order\":902}"
  request "${prefix} list board reviews" "GET" "/api/community/boards/reviews" "200"
  local board_id
  board_id="$(json_expr "next(b['id'] for b in data['items'] if b['title'] == '$board_title')" "$(latest_raw "${prefix} list board reviews")" || true)"
  if [[ -z "$board_id" ]]; then
    skip "${prefix} forum post flow" "board id not found"
    return 1
  fi

  request "${prefix} approve board" "POST" "/api/community/boards/${board_id}/review" "200" '{"action":"approve","note":"functional smoke"}'
  request "${prefix} create thread" "POST" "/api/community/boards/${board_id}/threads" "200" "{\"title\":\"$thread_title\",\"content\":\"$prefix functional thread body\",\"post_type\":\"normal\"}"
  request "${prefix} list threads" "GET" "/api/community/boards/${board_id}/threads" "200"
  local thread_id
  thread_id="$(json_expr "next(t['id'] for t in data['threads'] if t['title'] == '$thread_title')" "$(latest_raw "${prefix} list threads")" || true)"
  if [[ -z "$thread_id" ]]; then
    skip "${prefix} forum post flow" "thread id not found"
    return 1
  fi

  printf -v "$category_var" '%s' "$category_id"
  printf -v "$board_var" '%s' "$board_id"
  printf -v "$thread_var" '%s' "$thread_id"
  pass "${prefix} forum post flow" "category=$category_id board=$board_id thread=$thread_id"
}

create_app_snapshot_checkpoint() {
  request "snapshot create checkpoint" "POST" "/api/admin/snapshots" "200" '{"type":"manual","notes":"functional smoke checkpoint after baseline post"}'
  APP_SNAPSHOT_ID="$(json_expr 'data["snapshot_id"]' "$(latest_raw "snapshot create checkpoint")" || true)"
  if [[ -z "${APP_SNAPSHOT_ID:-}" ]]; then
    fail "snapshot checkpoint id" "snapshot_id missing"
    return 1
  fi
  pass "snapshot checkpoint id" "$APP_SNAPSHOT_ID"
  request "snapshot list after checkpoint" "GET" "/api/admin/snapshots" "200"
}

create_community_flow() {
  create_forum_post_flow "residual" CATEGORY_ID BOARD_ID THREAD_ID || return 0
  if [[ -z "${THREAD_ID:-}" ]]; then
    skip "community thread detail/actions" "thread id not found"
    return 0
  fi

  request "community thread detail" "GET" "/api/community/threads/${THREAD_ID}" "200"
  request "community thread like" "POST" "/api/community/threads/${THREAD_ID}/reaction" "200" '{"value":1}'
  request "community reward thread author" "POST" "/api/community/threads/${THREAD_ID}/reward" "200" '{"points":1,"reason":"functional smoke reward"}'
  if [[ -n "${SMOKE_USER_ID:-}" ]]; then
    request "community set board moderator permissions" "POST" "/api/community/boards/${BOARD_ID}/moderators" "200" "{\"user_id\":$SMOKE_USER_ID,\"can_review_threads\":true,\"can_pin_posts\":true,\"can_lock_threads\":true,\"can_edit_posts\":true,\"can_delete_posts\":true,\"can_reward_authors\":true,\"can_penalize_posts\":true}"
    request "community list board moderators" "GET" "/api/community/boards/${BOARD_ID}/moderators" "200"
  else
    skip "community board moderator permissions" "smoke user id missing"
  fi
  request "community reply" "POST" "/api/community/threads/${THREAD_ID}/posts" "200" '{"content":"functional smoke reply"}'
  request "community lock thread" "POST" "/api/community/threads/${THREAD_ID}/lock" "200" '{"locked":true}'
  request "community sticky thread" "POST" "/api/community/threads/${THREAD_ID}/sticky" "200" '{"sticky":true}'
  request "community curate thread" "POST" "/api/community/threads/${THREAD_ID}/curate" "200" '{"curated":true}'
}

run_checks() {
  start_server || return 1
  fetch_public_csrf || return 1

  request "public index" "GET" "/" "200"
  request "public site config" "GET" "/api/site-config" "200"
  request "public version" "GET" "/api/version" "200"
  request "public password strength" "POST" "/api/password-strength" "200" '{"pass''word":"SmokeUser123!"}'
  request "public captcha challenge" "GET" "/api/captcha/challenge" "200"
  check_local_tls_files

  login_root || return 1
  request "auth me" "GET" "/api/me" "200"
  if [[ "$(json_expr 'data.get("must_change_password", False)' "$(latest_raw "auth me")" || echo false)" == "true" ]]; then
    change_default_root_password || return 1
    request "auth me after password change" "GET" "/api/me" "200"
  fi

  enable_smoke_feature_flags || return 1
  create_forum_post_flow "baseline" BASELINE_CATEGORY_ID BASELINE_BOARD_ID BASELINE_THREAD_ID || return 1
  create_app_snapshot_checkpoint || return 1

  request "account sessions" "GET" "/api/account/sessions" "200,503"

  request "admin health" "GET" "/api/admin/health" "200"
  request "admin readiness" "GET" "/api/admin/health/readiness" "200"
  request "admin anomaly" "GET" "/api/admin/health/anomaly" "200"
  request "admin db integrity" "GET" "/api/admin/health/db-integrity" "200"
  request "admin audit chain" "GET" "/api/admin/health/audit-chain" "200"
  request "admin environment" "GET" "/api/admin/environment" "200"
  request "admin settings" "GET" "/api/admin/settings" "200"
  request "admin settings comfyui api port" "PUT" "/api/admin/settings" "200" '{"comfyui_api_port":8192}'
  request "admin features" "GET" "/api/admin/features" "200"
  request "admin access controls" "GET" "/api/admin/access-controls" "200"
  request "admin member rules" "GET" "/api/admin/member-level-rules" "200"
  request "admin platform stats" "GET" "/api/admin/platform-stats" "200"
  request "admin audit log" "GET" "/api/admin/audit" "200"
  request "security center summary" "GET" "/api/admin/security-center" "200"
  request "root server live output" "GET" "/api/admin/server-output?limit=50" "200"
  request "security center update thresholds" "PUT" "/api/admin/security-center/thresholds" "200" '{"security_pending_chat_reports_threshold":12,"security_pending_appeals_threshold":12,"security_pending_moderation_proposals_threshold":12,"security_quarantined_files_threshold":0,"security_unknown_encrypted_files_threshold":80,"security_log_tail_lines":120,"max_login_failures":3,"block_duration_minutes":10}'
  request "security center update controls" "PUT" "/api/admin/security-center/controls" "200" '{"ip_blocking_enabled":true,"login_violation_enabled":true,"rate_limit_violation_enabled":true,"integrity_guard_enabled":true,"integrity_guard_strict_mode":false,"browser_only_mode_enabled":false}'
  request "security center create custom profile" "POST" "/api/admin/security-center/profiles" "200" "{\"name\":\"smoke_profile_${RUN_ID,,}\",\"label\":\"Smoke Profile\",\"description\":\"functional smoke custom security profile\",\"settings\":{\"ip_blocking_enabled\":true,\"integrity_guard_strict_mode\":false},\"thresholds\":{\"security_pending_chat_reports_threshold\":7}}"
  request "security center apply custom profile" "POST" "/api/admin/server-mode" "200" "{\"mode\":\"smoke_profile_${RUN_ID,,}\",\"confirm\":\"\",\"notes\":\"functional smoke custom profile\"}"
  request "integrity guard status" "GET" "/api/root/integrity/status" "200"
  request "integrity guard pending findings" "GET" "/api/root/integrity/findings?status=pending" "200"

  create_smoke_user

  request "points wallet root" "GET" "/api/points/wallet" "200"
  request "points catalog" "GET" "/api/points/catalog" "200"
  request "points rules" "GET" "/api/points/rules" "200"
  if [[ -n "${SMOKE_USER_ID:-}" ]]; then
    request "points admin credit smoke user" "POST" "/api/admin/points/adjust" "200" "{\"user_id\":$SMOKE_USER_ID,\"currency_type\":\"soft\",\"direction\":\"credit\",\"amount\":1000,\"reason\":\"functional smoke seed\"}"
    request "points admin wallet smoke user" "GET" "/api/admin/points/wallets/${SMOKE_USER_ID}" "200"
    request "points admin ledger" "GET" "/api/admin/points/ledger?limit=20" "200"
    request "points chain seal" "POST" "/api/root/points/chain/seal" "200" '{"limit":100}'
    request "points chain verify" "GET" "/api/root/points/chain/verify" "200"
    request "points chain recovery status" "GET" "/api/root/points/chain/recovery" "200"
    request "points chain one-click anomaly handler" "POST" "/api/root/points/chain/recovery/auto-handle" "200" '{"confirm":"AUTO HANDLE POINTSCHAIN"}'
    request "points chain backup manual" "POST" "/api/root/points/chain/backups" "200" '{}'
    request "points economy stats" "GET" "/api/admin/points/economy/stats" "200"
    request "trading root report" "GET" "/api/admin/trading/report" "200"
    request "trading root manual price rejected" "POST" "/api/root/trading/markets/ETH%2FPOINTS" "400" '{"manual_price_points":5000,"max_price_jump_percent":10,"fee_rate_percent":0.3,"min_order_points":1,"max_order_points":100000,"enabled":true}'
    login_smoke_user || return 1
    request "trading user dashboard" "GET" "/api/trading/dashboard" "200"
    request "trading market buy" "POST" "/api/trading/orders" "200" '{"market_symbol":"ETH/POINTS","side":"buy","order_type":"market","quantity":"0.01"}'
    request "trading dashboard after buy" "GET" "/api/trading/dashboard" "200"
    request "trading open limit order" "POST" "/api/trading/orders" "200" '{"market_symbol":"ETH/POINTS","side":"buy","order_type":"limit","quantity":"0.01","limit_price_points":1}'
    TRADING_LIMIT_ORDER_UUID="$(json_expr 'data["order"]["order_uuid"]' "$(latest_raw "trading open limit order")" || true)"
    if [[ -n "${TRADING_LIMIT_ORDER_UUID:-}" ]]; then
      request "trading cancel limit order" "POST" "/api/trading/orders/${TRADING_LIMIT_ORDER_UUID}/cancel" "200" '{}'
    else
      skip "trading cancel limit order" "limit order uuid not found"
    fi
    login_root || return 1
    request "trading root report after smoke trades" "GET" "/api/admin/trading/report" "200"
  else
    skip "points admin credit smoke user" "smoke user id missing"
    skip "points chain seal/verify" "smoke user id missing"
  fi

  request "community announcements list" "GET" "/api/community/announcements" "200"
  request "community create announcement" "POST" "/api/community/announcements" "200" '{"title":"Smoke Announcement","content":"functional smoke announcement","is_pinned":true}'
  request "community categories list" "GET" "/api/community/categories" "200"
  request "community boards list" "GET" "/api/community/boards" "200"
  create_community_flow

  request "chat rooms list" "GET" "/api/chat/rooms" "200"
  ROOM_ID="$(json_expr 'data["rooms"][0]["id"]' "$(latest_raw "chat rooms list")" || true)"
  if [[ -n "${ROOM_ID:-}" ]]; then
    request "chat send message" "POST" "/api/chat/rooms/${ROOM_ID}/messages" "200" '{"content":"functional smoke chat message"}'
    request "chat messages list" "GET" "/api/chat/rooms/${ROOM_ID}/messages" "200"
  else
    skip "chat room message flow" "no room returned"
  fi

  if [[ -n "${SMOKE_USER_ID:-}" ]]; then
    request "dm create private chat room" "POST" "/api/chat/rooms" "200" '{"target_user":"smokeuser"}'
    DM_ROOM_ID="$(json_expr 'data["room"]["id"]' "$(latest_raw "dm create private chat room")" || true)"
    if [[ -n "${DM_ROOM_ID:-}" ]]; then
      request "dm send message" "POST" "/api/chat/rooms/${DM_ROOM_ID}/messages" "200" '{"content":"functional smoke dm"}'
      request "dm list messages" "GET" "/api/chat/rooms/${DM_ROOM_ID}/messages" "200"
    else
      skip "dm message flow" "private chat room id not found"
    fi
  fi

  request "files quota" "GET" "/api/files/quota" "200"
  request "files security policy" "GET" "/api/files/security-policy" "200"
  request "cloud drive storage upgrades root" "GET" "/api/cloud-drive/storage-upgrades" "200"
  if json_bool 'data.get("can_purchase") == False and "root" in str(data.get("message", "")).lower()' "$(latest_raw "cloud drive storage upgrades root")"; then
    pass "root storage purchase bypass" "root does not need storage purchase plans"
  else
    fail "root storage purchase bypass" "root should not see purchasable storage plans"
  fi
  request "root storage users" "GET" "/api/root/storage/users" "200"
  request "admin storage capacity summary" "GET" "/api/admin/storage/summary" "200"
  ROOT_QUOTA_SOURCE="$(json_expr 'data["security"]["usage"]["quota_source"]' "$(latest_raw "files security policy")" || true)"
  ROOT_QUOTA_TOTAL="$(json_expr 'data["security"]["usage"]["total_bytes"]' "$(latest_raw "files security policy")" || true)"
  ROOT_QUOTA_WARN="$(json_expr 'data["security"]["usage"]["warning_threshold_percent"]' "$(latest_raw "files security policy")" || true)"
  if [[ "$ROOT_QUOTA_SOURCE" == "root_disk_available_90_percent" && "${ROOT_QUOTA_TOTAL:-0}" -gt 0 && "$ROOT_QUOTA_WARN" == "80" ]]; then
    pass "root cloud drive disk quota" "quota_source=$ROOT_QUOTA_SOURCE total_bytes=$ROOT_QUOTA_TOTAL warning=$ROOT_QUOTA_WARN%"
  else
    fail "root cloud drive disk quota" "expected disk-backed 90% quota and 80% warning, got source=${ROOT_QUOTA_SOURCE:-missing}, total=${ROOT_QUOTA_TOTAL:-missing}, warning=${ROOT_QUOTA_WARN:-missing}"
  fi
  request "files privacy modes" "GET" "/api/files/privacy-modes" "200"
  request "cloud drive remote downloader capabilities" "GET" "/api/cloud-drive/remote-download/capabilities" "200"
  request "cloud drive remote downloader rejects local file" "POST" "/api/cloud-drive/remote-download" "400" '{"url":"file:///etc/passwd","privacy_mode":"standard_plain"}'
  request "cloud drive remote downloader task rejects local file" "POST" "/api/cloud-drive/remote-download/tasks" "400" '{"url":"file:///etc/passwd","privacy_mode":"standard_plain"}'
  request "comfyui status" "GET" "/api/comfyui/status" "200"
  request "comfyui models" "GET" "/api/comfyui/models" "200,503"
  if [[ "$(json_expr 'data.get("ok", False)' "$(latest_raw "comfyui models")" || echo false)" == "true" ]]; then
    pass "comfyui integration availability" "ComfyUI model endpoint is reachable"
  else
    skip "comfyui integration availability" "ComfyUI backend is optional for functional smoke"
  fi
  request "comfyui discard requires image ref" "POST" "/api/comfyui/discard" "400" '{"prompt_id":"smoke"}'
  request "comfyui share requires generated image" "POST" "/api/comfyui/share" "400" '{"title":"smoke comfyui share"}'
  request "cloud drive files list" "GET" "/api/cloud-drive/files" "200"
  request "storage files list" "GET" "/api/storage/files" "200"
  request "storage albums list" "GET" "/api/storage/albums" "200"

  printf 'functional smoke storage album file\n' > "$OUT_DIR/storage_album.txt"
  upload_file "storage file upload" "/api/storage/files" "$OUT_DIR/storage_album.txt" "200"
  STORAGE_FILE_ID="$(json_expr 'data["storage_file"]["id"]' "$(latest_raw "storage file upload")" || true)"
  request "storage folder create" "POST" "/api/storage/folders" "200" "{\"path\":\"/smoke/raw-$RUN_ID\"}"
  request "storage folders list" "GET" "/api/storage/folders" "200"
  if [[ -n "${STORAGE_FILE_ID:-}" ]]; then
    request "storage file organize" "PUT" "/api/storage/files/${STORAGE_FILE_ID}/organize" "200" "{\"virtual_path\":\"/smoke/raw-$RUN_ID/storage_album.txt\"}"
    request "storage folder album rejects non media folder" "POST" "/api/storage/folders/album" "400" "{\"path\":\"/smoke/raw-$RUN_ID\",\"title\":\"Smoke Folder Album $RUN_ID\"}"
    request "storage folder move" "PUT" "/api/storage/folders/move" "200" "{\"old_path\":\"/smoke/raw-$RUN_ID\",\"new_path\":\"/smoke/archive-$RUN_ID\"}"
  else
    skip "storage file organize" "storage file id not found"
    skip "storage folder move" "storage file id not found"
  fi
  request "storage album create" "POST" "/api/storage/albums" "200" "{\"title\":\"Smoke Album $RUN_ID\",\"description\":\"functional smoke album\",\"visibility\":\"unlisted\"}"
  ALBUM_ID="$(json_expr 'data["album"]["id"]' "$(latest_raw "storage album create")" || true)"
  if [[ -n "${STORAGE_FILE_ID:-}" && -n "${ALBUM_ID:-}" ]]; then
    request "storage album add file" "POST" "/api/storage/albums/${ALBUM_ID}/files" "200" "{\"storage_file_id\":\"$STORAGE_FILE_ID\",\"caption\":\"functional smoke\",\"sort_order\":1}"
    ALBUM_FILE_ID="$(json_expr 'data["album"]["files"][0]["id"]' "$(latest_raw "storage album add file")" || true)"
    request "storage album detail" "GET" "/api/storage/albums/${ALBUM_ID}" "200"
    request "storage album update" "PUT" "/api/storage/albums/${ALBUM_ID}" "200" "{\"title\":\"Smoke Album Updated $RUN_ID\",\"description\":\"updated by functional smoke\",\"visibility\":\"public\"}"
    if [[ -n "${ALBUM_FILE_ID:-}" ]]; then
      request "storage album remove file" "DELETE" "/api/storage/albums/${ALBUM_ID}/files/${ALBUM_FILE_ID}" "200" "{}"
    else
      skip "storage album remove file" "album file id not found"
    fi
    request "storage album delete" "DELETE" "/api/storage/albums/${ALBUM_ID}" "200" "{}"
  else
    skip "storage album membership flow" "storage_file_id=${STORAGE_FILE_ID:-missing}, album_id=${ALBUM_ID:-missing}"
  fi

  printf 'functional smoke upload\n' > "$OUT_DIR/upload.txt"
  upload_file "cloud drive upload" "/api/cloud-drive/upload" "$OUT_DIR/upload.txt" "200"
  UPLOAD_ID="$(json_expr 'data["file"]["file_id"]' "$(latest_raw "cloud drive upload")" || true)"
  if [[ -n "${UPLOAD_ID:-}" ]]; then
    request "file status" "GET" "/api/files/${UPLOAD_ID}/status" "200"
    request "cloud drive preview" "GET" "/api/cloud-drive/files/${UPLOAD_ID}/preview" "200"
    request "cloud drive download" "GET" "/api/cloud-drive/files/${UPLOAD_ID}/download" "200"
    request "cloud drive delete" "DELETE" "/api/cloud-drive/files/${UPLOAD_ID}" "200" '{}'
  else
    skip "file status/download/delete" "upload id not found"
  fi

  request "bug report create" "POST" "/api/bug-reports" "200" '{"severity":"low","title":"Smoke bug report","description":"functional smoke bug report"}'
  request "admin bug reports" "GET" "/api/admin/bug-reports" "200"
  request "reports list" "GET" "/api/admin/reports" "200"
  request "notifications list" "GET" "/api/notifications" "200"
  request "appeals list" "GET" "/api/appeals" "200"
  request "admin appeals list" "GET" "/api/admin/appeals" "200"
  request "moderation actions" "GET" "/api/admin/moderation-actions" "200,503"
  request "moderation proposals" "GET" "/api/admin/moderation/proposals" "200,503"
  request "violations list" "GET" "/api/admin/violations" "200"
  request "message reports" "GET" "/api/admin/message-reports" "200"
  if [[ -n "${SMOKE_USER_ID:-}" ]]; then
    request "mod notes create" "POST" "/api/admin/mod-notes/${SMOKE_USER_ID}" "200,503" '{"note":"functional smoke note"}'
    request "mod notes list" "GET" "/api/admin/mod-notes/${SMOKE_USER_ID}" "200,503"
  fi
  request "reputation history" "GET" "/api/account/reputation/history" "200,503"
  request "reputation summary" "GET" "/api/account/reputation/summary" "200,503"
  check_unknown_options

  request "snapshot restore checkpoint" "POST" "/api/admin/snapshots/${APP_SNAPSHOT_ID}/restore" "200" '{"confirm":"RESTORE","reason":"functional smoke cleanup verification"}'
  login_root || return 1
  request "restore verify baseline threads" "GET" "/api/community/boards/${BASELINE_BOARD_ID}/threads" "200"
  if json_bool "any(t['id'] == int('$BASELINE_THREAD_ID') for t in data['threads'])" "$(latest_raw "restore verify baseline threads")"; then
    pass "restore kept baseline post" "thread=$BASELINE_THREAD_ID"
  else
    fail "restore kept baseline post" "baseline thread not found after restore"
  fi
  if json_bool "any(str(t['title']).startswith('residual Thread') for t in data['threads'])" "$(latest_raw "restore verify baseline threads")"; then
    fail "restore removed residual posts" "residual thread still visible after restore"
  else
    pass "restore removed residual posts" "no residual thread under baseline board"
  fi
  request "restore verify residual category gone" "GET" "/api/community/categories" "200"
  if json_bool "any(str(c['name']).startswith('residual Category') for c in data['categories'])" "$(latest_raw "restore verify residual category gone")"; then
    fail "restore removed residual category" "residual category still visible after restore"
  else
    pass "restore removed residual category" "residual category not visible after restore"
  fi

  local reset_started_at_before
  reset_started_at_before="$(server_started_at "$RAW_DIR/reset_before_version.json" || true)"
  request "server reset runtime state" "POST" "/api/admin/system-reset" "200" '{"confirm":"RESET_RUNTIME_STATE","reason":"functional smoke reset verification"}'
  wait_for_restart_reconnect "server reset restart reconnect" "$reset_started_at_before" "$RESET_OFFLINE_TIMEOUT" "$RESET_RECONNECT_TIMEOUT" || true
  check_local_tls_files
  rm -f "$COOKIE_JAR"
  fetch_public_csrf || true
  login_root || true
  request "reset verify baseline board gone" "GET" "/api/community/boards/${BASELINE_BOARD_ID}/threads" "404,503"
  pass "reset removed baseline post" "baseline board/thread no longer visible after reset"
}

pass "runtime pre-start snapshot" "$PRE_START_SNAPSHOT"
run_checks || true

cat > "$SUMMARY" <<EOF
# Functional Smoke Test Report

- target: \`$BASE_URL\`
- started_at_utc: \`$RUN_ID\`
- runtime_root: \`$RUNTIME_ROOT\`
- keep_runtime: \`$KEEP_RUNTIME\`
- reset_offline_timeout_seconds: \`$RESET_OFFLINE_TIMEOUT\`
- reset_reconnect_timeout_seconds: \`$RESET_RECONNECT_TIMEOUT\`
- pre_start_snapshot: \`$PRE_START_SNAPSHOT\`
- server_log: \`$SERVER_LOG\`
- failures: \`$FAILURES\`
- skips: \`$SKIPS\`

## Results

\`\`\`text
$(cat "$RESULTS_TSV")
\`\`\`

## Functional Coverage

- runtime safety: pre-start filesystem snapshot, isolated runtime cleanup/restore
- public/API basics: index, site config, version, password strength, captcha challenge
- authentication: CSRF bootstrap, root login, forced default-password change, session identity
- administration: health, readiness, anomaly, DB integrity, audit chain, environment, settings, feature flags, access controls, member rules, platform stats, audit log
- security center: aggregate security overview, root-only audit data, server log/live output, security controls, threshold update, custom profile creation, custom profile mode switch, integrity guard status/pending finding checks
- PointsChain economy: wallet, catalog/rules, admin adjustment, ledger listing, root block sealing, chain verification, manual ledger backup, recovery status, economy stats
- Trading engine: root trading report, manual market price update, user spot market buy, limit order creation/cancellation, root trading audit report
- snapshots/restore/reset: in-app snapshot creation/listing, restore verification that keeps only the baseline forum post, server reset must go offline within 20 seconds then reconnect within 180 seconds by default, reset verification that removes the baseline post, and TLS files regenerate after reset
- deployment-local TLS: cert.pem/key.pem are generated on startup and regenerated after runtime reset
- storage and files: storage quota/listing, root storage capacity audit, root storage user list, cloud-drive storage upgrade catalog, cloud-drive upload/status/preview/download/delete, remote download capability checks
- ComfyUI integration: model endpoint wiring and optional backend availability check
- accounts: admin user creation/listing, account sessions when account-security feature is enabled
- community: announcements, categories, boards, board approval, board moderator permission scope, thread create/detail/reply/reaction/reward/lock/sticky/curate
- chat and DM: room listing, message send/list, DM thread/message flow
- reports and moderation: bug reports, reports, notifications, appeals, moderation actions/proposals, violations, message reports, mod notes, reputation endpoints
- hardening regression: unknown-path OPTIONS does not advertise unsafe methods

## Notes

- The server is started with all runtime paths redirected into the isolated runtime root.
- A filesystem snapshot is created before the server starts.
- By default, the runtime root is removed after the test. With \`--keep-runtime\`, it is restored to the pre-start snapshot state.
EOF

echo "[*] Summary: $SUMMARY"
if [[ "$FAILURES" -gt 0 ]]; then
  exit 1
fi
