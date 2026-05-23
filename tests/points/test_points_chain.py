import base64
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec, utils

from services.points_chain import (
    BURN_WALLET_ADDRESS,
    BIRTHDAY_GIFT_POINTS,
    DEFAULT_BACKUP_KEEP_DAILY,
    DEFAULT_BACKUP_KEEP_RECENT,
    DEFAULT_BACKUP_KEEP_WEEKLY,
    PointsLedgerService,
    address_from_public_key,
    bind_self_custody_wallet,
    create_official_hot_wallet,
    ensure_points_economy_schema,
    wallet_binding_payload,
    wallet_service_fee_payload,
)
from services.points_chain.economy_layer import economy_fund_address
from services.points_chain.schema import canonical_json, compute_block_hash, compute_ledger_hash, merkle_root


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


def _official_hot_wallet(service, user_id):
    conn = service.get_db()
    try:
        service.ensure_schema(conn)
        wallet = create_official_hot_wallet(conn, user_id=user_id, chain_secret=service.chain_secret)
        conn.commit()
        return wallet
    finally:
        conn.close()


def _b64url(data):
    return base64.urlsafe_b64encode(bytes(data)).decode("ascii").rstrip("=")


def _public_jwk(private_key):
    numbers = private_key.public_key().public_numbers()
    return {
        "kty": "EC",
        "crv": "P-256",
        "x": _b64url(numbers.x.to_bytes(32, "big")),
        "y": _b64url(numbers.y.to_bytes(32, "big")),
    }


def _signature(private_key, payload):
    der = private_key.sign(canonical_json(payload).encode("utf-8"), ec.ECDSA(hashes.SHA256()))
    r, s = utils.decode_dss_signature(der)
    return _b64url(r.to_bytes(32, "big") + s.to_bytes(32, "big"))


def _force_request_proved(service, tx_hash):
    proved_at = (datetime.now(timezone.utc) - timedelta(seconds=600)).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    conn = service.get_db()
    try:
        service.ensure_schema(conn)
        conn.execute(
            "UPDATE points_chain_transfer_requests SET created_at=? WHERE tx_group_hash=?",
            (proved_at, tx_hash),
        )
        conn.commit()
    finally:
        conn.close()


def _set_governance_timelock_ready(service, proposal_uuid):
    conn = service.get_db()
    try:
        service.ensure_schema(conn)
        conn.execute(
            "UPDATE points_chain_governance_proposals SET timelock_until='2026-01-01T00:00:00Z', timelock_ends_at='2026-01-01T00:00:00Z' WHERE proposal_uuid=?",
            (proposal_uuid,),
        )
        conn.commit()
    finally:
        conn.close()


def _official_treasury_grant_via_governance(service, *, destination_wallet_address, amount, request_uuid, action_type="TREASURY_TRANSFER"):
    root = {"id": 3, "username": "root", "role": "super_admin"}
    manager = {"id": 2, "username": "bob", "role": "manager"}
    root_wallet = _official_hot_wallet(service, 3)
    manager_wallet = _official_hot_wallet(service, 2)
    created = service.create_treasury_transfer_proposal(
        actor=manager,
        destination_wallet_address=destination_wallet_address,
        amount=amount,
        reason="governance official transfer",
        reference=request_uuid,
        action_type=action_type,
    )
    proposal_uuid = created["proposal"]["proposal_uuid"]
    service.cast_governance_vote(actor=root, proposal_uuid=proposal_uuid, vote="yes")
    service.cast_governance_vote(actor=manager, proposal_uuid=proposal_uuid, vote="yes")
    _set_governance_timelock_ready(service, proposal_uuid)
    service.sign_governance_multisig(actor=root, proposal_uuid=proposal_uuid, signer_wallet_address=root_wallet["address"])
    signed = service.sign_governance_multisig(actor=manager, proposal_uuid=proposal_uuid, signer_wallet_address=manager_wallet["address"])
    assert signed["multisig"]["ready"] is True
    executed = service.execute_governance_proposal(actor=manager, proposal_uuid=proposal_uuid)
    return executed["result"]["transfer"], proposal_uuid


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


def test_economy_stats_reports_member_circulating_supply(tmp_path):
    service = _service(tmp_path)
    service.record_transaction(
        user_id=1,
        currency_type="points",
        direction="credit",
        amount=100,
        action_type="admin_adjust_credit",
        idempotency_key="member:credit",
    )
    service.record_transaction(
        user_id=1,
        currency_type="points",
        direction="debit",
        amount=30,
        action_type="spend:post_cost_standard",
        idempotency_key="member:debit",
    )
    service.record_transaction(
        user_id=3,
        currency_type="points",
        direction="credit",
        amount=50,
        action_type="admin_adjust_credit",
        idempotency_key="root:credit",
    )

    stats = service.economy_stats()
    circulation = stats["circulation"]
    bridge = stats["economy_layer"]["legacy_bridge"]

    assert circulation["outstanding_points"] == 120
    assert circulation["member_outstanding_points"] == 70
    assert circulation["root_outstanding_points"] == 50
    assert circulation["member_wallet_count"] == 1
    assert circulation["root_wallet_count"] == 1
    assert circulation["ledger_net_points"] == 120
    assert circulation["member_ledger_net_points"] == 70
    assert circulation["member_supply_gap_points"] == 0
    assert bridge["legacy_outstanding_points"] == 70
    assert bridge["root_outstanding_points"] == 50
    assert bridge["total_legacy_outstanding_points"] == 120
    assert bridge["unfunded_legacy_outstanding_points"] == 0
    assert bridge["promo_balance"] == 5_000_000
    assert bridge["promo_balance_after_required_debit"] == 5_000_000
    assert bridge["actual_supply_equation_gap_points"] == 0
    assert bridge["bridged_supply_equation_gap_points"] == 0
    assert bridge["bridged_supply_equation_balanced"] is True


