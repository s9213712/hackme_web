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
RUNTIME_IN_SOURCE="${HACKME_DEV_RUNTIME_IN_SOURCE:-${HACKME_DEV_DEPLOY_IN_PLACE:-0}}"
ROOT_PASSWORD="${ROOT_PASSWORD:-root}"
MANAGER_PASSWORD="${MANAGER_PASSWORD:-admin}"
TEST_PASSWORD="${TEST_PASSWORD:-test}"
PYTHON_BIN="${PYTHON_BIN:-python3}"
FEATURE_MODE="${HACKME_DEV_FEATURE_MODE:-all}"
FEATURE_LIST="${HACKME_DEV_FEATURES:-}"
FEATURE_BUNDLES="${HACKME_DEV_FEATURE_BUNDLES:-${HACKME_DEV_FEATURE_PACKAGES:-}}"
DEV_TOKEN_FEATURES="${HACKME_DEV_TOKEN_FEATURES:-${HACKME_DEV_INTERNAL_TEST_TOKEN_FEATURES:-}}"
DEV_TOKEN_TTL_MINUTES="${HACKME_DEV_TOKEN_TTL_MINUTES:-1440}"
DEV_TOKEN_USER="${HACKME_DEV_TOKEN_USER:-test}"
DEV_TOKEN_PASSWORD="${HACKME_DEV_TOKEN_PASSWORD:-}"
DEV_TOKEN_ROLE="${HACKME_DEV_TOKEN_ROLE:-user}"
FEATURE_MODE_SET=0
SECURITY_SETTINGS_ENABLED="${HACKME_DEV_SECURITY_ENABLED:-0}"
SERVER_MODE="${HACKME_DEV_SERVER_MODE:-dev_ready}"
EXTRA_ACCOUNTS="${HACKME_DEV_EXTRA_ACCOUNTS:-}"
PORT_CONFLICT_ACTION="${HACKME_DEV_PORT_CONFLICT_ACTION:-}"
BTC_TRADE_AUTOSTART="${HACKME_DEV_BTC_TRADE_AUTOSTART:-0}"
BACKTEST_PROBE_ON_STARTUP="${HACKME_DEV_BACKTEST_PROBE_ON_STARTUP:-0}"
SERVER_RUNNER="${HACKME_DEV_SERVER_RUNNER:-gunicorn}"
GUNICORN_WORKERS="${HACKME_DEV_GUNICORN_WORKERS:-auto}"
GUNICORN_THREADS="${HACKME_DEV_GUNICORN_THREADS:-auto}"
GUNICORN_TIMEOUT="${HACKME_DEV_GUNICORN_TIMEOUT:-20}"
GUNICORN_GRACEFUL_TIMEOUT="${HACKME_DEV_GUNICORN_GRACEFUL_TIMEOUT:-10}"
GUNICORN_KEEP_ALIVE="${HACKME_DEV_GUNICORN_KEEP_ALIVE:-2}"
GUNICORN_BACKLOG="${HACKME_DEV_GUNICORN_BACKLOG:-64}"
GUNICORN_MAX_REQUESTS="${HACKME_DEV_GUNICORN_MAX_REQUESTS:-1000}"
GUNICORN_MAX_REQUESTS_JITTER="${HACKME_DEV_GUNICORN_MAX_REQUESTS_JITTER:-200}"
DRY_RUN=0

usage() {
  cat <<'USAGE'
Usage:
  ./test_for_develop.sh [options]

Purpose:
  Copy the repo to /tmp by default, initialize a development-friendly runtime,
  and launch server.py from the copied workspace so the repo never accumulates
  runtime or cache pollution. Pass --in-place / --no-copy when you explicitly
  want to launch from the current repo without copying source files while still
  keeping runtime under --run-root. Pass --runtime-in-source / --deploy-in-place
  when you intentionally want the current repo to own ./runtime directly.

Important:
  Without --cli, the script asks for workspace, host, port, server runner,
  feature mode, security posture, server mode, dependency handling, foreground
  mode, BTC_trade autostart, account password settings, and extra accounts.
  With --cli, it never prompts and only uses command-line/env values.

  For server-mode / production-gate validation, HTML_LEARNING_GIT_REPO_DIR must
  point at a real git repo with a readable .git directory. Do not point it at
  the /tmp copied workspace unless that copy still preserves git metadata.

Options:
  --cli                    Run non-interactively from command/env options
  --host HOST              Default: 127.0.0.1
  --port PORT              Default: 5000; prompts if occupied in interactive mode
  --feature-mode MODE      all, defaults, bundles, or custom. Default: all
  --feature-bundles LIST   Comma-separated feature package names such as
                           core-admin,social,storage,media,trading,ai.
  --features LIST          Comma-separated feature_* keys or package names for
                           custom mode. Required/recommended dependencies are
                           expanded automatically.
  --token-features LIST    Comma-separated feature_* keys, short feature names,
                           or interactive list numbers allowed by generated
                           test/internal-test dev tokens. Empty/0 means no extra
                           token-level feature restriction.
  --internal-test-token-features LIST
                           Comma-separated feature_* keys allowed by the
                           generated internal-test login token. Alias of
                           --token-features.
  --token-ttl-minutes N    TTL for generated test/internal-test tokens.
                           Default: 1440
  --token-user USERNAME    Account bound to generated test/internal-test tokens.
                           Default: test
  --token-password VALUE   Password to set when creating/updating --token-user.
                           Blank keeps existing users unchanged and auto-generates
                           a password only when the token user does not exist.
  --token-role ROLE        Role for a newly created/updated token account.
                           user, manager, or super_admin. Default: user
  --security VALUE         on/off. Default: off for dev-friendly runtime
  --server-mode MODE       dev_ready, internal_test, test, preprod, production,
                           superweak, maintenance, or incident_lockdown
  --add-account SPEC       Add dev account as username:password[:role]; repeatable
  --accounts LIST          Comma-separated --add-account specs
  --port-conflict ACTION   ask, kill, fallback, or fail. Default: ask interactively,
                           fallback under --cli. kill falls back to another port
                           if the process cannot be terminated or the port stays busy
  --btc-trade-autostart    Start BTC_trade in the background after boot
  --no-btc-trade-autostart Do not start BTC_trade in the background
  --backtest-probe-on-startup
                           Run the first-boot trading backtest capacity probe
                           in this temporary runtime
  --server-runner RUNNER    flask or gunicorn. Default: gunicorn
  --gunicorn-workers N      Default: auto when --server-runner gunicorn
  --gunicorn-threads N      Default: auto when --server-runner gunicorn
  --gunicorn-timeout N      Default: 20 seconds
  --gunicorn-backlog N      Default: 64
  --dry-run                Print resolved config and exit before copying/starting
  --run-root PATH          Use a fixed /tmp run root instead of auto-generating one
  --in-place, --no-copy    Launch from the current repo; runtime still uses run-root
  --runtime-in-source,
  --source-runtime,
  --deploy-in-place        Launch from the current repo and write runtime/ there.
                           This is the local deployment layout, not isolated QA.
  --tmp-runtime            With --in-place, keep runtime under --run-root
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
    all|defaults|bundles|custom)
      ;;
    default)
      FEATURE_MODE="defaults"
      ;;
    bundle|package|packages|preset|presets)
      FEATURE_MODE="bundles"
      ;;
    *)
      die "feature mode must be all, defaults, bundles, or custom: $FEATURE_MODE"
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

