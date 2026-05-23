import base64
import sqlite3

import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec, utils

from services.platform.db_mode_triggers import register_app_mode_function
from services.points_chain import (
    BURN_WALLET_ADDRESS,
    DISPLAY_CURRENCY,
    PointsLedgerService,
    address_from_public_key,
    award_signup_bonus_after_wallet_onboarding,
    bind_self_custody_wallet,
    create_multisig_wallet,
    create_official_hot_wallet,
    delete_cold_wallet,
    delete_primary_cold_wallet,
    ensure_system_wallets,
    ensure_wallet_identity_schema,
    wallet_binding_payload,
    wallet_service_fee_payload,
    wallet_transaction_payload,
    wallet_onboarding_status,
)
from services.points_chain.schema import canonical_json


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


def _private_jwk(private_key):
    jwk = _public_jwk(private_key)
    jwk["d"] = _b64url(private_key.private_numbers().private_value.to_bytes(32, "big"))
    return jwk


def _signature(private_key, payload):
    der = private_key.sign(canonical_json(payload).encode("utf-8"), ec.ECDSA(hashes.SHA256()))
    r, s = utils.decode_dss_signature(der)
    return _b64url(r.to_bytes(32, "big") + s.to_bytes(32, "big"))


def _db(tmp_path):
    path = tmp_path / "wallet_identity.db"

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
    conn.execute("INSERT INTO users (id, username, role, status) VALUES (1, 'alice', 'user', 'active')")
    conn.execute("INSERT INTO users (id, username, role, status) VALUES (2, 'bob', 'user', 'active')")
    conn.commit()
    conn.close()
    return get_db


def _points(tmp_path):
    return PointsLedgerService(
        get_db=_db(tmp_path),
        chain_secret="wallet-secret",
        backup_dir=tmp_path / "backups",
        mode_reader=lambda: "production",
    )


def test_system_mint_and_burn_wallets_are_identity_only(tmp_path):
    points = _points(tmp_path)
    conn = points.get_db()
    try:
        points.ensure_schema(conn)
        wallets = ensure_system_wallets(conn, chain_secret=points.chain_secret)
        conn.commit()
    finally:
        conn.close()

    assert [item["wallet_type"] for item in wallets] == ["mint", "burn"]
    assert all(item["custody_mode"] == "system" for item in wallets)
    assert all(item["server_private_key_stored"] is False for item in wallets)
    assert wallets[1]["address"] == BURN_WALLET_ADDRESS
    assert BURN_WALLET_ADDRESS == "pc1" + ("0" * 48)

    conn = points.get_db()
    try:
        conn.execute(
            "UPDATE points_wallet_identities SET address=?, public_key_hash=? WHERE wallet_type='burn'",
            ("pc1" + ("b" * 48), "legacy-burn-hash"),
        )
        realigned = ensure_system_wallets(conn, chain_secret=points.chain_secret)
        conn.commit()
    finally:
        conn.close()

    assert realigned[1]["address"] == BURN_WALLET_ADDRESS