def test_unknown_ledger_actions_do_not_guess_fund_flows(tmp_path):
    service = _service(tmp_path)

    tx = service.record_transaction(
        user_id=1,
        currency_type="points",
        direction="credit",
        amount=100,
        action_type="legacy_unknown_credit",
        idempotency_key="unknown:credit",
    )

    stats = service.economy_stats()["economy_layer"]
    ledger = service.list_ledger(user_id=1, limit=1)[0]

    assert tx["created"] is True
    assert stats["funds"]["official_treasury"]["balance"] == 10_000_000
    assert stats["funds"]["promo_fund"]["balance"] == 5_000_000
    assert stats["funds"]["exchange_fund"]["balance"] == 5_000_000
    assert ledger["wallet_flow"]["walletized"] is False
    assert "不再自動套用基金" in ledger["wallet_flow"]["walletization_note"]


def test_official_wallet_grant_debits_official_fund_by_wallet_address(tmp_path):
    service = _service(tmp_path)
    destination = _official_hot_wallet(service, 2)

    result, _proposal_uuid = _official_treasury_grant_via_governance(
        service,
        destination_wallet_address=destination["address"],
        amount=10_000,
        request_uuid="official-wallet-grant-1",
    )

    stats = service.economy_stats()["economy_layer"]

    assert result["transaction"]["wallet_flow"]["destination_wallet_address"] == destination["address"]
    assert result["transaction"]["action_type"] == "official_wallet_grant"
    assert result["transaction"]["status"] == "pending"
    assert service.explorer_wallet(destination["address"])["wallet"]["points_balance"] == 0
    assert stats["funds"]["official_treasury"]["balance"] == 10_000_000
    assert stats["supply"]["circulating_supply"] == 0
    assert service.list_ledger(user_id=2, limit=1) == []

    _force_request_proved(service, result["transaction_hash"])
    proved = service.explorer_transaction(result["transaction_hash"])["transaction"]
    stats = service.economy_stats()["economy_layer"]
    ledger = service.list_ledger(user_id=2, limit=1)[0]

    assert proved["status"] == "confirmed"
    assert proved["finality"]["finality_status"] == "proved"
    assert stats["funds"]["official_treasury"]["balance"] == 9_990_000
    assert stats["supply"]["circulating_supply"] == 10_000
    assert stats["supply_equation"]["official_treasury_balance"] == 9_990_000
    assert stats["supply_equation"]["total_legacy_outstanding_points"] == 10_000
    assert stats["supply_equation"]["actual_supply_equation_gap_points"] == 0
    assert ledger["wallet_flow"]["source_label"] == "官方 Treasury 錢包"
    assert ledger["action_type"] == "official_wallet_grant"
    assert ledger["wallet_flow"]["destination_label"] in {"用戶模擬鏈錢包", "Legacy 帳本身份"}
    assert ledger["wallet_flow"]["walletized"] is True


def test_official_treasury_can_replenish_exchange_fund_as_pending_transaction(tmp_path):
    service = _service(tmp_path)
    actor = {"id": 3, "username": "root", "role": "super_admin"}
    exchange_address = economy_fund_address(service.chain_secret, "exchange_fund")
    before = service.economy_stats()["economy_layer"]

    result, _proposal_uuid = _official_treasury_grant_via_governance(
        service,
        destination_wallet_address=exchange_address,
        amount=123,
        request_uuid="official-fund-transfer-exchange-1",
        action_type="EXCHANGE_FUND_REPLENISH",
    )
    pending = service.economy_stats()["economy_layer"]
    root_transactions = service.list_wallet_transactions(user_id=3, actor=actor)

    assert result["created"] is True
    assert result["destination_fund_key"] == "exchange_fund"
    assert result["transaction"]["action_type"] == "official_fund_transfer"
    assert result["transaction"]["status"] == "pending"
    assert result["transaction"]["wallet_flow"]["destination_fund_key"] == "exchange_fund"
    assert result["wallet"] is None
    assert pending["funds"]["exchange_fund"]["balance"] == before["funds"]["exchange_fund"]["balance"]
    assert root_transactions["transactions"][0]["direction"] == "official_fund_transfer"
    assert root_transactions["transactions"][0]["status"] == "pending"

    _force_request_proved(service, result["transaction_hash"])
    proved = service.explorer_transaction(result["transaction_hash"])["transaction"]
    after = service.economy_stats()["economy_layer"]

    assert proved["status"] == "confirmed"
    assert proved["action_type"] == "official_fund_transfer"
    assert after["funds"]["exchange_fund"]["balance"] == before["funds"]["exchange_fund"]["balance"] + 123
    assert after["funds"]["official_treasury"]["balance"] == before["funds"]["official_treasury"]["balance"] - 123
    assert after["supply_equation"]["actual_supply_equation_gap_points"] == 0
    assert service.verify_chain()["ok"] is True


