import base64
import sqlite3

import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec, utils

from services.platform.db_mode_triggers import register_app_mode_function
from services.points_chain import (
    BURN_WALLET_ADDRESS,
    PointsLedgerService,
    address_from_public_key,
    award_signup_bonus_after_wallet_onboarding,
    bind_self_custody_wallet,
    create_multisig_wallet,
    create_official_hot_wallet,
    delete_primary_cold_wallet,
    ensure_system_wallets,
    ensure_wallet_identity_schema,
    wallet_binding_payload,
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
    assert multisig["wallet_type"] == "multisig"
    assert multisig["metadata"]["multisig_policy"]["threshold"] == 2
    assert status["wallet"]["address"] == official["address"]
    assert status["signup_bonus_granted"] is False


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
    assert status_after_delete["wallet_required"] is True
    assert restored["id"] == wallet["id"]
    assert restored["address"] == address
    assert restored["wallet_type"] == "imported_cold"
    assert restored["status"] == "active"
    assert restored["is_primary"] is True
    assert status_after_restore["wallet"]["address"] == address
    assert official["wallet_type"] == "official_hot"