def test_self_custody_wallet_rejects_private_key_material_and_awards_signup_after_binding(tmp_path):
    points = _points(tmp_path)
    private_key = ec.generate_private_key(ec.SECP256R1())
    public_jwk = _public_jwk(private_key)
    address = address_from_public_key(public_jwk)
    payload = wallet_binding_payload(
        user_id=1,
        wallet_type="self_custody_cold",
        address=address,
        public_key_jwk=public_jwk,
    )
    signature = _signature(private_key, payload)

    conn = points.get_db()
    try:
        points.ensure_schema(conn)
        ensure_wallet_identity_schema(conn)
        with pytest.raises(ValueError, match="private key material"):
            bind_self_custody_wallet(
                conn,
                user_id=1,
                wallet_type="self_custody_cold",
                public_key_jwk=_private_jwk(private_key),
                address=address,
                signature=signature,
                backup_confirmed=True,
            )
        wallet = bind_self_custody_wallet(
            conn,
            user_id=1,
            wallet_type="self_custody_cold",
            public_key_jwk=public_jwk,
            address=address,
            signature=signature,
            backup_confirmed=True,
        )
        conn.commit()
    finally:
        conn.close()

    assert wallet["address"] == address
    assert wallet["custody_mode"] == "self_custody"
    assert wallet["server_private_key_stored"] is False
    first_bonus = award_signup_bonus_after_wallet_onboarding(
        points_service=points,
        user_id=1,
        actor={"id": 1, "username": "alice", "role": "user"},
    )
    second_bonus = award_signup_bonus_after_wallet_onboarding(
        points_service=points,
        user_id=1,
        actor={"id": 1, "username": "alice", "role": "user"},
    )
    assert first_bonus["created"] is True
    assert second_bonus["already_granted"] is True
    assert points.get_wallet(1)["points_balance"] == 100
    ledger = points.list_ledger(user_id=1, limit=1)[0]
    assert ledger["ledger_uuid"]
    assert ledger["wallet_flow"]["source_label"] == "PROMO 獎勵基金"
    assert ledger["wallet_flow"]["destination_wallet_address"] == address
    assert ledger["wallet_flow"]["target_wallet_address"] == address
    assert ledger["wallet_flow"]["legacy_public_account_id"] == ledger["public_account_id"]
    stats = points.economy_stats()["economy_layer"]
    assert stats["funds"]["promo_fund"]["balance"] == 4_999_900
    assert stats["supply"]["circulating_supply"] == 100


def test_self_custody_wallet_transfer_requires_private_key_signature(tmp_path):
    points = _points(tmp_path)
    private_key = ec.generate_private_key(ec.SECP256R1())
    public_jwk = _public_jwk(private_key)
    address = address_from_public_key(public_jwk)
    bind_signature = _signature(private_key, wallet_binding_payload(
        user_id=1,
        wallet_type="self_custody_cold",
        address=address,
        public_key_jwk=public_jwk,
    ))
    conn = points.get_db()
    try:
        points.ensure_schema(conn)
        wallet = bind_self_custody_wallet(
            conn,
            user_id=1,
            wallet_type="self_custody_cold",
            public_key_jwk=public_jwk,
            address=address,
            signature=bind_signature,
            backup_confirmed=True,
        )
        destination = create_official_hot_wallet(conn, user_id=2, chain_secret=points.chain_secret)
        conn.commit()
    finally:
        conn.close()
    points.record_transaction(
        user_id=1,
        currency_type=DISPLAY_CURRENCY,
        direction="credit",
        amount=50,
        action_type="test_seed",
        reference_type="test",
        reference_id="self-custody-transfer-funding",
        idempotency_key="self-custody-transfer-funding",
        actor={"id": 1, "username": "alice", "role": "user"},
    )

    with pytest.raises(PermissionError, match="transaction signature required"):
        points.submit_wallet_transaction(
            actor={"id": 1, "username": "alice", "role": "user"},
            source_wallet_address=wallet["address"],
            destination_wallet_address=destination["address"],
            amount_points=10,
            fee_points=1,
            request_uuid="self-custody-transfer-missing-signature",
            memo="signed",
        )

    tx_payload = wallet_transaction_payload(
        user_id=1,
        source_wallet_address=wallet["address"],
        destination_wallet_address=destination["address"],
        amount_points=10,
        fee_points=1,
        request_uuid="self-custody-transfer-signed",
        memo="signed",
        chain_branch="main",
        signer_key_id=wallet["public_key_hash"],
    )
    result = points.submit_wallet_transaction(
        actor={"id": 1, "username": "alice", "role": "user"},
        source_wallet_address=wallet["address"],
        destination_wallet_address=destination["address"],
        amount_points=10,
        fee_points=1,
        request_uuid="self-custody-transfer-signed",
        memo="signed",
        signature=_signature(private_key, tx_payload),
    )

    assert result["created"] is True
    assert result["transaction"]["status"] == "pending"


