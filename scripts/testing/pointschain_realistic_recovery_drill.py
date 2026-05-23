#!/usr/bin/env python3
"""Simulate theft, emergency review, freeze, voting, and recovery on a live runtime DB."""

from __future__ import annotations

import argparse
import base64
import json
import sqlite3
import sys
import time
from pathlib import Path

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec, utils

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from services.platform.db_mode_triggers import register_app_mode_function
from services.points_chain import (
    PointsLedgerService,
    address_dispute_payload,
    address_from_public_key,
    bind_self_custody_wallet,
    create_official_hot_wallet,
    ensure_points_economy_schema,
    wallet_binding_payload,
    wallet_transaction_payload,
)
from services.points_chain.economy_layer import append_economy_event
from services.points_chain.schema import _json_loads, canonical_json, sha256_text


def actor(row: sqlite3.Row) -> dict:
    return {
        "id": int(row["id"]),
        "username": row["username"],
        "role": row["role"],
        "member_level": row["member_level"] if "member_level" in row.keys() else "normal",
        "effective_level": row["effective_level"] if "effective_level" in row.keys() else "normal",
    }


def force_request_proved(service: PointsLedgerService, tx_hash: str) -> None:
    conn = service.get_db()
    try:
        service.ensure_schema(conn)
        conn.execute(
            "UPDATE points_chain_transfer_requests SET created_at='2026-01-01T00:00:00Z' WHERE tx_group_hash=?",
            (tx_hash,),
        )
        conn.commit()
    finally:
        conn.close()
    service.explorer_transaction(tx_hash)


def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(bytes(data)).decode("ascii").rstrip("=")


def public_jwk(private_key) -> dict:
    numbers = private_key.public_key().public_numbers()
    return {
        "kty": "EC",
        "crv": "P-256",
        "x": b64url(numbers.x.to_bytes(32, "big")),
        "y": b64url(numbers.y.to_bytes(32, "big")),
    }


def signature(private_key, payload: dict) -> str:
    der = private_key.sign(canonical_json(payload).encode("utf-8"), ec.ECDSA(hashes.SHA256()))
    r, s = utils.decode_dss_signature(der)
    return b64url(r.to_bytes(32, "big") + s.to_bytes(32, "big"))


def ensure_user(conn: sqlite3.Connection, *, username: str, role: str = "user", level: str = "trusted") -> sqlite3.Row:
    row = conn.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
    if row:
        return row
    cols = {item["name"] for item in conn.execute("PRAGMA table_info(users)").fetchall()}
    payload = {
        "username": username,
        "role": role,
        "status": "active",
        "member_level": level,
        "base_level": level,
        "effective_level": level,
    }
    insert_cols = [key for key in payload if key in cols]
    placeholders = ",".join("?" for _ in insert_cols)
    conn.execute(
        f"INSERT INTO users ({','.join(insert_cols)}) VALUES ({placeholders})",
        tuple(payload[key] for key in insert_cols),
    )
    return conn.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()


def wallet_for(service: PointsLedgerService, user_id: int) -> dict:
    conn = service.get_db()
    try:
        service.ensure_schema(conn)
        wallet = create_official_hot_wallet(conn, user_id=user_id, chain_secret=service.chain_secret)
        conn.commit()
        return wallet
    finally:
        conn.close()


def self_custody_wallet_for(service: PointsLedgerService, user_id: int, *, label: str) -> tuple[dict, object]:
    private_key = ec.generate_private_key(ec.SECP256R1())
    jwk = public_jwk(private_key)
    address = address_from_public_key(jwk)
    payload = wallet_binding_payload(
        user_id=user_id,
        wallet_type="self_custody_cold",
        address=address,
        public_key_jwk=jwk,
    )
    conn = service.get_db()
    try:
        service.ensure_schema(conn)
        wallet = bind_self_custody_wallet(
            conn,
            user_id=user_id,
            wallet_type="self_custody_cold",
            public_key_jwk=jwk,
            address=address,
            signature=signature(private_key, payload),
            backup_confirmed=True,
            label=label,
        )
        conn.commit()
        return wallet, private_key
    finally:
        conn.close()


def signed_transfer(service: PointsLedgerService, *, actor_value: dict, wallet: dict, private_key, destination: str, amount: int, fee: int, request_uuid: str, memo: str) -> dict:
    branch = service.explorer_wallet(wallet["address"])["wallet"]["chain_branch"]
    payload = wallet_transaction_payload(
        user_id=actor_value["id"],
        source_wallet_address=wallet["address"],
        destination_wallet_address=destination,
        amount_points=amount,
        fee_points=fee,
        request_uuid=request_uuid,
        memo=memo,
        chain_branch=branch,
        signer_key_id=wallet["public_key_hash"],
    )
    return service.submit_wallet_transaction(
        actor=actor_value,
        source_wallet_address=wallet["address"],
        destination_wallet_address=destination,
        amount_points=amount,
        fee_points=fee,
        request_uuid=request_uuid,
        memo=memo,
        signature=signature(private_key, payload),
    )


