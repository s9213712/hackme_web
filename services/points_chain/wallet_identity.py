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


COLD_WALLET_ADDRESS_RE = re.compile(r"^pc1[a-f0-9]{48}$")
INTERNAL_WALLET_ADDRESS_RE = re.compile(r"^pc0[a-f0-9]{48}$")
WALLET_ADDRESS_RE = re.compile(r"^pc[01][a-f0-9]{48}$")
MINT_WALLET_ADDRESS = "mint" + ("0" * 60)
BURN_WALLET_ADDRESS = "0" * 64
LEGACY_PC0_BURN_WALLET_ADDRESS = "pc0" + ("0" * 48)
SYSTEM_WALLET_ADDRESS_RE = re.compile(
    rf"^(?:{re.escape(MINT_WALLET_ADDRESS)}|{re.escape(BURN_WALLET_ADDRESS)})$"
)
POINTS_CHAIN_ADDRESS_RE = re.compile(
    rf"^(?:pc[01][a-f0-9]{{48}}|{re.escape(MINT_WALLET_ADDRESS)}|{re.escape(BURN_WALLET_ADDRESS)})$"
)
WALLET_IDENTITY_TYPES = {"official_hot", "self_custody_cold", "imported_cold", "multisig", "user_multisig_preview", "official_treasury_multisig", "mint", "burn"}
USER_WALLET_IDENTITY_TYPES = {"official_hot", "self_custody_cold", "imported_cold", "multisig", "user_multisig_preview"}
SYSTEM_WALLET_IDENTITY_TYPES = {"mint", "burn"}
WALLET_CUSTODY_MODES = {"server_hot", "self_custody", "multisig", "system"}
WALLET_SCOPES = {"user", "official_treasury", "system_reserve", "exchange_fund"}
WALLET_SPEND_CAPABILITIES = {"enabled", "receive_only", "disabled"}
WALLET_IDENTITY_STATUSES = {"pending_backup", "active", "revoked", "lost", "disabled"}
WALLET_KEY_ALGORITHMS = {"ECDSA_P256_SHA256", "MULTISIG_POLICY_V1", "SYSTEM_SIMULATED_V1"}
ADDRESS_DISPUTE_SIGNATURE_PURPOSES = {"address_dispute_open", "address_dispute_reply"}


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
            wallet_scope TEXT NOT NULL DEFAULT 'user' CHECK (wallet_scope IN ({_sql_in(WALLET_SCOPES)})),
            spend_capability TEXT NOT NULL DEFAULT 'enabled' CHECK (spend_capability IN ({_sql_in(WALLET_SPEND_CAPABILITIES)})),
            metadata_json TEXT NOT NULL DEFAULT '{{}}',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    cols = {row["name"] for row in conn.execute("PRAGMA table_info(points_wallet_identities)").fetchall()}
    if "wallet_scope" not in cols:
        conn.execute("ALTER TABLE points_wallet_identities ADD COLUMN wallet_scope TEXT NOT NULL DEFAULT 'user'")
    if "spend_capability" not in cols:
        conn.execute("ALTER TABLE points_wallet_identities ADD COLUMN spend_capability TEXT NOT NULL DEFAULT 'enabled'")
    now = utc_now()
    conn.execute(
        """
        UPDATE points_wallet_identities
        SET wallet_scope='system_reserve',
            spend_capability='disabled',
            updated_at=?
        WHERE wallet_type IN ('mint', 'burn')
          AND (wallet_scope!='system_reserve' OR spend_capability!='disabled')
        """,
        (now,),
    )
    conn.execute(
        """
        UPDATE points_wallet_identities
        SET wallet_scope='official_treasury',
            spend_capability='enabled',
            updated_at=?
        WHERE wallet_type='official_treasury_multisig'
          AND (wallet_scope!='official_treasury' OR spend_capability!='enabled')
        """,
        (now,),
    )
    conn.execute(
        """
        UPDATE points_wallet_identities
        SET wallet_scope='user',
            spend_capability='receive_only',
            updated_at=?
        WHERE custody_mode='multisig'
          AND wallet_type IN ('multisig', 'user_multisig_preview')
          AND (wallet_scope!='user' OR spend_capability!='receive_only')
        """,
        (now,),
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
        CREATE UNIQUE INDEX IF NOT EXISTS idx_points_wallet_identity_one_official_hot
        ON points_wallet_identities(user_id)
        WHERE user_id IS NOT NULL AND wallet_type='official_hot' AND status IN ('pending_backup', 'active')
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
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS points_wallet_identity_bindings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            wallet_identity_id INTEGER NOT NULL REFERENCES points_wallet_identities(id) ON DELETE CASCADE,
            address TEXT NOT NULL,
            wallet_type TEXT NOT NULL,
            is_primary INTEGER NOT NULL DEFAULT 0 CHECK (is_primary IN (0, 1)),
            status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'lost', 'revoked', 'disabled')),
            label TEXT NOT NULL DEFAULT '',
            metadata_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(user_id, address)
        )
        """
    )
    conn.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_points_wallet_binding_one_primary
        ON points_wallet_identity_bindings(user_id)
        WHERE is_primary=1 AND status='active'
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_points_wallet_binding_user
        ON points_wallet_identity_bindings(user_id, status, created_at)
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


def internal_address_from_hash(value):
    return "pc0" + sha256_text(value)[:48]


def normalize_wallet_address(address):
    address = str(address or "").strip().lower()
    if not WALLET_ADDRESS_RE.fullmatch(address):
        raise ValueError("wallet address format is invalid")
    return address


def normalize_points_chain_address(address):
    address = str(address or "").strip().lower()
    if not POINTS_CHAIN_ADDRESS_RE.fullmatch(address):
        raise ValueError("PointsChain address format is invalid")
    return address


def is_pc0_internal_address(address):
    return bool(INTERNAL_WALLET_ADDRESS_RE.fullmatch(str(address or "").strip().lower()))


def has_pc0_prefix(address):
    return str(address or "").strip().lower().startswith("pc0")


def is_pc1_chain_address(address):
    return bool(COLD_WALLET_ADDRESS_RE.fullmatch(str(address or "").strip().lower()))


def is_system_special_address(address):
    return bool(SYSTEM_WALLET_ADDRESS_RE.fullmatch(str(address or "").strip().lower()))


def is_burn_wallet_address(address):
    normalized = str(address or "").strip().lower()
    return normalized in {BURN_WALLET_ADDRESS, LEGACY_PC0_BURN_WALLET_ADDRESS}


def official_hot_wallet_address(chain_secret, user_id):
    return internal_address_from_hash(f"official_hot:{int(user_id)}:{chain_secret or ''}")


def system_wallet_address(chain_secret, wallet_type):
    wallet_type = str(wallet_type or "").strip().lower()
    if wallet_type not in SYSTEM_WALLET_IDENTITY_TYPES:
        raise ValueError("system wallet type must be mint or burn")
    if wallet_type == "burn":
        return BURN_WALLET_ADDRESS
    return MINT_WALLET_ADDRESS


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


def wallet_transaction_payload(
    *,
    user_id,
    source_wallet_address,
    destination_wallet_address,
    amount_points,
    fee_points,
    request_uuid,
    memo="",
    chain_branch="main",
    proposal_id="",
    action_type="points_wallet_transfer",
    payload_hash="",
    signer_key_id="",
):
    return {
        "action": str(action_type or "points_wallet_transfer").strip() or "points_wallet_transfer",
        "amount_points": int(amount_points),
        "chain_branch": str(chain_branch or "main").strip() or "main",
        "destination_wallet_address": normalize_wallet_address(destination_wallet_address),
        "fee_points": int(fee_points),
        "memo": str(memo or "")[:240],
        "payload_hash": str(payload_hash or "").strip(),
        "proposal_id": str(proposal_id or "").strip()[:120],
        "request_uuid": str(request_uuid or "").strip()[:120],
        "signer_key_id": str(signer_key_id or "").strip()[:120],
        "source_wallet_address": normalize_wallet_address(source_wallet_address),
        "user_id": int(user_id),
    }


def wallet_service_fee_payload(
    *,
    user_id,
    source_wallet_address,
    item_key,
    quantity,
    amount_points,
    request_uuid,
    reference_type="",
    reference_id="",
    chain_branch="main",
    proposal_id="",
    action_type="points_service_fee_payment",
    payload_hash="",
    signer_key_id="",
):
    return {
        "action": str(action_type or "points_service_fee_payment").strip() or "points_service_fee_payment",
        "amount_points": int(amount_points),
        "chain_branch": str(chain_branch or "main").strip() or "main",
        "item_key": str(item_key or "").strip(),
        "payload_hash": str(payload_hash or "").strip(),
        "proposal_id": str(proposal_id or "").strip()[:120],
        "quantity": int(quantity),
        "reference_id": str(reference_id or "")[:240],
        "reference_type": str(reference_type or "")[:120],
        "request_uuid": str(request_uuid or "").strip()[:120],
        "signer_key_id": str(signer_key_id or "").strip()[:120],
        "source_wallet_address": normalize_wallet_address(source_wallet_address),
        "user_id": int(user_id),
    }


def address_dispute_payload(
    *,
    tx_hash,
    from_wallet_address,
    to_wallet_address,
    amount_points,
    statement_hash,
    evidence_hash,
    nonce,
    chain_branch="main",
    purpose="address_dispute_open",
    runtime_mode="",
):
    purpose = str(purpose or "").strip()
    if purpose not in ADDRESS_DISPUTE_SIGNATURE_PURPOSES:
        raise ValueError("address dispute signature purpose is invalid")
    from_address = normalize_wallet_address(from_wallet_address)
    to_address = normalize_wallet_address(to_wallet_address)
    amount = int(amount_points)
    if amount < 0:
        raise ValueError("address dispute amount must be non-negative")
    nonce = str(nonce or "").strip()
    if len(nonce) < 8:
        raise ValueError("address dispute nonce is required")
    tx_hash = str(tx_hash or "").strip()
    if not tx_hash:
        raise ValueError("address dispute tx_hash is required")
    statement_hash = str(statement_hash or "").strip()
    evidence_hash = str(evidence_hash or "").strip()
    if len(statement_hash) != 64 or len(evidence_hash) != 64:
        raise ValueError("address dispute statement/evidence hashes are required")
    return {
        "amount": amount,
        "amount_points": amount,
        "chain_branch": str(chain_branch or "main").strip() or "main",
        "evidence_hash": evidence_hash,
        "from": from_address,
        "from_wallet_address": from_address,
        "nonce": nonce[:120],
        "purpose": purpose,
        "runtime_mode": str(runtime_mode or "").strip(),
        "statement_hash": statement_hash,
        "to": to_address,
        "to_wallet_address": to_address,
        "tx_hash": tx_hash,
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


def verify_wallet_transaction_signature(
    *,
    user_id,
    source_wallet_address,
    destination_wallet_address,
    amount_points,
    fee_points,
    request_uuid,
    memo,
    public_key_jwk,
    signature,
    chain_branch="main",
    proposal_id="",
    action_type="points_wallet_transfer",
    payload_hash="",
    signer_key_id="",
):
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import ec, utils

    payload = canonical_json(wallet_transaction_payload(
        user_id=user_id,
        source_wallet_address=source_wallet_address,
        destination_wallet_address=destination_wallet_address,
        amount_points=amount_points,
        fee_points=fee_points,
        request_uuid=request_uuid,
        memo=memo,
        chain_branch=chain_branch,
        proposal_id=proposal_id,
        action_type=action_type,
        payload_hash=payload_hash,
        signer_key_id=signer_key_id,
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
        raise ValueError("wallet transaction signature verification failed") from exc
    return True


def verify_wallet_service_fee_signature(
    *,
    user_id,
    source_wallet_address,
    item_key,
    quantity,
    amount_points,
    request_uuid,
    reference_type,
    reference_id,
    public_key_jwk,
    signature,
    chain_branch="main",
    proposal_id="",
    action_type="points_service_fee_payment",
    payload_hash="",
    signer_key_id="",
):
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import ec, utils

    payload = canonical_json(wallet_service_fee_payload(
        user_id=user_id,
        source_wallet_address=source_wallet_address,
        item_key=item_key,
        quantity=quantity,
        amount_points=amount_points,
        request_uuid=request_uuid,
        reference_type=reference_type,
        reference_id=reference_id,
        chain_branch=chain_branch,
        proposal_id=proposal_id,
        action_type=action_type,
        payload_hash=payload_hash,
        signer_key_id=signer_key_id,
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
        raise ValueError("wallet service fee signature verification failed") from exc
    return True


def verify_wallet_address_dispute_signature(
    *,
    tx_hash,
    from_wallet_address,
    to_wallet_address,
    amount_points,
    statement_hash,
    evidence_hash,
    nonce,
    chain_branch,
    purpose,
    signer_wallet_address,
    public_key_jwk,
    signature,
    runtime_mode="",
):
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import ec, utils

    signer_address = normalize_wallet_address(signer_wallet_address)
    public_jwk = canonical_public_jwk(public_key_jwk)
    expected_address = address_from_public_key(public_jwk)
    if signer_address != expected_address:
        raise ValueError("address dispute signature public key does not match signer address")
    purpose = str(purpose or "").strip()
    if purpose == "address_dispute_open" and signer_address != normalize_wallet_address(from_wallet_address):
        raise ValueError("address dispute opener must sign with the from address")
    if purpose == "address_dispute_reply" and signer_address != normalize_wallet_address(to_wallet_address):
        raise ValueError("address dispute reply must sign with the to address")
    payload = canonical_json(address_dispute_payload(
        tx_hash=tx_hash,
        from_wallet_address=from_wallet_address,
        to_wallet_address=to_wallet_address,
        amount_points=amount_points,
        statement_hash=statement_hash,
        evidence_hash=evidence_hash,
        nonce=nonce,
        chain_branch=chain_branch,
        purpose=purpose,
        runtime_mode=runtime_mode,
    )).encode("utf-8")
    raw_signature = _b64url_decode(signature)
    if len(raw_signature) == 64:
        r = int.from_bytes(raw_signature[:32], "big")
        s = int.from_bytes(raw_signature[32:], "big")
        signature_der = utils.encode_dss_signature(r, s)
    else:
        signature_der = raw_signature
    try:
        _public_key_from_jwk(public_jwk).verify(signature_der, payload, ec.ECDSA(hashes.SHA256()))
    except InvalidSignature as exc:
        raise ValueError("address dispute signature verification failed") from exc
    return True


def serialize_wallet_identity(row):
    if not row:
        return None
    metadata = _json_loads(row["metadata_json"], {})
    keys = set(row.keys())
    wallet_scope = row["wallet_scope"] if "wallet_scope" in keys else "user"
    spend_capability = row["spend_capability"] if "spend_capability" in keys else "enabled"
    stored_wallet_type = row["wallet_type"]
    public_wallet_type = stored_wallet_type
    if row["custody_mode"] == "multisig" and wallet_scope != "official_treasury":
        public_wallet_type = "user_multisig_preview"
        spend_capability = "receive_only"
    elif row["custody_mode"] == "multisig" and wallet_scope == "official_treasury":
        public_wallet_type = "official_treasury_multisig"
    return {
        "id": row["id"],
        "user_id": row["user_id"],
        "address": row["address"],
        "wallet_type": public_wallet_type,
        "stored_wallet_type": stored_wallet_type,
        "wallet_scope": wallet_scope,
        "custody_mode": row["custody_mode"],
        "spend_capability": spend_capability,
        "can_spend": bool(spend_capability == "enabled" and row["status"] == "active"),
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


def _wallet_identity_binding_view(row, binding):
    data = dict(row)
    binding_metadata = _json_loads(binding["metadata_json"], {})
    metadata = _json_loads(row["metadata_json"], {})
    metadata.update(binding_metadata)
    metadata.update({
        "address_control_model": "self_custody_private_key_controls_address_v1",
        "binding_record": True,
        "binding_id": int(binding["id"]),
    })
    data.update({
        "user_id": int(binding["user_id"]),
        "wallet_type": binding["wallet_type"] or row["wallet_type"],
        "is_primary": int(binding["is_primary"] or 0),
        "status": binding["status"],
        "label": binding["label"] or row["label"],
        "metadata_json": canonical_json(metadata),
        "created_at": binding["created_at"],
        "updated_at": binding["updated_at"],
    })
    return data


def _bound_wallet_identity_for_user_address(conn, user_id, address, *, active_only=True):
    status_filter = "AND b.status='active'" if active_only else ""
    return conn.execute(
        f"""
        SELECT w.*, b.id AS binding_id, b.user_id AS binding_user_id,
               b.wallet_type AS binding_wallet_type, b.is_primary AS binding_is_primary,
               b.status AS binding_status, b.label AS binding_label,
               b.metadata_json AS binding_metadata_json,
               b.created_at AS binding_created_at, b.updated_at AS binding_updated_at
        FROM points_wallet_identity_bindings b
        JOIN points_wallet_identities w ON w.id=b.wallet_identity_id
        WHERE b.user_id=? AND b.address=?
          {status_filter}
        LIMIT 1
        """,
        (int(user_id), str(address or "").strip().lower()),
    ).fetchone()


def _binding_view_from_joined_row(row):
    if not row:
        return None
    wallet = {key: row[key] for key in row.keys() if not str(key).startswith("binding_")}
    binding = {
        "id": row["binding_id"],
        "user_id": row["binding_user_id"],
        "wallet_type": row["binding_wallet_type"],
        "is_primary": row["binding_is_primary"],
        "status": row["binding_status"],
        "label": row["binding_label"],
        "metadata_json": row["binding_metadata_json"],
        "created_at": row["binding_created_at"],
        "updated_at": row["binding_updated_at"],
    }
    return _wallet_identity_binding_view(wallet, binding)


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
    row = conn.execute(
        """
        SELECT * FROM points_wallet_identities
        WHERE user_id=? AND is_primary=1 AND status IN ('pending_backup', 'active')
        ORDER BY id DESC
        LIMIT 1
        """,
        (int(user_id),),
    ).fetchone()
    if row:
        return row
    binding = conn.execute(
        """
        SELECT w.*, b.id AS binding_id, b.user_id AS binding_user_id,
               b.wallet_type AS binding_wallet_type, b.is_primary AS binding_is_primary,
               b.status AS binding_status, b.label AS binding_label,
               b.metadata_json AS binding_metadata_json,
               b.created_at AS binding_created_at, b.updated_at AS binding_updated_at
        FROM points_wallet_identity_bindings b
        JOIN points_wallet_identities w ON w.id=b.wallet_identity_id
        WHERE b.user_id=? AND b.is_primary=1 AND b.status='active'
        ORDER BY b.id DESC
        LIMIT 1
        """,
        (int(user_id),),
    ).fetchone()
    return _binding_view_from_joined_row(binding)


def list_wallet_identities(conn, user_id, *, include_inactive=False):
    ensure_wallet_identity_schema(conn)
    status_filter = "" if include_inactive else "AND status IN ('pending_backup', 'active')"
    direct_rows = conn.execute(
        f"""
        SELECT * FROM points_wallet_identities
        WHERE user_id=?
        {status_filter}
        ORDER BY is_primary DESC, created_at DESC, id DESC
        """,
        (int(user_id),),
    ).fetchall()
    binding_status_filter = "" if include_inactive else "AND b.status='active'"
    binding_rows = conn.execute(
        f"""
        SELECT w.*, b.id AS binding_id, b.user_id AS binding_user_id,
               b.wallet_type AS binding_wallet_type, b.is_primary AS binding_is_primary,
               b.status AS binding_status, b.label AS binding_label,
               b.metadata_json AS binding_metadata_json,
               b.created_at AS binding_created_at, b.updated_at AS binding_updated_at
        FROM points_wallet_identity_bindings b
        JOIN points_wallet_identities w ON w.id=b.wallet_identity_id
        WHERE b.user_id=?
          {binding_status_filter}
        ORDER BY b.is_primary DESC, b.created_at DESC, b.id DESC
        """,
        (int(user_id),),
    ).fetchall()
    direct_addresses = {str(row["address"] or "").strip().lower() for row in direct_rows}
    wallets = [serialize_wallet_identity(row) for row in direct_rows]
    for row in binding_rows:
        address = str(row["address"] or "").strip().lower()
        if address in direct_addresses:
            continue
        wallets.append(serialize_wallet_identity(_binding_view_from_joined_row(row)))
    wallets.sort(key=lambda item: (0 if item.get("is_primary") else 1, str(item.get("created_at") or ""), int(item.get("id") or 0)), reverse=False)
    return wallets


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
        if not row:
            row = conn.execute(
                """
                SELECT * FROM points_wallet_identities
                WHERE user_id IS NULL AND wallet_type=? AND custody_mode='system'
                ORDER BY id ASC
                LIMIT 1
                """,
                (wallet_type,),
            ).fetchone()
            if row and row["address"] != address:
                now = utc_now()
                conn.execute(
                    """
                    UPDATE points_wallet_identities
                    SET address=?, public_key_hash=?, label=?, metadata_json=?, updated_at=?
                    WHERE id=?
                    """,
                    (
                        address,
                        sha256_text(address),
                        "Mint wallet" if wallet_type == "mint" else "Burn wallet",
                        canonical_json({
                            "system_wallet": wallet_type,
                            "address_namespace": "system_special",
                            "not_official_hot_wallet": True,
                            "financial_source_of_truth": "points_economy_events",
                        }),
                        now,
                        row["id"],
                    ),
                )
                row = conn.execute("SELECT * FROM points_wallet_identities WHERE id=?", (row["id"],)).fetchone()
        if row:
            created.append(serialize_wallet_identity(row))
            continue
        now = utc_now()
        cur = conn.execute(
            """
            INSERT INTO points_wallet_identities (
                user_id, address, wallet_type, custody_mode, key_algorithm,
                public_key_jwk_json, public_key_hash, server_private_key_stored,
                is_primary, status, label, backup_confirmed_at, wallet_scope,
                spend_capability, metadata_json,
                created_at, updated_at
            ) VALUES (NULL, ?, ?, 'system', 'SYSTEM_SIMULATED_V1', '{}', ?, 0, 0, 'active', ?, ?, 'system_reserve', 'disabled', ?, ?, ?)
            """,
            (
                address,
                wallet_type,
                sha256_text(address),
                "Mint wallet" if wallet_type == "mint" else "Burn wallet",
                now,
                canonical_json({
                    "system_wallet": wallet_type,
                    "address_namespace": "system_special",
                    "not_official_hot_wallet": True,
                    "financial_source_of_truth": "points_economy_events",
                }),
                now,
                now,
            ),
        )
        row = conn.execute("SELECT * FROM points_wallet_identities WHERE id=?", (cur.lastrowid,)).fetchone()
        created.append(serialize_wallet_identity(row))
    return created


def create_official_hot_wallet(conn, *, user_id, chain_secret, label="站內託管錢包"):
    ensure_wallet_identity_schema(conn)
    existing = conn.execute(
        """
        SELECT * FROM points_wallet_identities
        WHERE user_id=? AND wallet_type='official_hot' AND status IN ('pending_backup', 'active')
        ORDER BY id ASC
        LIMIT 1
        """,
        (int(user_id),),
    ).fetchone()
    if existing:
        return serialize_wallet_identity(existing)
    primary = get_primary_wallet_identity(conn, user_id)
    now = utc_now()
    address = official_hot_wallet_address(chain_secret, user_id)
    cur = conn.execute(
        """
        INSERT INTO points_wallet_identities (
            user_id, address, wallet_type, custody_mode, key_algorithm,
            public_key_jwk_json, public_key_hash, server_private_key_stored,
            is_primary, status, label, backup_confirmed_at, wallet_scope,
            spend_capability, metadata_json,
            created_at, updated_at
        ) VALUES (?, ?, 'official_hot', 'server_hot', 'SYSTEM_SIMULATED_V1', '{}', ?, 0, ?, 'active', ?, ?, 'user', 'enabled', ?, ?, ?)
        """,
        (
            int(user_id),
            address,
            sha256_text(address),
            0 if primary else 1,
            str(label or "站內託管錢包")[:120],
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
    primary = get_primary_wallet_identity(conn, user_id)
    row = conn.execute(
        """
        SELECT * FROM points_wallet_identities
        WHERE user_id=? AND address=?
        ORDER BY CASE WHEN status IN ('pending_backup', 'active') THEN 0 ELSE 1 END, id DESC
        LIMIT 1
        """,
        (int(user_id), address),
    ).fetchone()
    now = utc_now()
    if row:
        metadata = _json_loads(row["metadata_json"], {})
        metadata.update({
            "private_key_server_received": False,
            "backup_confirmed": True,
            "restored_requires_private_key": True,
            "restored_at": now,
            "previous_status": row["status"],
            "claimed_lost_wallet": str(row["status"] or "") == "lost",
        })
        conn.execute(
            """
            UPDATE points_wallet_identities
            SET user_id=?, wallet_type=?, custody_mode='self_custody', key_algorithm='ECDSA_P256_SHA256',
                public_key_jwk_json=?, public_key_hash=?, server_private_key_stored=0,
                is_primary=?, status='active', label=?, backup_confirmed_at=?,
                imported_at=?, revoked_at=NULL, wallet_scope='user', spend_capability='enabled',
                metadata_json=?, updated_at=?
            WHERE id=?
            """,
            (
                int(user_id),
                wallet_type,
                canonical_json(jwk),
                public_key_hash(jwk),
                1 if not primary or primary["address"] == address else 0,
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
            detail={
                "address": address,
                "restore_requires_private_key": True,
                "claimed_lost_wallet": str(row["status"] or "") == "lost",
            },
        )
        return serialize_wallet_identity(conn.execute("SELECT * FROM points_wallet_identities WHERE id=?", (row["id"],)).fetchone())
    canonical_row = conn.execute(
        """
        SELECT * FROM points_wallet_identities
        WHERE address=?
        ORDER BY CASE WHEN status IN ('pending_backup', 'active') THEN 0 ELSE 1 END, id ASC
        LIMIT 1
        """,
        (address,),
    ).fetchone()
    if canonical_row:
        existing_binding = conn.execute(
            """
            SELECT * FROM points_wallet_identity_bindings
            WHERE user_id=? AND address=?
            LIMIT 1
            """,
            (int(user_id), address),
        ).fetchone()
        metadata = {
            "private_key_server_received": False,
            "backup_confirmed": True,
            "shared_private_key_control": True,
            "address_control_model": "self_custody_private_key_controls_address_v1",
            "bound_without_disclosing_other_account": True,
        }
        if existing_binding:
            conn.execute(
                """
                UPDATE points_wallet_identity_bindings
                SET wallet_type=?, is_primary=?, status='active', label=?, metadata_json=?, updated_at=?
                WHERE id=?
                """,
                (
                    wallet_type,
                    1 if (not primary or primary["address"] == address) else 0,
                    str(label or ("冷錢包" if wallet_type == "self_custody_cold" else "匯入冷錢包"))[:120],
                    canonical_json({**_json_loads(existing_binding["metadata_json"], {}), **metadata, "restored_at": now}),
                    now,
                    existing_binding["id"],
                ),
            )
            binding = conn.execute("SELECT * FROM points_wallet_identity_bindings WHERE id=?", (existing_binding["id"],)).fetchone()
            event_type = f"{wallet_type}_binding_restored"
        else:
            cur = conn.execute(
                """
                INSERT INTO points_wallet_identity_bindings (
                    user_id, wallet_identity_id, address, wallet_type, is_primary,
                    status, label, metadata_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, 'active', ?, ?, ?, ?)
                """,
                (
                    int(user_id),
                    int(canonical_row["id"]),
                    address,
                    wallet_type,
                    0 if primary else 1,
                    str(label or ("冷錢包" if wallet_type == "self_custody_cold" else "匯入冷錢包"))[:120],
                    canonical_json(metadata),
                    now,
                    now,
                ),
            )
            binding = conn.execute("SELECT * FROM points_wallet_identity_bindings WHERE id=?", (cur.lastrowid,)).fetchone()
            event_type = f"{wallet_type}_binding_created"
        _record_onboarding_event(
            conn,
            user_id=user_id,
            wallet_identity_id=canonical_row["id"],
            event_type=event_type,
            detail={
                "address": address,
                "private_key_proof": True,
                "address_control_model": "self_custody_private_key_controls_address_v1",
            },
        )
        return serialize_wallet_identity(_wallet_identity_binding_view(canonical_row, binding))
    cur = conn.execute(
        """
        INSERT INTO points_wallet_identities (
            user_id, address, wallet_type, custody_mode, key_algorithm,
            public_key_jwk_json, public_key_hash, server_private_key_stored,
            is_primary, status, label, backup_confirmed_at, imported_at,
            wallet_scope, spend_capability, metadata_json, created_at, updated_at
        ) VALUES (?, ?, ?, 'self_custody', 'ECDSA_P256_SHA256', ?, ?, 0, ?, 'active', ?, ?, ?, 'user', 'enabled', ?, ?, ?)
        """,
        (
            int(user_id),
            address,
            wallet_type,
            canonical_json(jwk),
            public_key_hash(jwk),
            0 if primary else 1,
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


def delete_cold_wallet(conn, *, user_id, address="", reason=""):
    ensure_wallet_identity_schema(conn)
    address = str(address or "").strip().lower()
    binding = None
    if address:
        primary = conn.execute(
            """
            SELECT * FROM points_wallet_identities
            WHERE user_id=? AND address=? AND status IN ('pending_backup', 'active')
            LIMIT 1
            """,
            (int(user_id), normalize_wallet_address(address)),
        ).fetchone()
        if not primary:
            binding = _bound_wallet_identity_for_user_address(conn, user_id, normalize_wallet_address(address), active_only=True)
            primary = _binding_view_from_joined_row(binding)
    else:
        primary = get_primary_wallet_identity(conn, user_id)
        if primary and _json_loads(primary["metadata_json"], {}).get("binding_record"):
            binding = _bound_wallet_identity_for_user_address(conn, user_id, primary["address"], active_only=True)
    if not primary:
        raise ValueError("no active wallet is bound")
    if primary["wallet_type"] not in {"self_custody_cold", "imported_cold"} or primary["custody_mode"] != "self_custody":
        raise ValueError("only self-custody cold wallets can be deleted; official hot wallets cannot be deleted")
    now = utc_now()
    if binding:
        metadata = _json_loads(binding["binding_metadata_json"], {})
        metadata.update({
            "deleted_at": now,
            "delete_reason": str(reason or "")[:240],
            "restore_requires_private_key": True,
            "financial_source_of_truth": "points_ledger",
            "address_control_model": "self_custody_private_key_controls_address_v1",
        })
        conn.execute(
            """
            UPDATE points_wallet_identity_bindings
            SET is_primary=0, status='lost', metadata_json=?, updated_at=?
            WHERE id=?
            """,
            (canonical_json(metadata), now, binding["binding_id"]),
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
                "binding_record": True,
            },
        )
        refreshed = _bound_wallet_identity_for_user_address(conn, user_id, primary["address"], active_only=False)
        return serialize_wallet_identity(_binding_view_from_joined_row(refreshed))
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
    if int(primary["is_primary"] or 0):
        replacement = conn.execute(
            """
            SELECT id FROM points_wallet_identities
            WHERE user_id=? AND status IN ('pending_backup', 'active')
            ORDER BY CASE WHEN wallet_type='official_hot' THEN 1 ELSE 0 END, created_at DESC, id DESC
            LIMIT 1
            """,
            (int(user_id),),
        ).fetchone()
        if replacement:
            conn.execute(
                """
                UPDATE points_wallet_identities
                SET is_primary=1, updated_at=?
                WHERE id=?
                """,
                (now, replacement["id"]),
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


def delete_primary_cold_wallet(conn, *, user_id, reason=""):
    return delete_cold_wallet(conn, user_id=user_id, reason=reason)


def create_multisig_wallet(conn, *, user_id, threshold, signer_addresses, label="多簽錢包"):
    ensure_wallet_identity_schema(conn)
    primary = get_primary_wallet_identity(conn, user_id)
    policy = normalize_multisig_policy(threshold=threshold, signer_addresses=signer_addresses)
    address = multisig_wallet_address(threshold=policy["threshold"], signer_addresses=policy["signer_addresses"])
    row = conn.execute("SELECT * FROM points_wallet_identities WHERE address=?", (address,)).fetchone()
    if row and int(row["user_id"] or 0) != int(user_id):
        raise ValueError("multisig wallet address is already bound to another user")
    if row and str(row["status"] or "") in {"pending_backup", "active"}:
        return serialize_wallet_identity(row)
    now = utc_now()
    cur = conn.execute(
        """
        INSERT INTO points_wallet_identities (
            user_id, address, wallet_type, custody_mode, key_algorithm,
            public_key_jwk_json, public_key_hash, server_private_key_stored,
            is_primary, status, label, backup_confirmed_at, wallet_scope,
            spend_capability, metadata_json,
            created_at, updated_at
        ) VALUES (?, ?, 'multisig', 'multisig', 'MULTISIG_POLICY_V1', '{}', ?, 0, ?, 'active', ?, ?, 'user', 'receive_only', ?, ?, ?)
        """,
        (
            int(user_id),
            address,
            multisig_policy_hash(threshold=policy["threshold"], signer_addresses=policy["signer_addresses"]),
            0 if primary else 1,
            str(label or "多簽錢包")[:120],
            now,
            canonical_json({
                "multisig_policy": policy,
                "private_key_server_received": False,
                "rc1_capability": "user_multisig_preview_receive_only",
            }),
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
    wallets = list_wallet_identities(conn, user_id)
    warnings = []
    try:
        balance_state = points_service._wallet_identity_balances_for_user(conn, user_id) if points_service else {}
        balances = balance_state.get("balances") or {}
        for wallet in wallets:
            balance = balances.get(wallet.get("address") or "", {})
            wallet["points_balance"] = int(balance.get("balance") or 0)
            wallet["points_frozen"] = int(balance.get("frozen") or 0)
            wallet["pending_outgoing_points"] = int(balance.get("pending_outgoing") or 0)
            address = str(wallet.get("address") or "").strip().lower()
            if address and hasattr(points_service, "_address_risk_label_locked"):
                wallet["risk_label"] = points_service._address_risk_label_locked(conn, address)
            if address and hasattr(points_service, "_address_freeze_locked"):
                freeze = points_service._address_freeze_locked(conn, address)
                provisional = points_service._address_provisional_freeze_locked(conn, address) if hasattr(points_service, "_address_provisional_freeze_locked") else None
                wallet["governance_freeze"] = freeze or provisional
                wallet["provisional_freeze"] = provisional
    except Exception as exc:
        warnings.append({"code": "wallet_balance_read_failed", "message": str(exc)[:240]})
    try:
        initial_grant = points_service.wallet_initial_grant_status(conn, user_id) if points_service else {}
    except Exception as exc:
        warnings.append({"code": "initial_grant_status_failed", "message": str(exc)[:240]})
        initial_grant = {}
    try:
        wallet_creation_fee = points_service.wallet_creation_fee_quote(conn, user_id) if points_service else {}
    except Exception as exc:
        warnings.append({"code": "wallet_creation_fee_quote_failed", "message": str(exc)[:240]})
        wallet_creation_fee = {}
    try:
        deposit_addresses = points_service._active_deposit_addresses_for_user(conn, user_id) if points_service else []
    except Exception as exc:
        warnings.append({"code": "deposit_address_status_failed", "message": str(exc)[:240]})
        deposit_addresses = []
    initial_grant_required = bool(initial_grant.get("required")) if isinstance(initial_grant, dict) else False
    wallet_required = not bool(primary_payload)
    return {
        "required": wallet_required or initial_grant_required,
        "wallet_required": wallet_required,
        "signup_bonus_required": not bonus_granted,
        "signup_bonus_granted": bonus_granted,
        "initial_grant_required": initial_grant_required,
        "initial_grant": initial_grant,
        "wallet": primary_payload,
        "wallets": wallets,
        "wallet_creation_fee": wallet_creation_fee,
        "deposit_addresses": deposit_addresses,
        "deposit_address": deposit_addresses[0]["address"] if deposit_addresses else "",
        "warnings": warnings,
        "system_wallets": system_wallets,
        "allowed_modes": ["official_hot", "self_custody_cold", "imported_cold"],
        "hidden_preview_modes": ["user_multisig_preview"],
        "multisig_policy": {
            "rc1_user_multisig": "receive_only",
            "rc1_official_multisig": "official_treasury_only",
        },
        "private_key_policy": {
            "server_accepts_private_key": False,
            "client_key_algorithm": "ECDSA_P256_SHA256",
            "address_prefix": "pc1",
            "official_hot_wallet_prefix": "pc0",
            "pc0_custody_model": "official_custodial_internal_ledger",
        },
    }


def system_account_wallet_onboarding_status(payload):
    """Hide member wallet onboarding fields for system/root accounts."""
    data = dict(payload or {})
    data.update({
        "required": False,
        "wallet_required": False,
        "signup_bonus_required": False,
        "signup_bonus_granted": False,
        "initial_grant_required": False,
        "initial_grant": {
            "required": False,
            "granted": False,
            "amount": 0,
            "grant": "",
            "ledger_uuid": "",
            "ledger_hash": "",
            "active_wallet_address": "",
            "deferred_until_wallet": False,
        },
        "wallet": None,
        "wallets": [],
        "wallet_creation_fee": {
            "amount_points": 0,
            "chargeable_wallet_types": [],
            "item_key": "system_account_no_member_wallet",
            "reference_type": "system_account",
        },
        "deposit_address": "",
        "deposit_addresses": [],
        "allowed_modes": [],
        "system_account": True,
        "system_account_note": "root manages official/system wallets; it does not use a member official hot wallet.",
    })
    return data


def award_signup_bonus_after_wallet_onboarding(*, points_service, user_id, actor=None):
    conn = points_service.get_db()
    try:
        points_service.ensure_schema(conn)
        create_official_hot_wallet(conn, user_id=int(user_id), chain_secret=getattr(points_service, "chain_secret", ""))
        try:
            points_service.ensure_user_deposit_address(conn, int(user_id))
        except Exception:
            pass
        if signup_bonus_granted(conn, user_id):
            return {"created": False, "already_granted": True, "ledger": None}
        conn.commit()
    finally:
        conn.close()
    return points_service.award_signup_bonus(user_id=user_id, actor=actor)
