#!/usr/bin/env bash
set -Eeuo pipefail

SOURCE_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEFAULT_GIT_REPO_DIR="$SOURCE_ROOT"
RUN_ID="$(date +%Y%m%d_%H%M%S)"
RUN_ROOT=""
HOST="${HOST:-127.0.0.1}"
PORT="${PORT:-5000}"
CLI_MODE=0
SKIP_INSTALL=0
FOREGROUND=0
IN_PLACE="${HACKME_DEV_IN_PLACE:-0}"
ROOT_PASSWORD="${ROOT_PASSWORD:-root}"
MANAGER_PASSWORD="${MANAGER_PASSWORD:-admin}"
TEST_PASSWORD="${TEST_PASSWORD:-test}"
PYTHON_BIN="${PYTHON_BIN:-python3}"
FEATURE_MODE="${HACKME_DEV_FEATURE_MODE:-all}"
FEATURE_LIST="${HACKME_DEV_FEATURES:-}"
DEV_TOKEN_FEATURES="${HACKME_DEV_TOKEN_FEATURES:-${HACKME_DEV_INTERNAL_TEST_TOKEN_FEATURES:-}}"
DEV_TOKEN_TTL_MINUTES="${HACKME_DEV_TOKEN_TTL_MINUTES:-1440}"
FEATURE_MODE_SET=0
SECURITY_SETTINGS_ENABLED="${HACKME_DEV_SECURITY_ENABLED:-0}"
SERVER_MODE="${HACKME_DEV_SERVER_MODE:-dev_ready}"
EXTRA_ACCOUNTS="${HACKME_DEV_EXTRA_ACCOUNTS:-}"
PORT_CONFLICT_ACTION="${HACKME_DEV_PORT_CONFLICT_ACTION:-}"
BTC_TRADE_AUTOSTART="${HACKME_DEV_BTC_TRADE_AUTOSTART:-0}"
BACKTEST_PROBE_ON_STARTUP="${HACKME_DEV_BACKTEST_PROBE_ON_STARTUP:-0}"
DRY_RUN=0

usage() {
  cat <<'USAGE'
Usage:
  ./test_for_develop.sh [options]

Purpose:
  Copy the repo to /tmp by default, initialize a development-friendly runtime,
  and launch server.py from the copied workspace so the repo never accumulates
  runtime or cache pollution. Pass --in-place / --no-copy when you explicitly
  want to launch from the current repo without copying source files.

Important:
  Without --cli, the script asks for workspace, host, port, feature mode,
  security posture, server mode, dependency handling, foreground mode,
  BTC_trade autostart, account password settings, and extra accounts.
  With --cli, it never prompts and only uses command-line/env values.

  For server-mode / production-gate validation, HTML_LEARNING_GIT_REPO_DIR must
  point at a real git repo with a readable .git directory. Do not point it at
  the /tmp copied workspace unless that copy still preserves git metadata.

Options:
  --cli                    Run non-interactively from command/env options
  --host HOST              Default: 127.0.0.1
  --port PORT              Default: 5000; prompts if occupied in interactive mode
  --feature-mode MODE      all, defaults, or custom. Default: all
  --features LIST          Comma-separated feature_* keys for custom mode
  --token-features LIST    Comma-separated feature_* keys allowed by generated
                           test/internal-test dev tokens. Empty means no extra
                           token-level feature restriction.
  --internal-test-token-features LIST
                           Comma-separated feature_* keys allowed by the
                           generated internal-test login token. Alias of
                           --token-features.
  --token-ttl-minutes N    TTL for generated test/internal-test tokens.
                           Default: 1440
  --security VALUE         on/off. Default: off for dev-friendly runtime
  --server-mode MODE       dev_ready, internal_test, test, preprod, production,
                           superweak, maintenance, or incident_lockdown
  --add-account SPEC       Add dev account as username:password[:role]; repeatable
  --accounts LIST          Comma-separated --add-account specs
  --port-conflict ACTION   ask, kill, fallback, or fail. Default: ask interactively,
                           fallback under --cli
  --btc-trade-autostart    Start BTC_trade in the background after boot
  --no-btc-trade-autostart Do not start BTC_trade in the background
  --backtest-probe-on-startup
                           Run the first-boot trading backtest capacity probe
                           in this temporary runtime
  --dry-run                Print resolved config and exit before copying/starting
  --run-root PATH          Use a fixed /tmp run root instead of auto-generating one
  --in-place, --no-copy    Launch from the current repo; runtime still uses run-root
  --copy                   Force the default /tmp copied source workspace
  --skip-install           Reuse runtime/venv or current Python environment
  --foreground             Run in the foreground instead of nohup background mode
  --root-password VALUE    Default: root
  --manager-password VALUE Default: admin
  --test-password VALUE    Default: test
  -h, --help               Show this help
USAGE
}

say() {
  printf '%s\n' "$*"
}

die() {
  printf 'ERROR: %s\n' "$*" >&2
  exit 1
}

normalize_feature_mode() {
  FEATURE_MODE="${FEATURE_MODE,,}"
  case "$FEATURE_MODE" in
    all|defaults|custom)
      ;;
    default)
      FEATURE_MODE="defaults"
      ;;
    *)
      die "feature mode must be all, defaults, or custom: $FEATURE_MODE"
      ;;
  esac
}

normalize_yes_no_value() {
  local value="${1,,}"
  case "$value" in
    1|true|yes|y|on|enable|enabled)
      NORMALIZED_YES_NO=1
      ;;
    0|false|no|n|off|disable|disabled)
      NORMALIZED_YES_NO=0
      ;;
    *)
      die "$2 must be on/off, yes/no, true/false, or 1/0: $1"
      ;;
  esac
}

normalize_server_mode() {
  SERVER_MODE="${SERVER_MODE,,}"
  case "$SERVER_MODE" in
    production|preprod|dev_ready|internal_test|test|superweak|maintenance|incident_lockdown)
      ;;
    dev|development)
      SERVER_MODE="dev_ready"
      ;;
    internal)
      SERVER_MODE="internal_test"
      ;;
    *)
      die "server mode must be production, preprod, dev_ready, internal_test, test, superweak, maintenance, or incident_lockdown: $SERVER_MODE"
      ;;
  esac
}

normalize_port_conflict_action() {
  PORT_CONFLICT_ACTION="${PORT_CONFLICT_ACTION,,}"
  if [[ -z "$PORT_CONFLICT_ACTION" ]]; then
    if [[ "$CLI_MODE" == "1" ]]; then
      PORT_CONFLICT_ACTION="fallback"
    else
      PORT_CONFLICT_ACTION="ask"
    fi
  fi
  case "$PORT_CONFLICT_ACTION" in
    ask|kill|fallback|fail)
      ;;
    port)
      PORT_CONFLICT_ACTION="fallback"
      ;;
    quit|error)
      PORT_CONFLICT_ACTION="fail"
      ;;
    *)
      die "port conflict action must be ask, kill, fallback, or fail: $PORT_CONFLICT_ACTION"
      ;;
  esac
}