normalize_server_runner() {
  SERVER_RUNNER="${SERVER_RUNNER,,}"
  case "$SERVER_RUNNER" in
    flask|werkzeug)
      SERVER_RUNNER="flask"
      ;;
    gunicorn|wsgi)
      SERVER_RUNNER="gunicorn"
      ;;
    *)
      die "server runner must be flask or gunicorn: $SERVER_RUNNER"
      ;;
  esac
}

resolve_auto_gunicorn_settings() {
  if [[ "$SERVER_RUNNER" != "gunicorn" ]]; then
    return 0
  fi
  if [[ "${GUNICORN_WORKERS,,}" != "auto" && "${GUNICORN_THREADS,,}" != "auto" ]]; then
    return 0
  fi
  local resolved
  resolved="$(python3 - "$GUNICORN_WORKERS" "$GUNICORN_THREADS" <<'PY'
import os
import sys

raw_workers = str(sys.argv[1] or "auto").strip().lower()
raw_threads = str(sys.argv[2] or "auto").strip().lower()
cpu = max(1, os.cpu_count() or 1)
try:
    mem_mb = int(os.sysconf("SC_PHYS_PAGES") * os.sysconf("SC_PAGE_SIZE") / (1024 * 1024))
except Exception:
    mem_mb = 0

def auto_workers():
    if cpu <= 2 or (mem_mb and mem_mb < 2048):
        return 1
    if cpu >= 16 and (not mem_mb or mem_mb >= 16384):
        return 3
    return 2

def auto_threads():
    if mem_mb and mem_mb < 2048:
        return 6
    if cpu <= 2 or (mem_mb and mem_mb < 4096):
        return 8
    if cpu <= 4:
        return 10
    if cpu >= 8 and (not mem_mb or mem_mb >= 16384):
        return 16
    return 12

workers = auto_workers() if raw_workers in {"", "auto", "dynamic"} else int(raw_workers)
threads = auto_threads() if raw_threads in {"", "auto", "dynamic"} else int(raw_threads)
workers = max(1, min(8, workers))
threads = max(2, min(64, threads))
print(f"{workers} {threads}")
PY
)"
  GUNICORN_WORKERS="${resolved%% *}"
  GUNICORN_THREADS="${resolved##* }"
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
  if [[ "$FEATURE_MODE" == "bundles" ]]; then
    [[ -n "$FEATURE_BUNDLES" ]] || die "feature mode bundles requires --feature-bundles or an interactive bundle selection"
    normalize_feature_or_bundle_selection "$FEATURE_BUNDLES" "bundle" || die "invalid feature bundle selection: $FEATURE_BUNDLES"
    FEATURE_LIST="$NORMALIZED_FEATURE_SELECTION"
  elif [[ "$FEATURE_MODE" == "custom" ]]; then
    normalize_feature_or_bundle_selection "$FEATURE_LIST" || die "invalid feature selection: $FEATURE_LIST"
    FEATURE_LIST="$NORMALIZED_FEATURE_SELECTION"
  fi
  normalize_server_mode
  normalize_token_feature_selection "$DEV_TOKEN_FEATURES" || die "invalid generated dev token feature selection: $DEV_TOKEN_FEATURES"
  DEV_TOKEN_FEATURES="$NORMALIZED_DEV_TOKEN_FEATURES"
  normalize_server_runner
  resolve_auto_gunicorn_settings
  normalize_port_conflict_action
  normalize_yes_no_value "$IN_PLACE" "in-place"
  IN_PLACE="$NORMALIZED_YES_NO"
  normalize_yes_no_value "$RUNTIME_IN_SOURCE" "runtime in source"
  RUNTIME_IN_SOURCE="$NORMALIZED_YES_NO"
  if [[ "$RUNTIME_IN_SOURCE" == "1" ]]; then
    IN_PLACE=1
  fi
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
  if [[ "$RUNTIME_IN_SOURCE" == "1" ]]; then
    say "  run_root:            <not used; source runtime>"
    say "  launch_mode:         source runtime deployment"
    say "  runtime_root:        $SOURCE_ROOT/runtime"
  elif [[ "$IN_PLACE" == "1" ]]; then
    say "  run_root:            ${RUN_ROOT:-/tmp/hackme_web_dev_${RUN_ID}_$$}"
    say "  launch_mode:         in-place (no source copy; tmp runtime)"
    say "  runtime_root:        ${RUN_ROOT:-/tmp/hackme_web_dev_${RUN_ID}_$$}/runtime"
  else
    say "  run_root:            ${RUN_ROOT:-/tmp/hackme_web_dev_${RUN_ID}_$$}"
    say "  launch_mode:         tmp copy"
    say "  runtime_root:        ${RUN_ROOT:-/tmp/hackme_web_dev_${RUN_ID}_$$}/hackme_web/runtime"
  fi
  say "  host:                $HOST"
  say "  port:                $PORT"
  say "  feature_mode:        $FEATURE_MODE"
  if [[ "$FEATURE_MODE" == "bundles" ]]; then
    say "  feature_bundles:     ${FEATURE_BUNDLES:-<none>}"
  fi
  say "  features:            ${FEATURE_LIST:-<none>}"
  say "  token_features:      ${DEV_TOKEN_FEATURES:-<unrestricted>}"
  say "  token_ttl_minutes:   $DEV_TOKEN_TTL_MINUTES"
  say "  token_user:          $DEV_TOKEN_USER"
  say "  token_role:          $DEV_TOKEN_ROLE"
  if [[ -n "$DEV_TOKEN_PASSWORD" ]]; then
    say "  token_password:      <configured>"
  else
    say "  token_password:      <keep existing / auto-generate for new user>"
  fi
  say "  security_enabled:    $SECURITY_SETTINGS_ENABLED"
  say "  server_mode:         $SERVER_MODE"
  say "  server_runner:       $SERVER_RUNNER"
  if [[ "$SERVER_RUNNER" == "gunicorn" ]]; then
    say "  gunicorn:            workers=$GUNICORN_WORKERS threads=$GUNICORN_THREADS timeout=$GUNICORN_TIMEOUT backlog=$GUNICORN_BACKLOG"
  fi
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
    bundles)
      default_choice="3"
      ;;
    custom)
      default_choice="4"
      ;;
  esac

  say "Feature mode:"
  say "  1) all      Enable every server DEFAULT_SETTINGS feature_* flag"
  say "  2) defaults Keep server feature defaults"
  say "  3) bundles  Enable feature packages with dependencies already grouped"
  say "  4) custom   Advanced: enter package names and/or feature_* keys"
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
        FEATURE_BUNDLES=""
        return 0
        ;;
      3|bundle|bundles|package|packages|preset|presets)
        FEATURE_MODE="bundles"
        prompt_feature_bundle_scope
        return 0
        ;;
      4|custom)
        FEATURE_MODE="custom"
        print_known_feature_bundles
        print_known_feature_keys
        prompt_value "Enabled feature packages / keys, comma-separated" "$FEATURE_LIST" FEATURE_LIST
        return 0
        ;;
      *)
        say "Please choose 1, 2, 3, or 4."
        ;;
    esac
  done
}

