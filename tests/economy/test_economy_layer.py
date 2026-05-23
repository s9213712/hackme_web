import sqlite3

import pytest

from services.platform.db_mode_triggers import register_app_mode_function
from services.points_chain import BURN_WALLET_ADDRESS, PointsLedgerService
from services.points_chain.economy_layer import (
    append_economy_event,
    append_economy_incident,
    compute_economy_event_hash,
    economy_layer_report,
    rebuild_economy_derived_balances,
    replay_economy_events,
    verify_economy_derived_balances,
)
from services.points_chain.schema import canonical_json, sha256_text, utc_now


def _db(tmp_path):
    path = tmp_path / "economy_layer.db"

    def get_db():
        conn = sqlite3.connect(path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        register_app_mode_function(conn, mode_reader=lambda: "production")
        return conn

    conn = get_db()
    conn.execute(
        "CREATE TABLE users (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT NOT NULL UNIQUE, role TEXT NOT NULL DEFAULT 'user', status TEXT NOT NULL DEFAULT 'active')"
    )
    conn.execute("INSERT INTO users (id, username, role, status) VALUES (1, 'root', 'super_admin', 'active')")
    conn.commit()
    conn.close()
    return get_db


def _points(tmp_path):
    return PointsLedgerService(
        get_db=_db(tmp_path),
        chain_secret="economy-test-secret",
        backup_dir=tmp_path / "backups",
        mode_reader=lambda: "production",
    )


def _open_economy(tmp_path):
    points = _points(tmp_path)
    conn = points.get_db()
    points.ensure_schema(conn)
    return points, conn


def test_bootstrap_is_idempotent_and_replay_is_the_balance_truth(tmp_path):
    points, conn = _open_economy(tmp_path)
    try:
        first = economy_layer_report(conn, chain_secret=points.chain_secret, actor={"id": 1, "role": "root"})
        second = economy_layer_report(conn, chain_secret=points.chain_secret, actor={"id": 1, "role": "root"})
        conn.commit()

        event_count = conn.execute("SELECT COUNT(*) AS count FROM points_economy_events").fetchone()["count"]
        snapshot_count = conn.execute("SELECT COUNT(*) AS count FROM points_economy_snapshots").fetchone()["count"]
    finally:
        conn.close()

    assert first["bootstrap"]["created_count"] == 3
    assert second["bootstrap"]["created_count"] == 0
    assert event_count == 3
    assert snapshot_count == 1
    assert second["supply"]["max_supply"] == 100_000_000
    assert second["supply"]["reserved_locked"] == 40_000_000
    assert second["supply"]["releasable_supply"] == 60_000_000
    assert second["supply"]["minted_total"] == 20_000_000
    assert second["supply"]["fund_supply"] == 20_000_000
    assert second["supply"]["circulating_supply"] == 0
    assert second["funds"]["official_treasury"]["balance"] == 10_000_000
    assert second["funds"]["promo_fund"]["balance"] == 5_000_000
    assert second["funds"]["exchange_fund"]["balance"] == 5_000_000
    assert second["replay"]["derived_verify"]["ok"] is True


def test_repeated_bootstrap_five_times_does_not_duplicate_mint(tmp_path):
    points, conn = _open_economy(tmp_path)
    try:
        reports = [
            economy_layer_report(conn, chain_secret=points.chain_secret, actor={"id": 1, "role": "root"})
            for _ in range(5)
        ]
        conn.commit()
        event_count = conn.execute("SELECT COUNT(*) AS count FROM points_economy_events").fetchone()["count"]
        idempotency_count = conn.execute("SELECT COUNT(DISTINCT idempotency_key) AS count FROM points_economy_events").fetchone()["count"]
        snapshot_count = conn.execute("SELECT COUNT(*) AS count FROM points_economy_snapshots").fetchone()["count"]
    finally:
        conn.close()

    assert [item["bootstrap"]["created_count"] for item in reports] == [3, 0, 0, 0, 0]
    assert event_count == 3
    assert idempotency_count == 3
    assert snapshot_count == 1
    assert {item["supply"]["minted_total"] for item in reports} == {20_000_000}
    assert {item["replay"]["height"] for item in reports} == {3}


def test_bootstrap_accepts_legacy_branchless_idempotency_hashes(tmp_path):
    points, conn = _open_economy(tmp_path)
    try:
        economy_layer_report(conn, chain_secret=points.chain_secret, actor={"id": 1, "role": "root"})
        rows = conn.execute(
            """
            SELECT * FROM points_economy_events
            WHERE idempotency_key LIKE 'economy_bootstrap:%'
            ORDER BY id ASC
            """
        ).fetchall()
        assert len(rows) == 3
        conn.execute("DROP TRIGGER IF EXISTS trg_points_economy_events_no_update")
        conn.execute("DROP TRIGGER IF EXISTS trg_points_economy_events_no_delete")
        for row in rows:
            legacy_request_hash = sha256_text(
                canonical_json(
                    {
                        "event_type": row["event_type"],
                        "transaction_type": row["transaction_type"],
                        "source_fund_key": row["source_fund_key"],
                        "destination_fund_key": row["destination_fund_key"],
                        "amount": int(row["amount"]),
                        "metadata": {"bootstrap": True, "phase": "1A"},
                        "policy_version": row["policy_version"],
                    }
                )
            )
            row_payload = dict(row)
            row_payload["request_hash"] = legacy_request_hash
            conn.execute(
                "UPDATE points_economy_events SET request_hash=?, event_hash=? WHERE id=?",
                (legacy_request_hash, compute_economy_event_hash(row_payload), row["id"]),
            )

        points.ensure_schema(conn)
        second = economy_layer_report(conn, chain_secret=points.chain_secret, actor={"id": 1, "role": "root"})
        conn.commit()
    finally:
        conn.close()

    assert second["bootstrap"]["created_count"] == 0
    assert second["supply"]["minted_total"] == 20_000_000


def test_mint_cannot_exceed_releasable_supply_without_override(tmp_path):
    points, conn = _open_economy(tmp_path)
    try:
        economy_layer_report(conn, chain_secret=points.chain_secret, actor={"id": 1, "role": "root"})

        with pytest.raises(ValueError, match="mint would exceed releasable supply"):
            append_economy_event(
                conn,
                chain_secret=points.chain_secret,
                event_type="mint",
                transaction_type="manual_mint",
                source_fund_key="mint",
                destination_fund_key="official_treasury",
                amount=40_000_001,
                idempotency_key="manual-mint-over-cap",
                actor={"id": 1, "role": "root"},
            )

        replay = replay_economy_events(conn, chain_secret=points.chain_secret)
    finally:
        conn.close()

    assert replay["minted_total"] == 20_000_000
    assert replay["releasable_remaining"] == 40_000_000


def test_burn_only_appends_burned_total_and_never_goes_negative(tmp_path):
    points, conn = _open_economy(tmp_path)
    try:
        economy_layer_report(conn, chain_secret=points.chain_secret, actor={"id": 1, "role": "root"})
        append_economy_event(
            conn,
            chain_secret=points.chain_secret,
            event_type="burn",
            transaction_type="treasury_burn",
            source_fund_key="official_treasury",
            destination_fund_key="burn",
            amount=1_000,
            idempotency_key="burn:official:1000",
            actor={"id": 1, "role": "root"},
        )

        with pytest.raises(ValueError, match="source fund balance is insufficient"):
            append_economy_event(
                conn,
                chain_secret=points.chain_secret,
                event_type="burn",
                transaction_type="promo_burn",
                source_fund_key="promo_fund",
                destination_fund_key="burn",
                amount=5_000_001,
                idempotency_key="burn:promo:overdraft",
                actor={"id": 1, "role": "root"},
            )

        replay = replay_economy_events(conn, chain_secret=points.chain_secret)
    finally:
        conn.close()

    assert replay["burned_total"] == 1_000
    assert replay["active_supply"] == 19_999_000
    assert replay["balances"]["official_treasury"]["balance"] == 9_999_000
    assert replay["balances"]["burn"]["balance"] == 1_000
    assert replay["balances"]["burn"]["address"] == BURN_WALLET_ADDRESS


def test_replay_rejects_corrupt_burn_that_would_make_active_supply_negative(tmp_path):
    points, conn = _open_economy(tmp_path)
    try:
        now = utc_now()
        row_payload = {
            "event_uuid": "corrupt-burn-active-negative",
            "event_type": "burn",
            "transaction_type": "corrupt_direct_burn",
            "source_fund_key": None,
            "source_address": None,
            "destination_fund_key": "burn",
            "destination_address": "pc1corruptburn",
            "amount": 1,
            "idempotency_key": "corrupt:burn:active-negative",
            "request_hash": sha256_text("corrupt:burn:active-negative"),
            "policy_version": "phase1_sim_economy_v1",
            "metadata_json": "{}",
            "previous_event_hash": None,
            "created_at": now,
        }
        conn.execute(
            """
            INSERT INTO points_economy_events (
                event_uuid, event_type, transaction_type, source_fund_key, source_address,
                destination_fund_key, destination_address, amount, idempotency_key,
                request_hash, policy_version, status, metadata_json, previous_event_hash,
                event_hash, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'confirmed', ?, ?, ?, ?)
            """,
            (
                row_payload["event_uuid"],
                row_payload["event_type"],
                row_payload["transaction_type"],
                row_payload["source_fund_key"],
                row_payload["source_address"],
                row_payload["destination_fund_key"],
                row_payload["destination_address"],
                row_payload["amount"],
                row_payload["idempotency_key"],
                row_payload["request_hash"],
                row_payload["policy_version"],
                row_payload["metadata_json"],
                row_payload["previous_event_hash"],
                compute_economy_event_hash(row_payload),
                now,
            ),
        )

        with pytest.raises(ValueError, match="negative active supply"):
            replay_economy_events(conn, chain_secret=points.chain_secret)
    finally:
        conn.close()


def test_derived_balance_cache_must_verify_against_replay(tmp_path):
    points, conn = _open_economy(tmp_path)
    try:
        report = economy_layer_report(conn, chain_secret=points.chain_secret, actor={"id": 1, "role": "root"})
        assert report["replay"]["derived_verify"]["ok"] is True

        conn.execute("UPDATE points_economy_derived_balances SET balance=balance+1 WHERE fund_key='promo_fund'")
        tampered = verify_economy_derived_balances(conn, chain_secret=points.chain_secret)
        assert tampered["ok"] is False
        assert any(item["fund_key"] == "promo_fund" for item in tampered["mismatches"])

        replay = replay_economy_events(conn, chain_secret=points.chain_secret)
        rebuilt = rebuild_economy_derived_balances(conn, replay=replay)
        verified = verify_economy_derived_balances(conn, replay=replay)
    finally:
        conn.close()

    assert rebuilt["rebuilt"] is True
    assert verified["ok"] is True


def test_economic_incident_is_append_only_and_does_not_mutate_balance(tmp_path):
    points, conn = _open_economy(tmp_path)
    try:
        economy_layer_report(conn, chain_secret=points.chain_secret, actor={"id": 1, "role": "root"})
        before = replay_economy_events(conn, chain_secret=points.chain_secret)
        incident = append_economy_incident(
            conn,
            severity="warning",
            category="promo_drain",
            trigger="test trigger",
            automatic_actions=["notify_root"],
        )
        after = replay_economy_events(conn, chain_secret=points.chain_secret)

        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            conn.execute("UPDATE points_economy_incidents SET status='resolved' WHERE id=?", (incident["id"],))
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            conn.execute("DELETE FROM points_economy_incidents WHERE id=?", (incident["id"],))
    finally:
        conn.close()

    assert after["wallet_root_hash"] == before["wallet_root_hash"]
    assert after["minted_total"] == before["minted_total"]
    assert after["burned_total"] == before["burned_total"]


def test_economy_event_idempotency_replays_same_request_and_conflicts_on_payload_change(tmp_path):
    points, conn = _open_economy(tmp_path)
    try:
        economy_layer_report(conn, chain_secret=points.chain_secret, actor={"id": 1, "role": "root"})
        first, created = append_economy_event(
            conn,
            chain_secret=points.chain_secret,
            event_type="transfer",
            transaction_type="treasury_to_promo",
            source_fund_key="official_treasury",
            destination_fund_key="promo_fund",
            amount=123,
            idempotency_key="transfer:treasury-promo:123",
            metadata={"memo": "same request"},
            actor={"id": 1, "role": "root"},
        )
        replayed, replay_created = append_economy_event(
            conn,
            chain_secret=points.chain_secret,
            event_type="transfer",
            transaction_type="treasury_to_promo",
            source_fund_key="official_treasury",
            destination_fund_key="promo_fund",
            amount=123,
            idempotency_key="transfer:treasury-promo:123",
            metadata={"memo": "same request"},
            actor={"id": 1, "role": "root"},
        )

        with pytest.raises(ValueError, match="idempotency key conflict"):
            append_economy_event(
                conn,
                chain_secret=points.chain_secret,
                event_type="transfer",
                transaction_type="treasury_to_promo",
                source_fund_key="official_treasury",
                destination_fund_key="promo_fund",
                amount=124,
                idempotency_key="transfer:treasury-promo:123",
                metadata={"memo": "changed request"},
                actor={"id": 1, "role": "root"},
            )

        event_count = conn.execute(
            "SELECT COUNT(*) AS count FROM points_economy_events WHERE idempotency_key='transfer:treasury-promo:123'"
        ).fetchone()["count"]
    finally:
        conn.close()

    assert created is True
    assert replay_created is False
    assert replayed["event_uuid"] == first["event_uuid"]
    assert event_count == 1


def test_exchange_principal_lent_is_external_supply_not_formula_gap(tmp_path):
    points, conn = _open_economy(tmp_path)
    try:
        economy_layer_report(conn, chain_secret=points.chain_secret, actor={"id": 1, "role": "root"})
        append_economy_event(
            conn,
            chain_secret=points.chain_secret,
            event_type="trading_reserve_pool_flow",
            transaction_type="margin_principal_lent",
            source_fund_key="exchange_fund",
            destination_fund_key=None,
            destination_address="pc1borrower",
            amount=4_999_964,
            idempotency_key="margin:principal:loan:stress",
            metadata={"test": "loan drains liquid cash but remains a receivable"},
            actor={"id": 1, "role": "root"},
        )

        report = economy_layer_report(
            conn,
            chain_secret=points.chain_secret,
            actor={"id": 1, "role": "root"},
            circulation={"member_outstanding_points": 0, "root_outstanding_points": 0},
        )
    finally:
        conn.close()

    assert report["funds"]["exchange_fund"]["balance"] == 36
    assert report["supply"]["exchange_receivable_principal"] == 4_999_964
    assert report["supply"]["exchange_total_assets"] == 5_000_000
    assert report["supply"]["external_supply"] == 4_999_964
    assert report["supply_equation"]["economy_external_circulating_points"] == 4_999_964
    assert report["supply_equation"]["off_wallet_economy_external_points"] == 4_999_964
    assert report["supply_equation"]["actual_supply_equation_gap_points"] == 0
    assert report["supply_equation"]["bridged_supply_equation_gap_points"] == 0
    assert report["supply_equation"]["bridged_supply_equation_balanced"] is True
    assert report["health"]["status"] == "yellow"
    assert report["health"]["reasons"] == ["exchange_fund_liquidity_critical"]


def test_exchange_non_receivable_drain_stays_red(tmp_path):
    points, conn = _open_economy(tmp_path)
    try:
        economy_layer_report(conn, chain_secret=points.chain_secret, actor={"id": 1, "role": "root"})
        append_economy_event(
            conn,
            chain_secret=points.chain_secret,
            event_type="trading_reserve_pool_flow",
            transaction_type="margin_profit_paid",
            source_fund_key="exchange_fund",
            destination_fund_key=None,
            destination_address="pc1profittaker",
            amount=4_900_001,
            idempotency_key="margin:profit:large",
            metadata={"test": "non-receivable expense"},
            actor={"id": 1, "role": "root"},
        )

        report = economy_layer_report(conn, chain_secret=points.chain_secret, actor={"id": 1, "role": "root"})
    finally:
        conn.close()

    assert report["funds"]["exchange_fund"]["balance"] == 99_999
    assert report["supply"]["exchange_receivable_principal"] == 0
    assert report["supply"]["exchange_total_assets"] == 99_999
    assert report["supply_equation"]["actual_supply_equation_gap_points"] == 0
    assert report["health"]["status"] == "red"
    assert report["health"]["reasons"] == ["exchange_fund_assets_critical"]