def test_self_custody_service_fee_reserve_requires_private_key_signature(tmp_path):
    points = _points(tmp_path)
    private_key = ec.generate_private_key(ec.SECP256R1())
    public_jwk = _public_jwk(private_key)
    address = address_from_public_key(public_jwk)
    bind_signature = _signature(private_key, wallet_binding_payload(
        user_id=1,
        wallet_type="self_custody_cold",
        address=address,
        public_key_jwk=public_jwk,
    ))
    conn = points.get_db()
    try:
        points.ensure_schema(conn)
        wallet = bind_self_custody_wallet(
            conn,
            user_id=1,
            wallet_type="self_custody_cold",
            public_key_jwk=public_jwk,
            address=address,
            signature=bind_signature,
            backup_confirmed=True,
        )
        conn.commit()
    finally:
        conn.close()
    points.record_transaction(
        user_id=1,
        currency_type=DISPLAY_CURRENCY,
        direction="credit",
        amount=50,
        action_type="test_seed",
        reference_type="test",
        reference_id="self-custody-service-fee-funding",
        idempotency_key="self-custody-service-fee-funding",
        actor={"id": 1, "username": "alice", "role": "user"},
    )

    with pytest.raises(PermissionError, match="service fee signature required"):
        points.spend_points(
            user_id=1,
            item_key="comfyui_txt2img_basic",
            source_wallet_address=wallet["address"],
            request_uuid="self-custody-service-fee-missing-signature",
            idempotency_key="self-custody-service-fee-missing-signature",
            actor={"id": 1, "username": "alice", "role": "user"},
        )

    payload = wallet_service_fee_payload(
        user_id=1,
        source_wallet_address=wallet["address"],
        item_key="comfyui_txt2img_basic",
        quantity=1,
        amount_points=5,
        request_uuid="self-custody-service-fee-signed",
        reference_type="price_catalog",
        reference_id="comfyui_txt2img_basic",
        chain_branch="main",
        signer_key_id=wallet["public_key_hash"],
    )
    result = points.spend_points(
        user_id=1,
        item_key="comfyui_txt2img_basic",
        source_wallet_address=wallet["address"],
        request_uuid="self-custody-service-fee-signed",
        idempotency_key="self-custody-service-fee-signed",
        signature=_signature(private_key, payload),
        actor={"id": 1, "username": "alice", "role": "user"},
    )

    wallet_after = points.get_wallet(1)
    assert result["created"] is True
    assert result["ledger"]["direction"] == "freeze"
    assert result["charge"]["status"] == "reserved"
    assert wallet_after["wallet_identity_balances"][wallet["address"]]["points_balance"] == 45
    assert wallet_after["wallet_identity_balances"][wallet["address"]]["points_frozen"] == 5


def test_official_hot_and_multisig_wallets_complete_onboarding_without_private_key(tmp_path):
    points = _points(tmp_path)
    conn = points.get_db()
    try:
        points.ensure_schema(conn)
        official = create_official_hot_wallet(conn, user_id=1, chain_secret=points.chain_secret)
        multisig = create_multisig_wallet(
            conn,
            user_id=2,
            threshold=2,
            signer_addresses=[official["address"], "pc1" + "a" * 48, "pc1" + "b" * 48],
        )
        status = wallet_onboarding_status(conn, points_service=points, user_id=1)
        conn.commit()
    finally:
        conn.close()

    assert official["wallet_type"] == "official_hot"
    assert official["server_private_key_stored"] is False
    assert multisig["wallet_type"] == "user_multisig_preview"
    assert multisig["wallet_scope"] == "user"
    assert multisig["spend_capability"] == "receive_only"
    assert multisig["metadata"]["multisig_policy"]["threshold"] == 2
    assert status["wallet"]["address"] == official["address"]
    assert status["signup_bonus_granted"] is False


def test_multisig_can_be_second_wallet_without_replacing_primary(tmp_path):
    points = _points(tmp_path)
    conn = points.get_db()
    try:
        points.ensure_schema(conn)
        official = create_official_hot_wallet(conn, user_id=1, chain_secret=points.chain_secret)
        multisig = create_multisig_wallet(
            conn,
            user_id=1,
            threshold=2,
            signer_addresses=[official["address"], "pc1" + "a" * 48, "pc1" + "b" * 48],
        )
        status = wallet_onboarding_status(conn, points_service=points, user_id=1)
        conn.commit()
    finally:
        conn.close()

    assert official["is_primary"] is True
    assert multisig["wallet_type"] == "user_multisig_preview"
    assert multisig["is_primary"] is False
    assert len(status["wallets"]) == 2
    assert status["wallet"]["address"] == official["address"]
    assert status["wallet_creation_fee"]["amount_points"] == 50
    assert "multisig" not in status["allowed_modes"]
    assert status["multisig_policy"]["rc1_user_multisig"] == "receive_only"