normalize_runtime_options() {
  normalize_feature_mode
  normalize_server_mode
  normalize_port_conflict_action
  normalize_yes_no_value "$IN_PLACE" "in-place"
  IN_PLACE="$NORMALIZED_YES_NO"
  normalize_yes_no_value "$SECURITY_SETTINGS_ENABLED" "security"
  SECURITY_SETTINGS_ENABLED="$NORMALIZED_YES_NO"
  normalize_yes_no_value "$BTC_TRADE_AUTOSTART" "btc trade autostart"
  BTC_TRADE_AUTOSTART="$NORMALIZED_YES_NO"
  normalize_yes_no_value "$BACKTEST_PROBE_ON_STARTUP" "backtest probe on startup"
  BACKTEST_PROBE_ON_STARTUP="$NORMALIZED_YES_NO"
}

append_csv_value() {
  local target_var="$1"
  local value="$2"
  local current_value="${!target_var:-}"
  if [[ -z "$current_value" ]]; then
    printf -v "$target_var" '%s' "$value"
  else
    printf -v "$target_var" '%s,%s' "$current_value" "$value"
  fi
}

print_resolved_config() {
  say "[dev-tmp] config:"
  say "  cli:                 $CLI_MODE"
  say "  run_root:            ${RUN_ROOT:-/tmp/hackme_web_dev_${RUN_ID}_$$}"
  if [[ "$IN_PLACE" == "1" ]]; then
    say "  launch_mode:         in-place (no source copy)"
  else
    say "  launch_mode:         tmp copy"
  fi
  say "  host:                $HOST"
  say "  port:                $PORT"
  say "  feature_mode:        $FEATURE_MODE"
  say "  features:            ${FEATURE_LIST:-<none>}"
  say "  token_features:      ${DEV_TOKEN_FEATURES:-<unrestricted>}"
  say "  token_ttl_minutes:   $DEV_TOKEN_TTL_MINUTES"
  say "  security_enabled:    $SECURITY_SETTINGS_ENABLED"
  say "  server_mode:         $SERVER_MODE"
  if [[ -n "$EXTRA_ACCOUNTS" ]]; then
    say "  extra_accounts:      <configured>"
  else
    say "  extra_accounts:      <none>"
  fi
  say "  port_conflict:       $PORT_CONFLICT_ACTION"
  say "  skip_install:        $SKIP_INSTALL"
  say "  foreground:          $FOREGROUND"
  say "  btc_trade_autostart: $BTC_TRADE_AUTOSTART"
  say "  backtest_probe:      $BACKTEST_PROBE_ON_STARTUP"
}

prompt_value() {
  local label="$1"
  local default_value="$2"
  local target_var="$3"
  local answer
  printf '%s [%s]: ' "$label" "$default_value"
  if ! read -r answer; then
    die "interactive setup was interrupted"
  fi
  if [[ -z "$answer" ]]; then
    answer="$default_value"
  fi
  printf -v "$target_var" '%s' "$answer"
}

prompt_yes_no() {
  local label="$1"
  local default_value="$2"
  local target_var="$3"
  local answer
  local suffix
  if [[ "$default_value" == "1" ]]; then
    suffix="Y/n"
  else
    suffix="y/N"
  fi
  while true; do
    printf '%s [%s]: ' "$label" "$suffix"
    if ! read -r answer; then
      die "interactive setup was interrupted"
    fi
    case "${answer,,}" in
      "")
        printf -v "$target_var" '%s' "$default_value"
        return 0
        ;;
      y|yes)
        printf -v "$target_var" '%s' "1"
        return 0
        ;;
      n|no)
        printf -v "$target_var" '%s' "0"
        return 0
        ;;
      *)
        say "Please answer y or n."
        ;;
    esac
  done
}

prompt_feature_settings() {
  local choice
  local default_choice

  normalize_feature_mode
  case "$FEATURE_MODE" in
    all)
      default_choice="1"
      ;;
    defaults)
      default_choice="2"
      ;;
    custom)
      default_choice="3"
      ;;
  esac

  say "Feature mode:"
  say "  1) all      Enable every server DEFAULT_SETTINGS feature_* flag"
  say "  2) defaults Keep server feature defaults"
  say "  3) custom   Enable only the comma-separated feature_* keys you enter"
  while true; do
    printf 'Feature mode [%s]: ' "$default_choice"
    if ! read -r choice; then
      die "interactive setup was interrupted"
    fi
    choice="${choice:-$default_choice}"
    case "${choice,,}" in
      1|all)
        FEATURE_MODE="all"
        FEATURE_LIST=""
        return 0
        ;;
      2|default|defaults)
        FEATURE_MODE="defaults"
        FEATURE_LIST=""
        return 0
        ;;
      3|custom)
        FEATURE_MODE="custom"
        prompt_value "Enabled feature keys, comma-separated" "$FEATURE_LIST" FEATURE_LIST
        return 0
        ;;
      *)
        say "Please choose 1, 2, or 3."
        ;;
    esac
  done
}

prompt_server_mode() {
  local choice
  normalize_server_mode
  say "Server mode:"
  say "  1) dev_ready"
  say "  2) internal_test"
  say "  3) test"
  say "  4) preprod"
  say "  5) production"
  say "  6) maintenance"
  say "  7) incident_lockdown"
  say "  8) superweak"
  while true; do
    printf 'Server mode [%s]: ' "$SERVER_MODE"
    if ! read -r choice; then
      die "interactive setup was interrupted"
    fi
    choice="${choice:-$SERVER_MODE}"
    case "${choice,,}" in
      1|dev|development|dev_ready)
        SERVER_MODE="dev_ready"
        return 0
        ;;
      2|internal|internal_test)
        SERVER_MODE="internal_test"
        return 0
        ;;
      3|test)
        SERVER_MODE="test"
        return 0
        ;;
      4|preprod)
        SERVER_MODE="preprod"
        return 0
        ;;
      5|production|prod)
        SERVER_MODE="production"
        return 0
        ;;
      6|maintenance)
        SERVER_MODE="maintenance"
        return 0
        ;;
      7|incident_lockdown|incident|lockdown)
        SERVER_MODE="incident_lockdown"
        return 0
        ;;
      8|superweak)
        SERVER_MODE="superweak"
        return 0
        ;;
      *)
        say "Please choose a listed mode."
        ;;
    esac
  done
}

prompt_extra_accounts() {
  local add_accounts=0
  local username
  local password
  local role

  prompt_yes_no "Create additional dev accounts" 0 add_accounts
  if [[ "$add_accounts" != "1" ]]; then
    return 0
  fi

  while true; do
    prompt_value "Extra account username (blank to finish)" "" username
    if [[ -z "$username" ]]; then
      return 0
    fi
    prompt_value "Password for $username" "test" password
    prompt_value "Role for $username (user/manager/super_admin)" "user" role
    append_csv_value EXTRA_ACCOUNTS "$username:$password:$role"
  done
}