print_known_feature_bundles() {
  PYTHONPATH="$SOURCE_ROOT" python3 - <<'PY' 2>/dev/null || true
try:
    from services.platform.settings import FEATURE_FLAG_KEYS
except Exception:
    raise SystemExit(0)

feature_keys = set(FEATURE_FLAG_KEYS)
bundles = [
    ("core-admin", "核心管理 / 健康 / audit", (
        "feature_accounts_enabled", "feature_audit_log_enabled", "feature_system_health_enabled",
        "feature_server_modes_enabled", "feature_snapshot_restore_enabled", "feature_health_center_enabled",
        "feature_reports_notifications_enabled",
    )),
    ("social", "聊天、討論區、附件、檢舉通知", (
        "feature_chat_enabled", "feature_community_enabled", "feature_attachments_enabled",
        "feature_reports_enabled", "feature_reports_notifications_enabled", "feature_social_search_enabled",
    )),
    ("storage", "雲端硬碟 / E2EE / 相簿", (
        "feature_privacy_uploads_enabled", "feature_storage_albums_enabled", "feature_attachments_enabled",
    )),
    ("media", "影音分享 / 上傳保存 / 打賞經濟", (
        "feature_videos_enabled", "feature_privacy_uploads_enabled", "feature_economy_enabled",
    )),
    ("games", "遊戲區 / 西洋棋", ("feature_games_enabled",)),
    ("ai", "ComfyUI AI 產圖 + 儲存分享", (
        "feature_comfyui_enabled", "feature_privacy_uploads_enabled",
    )),
    ("economy", "PointsChain 積分系統", ("feature_economy_enabled",)),
    ("trading", "積分交易所 + PointsChain", (
        "feature_trading_enabled", "feature_economy_enabled",
    )),
    ("moderation", "申訴、檢舉、違規治理", (
        "feature_accounts_enabled", "feature_appeals_enabled", "feature_reports_enabled",
        "feature_violation_center_enabled", "feature_reports_notifications_enabled",
        "feature_member_governance_enabled", "feature_identity_governance_enabled",
    )),
    ("personalization", "個人外觀與介面客製化", (
        "feature_personalization_enabled", "feature_ui_rebuild_enabled",
    )),
    ("full-user", "一般使用者完整體驗", (
        "feature_chat_enabled", "feature_community_enabled", "feature_privacy_uploads_enabled",
        "feature_storage_albums_enabled", "feature_videos_enabled", "feature_games_enabled",
        "feature_comfyui_enabled", "feature_economy_enabled", "feature_trading_enabled",
        "feature_personalization_enabled", "feature_social_search_enabled",
    )),
    ("qa-all", "QA / 找碴測試：所有 feature flags", tuple(FEATURE_FLAG_KEYS)),
]

print("Available feature packages:")
for index, (name, label, keys) in enumerate(bundles, 1):
    count = len([key for key in keys if key in feature_keys])
    print(f"  b{index:<2d}) {name}: {label} ({count} feature flags)")
PY
}

print_known_feature_keys() {
  PYTHONPATH="$SOURCE_ROOT" python3 - <<'PY' 2>/dev/null || true
try:
    from services.platform.settings import FEATURE_FLAG_KEYS
    from services.platform.settings_metadata import setting_detail
except Exception:
    raise SystemExit(0)

print("Available individual feature keys:")
for index, key in enumerate(FEATURE_FLAG_KEYS, 1):
    detail = setting_detail(key)
    label = str(detail.get("label") or key).strip()
    print(f"  f{index:<2d}) {key}: {label}")
PY
}