def test_second_wallet_creation_fee_charges_official_treasury(tmp_path):
    points = _points(tmp_path)
    conn = points.get_db()
    try:
        points.ensure_schema(conn)
        first = create_official_hot_wallet(conn, user_id=1, chain_secret=points.chain_secret)
        row, _created = points._record_transaction(
            conn,
            user_id=1,
            currency_type=DISPLAY_CURRENCY,
            direction="credit",
            amount=100,
            action_type="user_initial_grant",
            reference_type="unit",
            reference_id="fund-first-wallet",
            idempotency_key="fund-first-wallet",
            reason="unit funding",
            public_metadata={"destination_wallet_address": first["address"]},
            actor={"username": "system", "role": "system"},
        )
        assert row["amount"] == 100
        quote = points.wallet_creation_fee_quote(conn, 1)
        fee = points.charge_wallet_creation_fee_locked(
            conn,
            user_id=1,
            source_wallet_address=first["address"],
            request_uuid="create-wallet-fee-1",
            wallet_count_before=1,
            amount_points=quote["amount_points"],
            mode="self_custody_cold",
            actor={"id": 1, "username": "alice", "role": "user"},
        )
        wallet = points.wallet_payload_for_read(conn, 1)
        treasury_event = conn.execute(
            """
            SELECT * FROM points_economy_events
            WHERE transaction_type='wallet_creation_fee'
            ORDER BY id DESC
            LIMIT 1
            """
        ).fetchone()
        conn.commit()
    finally:
        conn.close()

    assert quote["amount_points"] == 25
    assert fee["charged"] is True
    assert fee["ledger"]["action_type"] == "wallet_creation_fee"
    assert wallet["wallet_identity_balances"][first["address"]]["points_balance"] == 75
    assert treasury_event["destination_fund_key"] == "official_treasury"
    assert treasury_event["amount"] == 25


def test_wallet_creation_fee_rejects_bad_quote_insufficient_balance_and_multisig_source(tmp_path):
    points = _points(tmp_path)
    conn = points.get_db()
    try:
        points.ensure_schema(conn)
        first = create_official_hot_wallet(conn, user_id=1, chain_secret=points.chain_secret)
        with pytest.raises(ValueError, match="quote changed"):
            points.charge_wallet_creation_fee_locked(
                conn,
                user_id=1,
                source_wallet_address=first["address"],
                request_uuid="bad-quote",
                wallet_count_before=1,
                amount_points=999,
                actor={"id": 1, "username": "alice", "role": "user"},
            )
        with pytest.raises(ValueError, match="insufficient balance"):
            points.charge_wallet_creation_fee_locked(
                conn,
                user_id=1,
                source_wallet_address=first["address"],
                request_uuid="no-balance",
                wallet_count_before=1,
                amount_points=25,
                actor={"id": 1, "username": "alice", "role": "user"},
            )
        points._record_transaction(
            conn,
            user_id=1,
            currency_type=DISPLAY_CURRENCY,
            direction="credit",
            amount=200,
            action_type="user_initial_grant",
            reference_type="unit",
            reference_id="fund-for-multisig-source",
            idempotency_key="fund-for-multisig-source",
            reason="unit funding",
            public_metadata={"destination_wallet_address": first["address"]},
            actor={"username": "system", "role": "system"},
        )
        multisig = create_multisig_wallet(
            conn,
            user_id=1,
            threshold=2,
            signer_addresses=[first["address"], "pc1" + "c" * 48, "pc1" + "d" * 48],
        )
        points._record_transaction(
            conn,
            user_id=1,
            currency_type=DISPLAY_CURRENCY,
            direction="credit",
            amount=200,
            action_type="test_seed_multisig_wallet",
            reference_type="unit",
            reference_id="fund-multisig",
            idempotency_key="fund-multisig",
            reason="unit funding",
            public_metadata={"destination_wallet_address": multisig["address"]},
            actor={"username": "system", "role": "system"},
        )
        with pytest.raises(PermissionError, match="一般用戶多簽目前僅支援收款/觀察"):
            points.charge_wallet_creation_fee_locked(
                conn,
                user_id=1,
                source_wallet_address=multisig["address"],
                request_uuid="multisig-source",
                wallet_count_before=2,
                amount_points=50,
                actor={"id": 1, "username": "alice", "role": "user"},
            )
        conn.commit()
    finally:
        conn.close()
    with pytest.raises(PermissionError, match="一般用戶多簽目前僅支援收款/觀察"):
        points.submit_wallet_transaction(
            actor={"id": 1, "username": "alice", "role": "user"},
            source_wallet_address=multisig["address"],
            destination_wallet_address=first["address"],
            amount_points=1,
            fee_points=1,
            request_uuid="user-multisig-transfer-blocked",
        )
    with pytest.raises(PermissionError, match="user_multisig_receive_only_rc1"):
        points.spend_points(
            user_id=1,
            item_key="comfyui_txt2img_basic",
            source_wallet_address=multisig["address"],
            request_uuid="user-multisig-service-fee-blocked",
            idempotency_key="user-multisig-service-fee-blocked",
            actor={"id": 1, "username": "alice", "role": "user"},
        )