prompt_runtime_config() {
  local default_run_root="${RUN_ROOT:-/tmp/hackme_web_dev_${RUN_ID}_$$}"
  local use_default_passwords=1

  if [[ ! -t 0 || ! -t 1 ]]; then
    die "interactive setup requires a TTY; pass --cli to use command/env options without prompts"
  fi

  normalize_yes_no_value "$SECURITY_SETTINGS_ENABLED" "security"
  SECURITY_SETTINGS_ENABLED="$NORMALIZED_YES_NO"
  normalize_yes_no_value "$BTC_TRADE_AUTOSTART" "btc trade autostart"
  BTC_TRADE_AUTOSTART="$NORMALIZED_YES_NO"

  say "[dev-tmp] interactive setup; pass --cli to skip prompts"
  prompt_value "Tmp workspace/run root" "$default_run_root" RUN_ROOT
  prompt_yes_no "Launch from current repo without copying source files" "$IN_PLACE" IN_PLACE
  prompt_value "Host" "$HOST" HOST
  prompt_value "Port" "$PORT" PORT
  prompt_feature_settings
  prompt_yes_no "Enable security settings" "$SECURITY_SETTINGS_ENABLED" SECURITY_SETTINGS_ENABLED
  prompt_server_mode
  if [[ "$SERVER_MODE" == "test" || "$SERVER_MODE" == "internal_test" ]]; then
    prompt_value "Generated dev token TTL minutes" "$DEV_TOKEN_TTL_MINUTES" DEV_TOKEN_TTL_MINUTES
    prompt_value "Generated dev token allowed feature keys (blank = unrestricted)" "$DEV_TOKEN_FEATURES" DEV_TOKEN_FEATURES
  fi
  prompt_yes_no "Skip dependency install / reuse existing environment" "$SKIP_INSTALL" SKIP_INSTALL
  prompt_yes_no "Run server in foreground" "$FOREGROUND" FOREGROUND
  prompt_yes_no "Start BTC_trade background job after boot" "$BTC_TRADE_AUTOSTART" BTC_TRADE_AUTOSTART

  if [[ "$ROOT_PASSWORD" != "root" || "$MANAGER_PASSWORD" != "admin" || "$TEST_PASSWORD" != "test" ]]; then
    use_default_passwords=0
  fi
  prompt_yes_no "Use default dev account passwords (root/root admin/admin test/test)" "$use_default_passwords" use_default_passwords
  if [[ "$use_default_passwords" == "1" ]]; then
    ROOT_PASSWORD="root"
    MANAGER_PASSWORD="admin"
    TEST_PASSWORD="test"
  else
    prompt_value "Root password" "$ROOT_PASSWORD" ROOT_PASSWORD
    prompt_value "Manager password" "$MANAGER_PASSWORD" MANAGER_PASSWORD
    prompt_value "Test password" "$TEST_PASSWORD" TEST_PASSWORD
  fi
  prompt_extra_accounts
}

copy_repo() {
  mkdir -p "$COPY_ROOT"
  # The tmp runtime only needs files required to run and develop the server.
  # Keep scripts/tests/workflows, but skip documentation, generated reports,
  # CI metadata and caches so large evidence/doc trees do not make startup hang.
  tar -C "$SOURCE_ROOT" \
    --exclude='./.git' \
    --exclude='./.github' \
    --exclude='./docs' \
    --exclude='./reports' \
    --exclude='./.pytest_cache' \
    --exclude='./.venv' \
    --exclude='./__pycache__' \
    --exclude='./cache' \
    --exclude='./runtime' \
    --exclude='*/reports' \
    --exclude='*/.pytest_cache' \
    --exclude='*/__pycache__' \
    --exclude='*/cache' \
    --exclude='*.log' \
    --exclude='*.out' \
    --exclude='*.pyc' \
    -cf - . | tar -C "$COPY_ROOT" -xf -
}

python_has_runtime_dependencies() {
  python3 - <<'PY' >/dev/null 2>&1
import argon2
import cryptography
import flask
import flask_talisman
PY
}

resolve_python() {
  local venv_dir="$RUNTIME_ROOT/venv"
  if [[ -x "$venv_dir/bin/python3" ]]; then
    PYTHON_BIN="$venv_dir/bin/python3"
    return 0
  fi
  if [[ "$SKIP_INSTALL" == "1" ]]; then
    if python_has_runtime_dependencies; then
      PYTHON_BIN="python3"
      return 0
    fi
    die "--skip-install requires either an existing tmp venv at $venv_dir or a ready system python3 environment"
  fi
  if python_has_runtime_dependencies; then
    PYTHON_BIN="python3"
    return 0
  fi
  python3 -m venv "$venv_dir"
  PYTHON_BIN="$venv_dir/bin/python3"
  if [[ ! -x "$PYTHON_BIN" ]]; then
    die "failed to create tmp venv at $venv_dir"
  fi
  PIP_DISABLE_PIP_VERSION_CHECK=1 "$PYTHON_BIN" -m pip install --upgrade pip
  PIP_DISABLE_PIP_VERSION_CHECK=1 "$PYTHON_BIN" -m pip install -r "$COPY_ROOT/requirements.txt"
}

wait_for_server_url() {
  command -v curl >/dev/null 2>&1 || return 1
  local url
  local scheme
  for _ in $(seq 1 80); do
    for scheme in https http; do
      url="${scheme}://${HOST}:${PORT}/api/version"
      if curl -k -sS "$url" >/dev/null 2>&1; then
        printf '%s\n' "${scheme}://${HOST}:${PORT}"
        return 0
      fi
    done
    sleep 0.5
  done
  return 1
}

print_generated_dev_tokens() {
  local tokens_file="${HACKME_DEV_TOKENS_FILE:-}"
  if [[ -z "$tokens_file" || ! -s "$tokens_file" ]]; then
    return 0
  fi
  say "[dev-tmp] tokens:    $tokens_file"
  "$PYTHON_BIN" - "$tokens_file" <<'PY'
import json
import sys

path = sys.argv[1]
try:
    with open(path, "r", encoding="utf-8") as fh:
        payload = json.load(fh)
except Exception as exc:
    print(f"[dev-tmp] token read failed: {exc}")
    raise SystemExit(0)

tokens = payload.get("tokens") if isinstance(payload, dict) else {}
if not isinstance(tokens, dict):
    raise SystemExit(0)
for name, info in tokens.items():
    if not isinstance(info, dict):
        continue
    token = str(info.get("token") or "").strip()
    if not token:
        continue
    username = info.get("username") or info.get("target_username") or "test"
    expires_at = info.get("expires_at") or ""
    features = info.get("allowed_features") or []
    feature_text = "unrestricted" if not features else ",".join(str(item) for item in features)
    print(f"[dev-tmp] {name}: {token}")
    print(f"[dev-tmp]   user={username} expires_at={expires_at} features={feature_text}")
for warning in payload.get("warnings") or []:
    print(f"[dev-tmp] token warning: {warning}")
PY
}