normalize_feature_or_bundle_selection() {
  local raw_value="$1"
  local number_mode="${2:-feature}"
  local normalized
  if ! normalized="$(PYTHONPATH="$SOURCE_ROOT" python3 - "$raw_value" "$number_mode" <<'PY'
import re
import sys

raw_value = str(sys.argv[1] or "").strip()
number_mode = str(sys.argv[2] or "feature").strip().lower()
try:
    from services.platform.settings import FEATURE_DEPENDENCY_RULES, FEATURE_FLAG_KEYS, normalize_feature_key
except Exception as exc:
    print(f"feature catalog unavailable: {exc}", file=sys.stderr)
    raise SystemExit(2)

feature_keys = list(FEATURE_FLAG_KEYS)
feature_key_set = set(feature_keys)
bundles = [
    ("core-admin", (
        "feature_accounts_enabled", "feature_audit_log_enabled", "feature_system_health_enabled",
        "feature_server_modes_enabled", "feature_snapshot_restore_enabled", "feature_health_center_enabled",
        "feature_reports_notifications_enabled",
    )),
    ("social", (
        "feature_chat_enabled", "feature_community_enabled", "feature_attachments_enabled",
        "feature_reports_enabled", "feature_reports_notifications_enabled", "feature_social_search_enabled",
    )),
    ("storage", (
        "feature_privacy_uploads_enabled", "feature_storage_albums_enabled", "feature_attachments_enabled",
    )),
    ("media", (
        "feature_videos_enabled", "feature_privacy_uploads_enabled", "feature_economy_enabled",
    )),
    ("games", ("feature_games_enabled",)),
    ("ai", ("feature_comfyui_enabled", "feature_privacy_uploads_enabled")),
    ("economy", ("feature_economy_enabled",)),
    ("trading", ("feature_trading_enabled", "feature_economy_enabled")),
    ("moderation", (
        "feature_accounts_enabled", "feature_appeals_enabled", "feature_reports_enabled",
        "feature_violation_center_enabled", "feature_reports_notifications_enabled",
        "feature_member_governance_enabled", "feature_identity_governance_enabled",
    )),
    ("personalization", ("feature_personalization_enabled", "feature_ui_rebuild_enabled")),
    ("full-user", (
        "feature_chat_enabled", "feature_community_enabled", "feature_privacy_uploads_enabled",
        "feature_storage_albums_enabled", "feature_videos_enabled", "feature_games_enabled",
        "feature_comfyui_enabled", "feature_economy_enabled", "feature_trading_enabled",
        "feature_personalization_enabled", "feature_social_search_enabled",
    )),
    ("qa-all", tuple(feature_keys)),
]
bundle_map = {name: tuple(key for key in keys if key in feature_key_set) for name, keys in bundles}
if not raw_value or raw_value.lower() in {"all", "*", "unrestricted", "none", "0"}:
    print("")
    raise SystemExit(0)

allowed = []
unknown = []
for item in re.split(r"[\s,，]+", raw_value):
    choice = item.strip()
    if not choice:
        continue
    lowered = choice.lower()
    if lowered in bundle_map:
        for key in bundle_map[lowered]:
            if key not in allowed:
                allowed.append(key)
        continue
    if lowered.startswith(("bundle:", "package:", "preset:")):
        bundle_name = lowered.split(":", 1)[1]
        if bundle_name in bundle_map:
            for key in bundle_map[bundle_name]:
                if key not in allowed:
                    allowed.append(key)
            continue
        unknown.append(choice)
        continue
    if lowered.startswith(("b", "p")) and lowered[1:].isdigit():
        index = int(lowered[1:])
        if 1 <= index <= len(bundles):
            for key in bundles[index - 1][1]:
                if key in feature_key_set and key not in allowed:
                    allowed.append(key)
            continue
        unknown.append(choice)
        continue
    if lowered.startswith("f") and lowered[1:].isdigit():
        index = int(lowered[1:])
        if 1 <= index <= len(feature_keys):
            key = feature_keys[index - 1]
        else:
            unknown.append(choice)
            continue
        if key not in allowed:
            allowed.append(key)
        continue
    if choice.isdigit():
        index = int(choice)
        if number_mode == "bundle" and 1 <= index <= len(bundles):
            for key in bundles[index - 1][1]:
                if key in feature_key_set and key not in allowed:
                    allowed.append(key)
            continue
        if 1 <= index <= len(feature_keys):
            key = feature_keys[index - 1]
        else:
            unknown.append(choice)
            continue
    else:
        key = normalize_feature_key(choice)
    if key not in feature_key_set:
        unknown.append(choice)
        continue
    if key not in allowed:
        allowed.append(key)

if unknown:
    print(f"unknown feature choice(s): {', '.join(unknown)}", file=sys.stderr)
    raise SystemExit(2)

changed = True
while changed:
    changed = False
    for key in list(allowed):
        rule = FEATURE_DEPENDENCY_RULES.get(key, {}) or {}
        for dep in tuple(rule.get("required", ()) or ()) + tuple(rule.get("recommended", ()) or ()):
            dep = normalize_feature_key(dep)
            if dep in feature_key_set and dep not in allowed:
                allowed.append(dep)
                changed = True

print(",".join(allowed))
PY
)"; then
    return 1
  fi
  NORMALIZED_FEATURE_SELECTION="$normalized"
  return 0
}

normalize_token_feature_selection() {
  normalize_feature_or_bundle_selection "$1" "feature" || return 1
  NORMALIZED_DEV_TOKEN_FEATURES="$NORMALIZED_FEATURE_SELECTION"
  return 0
}

prompt_feature_bundle_scope() {
  local answer
  say "Feature packages:"
  print_known_feature_bundles
  say "Enter comma-separated package numbers or names. Examples: 2,3,trading or social,storage,media."
  prompt_value "Feature packages" "${FEATURE_BUNDLES:-full-user}" answer
  FEATURE_BUNDLES="$answer"
  normalize_feature_or_bundle_selection "$FEATURE_BUNDLES" "bundle" || die "invalid feature bundle selection: $FEATURE_BUNDLES"
  FEATURE_LIST="$NORMALIZED_FEATURE_SELECTION"
  say "Resolved feature package keys: ${FEATURE_LIST:-<none>}"
}

