"""Shadow trading wallet and ledger helpers.

These helpers keep the internal-test shadow wallet / shadow ledger plumbing
used by ``TradingEngineService`` when Server Mode routes trading writes away
from production tables.
"""

import uuid

from services.points_chain import (
    DISPLAY_CURRENCY,
    actor_value,
    compute_ledger_hash,
    metadata_hash,
    normalize_currency_type,
    public_account_id,
    utc_now,
    _metadata_json_checked,
)


def shadow_actor_user_id(ctx, user_id):
    try:
        tester_id = int(getattr(ctx, "tester_id", None) or 0)
    except Exception:
        tester_id = 0
    return tester_id if tester_id > 0 else int(user_id)


def ensure_shadow_wallet(service, conn, user_id, ctx):
    now = utc_now()
    actor_user_id = service._shadow_actor_user_id(ctx, user_id)
    conn.execute(
        """
        INSERT OR IGNORE INTO test_shadow_wallets (
            tester_user_id, user_id, balance_points, frozen_points,
            total_points_earned, total_points_spent, wallet_status, risk_level,
            created_at, updated_at
        ) VALUES (?, ?, 0, 0, 0, 0, 'active', 'normal', ?, ?)
        """,
        (actor_user_id, int(user_id), now, now),
    )
    row = conn.execute("SELECT * FROM test_shadow_wallets WHERE user_id=?", (int(user_id),)).fetchone()
    if row is None:
        raise ValueError("shadow wallet not found")
    return row