normalize_port() {
  local value="$1"
  if [[ ! "$value" =~ ^[0-9]+$ ]]; then
    die "port must be a number: $value"
  fi
  local number=$((10#$value))
  if (( number < 1 || number > 65535 )); then
    die "port must be between 1 and 65535: $value"
  fi
  NORMALIZED_PORT="$number"
}

port_is_available() {
  local candidate="$1"
  "$PYTHON_BIN" - "$HOST" "$candidate" <<'PY'
import socket
import sys

host = sys.argv[1]
port = int(sys.argv[2])

try:
    addresses = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
except socket.gaierror:
    raise SystemExit(1)

if not addresses:
    raise SystemExit(1)

for family, socktype, proto, _canonname, sockaddr in addresses:
    try:
        with socket.socket(family, socktype, proto) as sock:
            sock.bind(sockaddr)
    except OSError:
        raise SystemExit(1)

raise SystemExit(0)
PY
}

port_pids() {
  local port="$1"
  if command -v lsof >/dev/null 2>&1; then
    lsof -nP -tiTCP:"$port" -sTCP:LISTEN 2>/dev/null || true
    return 0
  fi
  if command -v ss >/dev/null 2>&1; then
    ss -ltnp "sport = :$port" 2>/dev/null \
      | sed -n 's/.*pid=\([0-9][0-9]*\).*/\1/p' \
      | sort -u
    return 0
  fi
  if command -v fuser >/dev/null 2>&1; then
    fuser -n tcp "$port" 2>/dev/null \
      | tr ' ' '\n' \
      | sed '/^$/d' \
      | sort -u
    return 0
  fi
  return 0
}

port_pid_list() {
  local port="$1"
  { port_pids "$port" || true; } | tr '\n' ' ' | sed 's/[[:space:]]*$//'
}

show_port_processes() {
  local port="$1"
  local pids="$2"
  if [[ -z "$pids" ]]; then
    say "[dev-tmp] port:      no listening process id could be identified for $port"
    return 0
  fi
  say "[dev-tmp] port:      listening pid(s): $pids"
  if command -v ps >/dev/null 2>&1; then
    ps -o pid,ppid,comm,args -p "$(printf '%s' "$pids" | tr ' ' ',')" 2>/dev/null || true
  fi
}

find_next_available_port() {
  local requested="$1"
  local candidate
  local upper=$((requested + 200))
  AVAILABLE_PORT=""
  if (( upper > 65535 )); then
    upper=65535
  fi

  for ((candidate = requested + 1; candidate <= upper; candidate++)); do
    if port_is_available "$candidate"; then
      AVAILABLE_PORT="$candidate"
      return 0
    fi
  done

  for ((candidate = 49152; candidate <= 65535; candidate++)); do
    if (( candidate >= requested && candidate <= upper )); then
      continue
    fi
    if port_is_available "$candidate"; then
      AVAILABLE_PORT="$candidate"
      return 0
    fi
  done

  return 1
}

use_next_available_port() {
  local requested="$1"
  if ! find_next_available_port "$requested"; then
    die "no available port found for host $HOST"
  fi
  PORT="$AVAILABLE_PORT"
  say "[dev-tmp] port:      $requested is occupied on $HOST; using $PORT"
}

kill_port_processes() {
  local requested="$1"
  local pids="$2"
  if [[ -z "$pids" ]]; then
    die "cannot kill the process on port $requested because no pid was identified"
  fi
  say "[dev-tmp] port:      terminating pid(s): $pids"
  if ! kill $pids; then
    die "failed to terminate pid(s): $pids"
  fi
  for _ in $(seq 1 20); do
    if port_is_available "$requested"; then
      PORT="$requested"
      say "[dev-tmp] port:      $requested is now available"
      return 0
    fi
    sleep 0.25
  done
  die "port $requested is still occupied after terminating pid(s): $pids"
}

resolve_occupied_port_interactively() {
  local requested="$1"
  local pids
  local choice

  pids="$(port_pid_list "$requested")"
  say "[dev-tmp] port:      $requested is occupied on $HOST"
  show_port_processes "$requested" "$pids"

  while true; do
    printf '[dev-tmp] choose: [k]ill process, use [p]ort fallback, [q]uit (default: p): '
    if ! read -r choice; then
      choice="p"
    fi
    case "$choice" in
      k|K|kill|Kill)
        kill_port_processes "$requested" "$pids"
        return 0
        ;;
      ""|p|P|port|Port)
        use_next_available_port "$requested"
        return 0
        ;;
      q|Q|quit|Quit)
        die "port $requested is occupied"
        ;;
      *)
        say "[dev-tmp] choose k, p, or q"
        ;;
    esac
  done
}

resolve_server_port() {
  normalize_port "$PORT"
  local requested="$NORMALIZED_PORT"
  PORT="$requested"

  if port_is_available "$requested"; then
    return 0
  fi

  case "$PORT_CONFLICT_ACTION" in
    ask)
      if [[ -t 0 && -t 1 ]]; then
        resolve_occupied_port_interactively "$requested"
      else
        die "port $requested is occupied and --port-conflict ask requires a TTY"
      fi
      ;;
    kill)
      local pids
      pids="$(port_pid_list "$requested")"
      show_port_processes "$requested" "$pids"
      kill_port_processes "$requested" "$pids"
      ;;
    fallback)
      use_next_available_port "$requested"
      ;;
    fail)
      die "port $requested is occupied on $HOST"
      ;;
  esac
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --cli|-cli)
      CLI_MODE=1
      shift
      ;;
    --host)
      HOST="${2:?missing host}"
      shift 2
      ;;
    --port)
      PORT="${2:?missing port}"
      shift 2
      ;;
    --feature-mode)
      FEATURE_MODE="${2:?missing feature mode}"
      FEATURE_MODE_SET=1
      shift 2
      ;;
    --features|--enable-features)
      FEATURE_LIST="${2:?missing feature list}"
      if [[ "$FEATURE_MODE_SET" == "0" ]]; then
        FEATURE_MODE="custom"
      fi
      shift 2
      ;;
    --token-features|--internal-test-token-features)
      DEV_TOKEN_FEATURES="${2:?missing generated token feature list}"
      shift 2
      ;;
    --token-ttl-minutes|--internal-test-token-ttl-minutes)
      DEV_TOKEN_TTL_MINUTES="${2:?missing token ttl minutes}"
      shift 2
      ;;
    --security)
      SECURITY_SETTINGS_ENABLED="${2:?missing security value}"
      shift 2
      ;;
    --security-enabled|--enable-security)
      SECURITY_SETTINGS_ENABLED=1
      shift
      ;;
    --no-security|--disable-security)
      SECURITY_SETTINGS_ENABLED=0
      shift
      ;;
    --server-mode)
      SERVER_MODE="${2:?missing server mode}"
      shift 2
      ;;
    --add-account)
      append_csv_value EXTRA_ACCOUNTS "${2:?missing account spec}"
      shift 2
      ;;
    --accounts)
      EXTRA_ACCOUNTS="${2:?missing account list}"
      shift 2
      ;;
    --port-conflict)
      PORT_CONFLICT_ACTION="${2:?missing port conflict action}"
      shift 2
      ;;
    --btc-trade-autostart)
      BTC_TRADE_AUTOSTART=1
      shift
      ;;
    --no-btc-trade-autostart)
      BTC_TRADE_AUTOSTART=0
      shift
      ;;
    --backtest-probe-on-startup)
      BACKTEST_PROBE_ON_STARTUP=1
      shift
      ;;
    --dry-run)
      DRY_RUN=1
      shift
      ;;
    --run-root)
      RUN_ROOT="${2:?missing run root}"
      shift 2
      ;;
    --in-place|--no-copy)
      IN_PLACE=1
      shift
      ;;
    --copy)
      IN_PLACE=0
      shift
      ;;
    --skip-install)
      SKIP_INSTALL=1
      shift
      ;;
    --foreground)
      FOREGROUND=1
      shift
      ;;
    --root-password)
      ROOT_PASSWORD="${2:?missing root password}"
      shift 2
      ;;
    --manager-password)
      MANAGER_PASSWORD="${2:?missing manager password}"
      shift 2
      ;;
    --test-password)
      TEST_PASSWORD="${2:?missing test password}"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      die "unknown argument: $1"
      ;;
  esac
