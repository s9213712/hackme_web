#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import random
import sqlite3
import ssl
import string
import sys
import threading
import time
import uuid
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from pathlib import Path
from statistics import median
from typing import Any

import requests

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from services.platform.db_mode_triggers import register_app_mode_function
from services.points_chain import PointsLedgerService
from services.points_chain.economy_layer import append_economy_event


class ProbeClient:
    def __init__(self, base_url: str, username: str, password: str, *, timeout: float = 15.0):
        self.base_url = base_url.rstrip("/")
        self.username = username
        self.password = password
        self.timeout = float(timeout)
        self.session = requests.Session()
        self.session.verify = False
        self.csrf = ""
        self.lock = threading.Lock()

    def refresh_csrf(self) -> None:
        res = self.session.get(f"{self.base_url}/api/csrf-token", timeout=self.timeout)
        res.raise_for_status()
        try:
            self.csrf = str(res.json().get("csrf_token") or "")
        except Exception:
            self.csrf = ""
        if not self.csrf:
            self.csrf = str(self.session.cookies.get("csrf_token") or "")

    def login(self) -> dict[str, Any]:
        self.refresh_csrf()
        res = self.session.post(
            f"{self.base_url}/api/login",
            json={"username": self.username, "password": self.password},
            headers={"X-CSRF-Token": self.csrf},
            timeout=self.timeout,
        )
        self.csrf = str(res.cookies.get("csrf_token") or self.session.cookies.get("csrf_token") or self.csrf)
        return _json_response(res)

    def request(self, method: str, path: str, *, expected: set[int] | None = None, **kwargs) -> dict[str, Any]:
        method = method.upper()
        expected = expected or {200}
        headers = dict(kwargs.pop("headers", {}) or {})
        if method in {"POST", "PUT", "PATCH", "DELETE"}:
            if not self.csrf:
                self.refresh_csrf()
            headers.setdefault("X-CSRF-Token", self.csrf)
        started = time.perf_counter()
        with self.lock:
            try:
                res = self.session.request(
                    method,
                    f"{self.base_url}{path}",
                    headers=headers,
                    timeout=self.timeout,
                    **kwargs,
                )
                if method in {"POST", "PUT", "PATCH", "DELETE"} and res.status_code in {400, 403} and "csrf" in res.text.lower()[:300]:
                    self.refresh_csrf()
                    headers["X-CSRF-Token"] = self.csrf
                    started = time.perf_counter()
                    res = self.session.request(
                        method,
                        f"{self.base_url}{path}",
                        headers=headers,
                        timeout=self.timeout,
                        **kwargs,
                    )
                payload = _json_response(res)
                payload["elapsed_ms"] = round((time.perf_counter() - started) * 1000, 3)
                payload["expected"] = int(res.status_code) in expected
                return payload
            except Exception as exc:
                return {
                    "status": 0,
                    "ok": False,
                    "expected": False,
                    "elapsed_ms": round((time.perf_counter() - started) * 1000, 3),
                    "error": f"{exc.__class__.__name__}: {str(exc)[:240]}",
                }


def _json_response(res: requests.Response) -> dict[str, Any]:
    try:
        body = res.json()
    except Exception:
        body = {"raw": res.text[:500]}
    if not isinstance(body, dict):
        body = {"body": body}
    body.setdefault("ok", 200 <= int(res.status_code) < 400)
    body["status"] = int(res.status_code)
    return body


def utc_old(seconds: int = 900) -> str:
    return (datetime.now(timezone.utc) - timedelta(seconds=seconds)).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def random_unowned_address(rng: random.Random) -> str:
    return "pc1" + "".join(rng.choice("0123456789abcdef") for _ in range(48))


def pick_other_client_address(
    clients: list[dict[str, Any]],
    sender: dict[str, Any],
    *,
    rng: random.Random,
) -> str:
    candidates = [item["address"] for item in clients if item.get("address") != sender.get("address")]
    if not candidates:
        return random_unowned_address(rng)
    return rng.choice(candidates)


def db_path(runtime_root: str) -> Path:
    root = Path(runtime_root)
    candidates = [
        root / "runtime" / "database" / "database.db",
        root / "hackme_web" / "runtime" / "database" / "database.db",
        root / "database" / "database.db",
    ]
    for path in candidates:
        if path.exists():
            return path
    raise SystemExit(f"database.db not found under {runtime_root}")


