#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import time
from collections import Counter
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from datetime import datetime, timezone
from pathlib import Path
from statistics import median
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.testing.points_chain_destructive_stress import (
    db_counts,
    db_path,
    ensure_fixture_treasury_funding,
    fixture_official_grant,
    parse_pids,
    root_actor_for_service,
    service_for_runtime,
)
from scripts.testing.db_stress_probe import ResourceMonitor


def percentile(values: list[float], ratio: float) -> float:
    if not values:
        return 0.0
    idx = max(0, min(len(values) - 1, int(len(values) * ratio) - 1))
    return float(values[idx])


def latency_summary(values: list[float]) -> dict[str, Any]:
    values = sorted(float(value or 0) for value in values if float(value or 0) > 0)
    if not values:
        return {"count": 0}
    return {
        "count": len(values),
        "min_ms": round(values[0], 3),
        "median_ms": round(median(values), 3),
        "p95_ms": round(percentile(values, 0.95), 3),
        "p99_ms": round(percentile(values, 0.99), 3),
        "max_ms": round(values[-1], 3),
    }


def load_hot_wallet_users(service, *, username_like: str, limit: int) -> list[dict[str, Any]]:
    conn = service.get_db()
    conn.row_factory = sqlite3.Row
    try:
        service.ensure_schema(conn)
        rows = conn.execute(
            """
            SELECT u.id, u.username, u.role, w.address
            FROM users u
            JOIN points_wallet_identities w ON w.user_id=u.id
            WHERE u.username LIKE ?
              AND u.username != 'root'
              AND w.wallet_type='official_hot'
              AND w.status IN ('pending_backup', 'active')
            ORDER BY u.id DESC
            LIMIT ?
            """,
            (username_like, max(1, int(limit))),
        ).fetchall()
        return [
            {
                "id": int(row["id"]),
                "username": str(row["username"]),
                "role": str(row["role"] or "user"),
                "address": str(row["address"]),
            }
            for row in rows
        ]
    finally:
        conn.close()