done

if [[ -n "$FEATURE_LIST" && -z "${HACKME_DEV_FEATURE_MODE:-}" && "$FEATURE_MODE_SET" == "0" ]]; then
  FEATURE_MODE="custom"
fi

if [[ "$CLI_MODE" != "1" ]]; then
  prompt_runtime_config
fi
normalize_runtime_options

RUN_ROOT="${RUN_ROOT:-/tmp/hackme_web_dev_${RUN_ID}_$$}"
if [[ "$DRY_RUN" == "1" ]]; then
  print_resolved_config
  exit 0
fi

if [[ "$IN_PLACE" == "1" ]]; then
  COPY_ROOT="$SOURCE_ROOT"
  RUNTIME_ROOT="$RUN_ROOT/runtime"
else
  COPY_ROOT="$RUN_ROOT/hackme_web"
  RUNTIME_ROOT="$COPY_ROOT/runtime"
fi
LOG_CAPTURE="$RUNTIME_ROOT/logs/server_direct.out"
PID_FILE="$RUNTIME_ROOT/server.pid"

if [[ "$IN_PLACE" == "1" ]]; then
  mkdir -p "$RUN_ROOT"
else
  [[ ! -e "$COPY_ROOT" ]] || die "tmp copy already exists: $COPY_ROOT"
  copy_repo
fi
mkdir -p \
  "$RUNTIME_ROOT/database" \
  "$RUNTIME_ROOT/logs" \
  "$RUNTIME_ROOT/chats" \
  "$RUNTIME_ROOT/anchors" \
  "$RUNTIME_ROOT/storage" \
  "$RUNTIME_ROOT/reports"

resolve_python
if [[ "$PYTHON_BIN" != "python3" ]]; then
  say "[dev-tmp] python:    $PYTHON_BIN"
else
  say "[dev-tmp] python:    python3 (reuse current environment)"
fi
resolve_server_port
if [[ "$ROOT_PASSWORD" == "root" && "$MANAGER_PASSWORD" == "admin" && "$TEST_PASSWORD" == "test" ]]; then
  DEFAULT_ACCOUNT_PASSWORDS=1
else
  DEFAULT_ACCOUNT_PASSWORDS=0
fi

export HACKME_RUNTIME_DIR="$RUNTIME_ROOT"
export HTML_LEARNING_DB_DIR="$RUNTIME_ROOT/database"
export HTML_LEARNING_LOG_DIR="$RUNTIME_ROOT/logs"
export HTML_LEARNING_CHAT_DIR="$RUNTIME_ROOT/chats"
export HTML_LEARNING_ANCHOR_DIR="$RUNTIME_ROOT/anchors"
export HTML_LEARNING_STORAGE_DIR="$RUNTIME_ROOT/storage"
export HTML_LEARNING_REPORTS_DIR="$RUNTIME_ROOT/reports"
export HTML_LEARNING_HOST="$HOST"
export HTML_LEARNING_PORT="$PORT"
export HTML_LEARNING_ROOT_PASSWORD="$ROOT_PASSWORD"
export HTML_LEARNING_MANAGER_PASSWORD="$MANAGER_PASSWORD"
export HTML_LEARNING_TEST_PASSWORD="$TEST_PASSWORD"
export HACKME_DEV_FEATURE_MODE="$FEATURE_MODE"
export HACKME_DEV_FEATURES="$FEATURE_LIST"
export HACKME_DEV_IN_PLACE="$IN_PLACE"
export HACKME_DEV_TOKEN_FEATURES="$DEV_TOKEN_FEATURES"
export HACKME_DEV_TOKEN_TTL_MINUTES="$DEV_TOKEN_TTL_MINUTES"
export HACKME_DEV_INTERNAL_TEST_TOKEN_FEATURES="$DEV_TOKEN_FEATURES"
export HACKME_DEV_TOKENS_FILE="$RUNTIME_ROOT/dev_tokens.json"
export HACKME_DEV_SECURITY_ENABLED="$SECURITY_SETTINGS_ENABLED"
export HACKME_DEV_SERVER_MODE="$SERVER_MODE"
export HACKME_DEV_EXTRA_ACCOUNTS="$EXTRA_ACCOUNTS"
export HACKME_DEV_BTC_TRADE_AUTOSTART="$BTC_TRADE_AUTOSTART"
export HACKME_DEV_BACKTEST_PROBE_ON_STARTUP="$BACKTEST_PROBE_ON_STARTUP"
export HTML_LEARNING_TRADING_BACKTEST_PROBE_ON_STARTUP="$BACKTEST_PROBE_ON_STARTUP"
export HACKME_DEV_DEFAULT_ACCOUNT_PASSWORDS="$DEFAULT_ACCOUNT_PASSWORDS"
if [[ "$SECURITY_SETTINGS_ENABLED" == "1" ]]; then
  export HTML_LEARNING_DISABLE_DEFAULT_PASSWORD_POLICY=0
else
  export HTML_LEARNING_DISABLE_DEFAULT_PASSWORD_POLICY=1
fi
export HACKME_DEV_TRADING_ALLOW_CONSERVATIVE_MARKET_ORDERS=1
export HACKME_DEV_TRADING_ALLOW_UNREADY_MARKETS=1
export HACKME_DEV_TRADING_DISABLE_PRICE_CONFIDENCE_GATES=1
export HACKME_DEV_TRADING_ALLOW_QA_LIVE_PRICE_PROVIDER=1
if [[ -z "${HTML_LEARNING_GIT_REPO_DIR:-}" ]]; then
  if git -C "$DEFAULT_GIT_REPO_DIR" rev-parse HEAD >/dev/null 2>&1; then
    export HTML_LEARNING_GIT_REPO_DIR="$DEFAULT_GIT_REPO_DIR"
  else
    export HTML_LEARNING_GIT_REPO_DIR="$COPY_ROOT"
  fi