def chain_seed_path(runtime_root: str) -> Path:
    root = Path(runtime_root)
    candidates = [
        root / "runtime" / ".chain_seed",
        root / "hackme_web" / "runtime" / ".chain_seed",
        root / ".chain_seed",
    ]
    for path in candidates:
        if path.exists():
            return path
    raise SystemExit(f".chain_seed not found under {runtime_root}")


def service_for_runtime(runtime_root: str, *, mode: str) -> PointsLedgerService:
    database = db_path(runtime_root)
    chain_secret = chain_seed_path(runtime_root).read_text(encoding="utf-8").strip()

    def get_db() -> sqlite3.Connection:
        conn = sqlite3.connect(str(database), timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=30000")
        register_app_mode_function(conn, mode_reader=lambda: mode)
        return conn

    return PointsLedgerService(
        get_db=get_db,
        chain_secret=chain_secret,
        backup_dir=database.parent / "points_chain_backups",
        mode_reader=lambda: mode,
    )


def root_actor_for_service(service: PointsLedgerService) -> dict[str, Any]:
    conn = service.get_db()
    try:
        row = conn.execute("SELECT * FROM users WHERE username='root'").fetchone()
        if not row:
            raise RuntimeError("root user not found for fixture grant")
        keys = set(row.keys())
        return {
            "id": int(row["id"]),
            "username": str(row["username"]),
            "role": str(row["role"]),
            "member_level": row["member_level"] if "member_level" in keys else "trusted",
            "effective_level": row["effective_level"] if "effective_level" in keys else "trusted",
        }
    finally:
        conn.close()


def fixture_official_grant(service: PointsLedgerService, *, root_actor: dict[str, Any], destination: str, amount: int, request_uuid: str) -> dict[str, Any]:
    conn = service.get_db()
    try:
        service.ensure_schema(conn)
        conn.commit()
        conn.execute("BEGIN IMMEDIATE")
        transfer = service._official_wallet_grant_locked(
            conn,
            actor=root_actor,
            destination_wallet_address=destination,
            amount=int(amount),
            reason="destructive stress fixture official grant",
            request_uuid=request_uuid,
        )
        conn.commit()
        return transfer
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def fixture_mint_to_treasury(service: PointsLedgerService, *, root_actor: dict[str, Any], amount: int, request_uuid: str) -> dict[str, Any]:
    conn = service.get_db()
    try:
        service.ensure_schema(conn)
        conn.commit()
        conn.execute("BEGIN IMMEDIATE")
        event, created = append_economy_event(
            conn,
            chain_secret=service.chain_secret,
            event_type="mint",
            transaction_type="qa_destructive_stress_fixture_mint",
            source_fund_key="mint",
            destination_fund_key="official_treasury",
            amount=int(amount),
            idempotency_key=request_uuid,
            metadata={"fixture": True, "reason": "destructive stress isolated test funding"},
            actor=root_actor,
            chain_branch=service._canonical_branch_uuid(conn),
        )
        conn.commit()
        return {"event_uuid": event["event_uuid"], "created": bool(created), "amount": int(amount)}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def db_scalar(conn: sqlite3.Connection, sql: str, params: tuple[Any, ...] = ()) -> int:
    row = conn.execute(sql, params).fetchone()
    return int((row[0] if row else 0) or 0)


def force_proved(db: Path, prefix: str) -> dict[str, int]:
    conn = sqlite3.connect(str(db))
    try:
        old = utc_old()
        cur = conn.execute(
            """
            UPDATE points_chain_transfer_requests
            SET created_at=?
            WHERE request_uuid LIKE ? AND status='pending'
            """,
            (old, f"{prefix}%"),
        )
        conn.commit()
        return {"aged_pending_requests": int(cur.rowcount or 0)}
    finally:
        conn.close()


def db_counts(db: Path, prefix: str) -> dict[str, Any]:
    conn = sqlite3.connect(str(db))
    conn.row_factory = sqlite3.Row
    try:
        pending = db_scalar(conn, "SELECT COUNT(*) FROM points_chain_transfer_requests WHERE request_uuid LIKE ? AND status='pending'", (f"{prefix}%",))
        confirmed = db_scalar(conn, "SELECT COUNT(*) FROM points_chain_transfer_requests WHERE request_uuid LIKE ? AND status='confirmed'", (f"{prefix}%",))
        failed = db_scalar(conn, "SELECT COUNT(*) FROM points_chain_transfer_requests WHERE request_uuid LIKE ? AND status LIKE 'failed%'", (f"{prefix}%",))
        duplicate_request_uuid = db_scalar(
            conn,
            """
            SELECT COUNT(*) FROM (
                SELECT request_uuid FROM points_chain_transfer_requests
                GROUP BY request_uuid HAVING COUNT(*) > 1
            )
            """,
        )
        duplicate_active_wallet = db_scalar(
            conn,
            """
            SELECT COUNT(*) FROM (
                SELECT address FROM points_wallet_identities
                WHERE status IN ('pending_backup', 'active')
                GROUP BY address HAVING COUNT(*) > 1
            )
            """,
        )
        fee_to_burn = db_scalar(
            conn,
            """
            SELECT COUNT(*)
            FROM points_ledger
            WHERE action_type IN ('wallet_transfer_fee', 'chain_acceleration_fee')
              AND public_metadata_json LIKE '%burn%'
            """,
        )
        return {
            "prefix_pending": pending,
            "prefix_confirmed": confirmed,
            "prefix_failed": failed,
            "duplicate_request_uuid_groups": duplicate_request_uuid,
            "duplicate_active_wallet_address_groups": duplicate_active_wallet,
            "fee_ledgers_with_burn_metadata": fee_to_burn,
            "database_bytes": db.stat().st_size if db.exists() else 0,
        }
    finally:
        conn.close()


def pending_request_uuids(db: Path, prefix: str) -> list[str]:
    conn = sqlite3.connect(str(db))
    try:
        return [
            str(row[0])
            for row in conn.execute(
                """
                SELECT request_uuid
                FROM points_chain_transfer_requests
                WHERE request_uuid LIKE ? AND status='pending'
                ORDER BY id ASC
                """,
                (f"{prefix}%",),
            ).fetchall()
        ]
    finally:
        conn.close()


def finalize_prefix_pending_via_explorer(client: ProbeClient, db: Path, prefix: str) -> dict[str, Any]:
    refs = pending_request_uuids(db, prefix)
    results = []
    for ref in refs:
        res = client.request(
            "GET",
            f"/api/points/explorer/search?q={ref}&limit=1",
            expected={200, 404},
        )
        tx_status = ""
        try:
            tx_status = str((((res.get("result") or {}).get("transaction") or {}).get("status")) or "")
        except Exception:
            tx_status = ""
        results.append({"request_uuid": ref, "status": res.get("status"), "tx_status": tx_status})
    remaining = pending_request_uuids(db, prefix)
    return {
        "attempted": len(refs),
        "confirmed": sum(1 for item in results if item.get("tx_status") == "confirmed"),
        "remaining_pending": len(remaining),
        "remaining_request_uuids": remaining[:50],
        "samples": results[:20],
    }


def latency_summary(samples: list[dict[str, Any]]) -> dict[str, Any]:
    values = sorted(float(item.get("elapsed_ms") or 0) for item in samples if float(item.get("elapsed_ms") or 0) > 0)
    status = Counter(str(item.get("status", 0)) for item in samples)
    if not values:
        return {"count": len(samples), "status": dict(status)}
    return {
        "count": len(samples),
        "status": dict(sorted(status.items())),
        "p50_ms": round(float(median(values)), 3),
        "p95_ms": round(values[min(len(values) - 1, int(len(values) * 0.95))], 3),
        "p99_ms": round(values[min(len(values) - 1, int(len(values) * 0.99))], 3),
        "max_ms": round(values[-1], 3),
    }


def active_wallet(client: ProbeClient) -> tuple[str, dict[str, Any]]:
    wallet = client.request("GET", "/api/points/wallet")
    address = str((wallet.get("wallet") or {}).get("active_wallet_address") or "")
    if not address:
        onboarding = client.request("GET", "/api/points/wallet/onboarding")
        for item in ((onboarding.get("onboarding") or {}).get("wallets") or []):
            if item.get("wallet_type") == "official_hot" and item.get("address"):
                address = str(item["address"])
                break
    return address, wallet


def ensure_official_hot_wallet(client: ProbeClient) -> str:
    address, _wallet = active_wallet(client)
    if address:
        return address
    res = client.request(
        "POST",
        "/api/points/wallet/onboarding",
        json={"mode": "official_hot"},
        expected={200, 400, 409},
    )
    if int(res.get("status") or 0) != 200:
        raise RuntimeError(f"wallet onboarding failed for {client.username}: {res}")
    address = str((res.get("wallet_identity") or {}).get("address") or "")
    if not address:
        address, _wallet = active_wallet(client)
    if not address:
        raise RuntimeError(f"wallet address missing for {client.username}")
    return address


def create_or_get_user(root: ProbeClient, username: str, password: str) -> dict[str, Any]:
    search_path = f"/api/admin/users?q={username}&page_size=100"
    users = root.request("GET", search_path, expected={200})
    for item in users.get("users") or []:
        if item.get("username") == username:
            return {"id": int(item["id"]), "username": username, "created": False}
    res = root.request(
        "POST",
        "/api/admin/users",
        json={
            "username": username,
            "password": password,
            "password_confirm": password,
            "nickname": username,
            "role": "user",
            "status": "active",
        },
        expected={200, 409},
    )
    if int(res.get("status") or 0) not in {200, 409}:
        raise RuntimeError(f"user create failed: {username}: {res}")
    users = root.request("GET", search_path, expected={200})
    for item in users.get("users") or []:
        if item.get("username") == username:
            return {"id": int(item["id"]), "username": username, "created": int(res.get("status") or 0) == 200}
    raise RuntimeError(f"user not found after create: {username}")


def wallet_balance(client: ProbeClient) -> dict[str, int]:
    res = client.request("GET", "/api/points/wallet")
    wallet = res.get("wallet") or {}
    return {
        "balance": int(wallet.get("points_balance") or 0),
        "frozen": int(wallet.get("points_frozen") or 0),
        "account_balance": int(wallet.get("account_points_balance") or 0),
        "account_frozen": int(wallet.get("account_points_frozen") or 0),
    }


def fee_market_snapshot(client: ProbeClient, label: str) -> dict[str, Any]:
    base = client.request("GET", "/api/points/explorer/fee-estimate?fee_points=0", expected={200})
    estimate = base.get("estimate") or {}
    network = estimate.get("network_fee_state") or {}
    suggested_fee = int(network.get("suggested_priority_fee_points") or estimate.get("fee_reference_points") or 0)
    accelerated = client.request(
        "GET",
        f"/api/points/explorer/fee-estimate?fee_points={max(0, suggested_fee)}",
        expected={200},
    )
    accelerated_estimate = accelerated.get("estimate") or {}
    return {
        "label": label,
        "status": base.get("status"),
        "suggested_status": accelerated.get("status"),
        "pending_transfer_count": int(network.get("pending_transfer_count") or 0),
        "unsealed_ledger_count": int(network.get("unsealed_ledger_count") or 0),
        "recent_ledger_count": int(network.get("recent_ledger_count") or 0),
        "congestion_ratio": float(network.get("congestion_ratio") or 0),
        "congestion_label": network.get("congestion_label") or "",
        "base_fee_points": int(network.get("base_fee_points") or 0),
        "suggested_priority_fee_points": suggested_fee,
        "suggested_total_fee_points": int(network.get("suggested_total_fee_points") or 0),
        "zero_fee_estimated_seconds_min": int(estimate.get("estimated_seconds_min") or 0),
        "zero_fee_estimated_seconds_max": int(estimate.get("estimated_seconds_max") or 0),
        "suggested_fee_estimated_seconds_min": int(accelerated_estimate.get("estimated_seconds_min") or 0),
        "suggested_fee_estimated_seconds_max": int(accelerated_estimate.get("estimated_seconds_max") or 0),
        "speedup_ratio_at_suggested_fee": float(accelerated_estimate.get("speedup_ratio") or 0),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Destructive PointsChain/trading stress probe for isolated hackme_web runtimes.")
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--runtime-root", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--root-password", default="root")
    parser.add_argument("--accounts", type=int, default=20)
    parser.add_argument("--grant-points", type=int, default=5000)
    parser.add_argument("--transfer-ops", type=int, default=50)
    parser.add_argument("--trading-ops", type=int, default=30)
    parser.add_argument("--concurrency", type=int, default=16)
    parser.add_argument("--timeout", type=float, default=20.0)
    parser.add_argument("--mode", default="dev_ready")
    args = parser.parse_args()

    requests.packages.urllib3.disable_warnings()
    ssl._create_default_https_context = ssl._create_unverified_context

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    database = db_path(args.runtime_root)
    points_service = service_for_runtime(args.runtime_root, mode=args.mode)
    root_actor = root_actor_for_service(points_service)
    prefix = "dstress-" + datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S") + "-"
    rng = random.Random(prefix)
    samples: list[dict[str, Any]] = []
    findings: list[dict[str, Any]] = []
    fee_market_samples: list[dict[str, Any]] = []

    root = ProbeClient(args.base_url, "root", args.root_password, timeout=args.timeout)
    root_login = root.login()
    if int(root_login.get("status") or 0) != 200:
        raise SystemExit(f"root login failed: {root_login}")
    fee_market_samples.append(fee_market_snapshot(root, "baseline_before_internal_grants"))

    users: list[dict[str, Any]] = []
    password = "StressQa123!"
    for idx in range(max(1, int(args.accounts))):
        username = f"dstress_{datetime.now(timezone.utc).strftime('%H%M%S')}_{idx:02d}"
        users.append(create_or_get_user(root, username, password))

    clients: list[dict[str, Any]] = []
    for item in users:
        client = ProbeClient(args.base_url, item["username"], password, timeout=args.timeout)
        login = client.login()
        samples.append({"op": "login", **login})
        if int(login.get("status") or 0) != 200:
            findings.append({"severity": "high", "title": "stress user login failed", "user": item["username"], "response": login})
            continue
        address = ensure_official_hot_wallet(client)
        before = wallet_balance(client)
        clients.append({"user": item, "client": client, "address": address, "balance_before_grant": before})

    fixture_mint = fixture_mint_to_treasury(
        points_service,
        root_actor=root_actor,
        amount=max(0, len(clients) * int(args.grant_points) + 1000),
        request_uuid=prefix + "fixture-mint",
    )
    samples.append({"op": "fixture_mint_to_treasury", "status": 200, "ok": True, "expected": True, **fixture_mint})

    grant_samples = []
    for item in clients:
        request_uuid = prefix + "grant-" + item["user"]["username"]
        grant = fixture_official_grant(
            points_service,
            root_actor=root_actor,
            destination=item["address"],
            amount=int(args.grant_points),
            request_uuid=request_uuid,
        )
        res = {
            "ok": True,
            "status": 200,
            "expected": True,
            "op": "official_grant_fixture_internal",
            "transaction_hash": grant.get("transaction_hash"),
            "tx_group_hash": grant.get("transaction_hash"),
            "request_uuid": request_uuid,
            "settlement_rail": grant.get("settlement_rail") or "internal_hot_wallet",
            "fixture": True,
        }
        grant_samples.append(res)
        samples.append(res)
        after_grant = wallet_balance(item["client"])
        item["balance_after_internal_grant"] = after_grant
        item["grant_hash"] = res.get("transaction_hash") or res.get("tx_group_hash")
        if after_grant["balance"] < item["balance_before_grant"]["balance"] + int(args.grant_points):
            findings.append({
                "severity": "critical",
                "title": "pc0 official grant did not credit immediately",
                "user": item["user"]["username"],
                "before": item["balance_before_grant"],
                "after_grant": after_grant,
                "transaction_hash": item.get("grant_hash"),
            })

    fee_market_samples.append(fee_market_snapshot(root, "after_internal_official_grants"))
    forced_grants = force_proved(database, prefix + "grant-")
    root_refresh = root.request("GET", "/api/points/transactions?limit=100", expected={200})
    samples.append({"op": "root_finalize_grants", **root_refresh})
    explorer_finalized_grants = finalize_prefix_pending_via_explorer(root, database, prefix + "grant-")
    for item in clients:
        after_confirm = wallet_balance(item["client"])
        item["balance_after_confirmed_grant"] = after_confirm
        if after_confirm["balance"] < item["balance_before_grant"]["balance"] + int(args.grant_points):
            findings.append({
                "severity": "critical",
                "title": "official grant did not credit after forced proved finalization",
                "user": item["user"]["username"],
                "before": item["balance_before_grant"],
                "after_confirm": after_confirm,
                "transaction_hash": item.get("grant_hash"),
            })

    transfer_tasks: list[tuple[dict[str, Any], str, int, int, str, str]] = []
    for idx in range(max(1, int(args.transfer_ops))):
        sender = clients[idx % len(clients)]
        if idx % 5 == 0:
            destination = random_unowned_address(rng)
        else:
            destination = pick_other_client_address(clients, sender, rng=rng)
        amount = rng.randint(5, 45)
        fee = rng.randint(1, 30)
        transfer_tasks.append((sender, destination, amount, fee, prefix + f"tx-{idx:04d}", "stress transfer"))

    def submit_transfer(task: tuple[dict[str, Any], str, int, int, str, str]) -> dict[str, Any]:
        sender, destination, amount, fee, request_uuid, memo = task
        res = sender["client"].request(
            "POST",
            "/api/points/transactions/submit",
            json={
                "source_wallet_address": sender["address"],
                "destination_wallet_address": destination,
                "amount_points": amount,
                "fee_points": fee,
                "request_uuid": request_uuid,
                "memo": memo,
            },
            expected={200, 409},
        )
        res.update({
            "op": "wallet_transfer",
            "request_uuid": request_uuid,
            "sender_username": sender["user"]["username"],
            "sender_address": sender["address"],
            "amount": amount,
            "fee": fee,
        })
        return res

    with ThreadPoolExecutor(max_workers=max(1, int(args.concurrency))) as pool:
        for fut in as_completed([pool.submit(submit_transfer, task) for task in transfer_tasks]):
            samples.append(fut.result())

    duplicate_task = (clients[0], clients[1]["address"], 11, 1, prefix + "duplicate-once", "duplicate idempotency")
    dup_first = submit_transfer(duplicate_task)
    dup_second = submit_transfer(duplicate_task)
    samples.extend([{**dup_first, "op": "duplicate_first"}, {**dup_second, "op": "duplicate_second"}])
    if not (dup_first.get("transaction_hash") and dup_first.get("transaction_hash") == dup_second.get("transaction_hash") and dup_second.get("created") is False):
        findings.append({"severity": "high", "title": "duplicate request_uuid was not idempotent", "first": dup_first, "second": dup_second})

    rich = max(clients, key=lambda item: wallet_balance(item["client"])["balance"])
    rich_balance = wallet_balance(rich["client"])["balance"]
    oversized_amount = max(100, rich_balance // 3)
    overspend_tasks = [
        (rich, random_unowned_address(rng), oversized_amount, 1, prefix + f"overspend-{idx:02d}", "overspend probe")
        for idx in range(12)
    ]
    overspend_results = []
    with ThreadPoolExecutor(max_workers=min(12, max(1, int(args.concurrency)))) as pool:
        for fut in as_completed([pool.submit(submit_transfer, task) for task in overspend_tasks]):
            result = fut.result()
            result["op"] = "overspend_transfer"
            overspend_results.append(result)
            samples.append(result)
    if not any(int(r.get("status") or 0) == 409 for r in overspend_results):
        findings.append({"severity": "critical", "title": "overspend burst did not produce any insufficient-balance rejection", "balance": rich_balance, "amount": oversized_amount})
    rich_after_overspend = wallet_balance(rich["client"])
    if rich_after_overspend["balance"] < 0:
        findings.append({"severity": "critical", "title": "wallet balance went negative after overspend burst", "wallet": rich["address"], "balance": rich_after_overspend})

    fee_market_samples.append(fee_market_snapshot(root, "after_pending_transfer_burst"))
    pending_ok = [
        s
        for s in samples
        if s.get("op") in {"wallet_transfer", "duplicate_first", "overspend_transfer"}
        and int(s.get("status") or 0) == 200
        and str(((s.get("request") or {}).get("status")) or "").lower() == "pending"
        and str(((s.get("request") or {}).get("settlement_rail")) or "").lower() != "internal_hot_wallet"
    ]
    if pending_ok:
        target = pending_ok[0]
        owner = next((item for item in clients if item["user"]["username"] == target.get("sender_username")), clients[0])
        accel = owner["client"].request(
            "POST",
            "/api/points/explorer/accelerate",
            json={
                "ledger_ref": target.get("transaction_hash") or target.get("tx_group_hash"),
                "fee_points": 25,
                "request_uuid": prefix + "accelerate-1",
            },
            expected={200, 409},
        )
        accel["op"] = "accelerate_pending"
        samples.append(accel)
        if int(accel.get("status") or 0) != 200:
            findings.append({"severity": "high", "title": "transaction owner could not accelerate pending transfer", "target": target, "response": accel})
    else:
        samples.append({
            "op": "accelerate_pending_skipped",
            "status": 200,
            "ok": True,
            "expected": True,
            "reason": "no cold-chain pending transfer; pc0 internal transfers are immediately settled and cannot be accelerated",
        })

    notification_checks = []
    for item in clients[:2]:
        notices = item["client"].request("GET", "/api/notifications?limit=50", expected={200, 503})
        notification_checks.append({
            "user": item["user"]["username"],
            "status": notices.get("status"),
            "types": [n.get("type") for n in (notices.get("notifications") or [])[:20]],
            "unread_count": notices.get("unread_count"),
        })

    forced_transfers = force_proved(database, prefix)
    for _ in range(3):
        refreshed = root.request("GET", "/api/points/transactions?limit=100", expected={200})
        samples.append({"op": "root_finalize_transfers", **refreshed})
        if int(((refreshed.get("summary") or {}).get("pending_count") or 0)) == 0:
            break
        time.sleep(0.2)
    explorer_finalized = finalize_prefix_pending_via_explorer(root, database, prefix)
    fee_market_samples.append(fee_market_snapshot(root, "after_forced_finality_before_seal"))

    trading_results = []
    markets = clients[0]["client"].request("GET", "/api/trading/markets", expected={200, 403, 503})
    samples.append({"op": "trading_markets", **markets})
    market_list = markets.get("markets") or markets.get("data") or []
    if isinstance(market_list, list) and market_list:
        market = market_list[0]
        symbol = market.get("symbol") or "BTC/POINTS"
    else:
        symbol = "BTC/POINTS"
    for idx in range(max(0, int(args.trading_ops))):
        client = clients[idx % len(clients)]["client"]
        res = client.request(
            "POST",
            "/api/trading/orders",
            json={
                "market_symbol": symbol,
                "side": "buy",
                "order_type": "limit",
                "quantity": "1",
                "limit_price_points": 100,
            },
            expected={200, 400, 403, 409, 503},
        )
        res["op"] = "trading_limit_buy"
        trading_results.append(res)
        samples.append(res)

    margin_probe = clients[0]["client"].request(
        "POST",
        "/api/trading/margin/open",
        json={
            "market_symbol": symbol,
            "position_type": "margin_long",
            "quantity": "1000000",
            "collateral_points": 1,
            "idempotency_key": prefix + "margin-exhaustion",
        },
        expected={200, 400, 403, 409, 503},
    )
    margin_probe["op"] = "margin_exhaustion_probe"
    samples.append(margin_probe)

    seal = root.request("POST", "/api/root/points/chain/seal", json={"limit": 500}, expected={200, 400, 409})
    verify = root.request("GET", "/api/root/points/chain/verify", expected={200})
    root_report = root.request("GET", "/api/root/points/report", expected={200})
    trading_refresh = root.request("POST", "/api/root/trading/sitewide/refresh", json={"reason": "destructive_stress"}, expected={200, 400, 409, 503})
    trading_pools = root.request("GET", "/api/root/trading/sitewide/pools", expected={200, 400, 404, 409, 503})
    samples.extend([
        {"op": "root_chain_seal", **seal},
        {"op": "root_chain_verify", **verify},
        {"op": "root_points_report", **root_report},
        {"op": "root_trading_refresh", **trading_refresh},
        {"op": "root_trading_pools", **trading_pools},
    ])
    fee_market_samples.append(fee_market_snapshot(root, "after_seal"))

    counts = db_counts(database, prefix)
    if explorer_finalized["remaining_pending"]:
        findings.append({
            "severity": "critical",
            "title": "forced-proved pending transfers remained pending after root list and explorer finalization",
            "remaining_pending": explorer_finalized["remaining_pending"],
            "remaining_request_uuids": explorer_finalized["remaining_request_uuids"],
        })
    if len(fee_market_samples) >= 3:
        def assert_fee_market_monotonic(before: dict[str, Any], after: dict[str, Any], label: str) -> None:
            before_congestion = float(before.get("congestion_ratio") or 0)
            after_congestion = float(after.get("congestion_ratio") or 0)
            if after_congestion <= before_congestion:
                return
            if after["suggested_priority_fee_points"] < before["suggested_priority_fee_points"]:
                findings.append({
                    "severity": "high",
                    "title": f"suggested priority fee did not rise with {label} congestion",
                    "before": before,
                    "after": after,
                })
            if after["zero_fee_estimated_seconds_min"] < before["zero_fee_estimated_seconds_min"]:
                findings.append({
                    "severity": "high",
                    "title": f"zero-fee finality estimate got faster while {label} congestion increased",
                    "before": before,
                    "after": after,
                })

        baseline = fee_market_samples[0]
        internal_grants = fee_market_samples[1]
        transfer_pending = fee_market_samples[2]
        assert_fee_market_monotonic(baseline, internal_grants, "internal grant")
        assert_fee_market_monotonic(internal_grants, transfer_pending, "transfer burst")
        for snapshot in fee_market_samples:
            if snapshot["suggested_priority_fee_points"] > 0 and snapshot["suggested_fee_estimated_seconds_min"] >= snapshot["zero_fee_estimated_seconds_min"]:
                findings.append({
                    "severity": "medium",
                    "title": "suggested priority fee did not improve minimum finality estimate",
                    "snapshot": snapshot,
                })
    if counts["duplicate_request_uuid_groups"]:
        findings.append({"severity": "critical", "title": "duplicate request_uuid rows exist", "count": counts["duplicate_request_uuid_groups"]})
    if counts["duplicate_active_wallet_address_groups"]:
        findings.append({"severity": "critical", "title": "duplicate active wallet address bindings exist", "count": counts["duplicate_active_wallet_address_groups"]})
    if not bool(verify.get("ok")):
        findings.append({"severity": "critical", "title": "PointsChain verify failed after destructive stress", "verification": verify.get("verification")})
    hard_5xx = [s for s in samples if int(s.get("status") or 0) >= 500 and int(s.get("status") or 0) != 503]
    if hard_5xx:
        findings.append({"severity": "high", "title": "HTTP 5xx during destructive stress", "count": len(hard_5xx), "samples": hard_5xx[:10]})

    payload = {
        "ok": not findings,
        "prefix": prefix,
        "base_url": args.base_url,
        "runtime_root": args.runtime_root,
        "database": str(database),
        "accounts_requested": int(args.accounts),
        "accounts_active": len(clients),
        "grant_points": int(args.grant_points),
        "forced_grants": forced_grants,
        "explorer_finalized_grants": explorer_finalized_grants,
        "forced_transfers": forced_transfers,
        "explorer_finalized_transfers": explorer_finalized,
        "latency": latency_summary(samples),
        "fee_market_samples": fee_market_samples,
        "status_by_operation": {
            op: dict(Counter(str(item.get("status", 0)) for item in samples if item.get("op") == op))
            for op in sorted({str(item.get("op") or "") for item in samples})
        },
        "notification_checks": notification_checks,
        "db_counts": counts,
        "seal": seal,
        "verify": verify,
        "trading": {
            "market_symbol": symbol,
            "order_status": dict(Counter(str(item.get("status", 0)) for item in trading_results)),
            "margin_probe": margin_probe,
            "sitewide_refresh": trading_refresh,
            "sitewide_pools": trading_pools,
        },
        "findings": findings,
        "sample_errors": [s for s in samples if not s.get("expected", True) or int(s.get("status") or 0) >= 500][:100],
    }
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if payload["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