def test_cold_wallet_delete_requires_private_key_restore_and_official_hot_cannot_delete(tmp_path):
    points = _points(tmp_path)
    private_key = ec.generate_private_key(ec.SECP256R1())
    public_jwk = _public_jwk(private_key)
    address = address_from_public_key(public_jwk)
    payload = wallet_binding_payload(
        user_id=1,
        wallet_type="self_custody_cold",
        address=address,
        public_key_jwk=public_jwk,
    )
    signature = _signature(private_key, payload)

    conn = points.get_db()
    try:
        points.ensure_schema(conn)
        wallet = bind_self_custody_wallet(
            conn,
            user_id=1,
            wallet_type="self_custody_cold",
            public_key_jwk=public_jwk,
            address=address,
            signature=signature,
            backup_confirmed=True,
        )
        deleted = delete_primary_cold_wallet(conn, user_id=1, reason="unit test")
        status_after_delete = wallet_onboarding_status(conn, points_service=points, user_id=1)
        restore_payload = wallet_binding_payload(
            user_id=1,
            wallet_type="imported_cold",
            address=address,
            public_key_jwk=public_jwk,
        )
        restored = bind_self_custody_wallet(
            conn,
            user_id=1,
            wallet_type="imported_cold",
            public_key_jwk=public_jwk,
            address=address,
            signature=_signature(private_key, restore_payload),
            backup_confirmed=True,
        )
        status_after_restore = wallet_onboarding_status(conn, points_service=points, user_id=1)
        official = create_official_hot_wallet(conn, user_id=2, chain_secret=points.chain_secret)
        with pytest.raises(ValueError, match="official hot wallets cannot be deleted"):
            delete_primary_cold_wallet(conn, user_id=2, reason="must fail")
        conn.commit()
    finally:
        conn.close()

    assert wallet["address"] == address
    assert deleted["address"] == address
    assert deleted["status"] == "lost"
    assert deleted["is_primary"] is False
    assert deleted["metadata"]["restore_requires_private_key"] is True
    assert status_after_delete["wallet"] is None
    assert all(item["address"] != address for item in status_after_delete["wallets"])
    assert status_after_delete["wallet_required"] is True
    assert restored["id"] == wallet["id"]
    assert restored["address"] == address
    assert restored["wallet_type"] == "imported_cold"
    assert restored["status"] == "active"
    assert restored["is_primary"] is True
    assert status_after_restore["wallet"]["address"] == address
    assert official["wallet_type"] == "official_hot"