fi
export PYTHONPATH="$COPY_ROOT"
export PYTHONPYCACHEPREFIX="$RUNTIME_ROOT/pycache"

cd "$COPY_ROOT"

HACKME_RUNTIME_OUTPUT_CAPTURE=0 "$PYTHON_BIN" - <<'PY'
from datetime import datetime, timedelta
import json
import os
import server
from services.security.access_controls import (
    generate_internal_test_token,
    hash_internal_test_token,
    maintenance_bypass_expires_at,
)

server.init_db(
    ensure_secure_audit_columns=server.ensure_secure_audit_columns,
    ensure_user_columns=server.ensure_user_columns,
    ensure_appeal_columns=server.ensure_appeal_columns,
    ensure_session_columns=server.ensure_session_columns,
    ensure_security_support_schema=server.ensure_security_support_schema,
    ensure_points_economy_schema=server.ensure_points_economy_schema,
    ensure_official_chat_room=server.ensure_official_chat_room,
    hash_password=server.hash_password,
)

feature_keys = [
    key
    for key in server.DEFAULT_SETTINGS
    if key.startswith("feature_")
]
feature_mode = os.environ.get("HACKME_DEV_FEATURE_MODE", "all").strip().lower()
raw_feature_list = os.environ.get("HACKME_DEV_FEATURES", "")
security_enabled = str(os.environ.get("HACKME_DEV_SECURITY_ENABLED", "0")).strip().lower() in {"1", "true", "yes", "on", "enabled"}
default_account_passwords = str(os.environ.get("HACKME_DEV_DEFAULT_ACCOUNT_PASSWORDS", "0")).strip().lower() in {"1", "true", "yes", "on", "enabled"}
default_account_must_change = 1 if security_enabled and default_account_passwords else 0


def normalize_feature_key(value):
    value = value.strip()
    if not value:
        return ""
    if not value.startswith("feature_"):
        value = f"feature_{value}"
    return value


def normalize_token_feature_scope(raw_value):
    raw_value = str(raw_value or "").strip()
    if not raw_value or raw_value.lower() in {"all", "*", "unrestricted", "none"}:
        return []
    allowed = []
    unknown = []
    feature_key_set = set(feature_keys)
    for item in raw_value.replace("\n", ",").split(","):
        key = item.strip()
        if not key:
            continue
        if not key.startswith("feature_"):
            key = f"feature_{key}"
        if key not in feature_key_set and not key.endswith("_enabled"):
            maybe_enabled = f"{key}_enabled"
            if maybe_enabled in feature_key_set:
                key = maybe_enabled
        if key not in feature_key_set:
            unknown.append(key)
            continue
        if key not in allowed:
            allowed.append(key)
    if unknown:
        raise SystemExit(f"unknown dev token feature scope: {', '.join(unknown)}")
    return allowed


def dev_token_ttl_minutes():
    try:
        ttl = int(str(os.environ.get("HACKME_DEV_TOKEN_TTL_MINUTES", "1440")).strip())
    except Exception:
        ttl = 1440
    return max(5, min(ttl, 30 * 24 * 60))


selected_features = {
    key
    for key in (normalize_feature_key(item) for item in raw_feature_list.split(","))
    if key
}
if feature_mode == "defaults":
    feature_updates = {}
elif feature_mode == "custom":
    feature_updates = {
        key: key in selected_features
        for key in feature_keys
    }
else:
    feature_updates = {
        key: True
        for key in feature_keys
    }
feature_updates["feature_account_security_enabled"] = bool(security_enabled)
relaxed_security_settings = {
    "allow_register": True,
    "audit_chain_enabled": False,
    "audit_chain_reseal_required": False,
    "browser_only_mode_enabled": False,
    "captcha_mode": "none",
    "force_https": False,
    "integrity_guard_enabled": False,
    "integrity_guard_strict_mode": False,
    "ip_blocking_enabled": False,
    "login_violation_enabled": False,
    "max_login_failures": 999999,
    "production_single_account_ip_lock_enabled": False,
    "production_single_ip_account_lock_enabled": False,
    "rate_limit_violation_enabled": False,
    "require_email_verification": False,
    "root_ip_whitelist_enabled": False,
    "server_ssl_enabled": True,
    "session_idle_timeout_minutes": 1440,
    "session_ttl_hours": 168,
}
enabled_security_settings = {
    "allow_register": True,
    "audit_chain_enabled": True,
    "audit_chain_reseal_required": False,
    "browser_only_mode_enabled": False,
    "captcha_mode": "math",
    "force_https": False,
    "integrity_guard_enabled": True,
    "integrity_guard_strict_mode": False,
    "ip_blocking_enabled": True,
    "login_violation_enabled": True,
    "max_login_failures": 8,
    "production_single_account_ip_lock_enabled": False,
    "production_single_ip_account_lock_enabled": False,
    "rate_limit_violation_enabled": True,
    "require_email_verification": False,
    "root_ip_whitelist_enabled": False,
    "server_ssl_enabled": True,
    "session_idle_timeout_minutes": 60,
    "session_ttl_hours": 24,
}
feature_updates.update(enabled_security_settings if security_enabled else relaxed_security_settings)
feature_updates.update({
    # Dev default: assume root has the Windows-portable ComfyUI bundle
    # mounted under WSL at /mnt/d/share/ComfyUI_windows_portable and uses
    # run_in_linux.sh as the entrypoint. Switch to local mode so the dev
    # runtime calls the locally-launched ComfyUI on 127.0.0.1 by default.
    "comfyui_connection_mode": "local",
    "comfyui_base_dir": "/mnt/d/share/ComfyUI_windows_portable",
    "comfyui_local_start_script": "run_in_linux.sh",
})
server.save_settings(feature_updates)


def parse_extra_accounts(raw_value):
    accounts = []
    for spec in (raw_value or "").split(","):
        spec = spec.strip()
        if not spec:
            continue
        parts = spec.split(":", 2)
        if len(parts) < 2 or not parts[0].strip() or not parts[1]:
            raise SystemExit(f"invalid extra account spec: {spec!r}; expected username:password[:role]")
        role = parts[2].strip() if len(parts) >= 3 and parts[2].strip() else "user"
        if role not in {"user", "manager", "super_admin"}:
            raise SystemExit(f"invalid role for extra account {parts[0]!r}: {role}")
        accounts.append((parts[0].strip(), parts[1], role))
    return accounts