def test_wallet_transfer_to_unowned_address_confirms_and_balance_follows_address(tmp_path):
    service = _service(tmp_path)
    actor = {"id": 1, "username": "alice", "role": "user"}
    source = _official_hot_wallet(service, 1)
    destination = "pc1" + "8" * 48
    service.record_transaction(
        user_id=1,
        currency_type="points",
        direction="credit",
        amount=50,
        action_type="admin_adjust_credit",
        reference_type="test",
        reference_id="fund-unowned-transfer",
        idempotency_key="fund-unowned-transfer",
        actor={"id": 3, "username": "root", "role": "super_admin"},
    )

    result = service.submit_wallet_transaction(
        actor=actor,
        source_wallet_address=source["address"],
        destination_wallet_address=destination,
        amount_points=12,
        fee_points=2,
        request_uuid="transfer-to-unowned-address-1",
        memo="send to public address",
    )
    pending_sender = service.get_wallet(1)

    assert result["created"] is True
    assert result["transaction"]["status"] == "pending"
    assert result["transaction"]["wallet_flow"]["destination_unowned"] is True
    assert result["warnings"] == []
    assert pending_sender["wallet_identity_balances"][source["address"]]["points_balance"] == 36
    assert pending_sender["wallet_identity_balances"][source["address"]]["points_frozen"] == 14
    assert service.explorer_wallet(destination)["wallet"]["points_balance"] == 0
    sender_transactions = service.list_wallet_transactions(user_id=1, actor=actor)
    assert sender_transactions["transactions"][0]["direction"] == "outgoing"
    assert sender_transactions["summary"]["pending_outgoing_points"] == 14

    _force_request_proved(service, result["transaction_hash"])
    proved = service.explorer_transaction(result["transaction_hash"])["transaction"]
    final_sender = service.get_wallet(1)
    destination_wallet = service.explorer_wallet(destination)["wallet"]

    assert proved["status"] == "confirmed"
    assert proved["transfer_ledgers"]["transfer_in_ledger_uuid"] == ""
    assert final_sender["wallet_identity_balances"][source["address"]]["points_balance"] == 36
    assert final_sender["wallet_identity_balances"][source["address"]]["points_frozen"] == 0
    assert destination_wallet["points_balance"] == 12
    assert destination_wallet["received_tx_count"] == 1
    assert destination_wallet["recent_transactions"][0]["transaction_hash"] == result["transaction_hash"]
    assert service.verify_chain()["ok"] is True


def test_wallet_transfer_to_burn_address_burns_amount_and_fee(tmp_path):
    service = _service(tmp_path)
    actor = {"id": 1, "username": "alice", "role": "user"}
    source = _official_hot_wallet(service, 1)
    service.record_transaction(
        user_id=1,
        currency_type="points",
        direction="credit",
        amount=50,
        action_type="admin_adjust_credit",
        reference_type="test",
        reference_id="fund-burn-transfer",
        idempotency_key="fund-burn-transfer",
        actor={"id": 3, "username": "root", "role": "super_admin"},
    )
    before = service.economy_stats()["economy_layer"]

    result = service.submit_wallet_transaction(
        actor=actor,
        source_wallet_address=source["address"],
        destination_wallet_address=BURN_WALLET_ADDRESS,
        amount_points=12,
        fee_points=2,
        request_uuid="transfer-to-burn-address-1",
        memo="burn points",
    )

    assert result["created"] is True
    assert result["transaction"]["status"] == "pending"
    assert result["warnings"] == []

    _force_request_proved(service, result["transaction_hash"])
    proved = service.explorer_transaction(result["transaction_hash"])["transaction"]
    final_sender = service.get_wallet(1)
    burn_wallet = service.explorer_wallet(BURN_WALLET_ADDRESS)["wallet"]
    after = service.economy_stats()["economy_layer"]

    assert proved["status"] == "confirmed"
    assert proved["transfer_ledgers"]["transfer_in_ledger_uuid"] == ""
    assert final_sender["wallet_identity_balances"][source["address"]]["points_balance"] == 36
    assert final_sender["wallet_identity_balances"][source["address"]]["points_frozen"] == 0
    assert after["supply"]["burned_total"] == before["supply"]["burned_total"] + 14
    assert after["supply"]["active_supply"] == before["supply"]["active_supply"] - 14
    assert after["funds"]["burn"]["balance"] == before["funds"]["burn"]["balance"] + 14
    assert burn_wallet["points_balance"] == after["funds"]["burn"]["balance"]
    assert after["supply_equation"]["actual_supply_equation_gap_points"] == 0
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
    assert first["settlement_layer"] == "service_fee_subledger"
    assert first["ledger"]["direction"] == "freeze"
    assert first["charge"]["status"] == "reserved"
    assert service.get_wallet(1)["points_balance"] == 99
    assert service.get_wallet(1)["points_frozen"] == 1