def shadow_wallet_payload(service, row):
    if not row:
        return None
    points_balance = int(row["balance_points"] or 0)
    points_frozen = int(row["frozen_points"] or 0)
    total_points_earned = int(row["total_points_earned"] or 0)
    total_points_spent = int(row["total_points_spent"] or 0)
    return {
        "user_id": int(row["user_id"]),
        "public_account_id": public_account_id(service.points_service.chain_secret, int(row["user_id"])),
        "currency_type": DISPLAY_CURRENCY,
        "points_balance": points_balance,
        "points_frozen": points_frozen,
        "total_points_earned": total_points_earned,
        "total_points_spent": total_points_spent,
        "soft_balance": points_balance,
        "hard_balance": 0,
        "soft_frozen": points_frozen,
        "hard_frozen": 0,
        "wallet_status": row["wallet_status"],
        "risk_level": row["risk_level"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def wallet_row(service, conn, user_id, ctx=None):
    wallet_table, route_ctx = service._resolve_table("wallets", ctx, action="wallet-read")
    if wallet_table == "wallets":
        return service.points_service.ensure_wallet(conn, user_id)
    return service._ensure_shadow_wallet(conn, user_id, route_ctx)


def wallet_payload(service, conn, user_id, ctx=None):
    wallet_table, route_ctx = service._resolve_table("wallets", ctx, action="wallet-read")
    if wallet_table == "wallets":
        return service.points_service.serialize_wallet(service.points_service.ensure_wallet(conn, user_id))
    return service._shadow_wallet_payload(service._ensure_shadow_wallet(conn, user_id, route_ctx))


def shadow_existing_ledger_row(_service, conn, idempotency_key):
    if not idempotency_key:
        return None
    return conn.execute("SELECT * FROM test_shadow_ledger WHERE idempotency_key=?", (str(idempotency_key),)).fetchone()


def shadow_last_ledger_hash(_service, conn):
    row = conn.execute("SELECT ledger_hash FROM test_shadow_ledger ORDER BY id DESC LIMIT 1").fetchone()
    return str(row["ledger_hash"] or "") if row else None


def shadow_record_transaction(
    service,
    conn,
    *,
    ctx,
    user_id,
    currency_type,
    direction,
    amount,
    action_type,
    reference_type=None,
    reference_id=None,
    idempotency_key=None,
    reason="",
    public_metadata=None,
    private_metadata=None,
    sensitive_metadata_encrypted="",
    actor=None,
    risk_flag="none",
    risk_score=0,
):
    if direction not in {"credit", "debit", "freeze", "unfreeze", "reverse", "transfer_in", "transfer_out"}:
        raise ValueError("unsupported ledger direction")
    amount = int(amount or 0)
    if amount <= 0:
        raise ValueError("amount must be positive")
    existing = service._shadow_existing_ledger_row(conn, idempotency_key)
    if existing:
        return existing

    wallet = service._ensure_shadow_wallet(conn, user_id, ctx)
    if str(wallet["wallet_status"] or "active") == "closed":
        raise ValueError("wallet is closed")
    currency = normalize_currency_type(currency_type)
    balance_col = "balance_points"
    frozen_col = "frozen_points"
    earned_col = "total_points_earned"
    spent_col = "total_points_spent"
    balance_before = int(wallet[balance_col] or 0)
    frozen_before = int(wallet[frozen_col] or 0)
    balance_after = balance_before
    frozen_after = frozen_before
    earned_delta = 0
    spent_delta = 0
    if direction in {"credit", "transfer_in"}:
        balance_after += amount
        earned_delta = amount
    elif direction in {"debit", "transfer_out", "reverse"}:
        if balance_before < amount:
            raise ValueError("insufficient balance")
        balance_after -= amount
        spent_delta = amount
    elif direction == "freeze":
        if balance_before < amount:
            raise ValueError("insufficient balance")
        balance_after -= amount
        frozen_after += amount
    elif direction == "unfreeze":
        if frozen_before < amount:
            raise ValueError("insufficient frozen balance")
        balance_after += amount
        frozen_after -= amount

    public_json = _metadata_json_checked(public_metadata or {}, label="public_metadata")
    private_json = _metadata_json_checked(private_metadata or {}, label="private_metadata")
    meta_hash = metadata_hash(public_metadata or {}, private_metadata or {}, sensitive_metadata_encrypted or "")
    now = utc_now()
    ledger_uuid = str(uuid.uuid4())
    previous_ledger_hash = service._shadow_last_ledger_hash(conn)
    ledger_data = {
        "ledger_uuid": ledger_uuid,
        "public_account_id": public_account_id(service.points_service.chain_secret, int(user_id)),
        "currency_type": currency,
        "direction": direction,
        "amount": amount,
        "balance_before": balance_before,
        "balance_after": balance_after,
        "action_type": action_type,
        "reference_type": reference_type,
        "reference_id": str(reference_id) if reference_id is not None else None,
        "metadata_hash": meta_hash,
        "previous_ledger_hash": previous_ledger_hash,
        "created_at": now,
    }
    ledger_hash = compute_ledger_hash(ledger_data)
    actor_user_id = service._shadow_actor_user_id(ctx, user_id)
    cur = conn.execute(
        """
        INSERT INTO test_shadow_ledger (
            ledger_uuid, tester_user_id, user_id, public_account_id, currency_type, direction,
            amount, balance_before, balance_after, action_type, reference_type, reference_id,
            idempotency_key, reason, public_metadata_json, private_metadata_json,
            sensitive_metadata_encrypted, metadata_hash, previous_ledger_hash, ledger_hash,
            risk_flag, risk_score, created_by, created_by_role, status, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'confirmed', ?)
        """,
        (
            ledger_uuid,
            actor_user_id,
            int(user_id),
            ledger_data["public_account_id"],
            currency,
            direction,
            amount,
            balance_before,
            balance_after,
            action_type,
            reference_type,
            ledger_data["reference_id"],
            idempotency_key,
            reason or "",
            public_json,
            private_json,
            sensitive_metadata_encrypted or "",
            meta_hash,
            previous_ledger_hash,
            ledger_hash,
            risk_flag,
            int(risk_score or 0),
            int(actor_value(actor, "id")) if actor_value(actor, "id") else None,
            actor_value(actor, "role"),
            now,
        ),
    )
    conn.execute(
        """
        UPDATE test_shadow_wallets
        SET balance_points=?, frozen_points=?, total_points_earned=total_points_earned+?, total_points_spent=total_points_spent+?,
            balance_points=?, updated_at=?
        WHERE user_id=?
        """,
        (balance_after, frozen_after, earned_delta, spent_delta, balance_after, now, int(user_id)),
    )
    return conn.execute("SELECT * FROM test_shadow_ledger WHERE id=?", (cur.lastrowid,)).fetchone()