def ensure_extra_account(conn, username, password, role, now):
    member_level = "trusted" if role == "user" else "normal"
    row = conn.execute("SELECT id FROM users WHERE username=?", (username,)).fetchone()
    if row:
        user_id = row["id"]
        conn.execute(
            """
            UPDATE users
            SET status='active',
                role=?,
                must_change_password=0,
                is_default_password=0,
                failed_login_count=0,
                locked_until=NULL,
                blocked_until=NULL,
                member_level=?,
                base_level=?,
                effective_level=?,
                updated_at=?
            WHERE id=?
            """,
            (role, member_level, member_level, member_level, now, user_id),
        )
    else:
        cur = conn.execute(
            """
            INSERT INTO users
                (username, status, role, member_level, base_level, effective_level, created_at, updated_at)
            VALUES
                (?, 'active', ?, ?, ?, ?, ?, ?)
            """,
            (username, role, member_level, member_level, member_level, now, now),
        )
        user_id = cur.lastrowid
    conn.execute(
        "INSERT INTO user_passwords (user_id, password_hash, created_at) VALUES (?, ?, ?)",
        (user_id, server.hash_password(password), now),
    )


conn = server.get_db()
try:
    server.ensure_trading_schema(conn)
    now = datetime.now().isoformat()
    selected_server_mode = os.environ.get("HACKME_DEV_SERVER_MODE", "dev_ready").strip() or "dev_ready"
    def apply_selected_server_mode(mode_conn):
        changed = mode_conn.execute(
            """
            UPDATE server_modes
            SET previous_mode=CASE WHEN current_mode<>? THEN current_mode ELSE previous_mode END,
                current_mode=?,
                mode_changed_at=?,
                notes=?,
                reason=?,
                config_json=?
            WHERE id=1
            """,
            (
                selected_server_mode,
                selected_server_mode,
                now,
                "test_for_develop.sh",
                "dev runtime bootstrap",
                json.dumps(
                    {
                        "source": "test_for_develop.sh",
                        "security_enabled": security_enabled,
                    },
                    ensure_ascii=True,
                    sort_keys=True,
                ),
            ),
        ).rowcount
        if not changed:
            mode_conn.execute(
                """
                INSERT INTO server_modes
                    (id, current_mode, previous_mode, active_snapshot_id, checkpoint_id,
                     mode_changed_by, mode_changed_at, notes, reason, config_json)
                VALUES
                    (1, ?, NULL, NULL, NULL, NULL, ?, ?, ?, ?)
                """,
                (
                    selected_server_mode,
                    now,
                    "test_for_develop.sh",
                    "dev runtime bootstrap",
                    json.dumps({"source": "test_for_develop.sh", "security_enabled": security_enabled}, ensure_ascii=True, sort_keys=True),
                ),
            )
    try:
        apply_selected_server_mode(conn)
        control_conn = server.get_control_db()
        try:
            apply_selected_server_mode(control_conn)
            control_conn.commit()
        finally:
            control_conn.close()
    except Exception:
        pass
    conn.execute("DELETE FROM ip_blocks")
    conn.execute("DELETE FROM security_events")
    conn.execute("DELETE FROM notifications WHERE type='root_security_alert'")
    conn.execute("UPDATE sessions SET is_revoked=1, revoked_at=?", (now,))
    conn.execute(
        """
        UPDATE users
        SET must_change_password=?,
            is_default_password=?,
            failed_login_count=0,
            locked_until=NULL,
            blocked_until=NULL,
            updated_at=?
        WHERE username IN ('root', 'admin', 'test')
        """,
        (default_account_must_change, default_account_must_change, now),
    )
    for username, password, role in parse_extra_accounts(os.environ.get("HACKME_DEV_EXTRA_ACCOUNTS", "")):
        ensure_extra_account(conn, username, password, role, now)
    conn.execute(
        """
        UPDATE trading_markets_registry
        SET enabled=1,
            allow_spot=1,
            allow_margin=1,
            allow_bots=1,
            allow_risk_grade_usage=1,
            live_price_enabled=1,
            reference_price_enabled=1,
            updated_at=?
        """,
        (now,),
    )
    conn.execute(
        """
        UPDATE trading_markets
        SET enabled=1,
            allow_margin=1,
            allow_bots=1,
            allow_risk_grade_usage=1,
            live_price_enabled=1,
            reference_price_enabled=1,
            updated_at=?
        """,
        (now,),
    )
    for key, value in (
        ("trading.enabled", "true"),
        ("trading.borrowing_enabled", "true"),
        ("trading.margin_liquidation_enabled", "false"),
        ("trading.bot_auto_scan_enabled", "false"),
        ("trading.bot_audit_enabled", "false"),
        ("trading.price_degrade_pause_market_orders", "false"),
        ("trading.price_degrade_pause_bots", "false"),
        ("trading.price_degrade_pause_borrowing", "false"),
        ("trading.allow_unready_markets", "true"),
        ("trading.disable_price_confidence_gates", "true"),
        ("trading.dev_allow_conservative_market_orders", "true"),
        ("trading.dev_allow_unready_markets", "true"),
        ("trading.dev_disable_price_confidence_gates", "true"),
        ("trading.warning_language", "zh-TW"),
        ("trading.simulated_slippage_enabled", "false"),
        ("trading.simulated_slippage_base_basis_points", "0"),
        ("trading.simulated_slippage_size_basis_points_per_10k_notional", "0"),
        ("trading.simulated_slippage_max_basis_points", "0"),
        # Dev default: pin price fusion to Binance public API only so the
        # /tmp dev runtime does not require OKX/Coinbase/Kraken/Gemini/Bitstamp
        # reachability for spot trading, live-price, or risk-grade gating.
        ("trading.price_fusion_mode", "manual_weights"),
        (
            "trading.price_fusion_manual_weights_json",
            '{"binance_public_api": 100.0, "okx_public_api": 0.0, '
            '"coinbase_exchange": 0.0, "kraken_public_api": 0.0, '
            '"gemini_public_api": 0.0, "bitstamp_public_api": 0.0}',
        ),
        ("trading.price_fusion_min_provider_count", "1"),
        ("trading.price_fusion_trade_min_provider_count", "1"),
        # Lift the single-provider cap to 100% so dev runtime can run on
        # Binance alone without the provider_weight_cap_unenforceable warning.
        ("trading.price_fusion_max_single_provider_weight_percent", "100"),
        # Dev default: pin BTC_trade prediction engine on, parked at the
        # shared /tmp/BTC_trade workspace so multiple dev runs reuse the same
        # cloned repo, downloaded data and trained models. The signal pipeline
        # itself (clone → install → predict → retrain) is kicked off in the
        # background after the server URL becomes available; see the autostart
        # block further down.
        ("trading.btc_trade_enabled", "true"),
        ("trading.btc_trade_project_dir", "/tmp/BTC_trade"),
    ):
        conn.execute(
            "INSERT OR REPLACE INTO trading_settings (key, value, updated_at, updated_by) VALUES (?, ?, ?, ?)",
            (key, value, now, "test_for_develop"),
        )
    conn.commit()
finally:
    conn.close()