def test_spend_points_reserves_service_fee_then_batches_chain_debit(tmp_path):
    service = _service(tmp_path)
    source = _official_hot_wallet(service, 1)
    service.record_transaction(
        user_id=1,
        currency_type="points",
        direction="credit",
        amount=150,
        action_type="user_initial_grant",
        idempotency_key="credit:service-fee-batch",
    )

    reserved = service.spend_points(
        user_id=1,
        item_key="comfyui_txt2img_basic",
        source_wallet_address=source["address"],
        request_uuid="service-fee-reserve-small",
        idempotency_key="service-fee-reserve-small",
    )
    wallet_after_reserve = service.get_wallet(1)
    settled = service.spend_points(
        user_id=1,
        item_key="post_pin_24h",
        source_wallet_address=source["address"],
        request_uuid="service-fee-reserve-threshold",
        idempotency_key="service-fee-reserve-threshold",
    )
    final_wallet = service.get_wallet(1)
    conn = service.get_db()
    try:
        service.ensure_schema(conn)
        charges = conn.execute(
            "SELECT * FROM points_service_fee_charges WHERE user_id=1 ORDER BY id ASC"
        ).fetchall()
        ledgers = conn.execute(
            """
            SELECT direction, action_type, amount
            FROM points_ledger
            WHERE action_type LIKE 'service_fee_%' OR action_type LIKE 'service_fee_reserve:%'
            ORDER BY id ASC
            """
        ).fetchall()
    finally:
        conn.close()

    assert reserved["settlement"]["status"] == "reserved"
    assert reserved["ledger"]["direction"] == "freeze"
    assert wallet_after_reserve["wallet_identity_balances"][source["address"]]["points_balance"] == 145
    assert wallet_after_reserve["wallet_identity_balances"][source["address"]]["points_frozen"] == 5
    assert settled["settlement"]["created"] is True
    assert settled["settlement"]["settled_amount_points"] == 105
    assert final_wallet["wallet_identity_balances"][source["address"]]["points_balance"] == 45
    assert final_wallet["wallet_identity_balances"][source["address"]]["points_frozen"] == 0
    assert [row["status"] for row in charges] == ["settled", "settled"]
    assert [row["direction"] for row in ledgers] == ["freeze", "freeze", "unfreeze", "debit"]
    assert ledgers[-1]["action_type"] == "service_fee_batch_debit"
    assert service.verify_chain()["ok"] is True


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
    assert second["wallet"]["points_balance"] == 100
    assert second["ledger"]["currency_type"] == "points"


def test_birthday_gift_is_once_per_member_per_year(tmp_path):
    service = _service(tmp_path)

    first = service.award_birthday_gift(
        user_id=1,
        birthday_year=2026,
        birthday_date="2026-05-18",
        actor={"id": 1, "username": "alice", "role": "user"},
    )
    second = service.award_birthday_gift(
        user_id=1,
        birthday_year=2026,
        birthday_date="2026-05-18",
        actor={"id": 1, "username": "alice", "role": "user"},
    )
    next_year = service.award_birthday_gift(
        user_id=1,
        birthday_year=2027,
        birthday_date="2027-05-18",
        actor={"id": 1, "username": "alice", "role": "user"},
    )

    assert first["created"] is True
    assert second["created"] is False
    assert next_year["created"] is True
    assert first["ledger"]["action_type"] == "birthday_gift"
    assert first["ledger"]["amount"] == BIRTHDAY_GIFT_POINTS
    assert service.get_wallet(1)["points_balance"] == BIRTHDAY_GIFT_POINTS * 2
    report = service.root_report()
    assert "adjustments" not in report
    assert "birthday_gift" in [row["action_type"] for row in report["unsealed_transactions"]]


def test_initial_grants_create_genesis_block_once_for_default_accounts(tmp_path):
    service = _service(tmp_path)

    first = service.bootstrap_admin_initial_grants(actor={"username": "system", "role": "system"}, seal_genesis=True)

    assert first["created_count"] == 0
    assert first["deferred_count"] == 2
    assert first["deferred"][0]["username"] == "bob"
    assert first["deferred"][0]["amount"] == 1000
    assert first["deferred"][0]["reason"] == "wallet_required"
    assert first["deferred"][1]["username"] == "alice"
    assert first["deferred"][1]["amount"] == 100
    assert first["sealed"] is None
    assert service.get_wallet(2)["points_balance"] == 0
    assert service.get_wallet(1)["points_balance"] == 0

    _official_hot_wallet(service, 2)
    bob = service.award_initial_grants_after_wallet_onboarding(user_id=2, actor={"username": "system", "role": "system"})
    _official_hot_wallet(service, 1)
    alice = service.award_initial_grants_after_wallet_onboarding(user_id=1, actor={"username": "system", "role": "system"})
    second = service.bootstrap_admin_initial_grants(actor={"username": "system", "role": "system"}, seal_genesis=True)

    assert bob["created_count"] == 1
    assert bob["created"][0]["grant"] == "admin_initial"
    assert alice["created_count"] == 1
    assert alice["created"][0]["grant"] == "user_initial"
    assert second["created_count"] == 0
    assert second["deferred_count"] == 0
    assert service.get_wallet(2)["points_balance"] == 1000
    assert service.get_wallet(1)["points_balance"] == 100
    assert service.get_wallet(3)["points_balance"] == 0
    assert service.verify_chain()["counts"]["sealed_blocks"] == 0
    report = service.root_report()
    assert "adjustments" not in report
    assert {row["action_type"] for row in report["unsealed_transactions"]} >= {"admin_initial_grant", "user_initial_grant"}


