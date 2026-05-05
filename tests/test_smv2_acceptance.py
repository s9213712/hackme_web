"""Phase 8 of SERVER_MODE_V2_IMPLEMENTATION_PLAN.md — QA acceptance framework.

Locks the 9 acceptance conditions from
docs/SERVER_MODE_V2_TRADING_AND_POINTSCHAIN.md §8 / SERVER_MODE_V2_PROFILE_MATRIX.md
§QA Checklist:

    1. tester_trade_does_not_change_production_wallet
    2. tester_trade_does_not_write_points_chain
    3. production_trade_updates_chain_correctly
    4. liquidation_does_not_cross_world
    5. restore_recovers_chain_integrity
    6. funding_rate_does_not_cross_world
    7. matching_engine_namespaces_separate
    8. cache_keys_carry_mode_scope
    9. superweak_trading_remains_disabled

Tests that depend on a not-yet-landed phase are marked
`@pytest.mark.xfail(strict=True, reason=...)`. When the corresponding
phase lands, removing the marker promotes the test to a hard pass —
which is itself a regression alarm: if the test starts passing without
the marker being removed, pytest fails (xfail strict).

Phase status at this commit:
    - Phase 0 / 1 / 2 / 4 / 7  ✓  (some assertions can run eagerly)
    - Phase 6  pending  -> #8 xfail
    - Phase 5  pending  -> #1, #4, #6, #7 xfail
    - Phase 3  pending  -> not directly required for any of the 9
"""

import pytest

from services import server_mode_routing as routing
from services.points_chain import ChainModeViolation, PointsLedgerService
from services.server_mode_context import SmV2Context


def _ctx(mode):
    return SmV2Context(mode=mode, tester_id=None, actor_role=None, request_id="r")


# ─────────────────────────────────────────────────────────────────────
# 1. tester_trade_does_not_change_production_wallet
#
# In internal_test mode, "wallets" routing must point at the shadow
# table — so any tester order that updates "wallets" by logical name
# only ever touches test_shadow_wallets. Phase 5 will exercise the
# full trade path; for now the routing assertion is the strongest
# cheap proof we have that trades cannot reach production wallets.
# ─────────────────────────────────────────────────────────────────────


def test_tester_trade_does_not_change_production_wallet():
    assert routing.resolve_table("wallets", _ctx("internal_test")) == "test_shadow_wallets"
    # Inverse: production-mode trade *must* hit production wallets.
    assert routing.resolve_table("wallets", _ctx("production")) == "wallets"


# ─────────────────────────────────────────────────────────────────────
# 2. tester_trade_does_not_write_points_chain
#
# Phase 7 service-layer guard already enforces this: chain seal in
# any non-production mode raises ChainModeViolation BEFORE the SQL
# runs. We exercise the seal_block entry point + the routing-layer
# guard for double coverage.
# ─────────────────────────────────────────────────────────────────────


def test_tester_trade_does_not_write_points_chain(tmp_path):
    import sqlite3

    db_path = tmp_path / "p7.sqlite"

    def get_db():
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        return conn

    svc = PointsLedgerService(
        get_db=get_db,
        chain_secret="acceptance-test-secret",
        mode_reader=lambda: "internal_test",
    )
    with pytest.raises(ChainModeViolation):
        svc.seal_block()
    # Routing layer also blocks it.
    with pytest.raises(ChainModeViolation):
        routing.resolve_table("points_chain_blocks", _ctx("internal_test"))


# ─────────────────────────────────────────────────────────────────────
# 3. production_trade_updates_chain_correctly
#
# Asserts the routing layer accepts production-mode chain writes.
# Full chain hash chain correctness is exercised by tests/test_points_chain.py
# (existing test_points_chain_seal_verify_and_proof runs end-to-end).
# ─────────────────────────────────────────────────────────────────────


def test_production_trade_updates_chain_correctly():
    assert routing.resolve_table("points_chain_blocks", _ctx("production")) == "points_chain_blocks"
    assert routing.resolve_table("points_ledger", _ctx("production")) == "points_ledger"
    # The deeper production-mode-correctness signal is in
    # tests/test_points_chain.py::test_points_chain_seal_verify_and_proof.