prompt_token_feature_scope() {
  local answer
  say "Generated dev token allowed feature scope:"
  say "   0) unrestricted token scope (default; no token-level feature restriction)"
  print_known_feature_bundles
  print_known_feature_keys
  say "Enter comma-separated package names, b-numbers, f-numbers, or feature keys. Examples: social,storage,trading or b8,feature_videos_enabled,f20."
  while true; do
    prompt_value "Generated dev token allowed feature packages / keys" "$DEV_TOKEN_FEATURES" answer
    if normalize_token_feature_selection "$answer"; then
      DEV_TOKEN_FEATURES="$NORMALIZED_DEV_TOKEN_FEATURES"
      if [[ -z "$DEV_TOKEN_FEATURES" ]]; then
        say "Generated dev token feature scope: unrestricted"
      else
        say "Generated dev token feature scope: $DEV_TOKEN_FEATURES"
      fi
      return 0
    fi
    say "Please choose listed numbers, feature_* keys, short names like chat/videos, or 0 for unrestricted."
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

prompt_launch_layout() {
  local default_choice="1"
  local answer

  normalize_yes_no_value "$IN_PLACE" "in-place"
  IN_PLACE="$NORMALIZED_YES_NO"
  normalize_yes_no_value "$RUNTIME_IN_SOURCE" "runtime in source"
  RUNTIME_IN_SOURCE="$NORMALIZED_YES_NO"
  if [[ "$RUNTIME_IN_SOURCE" == "1" ]]; then
    default_choice="3"
  elif [[ "$IN_PLACE" == "1" ]]; then
    default_choice="2"
  fi

  say "Launch layout:"
  say "  1) isolated tmp copy + tmp runtime (best for QA; no repo runtime changes)"
  say "  2) current repo + tmp runtime (no source copy; runtime stays under --run-root)"
  say "  3) current repo + ./runtime (local deployment layout)"
  while true; do
    printf 'Choose launch layout [default %s]: ' "$default_choice"
    if ! read -r answer; then
      die "interactive setup was interrupted"
    fi
    answer="${answer:-$default_choice}"
    case "${answer,,}" in
      1|tmp|copy|isolated|qa)
        IN_PLACE=0
        RUNTIME_IN_SOURCE=0
        return 0
        ;;
      2|current|in-place|inplace|no-copy|nocopy)
        IN_PLACE=1
        RUNTIME_IN_SOURCE=0
        return 0
        ;;
      3|deploy|deployment|source|source-runtime|runtime-in-source|formal)
        IN_PLACE=1
        RUNTIME_IN_SOURCE=1
        return 0
        ;;
      *)
        say "Please choose 1, 2, or 3."
        ;;
    esac
  done
}

prompt_server_runner() {
  local default_choice="1"
  local answer
  local customize=0

  normalize_server_runner
  if [[ "$SERVER_RUNNER" == "flask" ]]; then
    default_choice="2"
  fi

  say "Server runner:"
  say "  1) bounded gunicorn (recommended; protects the app under uploads/HLS/load)"
  say "     - imports server:app; does not run server.py __main__ or legacy in-process workers"
  say "  2) Flask/Werkzeug direct server (debug only; not for upload/HLS stress)"
  say "     - same path as python3 server.py; starts legacy in-process workers in one process"
  while true; do
    printf 'Choose server runner [default %s]: ' "$default_choice"
    if ! read -r answer; then
      die "interactive setup was interrupted"
    fi
    answer="${answer:-$default_choice}"
    case "${answer,,}" in
      1|gunicorn|bounded|wsgi|prod|production)
        SERVER_RUNNER="gunicorn"
        break
        ;;
      2|flask|werkzeug|direct|debug)
        SERVER_RUNNER="flask"
        return 0
        ;;
      *)
        say "Please choose 1 or 2."
        ;;
    esac
  done

  prompt_yes_no "Customize gunicorn worker/thread settings" 0 customize
  if [[ "$customize" == "1" ]]; then
    prompt_value "Gunicorn workers" "$GUNICORN_WORKERS" GUNICORN_WORKERS
    prompt_value "Gunicorn threads per worker" "$GUNICORN_THREADS" GUNICORN_THREADS
    prompt_value "Gunicorn timeout seconds" "$GUNICORN_TIMEOUT" GUNICORN_TIMEOUT
    prompt_value "Gunicorn backlog" "$GUNICORN_BACKLOG" GUNICORN_BACKLOG
  fi
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
  prompt_launch_layout
  if [[ "$RUNTIME_IN_SOURCE" != "1" ]]; then
    prompt_value "Tmp workspace/run root" "$default_run_root" RUN_ROOT
  fi
  prompt_value "Host" "$HOST" HOST
  prompt_value "Port" "$PORT" PORT
  prompt_server_runner
  prompt_feature_settings
  prompt_yes_no "Enable security settings" "$SECURITY_SETTINGS_ENABLED" SECURITY_SETTINGS_ENABLED
  prompt_server_mode
  if [[ "$SERVER_MODE" == "test" || "$SERVER_MODE" == "internal_test" ]]; then
    prompt_value "Generated dev token TTL minutes" "$DEV_TOKEN_TTL_MINUTES" DEV_TOKEN_TTL_MINUTES
    prompt_token_feature_scope
    prompt_value "Generated dev token account username" "$DEV_TOKEN_USER" DEV_TOKEN_USER
    prompt_value "Password for generated token account (blank = keep existing or auto-generate new account)" "$DEV_TOKEN_PASSWORD" DEV_TOKEN_PASSWORD
    prompt_value "Role for generated token account (user/manager/super_admin)" "$DEV_TOKEN_ROLE" DEV_TOKEN_ROLE
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

ensure_official_workflows_source() {
  local root="$1"
  local workflow_dir="$root/workflows/comfyui"
  if [[ ! -f "$workflow_dir/txt2img_basic/workflow.json" || ! -f "$workflow_dir/txt2img_basic/manifest.json" ]]; then
    die "official ComfyUI workflow bundles are missing under $workflow_dir; dev runtime cannot seed default official workflows"
  fi
  local count
  count="$(find "$workflow_dir" -mindepth 2 -maxdepth 2 -name workflow.json 2>/dev/null | wc -l | tr -d ' ')"
  say "[dev-tmp] workflows: found $count official ComfyUI workflow bundle(s)"
}