def test_initial_grants_backfill_default_accounts_after_existing_block(tmp_path):
    path = tmp_path / "points-backfill.db"

    def get_db():
        conn = sqlite3.connect(path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
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
        "('admin', 'manager', 'active'), "
        "('root', 'super_admin', 'active'), "
        "('test', 'user', 'active')"
    )
    ensure_points_economy_schema(conn)
    conn.commit()
    conn.close()
    service = PointsLedgerService(
        get_db=get_db,
        chain_secret="test-secret",
        backup_dir=tmp_path / "points_chain_backups",
        mode_reader=lambda: "production",
    )

    service.record_transaction(
        user_id=3,
        currency_type="points",
        direction="credit",
        amount=1,
        action_type="preexisting_root_credit",
        idempotency_key="preexisting:block",
    )
    service.seal_block(actor={"username": "root", "role": "super_admin"}, limit=100)
    result = service.bootstrap_admin_initial_grants(actor={"username": "system", "role": "system"}, seal_genesis=True)

    assert result["created_count"] == 0
    assert result["deferred_count"] == 2
    assert {item["username"] for item in result["deferred"]} == {"admin", "test"}
    _official_hot_wallet(service, 2)
    admin = service.award_initial_grants_after_wallet_onboarding(user_id=2, actor={"username": "system", "role": "system"})
    _official_hot_wallet(service, 4)
    test_user = service.award_initial_grants_after_wallet_onboarding(user_id=4, actor={"username": "system", "role": "system"})
    assert admin["created_count"] == 1
    assert test_user["created_count"] == 1
    assert service.get_wallet(2)["points_balance"] == 1000
    assert service.get_wallet(4)["points_balance"] == 100
    assert service.get_wallet(1)["points_balance"] == 0


def test_admin_weekly_salary_is_idempotent_by_week(tmp_path):
    service = _service(tmp_path)

    first = service.award_admin_weekly_salaries(salary_week="2026-W18", actor={"username": "system", "role": "system"})
    second = service.award_admin_weekly_salaries(salary_week="2026-W18", actor={"username": "system", "role": "system"})

    assert first["created_count"] == 1
    assert second["created_count"] == 0
    assert service.get_wallet(2)["points_balance"] == 250
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


def test_points_chain_block_and_signature_tables_are_append_only(tmp_path):
    service = _service(tmp_path)
    service.record_transaction(
        user_id=1,
        currency_type="points",
        direction="credit",
        amount=10,
        action_type="test_credit",
    )
    sealed = service.seal_block(actor={"id": 3, "username": "root", "role": "super_admin"}, limit=100)
    block_id = sealed["block"]["id"]

    conn = service.get_db()
    try:
        with pytest.raises(sqlite3.IntegrityError, match="points chain blocks are append-only"):
            conn.execute("UPDATE points_chain_blocks SET merkle_root='forged' WHERE id=?", (block_id,))
        with pytest.raises(sqlite3.IntegrityError, match="points chain blocks are append-only"):
            conn.execute("DELETE FROM points_chain_blocks WHERE id=?", (block_id,))
        with pytest.raises(sqlite3.IntegrityError, match="points chain block signatures are append-only"):
            conn.execute("UPDATE points_chain_block_signatures SET signature='forged' WHERE block_id=?", (block_id,))
        with pytest.raises(sqlite3.IntegrityError, match="points chain block signatures are append-only"):
            conn.execute("DELETE FROM points_chain_block_signatures WHERE block_id=?", (block_id,))
    finally:
        conn.rollback()
        conn.close()


def test_points_chain_verify_detects_forged_sealed_transaction_hash_recompute(tmp_path):
    service = _service(tmp_path)
    tx = service.record_transaction(
        user_id=1,
        currency_type="points",
        direction="credit",
        amount=10,
        action_type="test_credit",
    )
    service.seal_block(actor={"id": 3, "username": "root", "role": "super_admin"}, limit=100)

    conn = service.get_db()
    try:
        conn.execute("DROP TRIGGER trg_points_ledger_core_immutable")
        conn.execute("UPDATE points_ledger SET amount=99 WHERE ledger_uuid=?", (tx["ledger"]["ledger_uuid"],))
        forged = conn.execute("SELECT * FROM points_ledger WHERE ledger_uuid=?", (tx["ledger"]["ledger_uuid"],)).fetchone()
        conn.execute(
            "UPDATE points_ledger SET ledger_hash=? WHERE ledger_uuid=?",
            (compute_ledger_hash(forged), tx["ledger"]["ledger_uuid"]),
        )
        conn.commit()
    finally:
        conn.close()

    verification = service.verify_chain()
    assert verification["ok"] is False
    assert any(error["type"] == "block_merkle_root" for error in verification["errors"])
    assert service.safe_mode_status()["safe_mode"] is True
    with pytest.raises(ValueError, match="safe mode"):
        service.record_transaction(user_id=1, currency_type="points", direction="credit", amount=1, action_type="blocked")