dev_tokens_path = os.environ.get("HACKME_DEV_TOKENS_FILE", "").strip()
dev_tokens_payload = {
    "ok": True,
    "server_mode": selected_server_mode,
    "tokens": {},
    "warnings": [],
}
if selected_server_mode in {"test", "internal_test"} and dev_tokens_path:
    ttl_minutes = dev_token_ttl_minutes()
    token_features = normalize_token_feature_scope(os.environ.get("HACKME_DEV_TOKEN_FEATURES", ""))
    token_user = None
    conn = server.get_db()
    try:
        token_user = conn.execute(
            "SELECT id, username FROM users WHERE username='test' LIMIT 1"
        ).fetchone()
    finally:
        conn.close()
    if token_user:
        user_id = int(token_user["id"])
        username = str(token_user["username"] or "test")
        if selected_server_mode == "internal_test":
            login_token = generate_internal_test_token()
            login_expires_at = maintenance_bypass_expires_at(ttl_minutes)
            server.save_settings({
                "internal_test_login_token_hash": hash_internal_test_token(login_token),
                "internal_test_login_token_expires_at": login_expires_at,
                "internal_test_login_token_user_id": user_id,
                "internal_test_login_token_username": username,
                "internal_test_login_token_allowed_features_json": json.dumps(token_features, ensure_ascii=True, sort_keys=True),
            })
            dev_tokens_payload["tokens"]["internal_test_login_token"] = {
                "token": login_token,
                "target_user_id": user_id,
                "target_username": username,
                "expires_at": login_expires_at,
                "ttl_minutes": ttl_minutes,
                "allowed_features": token_features,
                "usage": "login as the bound test user in internal_test mode via internal_test_token/login_token/X-Internal-Test-Token",
            }
        if hasattr(server, "server_mode_service"):
            tester_expires_at = (datetime.now() + timedelta(minutes=ttl_minutes)).replace(microsecond=0).isoformat()
            tester_result = server.server_mode_service.create_tester_token(
                actor={"id": 1, "username": "root", "role": "super_admin"},
                tester_user_id=user_id,
                allowed_features=token_features,
                allowed_routes=[],
                expires_at=tester_expires_at,
                max_requests_per_minute=120,
                can_modify_own_role=False,
                can_modify_own_points=False,
                can_run_security_tests=False,
            )
            if tester_result.get("ok"):
                dev_tokens_payload["tokens"]["tester_token"] = {
                    "token": tester_result.get("token"),
                    "token_id": tester_result.get("token_id"),
                    "user_id": user_id,
                    "username": username,
                    "expires_at": tester_result.get("expires_at") or tester_expires_at,
                    "ttl_minutes": ttl_minutes,
                    "allowed_features": token_features,
                    "usage": "X-Tester-Token for test/internal_test scoped API probes",
                }
            else:
                dev_tokens_payload["warnings"].append(f"tester token generation failed: {tester_result.get('msg') or tester_result}")
    else:
        dev_tokens_payload["warnings"].append("test user was not found; no dev token generated")
    os.makedirs(os.path.dirname(dev_tokens_path) or ".", exist_ok=True)
    tmp_path = f"{dev_tokens_path}.tmp"
    with open(tmp_path, "w", encoding="utf-8") as fh:
        json.dump(dev_tokens_payload, fh, ensure_ascii=False, indent=2, sort_keys=True)
        fh.write("\n")
    try:
        os.chmod(tmp_path, 0o600)
    except Exception:
        pass
    os.replace(tmp_path, dev_tokens_path)
PY

if [[ "$FOREGROUND" == "1" ]]; then
  if [[ "$IN_PLACE" == "1" ]]; then
    say "[dev-tmp] source:    $COPY_ROOT (in-place, no copy)"
  else
    say "[dev-tmp] repo copy: $COPY_ROOT"
  fi
  say "[dev-tmp] runtime:   $RUNTIME_ROOT"
  say "[dev-tmp] mode:      foreground server.py"
  print_generated_dev_tokens
  exec "$PYTHON_BIN" server.py
fi

setsid "$PYTHON_BIN" server.py >"$LOG_CAPTURE" 2>&1 < /dev/null &
SERVER_PID="$!"
printf '%s\n' "$SERVER_PID" > "$PID_FILE"

SERVER_URL="$(wait_for_server_url || true)"

if [[ "$IN_PLACE" == "1" ]]; then
  say "[dev-tmp] source:    $COPY_ROOT (in-place, no copy)"
else
  say "[dev-tmp] repo copy: $COPY_ROOT"
fi
say "[dev-tmp] runtime:   $RUNTIME_ROOT"
say "[dev-tmp] pid:       $SERVER_PID"
if [[ -n "$SERVER_URL" ]]; then
  say "[dev-tmp] url:       $SERVER_URL"
else
  say "[dev-tmp] url:       startup pending; inspect logs"
fi
say "[dev-tmp] accounts:   root/${ROOT_PASSWORD} admin/${MANAGER_PASSWORD} test/${TEST_PASSWORD}"
say "[dev-tmp] log:       $LOG_CAPTURE"
print_generated_dev_tokens

# BTC_trade autostart: kick the prediction pipeline off in the background
# so the trading dashboard already has live BTC_trade signal data on first
# page load. The server-side job uses setup_if_needed=True, so:
#   - first run: clones BTC_trade into /tmp/BTC_trade, installs deps,
#     trains the model, then predicts.
#   - re-run when /tmp/BTC_trade already has the required scripts: skips
#     clone/install and goes straight to update_data → retrain → predict.
# This is intentionally fire-and-forget so test_for_develop.sh exits fast.
if [[ -n "$SERVER_URL" && "$BTC_TRADE_AUTOSTART" == "1" ]]; then
  BTC_LOG="$RUNTIME_ROOT/logs/btc_trade_autostart.log"
  (
    set +e
    sleep 2
    JAR="$(mktemp)"
    LOGIN_BODY="$("$PYTHON_BIN" -c 'import json,os; print(json.dumps({"username":"root","password":os.environ["HTML_LEARNING_ROOT_PASSWORD"]}))')"
    csrf="$(curl -ksS -c "$JAR" "$SERVER_URL/api/csrf-token" | "$PYTHON_BIN" -c 'import json,sys;print(json.load(sys.stdin).get("csrf_token",""))')"
    curl -ksS -c "$JAR" -b "$JAR" \
      -H "Content-Type: application/json" -H "X-CSRF-Token: $csrf" \
      -X POST "$SERVER_URL/api/login" -d "$LOGIN_BODY" >/dev/null
    csrf="$(curl -ksS -c "$JAR" -b "$JAR" "$SERVER_URL/api/csrf-token" | "$PYTHON_BIN" -c 'import json,sys;print(json.load(sys.stdin).get("csrf_token",""))')"
    echo "[btc_trade_autostart] POST /api/root/trading/btc-trade/start"
    curl -ksS -b "$JAR" \
      -H "Content-Type: application/json" -H "X-CSRF-Token: $csrf" \
      -X POST "$SERVER_URL/api/root/trading/btc-trade/start" \
      -d '{"timeframe":"4h"}'
    echo
    rm -f "$JAR"
  ) > "$BTC_LOG" 2>&1 &
  say "[dev-tmp] btc_trade: autostart kicked off in background (log: $BTC_LOG)"
elif [[ -n "$SERVER_URL" ]]; then
  say "[dev-tmp] btc_trade: autostart disabled"
fi