def test_lost_cold_wallet_can_be_claimed_by_private_key_and_balance_follows_address(tmp_path):
    points = _points(tmp_path)
    private_key = ec.generate_private_key(ec.SECP256R1())
    public_jwk = _public_jwk(private_key)
    address = address_from_public_key(public_jwk)
    payload_user1 = wallet_binding_payload(
        user_id=1,
        wallet_type="self_custody_cold",
        address=address,
        public_key_jwk=public_jwk,
    )

    conn = points.get_db()
    try:
        points.ensure_schema(conn)
        bind_self_custody_wallet(
            conn,
            user_id=1,
            wallet_type="self_custody_cold",
            public_key_jwk=public_jwk,
            address=address,
            signature=_signature(private_key, payload_user1),
            backup_confirmed=True,
        )
        conn.commit()
    finally:
        conn.close()

    points.record_transaction(
        user_id=1,
        currency_type="points",
        direction="credit",
        amount=77,
        action_type="user_initial_grant",
        reference_type="unit",
        reference_id="lost-wallet-claim",
        idempotency_key="lost-wallet-claim-grant",
    )
    assert points.get_wallet(1)["points_balance"] == 77

    conn = points.get_db()
    try:
        points.ensure_schema(conn)
        delete_primary_cold_wallet(conn, user_id=1, reason="owner lost key")
        status_after_delete = wallet_onboarding_status(conn, points_service=points, user_id=1)
        conn.commit()
    finally:
        conn.close()

    assert status_after_delete["wallet"] is None
    assert all(item["address"] != address for item in status_after_delete["wallets"])
    assert points.get_wallet(1)["points_balance"] == 0
    assert points.explorer_wallet(address)["wallet"]["points_balance"] == 77
    assert points.verify_chain()["ok"] is True
    conn = points.get_db()
    try:
        row = conn.execute("SELECT soft_balance FROM points_wallets WHERE user_id=1").fetchone()
    finally:
        conn.close()
    assert int(row["soft_balance"]) == 0

    payload_user2 = wallet_binding_payload(
        user_id=2,
        wallet_type="imported_cold",
        address=address,
        public_key_jwk=public_jwk,
    )
    conn = points.get_db()
    try:
        points.ensure_schema(conn)
        restored = bind_self_custody_wallet(
            conn,
            user_id=2,
            wallet_type="imported_cold",
            public_key_jwk=public_jwk,
            address=address,
            signature=_signature(private_key, payload_user2),
            backup_confirmed=True,
        )
        status_user1 = wallet_onboarding_status(conn, points_service=points, user_id=1)
        status_user2 = wallet_onboarding_status(conn, points_service=points, user_id=2)
        with pytest.raises(ValueError, match="already bound to another active user"):
            bind_self_custody_wallet(
                conn,
                user_id=1,
                wallet_type="imported_cold",
                public_key_jwk=public_jwk,
                address=address,
                signature=_signature(private_key, wallet_binding_payload(
                    user_id=1,
                    wallet_type="imported_cold",
                    address=address,
                    public_key_jwk=public_jwk,
                )),
                backup_confirmed=True,
            )
        conn.commit()
    finally:
        conn.close()

    assert restored["user_id"] == 2
    assert restored["address"] == address
    assert restored["metadata"]["claimed_lost_wallet"] is True
    assert status_user1["wallet"] is None
    assert status_user2["wallet"]["address"] == address
    assert points.get_wallet(1)["points_balance"] == 0
    assert points.get_wallet(2)["points_balance"] == 77
    assert points.verify_chain()["ok"] is True
    conn = points.get_db()
    try:
        row1 = conn.execute("SELECT soft_balance FROM points_wallets WHERE user_id=1").fetchone()
        row2 = conn.execute("SELECT soft_balance FROM points_wallets WHERE user_id=2").fetchone()
    finally:
        conn.close()
    assert int(row1["soft_balance"]) == 0
    assert int(row2["soft_balance"]) == 77