def user_row(service: PointsLedgerService, user_id: int) -> sqlite3.Row:
    conn = service.get_db()
    try:
        return conn.execute("SELECT * FROM users WHERE id=?", (int(user_id),)).fetchone()
    finally:
        conn.close()


def proposal_row(service: PointsLedgerService, proposal_uuid: str) -> sqlite3.Row:
    conn = service.get_db()
    try:
        service.ensure_schema(conn)
        return conn.execute(
            "SELECT * FROM points_chain_governance_proposals WHERE proposal_uuid=?",
            (proposal_uuid,),
        ).fetchone()
    finally:
        conn.close()


def vote_until_passed(service: PointsLedgerService, proposal_uuid: str, *, recovery_choice: str = "") -> dict:
    row = proposal_row(service, proposal_uuid)
    eligible = [int(item) for item in _json_loads(row["eligible_voters_json"], [])]
    quorum = int(row["quorum_count"] or 0)
    needed = max(quorum, 2)
    result = None
    for user_id in eligible[:needed]:
        voter = actor(user_row(service, user_id))
        result = service.cast_governance_vote(
            actor=voter,
            proposal_uuid=proposal_uuid,
            vote="yes",
            recovery_choice=recovery_choice,
        )
        if (result.get("proposal") or {}).get("status") == "passed":
            return result
    return result or {"ok": False}