def test_points_chain_verify_detects_forged_block_rehash_without_node_signature(tmp_path):
    service = _service(tmp_path)
    tx = service.record_transaction(
        user_id=1,
        currency_type="points",
        direction="credit",
        amount=10,
        action_type="test_credit",
    )
    service.seal_block(actor={"id": 3, "username": "root", "role": "super_admin"}, limit=100)

    conn = service.get_db()
    try:
        conn.execute("DROP TRIGGER trg_points_ledger_core_immutable")
        conn.execute("DROP TRIGGER trg_points_chain_blocks_no_update")
        conn.execute("UPDATE points_ledger SET amount=99 WHERE ledger_uuid=?", (tx["ledger"]["ledger_uuid"],))
        forged = conn.execute("SELECT * FROM points_ledger WHERE ledger_uuid=?", (tx["ledger"]["ledger_uuid"],)).fetchone()
        conn.execute(
            "UPDATE points_ledger SET ledger_hash=? WHERE ledger_uuid=?",
            (compute_ledger_hash(forged), tx["ledger"]["ledger_uuid"]),
        )
        block = conn.execute("SELECT * FROM points_chain_blocks ORDER BY block_number ASC LIMIT 1").fetchone()
        hashes = [
            row["ledger_hash"]
            for row in conn.execute(
                "SELECT ledger_hash FROM points_ledger WHERE id BETWEEN ? AND ? ORDER BY id ASC",
                (block["first_ledger_id"], block["last_ledger_id"]),
            ).fetchall()
        ]
        forged_merkle = merkle_root(hashes)
        conn.execute("UPDATE points_chain_blocks SET merkle_root=? WHERE id=?", (forged_merkle, block["id"]))
        forged_block = conn.execute("SELECT * FROM points_chain_blocks WHERE id=?", (block["id"],)).fetchone()
        conn.execute(
            "UPDATE points_chain_blocks SET block_hash=? WHERE id=?",
            (compute_block_hash(forged_block), block["id"]),
        )
        conn.commit()
    finally:
        conn.close()

    verification = service.verify_chain()
    assert verification["ok"] is False
    assert any(error["type"] == "block_signature_invalid" for error in verification["errors"])
    assert service.safe_mode_status()["safe_mode"] is True


def test_points_chain_verify_does_not_auto_resign_missing_block_signature(tmp_path):
    service = _service(tmp_path)
    service.record_transaction(
        user_id=1,
        currency_type="points",
        direction="credit",
        amount=10,
        action_type="test_credit",
    )
    service.seal_block(actor={"id": 3, "username": "root", "role": "super_admin"}, limit=100)

    conn = service.get_db()
    try:
        conn.execute("DROP TRIGGER trg_points_chain_block_signatures_no_delete")
        conn.execute("DELETE FROM points_chain_block_signatures")
        conn.commit()
    finally:
        conn.close()

    verification = service.verify_chain()
    assert verification["ok"] is False
    assert any(error["type"] == "block_signature_missing" for error in verification["errors"])
    conn = service.get_db()
    try:
        count = conn.execute("SELECT COUNT(*) FROM points_chain_block_signatures").fetchone()[0]
    finally:
        conn.close()
    assert count == 0


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


