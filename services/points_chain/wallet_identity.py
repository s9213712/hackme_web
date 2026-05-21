"""PointsChain simulated blockchain wallet identity contract.

This module stores wallet public identity only. User-created cold wallet private
keys are generated and held by the browser; the server accepts public keys,
addresses, and signatures proving possession, but rejects private-key material.
"""

from __future__ import annotations

import base64
import json
import re

from .schema import canonical_json, sha256_text, utc_now


WALLET_ADDRESS_RE = re.compile(r"^pc1[a-f0-9]{48}$")
WALLET_IDENTITY_TYPES = {"official_hot", "self_custody_cold", "imported_cold", "multisig", "mint", "burn"}
USER_WALLET_IDENTITY_TYPES = {"official_hot", "self_custody_cold", "imported_cold", "multisig"}
SYSTEM_WALLET_IDENTITY_TYPES = {"mint", "burn"}
WALLET_CUSTODY_MODES = {"server_hot", "self_custody", "multisig", "system"}
WALLET_IDENTITY_STATUSES = {"pending_backup", "active", "revoked", "lost", "disabled"}
WALLET_KEY_ALGORITHMS = {"ECDSA_P256_SHA256", "MULTISIG_POLICY_V1", "SYSTEM_SIMULATED_V1"}


def _sql_in(values):
    return ", ".join(f"'{value}'" for value in sorted(values))


def ensure_wallet_identity_schema(conn):
    conn.execute(
        f"""
        CREATE TABLE IF NOT EXISTS points_wallet_identities (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
            address TEXT NOT NULL UNIQUE,
            wallet_type TEXT NOT NULL CHECK (wallet_type IN ({_sql_in(WALLET_IDENTITY_TYPES)})),
            custody_mode TEXT NOT NULL CHECK (custody_mode IN ({_sql_in(WALLET_CUSTODY_MODES)})),
            key_algorithm TEXT NOT NULL CHECK (key_algorithm IN ({_sql_in(WALLET_KEY_ALGORITHMS)})),
            public_key_jwk_json TEXT NOT NULL DEFAULT '{{}}',
            public_key_hash TEXT NOT NULL,
            server_private_key_stored INTEGER NOT NULL DEFAULT 0 CHECK (server_private_key_stored IN (0, 1)),
            is_primary INTEGER NOT NULL DEFAULT 0 CHECK (is_primary IN (0, 1)),
            status TEXT NOT NULL DEFAULT 'pending_backup' CHECK (status IN ({_sql_in(WALLET_IDENTITY_STATUSES)})),
            label TEXT NOT NULL DEFAULT '',
            backup_confirmed_at TEXT,
            imported_at TEXT,
            revoked_at TEXT,
            metadata_json TEXT NOT NULL DEFAULT '{{}}',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_points_wallet_identity_one_primary
        ON points_wallet_identities(user_id)
        WHERE user_id IS NOT NULL AND is_primary=1 AND status IN ('pending_backup', 'active')
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_points_wallet_identity_user
        ON points_wallet_identities(user_id, status, created_at)
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS points_wallet_onboarding_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
            wallet_identity_id INTEGER REFERENCES points_wallet_identities(id) ON DELETE SET NULL,
            event_type TEXT NOT NULL,
            detail_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL
        )
        """
    )


def _json_loads(raw, fallback=None):
    if not raw:
        return fallback if fallback is not None else {}
    try:
        value = json.loads(raw)
        return value if isinstance(value, (dict, list)) else (fallback if fallback is not None else {})
    except Exception:
        return fallback if fallback is not None else {}


def _b64url_decode(value):
    raw = str(value or "").encode("ascii")
    raw += b"=" * ((4 - len(raw) % 4) % 4)
    return base64.urlsafe_b64decode(raw)


def _b64url_uint(value):
    return int.from_bytes(_b64url_decode(value), "big")


def _b64url_encode(data):
    return base64.urlsafe_b64encode(bytes(data)).decode("ascii").rstrip("=")


def canonical_public_jwk(public_key_jwk):
    if not isinstance(public_key_jwk, dict):
        raise ValueError("public_key_jwk must be an object")
    forbidden = {"d", "p", "q", "dp", "dq", "qi", "oth", "private_key", "seed", "secret"}
    if any(key in public_key_jwk for key in forbidden):
        raise ValueError("private key material must not be sent to the server")
    jwk = {
        "crv": str(public_key_jwk.get("crv") or "").strip(),
        "kty": str(public_key_jwk.get("kty") or "").strip(),
        "x": str(public_key_jwk.get("x") or "").strip(),
        "y": str(public_key_jwk.get("y") or "").strip(),
    }
    if jwk["kty"] != "EC" or jwk["crv"] != "P-256" or not jwk["x"] or not jwk["y"]:
        raise ValueError("wallet public key must be ECDSA P-256 JWK")
    # Validate base64url coordinates now so malformed keys fail before storage.
    _b64url_uint(jwk["x"])
    _b64url_uint(jwk["y"])
    return jwk