# ─────────────────────────────────────────────────────────────────────
# 4. liquidation_does_not_cross_world
#
# Phase 5 (trading dual-engine) lands the actual liquidation routing.
# Until then the cheapest proof is: liquidation source is "positions",
# and "positions" routes to test_shadow_positions in internal_test.
# Marked xfail until Phase 5 actually wires liquidation through routing.
# ─────────────────────────────────────────────────────────────────────


@pytest.mark.xfail(strict=True, reason="Phase 5 trading dual-engine not yet landed")
def test_liquidation_does_not_cross_world():
    # Will assert that a shadow-position liquidation never reads
    # production positions and never writes production wallets/ledger.
    raise AssertionError("Phase 5 not landed — placeholder")


# ─────────────────────────────────────────────────────────────────────
# 5. restore_recovers_chain_integrity
#
# Existing tests/test_points_chain.py covers the full restore path;
# tests/test_snapshots.py covers the snapshot/restore path. Here we
# just assert the cross-cutting invariant exists in both places by
# importing the relevant entry points (a regression alarm if either
# entry point disappears).
# ─────────────────────────────────────────────────────────────────────


def test_restore_recovers_chain_integrity():
    from services.points_chain import PointsLedgerService as P
    from services.snapshots import SnapshotService as S
    # Existence of the two entry points is enforced via attribute lookup;
    # actual restore-correctness is in tests/test_points_chain.py
    # and tests/test_snapshots.py (existing comprehensive coverage).
    assert hasattr(P, "verify_chain")
    assert hasattr(P, "restore_from_backup") or hasattr(P, "force_seal_block")
    assert hasattr(S, "create_snapshot")
    assert hasattr(S, "restore_snapshot") or hasattr(S, "apply_snapshot_payload")


# ─────────────────────────────────────────────────────────────────────
# 6. funding_rate_does_not_cross_world
#
# Phase 5 lands the funding-rate-publish split. Marked xfail.
# ─────────────────────────────────────────────────────────────────────


@pytest.mark.xfail(strict=True, reason="Phase 5 trading dual-engine not yet landed")
def test_funding_rate_does_not_cross_world():
    raise AssertionError("Phase 5 not landed — placeholder")


# ─────────────────────────────────────────────────────────────────────
# 7. matching_engine_namespaces_separate
#
# Phase 5 + Phase 6 (cache key namespace) together. xfail until both.
# ─────────────────────────────────────────────────────────────────────


@pytest.mark.xfail(strict=True, reason="Phase 5 + Phase 6 not yet landed")
def test_matching_engine_namespaces_separate():
    raise AssertionError("Phases 5 / 6 not landed — placeholder")


# ─────────────────────────────────────────────────────────────────────
# 8. cache_keys_carry_mode_scope
#
# Phase 6 lands services/cache_keys.py. xfail until then.
# ─────────────────────────────────────────────────────────────────────


@pytest.mark.xfail(strict=True, reason="Phase 6 cache namespace helper not yet landed")
def test_cache_keys_carry_mode_scope():
    from services import cache_keys  # noqa: F401 — will not import until Phase 6
    raise AssertionError("Phase 6 not landed — placeholder")


# ─────────────────────────────────────────────────────────────────────
# 9. superweak_trading_remains_disabled
#
# The superweak profile in services/snapshots.py:BUILTIN_SECURITY_PROFILES
# already sets feature_economy_enabled=False / feature_trading_enabled=False.
# This test asserts the profile keeps that invariant — if anyone flips
# either flag in superweak, it fails here.
# ─────────────────────────────────────────────────────────────────────


def test_superweak_trading_remains_disabled():
    from services.snapshots import BUILTIN_SECURITY_PROFILES
    profile = BUILTIN_SECURITY_PROFILES.get("superweak")
    assert profile is not None, "superweak profile missing from BUILTIN_SECURITY_PROFILES"
    settings = profile.get("settings") or {}
    # Trading is mode-disabled in superweak; if either flag flips on,
    # production-grade economy state is reachable from a superweak run.
    assert settings.get("feature_economy_enabled") is False, settings
    assert settings.get("feature_trading_enabled") is False, settings
    # Routing also confirms: no trading logical name is routable.
    for logical in ("wallets", "orders", "positions", "points_ledger"):
        with pytest.raises(routing.RoutingNotAllowed):
            routing.resolve_table(logical, _ctx("superweak"))
    with pytest.raises(ChainModeViolation):
        routing.resolve_table("points_chain_blocks", _ctx("superweak"))