def test_verify_chain_uses_wallet_identity_balances_for_walletized_user(tmp_path):
    service = _service(tmp_path)
    service.record_transaction(
        user_id=1,
        currency_type="points",
        direction="credit",
        amount=100,
        action_type="user_initial_grant",
        reference_type="legacy_bootstrap",
        reference_id="before-wallet",
        idempotency_key="legacy-before-wallet",
        reason="legacy initial grant before wallet identity",
    )
    wallet = _official_hot_wallet(service, 1)
    service.record_transaction(
        user_id=1,
        currency_type="points",
        direction="credit",
        amount=100,
        action_type="new_user_signup_bonus",
        reference_type="wallet_signup",
        reference_id="after-wallet",
        idempotency_key="wallet-after-wallet",
        reason="walletized signup bonus",
    )

    payload = service.get_wallet(1)
    assert payload["wallet_identity_balances"][wallet["address"]]["points_balance"] == 100
    assert payload["account_points_balance"] == 100
    assert service.verify_chain()["ok"] is True

    conn = service.get_db()
    try:
        now = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        conn.execute(
            """
            INSERT OR REPLACE INTO points_chain_recovery_state
            (id, safe_mode, reason, verification_json, created_at, updated_at)
            VALUES (1, 1, 'legacy_identity_false_positive', '{}', ?, ?)
            """,
            (now, now),
        )
        conn.commit()
    finally:
        conn.close()
    verification = service.verify_chain()
    assert verification["ok"] is True
    assert verification["safe_mode"]["safe_mode"] is False
    assert service.safe_mode_status()["safe_mode"] is False


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
        service.compensate_ledger(
            actor={"id": 3, "username": "root", "role": "super_admin"},
            ledger_uuid=tx["ledger"]["ledger_uuid"],
            reason="dirty compensation should be blocked",
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
    destination = _official_hot_wallet(service, 1)
    _official_treasury_grant_via_governance(
        service,
        destination_wallet_address=destination["address"],
        amount=7,
        request_uuid="root-report-official-grant",
    )
    report = service.root_report()

    assert sealed["sealed"] is True
    assert report["verification"]["ok"] is True
    assert report["blocks"][0]["signature_algorithm"] == "hmac-sha256"
    assert report["audit_logs"][0]["event_type"] in {
        "POINTS_LEDGER_BACKUP_CREATED",
        "POINTS_BLOCK_SEALED",
        "POINTS_CHAIN_WALLET_CACHE_REBUILT",
        "LEDGER_APPEND",
        "OFFICIAL_WALLET_GRANT",
    }
    assert report["block_schedule"]["mode"] == "hybrid"
    assert report["block_schedule"]["ledger_threshold"] == 30
    assert report["block_schedule"]["max_interval_minutes"] == 24 * 60
    assert report["block_schedule"]["unsealed_entries"] == 0
    assert "adjustments" not in report
    assert report["unsealed_transactions"][0]["action_type"] == "official_wallet_grant"
    report_json = json.dumps(report, ensure_ascii=False)
    assert '"target_username"' not in report_json
    assert '"actor_username"' not in report_json
    assert '"user_id"' not in report_json
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


def test_root_rollback_is_disabled_and_compensation_is_append_only(tmp_path):
    service = _service(tmp_path)
    tx = service.record_transaction(
        user_id=1,
        currency_type="points",
        direction="credit",
        amount=10,
        action_type="test_credit",
    )

    with pytest.raises(PermissionError, match="rollback is disabled"):
        service.rollback_ledger(
            actor={"id": 3, "username": "root", "role": "super_admin"},
            ledger_uuid=tx["ledger"]["ledger_uuid"],
            reason="emergency correction",
        )

    compensation = service.compensate_ledger(
        actor={"id": 3, "username": "root", "role": "super_admin"},
        ledger_uuid=tx["ledger"]["ledger_uuid"],
        reason="emergency correction",
    )

    assert compensation["compensation_ledger"]["direction"] == "reverse"
    assert compensation["compensation_ledger"]["reference_id"] == tx["ledger"]["ledger_uuid"]
    assert compensation["wallet"]["points_balance"] == 0
    assert service.verify_chain()["ok"] is True
    audit_events = [row["event_type"] for row in service.list_chain_audit_logs(limit=10)]
    assert "LEDGER_COMPENSATION" in audit_events

    duplicate = service.compensate_ledger(
        actor={"id": 3, "username": "root", "role": "super_admin"},
        ledger_uuid=tx["ledger"]["ledger_uuid"],
        reason="duplicate correction",
    )
    assert duplicate["created"] is False


def test_direct_wallet_sanction_is_disabled(tmp_path):
    service = _service(tmp_path)
    root_actor = {"id": 3, "username": "root", "role": "super_admin"}
    service.record_transaction(
        user_id=1,
        currency_type="points",
        direction="credit",
        amount=20,
        action_type="test_credit",
    )

    with pytest.raises(PermissionError, match="direct wallet sanctions are disabled"):
        service.sanction_wallet(
            actor=root_actor,
            user_id=1,
            wallet_status="frozen",
            risk_level="high",
            reason="abuse investigation",
            freeze_amount=7,
        )
    assert service.get_wallet(1)["wallet_status"] == "active"
    assert service.get_wallet(1)["points_balance"] == 20


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


def test_manual_admin_adjust_is_disabled(tmp_path):
    service = _service(tmp_path)

    with pytest.raises(PermissionError, match="manual points adjustment is disabled"):
        service.admin_adjust(
            actor={"id": 3, "username": "root", "role": "super_admin"},
            user_id=1,
            currency_type="points",
            direction="credit",
            amount=5,
            reason="manual correction",
        )


def test_official_wallet_grant_is_idempotent_for_request_uuid(tmp_path):
    service = _service(tmp_path)
    actor = {"id": 3, "username": "root", "role": "super_admin"}
    destination = _official_hot_wallet(service, 1)

    first, proposal_uuid = _official_treasury_grant_via_governance(
        service,
        destination_wallet_address=destination["address"],
        amount=5,
        request_uuid="official-grant-click-1",
    )
    second = service.official_wallet_grant(
        actor=actor,
        destination_wallet_address=destination["address"],
        amount=5,
        reason="governance official transfer",
        request_uuid=f"governance:{proposal_uuid}:official_transfer",
        governance_proposal_uuid=proposal_uuid,
    )

    assert first["created"] is True
    assert second["created"] is False
    assert first["transaction"]["status"] == "pending"
    assert second["transaction"]["status"] == "pending"
    assert service.get_wallet(1)["points_balance"] == 0
    assert [
        row for row in service.list_ledger(user_id=1, include_user_id=True)
        if row["action_type"] == "official_wallet_grant"
    ] == []

    _force_request_proved(service, first["transaction_hash"])
    proved = service.explorer_transaction(first["transaction_hash"])["transaction"]

    assert proved["status"] == "confirmed"
    assert service.get_wallet(1)["points_balance"] == 5
    grants = [
        row for row in service.list_ledger(user_id=1, include_user_id=True)
        if row["action_type"] == "official_wallet_grant"
    ]
    assert len(grants) == 1


def test_official_wallet_grant_requires_root_but_allows_unowned_wallet_address(tmp_path):
    service = _service(tmp_path)
    destination = _official_hot_wallet(service, 1)
    unowned_address = "pc1" + "9" * 48

    with pytest.raises(PermissionError, match="requires executed governance proposal"):
        service.official_wallet_grant(
            actor={"id": 2, "username": "bob", "role": "manager"},
            destination_wallet_address=destination["address"],
            amount=1,
            reason="must fail",
            request_uuid="non-root-official-grant",
        )
    result, _proposal_uuid = _official_treasury_grant_via_governance(
        service,
        destination_wallet_address=unowned_address,
        amount=1,
        request_uuid="unknown-official-grant",
    )
    assert result["created"] is True
    assert result["destination_unowned"] is True
    assert result["transaction"]["wallet_flow"]["destination_unowned"] is True
    assert result["transaction"]["status"] == "pending"
    assert service.explorer_wallet(unowned_address)["wallet"]["points_balance"] == 0

    _force_request_proved(service, result["transaction_hash"])
    proved = service.explorer_transaction(result["transaction_hash"])["transaction"]

    assert proved["status"] == "confirmed"
    assert service.explorer_wallet(unowned_address)["wallet"]["points_balance"] == 1


def test_spend_points_uses_selected_source_wallet(tmp_path):
    service = _service(tmp_path)
    secondary_key = ec.generate_private_key(ec.SECP256R1())
    secondary_public_jwk = _public_jwk(secondary_key)
    conn = service.get_db()
    try:
        service.ensure_schema(conn)
        primary = create_official_hot_wallet(conn, user_id=1, chain_secret=service.chain_secret, label="primary hot")["address"]
        secondary = address_from_public_key(secondary_public_jwk)
        bind_payload = wallet_binding_payload(
            user_id=1,
            wallet_type="self_custody_cold",
            address=secondary,
            public_key_jwk=secondary_public_jwk,
        )
        secondary_wallet = bind_self_custody_wallet(
            conn,
            user_id=1,
            wallet_type="self_custody_cold",
            public_key_jwk=secondary_public_jwk,
            address=secondary,
            signature=_signature(secondary_key, bind_payload),
            label="secondary cold",
            backup_confirmed=True,
        )
        conn.commit()
    finally:
        conn.close()
    service.upsert_catalog_item(
        actor={"id": 3, "username": "root", "role": "super_admin"},
        item_key="unit_spend_item",
        item_name="Unit Spend Item",
        category="test",
        base_price=3,
        enabled=True,
    )
    grant, _proposal_uuid = _official_treasury_grant_via_governance(
        service,
        destination_wallet_address=secondary,
        amount=10,
        request_uuid="fund-secondary-wallet",
    )
    _force_request_proved(service, grant["transaction_hash"])
    service.explorer_transaction(grant["transaction_hash"])
    spend_request_uuid = "selected-source-service-fee"
    spend_signature_payload = wallet_service_fee_payload(
        user_id=1,
        source_wallet_address=secondary,
        item_key="unit_spend_item",
        quantity=1,
        amount_points=3,
        request_uuid=spend_request_uuid,
        reference_type="price_catalog",
        reference_id="unit_spend_item",
        chain_branch="main",
        signer_key_id=secondary_wallet["public_key_hash"],
    )
    spend = service.spend_points(
        user_id=1,
        item_key="unit_spend_item",
        quantity=1,
        source_wallet_address=secondary,
        request_uuid=spend_request_uuid,
        idempotency_key=spend_request_uuid,
        signature=_signature(secondary_key, spend_signature_payload),
        actor={"id": 1, "username": "alice", "role": "user"},
    )

    ledger = service.list_ledger(user_id=1, limit=1)[0]
    assert spend["wallet"]["account_points_balance"] == 7
    assert spend["wallet"]["account_points_frozen"] == 3
    assert spend["wallet"]["wallet_identity_balances"][secondary]["points_balance"] == 7
    assert spend["wallet"]["wallet_identity_balances"][secondary]["points_frozen"] == 3
    assert spend["wallet"]["wallet_identity_balances"][primary]["points_balance"] == 0
    assert ledger["direction"] == "freeze"
    assert ledger["action_type"] == "service_fee_reserve:unit_spend_item"
    assert ledger["wallet_flow"]["source_wallet_address"] == secondary

    with pytest.raises(ValueError, match="insufficient balance"):
        service.spend_points(
            user_id=1,
            item_key="unit_spend_item",
            quantity=1,
            source_wallet_address=primary,
            actor={"id": 1, "username": "alice", "role": "user"},
        )


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