def public_key_hash(public_key_jwk):
    return sha256_text(canonical_json(canonical_public_jwk(public_key_jwk)))


def address_from_public_key(public_key_jwk):
    return address_from_hash(public_key_hash(public_key_jwk))


def address_from_hash(value):
    return "pc1" + sha256_text(value)[:48]


def normalize_wallet_address(address):
    address = str(address or "").strip().lower()
    if not WALLET_ADDRESS_RE.fullmatch(address):
        raise ValueError("wallet address format is invalid")
    return address


def official_hot_wallet_address(chain_secret, user_id):
    return address_from_hash(f"official_hot:{int(user_id)}:{chain_secret or ''}")


def system_wallet_address(chain_secret, wallet_type):
    wallet_type = str(wallet_type or "").strip().lower()
    if wallet_type not in SYSTEM_WALLET_IDENTITY_TYPES:
        raise ValueError("system wallet type must be mint or burn")
    return address_from_hash(f"system:{wallet_type}:{chain_secret or ''}")


def multisig_policy_hash(*, threshold, signer_addresses):
    normalized = normalize_multisig_policy(threshold=threshold, signer_addresses=signer_addresses)
    return sha256_text(canonical_json(normalized))


def multisig_wallet_address(*, threshold, signer_addresses):
    return address_from_hash(multisig_policy_hash(threshold=threshold, signer_addresses=signer_addresses))


def normalize_multisig_policy(*, threshold, signer_addresses):
    try:
        threshold = int(threshold)
    except Exception as exc:
        raise ValueError("multisig threshold must be an integer") from exc
    signers = []
    for item in signer_addresses or []:
        signers.append(normalize_wallet_address(item))
    signers = sorted(set(signers))
    if len(signers) < 2:
        raise ValueError("multisig wallet requires at least two signer addresses")
    if threshold < 1 or threshold > len(signers):
        raise ValueError("multisig threshold must be between 1 and signer count")
    return {"threshold": threshold, "signer_addresses": signers}


def wallet_binding_payload(*, user_id, wallet_type, address, public_key_jwk):
    jwk = canonical_public_jwk(public_key_jwk)
    key_hash = public_key_hash(jwk)
    return {
        "action": "points_wallet_bind",
        "address": normalize_wallet_address(address),
        "key_algorithm": "ECDSA_P256_SHA256",
        "public_key_hash": key_hash,
        "user_id": int(user_id),
        "wallet_type": str(wallet_type or "").strip().lower(),
    }


def _public_key_from_jwk(public_key_jwk):
    from cryptography.hazmat.primitives.asymmetric import ec

    jwk = canonical_public_jwk(public_key_jwk)
    numbers = ec.EllipticCurvePublicNumbers(_b64url_uint(jwk["x"]), _b64url_uint(jwk["y"]), ec.SECP256R1())
    return numbers.public_key()


def verify_wallet_binding_signature(*, user_id, wallet_type, address, public_key_jwk, signature):
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import ec, utils

    payload = canonical_json(wallet_binding_payload(
        user_id=user_id,
        wallet_type=wallet_type,
        address=address,
        public_key_jwk=public_key_jwk,
    )).encode("utf-8")
    raw_signature = _b64url_decode(signature)
    if len(raw_signature) == 64:
        r = int.from_bytes(raw_signature[:32], "big")
        s = int.from_bytes(raw_signature[32:], "big")
        signature_der = utils.encode_dss_signature(r, s)
    else:
        signature_der = raw_signature
    try:
        _public_key_from_jwk(public_key_jwk).verify(signature_der, payload, ec.ECDSA(hashes.SHA256()))
    except InvalidSignature as exc:
        raise ValueError("wallet signature verification failed") from exc
    return True


