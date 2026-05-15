import json
import sqlite3
from pathlib import Path

import pytest

from services.points_chain import (
    DEFAULT_BACKUP_KEEP_DAILY,
    DEFAULT_BACKUP_KEEP_RECENT,
    DEFAULT_BACKUP_KEEP_WEEKLY,
    PointsLedgerService,
    ensure_points_economy_schema,
)


def _db(tmp_path):
    path = tmp_path / "points.db"

    def get_db():
        conn = sqlite3.connect(path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        # Phase 3: every connection must register app_mode() so the
        # BEFORE INSERT trigger on points_chain_blocks has something
        # to evaluate. These tests run as production-mode behavior.
        from services.platform.db_mode_triggers import register_app_mode_function
        register_app_mode_function(conn, mode_reader=lambda: "production")
        return conn

    conn = get_db()
    conn.execute(
        "CREATE TABLE users (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT NOT NULL UNIQUE, role TEXT NOT NULL DEFAULT 'user', status TEXT NOT NULL DEFAULT 'active')"
    )
    conn.execute(
        "INSERT INTO users (username, role, status) VALUES "
        "('alice', 'user', 'active'), "
        "('bob', 'manager', 'active'), "
        "('root', 'super_admin', 'active')"
    )
    ensure_points_economy_schema(conn)
    conn.commit()
    conn.close()
    return get_db


def _service(tmp_path):
    # Phase 7: chain writes require mode == 'production'. These tests
    # exercise the production-mode behavior of PointsChain; the new
    # production-only guard takes a mode_reader and refuses non-prod.
    return PointsLedgerService(
        get_db=_db(tmp_path),
        chain_secret="test-secret",
        backup_dir=tmp_path / "points_chain_backups",
        mode_reader=lambda: "production",
    )


def test_points_transaction_updates_wallet_and_hash_chain(tmp_path):
    service = _service(tmp_path)

    first = service.record_transaction(
        user_id=1,
        currency_type="points",
        direction="credit",
        amount=10,
        action_type="test_credit",
        idempotency_key="credit:1",
    )
    second = service.record_transaction(
        user_id=1,
        currency_type="points",
        direction="debit",
        amount=3,
        action_type="test_debit",
        idempotency_key="debit:1",
    )

    assert first["wallet"]["points_balance"] == 10
    assert second["wallet"]["points_balance"] == 7
    assert second["ledger"]["currency_type"] == "points"
    assert second["ledger"]["previous_ledger_hash"] == first["ledger"]["ledger_hash"]
    assert service.verify_chain()["ok"] is True


def test_rebuild_wallets_from_ledger_starts_its_own_transaction_when_needed(tmp_path):
    service = _service(tmp_path)
    service.record_transaction(
        user_id=1,
        currency_type="points",
        direction="credit",
        amount=10,
        action_type="test_credit",
        idempotency_key="credit:rebuild-wallets",
    )

    conn = service.get_db()
    try:
        assert conn.in_transaction is False
        rebuild = service._rebuild_wallets_from_ledger(conn)
        assert rebuild["wallets_rebuilt"] >= 1
        assert conn.in_transaction is False
    finally:
        conn.close()


def test_legacy_hard_currency_is_merged_into_single_points_balance(tmp_path):
    service = _service(tmp_path)

    first = service.record_transaction(
        user_id=1,
        currency_type="hard",
        direction="credit",
        amount=5,
        action_type="test_credit",
        idempotency_key="same-key",
    )
    second = service.record_transaction(
        user_id=1,
        currency_type="hard",
        direction="credit",
        amount=5,
        action_type="test_credit",
        idempotency_key="same-key",
    )

    assert first["created"] is True
    assert second["created"] is False
    assert second["wallet"]["points_balance"] == 5
    assert second["wallet"]["hard_balance"] == 0
    assert second["ledger"]["currency_type"] == "points"


def test_points_debit_cannot_make_wallet_negative(tmp_path):
    service = _service(tmp_path)

    with pytest.raises(ValueError, match="insufficient balance"):
        service.record_transaction(
            user_id=1,
            currency_type="points",
            direction="debit",
            amount=1,
            action_type="test_debit",
        )

    assert service.get_wallet(1)["points_balance"] == 0


def test_spend_points_uses_server_idempotency_when_client_omits_key(tmp_path):
    service = _service(tmp_path)
    service.record_transaction(
        user_id=1,
        currency_type="points",
        direction="credit",
        amount=100,
        action_type="test_credit",
        idempotency_key="credit:spend",
    )

    first = service.spend_points(user_id=1, item_key="post_cost_standard")
    second = service.spend_points(user_id=1, item_key="post_cost_standard")

    assert first["created"] is True
    assert second["created"] is False
    assert service.get_wallet(1)["points_balance"] == 99


def test_root_can_upsert_service_price_catalog_items(tmp_path):
    service = _service(tmp_path)
    item = service.upsert_catalog_item(
        actor={"id": 3, "username": "root", "role": "super_admin"},
        item_key="comfyui_txt2img_custom",
        item_name="ComfyUI 自定義生圖",
        category="comfyui",
        base_price=9,
        min_price=1,
        max_price=99,
        enabled=True,
        metadata={"note": "root configurable"},
    )

    assert item["item_key"] == "comfyui_txt2img_custom"
    assert item["base_price"] == 9
    catalog = service.list_catalog(include_disabled=True, category="comfyui")
    assert any(row["item_key"] == "comfyui_txt2img_custom" for row in catalog)


def test_cloud_drive_price_catalog_item_requires_storage_metadata(tmp_path):
    service = _service(tmp_path)
    with pytest.raises(ValueError, match="storage_bytes"):
        service.upsert_catalog_item(
            actor={"id": 3, "username": "root", "role": "super_admin"},
            item_key="cloud_storage_custom_missing",
            item_name="缺少容量資料",
            category="cloud_drive",
            base_price=10,
            enabled=True,
            metadata={},
        )


def test_ledger_metadata_has_hard_size_cap(tmp_path):
    service = _service(tmp_path)

    with pytest.raises(ValueError, match="public_metadata is too large"):
        service.record_transaction(
            user_id=1,
            currency_type="points",
            direction="credit",
            amount=1,
            action_type="test_large_metadata",
            public_metadata={"blob": "x" * 5000},
        )


def test_signup_bonus_is_single_currency_and_idempotent(tmp_path):
    service = _service(tmp_path)

    first = service.award_signup_bonus(user_id=1, actor={"id": 1, "username": "alice", "role": "user"})
    second = service.award_signup_bonus(user_id=1, actor={"id": 1, "username": "alice", "role": "user"})

    assert first["created"] is True
    assert second["created"] is False
    assert second["wallet"]["points_balance"] == 10
    assert second["ledger"]["currency_type"] == "points"


def test_initial_grants_create_genesis_block_once_for_default_accounts(tmp_path):
    service = _service(tmp_path)

    first = service.bootstrap_admin_initial_grants(actor={"username": "system", "role": "system"}, seal_genesis=True)
    second = service.bootstrap_admin_initial_grants(actor={"username": "system", "role": "system"}, seal_genesis=True)

    assert first["created_count"] == 2
    assert first["created"][0]["username"] == "bob"
    assert first["created"][0]["amount"] == 100
    assert first["created"][1]["username"] == "alice"
    assert first["created"][1]["amount"] == 10
    assert first["sealed"]["sealed"] is True
    assert first["sealed"]["block"]["block_number"] == 1
    assert second["created_count"] == 0
    assert service.get_wallet(2)["points_balance"] == 100
    assert service.get_wallet(1)["points_balance"] == 10
    assert service.get_wallet(3)["points_balance"] == 0
    assert service.verify_chain()["counts"]["sealed_blocks"] == 1
    actions = [row["action_type"] for row in service.root_report()["adjustments"]]
    assert "admin_initial_grant" in actions
    assert "user_initial_grant" in actions


def test_admin_weekly_salary_is_idempotent_by_week(tmp_path):
    service = _service(tmp_path)

    first = service.award_admin_weekly_salaries(salary_week="2026-W18", actor={"username": "system", "role": "system"})
    second = service.award_admin_weekly_salaries(salary_week="2026-W18", actor={"username": "system", "role": "system"})

    assert first["created_count"] == 1
    assert second["created_count"] == 0
    assert service.get_wallet(2)["points_balance"] == 100
    assert service.get_wallet(3)["points_balance"] == 0


def test_points_ledger_is_append_only(tmp_path):
    service = _service(tmp_path)
    tx = service.record_transaction(
        user_id=1,
        currency_type="points",
        direction="credit",
        amount=10,
        action_type="test_credit",
    )
    conn = service.get_db()
    try:
        with pytest.raises(sqlite3.DatabaseError, match="append-only"):
            conn.execute("DELETE FROM points_ledger WHERE ledger_uuid=?", (tx["ledger"]["ledger_uuid"],))
        with pytest.raises(sqlite3.DatabaseError, match="immutable"):
            conn.execute("UPDATE points_ledger SET amount=99 WHERE ledger_uuid=?", (tx["ledger"]["ledger_uuid"],))
    finally:
        conn.close()


def test_points_chain_seal_verify_and_proof(tmp_path):
    service = _service(tmp_path)
    tx = service.record_transaction(
        user_id=1,
        currency_type="points",
        direction="credit",
        amount=10,
        action_type="test_credit",
    )

    sealed = service.seal_block(actor={"id": 3, "username": "root", "role": "super_admin"}, limit=100)
    proof = service.ledger_proof(tx["ledger"]["ledger_uuid"])
    verification = service.verify_chain()

    assert sealed["sealed"] is True
    assert sealed["block"]["ledger_count"] == 1
    assert proof["sealed"] is True
    assert proof["block_number"] == sealed["block"]["block_number"]
    assert proof["ledger_hash"] == tx["ledger"]["ledger_hash"]
    assert verification["ok"] is True
    assert verification["counts"]["unsealed_entries"] == 0
    backups = service.list_ledger_backups()
    assert backups[0]["kind"] == "block_sealed"
    assert backups[0]["verified"] == 1
    assert backups[0]["ledger_row_count"] == 1


def test_points_chain_verify_identifies_tampered_ledger(tmp_path):
    service = _service(tmp_path)
    tx = service.record_transaction(
        user_id=1,
        currency_type="points",
        direction="credit",
        amount=10,
        action_type="test_credit",
    )
    conn = service.get_db()
    try:
        conn.execute("DROP TRIGGER trg_points_ledger_core_immutable")
        conn.execute("UPDATE points_ledger SET amount=99 WHERE ledger_uuid=?", (tx["ledger"]["ledger_uuid"],))
        conn.commit()
    finally:
        conn.close()

    verification = service.verify_chain()
    assert verification["ok"] is False
    error = next(row for row in verification["errors"] if row["type"] == "ledger_hash")
    assert error["ledger_uuid"] == tx["ledger"]["ledger_uuid"]
    assert error["ledger"]["amount"] == 99
    assert error["expected_ledger_hash"]
    assert error["actual_ledger_hash"] == tx["ledger"]["ledger_hash"]

    report = service.root_report()
    flagged = next(row for row in report["high_risk_ledger"] if row["ledger_uuid"] == tx["ledger"]["ledger_uuid"])
    assert flagged["verification_status"] == "tampered"
    assert flagged["verification_errors"][0]["type"] == "ledger_hash"
    recovery = service.safe_mode_status()
    assert recovery["safe_mode"] is True
    assert recovery["forensic_bundle_id"]
    assert recovery["restore_plan"]["auto_apply"] is False


def test_points_chain_safe_mode_blocks_writes_and_root_restore_rebuilds_wallets(tmp_path):
    service = _service(tmp_path)
    actor = {"id": 3, "username": "root", "role": "super_admin"}
    tx = service.record_transaction(
        user_id=1,
        currency_type="points",
        direction="credit",
        amount=30,
        action_type="test_credit",
    )
    sealed = service.seal_block(actor=actor, limit=100)
    backup_id = sealed["backup"]["backup_id"]

    conn = service.get_db()
    try:
        conn.execute("DROP TRIGGER trg_points_ledger_core_immutable")
        conn.execute("UPDATE points_ledger SET amount=99 WHERE ledger_uuid=?", (tx["ledger"]["ledger_uuid"],))
        conn.execute("UPDATE points_wallets SET soft_balance=999 WHERE user_id=1")
        conn.commit()
    finally:
        conn.close()

    verification = service.verify_chain()
    assert verification["ok"] is False
    assert service.safe_mode_status()["safe_mode"] is True

    with pytest.raises(ValueError, match="safe mode"):
        service.record_transaction(user_id=1, currency_type="points", direction="credit", amount=1, action_type="blocked")
    with pytest.raises(ValueError, match="safe mode"):
        service.seal_block(actor=actor, limit=100)

    with pytest.raises(ValueError, match="confirm"):
        service.restore_from_backup(actor=actor, backup_id=backup_id, confirm="wrong")

    restored = service.restore_from_backup(actor=actor, backup_id=backup_id, confirm="RESTORE POINTSCHAIN")
    assert restored["ok"] is True
    assert restored["verification"]["ok"] is True
    assert service.safe_mode_status()["safe_mode"] is False
    assert service.get_wallet(1)["points_balance"] == 30
    assert service.verify_chain()["ok"] is True


def test_points_chain_detects_wallet_tamper_and_restore_reports_success(tmp_path):
    service = _service(tmp_path)
    actor = {"id": 3, "username": "root", "role": "super_admin"}
    service.record_transaction(
        user_id=1,
        currency_type="points",
        direction="credit",
        amount=45,
        action_type="test_credit",
    )
    sealed = service.seal_block(actor=actor, limit=100)
    backup_id = sealed["backup"]["backup_id"]

    conn = service.get_db()
    try:
        conn.execute("UPDATE points_wallets SET soft_balance=999, total_soft_earned=999 WHERE user_id=1")
        conn.commit()
    finally:
        conn.close()

    verification = service.verify_chain()
    assert verification["ok"] is False
    assert verification["errors"][0]["type"] == "wallet_ledger_mismatch"
    assert service.safe_mode_status()["safe_mode"] is True

    restored = service.restore_from_backup(actor=actor, backup_id=backup_id, confirm="RESTORE POINTSCHAIN")
    assert restored["ok"] is True
    assert restored["msg"] == "PointsChain 已還原並驗證完成"
    assert restored["wallet_rebuild"]["wallets_rebuilt"] >= 1
    assert restored["verification"]["ok"] is True
    assert restored["recovery"]["safe_mode"] is False
    assert service.get_wallet(1)["points_balance"] == 45


def test_tampered_ledger_cannot_be_rolled_back_from_dirty_row(tmp_path):
    service = _service(tmp_path)
    tx = service.record_transaction(
        user_id=1,
        currency_type="points",
        direction="credit",
        amount=10,
        action_type="test_credit",
    )
    conn = service.get_db()
    try:
        conn.execute("DROP TRIGGER trg_points_ledger_core_immutable")
        conn.execute("UPDATE points_ledger SET amount=99 WHERE ledger_uuid=?", (tx["ledger"]["ledger_uuid"],))
        conn.commit()
    finally:
        conn.close()

    with pytest.raises(ValueError, match="tampered"):
        service.rollback_ledger(
            actor={"id": 3, "username": "root", "role": "super_admin"},
            ledger_uuid=tx["ledger"]["ledger_uuid"],
            reason="dirty rollback should be blocked",
        )


def test_points_chain_seal_adds_local_signature_and_root_report(tmp_path):
    service = _service(tmp_path)
    service.record_transaction(
        user_id=1,
        currency_type="points",
        direction="credit",
        amount=10,
        action_type="test_credit",
    )

    sealed = service.seal_block(actor={"id": 3, "username": "root", "role": "super_admin"}, limit=100)
    service.admin_adjust(
        actor={"id": 3, "username": "root", "role": "super_admin"},
        user_id=1,
        currency_type="points",
        direction="credit",
        amount=7,
        reason="manual bonus",
    )
    report = service.root_report()

    assert sealed["sealed"] is True
    assert report["verification"]["ok"] is True
    assert report["blocks"][0]["signature_algorithm"] == "hmac-sha256"
    assert report["audit_logs"][0]["event_type"] in {"POINTS_LEDGER_BACKUP_CREATED", "POINTS_BLOCK_SEALED", "LEDGER_APPEND"}
    assert report["block_schedule"]["mode"] == "hybrid"
    assert report["block_schedule"]["ledger_threshold"] == 30
    assert report["block_schedule"]["max_interval_minutes"] == 24 * 60
    assert report["block_schedule"]["unsealed_entries"] == 0
    assert report["adjustments"][0]["actor_username"] == "root"
    assert report["adjustments"][0]["target_username"] == "alice"
    assert report["adjustments"][0]["signed_amount"] == 7
    assert report["adjustments"][0]["reason"] == "manual bonus"
    report_json = json.dumps(report, ensure_ascii=False)
    assert '"soft"' not in report_json
    assert '"hard"' not in report_json


def test_root_report_sanitizes_legacy_currency_audit_text(tmp_path):
    service = _service(tmp_path)
    service.record_transaction(
        user_id=1,
        currency_type="points",
        direction="credit",
        amount=10,
        action_type="test_credit",
    )
    conn = service.get_db()
    try:
        conn.execute(
            """
            INSERT INTO points_chain_audit_logs (
                event_type, severity, actor_user_id, actor_role, target_user_id,
                related_ledger_id, related_block_id, message, metadata_json, created_at
            ) VALUES ('LEGACY_AUDIT', 'info', NULL, NULL, 1, NULL, NULL, ?, ?, '2026-04-29T00:00:00Z')
            """,
            (
                "credit 10 soft for user 1",
                json.dumps({"currency_type": "soft", "note": "legacy hard reward"}),
            ),
        )
        conn.commit()
    finally:
        conn.close()

    report = service.root_report()
    legacy = next(row for row in report["audit_logs"] if row["event_type"] == "LEGACY_AUDIT")

    assert legacy["message"] == "credit 10 points for user 1"
    assert legacy["metadata"]["currency_type"] == "points"
    assert legacy["metadata"]["note"] == "legacy points reward"
    assert '"soft"' not in json.dumps(report, ensure_ascii=False)
    assert '"hard"' not in json.dumps(report, ensure_ascii=False)


def test_root_rollback_creates_compensating_append_only_ledger(tmp_path):
    service = _service(tmp_path)
    tx = service.record_transaction(
        user_id=1,
        currency_type="points",
        direction="credit",
        amount=10,
        action_type="test_credit",
    )

    rollback = service.rollback_ledger(
        actor={"id": 3, "username": "root", "role": "super_admin"},
        ledger_uuid=tx["ledger"]["ledger_uuid"],
        reason="emergency correction",
    )

    assert rollback["rollback_ledger"]["direction"] == "reverse"
    assert rollback["rollback_ledger"]["reference_id"] == tx["ledger"]["ledger_uuid"]
    assert rollback["wallet"]["points_balance"] == 0
    assert service.verify_chain()["ok"] is True
    audit_events = [row["event_type"] for row in service.list_chain_audit_logs(limit=10)]
    assert "LEDGER_ROLLBACK" in audit_events

    with pytest.raises(ValueError, match="already reversed"):
        service.rollback_ledger(
            actor={"id": 3, "username": "root", "role": "super_admin"},
            ledger_uuid=tx["ledger"]["ledger_uuid"],
            reason="duplicate correction",
        )


def test_root_can_sanction_wallet_and_freeze_points(tmp_path):
    service = _service(tmp_path)
    root_actor = {"id": 3, "username": "root", "role": "super_admin"}
    service.record_transaction(
        user_id=1,
        currency_type="points",
        direction="credit",
        amount=20,
        action_type="test_credit",
    )

    frozen = service.sanction_wallet(
        actor=root_actor,
        user_id=1,
        wallet_status="frozen",
        risk_level="high",
        reason="abuse investigation",
        freeze_amount=7,
    )

    assert frozen["wallet"]["wallet_status"] == "frozen"
    assert frozen["wallet"]["risk_level"] == "high"
    assert frozen["wallet"]["points_balance"] == 13
    assert frozen["wallet"]["points_frozen"] == 7
    assert frozen["ledgers"][0]["direction"] == "freeze"

    with pytest.raises(ValueError, match="wallet is frozen"):
        service.record_transaction(
            user_id=1,
            currency_type="points",
            direction="debit",
            amount=1,
            action_type="test_debit",
        )

    active = service.sanction_wallet(
        actor=root_actor,
        user_id=1,
        wallet_status="active",
        risk_level="normal",
        reason="appeal accepted",
        unfreeze_amount=7,
    )

    assert active["wallet"]["wallet_status"] == "active"
    assert active["wallet"]["risk_level"] == "normal"
    assert active["wallet"]["points_balance"] == 20
    assert active["wallet"]["points_frozen"] == 0
    assert active["ledgers"][0]["direction"] == "unfreeze"
    audit_events = [row["event_type"] for row in service.list_chain_audit_logs(limit=20)]
    assert "WALLET_SANCTION" in audit_events

    limited = service.sanction_wallet(
        actor=root_actor,
        user_id=1,
        wallet_status="limited",
        risk_level="watch",
        reason="temporary spend limit",
    )
    assert limited["wallet"]["wallet_status"] == "limited"
    with pytest.raises(ValueError, match="wallet is limited"):
        service.record_transaction(
            user_id=1,
            currency_type="points",
            direction="debit",
            amount=1,
            action_type="test_limited_spend",
        )

    with pytest.raises(ValueError, match="root wallet cannot be sanctioned"):
        service.sanction_wallet(
            actor=root_actor,
            user_id=3,
            wallet_status="closed",
            risk_level="blocked",
            reason="root should not be point-sanctioned",
        )


def test_points_chain_auto_seals_when_hybrid_count_threshold_is_met(tmp_path):
    service = _service(tmp_path)
    actor = {"id": 3, "username": "root", "role": "super_admin"}
    for idx in range(9):
        service.record_transaction(
            user_id=1,
            currency_type="points",
            direction="credit",
            amount=1,
            action_type=f"test_credit_{idx}",
        )

    pending = service.seal_due_block(actor=actor, ledger_threshold=10)
    assert pending["sealed"] is False
    assert pending["schedule"]["unsealed_entries"] == 9
    assert pending["schedule"]["entries_remaining"] == 1

    service.record_transaction(
        user_id=1,
        currency_type="points",
        direction="credit",
        amount=1,
        action_type="test_credit_9",
    )
    sealed = service.seal_due_block(actor=actor, ledger_threshold=10)

    assert sealed["sealed"] is True
    assert sealed["block"]["ledger_count"] == 10
    assert service.verify_chain()["counts"]["unsealed_entries"] == 0


def test_points_chain_not_due_schedule_avoids_full_verification(tmp_path):
    service = _service(tmp_path)
    actor = {"id": 3, "username": "root", "role": "super_admin"}
    for idx in range(3):
        service.record_transaction(
            user_id=1,
            currency_type="points",
            direction="credit",
            amount=1,
            action_type=f"schedule_light_check_{idx}",
        )

    calls = 0

    def counted_verify_chain():
        nonlocal calls
        calls += 1
        raise AssertionError("seal_due_block should not verify the whole chain before the schedule is due")

    service.verify_chain = counted_verify_chain
    pending = service.seal_due_block(actor=actor, ledger_threshold=10)

    assert pending["sealed"] is False
    assert pending["schedule"]["unsealed_entries"] == 3
    assert calls == 0


def test_points_chain_root_report_reuses_single_verification(tmp_path):
    service = _service(tmp_path)
    service.record_transaction(
        user_id=1,
        currency_type="points",
        direction="credit",
        amount=10,
        action_type="root_report_single_verify",
    )
    original_verify_chain = service.verify_chain
    calls = 0

    def counted_verify_chain():
        nonlocal calls
        calls += 1
        return original_verify_chain()

    service.verify_chain = counted_verify_chain
    report = service.root_report()

    assert calls == 1
    assert report["verification"]["ok"] is True
    assert report["stats"]["chain"]["counts"] == report["verification"]["counts"]
    assert report["block_schedule"]["chain_ok"] is True


def test_points_chain_runtime_reset_clears_active_ledger_and_leaves_reset_audit(tmp_path):
    service = _service(tmp_path)
    actor = {"id": 3, "username": "root", "role": "super_admin"}
    service.record_transaction(
        user_id=1,
        currency_type="points",
        direction="credit",
        amount=10,
        action_type="test_credit",
        idempotency_key="credit:reset-test",
    )
    sealed = service.seal_block(actor=actor)
    assert sealed["sealed"] is True
    backup_root = tmp_path / "points_chain_backups" / "backups"
    assert backup_root.exists()
    assert service.list_ledger_backups()
    assert service.verify_chain()["counts"]["ledger_entries"] == 1

    reset = service.reset_runtime_chain(actor=actor, reason="server reset", pre_reset_snapshot_id="snap_test")

    assert reset["ok"] is True
    verification = service.verify_chain()
    assert verification["ok"] is True
    assert verification["counts"]["ledger_entries"] == 0
    assert verification["counts"]["sealed_blocks"] == 0
    assert service.list_ledger_backups() == []
    assert list(backup_root.iterdir()) == []
    assert service.get_wallet(1)["points_balance"] == 0
    audit_events = service.list_chain_audit_logs(limit=5)
    assert audit_events[0]["event_type"] == "POINTS_CHAIN_RESET"


def test_high_risk_admin_adjust_forces_block(tmp_path):
    service = _service(tmp_path)
    result = service.admin_adjust(
        actor={"id": 3, "username": "root", "role": "super_admin"},
        user_id=1,
        currency_type="points",
        direction="credit",
        amount=5,
        reason="manual correction",
    )

    assert result["forced_block"]["sealed"] is True
    assert result["forced_block"]["reason"] == "admin_adjust"
    assert service.verify_chain()["counts"]["unsealed_entries"] == 0


def test_admin_adjust_is_idempotent_for_client_key(tmp_path):
    service = _service(tmp_path)
    actor = {"id": 3, "username": "root", "role": "super_admin"}

    first = service.admin_adjust(
        actor=actor,
        user_id=1,
        currency_type="points",
        direction="credit",
        amount=5,
        reason="manual correction",
        idempotency_key="adjust-click-1",
    )
    second = service.admin_adjust(
        actor=actor,
        user_id=1,
        currency_type="points",
        direction="credit",
        amount=5,
        reason="manual correction",
        idempotency_key="adjust-click-1",
    )

    assert first["created"] is True
    assert second["created"] is False
    assert service.get_wallet(1)["points_balance"] == 5
    adjustments = [
        row for row in service.list_ledger(user_id=1, include_user_id=True)
        if row["action_type"] == "admin_adjust_credit"
    ]
    assert len(adjustments) == 1


def test_admin_adjust_without_client_key_has_auto_idempotency_window(tmp_path, monkeypatch):
    service = _service(tmp_path)
    actor = {"id": 3, "username": "root", "role": "super_admin"}
    monkeypatch.setattr("services.points_chain.time.time", lambda: 1_800_000_000)

    first = service.admin_adjust(
        actor=actor,
        user_id=1,
        currency_type="points",
        direction="credit",
        amount=1,
        reason="manual correction",
    )
    second = service.admin_adjust(
        actor=actor,
        user_id=1,
        currency_type="points",
        direction="credit",
        amount=1,
        reason="manual correction",
    )

    assert first["created"] is True
    assert second["created"] is False
    assert service.get_wallet(1)["points_balance"] == 1

    debit = service.admin_adjust(
        actor=actor,
        user_id=1,
        currency_type="points",
        direction="debit",
        amount=1,
        reason="manual correction",
    )
    duplicate_debit = service.admin_adjust(
        actor=actor,
        user_id=1,
        currency_type="points",
        direction="debit",
        amount=1,
        reason="manual correction",
    )

    assert debit["created"] is True
    assert duplicate_debit["created"] is False
    assert service.get_wallet(1)["points_balance"] == 0


def test_points_chain_backup_pruning_uses_small_site_retention(tmp_path):
    assert DEFAULT_BACKUP_KEEP_RECENT == 5
    assert DEFAULT_BACKUP_KEEP_DAILY == 7
    assert DEFAULT_BACKUP_KEEP_WEEKLY == 4

    service = _service(tmp_path)
    conn = service.get_db()
    backup_root = tmp_path / "points_chain_backups" / "backups"
    try:
        service.ensure_schema(conn)
        for day in range(21):
            backup_id = f"backup-{day:02d}"
            created_at = f"2026-04-{29 - day:02d}T00:00:00Z"
            backup_path = backup_root / backup_id
            backup_path.mkdir(parents=True)
            (backup_path / "manifest.json").write_text("{}", encoding="utf-8")
            (backup_path / "data.json").write_text("{}", encoding="utf-8")
            conn.execute(
                """
                INSERT INTO points_chain_backup_catalog (
                    backup_id, kind, created_at, chain_height, latest_block_hash,
                    ledger_row_count, wallet_count, schema_version, backup_path,
                    manifest_path, files_hash, signature, verified, verification_json, reason
                ) VALUES (?, 'scheduled', ?, ?, ?, 0, 0, 1, ?, ?, 'hash', 'sig', 1, '{}', 'test')
                """,
                (
                    backup_id,
                    created_at,
                    day,
                    f"hash-{day}",
                    str(backup_path),
                    str(backup_path / "manifest.json"),
                ),
            )
        conn.commit()

        service._prune_ledger_backups(conn)
        conn.commit()

        kept = [
            row["backup_id"]
            for row in conn.execute("SELECT backup_id FROM points_chain_backup_catalog ORDER BY created_at DESC").fetchall()
        ]
        kept_paths = sorted(path.name for path in Path(backup_root).iterdir())
    finally:
        conn.close()

    assert len(kept) <= DEFAULT_BACKUP_KEEP_RECENT + DEFAULT_BACKUP_KEEP_DAILY + DEFAULT_BACKUP_KEEP_WEEKLY
    assert kept[:DEFAULT_BACKUP_KEEP_RECENT] == [f"backup-{idx:02d}" for idx in range(DEFAULT_BACKUP_KEEP_RECENT)]
    assert "backup-20" not in kept
    assert sorted(kept) == kept_paths