def test_unowned_address_transfer_is_claimed_when_private_key_is_imported(tmp_path):
    points = _points(tmp_path)
    private_key = ec.generate_private_key(ec.SECP256R1())
    public_jwk = _public_jwk(private_key)
    destination = address_from_public_key(public_jwk)
    conn = points.get_db()
    try:
        points.ensure_schema(conn)
        source = create_official_hot_wallet(conn, user_id=1, chain_secret=points.chain_secret)
        conn.commit()
    finally:
        conn.close()

    points.record_transaction(
        user_id=1,
        currency_type="points",
        direction="credit",
        amount=40,
        action_type="user_initial_grant",
        reference_type="unit",
        reference_id="unowned-address-transfer-funding",
        idempotency_key="unowned-address-transfer-funding",
    )
    transfer = points.submit_wallet_transaction(
        actor={"id": 1, "username": "alice", "role": "user"},
        source_wallet_address=source["address"],
        destination_wallet_address=destination,
        amount_points=15,
        fee_points=1,
        request_uuid="unowned-address-transfer-claim",
    )
    conn = points.get_db()
    try:
        points.ensure_schema(conn)
        conn.execute(
            "UPDATE points_chain_transfer_requests SET created_at='2026-01-01T00:00:00Z' WHERE tx_group_hash=?",
            (transfer["transaction_hash"],),
        )
        conn.commit()
    finally:
        conn.close()
    proved = points.explorer_transaction(transfer["transaction_hash"])["transaction"]

    assert proved["status"] == "confirmed"
    assert points.explorer_wallet(destination)["wallet"]["points_balance"] == 15
    assert points.get_wallet(2)["points_balance"] == 0

    payload_user2 = wallet_binding_payload(
        user_id=2,
        wallet_type="imported_cold",
        address=destination,
        public_key_jwk=public_jwk,
    )
    conn = points.get_db()
    try:
        points.ensure_schema(conn)
        restored = bind_self_custody_wallet(
            conn,
            user_id=2,
            wallet_type="imported_cold",
            public_key_jwk=public_jwk,
            address=destination,
            signature=_signature(private_key, payload_user2),
            backup_confirmed=True,
        )
        status_user2 = wallet_onboarding_status(conn, points_service=points, user_id=2)
        conn.commit()
    finally:
        conn.close()

    assert restored["address"] == destination
    assert status_user2["wallet"]["address"] == destination
    assert points.get_wallet(2)["points_balance"] == 15
    user2_transactions = points.list_wallet_transactions(
        user_id=2,
        actor={"id": 2, "username": "bob", "role": "user"},
    )
    assert user2_transactions["transactions"][0]["direction"] == "incoming"
    assert user2_transactions["transactions"][0]["transaction_hash"] == transfer["transaction_hash"]


def test_delete_cold_wallet_by_address_hides_only_selected_wallet(tmp_path):
    points = _points(tmp_path)
    key_a = ec.generate_private_key(ec.SECP256R1())
    public_a = _public_jwk(key_a)
    address_a = address_from_public_key(public_a)
    key_b = ec.generate_private_key(ec.SECP256R1())
    public_b = _public_jwk(key_b)
    address_b = address_from_public_key(public_b)

    conn = points.get_db()
    try:
        points.ensure_schema(conn)
        wallet_a = bind_self_custody_wallet(
            conn,
            user_id=1,
            wallet_type="self_custody_cold",
            public_key_jwk=public_a,
            address=address_a,
            signature=_signature(key_a, wallet_binding_payload(
                user_id=1,
                wallet_type="self_custody_cold",
                address=address_a,
                public_key_jwk=public_a,
            )),
            backup_confirmed=True,
        )
        wallet_b = bind_self_custody_wallet(
            conn,
            user_id=1,
            wallet_type="self_custody_cold",
            public_key_jwk=public_b,
            address=address_b,
            signature=_signature(key_b, wallet_binding_payload(
                user_id=1,
                wallet_type="self_custody_cold",
                address=address_b,
                public_key_jwk=public_b,
            )),
            backup_confirmed=True,
        )
        deleted = delete_cold_wallet(conn, user_id=1, address=address_b, reason="remove selected")
        status = wallet_onboarding_status(conn, points_service=points, user_id=1)
        conn.commit()
    finally:
        conn.close()

    assert wallet_a["is_primary"] is True
    assert wallet_b["is_primary"] is False
    assert deleted["address"] == address_b
    assert deleted["status"] == "lost"
    assert status["wallet"]["address"] == address_a
    visible_addresses = {item["address"] for item in status["wallets"]}
    assert address_a in visible_addresses
    assert address_b not in visible_addresses