def serialize_wallet_identity(row):
    if not row:
        return None
    metadata = _json_loads(row["metadata_json"], {})
    return {
        "id": row["id"],
        "user_id": row["user_id"],
        "address": row["address"],
        "wallet_type": row["wallet_type"],
        "custody_mode": row["custody_mode"],
        "key_algorithm": row["key_algorithm"],
        "public_key_hash": row["public_key_hash"],
        "server_private_key_stored": bool(row["server_private_key_stored"]),
        "is_primary": bool(row["is_primary"]),
        "status": row["status"],
        "label": row["label"],
        "backup_confirmed_at": row["backup_confirmed_at"],
        "imported_at": row["imported_at"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "metadata": metadata,
    }


def _record_onboarding_event(conn, *, user_id, wallet_identity_id=None, event_type, detail=None):
    conn.execute(
        """
        INSERT INTO points_wallet_onboarding_events (
            user_id, wallet_identity_id, event_type, detail_json, created_at
        ) VALUES (?, ?, ?, ?, ?)
        """,
        (
            int(user_id) if user_id is not None else None,
            int(wallet_identity_id) if wallet_identity_id else None,
            str(event_type),
            canonical_json(detail or {}),
            utc_now(),
        ),
    )


def get_primary_wallet_identity(conn, user_id):
    ensure_wallet_identity_schema(conn)
    return conn.execute(
        """
        SELECT * FROM points_wallet_identities
        WHERE user_id=? AND is_primary=1 AND status IN ('pending_backup', 'active')
        ORDER BY id DESC
        LIMIT 1
        """,
        (int(user_id),),
    ).fetchone()


def list_wallet_identities(conn, user_id):
    ensure_wallet_identity_schema(conn)
    return [
        serialize_wallet_identity(row)
        for row in conn.execute(
            """
            SELECT * FROM points_wallet_identities
            WHERE user_id=?
            ORDER BY is_primary DESC, created_at DESC, id DESC
            """,
            (int(user_id),),
        ).fetchall()
    ]


def signup_bonus_granted(conn, user_id):
    try:
        row = conn.execute(
            """
            SELECT 1 FROM points_ledger
            WHERE user_id=? AND action_type='new_user_signup_bonus'
            LIMIT 1
            """,
            (int(user_id),),
        ).fetchone()
        return bool(row)
    except Exception:
        return False


def ensure_system_wallets(conn, *, chain_secret):
    ensure_wallet_identity_schema(conn)
    created = []
    for wallet_type in ("mint", "burn"):
        address = system_wallet_address(chain_secret, wallet_type)
        row = conn.execute("SELECT * FROM points_wallet_identities WHERE address=?", (address,)).fetchone()
        if row:
            created.append(serialize_wallet_identity(row))
            continue
        now = utc_now()
        cur = conn.execute(
            """
            INSERT INTO points_wallet_identities (
                user_id, address, wallet_type, custody_mode, key_algorithm,
                public_key_jwk_json, public_key_hash, server_private_key_stored,
                is_primary, status, label, backup_confirmed_at, metadata_json,
                created_at, updated_at
            ) VALUES (NULL, ?, ?, 'system', 'SYSTEM_SIMULATED_V1', '{}', ?, 0, 0, 'active', ?, ?, ?, ?, ?)
            """,
            (
                address,
                wallet_type,
                sha256_text(address),
                "Mint wallet" if wallet_type == "mint" else "Burn wallet",
                now,
                canonical_json({"system_wallet": wallet_type, "financial_source_of_truth": "points_ledger"}),
                now,
                now,
            ),
        )
        row = conn.execute("SELECT * FROM points_wallet_identities WHERE id=?", (cur.lastrowid,)).fetchone()
        created.append(serialize_wallet_identity(row))
    return created


def create_official_hot_wallet(conn, *, user_id, chain_secret, label="官方熱錢包"):
    ensure_wallet_identity_schema(conn)
    existing = get_primary_wallet_identity(conn, user_id)
    if existing:
        return serialize_wallet_identity(existing)
    now = utc_now()
    address = official_hot_wallet_address(chain_secret, user_id)
    cur = conn.execute(
        """
        INSERT INTO points_wallet_identities (
            user_id, address, wallet_type, custody_mode, key_algorithm,
            public_key_jwk_json, public_key_hash, server_private_key_stored,
            is_primary, status, label, backup_confirmed_at, metadata_json,
            created_at, updated_at
        ) VALUES (?, ?, 'official_hot', 'server_hot', 'SYSTEM_SIMULATED_V1', '{}', ?, 0, 1, 'active', ?, ?, ?, ?, ?)
        """,
        (
            int(user_id),
            address,
            sha256_text(address),
            str(label or "官方熱錢包")[:120],
            now,
            canonical_json({"server_managed": True, "private_key_exportable": False}),
            now,
            now,
        ),
    )
    _record_onboarding_event(conn, user_id=user_id, wallet_identity_id=cur.lastrowid, event_type="official_hot_wallet_created")
    return serialize_wallet_identity(conn.execute("SELECT * FROM points_wallet_identities WHERE id=?", (cur.lastrowid,)).fetchone())


def bind_self_custody_wallet(
    conn,
    *,
    user_id,
    wallet_type,
    public_key_jwk,
    address,
    signature,
    backup_confirmed,
    label="",
):
    ensure_wallet_identity_schema(conn)
    wallet_type = str(wallet_type or "").strip().lower()
    if wallet_type not in {"self_custody_cold", "imported_cold"}:
        raise ValueError("wallet_type must be self_custody_cold or imported_cold")
    if not backup_confirmed:
        raise ValueError("private key backup confirmation is required")
    jwk = canonical_public_jwk(public_key_jwk)
    expected = address_from_public_key(jwk)
    address = normalize_wallet_address(address)
    if address != expected:
        raise ValueError("wallet address does not match public key")
    verify_wallet_binding_signature(
        user_id=user_id,
        wallet_type=wallet_type,
        address=address,
        public_key_jwk=jwk,
        signature=signature,
    )
    existing = get_primary_wallet_identity(conn, user_id)
    if existing:
        if existing["address"] == address:
            return serialize_wallet_identity(existing)
        raise ValueError("primary wallet already exists")
    row = conn.execute("SELECT * FROM points_wallet_identities WHERE address=?", (address,)).fetchone()
    if row and int(row["user_id"] or 0) != int(user_id):
        raise ValueError("wallet address is already bound to another user")
    now = utc_now()
    if row:
        metadata = _json_loads(row["metadata_json"], {})
        metadata.update({
            "private_key_server_received": False,
            "backup_confirmed": True,
            "restored_requires_private_key": True,
            "restored_at": now,
            "previous_status": row["status"],
        })
        conn.execute(
            """
            UPDATE points_wallet_identities
            SET wallet_type=?, custody_mode='self_custody', key_algorithm='ECDSA_P256_SHA256',
                public_key_jwk_json=?, public_key_hash=?, server_private_key_stored=0,
                is_primary=1, status='active', label=?, backup_confirmed_at=?,
                imported_at=?, revoked_at=NULL, metadata_json=?, updated_at=?
            WHERE id=?
            """,
            (
                wallet_type,
                canonical_json(jwk),
                public_key_hash(jwk),
                str(label or ("冷錢包" if wallet_type == "self_custody_cold" else "匯入冷錢包"))[:120],
                now,
                now if wallet_type == "imported_cold" else row["imported_at"],
                canonical_json(metadata),
                now,
                row["id"],
            ),
        )
        _record_onboarding_event(
            conn,
            user_id=user_id,
            wallet_identity_id=row["id"],
            event_type=f"{wallet_type}_restored",
            detail={"address": address, "restore_requires_private_key": True},
        )
        return serialize_wallet_identity(conn.execute("SELECT * FROM points_wallet_identities WHERE id=?", (row["id"],)).fetchone())
    cur = conn.execute(
        """
        INSERT INTO points_wallet_identities (
            user_id, address, wallet_type, custody_mode, key_algorithm,
            public_key_jwk_json, public_key_hash, server_private_key_stored,
            is_primary, status, label, backup_confirmed_at, imported_at,
            metadata_json, created_at, updated_at
        ) VALUES (?, ?, ?, 'self_custody', 'ECDSA_P256_SHA256', ?, ?, 0, 1, 'active', ?, ?, ?, ?, ?, ?)
        """,
        (
            int(user_id),
            address,
            wallet_type,
            canonical_json(jwk),
            public_key_hash(jwk),
            str(label or ("冷錢包" if wallet_type == "self_custody_cold" else "匯入冷錢包"))[:120],
            now,
            now if wallet_type == "imported_cold" else None,
            canonical_json({"private_key_server_received": False, "backup_confirmed": True}),
            now,
            now,
        ),
    )
    _record_onboarding_event(conn, user_id=user_id, wallet_identity_id=cur.lastrowid, event_type=f"{wallet_type}_bound")
    return serialize_wallet_identity(conn.execute("SELECT * FROM points_wallet_identities WHERE id=?", (cur.lastrowid,)).fetchone())


def delete_primary_cold_wallet(conn, *, user_id, reason=""):
    ensure_wallet_identity_schema(conn)
    primary = get_primary_wallet_identity(conn, user_id)
    if not primary:
        raise ValueError("no active wallet is bound")
    if primary["wallet_type"] not in {"self_custody_cold", "imported_cold"} or primary["custody_mode"] != "self_custody":
        raise ValueError("only self-custody cold wallets can be deleted; official hot wallets cannot be deleted")
    now = utc_now()
    metadata = _json_loads(primary["metadata_json"], {})
    metadata.update({
        "deleted_at": now,
        "delete_reason": str(reason or "")[:240],
        "restore_requires_private_key": True,
        "financial_source_of_truth": "points_ledger",
    })
    conn.execute(
        """
        UPDATE points_wallet_identities
        SET is_primary=0, status='lost', revoked_at=?, metadata_json=?, updated_at=?
        WHERE id=?
        """,
        (now, canonical_json(metadata), now, primary["id"]),
    )
    _record_onboarding_event(
        conn,
        user_id=user_id,
        wallet_identity_id=primary["id"],
        event_type="cold_wallet_deleted",
        detail={
            "address": primary["address"],
            "wallet_type": primary["wallet_type"],
            "restore_requires_private_key": True,
        },
    )
    return serialize_wallet_identity(conn.execute("SELECT * FROM points_wallet_identities WHERE id=?", (primary["id"],)).fetchone())


def create_multisig_wallet(conn, *, user_id, threshold, signer_addresses, label="多簽錢包"):
    ensure_wallet_identity_schema(conn)
    existing = get_primary_wallet_identity(conn, user_id)
    if existing:
        return serialize_wallet_identity(existing)
    policy = normalize_multisig_policy(threshold=threshold, signer_addresses=signer_addresses)
    address = multisig_wallet_address(threshold=policy["threshold"], signer_addresses=policy["signer_addresses"])
    row = conn.execute("SELECT * FROM points_wallet_identities WHERE address=?", (address,)).fetchone()
    if row and int(row["user_id"] or 0) != int(user_id):
        raise ValueError("multisig wallet address is already bound to another user")
    now = utc_now()
    cur = conn.execute(
        """
        INSERT INTO points_wallet_identities (
            user_id, address, wallet_type, custody_mode, key_algorithm,
            public_key_jwk_json, public_key_hash, server_private_key_stored,
            is_primary, status, label, backup_confirmed_at, metadata_json,
            created_at, updated_at
        ) VALUES (?, ?, 'multisig', 'multisig', 'MULTISIG_POLICY_V1', '{}', ?, 0, 1, 'active', ?, ?, ?, ?, ?)
        """,
        (
            int(user_id),
            address,
            multisig_policy_hash(threshold=policy["threshold"], signer_addresses=policy["signer_addresses"]),
            str(label or "多簽錢包")[:120],
            now,
            canonical_json({"multisig_policy": policy, "private_key_server_received": False}),
            now,
            now,
        ),
    )
    _record_onboarding_event(conn, user_id=user_id, wallet_identity_id=cur.lastrowid, event_type="multisig_wallet_created", detail=policy)
    return serialize_wallet_identity(conn.execute("SELECT * FROM points_wallet_identities WHERE id=?", (cur.lastrowid,)).fetchone())


def wallet_onboarding_status(conn, *, points_service, user_id):
    ensure_wallet_identity_schema(conn)
    if points_service and hasattr(points_service, "ensure_schema"):
        points_service.ensure_schema(conn)
    chain_secret = getattr(points_service, "chain_secret", "") if points_service else ""
    system_wallets = ensure_system_wallets(conn, chain_secret=chain_secret)
    primary = get_primary_wallet_identity(conn, user_id)
    primary_payload = serialize_wallet_identity(primary)
    bonus_granted = signup_bonus_granted(conn, user_id)
    return {
        "required": not bool(primary_payload) or not bonus_granted,
        "wallet_required": not bool(primary_payload),
        "signup_bonus_required": not bonus_granted,
        "signup_bonus_granted": bonus_granted,
        "wallet": primary_payload,
        "wallets": list_wallet_identities(conn, user_id),
        "system_wallets": system_wallets,
        "allowed_modes": ["official_hot", "self_custody_cold", "imported_cold", "multisig"],
        "private_key_policy": {
            "server_accepts_private_key": False,
            "client_key_algorithm": "ECDSA_P256_SHA256",
            "address_prefix": "pc1",
        },
    }


def award_signup_bonus_after_wallet_onboarding(*, points_service, user_id, actor=None):
    conn = points_service.get_db()
    try:
        points_service.ensure_schema(conn)
        primary = get_primary_wallet_identity(conn, user_id)
        if not primary or primary["status"] != "active":
            raise ValueError("wallet onboarding is not complete")
        if signup_bonus_granted(conn, user_id):
            return {"created": False, "already_granted": True, "ledger": None}
    finally:
        conn.close()
    return points_service.award_signup_bonus(user_id=user_id, actor=actor)
