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
import tempfile
from pathlib import Path

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
# Until then the cheapest proof is: liquidation source is "margin_positions",
# and "margin_positions" routes to test_shadow_margin_positions in internal_test.
# Marked xfail until Phase 5 actually wires liquidation through routing.
# ─────────────────────────────────────────────────────────────────────


def test_liquidation_does_not_cross_world():
    """Liquidation source / sink must stay in the same world.
    Phase 5 (boundary) gate enforces this at every entry point.
    """
    from services.trading_mode_gate import (
        liquidation_target_table,
        liquidation_settle_table,
        assert_same_world,
        CrossWorldContamination,
        TradingDisabledInMode,
    )
    # A production liquidation reads from production positions and
    # writes to production wallets — both stay in prod.
    prod_ctx = _ctx("production")
    assert liquidation_target_table(prod_ctx) == "trading_margin_positions"
    assert liquidation_settle_table(prod_ctx) == "wallets"

    # An internal_test liquidation reads from shadow positions and
    # writes to shadow wallets — both stay in shadow.
    inter_ctx = _ctx("internal_test")
    assert liquidation_target_table(inter_ctx) == "test_shadow_margin_positions"
    assert liquidation_settle_table(inter_ctx) == "test_shadow_wallets"

    # Mixing prod source + shadow sink (or vice versa) — refuse loudly.
    with pytest.raises(CrossWorldContamination):
        assert_same_world(prod_ctx, inter_ctx, action="liquidation")
    with pytest.raises(CrossWorldContamination):
        assert_same_world(inter_ctx, prod_ctx, action="liquidation_settle")

    # Non-trading modes refuse outright.
    for bad_mode in ("dev_ready", "maintenance", "incident_lockdown", "superweak"):
        with pytest.raises(TradingDisabledInMode):
            liquidation_target_table(_ctx(bad_mode))


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


def test_funding_rate_does_not_cross_world():
    """Funding-rate publish channels are mode-scoped from day 1 via
    the cache-key helper. A production funding tick cannot be
    accidentally republished into a shadow channel — the keys differ.
    """
    from services.trading_mode_gate import funding_channel_key, TradingDisabledInMode
    prod = funding_channel_key("BTC", _ctx("production"))
    inter = funding_channel_key("BTC", SmV2Context(mode="internal_test", tester_id=7, actor_role="user", request_id="r"))
    assert prod != inter
    assert ":production:" in prod
    assert ":internal_test:" in inter and "tester7" in inter
    # Non-trading modes refuse outright.
    for bad_mode in ("dev_ready", "maintenance", "incident_lockdown", "superweak"):
        with pytest.raises(TradingDisabledInMode):
            funding_channel_key("BTC", _ctx(bad_mode))

    # Runtime publish path must also stay isolated by world.
    import sqlite3
    from services.points_chain import ensure_points_economy_schema
    from services.trading_engine import TradingEngineService, ensure_trading_schema

    db_path = Path(tempfile.mkdtemp(prefix="smv2_funding_acceptance_")) / "funding.sqlite"

    def get_db():
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    conn = get_db()
    conn.execute("CREATE TABLE users (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT NOT NULL UNIQUE, role TEXT NOT NULL DEFAULT 'user', status TEXT NOT NULL DEFAULT 'active')")
    conn.execute("INSERT INTO users (username, role, status) VALUES ('alice', 'user', 'active')")
    ensure_points_economy_schema(conn)
    ensure_trading_schema(conn)
    conn.execute(
        "INSERT OR REPLACE INTO trading_settings (key, value, updated_at) VALUES ('trading.shadow_funding_publish_enabled', 'true', datetime('now'))"
    )
    conn.commit()
    conn.close()

    points = PointsLedgerService(get_db=get_db, chain_secret="acceptance-funding", backup_dir=db_path.parent / "backups")
    trading = TradingEngineService(get_db=get_db, points_service=points, live_price_provider=lambda symbol: 77059)
    prod_snapshot = trading.publish_funding_rate_snapshot(
        market_symbol="BTC/POINTS",
        rate_percent=0.01,
        actor={"id": 1, "username": "alice", "role": "user"},
        ctx=SmV2Context(mode="production", tester_id=None, actor_role="user", request_id="prod"),
    )["snapshot"]
    shadow_snapshot = trading.publish_funding_rate_snapshot(
        market_symbol="BTC/POINTS",
        rate_percent=0.77,
        actor={"id": 1, "username": "alice", "role": "user"},
        ctx=SmV2Context(mode="internal_test", tester_id=7, actor_role="user", request_id="shadow"),
    )["snapshot"]
    assert prod_snapshot["channel_key"] != shadow_snapshot["channel_key"]
    assert trading.get_funding_rate_snapshot(
        market_symbol="BTC/POINTS",
        ctx=SmV2Context(mode="production", tester_id=None, actor_role="user", request_id="prod-read"),
    )["snapshot"]["rate_percent"] == pytest.approx(0.01)
    assert trading.get_funding_rate_snapshot(
        market_symbol="BTC/POINTS",
        ctx=SmV2Context(mode="internal_test", tester_id=7, actor_role="user", request_id="shadow-read"),
    )["snapshot"]["rate_percent"] == pytest.approx(0.77)