def test_wallet_ledger_flow_snapshot_survives_cold_wallet_delete_switch_and_restore(tmp_path):
    points = _points(tmp_path)
    key_a = ec.generate_private_key(ec.SECP256R1())
    public_a = _public_jwk(key_a)
    address_a = address_from_public_key(public_a)
    payload_a = wallet_binding_payload(
        user_id=1,
        wallet_type="self_custody_cold",
        address=address_a,
        public_key_jwk=public_a,
    )
    key_b = ec.generate_private_key(ec.SECP256R1())
    public_b = _public_jwk(key_b)
    address_b = address_from_public_key(public_b)
    payload_b = wallet_binding_payload(
        user_id=1,
        wallet_type="self_custody_cold",
        address=address_b,
        public_key_jwk=public_b,
    )

    conn = points.get_db()
    try:
        points.ensure_schema(conn)
        bind_self_custody_wallet(
            conn,
            user_id=1,
            wallet_type="self_custody_cold",
            public_key_jwk=public_a,
            address=address_a,
            signature=_signature(key_a, payload_a),
            backup_confirmed=True,
        )
        conn.commit()
    finally:
        conn.close()

    bonus = award_signup_bonus_after_wallet_onboarding(
        points_service=points,
        user_id=1,
        actor={"id": 1, "username": "alice", "role": "user"},
    )
    assert bonus["created"] is True
    ledger_after_a = points.list_ledger(user_id=1, limit=1)[0]
    assert ledger_after_a["wallet_flow"]["destination_wallet_address"] == address_a
    assert points.get_wallet(1)["points_balance"] == 100

    conn = points.get_db()
    try:
        points.ensure_schema(conn)
        delete_primary_cold_wallet(conn, user_id=1, reason="lost A")
        conn.commit()
    finally:
        conn.close()
    assert points.get_wallet(1)["points_balance"] == 0
    assert points.list_ledger(user_id=1, limit=1)[0]["wallet_flow"]["destination_wallet_address"] == address_a

    conn = points.get_db()
    try:
        points.ensure_schema(conn)
        bind_self_custody_wallet(
            conn,
            user_id=1,
            wallet_type="self_custody_cold",
            public_key_jwk=public_b,
            address=address_b,
            signature=_signature(key_b, payload_b),
            backup_confirmed=True,
        )
        conn.commit()
    finally:
        conn.close()
    assert points.get_wallet(1)["points_balance"] == 0
    assert points.list_ledger(user_id=1, limit=1)[0]["wallet_flow"]["destination_wallet_address"] == address_a
    with pytest.raises(ValueError, match="insufficient balance"):
        points.record_transaction(
            user_id=1,
            currency_type="points",
            direction="debit",
            amount=1,
            action_type="spend:post_cost_standard",
        )

    conn = points.get_db()
    try:
        points.ensure_schema(conn)
        delete_primary_cold_wallet(conn, user_id=1, reason="switch back to A")
        restore_payload = wallet_binding_payload(
            user_id=1,
            wallet_type="imported_cold",
            address=address_a,
            public_key_jwk=public_a,
        )
        restored = bind_self_custody_wallet(
            conn,
            user_id=1,
            wallet_type="imported_cold",
            public_key_jwk=public_a,
            address=address_a,
            signature=_signature(key_a, restore_payload),
            backup_confirmed=True,
        )
        conn.commit()
    finally:
        conn.close()

    assert restored["address"] == address_a
    assert points.get_wallet(1)["points_balance"] == 100
    ledger_after_restore = points.list_ledger(user_id=1, limit=1)[0]
    assert ledger_after_restore["wallet_flow"]["destination_wallet_address"] == address_a
    assert ledger_after_restore["public_metadata"]["wallet_flow_snapshot"]["destination_wallet_address"] == address_a
