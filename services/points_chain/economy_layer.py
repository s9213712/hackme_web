"""Replayable private economy layer for PointsChain Phase 1A.

This module is intentionally separate from product reward / trading flows. It
creates the fund-wallet and policy foundation, then derives balances from an
append-only economy event ledger.
"""

from __future__ import annotations

import json
import uuid

from .schema import canonical_json, sha256_text, utc_now
from .wallet_identity import address_from_hash, system_wallet_address


ECONOMY_POLICY_VERSION = "phase1_sim_economy_v1"
ECONOMY_FUND_KEYS = {"mint", "burn", "official_treasury", "promo_fund", "exchange_fund"}
ECONOMY_EVENT_STATUSES = {"confirmed"}
ECONOMY_INCIDENT_STATUSES = {"open", "resolved", "acknowledged"}
ECONOMY_INCIDENT_SEVERITIES = {"info", "warning", "critical"}

DEFAULT_ECONOMY_POLICY = {
    "policy_version": ECONOMY_POLICY_VERSION,
    "max_supply": 100_000_000,
    "reserved_locked": 40_000_000,
    "initial_mint": 20_000_000,
    "official_treasury_initial": 10_000_000,
    "promo_fund_initial": 5_000_000,
    "exchange_fund_initial": 5_000_000,
    "promo_daily_cap": 50_000,
    "promo_user_daily_cap": 1_000,
    "promo_action_daily_cap": 20_000,
    "promo_low_watermark": 500_000,
    "promo_critical_watermark": 100_000,
    "exchange_low_watermark": 1_000_000,
    "exchange_critical_watermark": 250_000,
    "mint_replenish_max_once": 1_000_000,
    "mint_replenish_min_remaining": 50_000_000,
    "dev_official_transfer_single_root_signature": True,
    "phase": "1A",
}

DEFAULT_FUND_LABELS = {
    "mint": "MINT 發行錢包",
    "burn": "BURN 銷毀錢包",
    "official_treasury": "官方 Treasury 錢包",
    "promo_fund": "PROMO 獎勵基金",
    "exchange_fund": "EXCHANGE 交易所基金",
}


def _sql_in(values):
    return ", ".join(f"'{value}'" for value in sorted(values))


def _json_loads(raw, fallback=None):
    if not raw:
        return fallback if fallback is not None else {}
    try:
        value = json.loads(raw)
        return value if isinstance(value, (dict, list)) else (fallback if fallback is not None else {})
    except Exception:
        return fallback if fallback is not None else {}


def _json_dumps(value):
    return canonical_json(value if value is not None else {})


def economy_fund_address(chain_secret, fund_key):
    fund_key = str(fund_key or "").strip().lower()
    if fund_key in {"mint", "burn"}:
        return system_wallet_address(chain_secret, fund_key)
    if fund_key not in ECONOMY_FUND_KEYS:
        raise ValueError("unsupported economy fund key")
    return address_from_hash(f"economy_fund:{fund_key}:{chain_secret or ''}")


def economy_event_hash_payload(row):
    return {
        "event_uuid": row["event_uuid"],
        "event_type": row["event_type"],
        "transaction_type": row["transaction_type"],
        "source_fund_key": row["source_fund_key"],
        "source_address": row["source_address"],
        "destination_fund_key": row["destination_fund_key"],
        "destination_address": row["destination_address"],
        "amount": int(row["amount"]),
        "idempotency_key": row["idempotency_key"],
        "request_hash": row["request_hash"],
        "policy_version": row["policy_version"],
        "metadata_json": row["metadata_json"],
        "previous_event_hash": row["previous_event_hash"],
        "created_at": row["created_at"],
    }


def compute_economy_event_hash(row):
    return sha256_text(canonical_json(economy_event_hash_payload(row)))