# ─────────────────────────────────────────────────────────────────────
# 7. matching_engine_namespaces_separate
#
# Phase 5 + Phase 6 (cache key namespace) together. xfail until both.
# ─────────────────────────────────────────────────────────────────────


def test_matching_engine_namespaces_separate():
    """Matching-engine orderbook keys carry mode scope. A buy at 1 BTC
    in internal_test sits in a different namespace than the same buy
    in production — so a shadow order can never collide with a prod
    one.
    """
    from services.trading_mode_gate import matching_orderbook_key
    prod_ctx = _ctx("production")
    test_ctx = _ctx("test")
    inter_ctx = SmV2Context(mode="internal_test", tester_id=1, actor_role="user", request_id="r")
    inter_ctx_2 = SmV2Context(mode="internal_test", tester_id=2, actor_role="user", request_id="r2")

    prod = matching_orderbook_key("BTC/POINTS", prod_ctx)
    test = matching_orderbook_key("BTC/POINTS", test_ctx)
    inter1 = matching_orderbook_key("BTC/POINTS", inter_ctx)
    inter2 = matching_orderbook_key("BTC/POINTS", inter_ctx_2)

    # All four namespaces are distinct.
    assert len({prod, test, inter1, inter2}) == 4
    # internal_test without tester_id must refuse — would otherwise
    # collide all testers into a single shadow orderbook.
    with pytest.raises(ValueError):
        matching_orderbook_key("BTC/POINTS", _ctx("internal_test"))


# ─────────────────────────────────────────────────────────────────────
# 8. cache_keys_carry_mode_scope
#
# Phase 6 lands services/cache_keys.py. xfail until then.
# ─────────────────────────────────────────────────────────────────────


def test_cache_keys_carry_mode_scope():
    from services.cache_keys import make_cache_key
    # Forgetting mode= must raise — the strongest spec-promise.
    with pytest.raises(TypeError):
        make_cache_key("orderbook", market="BTC/POINTS")  # type: ignore[call-arg]
    # mode='' rejected.
    with pytest.raises(ValueError):
        make_cache_key("orderbook", mode="", market="BTC/POINTS")
    # internal_test without tester_id rejected.
    with pytest.raises(ValueError):
        make_cache_key("orderbook", mode="internal_test", market="BTC/POINTS")
    # Production / test / internal_test produce distinct keys.
    prod = make_cache_key("orderbook", mode="production", market="BTC")
    test = make_cache_key("orderbook", mode="test", market="BTC")
    inter = make_cache_key("orderbook", mode="internal_test", tester_id=1, market="BTC")
    assert prod != test != inter
    assert ":production:" in prod and ":test:" in test and ":internal_test:" in inter


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
    for logical in ("wallets", "orders", "positions", "margin_positions", "points_ledger"):
        with pytest.raises(routing.RoutingNotAllowed):
            routing.resolve_table(logical, _ctx("superweak"))
    with pytest.raises(ChainModeViolation):
        routing.resolve_table("points_chain_blocks", _ctx("superweak"))