python_has_runtime_dependencies() {
  python3 - <<'PY' >/dev/null 2>&1 || return 1
import argon2
import cryptography
import flask
import flask_talisman
import chess
import websocket
PY
  if [[ "${SERVER_RUNNER:-flask}" == "gunicorn" ]]; then
    python3 - <<'PY' >/dev/null 2>&1 || return 1
import gunicorn
PY
  fi
  return 0
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
token_user = payload.get("token_user") if isinstance(payload, dict) else {}
if isinstance(token_user, dict) and token_user.get("username"):
    created_text = "created" if token_user.get("created") else "existing"
    print(f"[dev-tmp] token user: {token_user.get('username')} ({created_text}, role={token_user.get('role') or 'user'})")
    if token_user.get("password"):
        print(f"[dev-tmp]   password={token_user.get('password')}")
feature_scope = payload.get("token_feature_scope") or "unknown"
allowed_keys = payload.get("allowed_feature_keys") or []
print(f"[dev-tmp] token feature scope: {feature_scope}")
if allowed_keys:
    print(f"[dev-tmp] token allowed feature keys: {', '.join(str(item) for item in allowed_keys)}")
feature_catalog = payload.get("available_feature_keys") or []
if feature_catalog:
    print("[dev-tmp] available feature keys:")
    for item in feature_catalog:
        if not isinstance(item, dict):
            continue
        key = str(item.get("key") or "").strip()
        if not key:
            continue
        label = str(item.get("label") or key).strip()
        enabled = "on" if item.get("enabled") else "off"
        allowed = "allowed" if item.get("allowed_by_token") else "blocked"
        print(f"[dev-tmp]   {key} [{enabled}/{allowed}] - {label}")
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
    say "[dev-tmp] port:      cannot kill the process on port $requested because no pid was identified; falling back to another port"
    use_next_available_port "$requested"
    return 0
  fi
  say "[dev-tmp] port:      terminating pid(s): $pids"
  if ! kill $pids; then
    say "[dev-tmp] port:      failed to terminate pid(s): $pids; falling back to another port"
    use_next_available_port "$requested"
    return 0
  fi
  for _ in $(seq 1 20); do
    if port_is_available "$requested"; then
      PORT="$requested"
      say "[dev-tmp] port:      $requested is now available"
      return 0
    fi
    sleep 0.25
  done
  say "[dev-tmp] port:      port $requested is still occupied after terminating pid(s): $pids; falling back to another port"
  use_next_available_port "$requested"
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
    --feature-bundles|--feature-packages|--feature-presets)
      FEATURE_BUNDLES="${2:?missing feature bundle list}"
      FEATURE_MODE="bundles"
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
    --token-user)
      DEV_TOKEN_USER="${2:?missing token username}"
      shift 2
      ;;
    --token-password)
      DEV_TOKEN_PASSWORD="${2:?missing token password}"
      shift 2
      ;;
    --token-role)
      DEV_TOKEN_ROLE="${2:?missing token role}"
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
    --server-runner)
      SERVER_RUNNER="${2:?missing server runner}"
      shift 2
      ;;
    --gunicorn-workers)
      GUNICORN_WORKERS="${2:?missing gunicorn worker count}"
      shift 2
      ;;
    --gunicorn-threads)
      GUNICORN_THREADS="${2:?missing gunicorn thread count}"
      shift 2
      ;;
    --gunicorn-timeout)
      GUNICORN_TIMEOUT="${2:?missing gunicorn timeout}"
      shift 2
      ;;
    --gunicorn-graceful-timeout)
      GUNICORN_GRACEFUL_TIMEOUT="${2:?missing gunicorn graceful timeout}"
      shift 2
      ;;
    --gunicorn-keep-alive)
      GUNICORN_KEEP_ALIVE="${2:?missing gunicorn keep-alive}"
      shift 2
      ;;
    --gunicorn-backlog)
      GUNICORN_BACKLOG="${2:?missing gunicorn backlog}"
      shift 2
      ;;
    --gunicorn-max-requests)
      GUNICORN_MAX_REQUESTS="${2:?missing gunicorn max requests}"
      shift 2
      ;;
    --gunicorn-max-requests-jitter)
      GUNICORN_MAX_REQUESTS_JITTER="${2:?missing gunicorn max requests jitter}"
      shift 2
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
    --runtime-in-source|--source-runtime|--deploy-in-place)
      IN_PLACE=1
      RUNTIME_IN_SOURCE=1
      shift
      ;;
    --tmp-runtime)
      RUNTIME_IN_SOURCE=0
      shift
      ;;
    --copy)
      IN_PLACE=0
      RUNTIME_IN_SOURCE=0
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
if [[ -n "$FEATURE_BUNDLES" && -z "${HACKME_DEV_FEATURE_MODE:-}" && "$FEATURE_MODE_SET" == "0" ]]; then
  FEATURE_MODE="bundles"
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
  if [[ "$RUNTIME_IN_SOURCE" == "1" ]]; then
    RUNTIME_ROOT="$SOURCE_ROOT/runtime"
  else
    RUNTIME_ROOT="$RUN_ROOT/runtime"
  fi
else
  COPY_ROOT="$RUN_ROOT/hackme_web"
  RUNTIME_ROOT="$COPY_ROOT/runtime"
fi
LOG_CAPTURE="$RUNTIME_ROOT/logs/server_direct.out"
PID_FILE="$RUNTIME_ROOT/server.pid"

if [[ "$RUNTIME_IN_SOURCE" == "1" ]]; then
  :
elif [[ "$IN_PLACE" == "1" ]]; then
  mkdir -p "$RUN_ROOT"
else
  [[ ! -e "$COPY_ROOT" ]] || die "tmp copy already exists: $COPY_ROOT"
  copy_repo