def ensure_economy_layer_schema(conn):
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS points_economy_policy (
            id INTEGER PRIMARY KEY CHECK (id=1),
            policy_version TEXT NOT NULL,
            max_supply INTEGER NOT NULL CHECK (max_supply > 0),
            reserved_locked INTEGER NOT NULL DEFAULT 0 CHECK (reserved_locked >= 0),
            initial_mint INTEGER NOT NULL DEFAULT 0 CHECK (initial_mint >= 0),
            policy_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        f"""
        CREATE TABLE IF NOT EXISTS points_economy_fund_wallets (
            fund_key TEXT PRIMARY KEY CHECK (fund_key IN ({_sql_in(ECONOMY_FUND_KEYS)})),
            address TEXT NOT NULL UNIQUE,
            label TEXT NOT NULL,
            custody_mode TEXT NOT NULL DEFAULT 'system',
            derived_cache INTEGER NOT NULL DEFAULT 0 CHECK (derived_cache IN (0, 1)),
            metadata_json TEXT NOT NULL DEFAULT '{{}}',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        f"""
        CREATE TABLE IF NOT EXISTS points_economy_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_uuid TEXT NOT NULL UNIQUE,
            event_type TEXT NOT NULL,
            transaction_type TEXT NOT NULL,
            source_fund_key TEXT CHECK (source_fund_key IS NULL OR source_fund_key IN ({_sql_in(ECONOMY_FUND_KEYS)})),
            source_address TEXT,
            destination_fund_key TEXT CHECK (destination_fund_key IS NULL OR destination_fund_key IN ({_sql_in(ECONOMY_FUND_KEYS)})),
            destination_address TEXT,
            amount INTEGER NOT NULL CHECK (amount > 0),
            idempotency_key TEXT NOT NULL UNIQUE,
            request_hash TEXT NOT NULL,
            policy_version TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'confirmed' CHECK (status IN ({_sql_in(ECONOMY_EVENT_STATUSES)})),
            metadata_json TEXT NOT NULL DEFAULT '{{}}',
            previous_event_hash TEXT,
            event_hash TEXT NOT NULL UNIQUE,
            created_by INTEGER,
            created_by_role TEXT,
            created_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS points_economy_derived_balances (
            fund_key TEXT PRIMARY KEY,
            address TEXT NOT NULL,
            balance INTEGER NOT NULL CHECK (balance >= 0),
            derived_cache INTEGER NOT NULL DEFAULT 1 CHECK (derived_cache=1),
            replay_height INTEGER NOT NULL DEFAULT 0,
            replay_event_hash TEXT,
            updated_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        f"""
        CREATE TABLE IF NOT EXISTS points_economy_incidents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            incident_uuid TEXT NOT NULL UNIQUE,
            severity TEXT NOT NULL CHECK (severity IN ({_sql_in(ECONOMY_INCIDENT_SEVERITIES)})),
            category TEXT NOT NULL,
            trigger TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ({_sql_in(ECONOMY_INCIDENT_STATUSES)})),
            automatic_actions_json TEXT NOT NULL DEFAULT '[]',
            metadata_json TEXT NOT NULL DEFAULT '{{}}',
            created_at TEXT NOT NULL,
            resolved_at TEXT
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS points_economy_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            snapshot_uuid TEXT NOT NULL UNIQUE,
            snapshot_height INTEGER NOT NULL,
            event_hash TEXT,
            wallet_root_hash TEXT NOT NULL,
            minted_total INTEGER NOT NULL,
            burned_total INTEGER NOT NULL,
            active_supply INTEGER NOT NULL,
            circulating_supply INTEGER NOT NULL,
            metadata_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_points_economy_snapshots_replay
        ON points_economy_snapshots (snapshot_height, event_hash, wallet_root_hash)
        """
    )
    conn.execute(
        """
        CREATE TRIGGER IF NOT EXISTS trg_points_economy_events_no_update
        BEFORE UPDATE ON points_economy_events
        BEGIN
            SELECT RAISE(ABORT, 'points economy events are append-only');
        END
        """
    )
    conn.execute(
        """
        CREATE TRIGGER IF NOT EXISTS trg_points_economy_events_no_delete
        BEFORE DELETE ON points_economy_events
        BEGIN
            SELECT RAISE(ABORT, 'points economy events are append-only');
        END
        """
    )
    conn.execute(
        """
        CREATE TRIGGER IF NOT EXISTS trg_points_economy_incidents_core_immutable
        BEFORE UPDATE OF incident_uuid, severity, category, trigger, automatic_actions_json,
                         metadata_json, created_at
        ON points_economy_incidents
        BEGIN
            SELECT RAISE(ABORT, 'points economy incident core fields are append-only');
        END
        """
    )
    conn.execute(
        """
        CREATE TRIGGER IF NOT EXISTS trg_points_economy_incidents_no_update
        BEFORE UPDATE ON points_economy_incidents
        BEGIN
            SELECT RAISE(ABORT, 'points economy incidents are append-only');
        END
        """
    )
    conn.execute(
        """
        CREATE TRIGGER IF NOT EXISTS trg_points_economy_incidents_no_delete
        BEFORE DELETE ON points_economy_incidents
        BEGIN
            SELECT RAISE(ABORT, 'points economy incidents are append-only');
        END
        """
    )


def load_economy_policy(conn):
    ensure_economy_layer_schema(conn)
    row = conn.execute("SELECT * FROM points_economy_policy WHERE id=1").fetchone()
    if row:
        payload = _json_loads(row["policy_json"], {})
        payload.update({
            "policy_version": row["policy_version"],
            "max_supply": int(row["max_supply"]),
            "reserved_locked": int(row["reserved_locked"]),
            "initial_mint": int(row["initial_mint"]),
        })
        payload["releasable_supply"] = int(payload["max_supply"]) - int(payload["reserved_locked"])
        return payload
    now = utc_now()
    policy = dict(DEFAULT_ECONOMY_POLICY)
    conn.execute(
        """
        INSERT INTO points_economy_policy (
            id, policy_version, max_supply, reserved_locked, initial_mint,
            policy_json, created_at, updated_at
        ) VALUES (1, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            policy["policy_version"],
            int(policy["max_supply"]),
            int(policy["reserved_locked"]),
            int(policy["initial_mint"]),
            _json_dumps(policy),
            now,
            now,
        ),
    )
    policy["releasable_supply"] = int(policy["max_supply"]) - int(policy["reserved_locked"])
    return policy


def ensure_economy_fund_wallets(conn, *, chain_secret):
    ensure_economy_layer_schema(conn)
    now = utc_now()
    wallets = {}
    for fund_key in ("mint", "burn", "official_treasury", "promo_fund", "exchange_fund"):
        address = economy_fund_address(chain_secret, fund_key)
        row = conn.execute("SELECT * FROM points_economy_fund_wallets WHERE fund_key=?", (fund_key,)).fetchone()
        if not row:
            conn.execute(
                """
                INSERT INTO points_economy_fund_wallets (
                    fund_key, address, label, custody_mode, derived_cache,
                    metadata_json, created_at, updated_at
                ) VALUES (?, ?, ?, 'system', 0, ?, ?, ?)
                """,
                (
                    fund_key,
                    address,
                    DEFAULT_FUND_LABELS[fund_key],
                    _json_dumps({"phase": "1A", "financial_source_of_truth": "points_economy_events"}),
                    now,
                    now,
                ),
            )
            row = conn.execute("SELECT * FROM points_economy_fund_wallets WHERE fund_key=?", (fund_key,)).fetchone()
        wallets[fund_key] = dict(row)
    return wallets


def _last_economy_event_hash(conn):
    row = conn.execute("SELECT event_hash FROM points_economy_events ORDER BY id DESC LIMIT 1").fetchone()
    return row["event_hash"] if row else None


def _event_request_hash(payload):
    return sha256_text(canonical_json(payload))


def append_economy_event(
    conn,
    *,
    chain_secret,
    event_type,
    transaction_type,
    source_fund_key,
    destination_fund_key,
    source_address=None,
    destination_address=None,
    amount,
    idempotency_key,
    metadata=None,
    actor=None,
    allow_mint_override=False,
):
    policy = load_economy_policy(conn)
    wallets = ensure_economy_fund_wallets(conn, chain_secret=chain_secret)
    source_fund_key = str(source_fund_key or "").strip().lower() or None
    destination_fund_key = str(destination_fund_key or "").strip().lower() or None
    if source_fund_key is not None and source_fund_key not in ECONOMY_FUND_KEYS:
        raise ValueError("source fund is unsupported")
    if destination_fund_key is not None and destination_fund_key not in ECONOMY_FUND_KEYS:
        raise ValueError("destination fund is unsupported")
    source_address = str(source_address or "").strip()
    destination_address = str(destination_address or "").strip()
    if source_fund_key is None and not source_address:
        raise ValueError("source address is required when source fund is omitted")
    if destination_fund_key is None and not destination_address:
        raise ValueError("destination address is required when destination fund is omitted")
    amount = int(amount)
    if amount <= 0:
        raise ValueError("economy event amount must be positive")
    request_payload = {
        "event_type": str(event_type),
        "transaction_type": str(transaction_type),
        "source_fund_key": source_fund_key,
        "destination_fund_key": destination_fund_key,
        "amount": amount,
        "metadata": metadata or {},
        "policy_version": policy["policy_version"],
    }
    request_hash = _event_request_hash(request_payload)
    existing = conn.execute("SELECT * FROM points_economy_events WHERE idempotency_key=?", (str(idempotency_key),)).fetchone()
    if existing:
        if existing["request_hash"] != request_hash:
            raise ValueError("economy idempotency key conflict")
        return existing, False

    replay = replay_economy_events(conn, policy=policy, chain_secret=chain_secret, persist_cache=False)
    if source_fund_key == "mint" and not allow_mint_override:
        releasable = int(policy["max_supply"]) - int(policy["reserved_locked"])
        if int(replay["minted_total"]) + amount > releasable:
            raise ValueError("mint would exceed releasable supply")
    elif source_fund_key is not None and source_fund_key != "mint":
        source_balance = int((replay.get("balances") or {}).get(source_fund_key, {}).get("balance") or 0)
        if source_balance < amount:
            raise ValueError("source fund balance is insufficient")

    now = utc_now()
    event_uuid = str(uuid.uuid4())
    previous_hash = _last_economy_event_hash(conn)
    source_address = wallets[source_fund_key]["address"] if source_fund_key else source_address
    destination_address = wallets[destination_fund_key]["address"] if destination_fund_key else destination_address
    row_payload = {
        "event_uuid": event_uuid,
        "event_type": str(event_type),
        "transaction_type": str(transaction_type),
        "source_fund_key": source_fund_key,
        "source_address": source_address,
        "destination_fund_key": destination_fund_key,
        "destination_address": destination_address,
        "amount": amount,
        "idempotency_key": str(idempotency_key),
        "request_hash": request_hash,
        "policy_version": policy["policy_version"],
        "metadata_json": _json_dumps(metadata or {}),
        "previous_event_hash": previous_hash,
        "created_at": now,
    }
    event_hash = compute_economy_event_hash(row_payload)
    cur = conn.execute(
        """
        INSERT INTO points_economy_events (
            event_uuid, event_type, transaction_type, source_fund_key, source_address,
            destination_fund_key, destination_address, amount, idempotency_key,
            request_hash, policy_version, status, metadata_json, previous_event_hash,
            event_hash, created_by, created_by_role, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'confirmed', ?, ?, ?, ?, ?, ?)
        """,
        (
            event_uuid,
            row_payload["event_type"],
            row_payload["transaction_type"],
            source_fund_key,
            source_address,
            destination_fund_key,
            destination_address,
            amount,
            str(idempotency_key),
            request_hash,
            policy["policy_version"],
            row_payload["metadata_json"],
            previous_hash,
            event_hash,
            _actor_value(actor, "id"),
            _actor_value(actor, "role"),
            now,
        ),
    )
    return conn.execute("SELECT * FROM points_economy_events WHERE id=?", (cur.lastrowid,)).fetchone(), True


def _actor_value(actor, key):
    if not actor:
        return None
    if hasattr(actor, "keys"):
        return actor[key] if key in actor.keys() else None
    return actor.get(key) if hasattr(actor, "get") else None


def bootstrap_economy_layer(conn, *, chain_secret, actor=None):
    policy = load_economy_policy(conn)
    ensure_economy_fund_wallets(conn, chain_secret=chain_secret)
    allocations = (
        ("official_treasury", "treasury_allocation", int(policy["official_treasury_initial"])),
        ("promo_fund", "promo_allocation", int(policy["promo_fund_initial"])),
        ("exchange_fund", "exchange_allocation", int(policy["exchange_fund_initial"])),
    )
    created = []
    for fund_key, transaction_type, amount in allocations:
        row, was_created = append_economy_event(
            conn,
            chain_secret=chain_secret,
            event_type="mint",
            transaction_type=transaction_type,
            source_fund_key="mint",
            destination_fund_key=fund_key,
            amount=amount,
            idempotency_key=f"economy_bootstrap:{policy['policy_version']}:{fund_key}:{amount}",
            metadata={"bootstrap": True, "phase": "1A"},
            actor=actor,
        )
        if was_created:
            created.append(row["event_uuid"])
    return {"created_event_uuids": created, "created_count": len(created), "policy": policy}


def replay_economy_events(conn, *, policy=None, chain_secret, persist_cache=False):
    policy = policy or load_economy_policy(conn)
    wallets = ensure_economy_fund_wallets(conn, chain_secret=chain_secret)
    balances = {
        fund_key: {
            "fund_key": fund_key,
            "address": row["address"],
            "label": row["label"],
            "balance": 0,
            "custody_mode": row["custody_mode"],
            "wallet_status": "active",
            "derived_cache": True,
            "updated_at": row["updated_at"],
        }
        for fund_key, row in wallets.items()
    }
    rows = conn.execute("SELECT * FROM points_economy_events WHERE status='confirmed' ORDER BY id ASC").fetchall()
    minted_total = 0
    burned_total = 0
    for row in rows:
        amount = int(row["amount"])
        source = row["source_fund_key"]
        dest = row["destination_fund_key"]
        if source == "mint":
            minted_total += amount
        elif source:
            balances[source]["balance"] -= amount
            if balances[source]["balance"] < 0:
                raise ValueError(f"economy replay would create negative balance for {source}")
        if dest == "burn":
            burned_total += amount
            balances["burn"]["balance"] += amount
        elif dest:
            balances[dest]["balance"] += amount

    releasable_supply = int(policy["max_supply"]) - int(policy["reserved_locked"])
    if minted_total > releasable_supply:
        raise ValueError("economy replay exceeds releasable supply")
    active_supply = minted_total - burned_total
    if active_supply < 0:
        raise ValueError("economy replay would create negative active supply")
    last_hash = rows[-1]["event_hash"] if rows else None
    fund_supply = sum(
        int(balances.get(key, {}).get("balance") or 0)
        for key in ("official_treasury", "promo_fund", "exchange_fund")
    )
    circulating_supply = active_supply - fund_supply
    if circulating_supply < 0:
        raise ValueError("economy replay would create negative circulating supply")
    wallet_root_hash = sha256_text(canonical_json({key: item["balance"] for key, item in sorted(balances.items())}))
    health = economy_health(policy=policy, minted_total=minted_total, balances=balances)
    result = {
        "policy": policy,
        "balances": balances,
        "minted_total": minted_total,
        "burned_total": burned_total,
        "active_supply": active_supply,
        "max_supply": int(policy["max_supply"]),
        "reserved_locked": int(policy["reserved_locked"]),
        "releasable_supply": releasable_supply,
        "mint_remaining": int(policy["max_supply"]) - minted_total,
        "releasable_remaining": releasable_supply - minted_total,
        "fund_supply": fund_supply,
        "circulating_supply": circulating_supply,
        "event_count": len(rows),
        "replay_height": len(rows),
        "replay_event_hash": last_hash,
        "wallet_root_hash": wallet_root_hash,
        "health": health,
    }
    if persist_cache:
        rebuild_economy_derived_balances(conn, replay=result)
    return result


def economy_health(*, policy, minted_total, balances):
    max_supply = int(policy["max_supply"])
    mint_remaining = max_supply - int(minted_total)
    mint_remaining_ratio = mint_remaining / max_supply if max_supply else 0
    promo_balance = int(balances.get("promo_fund", {}).get("balance") or 0)
    exchange_balance = int(balances.get("exchange_fund", {}).get("balance") or 0)
    status = "green"
    reasons = []
    if mint_remaining_ratio < 0.2:
        status = "red"
        reasons.append("mint_remaining_below_20_percent")
    elif mint_remaining_ratio < 0.5:
        status = "yellow"
        reasons.append("mint_remaining_below_50_percent")
    if promo_balance < int(policy["promo_critical_watermark"]):
        status = "red"
        reasons.append("promo_fund_critical")
    elif promo_balance < int(policy["promo_low_watermark"]) and status != "red":
        status = "yellow"
        reasons.append("promo_fund_low")
    if exchange_balance < int(policy["exchange_critical_watermark"]):
        status = "red"
        reasons.append("exchange_fund_critical")
    elif exchange_balance < int(policy["exchange_low_watermark"]) and status != "red":
        status = "yellow"
        reasons.append("exchange_fund_low")
    return {"status": status, "reasons": reasons or ["ok"]}


def _int_value(value):
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def economy_supply_equation_report(*, replay, circulation=None):
    """Build the root closed-loop supply equation from replay and wallet cache."""

    circulation = circulation if isinstance(circulation, dict) else {}
    balances = replay.get("balances") if isinstance(replay.get("balances"), dict) else {}
    promo_balance = _int_value((balances.get("promo_fund") or {}).get("balance"))
    official_balance = _int_value((balances.get("official_treasury") or {}).get("balance"))
    exchange_balance = _int_value((balances.get("exchange_fund") or {}).get("balance"))
    legacy_outstanding = _int_value(circulation.get("member_outstanding_points"))
    root_outstanding = _int_value(circulation.get("root_outstanding_points"))
    total_legacy_outstanding = legacy_outstanding + root_outstanding
    economy_circulating = _int_value(replay.get("circulating_supply"))
    max_supply = _int_value(replay.get("max_supply"))
    burned_total = _int_value(replay.get("burned_total"))
    mint_remaining = _int_value(replay.get("mint_remaining"))

    unfunded_legacy = max(0, total_legacy_outstanding - economy_circulating)
    promo_after_required_debit = promo_balance - unfunded_legacy
    actual_total = burned_total + official_balance + exchange_balance + promo_balance + total_legacy_outstanding + mint_remaining
    bridged_total = (
        burned_total
        + official_balance
        + exchange_balance
        + promo_after_required_debit
        + total_legacy_outstanding
        + mint_remaining
    )
    actual_gap = actual_total - max_supply
    bridged_gap = bridged_total - max_supply
    status = "balanced"
    if unfunded_legacy > promo_balance:
        status = "blocker"
    elif actual_gap != 0:
        status = "legacy_gap"

    return {
        "phase": "1B_walletized_replay",
        "status": status,
        "legacy_outstanding_points": legacy_outstanding,
        "root_outstanding_points": root_outstanding,
        "total_legacy_outstanding_points": total_legacy_outstanding,
        "burned_total": burned_total,
        "official_treasury_balance": official_balance,
        "exchange_fund_balance": exchange_balance,
        "promo_fund_balance": promo_balance,
        "mint_remaining": mint_remaining,
        "max_supply": max_supply,
        "economy_circulating_supply": economy_circulating,
        "unfunded_legacy_outstanding_points": unfunded_legacy,
        "promo_debit_required_points": unfunded_legacy,
        "promo_balance": promo_balance,
        "promo_balance_after_required_debit": promo_after_required_debit,
        "actual_supply_equation_total": actual_total,
        "actual_supply_equation_gap_points": actual_gap,
        "bridged_supply_equation_total": bridged_total,
        "bridged_supply_equation_gap_points": bridged_gap,
        "bridged_supply_equation_balanced": bridged_gap == 0,
        "formula": "burned + official_treasury + user_outstanding + mint_remaining + exchange_fund + promo_fund = max_supply",
        "note": "Closed-loop status is balanced when actual_supply_equation_gap_points is zero.",
    }


def economy_legacy_bridge_report(*, replay, circulation=None):
    return economy_supply_equation_report(replay=replay, circulation=circulation)


def rebuild_economy_derived_balances(conn, *, replay=None, chain_secret=None):
    if replay is None:
        replay = replay_economy_events(conn, chain_secret=chain_secret, persist_cache=False)
    now = utc_now()
    conn.execute("DELETE FROM points_economy_derived_balances")
    for fund_key, item in sorted((replay.get("balances") or {}).items()):
        conn.execute(
            """
            INSERT INTO points_economy_derived_balances (
                fund_key, address, balance, derived_cache, replay_height,
                replay_event_hash, updated_at
            ) VALUES (?, ?, ?, 1, ?, ?, ?)
            """,
            (
                fund_key,
                item["address"],
                int(item["balance"]),
                int(replay["replay_height"]),
                replay.get("replay_event_hash"),
                now,
            ),
        )
    return {"rebuilt": True, "replay_height": int(replay["replay_height"]), "wallet_root_hash": replay["wallet_root_hash"]}


def verify_economy_derived_balances(conn, *, replay=None, chain_secret=None):
    if replay is None:
        replay = replay_economy_events(conn, chain_secret=chain_secret, persist_cache=False)
    cached = {
        row["fund_key"]: dict(row)
        for row in conn.execute("SELECT * FROM points_economy_derived_balances").fetchall()
    }
    mismatches = []
    for fund_key, item in sorted((replay.get("balances") or {}).items()):
        row = cached.get(fund_key)
        if not row:
            mismatches.append({"fund_key": fund_key, "reason": "missing_cache_row"})
            continue
        if int(row["derived_cache"] or 0) != 1:
            mismatches.append({"fund_key": fund_key, "reason": "not_marked_derived_cache"})
        if row["address"] != item["address"]:
            mismatches.append({"fund_key": fund_key, "reason": "address_mismatch"})
        if int(row["balance"]) != int(item["balance"]):
            mismatches.append({"fund_key": fund_key, "reason": "balance_mismatch"})
        if int(row["replay_height"]) != int(replay["replay_height"]):
            mismatches.append({"fund_key": fund_key, "reason": "replay_height_mismatch"})
        if (row["replay_event_hash"] or "") != (replay.get("replay_event_hash") or ""):
            mismatches.append({"fund_key": fund_key, "reason": "replay_hash_mismatch"})
    for fund_key in sorted(set(cached) - set((replay.get("balances") or {}))):
        mismatches.append({"fund_key": fund_key, "reason": "orphan_cache_row"})
    return {
        "ok": not mismatches,
        "mismatches": mismatches,
        "replay_height": int(replay["replay_height"]),
        "wallet_root_hash": replay["wallet_root_hash"],
    }


def create_economy_snapshot(conn, *, replay=None, chain_secret=None, metadata=None):
    if replay is None:
        replay = replay_economy_events(conn, chain_secret=chain_secret, persist_cache=False)
    event_hash = replay.get("replay_event_hash")
    existing = conn.execute(
        """
        SELECT * FROM points_economy_snapshots
        WHERE snapshot_height=? AND event_hash IS ? AND wallet_root_hash=?
        ORDER BY id DESC
        LIMIT 1
        """,
        (int(replay["replay_height"]), event_hash, replay["wallet_root_hash"]),
    ).fetchone()
    if existing:
        snapshot = dict(existing)
        snapshot["created"] = False
        return snapshot
    now = utc_now()
    cur = conn.execute(
        """
        INSERT INTO points_economy_snapshots (
            snapshot_uuid, snapshot_height, event_hash, wallet_root_hash,
            minted_total, burned_total, active_supply, circulating_supply,
            metadata_json, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            str(uuid.uuid4()),
            int(replay["replay_height"]),
            event_hash,
            replay["wallet_root_hash"],
            int(replay["minted_total"]),
            int(replay["burned_total"]),
            int(replay["active_supply"]),
            int(replay["circulating_supply"]),
            _json_dumps({
                "policy_version": replay["policy"]["policy_version"],
                "phase": "1A",
                "source": "replay",
                **(metadata or {}),
            }),
            now,
        ),
    )
    snapshot = dict(conn.execute("SELECT * FROM points_economy_snapshots WHERE id=?", (cur.lastrowid,)).fetchone())
    snapshot["created"] = True
    return snapshot


def append_economy_incident(conn, *, severity, category, trigger, automatic_actions=None, metadata=None):
    severity = str(severity or "").strip().lower()
    if severity not in ECONOMY_INCIDENT_SEVERITIES:
        raise ValueError("unsupported economy incident severity")
    now = utc_now()
    cur = conn.execute(
        """
        INSERT INTO points_economy_incidents (
            incident_uuid, severity, category, trigger, status,
            automatic_actions_json, metadata_json, created_at
        ) VALUES (?, ?, ?, ?, 'open', ?, ?, ?)
        """,
        (
            str(uuid.uuid4()),
            severity,
            str(category or ""),
            str(trigger or ""),
            _json_dumps(list(automatic_actions or [])),
            _json_dumps(metadata or {}),
            now,
        ),
    )
    return conn.execute("SELECT * FROM points_economy_incidents WHERE id=?", (cur.lastrowid,)).fetchone()


def economy_layer_report(conn, *, chain_secret, actor=None, circulation=None):
    bootstrap = bootstrap_economy_layer(conn, chain_secret=chain_secret, actor=actor)
    replay = replay_economy_events(conn, policy=bootstrap["policy"], chain_secret=chain_secret, persist_cache=False)
    derived = rebuild_economy_derived_balances(conn, replay=replay)
    derived_verify = verify_economy_derived_balances(conn, replay=replay)
    snapshot = create_economy_snapshot(conn, replay=replay)
    incidents = [
        dict(row)
        for row in conn.execute(
            """
            SELECT * FROM points_economy_incidents
            ORDER BY id DESC
            LIMIT 20
            """
        ).fetchall()
    ]
    supply_equation = economy_supply_equation_report(replay=replay, circulation=circulation)
    return {
        "phase": "1A",
        "guardrail": "append_only_replay_source_of_truth",
        "bootstrap": {"created_count": bootstrap["created_count"]},
        "policy": replay["policy"],
        "funds": replay["balances"],
        "supply": {
            "max_supply": replay["max_supply"],
            "reserved_locked": replay["reserved_locked"],
            "releasable_supply": replay["releasable_supply"],
            "minted_total": replay["minted_total"],
            "burned_total": replay["burned_total"],
            "active_supply": replay["active_supply"],
            "fund_supply": replay["fund_supply"],
            "circulating_supply": replay["circulating_supply"],
            "mint_remaining": replay["mint_remaining"],
            "releasable_remaining": replay["releasable_remaining"],
        },
        "replay": {
            "height": replay["replay_height"],
            "event_hash": replay["replay_event_hash"],
            "wallet_root_hash": replay["wallet_root_hash"],
            "derived_cache": True,
            "derived_rebuild": derived,
            "derived_verify": derived_verify,
            "snapshot": snapshot,
        },
        "legacy_bridge": supply_equation,
        "supply_equation": supply_equation,
        "health": replay["health"],
        "incidents": incidents,
    }
