#!/usr/bin/env bash
# server_mode_v2_phase_5b_acceptance.sh
# ---------------------------------------------------------------------------
# Phase 5b acceptance suite (A-1 .. A-7 from the
# COMMAND TO CODEX in ~/agent_communication.txt).
#
# Run from the repo root:
#     bash scripts/security/server_mode/server_mode_v2_phase_5b_acceptance.sh
#
# Exit 0 only when every block returns 0. Each block prints a [PASS] /
# [FAIL] header and the failing test list (if any). Use this in CI or
# in local re-runs after Codex pushes another G-* commit.
# ---------------------------------------------------------------------------

set -uo pipefail
cd "$(dirname "$0")/../../.."  # repo root

PYTHON="${PYTHON:-python3}"
pass_count=0
fail_count=0
fail_blocks=()

run_block() {
  local label="$1"; shift
  printf '\n========== %s ==========\n' "$label"
  if "$@"; then
    printf '[PASS] %s\n' "$label"
    pass_count=$((pass_count + 1))
  else
    printf '[FAIL] %s\n' "$label"
    fail_count=$((fail_count + 1))
    fail_blocks+=("$label")
  fi
}

# --- A-2  SMv2 phase suite must stay green ---------------------------------
SMV2_TESTS=(
  tests/server_mode/test_smv2_acceptance.py
  tests/platform/test_db_mode_triggers.py
  tests/points/test_chain_production_only.py
  tests/server_mode/test_smv2_context.py
  tests/platform/test_routing_service.py
  tests/server_mode/test_shadow_schema.py
  tests/platform/test_cache_keys_namespace.py
  tests/trading/runtime/test_trading_mode_gate.py
  tests/security/gates/test_production_gate_enforcement.py
  tests/security/auth/test_auth_csrf_safe.py
  tests/snapshots/test_snapshots.py
  tests/points/test_points_chain.py
  tests/scripts/security/test_server_mode_v2_full_smoke_scripts.py
)
run_block "A-2 SMv2 phase suite" "$PYTHON" -m pytest -q "${SMV2_TESTS[@]}"

# --- A-3  Trading regression must not break --------------------------------
TRADING_TESTS=(
  tests/trading/core/test_trading_engine.py
  tests/trading/pricing/test_trading_reference_prices.py
  tests/trading/core/test_trading_websocket_inputs.py
  tests/frontend/trading/test_frontend_economy.py
  tests/scripts/security/test_functional_smoke_script.py
)
run_block "A-3 trading regression" "$PYTHON" -m pytest -q "${TRADING_TESTS[@]}"

# --- A-4  Live full smoke (boots an isolated runtime, runs 6 .sh scripts) --
run_block "A-4 live full smoke" "$PYTHON" scripts/security/server_mode/server_mode_v2_full_smoke.py

# --- A-5  Source grep — no hardcoded prod-table writes -----------------------
# Every prod-table-name string in trading_engine.py must come from
# resolve_table(...) — direct INSERT / UPDATE on a hardcoded prod table
# is the contamination vector Phase 5b exists to remove.
printf '\n========== A-5 source-grep regression ==========\n'
hits=$(grep -nE 'INSERT INTO (trading_orders|trading_spot_positions|trading_margin_positions|points_ledger|wallets)\b' services/trading/trading_engine.py || true)
if [ -z "$hits" ]; then
  printf '[PASS] A-5 source-grep regression — no hardcoded prod-table INSERTs\n'
  pass_count=$((pass_count + 1))
else
  printf '[FAIL] A-5 source-grep regression — hardcoded prod-table INSERTs found:\n'
  printf '%s\n' "$hits"
  fail_count=$((fail_count + 1))
  fail_blocks+=("A-5 source-grep regression")
fi

# --- A-6  Acceptance regression (5 spec promises) --------------------------
A6_TESTS=(
  tests/server_mode/test_smv2_acceptance.py::test_tester_trade_does_not_change_production_wallet
  tests/server_mode/test_smv2_acceptance.py::test_tester_trade_does_not_write_points_chain
  tests/server_mode/test_smv2_acceptance.py::test_liquidation_does_not_cross_world
  tests/server_mode/test_smv2_acceptance.py::test_funding_rate_does_not_cross_world
  tests/server_mode/test_smv2_acceptance.py::test_matching_engine_namespaces_separate
)
run_block "A-6 acceptance regression" "$PYTHON" -m pytest -q "${A6_TESTS[@]}"

# --- Summary ---------------------------------------------------------------
printf '\n========== SUMMARY ==========\n'
printf 'passed blocks: %d\n' "$pass_count"
printf 'failed blocks: %d\n' "$fail_count"
if [ "$fail_count" -gt 0 ]; then
  printf 'failed:\n'
  for label in "${fail_blocks[@]}"; do
    printf '  - %s\n' "$label"
  done
  exit 1
fi
printf 'overall: PASS\n'
exit 0