def run_direct_transfers(service, *, users: list[dict[str, Any]], prefix: str, ops: int, concurrency: int) -> dict[str, Any]:
    completed = 0
    errors = 0
    latency_values: list[float] = []
    status_counts: Counter[str] = Counter()
    error_samples: list[dict[str, Any]] = []
    progress: list[dict[str, Any]] = []
    started = time.perf_counter()

    def submit(idx: int) -> dict[str, Any]:
        sender = users[idx % len(users)]
        recipient = users[(idx * 7 + 1) % len(users)]
        if recipient["address"] == sender["address"]:
            recipient = users[(idx + 1) % len(users)]
        request_uuid = prefix + f"direct-{idx:08d}"
        amount = 1 + (idx % 5)
        actor = {
            "id": sender["id"],
            "username": sender["username"],
            "role": sender.get("role") or "user",
            "member_level": "trusted",
            "effective_level": "trusted",
        }
        one_started = time.perf_counter()
        try:
            result = service.submit_wallet_transaction(
                actor=actor,
                source_wallet_address=sender["address"],
                destination_wallet_address=recipient["address"],
                amount_points=amount,
                fee_points=0,
                request_uuid=request_uuid,
                memo="direct throughput probe pc0 transfer",
            )
            return {
                "ok": True,
                "status": 200,
                "elapsed_ms": round((time.perf_counter() - one_started) * 1000, 3),
                "request_uuid": request_uuid,
                "tx_group_hash": result.get("tx_group_hash"),
            }
        except Exception as exc:
            return {
                "ok": False,
                "status": 0,
                "elapsed_ms": round((time.perf_counter() - one_started) * 1000, 3),
                "request_uuid": request_uuid,
                "error": f"{exc.__class__.__name__}: {str(exc)[:240]}",
            }

    max_workers = max(1, int(concurrency))
    max_inflight = max_workers * 4
    next_idx = 0
    futures = set()
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        while next_idx < ops and len(futures) < max_inflight:
            futures.add(pool.submit(submit, next_idx))
            next_idx += 1
        while futures:
            done, futures = wait(futures, return_when=FIRST_COMPLETED)
            for future in done:
                result = future.result()
                completed += 1
                elapsed_ms = float(result.get("elapsed_ms") or 0)
                if elapsed_ms > 0:
                    latency_values.append(elapsed_ms)
                status_counts[str(result.get("status", 0))] += 1
                if not result.get("ok"):
                    errors += 1
                    if len(error_samples) < 100:
                        error_samples.append(result)
                if completed % 10000 == 0 or completed == ops:
                    elapsed = max(0.001, time.perf_counter() - started)
                    marker = {
                        "completed": completed,
                        "requested": ops,
                        "errors": errors,
                        "elapsed_seconds": round(elapsed, 3),
                        "throughput_tps": round(completed / elapsed, 3),
                    }
                    progress.append(marker)
                    print(
                        f"[direct-throughput] completed {completed}/{ops} "
                        f"errors={errors} tps={marker['throughput_tps']}",
                        flush=True,
                    )
            while next_idx < ops and len(futures) < max_inflight:
                futures.add(pool.submit(submit, next_idx))
                next_idx += 1
    elapsed = max(0.001, time.perf_counter() - started)
    return {
        "completed": completed,
        "errors": errors,
        "elapsed_seconds": round(elapsed, 3),
        "throughput_tps": round(completed / elapsed, 3),
        "latency": latency_summary(latency_values),
        "status_counts": dict(status_counts),
        "error_samples": error_samples,
        "progress": progress,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="High-volume direct pc0 ledger throughput probe with resource monitoring.")
    parser.add_argument("--runtime-root", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--ops", type=int, default=100000)
    parser.add_argument("--accounts", type=int, default=64)
    parser.add_argument("--username-like", default="dstress_%")
    parser.add_argument("--grant-points", type=int, default=50000)
    parser.add_argument("--concurrency", type=int, default=64)
    parser.add_argument("--mode", default="dev_ready")
    parser.add_argument("--server-pids", default="")
    parser.add_argument("--resource-interval", type=float, default=1.0)
    args = parser.parse_args()

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    service = service_for_runtime(args.runtime_root, mode=args.mode)
    database = db_path(args.runtime_root)
    prefix = "dthrough-" + datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S") + "-"

    pids = parse_pids(args.server_pids)
    monitor = None
    if pids:
        database_dir = database.parent
        monitor = ResourceMonitor(
            runtime_root=Path(args.runtime_root),
            paths={
                "main": database_dir / "database.db",
                "auth": database_dir / "auth.db",
                "audit": database_dir / "audit.db",
                "control": database_dir / "control.db",
            },
            interval=max(0.2, float(args.resource_interval or 1.0)),
            pids=pids,
        )
        monitor.start()

    started = time.perf_counter()
    root_actor = root_actor_for_service(service)
    users = load_hot_wallet_users(service, username_like=args.username_like, limit=int(args.accounts))
    findings: list[dict[str, Any]] = []
    if len(users) < max(2, int(args.accounts)):
        findings.append({
            "severity": "high",
            "title": "not enough reusable official hot wallet users for requested throughput probe",
            "requested": int(args.accounts),
            "loaded": len(users),
            "username_like": args.username_like,
        })
    if len(users) < 2:
        payload = {"ok": False, "prefix": prefix, "findings": findings}
        out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
        return 1

    funding_needed = len(users) * int(args.grant_points) + int(args.ops) * 5 + 1000
    fixture_mint = ensure_fixture_treasury_funding(
        service,
        root_actor=root_actor,
        needed_amount=funding_needed,
        request_uuid=prefix + "fixture-mint",
    )
    grant_errors = []
    if int(args.grant_points) > 0:
        for item in users:
            try:
                fixture_official_grant(
                    service,
                    root_actor=root_actor,
                    destination=item["address"],
                    amount=int(args.grant_points),
                    request_uuid=prefix + "grant-" + item["username"],
                )
            except Exception as exc:
                grant_errors.append({"username": item["username"], "error": f"{exc.__class__.__name__}: {str(exc)[:240]}"})
                if len(grant_errors) >= 20:
                    break
    if grant_errors:
        findings.append({"severity": "critical", "title": "fixture grant failed before direct throughput probe", "samples": grant_errors})

    direct = run_direct_transfers(
        service,
        users=users,
        prefix=prefix,
        ops=max(0, int(args.ops)),
        concurrency=max(1, int(args.concurrency)),
    )
    if direct["errors"]:
        findings.append({"severity": "critical", "title": "direct pc0 transfer errors during throughput probe", "count": direct["errors"], "samples": direct["error_samples"][:10]})

    verify = service.verify_chain()
    if not bool(verify.get("ok")):
        findings.append({"severity": "critical", "title": "PointsChain verify failed after direct throughput probe", "verification": verify})
    counts = db_counts(database, prefix)
    resource_summary = monitor.stop() if monitor else {}
    payload = {
        "ok": not findings,
        "prefix": prefix,
        "runtime_root": args.runtime_root,
        "database": str(database),
        "accounts_requested": int(args.accounts),
        "accounts_loaded": len(users),
        "username_like": args.username_like,
        "grant_points": int(args.grant_points),
        "fixture_mint": fixture_mint,
        "direct": direct,
        "db_counts": counts,
        "verify": verify,
        "resource_monitor": resource_summary,
        "elapsed_seconds": round(time.perf_counter() - started, 3),
        "findings": findings,
    }
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if payload["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