def fixture_grant(service: PointsLedgerService, *, root: dict, destination: str, amount: int, ref: str) -> dict:
    conn = service.get_db()
    try:
        service.ensure_schema(conn)
        conn.execute("BEGIN IMMEDIATE")
        transfer = service._official_wallet_grant_locked(
            conn,
            actor=root,
            destination_wallet_address=destination,
            amount=amount,
            reason=f"realistic recovery drill setup fixture grant {ref}",
            request_uuid=ref,
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    force_request_proved(service, transfer["transaction_hash"])
    return transfer


def fixture_mint_to_treasury(service: PointsLedgerService, *, root: dict, amount: int, ref: str) -> dict:
    conn = service.get_db()
    try:
        service.ensure_schema(conn)
        conn.execute("BEGIN IMMEDIATE")
        event, created = append_economy_event(
            conn,
            chain_secret=service.chain_secret,
            event_type="mint",
            transaction_type="qa_recovery_drill_fixture_mint",
            source_fund_key="mint",
            destination_fund_key="official_treasury",
            amount=int(amount),
            idempotency_key=ref,
            metadata={"reason": "QA recovery drill setup funding", "fixture": True},
            actor=root,
            chain_branch=service._canonical_branch_uuid(conn),
        )
        conn.commit()
        return {"event_uuid": event["event_uuid"], "created": bool(created), "amount": int(amount)}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime-root", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--mode", default="dev_ready")
    args = parser.parse_args()

    runtime_root = Path(args.runtime_root)
    db_path = runtime_root / "database" / "database.db"
    chain_seed_path = runtime_root / ".chain_seed"
    chain_secret = chain_seed_path.read_text(encoding="utf-8").strip()

    def get_db() -> sqlite3.Connection:
        conn = sqlite3.connect(db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=30000")
        register_app_mode_function(conn, mode_reader=lambda: args.mode)
        return conn

    service = PointsLedgerService(
        get_db=get_db,
        chain_secret=chain_secret,
        backup_dir=runtime_root / "database" / "points_chain_backups",
        mode_reader=lambda: args.mode,
    )
    run_id = str(int(time.time()))
    victim_name = f"qa_victim_{run_id}"
    attacker_name = f"qa_attacker_{run_id}"
    merchant_name = f"qa_merchant_{run_id}"

    conn = get_db()
    try:
        service.ensure_schema(conn)
        ensure_points_economy_schema(conn)
        root_row = conn.execute("SELECT * FROM users WHERE username='root'").fetchone()
        manager_row = conn.execute("SELECT * FROM users WHERE role IN ('manager','super_admin') AND username!='root' ORDER BY id LIMIT 1").fetchone()
        if not root_row or not manager_row:
            raise RuntimeError("root and manager users are required")
        victim_row = ensure_user(conn, username=victim_name, role="user", level="trusted")
        attacker_row = ensure_user(conn, username=attacker_name, role="user", level="trusted")
        merchant_row = ensure_user(conn, username=merchant_name, role="user", level="trusted")
        conn.commit()
    finally:
        conn.close()

    root = actor(root_row)
    manager = actor(manager_row)
    victim = actor(victim_row)
    attacker = actor(attacker_row)

    victim_wallet, victim_key = self_custody_wallet_for(service, victim["id"], label=f"recovery drill victim {run_id}")
    attacker_wallet, attacker_key = self_custody_wallet_for(service, attacker["id"], label=f"recovery drill attacker {run_id}")
    merchant_wallet = wallet_for(service, int(merchant_row["id"]))

    fixture_mint = fixture_mint_to_treasury(
        service,
        root=root,
        amount=500,
        ref=f"recovery-drill-fixture-mint-{run_id}",
    )
    grant_victim = fixture_grant(
        service,
        root=root,
        destination=victim_wallet["address"],
        amount=100,
        ref=f"recovery-drill-victim-{run_id}",
    )
    grant_attacker = fixture_grant(
        service,
        root=root,
        destination=attacker_wallet["address"],
        amount=5,
        ref=f"recovery-drill-attacker-legit-{run_id}",
    )

    before_theft_victim = service.explorer_wallet(victim_wallet["address"])["wallet"]
    before_theft_attacker = service.explorer_wallet(attacker_wallet["address"])["wallet"]

    stolen = signed_transfer(
        service,
        actor_value=victim,
        wallet=victim_wallet,
        private_key=victim_key,
        destination=attacker_wallet["address"],
        amount=60,
        fee=1,
        request_uuid=f"recovery-drill-theft-{run_id}",
        memo="realistic drill: stolen transfer before discovery",
    )
    force_request_proved(service, stolen["transaction_hash"])

    attacker_spend = signed_transfer(
        service,
        actor_value=attacker,
        wallet=attacker_wallet,
        private_key=attacker_key,
        destination=merchant_wallet["address"],
        amount=30,
        fee=1,
        request_uuid=f"recovery-drill-attacker-spend-{run_id}",
        memo="realistic drill: attacker spends part of stolen funds before review",
    )
    force_request_proved(service, attacker_spend["transaction_hash"])

    dispute_statement = "Realistic drill victim statement: private key phishing caused unauthorized transfer."
    dispute_evidence = [stolen["transaction_hash"], attacker_spend["transaction_hash"]]
    dispute_tx = service.explorer_transaction(stolen["transaction_hash"])["transaction"]
    dispute_runtime_mode = service._address_dispute_runtime_mode()
    dispute_payload = address_dispute_payload(
        tx_hash=stolen["transaction_hash"],
        from_wallet_address=victim_wallet["address"],
        to_wallet_address=attacker_wallet["address"],
        amount_points=60,
        statement_hash=sha256_text(dispute_statement),
        evidence_hash=sha256_text(canonical_json(dispute_evidence)),
        nonce=f"recovery-drill-dispute-{run_id}",
        chain_branch=dispute_tx["chain_branch"],
        purpose="address_dispute_open",
        runtime_mode=dispute_runtime_mode,
    )
    dispute = service.create_transaction_dispute(
        actor=victim,
        tx_hash=stolen["transaction_hash"],
        statement=dispute_statement,
        victim_wallet_address=victim_wallet["address"],
        claimed_amount_points=60,
        loss_cause="private_key_leak",
        evidence=dispute_evidence,
        public_key_jwk=public_jwk(victim_key),
        signature=signature(victim_key, dispute_payload),
        signature_nonce=f"recovery-drill-dispute-{run_id}",
        from_wallet_address=victim_wallet["address"],
        to_wallet_address=attacker_wallet["address"],
        chain_branch=dispute_tx["chain_branch"],
    )["dispute"]
    reviewed = service.review_transaction_dispute(
        actor=root,
        dispute_uuid=dispute["dispute_uuid"],
        status="approved",
        review_note="root review approved incident; immediate temporary freeze while public governance decides",
        recommended_strategy="tainted_remainder_return",
        create_proposal=True,
    )

    blocked_after_freeze = False
    blocked_after_freeze_reason = ""
    try:
        service.submit_wallet_transaction(
            actor=attacker,
            source_wallet_address=attacker_wallet["address"],
            destination_wallet_address=merchant_wallet["address"],
            amount_points=1,
            fee_points=0,
            request_uuid=f"recovery-drill-blocked-after-freeze-{run_id}",
            memo="this should be blocked by provisional freeze",
        )
    except Exception as exc:
        blocked_after_freeze = True
        blocked_after_freeze_reason = str(exc)

    recovery_proposal_uuid = reviewed["proposal"]["proposal_uuid"]
    risk_proposal_uuid = reviewed["address_risk_proposal"]["proposal_uuid"]
    freeze_proposal_uuid = reviewed["address_freeze_proposal"]["proposal_uuid"]

    recovery_vote = vote_until_passed(service, recovery_proposal_uuid, recovery_choice="tainted_remainder_return")
    risk_vote = vote_until_passed(service, risk_proposal_uuid)
    freeze_vote = vote_until_passed(service, freeze_proposal_uuid)

    recovery_executed = service.execute_governance_proposal(actor=manager, proposal_uuid=recovery_proposal_uuid)
    risk_executed = service.execute_governance_proposal(actor=manager, proposal_uuid=risk_proposal_uuid)
    freeze_executed = service.execute_governance_proposal(actor=manager, proposal_uuid=freeze_proposal_uuid)

    after_victim = service.explorer_wallet(victim_wallet["address"])["wallet"]
    after_attacker = service.explorer_wallet(attacker_wallet["address"])["wallet"]
    after_merchant = service.explorer_wallet(merchant_wallet["address"])["wallet"]
    report = service.root_report()

    result = {
        "ok": bool(
            blocked_after_freeze
            and recovery_executed.get("ok")
            and risk_executed.get("ok")
            and freeze_executed.get("ok")
            and (after_attacker.get("governance_freeze") or {}).get("freeze_type") == "governance"
            and (after_attacker.get("risk_label") or {}).get("status") == "active"
        ),
        "run_id": run_id,
        "users": {
            "victim": {"id": victim["id"], "username": victim["username"], "wallet": victim_wallet["address"]},
            "attacker": {"id": attacker["id"], "username": attacker["username"], "wallet": attacker_wallet["address"]},
            "merchant": {"id": int(merchant_row["id"]), "username": merchant_row["username"], "wallet": merchant_wallet["address"]},
        },
        "setup_fixture_mint": fixture_mint,
        "setup_grants": [grant_victim["transaction_hash"], grant_attacker["transaction_hash"]],
        "incident": {
            "theft_tx_hash": stolen["transaction_hash"],
            "attacker_spend_tx_hash": attacker_spend["transaction_hash"],
            "strategy": "tainted_remainder_return",
            "claimed_amount": 60,
        },
        "dispute": reviewed["dispute"],
        "immediate_provisional_freeze": reviewed.get("provisional_freeze"),
        "blocked_after_freeze": blocked_after_freeze,
        "blocked_after_freeze_reason": blocked_after_freeze_reason,
        "proposals": {
            "recovery": {
                "proposal_uuid": recovery_proposal_uuid,
                "vote_status": (recovery_vote.get("proposal") or {}).get("status"),
                "execution": recovery_executed.get("result"),
            },
            "address_risk": {
                "proposal_uuid": risk_proposal_uuid,
                "vote_status": (risk_vote.get("proposal") or {}).get("status"),
                "execution": risk_executed.get("result"),
            },
            "address_freeze": {
                "proposal_uuid": freeze_proposal_uuid,
                "vote_status": (freeze_vote.get("proposal") or {}).get("status"),
                "execution": freeze_executed.get("result"),
            },
        },
        "balances": {
            "before_theft": {
                "victim": before_theft_victim["points_balance"],
                "attacker": before_theft_attacker["points_balance"],
            },
            "after_recovery": {
                "victim": after_victim["points_balance"],
                "attacker": after_attacker["points_balance"],
                "merchant": after_merchant["points_balance"],
            },
            "victim_recovered_points": int(after_victim["points_balance"]) - 39,
            "victim_unrecovered_or_fee_loss": 100 - int(after_victim["points_balance"]),
        },
        "attacker_wallet_state": {
            "risk_label": after_attacker.get("risk_label"),
            "governance_freeze": after_attacker.get("governance_freeze"),
            "provisional_freeze": after_attacker.get("provisional_freeze"),
        },
        "canonical_branch": next((item for item in report["governance"]["branches"] if item.get("is_canonical")), None),
        "notes": [
            "setup grants use the PointsChain official grant primitive as a test fixture because live treasury multisig signers are cold wallets and the drill does not have their private keys",
            "a fixture mint funds official treasury for this drill only; production mint remains governance-gated",
            "created_at was backdated only to simulate 20-proved elapsed time; incident, freeze, governance, and recovery used PointsChain service/governance paths",
            "provisional freeze is immediate and temporary; formal freeze/risk label required public governance execution",
        ],
    }

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