fi
ensure_official_workflows_source "$COPY_ROOT"
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
export HACKME_DEV_FEATURE_BUNDLES="$FEATURE_BUNDLES"
export HACKME_DEV_IN_PLACE="$IN_PLACE"
export HACKME_DEV_RUNTIME_IN_SOURCE="$RUNTIME_IN_SOURCE"
export HACKME_DEV_TOKEN_FEATURES="$DEV_TOKEN_FEATURES"
export HACKME_DEV_TOKEN_TTL_MINUTES="$DEV_TOKEN_TTL_MINUTES"
export HACKME_DEV_TOKEN_USER="$DEV_TOKEN_USER"
export HACKME_DEV_TOKEN_PASSWORD="$DEV_TOKEN_PASSWORD"
export HACKME_DEV_TOKEN_ROLE="$DEV_TOKEN_ROLE"
export HACKME_DEV_INTERNAL_TEST_TOKEN_FEATURES="$DEV_TOKEN_FEATURES"
export HACKME_DEV_TOKENS_FILE="$RUNTIME_ROOT/dev_tokens.json"
export HACKME_DEV_SECURITY_ENABLED="$SECURITY_SETTINGS_ENABLED"
export HACKME_DEV_SERVER_MODE="$SERVER_MODE"
export HACKME_DEV_EXTRA_ACCOUNTS="$EXTRA_ACCOUNTS"
export HACKME_DEV_BTC_TRADE_AUTOSTART="$BTC_TRADE_AUTOSTART"
export HACKME_DEV_BACKTEST_PROBE_ON_STARTUP="$BACKTEST_PROBE_ON_STARTUP"
export HTML_LEARNING_TRADING_BACKTEST_PROBE_ON_STARTUP="$BACKTEST_PROBE_ON_STARTUP"
export HACKME_DEV_DEFAULT_ACCOUNT_PASSWORDS="$DEFAULT_ACCOUNT_PASSWORDS"
export HACKME_DEV_SERVER_RUNNER="$SERVER_RUNNER"
export HACKME_DEV_GUNICORN_WORKERS="$GUNICORN_WORKERS"
export HACKME_DEV_GUNICORN_THREADS="$GUNICORN_THREADS"
export HACKME_DEV_GUNICORN_TIMEOUT="$GUNICORN_TIMEOUT"
if [[ "$SERVER_RUNNER" == "flask" ]]; then
  export HACKME_ALLOW_DIRECT_SERVER=1
fi
export HTML_LEARNING_BACKPRESSURE_ENABLED="${HTML_LEARNING_BACKPRESSURE_ENABLED:-1}"
if [[ "$SERVER_RUNNER" == "gunicorn" ]]; then
  export HTML_LEARNING_BACKPRESSURE_THREAD_CAPACITY="${HTML_LEARNING_BACKPRESSURE_THREAD_CAPACITY:-$GUNICORN_THREADS}"
else
  export HTML_LEARNING_BACKPRESSURE_THREAD_CAPACITY="${HTML_LEARNING_BACKPRESSURE_THREAD_CAPACITY:-auto}"
fi
export HTML_LEARNING_BACKPRESSURE_NORMAL_LIMIT="${HTML_LEARNING_BACKPRESSURE_NORMAL_LIMIT:-auto}"
export HTML_LEARNING_BACKPRESSURE_HEAVY_LIMIT="${HTML_LEARNING_BACKPRESSURE_HEAVY_LIMIT:-auto}"
export HTML_LEARNING_BACKPRESSURE_FAST_LANE_RESERVED="${HTML_LEARNING_BACKPRESSURE_FAST_LANE_RESERVED:-auto}"
export HTML_LEARNING_BACKPRESSURE_RETRY_AFTER_SECONDS="${HTML_LEARNING_BACKPRESSURE_RETRY_AFTER_SECONDS:-2}"
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
from pathlib import Path
import secrets
import server
from services.comfyui.template.seeding import seed_default_comfyui_workflows
from services.server.startup import bootstrap_points_initial_grants_if_due
from services.security.access_controls import (
    generate_internal_test_token,
    hash_internal_test_token,
    maintenance_bypass_expires_at,
)
try:
    from services.platform.settings_metadata import setting_detail
except Exception:
    setting_detail = None

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
server.ensure_local_tls_files(server.CERT_FILE, server.KEY_FILE)

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


def feature_label(key):
    if setting_detail is not None:
        try:
            detail = setting_detail(key)
            label = str(detail.get("label") or "").strip()
            if label:
                return label
        except Exception:
            pass
    return key.removeprefix("feature_").removesuffix("_enabled").replace("_", " ")


def dev_token_ttl_minutes():
    try:
        ttl = int(str(os.environ.get("HACKME_DEV_TOKEN_TTL_MINUTES", "1440")).strip())
    except Exception:
        ttl = 1440
    return max(5, min(ttl, 30 * 24 * 60))


def normalize_token_role(raw_value):
    role = str(raw_value or "user").strip() or "user"
    if role not in {"user", "manager", "super_admin"}:
        raise SystemExit(f"invalid generated token account role: {role}")
    return role


selected_features = {
    key
    for key in (normalize_feature_key(item) for item in raw_feature_list.split(","))
    if key
}
if feature_mode == "defaults":
    feature_updates = {}
elif feature_mode in {"custom", "bundles"}:
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


def ensure_dev_token_account(conn, now):
    username = str(os.environ.get("HACKME_DEV_TOKEN_USER", "test") or "test").strip()
    if not username:
        raise SystemExit("generated token account username cannot be blank")
    role = normalize_token_role(os.environ.get("HACKME_DEV_TOKEN_ROLE", "user"))
    configured_password = str(os.environ.get("HACKME_DEV_TOKEN_PASSWORD", "") or "")
    password_to_report = ""
    created = False
    updated_password = False

    row = conn.execute("SELECT id, username, role FROM users WHERE username=? LIMIT 1", (username,)).fetchone()
    if row:
        if configured_password:
            ensure_extra_account(conn, username, configured_password, role, now)
            updated_password = True
            password_to_report = configured_password
    else:
        password = configured_password or secrets.token_urlsafe(12)
        ensure_extra_account(conn, username, password, role, now)
        created = True
        password_to_report = password

    row = conn.execute("SELECT id, username, role FROM users WHERE username=? LIMIT 1", (username,)).fetchone()
    if not row:
        raise SystemExit(f"generated token account could not be created: {username}")
    return row, {
        "username": str(row["username"] or username),
        "role": str(row["role"] or role),
        "created": created,
        "password_updated": updated_password,
        "password": password_to_report,
    }


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

try:
    comfyui_seed = seed_default_comfyui_workflows(runtime_root=Path(os.environ["HACKME_RUNTIME_DIR"]))
    print(
        "[dev-tmp] workflows seeded: "
        f"source={comfyui_seed.get('source_count', 0)} "
        f"runtime={comfyui_seed.get('runtime_count', 0)} "
        f"copied={len(comfyui_seed.get('copied') or [])} "
        f"destination={comfyui_seed.get('destination')}"
    )
except Exception as exc:
    print(f"[dev-tmp] warning: official ComfyUI workflow seed failed: {exc}")

points_bootstrap = bootstrap_points_initial_grants_if_due(
    points_service=server.points_service,
    get_system_settings=server.get_system_settings,
    get_runtime_server_mode=server.get_runtime_server_mode,
    audit=server.audit,
    env_value="1" if selected_server_mode in {"production", "dev_ready", "test"} else "",
)
if not points_bootstrap.get("ok"):
    print(f"[dev-tmp] warning: default account point grants failed: {points_bootstrap.get('error')}")
elif not points_bootstrap.get("skipped"):
    genesis = points_bootstrap.get("genesis") or {}
    if genesis.get("created_count"):
        print(f"[dev-tmp] default account point grants created: {genesis.get('created_count')}")

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
    effective_feature_values = dict(server.DEFAULT_SETTINGS)
    effective_feature_values.update(feature_updates)
    dev_tokens_payload["token_feature_scope"] = "unrestricted" if not token_features else "restricted"
    dev_tokens_payload["allowed_feature_keys"] = token_features
    dev_tokens_payload["available_feature_keys"] = [
        {
            "key": key,
            "label": feature_label(key),
            "enabled": bool(effective_feature_values.get(key, False)),
            "allowed_by_token": (not token_features or key in token_features),
        }
        for key in feature_keys
    ]
    token_user = None
    token_user_info = {}
    conn = server.get_db()
    try:
        token_user, token_user_info = ensure_dev_token_account(conn, datetime.now().isoformat())
        conn.commit()
    finally:
        conn.close()
    dev_tokens_payload["token_user"] = token_user_info
    if token_user:
        user_id = int(token_user["id"])
        username = str(token_user["username"] or token_user_info.get("username") or "test")
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
                "usage": "login as the bound user in internal_test mode with username + internal_test_token/login_token/X-Internal-Test-Token; password may be blank",
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
                    "usage": "login as the bound user in test/internal_test mode with username + tester_token/login_token/X-Tester-Token; password may be blank",
                }
            else:
                dev_tokens_payload["warnings"].append(f"tester token generation failed: {tester_result.get('msg') or tester_result}")
    else:
        dev_tokens_payload["warnings"].append("generated token account was not found; no dev token generated")
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
  if [[ "$RUNTIME_IN_SOURCE" == "1" ]]; then
    say "[dev-tmp] source:    $COPY_ROOT (source runtime deployment)"
  elif [[ "$IN_PLACE" == "1" ]]; then
    say "[dev-tmp] source:    $COPY_ROOT (in-place, no copy; tmp runtime)"
  else
    say "[dev-tmp] repo copy: $COPY_ROOT"
  fi
  say "[dev-tmp] runtime:   $RUNTIME_ROOT"
  say "[dev-tmp] mode:      foreground $SERVER_RUNNER"
  if [[ "$SERVER_RUNNER" == "flask" ]]; then
    say "[dev-tmp] warning:   Flask/Werkzeug direct server is debug-only; use gunicorn for uploads/HLS/load."
  fi
  print_generated_dev_tokens
  if [[ "$SERVER_RUNNER" == "gunicorn" ]]; then
    exec "$PYTHON_BIN" -m gunicorn "server:app" \
      --bind "${HOST}:${PORT}" \
      --worker-class gthread \
      --workers "$GUNICORN_WORKERS" \
      --threads "$GUNICORN_THREADS" \
      --timeout "$GUNICORN_TIMEOUT" \
      --graceful-timeout "$GUNICORN_GRACEFUL_TIMEOUT" \
      --keep-alive "$GUNICORN_KEEP_ALIVE" \
      --backlog "$GUNICORN_BACKLOG" \
      --max-requests "$GUNICORN_MAX_REQUESTS" \
      --max-requests-jitter "$GUNICORN_MAX_REQUESTS_JITTER" \
      --certfile "$RUNTIME_ROOT/cert.pem" \
      --keyfile "$RUNTIME_ROOT/key.pem" \
      --access-logfile - \
      --error-logfile -
  fi
  exec "$PYTHON_BIN" server.py
fi

if [[ "$SERVER_RUNNER" == "gunicorn" ]]; then
  setsid "$PYTHON_BIN" -m gunicorn "server:app" \
    --bind "${HOST}:${PORT}" \
    --worker-class gthread \
    --workers "$GUNICORN_WORKERS" \
    --threads "$GUNICORN_THREADS" \
    --timeout "$GUNICORN_TIMEOUT" \
    --graceful-timeout "$GUNICORN_GRACEFUL_TIMEOUT" \
    --keep-alive "$GUNICORN_KEEP_ALIVE" \
    --backlog "$GUNICORN_BACKLOG" \
    --max-requests "$GUNICORN_MAX_REQUESTS" \
    --max-requests-jitter "$GUNICORN_MAX_REQUESTS_JITTER" \
    --certfile "$RUNTIME_ROOT/cert.pem" \
    --keyfile "$RUNTIME_ROOT/key.pem" \
    --access-logfile - \
    --error-logfile - >"$LOG_CAPTURE" 2>&1 < /dev/null &
else
  say "[dev-tmp] warning:   Flask/Werkzeug direct server is debug-only; use gunicorn for uploads/HLS/load."
  setsid "$PYTHON_BIN" server.py >"$LOG_CAPTURE" 2>&1 < /dev/null &
fi
SERVER_PID="$!"
printf '%s\n' "$SERVER_PID" > "$PID_FILE"

SERVER_URL="$(wait_for_server_url || true)"

if [[ "$RUNTIME_IN_SOURCE" == "1" ]]; then
  say "[dev-tmp] source:    $COPY_ROOT (source runtime deployment)"
elif [[ "$IN_PLACE" == "1" ]]; then
  say "[dev-tmp] source:    $COPY_ROOT (in-place, no copy; tmp runtime)"
else
  say "[dev-tmp] repo copy: $COPY_ROOT"
fi
say "[dev-tmp] runtime:   $RUNTIME_ROOT"
say "[dev-tmp] pid:       $SERVER_PID"
say "[dev-tmp] runner:    $SERVER_RUNNER"
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
